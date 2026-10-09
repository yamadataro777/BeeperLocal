"""Messenger E2EE inbox, durable local history and native account login."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from hashlib import sha256
import time

from .credentials import MacKeychain, MacLocalKeyStore
from .desktop import DesktopCore
from .errors import AppError
from .messenger import MessengerSession, SERVICE, STATE_DIR, normalize_checkpoint
from .storage import EncryptedMessageStore, db_exists
from .receiver_retry import wait_for_retry


def open_messenger_store():
    path = STATE_DIR / "messages-v1.sqlite3"
    keys = MacLocalKeyStore(service=SERVICE)
    return EncryptedMessageStore(keys.load() if db_exists(path) else keys.load_or_create(), path)


class MessengerDesktop(DesktopCore):
    provider = "messenger"
    settings_key = "desktop.messenger.settings.v1"
    grants_key = "desktop.messenger.mcp-clients.v1"
    default_mcp_port = 28646
    send_unknown = "MESSENGER_SEND_UNKNOWN"
    sent_not_stored = "MESSENGER_SENT_NOT_STORED"

    def __init__(self, *, credentials=None, db_factory=open_messenger_store,
                 session_factory=MessengerSession, emit=None):
        super().__init__(credentials=credentials, db_factory=db_factory, emit=emit)
        self.session_factory = session_factory

    def _initialize(self):
        already_started = self.started
        if not self.started and self.credentials is None:
            self.credentials = MacKeychain(service=SERVICE)
        super()._initialize()
        registered = self.db.private_get("messenger.registered_account")
        if registered is not None:
            if not isinstance(registered, str) or not registered.isdecimal():
                raise AppError("LOCAL_DB_CORRUPT")
            if self.account_id and registered != self.account_id:
                raise AppError("ACCOUNT_CHANGED")
            # Losing metadata must not make a previously registered device look new.
            self.account_id = registered
        if not already_started and self.account_id:
            key = self._selection_key()
            selected = self.db.private_get(key)
            if selected is not None and not isinstance(selected, str):
                raise AppError('LOCAL_DB_CORRUPT')
            self.selected_id = selected if selected in {r.id for r in self._records()} else None

    def _selection_key(self):
        return 'desktop.messenger.selected.' + sha256(self.account_id.encode()).hexdigest()

    def management(self):
        return super().management()

    def require_no_login(self):
        if self.login_active():
            raise AppError("MESSENGER_LOGIN_IN_PROGRESS")

    def set_login_state(self, **state):
        self.login_state = state
        self._notify("messenger_login_changed")

    def snapshot(self):
        return {**super().snapshot(), "catalogLimited": True, "receiveOnly": False}

    def _current_records(self):
        # Device-delivered inbox plus cached mapped threads; never claim full history/catalog.
        return self._records()

    def _set_account(self, account):
        if self.account_id and self.account_id != account:
            raise AppError("ACCOUNT_CHANGED")
        if self.account_id == account:
            return
        self.credentials.save(self.provider, {"account_id": account, "selections": []})
        self.account_id = account

    def _persist(self, event, account):
        self.require_storage()
        if self.account_id and self.account_id != account:
            raise AppError("ACCOUNT_CHANGED")
        messages, records = normalize_checkpoint(event, account, self.db.list_conversations(provider=self.provider, account_id=account))
        self._set_account(account)
        # Sender-authenticated revokes are retained until the corresponding body arrives.
        deleted = event.get('deletions') or []
        if not isinstance(deleted, list) or len(deleted) > 200: raise AppError('MESSENGER_PROTOCOL_ERROR')
        all_records = {r.conversation.id:r for r in self.db.list_conversations(provider=self.provider, account_id=account)}
        all_records.update({r.conversation.id:r for r in records})
        private, targets = {}, []
        from .messenger import JID
        from hashlib import sha256
        import json
        for item in deleted:
            if (not isinstance(item,dict) or not isinstance(item.get('conversation'),str) or not JID.fullmatch(item['conversation'])
                    or not isinstance(item.get('id'),str) or not 1 <= len(item['id']) <= 4096
                    or item.get('sender') not in {account+'@msgr',item['conversation']}):
                raise AppError('MESSENGER_PROTOCOL_ERROR')
            if item['conversation'] not in all_records: continue
            record = all_records[item['conversation']]
            key = 'delete.v1.' + record.id
            rules = private.setdefault(key, self.db.private_get(key, {}))
            rules[item['id']] = item['sender']
            if len(rules) > 100000: raise AppError('MESSENGER_PROTOCOL_ERROR')
        for record in all_records.values():
            key = 'delete.v1.' + record.id
            rules = private.get(key, self.db.private_get(key, {}))
            by_id = {m.provider_message_id:m for m in messages if m.conversation_id == record.conversation.id}
            for mid, actor in rules.items():
                local_id = sha256(json.dumps([self.provider,account,record.conversation.id,mid],separators=(',',':')).encode()).hexdigest()
                row = by_id.get(mid) or self.db.get_message(local_id)
                if row and row.sender_id == actor: targets.append((record,mid))
        touched = {r.id:r for r in records}
        touched.update({r.id:r for r,_ in targets})
        self.ingest(messages, records=touched.values(), historical=self.connection != 'connected', private_updates=private, deletions=targets)
        state = event.get("state", {})
        if state.get("device_db") and not state.get("registration_pending"):
            self.db.private_put("messenger.registered_account", account)
        if messages or records or targets:
            self._notify("messages_changed", conversationId=self.selected_id)

    async def connect(self):
        self.require_no_login()
        self.require_storage()
        await self.stop_watch()
        self.connection, self.receiving, self.error_code = "connecting", "starting", None
        self._notify("status", **self._status())
        ready = asyncio.get_running_loop().create_future()
        self.watch_generation += 1
        self.watch_task = asyncio.create_task(self._watch(self.watch_generation, ready))
        try:
            await asyncio.wait_for(asyncio.shield(ready), 150)
        except TimeoutError:
            await self.stop_watch()
            if not ready.done():
                ready.cancel()
            self.connection, self.error_code = "error", "MESSENGER_CONNECTION_LOST"
            raise AppError(self.error_code) from None
        except asyncio.CancelledError:
            await self.stop_watch()
            raise
        return self.snapshot()

    async def _watch(self, generation, ready):
        attempts, connected_at = 0, None
        while generation == self.watch_generation and not self.settings["storagePaused"]:
            try:
                session = self.session_factory()
                async with aclosing(session.watch(self._persist, account=self.account_id,
                        require_device=self.db.private_get("messenger.registered_account") is not None)) as stream:
                    async for status in stream:
                        if generation != self.watch_generation:
                            return
                        if status != "connected":
                            raise AppError("MESSENGER_PROTOCOL_ERROR")
                        self.connector = MessengerSender(self, session)
                        self.connection, self.receiving, self.error_code, self.retry_attempt = "connected", "waiting", None, 0
                        connected_at = time.monotonic()
                        self._notify("status", **self._status())
                        if not ready.done():
                            ready.set_result(True)
                raise AppError("MESSENGER_CONNECTION_LOST")
            except asyncio.CancelledError:
                if not ready.done():
                    ready.cancel()
                raise
            except Exception as exc:
                if generation != self.watch_generation:
                    return
                code = exc.code if isinstance(exc, AppError) else "MESSENGER_PROTOCOL_ERROR"
                if not ready.done():
                    ready.set_exception(AppError(code))
                    self.connection, self.receiving, self.error_code = "error", "error", code
                    self._notify("status", **self._status())
                    return
                if code != "MESSENGER_CONNECTION_LOST":
                    self.connection, self.receiving, self.error_code = "error", "error", code
                    self._notify("status", **self._status())
                    return
                if connected_at is not None and time.monotonic() - connected_at >= 60:
                    attempts = 0
                connected_at = None
                delay = self.retry_delays[min(attempts, len(self.retry_delays) - 1)] if attempts < len(self.retry_delays) else 60
                attempts += 1
                self.connection, self.receiving, self.error_code, self.retry_attempt = "connecting", "reconnecting", code, attempts
                self._notify("status", **self._status())
                await wait_for_retry(delay)

    async def select(self, identity):
        record = self._record(identity)
        # UI selection is not an authentication update. Keep it in encrypted
        # SQLite so opening another chat never invokes macOS Keychain access.
        if self.db.private_get(self._selection_key()) != record.id:
            self.db.private_put(self._selection_key(), record.id)
        self.selected_id = record.id
        return self.messages(identity)

    async def refresh(self):
        # Reconnect restores the device and collects messages still delivered to it.
        # It is not a request to restore Meta's encrypted history backup.
        return await self.connect()

    async def start_messenger_login(self):
        self.require_no_login()
        self.require_storage()
        async with self.operation_lock:
            await self.stop_watch()
            self.connection, self.error_code = "offline", None
            self.set_login_state(stage="web")
            self.login_task = asyncio.create_task(self._run_login())
        self._notify("status", **self._status())
        return self.login_state

    async def _run_login(self):
        try:
            account = await self.session_factory().login(self.account_id,
                require_device=self.db.private_get("messenger.registered_account") is not None)
            self._set_account(account)
            self.set_login_state(stage="completed")
        except asyncio.CancelledError:
            self.set_login_state(stage="cancelled")
            raise
        except Exception as exc:
            self.set_login_state(stage="failed", errorCode=exc.code if isinstance(exc, AppError) else "MESSENGER_PROTOCOL_ERROR")

    async def dispatch(self, request):
        allowed = {"ping", "snapshot", "connect", "select", "messages", "refresh", "stop", "search",
                   "send", "send_image", "attachment_media", "storage_pause", "messenger_login_start", "messenger_login_status", "messenger_login_cancel",
                   "management", "storage_delete_preview", "storage_delete", "messages_older", "mark_read", "history_backfill",
                   "mcp_configure", "mcp_register", "mcp_revoke"}
        if not isinstance(request, dict) or request.get("op") not in allowed:
            raise AppError("INVALID_INPUT")
        op = request["op"]
        if op.startswith("messenger_login_") or op == "storage_pause":
            if set(request) != ({"op", "paused"} if op == "storage_pause" else {"op"}):
                raise AppError("INVALID_INPUT")
            self._initialize()
            if op == "messenger_login_start":
                return await self.start_messenger_login()
            if op == "messenger_login_status":
                return self.login_state
            if op == "messenger_login_cancel":
                return await self.cancel_login()
            await self.pause_storage(request["paused"])
            return self.snapshot()
        return await super().dispatch(request)


class MessengerSender:
    """Adapt the durable outbox to the already-open E2EE session; never open a second device."""
    def __init__(self, core, session):
        self.core, self.session, self.account_id = core, session, core.account_id

    async def connect(self):
        if self.account_id != self.core.account_id:
            raise AppError("ACCOUNT_CHANGED")
        if self.core.connection != "connected" or self.core.receiving != "waiting":
            raise AppError("MESSENGER_CONNECTION_LOST")

    def selected_conversation(self):
        return self.core._record(self.core.selected_id).conversation

    async def send_text(self, text):
        return await self.session.send_text(self.selected_conversation().id, text, self.account_id)

    async def send_to(self, conversation, text, *, authorize):
        from .messenger import JID
        if (conversation.kind != "dm" or not JID.fullmatch(conversation.id)
                or conversation.id == self.account_id + "@msgr"):
            raise AppError("INVALID_INPUT")
        await self.connect()
        # Same authenticated receiver/device; never mutate the selected conversation.
        return await self.session.send_text(conversation.id, text, self.account_id, authorize=authorize)

    async def send_image_to(self, conversation, image, *, authorize):
        from .messenger import JID
        if conversation.kind != 'dm' or not JID.fullmatch(conversation.id) or conversation.id == self.account_id + '@msgr':
            raise AppError('INVALID_INPUT')
        await self.connect()
        return await self.session.send_image(conversation.id, image, self.account_id, authorize=authorize)
