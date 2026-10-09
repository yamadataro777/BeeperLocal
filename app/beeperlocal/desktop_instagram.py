"""Instagram desktop scope; reuse the user's verified Keychain and encrypted store."""
from __future__ import annotations

import asyncio
import time
from contextlib import aclosing
from datetime import datetime, timezone
from pathlib import Path

from .connectors.instagram import InstagramConnector
from .credentials import MacKeychain, MacLocalKeyStore
from .desktop import DesktopCore
from .errors import AppError
from .models import HistorySyncReceipt
from .storage import EncryptedMessageStore, db_exists
from .receiver_retry import wait_for_retry

IG_SERVICE = "BeeperLocalInstagramIntegration.v1"
IG_STATE_DIR = Path.home() / "Library" / "Application Support" / "BeeperLocalInstagramIntegration"


def open_instagram_store():
    path = IG_STATE_DIR / "messages-v1.sqlite3"
    keys = MacLocalKeyStore(service=IG_SERVICE)
    return EncryptedMessageStore(keys.load() if db_exists(path) else keys.load_or_create(), path)


class InstagramDesktop(DesktopCore):
    provider = "instagram"
    settings_key = "desktop.instagram.settings.v1"
    grants_key = "desktop.instagram.mcp-clients.v1"
    default_mcp_port = 28644  # 28643 is the Slack OAuth callback.
    history_limit = 20  # Per-page provider limit; older pages have resumable cursors.
    send_unknown = "IG_SEND_UNKNOWN"
    sent_not_stored = "IG_SENT_NOT_STORED"
    reconnect_interval = 60

    def __init__(self, *, credentials=None, db_factory=open_instagram_store,
                 connector_factory=InstagramConnector, emit=None):
        super().__init__(credentials=credentials, db_factory=db_factory,
                         connector_factory=connector_factory, emit=emit)

    def _initialize(self):
        if not self.started and self.credentials is None:
            self.credentials = MacKeychain(service=IG_SERVICE)
        super()._initialize()

    async def dispatch(self, request):
        allowed = {"ping", "snapshot", "connect", "select", "messages", "refresh",
                   "stop", "search", "send", "send_image", "storage_pause", "management", "storage_delete_preview", "storage_delete",
                   "messages_older", "mark_read", "history_backfill", "attachment_media", "avatar",
                   "mcp_configure", "mcp_register", "mcp_revoke"}
        if not isinstance(request, dict) or request.get("op") not in allowed:
            raise AppError("INVALID_INPUT")
        if request.get("op") == "storage_pause":
            if set(request) != {"op", "paused"}:
                raise AppError("INVALID_INPUT")
            self._initialize()
            await self.pause_storage(request["paused"])
            return self.snapshot()
        try:
            return await super().dispatch(request)
        except AppError as exc:
            if exc.code in {"CREDENTIALS_MISSING", "CREDENTIALS_INVALID"}:
                raise AppError("IG_LOGIN_REQUIRED") from None
            raise

    def management(self):
        # pause_storage uses this hook, without invoking LINE-specific accounting.
        return super().management()

    def snapshot(self):
        return {**super().snapshot(), "catalogLimited": bool(getattr(self.connector, 'catalog_limited', False))}

    async def select_remote(self, conversation):
        await self.connector.select_conversation(conversation)

    def persist_history(self, batch):
        if (batch.provider != self.provider or not batch.live or batch.errors
                or batch.normalization_errors or batch.conversations_requested != 1
                or batch.conversations_fetched != 1 or len(batch.conversations) != 1):
            raise AppError("BAD_RESPONSE")
        record = batch.conversations[0]
        expected = (self.provider, self.account_id, self._record(self.selected_id).conversation.id)
        if ((record.provider, record.account_id, record.conversation.id) != expected
                or any((m.provider, m.account_id, m.conversation_id) != expected for m in batch.messages)):
            raise AppError("BAD_RESPONSE")
        try:
            receipt = HistorySyncReceipt(*expected, completed_at=datetime.now(timezone.utc),
                requested_limit=batch.requested_limit, raw_items=batch.raw_items,
                stored_messages=len(batch.messages), excluded_events=batch.excluded_events,
                history_limited=True)
        except (ValueError, TypeError):
            raise AppError("BAD_RESPONSE") from None
        return receipt, self.db.upsert(batch.messages, conversations=[record], sync_receipts=[receipt])

    def start_watch(self):
        if self.supports_all_sync():
            self.start_all_sync()
        if not self.selected_id:
            return
        self.watch_generation += 1
        self.receiving = "starting"
        self.retry_attempt = 0
        self.watch_task = asyncio.create_task(self._watch(self.watch_generation, self.selected_id))

    async def _watch(self, generation, identity):
        attempts = 0
        connected_at = None
        all_conversations = self.supports_all_sync()

        def current():
            if generation != self.watch_generation or (not all_conversations and identity != self.selected_id):
                raise AppError("CONVERSATION_CHANGED")
            self.require_storage()

        def save(batch):
            current()
            self.persist_history(batch)  # Commit before the adapter's history_saved acknowledgement.
            self._notify("messages_changed", conversationId=identity)

        def status(value):
            nonlocal connected_at, attempts
            current()
            if value == "connected":
                connected_at = time.monotonic()
                self.retry_attempt = 0
            else:
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    attempts = 0
                connected_at = None
            self.receiving = "waiting" if value == "connected" else "reconnecting"
            self.error_code = None
            self._notify("status", **self._status())

        def change(conversation, event):
            current()
            record = next((r for r in self._records() if r.conversation.id == conversation.id), None)
            if record is None: return
            if event['action'] == 'delete':
                self.ingest([], records=[record], deletions=[(record, event['message_id'])])
            else:
                from hashlib import sha256
                from dataclasses import replace
                import json
                mid = sha256(json.dumps([self.provider,self.account_id,conversation.id,event['message_id']],separators=(',',':')).encode()).hexdigest()
                row = self.db.get_message(mid)
                if row is None: return
                try:
                    text = event['text']
                    edited = datetime.fromisoformat(event['edited_at'].replace('Z','+00:00'))
                    if not isinstance(text,str) or len(text.encode()) > 256*1024 or edited.tzinfo is None: raise ValueError()
                except (KeyError,TypeError,ValueError): raise AppError('BAD_RESPONSE') from None
                self.ingest([replace(row,text=text,edited_at=edited)],records=[record])
            self._notify('messages_changed',conversationId=record.id)

        while generation == self.watch_generation and not self.settings["storagePaused"]:
            try:
                # A fresh adapter reloads the current Keychain session and commits
                # a bounded history snapshot before resubscribing. No send is retried.
                extra = {"all_conversations": True, "on_change": change} if all_conversations else {}
                async with aclosing(self.connector.watch(timeout=0, from_now=all_conversations,
                        recovery_limit=self.history_limit, persist_history=save, on_status=status, **extra)) as stream:
                    async for message in stream:
                        current()
                        record = next((r for r in self._records() if r.conversation.id == message.conversation_id), None) if all_conversations else self._record(identity)
                        if record is None: continue
                        if ((message.provider, message.account_id, message.conversation_id)
                                != (self.provider, record.account_id, record.conversation.id)):
                            raise AppError("BAD_RESPONSE")
                        self.ingest([message], records=[record])
                        attempts = self.retry_attempt = 0
                        self._notify("messages_changed", conversationId=record.id)
                raise AppError("IG_REQUEST_FAILED")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if generation != self.watch_generation:
                    return
                code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
                if code in {"CREDENTIALS_MISSING", "CREDENTIALS_INVALID"}:
                    code = "IG_LOGIN_REQUIRED"
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    attempts = 0
                connected_at = None
                if code not in {"IG_REQUEST_FAILED", "IG_REQUEST_TIMEOUT", "NETWORK_ERROR"}:
                    self.receiving, self.error_code = "error", code
                    self._notify("status", **self._status())
                    return
                slow_retry = attempts >= len(self.retry_delays)
                delay = self.reconnect_interval if slow_retry else self.retry_delays[attempts]
                self.receiving, self.error_code = "reconnecting", "IG_RECONNECT_WAITING" if slow_retry else code
                self.retry_attempt = attempts + 1
                self._notify("status", **self._status())
                await wait_for_retry(delay)
                attempts += 1

    async def send(self, identity, text, request_id, **kwargs):
        # Each adapter instance refreshes cookies. Serialize send with watch so an older
        # session cannot overwrite a newer one. Resubscription recovers its latest page.
        await self.stop_watch()
        try:
            return await super().send(identity, text, request_id, **kwargs)
        finally:
            if self.connection == "connected" and self.selected_id and not self.settings["storagePaused"]:
                self.start_watch()
