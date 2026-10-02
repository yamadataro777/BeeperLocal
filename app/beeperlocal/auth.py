from __future__ import annotations
import asyncio
import re
from .credentials import CredentialStore
from .errors import AppError, telegram_error
from .privacy import secret_prompt

async def login_slack(store: CredentialStore) -> None:
    from .connectors.slack import SlackAPI, account_identity
    token = secret_prompt("Slack User OAuth Token (xoxp-, 入力非表示): ")
    api = SlackAPI(token, max_wait=0)
    auth = await asyncio.to_thread(api.call, "auth.test")
    identity = account_identity(auth)
    old = {}
    try:
        old = store.load("slack")
    except AppError as exc:
        if exc.code not in {"CREDENTIALS_MISSING", "CREDENTIALS_CORRUPT"}:
            raise
    selections = old.get("selections", []) if old.get("account_id") == identity else []
    store.save("slack", {"token": token, "account_id": identity, "selections": selections})

async def login_telegram(store: CredentialStore) -> None:
    from .connectors.telegram import create_client
    try:
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        raise AppError("DEPENDENCY_MISSING") from None
    api_id = secret_prompt("Telegram API ID (入力非表示): ")
    api_hash = secret_prompt("Telegram API hash (入力非表示): ")
    phone = secret_prompt("電話番号（国番号付き、例 +8190...／入力非表示）: ")
    if not api_id.isdigit() or int(api_id) <= 0 or not re.fullmatch(r"[0-9a-fA-F]{32}", api_hash) or not re.fullmatch(r"\+[0-9]{7,15}", phone):
        raise AppError("INVALID_INPUT")
    credentials = {"api_id": int(api_id), "api_hash": api_hash, "session": ""}
    client = create_client(credentials)
    try:
        await client.connect()
        sent = await client.send_code_request(phone)
        code = secret_prompt("Telegramに届いた確認コード（入力非表示）: ")
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
        except SessionPasswordNeededError:
            password = secret_prompt("Telegram 2段階認証パスワード（入力非表示）: ")
            await client.sign_in(password=password)
        me = await client.get_me()
        if me is None or not await client.is_user_authorized():
            raise AppError("CREDENTIALS_INVALID")
        if getattr(me, "bot", False):
            raise AppError("BOT_TOKEN_NOT_SUPPORTED")
        old = {}
        try:
            old = store.load("telegram")
        except AppError as exc:
            if exc.code not in {"CREDENTIALS_MISSING", "CREDENTIALS_CORRUPT"}:
                raise
        identity = str(me.id)
        credentials.update({"account_id": identity, "session": client.session.save(),
                            "selections": old.get("selections", []) if old.get("account_id") == identity else []})
        if not credentials["session"]:
            raise AppError("TELEGRAM_LOGIN_FAILED")
        store.save("telegram", credentials)
    except Exception as exc:
        raise telegram_error(exc) from None
    finally:
        await client.disconnect()

async def login_matrix(store: CredentialStore) -> None:
    from .connectors.matrix import MatrixAPI, matrix_identity, normalize_homeserver
    homeserver = input("Matrix homeserver URL [https://matrix.org]: ").strip() or "https://matrix.org"
    homeserver = normalize_homeserver(homeserver)
    mode = input("認証方法 1=Access Token / 2=ユーザー名+パスワード [1]: ").strip() or "1"
    if mode not in {"1", "2"}:
        raise AppError("INVALID_INPUT")
    if mode == "1":
        token = secret_prompt("Matrix Access Token（入力非表示）: ")
        api = MatrixAPI(homeserver, token)
        who = await asyncio.to_thread(api.get, "/_matrix/client/v3/account/whoami")
        identity = matrix_identity(who)
    else:
        user = input("Matrix ID（例 @name:matrix.org）: ").strip()
        password = secret_prompt("Matrix password（入力非表示）: ")
        api = MatrixAPI(homeserver)
        data = await asyncio.to_thread(api.password_login, user, password)
        token = data.get("access_token")
        if not isinstance(token, str) or not token:
            raise AppError("BAD_RESPONSE")
        identity = matrix_identity(data)
        api = MatrixAPI(homeserver, token)
        who = await asyncio.to_thread(api.get, "/_matrix/client/v3/account/whoami")
        if matrix_identity(who) != identity:
            raise AppError("ACCOUNT_CHANGED")
    old = {}
    try:
        old = store.load("matrix")
    except AppError as exc:
        if exc.code not in {"CREDENTIALS_MISSING", "CREDENTIALS_CORRUPT"}:
            raise
    selections = old.get("selections", []) if old.get("account_id") == identity else []
    store.save("matrix", {"homeserver": homeserver, "token": token, "account_id": identity, "selections": selections})
