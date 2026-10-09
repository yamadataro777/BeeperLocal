"""Desktop IPC, durable send intents and account routing. All data are fixtures."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock

from beeperlocal.connectors.line import LineConnector, normalize_line
from beeperlocal.desktop import DesktopCore
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from beeperlocal.outbox import OutgoingRequest
from beeperlocal.storage import EncryptedMessageStore
from .test_line import SELF, PEER, OTHER, CONV, KEY, BODY, FakeCLI, raw, store


class DesktopCLI(FakeCLI):
    def __init__(self):
        super().__init__()
        self.queue = asyncio.Queue()
        self.watch_started = asyncio.Event()
        self.send_calls = 0
        self.send_error = None

    async def request(self, *args, **kwargs):
        if args[0] == "chats":
            return [{"id": PEER, "name": "Fixture Friend"}, {"id": OTHER, "name": "Second Friend"}]
        if args[0] == "contacts":
            return [{"mid": PEER, "displayName": "Fixture Friend"}, {"mid": OTHER, "displayName": "Second Friend"}]
        if args[0] == "messages":
            if args[1] == OTHER:
                return []
        if args[0] == "send":
            self.send_calls += 1
            if self.send_error:
                raise self.send_error
        return await super().request(*args, **kwargs)

    async def events(self, *, timeout, from_now, started=None):
        if started:
            started.set()
        self.watch_started.set()
        try:
            while True:
                yield await self.queue.get()
        finally:
            self.closed = True


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / "state" / "messages.sqlite3"
        self.credentials = store()
        self.backend = DesktopCLI()
        self.events = []
        self.record = StoredConversation("line", SELF, CONV)
        self.other = StoredConversation("line", SELF, replace(CONV, id=OTHER, locator={"mid": OTHER}))
        self.core = self.new_core()

    def db(self):
        return EncryptedMessageStore(KEY, self.path)

    def new_core(self):
        return DesktopCore(credentials=self.credentials, db_factory=self.db,
                           connector_factory=lambda credentials: LineConnector(credentials, cli=self.backend),
                           emit=self.events.append)

    async def asyncTearDown(self):
        await self.core.close()

    async def connect(self):
        return await self.core.dispatch({"op": "connect"})

    async def send(self, text=BODY, identity=None, request_id=None):
        return await self.core.dispatch({"op": "send", "conversationId": identity or self.record.id,
                                         "text": text, "requestId": request_id or str(uuid4())})

    async def test_snapshot_is_local_and_does_not_expose_provider_ids(self):
        with self.db() as db:
            db.upsert([normalize_line(raw(), SELF, CONV)], conversations=[self.record])
        self.backend.whoami = AsyncMock(side_effect=AssertionError("no network"))
        snapshot = await self.core.dispatch({"op": "snapshot"})
        self.assertEqual(snapshot["connection"], "offline")
        self.assertEqual(snapshot["conversations"][0]["preview"], BODY)
        output = json.dumps(snapshot)
        self.assertNotIn(SELF, output)
        self.assertNotIn(PEER, output)
        self.assertEqual(self.backend.whoami.await_count, 0)

    async def test_ping_does_not_access_keychain_or_database(self):
        self.assertEqual((await self.core.dispatch({"op": "ping"}))["ready"], True)
        self.assertFalse(self.core.started)
        self.assertIsNone(self.core.db)

    async def test_connect_loads_catalog_recovers_history_and_starts_watch(self):
        snapshot = await self.connect()
        self.assertEqual(snapshot["connection"], "connected")
        self.assertEqual(len(snapshot["conversations"]), 2)
        self.assertEqual(snapshot["selectedId"], self.record.id)
        await asyncio.wait_for(self.backend.watch_started.wait(), 1)
        await self.backend.queue.put({"event": "message", "chat_id": PEER, "type": 26,
                                      "message": raw(id="live-fixture-reply", text="reply")})
        for _ in range(30):
            if self.core.db.total_count() == 2:
                break
            await asyncio.sleep(0.01)
        self.assertEqual(self.core.db.total_count(), 2)
        self.assertTrue(any(e["event"] == "messages_changed" for e in self.events))

    async def test_switch_stops_old_watcher_and_stale_send_is_rejected(self):
        await self.connect()
        await asyncio.wait_for(self.backend.watch_started.wait(), 1)
        result = await self.core.dispatch({"op": "select", "conversationId": self.other.id})
        self.assertEqual(result["conversationId"], self.other.id)
        self.assertEqual(result["messages"], [])
        self.assertTrue(self.backend.closed)
        with self.assertRaises(AppError) as error:
            await self.send(identity=self.record.id)
        self.assertEqual(error.exception.code, "CONVERSATION_CHANGED")
        self.assertEqual(self.backend.send_calls, 0)

    async def test_opaque_id_cannot_select_another_account(self):
        hidden = replace(self.record, account_id=OTHER)
        with self.db() as db:
            db.upsert_conversations([hidden])
        await self.connect()
        with self.assertRaises(AppError):
            await self.core.dispatch({"op": "messages", "conversationId": hidden.id})
        with self.assertRaises(AppError):
            await self.core.dispatch({"op": "select", "conversationId": PEER})

    async def test_send_intent_is_durable_before_network_and_replay_is_suppressed(self):
        await self.connect()
        request_id = str(uuid4())
        original = self.backend.request
        async def checked(*args, **kwargs):
            if args[0] == "send":
                with self.db() as db:
                    self.assertEqual(db.get_outgoing(request_id).status, "sending")
            return await original(*args, **kwargs)
        self.backend.request = checked
        first = await self.send(request_id=request_id)
        self.assertEqual(first["status"], "acknowledged")
        second = await self.send(request_id=request_id)
        self.assertTrue(second["duplicateSuppressed"])
        self.assertEqual(self.backend.send_calls, 1)
        await self.core.close()
        self.core = self.new_core()
        await self.connect()
        third = await self.send(request_id=request_id)
        self.assertTrue(third["duplicateSuppressed"])
        self.assertEqual(self.backend.send_calls, 1)
        for secret in (request_id, BODY, PEER, SELF):
            self.assertNotIn(secret.encode(), self.path.read_bytes())

    async def test_unknown_send_survives_restart_without_automatic_retry(self):
        await self.connect()
        request_id = str(uuid4())
        self.backend.send_error = AppError("LINE_SEND_UNKNOWN")
        with self.assertRaises(AppError):
            await self.send(request_id=request_id)
        self.assertEqual(self.core.db.get_outgoing(request_id).status, "unknown")
        await self.core.close()
        self.core = self.new_core()
        await self.connect()
        self.assertEqual(len(self.core.snapshot()["pendingSends"]), 1)
        with self.assertRaises(AppError):
            await self.send(request_id=request_id)
        self.assertEqual(self.backend.send_calls, 1)

    async def test_crashed_inflight_send_is_not_replayed(self):
        request_id = str(uuid4())
        with self.db() as db:
            db.upsert([], outgoing_requests=[OutgoingRequest(request_id, "line", SELF, PEER, BODY,
                                                             "sending", datetime.now(timezone.utc))])
        await self.connect()
        with self.assertRaises(AppError) as error:
            await self.send(request_id=request_id)
        self.assertEqual(error.exception.code, "LINE_SEND_UNKNOWN")
        self.assertEqual(self.backend.send_calls, 0)

    async def test_send_intent_storage_failure_prevents_remote_send(self):
        await self.connect()
        self.core.db.conn.execute("CREATE TRIGGER fail_intent BEFORE INSERT ON outgoing_requests "
                                  "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(AppError):
            await self.send()
        self.assertEqual(self.backend.send_calls, 0)

    async def test_ack_storage_failure_keeps_uncertain_intent_and_does_not_resend(self):
        await self.connect()
        request_id = str(uuid4())
        self.core.db.conn.execute("CREATE TRIGGER fail_ack BEFORE UPDATE ON outgoing_requests "
                                  "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        with self.assertRaises(AppError) as error:
            await self.send(request_id=request_id)
        self.assertEqual(error.exception.code, "LINE_SENT_NOT_STORED")
        self.assertEqual(self.core.db.get_outgoing(request_id).status, "sending")
        self.assertEqual(self.core.db.total_count(), 1)  # outgoing message rolled back
        with self.assertRaises(AppError):
            await self.send(request_id=request_id)
        self.assertEqual(self.backend.send_calls, 1)

    async def test_duplicate_request_with_changed_text_refused(self):
        await self.connect()
        request_id = str(uuid4())
        await self.send(request_id=request_id)
        with self.assertRaises(AppError) as error:
            await self.send(text="different", request_id=request_id)
        self.assertEqual(error.exception.code, "INVALID_INPUT")
        self.assertEqual(self.backend.send_calls, 1)

    async def test_local_search_scopes_account_and_returns_opaque_result(self):
        await self.connect()
        self.core.db.upsert([replace(normalize_line(raw(id="other-account"), SELF, CONV), account_id=OTHER, text="hidden")])
        result = await self.core.dispatch({"op": "search", "query": BODY})
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["conversationId"], self.record.id)
        self.assertNotIn(SELF, json.dumps(result))
        self.assertEqual((await self.core.dispatch({"op": "search", "query": "hidden"}))["results"], [])

    async def test_saved_conversation_outside_latest_catalog_remains_searchable(self):
        await self.connect()
        await self.core.dispatch({"op": "stop"})
        self.core.db.private_put(self.core.catalog_key(), [self.other.id])
        self.assertNotIn(self.record.id, [c['id'] for c in self.core.snapshot()['conversations']])
        result = self.core.search(BODY)
        self.assertEqual(result['results'][0]['conversationId'], self.record.id)
        history = await self.core.dispatch({'op': 'select', 'conversationId': self.record.id})
        self.assertEqual(history['messages'][0]['text'], BODY)

    async def test_unknown_commands_and_extra_arguments_are_rejected(self):
        for request in ({"op": "execute", "cmd": "anything"}, {"op": "snapshot", "path": "/tmp"},
                        {"op": "send", "conversationId": self.record.id, "text": BODY}):
            with self.subTest(), self.assertRaises(AppError) as error:
                await self.core.dispatch(request)
            self.assertEqual(error.exception.code, "INVALID_INPUT")
        self.assertFalse(self.core.started)

    async def test_stop_cancels_receiver_but_keeps_local_history(self):
        await self.connect()
        await asyncio.wait_for(self.backend.watch_started.wait(), 1)
        await self.core.dispatch({"op": "stop"})
        self.assertTrue(self.backend.closed)
        self.assertIsNone(self.core.watch_task)
        self.assertEqual(self.core.connection, "offline")
        result = await self.core.dispatch({"op": "messages", "conversationId": self.record.id})
        self.assertEqual(len(result["messages"]), 1)

    async def test_outbox_ciphertext_tampering_fails_closed(self):
        await self.connect()
        request_id = str(uuid4())
        await self.send(request_id=request_id)
        self.core.db.conn.execute("UPDATE outgoing_requests SET ciphertext=x'000102'")
        self.core.db.conn.commit()
        with self.assertRaises(AppError) as error:
            self.core.db.get_outgoing(request_id)
        self.assertEqual(error.exception.code, "LOCAL_DB_CORRUPT")

    async def test_unicode_limit_and_blank_messages_do_not_send(self):
        await self.connect()
        for text in ("  ", "😀" * 5001):
            with self.subTest(), self.assertRaises(AppError):
                await self.send(text=text)
        self.assertEqual(self.backend.send_calls, 0)
