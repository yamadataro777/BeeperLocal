"""Account polling, unread and resumable history using only artificial records."""
import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beeperlocal.desktop import DesktopCore
from beeperlocal.desktop_sync import HistoryPage
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation, UnifiedMessage
from beeperlocal.storage import EncryptedMessageStore
from .test_line import SELF, PEER, OTHER, CONV, KEY, store


class SyncTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'state' / 'messages.db'
        self.events = []
        self.core = DesktopCore(credentials=store(), db_factory=lambda: EncryptedMessageStore(KEY, self.path), emit=self.events.append)
        self.core._initialize()
        self.records = [StoredConversation('line', SELF, CONV), StoredConversation('line', SELF, replace(CONV, id=OTHER))]
        self.core.account_id = SELF
        self.core.connection = 'connected'
        self.core.selected_id = self.records[0].id
        self.core.db.upsert([], conversations=self.records, private_updates={self.core.catalog_key(): [r.id for r in self.records]})
        self.core.sync_interval = .002
        self.calls = []
        owner = self
        class Pages:
            async def fetch_page(self, conversation, *, cursor=None):
                owner.calls.append((conversation.id, cursor))
                return owner.page(conversation, cursor)
            async def list_conversations(self, limit): return [r.conversation for r in owner.records]
        self.core.connector = Pages()
        self.page = lambda c, cursor: HistoryPage(next(r for r in self.records if r.conversation.id == c.id), [], complete=True)

    async def asyncTearDown(self):
        await self.core.close()

    def msg(self, n, record=None):
        record = record or self.records[0]
        return UnifiedMessage('line', SELF, record.conversation.id, str(n), PEER,
            datetime(2026, 10, 1, tzinfo=timezone.utc) + timedelta(seconds=n), 'fixture text', 'Fixture', direction='incoming')

    async def until(self, predicate):
        for _ in range(1000):
            if predicate(): return
            await asyncio.sleep(.002)
        self.fail('fixture condition was not reached')

    async def test_every_conversation_polled_without_changing_selection_and_pause_stops(self):
        self.page = lambda c, cur: HistoryPage(next(r for r in self.records if r.conversation.id == c.id), [self.msg(1, next(r for r in self.records if r.conversation.id == c.id))], complete=True)
        self.core.start_all_sync()
        await self.until(lambda: len(self.calls) >= 2)
        self.assertEqual({c[0] for c in self.calls}, {PEER, OTHER})
        self.assertEqual(self.core.selected_id, self.records[0].id)
        self.assertEqual(self.core.snapshot()['unreadCount'], 0)
        await self.core.pause_storage(True)
        count = len(self.calls)
        await asyncio.sleep(.02)
        self.assertEqual(len(self.calls), count)

    async def test_new_messages_edits_read_boundary_and_delete_do_not_resurrect(self):
        a, b, c = self.msg(1), self.msg(2), self.msg(3)
        r = self.records[0]
        self.core.ingest([a], records=[r], historical=True)
        self.core.ingest([b,c], records=[r])
        self.core.ingest([replace(b, text='edited fixture')], records=[r])
        self.assertEqual(self.core.snapshot()['unreadCount'], 2)
        self.assertEqual(len([e for e in self.events if e['event'] == 'unread_changed']), 1)
        self.core.mark_read(r.id, b.id)
        self.assertEqual(self.core.snapshot()['unreadCount'], 1)
        self.core.ingest([], records=[r], deletions=[(r, c.provider_message_id)])
        self.core.ingest([c], records=[r])
        self.assertIsNone(self.core.db.get_message(c.id))
        self.assertEqual(self.core.snapshot()['unreadCount'], 0)
        with self.assertRaises(AppError): self.core.mark_read(self.records[1].id, b.id)

    async def test_cursor_commits_with_rows_and_backfill_survives_restart(self):
        r = self.records[0]
        self.core.db.private_put(self.core.catalog_key(), [r.id])
        def page(c, cursor):
            if cursor: return HistoryPage(r, [self.msg(1)], complete=True)
            return HistoryPage(r, [self.msg(10)], cursor={'before':'fixture-cursor'})
        self.page = page
        self.core.backfill(r.id, True)
        self.core.start_all_sync()
        await self.until(lambda: self.core.db.get_message(self.msg(1).id) is not None)
        await self.core.stop_watch()
        self.assertTrue(self.core.db.private_get('sync.v1.' + r.id)['complete'])
        self.assertEqual(self.core.snapshot()['unreadCount'], 0)
        with EncryptedMessageStore(KEY, self.path) as db:
            self.assertTrue(db.private_get('sync.v1.' + r.id)['backfill'])
            self.assertTrue(db.private_get('sync.v1.' + r.id)['complete'])
        self.assertNotIn(b'fixture-cursor', self.path.read_bytes())

    async def test_outage_catches_all_pages_until_known_overlap_without_backfill(self):
        r = self.records[0]
        self.core.db.private_put(self.core.catalog_key(), [r.id])
        self.core.ingest([self.msg(1)], records=[r], historical=True)
        def page(c, cursor):
            if cursor == {'before':'2'}: return HistoryPage(r, [self.msg(2),self.msg(1)], complete=True)
            return HistoryPage(r, [self.msg(4),self.msg(3)], cursor={'before':'2'})
        self.page = page
        self.core.start_all_sync()
        await self.until(lambda: self.core.db.total_count() == 4)
        self.assertEqual(self.core.snapshot()['unreadCount'], 3)

    async def test_failed_transaction_does_not_advance_cursor_or_notify(self):
        r = self.records[0]
        with patch.object(self.core.db, '_private_put', side_effect=AppError('LOCAL_DB_UNAVAILABLE')):
            with self.assertRaises(AppError):
                self.core.ingest([self.msg(1)], records=[r], private_updates={'sync.v1.' + r.id: {'cursor':'not-committed'}})
        self.assertEqual(self.core.db.total_count(), 0)
        self.assertIsNone(self.core.db.private_get('sync.v1.' + r.id))
        self.assertFalse(any(e['event'] == 'unread_changed' for e in self.events))

    async def test_scoped_older_pages_survive_reopen(self):
        r = self.records[0]
        rows = [self.msg(i) for i in range(205)]
        self.core.ingest(rows, records=[r], historical=True)
        first = self.core.messages(r.id)
        second = self.core.messages(r.id, before=first['olderCursor'])
        third = self.core.messages(r.id, before=second['olderCursor'])
        self.assertEqual([len(x['messages']) for x in (first,second,third)], [100,100,5])
        self.assertIsNone(third['olderCursor'])
        with EncryptedMessageStore(KEY, self.path) as reopened:
            self.assertEqual(len(reopened.list_messages('line', SELF, r.conversation.id, limit=100)),100)

    async def test_wrong_scope_page_is_terminal_before_commit(self):
        self.page = lambda c, cursor: HistoryPage(self.records[0], [self.msg(9, self.records[1])], complete=True)
        self.core.start_all_sync()
        await self.until(lambda: self.core.receiving == 'error')
        self.assertEqual(self.core.db.total_count(), 0)
        self.assertEqual(self.core.error_code, 'BAD_RESPONSE')
