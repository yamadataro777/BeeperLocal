"""One-to-one X Chat and explicitly labelled legacy DM text via a private worker."""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from uuid import UUID

from ..errors import AppError
from ..models import Conversation, FetchBatch, SendResult, StoredConversation, UnifiedMessage, finish_batch
from .instagram import stop_process

MAX_FRAME = 8 * 1024 * 1024
DECIMAL = re.compile(r"[0-9]{1,128}\Z")
WIRE_ERRORS = frozenset({
    "X_LOGIN_REQUIRED", "X_UNLOCK_REQUIRED", "X_UNLOCK_FAILED", "X_KEY_CHANGED", "X_SETUP_REQUIRED",
    "X_VERIFY_FAILED", "X_ALREADY_RUNNING", "X_REQUEST_TIMEOUT", "X_REQUEST_FAILED", "X_PROTOCOL_ERROR",
    "X_SEND_UNKNOWN", "X_DIRECT_ONLY", "X_HISTORY_INCOMPLETE", "X_LOGIN_TIMEOUT", "X_LOGIN_CANCELLED",
    "X_LOGIN_FAILED", "ACCOUNT_CHANGED", "INVALID_INPUT", "LOCAL_DB_CORRUPT", "LOCAL_DB_UNAVAILABLE",
    "KEYCHAIN_UNAVAILABLE", "KEYCHAIN_AUTH_FAILED", "KEYCHAIN_ACCESS_DENIED", "KEYCHAIN_INTERACTION_REQUIRED",
    "KEYCHAIN_SIGNATURE_INVALID", "KEYCHAIN_SESSION_AUTH_FAILED", "KEYCHAIN_WRITE_FAILED",
})


def decimal(value):
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise AppError("BAD_RESPONSE")
    return value


def pair(raw, account):
    if not isinstance(raw, str) or not re.fullmatch(r"[0-9]{1,128}[:-][0-9]{1,128}", raw):
        raise AppError("X_DIRECT_ONLY")
    parts = re.split("[:-]", raw)
    if parts[0] == parts[1] or decimal(account) not in parts:
        raise AppError("BAD_RESPONSE")
    return parts


def selected_members(selected, account):
    raw = selected.locator.get('raw_id')
    if selected.kind == 'group':
        members = selected.locator.get('members')
        if not isinstance(raw, str) or not re.fullmatch(r'g[0-9]{1,128}', raw) or selected.id != 'xchat:' + raw or not isinstance(members, list) or not 1 <= len(members) <= 2000 or account not in members:
            raise AppError('BAD_RESPONSE')
        return [decimal(m) for m in members]
    parts = pair(raw, account)
    if selected.kind != 'dm' or selected.id != 'xchat:' + ':'.join(parts):
        raise AppError('BAD_RESPONSE')
    return parts


def conversation(item, account):
    if not isinstance(item, dict):
        raise AppError("BAD_RESPONSE")
    raw = item.get("raw_id")
    if item.get('kind') == 'group':
        if item.get('id') != raw or not isinstance(item.get('name'), str): raise AppError('BAD_RESPONSE')
        selected = Conversation('xchat:' + raw, item['name'] or 'Xグループ', 'group', {'raw_id': raw, 'members': item.get('members')})
        selected_members(selected, account)
        return selected
    parts = pair(raw, account)
    canonical = ":".join(parts)
    peer = next(value for value in parts if value != account)
    if item.get("id") != canonical or item.get("peer") != peer or not isinstance(item.get("name"), str):
        raise AppError("BAD_RESPONSE")
    return Conversation("xchat:" + canonical, item["name"] or "X Chat", "dm",
                        {"raw_id": raw, "peer_id": peer})


def normalize_x(raw, account, selected, *, allow_legacy=False):
    if not isinstance(raw, dict):
        raise AppError("X_VERIFY_FAILED")
    legacy = allow_legacy and raw.get("verified") is False and raw.get("source") == "legacy"
    if not legacy and (raw.get("verified") is not True or raw.get("source") == "legacy"):
        raise AppError("X_VERIFY_FAILED")
    members = selected_members(selected, account)
    sender = decimal(raw.get("sender_id"))
    if (raw.get("provider") != "x" or raw.get("account_id") != account
            or raw.get("conversation_id") != selected.id or sender not in members):
        raise AppError("X_VERIFY_FAILED")
    direction = "outgoing" if sender == account else "incoming"
    if raw.get("direction") != ("self" if direction == "outgoing" else "peer"):
        raise AppError("X_VERIFY_FAILED")
    try:
        identity = raw["provider_message_id"]
        if not isinstance(identity, str):
            raise ValueError()
        if legacy:
            if not identity.startswith("legacy:"):
                raise ValueError()
            original = identity[7:]
            if not DECIMAL.fullmatch(original) and str(UUID(original)) != original:
                raise ValueError()
        elif str(UUID(identity)) != identity:
            raise ValueError()
        stamp = raw.get("created_at_msec")
        if type(stamp) is not int or stamp <= 0 or not isinstance(raw.get("text"), str):
            raise ValueError()
        sent_at = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        return UnifiedMessage("x", account, selected.id, identity, sender, sent_at,
                              raw["text"], selected.title, direction=direction, attachments=raw.get("attachments", []), attachment_count=len(raw.get("attachments", [])))
    except (ValueError, TypeError, KeyError, OverflowError, OSError):
        raise AppError("BAD_RESPONSE") from None


class XAdapter:
    def __init__(self, command=None):
        self.command = command

    async def events(self, request, *, authorize=None):
        frozen = getattr(sys, "frozen", False)
        command = self.command or ([sys.executable, "--x-worker"] if frozen else
                                   [sys.executable, "-B", "-m", "beeperlocal.x_worker"])
        try:
            process = await asyncio.create_subprocess_exec(*command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL, limit=MAX_FRAME,
                cwd=None if frozen else str(Path(__file__).resolve().parents[2]), start_new_session=True,
                env={"PATH": os.defpath, "LANG": "en_US.UTF-8", "PYTHONDONTWRITEBYTECODE": "1",
                     "PYTHONNOUSERSITE": "1"})
        except OSError:
            raise AppError("X_ADAPTER_MISSING") from None
        operation = request["op"]

        async def write(value):
            frame = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            if len(frame) > MAX_FRAME:
                raise AppError("INVALID_INPUT")
            process.stdin.write(frame)
            await process.stdin.drain()

        try:
            if authorize:
                authorize()
            await write(request)
            while True:
                deadline = 940 if operation in {"login", "unlock"} else 170
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), deadline)
                    if not line:
                        raise AppError("X_SEND_UNKNOWN" if operation in {"send", "send_image"} else "X_REQUEST_FAILED")
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError, TimeoutError):
                    raise AppError("X_SEND_UNKNOWN" if operation in {"send", "send_image"} else "X_PROTOCOL_ERROR") from None
                kind = event.get("type")
                if kind == "error":
                    code = event.get("code")
                    raise AppError(code if code in WIRE_ERRORS else ("X_SEND_UNKNOWN" if operation in {"send", "send_image"} else "X_PROTOCOL_ERROR"))
                if kind not in {"result", "status", "history", "done", "auth_status"}:
                    raise AppError("X_SEND_UNKNOWN" if operation in {"send", "send_image"} else "X_PROTOCOL_ERROR")
                if kind == "auth_status" and operation not in {"login", "unlock"}:
                    raise AppError("X_PROTOCOL_ERROR")
                if kind == "history" and operation != "watch":
                    raise AppError("X_PROTOCOL_ERROR")
                yield event
                if kind == "history":
                    # Consumer normalizes + atomically saves the common-model
                    # batch before the worker is allowed to wait for another hint.
                    await write({"history_saved": True})
                if kind in {"result", "done"}:
                    return
        except (BrokenPipeError, ConnectionError, OSError):
            raise AppError("X_SEND_UNKNOWN" if operation in {"send", "send_image"} else "X_REQUEST_FAILED") from None
        finally:
            await stop_process(process)


class XConnector:
    def __init__(self, store, *, adapter=None):
        self.store, self.adapter = store, adapter or XAdapter()
        try:
            self.credentials = store.load("x")
        except AppError as exc:
            if exc.code != "CREDENTIALS_MISSING":
                raise
            self.credentials = {}
        self.account_id = self.credentials.get("account_id", "")
        if self.account_id:
            decimal(self.account_id)
        self.catalog = {}
        self.catalog_limited = True
        self.history_limited = True
        self.unsupported_legacy_count = 0
        self.legacy_message_count = 0

    def _check_account(self):
        try:
            current = self.store.load("x")
        except AppError as exc:
            if exc.code == "CREDENTIALS_MISSING" and not self.account_id:
                return
            raise
        if current.get("account_id", "") != self.account_id:
            raise AppError("ACCOUNT_CHANGED")

    async def _request(self, op, *, authorize=None, **values):
        self._check_account()
        if authorize:
            authorize()
        async with aclosing(self.adapter.events({"op": op, "account_id": self.account_id, **values},
                **({"authorize": authorize} if authorize else {}))) as stream:
            async for event in stream:
                if event["type"] != "result":
                    raise AppError("X_PROTOCOL_ERROR")
                return event
        raise AppError("X_REQUEST_FAILED")

    async def connect(self):
        result = await self._request("connect")
        account = decimal(result.get("account_id"))
        if self.account_id and account != self.account_id:
            raise AppError("ACCOUNT_CHANGED")
        try:
            current = self.store.load("x")
        except AppError as exc:
            if exc.code != "CREDENTIALS_MISSING":
                raise
            current = {}
        if current.get("account_id") not in {None, account}:
            raise AppError("ACCOUNT_CHANGED")
        self.account_id = account
        self.credentials = {"account_id": account, "selections": current.get("selections", [])}
        self.store.save("x", self.credentials)

    async def list_conversations(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise AppError("INVALID_INPUT")
        result = await self._request("conversations", limit=limit)
        raw = result.get("items")
        if not isinstance(raw, list) or len(raw) > limit or type(result.get("limited")) is not bool:
            raise AppError("BAD_RESPONSE")
        rows = [conversation(item, self.account_id) for item in raw]
        if len({row.id for row in rows}) != len(rows):
            raise AppError("BAD_RESPONSE")
        self.catalog_limited = result["limited"]
        self.catalog = {row.id:row for row in rows}
        return rows

    def selected_conversation(self):
        try:
            rows = self.credentials.get("selections", [])
            if not rows:
                raise AppError("NO_SELECTION")
            if not isinstance(rows, list) or len(rows) != 1:
                raise ValueError()
            selected = Conversation.from_selection(rows[0])
            selected_members(selected, self.account_id)
            return self.catalog.get(selected.id, selected)
        except (ValueError, TypeError, KeyError):
            raise AppError("CREDENTIALS_CORRUPT") from None

    async def select_conversation(self, selected):
        selected_members(selected, self.account_id)
        current = self.store.load("x")
        if current.get("account_id") != self.account_id:
            raise AppError("ACCOUNT_CHANGED")
        self.credentials = {**current, "selections": [selected.selection()]}
        self.store.save("x", self.credentials)

    def _history_batch(self, result, selected, limit):
        rows = result.get("messages")
        counts = [result.get(key) for key in ("raw_items", "excluded_events", "unsupported_legacy_count")]
        if (not isinstance(rows, list) or len(rows) > limit or any(type(n) is not int or n < 0 for n in counts)
                or counts[0] < len(rows) + counts[1] or counts[2] > counts[1]
                or type(result.get("history_limited")) is not bool):
            raise AppError("BAD_RESPONSE")
        messages = [normalize_x(row, self.account_id, selected, allow_legacy=True) for row in rows]
        legacy_count = result.get("legacy_message_count", 0)
        if (type(legacy_count) is not int or legacy_count != sum(m.provider_message_id.startswith("legacy:") for m in messages)):
            raise AppError("BAD_RESPONSE")
        batch = FetchBatch("x", True, limit, conversations_requested=1, conversations_fetched=1,
                           messages=messages, raw_items=counts[0], excluded_events=counts[1],
                           history_limited=result["history_limited"],
                           conversations=[StoredConversation("x", self.account_id, selected)])
        self.history_limited = batch.history_limited
        self.unsupported_legacy_count = counts[2]
        self.legacy_message_count = legacy_count
        return finish_batch(batch)

    async def fetch(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AppError("INVALID_INPUT")
        selected = self.selected_conversation()
        return self._history_batch(await self._request("history", conversation=selected.locator["raw_id"], limit=limit), selected, limit)

    async def fetch_page(self, selected, *, cursor=None):
        from ..desktop_sync import HistoryPage
        selected_members(selected, self.account_id)
        cursor = cursor or {}
        if set(cursor) - {'before'}: raise AppError('INVALID_INPUT')
        result = await self._request('history_page', conversation=selected.locator['raw_id'], before=cursor.get('before'))
        # Refresh membership from the authenticated conversation detail for group changes.
        if selected.kind == 'group':
            selected = Conversation(selected.id, selected.title, selected.kind, {**selected.locator, 'members': result.get('members')})
        batch = self._history_batch(result, selected, 3000)
        before = result.get('next_before')
        if before is not None and (not isinstance(before, str) or not DECIMAL.fullmatch(before)): raise AppError('BAD_RESPONSE')
        return HistoryPage(batch.conversations[0], batch.messages, cursor={'before':before} if before else None,
            complete=not result['history_limited'], deletions=result.get('deletions', []), coverage='verified_chat_and_legacy_text')

    async def download_attachment(self, selected, message_id, index):
        import base64
        selected_members(selected, self.account_id)
        result = await self._request('media', conversation=selected.locator['raw_id'], message_id=message_id, index=index)
        try:
            data = base64.b64decode(result['data'], validate=True)
            if len(data) > 4 * 1024 * 1024: raise ValueError()
            return data
        except (ValueError, KeyError, TypeError):
            raise AppError('BAD_RESPONSE') from None

    async def send_text(self, text):
        return await self._send_conversation(self.selected_conversation(), text)

    async def send_image_to(self, selected, image, *, authorize):
        selected_members(selected, self.account_id)
        result = await self._request('send_image', conversation=selected.locator['raw_id'], image=image.wire(), authorize=authorize)
        try:
            message = normalize_x(result.get('message'), self.account_id, selected)
            if message.direction != 'outgoing' or message.text or message.attachment_count != 1 or result.get('encrypted') is not True:
                raise AppError('BAD_RESPONSE')
        except AppError:
            raise AppError('X_SEND_UNKNOWN') from None
        return SendResult(message, encrypted=True)

    async def send_to(self, selected, text, *, authorize):
        selected_members(selected, self.account_id)
        # The worker verifies current membership and encryption keys before sending.
        return await self._send_conversation(selected, text, authorize=authorize)

    async def _send_conversation(self, selected, text, *, authorize=None):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 10000:
            raise AppError("INVALID_INPUT")
        result = await self._request("send", conversation=selected.locator["raw_id"], text=text, authorize=authorize)
        try:
            message = normalize_x(result.get("message"), self.account_id, selected)
            if message.direction != "outgoing" or message.text != text or result.get("encrypted") is not True:
                raise AppError("BAD_RESPONSE")
        except AppError:
            raise AppError("X_SEND_UNKNOWN") from None
        return SendResult(message, encrypted=True)

    async def watch(self, *, timeout=0, from_now=False, recovery_limit=100, persist_history=None, on_status=None):
        self._check_account()
        selected = self.selected_conversation()
        request = {"op": "watch", "account_id": self.account_id, "conversation": selected.locator["raw_id"],
                   "timeout": timeout, "limit": recovery_limit}
        async with aclosing(self.adapter.events(request)) as stream:
            async for event in stream:
                if event["type"] == "history":
                    batch = self._history_batch(event, selected, recovery_limit)
                    if persist_history:
                        persist_history(batch)
                    else:
                        for message in batch.messages:
                            yield message
                elif event["type"] == "status" and event.get("code") == "connected":
                    if on_status:
                        on_status("connected")
                elif event["type"] == "done":
                    return
                else:
                    raise AppError("X_PROTOCOL_ERROR")
