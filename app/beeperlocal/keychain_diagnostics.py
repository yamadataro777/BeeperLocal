"""Read-only macOS Keychain state. Never retrieve secrets or alter authentication."""
from __future__ import annotations

import ctypes
import ctypes.util
import sys


def session_authentication_failed() -> bool:
    """Distinguish an unlocked-but-unusable login session from an item ACL denial.

    SecKeychainGetStatus can report unlocked while SecKeychainCopySettings fails
    with errSecAuthFailed. Only report this condition if both native calls agree.
    No lock, unlock, password, item lookup, settings write or reset is performed.
    """
    if sys.platform != "darwin":
        return False
    keychain = ctypes.c_void_p()
    release = None
    try:
        security = ctypes.CDLL(ctypes.util.find_library("Security"))
        foundation = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        release = foundation.CFRelease
        release.argtypes = [ctypes.c_void_p]
        release.restype = None
        copy_default = security.SecKeychainCopyDefault
        copy_default.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
        copy_default.restype = ctypes.c_int32
        get_status = security.SecKeychainGetStatus
        get_status.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
        get_status.restype = ctypes.c_int32

        class Settings(ctypes.Structure):
            _fields_ = [("version", ctypes.c_uint32), ("lock_on_sleep", ctypes.c_ubyte),
                        ("use_lock_interval", ctypes.c_ubyte), ("lock_interval", ctypes.c_uint32)]

        copy_settings = security.SecKeychainCopySettings
        copy_settings.argtypes = [ctypes.c_void_p, ctypes.POINTER(Settings)]
        copy_settings.restype = ctypes.c_int32
        if copy_default(ctypes.byref(keychain)) != 0 or not keychain:
            return False
        flags = ctypes.c_uint32()
        if get_status(keychain, ctypes.byref(flags)) != 0 or not flags.value & 1:
            return False
        settings = Settings(version=1)
        return copy_settings(keychain, ctypes.byref(settings)) == -25293
    except Exception:
        return False  # An unavailable diagnostic must not replace the original error.
    finally:
        if release is not None and keychain:
            release(keychain)


def failure_code(exc: Exception, *, writing: bool = False) -> str:
    """Read only numeric OSStatus from an exception chain, never its message."""
    current = exc
    seen = set()
    for _ in range(6):
        if current is None or id(current) in seen:
            break
        seen.add(id(current))
        status = current.args[0] if current.args else None
        if type(status) is int:
            if status == -25293:
                return "KEYCHAIN_SESSION_AUTH_FAILED" if session_authentication_failed() else "KEYCHAIN_AUTH_FAILED"
            if status == -25308:
                return "KEYCHAIN_INTERACTION_REQUIRED"
            if status == -128:
                return "KEYCHAIN_ACCESS_DENIED"
            if status == -67030:
                return "KEYCHAIN_SIGNATURE_INVALID"
        current = current.__cause__ or current.__context__
    return "KEYCHAIN_WRITE_FAILED" if writing else "KEYCHAIN_UNAVAILABLE"
