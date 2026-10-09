"""Slack User OAuth connector; preserve the existing selected-history path."""
from __future__ import annotations
import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import re
import ssl
from ..tls import client_context
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, HTTPSHandler, ProxyHandler
from ..credentials import CredentialStore
from ..models import StoredConversation
from ..errors import AppError
from ..models import Conversation, FetchBatch, UnifiedMessage, SendResult, finish_batch

ALLOWED_METHODS = frozenset({"auth.test", "conversations.list", "conversations.info", "conversations.history", "conversations.replies", "users.info"})
SLACK_ERRORS = {
    "invalid_auth": "CREDENTIALS_INVALID", "token_revoked": "CREDENTIALS_INVALID",
    "token_expired": "CREDENTIALS_INVALID", "not_authed": "CREDENTIALS_INVALID",
    "account_inactive": "CREDENTIALS_INVALID", "missing_scope": "MISSING_SCOPE",
    "no_permission": "CONVERSATION_UNAVAILABLE", "not_in_channel": "CONVERSATION_UNAVAILABLE",
    "channel_not_found": "CONVERSATION_UNAVAILABLE", "is_archived": "CONVERSATION_UNAVAILABLE",
    "not_allowed_token_type": "BOT_TOKEN_NOT_SUPPORTED", "ratelimited": "RATE_LIMITED",
    "restricted_action": "CONVERSATION_UNAVAILABLE", "thread_not_found": "CONVERSATION_UNAVAILABLE",
}
# These are events, not content to count toward the 50-message proof.
EXCLUDED_SUBTYPES = {
    "channel_join", "channel_leave", "channel_name", "channel_topic", "channel_purpose",
    "channel_archive", "channel_unarchive", "group_join", "group_leave", "group_name",
    "group_topic", "group_purpose", "group_archive", "group_unarchive",
    "message_changed", "message_deleted", "message_replied", "tombstone",
    "pinned_item", "unpinned_item", "reminder_add", "bot_add", "bot_remove",
}
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
TS_PATTERN = re.compile(r"^[0-9]{1,12}\.[0-9]{6}$")


def allowed_conversation(info):
    if info.get("is_archived") or (info.get("is_member") is False and not info.get("is_im")):
        return False
    return bool(info.get("is_member") or info.get("is_im") or info.get("is_mpim") or info.get("is_private"))

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward the bearer token to a redirect target.
        return None

class SlackAPI:
    def __init__(self, token: str, *, max_wait: float = 240, max_requests: int = 100,
                 opener=None, sleep: Callable[[float], None] = time.sleep,
                 notice: Callable[[str], None] | None = None, cooldowns=None):
        if not isinstance(token, str) or not token.startswith(("xoxp-", "xoxe.xoxp-")) or any(c.isspace() for c in token):
            raise AppError("BOT_TOKEN_NOT_SUPPORTED")
        self._token = token
        self.remaining_wait = max_wait
        self.remaining_requests = max_requests
        self.sleep = sleep
        self.notice = notice or (lambda _: None)
        self.cooldowns = cooldowns if cooldowns is not None else {}
        # No ambient HTTP(S)_PROXY forwarding. TLS validation always remains on.
        self.opener = opener or build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=client_context()))

    def _file_post(self, method, payload):
        if method not in {'files.getUploadURLExternal', 'files.completeUploadExternal'}:
            raise AppError('INVALID_INPUT')
        request = Request('https://slack.com/api/' + method, data=json.dumps(payload).encode(), method='POST',
            headers={'Authorization': 'Bearer ' + self._token, 'Content-Type': 'application/json; charset=utf-8'})
        try:
            with self.opener.open(request, timeout=40) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ValueError()
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise ValueError()
        except HTTPError as exc:
            exc.close()
            raise AppError('SLACK_SEND_UNKNOWN') from None
        except (URLError, OSError, TimeoutError, ValueError, UnicodeError):
            raise AppError('SLACK_SEND_UNKNOWN') from None
        if data.get('ok') is not True:
            code = data.get('error')
            if code == 'missing_scope':
                raise AppError('SLACK_IMAGE_SCOPE_REQUIRED')
            raise AppError(SLACK_ERRORS.get(code, 'SLACK_SEND_UNKNOWN') if isinstance(code, str) else 'SLACK_SEND_UNKNOWN')
        return data

    def upload_image(self, *, channel, image):
        created = self._file_post('files.getUploadURLExternal', {'filename': image.name, 'length': len(image.data)})
        fid, target = created.get('file_id'), created.get('upload_url')
        if not isinstance(fid, str) or not re.fullmatch(r'F[A-Z0-9]{1,80}', fid) or not slack_file_url(target, upload=True):
            raise AppError('SLACK_SEND_UNKNOWN')
        # The one-use upload URL needs no bearer token. Never redirect/replay it.
        request = Request(target, data=image.data, method='POST', headers={'Content-Type': image.mime})
        try:
            with self.opener.open(request, timeout=40) as response:
                if response.status != 200:
                    raise ValueError()
                response.read(65536)
        except HTTPError as exc:
            exc.close()
            raise AppError('SLACK_SEND_UNKNOWN') from None
        except (URLError, OSError, TimeoutError, ValueError):
            raise AppError('SLACK_SEND_UNKNOWN') from None
        completed = self._file_post('files.completeUploadExternal', {'files': [{'id': fid, 'title': image.name}], 'channel_id': channel})
        files = completed.get('files')
        if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict) or files[0].get('id') != fid:
            raise AppError('SLACK_SEND_UNKNOWN')
        return fid

    def download_image(self, url):
        if not slack_file_url(url):
            raise AppError('INVALID_INPUT')
        request = Request(url, headers={'Authorization': 'Bearer ' + self._token})
        try:
            with self.opener.open(request, timeout=25) as response:
                data = response.read(4 * 1024 * 1024 + 1)
            if len(data) > 4 * 1024 * 1024:
                raise AppError('IMAGE_TOO_LARGE')
            return data
        except HTTPError as exc:
            exc.close()
            raise AppError('NETWORK_ERROR') from None
        except (URLError, OSError, TimeoutError):
            raise AppError('NETWORK_ERROR') from None

    def post_message(self, *, channel: str, text: str) -> dict[str, Any]:
        # A separate, single-attempt POST path: no GET retry policy or URL body.
        # Slack treats these characters as controls even in otherwise plain text.
        # Escape only its three supported entities; never activate explicit mentions.
        literal_text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        payload = {"channel": channel, "text": literal_text, "mrkdwn": False,
                   "parse": "none", "link_names": False, "unfurl_links": False, "unfurl_media": False}
        request = Request("https://slack.com/api/chat.postMessage",
            data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Authorization": "Bearer " + self._token, "Content-Type": "application/json; charset=utf-8"})
        try:
            with self.opener.open(request, timeout=25) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
            if len(raw) > MAX_RESPONSE_BYTES:
                raise AppError("SLACK_SEND_UNKNOWN")
            data = json.loads(raw)
        except HTTPError as exc:
            exc.close()
            raise AppError("SLACK_SEND_UNKNOWN") from None
        except (URLError, OSError, TimeoutError, ValueError, UnicodeError):
            raise AppError("SLACK_SEND_UNKNOWN") from None
        if not isinstance(data, dict):
            raise AppError("SLACK_SEND_UNKNOWN")
        if data.get("ok") is not True:
            error = data.get("error")
            raise AppError(SLACK_ERRORS.get(error, "SLACK_SEND_UNKNOWN") if isinstance(error, str) else "SLACK_SEND_UNKNOWN")
        return data

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        if method not in ALLOWED_METHODS or "token" in params:
            raise AppError("INVALID_INPUT")
        if self.cooldowns.get(method, 0) > time.monotonic():
            raise AppError("RATE_LIMITED")
        query = urlencode({k: v for k, v in params.items() if v is not None})
        url = "https://slack.com/api/" + method + ("?" + query if query else "")
        for attempt in range(7):
            if self.remaining_requests <= 0:
                raise AppError("REQUEST_BUDGET_EXCEEDED")
            self.remaining_requests -= 1
            request = Request(url, headers={"Authorization": "Bearer " + self._token,
                                           "Accept": "application/json",
                                           "User-Agent": "BeeperLocalPoC/0.1"}, method="GET")
            try:
                with self.opener.open(request, timeout=25) as response:
                    raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise AppError("BAD_RESPONSE")
                data = json.loads(raw)
            except HTTPError as exc:
                try:
                    status = exc.code
                    retry_header = exc.headers.get("Retry-After", "60")
                finally:
                    exc.close()
                if status == 429:
                    try:
                        wait = max(1.0, float(retry_header))
                        if wait != wait or wait == float("inf"):
                            raise ValueError()
                    except (TypeError, ValueError):
                        wait = 60.0
                    self.cooldowns[method] = time.monotonic() + wait
                    if attempt >= 6 or wait > self.remaining_wait:
                        raise AppError("RATE_LIMITED") from None
                    self.remaining_wait -= wait
                    self.notice(f"Slack: レート制限のRetry-Afterに従い {wait:g} 秒待機します。")
                    self.sleep(wait)
                    self.cooldowns.pop(method, None)
                    continue
                if status in {500, 502, 503, 504} and attempt < 2:
                    wait = float(2 ** attempt)
                    if wait > self.remaining_wait:
                        raise AppError("HTTP_ERROR") from None
                    self.remaining_wait -= wait
                    self.sleep(wait)
                    continue
                raise AppError("HTTP_ERROR") from None
            except (URLError, OSError, TimeoutError):
                raise AppError("NETWORK_ERROR") from None
            except (ValueError, UnicodeError):
                raise AppError("BAD_RESPONSE") from None
            if not isinstance(data, dict):
                raise AppError("BAD_RESPONSE")
            if data.get("ok") is not True:
                # Ignore provider-supplied prose/URLs, even on error.
                error = data.get("error")
                raise AppError(SLACK_ERRORS.get(error, "API_ERROR") if isinstance(error, str) else "BAD_RESPONSE")
            return data
        raise AppError("RATE_LIMITED")


def slack_file_url(value, *, upload=False):
    if not isinstance(value, str) or len(value) > 8192 or any(c.isspace() for c in value) or '\\' in value:
        return False
    try:
        url = urlsplit(value)
        return (url.scheme == 'https' and url.hostname == 'files.slack.com' and url.port in (None, 443)
                and not url.username and not url.password and not url.fragment
                and url.path.startswith('/upload/' if upload else '/files-'))
    except ValueError:
        return False


def account_identity(auth: dict[str, Any]) -> str:
    if auth.get("bot_id"):
        raise AppError("BOT_TOKEN_NOT_SUPPORTED")
    team_id, user_id = auth.get("team_id"), auth.get("user_id")
    if not isinstance(team_id, str) or not team_id or not isinstance(user_id, str) or not user_id:
        raise AppError("BAD_RESPONSE")
    return team_id + ":" + user_id


def parse_ts(value: str) -> datetime:
    if not isinstance(value, str) or not TS_PATTERN.fullmatch(value):
        raise ValueError("invalid Slack timestamp")
    # Decimal avoids losing microseconds through a float timestamp.
    try:
        micros = int(Decimal(value) * Decimal(1_000_000))
        return datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(microseconds=micros)
    except (InvalidOperation, OverflowError):
        raise ValueError("invalid Slack timestamp") from None


def normalize_slack(raw: dict[str, Any], account_id: str, self_user: str, conversation: Conversation) -> UnifiedMessage | None:
    if not isinstance(raw, dict):
        raise ValueError("invalid message")
    if raw.get("type") != "message" or raw.get("hidden") is True or raw.get("subtype") in EXCLUDED_SUBTYPES:
        return None
    text = raw.get("text")
    files = raw.get("files", [])
    if text is not None and not isinstance(text, str):
        raise ValueError("invalid text")
    if not isinstance(files, list):
        raise ValueError("invalid attachment list")
    if not text and not files:
        return None
    if text:
        # Decode Slack's three entities once, with ampersand last. A literal
        # '&lt;' arrives as '&amp;lt;' and must not become '<'. Do not decode HTML.
        text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
    sender = raw.get("user") or raw.get("bot_id") or "unknown"
    if not isinstance(sender, str):
        raise ValueError("invalid sender")
    stamp = raw.get("ts")
    edited = raw.get("edited")
    edited_at = parse_ts(edited["ts"]) if isinstance(edited, dict) and edited.get("ts") else None
    reply = raw.get("thread_ts")
    if reply is not None:
        parse_ts(reply)
    attachments = []
    for file in files[:20]:
        if not isinstance(file, dict):
            continue
        fid = file.get('id')
        url = next((file.get(k) for k in ('thumb_1024', 'thumb_720', 'url_private') if slack_file_url(file.get(k))), None)
        if isinstance(fid, str) and re.fullmatch(r'F[A-Z0-9]{1,80}', fid) and url and str(file.get('mimetype', '')).startswith('image/'):
            attachments.append({'kind': 'image', 'url': url, 'file_id': fid})
    return UnifiedMessage(
        provider="slack", account_id=account_id, conversation_id=conversation.id,
        provider_message_id=stamp, sender_id=sender, sent_at=parse_ts(stamp),
        text=text or None, conversation_title=conversation.title, attachment_count=len(files),
        edited_at=edited_at, reply_to_message_id=reply if reply != stamp else None, attachments=attachments,
        direction="outgoing" if sender == self_user else ("unknown" if sender == "unknown" else "incoming"),
    )


def cursor_of(data: dict[str, Any]) -> str:
    metadata = data.get("response_metadata") or {}
    if not isinstance(metadata, dict):
        raise AppError("BAD_RESPONSE")
    cursor = metadata.get("next_cursor") or ""
    if not isinstance(cursor, str):
        raise AppError("BAD_RESPONSE")
    return cursor.strip()

class SlackConnector:
    def __init__(self, store: CredentialStore, *, api: SlackAPI | None = None, max_wait: float = 240, notice=None):
        self.store = store
        self.credentials = store.load("slack")
        token = self.credentials.get("token")
        if not isinstance(token, str):
            raise AppError("CREDENTIALS_CORRUPT")
        self.api = api or SlackAPI(token, max_wait=max_wait, notice=notice)
        self._injected_api = api is not None
        self._auth_lock = asyncio.Lock()
        self._api_options = {"max_wait": max_wait, "notice": notice, "cooldowns": self.api.cooldowns if isinstance(self.api, SlackAPI) else {}}
        self.identity: str | None = None
        self.self_user: str | None = None
        self.catalog_limited = True

    @property
    def account_id(self):
        return self.credentials["account_id"]

    async def _begin_operation(self):
        # Budgets are bounded per operation, not exhausted forever by a long-running Core.
        async with self._auth_lock:
            current = self.store.load("slack")
            if current.get("account_id") != self.account_id:
                raise AppError("ACCOUNT_CHANGED")
            if not self._injected_api:
                from ..slack_oauth import refresh_credentials
                current = await asyncio.to_thread(refresh_credentials, self.store, current)
            self.credentials = current
            if not self._injected_api:
                self.api = SlackAPI(current.get("token"), **self._api_options)

    def selected_conversation(self):
        selections = self.credentials.get("selections", [])
        if not selections:
            raise AppError("NO_SELECTION")
        if not isinstance(selections, list) or len(selections) != 1:
            raise AppError("SLACK_SELECT_ONE")
        try:
            return Conversation.from_selection(selections[0])
        except (TypeError, ValueError, KeyError):
            raise AppError("CREDENTIALS_CORRUPT") from None

    async def select_conversation(self, conversation):
        await self._begin_operation()
        await self.connect()
        await self._check_conversation(conversation)
        async with self._auth_lock:
            current = self.store.load("slack")
            if current.get("account_id") != self.account_id:
                raise AppError("ACCOUNT_CHANGED")
            updated = {**current, "selections": [conversation.selection()]}
            self.store.save("slack", updated)
            self.credentials = updated

    async def _check_conversation(self, conversation):
        cid = conversation.locator.get("channel_id")
        if not isinstance(cid, str) or cid != conversation.id or not re.fullmatch(r"[CGD][A-Z0-9]+", cid):
            raise AppError("CREDENTIALS_CORRUPT")
        data = await asyncio.to_thread(self.api.call, "conversations.info", channel=cid)
        info = data.get("channel")
        if not isinstance(info, dict) or info.get("id") != cid:
            raise AppError("BAD_RESPONSE")
        if not allowed_conversation(info):
            raise AppError("CONVERSATION_UNAVAILABLE")
        return cid

    async def send_text(self, text):
        return await self.send_to(self.selected_conversation(), text)

    async def send_image_to(self, conversation, image, *, authorize):
        await self._begin_operation()
        await self.connect()
        cid = await self._check_conversation(conversation)
        authorize()
        fid = await asyncio.to_thread(self.api.upload_image, channel=cid, image=image)
        # Slack's completion confirms the file share, but returns no message ts.
        # History later merges this provisional row by the file id within its scope.
        message = UnifiedMessage('slack', self.identity, cid, 'file:' + fid, self.self_user,
            datetime.now(timezone.utc), '', conversation.title, direction='outgoing', attachment_count=1,
            attachments=[{'kind': 'image', 'file_id': fid, 'url': ''}])
        return SendResult(message, encrypted=False)

    async def download_attachment(self, attachment):
        await self._begin_operation()
        return await asyncio.to_thread(self.api.download_image, attachment.get('url'))

    async def send_to(self, conversation, text, *, authorize=None):
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise AppError("INVALID_INPUT")
        await self._begin_operation()
        await self.connect()
        cid = await self._check_conversation(conversation)
        if authorize:
            authorize()
        data = await asyncio.to_thread(self.api.post_message, channel=cid, text=text)
        try:
            raw = data.get("message")
            # User-token posts can carry bot_id/app_id attribution. The author must
            # still match the non-bot user verified by auth.test; metadata alone
            # does not turn a human-authored post into a bot message.
            if (data.get("channel") != cid or not isinstance(raw, dict)
                    or raw.get("user") != self.self_user or raw.get("subtype") == "bot_message"
                    or raw.get("ts") != data.get("ts")):
                raise ValueError()
            message = normalize_slack(raw, self.identity, self.self_user, conversation)
            if message is None or message.direction != "outgoing":
                raise ValueError()
            # Slack may normalize text formatting; retain the exact user's submitted plain text.
            from dataclasses import replace
            return SendResult(replace(message, text=text), encrypted=False)
        except (ValueError, TypeError, KeyError, OverflowError):
            raise AppError("SLACK_SEND_UNKNOWN") from None

    async def connect(self) -> None:
        await self._begin_operation()
        auth = await asyncio.to_thread(self.api.call, "auth.test")
        self.identity = account_identity(auth)
        self.self_user = auth["user_id"]
        if self.credentials.get("account_id") != self.identity:
            raise AppError("ACCOUNT_CHANGED")

    async def fetch_user_profile(self, user_id):
        from ..slack_profiles import USER_ID, profile_view
        if not isinstance(user_id, str) or not USER_ID.fullmatch(user_id):
            raise AppError("INVALID_INPUT")
        await self._begin_operation()
        await self.connect()
        data = await asyncio.to_thread(self.api.call, "users.info", user=user_id)
        return profile_view(data, user_id)

    async def list_conversations(self, limit: int = 100, types: str = "public_channel,private_channel,im,mpim") -> list[Conversation]:
        await self._begin_operation()
        await self.connect()
        cursor = ""
        seen_cursors: set[str] = set()
        results: dict[str, Conversation] = {}
        for _ in range(50):
            data = await asyncio.to_thread(self.api.call, "conversations.list", types=types,
                                          exclude_archived="true", limit=100, cursor=cursor or None)
            channels = data.get("channels")
            if not isinstance(channels, list):
                raise AppError("BAD_RESPONSE")
            for channel in channels:
                if not isinstance(channel, dict) or not isinstance(channel.get("id"), str):
                    raise AppError("BAD_RESPONSE")
                # Personal inbox PoC: don't silently import every public channel.
                if not allowed_conversation(channel):
                    continue
                cid = channel["id"]
                title = channel.get("name") or ("DM " + str(channel.get("user", cid)))
                kind = "dm" if channel.get("is_im") else ("group" if channel.get("is_mpim") or channel.get("is_private") else "channel")
                locator = {"channel_id": cid}
                peer = channel.get("user")
                if channel.get("is_im") and isinstance(peer, str) and re.fullmatch(r"[UW][A-Z0-9]{1,80}", peer):
                    locator["peer_user_id"] = peer
                results[cid] = Conversation(cid, str(title), kind, locator)
                if len(results) >= limit:
                    self.catalog_limited = True
                    return list(results.values())
            cursor = cursor_of(data)
            if not cursor:
                self.catalog_limited = False
                return list(results.values())
            if cursor in seen_cursors:
                raise AppError("PAGINATION_STALLED")
            seen_cursors.add(cursor)
        raise AppError("SCAN_LIMIT_REACHED")

    async def fetch_sync_page(self, conversation, *, cursor=None, metadata=None):
        # Persist the thread inventory with the same cursor/message transaction.
        # New replies to an old root do not reorder conversations.history.
        metadata = dict(metadata or {})
        roots = metadata.get('threads', [])
        if (not isinstance(roots,list) or len(roots)>10000 or any(not isinstance(v,str) or not TS_PATTERN.fullmatch(v) for v in roots)
                or type(metadata.get('turn',0)) is not int or type(metadata.get('next',0)) is not int):
            raise AppError('BAD_RESPONSE')
        requested = cursor
        if cursor is None:
            turn = metadata.get('turn',0)
            metadata['turn'] = (turn + 1) % 2
            if turn % 2 and roots:
                position = metadata.get('next',0) % len(roots)
                requested = {'thread':roots[position], 'threads':[], 'history':None}
                metadata['next'] = (position + 1) % len(roots)
        page = await self.fetch_page(conversation, cursor=requested)
        found = []
        for value in (requested, page.cursor):
            if value and value.get('thread'):
                found.extend([value['thread'], *value.get('threads',[])])
        all_roots = list(dict.fromkeys(roots + found))
        metadata['threads'] = all_roots[:10000]
        metadata['threadsLimited'] = metadata.get('threadsLimited',False) or len(all_roots)>10000
        page.poll_metadata = metadata
        return page

    async def fetch_page(self, conversation, *, cursor=None):
        from ..desktop_sync import HistoryPage
        await self._begin_operation()
        await self.connect()
        cid = await self._check_conversation(conversation)
        cursor = cursor or {}
        if set(cursor) - {'cursor', 'latest', 'thread', 'thread_cursor', 'threads', 'history'}:
            raise AppError('INVALID_INPUT')
        thread = cursor.get('thread')
        if thread:
            parse_ts(thread)
            data = await asyncio.to_thread(self.api.call, 'conversations.replies', channel=cid, ts=thread,
                limit=15, cursor=cursor.get('thread_cursor'))
        else:
            data = await asyncio.to_thread(self.api.call, 'conversations.history', channel=cid, limit=15,
                cursor=cursor.get('cursor'), latest=cursor.get('latest'), inclusive='false')
        raw = data.get('messages')
        if not isinstance(raw, list) or len(raw) > 100:
            raise AppError('BAD_RESPONSE')
        messages, deleted, threads = [], [], []
        try:
            for item in raw:
                if item.get('subtype') in {'message_deleted', 'tombstone'}:
                    mid = item.get('deleted_ts') or item.get('ts')
                    parse_ts(mid)
                    deleted.append(mid)
                    continue
                value = item.get('message') if item.get('subtype') == 'message_changed' else item
                message = normalize_slack(value, self.identity, self.self_user, conversation)
                if message:
                    messages.append(message)
                    if not thread and type(value.get('reply_count')) is int and value['reply_count'] > 0:
                        threads.append(value['ts'])
            token = cursor_of(data)
            if thread:
                threads = cursor.get('threads', [])
                history = cursor.get('history')
                if token:
                    next_page = {**cursor, 'thread_cursor': token}
                elif data.get('has_more'):
                    raise AppError('PAGINATION_STALLED')
                elif threads:
                    next_page = {'thread':threads[0], 'threads':threads[1:], 'history':history}
                else:
                    next_page = history
            else:
                history = {'cursor': token} if token else None
                if not token and data.get('has_more'):
                    stamps = [item['ts'] for item in raw if TS_PATTERN.fullmatch(item.get('ts', ''))]
                    if not stamps:
                        raise AppError('PAGINATION_STALLED')
                    history = {'latest': min(stamps, key=Decimal)}
                next_page = {'thread':threads[0], 'threads':threads[1:], 'history':history} if threads else history
            return HistoryPage(StoredConversation('slack', self.account_id, conversation), messages,
                cursor=next_page, complete=next_page is None and not bool(data.get('is_limited')),
                followup={**next_page, 'history': None} if next_page and next_page.get('thread') else None,
                deletions=deleted, coverage='workspace_retention' if data.get('is_limited') else 'channel_and_thread_history')
        except (TypeError, KeyError, ValueError, AttributeError):
            raise AppError('BAD_RESPONSE') from None

    async def fetch(self, limit: int = 50) -> FetchBatch:
        return await self._fetch(limit)

    async def fetch_recent(self, limit: int = 15) -> FetchBatch:
        """One selected conversation, one history page including excluded events."""
        return await self._fetch(limit, single_page=True)

    async def _fetch(self, limit: int, *, single_page: bool = False) -> FetchBatch:
        batch = FetchBatch("slack", True, limit)
        try:
            if type(limit) is not int or not 1 <= limit <= (15 if single_page else 100):
                raise AppError("INVALID_INPUT")
            await self._begin_operation()
            selections = self.credentials.get("selections", [])
            if not isinstance(selections, list) or not selections:
                raise AppError("NO_SELECTION")
            if single_page and len(selections) != 1:
                raise AppError("SLACK_SELECT_ONE")
            if len(selections) > 5:
                raise AppError("CREDENTIALS_CORRUPT")
            conversations = [Conversation.from_selection(c) for c in selections]
            batch.conversations = [StoredConversation("slack", self.credentials["account_id"], c) for c in conversations]
            if len({c.id for c in conversations}) != len(conversations):
                raise AppError("CREDENTIALS_CORRUPT")
            batch.conversations_requested = len(conversations)
            await self.connect()
            for conversation in conversations:
                try:
                    await self._fetch_conversation(conversation, limit, batch, single_page=single_page)
                    batch.conversations_fetched += 1
                except AppError as exc:
                    batch.errors.append(exc.code)
                    # Stop on throttling/auth/transport errors; do not hammer the next chat.
                    break
        except AppError as exc:
            batch.errors.append(exc.code)
        except (ValueError, TypeError, KeyError):
            batch.errors.append("CREDENTIALS_CORRUPT")
        return finish_batch(batch)

    async def _fetch_conversation(self, conversation: Conversation, limit: int, batch: FetchBatch,
                                  *, single_page: bool = False) -> None:
        cid = await self._check_conversation(conversation)
        cursor = ""
        latest = None
        seen_pages: set[tuple[str, str | None]] = set()
        unique_ids: set[str] = set()
        for _ in range(30):
            page_key = (cursor, latest)
            if page_key in seen_pages:
                raise AppError("PAGINATION_STALLED")
            seen_pages.add(page_key)
            data = await asyncio.to_thread(self.api.call, "conversations.history", channel=cid,
                                          limit=min(15, limit) if single_page else 15,
                                          cursor=cursor or None, latest=latest,
                                          inclusive="false")
            raw_messages = data.get("messages")
            if not isinstance(raw_messages, list):
                raise AppError("BAD_RESPONSE")
            batch.history_limited = batch.history_limited or bool(data.get("is_limited"))
            batch.raw_items += len(raw_messages)
            for raw in raw_messages:
                try:
                    message = normalize_slack(raw, self.identity, self.self_user, conversation)
                    if message is None:
                        batch.excluded_events += 1
                        continue
                    if len(unique_ids) >= limit and message.id not in unique_ids:
                        continue
                    batch.messages.append(message)
                    unique_ids.add(message.id)
                except (ValueError, TypeError, KeyError, OverflowError):
                    batch.normalization_errors += 1
            if single_page:
                # Stop at the page boundary, not the count of content messages.
                # A join/leave event must not trigger another history request.
                batch.history_limited |= bool(cursor_of(data) or data.get("has_more")
                                              or len(unique_ids) >= limit)
                return
            if len(unique_ids) >= limit:
                batch.history_limited = True
                return
            next_cursor = cursor_of(data)
            if next_cursor:
                cursor = next_cursor
                continue
            if data.get("has_more"):
                # Slack also documents time-based pagination when no cursor is supplied.
                stamps = [raw.get("ts") for raw in raw_messages if isinstance(raw, dict)
                          and isinstance(raw.get("ts"), str) and TS_PATTERN.fullmatch(raw["ts"])]
                if not stamps:
                    raise AppError("PAGINATION_STALLED")
                next_latest = min(stamps, key=Decimal)
                if latest is not None and Decimal(next_latest) >= Decimal(latest):
                    raise AppError("PAGINATION_STALLED")
                latest, cursor = next_latest, ""
                continue
            return
        raise AppError("SCAN_LIMIT_REACHED")

    async def fetch_thread(self, conversation, root_ts, limit=100):
        """Explicit bounded thread read; ordinary history does not include all replies."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise AppError("INVALID_INPUT")
        try:
            parse_ts(root_ts)
        except ValueError:
            raise AppError("INVALID_INPUT") from None
        await self._begin_operation()
        await self.connect()
        cid = await self._check_conversation(conversation)
        batch = FetchBatch("slack", True, limit, conversations_requested=1)
        batch.conversations = [StoredConversation("slack", self.identity, conversation)]
        cursor, oldest = "", None
        pages, unique = set(), set()
        for _ in range(30):
            if (cursor, oldest) in pages:
                raise AppError("PAGINATION_STALLED")
            pages.add((cursor, oldest))
            data = await asyncio.to_thread(self.api.call, "conversations.replies", channel=cid,
                ts=root_ts, limit=15, cursor=cursor or None, oldest=oldest, inclusive="false")
            rows = data.get("messages")
            if not isinstance(rows, list):
                raise AppError("BAD_RESPONSE")
            batch.raw_items += len(rows)
            batch.history_limited |= bool(data.get("is_limited"))
            for raw in rows:
                try:
                    m = normalize_slack(raw, self.identity, self.self_user, conversation)
                    if m is None:
                        batch.excluded_events += 1
                        continue
                    if m.provider_message_id != root_ts and m.reply_to_message_id != root_ts:
                        raise ValueError()
                    if m.id not in unique and len(unique) < limit:
                        unique.add(m.id)
                        batch.messages.append(m)
                except (ValueError, KeyError, TypeError, OverflowError):
                    raise AppError("BAD_RESPONSE") from None
            if len(unique) >= limit:
                batch.history_limited = True
                break
            cursor = cursor_of(data)
            if cursor:
                continue
            if not data.get("has_more"):
                break
            stamps = [r.get("ts") for r in rows if isinstance(r, dict) and isinstance(r.get("ts"), str) and TS_PATTERN.fullmatch(r["ts"])]
            if not stamps or (oldest is not None and Decimal(max(stamps, key=Decimal)) <= Decimal(oldest)):
                raise AppError("PAGINATION_STALLED")
            oldest = max(stamps, key=Decimal)
        else:
            raise AppError("SCAN_LIMIT_REACHED")
        batch.conversations_fetched = 1
        return finish_batch(batch)
