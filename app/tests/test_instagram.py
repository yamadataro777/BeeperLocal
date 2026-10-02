from __future__ import annotations

from contextlib import aclosing
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4

from beeperlocal.cli import batch_ready_for_persistence, parser
from beeperlocal.connectors.instagram import (InstagramAdapter, InstagramConnector, conversation,
                                             login_instagram, normalize_instagram, save_session)
from beeperlocal.connectors.registry import create_connector, require_capability
from beeperlocal.errors import AppError
from beeperlocal.instagram_sync import persist_history
from beeperlocal.models import StoredConversation
from beeperlocal.outbox import OutgoingRequest
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore

CONVERSATION = {"id": "111222333", "title": "IG_PRIVATE_TITLE_CANARY", "long_id": "999888777666555444333222111"}
SESSION_EVENT = {"type": "session", "account_id": "123456", "own_fbid": "654321",
                 "session": {"cookies": {"ds_user_id": "123456", "sessionid": "FAKE_IG_SESSION_CANARY", "csrftoken": "FAKE_CSRF"}, "www_claim": ""}}


def message(**overrides):
    return {"id": "mid.CANONICAL_GRAPHQL_ID", "thread_id": CONVERSATION["id"], "sender_id": "777888",
            "sent_at": "2026-09-30T00:01:02.123456Z", "text": "IG_PRIVATE_BODY_CANARY_日本語", "direction": "incoming", **overrides}


def store():
    return MemoryStore({"instagram": {"account_id": "123456", "own_fbid": "654321", "session": deepcopy(SESSION_EVENT["session"]),
                                      "selections": [conversation(CONVERSATION).selection()]}})


def history(*messages, **overrides):
    return {"type": "result", "conversation": deepcopy(CONVERSATION), "messages": list(messages),
            "raw_items": len(messages), "excluded_events": 0, "history_limited": False, **overrides}


class FakeAdapter:
    def __init__(self, *events):
        self.rows = list(events)
        self.requests = []
        self.closed = 0
    async def events(self, request, *, prompt=None):
        self.requests.append(deepcopy(request))
        try:
            for event in self.rows:
                if isinstance(event, Exception):
                    raise event
                yield deepcopy(event)
        finally:
            self.closed += 1


class InstagramNormalizationTests(unittest.TestCase):
    def test_history_send_and_event_identity_is_graphql_id(self):
        conv = conversation(CONVERSATION)
        result = normalize_instagram(message(), "123456", "654321", conv)
        self.assertEqual(result.provider_message_id, "mid.CANONICAL_GRAPHQL_ID")
        sent = normalize_instagram(message(sender_id="654321", direction="outgoing"), "123456", "654321", conv)
        self.assertEqual(result.id, sent.id)
        self.assertEqual(result.sent_at.microsecond, 123456)
        self.assertNotEqual(result.id, replace(result, provider="line").id)
        self.assertNotEqual(result.id, replace(result, account_id="111").id)
        self.assertNotEqual(result.id, replace(result, conversation_id="222").id)

    def test_reject_wrong_thread_direction_and_bad_time(self):
        for changes in ({"thread_id": "999"}, {"direction": "outgoing"}, {"sent_at": "2026-09-30T00:00:00"},
                        {"sent_at": "bad"}, {"sender_id": True}, {"id": ""}, {"text": None}):
            with self.subTest(changes=changes), self.assertRaises(AppError):
                normalize_instagram(message(**changes), "123456", "654321", conversation(CONVERSATION))

    def test_renaming_does_not_change_identity(self):
        first = normalize_instagram(message(), "123456", "654321", conversation(CONVERSATION))
        second = normalize_instagram(message(), "123456", "654321", conversation({**CONVERSATION, "title": "renamed"}))
        self.assertEqual(first.id, second.id)

    def test_session_only_saved_to_provider_record_preserving_selection(self):
        target = store()
        old = deepcopy(target.records["instagram"]["selections"])
        save_session(target, SESSION_EVENT, "123456")
        self.assertEqual(target.writes, ["instagram"])
        self.assertEqual(target.records["instagram"]["selections"], old)
        self.assertNotIn("password", target.records["instagram"])

    def test_session_mismatched_account_or_cookie_is_never_saved(self):
        for event in ({**SESSION_EVENT, "account_id": "777"},
                      {**SESSION_EVENT, "session": {"cookies": {"sessionid": "X"}}}):
            target = store()
            with self.assertRaises(AppError):
                save_session(target, event, "123456")
            self.assertEqual(target.writes, [])

    def test_new_login_account_clears_old_selection(self):
        target = store()
        event = deepcopy(SESSION_EVENT)
        event["account_id"] = event["session"]["cookies"]["ds_user_id"] = "777"
        save_session(target, event)
        self.assertEqual(target.records["instagram"]["selections"], [])

    def test_cli_routes_are_available(self):
        for words in (["login", "instagram"], ["select", "instagram"], ["sync", "instagram"],
                      ["send", "instagram"], ["watch", "instagram"], ["search", "--provider", "instagram"]):
            with self.subTest(words=words):
                self.assertEqual(parser().parse_args(words).provider, "instagram")
        require_capability("instagram", "send_text")
        self.assertIsInstance(create_connector("instagram", store()), InstagramConnector)


class InstagramConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_session_restore_and_history_saved_encrypted_and_found_after_restart(self):
        target = store()
        adapter = FakeAdapter(SESSION_EVENT, history(message()))
        connector = InstagramConnector(target, adapter=adapter)
        batch = await connector.fetch(20)
        self.assertEqual(adapter.requests[0]["session"], SESSION_EVENT["session"])
        self.assertEqual(adapter.closed, 1)
        self.assertTrue(batch_ready_for_persistence(batch))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "private" / "messages.sqlite3"
            with EncryptedMessageStore(bytes(range(32)), path) as db:
                persist_history(db, batch)
                persist_history(db, batch)
                self.assertEqual(db.total_count(), 1)
            with EncryptedMessageStore(bytes(range(32)), path) as db:
                rows, _ = db.search("日本語", provider="instagram")
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].text, message()["text"])
            raw = path.read_bytes()
            for value in [message()["text"], message()["id"], CONVERSATION["title"], CONVERSATION["id"], "FAKE_IG_SESSION_CANARY"]:
                self.assertNotIn(value.encode(), raw)

    async def test_empty_history_is_valid_but_not_live_delivery_evidence(self):
        batch = await InstagramConnector(store(), adapter=FakeAdapter(history())).fetch()
        self.assertTrue(batch_ready_for_persistence(batch))
        self.assertEqual(batch.messages, [])

    async def test_incomplete_batch_never_passes_persistence_gate(self):
        batch = await InstagramConnector(store(), adapter=FakeAdapter(history(message()))).fetch()
        batch.errors.append("IG_REQUEST_FAILED")
        self.assertFalse(batch_ready_for_persistence(batch))

    async def test_history_bad_counts_or_mixed_thread_rejected(self):
        for response in (history(message(), raw_items=2), history(message(thread_id="999")), history(message(), history_limited="false")):
            with self.subTest(response=response), self.assertRaises(AppError):
                await InstagramConnector(store(), adapter=FakeAdapter(response)).fetch()

    async def test_keychain_failure_stops_before_result(self):
        class FailingStore(MemoryStore):
            def save(self, *args):
                raise AppError("KEYCHAIN_UNAVAILABLE")
        target = FailingStore(store().records)
        adapter = FakeAdapter(SESSION_EVENT, history(message()))
        with self.assertRaises(AppError) as error:
            await InstagramConnector(target, adapter=adapter).fetch()
        self.assertEqual(error.exception.code, "KEYCHAIN_UNAVAILABLE")
        self.assertEqual(adapter.closed, 1)

    async def test_send_once_and_ambiguous_send_is_not_retried(self):
        adapter = FakeAdapter(AppError("IG_SEND_UNKNOWN"))
        connector = InstagramConnector(store(), adapter=adapter)
        with self.assertRaises(AppError) as error:
            await connector.send_text("hello")
        self.assertEqual(error.exception.code, "IG_SEND_UNKNOWN")
        self.assertEqual(len(adapter.requests), 1)

    async def test_send_ack_requires_canonical_outgoing_text(self):
        ack = {"type": "result", "message": message(sender_id="654321", direction="outgoing", text="hello"), "encrypted": False}
        result = await InstagramConnector(store(), adapter=FakeAdapter(ack)).send_text("hello")
        self.assertFalse(result.encrypted)
        self.assertEqual(result.message.direction, "outgoing")
        ack["message"]["text"] = "wrong"
        with self.assertRaises(AppError) as error:
            await InstagramConnector(store(), adapter=FakeAdapter(ack)).send_text("hello")
        self.assertEqual(error.exception.code, "IG_SEND_UNKNOWN")

    async def test_watch_recovery_is_atomic_and_separate_from_realtime(self):
        adapter = FakeAdapter(history(message(), type="history"), {"type":"status","code":"connected"},
                              {"type":"message","source":"realtime","message":message(id="mid.new")}, {"type":"done"})
        connector = InstagramConnector(store(), adapter=adapter)
        saved = []
        seen = []
        async with aclosing(connector.watch(persist_history=saved.append)) as stream:
            async for item in stream:
                seen.append(item)
                self.assertEqual(connector.last_event_source, "realtime")
        self.assertEqual(len(saved), 1)
        self.assertEqual(len(saved[0].messages), 1)
        self.assertEqual([item.provider_message_id for item in seen], ["mid.new"])
        self.assertEqual(adapter.closed, 1)

    async def test_watch_storage_failure_closes_stream_without_progress(self):
        adapter = FakeAdapter(history(message(), type="history"), {"type":"message","source":"realtime","message":message(id="mid.new")})
        def fail(_):
            raise AppError("LOCAL_DB_UNAVAILABLE")
        with self.assertRaises(AppError):
            async for _ in InstagramConnector(store(), adapter=adapter).watch(persist_history=fail):
                self.fail("should not start realtime after a failed history commit")
        self.assertEqual(adapter.closed, 1)

    async def test_account_change_is_detected_before_provider_request(self):
        target = store()
        adapter = FakeAdapter(history(message()))
        connector = InstagramConnector(target, adapter=adapter)
        target.records["instagram"]["account_id"] = "777"
        with self.assertRaises(AppError):
            await connector.fetch()
        self.assertEqual(adapter.requests, [])

    async def test_account_fbid_change_never_overwrites_saved_session(self):
        target = store()
        event = {**SESSION_EVENT, "own_fbid": "777"}
        with self.assertRaises(AppError):
            await InstagramConnector(target, adapter=FakeAdapter(event)).fetch()
        self.assertEqual(target.writes, [])

    async def test_login_accepts_session_only_via_keychain(self):
        target = MemoryStore()
        adapter = FakeAdapter(SESSION_EVENT, {"type":"result","account_id":"123456","own_fbid":"654321"})
        await login_instagram(target, adapter=adapter)
        self.assertEqual(target.writes, ["instagram"])
        self.assertEqual(adapter.requests, [{"op":"login"}])

    async def test_invalid_selected_scope_rejected(self):
        for rows in ([], [conversation(CONVERSATION).selection()] * 2,
                     [{**conversation(CONVERSATION).selection(), "kind":"group"}]):
            target = store()
            target.records["instagram"]["selections"] = rows
            with self.assertRaises(AppError):
                await InstagramConnector(target, adapter=FakeAdapter()).send_text("hello")

    async def test_outgoing_intent_survives_restart_and_stays_provider_scoped(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp).resolve() / "private" / "messages.sqlite3"
            request = OutgoingRequest(str(uuid4()), "instagram", "123456", "111222333", "IG_PRIVATE_BODY_CANARY", "sending", datetime.now(timezone.utc))
            with EncryptedMessageStore(bytes(range(32)), path) as db:
                db.upsert([], outgoing_requests=[request])
            with EncryptedMessageStore(bytes(range(32)), path) as db:
                self.assertEqual(len(db.pending_outgoing("123456", provider="instagram")), 1)
                self.assertEqual(db.pending_outgoing("123456"), [])
                self.assertEqual(db.get_outgoing(request.request_id).status, "sending")
            self.assertNotIn(b"IG_PRIVATE_BODY_CANARY", path.read_bytes())


class InstagramBinaryOfflineTests(unittest.IsolatedAsyncioTestCase):
    async def test_private_pipe_session_saved_ack_before_result(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "adapter"
            script.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + '''
import json, sys
request = json.loads(sys.stdin.readline())
assert len(sys.argv) == 1
assert request['session']['cookies']['sessionid'] == 'FAKE_IG_SESSION_CANARY'
print(json.dumps({'type':'session','account_id':'123456','own_fbid':'654321','session':request['session']}), flush=True)
assert json.loads(sys.stdin.readline()) == {'session_saved':True}
print(json.dumps({'type':'result','account_id':'123456','own_fbid':'654321'}), flush=True)
''')
            script.chmod(0o700)
            target = store()
            await InstagramConnector(target, adapter=InstagramAdapter(script)).connect()
            self.assertEqual(target.writes, ["instagram"])

    async def test_send_eof_is_unknown_and_stderr_stays_private(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "adapter"
            script.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + '''
import sys
sys.stdin.readline()
print('PRIVATE_TOKEN_CANARY', file=sys.stderr)
''')
            script.chmod(0o700)
            with self.assertRaises(AppError) as error:
                async for _ in InstagramAdapter(script).events({'op':'send'}):
                    self.fail("unexpected event")
            self.assertEqual(error.exception.code, "IG_SEND_UNKNOWN")
            self.assertNotIn("PRIVATE_TOKEN_CANARY", str(error.exception))

    async def test_malformed_send_reply_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "adapter"
            script.write_text("#!" + str(Path(sys.executable).resolve()) + "\n" + '''
import sys
sys.stdin.readline()
print('not-json', flush=True)
''')
            script.chmod(0o700)
            with self.assertRaises(AppError) as error:
                async for _ in InstagramAdapter(script).events({'op':'send'}):
                    self.fail("unexpected event")
            self.assertEqual(error.exception.code, "IG_SEND_UNKNOWN")

    async def test_real_adapter_invalid_request_exits_without_network(self):
        adapter = InstagramAdapter()
        if not Path(adapter.binary).is_file():
            self.skipTest("build the adapter to test the real IPC binary")
        with self.assertRaises(AppError) as error:
            async for _ in adapter.events({"op":"unsupported"}):
                self.fail("unexpected event")
        self.assertEqual(error.exception.code, "INVALID_INPUT")

    async def test_real_adapter_missing_session_is_safe(self):
        adapter = InstagramAdapter()
        if not Path(adapter.binary).is_file():
            self.skipTest("build the adapter to test the real IPC binary")
        with self.assertRaises(AppError) as error:
            async for _ in adapter.events({"op":"whoami"}):
                self.fail("unexpected event")
        self.assertEqual(error.exception.code, "CREDENTIALS_MISSING")


if __name__ == "__main__":
    unittest.main()
