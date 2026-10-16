"""Synthetic, offline fixtures. No fixture is an actual match result."""

import base64
import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests

import update_result


class OfflineResultTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("No network requests in tests"),
        ))
        self.output = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.output))

    def mock(self, name, **kwargs):
        return self.stack.enter_context(patch.object(update_result, name, **kwargs))


class ResultParsingTests(OfflineResultTestCase):
    def parse(self, text):
        with patch.object(update_result, "get_with_retry", return_value=SimpleNamespace(text=text)):
            return update_result.parse_result_article("https://example.test/result")

    def test_explicit_team_left_score(self):
        self.assertEqual(self.parse('<article><h1>第12節 試合結果</h1><p>エスポラーダ北海道 3-2 テストチーム</p></article>'), {
            "node": 12, "result": "○ 3-2",
        })

    def test_article_header_keeps_its_round_number(self):
        self.assertEqual(self.parse('<article><header><h1>第12節 試合結果</h1></header><p>エスポラーダ北海道 3-2 テストチーム</p></article>'), {
            "node": 12, "result": "○ 3-2",
        })

    def test_explicit_team_right_score_is_reoriented(self):
        self.assertEqual(self.parse('<main><h1>第12節 試合結果</h1><p>テストチーム 4－1 エスポラーダ北海道</p></main>'), {
            "node": 12, "result": "● 1-4",
        })

    def test_labeled_draw(self):
        self.assertEqual(self.parse('<h1>第1節 試合結果</h1><p>エスポラーダ北海道 △ 2–2 テストチーム</p>'), {
            "node": 1, "result": "△ 2-2",
        })

    def test_unlabeled_score_is_unresolved(self):
        self.assertIsNone(self.parse('<h1>第12節 試合結果</h1><p>最終スコア 3-2</p>'))

    def test_season_year_is_not_a_score(self):
        self.assertIsNone(self.parse('<h1>2026-27シーズン 第12節 試合結果</h1><p>結果は後ほど掲載します。</p>'))

    def test_team_name_far_from_score_does_not_establish_orientation(self):
        self.assertIsNone(self.parse('<h1>第12節 試合結果</h1><p>3-2でした。次回はエスポラーダ北海道を応援しよう。</p>'))

    def test_conflicting_labeled_scores_are_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><p>エスポラーダ北海道 3-2 テストチーム</p><p>エスポラーダ北海道 4-2 テストチーム</p></article>'))

    def test_conflicting_round_numbers_are_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><p>第13節 エスポラーダ北海道 3-2 テストチーム</p></article>'))

    def test_repeated_same_result_is_consistent(self):
        self.assertEqual(self.parse('<article><h1>第12節 試合結果</h1><p>エスポラーダ北海道 3-2 テストチーム</p><p>第12節 エスポラーダ北海道 3-2 テストチーム</p></article>'), {
            "node": 12, "result": "○ 3-2",
        })

    def test_navigation_does_not_supply_result_or_round(self):
        self.assertEqual(self.parse('<nav>第1節 エスポラーダ北海道 1-0 テストチーム</nav><article><h1>第12節 試合結果</h1><p>エスポラーダ北海道 3-2 テストチーム</p></article>'), {
            "node": 12, "result": "○ 3-2",
        })

    def test_navigation_only_score_is_unresolved(self):
        self.assertIsNone(self.parse('<nav>第1節 エスポラーダ北海道 1-0 テストチーム</nav><article><h1>第12節 試合結果</h1><p>結果は後ほど掲載します。</p></article>'))

    def test_half_time_only_score_is_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><p>前半 エスポラーダ北海道 1-0 テストチーム</p></article>'))

    def test_half_time_label_in_ancestor_is_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><div>前半<p>エスポラーダ北海道 1-0 テストチーム</p></div><p>試合終了後に結果を更新します。</p></article>'))

    def test_half_time_label_in_heading_is_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><h2>前半</h2><p>エスポラーダ北海道 1-0 テストチーム</p></article>'))

    def test_conflicting_score_in_heading_is_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><h2>エスポラーダ北海道 2-4 テストチーム</h2><p>エスポラーダ北海道 1-0 テストチーム</p></article>'))

    def test_conflicting_score_in_parent_text_is_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 試合結果</h1><div>エスポラーダ北海道 2-4 テストチーム<p>エスポラーダ北海道 1-0 テストチーム</p></div></article>'))

    def test_contradictory_attached_outcome_marker_is_unresolved(self):
        for result in ['エスポラーダ北海道 ● 3-2 テストチーム',
                       'エスポラーダ北海道 3-2 △ テストチーム',
                       'テストチーム 4-1 ○ エスポラーダ北海道',
                       'テストチーム 4-1 エスポラーダ北海道 ○']:
            with self.subTest(result=result):
                self.assertIsNone(self.parse(f'<article><h1>第12節 試合結果</h1><p>{result}</p></article>'))

    def test_team_and_score_in_different_blocks_are_unresolved(self):
        self.assertIsNone(self.parse('<article><h1>第12節 エスポラーダ北海道</h1><p>3-2 テストチーム</p></article>'))

    def test_fetch_failure_is_unresolved(self):
        self.mock("get_with_retry", side_effect=requests.Timeout("fixture timeout"))
        self.assertIsNone(update_result.parse_result_article("https://example.test/result"))


class ResultLedgerTests(OfflineResultTestCase):
    def setUp(self):
        super().setUp()
        os.environ["CHANTS_PAT"] = "test-token"
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.ledger = Path(directory) / "posted_results.json"
        self.mock("POSTED_RESULT_FILE", new=str(self.ledger))
        self.articles = [{"title": "第12節 テスト試合結果", "url": "https://example.test/result"}]
        self.mock("fetch_match_result_articles", return_value=self.articles)
        self.parse = self.mock("parse_result_article", return_value={"node": 12, "result": "○ 3-2"})
        self.update = self.mock("update_schedule_json", return_value=True)

    def test_unresolved_article_is_not_marked_processed(self):
        self.parse.return_value = None
        update_result.main()
        self.update.assert_not_called()
        self.assertFalse(self.ledger.exists())

    def test_failed_update_is_not_marked_processed(self):
        self.update.return_value = False
        update_result.main()
        self.assertFalse(self.ledger.exists())

    def test_update_exception_keeps_article_pending(self):
        self.update.side_effect = requests.Timeout("fixture timeout")
        update_result.main()
        self.assertFalse(self.ledger.exists())

    def test_success_is_saved_and_not_reprocessed(self):
        update_result.main()
        update_result.main()
        self.update.assert_called_once()
        self.assertEqual(update_result.load_posted_results(), {self.articles[0]["url"]})

    def test_failed_article_is_retried(self):
        self.update.side_effect = [False, True]
        update_result.main()
        update_result.main()
        self.assertEqual(self.update.call_count, 2)
        self.assertEqual(update_result.load_posted_results(), {self.articles[0]["url"]})

    def test_failed_article_does_not_block_later_result(self):
        second = {"title": "第13節 テスト試合結果", "url": "https://example.test/result-2"}
        self.articles.append(second)
        self.update.side_effect = [requests.Timeout("fixture timeout"), True]
        update_result.main()
        self.assertEqual(update_result.load_posted_results(), {second["url"]})


class ScheduleUpdateTests(OfflineResultTestCase):
    def response(self, result=None):
        document = {"updated": "2026-10-15", "matches": [{"node": 12, "result": result}]}
        encoded = base64.b64encode(json.dumps(document).encode()).decode()
        return Mock(status_code=200, json=Mock(return_value={"sha": "fixture-sha", "content": encoded}))

    def test_already_matching_result_is_idempotent_success(self):
        with patch.object(update_result.requests, "get", return_value=self.response("○ 3-2")):
            with patch.object(update_result.requests, "put") as put:
                self.assertTrue(update_result.update_schedule_json(12, "○ 3-2", "test-token"))
                put.assert_not_called()

    def test_conflicting_existing_result_is_preserved(self):
        with patch.object(update_result.requests, "get", return_value=self.response("● 1-4")):
            with patch.object(update_result.requests, "put") as put:
                self.assertFalse(update_result.update_schedule_json(12, "○ 3-2", "test-token"))
                put.assert_not_called()

    def test_unknown_round_is_not_written(self):
        with patch.object(update_result.requests, "get", return_value=self.response()):
            with patch.object(update_result.requests, "put") as put:
                self.assertFalse(update_result.update_schedule_json(99, "○ 3-2", "test-token"))
                put.assert_not_called()

    def test_successful_update_uses_current_sha(self):
        with patch.object(update_result.requests, "get", return_value=self.response()):
            with patch.object(update_result.requests, "put", return_value=Mock(status_code=200)) as put:
                self.assertTrue(update_result.update_schedule_json(12, "○ 3-2", "test-token"))
                payload = put.call_args.kwargs["json"]
                self.assertEqual(payload["sha"], "fixture-sha")
                content = json.loads(base64.b64decode(payload["content"]))
                self.assertEqual(content["matches"][0]["result"], "○ 3-2")

    def test_conflict_response_is_failure(self):
        with patch.object(update_result.requests, "get", return_value=self.response()):
            with patch.object(update_result.requests, "put", return_value=Mock(status_code=409, text="fixture conflict")):
                self.assertFalse(update_result.update_schedule_json(12, "○ 3-2", "test-token"))


if __name__ == "__main__":
    unittest.main()
