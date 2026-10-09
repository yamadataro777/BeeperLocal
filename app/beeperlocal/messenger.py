"""Private Messenger IPC. Device keys stay in native Keychain."""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import sys
from uuid import uuid4

from .connectors.instagram import stop_process
from .credentials import _backend
from .errors import AppError
from .keychain_diagnostics import failure_code
from .models import Conversation, StoredConversation, UnifiedMessage, SendResult
from .reporting import private_directory

STATE_DIR = Path.home() / "Library/Application Support/BeeperLocalMessengerIntegration"
SERVICE = "BeeperLocalMessengerIntegration.v1"
# Continue using the verified device identity in its original item (no copy/reset).
DEVICE_SERVICE = "local.beeperlocal.messenger-verification.v1"
DEVICE_ACCOUNT = "bounded-receive-state"
MAX_FRAME = 6 * 1024 * 1024
DECIMAL = re.compile(r"[1-9][0-9]{0,127}\Z")
JID = re.compile(r"[1-9][0-9]{0,127}@msgr\Z")
ERRORS = {
    "registration_result_unknown": "MESSENGER_REGISTRATION_UNKNOWN",
    "login_required": "MESSENGER_LOGIN_REQUIRED", "inbox_failed": "MESSENGER_AUTH_FAILED",
    "account_mismatch": "ACCOUNT_CHANGED", "device_restore_failed": "MESSENGER_DEVICE_INVALID",
    "persistence_failed": "MESSENGER_PERSIST_FAILED", "decrypt_failed": "MESSENGER_DECRYPT_FAILED",
    "provider_rejected": "MESSENGER_AUTH_FAILED", "connection_lost": "MESSENGER_CONNECTION_LOST",
}


def validate_state(value):
    if not isinstance(value, dict) or type(value.get("version")) is not int or value["version"] != 1:
        raise AppError("MESSENGER_DEVICE_INVALID")
    if value.get("messages", {}) != {}:
        raise AppError("MESSENGER_DEVICE_INVALID")
    cookies = value.get("cookies")
    if (not isinstance(cookies, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in cookies.items())
            or not DECIMAL.fullmatch(cookies.get("c_user", ""))
            or any(not cookies.get(key) for key in ("xs", "datr"))
            or not isinstance(value.get("device_db", ""), str)
            or type(value.get("registration_pending", False)) is not bool):
        raise AppError("MESSENGER_DEVICE_INVALID")
    encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":"))
    if len(encoded.encode()) > MAX_FRAME - 4096:
        raise AppError("MESSENGER_STATE_LIMIT")
    return encoded


class DeviceStore:
    def __init__(self, backend=None):
        self.backend = backend or _backend()

    def load(self):
        try:
            raw = self.backend.get_password(DEVICE_SERVICE, DEVICE_ACCOUNT)
        except Exception as exc:
            raise AppError(failure_code(exc)) from None
        if raw is None:
            raise AppError("MESSENGER_LOGIN_REQUIRED")
        try:
            state = json.loads(raw)
        except (ValueError, TypeError):
            raise AppError("MESSENGER_DEVICE_INVALID") from None
        validate_state(state)
        return state

    def save(self, state):
        encoded = validate_state(state)
        try:
            self.backend.set_password(DEVICE_SERVICE, DEVICE_ACCOUNT, encoded)
            if self.backend.get_password(DEVICE_SERVICE, DEVICE_ACCOUNT) != encoded:
                raise RuntimeError()
        except Exception as exc:
            raise AppError(failure_code(exc, writing=True)) from None


def helper(name):
    candidates = [Path(sys.executable).parent / name, Path(__file__).resolve().parents[1] / "bin" / name]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    raise AppError("MESSENGER_ADAPTER_MISSING")


@contextmanager
def session_lock(directory=STATE_DIR):
    private_directory(directory)
    # Also exclude the original probe during source-tree development. Both use the same Keychain item.
    paths = [directory / "session.lock"]
    probe = Path(__file__).resolve().parents[2] / "workstreams/messenger-verification/probe.lock"
    if probe.parent.is_dir():
        paths.append(probe)
    handles = []
    try:
        for path in paths:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            handles.append(fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise AppError("MESSENGER_ALREADY_RUNNING")
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AppError("MESSENGER_ALREADY_RUNNING") from None
        yield
    finally:
        for fd in reversed(handles):
            os.close(fd)


def normalize_checkpoint(event, account, existing=()):
    """Validate the entire batch before any DB write. Never guess an E2EE thread mapping."""
    rows, catalog = event.get("messages"), event.get("conversations")
    rows = [] if rows is None else rows
    catalog = [] if catalog is None else catalog
    if not isinstance(rows, list) or len(rows) > 200 or not isinstance(catalog, list) or len(catalog) > 500:
        raise AppError("MESSENGER_PROTOCOL_ERROR")
    records = {r.conversation.id: r for r in existing}
    changed = {}
    for raw in catalog:
        if (not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not JID.fullmatch(raw["id"])
                or not isinstance(raw.get("title"), str) or len(raw["title"]) > 4096):
            raise AppError("MESSENGER_PROTOCOL_ERROR")
        c = Conversation(raw["id"], raw["title"] or "Messengerの会話", "dm", {})
        records[c.id] = changed[c.id] = StoredConversation("messenger", account, c)
    messages = []
    for raw in rows:
        if (not isinstance(raw, dict) or raw.get("provider") != "messenger" or raw.get("account") != account
                or not isinstance(raw.get("conversation"), str) or not JID.fullmatch(raw["conversation"])
                or not isinstance(raw.get("id"), str) or not 1 <= len(raw["id"]) <= 4096
                or not isinstance(raw.get("text"), str) or len(raw["text"].encode()) > 256 * 1024
                or type(raw.get("timestamp")) is not int or raw["timestamp"] <= 0):
            raise AppError("MESSENGER_PROTOCOL_ERROR")
        sender, direction = raw.get("sender"), raw.get("direction")
        if direction not in {"incoming", "outgoing", "unknown"} or not isinstance(sender, str) or not sender:
            raise AppError("MESSENGER_PROTOCOL_ERROR")
        c = records.get(raw["conversation"])
        if c is None:
            c = StoredConversation("messenger", account, Conversation(raw["conversation"], "Messengerの会話", "dm", {}))
            records[c.conversation.id] = changed[c.conversation.id] = c
        try:
            messages.append(UnifiedMessage("messenger", account, c.conversation.id, raw["id"], sender,
                datetime.fromtimestamp(raw["timestamp"], timezone.utc), raw["text"], c.conversation.title, direction=direction))
        except (ValueError, TypeError, OverflowError, OSError):
            raise AppError("MESSENGER_PROTOCOL_ERROR") from None
    return messages, list(changed.values())


class MessengerSession:
    def __init__(self, *, device_store=None, command=None, login_command=None, lock=session_lock):
        self.store = device_store or DeviceStore()
        self.command, self.login_command, self.lock = command, login_command, lock
        self.process = None
        self.pending = {}
        self.write_lock = asyncio.Lock()

    async def send_text(self, conversation, text, account, *, authorize=None):
        if (not isinstance(conversation, str) or not JID.fullmatch(conversation)
                or not isinstance(text, str) or not text.strip() or len(text) > 4000):
            raise AppError("INVALID_INPUT")
        return await self._send(conversation, text, account, authorize=authorize)

    async def send_image(self, conversation, image, account, *, authorize=None):
        if not isinstance(conversation, str) or not JID.fullmatch(conversation):
            raise AppError("INVALID_INPUT")
        return await self._send(conversation, '', account, image=image, authorize=authorize)

    async def _send(self, conversation, text, account, *, image=None, authorize=None):
        if self.process is None:
            raise AppError("MESSENGER_CONNECTION_LOST")
        request_id = str(uuid4())
        future = asyncio.get_running_loop().create_future()
        self.pending[request_id] = future
        try:
            value = {"op": "send_image" if image else "send", "request_id": request_id, "conversation": conversation}
            value.update({'image': image.wire()} if image else {'text': text})
            await self._write(self.process, value, authorize=authorize)
            raw = await asyncio.wait_for(future, 90)
            rows, _ = normalize_checkpoint({"messages": [raw]}, account)
            message = rows[0]
            if (message.conversation_id, message.direction, message.text) != (conversation, "outgoing", text):
                raise AppError("MESSENGER_SEND_UNKNOWN")
            return SendResult(replace(message, attachment_count=1) if image else message, encrypted=True)
        except (TimeoutError, BrokenPipeError, ConnectionError, OSError):
            raise AppError("MESSENGER_SEND_UNKNOWN") from None
        finally:
            self.pending.pop(request_id, None)

    async def _spawn(self, command):
        try:
            return await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_FRAME,
                env={"PATH": os.defpath, "LANG": "en_US.UTF-8"}, start_new_session=True)
        except OSError:
            raise AppError("MESSENGER_ADAPTER_MISSING") from None

    async def _write(self, process, value, *, authorize=None):
        data = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode() + b"\n"
        if len(data) > MAX_FRAME:
            raise AppError("MESSENGER_STATE_LIMIT")
        async with self.write_lock:
            if authorize:
                authorize()  # Revocation or a storage pause can occur while waiting for an ACK writer.
            process.stdin.write(data)
            await process.stdin.drain()

    async def _read(self, process, timeout):
        try:
            line = await asyncio.wait_for(process.stdout.readline(), timeout)
            if not line:
                raise AppError("MESSENGER_CONNECTION_LOST")
            if len(line) > MAX_FRAME or not line.endswith(b"\n"):
                raise ValueError()
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except TimeoutError:
            raise AppError("MESSENGER_CONNECTION_LOST") from None
        except (ValueError, UnicodeError):
            raise AppError("MESSENGER_PROTOCOL_ERROR") from None

    def _load_existing(self, *, account, require_device):
        try:
            state = self.store.load()
        except AppError as exc:
            if exc.code == "MESSENGER_LOGIN_REQUIRED" and (account or require_device):
                raise AppError("MESSENGER_DEVICE_INVALID") from None
            raise
        if require_device and not state.get("device_db"):
            raise AppError("MESSENGER_DEVICE_INVALID")
        return state

    async def watch(self, persist, *, account="", require_device=False):
        with self.lock():
            state = self._load_existing(account=account, require_device=require_device)
            if state.get("registration_pending"):
                raise AppError("MESSENGER_REGISTRATION_UNKNOWN")
            actual = state["cookies"]["c_user"]
            if account and account != actual:
                raise AppError("ACCOUNT_CHANGED")
            process = await self._spawn(self.command or [helper("beeperlocal-messenger")])
            try:
                await self._write(process, {"op": "watch", "state": state})
                while True:
                    event = await self._read(process, 120)
                    if event.get("kind") == "checkpoint":
                        updated = event.get("state")
                        validate_state(updated)
                        if updated["cookies"]["c_user"] != actual or (state.get("device_db") and not updated.get("device_db")):
                            raise AppError("ACCOUNT_CHANGED")
                        persist(event, actual)  # AES-GCM SQLite commit BEFORE keychain and provider ACK.
                        self.store.save(updated)
                        state = updated
                        await self._write(process, {"ok": True})
                    elif event.get("kind") == "status":
                        code = event.get("code")
                        if code == "connected":
                            self.process = process
                            yield "connected"
                        elif code != "heartbeat":
                            raise AppError(ERRORS.get(code, "MESSENGER_PROTOCOL_ERROR"))
                    elif event.get("kind") == "send_result":
                        future = self.pending.get(event.get("request_id"))
                        if future is not None and not future.done():
                            if event.get("message") is None:
                                future.set_exception(AppError("MESSENGER_SEND_UNKNOWN"))
                            else:
                                future.set_result(event["message"])
                    else:
                        raise AppError("MESSENGER_PROTOCOL_ERROR")
            except (BrokenPipeError, ConnectionError, OSError):
                raise AppError("MESSENGER_CONNECTION_LOST") from None
            finally:
                self.process = None
                for future in self.pending.values():
                    if not future.done(): future.set_exception(AppError("MESSENGER_SEND_UNKNOWN"))
                await stop_process(process)

    async def login(self, account="", *, require_device=False):
        with self.lock():
            try:
                previous = self._load_existing(account=account, require_device=require_device)
            except AppError as exc:
                if exc.code != "MESSENGER_LOGIN_REQUIRED":
                    raise
                previous = None
            if previous and previous.get("registration_pending"):
                raise AppError("MESSENGER_REGISTRATION_UNKNOWN")
            expected = previous["cookies"]["c_user"] if previous else account
            if account and expected != account:
                raise AppError("ACCOUNT_CHANGED")
            process = await self._spawn(self.login_command or [helper("beeperlocal-messenger-login")])
            try:
                await self._write(process, {"op": "web_login", "protocol": 1})
                result = await self._read(process, 930)
                if result.get("ok") is not True:
                    raise AppError("MESSENGER_LOGIN_CANCELLED")
                updated = {**(previous or {"version": 1}), "cookies": result.get("cookies")}
                validate_state(updated)
                actual = updated["cookies"]["c_user"]
                if expected and actual != expected:
                    raise AppError("ACCOUNT_CHANGED")
                self.store.save(updated)  # Refresh cookies only; keep device identity and unknown-registration guard.
                return actual
            finally:
                await stop_process(process)
