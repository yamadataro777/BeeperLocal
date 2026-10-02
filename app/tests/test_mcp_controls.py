"""Scoped MCP, durable grants, pause and deletion; synthetic local data only."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest
from uuid import uuid4
from unittest.mock import AsyncMock

from beeperlocal.connectors.line import LineConnector, normalize_line
from beeperlocal.desktop import DesktopCore
from beeperlocal.errors import AppError
from beeperlocal.mcp_access import GRANTS_KEY, SETTINGS_KEY
from beeperlocal.models import StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from .test_desktop import DesktopCLI
from .test_line import SELF, PEER, OTHER, CONV, KEY, BODY, raw, store


class ScopedCLI(DesktopCLI):
    async def request(self, *args, **kwargs):
        if args[0] == 'send':
            self.response = {'id': str(2000 + self.send_calls), 'chat_id': args[1], 'encrypted': True}
        return await super().request(*args, **kwargs)


class ControlFixture(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name).resolve() / 'state' / 'messages.sqlite3'
        self.credentials, self.backend, self.events = store(), ScopedCLI(), []
        self.record = StoredConversation('line', SELF, CONV)
        self.other = StoredConversation('line', SELF, replace(CONV, id=OTHER, locator={'mid': OTHER}))
        self.core = self.new_core()

    def db(self):
        return EncryptedMessageStore(KEY, self.path)

    def new_core(self):
        core = DesktopCore(credentials=self.credentials, db_factory=self.db,
            connector_factory=lambda credentials: LineConnector(credentials, cli=self.backend), emit=self.events.append)
        core.retry_delays = (0.01, 0.01, 0.01)
        return core

    async def asyncSetUp(self):
        await self.core.dispatch({'op': 'connect'})
        await self.core.stop_watch()

    async def asyncTearDown(self):
        await self.core.close()

    def grant(self, ids=None, read=True, send=False):
        return self.core.register_client({'name': 'CLIENT_PRIVATE_CANARY', 'conversationIds': ids or [self.record.id], 'read': read, 'send': send})

    def enable_without_network(self):
        self.core._save_settings(mcpEnabled=True)

    async def denied(self, call, code='MCP_ACCESS_DENIED'):
        with self.assertRaises(AppError) as error:
            await call
        self.assertEqual(error.exception.code, code)

    async def wait_until(self, predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(0.01)
        self.fail('fixture condition timed out')


class AccessTests(ControlFixture):
    async def test_default_disabled_and_scoped_reads_no_other_account_or_conversation(self):
        token = self.grant()['token']
        await self.denied(self.core.mcp_call(token, 'list_conversations', {}), 'MCP_DISABLED')
        self.enable_without_network()
        hidden = replace(normalize_line(raw(id='hidden'), SELF, CONV), conversation_id=OTHER, text='HIDDEN_PRIVATE_CANARY')
        old_account = replace(hidden, account_id=OTHER)
        self.core.db.upsert([hidden, old_account])
        result = await self.core.mcp_call(token, 'list_conversations', {})
        self.assertEqual([r['id'] for r in result['conversations']], [self.record.id])
        await self.denied(self.core.mcp_call(token, 'get_messages', {'conversation_id': self.other.id}))
        result = await self.core.mcp_call(token, 'search_messages', {'query': 'HIDDEN_PRIVATE_CANARY'})
        self.assertEqual(result['results'], [])
        self.assertEqual(result['scannedPermittedMessages'], 1)
        self.core.account_id = OTHER
        await self.denied(self.core.mcp_call(token, 'list_conversations', {}))

    async def test_invalid_token_read_only_and_send_only_permissions(self):
        self.enable_without_network()
        readonly = self.grant()['token']
        sender = self.grant(read=False, send=True)['token']
        args = {'conversation_id': self.record.id, 'text': BODY, 'request_id': str(uuid4())}
        await self.denied(self.core.mcp_call(readonly, 'send_message', args))
        await self.denied(self.core.mcp_call(sender, 'get_messages', {'conversation_id': self.record.id}))
        for token in ('', readonly + 'x', 'blc_' + 'z' * 43):
            await self.denied(self.core.mcp_call(token, 'list_conversations', {}))
        self.assertEqual(self.backend.send_calls, 0)

    async def test_grants_encrypted_persisted_and_revocation_survives_restart(self):
        grant = self.grant()
        self.enable_without_network()
        for secret in (grant['token'], 'CLIENT_PRIVATE_CANARY', SELF, PEER, BODY):
            self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.assertNotIn(grant['token'], json.dumps(self.core.management()))
        await self.core.close()
        self.core = self.new_core(); self.core._initialize()
        self.core.require_mcp(grant['token'], 'read')
        self.core.access.revoke(grant['client']['id'], SELF)
        await self.core.close()
        self.core = self.new_core(); self.core._initialize()
        await self.denied(self.core.mcp_call(grant['token'], 'list_conversations', {}))

    async def test_tampered_grants_and_settings_fail_closed(self):
        grant = self.grant(); self.enable_without_network()
        self.core.db.private_put(GRANTS_KEY, [{'bad': 'value'}])
        await self.denied(self.core.mcp_call(grant['token'], 'list_conversations', {}), 'LOCAL_DB_CORRUPT')
        self.core.db.private_put(SETTINGS_KEY, {'mcpEnabled': True})
        await self.core.close(); self.core = self.new_core()
        with self.assertRaises(AppError) as error: self.core._initialize()
        self.assertEqual(error.exception.code, 'LOCAL_DB_CORRUPT')

    async def test_other_target_send_does_not_change_gui_and_concurrent_duplicate_sends_once(self):
        token = self.grant([self.other.id], send=True)['token']; self.enable_without_network()
        args = {'conversation_id': self.other.id, 'text': BODY, 'request_id': str(uuid4())}
        results = await asyncio.gather(*(self.core.mcp_call(token, 'send_message', args) for _ in range(2)))
        self.assertEqual(self.backend.send_calls, 1)
        self.assertTrue(results[1]['duplicateSuppressed'])
        self.assertEqual(self.core.selected_id, self.record.id)
        self.assertEqual(self.core.connector.selected_conversation().id, PEER)
        self.assertEqual(len(self.core.messages(self.other.id)['messages']), 1)
        await self.denied(self.core.mcp_call(token, 'send_message', {**args, 'text': 'different'}), 'INVALID_INPUT')

    async def test_unknown_request_not_replayed_after_restart(self):
        token = self.grant(send=True)['token']; self.enable_without_network()
        args = {'conversation_id': self.record.id, 'text': BODY, 'request_id': str(uuid4())}
        self.backend.send_error = AppError('LINE_SEND_UNKNOWN')
        await self.denied(self.core.mcp_call(token, 'send_message', args), 'LINE_SEND_UNKNOWN')
        await self.core.close(); self.core = self.new_core(); self.core._initialize()
        await self.core.connect(); await self.core.stop_watch()
        await self.denied(self.core.mcp_call(token, 'send_message', args), 'LINE_SEND_UNKNOWN')
        self.assertEqual(self.backend.send_calls, 1)

    async def test_revoke_disable_pause_or_stop_during_auth_prevents_issuance(self):
        for mutation in ('revoke', 'disable', 'pause', 'stop'):
            with self.subTest(mutation=mutation):
                self.core._save_settings(storagePaused=False); self.core.connection = 'connected'
                grant = self.grant(send=True); self.enable_without_network()
                entered, release = asyncio.Event(), asyncio.Event()
                calls = 0
                async def whoami():
                    nonlocal calls
                    calls += 1
                    if calls == 2:  # second authorization, after durable intent
                        entered.set(); await release.wait()
                    return SELF
                self.backend.whoami = whoami
                task = asyncio.create_task(self.core.mcp_call(grant['token'], 'send_message',
                    {'conversation_id': self.record.id, 'text': BODY, 'request_id': str(uuid4())}))
                await asyncio.wait_for(entered.wait(), 1)
                if mutation == 'revoke': self.core.access.revoke(grant['client']['id'], SELF)
                if mutation == 'disable': self.core._save_settings(mcpEnabled=False)
                if mutation == 'pause': await self.core.pause_storage(True)
                if mutation == 'stop': await self.core.dispatch({'op': 'stop'})
                release.set()
                with self.assertRaises(AppError): await task
                self.assertEqual(self.backend.send_calls, 0)


class StorageControlTests(ControlFixture):
    async def test_pause_survives_restart_and_allows_saved_reads(self):
        token = self.grant()['token']; self.enable_without_network()
        await self.core.pause_storage(True)
        await self.denied(self.core.connect(), 'STORAGE_PAUSED')
        await self.denied(self.core.sync_selected(), 'STORAGE_PAUSED')
        self.assertEqual(len((await self.core.mcp_call(token, 'get_messages', {'conversation_id': self.record.id}))['messages']), 1)
        await self.core.close(); self.core = self.new_core(); self.core._initialize()
        self.assertTrue(self.core.settings['storagePaused'])
        self.assertIsNone(self.core.watch_task)

    async def test_delete_only_current_line_account_revokes_grants_and_prevents_replay(self):
        from beeperlocal.outbox import OutgoingRequest
        from datetime import datetime, timezone
        grant = self.grant(send=True); self.enable_without_network()
        request_id = str(uuid4())
        self.core.db.upsert([], outgoing_requests=[OutgoingRequest(request_id, 'line', SELF, PEER, BODY, 'unknown', datetime.now(timezone.utc))])
        base = normalize_line(raw(id='keep'), SELF, CONV)
        keep = [replace(base, account_id=OTHER), replace(base, provider='slack')]
        self.core.db.upsert(keep, conversations=[replace(self.record, account_id=OTHER), replace(self.record, provider='slack')])
        credentials_before = self.credentials.load('line')
        preview = await self.core.deletion_preview()
        self.assertEqual(preview['counts']['messages'], 1)
        result = await self.core.delete_local_data(preview['confirmation'])
        self.assertEqual(result['deleted']['outgoing_requests'], 1)
        self.assertEqual(self.core.db.total_count(), 2)
        self.assertEqual(self.core.access.all(), [])
        self.assertEqual(self.credentials.load('line'), credentials_before)
        self.assertTrue(self.core.db.request_retired(request_id))
        self.assertEqual(self.core.snapshot()['conversations'], [])
        self.assertFalse(self.core.settings['mcpEnabled'])
        self.assertTrue(self.core.settings['storagePaused'])
        await self.core.pause_storage(False); await self.core.connect(); await self.core.stop_watch()
        await self.denied(self.core.send(self.record.id, BODY, request_id), 'LINE_SEND_UNKNOWN')
        self.assertEqual(self.backend.send_calls, 0)

    async def test_delete_expiry_stale_counts_and_missing_confirmation_do_not_delete(self):
        await self.denied(self.core.delete_local_data('no'), 'DELETE_CONFIRMATION_EXPIRED')
        preview = await self.core.deletion_preview()
        nonce, account, _, counts = self.core.deletion_challenge
        self.core.deletion_challenge = (nonce, account, time.monotonic() - 1, counts)
        await self.denied(self.core.delete_local_data(nonce), 'DELETE_CONFIRMATION_EXPIRED')
        preview = await self.core.deletion_preview()
        self.core.db.upsert([normalize_line(raw(id='new'), SELF, CONV)])
        await self.denied(self.core.delete_local_data(preview['confirmation']), 'DELETE_CONFIRMATION_EXPIRED')
        self.assertEqual(self.core.db.total_count(), 2)

    async def test_delete_transaction_failure_preserves_content_and_grants(self):
        self.grant()
        preview = await self.core.deletion_preview()
        self.core.db.conn.execute("CREATE TRIGGER fail_delete BEFORE DELETE ON conversations BEGIN SELECT RAISE(ABORT, 'fixture'); END")
        await self.denied(self.core.delete_local_data(preview['confirmation']), 'LOCAL_DB_UNAVAILABLE')
        self.assertEqual(self.core.db.total_count(), 1)
        self.assertEqual(len(self.core.access.all()), 1)

    async def test_deletion_is_not_limited_by_search_scan_window(self):
        rows = [normalize_line(raw(id='bulk-' + str(i)), SELF, CONV) for i in range(10001)]
        self.core.db.upsert(rows)
        preview = await self.core.deletion_preview()
        self.assertEqual(preview['counts']['messages'], 10002)
        await self.core.delete_local_data(preview['confirmation'])
        self.assertEqual(self.core.db.total_count(), 0)


class ReconnectTests(ControlFixture):
    async def test_disconnect_recovers_gap_deduplicates_and_restarts(self):
        starts = 0
        async def events(**kwargs):
            nonlocal starts
            starts += 1; kwargs['started'].set()
            if starts == 1:
                self.backend.rows.append(raw(id='missed'))
                raise AppError('LINE_WATCH_FAILED')
            yield {'event': 'message', 'chat_id': PEER, 'type': 26, 'message': raw(id='missed')}
            await asyncio.Event().wait()
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: starts >= 2 and self.core.db.total_count() == 2)
        self.assertTrue(any(e.get('receiving') == 'reconnecting' for e in self.events))
        self.assertEqual(self.core.receiving, 'waiting')
        await self.core.pause_storage(True)
        self.assertIsNone(self.core.watch_task)
        self.assertIsNone(self.core.recovery_task)

    async def test_eof_exhaustion_switches_to_slow_cancellable_retries(self):
        starts = 0
        self.core.line_retry_interval = 10
        async def events(**kwargs):
            nonlocal starts
            starts += 1; kwargs['started'].set()
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: self.core.error_code == 'LINE_RECONNECT_WAITING')
        self.assertEqual(starts, 4)
        await asyncio.sleep(0)
        self.assertFalse(self.core.watch_task.done())
        self.assertFalse(self.core.recovery_task.done())
        self.assertFalse(self.core.watch_ready.is_set())
        self.assertEqual(self.core.receiving, 'reconnecting')

    async def test_fatal_decryption_error_does_not_retry(self):
        starts = 0
        async def events(**kwargs):
            nonlocal starts
            starts += 1
            raise AppError('LINE_DECRYPT_FAILED')
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: self.core.receiving == 'error')
        self.assertEqual(starts, 1)
        self.assertEqual(self.core.error_code, 'LINE_DECRYPT_FAILED')

    async def test_pausing_during_fetch_discards_network_result(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.backend.request
        async def request(*args, **kwargs):
            if args[0] == 'messages': entered.set(); await release.wait()
            return await original(*args, **kwargs)
        self.backend.request = request
        self.backend.rows.append(raw(id='after-pause'))
        task = asyncio.create_task(self.core.sync_selected())
        await entered.wait(); await self.core.pause_storage(True); release.set()
        await self.denied(task, 'STORAGE_PAUSED')
        self.assertEqual(self.core.db.total_count(), 1)
