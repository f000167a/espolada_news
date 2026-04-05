#!/usr/bin/env python3
"""
エスポラーダ北海道 試合リマインドBot
毎朝実行し、次の試合情報をBuffer経由でXに投稿する。
"""

import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

JST = timezone(timedelta(hours=9))
BUFFER_API_URL = "https://api.buffer.com"
SCHEDULE_FILE = Path(__file__).parent / "schedule.json"
MAX_DAYS_AHEAD = 21


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


def find_next_match(schedule: list[dict], today: str) -> dict | None:
    for match in schedule:
        if match["date"] is None:
            continue
        if match["date"] >= today:
            return match
    return None


def compose_reminder(match: dict, days_until: int) -> str:
    opponent = match["opponent"]
    time = match["time"]
    venue = match["venue"]
    round_num = match["round"]
    home_away = "🏠ホーム" if match["home"] else "✈️アウェイ"

    if days_until == 0:
        msg = (
            f"⚽ 【試合当日】Fリーグ第{round_num}節\n"
            f"本日 {time} キックオフ！\n"
            f"vs {opponent}\n"
            f"📍 {venue}（{home_away}）\n"
            f"応援よろしくお願いします！\n"
            f"#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
        )
    elif days_until == 1:
        msg = (
            f"📣 【明日は試合日】Fリーグ第{round_num}節\n"
            f"明日 {time} キックオフ\n"
            f"vs {opponent}\n"
            f"📍 {venue}（{home_away}）\n"
            f"#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
        )
    else:
        msg = (
            f"📅 次の試合まであと{days_until}日！\n"
            f"Fリーグ第{round_num}節\n"
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
    print(f"今日: {today}")

    schedule = load_schedule()
    match = find_next_match(schedule, today)

    if match is None:
        print("今シーズンの残り試合はありません。")
        return

    match_date = datetime.strptime(match["date"], "%Y-%m-%d").replace(tzinfo=JST)
    days_until = (match_date - now.replace(hour=0, minute=0, second=0, microsecond=0)).days

    print(f"次の試合: 第{match['round']}節 vs {match['opponent']} ({match['date']}) あと{days_until}日")

    if days_until > MAX_DAYS_AHEAD:
        print(f"次の試合まで{days_until}日（{MAX_DAYS_AHEAD}日超）。投稿スキップ。")
        return

    reminder = compose_reminder(match, days_until)
    print(f"--- ポスト内容 ---\n{reminder}\n---")

    print("Bufferチャンネル検索中...")
    channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
    if not channel_id:
        print("Bufferチャンネルが見つかりません。")
        return
    print(f"チャンネルID: {channel_id}")

    post_to_buffer(buffer_api_key, channel_id, reminder)


if __name__ == "__main__":
    main()
