"""Durable send intent. An ambiguous attempt is never replayed automatically."""
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from uuid import UUID
import re


def request_key(request_id: str) -> str:
    if not isinstance(request_id, str) or str(UUID(request_id)) != request_id:
        raise ValueError("invalid request identity")
    return sha256(("BeeperLocal/send/v1/" + request_id).encode()).hexdigest()


@dataclass(frozen=True)
class OutgoingRequest:
    request_id: str = field(repr=False)
    provider: str
    account_id: str = field(repr=False)
    conversation_id: str = field(repr=False)
    text: str = field(repr=False)
    status: str
    created_at: datetime
    message_id: str | None = field(default=None, repr=False)
    image_digest: str | None = field(default=None, repr=False)

    def __post_init__(self):
        request_key(self.request_id)
        if self.provider not in {"line", "instagram", "slack", "x", "messenger"} or not self.account_id or not self.conversation_id:
            raise ValueError("invalid outgoing scope")
        if self.image_digest is not None and (not isinstance(self.image_digest, str)
                or not re.fullmatch(r'[a-f0-9]{64}', self.image_digest) or self.text != ''):
            raise ValueError('invalid outgoing image')
        if not isinstance(self.text, str) or (not self.text.strip() and self.image_digest is None) or len(self.text.encode("utf-16-le")) // 2 > 10000:
            raise ValueError("invalid outgoing text")
        if self.provider == "instagram" and len(self.text.encode("utf-8")) > 4000:
            raise ValueError("invalid outgoing text")
        if self.provider in {"slack", "messenger"} and len(self.text) > 4000:
            raise ValueError("invalid outgoing text")
        if self.provider == "x" and len(self.text.encode("utf-8")) > 10000:
            raise ValueError("invalid outgoing text")
        if self.status not in {"sending", "acknowledged", "unknown"}:
            raise ValueError("invalid outgoing status")
        if not isinstance(self.created_at, datetime) or self.created_at.utcoffset() is None:
            raise ValueError("invalid outgoing timestamp")
        if self.status == "acknowledged" and not self.message_id:
            raise ValueError("missing acknowledgement")

    @property
    def id(self):
        return request_key(self.request_id)
