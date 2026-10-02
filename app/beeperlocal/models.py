"""Provider-independent data. Full message IDs include their conversation."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any

SUPPORTED_PROVIDERS = ("telegram", "slack", "matrix", "line", "instagram")
PERSISTENCE_PROVIDERS = ("matrix", "slack", "line", "instagram")
PROOF_PROVIDERS = ("matrix", "slack")
MIN_CONNECTIVITY_MESSAGES = 1
MIN_VOLUME_MESSAGES = 50

@dataclass(frozen=True)
class Conversation:
    id: str
    title: str
    kind: str
    locator: dict[str, Any] = field(repr=False)

    def selection(self) -> dict[str, Any]:
        # Kept in Keychain or an encrypted DB payload, never a plaintext config.
        return {"id": self.id, "title": self.title, "kind": self.kind, "locator": self.locator}

    @classmethod
    def from_selection(cls, data: dict[str, Any]) -> Conversation:
        if not isinstance(data, dict) or not isinstance(data.get("locator"), dict):
            raise ValueError("invalid conversation selection")
        for key in ("id", "title", "kind"):
            if not isinstance(data.get(key), str) or not data[key]:
                raise ValueError("invalid conversation selection")
        return cls(data["id"], data["title"], data["kind"], data["locator"])

@dataclass(frozen=True)
class StoredConversation:
    provider: str
    account_id: str = field(repr=False)
    conversation: Conversation = field(repr=False)

    def __post_init__(self):
        if self.provider not in SUPPORTED_PROVIDERS or not isinstance(self.account_id, str) or not self.account_id:
            raise ValueError("invalid conversation account")
        Conversation.from_selection(self.conversation.selection())

    @property
    def id(self) -> str:
        fields = [self.provider, self.account_id, self.conversation.id]
        return sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class HistorySyncReceipt:
    """A committed bounded read, not a provider cursor or completeness claim."""
    provider: str
    account_id: str = field(repr=False)
    conversation_id: str = field(repr=False)
    completed_at: datetime
    requested_limit: int
    raw_items: int
    stored_messages: int
    excluded_events: int
    history_limited: bool

    def __post_init__(self):
        if self.provider not in PERSISTENCE_PROVIDERS:
            raise ValueError("invalid receipt provider")
        if not all(isinstance(v, str) and v for v in (self.account_id, self.conversation_id)):
            raise ValueError("invalid receipt scope")
        if (not isinstance(self.completed_at, datetime) or self.completed_at.tzinfo is None
                or self.completed_at.utcoffset() is None):
            raise ValueError("invalid receipt time")
        counts = (self.requested_limit, self.raw_items, self.stored_messages, self.excluded_events)
        if any(type(n) is not int or n < 0 for n in counts):
            raise ValueError("invalid receipt counts")
        if (not 1 <= self.requested_limit <= 100 or self.stored_messages > self.requested_limit
                or self.raw_items < self.stored_messages + self.excluded_events
                or type(self.history_limited) is not bool):
            raise ValueError("invalid receipt bounds")

    @property
    def id(self) -> str:
        fields = [self.provider, self.account_id, self.conversation_id]
        return sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class UnifiedMessage:
    provider: str
    account_id: str
    conversation_id: str
    provider_message_id: str
    sender_id: str
    sent_at: datetime
    text: str | None = field(repr=False)
    conversation_title: str = field(default="", repr=False)
    attachment_count: int = 0
    edited_at: datetime | None = None
    reply_to_message_id: str | None = None
    direction: str = "unknown"

    def __post_init__(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ValueError("unsupported provider")
        if not all(isinstance(v, str) and v for v in (self.account_id, self.conversation_id, self.provider_message_id, self.sender_id)):
            raise ValueError("invalid identity")
        if not isinstance(self.sent_at, datetime):
            raise ValueError("sent_at is required")
        for value in (self.sent_at, self.edited_at):
            if value is not None and (not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None):
                raise ValueError("timestamps must be timezone-aware")
        if self.text is not None and not isinstance(self.text, str):
            raise ValueError("invalid text")
        if not isinstance(self.attachment_count, int) or self.attachment_count < 0:
            raise ValueError("invalid attachment count")
        if self.direction not in {"incoming", "outgoing", "unknown"}:
            raise ValueError("invalid direction")

    @property
    def id(self) -> str:
        fields = [self.provider, self.account_id, self.conversation_id, self.provider_message_id]
        return sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()

    @property
    def sort_key(self) -> tuple:
        return (self.sent_at, self.provider, self.account_id, self.conversation_id, self.provider_message_id)

    def to_contract(self) -> dict[str, Any]:
        """In-memory handoff shape. The CLI does NOT write these bodies to disk."""
        return {
            "id": self.id, "provider": self.provider, "accountId": self.account_id,
            "conversationId": self.conversation_id, "providerMessageId": self.provider_message_id,
            "senderId": self.sender_id, "text": self.text, "sentAt": iso(self.sent_at),
            "editedAt": iso(self.edited_at) if self.edited_at else None,
            "replyToMessageId": self.reply_to_message_id,
            "direction": self.direction, "attachmentCount": self.attachment_count,
        }

@dataclass(frozen=True)
class SendResult:
    message: UnifiedMessage = field(repr=False)
    encrypted: bool


@dataclass
class FetchBatch:
    provider: str
    live: bool
    requested_limit: int
    messages: list[UnifiedMessage] = field(default_factory=list, repr=False)
    conversations_requested: int = 0
    conversations_fetched: int = 0
    raw_items: int = 0
    excluded_events: int = 0
    normalization_errors: int = 0
    duplicates_removed: int = 0
    history_limited: bool = False
    errors: list[str] = field(default_factory=list)
    conversations: list[StoredConversation] = field(default_factory=list, repr=False)


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def unique_latest(messages: list[UnifiedMessage], limit: int) -> tuple[list[UnifiedMessage], int]:
    unique: dict[str, UnifiedMessage] = {}
    for message in messages:
        old = unique.get(message.id)
        if old is None or (message.edited_at or message.sent_at) > (old.edited_at or old.sent_at):
            unique[message.id] = message
    ordered = sorted(unique.values(), key=lambda m: m.sort_key)
    return ordered[-limit:], len(messages) - len(unique)


def finish_batch(batch: FetchBatch) -> FetchBatch:
    batch.messages, count = unique_latest(batch.messages, batch.requested_limit)
    batch.duplicates_removed += count
    return batch


def make_report(batches: list[FetchBatch], *, demo: bool = False) -> dict[str, Any]:
    """Build two explicit gates.

    Gate A (loop_status): connectivity/integration proof. Two distinct live providers,
    at least one unique real message each, selected conversations fetched, and no
    fetch/normalization errors.

    Gate B (volume_loop_status): volume/pagination proof. Same requirements, plus
    at least MIN_VOLUME_MESSAGES unique messages from each provider.
    """
    by_provider = {batch.provider: batch for batch in batches}
    rows = []
    expected = tuple(PROOF_PROVIDERS)
    connectivity_complete = len(batches) == len(expected) and set(by_provider) == set(expected) and not demo
    volume_complete = connectivity_complete

    # Include single-provider fetch/sync diagnostics without changing Gate A/B.
    for provider in dict.fromkeys((*expected, *by_provider)):
        batch = by_provider.get(provider)
        if batch is None:
            connectivity_complete = False
            volume_complete = False
            rows.append({
                "provider": provider,
                "status": "NOT_RUN",
                "volume_status": "NOT_RUN",
                "real_messages": 0,
            })
            continue

        distinct = {m.id for m in batch.messages}
        valid_provenance = all(m.provider == provider for m in batch.messages)
        connectivity_enough = len(distinct) >= MIN_CONNECTIVITY_MESSAGES
        volume_enough = len(distinct) >= MIN_VOLUME_MESSAGES
        common_ok = (
            batch.live
            and valid_provenance
            and not batch.errors
            and batch.normalization_errors == 0
            and batch.conversations_requested > 0
            and batch.conversations_fetched == batch.conversations_requested
        )
        connectivity_ok = common_ok and connectivity_enough
        volume_ok = common_ok and volume_enough
        connectivity_complete = connectivity_complete and connectivity_ok
        volume_complete = volume_complete and volume_ok

        if demo or not batch.live:
            status = "DEMO_NOT_EVIDENCE"
        elif "CREDENTIALS_MISSING" in batch.errors:
            status = "BLOCKED_BY_USER_CREDENTIALS"
        elif "NO_SELECTION" in batch.errors:
            status = "BLOCKED_BY_USER_SELECTION"
        elif batch.errors:
            status = "FAILED"
        elif batch.normalization_errors or not valid_provenance:
            status = "NORMALIZATION_FAILED"
        elif not connectivity_enough:
            status = "NO_REAL_MESSAGES"
        elif not connectivity_ok:
            status = "INCOMPLETE"
        else:
            status = "PASS"

        if status != "PASS":
            volume_status = status
        elif volume_enough:
            volume_status = "PASS"
        else:
            volume_status = "INSUFFICIENT_MESSAGES"

        ordered = sorted(batch.messages, key=lambda m: m.sort_key)
        rows.append({
            "provider": provider,
            "status": status,
            "volume_status": volume_status,
            "requested_limit": batch.requested_limit,
            "normalized_unique_messages": len(distinct),
            "real_messages": len(distinct) if batch.live and not demo else 0,
            "conversations_requested": batch.conversations_requested,
            "conversations_fetched": batch.conversations_fetched,
            "raw_items": batch.raw_items,
            "excluded_events": batch.excluded_events,
            "duplicates_removed": batch.duplicates_removed,
            "normalization_errors": batch.normalization_errors,
            "history_limited": batch.history_limited,
            "oldest": iso(ordered[0].sent_at) if ordered else None,
            "newest": iso(ordered[-1].sent_at) if ordered else None,
            "error_codes": batch.errors,
        })

    return {
        "schema_version": 2,
        "application": "BeeperLocalPoC",
        "generated_at": iso(datetime.now(timezone.utc)),
        "mode": "DEMO" if demo else "LIVE_ATTEMPT",
        "loop_status": "DEMO_NOT_EVIDENCE" if demo else ("CLOSED" if connectivity_complete else "OPEN"),
        "volume_loop_status": "DEMO_NOT_EVIDENCE" if demo else ("CLOSED" if volume_complete else "OPEN"),
        "acceptance": "Gate A: 2 distinct live providers; >=1 unique real message EACH; selected conversations fetched; no normalization or fetch errors",
        "volume_acceptance": f"Gate B: Gate A plus >={MIN_VOLUME_MESSAGES} unique messages EACH for volume/pagination evidence",
        "scope": "Bounded history-read + normalization + chronological merge only. Not full sync, send, security audit, or desktop MVP acceptance.",
        "providers": rows,
    }
