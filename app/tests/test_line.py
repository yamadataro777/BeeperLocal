from __future__ import annotations
import asyncio
from contextlib import aclosing, redirect_stdout, redirect_stderr
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from beeperlocal import cli
from beeperlocal.connectors.line import LineCLI, LineConnector, attach_session, direct_mid, normalize_line
from beeperlocal.errors import AppError
from beeperlocal.models import Conversation, SendResult, make_report
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore

SELF = "U" + "a" * 43
PEER = "U" + "b" * 43
OTHER = "U" + "c" * 43
BODY = "LINE_PRIVATE_BODY_CANARY"
CONV = Conversation(PEER, "LINE test DM", "dm", {"mid": PEER})
KEY = b"k" * 32


def store():
    return MemoryStore({"line": {"account_id": SELF, "selections": [CONV.selection()]}})


def raw(**changes):
    value = {"id": "1234567890", "from": PEER, "to": SELF, "created_time": 1790726400123,
             "content_type": 0, "text": BODY, "encrypted": True, "status": "decrypted"}
    value.update(changes)
    return value


def event(**changes):
    value = {"event": "message", "revision": "123", "type": 26, "chat_id": PEER, "message": raw()}
    value.update(changes)
    return value


class FakeCLI:
    def __init__(self, *, account=SELF, rows=None, events=None, response=None):
        self.account = account
        self.rows = [raw()] if rows is None else rows
        self.stream = events or []
        self.response = response or {"id": "1234567891", "chat_id": PEER, "encrypted": True}
        self.calls = []
        self.closed = False
    async def whoami(self):
        return self.account
    async def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "messages":
            return self.rows
        if isinstance(self.response, Exception):
            raise self.response
        return self.response
    async def events(self, **kwargs):
        try:
            for value in self.stream:
                yield value
        finally:
            self.closed = True


class NormalizationTests(unittest.TestCase):
    def test_canonical_mid_direction_and_timestamp(self):
        m = normalize_line(raw(), SELF, CONV)
        self.assertEqual((m.provider, m.account_id, m.conversation_id, m.sender_id), ("line", SELF, PEER, PEER))
        self.assertEqual(m.direction, "incoming")
        self.assertEqual(m.sent_at.microsecond, 123000)
        self.assertEqual(m.id, normalize_line(raw(), SELF, replace(CONV, title="renamed")).id)
        self.assertEqual(m.conversation_id, m.to_contract()["conversationId"])
        self.assertEqual(normalize_line(raw(**{"from": SELF, "to": PEER}), SELF, CONV).direction, "outgoing")
    def test_raw_ids_preserve_case_and_reject_names_groups_rooms(self):
        self.assertEqual(direct_mid(PEER), PEER)
        self.assertEqual(direct_mid("u" + "a" * 32), "u" + "a" * 32)
        for value in ["Alice", "Uabc", "C" + "x" * 43, "R" + "x" * 43, "--help", None]:
            with self.assertRaises(AppError):
                direct_mid(value)
    def test_unsupported_content_excluded(self):
        for kind in [1, 2, 7, 13, 14]:
            self.assertIsNone(normalize_line(raw(content_type=kind), SELF, CONV))
    def test_bad_or_undecryptable_text_refused(self):
        for changes in [{"status": "decryption_failed"}, {"to": OTHER}, {"text": None},
                        {"created_time": 0}, {"created_time": True}, {"created_time": "NaN"},
                        {"created_time": "9" * 400}, {"content_type": False}, {"id": ""}]:
            with self.assertRaises(AppError):
                normalize_line(raw(**changes), SELF, CONV)


class ConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_attach_only_saves_identity_and_selection(self):
        memory = store()
        await attach_session(memory, FakeCLI())
        self.assertEqual(set(memory.records["line"]), {"account_id", "selections"})
        self.assertEqual(memory.records["line"]["selections"][0]["id"], PEER)
        await attach_session(memory, FakeCLI(account=OTHER))
        self.assertEqual(memory.records["line"]["selections"], [])
    async def test_selection_and_fetch_use_mid_without_resolver(self):
        backend = FakeCLI()
        connector = LineConnector(store(), cli=backend)
        await connector.select_mid(PEER)
        batch = await connector.fetch(1)
        self.assertEqual(backend.calls[0][0], ("messages", PEER, "--limit", "1", "--json"))
        self.assertEqual(batch.messages[0].conversation_id, PEER)
        self.assertTrue(cli.batch_ready_for_persistence(batch))
        report = make_report([batch])
        self.assertEqual(next(r for r in report["providers"] if r["provider"] == "line")["status"], "PASS")
        self.assertEqual(report["loop_status"], "OPEN")
    async def test_account_change_prevents_send(self):
        backend = FakeCLI(account=OTHER)
        with self.assertRaises(AppError) as ctx:
            await LineConnector(store(), cli=backend).send_text(BODY)
        self.assertEqual(ctx.exception.code, "ACCOUNT_CHANGED")
        self.assertEqual(backend.calls, [])
    async def test_exactly_one_send_with_stdin_body_and_server_id(self):
        backend = FakeCLI()
        result = await LineConnector(store(), cli=backend).send_text(BODY)
        self.assertEqual(backend.calls, [(("send", PEER, "--stdin", "--json"), {"text": BODY, "mutation": True})])
        self.assertEqual(result.message.provider_message_id, "1234567891")
        self.assertEqual(result.message.direction, "outgoing")
        self.assertTrue(result.encrypted)
        self.assertNotIn(BODY, repr(result))
    async def test_no_retry_on_ambiguous_send_or_bad_ack(self):
        for response in [AppError("LINE_SEND_UNKNOWN"), {"id": "", "chat_id": PEER},
                         {"id": "123", "chat_id": OTHER, "encrypted": True}]:
            backend = FakeCLI(response=response)
            with self.assertRaises(AppError) as ctx:
                await LineConnector(store(), cli=backend).send_text(BODY)
            self.assertEqual(ctx.exception.code, "LINE_SEND_UNKNOWN")
            self.assertEqual(len(backend.calls), 1)
    async def test_watch_filters_other_chats_operations_media_and_closes(self):
        backend = FakeCLI(events=[event(chat_id=OTHER), event(event="operation", type=55),
                                  event(message=raw(content_type=7)), event()])
        connector = LineConnector(store(), cli=backend)
        result = [m async for m in connector.watch()]
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].text, BODY)
        self.assertTrue(backend.closed)
    async def test_resync_and_decryption_failures_are_not_success(self):
        for item, code in [(event(event="resync_required"), "LINE_RESYNC_REQUIRED"),
                           (event(message=raw(status="decryption_failed")), "LINE_DECRYPT_FAILED")]:
            backend = FakeCLI(events=[item])
            with self.assertRaises(AppError) as ctx:
                _ = [m async for m in LineConnector(store(), cli=backend).watch()]
            self.assertEqual(ctx.exception.code, code)
            self.assertTrue(backend.closed)

    async def test_bad_history_does_not_authorize_partial_persistence(self):
        backend = FakeCLI(rows=[raw(), raw(status="decryption_failed")])
        batch = await LineConnector(store(), cli=backend).fetch(2)
        self.assertEqual(len(batch.messages), 1)
        self.assertFalse(cli.batch_ready_for_persistence(batch))


class ProcessTests(unittest.IsolatedAsyncioTestCase):
    def transport(self):
        result = LineCLI.__new__(LineCLI)
        result.binary = "/fixture/line"
        return result
    async def test_raw_stderr_never_inherited_and_no_shell(self):
        with patch("asyncio.create_subprocess_exec", new_callable=AsyncMock) as spawn:
            await self.transport()._start("send", PEER, "--stdin", "--json", input_pipe=True)
        args, kwargs = spawn.call_args
        self.assertEqual(args[0], "/fixture/line")
        self.assertEqual(kwargs["stderr"], asyncio.subprocess.DEVNULL)
        self.assertEqual(kwargs["stdout"], asyncio.subprocess.PIPE)
        self.assertTrue(kwargs["start_new_session"])
    async def test_timeout_or_failure_sanitized_and_send_not_retried(self):
        for output, failure, code in [(b"PRIVATE_ACCESS_TOKEN", None, 1), (b"PRIVATE_ACCESS_TOKEN", None, 0),
                                      (b"", TimeoutError("PRIVATE_COOKIE"), None)]:
            class Process:
                returncode = code
                def terminate(self): self.returncode = -15
                def kill(self): self.returncode = -9
                async def wait(self): return self.returncode
                async def communicate(self, body):
                    if failure: raise failure
                    return output, None
            transport = self.transport()
            with patch.object(transport, "_start", new=AsyncMock(return_value=Process())) as start:
                with self.assertRaises(AppError) as ctx:
                    await transport.request("send", PEER, "--stdin", "--json", text=BODY, mutation=True)
                self.assertEqual(str(ctx.exception), "LINE_SEND_UNKNOWN")
                self.assertEqual(start.await_count, 1)
    async def test_real_subprocess_ndjson_is_private_and_terminated(self):
        # Exercise OS pipes and cancellation with a synthetic executable; no LINE access.
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fixture-line"
            import sys
            script.write_text("#!" + sys.executable + "\nimport json, sys, time\n"
                              + "print('PRIVATE_COOKIE', file=sys.stderr, flush=True)\n"
                              + "print(" + repr(json.dumps(event())) + ", flush=True)\n"
                              + "time.sleep(20)\n")
            script.chmod(0o700)
            transport = self.transport()
            transport.binary = str(script)
            processes = []
            original = transport._start
            async def start(*args, **kwargs):
                process = await original(*args, **kwargs)
                processes.append(process)
                return process
            with patch.object(transport, "_start", new=start):
                async with aclosing(transport.events(timeout=5, from_now=False)) as events:
                    received = await anext(events)
                    self.assertEqual(received["message"]["text"], BODY)
            self.assertIsNotNone(processes[0].returncode)


class CorePersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name).resolve() / "state" / "messages-v1.sqlite3"
        self.addCleanup(self.tmp.cleanup)
    def db(self):
        return EncryptedMessageStore(KEY, self.path)
    def test_core_send_realtime_search_reopen_and_encryption(self):
        backend = FakeCLI(events=[event(), event()])
        connector = LineConnector(store(), cli=backend)
        output, errors = io.StringIO(), io.StringIO()
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.open_message_store", side_effect=self.db), patch("beeperlocal.cli.secret_prompt", return_value=BODY), \
             redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(cli.main(["send", "line"]), 0)
            self.assertEqual(cli.main(["watch", "line", "--timeout", "5"]), 0)
        with self.db() as db:
            self.assertEqual(db.count_by_provider(), {"line": 2})
            found, _ = db.search(BODY, provider="line")
            self.assertEqual({m.direction for m in found}, {"incoming", "outgoing"})
            self.assertEqual({m.conversation_id for m in found}, {PEER})
        for secret in [BODY, SELF, PEER]:
            self.assertNotIn(secret.encode(), self.path.read_bytes())
            self.assertNotIn(secret, output.getvalue() + errors.getvalue())
        conn = sqlite3.connect(self.path)
        self.assertFalse(any("fts" in r[0].lower() for r in conn.execute("SELECT name FROM sqlite_master")))
        conn.close()
        with patch("beeperlocal.cli.secret_prompt", return_value=BODY), \
             patch("beeperlocal.storage.db_exists", return_value=True), \
             patch("beeperlocal.cli.MacLocalKeyStore") as keys, \
             patch("beeperlocal.storage.EncryptedMessageStore", side_effect=lambda key: self.db()), redirect_stdout(output):
            keys.return_value.load.return_value = KEY
            self.assertEqual(cli.main(["search", "--provider", "line"]), 0)
        self.assertIn("local_search: matches=2", output.getvalue())
    def test_db_failure_before_send_prevents_network_mutation(self):
        connector = LineConnector(store(), cli=FakeCLI())
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.secret_prompt", return_value=BODY), \
             patch("beeperlocal.cli.open_message_store", side_effect=AppError("LOCAL_DB_KEY_MISMATCH")), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["send", "line"]), 1)
        self.assertEqual(connector.cli.calls, [])
    def test_db_failure_after_ack_does_not_resend(self):
        backend = FakeCLI()
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), \
             patch("beeperlocal.cli.get_connector", return_value=LineConnector(store(), cli=backend)), \
             patch("beeperlocal.cli.secret_prompt", return_value=BODY), \
             patch("beeperlocal.cli.open_message_store") as opener, redirect_stderr(io.StringIO()) as error:
            opener.return_value.__enter__.return_value.upsert.side_effect = RuntimeError(BODY)
            self.assertEqual(cli.main(["send", "line"]), 1)
        self.assertEqual(len(backend.calls), 1)
        self.assertIn("LINE_SENT_NOT_STORED", error.getvalue())
        self.assertNotIn(BODY, error.getvalue())
    def test_zero_incoming_is_not_success(self):
        connector = LineConnector(store(), cli=FakeCLI())
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.open_message_store", side_effect=self.db), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["watch", "line", "--timeout", "1"]), 1)

    def test_max_messages_counts_only_unique_incoming_and_closes_stream(self):
        backend = FakeCLI(events=[event(type=25, message=raw(**{"from": SELF, "to": PEER, "id": "sent"})),
                                  event(), event(), event(message=raw(id="second-reply")),
                                  event(message=raw(id="must-not-read"))])
        connector = LineConnector(store(), cli=backend)
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.open_message_store", side_effect=self.db), redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["watch", "line", "--max-messages", "2"]), 0)
        with self.db() as db:
            self.assertEqual(db.total_count(), 3)
        self.assertTrue(backend.closed)

    def test_fetch_line_writes_allowlisted_body_free_report(self):
        from beeperlocal.reporting import save_report
        backend = FakeCLI()
        connector = LineConnector(store(), cli=backend)
        report_dir = self.path.parent / "reports"
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.save_report", side_effect=lambda report, name: save_report(report, name, report_dir)), \
             redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["fetch", "line", "--limit", "1"]), 0)
        report = (report_dir / "last-fetch-line.json").read_text()
        for secret in (BODY, SELF, PEER):
            self.assertNotIn(secret, report)
    def test_new_arguments_and_provider_defaults(self):
        parser = cli.parser()
        self.assertIsNone(parser.parse_args(["sync"]).provider)
        self.assertEqual(parser.parse_args(["sync", "line"]).provider, "line")
        for args in [["send", "line", BODY], ["select", "line", PEER]]:
            with redirect_stderr(io.StringIO()) as error, self.assertRaises(SystemExit):
                parser.parse_args(args)
            self.assertNotIn(BODY, error.getvalue())
            self.assertNotIn(PEER, error.getvalue())
