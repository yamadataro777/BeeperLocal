"""Outages beyond the fast retry budget must not strand a LINE receiver."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from beeperlocal.errors import AppError
from beeperlocal.receiver_retry import wait_for_retry
from .test_mcp_controls import ControlFixture
from .test_line import PEER, raw


class PersistentLineRecoveryTests(ControlFixture):
    async def test_long_watch_outage_recovers_gap_without_a_manual_connect(self):
        starts = 0
        self.core.line_retry_interval = 0.02
        async def events(**kwargs):
            nonlocal starts
            starts += 1
            if starts <= len(self.core.retry_delays) + 2:
                raise AppError('LINE_WATCH_FAILED')
            kwargs['started'].set()
            yield {'event': 'message', 'chat_id': PEER, 'type': 26,
                   'message': raw(id='during-long-outage')}
            await asyncio.Event().wait()
        self.backend.rows.append(raw(id='during-long-outage'))
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: starts >= 6 and self.core.receiving == 'waiting')
        self.assertEqual(self.core.db.total_count(), 2)
        self.assertIsNone(self.core.error_code)
        self.assertEqual(self.core.retry_attempt, 0)
        self.assertFalse(self.core.watch_task.done())
        self.assertFalse(self.core.recovery_task.done())
        self.assertEqual(self.backend.send_calls, 0)

    async def test_long_history_outage_does_not_cancel_the_live_receiver(self):
        self.core.line_retry_interval = 0.02
        self.core.recovery_interval = 0.01
        calls = 0
        original = self.core.connector.fetch
        async def fetch(limit):
            nonlocal calls
            calls += 1
            if calls <= len(self.core.retry_delays) + 2:
                raise AppError('NETWORK_ERROR')
            return await original(limit)
        self.core.connector.fetch = fetch
        self.backend.rows.append(raw(id='history-after-outage'))
        self.core.start_watch()
        await self.wait_until(lambda: calls >= 6 and self.core.db.total_count() == 2)
        self.assertFalse(self.core.watch_task.done())
        self.assertFalse(self.core.recovery_task.done())
        self.assertIsNone(self.core.error_code)
        self.assertEqual(self.backend.send_calls, 0)

    async def test_stop_cancels_slow_retries_and_never_restarts_them(self):
        starts = 0
        self.core.line_retry_interval = 10
        async def events(**kwargs):
            nonlocal starts
            starts += 1
            raise AppError('LINE_WATCH_FAILED')
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: self.core.error_code == 'LINE_RECONNECT_WAITING')
        self.assertEqual(starts, 4)
        await self.core.dispatch({'op': 'stop'})
        await asyncio.sleep(0.04)
        self.assertEqual(starts, 4)
        self.assertIsNone(self.core.watch_task)
        self.assertIsNone(self.core.recovery_task)

    async def test_storage_pause_cancels_slow_retries(self):
        self.core.line_retry_interval = 10
        self.core.connector.fetch = AsyncMock(side_effect=AppError('NETWORK_ERROR'))
        self.core.start_watch()
        await self.wait_until(lambda: self.core.error_code == 'LINE_RECONNECT_WAITING')
        calls = self.core.connector.fetch.await_count
        await self.core.pause_storage(True)
        await asyncio.sleep(0.04)
        self.assertEqual(self.core.connector.fetch.await_count, calls)
        self.assertIsNone(self.core.watch_task)
        self.assertIsNone(self.core.recovery_task)

    async def test_history_storage_error_remains_terminal(self):
        self.core.connector.fetch = AsyncMock(side_effect=AppError('LOCAL_DB_UNAVAILABLE'))
        self.core.start_watch()
        await self.wait_until(lambda: self.core.receiving == 'error')
        await asyncio.sleep(0)
        self.assertEqual(self.core.error_code, 'LOCAL_DB_UNAVAILABLE')
        self.assertEqual(self.core.connector.fetch.await_count, 1)
        self.assertTrue(self.core.watch_task.done())

    async def test_authentication_failure_after_an_outage_stops_retries(self):
        self.core.line_retry_interval = 0.02
        starts = 0
        async def events(**kwargs):
            nonlocal starts
            starts += 1
            raise AppError('LINE_WATCH_FAILED')
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: self.core.error_code == 'LINE_RECONNECT_WAITING')
        self.backend.whoami = AsyncMock(side_effect=AppError('LINE_LOGIN_REQUIRED'))
        await self.wait_until(lambda: self.core.receiving == 'error')
        self.assertEqual(self.core.error_code, 'LINE_LOGIN_REQUIRED')
        self.assertEqual(starts, 4)
        self.assertEqual(self.backend.send_calls, 0)

    async def test_immediate_eof_cannot_publish_stale_waiting_status(self):
        self.core.retry_delays = (10,)
        async def events(**kwargs):
            kwargs['started'].set()
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: self.core.retry_attempt == 1)
        await asyncio.sleep(0)
        self.assertEqual(self.core.receiving, 'reconnecting')
        self.assertFalse(self.core.watch_ready.is_set())
        self.assertEqual(self.events[-1]['receiving'], 'reconnecting')

    async def test_unknown_send_is_not_replayed_when_the_receiver_recovers(self):
        request_id = str(uuid4())
        self.backend.send_error = AppError('LINE_SEND_UNKNOWN')
        with self.assertRaises(AppError):
            await self.core.dispatch({'op': 'send', 'conversationId': self.record.id,
                                      'text': 'synthetic uncertain send', 'requestId': request_id})
        self.core.line_retry_interval = 0.02
        starts = 0
        async def events(**kwargs):
            nonlocal starts
            starts += 1
            if starts < 5:
                raise AppError('LINE_WATCH_FAILED')
            kwargs['started'].set()
            await asyncio.Event().wait()
            if False: yield
        self.backend.events = events
        self.core.start_watch()
        await self.wait_until(lambda: starts == 5 and self.core.receiving == 'waiting')
        self.assertEqual(self.backend.send_calls, 1)
        self.assertEqual(self.core.db.get_outgoing(request_id).status, 'unknown')


class WakeAwareRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_sleep_time_expires_retry_without_waiting_the_full_delay_again(self):
        clock = {'wall': 1000, 'mono': 1000}
        delays = []
        async def sleep(delay):
            delays.append(delay)
            clock['mono'] += delay
            clock['wall'] += 120
        with patch('beeperlocal.receiver_retry.time', SimpleNamespace(
                time=lambda: clock['wall'], monotonic=lambda: clock['mono'])), \
             patch('beeperlocal.receiver_retry.asyncio', SimpleNamespace(sleep=sleep)):
            await wait_for_retry(60)
        self.assertEqual(delays, [5])

    async def test_backward_clock_change_does_not_extend_retry_delay(self):
        clock = {'wall': 1000, 'mono': 1000}
        delays = []
        async def sleep(delay):
            delays.append(delay)
            clock['mono'] += delay
            clock['wall'] -= 100
        with patch('beeperlocal.receiver_retry.time', SimpleNamespace(
                time=lambda: clock['wall'], monotonic=lambda: clock['mono'])), \
             patch('beeperlocal.receiver_retry.asyncio', SimpleNamespace(sleep=sleep)):
            await wait_for_retry(12)
        self.assertEqual(sum(delays), 12)
