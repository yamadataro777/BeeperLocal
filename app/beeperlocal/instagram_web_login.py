"""Instagram's own interactive verification, in a dedicated ephemeral browser."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
import json
from pathlib import Path
import sys

from .connectors.instagram import InstagramAdapter, decimal_id, save_session
from .connectors.line import stop_process
from .errors import AppError

COOKIE_NAMES = {'sessionid', 'ds_user_id', 'csrftoken', 'mid', 'ig_did', 'ig_nrcb', 'rur', 'datr'}
MAX_RESULT = 64 * 1024


def login_binary():
    path = (Path(sys.executable).parent / 'beeperlocal-instagram-login' if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[1] / 'bin/beeperlocal-instagram-login')
    if sys.platform != 'darwin' or not path.is_file():
        raise AppError('IG_WEB_LOGIN_UNAVAILABLE')
    return str(path)


def validate_result(result):
    if not isinstance(result, dict) or type(result.get('ok')) is not bool:
        raise AppError('IG_PROTOCOL_ERROR')
    if not result['ok']:
        raise AppError({'cancelled': 'IG_LOGIN_CANCELLED', 'web_login_timeout': 'IG_REQUEST_TIMEOUT'}.get(result.get('error'), 'IG_WEB_LOGIN_UNAVAILABLE'))
    jar = result.get('cookies')
    if (not isinstance(jar, dict) or not set(jar) <= COOKIE_NAMES
            or not all(jar.get(k) for k in ('sessionid', 'ds_user_id', 'csrftoken'))
            or any(not isinstance(v, str) or not v or len(v) > 8192
                   or any(ord(c) < 32 or ord(c) == 127 or c == ';' for c in v) for v in jar.values())):
        raise AppError('IG_PROTOCOL_ERROR')
    decimal_id(jar['ds_user_id'])
    return jar


async def browser_cookies():
    try:
        process = await asyncio.create_subprocess_exec(login_binary(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_RESULT, start_new_session=True)
    except OSError:
        raise AppError('IG_WEB_LOGIN_UNAVAILABLE') from None
    try:
        async with asyncio.timeout(920):
            process.stdin.write(b'{"op":"web_login","protocol":1}\n')
            await process.stdin.drain()
            process.stdin.close()
            raw = await process.stdout.readline()
            if not raw or len(raw) > MAX_RESULT or await process.wait() != 0:
                raise AppError('IG_WEB_LOGIN_UNAVAILABLE')
            return validate_result(json.loads(raw))
    except (ValueError, UnicodeError):
        raise AppError('IG_PROTOCOL_ERROR') from None
    except TimeoutError:
        raise AppError('IG_REQUEST_TIMEOUT') from None
    finally:
        await stop_process(process)


async def login_instagram_web(store, *, adapter=None, browser=None):
    jar = validate_result({'ok': True, 'cookies': await (browser or browser_cookies)()})
    account = jar['ds_user_id']
    adapter = adapter or InstagramAdapter()
    saved = None
    # LoadIndex proves the identity and usable Direct session before emitting
    # the session event. Cookie presence alone never writes to the Keychain.
    request = {'op': 'whoami', 'account_id': account, 'session': {'cookies': jar, 'www_claim': ''}}
    async with aclosing(adapter.events(request)) as stream:
        async for event in stream:
            if event['type'] == 'session':
                if event.get('account_id') != account:
                    raise AppError('ACCOUNT_CHANGED')
                saved = save_session(store, event)
            elif event['type'] == 'result':
                if saved is None or event.get('account_id') != account or event.get('own_fbid') != saved['own_fbid']:
                    raise AppError('BAD_RESPONSE')
                return
            else:
                raise AppError('IG_PROTOCOL_ERROR')
    raise AppError('IG_REQUEST_FAILED')
