"""Instagram 1:1 text via the validated local instameow adapter.

Secrets and messages cross private pipes, never argv, files, environment or logs.
The SDK's GraphQL ID is canonical for both history, events and send results.
"""
from __future__ import annotations

import asyncio
from contextlib import aclosing
from datetime import datetime
import json
from pathlib import Path
import re
import sys

from ..errors import AppError
from ..models import Conversation, FetchBatch, SendResult, StoredConversation, UnifiedMessage, finish_batch

MAX_FRAME = 6 * 1024 * 1024
DECIMAL = re.compile(r"[1-9][0-9]{0,127}\Z")
WIRE_ERRORS = frozenset({
    "INVALID_INPUT", "BAD_RESPONSE", "ACCOUNT_CHANGED", "CREDENTIALS_MISSING",
    "CREDENTIALS_INVALID", "RATE_LIMITED", "IG_AUTH_ACTION_REQUIRED", "IG_PROTOCOL_ERROR",
    "IG_REQUEST_TIMEOUT", "IG_REQUEST_FAILED", "IG_SESSION_NOT_SAVED", "IG_DIRECT_ONLY",
    "IG_SEND_UNKNOWN", "IG_RESYNC_REQUIRED",
    "IG_PASSWORD_REJECTED", "IG_CODE_REJECTED", "IG_ACCOUNT_ACTION_REQUIRED", "IG_LOGIN_REJECTED",
})


def decimal_id(value):
    if not isinstance(value, str) or not DECIMAL.fullmatch(value):
        raise AppError("BAD_RESPONSE")
    return value


def conversation(raw):
    if not isinstance(raw, dict):
        raise AppError("BAD_RESPONSE")
    ident = decimal_id(raw.get("id"))
    title, long_id = raw.get("title"), raw.get("long_id", "")
    if not isinstance(title, str) or not isinstance(long_id, str):
        raise AppError("BAD_RESPONSE")
    if long_id:
        decimal_id(long_id)
    kind = raw.get('kind', 'dm')
    if kind not in {'dm', 'group'}:
        raise AppError('BAD_RESPONSE')
    locator = {"thread_id": ident, "long_id": long_id}
    from ..desktop_profiles import profile_reference
    picture = raw.get('picture_url', '')
    if profile_reference('instagram', {'picture_url': picture}):
        locator['picture_url'] = picture
    return Conversation(ident, title or "Instagram DM", kind, locator)


def timestamp(value):
    try:
        if not isinstance(value, str):
            raise ValueError()
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.utcoffset() is None or stamp.timestamp() <= 0:
            raise ValueError()
        return stamp
    except (ValueError, TypeError, OverflowError, OSError):
        raise AppError("BAD_RESPONSE") from None


def normalize_instagram(raw, account_id, own_fbid, selected):
    if not isinstance(raw, dict) or raw.get("thread_id") != selected.id:
        raise AppError("BAD_RESPONSE")
    ident, text = raw.get("id"), raw.get("text")
    sender = decimal_id(raw.get("sender_id"))
    if not isinstance(ident, str) or not ident or len(ident) > 4096 or not isinstance(text, str):
        raise AppError("BAD_RESPONSE")
    direction = "outgoing" if sender == own_fbid else "incoming"
    if raw.get("direction") != direction:
        raise AppError("BAD_RESPONSE")
    return UnifiedMessage(
        "instagram", decimal_id(account_id), selected.id, ident, sender,
        timestamp(raw.get("sent_at")), text, selected.title,
        edited_at=timestamp(raw["edited_at"]) if raw.get("edited_at") else None,
        direction=direction,
        attachments=raw.get('attachments', []), attachment_count=len(raw.get('attachments', [])),
    )


async def stop_process(process):
    if process.returncode is None:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
        try:
            await asyncio.wait_for(process.wait(), 3)
        except TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
    await process.wait()


class InstagramAdapter:
    def __init__(self, binary=None):
        if binary is None:
            binary = (Path(sys.executable).parent / "beeperlocal-ig" if getattr(sys, "frozen", False)
                      else Path(__file__).resolve().parents[2] / "bin" / "beeperlocal-ig")
        self.binary = str(binary)

    async def events(self, request, *, prompt=None, authorize=None):
        if not Path(self.binary).is_file():
            raise AppError("IG_ADAPTER_MISSING")
        try:
            process = await asyncio.create_subprocess_exec(
                self.binary, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL, limit=MAX_FRAME, start_new_session=True)
        except OSError:
            raise AppError("IG_ADAPTER_MISSING") from None
        operation = request["op"]
        succeeded = False
        streaming = False

        async def write(data):
            frame = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
            if len(frame) >= MAX_FRAME:
                raise AppError("INVALID_INPUT")
            process.stdin.write(frame)
            await process.stdin.drain()

        try:
            if authorize:
                authorize()
            await write(request)
            steps = 0
            while True:
                # Idle realtime streams are allowed; finite watches are bounded by their caller.
                deadline = None if operation == "watch" and streaming else (610 if operation == "login" else 80)
                try:
                    line = await asyncio.wait_for(process.stdout.readline(), deadline)
                    if not line:
                        break
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError, TimeoutError):
                    raise AppError("IG_SEND_UNKNOWN" if operation in {"send", "send_image"} else "IG_PROTOCOL_ERROR") from None
                kind = event.get("type")
                if kind == "error":
                    code = event.get("code")
                    raise AppError(code if code in WIRE_ERRORS else ("IG_SEND_UNKNOWN" if operation in {"send", "send_image"} else "IG_REQUEST_FAILED"))
                if kind == "auth_step":
                    steps += 1
                    if operation != "login" or prompt is None or steps > 30:
                        raise AppError("IG_AUTH_ACTION_REQUIRED")
                    await write({"input": await prompt(event.get("fields"))})
                    continue
                if kind not in {"session", "result", "status", "history", "message", "change", "done"}:
                    raise AppError("IG_SEND_UNKNOWN" if operation in {"send", "send_image"} else "IG_PROTOCOL_ERROR")
                yield event
                if kind == "status" and event.get("code") == "connected":
                    streaming = True
                if kind == "session":
                    # The consumer must persist to Keychain before resuming this generator.
                    if authorize:
                        authorize()
                    await write({"session_saved": True})
                if kind == "history" and operation == "watch":
                    await write({"history_saved": True})
                if kind in {"result", "done"}:
                    succeeded = True
                    break
            if not succeeded:
                raise AppError("IG_SEND_UNKNOWN" if operation in {"send", "send_image"} else "IG_REQUEST_FAILED")
        except (BrokenPipeError, ConnectionError, OSError):
            raise AppError("IG_SEND_UNKNOWN" if operation in {"send", "send_image"} else "IG_REQUEST_FAILED") from None
        finally:
            await stop_process(process)


def save_session(store, event, expected=None):
    account = decimal_id(event.get("account_id"))
    own_fbid = decimal_id(event.get("own_fbid"))
    session = event.get("session")
    if expected and account != expected:
        raise AppError("ACCOUNT_CHANGED")
    if not isinstance(session, dict) or not isinstance(session.get("cookies"), dict):
        raise AppError("BAD_RESPONSE")
    jar = session["cookies"]
    if (any(not isinstance(k, str) or not isinstance(v, str) for k, v in jar.items())
            or not all(jar.get(k) for k in ("sessionid", "csrftoken", "ds_user_id"))
            or jar["ds_user_id"] != account or not isinstance(session.get("www_claim", ""), str)):
        raise AppError("BAD_RESPONSE")
    try:
        current = store.load("instagram")
    except AppError as exc:
        if exc.code != "CREDENTIALS_MISSING":
            raise
        current = {}
    if expected and current.get("account_id") != expected:
        raise AppError("ACCOUNT_CHANGED")
    data = {"account_id": account, "own_fbid": own_fbid, "session": session,
            "selections": current.get("selections", []) if current.get("account_id") == account else []}
    store.save("instagram", data)
    return data


async def login_instagram(store, *, adapter=None, prompt=None):
    if prompt is None:
        from ..instagram_cli import auth_prompt
        prompt = auth_prompt
    adapter = adapter or InstagramAdapter()
    saved = None
    async with aclosing(adapter.events({"op": "login"}, prompt=prompt)) as stream:
        async for event in stream:
            if event["type"] == "session":
                saved = save_session(store, event)
            elif event["type"] == "result":
                if saved is None or event.get("account_id") != saved["account_id"]:
                    raise AppError("BAD_RESPONSE")
                return
            else:
                raise AppError("IG_PROTOCOL_ERROR")
    raise AppError("IG_REQUEST_FAILED")


class InstagramConnector:
    def __init__(self, store, *, adapter=None):
        self.store = store
        self.adapter = adapter or InstagramAdapter()
        self.credentials = store.load("instagram")
        self.account_id = decimal_id(self.credentials.get("account_id"))
        self.own_fbid = decimal_id(self.credentials.get("own_fbid"))
        self.history_limited = True
        self.catalog_limited = True
        self.last_event_source = ""
        self.connection_status = "disconnected"
        self.catalog = {}
        self.session_lock = asyncio.Lock()

    def selected_conversation(self):
        rows = self.credentials.get("selections")
        if not rows:
            raise AppError("NO_SELECTION")
        if not isinstance(rows, list) or len(rows) != 1:
            raise AppError("CREDENTIALS_CORRUPT")
        try:
            selected = Conversation.from_selection(rows[0])
        except (ValueError, KeyError, TypeError):
            raise AppError("CREDENTIALS_CORRUPT") from None
        if selected.kind not in {"dm", "group"} or selected.locator.get("thread_id") != selected.id:
            raise AppError("CREDENTIALS_CORRUPT")
        decimal_id(selected.id)
        return selected

    async def _events(self, op, *, on_status=None, authorize=None, **kwargs):
        await self.session_lock.acquire()
        locked = True
        try:
            current = self.store.load("instagram")
            if current.get("account_id") != self.account_id:
                raise AppError("ACCOUNT_CHANGED")
            self.credentials = current
            request = {"op": op, "account_id": self.account_id, "session": current.get("session"), **kwargs}
            if authorize:
                authorize()  # Recheck after the session lock, before issuing the mutation.
            async with aclosing(self.adapter.events(request, **({"authorize": authorize} if authorize else {}))) as stream:
                async for event in stream:
                    if event["type"] == "session":
                        if event.get("own_fbid") != self.own_fbid:
                            raise AppError("ACCOUNT_CHANGED")
                        self.credentials = save_session(self.store, event, self.account_id)
                        if locked:
                            self.session_lock.release()
                            locked = False
                    elif event["type"] == "status":
                        if event.get("code") not in {"connected", "reconnecting"}:
                            raise AppError("IG_PROTOCOL_ERROR")
                        self.connection_status = event["code"]
                        if on_status:
                            on_status(self.connection_status)
                    else:
                        yield event
        finally:
            if locked:
                self.session_lock.release()

    async def _request(self, op, **kwargs):
        async with aclosing(self._events(op, **kwargs)) as stream:
            async for event in stream:
                if event["type"] != "result":
                    raise AppError("IG_PROTOCOL_ERROR")
                return event
        raise AppError("IG_REQUEST_FAILED")

    async def connect(self):
        result = await self._request("whoami")
        if result.get("account_id") != self.account_id or result.get("own_fbid") != self.own_fbid:
            raise AppError("ACCOUNT_CHANGED")

    async def list_conversations(self, limit=100):
        if type(limit) is not int or not 1 <= limit <= 10000:
            raise AppError("INVALID_INPUT")
        rows, seen, cursor = {}, set(), ''
        while len(rows) < limit:
            kwargs = {'limit': min(limit - len(rows), 100)}
            if cursor: kwargs['cursor'] = cursor
            result = await self._request("conversations", **kwargs)
            raw = result.get("conversations")
            if not isinstance(raw, list) or len(raw) > kwargs['limit'] or type(result.get("limited")) is not bool:
                raise AppError("BAD_RESPONSE")
            for item in raw:
                row = conversation(item)
                rows[row.id] = row
                self.catalog[row.id] = row
            self.catalog_limited = result['limited']
            cursor = result.get('next_cursor', '')
            if not isinstance(cursor, str) or len(cursor) > 16384 or cursor in seen:
                raise AppError('PAGINATION_STALLED')
            if not cursor: break
            seen.add(cursor)
            if len(seen) > 1000: raise AppError('SCAN_LIMIT_REACHED')
        return list(rows.values())[:limit]

    async def fetch_page(self, selected, *, cursor=None):
        from ..desktop_sync import HistoryPage
        kwargs = {'thread_id': selected.id, 'limit': 20}
        if cursor:
            if set(cursor) != {'after'} or not isinstance(cursor['after'], str) or len(cursor['after']) > 16384:
                raise AppError('INVALID_INPUT')
            kwargs['cursor'] = cursor['after']
        result = await self._request('history', **kwargs)
        batch = self._history_batch(result, selected, 20)
        after = result.get('next_cursor', '')
        if not isinstance(after, str) or len(after) > 16384:
            raise AppError('BAD_RESPONSE')
        return HistoryPage(batch.conversations[0], batch.messages, cursor={'after': after} if after else None,
                           complete=not after and result.get('page_complete', not batch.history_limited) is True)

    async def select_conversation(self, selected):
        # Recheck membership and one-to-one type server-side before saving a selection.
        result = await self._request("history", thread_id=decimal_id(selected.id), limit=1)
        verified = conversation(result.get("conversation"))
        if verified.id != selected.id:
            raise AppError("BAD_RESPONSE")
        self.credentials["selections"] = [verified.selection()]
        self.store.save("instagram", self.credentials)

    def _history_batch(self, result, selected, limit):
        verified = conversation(result.get("conversation"))
        raw = result.get("messages")
        if verified.id != selected.id or not isinstance(raw, list) or len(raw)>limit:
            raise AppError("BAD_RESPONSE")
        counts = (result.get("raw_items"), result.get("excluded_events"))
        if (any(type(n) is not int or n < 0 for n in counts) or counts[0] > limit
                or counts[0] != len(raw) + counts[1] or type(result.get("history_limited")) is not bool):
            raise AppError("BAD_RESPONSE")
        batch = FetchBatch("instagram", True, limit, conversations_requested=1, conversations_fetched=1,
                           raw_items=counts[0], excluded_events=counts[1], history_limited=result["history_limited"],
                           conversations=[StoredConversation("instagram", self.account_id, verified)])
        batch.messages = [normalize_instagram(row, self.account_id, self.own_fbid, verified) for row in raw]
        self.history_limited = batch.history_limited
        return finish_batch(batch)

    async def fetch(self, limit=50):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AppError("INVALID_INPUT")
        selected = self.selected_conversation()
        result = await self._request("history", thread_id=selected.id, limit=limit)
        return self._history_batch(result, selected, limit)

    async def send_text(self, text):
        return await self._send_conversation(self.selected_conversation(), text)

    async def send_image_to(self, selected, image, *, authorize):
        from dataclasses import replace
        if selected.kind not in {'dm', 'group'} or selected.locator.get('thread_id') != decimal_id(selected.id):
            raise AppError('INVALID_INPUT')
        result = await self._request('send_image', thread_id=decimal_id(selected.id), image=image.wire(), authorize=authorize)
        try:
            message = normalize_instagram(result.get('message'), self.account_id, self.own_fbid, selected)
            if message.direction != 'outgoing' or result.get('encrypted') is not False:
                raise AppError('BAD_RESPONSE')
            return SendResult(replace(message, attachment_count=1), encrypted=False)
        except AppError:
            raise AppError('IG_SEND_UNKNOWN') from None

    async def send_to(self, selected, text, *, authorize):
        if selected.kind not in {"dm", "group"} or selected.locator.get("thread_id") != decimal_id(selected.id):
            raise AppError("INVALID_INPUT")
        # Confirm current access without persisting a new GUI selection.
        result = await self._request("history", thread_id=selected.id, limit=1)
        verified = conversation(result.get("conversation"))
        if verified.id != selected.id:
            raise AppError("BAD_RESPONSE")
        return await self._send_conversation(verified, text, authorize=authorize)

    async def _send_conversation(self, selected, text, *, authorize=None):
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 4000:
            raise AppError("INVALID_INPUT")
        result = await self._request("send", thread_id=selected.id, text=text, authorize=authorize)
        try:
            message = normalize_instagram(result.get("message"), self.account_id, self.own_fbid, selected)
            if message.direction != "outgoing" or message.text != text or result.get("encrypted") is not False:
                raise AppError("BAD_RESPONSE")
        except AppError:
            raise AppError("IG_SEND_UNKNOWN") from None
        # E2EE is not claimed. Core persistence is separately AES-GCM encrypted.
        return SendResult(message, encrypted=False)

    async def watch(self, *, timeout=300, from_now=False, recovery_limit=100, persist_history=None, on_status=None, all_conversations=False, on_change=None):
        if type(timeout) is not int or not 0 <= timeout <= 600 or type(recovery_limit) is not int or not 1 <= recovery_limit <= 100:
            raise AppError("INVALID_INPUT")
        selected = self.selected_conversation()
        self.catalog[selected.id] = selected
        extra = {"all_conversations": True} if all_conversations else {}
        try:
            async with aclosing(self._events("watch", **extra, thread_id=selected.id, timeout=timeout, from_now=from_now, limit=recovery_limit, on_status=on_status)) as stream:
                async for event in stream:
                    if event["type"] == "history":
                        batch = self._history_batch(event, selected, recovery_limit)
                        self.last_event_source = "recovery"
                        if persist_history is not None:
                            persist_history(batch)
                        else:
                            for message in batch.messages:
                                yield message
                    elif event["type"] == "message" and event.get("source") == "realtime":
                        self.last_event_source = "realtime"
                        target = self.catalog.get(event.get('message', {}).get('thread_id')) if all_conversations else selected
                        if target is not None:
                            yield normalize_instagram(event.get("message"), self.account_id, self.own_fbid, target)
                    elif event['type'] == 'change':
                        target = self.catalog.get(event.get('thread_id')) if all_conversations else selected
                        if target and target.id == event.get('thread_id') and on_change:
                            if (event.get('action') not in {'edit','delete'} or not isinstance(event.get('message_id'), str)
                                    or not 1 <= len(event['message_id']) <= 4096):
                                raise AppError('BAD_RESPONSE')
                            on_change(target, event)
                    elif event["type"] == "done":
                        return
                    else:
                        raise AppError("IG_PROTOCOL_ERROR")
        finally:
            self.connection_status = "disconnected"
