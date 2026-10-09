"""Explicit native macOS Keychain backends; never fall back to file/env secrets."""
from __future__ import annotations
import base64
import json
import secrets
import sys
import uuid
from typing import Any, Protocol
from .errors import AppError
from .keychain_diagnostics import failure_code
from .models import SUPPORTED_PROVIDERS

SERVICE = "BeeperLocalPoC.v1"
LOCAL_DB_KEY_ACCOUNT = "local-db-key-v1"
_desktop_session = None


def start_desktop_keychain_session():
    global _desktop_session
    if _desktop_session is not None:
        return
    from .keychain_session import KeychainSession
    _desktop_session = KeychainSession(_backend())


def end_desktop_keychain_session():
    global _desktop_session
    if _desktop_session is not None:
        _desktop_session.clear()
    _desktop_session = None


def retry_desktop_keychain(provider):
    if _desktop_session is None:
        return
    services = {'line': SERVICE, 'slack': SERVICE, 'instagram': 'BeeperLocalInstagramIntegration.v1',
                'x': 'BeeperLocalXIntegration.v1', 'messenger': 'BeeperLocalMessengerIntegration.v1'}
    _desktop_session.retry(services[provider], provider)
    if provider == 'messenger':
        _desktop_session.retry('local.beeperlocal.messenger-verification.v1', 'bounded-receive-state')


def _backend():
    if _desktop_session is not None:
        return _desktop_session
    if sys.platform != "darwin":
        raise AppError("UNSUPPORTED_PLATFORM")
    try:
        from .native_keychain import NativeKeychain
        return NativeKeychain()
    except ImportError:
        raise AppError("DEPENDENCY_MISSING") from None
    except Exception:
        raise AppError("KEYCHAIN_UNAVAILABLE") from None


class CredentialStore(Protocol):
    def load(self, provider: str) -> dict[str, Any]: ...
    def save(self, provider: str, data: dict[str, Any]) -> None: ...
    def delete(self, provider: str) -> None: ...


class MacKeychain:
    service = SERVICE
    def __init__(self, *, service=SERVICE) -> None:
        self.service = service
        self.backend = _backend()

    def _check(self, provider: str) -> None:
        if provider not in SUPPORTED_PROVIDERS:
            raise AppError("INVALID_INPUT")

    def load(self, provider: str) -> dict[str, Any]:
        self._check(provider)
        try:
            raw = self.backend.get_password(self.service, provider)
        except Exception as exc:
            raise AppError(failure_code(exc)) from None
        if not raw:
            raise AppError("CREDENTIALS_MISSING")
        try:
            value = json.loads(raw)
            if not isinstance(value, dict) or value.get("schema_version") != 1:
                raise ValueError()
            return value
        except (ValueError, TypeError):
            raise AppError("CREDENTIALS_CORRUPT") from None

    def save(self, provider: str, data: dict[str, Any]) -> None:
        self._check(provider)
        raw = json.dumps({**data, "schema_version": 1}, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        try:
            self.backend.set_password(self.service, provider, raw)
            if self.backend.get_password(self.service, provider) != raw:
                raise RuntimeError()
        except Exception as exc:
            raise AppError(failure_code(exc, writing=True)) from None

    def delete(self, provider: str) -> None:
        self._check(provider)
        try:
            if self.backend.get_password(self.service, provider) is not None:
                self.backend.delete_password(self.service, provider)
        except Exception as exc:
            raise AppError(failure_code(exc)) from None

    def probe(self) -> None:
        key = "doctor-" + uuid.uuid4().hex
        value = uuid.uuid4().hex
        try:
            self.backend.set_password(self.service, key, value)
            if self.backend.get_password(self.service, key) != value:
                raise RuntimeError()
        except Exception as exc:
            raise AppError(failure_code(exc)) from None
        finally:
            try:
                self.backend.delete_password(self.service, key)
            except Exception:
                pass


class MacLocalKeyStore:
    service = SERVICE
    """Stores only the random 256-bit local-message encryption key in Keychain."""
    def __init__(self, *, service=SERVICE) -> None:
        self.service = service
        self.backend = _backend()

    def load(self) -> bytes:
        try:
            raw = self.backend.get_password(self.service, LOCAL_DB_KEY_ACCOUNT)
        except Exception as exc:
            raise AppError(failure_code(exc)) from None
        if not raw:
            raise AppError("LOCAL_DB_KEY_MISSING")
        try:
            key = base64.urlsafe_b64decode(raw.encode("ascii"))
        except Exception:
            raise AppError("LOCAL_DB_KEY_INVALID") from None
        if len(key) != 32:
            raise AppError("LOCAL_DB_KEY_INVALID")
        return key

    def load_or_create(self) -> bytes:
        try:
            return self.load()
        except AppError as exc:
            if exc.code != "LOCAL_DB_KEY_MISSING":
                raise
        key = secrets.token_bytes(32)
        raw = base64.urlsafe_b64encode(key).decode("ascii")
        try:
            self.backend.set_password(self.service, LOCAL_DB_KEY_ACCOUNT, raw)
            if self.backend.get_password(self.service, LOCAL_DB_KEY_ACCOUNT) != raw:
                raise RuntimeError()
        except Exception as exc:
            raise AppError(failure_code(exc, writing=True)) from None
        return key

    def delete(self) -> None:
        try:
            if self.backend.get_password(self.service, LOCAL_DB_KEY_ACCOUNT) is not None:
                self.backend.delete_password(self.service, LOCAL_DB_KEY_ACCOUNT)
        except Exception as exc:
            raise AppError(failure_code(exc)) from None
