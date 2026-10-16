"""Offline regressions for delivery receipts and news de-duplication."""

import io
import json
import os
import tempfile
import unittest
import xml.etree.ElementTree as ET
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import requests

import generate_rss
import news_search


def official_article(number):
    return {
        "title": f"エスポラーダのお知らせ {number}",
        "url": f"https://espolada.com/news/{number}/",
        "date": "2026-10-16",
        "category": "お知らせ",
    }


def search_article(number, title=None, source="北海道新聞"):
    return {
        "title": title or f"エスポラーダ北海道 ニュース {number} - {source}",
        "link": f"https://news.google.com/rss/articles/{number}",
        "pub_date": "Fri, 16 Oct 2026 00:00:00 GMT",
        "source": source,
    }


class OfflineTestCase(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {}, clear=True))
        self.stack.enter_context(patch(
            "requests.sessions.Session.request",
            side_effect=AssertionError("Tests must never make network requests"),
        ))
        self.output = io.StringIO()
        self.stack.enter_context(redirect_stdout(self.output))
        temp = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.directory = Path(temp)

    def mock(self, module, name, **kwargs):
        return self.stack.enter_context(patch.object(module, name, **kwargs))

    def credentials(self):
        os.environ.update(BUFFER_API_KEY="test-key", BUFFER_ORG_ID="test-org")


class OfficialNewsDeliveryTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.ledger = self.directory / "posted.json"
        self.feed = self.directory / "feed.xml"
        self.mock(generate_rss, "POSTED_FILE", new=str(self.ledger))
        self.mock(generate_rss, "OUTPUT_FILE", new=str(self.feed))
        self.fetch = self.mock(generate_rss, "fetch_news_list", return_value=[official_article(1)])
        self.channel = self.mock(generate_rss, "get_buffer_channel_id", return_value="x-channel")
        self.buffer = self.mock(generate_rss, "post_to_buffer", return_value=False)
        self.x = self.mock(generate_rss, "post_to_x", return_value=False)

    def test_no_credentials_does_not_mark_article_posted(self):
        generate_rss.main()
        self.assertFalse(self.ledger.exists())
        self.buffer.assert_not_called()
        self.assertEqual(len(ET.parse(self.feed).findall("./channel/item")), 1)

    def test_both_posting_methods_fail_keep_existing_ledger_unchanged(self):
        self.credentials()
        generate_rss.save_posted({"https://espolada.com/news/already-posted/"})
        before = self.ledger.read_bytes()
        generate_rss.main()
        self.assertEqual(self.ledger.read_bytes(), before)

    def test_buffer_success_is_saved_without_direct_x_fallback(self):
        self.credentials()
        self.buffer.return_value = True
        generate_rss.main()
        self.assertEqual(generate_rss.load_posted(), {official_article(1)["url"]})
        self.x.assert_not_called()

    def test_direct_x_fallback_success_is_saved(self):
        self.credentials()
        self.x.return_value = True
        generate_rss.main()
        self.assertEqual(generate_rss.load_posted(), {official_article(1)["url"]})

    def test_channel_lookup_failure_can_use_direct_x_fallback(self):
        self.credentials()
        self.channel.side_effect = requests.Timeout("fixture timeout")
        self.x.return_value = True
        generate_rss.main()
        self.assertEqual(generate_rss.load_posted(), {official_article(1)["url"]})
        self.buffer.assert_not_called()

    def test_failed_article_is_retried_and_success_is_not_reposted(self):
        self.credentials()
        generate_rss.main()
        self.buffer.return_value = True
        generate_rss.main()
        generate_rss.main()
        self.assertEqual(self.buffer.call_count, 2)
        self.assertEqual(generate_rss.load_posted(), {official_article(1)["url"]})

    def test_three_success_limit_keeps_failed_and_remaining_articles_pending(self):
        self.credentials()
        self.fetch.return_value = [official_article(i) for i in [5, 4, 3, 2, 1]]
        self.buffer.side_effect = [True, False, True, True]
        generate_rss.main()
        self.assertEqual(self.buffer.call_count, 4)
        self.assertEqual(generate_rss.load_posted(), {
            official_article(i)["url"] for i in [1, 3, 4]
        })

    def test_permanent_failures_do_not_starve_later_articles(self):
        self.credentials()
        self.fetch.return_value = [official_article(i) for i in [4, 3, 2, 1]]
        attempted = []

        def respond(api_key, channel_id, text):
            attempted.append(text)
            return official_article(4)["url"] in text

        self.buffer.side_effect = respond
        for _ in range(3):
            generate_rss.main()
        self.assertEqual(generate_rss.load_posted(), {official_article(4)["url"]})
        self.assertEqual(sum(official_article(4)["url"] in text for text in attempted), 1)
        self.assertEqual(len(attempted), 10)


class SearchNewsDeliveryTests(OfflineTestCase):
    def setUp(self):
        super().setUp()
        self.credentials()
        self.ledger = self.directory / "posted_news.json"
        self.mock(news_search, "POSTED_NEWS_FILE", new=self.ledger)
        self.mock(news_search, "SEARCH_KEYWORDS", new=["エスポラーダ北海道"])
        self.fetch = self.mock(news_search, "fetch_google_news", return_value=[search_article(1)])
        self.channel = self.mock(news_search, "get_buffer_channel_id", return_value="x-channel")
        self.buffer = self.mock(news_search, "post_to_buffer", return_value=False)

    def test_failed_post_remains_pending(self):
        news_search.main()
        self.assertEqual(news_search.load_posted_news(), set())
        self.assertIn("投稿完了: 0件", self.output.getvalue())

    def test_success_is_saved_and_not_reposted(self):
        self.buffer.return_value = True
        news_search.main()
        news_search.main()
        self.buffer.assert_called_once()
        self.assertEqual(news_search.load_posted_news(), {search_article(1)["link"]})

    def test_successful_post_is_checkpointed_before_next_attempt(self):
        self.fetch.return_value = [search_article(1), search_article(2)]

        def respond(*args):
            if self.buffer.call_count == 1:
                return True
            self.assertEqual(news_search.load_posted_news(), {search_article(1)["link"]})
            return False

        self.buffer.side_effect = respond
        news_search.main()
        self.assertEqual(news_search.load_posted_news(), {search_article(1)["link"]})
        self.assertIn("投稿完了: 1件", self.output.getvalue())

    def test_failed_story_does_not_acknowledge_duplicate_urls(self):
        self.fetch.return_value = [
            search_article(1, "エスポラーダ北海道の選手インタビュー - 北海道新聞"),
            search_article(2, "エスポラーダ北海道の選手インタビュー - 共同通信", "共同通信"),
        ]
        news_search.main()
        self.buffer.assert_called_once()
        self.assertEqual(news_search.load_posted_news(), set())

    def test_successful_story_acknowledges_duplicate_urls(self):
        self.buffer.return_value = True
        self.fetch.return_value = [
            search_article(1, "エスポラーダ北海道の選手インタビュー - 北海道新聞"),
            search_article(2, "エスポラーダ北海道の選手インタビュー - 共同通信", "共同通信"),
        ]
        news_search.main()
        self.buffer.assert_called_once()
        self.assertEqual(news_search.load_posted_news(), {
            search_article(1)["link"], search_article(2)["link"],
        })

    def test_long_common_prefix_does_not_hide_different_stories(self):
        prefix = "エスポラーダ北海道 メットライフ生命Ｆリーグ2026-27 "
        self.fetch.return_value = [
            search_article(1, prefix + "試合結果 - 北海道新聞"),
            search_article(2, prefix + "チケット発売 - 北海道新聞"),
        ]
        self.buffer.return_value = True
        news_search.main()
        self.assertEqual(self.buffer.call_count, 2)

    def test_deferred_story_and_its_duplicates_remain_pending(self):
        self.buffer.return_value = True
        self.fetch.return_value = [search_article(i) for i in range(1, 5)] + [
            search_article(5, search_article(4)["title"]),
        ]
        news_search.main()
        self.assertEqual(self.buffer.call_count, 3)
        self.assertEqual(news_search.load_posted_news(), {
            search_article(i)["link"] for i in range(1, 4)
        })

    def test_already_posted_story_suppresses_same_title_from_other_source(self):
        news_search.save_posted_news({search_article(1)["link"]})
        self.fetch.return_value = [
            search_article(2, "エスポラーダ北海道の選手インタビュー - 共同通信", "共同通信"),
            search_article(1, "エスポラーダ北海道の選手インタビュー - 北海道新聞"),
        ]
        news_search.main()
        self.buffer.assert_not_called()
        self.assertEqual(news_search.load_posted_news(), {
            search_article(1)["link"], search_article(2)["link"],
        })

    def test_channel_lookup_failure_keeps_all_stories_pending(self):
        self.channel.side_effect = requests.Timeout("fixture timeout")
        news_search.main()
        self.assertEqual(news_search.load_posted_news(), set())
        self.buffer.assert_not_called()

    def test_permanent_failures_do_not_starve_later_stories(self):
        self.fetch.return_value = [search_article(i) for i in range(1, 5)]
        attempted = []

        def respond(api_key, channel_id, text):
            attempted.append(text)
            return search_article(4)["link"] in text

        self.buffer.side_effect = respond
        for _ in range(3):
            news_search.main()
        self.assertEqual(news_search.load_posted_news(), {search_article(4)["link"]})
        self.assertEqual(sum(search_article(4)["link"] in text for text in attempted), 1)
        self.assertEqual(len(attempted), 10)

    def test_three_success_limit_skips_failures_and_leaves_later_stories_pending(self):
        self.fetch.return_value = [search_article(i) for i in range(1, 6)]
        self.buffer.side_effect = [True, False, True, True]
        news_search.main()
        self.assertEqual(self.buffer.call_count, 4)
        self.assertEqual(news_search.load_posted_news(), {
            search_article(i)["link"] for i in [1, 3, 4]
        })

    def test_repeated_url_across_searches_is_only_sent_once(self):
        self.buffer.return_value = True
        self.fetch.return_value = [search_article(1), search_article(1)]
        news_search.main()
        self.buffer.assert_called_once()


class BufferResponseTests(OfflineTestCase):
    def test_missing_receipt_is_not_success(self):
        responses = [
            {}, {"data": None}, {"data": {}},
            {"data": {"createPost": None}},
            {"data": {"createPost": {}}},
            {"data": {"createPost": {"post": None}}},
            {"data": {"createPost": {"post": {}}}},
            {"data": {"createPost": {"post": {"id": ""}}}},
            {"data": {"createPost": {"message": "rate limit"}}},
            {"errors": [{"message": "fixture error"}]},
        ]
        for module in [generate_rss, news_search]:
            for response in responses:
                with self.subTest(module=module.__name__, response=response):
                    with patch.object(module, "buffer_graphql", return_value=response):
                        self.assertFalse(module.post_to_buffer("key", "channel", "test"))

    def test_receipt_id_is_success(self):
        for module in [generate_rss, news_search]:
            with self.subTest(module=module.__name__):
                with patch.object(module, "buffer_graphql", return_value={
                    "data": {"createPost": {"post": {"id": "post-123"}}},
                }):
                    self.assertTrue(module.post_to_buffer("key", "channel", "test"))

    def test_transport_failure_is_not_success(self):
        for module in [generate_rss, news_search]:
            with self.subTest(module=module.__name__):
                with patch.object(module, "buffer_graphql", side_effect=requests.Timeout):
                    self.assertFalse(module.post_to_buffer("key", "channel", "test"))

    def test_channel_selection_never_falls_back_to_another_social_network(self):
        for module in [generate_rss, news_search]:
            with self.subTest(module=module.__name__):
                with patch.object(module, "buffer_graphql", return_value={
                    "data": {"channels": [{"id": "instagram", "service": "instagram", "name": "Test"}]},
                }):
                    self.assertEqual(module.get_buffer_channel_id("key", "org"), "")

    def test_x_channel_is_selected(self):
        for module in [generate_rss, news_search]:
            for service in ["twitter", "x"]:
                with self.subTest(module=module.__name__, service=service):
                    with patch.object(module, "buffer_graphql", return_value={
                        "data": {"channels": [{"id": "x-channel", "service": service, "name": "Test"}]},
                    }):
                        self.assertEqual(module.get_buffer_channel_id("key", "org"), "x-channel")

    def test_null_channel_response_is_safe(self):
        for module in [generate_rss, news_search]:
            for response in [{"data": None}, {"data": {"channels": None}}]:
                with self.subTest(module=module.__name__, response=response):
                    with patch.object(module, "buffer_graphql", return_value=response):
                        self.assertEqual(module.get_buffer_channel_id("key", "org"), "")


class SearchTitleTests(OfflineTestCase):
    def test_only_matching_source_suffix_is_removed(self):
        article = search_article(1, "エスポラーダ北海道 3-2 で勝利 - 北海道新聞")
        self.assertIn("エスポラーダ北海道 3-2 で勝利\n", news_search.compose_news_post(article))

    def test_hyphenated_title_without_source_suffix_is_preserved(self):
        article = search_article(1, "エスポラーダ北海道 3-2", source="")
        self.assertIn("エスポラーダ北海道 3-2\n", news_search.compose_news_post(article))


if __name__ == "__main__":
    unittest.main()
