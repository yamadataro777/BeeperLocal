"""Read-only Slack network probe of the existing selection; output contains counts/status only.

No sending, credential export, selection changes or message/title/identifier output.
The existing encrypted database may be upserted only after a complete valid fetch.
"""
import asyncio
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from beeperlocal.connectors.slack import SlackConnector
from beeperlocal.credentials import MacKeychain
from beeperlocal.desktop import open_store
from beeperlocal.errors import AppError


async def check():
    result = {"live_send_attempts": 0, "auth": "UNVERIFIED", "history": "UNVERIFIED",
              "encrypted_persistence": "UNVERIFIED", "reopen": "UNVERIFIED", "search": "UNVERIFIED"}
    try:
        connector = SlackConnector(MacKeychain(), max_wait=0)
        await connector.connect()
        result["auth"] = "USER_OAUTH_CONFIRMED"
        batch = await connector.fetch(limit=1)
        if batch.errors:
            raise AppError(batch.errors[0])
        if batch.normalization_errors or batch.conversations_requested != batch.conversations_fetched:
            raise AppError("BAD_RESPONSE")
        result["history"] = "PASS"
        result["conversations_fetched"] = batch.conversations_fetched
        result["messages_fetched"] = len(batch.messages)
        result["conversation_kinds"] = sorted({c.conversation.kind for c in batch.conversations})
        with open_store() as db:
            db.upsert(batch.messages, conversations=batch.conversations)
        result["encrypted_persistence"] = "PASS"
        with open_store() as db:
            saved = {m.id for c in batch.conversations for m in db.list_messages(
                "slack", c.account_id, c.conversation.id, limit=100)}
            if not all(m.id in saved for m in batch.messages):
                raise AppError("LOCAL_DB_CORRUPT")
            result["reopen"] = "PASS"
            queries = [m for m in batch.messages if m.text and m.text.strip()]
            if queries:
                matches, _ = db.search(queries[0].text.strip()[:40], provider="slack", limit=100)
                result["search"] = "PASS" if any(m.id == queries[0].id for m in matches) else "NOT_FOUND_WITHIN_BOUND"
    except AppError as exc:
        result["error_code"] = exc.code
    except Exception:
        result["error_code"] = "UNEXPECTED_ERROR"
    return result


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    print(json.dumps(asyncio.run(check()), indent=2))
