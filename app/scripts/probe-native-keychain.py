#!/usr/bin/env python3
"""Explicit, isolated live Keychain check; never touches production service names."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from beeperlocal.native_keychain import NativeKeychain, check


def persistent_reference(store, service, account):
    values = {**store.attributes(service, account),
              "kSecReturnPersistentRef": store.constant("kCFBooleanTrue"),
              "kSecMatchLimit": store.constant("kSecMatchLimitOne")}
    result = ctypes.c_void_p()
    try:
        with store.query(values) as query:
            check(store.security.SecItemCopyMatching(query, ctypes.byref(result)))
        return ctypes.string_at(store.cf.CFDataGetBytePtr(result), store.cf.CFDataGetLength(result))
    finally:
        if result:
            store.cf.CFRelease(result)


def probe():
    from keyring.backends.macOS import Keyring
    native, legacy = NativeKeychain(), Keyring()
    results = {}
    for origin, creator in [("native", native), ("legacy", legacy)]:
        service = "local.beeperlocal.keychain-test." + uuid4().hex
        account = "temporary-fixture"
        assert native.get_password(service, account) is None
        try:
            creator.set_password(service, account, "fixture-before")
            original = persistent_reference(native, service, account)
            assert native.get_password(service, account) == "fixture-before"
            for value in ["fixture-after", "日本語☕\x00fixture"]:
                native.set_password(service, account, value)
                assert persistent_reference(native, service, account) == original
                assert native.get_password(service, account) == value
                assert legacy.get_password(service, account) == value
            try:
                native.set_password(service, account, "")
            except ValueError:
                pass
            else:
                raise AssertionError("Empty update must fail explicitly")
            assert native.get_password(service, account) == value
            assert persistent_reference(native, service, account) == original
            results[origin + "_item_preserved"] = True
        finally:
            native.delete_password(service, account)
        assert native.get_password(service, account) is None
    return {**results, "cleanup_verified": True, "production_items_accessed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    try:
        print(json.dumps(probe()))
    except Exception:
        print('{"ok":false,"error":"ISOLATED_KEYCHAIN_PROBE_FAILED"}')
        raise SystemExit(1)
