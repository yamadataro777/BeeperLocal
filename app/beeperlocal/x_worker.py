"""Private X worker: credentials stay here; verified Chat and labelled legacy text cross IPC.

The frozen Core starts itself with --x-worker. Each command holds an exclusive
adapter lock, so a cancelled watch must finish before another operation starts.
"""
from __future__ import annotations

import json
import logging
import os
import re
import signal
import sys
import time

from .errors import AppError
from .keychain_diagnostics import failure_code
from .native_keychain import NativeKeychain, KeychainStatusError
from .reporting import private_directory
from .xcrypto.core import (Bridge, Connector, ConnectorError, STATE_DIR, canonical,
                          participant_pair, disable_core_dumps, instance_lock)
from .xcrypto.web_login import browser_login, chat_pin

MAX_FRAME = 8 * 1024 * 1024
ERROR_MAP = {
    "login_required": "X_LOGIN_REQUIRED", "reauth_required": "X_LOGIN_REQUIRED",
    "chat_pin_required": "X_UNLOCK_REQUIRED", "key_rotation_requires_login": "X_KEY_CHANGED",
    "chat_pin_unlock_failed": "X_UNLOCK_FAILED", "x_chat_setup_required": "X_SETUP_REQUIRED",
    "identity_key_mismatch": "X_VERIFY_FAILED", "identity_binding_failed": "X_VERIFY_FAILED",
    "signature_or_decryption_failed": "X_VERIFY_FAILED", "signature_verification_failed": "X_VERIFY_FAILED",
    "signing_keys_missing": "X_VERIFY_FAILED", "conversation_key_rollback": "X_VERIFY_FAILED",
    "signed_id_conflict": "X_VERIFY_FAILED", "message_scope_mismatch": "X_VERIFY_FAILED",
    "account_scope_mismatch": "ACCOUNT_CHANGED", "already_running": "X_ALREADY_RUNNING",
    "bridge_timeout": "X_REQUEST_TIMEOUT", "network_timeout": "X_REQUEST_TIMEOUT",
    "bridge_closed": "X_REQUEST_FAILED", "x_request_failed": "X_REQUEST_FAILED",
    "send_outcome_unknown": "X_SEND_UNKNOWN", "send_already_attempted": "X_SEND_UNKNOWN",
    "storage_integrity_failed": "LOCAL_DB_CORRUPT", "unsafe_storage_path": "LOCAL_DB_UNAVAILABLE",
    "direct_conversation_required": "X_DIRECT_ONLY", "history_window_incomplete": "X_HISTORY_INCOMPLETE",
    "web_login_timeout": "X_LOGIN_TIMEOUT", "web_login_closed": "X_LOGIN_CANCELLED",
    "cancelled": "X_LOGIN_CANCELLED", "interactive_challenge_required": "X_LOGIN_REQUIRED",
    "web_login_protocol_failed": "X_LOGIN_FAILED",
}


def write(value):
    frame = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
    if len(frame) > MAX_FRAME:
        raise AppError("X_PROTOCOL_ERROR")
    sys.stdout.buffer.write(frame)
    sys.stdout.buffer.flush()


def read():
    line = sys.stdin.buffer.readline(MAX_FRAME + 1)
    if not line or len(line) > MAX_FRAME or not line.endswith(b"\n"):
        raise AppError("X_PROTOCOL_ERROR")
    try:
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise AppError("X_PROTOCOL_ERROR") from None


def history_payload(connector, conversation, limit):
    result = connector.history(conversation)
    rows = sorted(result["messages"], key=lambda m: (m["created_at_msec"] or 0, m["provider_message_id"]))
    rows_visible = rows[-limit:]
    return {"type": "history", "messages": rows_visible,
            "legacy_message_count": sum(m.get("source") == "legacy" and m.get("verified") is False for m in rows_visible), "raw_items": result["raw_count"],
            "excluded_events": result["raw_count"] - len(rows),
            "unsupported_legacy_count": result["unsupported_legacy_count"],
            "history_limited": not result["complete"] or len(rows) > limit,
            "caught_up": result["caught_up"]}


def run(request, *, connector_factory=None, emit=write, read_ack=read):
    operation = request.get("op")
    shapes = {"connect": {"account_id"}, "conversations": {"account_id", "limit"},
              "clear_local": {"account_id"},
              "history": {"account_id", "conversation", "limit"},
              "history_page": {"account_id", "conversation", "before"},
              "media": {"account_id", "conversation", "message_id", "index"},
              "send": {"account_id", "conversation", "text"},
              "send_image": {"account_id", "conversation", "image"},
              "watch": {"account_id", "conversation", "limit", "timeout"},
              "login": {"account_id"}, "unlock": {"account_id"}}
    if operation not in shapes or set(request) != {"op"} | shapes[operation]:
        raise AppError("INVALID_INPUT")
    expected = request["account_id"]
    if not isinstance(expected, str) or (expected and not re.fullmatch(r"[0-9]{1,128}", expected)):
        raise AppError("INVALID_INPUT")
    if operation not in {"connect", "login", "unlock"} and not expected:
        raise AppError("X_LOGIN_REQUIRED")
    limit = request.get("limit", 100)
    if type(limit) is not int or not 1 <= limit <= (10000 if operation == "conversations" else 100):
        raise AppError("INVALID_INPUT")
    timeout = request.get("timeout", 0)
    if type(timeout) is not int or not 0 <= timeout <= 600:
        raise AppError("INVALID_INPUT")
    if "conversation" in request:
        conv = canonical(request["conversation"])
        if not conv.startswith("g"): participant_pair(conv, expected)
    if operation == 'clear_local':
        connector = connector_factory() if connector_factory else Connector(NativeKeychain(), None)
        connector.credentials = connector.read_credentials()
        if not connector.credentials or connector.credentials.get('user') != expected:
            raise AppError('ACCOUNT_CHANGED')
        connector.open_store()
        try: connector.store.clear_message_data()
        finally: connector.store.close()
        emit({'type':'result', 'cleared':True})
        return
    connector = connector_factory() if connector_factory else Connector(NativeKeychain(), Bridge())
    try:
        if operation in {"login", "unlock"}:
            if operation == "login":
                emit({"type": "auth_status", "stage": "web"})
                connector.login_browser(browser_login)
            else:
                connector.resume()
            def prompt():
                emit({"type": "auth_status", "stage": "pin"})
                return chat_pin()
            connector.unlock(prompt)
        else:
            connector.resume()
            connector.unlock()
        if expected and connector.own != expected:
            raise AppError("ACCOUNT_CHANGED")
        if operation in {"connect", "login", "unlock"}:
            emit({"type": "result", "account_id": connector.own})
        elif operation == "conversations":
            result = connector.conversations()
            emit({"type": "result", "items": result["items"][:limit],
                  "limited": not result["complete"] or len(result["items"]) > limit})
        elif operation == 'history_page':
            result = connector.history(request['conversation'], max_pages=1, before_cursor=request['before'])
            rows = result['messages']
            emit({'type':'result', 'messages':rows, 'raw_items':result['raw_count'], 'excluded_events':result['raw_count']-len(rows),
                  'unsupported_legacy_count':result['unsupported_legacy_count'], 'legacy_message_count':result.get('legacy_message_count', 0),
                  'history_limited':not result['complete'], 'next_before':result.get('next_before'), 'deletions':result.get('deletions', []),
                  'members':connector.store.get('members:' + canonical(request['conversation']))})
        elif operation == 'media':
            import base64
            data = connector.download_attachment(request['conversation'], request['message_id'], request['index'])
            emit({'type':'result', 'data':base64.b64encode(data).decode()})
        elif operation == "history":
            emit({**history_payload(connector, request["conversation"], limit), "type": "result"})
        elif operation in {"send", "send_image"}:
            if operation == 'send_image':
                from .outgoing_images import image_from_wire
                intent = connector.prepare_image(request['conversation'], image_from_wire(request['image']))
            else:
                intent = connector.prepare_send(request["conversation"], request["text"])
            connector.send_confirmed(intent["id"])
            key = "message:" + canonical(request["conversation"]) + ":" + intent["id"]
            message = connector.store.get(key)
            if not message or message.get("verified") is not True:
                raise AppError("X_SEND_UNKNOWN")
            emit({"type": "result", "encrypted": True, "message": message})
        else:
            deadline = time.monotonic() + timeout if timeout else None
            first = True
            while deadline is None or time.monotonic() < deadline:
                started = time.monotonic()
                result = history_payload(connector, request["conversation"], limit)
                if not first and not result["caught_up"]:
                    raise AppError("X_HISTORY_INCOMPLETE")
                emit(result)
                if read_ack() != {"history_saved": True}:
                    raise AppError("X_PROTOCOL_ERROR")
                emit({"type": "status", "code": "connected"})
                first = False
                connector.bridge.call("listen")
                # Socket bootstrap/control hints must not create a busy poll loop.
                remaining = 2 - (time.monotonic() - started)
                if remaining > 0:
                    time.sleep(remaining)
            emit({"type": "done"})
    finally:
        connector.close()


def main():
    if sys.stdin.isatty() or sys.stdout.isatty():
        return 2
    logging.disable(logging.CRITICAL)
    disable_core_dumps()
    os.umask(0o077)
    def terminate(*_):
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, terminate)
    try:
        request = read()
        private_directory(STATE_DIR.parent)
        with instance_lock(STATE_DIR):
            run(request)
        return 0
    except AppError as exc:
        code = exc.code
    except ConnectorError as exc:
        code = ERROR_MAP.get(str(exc), "X_PROTOCOL_ERROR")
    except KeychainStatusError as exc:
        code = failure_code(exc)
    except Exception:
        code = "X_REQUEST_FAILED"
    write({"type": "error", "code": code})
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
