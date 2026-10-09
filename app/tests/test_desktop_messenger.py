"""Messenger integration tests. All identities, device material and text are synthetic."""
import asyncio
from contextlib import aclosing, nullcontext
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from beeperlocal.desktop_messenger import MessengerDesktop
from beeperlocal.desktop_router import DesktopRouter
from beeperlocal.errors import AppError
from beeperlocal.messenger import DeviceStore, MessengerSession, MAX_FRAME, normalize_checkpoint, session_lock, validate_state
from beeperlocal.models import Conversation, StoredConversation, SendResult
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore

ACCOUNT = "123456789001"
CHAT = "987654321009@msgr"
COOKIES = {"c_user": ACCOUNT, "xs": "FIXTURE_LOGIN_ONLY", "datr": "FIXTURE_DEVICE_ONLY"}
STATE = {"version": 1, "cookies": COOKIES, "device_db": "FIXTURE_SNAPSHOT_ONLY"}
CATALOG = [{"id": CHAT, "title": "MESSENGER_TITLE_CANARY"}]


def message(**updates):
    return {"provider": "messenger", "account": ACCOUNT, "conversation": CHAT, "id": "fixture-message-1",
            "sender": CHAT, "direction": "incoming", "timestamp": 1790910000,
            "text": "MESSENGER_BODY_CANARY 日本語", **updates}


def checkpoint(*rows, **updates):
    return {"kind": "checkpoint", "state": deepcopy(STATE), "messages": list(rows), "conversations": CATALOG, **updates}


class Backend:
    def __init__(self, state=None):
        self.value = json.dumps(state) if state is not None else None
        self.writes = 0
        self.failure = False
    def get_password(self, service, account):
        return self.value
    def set_password(self, service, account, value):
        if self.failure:
            raise RuntimeError("FIXTURE_PRIVATE_NATIVE_ERROR")
        self.writes += 1
        self.value = value


class Session:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.runs = self.live = 0
        self.rows = [message()]
        self.login_result = ACCOUNT
        self.sends = 0
        self.send_error = None
        self.before_send = lambda: None
    async def send_text(self, conversation, text, account, *, authorize=None):
        if authorize: authorize()
        self.before_send()
        self.sends += 1
        if self.send_error:
            raise self.send_error
        rows, _ = normalize_checkpoint(checkpoint(message(id="fixture-outgoing", conversation=conversation,
            direction="outgoing", text=text, sender=ACCOUNT + "@msgr")), account)
        return SendResult(rows[0], encrypted=True)
    async def watch(self, persist, *, account="", require_device=False):
        self.runs += 1
        self.live += 1
        try:
            persist(checkpoint(*self.rows), ACCOUNT)
            yield "connected"
            while True:
                event = await self.queue.get()
                if isinstance(event, Exception):
                    raise event
                if event is None:
                    return
                persist(event, ACCOUNT)
        finally:
            self.live -= 1
    async def login(self, account, *, require_device=False):
        return self.login_result


class StateTests(unittest.TestCase):
    def test_device_store_preserves_current_identity(self):
        backend = Backend(STATE)
        store = DeviceStore(backend)
        value = store.load()
        value["cookies"]["xs"] = "REFRESHED_FIXTURE_LOGIN"
        store.save(value)
        self.assertEqual(store.load()["device_db"], STATE["device_db"])
        self.assertEqual(backend.writes, 1)

    def test_keychain_failure_and_invalid_state_never_reset(self):
        backend = Backend(STATE)
        before = backend.value
        backend.failure = True
        with self.assertRaises(AppError) as caught:
            DeviceStore(backend).save(STATE)
        self.assertNotIn("FIXTURE_PRIVATE_NATIVE_ERROR", str(caught.exception))
        self.assertEqual(backend.value, before)
        for state in ({}, {**STATE, "version": True}, {**STATE, "cookies": {}}, {**STATE, "device_db": "x" * MAX_FRAME}):
            with self.assertRaises(AppError):
                DeviceStore(backend).save(state)
        self.assertEqual(backend.writes, 0)

    def test_full_batch_validation_scope_and_identity(self):
        baseline, _ = normalize_checkpoint(checkpoint(message()), ACCOUNT)
        first = baseline[0]
        for updates in ({"provider": "line"}, {"account": "99"}, {"conversation": "123@g.us"},
                        {"id": ""}, {"timestamp": True}, {"timestamp": 10**100}, {"text": []}, {"direction": "peer"}):
            with self.assertRaises(AppError):
                normalize_checkpoint(checkpoint(message(), message(**updates)), ACCOUNT)
        self.assertNotEqual(first.id, replace(first, provider="line").id)
        self.assertNotEqual(first.id, replace(first, account_id="55").id)
        self.assertNotEqual(first.id, replace(first, conversation_id="88@msgr").id)

    def test_checkpoint_requires_current_sender_and_direction(self):
        raw = message()
        del raw["sender"], raw["direction"]
        with self.assertRaises(AppError) as caught:
            normalize_checkpoint({"messages": [raw]}, ACCOUNT)
        self.assertEqual(caught.exception.code, "MESSENGER_PROTOCOL_ERROR")

    def test_exclusive_session_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder).resolve() / "private"
            with session_lock(directory):
                with self.assertRaises(AppError):
                    with session_lock(directory):
                        self.fail("concurrent writer accepted")
            with session_lock(directory):
                pass
            other = Path(folder).resolve() / "unsafe"
            other.mkdir()
            (other / "session.lock").symlink_to(directory / "session.lock")
            with self.assertRaises(OSError):
                with session_lock(other):
                    self.fail("symlink accepted")


class PipeTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self, code, state=STATE):
        backend = Backend(deepcopy(state))
        session = MessengerSession(device_store=DeviceStore(backend), command=[sys.executable, "-B", "-c", code],
                                   login_command=[sys.executable, "-B", "-c", code], lock=nullcontext)
        return session, backend

    def child(self, event):
        return ("import json,sys;sys.stdin.readline();print(" + repr(json.dumps(event)) + ",flush=True);"
                "assert json.loads(sys.stdin.readline())=={'ok':True};"
                "print(json.dumps({'kind':'status','code':'connected'}),flush=True);sys.stdin.readline()")

    async def test_commit_then_keychain_verify_then_ack(self):
        session, backend = self.make_session(self.child(checkpoint(message())))
        order = []
        save = session.store.save
        def persist(event, account):
            self.assertEqual(account, ACCOUNT)
            if event.get("kind") == "checkpoint":
                order.append("db_committed")
        def store(state):
            self.assertEqual(order, ["db_committed"])
            save(state)
            order.append("keychain_verified")
        session.store.save = store
        async with aclosing(session.watch(persist)) as stream:
            self.assertEqual(await anext(stream), "connected")
            self.assertEqual(order, ["db_committed", "keychain_verified"])
        self.assertEqual(backend.writes, 1)

    async def test_db_or_keychain_failure_never_acknowledges(self):
        for failure in ("db", "keychain"):
            session, backend = self.make_session(self.child(checkpoint(message())))
            writes = []
            original = session._write
            async def write(proc, frame):
                writes.append(frame.get("ok"))
                await original(proc, frame)
            session._write = write
            backend.failure = failure == "keychain"
            def persist(event, account):
                if event.get("kind") == "checkpoint" and failure == "db":
                    raise AppError("LOCAL_DB_UNAVAILABLE")
            with self.assertRaises(AppError):
                async with aclosing(session.watch(persist)) as stream:
                    await anext(stream)
            self.assertNotIn(True, writes)
            self.assertEqual(backend.writes, 0)

    async def test_old_body_cache_is_rejected_before_import_spawn_or_keychain_write(self):
        state = {**STATE, "messages": {"old": message()}}
        session, backend = self.make_session("raise AssertionError()", state)
        before = backend.value
        def never(*args): self.fail("must not import old bodies")
        with patch.object(session, "_spawn", side_effect=AssertionError("must not spawn")):
            with self.assertRaises(AppError) as caught:
                async with aclosing(session.watch(never)) as stream:
                    await anext(stream)
        self.assertEqual(caught.exception.code, "MESSENGER_DEVICE_INVALID")
        self.assertEqual(backend.value, before)
        self.assertEqual(backend.writes, 0)

    async def test_registration_pending_and_account_change_stop_before_spawn(self):
        for state, account, expected in (({**STATE, "registration_pending": True}, "", "MESSENGER_REGISTRATION_UNKNOWN"),
                                         (STATE, "999", "ACCOUNT_CHANGED")):
            session, backend = self.make_session("raise AssertionError()", state)
            with patch.object(session, "_spawn", side_effect=AssertionError("must not spawn")):
                with self.assertRaises(AppError) as caught:
                    async with aclosing(session.watch(lambda *args: None, account=account)) as stream:
                        await anext(stream)
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(backend.writes, 0)

    async def test_invalid_private_response_cannot_leak_raw_values(self):
        for response in ("private-invalid-json", json.dumps({"kind": "status", "code": "PRIVATE_BODY_ERROR"})):
            session, _ = self.make_session("import sys;sys.stdin.readline();print(" + repr(response) + ",flush=True)")
            with self.assertRaises(AppError) as caught:
                async with aclosing(session.watch(lambda *args: None)) as stream:
                    await anext(stream)
            self.assertEqual(caught.exception.code, "MESSENGER_PROTOCOL_ERROR")
            self.assertNotIn("PRIVATE_BODY_ERROR", str(caught.exception))

    async def test_cookie_refresh_preserves_device_and_rejects_other_account(self):
        for account in (ACCOUNT, "999"):
            result = {"ok": True, "cookies": {**COOKIES, "c_user": account, "xs": "NEW_FIXTURE"}}
            session, backend = self.make_session("import sys;sys.stdin.readline();print(" + repr(json.dumps(result)) + ",flush=True)")
            before = backend.value
            if account == ACCOUNT:
                self.assertEqual(await session.login(ACCOUNT), ACCOUNT)
                self.assertEqual(session.store.load()["device_db"], STATE["device_db"])
            else:
                with self.assertRaises(AppError) as caught:
                    await session.login(ACCOUNT)
                self.assertEqual(caught.exception.code, "ACCOUNT_CHANGED")
                self.assertEqual(backend.value, before)

    async def test_pending_registration_blocks_login_as_well(self):
        session, backend = self.make_session("raise AssertionError()", {**STATE, "registration_pending": True})
        with self.assertRaises(AppError) as caught:
            await session.login()
        self.assertEqual(caught.exception.code, "MESSENGER_REGISTRATION_UNKNOWN")
        self.assertEqual(backend.writes, 0)

    async def test_missing_registered_device_never_becomes_fresh_login(self):
        for state in (None, {"version": 1, "cookies": COOKIES}):
            session, backend = self.make_session("raise AssertionError()", state)
            with patch.object(session, "_spawn", side_effect=AssertionError("must not spawn")):
                with self.assertRaises(AppError) as caught:
                    await session.login(ACCOUNT, require_device=True)
                self.assertEqual(caught.exception.code, "MESSENGER_DEVICE_INVALID")
                with self.assertRaises(AppError):
                    async with aclosing(session.watch(lambda *args: None, account=ACCOUNT, require_device=True)) as stream:
                        await anext(stream)
            self.assertEqual(backend.writes, 0)

    async def test_replayed_message_after_storage_interruption_is_idempotent(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder).resolve() / "private/messages.db"
            db = EncryptedMessageStore(b"m" * 32, path)
            def persist(event, account):
                rows, records = normalize_checkpoint(event, account)
                db.upsert(rows, conversations=records)
            first, backend = self.make_session(self.child(checkpoint(message())))
            backend.failure = True
            with self.assertRaises(AppError):
                async with aclosing(first.watch(persist)) as stream:
                    await anext(stream)
            db.close()
            db = EncryptedMessageStore(b"m" * 32, path)
            try:
                second, _ = self.make_session(self.child(checkpoint(message())))
                async with aclosing(second.watch(persist)) as stream:
                    self.assertEqual(await anext(stream), "connected")
                self.assertEqual(db.total_count(), 1)
                self.assertNotIn(b"MESSENGER_BODY_CANARY", path.read_bytes())
            finally:
                db.close()


class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / "private/messages.db"
        self.credentials = MemoryStore()
        self.session = Session()
        self.events = []
        self.core = self.make_core()
    def make_core(self):
        return MessengerDesktop(credentials=self.credentials, db_factory=lambda: EncryptedMessageStore(b"m" * 32, self.path),
                                session_factory=lambda: self.session, emit=self.events.append)
    async def asyncTearDown(self):
        await self.core.close()
    async def until(self, predicate):
        for _ in range(100):
            if predicate():
                return
            await asyncio.sleep(.005)
        self.fail("fixture state not reached")

    async def test_receive_restart_search_and_encrypted_identities(self):
        snapshot = await self.core.dispatch({"op": "connect"})
        identity = snapshot["conversations"][0]["id"]
        await self.core.dispatch({"op": "select", "conversationId": identity})
        self.assertEqual(self.session.runs, 1)  # Changing selection does not restart the device.
        await self.session.queue.put(checkpoint(message(id="new", text="MESSENGER_NEW_BODY")))
        await self.until(lambda: self.core.db.total_count() == 2)
        await self.core.close()
        self.core = self.make_core()
        snapshot = await self.core.dispatch({"op": "snapshot"})
        self.assertEqual(snapshot["connection"], "offline")
        self.assertEqual(snapshot["selectedId"], identity)
        self.assertEqual(len((await self.core.dispatch({"op": "search", "query": "MESSENGER_NEW_BODY"}))["results"]), 1)
        for canary in (ACCOUNT, CHAT, "fixture-message-1", "MESSENGER_TITLE_CANARY", "MESSENGER_BODY_CANARY", "MESSENGER_NEW_BODY"):
            self.assertNotIn(canary.encode(), self.path.read_bytes())

    async def test_chat_switches_never_access_keychain_and_last_selection_survives_restart(self):
        await self.core.dispatch({'op': 'connect'})
        original = self.core._records()[0]
        other = StoredConversation('messenger', ACCOUNT, Conversation('987654321008@msgr', 'OTHER_FIXTURE', 'dm', {}))
        self.core.db.upsert_conversations([other])
        with patch.object(self.credentials, 'load', side_effect=AssertionError('selection must not read credentials')), \
             patch.object(self.credentials, 'save', side_effect=AssertionError('selection must not write credentials')):
            for record in [original, other, original, other, other]:
                await self.core.dispatch({'op': 'select', 'conversationId': record.id})
        await self.core.close()
        self.core = self.make_core()
        self.assertEqual((await self.core.dispatch({'op': 'snapshot'}))['selectedId'], other.id)
        # Opaque local hashes are indexes; the saved JSON preference is encrypted.
        self.assertNotIn(json.dumps(other.id).encode(), self.path.read_bytes())
        self.assertNotIn(other.conversation.id.encode(), self.path.read_bytes())

    async def test_keychain_selection_is_not_imported_and_stale_db_selection_is_ignored(self):
        await self.core.dispatch({'op': 'connect'})
        record = self.core._records()[0]
        await self.core.close()
        self.credentials.save('messenger', {'account_id': ACCOUNT, 'selections': [record.conversation.selection()]})
        self.core = self.make_core()
        with patch.object(self.credentials, 'save', side_effect=AssertionError('selection must not write credentials')):
            self.assertIsNone((await self.core.dispatch({'op': 'snapshot'}))['selectedId'])
        self.assertIsNone(self.core.db.private_get(self.core._selection_key()))
        self.core.db.private_put(self.core._selection_key(), 'f' * 64)
        await self.core.close()
        self.core = self.make_core()
        self.assertIsNone((await self.core.dispatch({'op': 'snapshot'}))['selectedId'])

    async def test_send_persists_intent_and_uses_same_device_with_deduplication(self):
        snapshot = await self.core.dispatch({"op": "connect"})
        identity = snapshot["conversations"][0]["id"]
        await self.core.dispatch({"op": "select", "conversationId": identity})
        request_id = str(uuid4())
        self.session.before_send = lambda: self.assertEqual(self.core.db.get_outgoing(request_id).status, "sending")
        command = {"op": "send", "conversationId": identity, "text": "FIXTURE_SEND", "requestId": request_id}
        self.assertEqual((await self.core.dispatch(command))["status"], "acknowledged")
        self.assertTrue((await self.core.dispatch(command))["duplicateSuppressed"])
        self.assertEqual(self.session.sends, 1)
        self.assertEqual(self.session.runs, 1)

    async def test_ambiguous_send_is_never_retried_after_restart(self):
        snapshot = await self.core.dispatch({"op": "connect"})
        identity = snapshot["conversations"][0]["id"]
        await self.core.dispatch({"op": "select", "conversationId": identity})
        command = {"op": "send", "conversationId": identity, "text": "FIXTURE_SEND", "requestId": str(uuid4())}
        self.session.send_error = AppError("MESSENGER_SEND_UNKNOWN")
        with self.assertRaises(AppError): await self.core.dispatch(command)
        await self.core.close()
        self.core = self.make_core()
        await self.core.dispatch({"op": "connect"})
        with self.assertRaises(AppError): await self.core.dispatch(command)
        self.assertEqual(self.session.sends, 1)

    async def test_delete_stops_receiver_without_erasing_device_marker(self):
        await self.core.dispatch({"op": "connect"})
        preview = await self.core.dispatch({"op": "storage_delete_preview"})
        self.assertEqual(self.session.live, 0)
        await self.core.dispatch({"op": "storage_delete", "confirmation": preview["confirmation"]})
        self.assertEqual(self.core.db.total_count(), 0)
        self.assertEqual(self.core.db.private_get("messenger.registered_account"), ACCOUNT)
        self.assertTrue(self.core.settings["storagePaused"])

    async def test_more_than_200_messages_use_main_store(self):
        await self.core.dispatch({"op": "connect"})
        for n in range(201):
            self.core._persist(checkpoint(message(id=f"fixture-{n}")), ACCOUNT)
        self.assertEqual(self.core.db.total_count(), 202)
        self.assertEqual(len(self.core.messages(self.core._records()[0].id)["messages"]), 100)

    async def test_incomplete_requests_other_login_and_cross_account_access_are_rejected(self):
        await self.core.dispatch({"op": "connect"})
        for op in ("send", "mcp_configure", "mcp_register", "line_login_start", "x_login_start", "avatar", "storage_delete"):
            with self.assertRaises(AppError):
                await self.core.dispatch({"op": op})
        original = self.core._records()[0]
        foreign = replace(original, account_id="999")
        self.core.db.upsert_conversations([foreign])
        with self.assertRaises(AppError):
            await self.core.dispatch({"op": "select", "conversationId": foreign.id})
        self.assertEqual(len(self.core.snapshot()["conversations"]), 1)
        self.assertIsNone(self.core.mcp_runtime)

    async def test_pause_stops_receiver_and_persists_across_restart(self):
        await self.core.dispatch({"op": "connect"})
        await self.core.dispatch({"op": "storage_pause", "paused": True})
        self.assertEqual(self.session.live, 0)
        with self.assertRaises(AppError):
            await self.core.dispatch({"op": "connect"})
        await self.core.close()
        self.core = self.make_core()
        self.assertTrue((await self.core.dispatch({"op": "snapshot"}))["storagePaused"])

    async def test_registered_account_survives_missing_metadata_and_rejects_switch(self):
        await self.core.dispatch({"op": "connect"})
        await self.core.close()
        self.credentials = MemoryStore()
        self.core = self.make_core()
        snapshot = await self.core.dispatch({"op": "snapshot"})
        self.assertEqual(len(snapshot["conversations"]), 1)
        self.assertEqual(self.core.account_id, ACCOUNT)
        await self.core.close()
        self.credentials = MemoryStore({"messenger": {"account_id": "999", "selections": []}})
        self.core = self.make_core()
        with self.assertRaises(AppError) as caught:
            await self.core.dispatch({"op": "snapshot"})
        self.assertEqual(caught.exception.code, "ACCOUNT_CHANGED")

    async def test_reconnect_restores_stream_and_storage_failure_does_not_retry(self):
        await self.core.dispatch({"op": "connect"})
        self.core.retry_delays = (.001,)
        await self.session.queue.put(None)
        await self.until(lambda: self.session.runs == 2 and self.core.receiving == "waiting")
        self.assertEqual(self.core.db.total_count(), 1)
        await self.session.queue.put(AppError("KEYCHAIN_ACCESS_DENIED"))
        await self.until(lambda: self.core.receiving == "error")
        await asyncio.sleep(.03)
        self.assertEqual(self.session.runs, 2)
        self.assertEqual(self.core.error_code, "KEYCHAIN_ACCESS_DENIED")

    async def test_stop_cancels_scheduled_reconnect(self):
        await self.core.dispatch({"op": "connect"})
        self.core.retry_delays = (.05,)
        await self.session.queue.put(None)
        await self.until(lambda: self.core.receiving == "reconnecting")
        await self.core.dispatch({"op": "stop"})
        await asyncio.sleep(.07)
        self.assertEqual(self.session.runs, 1)

    async def test_invalid_batch_never_partially_saves(self):
        await self.core.dispatch({"op": "connect"})
        await self.session.queue.put(checkpoint(message(id="valid-new"), message(id="invalid-new", account="999")))
        await self.until(lambda: self.core.receiving == "error")
        self.assertEqual(self.core.db.total_count(), 1)

    async def test_router_tags_events_and_only_constructs_requested_core(self):
        router = DesktopRouter(messenger_factory=lambda emit: MessengerDesktop(credentials=self.credentials,
            db_factory=lambda: EncryptedMessageStore(b"m" * 32, self.path), session_factory=lambda: self.session, emit=emit),
            emit=self.events.append)
        try:
            result = await router.dispatch({"provider": "messenger", "op": "connect"})
            self.assertEqual(result["connection"], "connected")
            self.assertEqual(set(router.cores), {"messenger"})
            self.assertTrue(all(e["provider"] == "messenger" for e in self.events))
        finally:
            await router.close()
