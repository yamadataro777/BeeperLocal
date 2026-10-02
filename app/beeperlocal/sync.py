"""Bounded LINE history recovery. Never advance an external cursor or send."""
from datetime import datetime, timezone

from .errors import AppError
from .models import FetchBatch, HistorySyncReceipt


def line_history_receipt(batch: FetchBatch) -> HistorySyncReceipt:
    if batch.errors:
        raise AppError(batch.errors[0])
    if (batch.provider != "line" or not batch.live or batch.normalization_errors
            or batch.conversations_requested != 1 or batch.conversations_fetched != 1
            or len(batch.conversations) != 1):
        raise AppError("BAD_RESPONSE")
    record = batch.conversations[0]
    if record.provider != "line" or record.conversation.kind != "dm":
        raise AppError("BAD_RESPONSE")
    scope = (record.provider, record.account_id, record.conversation.id)
    if any((m.provider, m.account_id, m.conversation_id) != scope for m in batch.messages):
        raise AppError("BAD_RESPONSE")
    if len({m.id for m in batch.messages}) != len(batch.messages):
        raise AppError("BAD_RESPONSE")
    try:
        return HistorySyncReceipt(
            *scope, completed_at=datetime.now(timezone.utc), requested_limit=batch.requested_limit,
            raw_items=batch.raw_items, stored_messages=len(batch.messages),
            excluded_events=batch.excluded_events,
            history_limited=batch.history_limited or batch.raw_items >= batch.requested_limit,
        )
    except (TypeError, ValueError):
        raise AppError("BAD_RESPONSE") from None


def persist_line_history(db, batch: FetchBatch):
    receipt = line_history_receipt(batch)
    stats = db.upsert(batch.messages, conversations=batch.conversations, sync_receipts=[receipt])
    return receipt, stats


async def recover_line_history(connector, db, *, limit=50):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise AppError("INVALID_INPUT")
    return persist_line_history(db, await connector.fetch(limit))
