"""System-owned OAuth browser: authorization code/state travel through a private pipe."""
import asyncio
import json
from pathlib import Path
import secrets
import sys

from .connectors.line import stop_process
from .errors import AppError


def login_binary():
    path = (Path(sys.executable).parent / 'beeperlocal-slack-login' if getattr(sys, 'frozen', False)
            else Path(__file__).resolve().parents[1] / 'bin/beeperlocal-slack-login')
    if sys.platform != 'darwin' or not path.is_file():
        raise AppError('SLACK_BROWSER_FAILED')
    return str(path)


def validate_result(value, state):
    if not isinstance(value, dict) or type(value.get('ok')) is not bool:
        raise AppError('SLACK_OAUTH_FAILED')
    if not value['ok']:
        raise AppError({'cancelled': 'SLACK_OAUTH_CANCELLED', 'timeout': 'SLACK_OAUTH_TIMEOUT'}.get(value.get('error'), 'SLACK_BROWSER_FAILED'))
    code, actual = value.get('code'), value.get('state')
    if (not isinstance(code, str) or not 1 <= len(code) <= 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in code)
            or not isinstance(actual, str) or not actual.isascii() or not secrets.compare_digest(actual, state)):
        raise AppError('SLACK_OAUTH_FAILED')
    return code


async def authorization_code(url, state):
    try:
        process = await asyncio.create_subprocess_exec(login_binary(), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=32768, start_new_session=True)
    except OSError:
        raise AppError('SLACK_BROWSER_FAILED') from None
    try:
        async with asyncio.timeout(200):
            process.stdin.write(json.dumps({'protocol': 1, 'url': url, 'state': state}).encode() + b'\n')
            await process.stdin.drain(); process.stdin.close()
            raw = await process.stdout.readline()
            if not raw or len(raw) > 32768 or await process.wait() != 0:
                raise AppError('SLACK_BROWSER_FAILED')
            return validate_result(json.loads(raw), state)
    except (ValueError, UnicodeError):
        raise AppError('SLACK_OAUTH_FAILED') from None
    except TimeoutError:
        raise AppError('SLACK_OAUTH_TIMEOUT') from None
    finally:
        await stop_process(process)
