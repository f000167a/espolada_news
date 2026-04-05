#!/usr/bin/env python3
"""
エスポラーダ北海道 日程案内Bot
毎日定時に公式日程ページを案内する。
"""

import os
from datetime import datetime, timezone, timedelta

import requests

JST = timezone(timedelta(hours=9))
BUFFER_API_URL = "https://api.buffer.com"


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


def main():
    buffer_api_key = os.getenv("BUFFER_API_KEY")
    buffer_org_id = os.getenv("BUFFER_ORG_ID")

    if not buffer_api_key or not buffer_org_id:
        print("BUFFER_API_KEY または BUFFER_ORG_ID が未設定です。")
        return

    now = datetime.now(JST)
    print(f"実行日時: {now.strftime('%Y-%m-%d %H:%M')}")

    msg = (
        "📋 メットライフ生命Fリーグ2026-27\n"
        "エスポラーダ北海道の試合日程はこちら👇\n"
        "🔗 https://espolada.com/match-info/fleague-schedule/\n"
        "#エスポラーダ北海道 #Fリーグ #メットライフ生命Fリーグ"
    )

    print(f"--- ポスト内容 ---\n{msg}\n---")

    print("Bufferチャンネル検索中...")
    channel_id = get_buffer_channel_id(buffer_api_key, buffer_org_id)
    if not channel_id:
        print("Bufferチャンネルが見つかりません。")
        return

    post_to_buffer(buffer_api_key, channel_id, msg)


if __name__ == "__main__":
    main()
