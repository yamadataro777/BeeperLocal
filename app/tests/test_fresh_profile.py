"""Cold-profile fixtures: real Core/SQLite, empty credential boundaries, no provider traffic."""
import asyncio
from contextlib import nullcontext
from functools import partial
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from beeperlocal.connectors.line import LineConnector
from beeperlocal.connectors.x import XConnector
from beeperlocal.desktop import DesktopCore
from beeperlocal.desktop_instagram import InstagramDesktop
from beeperlocal.desktop_slack import SlackDesktop
from beeperlocal.desktop_x import XDesktop
from beeperlocal.desktop_messenger import MessengerDesktop
from beeperlocal.desktop_router import DesktopRouter
from beeperlocal.messenger import MessengerSession, DeviceStore
from beeperlocal.errors import AppError
from beeperlocal.slack_oauth import SlackOAuth
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore


class EmptyLine:
    async def whoami(self):
        raise AppError('LINE_LOGIN_REQUIRED')


class EmptyX:
    async def events(self, request):
        raise AppError('X_LOGIN_REQUIRED')
        yield  # This boundary implements the worker's event iterator.


class EmptyKeychain:
    def get_password(self, service, account):
        return None


class FreshProfileTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='beeperlocal-empty-profile-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name).resolve()
        self.keys = {p: os.urandom(32) for p in ('line', 'instagram', 'x', 'messenger')}
        self.credentials = MemoryStore()
        self.events = []
        self.router = self.new_router()
        # An accidental connection to the user's credential namespace must fail the test.
        for target in ('beeperlocal.native_keychain.NativeKeychain', 'asyncio.create_subprocess_exec'):
            guard = patch(target, side_effect=AssertionError('external I/O forbidden in cold fixture'))
            guard.start()
            self.addCleanup(guard.stop)

    def new_router(self):
        def factory(cls, scope, **kwargs):
            return partial(cls, credentials=self.credentials,
                db_factory=lambda: EncryptedMessageStore(self.keys[scope], self.directory / scope / 'messages.sqlite3'), **kwargs)
        return DesktopRouter(emit=self.events.append,
            line_factory=factory(DesktopCore, 'line', connector_factory=lambda c: LineConnector(c, cli=EmptyLine())),
            instagram_factory=factory(InstagramDesktop, 'instagram'),
            slack_factory=factory(SlackDesktop, 'line', oauth_factory=lambda c: SlackOAuth(c, client_id='')),
            x_factory=factory(XDesktop, 'x', connector_factory=lambda c: XConnector(c, adapter=EmptyX())),
            messenger_factory=factory(MessengerDesktop, 'messenger', session_factory=lambda: MessengerSession(
                device_store=DeviceStore(backend=EmptyKeychain()), lock=nullcontext)))

    async def asyncTearDown(self):
        await self.router.close()

    async def call(self, provider, op, **kwargs):
        return await self.router.dispatch({'provider': provider, 'op': op, **kwargs})

    async def test_empty_profiles_have_no_history_grants_listener_or_implicit_login(self):
        for provider in self.router.factories:
            with self.subTest(provider=provider):
                state = await self.call(provider, 'snapshot')
                self.assertEqual(state['conversations'], [])
                self.assertIsNone(state['selectedId'])
                self.assertEqual(state['pendingSends'], [])
                self.assertEqual(state['connection'], 'offline')
                control = await self.call(provider, 'management')
                self.assertFalse(control['accountAvailable'])
                self.assertFalse(control['mcp']['enabled'])
                self.assertFalse(control['mcp']['running'])
                self.assertEqual(control['clients'], [])
                self.assertEqual((await self.call(provider, 'search', query='fixture'))['results'], [])
                await self.call(provider, 'stop')
        self.assertEqual(self.credentials.writes, [])

    async def test_first_connect_reports_login_required_and_settings_remain_usable(self):
        expected = {'line': 'LINE_LOGIN_REQUIRED', 'instagram': 'IG_LOGIN_REQUIRED',
                    'slack': 'SLACK_LOGIN_REQUIRED', 'x': 'X_LOGIN_REQUIRED', 'messenger': 'MESSENGER_LOGIN_REQUIRED'}
        for provider, code in expected.items():
            with self.subTest(provider=provider):
                with self.assertRaises(AppError) as caught:
                    await asyncio.wait_for(self.call(provider, 'connect'), 2)
                self.assertEqual(caught.exception.code, code)
                self.assertFalse((await self.call(provider, 'management'))['accountAvailable'])
                await self.call(provider, 'stop')
                await self.call(provider, 'storage_pause', paused=True)
        await self.router.close()
        self.router = self.new_router()
        for provider in expected:
            state = await self.call(provider, 'snapshot')
            self.assertTrue(state['storagePaused'])
            with self.assertRaises(AppError) as caught:
                await self.call(provider, 'connect')
            self.assertEqual(caught.exception.code, 'STORAGE_PAUSED')

    async def test_unconfigured_slack_is_known_before_start_and_does_not_stop_receiver(self):
        status = await self.call('slack', 'slack_login_status')
        self.assertEqual(status, {'stage': 'idle', 'configured': False})
        core = self.router.cores['slack']
        core.connection = 'connected'
        with self.assertRaises(AppError) as caught:
            await self.call('slack', 'slack_login_start')
        self.assertEqual(caught.exception.code, 'SLACK_OAUTH_NOT_CONFIGURED')
        self.assertEqual(core.connection, 'connected')
        self.assertIsNone(core.login_task)
