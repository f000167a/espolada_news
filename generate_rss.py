#!/usr/bin/env python3
"""
エスポラーダ北海道ニュースRSSフィード生成スクリプト
espolada.com/news/ をスクレイピングしてRSS (feed.xml) を生成する。
GitHub Actionsで定期実行 → GitHub Pagesで公開する想定。
"""

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
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
JST = timezone(timedelta(hours=9))


def fetch_news_list() -> list[dict]:
    """ニュース一覧ページから記事リストを取得"""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.get(NEWS_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    articles = []
    seen_urls = set()

    # ニュースページ内のリンクを探索
    for link in soup.find_all("a", href=True):
        href = link["href"]

        # /news/ 配下の個別記事リンクのみ対象
        if "/news/" not in href:
            continue
        if href.rstrip("/") == NEWS_URL.rstrip("/"):
            continue
        if href.startswith("/"):
            href = BASE_URL + href

        # ニュース一覧のURLそのものは除外
        if href.rstrip("/") in (NEWS_URL.rstrip("/"), BASE_URL + "/news"):
            continue

        # 重複排除
        clean_url = href.rstrip("/")
        if clean_url in seen_urls:
            continue

        # タイトル取得
        title = link.get_text(strip=True)
        if not title or len(title) < 5:
            continue

        # ナビゲーション要素を除外（短すぎるテキスト）
        if title in ("ニュース", "一覧に戻る", "前の記事", "次の記事"):
            continue

        seen_urls.add(clean_url)

        # 日付を親要素から探す
        date_str = ""
        parent = link.find_parent(["li", "div", "article", "dl", "dd"])
        if parent:
            date_match = re.search(r"(\d{4})[./](\d{1,2})[./](\d{1,2})", parent.get_text())
            if date_match:
                y, m, d = date_match.groups()
                date_str = f"{y}-{int(m):02d}-{int(d):02d}"

        # カテゴリ
        category = ""
        if parent:
            cat_el = parent.find(class_=re.compile(r"cat|category|tag|label"))
            if cat_el:
                category = cat_el.get_text(strip=True)

        articles.append({
            "title": title,
            "url": href,
            "date": date_str,
            "category": category,
        })

    print(f"取得記事数: {len(articles)}")
    return articles


def fetch_article_summary(url: str) -> str:
    """記事ページから冒頭テキストを取得"""
    headers = {"User-Agent": USER_AGENT}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # 記事本文エリアを探す
    content = (
        soup.find("article")
        or soup.find(class_=re.compile(r"entry|post-content|news-content|content"))
        or soup.find("main")
    )
    if not content:
        return ""

    texts = []
    for el in content.find_all(["p", "div"], recursive=False):
        t = el.get_text(strip=True)
        if t and len(t) > 10:
            texts.append(t)
    return " ".join(texts)[:300]


def generate_rss(articles: list[dict]) -> str:
    """記事リストからRSS XMLを生成"""
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

    # atom:link (self)
    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for article in articles:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = article["title"]
        ET.SubElement(item, "link").text = article["url"]
        ET.SubElement(item, "guid").text = article["url"]

        # 日付がある場合、pubDateを設定
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

        # description（要約）
        summary = fetch_article_summary(article["url"])
        if summary:
            ET.SubElement(item, "description").text = summary
        else:
            ET.SubElement(item, "description").text = article["title"]

    # 整形出力
    rough_string = ET.tostring(rss, encoding="unicode", xml_declaration=False)
    dom = minidom.parseString(rough_string)
    pretty = dom.toprettyxml(indent="  ", encoding="UTF-8")
    return pretty.decode("utf-8")


def main():
    import os

    articles = fetch_news_list()
    if not articles:
        print("記事が取得できませんでした。")
        return

    xml_content = generate_rss(articles)

    # docs/ ディレクトリに出力（GitHub Pages用）
    os.makedirs("docs", exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(xml_content)

    print(f"RSSフィード生成完了: {OUTPUT_FILE} ({len(articles)}記事)")


if __name__ == "__main__":
    main()
