"""Telegram cloud-chat history via documented MTProto and third-party Telethon.
No Secret Chat support, .session files, send calls, or read acknowledgements.
"""
from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Any
from ..credentials import CredentialStore
from ..models import StoredConversation
from ..errors import AppError, telegram_error
from ..models import Conversation, FetchBatch, UnifiedMessage, finish_batch


def sdk():
    try:
        from telethon import TelegramClient, types, utils
        from telethon.sessions import StringSession
        return TelegramClient, types, utils, StringSession
    except ImportError:
        raise AppError("DEPENDENCY_MISSING") from None


def create_client(credentials: dict[str, Any]):
    TelegramClient, _, _, StringSession = sdk()
    try:
        api_id = int(credentials["api_id"])
        api_hash = credentials["api_hash"]
        session = credentials.get("session", "")
        if api_id <= 0 or not isinstance(api_hash, str) or not isinstance(session, str):
            raise ValueError()
        return TelegramClient(
            StringSession(session), api_id, api_hash,
            device_model="BeeperLocal PoC", app_version="0.1.0-poc",
            receive_updates=False, flood_sleep_threshold=0,
            request_retries=0, connection_retries=1, retry_delay=1,
            timeout=25, auto_reconnect=False, raise_last_call_error=True,
        )
    except (ValueError, TypeError, KeyError):
        raise AppError("CREDENTIALS_CORRUPT") from None


def normalize_telegram(raw, account_id: str, conversation: Conversation) -> UnifiedMessage | None:
    # Service events (joined, title change, etc.) are not counted as content.
    if getattr(raw, "action", None) is not None:
        return None
    text = getattr(raw, "message", None)
    media = getattr(raw, "media", None)
    if not text and media is None:
        return None
    mid = getattr(raw, "id", None)
    if not isinstance(mid, int) or isinstance(mid, bool) or mid <= 0:
        raise ValueError("invalid message id")
    reply = getattr(raw, "reply_to", None)
    reply_id = getattr(reply, "reply_to_msg_id", None) if reply else None
    sender = getattr(raw, "sender_id", None)
    outgoing = getattr(raw, "out", None)
    return UnifiedMessage(
        provider="telegram", account_id=account_id, conversation_id=conversation.id,
        provider_message_id=str(mid), sender_id=str(sender) if sender is not None else "unknown",
        sent_at=getattr(raw, "date", None), text=text or None,
        conversation_title=conversation.title, attachment_count=1 if media is not None else 0,
        edited_at=getattr(raw, "edit_date", None),
        reply_to_message_id=str(reply_id) if reply_id is not None else None,
        direction="outgoing" if outgoing is True else ("incoming" if outgoing is False else "unknown"),
    )


class TelegramConnector:
    def __init__(self, store: CredentialStore, *, client_factory=create_client):
        self.store = store
        self.credentials = store.load("telegram")
        self.client_factory = client_factory

    @asynccontextmanager
    async def connected(self):
        client = self.client_factory(self.credentials)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                raise AppError("CREDENTIALS_INVALID")
            me = await client.get_me()
            if me is None:
                raise AppError("CREDENTIALS_INVALID")
            if getattr(me, "bot", False):
                raise AppError("BOT_TOKEN_NOT_SUPPORTED")
            if str(me.id) != self.credentials.get("account_id"):
                raise AppError("ACCOUNT_CHANGED")
            yield client
            # StringSession can change on a DC migration. Save only to Keychain.
            session = client.session.save()
            if session != self.credentials.get("session"):
                self.credentials["session"] = session
                self.store.save("telegram", self.credentials)
        except Exception as exc:
            raise telegram_error(exc) from None
        finally:
            await client.disconnect()

    async def list_conversations(self, limit: int = 100) -> list[Conversation]:
        _, types, _, _ = sdk()
        results: list[Conversation] = []
        async with self.connected() as client:
            async for dialog in client.iter_dialogs(limit=limit):
                peer = dialog.input_entity
                if isinstance(peer, types.InputPeerUser):
                    locator = {"kind": "user", "id": str(peer.user_id), "access_hash": str(peer.access_hash)}
                elif isinstance(peer, types.InputPeerChannel):
                    locator = {"kind": "channel", "id": str(peer.channel_id), "access_hash": str(peer.access_hash)}
                elif isinstance(peer, types.InputPeerChat):
                    locator = {"kind": "chat", "id": str(peer.chat_id)}
                elif isinstance(peer, types.InputPeerSelf):
                    locator = {"kind": "self"}
                else:
                    continue
                kind = "dm" if dialog.is_user else ("group" if dialog.is_group else "channel")
                results.append(Conversation(str(dialog.id), str(dialog.name or dialog.id), kind, locator))
        return results

    @staticmethod
    def peer_from_selection(conversation: Conversation):
        _, types, utils, _ = sdk()
        locator = conversation.locator
        try:
            kind = locator["kind"]
            if kind == "user":
                peer = types.InputPeerUser(int(locator["id"]), int(locator["access_hash"]))
            elif kind == "channel":
                peer = types.InputPeerChannel(int(locator["id"]), int(locator["access_hash"]))
            elif kind == "chat":
                peer = types.InputPeerChat(int(locator["id"]))
            elif kind == "self":
                return types.InputPeerSelf()
            else:
                raise ValueError()
            if str(utils.get_peer_id(peer)) != conversation.id:
                raise ValueError()
            return peer
        except (ValueError, TypeError, KeyError):
            raise AppError("CREDENTIALS_CORRUPT") from None

    async def fetch(self, limit: int = 50) -> FetchBatch:
        batch = FetchBatch("telegram", True, limit)
        try:
            selections = self.credentials.get("selections", [])
            if not isinstance(selections, list) or not selections:
                raise AppError("NO_SELECTION")
            if len(selections) > 5:
                raise AppError("CREDENTIALS_CORRUPT")
            conversations = [Conversation.from_selection(c) for c in selections]
            batch.conversations = [StoredConversation("telegram", self.credentials["account_id"], c) for c in conversations]
            if len({c.id for c in conversations}) != len(conversations):
                raise AppError("CREDENTIALS_CORRUPT")
            batch.conversations_requested = len(conversations)
            async with self.connected() as client:
                for conversation in conversations:
                    peer = self.peer_from_selection(conversation)
                    found: set[str] = set()
                    scanned = 0
                    async for raw in client.iter_messages(peer, limit=limit * 5 + 50, wait_time=1):
                        scanned += 1
                        batch.raw_items += 1
                        try:
                            message = normalize_telegram(raw, self.credentials["account_id"], conversation)
                            if message is None:
                                batch.excluded_events += 1
                                continue
                            batch.messages.append(message)
                            found.add(message.id)
                        except (ValueError, TypeError, KeyError, OverflowError):
                            batch.normalization_errors += 1
                        if len(found) >= limit:
                            break
                    if scanned >= limit * 5 + 50 and len(found) < limit:
                        raise AppError("SCAN_LIMIT_REACHED")
                    batch.conversations_fetched += 1
        except AppError as exc:
            batch.errors.append(exc.code)
        except (ValueError, TypeError, KeyError):
            batch.errors.append("CREDENTIALS_CORRUPT")
        except Exception as exc:
            batch.errors.append(telegram_error(exc).code)
        return finish_batch(batch)
