"""User-token Slack Core using the existing encrypted store, outbox and MCP boundary."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from functools import partial

from .connectors.slack import SlackConnector
from .desktop import DesktopCore, open_store, message_view
from .errors import AppError
from .mcp_access import AccessManager, load_settings, default_settings
from .models import HistorySyncReceipt
from .slack_profiles import SlackProfiles
from .receiver_retry import wait_for_retry

SETTINGS = "desktop.slack.settings.v1"
GRANTS = "desktop.slack.mcp-clients.v1"


def slack_message_view(message):
    return {**message_view(message), "replyToMessageId":
        replace(message, provider_message_id=message.reply_to_message_id).id if message.reply_to_message_id else None}


class SlackDesktop(SlackProfiles, DesktopCore):
    provider = "slack"
    settings_key = SETTINGS
    # One 15-item history request per poll also works with Slack's restrictive tier.
    history_limit = 15
    send_unknown = "SLACK_SEND_UNKNOWN"
    sent_not_stored = "SLACK_SENT_NOT_STORED"
    reconnect_interval = 300
    sync_interval = 65

    def __init__(self, *, credentials=None, db_factory=open_store,
                 connector_factory=None, emit=None, oauth_factory=None):
        super().__init__(credentials=credentials, db_factory=db_factory,
            connector_factory=connector_factory or partial(SlackConnector, max_wait=0), emit=emit)
        self.poll_interval = 65
        self.retry_delays = (65, 130, 260)
        self.initialize_slack_profiles()
        from .slack_oauth import SlackOAuth
        self.oauth_factory = oauth_factory or SlackOAuth

    async def start_slack_login(self):
        self.require_no_login()
        self.require_storage()
        oauth = self.oauth_factory(self.credentials)
        oauth.check_configuration()  # Do not stop an existing receiver for an unavailable flow.
        async with self.operation_lock:
            self.require_storage()
            await self.stop_watch()
            self.connection = "offline"
            self.login_state = {"stage": "web"}
            self.login_task = asyncio.create_task(self._run_slack_login(oauth))
        self._notify("status", **self._status())
        return self.login_state

    async def _run_slack_login(self, oauth):
        try:
            account = await oauth.login(self.account_id)
            self.account_id, self.connector = account, None
            self.login_state = {"stage": "completed"}
        except asyncio.CancelledError:
            self.login_state = {"stage": "cancelled"}
            raise
        except Exception as exc:
            self.login_state = {"stage": "failed", "errorCode": exc.code if isinstance(exc, AppError) else "SLACK_OAUTH_FAILED"}
        finally:
            self._notify("slack_login_changed")

    async def connect(self):
        await self.clear_avatars()
        self.slack_profile_error = None
        return await super().connect()

    def _status(self):
        return {**super()._status(), "profileErrorCode": self.slack_profile_error}

    def snapshot(self):
        result = super().snapshot()
        records = {r.id: r for r in self._current_records()}
        for view in result["conversations"]:
            conversation = records[view["id"]].conversation
            view["kind"] = conversation.kind
            peer = conversation.locator.get("peer_user_id")
            if peer:
                view["avatarVersion"] = "slack-profile"
                profile = self.cached_slack_profile(peer)
                if profile and profile["name"]:
                    view["title"] = profile["name"]
        return result

    def initialize_controls(self):
        self.settings = load_settings(self.db, SETTINGS, {**default_settings(), "port": 28642})
        self.access = AccessManager(self.db, GRANTS)

    def _save_settings(self, **updates):
        value = {**self.settings, **updates}
        self.db.private_put(SETTINGS, value)
        self.settings = value

    def management(self):
        runtime = self.mcp_runtime
        return {"mcp": {"enabled": self.settings["mcpEnabled"],
            "running": bool(runtime and runtime.running), "port": self.settings["port"],
            "url": f"http://127.0.0.1:{self.settings['port']}/mcp", "errorCode": self.mcp_error},
            "clients": [g.view() for g in self.access.all() if g.account_id == self.account_id],
            "storage": {"paused": self.settings["storagePaused"], "path": str(self.db.path),
                        "counts": self.db.provider_data_counts(self.provider, self.account_id) if self.account_id else {}, "retention": "until_deleted"},
            "accountAvailable": bool(self.account_id)}

    def register_client(self, request):
        # Only the current provider catalog can be newly granted.
        grant, token = self.access.create(name=request["name"], account_id=self.account_id,
            conversations=request["conversationIds"], read=request["read"], send=request["send"],
            available={r.id for r in self._current_records()})
        return {"client": grant.view(), "token": token, "url": self.management()["mcp"]["url"]}

    async def dispatch(self, request):
        if isinstance(request, dict) and request.get("op") in {"slack_login_start", "slack_login_status", "slack_login_cancel"}:
            if set(request) != {"op"}:
                raise AppError("INVALID_INPUT")
            self._initialize()
            if request["op"] == "slack_login_start": return await self.start_slack_login()
            if request["op"] == "slack_login_cancel": return await self.cancel_login()
            try:
                self.oauth_factory(self.credentials).check_configuration()
                configured = True
            except AppError as exc:
                if exc.code != 'SLACK_OAUTH_NOT_CONFIGURED':
                    raise
                configured = False
            return {**self.login_state, "configured": configured}
        if isinstance(request, dict) and request.get("op") == "slack_profile":
            if set(request) not in ({"op", "conversationId"}, {"op", "conversationId", "messageId"}):
                raise AppError("INVALID_INPUT")
            self._initialize()
            return self.slack_profile(request["conversationId"], request.get("messageId"))
        allowed = {"ping", "snapshot", "connect", "select", "messages", "refresh", "stop", "search",
                   "send", "send_image", "attachment_media", "management", "mcp_configure", "mcp_register", "mcp_revoke", "storage_pause",
                   "storage_delete_preview", "storage_delete", "messages_older", "mark_read", "history_backfill"}
        if not isinstance(request, dict) or request.get("op") not in allowed:
            raise AppError("INVALID_INPUT")
        try:
            return await super().dispatch(request)
        except AppError as exc:
            if exc.code in {"CREDENTIALS_MISSING", "CREDENTIALS_INVALID"}:
                raise AppError("SLACK_LOGIN_REQUIRED") from None
            raise

    async def select_remote(self, conversation):
        await self.connector.select_conversation(conversation)

    def message_view(self, message):
        return {**super().message_view(message), 'replyToMessageId':
            replace(message, provider_message_id=message.reply_to_message_id).id if message.reply_to_message_id else None}

    def messages(self, identity, before=None):
        result = super().messages(identity, before=before)
        record = self._record(identity)
        result["messages"] = [{**self.message_view(m), "profile": {"conversationId": identity,
            "messageId": m.id}} for m in self.db.list_messages(
            "slack", self.account_id, record.conversation.id, limit=100, before=before)]
        result["coverage"] = "paged_channel_and_thread_history; workspace_retention_applies"
        result["receivingMode"] = "polling"
        return result

    async def _fetch_selected_history(self):
        return await self.connector.fetch_recent(self.history_limit)

    def persist_history(self, batch):
        if batch.errors:
            raise AppError(batch.errors[0])
        if (batch.provider != "slack" or not batch.live or batch.normalization_errors
                or batch.conversations_requested != 1 or batch.conversations_fetched != 1
                or len(batch.conversations) != 1):
            raise AppError("BAD_RESPONSE")
        record = self._record(self.selected_id)
        expected = (self.provider, self.account_id, record.conversation.id)
        actual = batch.conversations[0]
        if ((actual.provider, actual.account_id, actual.conversation.id) != expected
                or any((m.provider, m.account_id, m.conversation_id) != expected for m in batch.messages)):
            raise AppError("BAD_RESPONSE")
        receipt = HistorySyncReceipt(*expected, completed_at=datetime.now(timezone.utc),
            requested_limit=batch.requested_limit, raw_items=batch.raw_items,
            stored_messages=len(batch.messages), excluded_events=batch.excluded_events,
            history_limited=batch.history_limited)
        return receipt, self.db.upsert(batch.messages, conversations=[record], sync_receipts=[receipt])

    def start_watch(self):
        if self.supports_all_sync():
            self.start_all_sync()
            return
        self.watch_generation += 1
        self.receiving = "waiting"
        self.retry_attempt = 0
        self.watch_task = asyncio.create_task(self._poll(self.watch_generation, self.selected_id))

    async def _poll(self, generation, identity):
        attempts, delay = 0, self.poll_interval
        while generation == self.watch_generation:
            await wait_for_retry(delay)
            try:
                async with self.operation_lock:
                    if generation != self.watch_generation or identity != self.selected_id:
                        return
                    await self.sync_selected()
                attempts, delay = 0, self.poll_interval
                self.retry_attempt = 0
                self.receiving, self.error_code = "waiting", None
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = exc.code if isinstance(exc, AppError) else "UNEXPECTED_ERROR"
                if code not in {"NETWORK_ERROR", "HTTP_ERROR", "RATE_LIMITED"}:
                    self.receiving, self.error_code = "error", code
                    self._notify("status", **self._status())
                    return
                slow_retry = attempts >= len(self.retry_delays)
                delay = self.reconnect_interval if slow_retry else self.retry_delays[attempts]
                if code == "RATE_LIMITED":
                    import time
                    cooldowns = getattr(self.connector.api, "cooldowns", {})
                    delay = max(delay, max(cooldowns.values(), default=0) - time.monotonic())
                attempts += 1
                self.retry_attempt = attempts
                self.receiving, self.error_code = "reconnecting", "SLACK_RECONNECT_WAITING" if slow_retry else code
            self._notify("status", **self._status())

    async def mcp_call(self, token, operation, arguments):
        if operation != "get_thread":
            return await super().mcp_call(token, operation, arguments)
        async with self.operation_lock:
            identity = arguments["conversation_id"]
            self.require_mcp(token, "read", identity)
            self.require_connected()
            self.require_storage()
            record = self._record(identity)
            root = next((m for m in self.db.list_messages("slack", self.account_id,
                record.conversation.id, limit=100) if m.id == arguments["message_id"]), None)
            if root is None or root.reply_to_message_id:
                raise AppError("INVALID_INPUT")
            batch = await self.connector.fetch_thread(record.conversation, root.provider_message_id, limit=15)
            self.require_mcp(token, "read", identity)
            self.require_storage()
            if batch.errors or batch.normalization_errors or any(
                    (m.provider, m.account_id, m.conversation_id) != ("slack", self.account_id, record.conversation.id)
                    for m in batch.messages):
                raise AppError("BAD_RESPONSE")
            self.db.upsert(batch.messages, conversations=[record])
            self._notify("messages_changed", conversationId=identity)
            return {"conversationId": identity, "messages": [self.message_view(m) for m in batch.messages],
                    "historyLimited": batch.history_limited, "limit": 15, "source": "slack_thread_fetch"}
