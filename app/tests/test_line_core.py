"""Focused regression for ordinary LINE use and the small E2E command."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock

from beeperlocal.connectors.line import LineConnector
from beeperlocal.connectors.registry import create_connector, require_capability
from beeperlocal.errors import AppError
from beeperlocal.line_e2e import run_e2e
from beeperlocal.models import StoredConversation, SendResult
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore, matrix_store, slack_store
from .test_line import SELF, PEER, CONV, KEY, BODY, FakeCLI, raw, store
from beeperlocal.connectors.line import normalize_line


class LineCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / "state" / "messages.sqlite3"
    def db(self):
        return EncryptedMessageStore(KEY, self.path)

    async def test_catalog_reopen_rename_and_encrypted_canonical_mid(self):
        record = StoredConversation("line", SELF, CONV)
        message = normalize_line(raw(), SELF, CONV)
        with self.db() as db:
            db.upsert([message], conversations=[record])
            db.upsert_conversations([replace(record, conversation=replace(CONV, title="New name"))])
        with self.db() as db:
            rows = db.list_conversations(provider="line", account_id=SELF)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].id, record.id)
            self.assertEqual(rows[0].conversation.id, PEER)
            self.assertEqual(rows[0].conversation.title, "New name")
            self.assertEqual(db.list_messages("line", SELF, PEER)[0].id, message.id)
        for secret in (SELF, PEER, BODY, "New name"):
            self.assertNotIn(secret.encode(), self.path.read_bytes())

    async def test_catalog_is_atomic_with_messages(self):
        with self.db() as db:
            db.conn.execute("CREATE TRIGGER fail_message BEFORE INSERT ON messages BEGIN SELECT RAISE(ABORT, 'fixture'); END")
            with self.assertRaises(AppError):
                db.upsert([normalize_line(raw(), SELF, CONV)], conversations=[StoredConversation("line", SELF, CONV)])
            self.assertEqual(db.list_conversations(), [])

    async def test_existing_session_auto_restore_and_named_selection(self):
        memory = MemoryStore()
        backend = FakeCLI()
        backend.request = AsyncMock(side_effect=[[{"id": PEER, "type": 0, "name": "Friend"}]])
        connector = LineConnector(memory, cli=backend)
        choices = await connector.list_conversations()
        await connector.select_mid(choices[0].id, title=choices[0].title)
        self.assertEqual(memory.records["line"]["account_id"], SELF)
        self.assertEqual(connector.selected_conversation().id, PEER)
        self.assertEqual(connector.selected_conversation().title, "Friend")
        self.assertEqual(set(memory.records["line"]), {"account_id", "selections"})

    async def test_common_registry_keeps_history_providers_and_capabilities(self):
        self.assertEqual(type(create_connector("matrix", matrix_store())).__name__, "MatrixConnector")
        self.assertEqual(type(create_connector("slack", slack_store())).__name__, "SlackConnector")
        require_capability("line", "watch")
        require_capability("slack", "send_text")
        with self.assertRaises(AppError):
            require_capability("slack", "watch")

    async def exercise_e2e(self, *, reply=True, send_error=False):
        connector = LineConnector(store(), cli=FakeCLI())
        queue = asyncio.Queue()
        async def watch(*, timeout, started):
            started.set()
            while True:
                yield await queue.get()
        async def send(text):
            if send_error:
                raise AppError("LINE_SEND_UNKNOWN")
            outgoing = normalize_line(raw(**{"from": SELF, "to": PEER, "text": text, "id": "sent"}), SELF, CONV)
            await queue.put(outgoing)  # Own echo must not close the loop.
            await queue.put(normalize_line(raw(text="old unrelated reply"), SELF, CONV))
            if reply:
                await queue.put(normalize_line(raw(text=text), SELF, CONV))
            return SendResult(outgoing, True)
        connector.watch = watch
        connector.send_text = AsyncMock(side_effect=send)
        output = []
        try:
            await run_e2e(connector, self.db, timeout=0.1, notice=output.append)
        finally:
            self.assertEqual(connector.send_text.await_count, 1)
            self.assertNotIn(PEER, "".join(output))
        return output

    async def test_e2e_one_send_realtime_and_reopen_search(self):
        output = await self.exercise_e2e()
        self.assertTrue(any("line_e2e=CLOSED" in s for s in output))
        with self.db() as db:
            self.assertEqual(db.total_count(), 2)

    async def test_e2e_unrelated_reply_times_out_without_resend(self):
        with self.assertRaises(AppError) as error:
            await self.exercise_e2e(reply=False)
        self.assertEqual(error.exception.code, "LINE_E2E_TIMEOUT")

    async def test_e2e_ambiguous_send_is_not_retried(self):
        with self.assertRaises(AppError) as error:
            await self.exercise_e2e(send_error=True)
        self.assertEqual(error.exception.code, "LINE_SEND_UNKNOWN")
