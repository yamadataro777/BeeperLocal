"""Encrypted-at-rest local message persistence for the Phase-1 CLI.

This is intentionally not FTS. Message content and sensitive identifiers live inside
an AES-256-GCM encrypted payload. SQLite keeps only a stable message hash, provider,
and ordering timestamp in plaintext. Search decrypts bounded rows in memory.
"""
from __future__ import annotations

import base64
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import sqlite3
import stat
from typing import Iterable

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:  # pragma: no cover - mapped to a fixed diagnostic at runtime
    AESGCM = None
    InvalidTag = Exception

from .errors import AppError
from .models import Conversation, HistorySyncReceipt, StoredConversation, UnifiedMessage, iso
from .reporting import default_state_dir, private_directory
from .outbox import OutgoingRequest, request_key

DB_FILENAME = "messages-v1.sqlite3"
DB_SCHEMA_VERSION = 1
MAX_SEARCH_SCAN = 10_000


def default_db_path() -> Path:
    return default_state_dir() / DB_FILENAME


def db_exists(path: Path | None = None) -> bool:
    return (path or default_db_path()).exists()


def _parse_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value:
        raise ValueError("bad timestamp")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("naive timestamp")
    return dt


def _sent_at_micros(value: datetime) -> int:
    return int(value.astimezone(timezone.utc).timestamp() * 1_000_000)


def _key_fingerprint(key: bytes) -> str:
    return sha256(b"BeeperLocalPoC/local-db-key/v1\0" + key).hexdigest()


def _payload(message: UnifiedMessage) -> bytes:
    value = {
        "provider": message.provider,
        "account_id": message.account_id,
        "conversation_id": message.conversation_id,
        "provider_message_id": message.provider_message_id,
        "sender_id": message.sender_id,
        "sent_at": iso(message.sent_at),
        "text": message.text,
        "conversation_title": message.conversation_title,
        "attachment_count": message.attachment_count,
        "edited_at": iso(message.edited_at) if message.edited_at else None,
        "reply_to_message_id": message.reply_to_message_id,
        "direction": message.direction,
        "media": message.media,
        "attachments": message.attachments,
    }
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _message_from_payload(raw: bytes) -> UnifiedMessage:
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("bad payload")
    return UnifiedMessage(
        provider=value["provider"],
        account_id=value["account_id"],
        conversation_id=value["conversation_id"],
        provider_message_id=value["provider_message_id"],
        sender_id=value["sender_id"],
        sent_at=_parse_iso(value["sent_at"]),
        text=value.get("text"),
        conversation_title=value.get("conversation_title", ""),
        attachment_count=value.get("attachment_count", 0),
        edited_at=_parse_iso(value.get("edited_at")),
        reply_to_message_id=value.get("reply_to_message_id"),
        direction=value.get("direction", "unknown"),
        media=value.get("media"),
        attachments=value.get("attachments", []),
    )


class EncryptedMessageStore:
    def __init__(self, key: bytes, path: Path | None = None):
        if AESGCM is None:
            raise AppError("DEPENDENCY_MISSING")
        if not isinstance(key, bytes) or len(key) != 32:
            raise AppError("LOCAL_DB_KEY_INVALID")
        self.key = key
        self.aead = AESGCM(key)
        self.path = (path or default_db_path()).expanduser().absolute()
        private_directory(self.path.parent)
        if self.path.is_symlink():
            raise AppError("UNSAFE_PATH")
        for suffix in ("-journal", "-wal", "-shm"):
            sidecar = Path(str(self.path) + suffix)
            if sidecar.is_symlink():
                raise AppError("UNSAFE_PATH")
        self.conn = self._open()
        self._initialize()

    def _open(self) -> sqlite3.Connection:
        try:
            conn = sqlite3.connect(self.path, timeout=5.0)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA trusted_schema=OFF")
            if self.path.exists():
                self.path.chmod(0o600)
            return conn
        except (OSError, sqlite3.Error):
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    def _initialize(self) -> None:
        try:
            tables = {r[0] for r in self.conn.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if tables:
                self._validate_schema(tables)
            elif self.conn.execute("PRAGMA user_version").fetchone()[0] != 0:
                raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")
            # Validate an existing DB before changing its journal mode or any content.
            self.conn.execute("PRAGMA journal_mode=DELETE")
            self.conn.execute("PRAGMA synchronous=FULL")
            self.conn.execute("PRAGMA secure_delete=ON")
            self.conn.execute("PRAGMA temp_store=MEMORY")
            self.conn.execute("PRAGMA foreign_keys=ON")
            if not tables:
                self.conn.executescript("""
                    BEGIN;
                    CREATE TABLE meta (
                        key TEXT PRIMARY KEY, value TEXT NOT NULL
                    ) WITHOUT ROWID;
                    CREATE TABLE messages (
                        id TEXT PRIMARY KEY, provider TEXT NOT NULL,
                        sent_at_us INTEGER NOT NULL, ciphertext BLOB NOT NULL,
                        scope_id TEXT NOT NULL
                    ) WITHOUT ROWID;
                    CREATE INDEX messages_provider_time ON messages(provider, sent_at_us DESC);
                    CREATE INDEX messages_scope_time ON messages(scope_id, sent_at_us DESC, id DESC);
                    CREATE TABLE conversations (
                        id TEXT PRIMARY KEY, provider TEXT NOT NULL, ciphertext BLOB NOT NULL
                    ) WITHOUT ROWID;
                    CREATE TABLE sync_receipts (
                        id TEXT PRIMARY KEY, provider TEXT NOT NULL, ciphertext BLOB NOT NULL
                    ) WITHOUT ROWID;
                    CREATE TABLE outgoing_requests (
                        id TEXT PRIMARY KEY, provider TEXT NOT NULL, ciphertext BLOB NOT NULL
                    ) WITHOUT ROWID;
                    CREATE TABLE private_settings (
                        id TEXT PRIMARY KEY, ciphertext BLOB NOT NULL
                    ) WITHOUT ROWID;
                    CREATE TABLE retired_requests (id TEXT PRIMARY KEY) WITHOUT ROWID;
                    CREATE TABLE message_tombstones (
                        id TEXT PRIMARY KEY, provider TEXT NOT NULL, scope_id TEXT NOT NULL
                    ) WITHOUT ROWID;
                """)
                self.conn.executemany("INSERT INTO meta(key,value) VALUES(?,?)", [
                    ("key_fingerprint", _key_fingerprint(self.key)),
                    ("schema_version", str(DB_SCHEMA_VERSION)),
                ])
                self.conn.execute(f"PRAGMA user_version={DB_SCHEMA_VERSION}")
                self.conn.commit()
            if self.path.exists():
                self.path.chmod(0o600)
        except AppError:
            self.close()
            raise
        except sqlite3.DatabaseError:
            self.close()
            raise AppError("LOCAL_DB_CORRUPT") from None
        except (OSError, sqlite3.Error):
            self.close()
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    def _validate_schema(self, tables) -> None:
        columns = {
            "meta": {"key", "value"},
            "messages": {"id", "provider", "sent_at_us", "ciphertext", "scope_id"},
            "conversations": {"id", "provider", "ciphertext"},
            "sync_receipts": {"id", "provider", "ciphertext"},
            "outgoing_requests": {"id", "provider", "ciphertext"},
            "private_settings": {"id", "ciphertext"},
            "retired_requests": {"id"},
            "message_tombstones": {"id", "provider", "scope_id"},
        }
        if tables != columns.keys() or self.conn.execute("PRAGMA user_version").fetchone()[0] != DB_SCHEMA_VERSION:
            raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")
        for table, expected in columns.items():
            actual = {r["name"] for r in self.conn.execute(f"PRAGMA table_info({table})")}
            if actual != expected:
                raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")
        metadata = dict(self.conn.execute("SELECT key,value FROM meta"))
        if metadata.get("schema_version") != str(DB_SCHEMA_VERSION) or "key_fingerprint" not in metadata:
            raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")
        if metadata["key_fingerprint"] != _key_fingerprint(self.key):
            raise AppError("LOCAL_DB_KEY_MISMATCH")
        if self.conn.execute("SELECT 1 FROM messages WHERE scope_id IS NULL LIMIT 1").fetchone():
            raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def _encrypt(self, message: UnifiedMessage) -> bytes:
        nonce = os.urandom(12)
        aad = ("BeeperLocalPoC/message/v1/" + message.id).encode("ascii")
        return nonce + self.aead.encrypt(nonce, _payload(message), aad)

    def _decrypt(self, message_id: str, ciphertext: bytes) -> UnifiedMessage:
        if not isinstance(ciphertext, (bytes, bytearray)) or len(ciphertext) < 29:
            raise AppError("LOCAL_DB_CORRUPT")
        nonce, body = bytes(ciphertext[:12]), bytes(ciphertext[12:])
        aad = ("BeeperLocalPoC/message/v1/" + message_id).encode("ascii")
        try:
            raw = self.aead.decrypt(nonce, body, aad)
            message = _message_from_payload(raw)
            if message.id != message_id:
                raise ValueError("identity mismatch")
            return message
        except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError, json.JSONDecodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    def get_message(self, message_id):
        """Internal exact lookup; callers must enforce provider/account/conversation scope."""
        try:
            row = self.conn.execute("SELECT ciphertext FROM messages WHERE id=?", (message_id,)).fetchone()
            return self._decrypt(message_id, row[0]) if row else None
        except sqlite3.Error:
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    def _conversation_rows(self, conversations):
        rows = []
        for record in {c.id: c for c in conversations}.values():
            payload = json.dumps({"provider": record.provider, "account_id": record.account_id,
                                  "conversation": record.conversation.selection()},
                                 ensure_ascii=False, separators=(",", ":")).encode()
            nonce = os.urandom(12)
            aad = ("BeeperLocalPoC/conversation/v1/" + record.id).encode("ascii")
            rows.append((record.id, record.provider, nonce + self.aead.encrypt(nonce, payload, aad)))
        return rows

    def upsert_conversations(self, conversations: Iterable[StoredConversation]) -> None:
        self.upsert([], conversations=conversations)

    def list_conversations(self, *, provider=None, account_id=None) -> list[StoredConversation]:
        query = "SELECT id,provider,ciphertext FROM conversations"
        params = ()
        if provider:
            query += " WHERE provider=?"
            params = (provider,)
        try:
            records = []
            for row in self.conn.execute(query, params):
                blob = row["ciphertext"]
                aad = ("BeeperLocalPoC/conversation/v1/" + row["id"]).encode("ascii")
                raw = json.loads(self.aead.decrypt(blob[:12], blob[12:], aad))
                record = StoredConversation(raw["provider"], raw["account_id"], Conversation.from_selection(raw["conversation"]))
                if record.id != row["id"] or record.provider != row["provider"]:
                    raise ValueError()
                if account_id is None or record.account_id == account_id:
                    records.append(record)
            return sorted(records, key=lambda r: (r.provider, r.conversation.title, r.id))
        except (sqlite3.Error, InvalidTag, ValueError, TypeError, KeyError, UnicodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    @staticmethod
    def _message_scope(message):
        return sha256(json.dumps([message.provider, message.account_id, message.conversation_id],
                                 separators=(",", ":")).encode()).hexdigest()

    def list_messages(self, provider, account_id, conversation_id, *, limit=50, before=None):
        if not 1 <= limit <= 100:
            raise AppError("INVALID_INPUT")
        try:
            scope = sha256(json.dumps([provider, account_id, conversation_id], separators=(",", ":")).encode()).hexdigest()
            boundary = ""
            params = [scope]
            if before is not None:
                anchor = self.get_message(before)
                if anchor is None or (anchor.provider, anchor.account_id, anchor.conversation_id) != (provider, account_id, conversation_id):
                    raise AppError("INVALID_INPUT")
                boundary = " AND (sent_at_us<? OR (sent_at_us=? AND id<?))"
                stamp = _sent_at_micros(anchor.sent_at)
                params.extend([stamp, stamp, before])
            rows = self.conn.execute("SELECT id,ciphertext FROM messages WHERE scope_id=?" + boundary +
                                     " ORDER BY sent_at_us DESC,id DESC LIMIT ?", (*params, limit))
            messages = []
            for row in rows:
                message = self._decrypt(row["id"], row["ciphertext"])
                if message.account_id == account_id and message.conversation_id == conversation_id:
                    messages.append(message)
                    if len(messages) >= limit:
                        break
            return sorted(messages, key=lambda m: (m.sent_at, m.id))
        except sqlite3.Error:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def _sync_receipt_rows(self, receipts):
        rows = []
        for receipt in receipts:
            value = asdict(receipt)
            value["completed_at"] = iso(receipt.completed_at)
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            nonce = os.urandom(12)
            aad = ("BeeperLocalPoC/sync-receipt/v1/" + receipt.id).encode("ascii")
            rows.append((receipt.id, receipt.provider, nonce + self.aead.encrypt(nonce, payload, aad)))
        return rows

    def get_sync_receipt(self, conversation: StoredConversation) -> HistorySyncReceipt | None:
        try:
            row = self.conn.execute("SELECT provider,ciphertext FROM sync_receipts WHERE id=?",
                                    (conversation.id,)).fetchone()
            if row is None:
                return None
            blob = row["ciphertext"]
            if not isinstance(blob, bytes) or len(blob) < 29:
                raise ValueError()
            aad = ("BeeperLocalPoC/sync-receipt/v1/" + conversation.id).encode("ascii")
            value = json.loads(self.aead.decrypt(blob[:12], blob[12:], aad))
            value["completed_at"] = _parse_iso(value["completed_at"])
            receipt = HistorySyncReceipt(**value)
            if receipt.id != conversation.id or receipt.provider != row["provider"]:
                raise ValueError()
            return receipt
        except (sqlite3.Error, InvalidTag, ValueError, TypeError, KeyError, UnicodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    def _outgoing_rows(self, requests):
        rows = []
        for request in requests:
            value = asdict(request)
            value["created_at"] = iso(request.created_at)
            nonce = os.urandom(12)
            aad = ("BeeperLocalPoC/outgoing/v1/" + request.id).encode()
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
            rows.append((request.id, request.provider, nonce + self.aead.encrypt(nonce, payload, aad)))
        return rows

    def _decrypt_outgoing(self, row):
        try:
            blob = row["ciphertext"]
            aad = ("BeeperLocalPoC/outgoing/v1/" + row["id"]).encode()
            value = json.loads(self.aead.decrypt(blob[:12], blob[12:], aad))
            value["created_at"] = _parse_iso(value["created_at"])
            request = OutgoingRequest(**value)
            if request.id != row["id"] or request.provider != row["provider"]:
                raise ValueError()
            return request
        except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    def get_outgoing(self, request_id: str) -> OutgoingRequest | None:
        try:
            identity = request_key(request_id)
        except (ValueError, TypeError, AttributeError):
            raise AppError("INVALID_INPUT") from None
        try:
            row = self.conn.execute("SELECT * FROM outgoing_requests WHERE id=?", (identity,)).fetchone()
            return self._decrypt_outgoing(row) if row else None
        except sqlite3.Error:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def pending_outgoing(self, account_id: str, *, provider="line"):
        try:
            rows = self.conn.execute("SELECT * FROM outgoing_requests WHERE provider=?", (provider,))
            requests = [self._decrypt_outgoing(row) for row in rows]
            return [r for r in requests if r.account_id == account_id and r.status != "acknowledged"]
        except sqlite3.Error:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def recent_messages(self, *, provider: str, limit: int = MAX_SEARCH_SCAN):
        if type(limit) is not int or not 1 <= limit <= MAX_SEARCH_SCAN:
            raise AppError("INVALID_INPUT")
        try:
            rows = self.conn.execute("SELECT id,ciphertext FROM messages WHERE provider=? "
                                     "ORDER BY sent_at_us DESC,id DESC LIMIT ?", (provider, limit))
            return [self._decrypt(row["id"], row["ciphertext"]) for row in rows]
        except sqlite3.Error:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def _private_key(self, name: str) -> str:
        return sha256(("BeeperLocal/private-setting/v1/" + name).encode()).hexdigest()

    def private_get(self, name: str, default=None):
        identity = self._private_key(name)
        try:
            row = self.conn.execute("SELECT ciphertext FROM private_settings WHERE id=?", (identity,)).fetchone()
            if row is None:
                return default
            blob = row["ciphertext"]
            aad = ("BeeperLocal/private-setting/v1/" + identity).encode()
            value = json.loads(self.aead.decrypt(blob[:12], blob[12:], aad))
            if not isinstance(value, dict) or value.get("name") != name:
                raise ValueError()
            return value["value"]
        except (sqlite3.Error, InvalidTag, ValueError, TypeError, KeyError, UnicodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    def _private_put(self, name, value):
        identity = self._private_key(name)
        nonce = os.urandom(12)
        aad = ("BeeperLocal/private-setting/v1/" + identity).encode()
        payload = json.dumps({"name": name, "value": value}, ensure_ascii=False, separators=(",", ":")).encode()
        blob = nonce + self.aead.encrypt(nonce, payload, aad)
        self.conn.execute("INSERT INTO private_settings(id,ciphertext) VALUES(?,?) "
                          "ON CONFLICT(id) DO UPDATE SET ciphertext=excluded.ciphertext", (identity, blob))

    def private_put(self, name: str, value) -> None:
        try:
            with self.conn:
                self._private_put(name, value)
        except sqlite3.Error:
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    @staticmethod
    def _profile_index(provider, account):
        return 'profile-index.v1.' + sha256(json.dumps([provider, account], separators=(',', ':')).encode()).hexdigest()

    def profile_cache_put(self, provider, account, name, value):
        """Bounded encrypted raster cache, independently scoped to each account."""
        index = self._profile_index(provider, account)
        keys = self.private_get(index, [])
        if not isinstance(keys, list) or len(keys) > 128 or any(not isinstance(k, str) for k in keys):
            raise AppError('LOCAL_DB_CORRUPT')
        keys = [key for key in keys if key != name] + [name]
        try:
            with self.conn:
                self._private_put(name, value)
                for key in keys[:-128]:
                    self.conn.execute('DELETE FROM private_settings WHERE id=?', (self._private_key(key),))
                self._private_put(index, keys[-128:])
        except sqlite3.Error:
            raise AppError('LOCAL_DB_UNAVAILABLE') from None

    def request_retired(self, request_id: str) -> bool:
        try:
            identity = request_key(request_id)
            return self.conn.execute("SELECT 1 FROM retired_requests WHERE id=?", (identity,)).fetchone() is not None
        except (ValueError, TypeError, AttributeError):
            raise AppError("INVALID_INPUT") from None
        except sqlite3.Error:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def _provider_data_ids(self, provider, account_id):
        """Deletion is account-scoped and must not stop at the search scan limit."""
        try:
            messages = [row["id"] for row in self.conn.execute(
                "SELECT id,ciphertext FROM messages WHERE provider=?", (provider,))
                if self._decrypt(row["id"], row["ciphertext"]).account_id == account_id]
            conversations = [r.id for r in self.list_conversations(provider=provider, account_id=account_id)]
            outgoing = [row["id"] for row in self.conn.execute(
                "SELECT * FROM outgoing_requests WHERE provider=?", (provider,))
                if self._decrypt_outgoing(row).account_id == account_id]
            # Receipts normally have a catalog row; decode all to also remove orphaned receipts.
            receipts = []
            for row in self.conn.execute("SELECT id,ciphertext FROM sync_receipts WHERE provider=?", (provider,)):
                blob = row["ciphertext"]
                aad = ("BeeperLocalPoC/sync-receipt/v1/" + row["id"]).encode()
                value = json.loads(self.aead.decrypt(blob[:12], blob[12:], aad))
                value["completed_at"] = _parse_iso(value["completed_at"])
                receipt = HistorySyncReceipt(**value)
                if receipt.id != row["id"] or receipt.provider != provider:
                    raise ValueError()
                if receipt.account_id == account_id:
                    receipts.append(row["id"])
            return {"messages": messages, "conversations": conversations,
                    "sync_receipts": receipts, "outgoing_requests": outgoing,
                    "message_tombstones": [r["id"] for r in self.conn.execute(
                        "SELECT id,scope_id FROM message_tombstones WHERE provider=?", (provider,))
                        if r["scope_id"] in set(conversations)]}
        except (sqlite3.Error, InvalidTag, ValueError, TypeError, KeyError, UnicodeError):
            raise AppError("LOCAL_DB_CORRUPT") from None

    def line_data_counts(self, account_id):
        return self.provider_data_counts("line", account_id)

    def provider_data_counts(self, provider, account_id):
        return {name: len(ids) for name, ids in self._provider_data_ids(provider, account_id).items()}

    def clear_line_data(self, account_id, *, private_updates, expected_counts=None):
        return self.clear_provider_data("line", account_id, private_updates=private_updates,
                                        expected_counts=expected_counts)

    def clear_provider_data(self, provider, account_id, *, private_updates, expected_counts=None):
        """Atomically erase this account's content and revoke its grants.

        Shared session credentials, database key, and other providers/accounts stay intact.
        Only irreversible send-request hashes survive the content deletion.
        """
        try:
            with self.conn:
                self.conn.execute("BEGIN IMMEDIATE")
                identities = self._provider_data_ids(provider, account_id)
                if expected_counts is not None and {k: len(v) for k, v in identities.items()} != expected_counts:
                    raise AppError("DELETE_CONFIRMATION_EXPIRED")
                self.conn.executemany("INSERT OR IGNORE INTO retired_requests(id) VALUES(?)",
                                      [(i,) for i in identities["outgoing_requests"]])
                for table, ids in identities.items():
                    # Table names come solely from the fixed dictionary above.
                    self.conn.executemany(f"DELETE FROM {table} WHERE id=?", [(i,) for i in ids])
                for identity in identities['messages']:
                    self.conn.execute('DELETE FROM private_settings WHERE id=?', (self._private_key('image.v1.' + identity),))
                profile_index = self._profile_index(provider, account_id)
                for key in self.private_get(profile_index, []) + [profile_index]:
                    self.conn.execute('DELETE FROM private_settings WHERE id=?', (self._private_key(key),))
                # Per-conversation cursors/read state belong to deleted content.
                # Device registration markers and credentials must survive.
                for identity in identities["conversations"]:
                    for prefix in ("sync.v1.", "read.v1.", "delete.v1.", "x.history.", "profile.v1."):
                        self.conn.execute("DELETE FROM private_settings WHERE id=?",
                                          (self._private_key(prefix + identity),))
                for name, value in private_updates.items():
                    self._private_put(name, value)
            return {name: len(ids) for name, ids in identities.items()}
        except sqlite3.Error:
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    def upsert(self, messages: Iterable[UnifiedMessage], *, conversations=(), sync_receipts=(), outgoing_requests=(),
               private_updates=None, deletions=()) -> dict[str, int]:
        # Deletions carry a verified conversation and the provider's original message ID.
        deleted = list(deletions)
        deletion_rows = [(sha256(json.dumps([r.provider, r.account_id, r.conversation.id, mid], separators=(",", ":")).encode()).hexdigest(),
                          r.provider, r.id) for r, mid in deleted]
        deleted_ids = {row[0] for row in deletion_rows}
        values = [m for m in messages if m.id not in deleted_ids and not self.conn.execute(
            "SELECT 1 FROM message_tombstones WHERE id=?", (m.id,)).fetchone()]
        # Slack upload acknowledgements have a file id before their message ts
        # becomes visible. Merge only the same author's file in the same chat.
        provisional_ids = set()
        private_updates = dict(private_updates or {})
        for message in values:
            if message.provider != 'slack' or message.direction != 'outgoing' or message.provider_message_id.startswith('file:'):
                continue
            for attachment in message.attachments:
                fid = attachment.get('file_id')
                if not fid:
                    continue
                from dataclasses import replace
                identity = replace(message, provider_message_id='file:' + fid).id
                prior = self.get_message(identity)
                if prior is not None and prior.direction == 'outgoing' and prior.sender_id == message.sender_id:
                    provisional_ids.add(identity)
                    preview = self.private_get('image.v1.' + identity)
                    if preview:
                        private_updates.setdefault('image.v1.' + message.id, preview)
        conversation_values = list(conversations)
        receipts = list(sync_receipts)
        outgoing = list(outgoing_requests)
        if not values and not conversation_values and not receipts and not outgoing and not private_updates and not deleted:
            return {"processed": 0, "inserted": 0, "updated": 0}
        conversation_ids = {c.id for c in conversation_values}
        if (any(r.id not in conversation_ids for r in receipts)
                or len({r.id for r in receipts}) != len(receipts)):
            raise AppError("INVALID_INPUT")
        ids = [m.id for m in values]
        if len(set(ids)) != len(ids):
            # Caller should deduplicate first. Refuse ambiguity instead of silently picking a row.
            raise AppError("INVALID_INPUT")
        try:
            existing = set()
            for start in range(0, len(ids), 400):
                chunk = ids[start:start + 400]
                marks = ",".join("?" for _ in chunk)
                existing.update(r[0] for r in self.conn.execute(f"SELECT id FROM messages WHERE id IN ({marks})", chunk))
            rows = [(m.id, m.provider, _sent_at_micros(m.sent_at), self._encrypt(m), self._message_scope(m)) for m in values]
            conversation_rows = self._conversation_rows(conversation_values)
            receipt_rows = self._sync_receipt_rows(receipts)
            outgoing_rows = self._outgoing_rows(outgoing)
            with self.conn:
                for identity in provisional_ids:
                    self.conn.execute('DELETE FROM messages WHERE id=?', (identity,))
                    self.conn.execute('DELETE FROM private_settings WHERE id=?', (self._private_key('image.v1.' + identity),))
                self.conn.executemany("""INSERT INTO conversations(id,provider,ciphertext) VALUES(?,?,?)
                    ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,ciphertext=excluded.ciphertext""", conversation_rows)
                self.conn.executemany(
                    """
                    INSERT INTO messages(id,provider,sent_at_us,ciphertext,scope_id) VALUES(?,?,?,?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        provider=excluded.provider,
                        sent_at_us=excluded.sent_at_us,
                        ciphertext=excluded.ciphertext,
                        scope_id=excluded.scope_id
                    """,
                    rows,
                )
                self.conn.executemany("""INSERT INTO sync_receipts(id,provider,ciphertext) VALUES(?,?,?)
                    ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,ciphertext=excluded.ciphertext""",
                                      receipt_rows)
                self.conn.executemany("""INSERT INTO outgoing_requests(id,provider,ciphertext) VALUES(?,?,?)
                    ON CONFLICT(id) DO UPDATE SET provider=excluded.provider,ciphertext=excluded.ciphertext""",
                                      outgoing_rows)
                self.conn.executemany("INSERT OR IGNORE INTO message_tombstones(id,provider,scope_id) VALUES(?,?,?)", deletion_rows)
                self.conn.executemany("DELETE FROM messages WHERE id=?", [(row[0],) for row in deletion_rows])
                for row in deletion_rows:
                    self.conn.execute('DELETE FROM private_settings WHERE id=?', (self._private_key('image.v1.' + row[0]),))
                for name, value in (private_updates or {}).items():
                    self._private_put(name, value)
            return {"processed": len(values), "inserted": len(values) - len(existing), "updated": len(existing)}
        except AppError:
            raise
        except sqlite3.DatabaseError:
            raise AppError("LOCAL_DB_CORRUPT") from None
        except sqlite3.Error:
            raise AppError("LOCAL_DB_UNAVAILABLE") from None

    def count_by_provider(self) -> dict[str, int]:
        try:
            return {row["provider"]: int(row["n"]) for row in self.conn.execute(
                "SELECT provider, COUNT(*) AS n FROM messages GROUP BY provider ORDER BY provider"
            )}
        except sqlite3.DatabaseError:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def total_count(self) -> int:
        try:
            return int(self.conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0])
        except sqlite3.DatabaseError:
            raise AppError("LOCAL_DB_CORRUPT") from None

    def search(self, query: str, *, provider: str | None = None, limit: int = 20,
               scan_limit: int = MAX_SEARCH_SCAN) -> tuple[list[UnifiedMessage], int]:
        needle = query.strip().casefold()
        if not needle or len(needle) > 500 or not 1 <= limit <= 100 or not 1 <= scan_limit <= MAX_SEARCH_SCAN:
            raise AppError("INVALID_INPUT")
        sql = "SELECT id,ciphertext FROM messages"
        params: list[object] = []
        if provider:
            sql += " WHERE provider=?"
            params.append(provider)
        sql += " ORDER BY sent_at_us DESC LIMIT ?"
        params.append(scan_limit)
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except sqlite3.DatabaseError:
            raise AppError("LOCAL_DB_CORRUPT") from None
        results: list[UnifiedMessage] = []
        for row in rows:
            message = self._decrypt(row["id"], row["ciphertext"])
            haystack = "\n".join((message.text or "", message.conversation_title, message.sender_id)).casefold()
            if needle in haystack:
                results.append(message)
                if len(results) >= limit:
                    break
        return results, len(rows)


def delete_database_files(path: Path | None = None) -> int:
    target = (path or default_db_path()).expanduser().absolute()
    private_directory(target.parent)
    removed = 0
    for candidate in [target, Path(str(target) + "-journal"), Path(str(target) + "-wal"), Path(str(target) + "-shm")]:
        if candidate.is_symlink():
            raise AppError("UNSAFE_PATH")
        if candidate.exists():
            try:
                info = candidate.lstat()
                if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
                    raise AppError("UNSAFE_PATH")
                candidate.unlink()
                removed += 1
            except AppError:
                raise
            except OSError:
                raise AppError("LOCAL_DB_UNAVAILABLE") from None
    return removed
