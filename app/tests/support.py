from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from types import SimpleNamespace
from beeperlocal.errors import AppError
from beeperlocal.models import Conversation, UnifiedMessage

class MemoryStore:
    def __init__(self, records=None):
        self.records = deepcopy(records or {})
        self.writes = []
    def load(self, provider):
        if provider not in self.records:
            raise AppError("CREDENTIALS_MISSING")
        return deepcopy(self.records[provider])
    def save(self, provider, data):
        self.records[provider] = deepcopy(data)
        self.writes.append(provider)
    def delete(self, provider):
        self.records.pop(provider, None)

CONV = Conversation("C001", "Test channel", "channel", {"channel_id": "C001"})

def slack_store(selections=None):
    return MemoryStore({"slack": {"schema_version": 1, "token": "xoxp-NOT-A-REAL-TOKEN",
                                 "account_id": "T001:U001", "selections": selections if selections is not None else [CONV.selection()]}})

def slack_message(i=0, **overrides):
    value = {"type": "message", "user": "U002", "text": f"fixture-{i}", "ts": f"1700000000.{i:06d}"}
    value.update(overrides)
    return value

class FakeAPI:
    def __init__(self, history=None, lists=None, identity=None):
        self.history = list(history or [])
        self.lists = list(lists or [])
        self.identity = identity or {"ok": True, "team_id": "T001", "user_id": "U001"}
        self.calls = []
    def call(self, method, **params):
        self.calls.append((method, params))
        if method == "auth.test":
            return self.identity
        if method == "conversations.info":
            return {"ok": True, "channel": {"id": params["channel"], "is_member": True}}
        if method == "conversations.history":
            response = self.history.pop(0)
        elif method == "conversations.list":
            response = self.lists.pop(0)
        else:
            raise AssertionError("unexpected method")
        if isinstance(response, Exception):
            raise response
        return response

class Response(io.BytesIO):
    def __init__(self, data):
        super().__init__(json.dumps(data).encode())

class FakeOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
    def open(self, request, timeout):
        self.requests.append(request)
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def unified(i=0, provider="telegram", **kwargs):
    params = {"provider": provider, "account_id": "account", "conversation_id": "chat",
              "provider_message_id": str(i), "sender_id": "sender",
              "sent_at": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i),
              "text": "PRIVATE_BODY_CANARY", "conversation_title": "PRIVATE_TITLE_CANARY"}
    params.update(kwargs)
    return UnifiedMessage(**params)


def telegram_raw(i=1, **kwargs):
    data = {"id": i, "message": f"fixture-{i}", "date": datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i),
            "action": None, "media": None, "sender_id": 2, "out": False,
            "edit_date": None, "reply_to": None}
    data.update(kwargs)
    return SimpleNamespace(**data)

MATRIX_CONV = Conversation("!room:example.org", "Matrix Test", "room", {"room_id": "!room:example.org"})

def matrix_store(selections=None):
    return MemoryStore({"matrix": {"schema_version": 1, "homeserver": "https://matrix.example.org",
                                  "token": "MATRIX_PRIVATE_TOKEN_CANARY", "account_id": "@me:example.org",
                                  "selections": selections if selections is not None else [MATRIX_CONV.selection()]}})

def matrix_message(i=0, **overrides):
    value = {"type": "m.room.message", "event_id": f"$event{i}:example.org", "sender": "@other:example.org",
             "origin_server_ts": 1700000000000 + i, "content": {"msgtype": "m.text", "body": f"fixture-{i}"}}
    value.update(overrides)
    return value

class FakeMatrixAPI:
    def __init__(self, pages=None, sync=None, whoami=None):
        self.pages = list(pages or [])
        self.sync = sync or {"rooms": {"join": {}}}
        self.whoami = whoami or {"user_id": "@me:example.org"}
        self.calls = []
    def get(self, path, **params):
        self.calls.append((path, params))
        if path.endswith("/account/whoami"):
            return deepcopy(self.whoami)
        if path.endswith("/sync"):
            return deepcopy(self.sync)
        if "/messages" in path:
            value = self.pages.pop(0)
            if isinstance(value, Exception):
                raise value
            return deepcopy(value)
        raise AssertionError(f"unexpected path {path}")
