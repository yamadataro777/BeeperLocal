"""Bounded Instagram snapshot persistence, separate from LINE synchronization."""
from datetime import datetime, timezone

from .errors import AppError
from .models import HistorySyncReceipt


def history_receipt(batch):
    if (batch.provider != "instagram" or not batch.live or batch.errors or batch.normalization_errors
            or batch.conversations_requested != 1 or batch.conversations_fetched != 1
            or len(batch.conversations) != 1):
        raise AppError("BAD_RESPONSE")
    record = batch.conversations[0]
    scope = (record.provider, record.account_id, record.conversation.id)
    if record.provider != "instagram" or record.conversation.kind != "dm":
        raise AppError("BAD_RESPONSE")
    if any((m.provider, m.account_id, m.conversation_id) != scope for m in batch.messages):
        raise AppError("BAD_RESPONSE")
    if len({m.id for m in batch.messages}) != len(batch.messages):
        raise AppError("BAD_RESPONSE")
    try:
        return HistorySyncReceipt(*scope, datetime.now(timezone.utc), batch.requested_limit,
                                  batch.raw_items, len(batch.messages), batch.excluded_events,
                                  batch.history_limited)
    except (TypeError, ValueError):
        raise AppError("BAD_RESPONSE") from None


def persist_history(db, batch):
    receipt = history_receipt(batch)
    return db.upsert(batch.messages, conversations=batch.conversations, sync_receipts=[receipt])
