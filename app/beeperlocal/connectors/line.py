"""Mac-native adapter for the installed, validated line-cli v0.4.0.

Only JSON crosses the private subprocess pipes. Session/E2EE remain in line-cli.
Never print subprocess arguments, output, or exception details.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import shutil
import sys

from ..credentials import CredentialStore
from ..models import StoredConversation
from ..errors import AppError
from ..models import Conversation, FetchBatch, SendResult, UnifiedMessage, finish_batch

# Preserve case: modern IDs are opaque base64url, legacy IDs are lowercase hex.
DIRECT_MID = re.compile(r"(?:[uU][A-Za-z0-9_-]{43}|u[0-9a-f]{32})\Z")
MAX_EVENT_BYTES = 1024 * 1024
MAX_IMAGE_BYTES = 20 * 1024 * 1024


def direct_mid(value) -> str:
    if not isinstance(value, str) or not DIRECT_MID.fullmatch(value):
        raise AppError("LINE_DIRECT_MID_REQUIRED")
    return value


def identity(profile) -> str:
    if not isinstance(profile, dict):
        raise AppError("BAD_RESPONSE")
    return direct_mid(profile.get("mid"))


def normalize_line(raw, account_id: str, conversation: Conversation) -> UnifiedMessage | None:
    if not isinstance(raw, dict) or type(raw.get("content_type")) is not int:
        raise AppError("BAD_RESPONSE")
    kind = raw["content_type"]
    if kind not in {0, 1, 7}:
        return None
    if kind == 0 and raw.get("status") not in {"plaintext", "decrypted"}:
        raise AppError("LINE_DECRYPT_FAILED")
    media = None
    if kind in {1, 7}:
        media = {"kind": "image" if kind == 1 else "sticker"}
        # Older bundled CLIs mark stickers unsupported and omit their metadata.
        sticker_id = raw.get("sticker_id")
        if kind == 7 and isinstance(sticker_id, str) and re.fullmatch(r"[0-9]{1,20}", sticker_id):
            media["sticker_id"] = sticker_id
    sender, recipient = raw.get("from"), raw.get("to")
    if (sender, recipient) == (account_id, conversation.id):
        direction = "outgoing"
    elif (sender, recipient) == (conversation.id, account_id):
        direction = "incoming"
    else:
        raise AppError("BAD_RESPONSE")
    message_id, text = raw.get("id"), raw.get("text")
    if media:
        text = "画像" if kind == 1 else "スタンプ"
    if not isinstance(message_id, str) or not message_id or not isinstance(text, str):
        raise AppError("BAD_RESPONSE")
    try:
        stamp = raw["created_time"]
        if isinstance(stamp, bool) or not isinstance(stamp, (int, str)) or not re.fullmatch(r"[0-9]+", str(stamp)):
            raise ValueError()
        if int(stamp) <= 0:
            raise ValueError()
        sent_at = datetime.fromtimestamp(int(stamp) / 1000, timezone.utc)
    except (KeyError, ValueError, OverflowError, OSError):
        raise AppError("BAD_RESPONSE") from None
    return UnifiedMessage("line", account_id, conversation.id, message_id, sender,
                          sent_at, text, conversation.title, direction=direction,
                          attachment_count=1 if media else 0, media=media)


async def stop_process(process) -> None:
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


class LineCLI:
    def __init__(self):
        if sys.platform != "darwin":
            raise AppError("UNSUPPORTED_PLATFORM")
        bundled = [Path(sys.executable).parent / "line"] if getattr(sys, "frozen", False) else [Path(__file__).resolve().parents[2] / "desktop/src-tauri/binaries/line-aarch64-apple-darwin"]
        self.binary = next((str(p) for p in (*bundled, Path("/opt/homebrew/bin/line"), Path("/usr/local/bin/line"))
                            if p.is_file()), None) or shutil.which("line")
        if not self.binary:
            raise AppError("LINE_CLI_MISSING")

    async def _start(self, *args, input_pipe=False):
        try:
            return await asyncio.create_subprocess_exec(
                self.binary, *args, stdin=asyncio.subprocess.PIPE if input_pipe else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                limit=MAX_EVENT_BYTES, start_new_session=True)
        except OSError:
            raise AppError("LINE_CLI_MISSING") from None

    async def request(self, *args, text=None, data=None, mutation=False, allow_failure=False):
        # Exactly one spawn/attempt, including ambiguous send failures.
        if text is not None and data is not None:
            raise AppError('INVALID_INPUT')
        process = await self._start(*args, input_pipe=text is not None or data is not None)
        try:
            try:
                stdout, _ = await asyncio.wait_for(
                    process.communicate(text.encode("utf-8") if text is not None else data), 90 if data is not None else 60)
                if process.returncode != 0 and not allow_failure:
                    raise ValueError()
                return json.loads(stdout)
            except (ValueError, UnicodeError, TimeoutError, OSError):
                raise AppError("LINE_SEND_UNKNOWN" if mutation else "LINE_REQUEST_FAILED") from None
        finally:
            await stop_process(process)

    async def login_events(self, *, replace=False):
        args = ["login", "--qr", "--json"] + (["--force"] if replace else [])
        process = await self._start(*args)
        try:
            while raw := await process.stdout.readline():
                try:
                    event = json.loads(raw)
                    if not isinstance(event, dict): raise ValueError()
                except (ValueError, UnicodeError):
                    raise AppError("LINE_LOGIN_FAILED") from None
                yield event
            if await process.wait() != 0:
                raise AppError("LINE_LOGIN_FAILED")
        finally:
            await stop_process(process)

    async def download_image(self, conversation_id, message_id):
        direct_mid(conversation_id)
        if not isinstance(message_id, str) or not re.fullmatch(r"[0-9]{1,32}", message_id):
            raise AppError("INVALID_INPUT")
        process = await self._start("download", conversation_id, "--message", message_id, "--output", "-")
        try:
            async with asyncio.timeout(130):
                data = bytearray()
                while chunk := await process.stdout.read(64 * 1024):
                    data.extend(chunk)
                    if len(data) > MAX_IMAGE_BYTES:
                        raise AppError("LINE_MEDIA_UNAVAILABLE")
                if await process.wait() != 0 or not data:
                    raise AppError("LINE_MEDIA_UNAVAILABLE")
                return bytes(data)
        except (TimeoutError, OSError):
            raise AppError("LINE_MEDIA_UNAVAILABLE") from None
        finally:
            await stop_process(process)

    async def whoami(self):
        status = await self.request("auth", "status", "--json", allow_failure=True)
        self.check_session_status(status)
        # watch briefly owns the CLI session lock during startup/key operations.
        # Retry only this read-only identity check; request(send) is never replayed.
        for attempt in range(4):
            try:
                return identity(await self.request("whoami", "--json"))
            except AppError as exc:
                if exc.code != "LINE_REQUEST_FAILED":
                    raise
                status = await self.request("auth", "status", "--json", allow_failure=True)
                self.check_session_status(status)
                if attempt == 3:
                    raise
                await asyncio.sleep(0.25 * (2 ** attempt))

    @staticmethod
    def check_session_status(status):
        if isinstance(status, dict):
            if status.get('line_validity') == 'invalidated':
                raise AppError('LINE_SESSION_REVOKED')
            if status.get('reason') == 'no_session':
                raise AppError('LINE_LOGIN_REQUIRED')

    async def events(self, *, timeout: int, from_now: bool, started=None, status_changed=None):
        args = ["watch", "--json", "--status-events", "--timeout", f"{timeout}s"]
        if from_now:
            args.append("--from-now")
        process = await self._start(*args)
        try:
            while True:
                try:
                    raw = await process.stdout.readline()
                    if not raw:
                        break
                    event = json.loads(raw)
                    if not isinstance(event, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    raise AppError("BAD_RESPONSE") from None
                if event.get('event') == 'status':
                    state = event.get('state')
                    if state == 'logged_out':
                        code = event.get('code')
                        raise AppError(code if code in {'LINE_SESSION_REVOKED', 'LINE_LOGIN_REQUIRED'} else 'BAD_RESPONSE')
                    if state not in {'ready', 'reconnecting'}:
                        raise AppError('BAD_RESPONSE')
                    if started is not None:
                        started.set() if state == 'ready' else started.clear()
                    if status_changed is not None:
                        status_changed(state)
                    continue
                yield event
            if await process.wait() != 0:
                # Covers early failures before the watcher could emit a status.
                self.check_session_status(await self.request('auth', 'status', '--json', allow_failure=True))
                raise AppError("LINE_WATCH_FAILED")
        finally:
            await stop_process(process)


async def attach_session(store: CredentialStore, cli=None) -> None:
    cli = cli or LineCLI()
    account_id = await cli.whoami()
    old = {}
    try:
        old = store.load("line")
    except AppError as exc:
        if exc.code not in {"CREDENTIALS_MISSING", "CREDENTIALS_CORRUPT"}:
            raise
    store.save("line", {"account_id": account_id,
                       "selections": old.get("selections", []) if old.get("account_id") == account_id else []})


class LineConnector:
    def __init__(self, store: CredentialStore, *, cli=None):
        self.store = store
        try:
            self.credentials = store.load("line")
        except AppError as exc:
            if exc.code != "CREDENTIALS_MISSING":
                raise
            self.credentials = {"account_id": "", "selections": []}
        self.account_id = direct_mid(self.credentials["account_id"]) if self.credentials.get("account_id") else ""
        self.cli = cli or LineCLI()
        self.catalog = {}

    @property
    def supports_watch_status(self):
        return isinstance(self.cli, LineCLI)

    async def connect(self):
        account_id = await self.cli.whoami()
        if not self.account_id:
            self.credentials = {"account_id": account_id, "selections": []}
            self.store.save("line", self.credentials)
            self.account_id = account_id
        elif account_id != self.account_id:
            raise AppError("ACCOUNT_CHANGED")

    def selected_conversation(self) -> Conversation:
        selections = self.credentials.get("selections")
        if not selections:
            raise AppError("NO_SELECTION")
        if not isinstance(selections, list) or len(selections) != 1:
            raise AppError("CREDENTIALS_CORRUPT")
        try:
            conversation = Conversation.from_selection(selections[0])
        except (ValueError, TypeError, KeyError):
            raise AppError("CREDENTIALS_CORRUPT") from None
        direct_mid(conversation.id)
        if conversation.id == self.account_id or conversation.kind != "dm" or conversation.locator.get("mid") != conversation.id:
            raise AppError("CREDENTIALS_CORRUPT")
        return conversation

    async def select_mid(self, mid: str, *, title: str = "LINE test DM"):
        mid = direct_mid(mid)
        await self.connect()
        if mid == self.account_id:
            raise AppError("INVALID_INPUT")
        # title is mutable metadata; routing and identity always use raw MID.
        conversation = self.catalog.get(mid) or Conversation(mid, title, "dm", {"mid": mid})
        updated = {**self.credentials, "selections": [conversation.selection()]}
        self.store.save("line", updated)
        self.credentials = updated

    async def list_conversations(self, limit: int = 100) -> list[Conversation]:
        await self.connect()
        rows = await self.cli.request("chats", "--details", "--direct", "--json", "--limit", str(limit))
        if not isinstance(rows, list):
            raise AppError("BAD_RESPONSE")
        results, seen = [], set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str):
                raise AppError("BAD_RESPONSE")
            mid = row["id"]
            if DIRECT_MID.fullmatch(mid) and mid != self.account_id and mid not in seen:
                title = row.get("name")
                if not isinstance(title, str) or not title or title == mid:
                    title = "名前未取得の会話 " + sha256(mid.encode()).hexdigest()[:8]
                updated = row.get("updated_at", 0)
                if type(updated) is not int or not 0 <= updated <= 253402300799000:
                    raise AppError("BAD_RESPONSE")
                picture = row.get("picture_path", "")
                if not isinstance(picture, str) or len(picture) > 2048:
                    raise AppError("BAD_RESPONSE")
                results.append(Conversation(mid, title, "dm", {"mid": mid, "updated_at": updated, "picture_path": picture}))
                seen.add(mid)
        results.sort(key=lambda c: c.locator["updated_at"], reverse=True)
        self.catalog = {c.id: c for c in results[:limit]}
        # Fetch/watch must not reintroduce stale selected metadata from Keychain.
        selections = self.credentials.get("selections", [])
        if selections:
            selected = self.selected_conversation()
            if selected.id in self.catalog:
                self.credentials = {**self.credentials, "selections": [self.catalog[selected.id].selection()]}
        return results[:limit]

    async def fetch(self, limit: int = 50) -> FetchBatch:
        batch = FetchBatch("line", True, limit)
        try:
            await self.connect()
            conversation = self.selected_conversation()
            batch.conversations_requested = 1
            batch.conversations = [StoredConversation("line", self.account_id, conversation)]
            rows = await self.cli.request("messages", conversation.id, "--limit", str(limit), "--json")
            if not isinstance(rows, list):
                raise AppError("BAD_RESPONSE")
            batch.history_limited = len(rows) >= limit
            for raw in rows:
                batch.raw_items += 1
                message = normalize_line(raw, self.account_id, conversation)
                if message is None:
                    batch.excluded_events += 1
                else:
                    batch.messages.append(message)
            batch.conversations_fetched = 1
        except AppError as exc:
            batch.errors.append(exc.code)
        return finish_batch(batch)

    async def fetch_page(self, conversation, *, cursor=None):
        from ..desktop_sync import HistoryPage
        if cursor is not None:
            raise AppError('CONNECTOR_CAPABILITY_UNSUPPORTED')
        direct_mid(conversation.id)
        await self.connect()
        rows = await self.cli.request('messages', conversation.id, '--limit', '100', '--json')
        if not isinstance(rows, list):
            raise AppError('BAD_RESPONSE')
        messages = [m for raw in rows if (m := normalize_line(raw, self.account_id, conversation)) is not None]
        return HistoryPage(StoredConversation('line', self.account_id, conversation), messages,
                           complete=False, coverage='provider_recent_window')

    async def send_text(self, text: str) -> SendResult:
        await self.connect()
        return await self._send_to_conversation(self.selected_conversation(), text)

    async def send_to(self, conversation: Conversation, text: str, *, authorize) -> SendResult:
        """An explicitly granted target does not change the GUI selection or its watcher."""
        mid = direct_mid(conversation.id)
        if mid == self.account_id or conversation.kind != "dm" or conversation.locator.get("mid") != mid:
            raise AppError("INVALID_INPUT")
        await self.connect()
        authorize()  # Recheck revocation/pause after identity IO and immediately before issuing the send.
        return await self._send_to_conversation(conversation, text)

    async def _send_to_conversation(self, conversation: Conversation, text: str) -> SendResult:
        try:
            valid = isinstance(text, str) and text.strip() and len(text.encode("utf-16-le")) // 2 <= 10000
        except UnicodeError:
            valid = False
        if not valid:
            raise AppError("INVALID_INPUT")
        sent_at = datetime.now(timezone.utc)
        data = await self.cli.request("send", conversation.id, "--stdin", "--json", text=text, mutation=True)
        if (not isinstance(data, dict) or data.get("chat_id") != conversation.id
                or not isinstance(data.get("id"), str) or not data["id"]
                or type(data.get("encrypted")) is not bool):
            raise AppError("LINE_SEND_UNKNOWN")
        # CLI acknowledgment lacks server timestamp; history/live echo replaces it.
        message = UnifiedMessage("line", self.account_id, conversation.id, data["id"], self.account_id,
                                 sent_at, text, conversation.title, direction="outgoing")
        return SendResult(message, data["encrypted"])

    async def send_image_to(self, conversation, image, *, authorize):
        mid = direct_mid(conversation.id)
        if mid == self.account_id or conversation.kind != 'dm' or conversation.locator.get('mid') != mid:
            raise AppError('INVALID_INPUT')
        await self.connect()
        authorize()
        data = await self.cli.request('send', conversation.id, '--image-stdin', '--json', data=image.data, mutation=True)
        if (not isinstance(data, dict) or data.get('chat_id') != conversation.id
                or not isinstance(data.get('id'), str) or not data['id'] or type(data.get('encrypted')) is not bool):
            raise AppError('LINE_SEND_UNKNOWN')
        message = UnifiedMessage('line', self.account_id, conversation.id, data['id'], self.account_id,
            datetime.now(timezone.utc), '', conversation.title, direction='outgoing', attachment_count=1, media={'kind': 'image'})
        return SendResult(message, data['encrypted'])

    async def watch(self, *, timeout: int = 300, from_now: bool = False, started=None, all_conversations=False, status_changed=None):
        from contextlib import aclosing
        await self.connect()
        selected = None if all_conversations else self.selected_conversation()
        options = {"timeout": timeout, "from_now": from_now}
        if started is not None:
            options["started"] = started
        if status_changed is not None:
            options['status_changed'] = status_changed
        async with aclosing(self.cli.events(**options)) as events:
            async for event in events:
                if event.get("event") == "resync_required":
                    raise AppError("LINE_RESYNC_REQUIRED")
                if event.get("event") != "message":
                    continue
                conversation = self.catalog.get(event.get("chat_id")) if all_conversations else selected
                if conversation is None or event.get("chat_id") != conversation.id:
                    continue
                if event.get("type") not in {25, 26}:
                    continue
                message = normalize_line(event.get("message"), self.account_id, conversation)
                if message is not None:
                    expected = "incoming" if event["type"] == 26 else "outgoing"
                    if message.direction != expected:
                        raise AppError("BAD_RESPONSE")
                    yield message
