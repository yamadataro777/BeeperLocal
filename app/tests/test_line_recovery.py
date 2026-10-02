"""Crash/replay/identity boundaries for bounded recovery; no live credentials."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beeperlocal import cli
from beeperlocal.connectors.line import LineConnector, normalize_line
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from beeperlocal.sync import line_history_receipt, persist_line_history, recover_line_history
from .test_line import SELF, PEER, OTHER, CONV, KEY, BODY, FakeCLI, event, raw, store


class RecoveryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / "state" / "messages.sqlite3"
        self.record = StoredConversation("line", SELF, CONV)

    def db(self):
        return EncryptedMessageStore(KEY, self.path)

    def connector(self, **kwargs):
        return LineConnector(store(), cli=FakeCLI(**kwargs))

    async def test_reopen_replay_updates_edits_and_encrypts_receipt(self):
        with self.db() as db:
            first, stats = await recover_line_history(self.connector(), db)
            self.assertEqual(stats["inserted"], 1)
        with self.db() as db:
            self.assertEqual(db.get_sync_receipt(self.record), first)
            second, stats = await recover_line_history(self.connector(rows=[raw(text="changed private text")]), db)
            self.assertEqual(stats, {"processed": 1, "inserted": 0, "updated": 1})
            self.assertEqual(db.get_sync_receipt(self.record), second)
            self.assertEqual(db.total_count(), 1)
            self.assertEqual(db.search("changed private")[0][0].text, "changed private text")
        for value in (SELF, PEER, BODY, "changed private text", "completed_at", "raw_items"):
            self.assertNotIn(value.encode(), self.path.read_bytes())
        self.assertNotIn(SELF, repr(first))
        self.assertNotIn(PEER, repr(first))

    async def test_receipt_write_failure_rolls_back_messages_and_conversation(self):
        with self.db() as db:
            original, _ = await recover_line_history(self.connector(), db)
            original_message = db.list_messages("line", SELF, PEER)[0]
            db.conn.execute("CREATE TRIGGER refuse_receipt BEFORE INSERT ON sync_receipts "
                            "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
            connector = self.connector(rows=[raw(text="must roll back"), raw(id="new")])
            connector.credentials["selections"] = [replace(CONV, title="must roll back").selection()]
            with self.assertRaises(AppError):
                await recover_line_history(connector, db)
            self.assertEqual(db.get_sync_receipt(self.record), original)
            self.assertEqual(db.list_messages("line", SELF, PEER), [original_message])
            self.assertEqual(db.list_conversations(), [self.record])

    async def test_message_write_failure_does_not_create_receipt(self):
        with self.db() as db:
            db.conn.execute("CREATE TRIGGER refuse_message BEFORE INSERT ON messages "
                            "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
            with self.assertRaises(AppError):
                await recover_line_history(self.connector(), db)
            self.assertIsNone(db.get_sync_receipt(self.record))
            self.assertEqual(db.list_conversations(), [])

    async def test_fetch_failure_keeps_previous_success(self):
        with self.db() as db:
            receipt, _ = await recover_line_history(self.connector(), db)
            with self.assertRaises(AppError) as error:
                await recover_line_history(self.connector(rows=[raw(id="unsaved"), raw(status="decryption_failed")]), db)
            self.assertEqual(error.exception.code, "LINE_DECRYPT_FAILED")
            self.assertEqual(db.get_sync_receipt(self.record), receipt)
            self.assertEqual(db.total_count(), 1)

    async def test_scope_substitution_and_incomplete_batches_rejected_before_write(self):
        batch = await self.connector().fetch()
        wrong_message = replace(batch.messages[0], account_id=OTHER)
        for broken in (replace(batch, messages=[wrong_message]), replace(batch, live=False),
                       replace(batch, conversations_fetched=0), replace(batch, raw_items=0),
                       replace(batch, normalization_errors=1), replace(batch, messages=batch.messages * 2)):
            with self.subTest(), self.db() as db:
                with self.assertRaises(AppError):
                    persist_line_history(db, broken)
                self.assertEqual(db.total_count(), 0)
                self.assertIsNone(db.get_sync_receipt(self.record))

    async def test_empty_and_media_only_history_recorded_without_live_success(self):
        for rows, excluded in (([], 0), ([raw(content_type=7)], 1)):
            with self.subTest(), self.db() as db:
                receipt, stats = await recover_line_history(self.connector(rows=rows), db)
                self.assertEqual(stats["processed"], 0)
                self.assertEqual(receipt.excluded_events, excluded)
                self.assertEqual(receipt.raw_items, len(rows))
                self.assertEqual(receipt.stored_messages, 0)
                self.assertEqual(db.get_sync_receipt(self.record), receipt)
                self.assertFalse(receipt.history_limited)

    async def test_limit_and_conversation_account_provider_scoping(self):
        with self.db() as db:
            receipt, _ = await recover_line_history(self.connector(), db, limit=1)
            self.assertTrue(receipt.history_limited)
            for other in (replace(self.record, account_id=OTHER), replace(self.record, provider="matrix"),
                          replace(self.record, conversation=replace(CONV, id=OTHER))):
                self.assertIsNone(db.get_sync_receipt(other))
            self.assertEqual(db.get_sync_receipt(replace(self.record, conversation=replace(CONV, title="renamed"))), receipt)
            for invalid in (0, 101, True):
                with self.assertRaises(AppError):
                    await recover_line_history(self.connector(), db, limit=invalid)

    async def test_receipt_tampering_and_row_swap_detected(self):
        batch = await self.connector().fetch()
        first = line_history_receipt(batch)
        second = replace(first, conversation_id=OTHER)
        other_record = replace(self.record, conversation=replace(CONV, id=OTHER))
        with self.db() as db:
            db.upsert(batch.messages, conversations=[self.record, other_record], sync_receipts=[first, second])
            blob = db.conn.execute("SELECT ciphertext FROM sync_receipts WHERE id=?", (first.id,)).fetchone()[0]
            db.conn.execute("UPDATE sync_receipts SET ciphertext=? WHERE id=?", (blob, second.id))
            db.conn.commit()
            with self.assertRaises(AppError) as error:
                db.get_sync_receipt(other_record)
            self.assertEqual(error.exception.code, "LOCAL_DB_CORRUPT")
            db.conn.execute("UPDATE sync_receipts SET ciphertext=? WHERE id=?", (blob[:-1] + bytes([blob[-1] ^ 1]), first.id))
            db.conn.commit()
            with self.assertRaises(AppError):
                db.get_sync_receipt(self.record)

    async def test_additive_table_keeps_old_message_ciphertext(self):
        message = normalize_line(raw(), SELF, CONV)
        with self.db() as db:
            db.upsert([message])
            old = tuple(db.conn.execute("SELECT * FROM messages").fetchone())
            db.conn.execute("DROP TABLE sync_receipts")
            db.conn.commit()
        with self.db() as db:
            self.assertEqual(tuple(db.conn.execute("SELECT * FROM messages").fetchone()), old)
            self.assertIsNone(db.get_sync_receipt(self.record))
            await recover_line_history(self.connector(), db)
            self.assertEqual(db.total_count(), 1)


class RecoveryCLITests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / "state" / "messages.sqlite3"
        self.record = StoredConversation("line", SELF, CONV)

    def db(self, *args):
        return EncryptedMessageStore(KEY, self.path)

    def run_cli(self, args, connector):
        output = io.StringIO()
        with patch("beeperlocal.cli.MacKeychain", return_value=store()), \
             patch("beeperlocal.cli.get_connector", return_value=connector), \
             patch("beeperlocal.cli.open_message_store", side_effect=self.db), \
             patch("beeperlocal.storage.db_exists", return_value=True), \
             patch("beeperlocal.cli.MacLocalKeyStore") as keys, \
             patch("beeperlocal.storage.EncryptedMessageStore", side_effect=self.db), \
             patch("beeperlocal.cli.save_report"), redirect_stdout(output), redirect_stderr(output):
            keys.return_value.load.return_value = KEY
            code = cli.main(args)
        text = output.getvalue()
        for secret in (BODY, SELF, PEER):
            self.assertNotIn(secret, text)
        return code, text

    def test_daemon_recovers_before_stream_and_counts_only_stream_incoming(self):
        backend = FakeCLI(rows=[raw(id="missed-during-stop")], events=[event(message=raw(id="new-reply"))])
        connector = LineConnector(store(), cli=backend)
        original = backend.events
        async def checked_events(**kwargs):
            with self.db() as db:
                self.assertIsNotNone(db.get_sync_receipt(self.record))
                self.assertEqual(db.total_count(), 1)
            async for item in original(**kwargs):
                yield item
        backend.events = checked_events
        code, text = self.run_cli(["daemon", "line", "--max-messages", "1", "--recovery-limit", "100"], connector)
        self.assertEqual(code, 0)
        self.assertIn("incoming_unique=1", text)
        self.assertEqual(backend.calls[0][0], ("messages", PEER, "--limit", "100", "--json"))
        with self.db() as db:
            self.assertEqual(db.total_count(), 2)

    def test_recovered_history_alone_does_not_count_as_realtime_success(self):
        code, text = self.run_cli(["watch", "line", "--timeout", "1"], LineConnector(store(), cli=FakeCLI()))
        self.assertEqual(code, 1)
        self.assertIn("line_history=RECOVERED", text)
        self.assertIn("incoming_unique=0", text)

    def test_failed_recovery_does_not_start_watch(self):
        backend = FakeCLI(rows=[raw(status="decryption_failed")], events=[event()])
        code, text = self.run_cli(["daemon", "line", "--timeout", "1"], LineConnector(store(), cli=backend))
        self.assertEqual(code, 1)
        self.assertFalse(backend.closed)  # events never entered
        self.assertNotIn("line_watch=STARTING", text)
        with self.db() as db:
            self.assertEqual(db.total_count(), 0)
            self.assertIsNone(db.get_sync_receipt(self.record))

    def test_from_now_skips_recovery_and_does_not_create_receipt(self):
        backend = FakeCLI(events=[event()])
        code, text = self.run_cli(["watch", "line", "--from-now", "--max-messages", "1"], LineConnector(store(), cli=backend))
        self.assertEqual(code, 0)
        self.assertEqual(backend.calls, [])
        self.assertIn("line_history=SKIPPED", text)
        with self.db() as db:
            self.assertIsNone(db.get_sync_receipt(self.record))

    def test_sync_and_offline_status_share_receipt_without_provider_calls(self):
        backend = FakeCLI()
        connector = LineConnector(store(), cli=backend)
        code, text = self.run_cli(["sync", "line", "--limit", "1"], connector)
        self.assertEqual(code, 0)
        self.assertIn("limit_reached=true", text)
        backend.calls.clear()
        code, text = self.run_cli(["sync-status", "line"], connector)
        self.assertEqual(code, 0)
        self.assertEqual(backend.calls, [])
        self.assertIn("coverage=BOUNDED", text)
        self.assertIn("line_history=RECORDED", text)

    def test_sync_empty_history_is_successful_read_with_zero_real_messages(self):
        code, text = self.run_cli(["sync", "line"], LineConnector(store(), cli=FakeCLI(rows=[])))
        self.assertEqual(code, 0)
        self.assertIn("real_messages=0", text)
        self.assertIn("stored_text=0", text)
        with self.db() as db:
            self.assertEqual(db.total_count(), 0)
            self.assertIsNotNone(db.get_sync_receipt(self.record))

    def test_receipt_commit_failure_never_starts_watch(self):
        with self.db() as db:
            db.conn.execute("CREATE TRIGGER refuse_receipt BEFORE INSERT ON sync_receipts "
                            "BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        backend = FakeCLI(events=[event()])
        code, text = self.run_cli(["daemon", "line", "--timeout", "1"], LineConnector(store(), cli=backend))
        self.assertEqual(code, 1)
        self.assertFalse(backend.closed)
        self.assertNotIn("line_watch=STARTING", text)
        with self.db() as db:
            self.assertEqual(db.total_count(), 0)
