#!/usr/bin/env python3
"""
エスポラーダ北海道 試合リマインドBot
毎朝実行し、当日・翌日の試合があればBuffer経由でXに投稿する。
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

JST = timezone(timedelta(hours=9))
BUFFER_API_URL = "https://api.buffer.com"
SCHEDULE_FILE = Path(__file__).parent / "schedule.json"


def load_schedule() -> list[dict]:
    return json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))


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


def compose_reminder(match: dict, is_today: bool) -> str:
    opponent = match["opponent"]
    time = match["time"]
    venue = match["venue"]
    round_num = match["round"]
    home_away = "🏠ホーム" if match["home"] else "✈️アウェイ"

    if is_today:
        msg = (
            f"⚽ 【試合当日】Fリーグ第{round_num}節\n"
            f"本日 {time} キックオフ！\n"
            f"vs {opponent}\n"
            f"📍 {venue}（{home_away}）\n"
            f"応援よろしくお願いします！\n"
            f"#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
        )
    else:
        msg = (
            f"📣 【明日は試合日】Fリーグ第{round_num}節\n"
            f"明日 {time} キックオフ\n"
            f"vs {opponent}\n"
            f"📍 {venue}（{home_away}）\n"
            f"#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
        )
    return msg


def main():
    buffer_api_key = os.getenv("BUFFER_API_KEY")
    buffer_org_id = os.getenv("BUFFER_ORG_ID")

    if not buffer_api_key or not buffer_org_id:
        print("BUFFER_API_KEY または BUFFER_ORG_ID が未設定です。")
        return

    now = datetime.now(JST)
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    print(f"今日: {today} / 明日: {tomorrow}")

    schedule = load_schedule()

    channel_id = ""
    posted = False

    for match in schedule:
        if match["date"] is None:
            continue

        is_today = match["date"] == today
        is_tomorrow = match["date"] == tomorrow

        if not is_today and not is_tomorrow:
            continue

        if not channel_id:
            print("Bufferチャンネル検索中...")
            channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
            if not channel_id:
                print("Bufferチャンネルが見つかりません。")
                return
            print(f"チャンネルID: {channel_id}")

        reminder = compose_reminder(match, is_today)
        label = "当日" if is_today else "前日"
        print(f"リマインド投稿（{label}）: vs {match['opponent']}")
        print(f"--- ポスト内容 ---\n{reminder}\n---")

        post_to_buffer(buffer_api_key, channel_id, reminder)
        posted = True

    if not posted:
        print("今日・明日に試合はありません。")


if __name__ == "__main__":
    main()
