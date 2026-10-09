"""X-only adapter: verified crypto, private process channel, encrypted persistence."""
from __future__ import annotations

import base64
import contextlib
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import resource
import selectors
import sqlite3
import stat
import subprocess
import sys
import time
import uuid

from chat_xdk import Chat
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = Path.home() / "Library" / "Application Support" / "BeeperLocalXIntegration" / "adapter"
SERVICE = "local.beeperlocal.xconnector.v1"
KEYCHAIN_ACCOUNT = "primary"
MAX_FRAME = 16 * 1024 * 1024


class ConnectorError(Exception):
    """Only fixed, non-secret public codes are allowed."""


def fail(code):
    raise ConnectorError(code)


def canonical(value):
    if isinstance(value, str) and re.fullmatch(r"g[0-9]{1,128}", value):
        return value
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+[:-][0-9]+", value):
        fail("direct_conversation_required")
    a, b = re.split("[:-]", value)
    if a == b:
        fail("direct_conversation_required")
    return f"{a}:{b}"


def participant_pair(conversation, own):
    pair = canonical(conversation).split(":")
    if own not in pair:
        fail("account_scope_mismatch")
    return pair


def conversation_members(conversation, own, detail=None, *, history=False):
    conv = canonical(conversation)
    if not conv.startswith('g'):
        return participant_pair(conv, own)
    detail = detail or {}
    if canonical(detail.get('conversation_id')) != conv:
        fail('message_scope_mismatch')
    fields = ('participants_results', 'group_members_results', 'group_admins_results')
    active = {r.get('rest_id') for field in fields for r in detail.get(field, []) if isinstance(r, dict)}
    if own not in active:
        fail('account_scope_mismatch')
    members = active | ({r.get('rest_id') for r in detail.get('group_removed_users', []) if isinstance(r, dict)} if history else set())
    if not members or len(members) > 2000 or any(not isinstance(m, str) or not re.fullmatch(r'[0-9]{1,128}', m) for m in members):
        fail('message_scope_mismatch')
    return sorted(members)


def private_dir(path):
    path = Path(path)
    if path.is_symlink():
        fail("unsafe_storage_path")
    path.mkdir(mode=0o700, parents=False, exist_ok=True)
    st = path.stat()
    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid():
        fail("unsafe_storage_path")
    path.chmod(0o700)
    return path


@contextlib.contextmanager
def instance_lock(path):
    directory = private_dir(path)
    fd = os.open(directory / "instance.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        if os.fstat(fd).st_nlink != 1:
            fail("unsafe_storage_path")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            fail("already_running")
        yield directory
    finally:
        os.close(fd)


class Store:
    """HMAC indexes + AES-GCM payloads: no account, cursor, text or key plaintext."""
    def __init__(self, directory, key):
        if len(key) != 32:
            fail("storage_key_invalid")
        self.key, self.aes = key, AESGCM(key)
        directory = private_dir(directory)
        self.path = directory / "history.sqlite3"
        for suffix in ("", "-journal", "-wal", "-shm"):
            p = Path(str(self.path) + suffix)
            if p.is_symlink() or (p.exists() and (not p.is_file() or p.stat().st_nlink != 1)):
                fail("unsafe_storage_path")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.fchmod(fd, 0o600)
        os.close(fd)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        for pragma in ("journal_mode=DELETE", "synchronous=FULL", "secure_delete=ON",
                       "temp_store=MEMORY", "trusted_schema=OFF"):
            self.db.execute("PRAGMA " + pragma)
        self.db.execute("CREATE TABLE IF NOT EXISTS records (k BLOB PRIMARY KEY, v BLOB NOT NULL)")
        check_id = hashlib.sha256(b"x-store-keycheck-v1").digest()
        check = self.db.execute("SELECT v FROM records WHERE k=?", (check_id,)).fetchone()
        if check is None:
            if self.db.execute("SELECT count(*) FROM records").fetchone()[0]:
                self.db.close()
                fail("storage_integrity_failed")
            nonce = os.urandom(12)
            self.db.execute("INSERT INTO records VALUES (?,?)", (check_id, nonce + self.aes.encrypt(nonce, b"x-store-v1", check_id)))
        else:
            try:
                if self.aes.decrypt(check[0][:12], check[0][12:], check_id) != b"x-store-v1":
                    raise ValueError()
            except Exception:
                self.db.close()
                fail("storage_integrity_failed")

    def index(self, key):
        return hmac.digest(self.key, b"x-index-v1\0" + key.encode(), "sha256")

    def get(self, key, default=None):
        idx = self.index(key)
        row = self.db.execute("SELECT v FROM records WHERE k=?", (idx,)).fetchone()
        if row is None:
            return default
        raw = row[0]
        try:
            return json.loads(self.aes.decrypt(raw[:12], raw[12:], b"x-record-v1\0" + idx))
        except Exception:
            fail("storage_integrity_failed")

    def put(self, key, value):
        idx, nonce = self.index(key), os.urandom(12)
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
        encrypted = nonce + self.aes.encrypt(nonce, raw, b"x-record-v1\0" + idx)
        self.db.execute("INSERT INTO records VALUES (?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (idx, encrypted))

    @contextlib.contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self):
        self.db.close()

    def clear_message_data(self):
        # Key envelopes/key floors (lists/numbers) and account binding survive.
        # Every dict holds content, catalog, cursor or a send intent. Retired
        # intents keep their original HMAC index but no body or recipient.
        check_id = hashlib.sha256(b'x-store-keycheck-v1').digest()
        with self.transaction():
            for idx, raw in self.db.execute('SELECT k,v FROM records').fetchall():
                if idx == check_id: continue
                try: value = json.loads(self.aes.decrypt(raw[:12], raw[12:], b'x-record-v1\0' + idx))
                except Exception: fail('storage_integrity_failed')
                if not isinstance(value, dict): continue
                if 'state' in value:
                    nonce = os.urandom(12)
                    encrypted = nonce + self.aes.encrypt(nonce, b'{"state":"retired"}', b'x-record-v1\0' + idx)
                    self.db.execute('UPDATE records SET v=? WHERE k=?', (encrypted, idx))
                else:
                    self.db.execute('DELETE FROM records WHERE k=?', (idx,))


class Bridge:
    def __init__(self, executable=None):
        if executable is None:
            executable = (Path(sys.executable).parent / "beeperlocal-x" if getattr(sys, "frozen", False)
                          else ROOT / "bin/beeperlocal-x")
        # Prevent inherited debugging/env settings from enabling third-party logs.
        env = {"PATH": "/usr/bin:/bin", "LANG": "en_US.UTF-8", "GOTRACEBACK": "none"}
        self.proc = subprocess.Popen([str(executable)], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                     env=env, bufsize=0, close_fds=True)
        self.buffer = bytearray()
        self.selector = selectors.DefaultSelector()
        self.selector.register(self.proc.stdout, selectors.EVENT_READ)

    def call(self, op, **kwargs):
        raw = json.dumps({"op": op, **kwargs}, separators=(",", ":")).encode() + b"\n"
        if len(raw) > MAX_FRAME:
            fail("request_too_large")
        try:
            # BufferedWriter is not used; write all bytes even for large histories.
            remaining = memoryview(raw)
            while remaining:
                n = os.write(self.proc.stdin.fileno(), remaining)
                remaining = remaining[n:]
            deadline = time.monotonic() + 65
            while b"\n" not in self.buffer:
                timeout = deadline - time.monotonic()
                if timeout <= 0 or not self.selector.select(timeout):
                    self.close()
                    fail("bridge_timeout")
                chunk = os.read(self.proc.stdout.fileno(), 65536)
                if not chunk:
                    fail("bridge_closed")
                self.buffer.extend(chunk)
                if len(self.buffer) > MAX_FRAME:
                    self.close()
                    fail("response_too_large")
            line, _, rest = self.buffer.partition(b"\n")
            self.buffer = bytearray(rest)
            result = json.loads(line)
            if result.get("ok") is not True:
                code = result.get("error")
                allowed = {"interactive_challenge_required", "reauth_required", "invalid_request",
                           "network_timeout", "x_request_failed", "response_too_large"}
                fail(code if code in allowed else "bridge_protocol_failed")
            return result["result"]
        except ConnectorError:
            raise
        except Exception:
            self.close()
            fail("bridge_protocol_failed")

    def close(self):
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        self.selector.close()
        self.proc.stdin.close()
        self.proc.stdout.close()


def public_records(response):
    out = {}
    for user in response.get("data", {}).get("user_results_by_rest_ids", []):
        uid = user.get("rest_id")
        rows = user.get("result", {}).get("get_public_keys", {}).get("public_keys_with_token_map", [])
        if uid:
            out[uid] = rows
    return out


def signing_records(records, expected):
    out = []
    for uid in expected:
        for row in records.get(uid, []):
            metadata = row.get("public_key_with_metadata", {})
            key = metadata.get("public_key", {})
            if all(key.get(x) for x in ("public_key", "signing_public_key", "identity_public_key_signature")):
                out.append({"user_id": uid, "public_key_version": metadata["version"],
                            "public_key": key["signing_public_key"],
                            "identity_public_key": key["public_key"],
                            "identity_public_key_signature": key["identity_public_key_signature"]})
    if {r["user_id"] for r in out} != set(expected):
        fail("signing_keys_missing")
    return out


def same_signing_public_key(local_b64, registered_b64):
    """Compare P-256 points, not SEC1-vs-SPKI base64 representations.

    chatxdk.get_public_keys() returns a raw SEC1 point; X's registration
    endpoint returns a DER SubjectPublicKeyInfo container for the same key.
    Parsing both via the crypto library preserves curve/key checks.
    """
    def decode(value):
        raw = base64.b64decode(value, validate=True)
        if len(raw) in (33, 65) and raw[0] in (2, 3, 4):
            key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), raw)
        else:
            key = serialization.load_der_public_key(raw)
        if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
            raise ValueError()
        return key.public_numbers()
    try:
        return decode(local_b64) == decode(registered_b64)
    except (ValueError, TypeError):
        return False


def verified_messages(events, conversation, own, members=None):
    """Backend sequence/time are metadata, never the authenticated identity."""
    conv = canonical(conversation)
    members = members or participant_pair(conv, own)
    if own not in members: fail('account_scope_mismatch')
    messages = []
    for event in events:
        if event.get("type") not in {"Message", "KeyChange"}:
            continue
        if event.get("verified") is not True:
            fail("signature_verification_failed")
        if canonical(event.get("conversation_id")) != conv or event.get("sender_id") not in members:
            fail("message_scope_mismatch")
        if event["type"] != "Message":
            continue
        try:
            signed_id = str(uuid.UUID(event["id"]))
        except (KeyError, ValueError, TypeError, AttributeError):
            fail("signed_message_id_missing")
        # Text (including empty captions) and its verified attachments only.
        content = event.get("content", {})
        if content.get("content_type") != "Text":
            continue
        text = content.get("text")
        if not isinstance(text, str):
            fail("message_shape_invalid")
        if event.get("ttl_msec") is not None:
            # Disappearing messages need a retention scheduler; don't retain them.
            continue
        attachments = []
        for attachment in event.get('attachments', []):
            if attachment.get('attachment_type') != 'Media':
                continue
            kind = {'image':'image', 'gif':'image', 'video':'video', 'audio':'audio'}.get(attachment.get('media_type'), 'file')
            item = {'kind': kind, 'name': attachment.get('filename') or ''}
            media_hash = attachment.get('media_hash_key')
            if media_hash:
                if not re.fullmatch(r'[a-zA-Z0-9_-]{1,1024}', media_hash): fail('message_shape_invalid')
                item.update(media_hash_key=media_hash, key_version=event.get('key_version') or '')
            elif attachment.get('legacy_media_url_https'):
                item['url'] = attachment['legacy_media_url_https']
            else:
                continue
            attachments.append(item)
        if len(attachments) > 20: fail('message_shape_invalid')
        messages.append({"attachments": attachments, "provider": "x", "account_id": own,
                         "conversation_id": "xchat:" + conv,
                         "provider_message_id": signed_id,
                         "sender_id": event["sender_id"],
                         "direction": "self" if event["sender_id"] == own else "peer",
                         "text": text, "verified": True,
                         "sequence_id": event.get("sequence_id"),
                         "created_at_msec": event.get("created_at_msec")})
    return messages


def deletion_rules(events, conversation, own, members):
    result = []
    for event in events:
        if event.get('type') != 'MessageDeleted': continue
        if event.get('verified') is not True or canonical(event.get('conversation_id')) != canonical(conversation) or event.get('sender_id') not in members:
            fail('signature_verification_failed')
        sequences = event.get('message_ids')
        if type(event.get('delete_for_all')) is not bool or not isinstance(sequences, list) or len(sequences) > 1000 or any(not isinstance(v,str) or not re.fullmatch(r'[0-9]{1,128}',v) for v in sequences):
            fail('message_shape_invalid')
        if event['delete_for_all'] or event['sender_id'] == own:
            result.append({'actor':event['sender_id'], 'sequences':sequences, 'all':event['delete_for_all']})
    return result


def legacy_identity(value):
    if not isinstance(value, str):
        fail("message_shape_invalid")
    if value.isascii() and value.isdigit() and 1 <= len(value) <= 128:
        return "legacy:" + value
    try:
        return "legacy:" + str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        fail("message_shape_invalid")


def legacy_message(shape, conv, own, members=None):
    if canonical(shape.get("conversation")) != conv:
        fail("message_scope_mismatch")
    content = shape.get("legacy", {})
    if content.get("status") != "text":
        return None
    sender, stamp, text = content.get("sender_id"), content.get("created_at_msec"), content.get("text")
    if sender not in (members or participant_pair(conv, own)):
        fail("message_scope_mismatch")
    if (not isinstance(stamp, str) or not stamp.isascii() or not stamp.isdigit()
            or not 0 < int(stamp) < 253402300800000 or not isinstance(text, str) or not text):
        fail("message_shape_invalid")
    return {"provider": "x", "account_id": own, "conversation_id": "xchat:" + conv,
            "provider_message_id": legacy_identity(shape.get("message_id")), "sender_id": sender,
            "direction": "self" if sender == own else "peer", "text": text,
            "verified": False, "source": "legacy", "created_at_msec": int(stamp),
            "sequence_id": shape.get("sequence")}


class Connector:
    def __init__(self, keychain, bridge, directory=STATE_DIR):
        self.keychain, self.bridge, self.directory = keychain, bridge, directory
        self.credentials = None
        self.store = None
        self.chat = None
        self.keys = {}
        self.own = None

    def read_credentials(self):
        raw = self.keychain.get_password(SERVICE, KEYCHAIN_ACCOUNT)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            fail("credential_shape_invalid")

    def save_credentials(self):
        self.keychain.set_password(SERVICE, KEYCHAIN_ACCOUNT, json.dumps(self.credentials, separators=(",", ":")))

    def persist_session(self):
        self.credentials.update(self.bridge.call("session"))
        self.save_credentials()

    def open_store(self):
        self.own = self.credentials["user"]
        if not re.fullmatch(r"[0-9]+", self.own):
            fail("account_scope_mismatch")
        self.store = Store(self.directory, base64.b64decode(self.credentials["database_key"], validate=True))
        stored = self.store.get("account")
        if stored is not None and stored != self.own:
            fail("account_scope_mismatch")
        self.store.put("account", self.own)

    def login(self, ask):
        if self.chat:
            self.chat.lock()
        self.chat = None
        previous = self.read_credentials()
        result = self.bridge.call("login_start")
        for _ in range(12):
            status = result.get("status")
            if status == "complete":
                break
            fields = {"needs_identifier": "identifier", "needs_password": "password",
                      "needs_text": "text", "needs_auth_method": "method"}
            if status not in fields:
                fail("interactive_challenge_required")
            value = ask(fields[status], result)
            if not value:
                fail("cancelled")
            result = self.bridge.call("login_answer", field=fields[status], value=value)
            value = None
        else:
            fail("login_steps_exceeded")
        profile = self.bridge.call("profile")
        if previous and previous["user"] != profile["user"]:
            fail("account_scope_mismatch")
        self.credentials = previous or {"database_key": base64.b64encode(os.urandom(32)).decode()}
        self.credentials.update(self.bridge.call("session"))
        self.credentials["profile"] = profile
        self.save_credentials()
        self.open_store()
        return profile

    def login_browser(self, acquire_session):
        if self.chat:
            self.chat.lock()
        self.chat = None
        previous = self.read_credentials()
        # Session comes only from the user-operated ephemeral helper, never from
        # another browser's profiles or arbitrary pasted input.
        cookie = acquire_session()
        profile = self.bridge.call("web_login", cookies=cookie, user=previous["user"] if previous else "")
        cookie = None
        if previous and previous["user"] != profile["user"]:
            fail("account_scope_mismatch")
        self.credentials = previous or {"database_key": base64.b64encode(os.urandom(32)).decode()}
        self.credentials.update(self.bridge.call("session"))
        self.credentials["profile"] = profile
        self.save_credentials()
        self.open_store()
        return profile

    def resume(self):
        if self.chat:
            self.chat.lock()
        self.chat = None
        self.credentials = self.read_credentials()
        if not self.credentials:
            fail("login_required")
        profile = self.bridge.call("restore", cookies=self.credentials["cookies"],
                                   session=self.credentials["session"], user=self.credentials["user"])
        self.credentials["profile"] = profile
        self.persist_session()
        self.open_store()
        return profile

    def unlock(self, ask_pin=None):
        if self.chat:
            self.chat.lock()
        self.chat = None
        records = public_records(self.bridge.call("keys", users=[self.own]))
        rows = records.get(self.own, [])
        if not rows:
            fail("x_chat_setup_required")
        stored_version = self.credentials.get("key_version")
        if self.credentials.get("identity_keys"):
            matching = [r for r in rows if r["public_key_with_metadata"]["version"] == stored_version]
            if not matching:
                fail("key_rotation_requires_login")
            row = matching[0]
            chat = Chat()
            chat.import_keys(base64.b64decode(self.credentials["identity_keys"], validate=True), version=stored_version)
        else:
            if ask_pin is None:
                fail("chat_pin_required")
            # Exactly one explicit PIN attempt. Never setup/delete/re-register keys.
            rows = sorted(rows, key=lambda r: int(r["public_key_with_metadata"]["version"]), reverse=True)
            row = rows[0]
            chat = Chat(json.dumps(row["token_map"]))
            pin = ask_pin()
            try:
                chat.unlock(pin)
            except Exception:
                fail("chat_pin_unlock_failed")
            finally:
                pin = None
        metadata = row["public_key_with_metadata"]
        key = metadata["public_key"]
        try:
            identity_matches = chat.matches_registered_key(key["public_key"])
            signing_matches = same_signing_public_key(chat.get_public_keys().signing, key["signing_public_key"])
        except Exception:
            identity_matches = signing_matches = False
        if not identity_matches or not signing_matches:
            chat.lock()
            fail("identity_key_mismatch")
        try:
            binding_verified = chat.verify_key_binding(key["public_key"], key["signing_public_key"], key["identity_public_key_signature"])
        except Exception:
            binding_verified = False
        if binding_verified is not True:
            chat.lock()
            fail("identity_binding_failed")
        chat.set_identity(self.own, metadata["version"])
        chat.set_reject_unverified(True)
        chat.set_cache_keys(True)
        self.credentials["identity_keys"] = base64.b64encode(chat.export_keys()).decode()
        self.credentials["key_version"] = metadata["version"]
        self.save_credentials()
        self.chat = chat
        self.keys.update(records)

    def conversations(self, max_pages=100):
        cursor = None
        items, seen = [], set()
        complete = False
        for _ in range(max_pages):
            page = self.bridge.call("inbox", **({"cursor": cursor} if cursor else {}))
            for item in page.get("items", []):
                detail = item.get("conversation_detail", {})
                raw = detail.get("conversation_id", "")
                try:
                    conv = canonical(raw)
                    members = conversation_members(conv, self.own, detail, history=True)
                except ConnectorError:
                    continue  # Non-message or inaccessible conversation.
                if conv in seen:
                    continue
                peer = next((x for x in members if x != self.own), self.own)
                name = (detail.get('group_metadata') or {}).get('group_name') or 'Xグループ' if conv.startswith('g') else peer
                for user in detail.get("participants_results", []):
                    if not conv.startswith("g") and user.get("rest_id") == peer:
                        core = (user.get("result") or {}).get("core") or {}
                        name = core.get("screen_name") or core.get("name") or peer
                items.append({"id": conv, "raw_id": raw, "peer": peer, "name": name, "kind": "group" if conv.startswith("g") else "dm", "members": members})
                self.store.put("inbox-item:" + conv, item)
                seen.add(conv)
            c = page.get("inboxCursor", {})
            if c.get("pull_finished") is True:
                complete = True
                break
            next_cursor = {"cursor_id": c.get("cursor_id", ""), "graph_snapshot_id": c.get("graph_snapshot_id", "")}
            if not next_cursor["cursor_id"] or next_cursor == cursor:
                break
            cursor = next_cursor
        self.store.put("catalog", {"items": items, "complete": complete})
        self.persist_session()
        return {"items": items, "complete": complete}

    def _commit(self, conv, messages, key_events, token, checkpoint, rules=()):
        added = []
        with self.store.transaction():
            ids = self.store.get("messages:" + conv, [])
            prior_rules = self.store.get('delete-events:' + conv, [])
            for rule in rules:
                if rule not in prior_rules: prior_rules.append(rule)
            deleted = set(self.store.get('deleted:' + conv, []))
            candidates = [self.store.get('message:' + conv + ':' + mid) for mid in ids] + messages
            for msg in candidates:
                if msg and any(msg.get('sequence_id') in rule['sequences'] and (not rule['all'] or msg['sender_id'] == rule['actor']) for rule in prior_rules):
                    deleted.add(msg['provider_message_id'])
            self.store.put('delete-events:' + conv, prior_rules)
            self.store.put('deleted:' + conv, sorted(deleted))
            for mid in deleted:
                self.store.db.execute('DELETE FROM records WHERE k=?', (self.store.index('message:' + conv + ':' + mid),))
            ids = [mid for mid in ids if mid not in deleted]
            for msg in messages:
                if msg['provider_message_id'] in deleted: continue
                mid = msg["provider_message_id"]
                key = "message:" + conv + ":" + mid
                previous = self.store.get(key)
                if previous is not None:
                    if any(previous[k] != msg[k] for k in ("text", "sender_id", "account_id", "conversation_id")):
                        fail("signed_id_conflict")
                    continue
                self.store.put(key, msg)
                if mid not in ids: ids.append(mid)
                added.append(msg)
            self.store.put("messages:" + conv, ids)
            # These are encrypted signed key-change envelopes, not private keys.
            old_keys = self.store.get("key-events:" + conv, [])
            self.store.put("key-events:" + conv, list(dict.fromkeys(old_keys + key_events)))
            if token:
                self.store.put("token:" + conv, token)
            self.store.put("checkpoint:" + conv, checkpoint)
        return added

    def history(self, conversation, max_pages=3, before_cursor=None):
        if self.chat is None:
            fail("chat_pin_required")
        conv = canonical(conversation)
        detail = self.bridge.call("detail", conversation=conversation)
        members = conversation_members(conv, self.own, detail.get("conversation_detail"), history=True)
        self.store.put("members:" + conv, members)
        if canonical(detail.get("conversation_detail", {}).get("conversation_id")) != conv:
            fail("message_scope_mismatch")
        raw_keys = list(dict.fromkeys(self.store.get("key-events:" + conv, []) + detail.get("latest_conversation_key_change_events", [])))
        raw = [] if before_cursor else list(detail.get("latest_message_events", [])) + detail.get("encoded_message_events", [])
        if before_cursor is not None and not re.fullmatch(r"[0-9]{1,128}", before_cursor): fail("bridge_protocol_failed")
        before = before_cursor or ""
        known = set(self.store.get("messages:" + conv, []))
        candidate_anchor = False
        complete = False
        for _ in range(max_pages):
            page = self.bridge.call("conversation", conversation=conversation, before=before)
            batch = page.get("encoded_message_events", [])
            raw.extend(batch)
            raw_keys.extend(page.get("missing_conversation_key_change_events", []))
            if page.get("has_more") is not True:
                complete = True
                break
            meta = self.bridge.call("inspect", events=batch) if batch else []
            if not before_cursor and any(x.get("message_id") in known or "legacy:" + str(x.get("message_id")) in known for x in meta):
                candidate_anchor = True
            seqs = [int(x["sequence"]) for x in meta if isinstance(x.get("sequence"), str) and x["sequence"].isdigit()]
            if not seqs or str(min(seqs)) == before:
                fail("history_pagination_stalled")
            before = str(min(seqs))
            if candidate_anchor: break
        raw_keys = list(dict.fromkeys(raw_keys))
        raw = list(dict.fromkeys(raw_keys + raw))
        raw_count = len(raw)
        if not raw:
            return {"added": [], "messages": [], "complete": complete, "caught_up": complete,
                    "raw_count": 0, "count": 0, "unsupported_legacy_count": 0, "legacy_message_count": 0}
        if len(raw) > 3000:
            fail("history_limit_exceeded")
        meta = self.bridge.call("inspect", events=raw)
        if len(meta) != len(raw):
            fail("bridge_protocol_failed")
        # Only envelopes with neither signature nor encryption marker enter
        # the legacy parser. Their IDs and provenance stay separate from Chat.
        unsupported_legacy = 0
        supported, legacy, legacy_ids = [], [], set()
        for encoded, shape in zip(raw, meta):
            if (shape.get("kind") == "message" and shape.get("encrypted") is False
                    and shape.get("signature_present") is False):
                if canonical(shape.get("conversation")) != conv:
                    fail("message_scope_mismatch")
                if shape.get("message_id") in known:
                    fail("signature_or_decryption_failed")
                row = legacy_message(shape, conv, self.own, members)
                if row is None:
                    unsupported_legacy += 1
                else:
                    legacy.append(row)
                    legacy_ids.add(row["provider_message_id"][7:])
            else:
                supported.append(encoded)
        raw = supported
        result = {"messages": [], "errors": []}
        if raw:
            records = public_records(self.bridge.call("keys", users=members))
            signing = signing_records(records, members)
            self.chat.set_signing_keys(signing)
            result = self.chat.decrypt_events(raw, signing)
        if result.get("errors"):
            # A valid subset must not advance history or send with new keys.
            self.chat.lock()
            self.chat = None
            fail("signature_or_decryption_failed")
        events = [m["event"] for m in result.get("messages", [])]
        try:
            messages = verified_messages(events, conv, self.own, members)
            if legacy_ids.intersection(known) or legacy_ids.intersection(m["provider_message_id"] for m in messages):
                fail("signature_or_decryption_failed")
            messages += legacy
        except Exception:
            self.chat.lock()
            self.chat = None
            raise
        caught_up = complete or (candidate_anchor and any(m["provider_message_id"] in known for m in messages))
        # Retain every verified key envelope, including ones embedded in history.
        raw_keys = [m["original_b64"] for m in result.get("messages", [])
                    if m["event"].get("type") == "KeyChange" and m["event"].get("verified") is True]
        key_versions = [int(e["key_version"]) for e in events if e.get("type") == "KeyChange" and e.get("verified") is True and str(e.get("key_version", "")).isdigit()]
        high = max(key_versions, default=0)
        floor = self.store.get("key-floor:" + conv, 0)
        if raw and high < floor:
            fail("conversation_key_rollback")
        meta = self.bridge.call("inspect", events=raw)
        token = next((x["token"] for x in reversed(meta) if x.get("token") and canonical(x["conversation"]) == conv), None)
        # Unsupported legacy attachments/control events remain excluded.
        exhausted = complete
        complete = complete and unsupported_legacy == 0
        added = self._commit(conv, messages, raw_keys, token, {"before": before, "complete": complete,
                              "unsupported_legacy_count": unsupported_legacy}, rules=deletion_rules(events, conv, self.own, members))
        self.store.put("key-floor:" + conv, max(floor, high))
        self.persist_session()
        # The same legacy identity may arrive in direct and wrapped envelopes.
        # _commit has checked every copy for conflicts before deduplication.
        unique = {}
        for message in messages:
            unique.setdefault(message["provider_message_id"], message)
        messages = list(unique.values())
        return {"added": added, "messages": messages, "raw_count": raw_count,
                "complete": complete, "caught_up": caught_up, "next_before": None if exhausted else before, "count": len(messages),
                "deletions": self.store.get("deleted:" + conv, []), "unsupported_legacy_count": unsupported_legacy, "legacy_message_count": sum(m.get("source") == "legacy" for m in messages)}

    def messages(self, conversation):
        conv = canonical(conversation)
        rows = [self.store.get("message:" + conv + ":" + mid) for mid in self.store.get("messages:" + conv, [])]
        return sorted([row for row in rows if row], key=lambda m: (m.get("created_at_msec") or 0, m["provider_message_id"]))

    def download_attachment(self, conversation, message_id, index):
        conv = canonical(conversation)
        if not isinstance(message_id, str) or type(index) is not int or not 0 <= index < 20:
            fail('message_shape_invalid')
        saved = self.store.get('message:' + conv + ':' + message_id)
        if not saved or saved.get('verified') is not True or saved.get('account_id') != self.own or saved.get('conversation_id') != 'xchat:' + conv:
            fail('message_scope_mismatch')
        attachments = saved.get('attachments', [])
        if index >= len(attachments): fail('message_shape_invalid')
        attachment = attachments[index]
        if not attachment.get('media_hash_key'): fail('message_shape_invalid')
        detail = self.bridge.call('detail', conversation=conversation)
        members = conversation_members(conv, self.own, detail.get('conversation_detail'), history=True)
        if canonical(detail.get('conversation_detail', {}).get('conversation_id')) != conv:
            fail('message_scope_mismatch')
        signing = signing_records(public_records(self.bridge.call('keys', users=members)), members)
        self.chat.set_signing_keys(signing)
        # Every cached key envelope was originally verified before persistence,
        # and is verified again against identity-bound signing keys here.
        result = self.chat.decrypt_events(self.store.get('key-events:' + conv, []), signing)
        if result.get('errors'): fail('signature_or_decryption_failed')
        raw_key = result.get('conversation_keys', {}).get('keys', {}).get(attachment['key_version'])
        if not isinstance(raw_key, (bytes, list)) or len(raw_key) != 32: fail('signature_or_decryption_failed')
        encrypted = self.bridge.call('media', conversation=conversation, media_hash=attachment['media_hash_key'])
        ciphertext = base64.b64decode(encrypted['data'], validate=True)
        if len(ciphertext) > 4 * 1024 * 1024 + 65536: fail('message_shape_invalid')
        # decrypt_stream verifies authentication and the final frame (truncation).
        plaintext = self.chat.decrypt_stream(ciphertext, bytes(raw_key))
        if len(plaintext) > 4 * 1024 * 1024: fail('message_shape_invalid')
        return plaintext

    def prepare_send(self, conversation, text):
        conv = canonical(conversation)
        if not isinstance(text, str) or not text.strip() or len(text.encode()) > 10000:
            fail("invalid_message_text")
        self.history(conversation, max_pages=1)
        token = self.store.get("token:" + conv)
        if not token:
            fail("conversation_token_missing")
        payload = self.chat.encrypt_message(conv, text)
        intent = {"conversation": conversation, "canonical": conv, "text": text,
                  "message_id": payload.message_id, "token": token,
                  "content": payload.encrypted_content, "signature": payload.encoded_event_signature,
                  "state": "prepared"}
        self.store.put("send:" + payload.message_id, intent)
        return {"id": payload.message_id, "conversation": conv,
                "recipient": conv if conv.startswith("g") else next(x for x in participant_pair(conv, self.own) if x != self.own), "text": text}

    def prepare_image(self, conversation, image):
        conv = canonical(conversation)
        self.history(conversation, max_pages=1)
        token = self.store.get('token:' + conv)
        if not token: fail('conversation_token_missing')
        result = self.chat.decrypt_events(self.store.get('key-events:' + conv, []))
        if result.get('errors'): fail('signature_or_decryption_failed')
        events = [m['event'] for m in result.get('messages', [])]
        verified_messages(events, conv, self.own, self.store.get('members:' + conv))
        versions = [e.get('key_version') for e in events if e.get('type') == 'KeyChange' and str(e.get('key_version', '')).isdigit()]
        if not versions: fail('signature_or_decryption_failed')
        version = str(max(versions, key=int))
        if int(version) < self.store.get('key-floor:' + conv, 0): fail('conversation_key_rollback')
        key = result.get('conversation_keys', {}).get('keys', {}).get(version)
        if not isinstance(key, (bytes, list)) or len(key) != 32: fail('signature_or_decryption_failed')
        key = bytes(key)
        ciphertext = self.chat.encrypt_stream(image.data, key)
        # Upload id is separate from the subsequently SDK-generated, signed
        # message id, as in the XDK media flow. Persist before the first write.
        upload_id = str(uuid.uuid4())
        upload = {'conversation': conv, 'state': 'uploading', 'digest': image.digest}
        self.store.put('upload:' + upload_id, upload)
        try:
            result = self.bridge.call('upload_image', conversation=conversation, message_id=upload_id,
                                      data=base64.b64encode(ciphertext).decode())
            media_hash = result.get('media_hash_key')
            if not isinstance(media_hash, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,1024}', media_hash):
                fail('message_shape_invalid')
            attachment = {'attachment_type': 'media', 'media_hash_key': media_hash, 'width': image.width,
                          'height': image.height, 'filesize_bytes': len(image.data), 'filename': image.name,
                          'media_type': 1}
            payload = self.chat.encrypt_message(conv, '', conversation_key=key, conversation_key_version=version,
                                                attachments=[attachment])
            intent = {'conversation': conversation, 'canonical': conv, 'text': '', 'message_id': payload.message_id,
                      'token': token, 'content': payload.encrypted_content, 'signature': payload.encoded_event_signature,
                      'state': 'prepared', 'media_hash': media_hash, 'media_key_version': version}
            self.store.put('send:' + payload.message_id, intent)
            upload['state'] = 'uploaded'
            self.store.put('upload:' + upload_id, upload)
            return {'id': payload.message_id, 'conversation': conv, 'text': ''}
        except Exception:
            upload['state'] = 'unknown'
            self.store.put('upload:' + upload_id, upload)
            fail('send_outcome_unknown')

    def send_confirmed(self, intent_id):
        intent = self.store.get("send:" + intent_id)
        if not intent or intent["state"] != "prepared":
            fail("send_already_attempted")
        intent["state"] = "dispatching"
        self.store.put("send:" + intent_id, intent)  # durable before the POST
        try:
            reply = self.bridge.call("send", **{k: intent[k] for k in ("conversation", "message_id", "token", "content", "signature")})
            result = self.chat.decrypt_events([reply["event"]])
            if result.get("errors"):
                fail("send_ack_unverified")
            messages = verified_messages([m["event"] for m in result.get("messages", [])], intent["canonical"], self.own, self.store.get("members:" + intent["canonical"]))
            if len(messages) != 1 or messages[0]["provider_message_id"] != intent_id or messages[0]["sender_id"] != self.own or messages[0]["text"] != intent["text"]:
                fail("send_ack_mismatch")
            if intent.get('media_hash'):
                attachments = messages[0].get('attachments', [])
                if len(attachments) != 1 or attachments[0].get('kind') != 'image' or attachments[0].get('media_hash_key') != intent['media_hash'] or attachments[0].get('key_version') != intent['media_key_version']:
                    fail('send_ack_mismatch')
            self._commit(intent["canonical"], messages, [], None, self.store.get("checkpoint:" + intent["canonical"], {}))
            intent["state"] = "sent_verified"
        except Exception:
            intent["state"] = "unknown"
            self.store.put("send:" + intent_id, intent)
            fail("send_outcome_unknown")
        self.store.put("send:" + intent_id, intent)
        self.persist_session()
        return intent["state"]

    def watch(self, conversation, callback, stop=lambda: False):
        # Scan immediately, then after each socket hint/40-second timer. A socket
        # failure is surfaced; no infinite retry storm or false healthy status.
        first = True
        while not stop():
            result = self.history(conversation)
            callback(result)
            if not first and not result.get("caught_up", result["complete"]):
                fail("history_window_incomplete")
            first = False
            self.bridge.call("listen")

    def close(self):
        if self.chat:
            self.chat.lock()
        if self.store:
            self.store.close()
        self.bridge.close()


def disable_core_dumps():
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
