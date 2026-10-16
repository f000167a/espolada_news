#!/usr/bin/env python3
"""
エスポラーダ北海道 試合結果自動反映スクリプト

espolada.comの「試合」カテゴリ新着記事を検出し、
スコアを抽出してespolada_chantsのschedule.jsonを更新する。

GitHub Secrets:
  CHANTS_PAT: espolada_chantsリポジトリへのwrite権限付きPAT
"""

import json
import os
import re
import base64
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from http_util import get_with_retry

# ── 設定 ──────────────────────────────────────────────
NEWS_URL    = "https://espolada.com/news/"
BASE_URL    = "https://espolada.com"
USER_AGENT  = "EspoladaRSSBot/1.0"

CHANTS_REPO  = "f000167a/espolada_chants"
SCHEDULE_PATH = "schedule.json"
GITHUB_API   = "https://api.github.com"

POSTED_RESULT_FILE = "posted_results.json"
JST = timezone(timedelta(hours=9))


# ── posted_results管理 ────────────────────────────────
def load_posted_results() -> set:
    if Path(POSTED_RESULT_FILE).exists():
        data = json.loads(Path(POSTED_RESULT_FILE).read_text(encoding="utf-8"))
        return set(data.get("posted_urls", []))
    return set()


def save_posted_results(posted: set):
    data = {
        "posted_urls": sorted(posted),
        "updated_at": datetime.now(JST).isoformat()
    }
    Path(POSTED_RESULT_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ── 記事一覧から試合結果記事を抽出 ───────────────────
def fetch_match_result_articles() -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    resp = get_with_retry(NEWS_URL, headers=headers, timeout=30)
    soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    seen = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/news/" not in href:
            continue
        if href.startswith("/"):
            href = BASE_URL + href
        clean_url = href.rstrip("/")
        if clean_url in seen:
            continue
        seen.add(clean_url)

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        # カテゴリと日付をパース
        m = re.match(
            r"^(お知らせ|試合|レディース|サテライト|スクール|アカデミー)?"
            r"(\d{4}\.\d{1,2}\.\d{1,2})?"
            r"(.+)$",
            title,
        )
        if not m:
            continue

        category   = m.group(1) or ""
        clean_title = m.group(3).strip()

        # 「試合」カテゴリ かつ 「試合結果」を含む記事のみ対象
        # Fリーグ本戦のみ（サテライト・レディースは除外）
        if category != "試合":
            continue
        if "試合結果" not in clean_title:
            continue
        if "サテライト" in clean_title or "イルネーヴェ" in clean_title:
            continue

        results.append({
            "title": clean_title,
            "url":   href,
        })

    print(f"試合結果記事候補: {len(results)}件")
    return results


# ── 記事本文からスコアと節番号を抽出 ─────────────────
def parse_result_article(url: str) -> dict | None:
    """
    記事本文を取得してスコアと節番号を抽出する。
    返り値: {"node": int, "result": "○ 3-2" など}。
    節番号・スコアの向きが一意に確認できない場合は None（未解決）。
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = get_with_retry(url, headers=headers, timeout=30)
    except Exception as e:
        print(f"  記事取得失敗: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    # 関連記事・ナビゲーションの節番号やスコアを混ぜない。
    content = soup.find("article") or soup.find("main") or soup.body or soup
    for element in content.find_all(["nav", "footer", "aside", "script", "style"]):
        element.decompose()
    text = content.get_text(" ", strip=True)

    nodes = {int(value) for value in re.findall(r"第\s*(\d+)\s*節", text)}
    if len(nodes) != 1 or 0 in nodes:
        print(f"  節番号を一意に確認できませんでした（未解決）: {url}")
        return None
    node = nodes.pop()

    # 前半・後半のラベルが祖先要素や見出しにある場合もある。
    # セクションと最終結果の関連を証明できないため、半分のスコアを
    # 含む記事は保守的に未解決とする。
    if re.search(r"前半|後半|ハーフタイム", text):
        print(f"  前後半のスコアと最終結果の区別が必要です（未解決）: {url}")
        return None

    # チーム名に隣接するスコアのみを候補にする。年号やページ中で
    # 最初に見つかった X-Y からスコア・ホーム/アウェーを推定しない。
    left_pattern = re.compile(
        r"エスポラーダ北海道\s*(?P<before>[○〇●△])?\s*"
        r"(?P<a>\d{1,2})\s*[-－–]\s*(?P<b>\d{1,2})(?!\d)"
        r"\s*(?P<after>[○〇●△])?"
    )
    right_pattern = re.compile(
        r"(?<!\d)(?P<a>\d{1,2})\s*[-－–]\s*(?P<b>\d{1,2})"
        r"\s*(?P<before>[○〇●△])?\s*エスポラーダ北海道\s*(?P<after>[○〇●△])?"
    )

    def labeled_scores(value):
        scores = set()
        for pattern, reverse in [(left_pattern, False), (right_pattern, True)]:
            for match in pattern.finditer(value):
                a, b = int(match.group("a")), int(match.group("b"))
                own, opponent = (b, a) if reverse else (a, b)
                expected = "○〇" if own > opponent else "●" if own < opponent else "△"
                for marker in [match.group("before"), match.group("after")]:
                    if marker and marker not in expected:
                        return None
                scores.add((own, opponent))
        return scores

    # 見出しや親要素の直接テキストを含め、全候補の矛盾を確認する。
    scores = labeled_scores(text)
    if scores is None or len(scores) != 1:
        print(f"  チーム名付きの最終スコアを一意に確認できませんでした（未解決）: {url}")
        return None

    # 見出しのチーム名と別段落の数字が偶然つながっただけでは受理しない。
    block_tags = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr", "div"]
    blocks = [element for element in content.find_all(block_tags)
              if not element.find(block_tags)] or [content]
    local_scores = set()
    for block in blocks:
        candidate = labeled_scores(block.get_text(" ", strip=True))
        if candidate is None:
            print(f"  勝敗記号とスコアが一致しませんでした（未解決）: {url}")
            return None
        local_scores.update(candidate)
    if local_scores != scores:
        print(f"  同じ本文ブロック内でチームとスコアを確認できませんでした（未解決）: {url}")
        return None
    espo_score, opp_score = scores.pop()

    # 勝敗判定
    if espo_score > opp_score:
        win_loss = "○"
    elif espo_score < opp_score:
        win_loss = "●"
    else:
        win_loss = "△"

    result_str = f"{win_loss} {espo_score}-{opp_score}"
    print(f"  第{node}節 結果: {result_str}")

    return {
        "node":      node,
        "result":    result_str,
    }


# ── GitHub APIでschedule.jsonを更新 ──────────────────
def update_schedule_json(node: int, result: str, pat: str) -> bool:
    headers = {
        "Authorization": f"token {pat}",
        "Accept":        "application/vnd.github.v3+json",
        "User-Agent":    USER_AGENT,
    }

    # 現在のファイルを取得
    url = f"{GITHUB_API}/repos/{CHANTS_REPO}/contents/{SCHEDULE_PATH}"
    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"  schedule.json取得失敗: {resp.status_code} {resp.text}")
        return False

    file_data = resp.json()
    sha      = file_data["sha"]
    content  = json.loads(base64.b64decode(file_data["content"]).decode("utf-8"))

    # 該当節を更新
    updated = False
    for match in content["matches"]:
        if match["node"] != node:
            continue
        if match["result"] == result:
            # 前回GitHub更新だけが成功し、履歴保存前に止まった場合の再実行。
            print(f"  schedule.json 第{node}節は同じ結果で反映済み: {result}")
            return True
        if match["result"] is None:
            match["result"] = result
            updated = True
            print(f"  schedule.json 第{node}節を更新: {result}")
        break

    if not updated:
        print(f"  第{node}節が見つからないか既に結果あり。スキップ。")
        return False

    # 更新日時を記録
    content["updated"] = datetime.now(JST).strftime("%Y-%m-%d")

    # コミット
    new_content = base64.b64encode(
        json.dumps(content, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")

    commit_url  = f"{GITHUB_API}/repos/{CHANTS_REPO}/contents/{SCHEDULE_PATH}"
    commit_body = {
        "message": f"chore: 第{node}節試合結果を反映 ({result}) [skip ci]",
        "content": new_content,
        "sha":     sha,
        "branch":  "main",
    }

    resp2 = requests.put(commit_url, headers=headers, json=commit_body, timeout=30)
    if resp2.status_code in (200, 201):
        print(f"  GitHub commit成功")
        return True
    else:
        print(f"  GitHub commit失敗: {resp2.status_code} {resp2.text}")
        return False


# ── メイン ────────────────────────────────────────────
def main():
    pat = os.getenv("CHANTS_PAT")
    if not pat:
        print("CHANTS_PAT が設定されていません。スキップ。")
        return

    posted = load_posted_results()
    try:
        articles = fetch_match_result_articles()
    except requests.RequestException as e:
        # 一時的な接続障害。次回実行で再試行されるため異常終了しない。
        print(f"記事一覧の取得に失敗しました。今回はスキップします: {e}")
        return

    new_articles = [a for a in articles if a["url"] not in posted]
    if not new_articles:
        print("新着の試合結果記事なし。")
        return

    print(f"未処理の試合結果記事: {len(new_articles)}件")

    for article in new_articles:
        print(f"\n処理中: {article['title']}")
        parsed = parse_result_article(article["url"])

        if not parsed:
            print("  ✗ 未解決。処理済みにせず、次回実行に残します。")
            continue

        try:
            success = update_schedule_json(
                node=parsed["node"],
                result=parsed["result"],
                pat=pat,
            )
        except (requests.RequestException, ValueError, KeyError) as e:
            print(f"  ✗ 反映失敗: {e}")
            continue
        if not success:
            print("  ✗ 反映失敗。処理済みにせず、次回実行に残します。")
            continue

        print("  ✓ 反映完了")
        # 反映成功（同じ結果の反映済みも含む）だけを処理済みとして記録。
        posted.add(article["url"])
        save_posted_results(posted)


if __name__ == "__main__":
    main()
