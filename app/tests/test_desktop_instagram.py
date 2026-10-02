"""GUI provider isolation and durable IG send/receive; all accounts are fixtures."""
import asyncio
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from beeperlocal.connectors.instagram import InstagramConnector, conversation
from beeperlocal.desktop_instagram import InstagramDesktop
from beeperlocal.desktop_router import DesktopRouter
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from .test_instagram import CONVERSATION, SESSION_EVENT, history, message, store


class DesktopAdapter:
    def __init__(self):
        self.queue = asyncio.Queue()
        self.ready = asyncio.Event()
        self.live_watchers = 0
        self.sends = 0
        self.send_error = None
        self.before_send = lambda: None
        self.requests = []
        self.history_rows = [message()]
        self.watch_failures = []

    async def events(self, request, **kwargs):
        self.requests.append(request['op'])
        yield deepcopy(SESSION_EVENT)
        op = request['op']
        if op == 'whoami':
            yield {'type': 'result', 'account_id': '123456', 'own_fbid': '654321'}
        elif op == 'conversations':
            yield {'type': 'result', 'conversations': [CONVERSATION], 'limited': True}
        elif op == 'history':
            yield history(*self.history_rows)
        elif op == 'send':
            self.sends += 1
            self.before_send()
            if self.send_error:
                raise self.send_error
            yield {'type': 'result', 'encrypted': False, 'message': message(
                id='mid.sent', sender_id='654321', direction='outgoing', text=request['text'])}
        elif op == 'watch':
            self.live_watchers += 1
            try:
                if self.watch_failures:
                    raise self.watch_failures.pop(0)
                yield history(*self.history_rows, type='history')
                yield {'type': 'status', 'code': 'connected'}
                self.ready.set()
                while True:
                    event = await self.queue.get()
                    if event is None:
                        return
                    if isinstance(event, Exception):
                        raise event
                    yield event
            finally:
                self.live_watchers -= 1


class InstagramDesktopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve() / 'state' / 'messages.sqlite3'
        self.credentials = store()
        self.adapter = DesktopAdapter()
        self.events = []
        self.record = StoredConversation('instagram', '123456', conversation(CONVERSATION))
        self.core = self.make_core()

    def make_core(self):
        return InstagramDesktop(credentials=self.credentials,
            db_factory=lambda: EncryptedMessageStore(b'k' * 32, self.path),
            connector_factory=lambda credentials: InstagramConnector(credentials, adapter=self.adapter),
            emit=self.events.append)

    async def asyncTearDown(self):
        await self.core.close()

    async def connect(self):
        self.adapter.ready.clear()
        result = await self.core.dispatch({'op': 'connect'})
        await asyncio.wait_for(self.adapter.ready.wait(), 1)
        return result

    async def until(self, condition):
        for _ in range(100):
            if condition():
                return
            await asyncio.sleep(.01)
        self.fail('Expected state was not reached')

    async def test_terminated_watch_recovers_history_once_and_keeps_receiving(self):
        await self.connect()
        self.core.retry_delays = (.01, .02)
        self.adapter.history_rows.append(message(id='mid.while.offline', text='offline canary'))
        await self.adapter.queue.put(None)
        await self.until(lambda: self.adapter.requests.count('watch') == 2 and self.core.receiving == 'waiting')
        self.assertEqual(self.core.db.total_count(), 2)
        self.assertIsNone(self.core.error_code)
        self.assertEqual(self.adapter.live_watchers, 1)
        self.assertEqual(self.adapter.sends, 0)
        self.assertTrue(any(e.get('receiving') == 'reconnecting' and e.get('retryAttempt') == 1 for e in self.events))
        await self.adapter.queue.put({'type': 'message', 'source': 'realtime',
                                     'message': message(id='mid.while.offline', text='offline canary')})
        await asyncio.sleep(.02)
        self.assertEqual(self.core.db.total_count(), 2)

    async def test_repeated_transient_failures_stop_at_retry_limit(self):
        await self.connect()
        self.core.retry_delays = (.01, .02)
        self.adapter.watch_failures = [AppError('IG_REQUEST_TIMEOUT'), AppError('IG_REQUEST_FAILED')]
        await self.adapter.queue.put(AppError('IG_REQUEST_FAILED'))
        await self.until(lambda: self.core.error_code == 'SYNC_RETRY_EXHAUSTED')
        self.assertEqual(self.core.receiving, 'error')
        self.assertEqual(self.adapter.requests.count('watch'), 3)
        self.assertEqual(self.adapter.live_watchers, 0)
        self.assertEqual(self.adapter.sends, 0)

    async def test_explicit_stop_cancels_pending_reconnect(self):
        await self.connect()
        self.core.retry_delays = (.05,)
        await self.adapter.queue.put(AppError('IG_REQUEST_FAILED'))
        await self.until(lambda: self.core.receiving == 'reconnecting')
        await self.core.dispatch({'op': 'stop'})
        await asyncio.sleep(.07)
        self.assertEqual(self.core.receiving, 'stopped')
        self.assertEqual(self.adapter.requests.count('watch'), 1)
        self.assertEqual(self.adapter.live_watchers, 0)

    async def test_auth_and_protocol_errors_never_reconnect(self):
        for code in ('CREDENTIALS_INVALID', 'IG_AUTH_ACTION_REQUIRED', 'IG_PROTOCOL_ERROR', 'IG_RESYNC_REQUIRED'):
            with self.subTest(code=code):
                await self.connect()
                before = self.adapter.requests.count('watch')
                self.core.retry_delays = (.001,)
                await self.adapter.queue.put(AppError(code))
                await self.until(lambda: self.core.receiving == 'error')
                self.assertEqual(self.core.error_code, 'IG_LOGIN_REQUIRED' if code == 'CREDENTIALS_INVALID' else code)
                await asyncio.sleep(.01)
                self.assertEqual(self.adapter.requests.count('watch'), before)

    async def test_storage_failure_stops_without_reconnect_or_send(self):
        await self.connect()
        before = self.adapter.requests.count('watch')
        original = self.core.db.upsert
        def fail(*args, **kwargs):
            raise AppError('LOCAL_DB_UNAVAILABLE')
        self.core.db.upsert = fail
        await self.adapter.queue.put({'type': 'message', 'source': 'realtime',
                                     'message': message(id='mid.not.saved')})
        await self.until(lambda: self.core.error_code == 'LOCAL_DB_UNAVAILABLE')
        self.core.db.upsert = original
        self.assertEqual(self.core.receiving, 'error')
        self.assertEqual(self.adapter.requests.count('watch'), before)
        self.assertEqual(self.adapter.sends, 0)

    async def test_account_change_while_retrying_stops_before_provider_request(self):
        await self.connect()
        self.core.retry_delays = (.02,)
        self.credentials.save('instagram', {**self.credentials.load('instagram'), 'account_id': '999'})
        await self.adapter.queue.put(AppError('IG_REQUEST_FAILED'))
        await self.until(lambda: self.core.error_code == 'ACCOUNT_CHANGED')
        self.assertEqual(self.core.receiving, 'error')
        self.assertEqual(self.adapter.requests.count('watch'), 1)

    def send_request(self, **changes):
        return {'op': 'send', 'conversationId': self.record.id, 'text': 'IG送信テスト',
                'requestId': str(uuid4()), **changes}

    async def test_connect_receive_restart_search_and_ciphertext(self):
        result = await self.connect()
        self.assertEqual(result['selectedId'], self.record.id)
        self.assertEqual(result['conversations'][0]['provider'], 'instagram')
        self.assertEqual(self.core.receiving, 'waiting')
        await self.adapter.queue.put({'type': 'message', 'source': 'realtime',
                                     'message': message(id='mid.realtime', text='IG新着canary')})
        for _ in range(30):
            if self.core.db.total_count() == 2:
                break
            await asyncio.sleep(.01)
        self.assertEqual(self.core.db.total_count(), 2)
        self.assertEqual(self.core.messages(self.record.id)['historyLimit'], 20)
        await self.core.close()
        self.core = self.make_core()
        result = await self.core.dispatch({'op': 'snapshot'})
        self.assertEqual(result['connection'], 'offline')
        found = await self.core.dispatch({'op': 'search', 'query': 'IG新着canary'})
        self.assertEqual(len(found['results']), 1)
        for canary in (b'IG_PRIVATE_BODY_CANARY', b'IG_PRIVATE_TITLE_CANARY', b'123456', 'IG新着canary'.encode()):
            self.assertNotIn(canary, self.path.read_bytes())

    async def test_send_is_durable_once_and_stops_watch_before_cookie_update(self):
        await self.connect()
        request = self.send_request()
        def check():
            self.assertEqual(self.adapter.live_watchers, 0)
            self.assertEqual(self.core.db.get_outgoing(request['requestId']).status, 'sending')
        self.adapter.before_send = check
        first = await self.core.dispatch(request)
        again = await self.core.dispatch(request)
        self.assertEqual(first['messageId'], again['messageId'])
        self.assertEqual(self.adapter.sends, 1)
        self.assertTrue(again['duplicateSuppressed'])

    async def test_unknown_send_survives_restart_and_is_not_replayed(self):
        await self.connect()
        request = self.send_request()
        self.adapter.send_error = AppError('IG_SEND_UNKNOWN')
        with self.assertRaises(AppError):
            await self.core.dispatch(request)
        await self.core.close()
        self.core = self.make_core()
        result = await self.connect()
        self.assertEqual(len(result['pendingSends']), 1)
        with self.assertRaises(AppError):
            await self.core.dispatch(request)
        self.assertEqual(self.adapter.sends, 1)

    async def test_wrong_provider_identity_and_oversized_text_never_send(self):
        await self.connect()
        wrong = replace(self.record, provider='line')
        for request in (self.send_request(conversationId=wrong.id), self.send_request(text='あ' * 1334)):
            with self.assertRaises(AppError):
                await self.core.dispatch(request)
        self.assertEqual(self.adapter.sends, 0)

    async def test_failed_storage_prevents_send(self):
        await self.connect()
        await self.core.stop_watch()
        original = self.core.db.upsert
        def fail(messages, **kwargs):
            if kwargs.get('outgoing_requests'):
                raise AppError('LOCAL_DB_UNAVAILABLE')
            return original(messages, **kwargs)
        self.core.db.upsert = fail
        with self.assertRaises(AppError):
            await self.core.dispatch(self.send_request())
        self.assertEqual(self.adapter.sends, 0)

    async def test_pause_persists_and_mcp_operations_are_rejected(self):
        await self.connect()
        await self.core.dispatch({'op': 'storage_pause', 'paused': True})
        self.assertEqual(self.adapter.live_watchers, 0)
        with self.assertRaises(AppError):
            await self.core.dispatch({'op': 'connect'})
        await self.core.close()
        self.core = self.make_core()
        self.assertTrue((await self.core.dispatch({'op': 'snapshot'}))['storagePaused'])
        for op in ('management', 'mcp_configure', 'storage_delete', 'line_login_start', 'line_login_status', 'avatar'):
            with self.assertRaises(AppError):
                await self.core.dispatch({'op': op})

    async def test_scope_mismatch_never_persists_a_history_batch(self):
        await self.connect()
        batch = await self.core.connector.fetch(20)
        batch.conversations = [replace(self.record, account_id='999')]
        with self.assertRaises(AppError):
            self.core.persist_history(batch)
        self.assertEqual(self.core.db.total_count(), 1)


class RouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_desktop_cores_preserve_line_features_and_refuse_cross_provider_send(self):
        from beeperlocal.desktop import DesktopCore
        from beeperlocal.connectors.line import LineConnector
        from .test_desktop import DesktopCLI
        from .test_line import store as line_store
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve()
            line, instagram = DesktopCLI(), DesktopAdapter()
            events = []
            router = DesktopRouter(emit=events.append,
                line_factory=lambda emit: DesktopCore(credentials=line_store(),
                    db_factory=lambda: EncryptedMessageStore(b'l' * 32, directory / 'line' / 'messages.db'),
                    connector_factory=lambda c: LineConnector(c, cli=line), emit=emit),
                instagram_factory=lambda emit: InstagramDesktop(credentials=store(),
                    db_factory=lambda: EncryptedMessageStore(b'i' * 32, directory / 'instagram' / 'messages.db'),
                    connector_factory=lambda c: InstagramConnector(c, adapter=instagram), emit=emit))
            try:
                first = await router.dispatch({'op': 'connect', 'provider': 'line'})
                second = await router.dispatch({'op': 'connect', 'provider': 'instagram'})
                await asyncio.wait_for(instagram.ready.wait(), 1)
                self.assertTrue(all(c['provider'] == 'line' for c in first['conversations']))
                self.assertTrue(all(c['provider'] == 'instagram' for c in second['conversations']))
                self.assertEqual((await router.dispatch({'op': 'line_login_status'}))['stage'], 'idle')
                self.assertFalse((await router.dispatch({'op': 'management'}))['mcp']['enabled'])
                for provider, wrong in [('line', second['selectedId']), ('instagram', first['selectedId'])]:
                    with self.assertRaises(AppError):
                        await router.dispatch({'op': 'send', 'provider': provider, 'conversationId': wrong,
                                               'text': 'must never send', 'requestId': str(uuid4())})
                await router.dispatch({'op': 'storage_pause', 'provider': 'instagram', 'paused': True})
                self.assertFalse((await router.dispatch({'op': 'snapshot', 'provider': 'line'}))['storagePaused'])
                self.assertEqual(line.send_calls, 0)
                self.assertEqual(instagram.sends, 0)
                self.assertEqual({e['provider'] for e in events}, {'line', 'instagram'})
            finally:
                await router.close()

    async def test_provider_is_explicit_and_events_keep_their_scope(self):
        class FakeCore:
            def __init__(self, emit): self.emit = emit
            async def dispatch(self, request):
                self.emit({'event': 'messages_changed'})
                return request
            async def close(self): pass
        events = []
        router = DesktopRouter(emit=events.append, line_factory=FakeCore, instagram_factory=FakeCore)
        self.assertEqual(await router.dispatch({'op': 'snapshot', 'provider': 'instagram'}), {'op': 'snapshot'})
        self.assertEqual(events[-1]['provider'], 'instagram')
        await router.dispatch({'op': 'snapshot'})
        self.assertEqual(events[-1]['provider'], 'line')
        for value in ('x', None, ['instagram']):
            with self.assertRaises(AppError): await router.dispatch({'op': 'snapshot', 'provider': value})
        await router.close()
