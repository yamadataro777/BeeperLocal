"""Private, allowlisted NDJSON IPC for the desktop. Stdout is IPC, never a log."""
from __future__ import annotations

import asyncio
from contextlib import aclosing, suppress
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import logging
import os
import re
import signal
import sys
import time

from .connectors.line import LineConnector
from .credentials import MacKeychain, MacLocalKeyStore
from .errors import AppError
from .models import StoredConversation, Conversation, iso
from .outbox import OutgoingRequest
from .reporting import default_state_dir, private_directory
from .storage import EncryptedMessageStore, db_exists
from .sync import recover_line_history
from .desktop_control import DesktopControls
from .desktop_profiles import DesktopProfiles, profile_version
from .desktop_media import DesktopMedia
from .desktop_sync import DesktopSync
from .mcp_access import default_settings
from .receiver_retry import wait_for_retry
from .outgoing_images import DesktopImageSending

MAX_REQUEST_BYTES = 6 * 1024 * 1024
OPAQUE_ID = re.compile(r"[a-f0-9]{64}\Z")


def open_store():
    keys = MacLocalKeyStore()
    return EncryptedMessageStore(keys.load() if db_exists() else keys.load_or_create())


def message_view(message):
    return {"id": message.id, "text": message.text or "", "sentAt": iso(message.sent_at),
            "direction": message.direction, "attachmentCount": message.attachment_count,
            "attachments": [{"index": i, "kind": a['kind'], "name": a.get('name', '')}
                            for i, a in enumerate(message.attachments)],
            **({"media": {"kind": message.media["kind"]}} if message.media else {})}


class DesktopCore(DesktopImageSending, DesktopSync, DesktopControls, DesktopProfiles, DesktopMedia):
    provider = "line"
    history_limit = 100
    line_retry_interval = 60
    send_unknown = "LINE_SEND_UNKNOWN"
    sent_not_stored = "LINE_SENT_NOT_STORED"

    def __init__(self, *, credentials=None, db_factory=open_store, connector_factory=LineConnector, emit=None):
        self.initialize_profiles()
        self.initialize_media()
        self.initialize_sync()
        self.credentials = credentials
        self.db_factory = db_factory
        self.connector_factory = connector_factory
        self.emit = emit or (lambda event: None)
        self.connector = None
        self.db = None
        self.account_id = ""
        self.selected_id = None
        self.connection = "offline"
        self.receiving = "stopped"
        self.error_code = None
        self.watch_task = None
        self.recovery_task = None
        self.watch_generation = 0
        self.started = False
        self.settings = default_settings()
        self.access = None
        self.mcp_runtime = None
        self.mcp_error = None
        self.mcp_restore_attempted = False
        self.deletion_challenge = None
        self.shutting_down = False
        self.operation_lock = asyncio.Lock()
        self.recovery_lock = asyncio.Lock()
        self.retry_delays = (1, 2, 4, 8, 16, 30)
        self.retry_attempt = 0
        self.recovery_interval = 60
        self.watch_ready = asyncio.Event()

    def _initialize(self):
        if self.started:
            return
        self.credentials = self.credentials or MacKeychain()
        if self.db is None:
            self.db = self.db_factory()
        try:
            metadata = self.credentials.load(self.provider)
            self.account_id = metadata.get("account_id", "")
            selections = metadata.get("selections", [])
            if self.account_id and selections:
                self.selected_id = StoredConversation(self.provider, self.account_id,
                                                       Conversation.from_selection(selections[0])).id
        except AppError as exc:
            if exc.code != "CREDENTIALS_MISSING":
                raise
        self.initialize_controls()
        if self.selected_id not in {r.id for r in self._records()}:
            self.selected_id = None
        self.started = True

    def _records(self):
        return self.db.list_conversations(provider=self.provider, account_id=self.account_id) if self.account_id else []

    def catalog_key(self):
        return f"desktop.{self.provider}.catalog." + sha256(self.account_id.encode()).hexdigest()

    def _current_records(self):
        records = self._records()
        catalog = self.db.private_get(self.catalog_key()) if self.account_id else None
        if catalog is None: return records  # No remote catalog snapshot has been fetched yet.
        if not isinstance(catalog, list) or any(not isinstance(item, str) or not OPAQUE_ID.fullmatch(item) for item in catalog):
            raise AppError("LOCAL_DB_CORRUPT")
        visible = set(catalog)
        return [record for record in records if record.id in visible]

    def _record(self, identity):
        if not isinstance(identity, str) or not OPAQUE_ID.fullmatch(identity):
            raise AppError("INVALID_INPUT")
        for record in self._records():
            if record.id == identity:
                return record
        raise AppError("CONVERSATION_UNAVAILABLE")

    def _status(self):
        return {"connection": self.connection, "receiving": self.receiving,
                "errorCode": self.error_code, "selectedId": self.selected_id,
                "retryAttempt": self.retry_attempt, "storagePaused": self.settings["storagePaused"],
                "sync": self.sync_state}

    def _notify(self, event, **values):
        self.emit({"event": event, **values})

    def snapshot(self):
        records = self._current_records()
        by_raw_id = {r.conversation.id: r for r in records}
        latest = {}
        for message in self.db.recent_messages(provider=self.provider):
            if message.account_id == self.account_id and message.conversation_id in by_raw_id:
                latest.setdefault(message.conversation_id, message)
        views = []
        for record in records:
            last = latest.get(record.conversation.id)
            stamp = record.conversation.locator.get("updated_at", 0)
            upstream = datetime.fromtimestamp(stamp / 1000, timezone.utc) if stamp else None
            newest = max([d for d in (upstream, last.sent_at if last else None) if d], default=None)
            views.append({"id": record.id, "title": record.conversation.title, "provider": self.provider,
                          "kind": record.conversation.kind, "unreadCount": len(self.read_state(record.id)['unread']),
                          "preview": (last.text or "")[:100] if last and newest == last.sent_at else "",
                          "avatarVersion": profile_version(self.provider, record.conversation.locator),
                          "lastMessageAt": iso(newest) if newest else None})
        views.sort(key=lambda c: (c["lastMessageAt"] is not None, c["lastMessageAt"] or "", c["id"]), reverse=True)
        pending = self.db.pending_outgoing(self.account_id, provider=self.provider) if self.account_id else []
        scoped = {r.conversation.id: r.id for r in records}
        return {**self._status(), "conversations": views, "unreadCount": sum(v['unreadCount'] for v in views),
                "catalogLimited": getattr(self.connector, 'catalog_limited', len(records) >= 500),
                "pendingSends": [{"requestId": r.request_id, "conversationId": scoped.get(r.conversation_id),
                                   "text": r.text, "imageDigest": r.image_digest, "status": "unknown", "createdAt": iso(r.created_at)}
                                  for r in pending]}

    async def connect(self):
        self.require_no_login()
        self.require_storage()
        await self.clear_media()
        await self.stop_watch()
        self.connection = "connecting"
        self.error_code = None
        self._notify("status", **self._status())
        try:
            candidate = self.connector_factory(self.credentials)
            await candidate.connect()
            self.connector = candidate
            self.account_id = candidate.account_id
            choices = await candidate.list_conversations(10000 if self.supports_all_sync() else 500)
            self.require_storage()
            records = [StoredConversation(self.provider, self.account_id, c) for c in choices]
            self.db.upsert_conversations(records)
            self.db.private_put(self.catalog_key(), [r.id for r in records])
            try:
                selected = candidate.selected_conversation()
                self.selected_id = (StoredConversation(self.provider, self.account_id, selected).id
                                    if selected.id in {c.id for c in choices} else None)
            except AppError as exc:
                if exc.code not in {"NO_SELECTION", "SLACK_SELECT_ONE"}:
                    raise
                self.selected_id = None
            self.connection = "connected"
            if self.selected_id:
                await self.sync_selected()
                self.start_watch()
            elif self.supports_all_sync():
                self.start_watch()
            self._notify("status", **self._status())
            return self.snapshot()
        except AppError as exc:
            self.connection = "error"
            self.error_code = exc.code
            self._notify("status", **self._status())
            raise

    async def select_remote(self, conversation):
        await self.connector.select_mid(conversation.id, title=conversation.title)

    def persist_history(self, batch):
        from .sync import persist_line_history
        return persist_line_history(self.db, batch)

    def require_connected(self):
        self.require_no_login()
        if self.connection != "connected" or self.connector is None:
            raise AppError("DESKTOP_NOT_CONNECTED")

    def invalidate_line_session(self, code):
        if self.provider != 'line' or code not in {'LINE_SESSION_REVOKED', 'LINE_LOGIN_REQUIRED'}:
            return False
        self.watch_generation += 1
        self.watch_ready.clear()
        self.connection = self.receiving = 'error'
        self.error_code = code
        self.retry_attempt = 0
        self.sync_state['mode'] = 'error'
        current = asyncio.current_task()
        for task in (self.watch_task, self.recovery_task, self.sync_task):
            if task and task is not current:
                task.cancel()
        self._notify('status', **self._status())
        return True

    async def select(self, identity):
        record = self._record(identity)
        if identity != self.selected_id:
            await self.clear_media()
        await self.stop_watch()
        if self.connection == "connected" and not self.settings["storagePaused"]:
            try:
                await self.select_remote(record.conversation)
            except AppError as exc:
                # Keep routing/selection consistent when Keychain persistence fails.
                self.error_code = exc.code
                self.receiving = "error"
                self._notify("status", **self._status())
                raise
            self.selected_id = record.id
            self.receiving = "recovering"
            self._notify("status", **self._status())
            try:
                await self.sync_selected()
                self.start_watch()
            except AppError as exc:
                self.receiving = "error"
                self.error_code = exc.code
                self._notify("status", **self._status())
                raise
        else:
            self.selected_id = record.id
        return self.messages(identity)

    def messages(self, identity, before=None):
        record = self._record(identity)
        rows = self.db.list_messages(self.provider, self.account_id, record.conversation.id, limit=100, before=before)
        receipt = self.db.get_sync_receipt(record)
        sync = self.db.private_get('sync.v1.' + identity, {})
        return {"conversationId": record.id, "messages": [self.message_view(m) for m in rows],
                "olderCursor": rows[0].id if len(rows) == 100 else None,
                "sync": {k: sync[k] for k in ('backfill', 'complete', 'exhausted', 'coverage', 'lastSync') if k in sync},
                "lastRecovery": iso(receipt.completed_at) if receipt else None,
                    "historyLimit": receipt.requested_limit if receipt else None,
                "historyLimited": True, "limitReached": receipt.history_limited if receipt else False}

    async def _fetch_selected_history(self):
        return await self.connector.fetch(self.history_limit)

    async def sync_selected(self):
        self.require_storage()
        self.require_connected()
        if not self.selected_id:
            raise AppError("NO_SELECTION")
        async with self.recovery_lock:
            identity, generation = self.selected_id, self.watch_generation
            batch = await self._fetch_selected_history()
            self.require_storage()
            if identity != self.selected_id or generation != self.watch_generation:
                raise AppError("CONVERSATION_CHANGED")
            receipt, stats = self.persist_history(batch)
            self.error_code = None
            self._notify("messages_changed", conversationId=identity)
            return {"inserted": stats["inserted"], "updated": stats["updated"],
                    "lastRecovery": iso(receipt.completed_at), "historyLimited": True}

    async def refresh(self):
        self.require_connected()
        await self.stop_watch()
        try:
            result = await self.sync_selected()
            self.start_watch()
            return result
        except AppError as exc:
            self.receiving = "error"
            self.error_code = exc.code
            self._notify("status", **self._status())
            raise

    def start_watch(self):
        self.require_connected()
        if self.supports_all_sync():
            self.start_all_sync()
        self.watch_generation += 1
        generation = self.watch_generation
        identity = self.selected_id
        self.receiving = "starting"
        self.retry_attempt = 0
        self.watch_ready = asyncio.Event()
        self.watch_task = asyncio.create_task(self._watch(generation, identity))
        # Bounded recovery also catches messages missed while the external cursor advanced.
        if identity:
            self.recovery_task = asyncio.create_task(self._recover_periodically(generation, identity))

    async def _watch(self, generation, identity):
        attempts = 0
        while generation == self.watch_generation and not self.settings["storagePaused"]:
            started = asyncio.Event()
            started_at = None
            async def ready():
                nonlocal started_at
                await started.wait()
                if self.watch_generation == generation and started.is_set():
                    started_at = time.monotonic()
                    self.receiving = "waiting"
                    self.retry_attempt = 0
                    self.error_code = None
                    self.watch_ready.set()
                    self._notify("status", **self._status())
            ready_task = asyncio.create_task(ready())
            def status_changed(state):
                nonlocal started_at
                if generation != self.watch_generation or self.connection != 'connected':
                    return
                if state == 'ready':
                    started_at = time.monotonic()
                    self.receiving, self.error_code, self.retry_attempt = 'waiting', None, 0
                    self.watch_ready.set()
                else:
                    self.receiving, self.error_code = 'reconnecting', 'LINE_WATCH_FAILED'
                    self.watch_ready.clear()
                self._notify('status', **self._status())
            try:
                if attempts and self.selected_id:
                    await self.sync_selected()
                options = {'all_conversations': True} if self.supports_all_sync() else {}
                if getattr(self.connector, 'supports_watch_status', False):
                    options['status_changed'] = status_changed
                async with aclosing(self.connector.watch(timeout=0, from_now=False, started=started, **options)) as stream:
                    async for message in stream:
                        if generation != self.watch_generation:
                            return
                        self.require_storage()
                        record = next((r for r in self._records() if r.conversation.id == message.conversation_id), None)
                        if record is None:
                            raise AppError('BAD_RESPONSE')
                        if (message.account_id, message.conversation_id) != (record.account_id, record.conversation.id):
                            raise AppError("BAD_RESPONSE")
                        self.ingest([message], records=[record])
                        attempts = self.retry_attempt = 0
                        self.receiving = "waiting"
                        self.error_code = None
                        self._notify("messages_changed", conversationId=record.id)
                raise AppError("LINE_WATCH_FAILED")  # EOF is a disconnect, not successful indefinite watching.
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                # EOF can arrive before ready() runs. Never let that stale task
                # label a dead subprocess as waiting during the retry delay.
                ready_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ready_task
                self.watch_ready.clear()
                if generation != self.watch_generation:
                    return
                code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
                if self.invalidate_line_session(code):
                    return
                if started_at is not None and time.monotonic() - started_at >= 60:
                    attempts = 0
                if code not in {"LINE_REQUEST_FAILED", "LINE_WATCH_FAILED", "NETWORK_ERROR"}:
                    self.receiving, self.error_code = "error", code
                    if self.recovery_task:
                        self.recovery_task.cancel()
                    self._notify("status", **self._status())
                    return
                slow_retry = attempts >= len(self.retry_delays)
                delay = self.line_retry_interval if slow_retry else self.retry_delays[attempts]
                self.receiving = "reconnecting"
                self.error_code = "LINE_RECONNECT_WAITING" if slow_retry else code
                self.retry_attempt = attempts + 1
                self._notify("status", **self._status())
                await wait_for_retry(delay)
                attempts += 1
                # The restarted watcher and the independent bounded recovery share the same generation.
            finally:
                ready_task.cancel()
                with suppress(asyncio.CancelledError):
                    await ready_task

    async def _recover_periodically(self, generation, identity):
        attempts = 0
        while generation == self.watch_generation:
            try:
                await self.watch_ready.wait()
                if generation != self.watch_generation or identity != self.selected_id:
                    return
                # Also recover once after watch starts, narrowing the startup gap within the 100-row window.
                await self.sync_selected()
                attempts = 0
                if self.watch_ready.is_set():
                    self.retry_attempt = 0
                    self._notify("status", **self._status())
                await asyncio.sleep(self.recovery_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if generation != self.watch_generation:
                    return
                code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
                if self.invalidate_line_session(code):
                    return
                if code not in {"LINE_REQUEST_FAILED", "NETWORK_ERROR"}:
                    self.receiving = "error"
                    self.error_code = code
                    if self.watch_task:
                        self.watch_task.cancel()
                    self._notify("status", **self._status())
                    return
                slow_retry = attempts >= len(self.retry_delays)
                delay = self.line_retry_interval if slow_retry else self.retry_delays[attempts]
                self.error_code = "LINE_RECONNECT_WAITING" if slow_retry else code
                self._notify("status", **self._status())
                await wait_for_retry(delay)
                attempts += 1

    async def stop_watch(self):
        self.watch_generation += 1
        tasks = [t for t in (self.watch_task, self.recovery_task, self.sync_task) if t]
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        self.watch_task = self.recovery_task = None
        self.sync_task = None
        self.sync_state['mode'] = 'stopped'
        self.receiving = "stopped"
        self.retry_attempt = 0

    async def send(self, identity, text, request_id, *, explicit_target=False, authorize=None):
        self.require_storage()
        self.require_connected()
        record = self._record(identity)
        if not explicit_target and identity != self.selected_id:
            raise AppError("CONVERSATION_CHANGED")
        try:
            request = OutgoingRequest(request_id, self.provider, self.account_id, record.conversation.id,
                                      text, "sending", datetime.now(timezone.utc))
        except (ValueError, TypeError, AttributeError, UnicodeError):
            raise AppError("INVALID_INPUT") from None
        if self.db.request_retired(request_id):
            raise AppError(self.send_unknown)
        previous = self.db.get_outgoing(request_id)
        if previous:
            if (previous.provider, previous.account_id, previous.conversation_id, previous.text) != (request.provider, request.account_id, request.conversation_id, text):
                raise AppError("INVALID_INPUT")
            if previous.status == "acknowledged":
                return {"status": "acknowledged", "messageId": previous.message_id, "duplicateSuppressed": True}
            raise AppError(self.send_unknown)
        await self.connector.connect()
        self.require_storage()
        self.require_connected()
        if authorize:
            authorize()
        if not explicit_target and self.connector.selected_conversation().id != record.conversation.id:
            raise AppError("CONVERSATION_CHANGED")
        self.db.upsert([], outgoing_requests=[request])  # durable BEFORE the remote mutation
        try:
            if explicit_target:
                def check():
                    self.require_storage()
                    self.require_connected()
                    authorize()
                result = await self.connector.send_to(record.conversation, text, authorize=check)
            else:
                result = await self.connector.send_text(text)
        except BaseException:
            self.db.upsert([], outgoing_requests=[replace(request, status="unknown")])
            raise
        if (result.message.provider, result.message.account_id, result.message.conversation_id, result.message.direction, result.message.text) != (self.provider, self.account_id, record.conversation.id, "outgoing", text):
            self.db.upsert([], outgoing_requests=[replace(request, status="unknown")])
            raise AppError(self.send_unknown)
        acknowledged = replace(request, status="acknowledged", message_id=result.message.id)
        try:
            self.db.upsert([result.message], conversations=[record], outgoing_requests=[acknowledged])
        except Exception:
            raise AppError(self.sent_not_stored) from None
        self._notify("messages_changed", conversationId=identity)
        return {"status": "acknowledged", "messageId": result.message.id, "encrypted": result.encrypted}

    def search(self, query):
        if not isinstance(query, str):
            raise AppError("INVALID_INPUT")
        # Account filtering is done before limiting matches, avoiding old-account leaks.
        needle = query.strip().casefold()
        if not needle or len(needle) > 500:
            raise AppError("INVALID_INPUT")
        # A bounded remote catalog is not a deletion notice. Saved conversations
        # outside its latest page must remain searchable for this account.
        records = {r.conversation.id: r for r in self._records()}
        rows = self.db.recent_messages(provider=self.provider)
        results = []
        for message in rows:
            if message.account_id != self.account_id or message.conversation_id not in records:
                continue
            record = records[message.conversation_id]
            if needle in ((message.text or "") + "\n" + record.conversation.title).casefold():
                results.append({**self.message_view(message), "conversationId": record.id, "title": record.conversation.title})
                if len(results) == 50:
                    break
        return {"results": results, "scanned": len(rows), "scanLimit": 10000}

    async def dispatch(self, request):
        if not isinstance(request, dict):
            raise AppError("INVALID_INPUT")
        operation = request.get("op")
        schemas = {"ping": set(), "snapshot": set(), "connect": set(), "select": {"conversationId"},
                   "messages": {"conversationId"}, "refresh": set(), "stop": set(),
                   "search": {"query"}, "send": {"conversationId", "text", "requestId"},
                   "send_image": {"conversationId", "dataUrl", "requestId"},
                   "management": set(), "mcp_configure": {"enabled", "port"},
                   "mcp_register": {"name", "conversationIds", "read", "send"},
                   "mcp_revoke": {"clientId"}, "storage_pause": {"paused"},
                   "storage_delete_preview": set(), "storage_delete": {"confirmation"},
                   "line_login_start": {"replace"}, "line_login_status": set(), "line_login_cancel": set(),
                   "avatar": {"conversationId"}, "line_media": {"conversationId", "messageId", "retry"}}
        schemas.update({"mark_read": {"conversationId", "throughMessageId"},
                        "attachment_media": {"conversationId", "messageId", "index", "retry"},
                        "messages_older": {"conversationId", "before"},
                        "history_backfill": {"conversationId", "enabled"}})
        if operation not in schemas or set(request) != schemas[operation] | {"op"}:
            raise AppError("INVALID_INPUT")
        if operation == "ping":
            return {"ready": True, "version": "0.9.5"}
        self._initialize()
        await self.restore_mcp()
        if operation == "line_login_status": return self.login_state
        if operation == "line_login_cancel": return await self.cancel_login()
        if operation == "line_login_start": return await self.start_login(request["replace"])
        if operation == "avatar": return self.avatar(request["conversationId"])
        if operation == "line_media": return self.line_media(request["conversationId"], request["messageId"], request["retry"])
        if operation == "attachment_media": return self.attachment_media(request['conversationId'], request['messageId'], request['index'], request['retry'])
        if operation in {"connect", "select", "refresh", "send", "send_image", "mcp_configure", "storage_delete_preview", "storage_delete"}:
            self.require_no_login()
        if operation == "management": return self.management()
        if operation == "mcp_configure": return await self.configure_mcp(request["enabled"], request["port"])
        if operation == "mcp_register": return self.register_client(request)
        if operation == "mcp_revoke":
            self.access.revoke(request["clientId"], self.account_id)
            return self.management()
        if operation == "storage_pause": return await self.pause_storage(request["paused"])
        if operation == "storage_delete_preview": return await self.deletion_preview()
        if operation == "storage_delete": return await self.delete_local_data(request["confirmation"])
        if operation == "snapshot": return self.snapshot()
        if operation == "messages": return self.messages(request["conversationId"])
        if operation == "messages_older": return self.messages(request['conversationId'], before=request['before'])
        if operation == "mark_read": return self.mark_read(request['conversationId'], request['throughMessageId'])
        if operation == "history_backfill": return self.backfill(request['conversationId'], request['enabled'])
        if operation == "search": return self.search(request["query"])
        if operation in {"connect", "select", "refresh", "send", "send_image"}:
            async with self.operation_lock:
                try:
                    if operation == "connect": return await self.connect()
                    if operation == "select": return await self.select(request["conversationId"])
                    if operation == "refresh": return await self.refresh()
                    if operation == "send_image": return await self.send_image(request['conversationId'], request['dataUrl'], request['requestId'])
                    return await self.send(request["conversationId"], request["text"], request["requestId"])
                except AppError as exc:
                    self.invalidate_line_session(exc.code)
                    raise
        if operation == "stop":
            await self.clear_media()
            await self.stop_watch()
            self.connection = "offline"
            self._notify("status", **self._status())
            return self._status()

    async def close(self):
        self.shutting_down = True
        await self.cancel_login()
        await self.clear_avatars()
        await self._stop_mcp()
        await self.stop_watch()
        if self.db:
            self.db.close()


def write_ipc(value):
    sys.stdout.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


async def serve_stream(reader, core, emit):
    pending = set()

    async def respond(raw):
        request_id = None
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or set(value) != {"id", "request"}:
                raise AppError("INVALID_INPUT")
            request_id = value["id"]
            if type(request_id) is not int or not 0 <= request_id <= 2**53:
                request_id = None
                raise AppError("INVALID_INPUT")
            result = await core.dispatch(value["request"])
            emit({"id": request_id, "ok": True, "result": result})
        except Exception as exc:
            code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
            emit({"id": request_id, "ok": False, "error": code})

    try:
        while True:
            raw = await reader.readline()
            if not raw:
                break
            if len(raw) > MAX_REQUEST_BYTES:
                emit({"id": None, "ok": False, "error": "INVALID_INPUT"})
                continue
            # Update preparation is a barrier: all accepted commands finish
            # before receivers stop and the app bundle can be replaced.
            try:
                frame = json.loads(raw)
                barrier = isinstance(frame, dict) and frame.get('request') == {'op': 'prepare_update'}
            except (ValueError, UnicodeError):
                barrier = False
            if barrier:
                await asyncio.gather(*tuple(pending))
                await respond(raw)
                continue
            if len(pending) >= 64:
                await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            task = asyncio.create_task(respond(raw))
            pending.add(task)
            task.add_done_callback(pending.discard)
        await asyncio.gather(*tuple(pending))
    finally:
        for task in tuple(pending):
            task.cancel()
        await asyncio.gather(*tuple(pending), return_exceptions=True)


async def serve():
    from .desktop_router import DesktopRouter
    from .credentials import start_desktop_keychain_session, end_desktop_keychain_session
    start_desktop_keychain_session()
    core = DesktopRouter(emit=write_ipc)
    reader = asyncio.StreamReader(limit=MAX_REQUEST_BYTES)
    protocol = asyncio.StreamReaderProtocol(reader)
    transport, _ = await asyncio.get_running_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    try:
        await serve_stream(reader, core, write_ipc)
    finally:
        transport.close()
        await core.close()
        end_desktop_keychain_session()


async def run_server():
    task = asyncio.create_task(serve())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass


def main():
    logging.disable(logging.CRITICAL)
    os.umask(0o077)
    # The lock carries no account data. macOS releases it on process exit/crash.
    lock = None
    try:
        directory = default_state_dir()
        private_directory(directory)
        path = directory / "desktop.lock"
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        lock = os.fdopen(fd, "w")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            write_ipc({"event": "fatal", "error": "DESKTOP_ALREADY_RUNNING"})
            return 1
        asyncio.run(run_server())
        return 0
    except (BrokenPipeError, KeyboardInterrupt):
        return 1
    except Exception:
        return 1  # Never expose raw SDK/Python errors from a frozen process.
    finally:
        if lock:
            lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
