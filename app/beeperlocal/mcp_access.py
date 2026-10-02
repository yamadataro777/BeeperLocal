"""Local client grants. No network, plaintext credentials, or raw provider IDs in views."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import hmac
import re
import secrets
from uuid import UUID, uuid4

from .errors import AppError

SETTINGS_KEY = "desktop-settings-v1"
GRANTS_KEY = "mcp-clients-v1"
DEFAULT_PORT = 28641
MAX_CLIENTS = 100
IDENTITY = re.compile(r"[a-f0-9]{64}\Z")
TOKEN = re.compile(r"blc_[A-Za-z0-9_-]{43}\Z")


def default_settings():
    return {"mcpEnabled": False, "port": DEFAULT_PORT, "storagePaused": False}


def load_settings(db, key=SETTINGS_KEY, defaults=None):
    result = db.private_get(key, defaults or default_settings())
    if (not isinstance(result, dict) or set(result) != set(default_settings())
            or type(result["mcpEnabled"]) is not bool or type(result["storagePaused"]) is not bool
            or type(result["port"]) is not int or not 1024 <= result["port"] <= 65535):
        raise AppError("LOCAL_DB_CORRUPT")
    return result


@dataclass(frozen=True)
class Grant:
    id: str
    name: str
    account_id: str = field(repr=False)
    conversations: tuple[str, ...]
    read: bool
    send: bool
    token_hash: str = field(repr=False)
    created_at: str

    def view(self):
        return {"id": self.id, "name": self.name, "conversationIds": list(self.conversations),
                "read": self.read, "send": self.send, "createdAt": self.created_at}

    def persisted(self):
        return {**self.view(), "accountId": self.account_id, "tokenHash": self.token_hash}


class AccessManager:
    def __init__(self, db, key=GRANTS_KEY):
        self.db = db
        self.key = key

    def all(self):
        values = self.db.private_get(self.key, [])
        if not isinstance(values, list) or len(values) > MAX_CLIENTS:
            raise AppError("LOCAL_DB_CORRUPT")
        grants = []
        try:
            for v in values:
                if (not isinstance(v, dict) or set(v) != {"id", "name", "accountId", "conversationIds", "read", "send", "createdAt", "tokenHash"}
                        or str(UUID(v["id"])) != v["id"] or not isinstance(v["name"], str)
                        or not 1 <= len(v["name"]) <= 80 or not isinstance(v["accountId"], str) or not v["accountId"]
                        or type(v["read"]) is not bool or type(v["send"]) is not bool
                        or not (v["read"] or v["send"]) or not isinstance(v["conversationIds"], list)
                        or not 1 <= len(v["conversationIds"]) <= 500
                        or len(set(v["conversationIds"])) != len(v["conversationIds"])
                        or any(not isinstance(i, str) or not IDENTITY.fullmatch(i) for i in v["conversationIds"])
                        or not isinstance(v["tokenHash"], str) or not IDENTITY.fullmatch(v["tokenHash"])
                        or not isinstance(v["createdAt"], str)):
                    raise ValueError()
                grants.append(Grant(v["id"], v["name"], v["accountId"], tuple(v["conversationIds"]),
                                    v["read"], v["send"], v["tokenHash"], v["createdAt"]))
            if len({g.id for g in grants}) != len(grants) or len({g.token_hash for g in grants}) != len(grants):
                raise ValueError()
        except (ValueError, TypeError, KeyError, AttributeError):
            raise AppError("LOCAL_DB_CORRUPT") from None
        return grants

    def create(self, *, name, account_id, conversations, read, send, available):
        if (not isinstance(name, str) or not 1 <= len(name.strip()) <= 80
                or any(ord(c) < 32 for c in name) or not account_id
                or type(read) is not bool or type(send) is not bool or not (read or send)
                or not isinstance(conversations, list) or not 1 <= len(conversations) <= 500
                or any(not isinstance(i, str) or i not in available for i in conversations)
                or len(set(conversations)) != len(conversations)):
            raise AppError("INVALID_INPUT")
        grants = self.all()
        if len(grants) >= MAX_CLIENTS:
            raise AppError("MCP_CLIENT_LIMIT")
        token = "blc_" + secrets.token_urlsafe(32)
        grant = Grant(str(uuid4()), name.strip(), account_id, tuple(conversations), read, send,
                      sha256(token.encode()).hexdigest(), datetime.now(timezone.utc).isoformat())
        self.db.private_put(self.key, [g.persisted() for g in (*grants, grant)])
        return grant, token  # The only path that returns the token; never saved or logged.

    def revoke(self, client_id, account_id):
        grants = self.all()
        selected = [g for g in grants if g.id == client_id and g.account_id == account_id]
        if not selected:
            raise AppError("MCP_ACCESS_DENIED")
        self.db.private_put(self.key, [g.persisted() for g in grants if g not in selected])

    def authenticate(self, token, account_id):
        if not isinstance(token, str) or not TOKEN.fullmatch(token):
            raise AppError("MCP_ACCESS_DENIED")
        hashed = sha256(token.encode()).hexdigest()
        matched = None
        for grant in self.all():
            if hmac.compare_digest(hashed, grant.token_hash) and grant.account_id == account_id:
                matched = grant
        if matched is None:
            raise AppError("MCP_ACCESS_DENIED")
        return matched

    def authorize(self, token, account_id, permission, conversation_id=None):
        grant = self.authenticate(token, account_id)
        if permission not in {"read", "send"} or not getattr(grant, permission):
            raise AppError("MCP_ACCESS_DENIED")
        if conversation_id is not None and conversation_id not in grant.conversations:
            raise AppError("MCP_ACCESS_DENIED")
        return grant
