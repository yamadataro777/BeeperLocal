"""Private GUI controls and explicitly scoped MCP operations on the same Core."""
from __future__ import annotations

import asyncio
import secrets
import time
from uuid import UUID, uuid5

from .errors import AppError
from .mcp_access import AccessManager, GRANTS_KEY, SETTINGS_KEY, DEFAULT_PORT, default_settings, load_settings
from .models import iso

MCP_REQUEST_NAMESPACE = UUID("26d908bb-6302-4d9b-af5b-a9c6f78b7084")


class DesktopControls:
    settings_key = SETTINGS_KEY
    grants_key = GRANTS_KEY
    default_mcp_port = DEFAULT_PORT

    def initialize_controls(self):
        defaults = {**default_settings(), "port": self.default_mcp_port}
        if (self.settings_key != SETTINGS_KEY and self.db.private_get(self.settings_key) is None
                and self.db.private_get(SETTINGS_KEY) is not None):
            # Reject old controls: defaulting here could silently resume paused storage.
            raise AppError("LOCAL_DB_SCHEMA_UNSUPPORTED")
        self.settings = load_settings(self.db, self.settings_key, defaults)
        self.access = AccessManager(self.db, self.grants_key)

    def require_storage(self):
        if self.settings["storagePaused"]:
            raise AppError("STORAGE_PAUSED")

    def _save_settings(self, **updates):
        value = {**self.settings, **updates}
        self.db.private_put(self.settings_key, value)
        self.settings = value

    async def restore_mcp(self):
        if self.mcp_restore_attempted:
            return
        self.mcp_restore_attempted = True
        if self.settings["mcpEnabled"]:
            try:
                await self._start_mcp(self.settings["port"])
            except AppError as exc:
                self.mcp_error = exc.code

    async def _start_mcp(self, port):
        try:
            from .mcp_server import MCPRuntime
            runtime = MCPRuntime(self, port=port)
            await runtime.start()
        except AppError:
            raise
        except Exception:
            raise AppError("MCP_START_FAILED") from None
        self.mcp_runtime = runtime
        self.mcp_error = None

    async def _stop_mcp(self):
        runtime, self.mcp_runtime = self.mcp_runtime, None
        if runtime:
            await runtime.stop()

    async def configure_mcp(self, enabled, port):
        if type(enabled) is not bool or type(port) is not int or not 1024 <= port <= 65535:
            raise AppError("INVALID_INPUT")
        # Invalidate access before yielding to shutdown or attempting another port.
        self._save_settings(mcpEnabled=False, port=port)
        await self._stop_mcp()
        self.mcp_error = None
        if enabled:
            try:
                await self._start_mcp(port)
                self._save_settings(mcpEnabled=True)
            except AppError as exc:
                await self._stop_mcp()
                self.mcp_error = exc.code
                raise
        return self.management()

    def management(self):
        grants = [g.view() for g in self.access.all() if g.account_id == self.account_id]
        runtime = self.mcp_runtime
        return {"mcp": {"enabled": self.settings["mcpEnabled"],
                        "running": bool(runtime and runtime.running), "port": self.settings["port"],
                        "url": f"http://127.0.0.1:{self.settings['port']}/mcp", "errorCode": self.mcp_error},
                "clients": grants,
                "storage": {"paused": self.settings["storagePaused"], "path": str(self.db.path),
                            "counts": self.db.provider_data_counts(self.provider, self.account_id) if self.account_id else {},
                            "retention": "until_deleted"},
                "accountAvailable": bool(self.account_id)}

    def register_client(self, request):
        available = {r.id for r in self._records()}
        grant, token = self.access.create(name=request["name"], account_id=self.account_id,
            conversations=request["conversationIds"], read=request["read"], send=request["send"], available=available)
        return {"client": grant.view(), "token": token, "url": self.management()["mcp"]["url"]}

    async def pause_storage(self, paused):
        if type(paused) is not bool:
            raise AppError("INVALID_INPUT")
        self._save_settings(storagePaused=paused)
        self.deletion_challenge = None
        if paused:
            await self.cancel_login()
            await self.clear_avatars()
            await self.stop_watch()
            self.connection = "offline"
        self._notify("status", **self._status())
        return self.management()

    async def deletion_preview(self):
        if not self.account_id:
            raise AppError("CREDENTIALS_MISSING")
        await self.pause_storage(True)
        # Let an already issued send finish recording its outcome before showing counts.
        async with self.operation_lock:
            counts = self.db.provider_data_counts(self.provider, self.account_id)
            nonce = secrets.token_urlsafe(24)
            self.deletion_challenge = (nonce, self.account_id, time.monotonic() + 120, counts)
            return {"confirmation": nonce, "counts": counts, "expiresInSeconds": 120}

    async def delete_local_data(self, confirmation):
        challenge, self.deletion_challenge = self.deletion_challenge, None
        if (not challenge or not isinstance(confirmation, str)
                or not secrets.compare_digest(confirmation, challenge[0])
                or challenge[1] != self.account_id or time.monotonic() > challenge[2]
                or not self.settings["storagePaused"]):
            raise AppError("DELETE_CONFIRMATION_EXPIRED")
        # Disable external reads immediately, before waiting for any outstanding operation.
        self._save_settings(mcpEnabled=False)
        await self._stop_mcp()
        async with self.operation_lock:
            if self.db.provider_data_counts(self.provider, self.account_id) != challenge[3]:
                raise AppError("DELETE_CONFIRMATION_EXPIRED")
            await self.clear_provider_cache()
            remaining = [g.persisted() for g in self.access.all() if g.account_id != self.account_id]
            counts = self.db.clear_provider_data(self.provider, self.account_id,
                private_updates={self.access.key: remaining, self.settings_key: self.settings,
                                 self.catalog_key(): []}, expected_counts=challenge[3])
            self.selected_id = None
            self.connector = None
            self.connection = "offline"
            self.error_code = None
            self._notify("data_cleared", **self._status())
            return {"deleted": counts, "management": self.management()}

    async def clear_provider_cache(self):
        """Provider-specific duplicate content; keep login/device keys intact."""
        return

    def require_mcp(self, token, permission=None, conversation_id=None):
        if self.shutting_down or not self.settings["mcpEnabled"]:
            raise AppError("MCP_DISABLED")
        if permission is None:
            return self.access.authenticate(token, self.account_id)
        return self.access.authorize(token, self.account_id, permission, conversation_id)

    async def mcp_call(self, token, operation, arguments):
        # serialize sends with GUI selection/connection; revocation is intentionally not blocked
        async with self.operation_lock:
            if operation == "send_message":
                identity = arguments["conversation_id"]
                grant = self.require_mcp(token, "send", identity)
                self.require_storage()
                supplied_id = arguments["request_id"]
                try:
                    if not isinstance(supplied_id, str) or str(UUID(supplied_id)) != supplied_id:
                        raise ValueError()
                except ValueError:
                    raise AppError("INVALID_INPUT") from None
                effective_id = str(uuid5(MCP_REQUEST_NAMESPACE, grant.id + "/" + supplied_id))
                guard = lambda: self.require_mcp(token, "send", identity)
                return await self.send(identity, arguments["text"], effective_id, explicit_target=True, authorize=guard)

            identity = arguments.get("conversation_id")
            grant = self.require_mcp(token, "read", identity)
            allowed = set(grant.conversations)
            records = {r.id: r for r in self._records() if r.id in allowed}
            if operation == "list_conversations":
                # Build views only after checking the granted set, never return a global snapshot.
                result = {"conversations": [{"id": r.id, "title": r.conversation.title, "provider": self.provider}
                                             for r in records.values()], "source": "saved_local_data"}
            elif operation == "get_messages":
                if identity not in records:
                    raise AppError("MCP_ACCESS_DENIED")
                result = {**self.messages(identity, before=arguments.get("before")), "source": "saved_local_data"}
            elif operation == "search_messages":
                query = arguments["query"]
                if not isinstance(query, str) or not query.strip() or len(query) > 500:
                    raise AppError("INVALID_INPUT")
                needle = query.strip().casefold()
                by_raw = {r.conversation.id: r for r in records.values()}
                hits, scanned = [], 0
                for m in self.db.recent_messages(provider=self.provider):
                    record = by_raw.get(m.conversation_id)
                    if m.account_id != self.account_id or record is None:
                        continue
                    scanned += 1
                    if needle in ((m.text or "") + "\n" + record.conversation.title).casefold():
                        if len(hits) < 50:
                            hits.append({"id": m.id, "conversationId": record.id, "title": record.conversation.title,
                                         "text": m.text or "", "direction": m.direction, "sentAt": iso(m.sent_at)})
                result = {"results": hits, "scannedPermittedMessages": scanned, "scanLimit": 10000,
                          "resultLimit": 50, "source": "saved_local_data"}
            else:
                raise AppError("INVALID_INPUT")
            self.require_mcp(token, "read", identity)
            return result
