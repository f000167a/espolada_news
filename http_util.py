#!/usr/bin/env python3
"""
HTTP取得の共通ユーティリティ。

espolada.com はGitHub Actionsランナーから稀に接続タイムアウトするため、
一時的な失敗はリトライで吸収する。
"""

import time

import requests

# リトライ対象（一時的なネットワーク障害）
RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectTimeout,
    requests.exceptions.ReadTimeout,
    requests.exceptions.ConnectionError,
)
# リトライ対象（サーバ側の一時的な応答）
RETRYABLE_STATUS = (429, 500, 502, 503, 504)


def get_with_retry(url: str, headers: dict = None, timeout: int = 30,
                   retries: int = 3, backoff: int = 2) -> requests.Response:
    """
    GETを最大retries回試行する。試行間の待機は backoff の指数（2秒, 4秒, ...）。
    すべて失敗した場合は最後のエラーを送出する（呼び出し側で捕捉する想定）。
    """
    last_error = None

    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
        except RETRYABLE_EXCEPTIONS as e:
            last_error = e
        else:
            if resp.status_code not in RETRYABLE_STATUS:
                resp.raise_for_status()
                return resp
            last_error = requests.exceptions.HTTPError(
                f"HTTP {resp.status_code}", response=resp
            )

        if attempt < retries:
            wait = backoff ** attempt
            print(f"取得失敗 {attempt}/{retries}（{wait}秒後に再試行）: {url} — {last_error}")
            time.sleep(wait)

    raise last_error
