"""Generic passwords in the macOS login Keychain, preserving item access controls.

Updates never delete/recreate an item or change its ACL. New items use macOS's
default creator-only access. No all-app access, partition-list edits, alternate
secret stores, environment overrides, or process-global UI policy changes.
"""
from __future__ import annotations

from contextlib import contextmanager
import ctypes as C
import sys

NOT_FOUND = -25300
DUPLICATE = -25299
MAX_SECRET_BYTES = 4 * 1024 * 1024


class KeychainStatusError(Exception):
    """Numeric OSStatus only; the caller maps it to a fixed public error code."""


def check(status):
    if status:
        raise KeychainStatusError(int(status))


class NativeKeychain:
    def __init__(self):
        if sys.platform != "darwin":
            raise RuntimeError("macOS required")
        self.security = C.CDLL("/System/Library/Frameworks/Security.framework/Security")
        self.cf = C.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        pointer = C.c_void_p
        self._bind(self.cf, "CFRelease", None, pointer)
        self._bind(self.cf, "CFDictionaryCreate", pointer, pointer, pointer, pointer,
                   C.c_long, pointer, pointer)
        self._bind(self.cf, "CFStringCreateWithBytes", pointer, pointer, pointer,
                   C.c_long, C.c_uint32, C.c_bool)
        self._bind(self.cf, "CFDataCreate", pointer, pointer, pointer, C.c_long)
        self._bind(self.cf, "CFDataGetLength", C.c_long, pointer)
        self._bind(self.cf, "CFDataGetBytePtr", pointer, pointer)
        self._bind(self.cf, "CFGetTypeID", C.c_ulong, pointer)
        self._bind(self.cf, "CFDataGetTypeID", C.c_ulong)
        self._bind(self.security, "SecItemCopyMatching", C.c_int32, pointer, pointer)
        self._bind(self.security, "SecItemUpdate", C.c_int32, pointer, pointer)
        self._bind(self.security, "SecItemAdd", C.c_int32, pointer, pointer)
        self._bind(self.security, "SecItemDelete", C.c_int32, pointer)

    @staticmethod
    def _bind(library, name, result, *args):
        function = getattr(library, name)
        function.restype, function.argtypes = result, args

    def constant(self, name):
        library = self.cf if name.startswith("kCF") else self.security
        return C.c_void_p.in_dll(library, name)

    @contextmanager
    def query(self, values):
        owned = []
        try:
            keys, refs = [], []
            for name, value in values.items():
                keys.append(self.constant(name))
                if isinstance(value, str):
                    data = value.encode("utf-8")
                    ref = self.cf.CFStringCreateWithBytes(None, data, len(data), 0x08000100, False)
                    owned.append(ref)
                elif isinstance(value, bytes):
                    ref = self.cf.CFDataCreate(None, value, len(value))
                    owned.append(ref)
                else:
                    ref = value  # borrowed native constant
                if not ref:
                    raise MemoryError()
                refs.append(ref)
            array = C.c_void_p * len(keys)
            dictionary = self.cf.CFDictionaryCreate(
                None, array(*keys), array(*refs), len(keys),
                C.byref(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryKeyCallBacks")),
                C.byref(C.c_byte.in_dll(self.cf, "kCFTypeDictionaryValueCallBacks")))
            if not dictionary:
                raise MemoryError()
            owned.append(dictionary)
            yield dictionary
        finally:
            for ref in reversed(owned):
                if ref:
                    self.cf.CFRelease(ref)

    def attributes(self, service, account):
        if not isinstance(service, str) or not service or not isinstance(account, str) or not account:
            raise ValueError("Invalid Keychain identifier")
        return {"kSecClass": self.constant("kSecClassGenericPassword"),
                "kSecAttrService": service, "kSecAttrAccount": account}

    def get_password(self, service, account):
        values = {**self.attributes(service, account),
                  "kSecMatchLimit": self.constant("kSecMatchLimitOne"),
                  "kSecReturnData": self.constant("kCFBooleanTrue")}
        result = C.c_void_p()
        try:
            with self.query(values) as query:
                status = self.security.SecItemCopyMatching(query, C.byref(result))
            if status == NOT_FOUND:
                return None
            check(status)
            if not result or self.cf.CFGetTypeID(result) != self.cf.CFDataGetTypeID():
                raise KeychainStatusError(-26275)
            length = self.cf.CFDataGetLength(result)
            if not 0 <= length <= MAX_SECRET_BYTES:
                raise KeychainStatusError(-26275)
            return C.string_at(self.cf.CFDataGetBytePtr(result), length).decode("utf-8")
        finally:
            if result:
                self.cf.CFRelease(result)

    def set_password(self, service, account, password):
        data = password.encode("utf-8")
        # macOS can report success for an empty-data update while retaining the
        # previous value. Our JSON credentials and DB keys are always nonempty.
        if not data or len(data) > MAX_SECRET_BYTES:
            raise ValueError("Invalid Keychain item size")
        values = self.attributes(service, account)
        # No kSecAttrAccess/AccessControl: preserve existing item permissions.
        with self.query(values) as query, self.query({"kSecValueData": data}) as update:
            status = self.security.SecItemUpdate(query, update)
            if status == NOT_FOUND:
                with self.query({**values, "kSecValueData": data}) as new_item:
                    status = self.security.SecItemAdd(new_item, None)
                if status == DUPLICATE:  # Another process created it between update and add.
                    status = self.security.SecItemUpdate(query, update)
            check(status)

    def delete_password(self, service, account):
        with self.query(self.attributes(service, account)) as query:
            status = self.security.SecItemDelete(query)
        if status != NOT_FOUND:
            check(status)
