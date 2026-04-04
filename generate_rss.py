#!/usr/bin/env python3
"""
エスポラーダ北海道 ニュースRSS生成 & X投稿スクリプト
"""

import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from pathlib import Path
from xml.dom import minidom

import requests
from bs4 import BeautifulSoup

NEWS_URL = "https://espolada.com/news/"
BASE_URL = "https://espolada.com"
FEED_TITLE = "エスポラーダ北海道 ニュース"
FEED_DESCRIPTION = "エスポラーダ北海道 公式サイトの最新ニュース"
FEED_LINK = "https://espolada.com/news/"
USER_AGENT = "EspoladaRSSBot/1.0"
OUTPUT_FILE = "docs/feed.xml"
POSTED_FILE = "posted.json"
JST = timezone(timedelta(hours=9))


def load_posted() -> set:
    if Path(POSTED_FILE).exists():
        data = json.loads(Path(POSTED_FILE).read_text(encoding="utf-8"))
        return set(data.get("posted_urls", []))
    return set()


def save_posted(posted: set):
    data = {"posted_urls": sorted(posted), "updated_at": datetime.now(JST).isoformat()}
    Path(POSTED_FILE).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def fetch_news_list() -> list[dict]:
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(NEWS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls = set()

    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/news/" not in href:
            continue
        if href.startswith("/"):
            href = BASE_URL + href

        clean_url = href.rstrip("/")
        if clean_url in seen_urls:
            continue
        if clean_url in (NEWS_URL.rstrip("/"), BASE_URL + "/news"):
            continue

        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        if title in ("ニュース", "一覧に戻る", "前の記事", "次の記事"):
            continue

        seen_urls.add(clean_url)

        # 日付とカテゴリをタイトルから分離
        # パターン: "カテゴリYYYY.MM.DD本文タイトル"
        clean_title = title
        category = ""
        date_str = ""
        m = re.match(
            r"^(お知らせ|試合|レディース|サテライト|スクール|アカデミー)?"
            r"(\d{4}\.\d{1,2}\.\d{1,2})?"
            r"(.+)$",
            title,
        )
        if m:
            category = m.group(1) or ""
            if m.group(2):
                parts = m.group(2).split(".")
                date_str = f"{parts[0]}-{int(parts[1]):02d}-{int(parts[2]):02d}"
            clean_title = m.group(3).strip()

        # 親要素からも日付を探す（フォールバック）
        if not date_str:
            parent = link.find_parent(["li", "div", "article", "dl", "dd"])
            if parent:
                date_match = re.search(
                    r"(\d{4})[./](\d{1,2})[./](\d{1,2})", parent.get_text()
                )
                if date_match:
                    y, mo, d = date_match.groups()
                    date_str = f"{y}-{int(mo):02d}-{int(d):02d}"

        articles.append(
            {
                "title": clean_title,
                "url": href,
                "date": date_str,
                "category": category,
            }
        )

    print(f"取得記事数: {len(articles)}")
    return articles


def generate_rss(articles: list[dict]) -> str:
    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = FEED_TITLE
    ET.SubElement(channel, "link").text = FEED_LINK
    ET.SubElement(channel, "description").text = FEED_DESCRIPTION
    ET.SubElement(channel, "language").text = "ja"

    now = datetime.now(timezone.utc)
    ET.SubElement(channel, "lastBuildDate").text = now.strftime(
        "%a, %d %b %Y %H:%M:%S +0000"
    )

    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]

        if article["date"]:
            try:
                dt = datetime.strptime(article["date"], "%Y-%m-%d")
                dt = dt.replace(tzinfo=JST)
                ET.SubElement(item, "pubDate").text = dt.strftime(
                    "%a, %d %b %Y %H:%M:%S +0900"
                )
            except ValueError:
                pass

        if article.get("category"):
            ET.SubElement(item, "category").text = article["category"]

        ET.SubElement(item, "description").text = article["title"]

    rough_string = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough_string)
    pretty = dom.toprettyxml(indent="  ", encoding="UTF-8")
    return pretty.decode("utf-8")


def post_to_x(text: str) -> bool:
    api_key = os.getenv("X_API_KEY")
    api_secret = os.getenv("X_API_SECRET")
    access_token = os.getenv("X_ACCESS_TOKEN")
    access_secret = os.getenv("X_ACCESS_SECRET")

    if not all([api_key, api_secret, access_token, access_secret]):
        print("X APIキー未設定。投稿スキップ。")
        return False

    try:
        import tweepy

        client = tweepy.Client(
            consumer_key=api_key,
            consumer_secret=api_secret,
            access_token=access_token,
            access_token_secret=access_secret,
        )
        response = client.create_tweet(text=text)
        tweet_id = response.data["id"]
        print(f"Xポスト成功: https://x.com/i/status/{tweet_id}")
        return True
    except Exception as e:
        print(f"Xポスト失敗: {e}")
        return False


def compose_tweet(article: dict) -> str:
    title = article["title"]
    url = article["url"]
    hashtags = "\n#エスポラーダ北海道 #Fリーグ"
    link = f"\n🔗 {url}"
    header = f"📢 {title}"

    # 280文字制限チェック（URLは23文字換算）
    max_len = 280 - 23 - len(hashtags) - 5
    if len(header) > max_len:
        header = f"📢 {title[: max_len - 4]}…"

    return f"{header}{link}{hashtags}"


def main():
    os.makedirs("docs", exist_ok=True)

    articles = fetch_news_list()
    if not articles:
        print("記事が取得できませんでした。")
        return

    # RSS生成
    xml_content = generate_rss(articles)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)
    print(f"RSSフィード生成完了: {OUTPUT_FILE} ({len(articles)}記事)")

    # X投稿（新着のみ）
    posted = load_posted()
    new_articles = [a for a in articles if a["url"] not in posted]

    if not new_articles:
        print("新着記事なし。投稿スキップ。")
        return

    print(f"新着記事: {len(new_articles)}件")

    for article in reversed(new_articles):
        tweet = compose_tweet(article)
        print(f"投稿中: {article['title']}")
        post_to_x(tweet)
        posted.add(article["url"])
        save_posted(posted)


if __name__ == "__main__":
    main()
