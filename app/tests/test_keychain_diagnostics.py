"""Authentication diagnostics use fixtures and never unlock the real Keychain."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from beeperlocal.credentials import MacKeychain, MacLocalKeyStore
from beeperlocal.errors import AppError
from beeperlocal.keychain_diagnostics import failure_code, session_authentication_failed


def wrapped_status(status):
    outer = RuntimeError('PRIVATE_SECRET_CANARY')
    outer.__cause__ = Exception(status, 'PRIVATE_SECRET_CANARY')
    return outer


class KeychainFailureTests(unittest.TestCase):
    def test_native_auth_error_with_unusable_session_gets_specific_code(self):
        with patch('beeperlocal.keychain_diagnostics.session_authentication_failed', return_value=True):
            self.assertEqual(failure_code(wrapped_status(-25293)), 'KEYCHAIN_SESSION_AUTH_FAILED')

    def test_item_auth_failure_does_not_claim_system_failure(self):
        with patch('beeperlocal.keychain_diagnostics.session_authentication_failed', return_value=False):
            self.assertEqual(failure_code(wrapped_status(-25293)), 'KEYCHAIN_AUTH_FAILED')

    def test_cancel_interaction_and_signature_are_distinguished_without_probe(self):
        with patch('beeperlocal.keychain_diagnostics.session_authentication_failed', side_effect=AssertionError):
            for status, expected in [(-128, 'KEYCHAIN_ACCESS_DENIED'), (-25308, 'KEYCHAIN_INTERACTION_REQUIRED'),
                                     (-67030, 'KEYCHAIN_SIGNATURE_INVALID')]:
                with self.subTest(status=status):
                    self.assertEqual(failure_code(wrapped_status(status)), expected)

    def test_never_parses_or_repeats_exception_text(self):
        self.assertEqual(failure_code(RuntimeError('PRIVATE_SECRET_CANARY -25293')), 'KEYCHAIN_UNAVAILABLE')
        self.assertEqual(failure_code(RuntimeError('PRIVATE_SECRET_CANARY'), writing=True), 'KEYCHAIN_WRITE_FAILED')

    def test_exception_cycle_is_bounded(self):
        error = RuntimeError('PRIVATE_SECRET_CANARY')
        error.__cause__ = error
        self.assertEqual(failure_code(error), 'KEYCHAIN_UNAVAILABLE')

    def test_session_failure_never_replaces_existing_db_key(self):
        store = MacLocalKeyStore.__new__(MacLocalKeyStore)
        store.backend = Mock()
        store.backend.get_password.side_effect = wrapped_status(-25293)
        with patch('beeperlocal.keychain_diagnostics.session_authentication_failed', return_value=True), \
             patch('beeperlocal.credentials.secrets.token_bytes', side_effect=AssertionError):
            with self.assertRaises(AppError) as caught:
                store.load_or_create()
        self.assertEqual(caught.exception.code, 'KEYCHAIN_SESSION_AUTH_FAILED')
        store.backend.set_password.assert_not_called()
        store.backend.delete_password.assert_not_called()
        self.assertNotIn('PRIVATE_SECRET_CANARY', str(caught.exception))

    def test_provider_credentials_do_not_leak_native_errors(self):
        store = MacKeychain.__new__(MacKeychain)
        store.backend = Mock()
        store.backend.get_password.side_effect = wrapped_status(-128)
        with self.assertRaises(AppError) as caught:
            store.load('line')
        self.assertEqual(str(caught.exception), 'KEYCHAIN_ACCESS_DENIED')
        store.backend.set_password.assert_not_called()


class NativeMetadataTests(unittest.TestCase):
    def native_state(self, *, unlocked=True, settings_status=-25293):
        calls = []
        def copy_default(result):
            result._obj.value = 42
            calls.append('default')
            return 0
        def get_status(keychain, flags):
            flags._obj.value = 7 if unlocked else 6
            calls.append('status')
            return 0
        def copy_settings(keychain, settings):
            self.assertEqual(settings._obj.version, 1)
            self.assertEqual(ctypes.sizeof(settings._obj), 12)
            calls.append('settings')
            return settings_status
        def release(value):
            self.assertEqual(value.value, 42)
            calls.append('release')
        security = SimpleNamespace(SecKeychainCopyDefault=copy_default, SecKeychainGetStatus=get_status,
                                   SecKeychainCopySettings=copy_settings)
        foundation = SimpleNamespace(CFRelease=release)
        with patch('sys.platform', 'darwin'), patch('ctypes.util.find_library', side_effect=lambda name: name), \
             patch('ctypes.CDLL', side_effect=[security, foundation]):
            result = session_authentication_failed()
        return result, calls

    def test_unlocked_but_settings_auth_failed_is_detected_with_read_only_calls(self):
        result, calls = self.native_state()
        self.assertTrue(result)
        self.assertEqual(calls, ['default', 'status', 'settings', 'release'])

    def test_locked_keychain_does_not_trigger_settings_authentication(self):
        result, calls = self.native_state(unlocked=False)
        self.assertFalse(result)
        self.assertEqual(calls, ['default', 'status', 'release'])

    def test_healthy_settings_do_not_claim_session_failure(self):
        result, calls = self.native_state(settings_status=0)
        self.assertFalse(result)
        self.assertEqual(calls[-1], 'release')

    def test_unavailable_diagnostic_keeps_original_error_classification(self):
        with patch('ctypes.CDLL', side_effect=OSError):
            self.assertFalse(session_authentication_failed())
