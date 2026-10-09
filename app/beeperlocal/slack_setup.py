"""Interactive, packaged Slack User OAuth setup. No credentials in arguments."""
from __future__ import annotations

import asyncio
import json
import logging
import sys
import subprocess

from .auth import login_slack
from .credentials import MacKeychain
from .errors import AppError
from .slack_web_login import login_binary


def verify_runtime():
    try:
        from .native_keychain import NativeKeychain
        from .connectors.slack import SlackAPI
        NativeKeychain()  # Load frameworks without accessing any Keychain items.
        native = subprocess.run([login_binary(), '--self-test'], capture_output=True, text=True, timeout=15)
        if native.returncode or json.loads(native.stdout).get('selfTest') is not True:
            raise AppError('SLACK_BROWSER_FAILED')
        print(json.dumps({"slackLoginReady": True}))
        return 0
    except Exception:
        print(json.dumps({"slackLoginReady": False, "error": "RUNTIME_INCOMPLETE"}))
        return 1


def main():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise AppError("INTERACTIVE_REQUIRED")
        print("ワークスペースで承認されたSlackアプリのUser OAuth Tokenを入力してください。")
        print("Bot Tokenは使えません。トークンは入力時に表示せず、Macのキーチェーンに保存します。")
        asyncio.run(login_slack(MacKeychain()))
        print("Slackの認証を保存しました。BeeperLocalに戻り、Slackへ再接続してください。")
        return 0
    except KeyboardInterrupt:
        print("Slackの接続を中止しました。")
        return 130
    except Exception as exc:
        error = exc if isinstance(exc, AppError) else AppError("UNEXPECTED_ERROR")
        print(f"接続を完了できませんでした [{error.code}]。{error.safe_message}", file=sys.stderr)
        return 1
    finally:
        logging.disable(previous)
