"""Keychain policy tests do not touch the user's real Keychain."""
from contextlib import contextmanager
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from beeperlocal.native_keychain import NativeKeychain, KeychainStatusError, NOT_FOUND, DUPLICATE


class NativeKeychainTests(unittest.TestCase):
    def setUp(self):
        self.native = NativeKeychain.__new__(NativeKeychain)
        self.native.constant = lambda key: key
        @contextmanager
        def query(values):
            yield values
        self.native.query = query
        self.native.security = SimpleNamespace(
            SecItemUpdate=Mock(return_value=0), SecItemAdd=Mock(return_value=0),
            SecItemDelete=Mock(return_value=0), SecItemCopyMatching=Mock(return_value=NOT_FOUND))
        self.native.cf = SimpleNamespace(CFRelease=Mock())

    def test_update_preserves_item_and_its_access_controls(self):
        self.native.set_password("service", "account", "更新☕")
        query, update = self.native.security.SecItemUpdate.call_args.args
        self.assertEqual(query, {"kSecClass": "kSecClassGenericPassword", "kSecAttrService": "service",
                                 "kSecAttrAccount": "account"})
        self.assertEqual(update, {"kSecValueData": "更新☕".encode()})
        self.native.security.SecItemAdd.assert_not_called()
        self.native.security.SecItemDelete.assert_not_called()

    def test_new_item_uses_default_owner_without_widening_access(self):
        self.native.security.SecItemUpdate.return_value = NOT_FOUND
        self.native.set_password("service", "account", "fixture")
        values, output = self.native.security.SecItemAdd.call_args.args
        self.assertEqual(set(values), {"kSecClass", "kSecAttrService", "kSecAttrAccount", "kSecValueData"})
        self.assertIsNone(output)
        self.native.security.SecItemDelete.assert_not_called()

    def test_cancel_denial_and_locked_keychain_do_not_recreate_item(self):
        for status in (-128, -25293, -25308, -67030):
            with self.subTest(status=status):
                self.native.security.SecItemUpdate.return_value = status
                with self.assertRaises(KeychainStatusError) as caught:
                    self.native.set_password("service", "account", "PRIVATE_SECRET_CANARY")
                self.assertEqual(caught.exception.args, (status,))
                self.native.security.SecItemAdd.assert_not_called()
                self.native.security.SecItemDelete.assert_not_called()

    def test_creation_race_updates_winner_without_replacing_permissions(self):
        self.native.security.SecItemUpdate.side_effect = [NOT_FOUND, 0]
        self.native.security.SecItemAdd.return_value = DUPLICATE
        self.native.set_password("service", "account", "fixture")
        self.assertEqual(self.native.security.SecItemUpdate.call_count, 2)
        self.native.security.SecItemDelete.assert_not_called()

    def test_failed_add_stops_without_delete_or_retry(self):
        self.native.security.SecItemUpdate.return_value = NOT_FOUND
        self.native.security.SecItemAdd.return_value = -128
        with self.assertRaises(KeychainStatusError):
            self.native.set_password("service", "account", "fixture")
        self.assertEqual(self.native.security.SecItemUpdate.call_count, 1)
        self.native.security.SecItemDelete.assert_not_called()

    def test_absent_read_is_none_and_denied_read_is_not_absence(self):
        self.assertIsNone(self.native.get_password("service", "account"))
        self.native.security.SecItemCopyMatching.return_value = -128
        with self.assertRaises(KeychainStatusError):
            self.native.get_password("service", "account")

    def test_read_releases_result_on_decode_failure(self):
        def read(query, output):
            output._obj.value = 42
            return 0
        self.native.security.SecItemCopyMatching.side_effect = read
        self.native.cf.CFGetTypeID = lambda ref: 1
        self.native.cf.CFDataGetTypeID = lambda: 1
        self.native.cf.CFDataGetLength = lambda ref: 1
        buffer = ctypes.create_string_buffer(b"\xff")
        self.native.cf.CFDataGetBytePtr = lambda ref: ctypes.addressof(buffer)
        with self.assertRaises(UnicodeDecodeError):
            self.native.get_password("service", "account")
        self.native.cf.CFRelease.assert_called_once()

    def test_explicit_delete_is_scoped_and_missing_is_idempotent(self):
        self.native.security.SecItemDelete.return_value = NOT_FOUND
        self.native.delete_password("service", "account")
        query, = self.native.security.SecItemDelete.call_args.args
        self.assertEqual(query["kSecAttrService"], "service")
        self.assertEqual(query["kSecAttrAccount"], "account")
        self.native.security.SecItemUpdate.assert_not_called()

    def test_invalid_identifiers_and_large_values_never_call_keychain(self):
        for service, account in [("", "account"), ("service", ""), (None, "account")]:
            with self.assertRaises(ValueError):
                self.native.set_password(service, account, "fixture")
        with self.assertRaises(ValueError):
            self.native.set_password("service", "account", "x" * (4 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            self.native.set_password("service", "account", "")
        self.native.security.SecItemUpdate.assert_not_called()
