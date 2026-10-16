#!/usr/bin/env python3
"""
エスポラーダ北海道 ネットニュース収集Bot
Google News RSSからエスポラーダ関連ニュースを検索し、Buffer経由でXに投稿する。
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

import requests

from http_util import get_with_retry

JST = timezone(timedelta(hours=9))
BUFFER_API_URL = "https://api.buffer.com"
POSTED_NEWS_FILE = Path(__file__).parent / "posted_news.json"

SEARCH_KEYWORDS = [
    "エスポラーダ北海道",
    "イルネーヴェ",
]

EXCLUDE_DOMAINS = [
    "espolada.com",
]


def load_posted_news() -> set:
    if POSTED_NEWS_FILE.exists():
        data = json.loads(POSTED_NEWS_FILE.read_text(encoding="utf-8"))
        return set(data.get("posted_urls", []))
    return set()


def save_posted_news(posted: set):
    data = {"posted_urls": sorted(posted), "updated_at": datetime.now(JST).isoformat()}
    POSTED_NEWS_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_google_news(keyword: str) -> list[dict]:
    # when:7d で直近7日間に限定
    url = f"https://news.google.com/rss/search?q={quote(keyword)}+when:7d&hl=ja&gl=JP&ceid=JP:ja"
    try:
        resp = get_with_retry(url, timeout=15)
    except requests.RequestException as e:
        print(f"Google News取得失敗 ({keyword}): {e}")
        return []

    root = ET.fromstring(resp.text)
    articles = []

    now = datetime.now(timezone.utc)
    max_age = timedelta(days=3)  # 3日以内の記事のみ

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")
        source = item.findtext("source", "")

        if not title or not link:
            continue

        # 日付チェック（3日以内のみ）
        if pub_date:
            try:
                from email.utils import parsedate_to_datetime
                article_date = parsedate_to_datetime(pub_date)
                if now - article_date > max_age:
                    continue
            except Exception:
                pass

        # espolada.com自体のニュースは除外
        skip = False
        for domain in EXCLUDE_DOMAINS:
            if domain in link:
                skip = True
                break
        if skip:
            continue
            
        # タイトルに関連キーワードが含まれているか確認
        title_lower = title.lower()
        if not any(kw in title_lower for kw in ["エスポラーダ", "イルネーヴェ", "espolada", "fリーグ"]):
            print(f"  スキップ（無関係）: {title}")
            continue


        articles.append({
            "title": title,
            "link": link,
            "pub_date": pub_date,
            "source": source,
        })

    return articles


def buffer_graphql(api_key: str, query: str, variables: dict = None) -> dict:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {"query": query}
    if variables:
        payload["variables"] = variables
    resp = requests.post(BUFFER_API_URL, headers=headers, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def get_buffer_channel_id(api_key: str, org_id: str) -> str:
    query = """
    query GetChannels($input: ChannelsInput!) {
        channels(input: $input) {
            id
            name
            service
        }
    }
    """
    variables = {"input": {"organizationId": org_id}}
    result = buffer_graphql(api_key, query, variables)
    if result.get("errors"):
        print(f"Bufferチャンネル取得エラー: {result['errors']}")
        return ""
    channels = (result.get("data") or {}).get("channels") or []
    for ch in channels:
        if ch.get("service") in ("twitter", "x") and ch.get("id"):
            return ch["id"]
    # X以外のチャンネルへ誤投稿しない。
    return ""


def post_to_buffer(api_key: str, channel_id: str, text: str) -> bool:
    query = """
    mutation CreatePost($input: CreatePostInput!) {
        createPost(input: $input) {
            ... on PostActionSuccess {
                post {
                    id
                    text
                }
            }
            ... on MutationError {
                message
            }
        }
    }
    """
    variables = {
        "input": {
            "text": text,
            "channelId": channel_id,
            "schedulingType": "automatic",
            "mode": "shareNow",
        }
    }
    try:
        result = buffer_graphql(api_key, query, variables)
        if result.get("errors"):
            print(f"Buffer投稿エラー: {result['errors']}")
            return False
        create_post = (result.get("data") or {}).get("createPost") or {}
        if "message" in create_post:
            print(f"Buffer投稿エラー: {create_post['message']}")
            return False
        post = create_post.get("post") or {}
        if not post.get("id"):
            print("Buffer投稿成功を確認できませんでした（投稿IDなし）。")
            return False
        print(f"Buffer投稿成功: id={post['id']}")
        return True
    except Exception as e:
        print(f"Buffer投稿失敗: {e}")
        return False


def article_title(article: dict) -> str:
    """媒体名の接尾辞だけを除去し、スコアなど本文中のハイフンは保つ。"""
    title = article["title"].strip()
    source = article.get("source", "").strip()
    suffix = f" - {source}"
    if source and title.endswith(suffix):
        title = title[:-len(suffix)].rstrip()
    return title


def compose_news_post(article: dict) -> str:
    link = article["link"]
    source = article["source"]

    title_clean = article_title(article)

    if source:
        msg = (
            f"📰 {title_clean}\n"
            f"（{source}）\n"
            f"🔗 {link}\n"
            f"#エスポラーダ北海道 #Fリーグ"
        )
    else:
        msg = (
            f"📰 {title_clean}\n"
            f"🔗 {link}\n"
            f"#エスポラーダ北海道 #Fリーグ"
        )
    return msg


def main():
    buffer_api_key = os.getenv("BUFFER_API_KEY")
    buffer_org_id = os.getenv("BUFFER_ORG_ID")
    max_posts = 3  # 1回あたり最大投稿数

    if not buffer_api_key or not buffer_org_id:
        print("BUFFER_API_KEY または BUFFER_ORG_ID が未設定です。")
        return

    posted = load_posted_news()
    all_articles = []

    for keyword in SEARCH_KEYWORDS:
        print(f"検索中: {keyword}")
        articles = fetch_google_news(keyword)
        print(f"  → {len(articles)}件取得")
        all_articles.extend(articles)

    # 全タイトルが一致する記事だけをまとめる。共通の冒頭だけでは
    # 別の試合結果やお知らせまで重複と誤判定してしまう。
    seen_urls = set()
    groups = {}
    for article in all_articles:
        url = article["link"]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        title_key = re.sub(r"[\s　]", "", article_title(article)).casefold()
        group = groups.setdefault(title_key, {"article": article, "urls": set()})
        group["urls"].add(url)

    previously_posted = posted.copy()
    unique_articles = []
    for group in groups.values():
        if group["urls"] & posted:
            # 同じ記事の別URLは、代表URLの投稿が確認できている場合だけ記録。
            posted.update(group["urls"])
        else:
            unique_articles.append(group)
    if posted != previously_posted:
        save_posted_news(posted)

    if not unique_articles:
        print("新着ニュースなし。")
        return

    print(f"新着ニュース: {len(unique_articles)}件（最大{max_posts}件投稿）")

    print("Bufferチャンネル検索中...")
    try:
        channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
    except (requests.RequestException, ValueError) as e:
        print(f"Bufferチャンネル取得失敗: {e}")
        return
    if not channel_id:
        print("Bufferチャンネルが見つかりません。")
        return

    count = 0
    for group in unique_articles[:max_posts]:
        article = group["article"]
        tweet = compose_news_post(article)
        print(f"投稿中: {article['title']}")
        if not post_to_buffer(buffer_api_key, channel_id, tweet):
            print("投稿に成功しませんでした。未投稿のまま次回実行に残します。")
            continue
        posted.update(group["urls"])
        # 後続の投稿が失敗しても、成功済みの投稿を次回重複させない。
        save_posted_news(posted)
        count += 1

    print(f"投稿完了: {count}件")


if __name__ == "__main__":
    main()
