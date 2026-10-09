import unittest
from unittest.mock import Mock, patch
from beeperlocal.keychain_session import KeychainSession
from beeperlocal.native_keychain import KeychainStatusError
from beeperlocal.desktop_router import DesktopRouter


class SessionTests(unittest.TestCase):
    def test_reads_and_identical_writes_reuse_only_verified_ram_value(self):
        backend = Mock()
        backend.get_password.side_effect = ['old', 'new']
        session = KeychainSession(backend)
        self.assertEqual(session.get_password('service', 'account'), 'old')
        self.assertEqual(session.get_password('service', 'account'), 'old')
        session.set_password('service', 'account', 'old')
        backend.set_password.assert_not_called()
        session.set_password('service', 'account', 'new')
        self.assertEqual(session.get_password('service', 'account'), 'new')
        self.assertEqual(backend.get_password.call_count, 2)
        self.assertEqual(backend.set_password.call_count, 1)

    def test_cancel_is_not_prompted_again_until_explicit_retry(self):
        backend = Mock()
        backend.get_password.side_effect = [KeychainStatusError(-128), 'accepted']
        session = KeychainSession(backend)
        for _ in range(4):
            with self.assertRaises(KeychainStatusError): session.get_password('service', 'local-db-key-v1')
        self.assertEqual(backend.get_password.call_count, 1)
        session.retry('other-service', 'account')
        with self.assertRaises(KeychainStatusError): session.get_password('service', 'local-db-key-v1')
        session.retry('service', 'account')
        self.assertEqual(session.get_password('service', 'local-db-key-v1'), 'accepted')
        self.assertEqual(backend.get_password.call_count, 2)

    def test_helper_refresh_preserves_loaded_db_key_and_failed_write_is_not_cached(self):
        backend = Mock()
        backend.get_password.side_effect = ['db-key', 'old-login', 'new-login', 'wrong-write']
        session = KeychainSession(backend)
        session.get_password('service', 'local-db-key-v1')
        session.get_password('service', 'instagram')
        session.retry('service', 'instagram')
        self.assertEqual(session.get_password('service', 'local-db-key-v1'), 'db-key')
        self.assertEqual(session.get_password('service', 'instagram'), 'new-login')
        with self.assertRaises(KeychainStatusError): session.set_password('service', 'instagram', 'must-match')
        self.assertNotIn(('service', 'instagram'), session.values)
        session.clear(); self.assertEqual(len(session.values), 0)


class RouterRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_user_connect_resumes_cancelled_keychain(self):
        class Core:
            def __init__(self, **kwargs): pass
            async def dispatch(self, value): return value
        router = DesktopRouter(line_factory=Core)
        with patch('beeperlocal.credentials.retry_desktop_keychain') as retry:
            await router.dispatch({'op': 'snapshot'})
            await router.dispatch({'op': 'connect'})
            retry.assert_not_called()
            self.assertEqual(await router.dispatch({'op': 'connect', 'interactive': True}), {'op': 'connect'})
            retry.assert_called_once_with('line')
