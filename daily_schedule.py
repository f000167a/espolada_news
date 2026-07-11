#!/usr/bin/env python3
"""
エスポラーダ北海道 応援コンテンツBot
毎日定時に、日程案内とチャント紹介をローテーションして投稿する。
（試合リマインドBot＝match_reminder.pyと内容が重複しないよう、
 こちらは日程ページ案内とチャント紹介のみを担当する）
"""

import os
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
BUFFER_API_URL = "https://api.buffer.com"

# チームチャント一覧（espolada_chants/index.html の chants データより）
CHANTS = [
    {"title": "エスポラーダコール"},
    {"title": "北海道コール"},
    {"title": "ビルド１"},
    {"title": "ビルド２"},
    {"title": "UP Draft", "origin": "リパブリック讃歌"},
    {"title": "バモ北海道"},
    {"title": "Can't Take My Eyes Off You", "origin": "君の瞳に恋してる"},
    {"title": "行こうぜエスポラーダ"},
    {"title": "青と白の戦士"},
    {"title": "ONE HEART HOKKAIDO"},
    {"title": "バモバモ北海道"},
    {"title": "エスポラーダGO"},
    {"title": "エスポのゴールが見たい"},
    {"title": "道産子の誇り"},
]

CHANT_BOOK_URL = "https://f000167a.github.io/espolada_chants/"
SCHEDULE_URL = "https://espolada.com/match-info/fleague-schedule/"


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


def compose_schedule_post() -> str:
    return (
        "📋 メットライフ生命Fリーグ2026-27\n"
        "エスポラーダ北海道の試合日程はこちら👇\n"
        f"🔗 {SCHEDULE_URL}\n"
        "#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
    )


def compose_chant_post(chant: dict) -> str:
    origin_line = f"（原曲：{chant['origin']}）\n" if chant.get("origin") else ""
    return (
        f"🎤 チャント紹介：{chant['title']}\n"
        f"{origin_line}"
        "声を合わせてエスポラーダを後押ししよう！\n"
        "📖 歌詞・コールの全一覧はこちら👇\n"
        f"🔗 {CHANT_BOOK_URL}\n"
        "#エスポラーダ北海道 #Fリーグ"
    )


def compose_post(now: datetime) -> str:
    """
    日程案内とチャント紹介をローテーション投稿する。
    朝(午前)と夜(午後)で別コンテンツになるよう、日付とスロットからインデックスを決定。
    variants: [日程案内, チャント1, チャント2, ... チャントN]
    """
    slot = 0 if now.hour < 15 else 1
    variants = len(CHANTS) + 1
    idx = (now.timetuple().tm_yday * 2 + slot) % variants

    if idx == 0:
        return compose_schedule_post()
    return compose_chant_post(CHANTS[idx - 1])


def main():
    buffer_api_key = os.getenv("BUFFER_API_KEY")
    buffer_org_id = os.getenv("BUFFER_ORG_ID")

    if not buffer_api_key or not buffer_org_id:
        print("BUFFER_API_KEY または BUFFER_ORG_ID が未設定です。")
        return

    now = datetime.now(JST)
    print(f"実行日時: {now.strftime('%Y-%m-%d %H:%M')}")

    msg = compose_post(now)

    print(f"--- ポスト内容 ---\n{msg}\n---")

    print("Bufferチャンネル検索中...")
    channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
    if not channel_id:
        print("Bufferチャンネルが見つかりません。")
        return

    post_to_buffer(buffer_api_key, channel_id, msg)


if __name__ == "__main__":
    main()
