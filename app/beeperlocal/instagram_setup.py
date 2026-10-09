"""Packaged Instagram login; never depends on a development checkout."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
import logging
import sys

from .connectors.instagram import InstagramAdapter
from .instagram_web_login import login_instagram_web as login_instagram, login_binary
from .credentials import MacKeychain
from .desktop_instagram import IG_SERVICE
from .errors import AppError


async def check_adapter():
    process = await asyncio.create_subprocess_exec(login_binary(), '--self-test',
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        output, _ = await asyncio.wait_for(process.communicate(), 20)
        if process.returncode != 0 or output.strip() != b'native_login_boundary_checks_passed':
            raise AppError('IG_WEB_LOGIN_UNAVAILABLE')
    finally:
        from .connectors.line import stop_process
        await stop_process(process)
    # Unsupported operations are rejected before session loading or networking.
    try:
        async with aclosing(InstagramAdapter().events({'op': 'unsupported'})) as events:
            async for _ in events:
                raise AppError('IG_PROTOCOL_ERROR')
    except AppError as exc:
        if exc.code == 'INVALID_INPUT':
            return
        raise
    raise AppError('IG_PROTOCOL_ERROR')


def verify_runtime():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        from .native_keychain import NativeKeychain
        NativeKeychain()  # Load frameworks without reading or writing an item.
        asyncio.run(check_adapter())
        print(json.dumps({'instagramLoginReady': True}))
        return 0
    except Exception:
        print(json.dumps({'instagramLoginReady': False, 'error': 'RUNTIME_INCOMPLETE'}))
        return 1
    finally:
        logging.disable(previous)


def main():
    previous = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        # Reject pipes before accessing the Keychain or starting a provider request.
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise AppError('INTERACTIVE_REQUIRED')
        print('Instagram公式サイトの専用ログイン画面を開きます。本人確認はその画面で進めてください。')
        print('通知が届かない場合は、Instagram画面に表示される「別の方法」などから選べる確認方法を使ってください。')
        print('認証が終わったら、右上の「ログイン完了・接続する」を押してください。')
        asyncio.run(login_instagram(MacKeychain(service=IG_SERVICE)))
        print('Instagramのログイン情報を、このMacのキーチェーンへ保存しました。')
        print('BeeperLocalでInstagramへ接続し、会話一覧から相手を選んでください。')
        return 0
    except KeyboardInterrupt:
        print('Instagramの接続を中止しました。')
        return 130
    except Exception as exc:
        error = exc if isinstance(exc, AppError) else AppError('UNEXPECTED_ERROR')
        print(f'接続を完了できませんでした [{error.code}]。{error.safe_message}', file=sys.stderr)
        return 1
    finally:
        logging.disable(previous)
