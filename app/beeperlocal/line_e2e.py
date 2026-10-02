"""Small manual regression: one send, matching realtime reply, local reopen/search."""
from __future__ import annotations
import asyncio
from contextlib import aclosing, suppress
import secrets
from .errors import AppError
from .models import StoredConversation


async def run_e2e(connector, open_db, *, timeout=300, notice=print):
    conversation = connector.selected_conversation()
    catalog = [StoredConversation("line", connector.account_id, conversation)]
    nonce = secrets.token_hex(16)
    text = "BeeperLocal接続テスト。このメッセージ全文をコピーして、そのまま返信してください。\n確認コード: " + nonce
    received = None
    outgoing = None
    watcher = starter = None
    started = asyncio.Event()
    with open_db() as db:
        db.upsert_conversations(catalog)

    async def receive():
        nonlocal received
        async with aclosing(connector.watch(timeout=timeout, started=started)) as stream:
            async for message in stream:
                if (message.provider != "line" or message.account_id != connector.account_id
                        or message.conversation_id != conversation.id or message.direction != "incoming"
                        or message.sender_id != conversation.id or message.text != text):
                    continue
                with open_db() as db:
                    db.upsert([message], conversations=catalog)
                received = message
                notice("line_realtime=STORED | direction=incoming | matched_current_run=true")
                return
        raise AppError("LINE_E2E_TIMEOUT")

    try:
        async with asyncio.timeout(timeout):
            watcher = asyncio.create_task(receive())
            starter = asyncio.create_task(started.wait())
            await asyncio.wait({watcher, starter}, return_when=asyncio.FIRST_COMPLETED)
            if watcher.done():
                await watcher
            result = await connector.send_text(text)  # One attempt, no retry/resume state.
            outgoing = result.message
            with open_db() as db:
                db.upsert([outgoing], conversations=catalog)
            notice("line_send=ACKNOWLEDGED | encrypted=" + str(result.encrypted).lower())
            notice("相手に届いたテストメッセージ全文を、そのままコピーして返信してもらってください。")
            await watcher
        with open_db() as db:
            found, _ = db.search(nonce, provider="line", limit=100)
        by_id = {m.id: m for m in found}
        if (received is None or any(m.id not in by_id or by_id[m.id].text != text
                                   or by_id[m.id].direction != m.direction for m in (outgoing, received))):
            raise AppError("LINE_E2E_VERIFY_FAILED")
        notice("line_e2e=CLOSED | realtime_reply=PASS | local_search=PASS")
        return 0
    except TimeoutError:
        raise AppError("LINE_E2E_TIMEOUT") from None
    finally:
        for task in (starter, watcher):
            if task is not None:
                if not task.done():
                    task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
