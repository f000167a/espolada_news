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
    resp = requests.get(NEWS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
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
    返り値: {"node": int, "score_espo": int, "score_opp": int, "win_loss": "○"|"●"|"△"}
    または None（抽出失敗）
    """
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  記事取得失敗: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")
    text = soup.get_text(" ", strip=True)

    # 節番号の抽出
    # 例: 「第1節」「第12節」
    node_match = re.search(r"第\s*(\d+)\s*節", text)
    node = int(node_match.group(1)) if node_match else None

    if node is None:
        print(f"  節番号が見つかりませんでした: {url}")
        return None

    # スコアの抽出
    # エスポラーダのスコアが左か右かを判定して取得
    # パターン1: 「エスポラーダ北海道 X－Y 相手」
    # パターン2: 「相手 X－Y エスポラーダ北海道」
    # パターン3: スコアのみ「X-Y」

    espo_score = None
    opp_score  = None

    # エスポラーダが左に書かれているパターン
    m = re.search(
        r"エスポラーダ北海道\D{0,10}?(\d+)\s*[-－–]\s*(\d+)\D{0,30}?(?:vs|対|　)",
        text
    )
    if m:
        espo_score = int(m.group(1))
        opp_score  = int(m.group(2))

    # エスポラーダが右に書かれているパターン
    if espo_score is None:
        m = re.search(
            r"(\d+)\s*[-－–]\s*(\d+)\D{0,30}?エスポラーダ北海道",
            text
        )
        if m:
            opp_score  = int(m.group(1))
            espo_score = int(m.group(2))

    # スコアのみのパターン（シンプルな「X-Y」を最初の出現から取得）
    if espo_score is None:
        # ページ内の全スコアパターンを取得
        scores = re.findall(r"\b(\d+)\s*[-－–]\s*(\d+)\b", text)
        if scores:
            # 最初に出現するスコアをとりあえず使う（精度が低いのでログ出力）
            a, b = scores[0]
            print(f"  スコア推定（要確認）: {a}-{b}")
            # ホーム/アウェー判定が難しいため、後述のscheduleから判断
            espo_score = int(a)
            opp_score  = int(b)

    if espo_score is None:
        print(f"  スコアが見つかりませんでした: {url}")
        return None

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
        if match["node"] == node and match["result"] is None:
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
    articles = fetch_match_result_articles()

    new_articles = [a for a in articles if a["url"] not in posted]
    if not new_articles:
        print("新着の試合結果記事なし。")
        return

    print(f"未処理の試合結果記事: {len(new_articles)}件")

    for article in new_articles:
        print(f"\n処理中: {article['title']}")
        parsed = parse_result_article(article["url"])

        if parsed:
            success = update_schedule_json(
                node   = parsed["node"],
                result = parsed["result"],
                pat    = pat,
            )
            if success:
                print(f"  ✓ 反映完了")
            else:
                print(f"  ✗ 反映失敗")
        else:
            print(f"  ✗ パース失敗")

        # 処理済みとして記録（成否に関わらず）
        posted.add(article["url"])
        save_posted_results(posted)


if __name__ == "__main__":
    main()
