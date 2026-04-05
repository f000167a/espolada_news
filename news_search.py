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
    url = f"https://news.google.com/rss/search?q={quote(keyword)}&hl=ja&gl=JP&ceid=JP:ja"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"Google News取得失敗 ({keyword}): {e}")
        return []

    root = ET.fromstring(resp.text)
    articles = []

    for item in root.findall(".//item"):
        title = item.findtext("title", "")
        link = item.findtext("link", "")
        pub_date = item.findtext("pubDate", "")
        source = item.findtext("source", "")

        if not title or not link:
            continue

        # espolada.com自体のニュースは除外（公式Bot側で処理済み）
        skip = False
        for domain in EXCLUDE_DOMAINS:
            if domain in link:
                skip = True
                break
        if skip:
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
    channels = result.get("data", {}).get("channels", [])
    for ch in channels:
        if ch.get("service") in ("twitter", "x"):
            return ch["id"]
    if channels:
        return channels[0]["id"]
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
        if "errors" in result:
            print(f"Buffer投稿エラー: {result['errors']}")
            return False
        create_post = result.get("data", {}).get("createPost", {})
        if "message" in create_post:
            print(f"Buffer投稿エラー: {create_post['message']}")
            return False
        post = create_post.get("post", {})
        print(f"Buffer投稿成功: id={post.get('id')}")
        return True
    except Exception as e:
        print(f"Buffer投稿失敗: {e}")
        return False


def compose_news_post(article: dict) -> str:
    title = article["title"]
    link = article["link"]
    source = article["source"]

    # タイトルから末尾の " - ソース名" を除去
    title_clean = re.sub(r"\s*-\s*[^-]+$", "", title).strip()

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

    # URL重複排除
    seen = set()
    unique_articles = []
    for a in all_articles:
        if a["link"] not in seen and a["link"] not in posted:
            seen.add(a["link"])
            unique_articles.append(a)

    if not unique_articles:
        print("新着ニュースなし。")
        save_posted_news(posted)
        return

    print(f"新着ニュース: {len(unique_articles)}件（最大{max_posts}件投稿）")

    print("Bufferチャンネル検索中...")
    channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
    if not channel_id:
        print("Bufferチャンネルが見つかりません。")
        return

    count = 0
    for article in unique_articles[:max_posts]:
        tweet = compose_news_post(article)
        print(f"投稿中: {article['title']}")
        post_to_buffer(buffer_api_key, channel_id, tweet)
        posted.add(article["link"])
        count += 1

    save_posted_news(posted)
    print(f"投稿完了: {count}件")


if __name__ == "__main__":
    main()
