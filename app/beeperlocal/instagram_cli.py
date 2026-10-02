"""Interactive Instagram entrypoints; no changes to LINE's active desktop path."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from dataclasses import replace
from datetime import datetime, timezone
import getpass
import sys
import warnings
from uuid import uuid4

from .connectors.instagram import InstagramConnector
from .credentials import MacKeychain
from .desktop_instagram import IG_SERVICE, open_instagram_store as open_message_store
from .errors import AppError
from .instagram_sync import persist_history
from .models import StoredConversation
from .outbox import OutgoingRequest
from .privacy import safe_text, secret_prompt


async def auth_prompt(fields):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise AppError("INTERACTIVE_REQUIRED")
    if not isinstance(fields, list) or not 1 <= len(fields) <= 8:
        raise AppError("IG_PROTOCOL_ERROR")
    labels = {"username": "Instagramユーザー名", "password": "Instagramパスワード",
              "verification_code": "Instagram確認コード", "method": "本人確認の方法",
              "action": "本人確認の操作", "cookie_consent": "InstagramのログインCookie利用（accept=承諾 / cancel=中止）"}
    answer = {}
    for field in fields:
        if not isinstance(field, dict) or not isinstance(field.get("id"), str):
            raise AppError("IG_PROTOCOL_ERROR")
        ident = field["id"]
        if not ident or len(ident) > 80:
            raise AppError("IG_PROTOCOL_ERROR")
        options = field.get("options", [])
        if not isinstance(options, list) or len(options) > 30 or any(not isinstance(o, str) for o in options):
            raise AppError("IG_PROTOCOL_ERROR")
        label = labels.get(ident, "Instagramの本人確認: " + safe_text(ident, 60))
        if options:
            print(label)
            for i, option in enumerate(options, 1):
                print(f"{i}. {safe_text(option, 120)}")
            try:
                index = int(input("番号: ")) - 1
                if index < 0:
                    raise ValueError()
                value = options[index]
            except (ValueError, IndexError, EOFError):
                raise AppError("INVALID_INPUT") from None
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("error", getpass.GetPassWarning)
                try:
                    value = getpass.getpass(label + "（入力非表示）: ")
                except (getpass.GetPassWarning, EOFError):
                    raise AppError("INTERACTIVE_REQUIRED") from None
            if ident != "password":
                value = value.strip()
        if not value or len(value) > 4096:
            raise AppError("INVALID_INPUT")
        answer[ident] = value
    return answer


async def select_instagram(connector, limit):
    from .cli import parse_selection
    choices = await connector.list_conversations(limit)
    if not choices:
        raise AppError("NO_CONVERSATIONS")
    print("Instagramで利用する1対1の相手を1人選んでください。")
    for i, row in enumerate(choices, 1):
        print(f"{i:3d}. {safe_text(row.title, 70)}")
    if connector.catalog_limited:
        print("現在取得できた一覧だけを表示しています。全会話の一覧取得は未対応です。")
    indexes = parse_selection(input("相手の番号: "), len(choices))
    if len(indexes) != 1:
        raise AppError("INVALID_INPUT")
    await connector.select_conversation(choices[indexes[0]])
    with open_message_store() as db:
        db.upsert_conversations([StoredConversation("instagram", connector.account_id, connector.selected_conversation())])
    print("instagram: 選択した相手をKeychainと暗号化DBへ保存しました。")
    return 0


async def send_instagram(args):
    connector = InstagramConnector(MacKeychain(service=IG_SERVICE))
    selected = connector.selected_conversation()
    print("Instagramの送信先: " + safe_text(selected.title, 70))
    text = secret_prompt("本文（入力非表示。Enterでこの相手へ1回送信）: ")
    if len(text.encode()) > 4000:
        raise AppError("INVALID_INPUT")
    record = StoredConversation("instagram", connector.account_id, selected)
    request = OutgoingRequest(str(uuid4()), "instagram", connector.account_id, selected.id, text,
                              "sending", datetime.now(timezone.utc))
    with open_message_store() as db:
        # Intent is durable before remote send; a crash never triggers replay.
        db.upsert([], conversations=[record], outgoing_requests=[request])
        try:
            result = await connector.send_text(text)
        except (Exception, asyncio.CancelledError):
            db.upsert([], outgoing_requests=[replace(request, status="unknown")])
            raise
        try:
            db.upsert([result.message], conversations=[record], outgoing_requests=[
                replace(request, status="acknowledged", message_id=result.message.id)])
        except Exception:
            raise AppError("IG_SENT_NOT_STORED") from None
    print("instagram_send=ACKNOWLEDGED | local_store=WRITTEN | 自動再送なし")
    print("Instagramの受付応答と暗号化保存を確認しました。相手側の着信は別途確認してください。")
    return 0


async def watch_instagram(args):
    connector = InstagramConnector(MacKeychain(service=IG_SERVICE))
    selected = connector.selected_conversation()
    record = StoredConversation("instagram", connector.account_id, selected)
    received = 0
    seen = set()
    with open_message_store() as db:
        def save_history(batch):
            stats = persist_history(db, batch)
            print(f"instagram_history=STORED | processed={stats['processed']} | limited={str(batch.history_limited).lower()}", flush=True)
        print("instagram_watch=STARTING | 選択した1会話を受信します。Ctrl-Cで停止。", flush=True)
        try:
            async with asyncio.timeout(args.timeout + 80 if args.timeout else None):
                async with aclosing(connector.watch(timeout=args.timeout, from_now=args.from_now,
                                                    recovery_limit=args.recovery_limit, persist_history=save_history)) as stream:
                    async for message in stream:
                        stats = db.upsert([message], conversations=[record])
                        print(f"instagram_realtime=STORED | direction={message.direction} | inserted={stats['inserted']}", flush=True)
                        if message.direction == "incoming":
                            if args.timeout or args.max_messages:
                                if message.id not in seen:
                                    received += 1
                                    seen.add(message.id)
                            else:
                                received += stats["inserted"]
                        if args.max_messages and received >= args.max_messages:
                            break
        except TimeoutError:
            raise AppError("IG_REQUEST_TIMEOUT") from None
    print(f"instagram_watch=STOPPED | incoming_unique={received}")
    return 0 if received else 1


async def run_instagram(args):
    """The Instagram CLI and GUI share exactly the same native credential/DB scope."""
    store = MacKeychain(service=IG_SERVICE)
    if args.command == "login":
        from .connectors.instagram import login_instagram
        await login_instagram(store)
        print("instagram: ログイン確認・Keychain保存が完了しました。")
        return 0
    if args.command == "send":
        return await send_instagram(args)
    if args.command in {"watch", "daemon"}:
        return await watch_instagram(args)
    connector = InstagramConnector(store)
    if args.command == "select":
        return await select_instagram(connector, args.list_limit)
    if args.command in {"sync", "fetch"}:
        batch = await connector.fetch(min(args.limit, 100))
        if args.command == "sync":
            with open_message_store() as db:
                stats = persist_history(db, batch)
                print(f"instagram=PASS | real_messages={len(batch.messages)} | local_store=WRITTEN | processed={stats['processed']} | inserted={stats['inserted']} | updated={stats['updated']} | total={db.total_count()}")
        else:
            print(f"instagram=PASS | real_messages={len(batch.messages)} | history_limited=true")
        if args.preview:
            from .privacy import preview_line
            for message in batch.messages:
                print(preview_line(message, preview=True))
        return 0
    if args.command == "search":
        from .privacy import preview_line
        query = secret_prompt("検索語（入力非表示）: ")
        with open_message_store() as db:
            rows, scanned = db.search(query, provider="instagram", limit=args.limit)
        print(f"local_search: matches={len(rows)} scanned={scanned}")
        for row in rows:
            print(preview_line(row, preview=args.preview))
        return 0
    if args.command == "conversations":
        with open_message_store() as db:
            if args.refresh:
                rows = await connector.list_conversations(100)
                db.upsert_conversations([StoredConversation("instagram", connector.account_id, c) for c in rows])
            rows = db.list_conversations(provider="instagram", account_id=connector.account_id)
            print(f"instagram_conversations={len(rows)}")
            if args.names:
                for row in rows:
                    print(safe_text(row.conversation.title, 70))
        return 0
    if args.command == "messages":
        from .privacy import preview_line
        with open_message_store() as db:
            rows = db.list_messages("instagram", connector.account_id, connector.selected_conversation().id, limit=args.limit)
        print(f"instagram_messages={len(rows)}")
        for row in rows:
            print(preview_line(row, preview=args.preview))
        return 0
    if args.command == "forget":
        if not sys.stdin.isatty():
            raise AppError("INTERACTIVE_REQUIRED")
        if input("Instagramのログイン情報だけ削除する場合は DELETE と入力: ") == "DELETE":
            store.delete("instagram")
        return 0
    raise AppError("INVALID_INPUT")
