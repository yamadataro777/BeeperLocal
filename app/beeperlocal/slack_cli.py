"""Slack send/poll commands reuse the Core's encrypted outbox and recovery path."""
import asyncio
from uuid import uuid4

from .desktop_slack import SlackDesktop
from .errors import AppError
from .models import StoredConversation
from .privacy import secret_prompt


async def run_slack(args):
    core = SlackDesktop()
    try:
        core._initialize()
        core.require_storage()
        core.connector = core.connector_factory(core.credentials)
        await core.connector.connect()
        conversation = core.connector.selected_conversation()
        core.account_id = core.connector.account_id
        record = StoredConversation("slack", core.account_id, conversation)
        core.db.upsert_conversations([record])
        core.selected_id, core.connection = record.id, "connected"
        if args.command == "send":
            text = secret_prompt("選択済みSlack会話へ本人名義で1回送信（本文は入力非表示）: ")
            await core.send(record.id, text, str(uuid4()))
            print("slack_send=ACKNOWLEDGED | local_store=WRITTEN | delivery=UNVERIFIED")
            return 0
        if args.from_now or args.max_messages:
            raise AppError("INVALID_INPUT")
        core.history_limit = min(args.recovery_limit, 15)
        await core.sync_selected()
        core.start_watch()
        print(f"slack_receive=POLLING | interval_seconds=65 | history_limit={core.history_limit} | coverage=BOUNDED | Ctrl-Cで停止", flush=True)
        try:
            async with asyncio.timeout(args.timeout or None):
                while core.watch_task and not core.watch_task.done():
                    await asyncio.sleep(1)
        except TimeoutError:
            return 0
        if core.error_code:
            raise AppError(core.error_code)
        return 0
    finally:
        await core.close()
