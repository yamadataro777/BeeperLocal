"""Read-only Matrix Client-Server API connector for Phase-0 proof.

The connector reads joined rooms and room history only. Login may create a Matrix
client session/token, but message send/mutation endpoints are deliberately absent.
E2EE decryption is out of scope for this Phase-0 connector; select an unencrypted
room with at least 50 m.room.message events for the proof.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
import ssl
from ..tls import client_context
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request, build_opener, HTTPSHandler, HTTPRedirectHandler

from ..credentials import CredentialStore
from ..models import StoredConversation
from ..errors import AppError
from ..models import Conversation, FetchBatch, UnifiedMessage, finish_batch


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_homeserver(value: str) -> str:
    value = value.strip().rstrip("/")
    try:
        parsed = urlsplit(value)
    except ValueError:
        raise AppError("INVALID_INPUT") from None
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or parsed.path not in ("", "/")):
        raise AppError("INVALID_INPUT")
    return f"https://{parsed.netloc}"


class MatrixAPI:
    def __init__(self, homeserver: str, token: str | None = None, *, opener=None, timeout: int = 25):
        self.homeserver = normalize_homeserver(homeserver)
        if token is not None and (not isinstance(token, str) or not token):
            raise AppError("CREDENTIALS_CORRUPT")
        self.token = token
        self.timeout = timeout
        context = client_context()
        self.opener = opener or build_opener(NoRedirect(), HTTPSHandler(context=context))

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                 body: dict[str, Any] | None = None, authenticated: bool = True) -> dict[str, Any]:
        if method not in {"GET", "POST"} or not path.startswith("/") or "://" in path:
            raise AppError("INVALID_INPUT")
        if authenticated and not self.token:
            raise AppError("CREDENTIALS_MISSING")
        url = self.homeserver + path
        if params:
            url += "?" + urlencode(params)
        headers = {"Accept": "application/json", "User-Agent": "BeeperLocalPoC/0.2"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            data = json.dumps(body, separators=(",", ":")).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise AppError("BAD_RESPONSE")
            value = json.loads(raw.decode("utf-8"))
            if not isinstance(value, dict):
                raise ValueError()
            return value
        except AppError:
            raise
        except HTTPError as exc:
            if exc.code in {401}:
                raise AppError("CREDENTIALS_INVALID") from None
            if exc.code == 403:
                raise AppError("CREDENTIALS_INVALID" if not authenticated else "CONVERSATION_UNAVAILABLE") from None
            if exc.code == 429:
                raise AppError("RATE_LIMITED") from None
            raise AppError("HTTP_ERROR") from None
        except (URLError, TimeoutError, ConnectionError, OSError):
            raise AppError("NETWORK_ERROR") from None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            raise AppError("BAD_RESPONSE") from None

    def get(self, path: str, **params) -> dict[str, Any]:
        return self._request("GET", path, params=params or None)

    def password_login(self, user: str, password: str, device_name: str = "BeeperLocal PoC") -> dict[str, Any]:
        if not isinstance(user, str) or not user or not isinstance(password, str) or not password:
            raise AppError("INVALID_INPUT")
        return self._request(
            "POST", "/_matrix/client/v3/login", authenticated=False,
            body={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": user},
                "password": password,
                "initial_device_display_name": device_name,
            },
        )


def matrix_identity(data: dict[str, Any]) -> str:
    user_id = data.get("user_id")
    if not isinstance(user_id, str) or not user_id.startswith("@") or ":" not in user_id:
        raise AppError("BAD_RESPONSE")
    return user_id


def normalize_matrix(raw: dict[str, Any], account_id: str, conversation: Conversation) -> UnifiedMessage | None:
    if not isinstance(raw, dict) or raw.get("type") != "m.room.message":
        return None
    event_id = raw.get("event_id")
    sender = raw.get("sender")
    ts = raw.get("origin_server_ts")
    content = raw.get("content")
    if (not isinstance(event_id, str) or not event_id or not isinstance(sender, str) or not sender
            or not isinstance(ts, int) or isinstance(ts, bool) or ts < 0 or not isinstance(content, dict)):
        raise ValueError("invalid event")
    body = content.get("body")
    if body is not None and not isinstance(body, str):
        raise ValueError("invalid body")
    msgtype = content.get("msgtype")
    if not isinstance(msgtype, str) or not msgtype:
        raise ValueError("invalid msgtype")
    # Standard Matrix message content requires a body. Empty text is allowed, but
    # events with no body are not counted as proof content.
    if body is None:
        return None
    relates = content.get("m.relates_to")
    reply_id = None
    if isinstance(relates, dict):
        in_reply_to = relates.get("m.in_reply_to")
        if isinstance(in_reply_to, dict) and isinstance(in_reply_to.get("event_id"), str):
            reply_id = in_reply_to["event_id"]
    attachment = 0 if msgtype in {"m.text", "m.notice", "m.emote"} else 1
    sent_at = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
    return UnifiedMessage(
        provider="matrix", account_id=account_id, conversation_id=conversation.id,
        provider_message_id=event_id, sender_id=sender, sent_at=sent_at,
        text=body or None, conversation_title=conversation.title,
        attachment_count=attachment, edited_at=None, reply_to_message_id=reply_id,
        direction="outgoing" if sender == account_id else "incoming",
    )


class MatrixConnector:
    def __init__(self, store: CredentialStore, *, api: MatrixAPI | None = None):
        self.store = store
        self.credentials = store.load("matrix")
        try:
            homeserver = self.credentials["homeserver"]
            token = self.credentials["token"]
            account_id = self.credentials["account_id"]
            if not all(isinstance(v, str) and v for v in (homeserver, token, account_id)):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise AppError("CREDENTIALS_CORRUPT") from None
        self.api = api or MatrixAPI(homeserver, token)

    async def _whoami(self) -> str:
        data = await asyncio.to_thread(self.api.get, "/_matrix/client/v3/account/whoami")
        identity = matrix_identity(data)
        if identity != self.credentials.get("account_id"):
            raise AppError("ACCOUNT_CHANGED")
        return identity

    async def list_conversations(self, limit: int = 100) -> list[Conversation]:
        await self._whoami()
        filter_value = json.dumps({
            "room": {
                "timeline": {"limit": 0},
                "state": {"types": ["m.room.name", "m.room.canonical_alias", "m.room.encryption"]},
                "ephemeral": {"types": []},
                "account_data": {"types": []},
            },
            "presence": {"types": []},
            "account_data": {"types": []},
        }, separators=(",", ":"))
        data = await asyncio.to_thread(self.api.get, "/_matrix/client/v3/sync", timeout="0", filter=filter_value)
        joined = data.get("rooms", {}).get("join", {}) if isinstance(data.get("rooms"), dict) else {}
        if not isinstance(joined, dict):
            raise AppError("BAD_RESPONSE")
        results: list[Conversation] = []
        for room_id, room in joined.items():
            if len(results) >= limit:
                break
            if not isinstance(room_id, str) or not room_id.startswith("!") or not isinstance(room, dict):
                continue
            events = room.get("state", {}).get("events", []) if isinstance(room.get("state"), dict) else []
            if not isinstance(events, list):
                events = []
            title = room_id
            alias = None
            encrypted = False
            for event in events:
                if not isinstance(event, dict) or not isinstance(event.get("content"), dict):
                    continue
                if event.get("type") == "m.room.name" and isinstance(event["content"].get("name"), str) and event["content"]["name"]:
                    title = event["content"]["name"]
                elif event.get("type") == "m.room.canonical_alias" and isinstance(event["content"].get("alias"), str):
                    alias = event["content"]["alias"]
                elif event.get("type") == "m.room.encryption":
                    encrypted = True
            if title == room_id and alias:
                title = alias
            results.append(Conversation(room_id, title, "encrypted-room" if encrypted else "room", {"room_id": room_id}))
        return results

    async def fetch(self, limit: int = 50) -> FetchBatch:
        batch = FetchBatch("matrix", True, limit)
        try:
            await self._whoami()
            selections = self.credentials.get("selections", [])
            if not isinstance(selections, list) or not selections:
                raise AppError("NO_SELECTION")
            if len(selections) > 5:
                raise AppError("CREDENTIALS_CORRUPT")
            conversations = [Conversation.from_selection(c) for c in selections]
            batch.conversations = [StoredConversation("matrix", self.credentials["account_id"], c) for c in conversations]
            if len({c.id for c in conversations}) != len(conversations):
                raise AppError("CREDENTIALS_CORRUPT")
            batch.conversations_requested = len(conversations)
            for conversation in conversations:
                if conversation.kind == "encrypted-room":
                    raise AppError("MATRIX_ENCRYPTED_ROOM")
                room_id = conversation.locator.get("room_id")
                if room_id != conversation.id or not isinstance(room_id, str):
                    raise AppError("CREDENTIALS_CORRUPT")
                found: set[str] = set()
                from_token: str | None = None
                seen_tokens: set[str] = set()
                pages = 0
                while len(found) < limit and pages < 20:
                    pages += 1
                    params: dict[str, Any] = {
                        "dir": "b",
                        "limit": min(100, max(50, limit * 2)),
                        "filter": json.dumps({"types": ["m.room.message"]}, separators=(",", ":")),
                    }
                    if from_token:
                        params["from"] = from_token
                    path = "/_matrix/client/v3/rooms/" + quote(room_id, safe="") + "/messages"
                    data = await asyncio.to_thread(self.api.get, path, **params)
                    chunk = data.get("chunk")
                    if not isinstance(chunk, list):
                        raise AppError("BAD_RESPONSE")
                    batch.raw_items += len(chunk)
                    for raw in chunk:
                        try:
                            message = normalize_matrix(raw, self.credentials["account_id"], conversation)
                            if message is None:
                                batch.excluded_events += 1
                                continue
                            if len(found) >= limit and message.id not in found:
                                continue
                            batch.messages.append(message)
                            found.add(message.id)
                        except (ValueError, TypeError, KeyError, OverflowError, OSError):
                            batch.normalization_errors += 1
                    if len(found) >= limit:
                        break
                    end = data.get("end")
                    if not chunk or not isinstance(end, str) or not end:
                        break
                    if end in seen_tokens:
                        raise AppError("PAGINATION_STALLED")
                    seen_tokens.add(end)
                    from_token = end
                if pages >= 20 and len(found) < limit:
                    raise AppError("SCAN_LIMIT_REACHED")
                batch.conversations_fetched += 1
        except AppError as exc:
            batch.errors.append(exc.code)
        except (ValueError, TypeError, KeyError):
            batch.errors.append("CREDENTIALS_CORRUPT")
        except Exception:
            batch.errors.append("UNEXPECTED_ERROR")
        return finish_batch(batch)
