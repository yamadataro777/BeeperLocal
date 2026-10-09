"""X desktop scope: verified history, private onboarding and durable GUI sends."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
from pathlib import Path
import time

from .connectors.x import XAdapter, XConnector, decimal
from .credentials import MacKeychain, MacLocalKeyStore
from .desktop import DesktopCore
from .errors import AppError
from .models import HistorySyncReceipt
from .storage import EncryptedMessageStore, db_exists
from .receiver_retry import wait_for_retry

X_SERVICE = "BeeperLocalXIntegration.v1"
X_STATE_DIR = Path.home() / "Library" / "Application Support" / "BeeperLocalXIntegration"


def open_x_store():
    path = X_STATE_DIR / "messages-v1.sqlite3"
    keys = MacLocalKeyStore(service=X_SERVICE)
    return EncryptedMessageStore(keys.load() if db_exists(path) else keys.load_or_create(), path)


class XDesktop(DesktopCore):
    async def clear_provider_cache(self):
        candidate = self.connector or self.connector_factory(self.credentials)
        result = await candidate._request('clear_local')
        if result.get('cleared') is not True:
            raise AppError('LOCAL_DB_UNAVAILABLE')

    provider = "x"
    settings_key = "desktop.x.settings.v1"
    grants_key = "desktop.x.mcp-clients.v1"
    default_mcp_port = 28645
    history_limit = 100
    send_unknown = "X_SEND_UNKNOWN"
    sent_not_stored = "X_SENT_NOT_STORED"

    def __init__(self, *, credentials=None, db_factory=open_x_store,
                 connector_factory=XConnector, login_adapter_factory=XAdapter, emit=None):
        super().__init__(credentials=credentials, db_factory=db_factory,
                         connector_factory=connector_factory, emit=emit)
        self.login_adapter_factory = login_adapter_factory

    def _initialize(self):
        if not self.started and self.credentials is None:
            self.credentials = MacKeychain(service=X_SERVICE)
        super()._initialize()

    def require_no_login(self):
        if self.login_active():
            raise AppError("X_LOGIN_IN_PROGRESS")

    def set_login_state(self, **state):
        self.login_state = state  # Stages/codes only; cookies and PIN stay in the worker.
        self._notify("x_login_changed")

    async def start_x_login(self, unlock_only):
        if type(unlock_only) is not bool:
            raise AppError("INVALID_INPUT")
        self.require_no_login()
        self.require_storage()
        async with self.operation_lock:
            self.require_storage()
            await self.stop_watch()
            self.connection, self.error_code = "offline", None
            self.set_login_state(stage="starting")
            self.login_task = asyncio.create_task(self._run_x_login(unlock_only))
        self._notify("status", **self._status())
        return self.login_state

    async def _run_x_login(self, unlock_only):
        try:
            adapter = self.login_adapter_factory()
            request = {"op": "unlock" if unlock_only else "login", "account_id": self.account_id}
            completed = False
            async with aclosing(adapter.events(request)) as events:
                async for event in events:
                    if event["type"] == "auth_status" and event.get("stage") in {"web", "pin"}:
                        self.set_login_state(stage=event["stage"])
                    elif event["type"] == "result":
                        account = decimal(event.get("account_id"))
                        if self.account_id and account != self.account_id:
                            raise AppError("ACCOUNT_CHANGED")
                        try:
                            old = self.credentials.load("x")
                        except AppError as exc:
                            if exc.code != "CREDENTIALS_MISSING":
                                raise
                            old = {}
                        if old.get("account_id") not in {None, account}:
                            raise AppError("ACCOUNT_CHANGED")
                        self.credentials.save("x", {"account_id": account, "selections": old.get("selections", [])})
                        self.account_id, self.connector = account, None
                        completed = True
                    else:
                        raise AppError("X_PROTOCOL_ERROR")
            if not completed:
                raise AppError("X_LOGIN_FAILED")
            self.set_login_state(stage="completed")
        except asyncio.CancelledError:
            self.set_login_state(stage="cancelled")
            raise
        except Exception as exc:
            self.set_login_state(stage="failed", errorCode=exc.code if isinstance(exc, AppError) else "X_LOGIN_FAILED")

    async def dispatch(self, request):
        allowed = {"ping", "snapshot", "connect", "select", "messages", "refresh", "stop", "search", "send", "send_image",
                   "storage_pause", "x_login_start", "x_login_status", "x_login_cancel",
                   "management", "storage_delete_preview", "storage_delete", "messages_older", "mark_read", "history_backfill", "attachment_media",
                   "mcp_configure", "mcp_register", "mcp_revoke"}
        if not isinstance(request, dict) or request.get("op") not in allowed:
            raise AppError("INVALID_INPUT")
        operation = request["op"]
        if operation in {"storage_pause", "x_login_start", "x_login_status", "x_login_cancel"}:
            fields = {"paused"} if operation == "storage_pause" else {"unlockOnly"} if operation == "x_login_start" else set()
            if set(request) != {"op"} | fields:
                raise AppError("INVALID_INPUT")
            self._initialize()
            if operation == "x_login_start":
                return await self.start_x_login(request["unlockOnly"])
            if operation == "x_login_status":
                return self.login_state
            if operation == "x_login_cancel":
                return await self.cancel_login()
            await self.pause_storage(request["paused"])
            return self.snapshot()
        return await super().dispatch(request)

    def management(self):
        return super().management()

    def snapshot(self):
        return {**super().snapshot(), "catalogLimited": self.connector.catalog_limited if self.connector else True}

    def messages(self, identity, before=None):
        details = self.db.private_get("x.history." + identity) or {}
        result = super().messages(identity, before=before)
        record = self._record(identity)
        rows = self.db.list_messages(self.provider, self.account_id, record.conversation.id, limit=100, before=before)
        return {**result, "unsupportedLegacyCount": details.get("legacy", 0),
                "legacyMessageCount": sum(m.provider_message_id.startswith("legacy:") for m in rows)}

    async def select_remote(self, conversation):
        await self.connector.select_conversation(conversation)

    def persist_history(self, batch):
        if (batch.provider != "x" or not batch.live or batch.errors or batch.normalization_errors
                or batch.conversations_requested != 1 or batch.conversations_fetched != 1
                or len(batch.conversations) != 1):
            raise AppError("BAD_RESPONSE")
        record = batch.conversations[0]
        expected = ("x", self.account_id, self._record(self.selected_id).conversation.id)
        if ((record.provider, record.account_id, record.conversation.id) != expected
                or any((m.provider, m.account_id, m.conversation_id) != expected for m in batch.messages)):
            raise AppError("BAD_RESPONSE")
        try:
            receipt = HistorySyncReceipt(*expected, completed_at=datetime.now(timezone.utc),
                requested_limit=batch.requested_limit, raw_items=batch.raw_items,
                stored_messages=len(batch.messages), excluded_events=batch.excluded_events,
                history_limited=batch.history_limited)
        except (TypeError, ValueError):
            raise AppError("BAD_RESPONSE") from None
        stats = self.db.upsert(batch.messages, conversations=[record], sync_receipts=[receipt])
        self.db.private_put("x.history." + record.id, {"legacy": self.connector.unsupported_legacy_count,
                                                                    "legacy_text": self.connector.legacy_message_count})
        return receipt, stats

    def start_watch(self):
        if self.supports_all_sync():
            self.start_all_sync()
            return
        self.watch_generation += 1
        self.receiving, self.retry_attempt = "starting", 0
        self.watch_task = asyncio.create_task(self._watch(self.watch_generation, self.selected_id))

    async def _watch(self, generation, identity):
        attempts, connected_at = 0, None
        def current():
            if generation != self.watch_generation or identity != self.selected_id:
                raise AppError("CONVERSATION_CHANGED")
            self.require_storage()
        def save(batch):
            current()
            self.persist_history(batch)
            self._notify("messages_changed", conversationId=identity)
        def status(value):
            nonlocal connected_at
            current()
            if value != "connected":
                raise AppError("X_PROTOCOL_ERROR")
            connected_at = time.monotonic()
            self.receiving, self.retry_attempt, self.error_code = "waiting", 0, None
            self._notify("status", **self._status())
        while generation == self.watch_generation and not self.settings["storagePaused"]:
            try:
                async with aclosing(self.connector.watch(timeout=0, recovery_limit=self.history_limit,
                        persist_history=save, on_status=status)) as stream:
                    async for _ in stream:
                        raise AppError("X_PROTOCOL_ERROR")
                raise AppError("X_REQUEST_FAILED")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if generation != self.watch_generation:
                    return
                code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    attempts = 0
                connected_at = None
                if code not in {"X_REQUEST_FAILED", "X_REQUEST_TIMEOUT", "NETWORK_ERROR"}:
                    self.receiving, self.error_code = "error", code
                    self._notify("status", **self._status())
                    return
                if attempts >= len(self.retry_delays):
                    self.receiving, self.error_code = "error", "SYNC_RETRY_EXHAUSTED"
                    self._notify("status", **self._status())
                    return
                self.receiving, self.error_code, self.retry_attempt = "reconnecting", code, attempts + 1
                self._notify("status", **self._status())
                await wait_for_retry(self.retry_delays[attempts])
                attempts += 1

    async def send(self, identity, text, request_id, **kwargs):
        await self.stop_watch()
        try:
            return await super().send(identity, text, request_id, **kwargs)
        finally:
            if self.connection == "connected" and self.selected_id and not self.settings["storagePaused"]:
                self.start_watch()
