"""Forced logout crosses the actual subprocess/status/core boundary; no account IO."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock

from beeperlocal.connectors.line import LineCLI
from beeperlocal.errors import AppError
from beeperlocal.desktop_sync import HistoryPage
from . import test_desktop as fixtures


class Process:
    def __init__(self):
        self.stdout = asyncio.StreamReader()
        self.returncode = None
    def terminate(self): self.returncode = 0
    def kill(self): self.returncode = 0
    async def wait(self): return self.returncode or 0
    def emit(self, **event): self.stdout.feed_data(json.dumps(event).encode() + b'\n')


class LineStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_spawn_is_not_ready_and_logout_is_terminal_without_message(self):
        cli = object.__new__(LineCLI)
        process, started, statuses = Process(), asyncio.Event(), []
        cli._start = AsyncMock(return_value=process)
        async def consume():
            async for _ in cli.events(timeout=0, from_now=False, started=started, status_changed=statuses.append):
                self.fail('control events must not become messages')
        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        self.assertFalse(started.is_set())
        process.emit(event='status', state='ready')
        await asyncio.wait_for(started.wait(), 1)
        process.emit(event='status', state='reconnecting')
        await asyncio.sleep(0)
        self.assertFalse(started.is_set())
        process.emit(event='status', state='logged_out', code='LINE_SESSION_REVOKED')
        with self.assertRaises(AppError) as caught:
            await task
        self.assertEqual(caught.exception.code, 'LINE_SESSION_REVOKED')
        self.assertEqual(statuses, ['ready', 'reconnecting'])
        self.assertEqual(cli._start.await_count, 1)
        self.assertIn('--status-events', cli._start.call_args.args)
        self.assertIsNotNone(process.returncode)

    async def test_invalidated_identity_does_not_retry_or_log_in(self):
        cli = object.__new__(LineCLI)
        cli.request = AsyncMock(return_value={'line_validity': 'invalidated'})
        with self.assertRaises(AppError) as caught:
            await cli.whoami()
        self.assertEqual(caught.exception.code, 'LINE_SESSION_REVOKED')
        cli.request.assert_awaited_once_with('auth', 'status', '--json', allow_failure=True)


class LineSessionCoreTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixtures.DesktopTests.setUp
    db = fixtures.DesktopTests.db
    new_core = fixtures.DesktopTests.new_core
    asyncTearDown = fixtures.DesktopTests.asyncTearDown
    connect = fixtures.DesktopTests.connect
    send = fixtures.DesktopTests.send

    async def wait_state(self, state):
        for _ in range(100):
            if self.core.connection == state: return
            await asyncio.sleep(.001)
        self.fail('state did not change')

    async def test_watch_logout_cancels_polling_and_keeps_saved_history(self):
        async def revoked(**options):
            options['started'].set()
            raise AppError('LINE_SESSION_REVOKED')
            yield
        self.backend.events = revoked
        await self.connect()
        await self.wait_state('error')
        await asyncio.sleep(0)
        self.assertEqual(self.core.error_code, 'LINE_SESSION_REVOKED')
        self.assertFalse(self.core.watch_ready.is_set())
        self.assertTrue(self.core.sync_task.done())
        self.assertTrue(self.core.recovery_task.done())
        self.assertEqual(self.core.sync_state['mode'], 'error')
        self.assertEqual(len(self.core.messages(self.record.id)['messages']), 1)
        with self.assertRaises(AppError): await self.send()
        self.assertEqual(self.backend.send_calls, 0)
        await self.core.dispatch({'op': 'select', 'conversationId': self.record.id})
        self.assertEqual(self.core.connection, 'error')
        self.assertEqual(self.core.error_code, 'LINE_SESSION_REVOKED')

    async def test_send_identity_failure_disables_connection_before_mutation(self):
        await self.connect()
        self.backend.whoami = AsyncMock(side_effect=AppError('LINE_SESSION_REVOKED'))
        with self.assertRaises(AppError): await self.send()
        self.assertEqual(self.core.connection, 'error')
        self.assertEqual(self.backend.send_calls, 0)
        self.assertEqual(self.core.db.pending_outgoing(self.core.account_id), [])

    async def test_background_history_auth_failure_stops_receiver(self):
        await self.connect()
        self.core.connector.fetch_page = AsyncMock(side_effect=AppError('LINE_SESSION_REVOKED'))
        self.core.sync_interval = .001
        self.core.sync_task.cancel()
        await asyncio.gather(self.core.sync_task, return_exceptions=True)
        self.core.sync_task = asyncio.create_task(self.core._sync_account())
        await self.wait_state('error')
        await asyncio.sleep(0)
        self.assertEqual(self.core.error_code, 'LINE_SESSION_REVOKED')
        self.assertTrue(self.core.watch_task.done())

    async def test_late_history_success_cannot_revive_revoked_session(self):
        await self.connect()
        entered, release = asyncio.Event(), asyncio.Event()
        async def late(*args, **kwargs):
            entered.set()
            try: await release.wait()
            except asyncio.CancelledError: pass  # A provider ignored cancellation.
            return HistoryPage(self.record, [])
        self.core.connector.fetch_page = late
        self.core.sync_interval = .001
        self.core.sync_task.cancel()
        await asyncio.gather(self.core.sync_task, return_exceptions=True)
        self.core.sync_task = asyncio.create_task(self.core._sync_account())
        await asyncio.wait_for(entered.wait(), 1)
        self.core.invalidate_line_session('LINE_SESSION_REVOKED')
        release.set()
        await asyncio.wait_for(self.core.sync_task, 1)
        self.assertEqual((self.core.connection, self.core.receiving, self.core.error_code),
                         ('error', 'error', 'LINE_SESSION_REVOKED'))
