import base64
import copy
import json
import os
from pathlib import Path
import socket
import struct
import tempfile
import unittest
from unittest.mock import patch

from chat_xdk import Chat
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from beeperlocal.xcrypto.core import (Bridge, Connector, ConnectorError, Store, ROOT,
                            canonical, verified_messages, signing_records,
                            same_signing_public_key)

V = json.loads((ROOT / "tests/fixtures/x_sdk_vectors.json").read_text())
CONV = V["event_conversation_id"]
SELF = V["event_sender_id"]
PEER = next(x for x in CONV.split(":") if x != SELF)
SIGNING = [{"user_id": SELF, "public_key_version": V["event_signing_key_version"],
            "public_key": V["signing_public_b64"],
            "identity_public_key": V["identity_public_b64"],
            "identity_public_key_signature": V["identity_public_key_signature_b64"]}]


def chat():
    c = Chat()
    c.import_keys(base64.b64decode(V["private_keys_concat_b64"]), version=V["event_recipient_key_version"])
    c.set_identity(SELF, V["event_signing_key_version"])
    c.set_cache_keys(True)
    c.set_signing_keys(SIGNING)
    return c


def events():
    r = chat().decrypt_events([V["event_key_change_b64"], V["event_message_b64"]])
    assert not r["errors"]
    return [m["event"] for m in r["messages"]]


def spki(raw_b64):
    key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), base64.b64decode(raw_b64))
    return base64.b64encode(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()


def synthetic_legacy_event(*, encrypted=False, signed=False, conversation=CONV,
                           message_id="00000000-0000-4000-8000-000000000001",
                           sender=SELF, wrapped=False, malformed=False, ttl=None, body="synthetic legacy content"):
    def string(field, value):
        raw = value.encode() if isinstance(value, str) else value
        return struct.pack(">bhi", 11, field, len(raw)) + raw
    text = string(1, body) + b"\0"
    if wrapped:
        text = struct.pack(">bhbh", 12, 1, 12, 1) + text + b"\0\0"
    content = string(100, b"invalid thrift" if malformed else text)
    if ttl is not None:
        content += struct.pack(">bhq", 10, 103, ttl)
    if encrypted:
        content += string(101, "1")
    detail = struct.pack(">bh", 12, 1) + content + b"\0\0"
    raw = string(1, "999") + string(2, message_id) + string(3, sender) + string(4, conversation) + string(6, "1790812345000")
    raw += struct.pack(">bh", 12, 7) + detail
    if signed:
        raw += struct.pack(">bh", 12, 9) + string(1, "invalid") + string(2, "1") + b"\0"
    return base64.b64encode(raw + b"\0").decode()


class RegisteredKeyTests(unittest.TestCase):
    def test_same_point_raw_and_registered_spki_match(self):
        raw = chat().get_public_keys().signing
        registered = spki(raw)
        self.assertNotEqual(raw, registered)  # Reproduces the old false mismatch.
        self.assertTrue(same_signing_public_key(raw, registered))
        self.assertTrue(same_signing_public_key(registered, raw))
        self.assertTrue(same_signing_public_key(raw, raw))

    def test_different_point_or_curve_rejected(self):
        raw = chat().get_public_keys().signing
        different = ec.generate_private_key(ec.SECP256R1()).public_key()
        different_curve = ec.generate_private_key(ec.SECP384R1()).public_key()
        for key in (different, different_curve):
            registered = base64.b64encode(key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
            self.assertFalse(same_signing_public_key(raw, registered))

    def test_malformed_registration_rejected(self):
        raw = chat().get_public_keys().signing
        for invalid in (None, "", "invalid base64!", base64.b64encode(b"not DER").decode(),
                        base64.b64encode(b"\x04" + b"\x00" * 64).decode()):
            with self.subTest(kind=type(invalid).__name__):
                self.assertFalse(same_signing_public_key(raw, invalid))


class CryptoTests(unittest.TestCase):
    def test_real_sdk_decrypts_and_verifies_fixture(self):
        rows = verified_messages(events(), CONV, SELF)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["text"], V["event_message_text"])
        self.assertTrue(rows[0]["verified"])

    def test_modified_signed_id_rejected_by_crypto(self):
        raw = base64.b64decode(V["event_message_b64"])
        message_id = events()[1]["id"].encode()
        altered = raw.replace(message_id, b"0" + message_id[1:])
        r = chat().decrypt_events([V["event_key_change_b64"], base64.b64encode(altered).decode()])
        self.assertTrue(r["errors"])

    def test_unsigned_sequence_mutation_does_not_change_identity(self):
        raw = base64.b64decode(V["event_message_b64"])
        # Thrift field 1 (sequence) changed in place, preserving the signature.
        self.assertEqual(raw[:8], b"\x0b\x00\x01\x00\x00\x00\x011")
        changed = raw[:7] + b"9" + raw[8:]
        r = chat().decrypt_events([V["event_key_change_b64"], base64.b64encode(changed).decode()])
        self.assertFalse(r["errors"])
        rows = verified_messages([m["event"] for m in r["messages"]], CONV, SELF)
        original = verified_messages(events(), CONV, SELF)[0]
        self.assertEqual(rows[0]["provider_message_id"], original["provider_message_id"])
        self.assertNotEqual(rows[0]["sequence_id"], original["sequence_id"])

    def test_sender_and_conversation_and_strict_bool(self):
        for field, bad in [("sender_id", "3333"), ("conversation_id", "1111:3333"), ("verified", 1), ("id", None)]:
            event = events()[1]
            event[field] = bad
            with self.subTest(field=field), self.assertRaises(ConnectorError):
                verified_messages([event], CONV, SELF)

    def test_disappearing_and_control_messages_not_stored(self):
        event = events()[1]
        event["ttl_msec"] = 1000
        self.assertEqual(verified_messages([event], CONV, SELF), [])
        event["ttl_msec"] = None
        event["content"] = {"content_type": "ReactionAdd", "text": "not a message"}
        self.assertEqual(verified_messages([event], CONV, SELF), [])

    def test_missing_signing_keys_are_not_bypassed(self):
        r = chat().decrypt_events([V["event_key_change_b64"], V["event_message_b64"]], [])
        # An explicit empty list may fall back to the configured trusted store;
        # use a fresh Chat with no trust configuration for this check.
        c = Chat(); c.import_keys(base64.b64decode(V["private_keys_concat_b64"]), version="1")
        self.assertTrue(c.decrypt_events([V["event_key_change_b64"], V["event_message_b64"]])["errors"])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "state"
        self.key = os.urandom(32)
        self.store = Store(self.directory, self.key)
        self.connector = Connector(None, None, self.directory)
        self.connector.store = self.store
        self.connector.own = SELF

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_encrypted_reopen_and_no_plaintext(self):
        self.store.put("private-account", {"secret": "distinctive-message-body"})
        raw = self.store.path.read_bytes()
        self.assertNotIn(b"distinctive-message-body", raw)
        self.assertNotIn(b"private-account", raw)
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.store.close()
        self.store = Store(self.directory, self.key)
        self.assertEqual(self.store.get("private-account"), {"secret": "distinctive-message-body"})

    def test_tamper_and_wrong_key_fail_closed(self):
        self.store.put("a", {"v": 1})
        with self.assertRaisesRegex(ConnectorError, "storage_integrity_failed"):
            Store(self.directory, os.urandom(32))
        self.store.db.execute("UPDATE records SET v=randomblob(48)")
        with self.assertRaises(ConnectorError):
            self.store.get("a")

    def test_replayed_sequence_deduplicates_and_checkpoint_atomic(self):
        row = verified_messages(events(), CONV, SELF)[0]
        first = self.connector._commit(CONV, [row], [], None, {"before": "1"})
        changed = {**row, "sequence_id": "9999", "created_at_msec": 9999999}
        second = self.connector._commit(CONV, [changed], [], None, {"before": "2"})
        self.assertEqual((len(first), len(second)), (1, 0))
        self.assertEqual(len(self.connector.messages(CONV)), 1)
        with self.assertRaises(ConnectorError):
            self.connector._commit(CONV, [{**row, "text": "forged"}], [], None, {"before": "3"})
        self.assertEqual(self.store.get("checkpoint:" + CONV), {"before": "2"})

    def test_symlink_database_rejected(self):
        directory = Path(self.temp.name) / "unsafe"
        directory.mkdir()
        (directory / "history.sqlite3").symlink_to(self.store.path)
        with self.assertRaises(ConnectorError):
            Store(directory, self.key)

    def test_send_timeout_is_durable_unknown_and_never_retries(self):
        outer = self
        class FailedBridge:
            calls = 0
            def call(self, op, **kwargs):
                self.calls += 1
                outer.assertEqual(outer.store.get("send:draft")["state"], "dispatching")
                raise ConnectorError("bridge_timeout")
        bridge = FailedBridge()
        self.connector.bridge = bridge
        self.store.put("send:draft", {"state": "prepared", "conversation": CONV, "message_id": "draft",
                                      "token": "test", "content": "test", "signature": "test"})
        with self.assertRaisesRegex(ConnectorError, "send_outcome_unknown"):
            self.connector.send_confirmed("draft")
        self.assertEqual(self.store.get("send:draft")["state"], "unknown")
        with self.assertRaisesRegex(ConnectorError, "send_already_attempted"):
            self.connector.send_confirmed("draft")
        self.assertEqual(bridge.calls, 1)


class ProtocolTests(unittest.TestCase):
    def test_helper_hello_invalid_op_and_bounded_inspect(self):
        b = Bridge()
        try:
            self.assertEqual(b.call("hello")["protocol"], 1)
            with self.assertRaisesRegex(ConnectorError, "invalid_request"):
                b.call("send")
            metadata = b.call("inspect", events=[V["event_message_b64"]])
            self.assertEqual(metadata[0]["conversation"], CONV)
            self.assertEqual(metadata[0]["message_id"], events()[1]["id"])
            with self.assertRaisesRegex(ConnectorError, "invalid_request"):
                b.call("inspect", events=["malformed"])
            self.assertEqual(b.call("hello")["protocol"], 1)
        finally:
            b.close()

    def test_bad_protocol_never_exposes_received_text(self):
        with tempfile.TemporaryDirectory() as d:
            executable = Path(d) / "bad-helper"
            executable.write_text('#!/bin/sh\nread input\nprintf \'{"ok":false,"error":"PRIVATE_TOKEN"}\\n\'\n')
            executable.chmod(0o700)
            b = Bridge(executable)
            try:
                with self.assertRaisesRegex(ConnectorError, "bridge_protocol_failed"):
                    b.call("hello")
            finally:
                b.close()


class FakeKeychain:
    def __init__(self):
        self.value = None
    def get_password(self, service, account):
        return self.value
    def set_password(self, service, account, value):
        self.value = value


class FixtureBridge:
    def __init__(self):
        self.bad = False
        self.login_steps = []
    def call(self, op, **kwargs):
        if op == "login_start":
            return {"status": "needs_identifier"}
        if op == "login_answer":
            self.login_steps.append(kwargs["field"])
            return {"status": "needs_password" if kwargs["field"] == "identifier" else "complete"}
        if op in {"profile", "restore", "web_login"}:
            return {"user": SELF, "screen_name": "fixture"}
        if op == "session":
            return {"user": SELF, "cookies": "synthetic-test-cookie", "session": {}}
        if op == "keys":
            return {"data": {"user_results_by_rest_ids": [
                {"rest_id": uid, "result": {"get_public_keys": {"public_keys_with_token_map": [
                    {"public_key_with_metadata": {"version": "1", "public_key": {
                        "public_key": V["identity_public_b64"], "signing_public_key": V["signing_public_b64"],
                        "identity_public_key_signature": V["identity_public_key_signature_b64"]}}}
                ]}}} for uid in kwargs["users"]]}}
        if op == "detail":
            return {"conversation_detail": {"conversation_id": CONV},
                    "latest_conversation_key_change_events": [V["event_key_change_b64"]]}
        if op == "conversation":
            return {"encoded_message_events": [V["event_garbage_b64"] if self.bad else V["event_message_b64"]], "has_more": False}
        if op == "inspect":
            return [{"conversation": CONV, "token": "synthetic-token", "sequence": "1"} for _ in kwargs["events"]]
        raise AssertionError("unexpected fixture operation")
    def close(self):
        pass


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name) / "state"
        self.kc, self.bridge = FakeKeychain(), FixtureBridge()
        self.c = Connector(self.kc, self.bridge, self.directory)
        self.c.login(lambda field, state: "synthetic-value")
        self.c.credentials.update(identity_keys=V["private_keys_concat_b64"], key_version="1")
        self.c.save_credentials()
        self.c.unlock()
    def tearDown(self):
        self.c.close()
        self.temp.cleanup()

    def test_login_does_not_persist_password_and_verified_history_survives_restart(self):
        self.assertEqual(self.bridge.login_steps, ["identifier", "password"])
        self.assertNotIn("synthetic-value", self.kc.value)
        first = self.c.history(CONV)
        self.assertEqual(len(first["added"]), 1)
        self.c.close()
        self.c = Connector(self.kc, FixtureBridge(), self.directory)
        self.c.resume()
        self.c.unlock()
        again = self.c.history(CONV)
        self.assertEqual(again["added"], [])
        self.assertEqual(self.c.messages(CONV)[0]["text"], V["event_message_text"])

    def test_invalid_history_does_not_commit_and_locks_crypto(self):
        self.bridge.bad = True
        with self.assertRaisesRegex(ConnectorError, "signature_or_decryption_failed"):
            self.c.history(CONV)
        self.assertIsNone(self.c.store.get("checkpoint:" + CONV))
        self.assertEqual(self.c.messages(CONV), [])
        self.assertIsNone(self.c.chat)

    def mixed_history(self, extra):
        """Use the actual Go Thrift parser and actual SDK for mixed history."""
        original = self.bridge.call
        helper = Bridge()
        self.addCleanup(helper.close)
        def with_extra(op, **kwargs):
            if op == "inspect":
                return helper.call(op, **kwargs)
            if op == "conversation":
                return {"encoded_message_events": [V["event_message_b64"], extra], "has_more": False}
            return original(op, **kwargs)
        self.bridge.call = with_extra

    def test_legacy_direct_and_wrapped_text_are_stored_with_distinct_provenance(self):
        for wrapped in (False, True):
            legacy = synthetic_legacy_event(wrapped=wrapped)
            self.mixed_history(legacy)
            result = self.c.history(CONV)
            self.assertEqual(result["unsupported_legacy_count"], 0)
            self.assertEqual(result["legacy_message_count"], 1)
            self.assertTrue(result["complete"])
            self.assertEqual(len(self.c.messages(CONV)), 2)
            row = next(m for m in result["messages"] if m.get("source") == "legacy")
            self.assertIs(row["verified"], False)
            self.assertTrue(row["provider_message_id"].startswith("legacy:"))
            self.assertEqual(row["text"], "synthetic legacy content")
            self.assertNotIn(b"synthetic legacy content", self.c.store.path.read_bytes())

    def test_legacy_only_peer_needs_no_chat_public_key(self):
        helper = Bridge(); self.addCleanup(helper.close)
        original = self.bridge.call
        def only_legacy(op, **kwargs):
            if op == "keys": self.fail("Legacy history should not request peer signing keys")
            if op == "detail": return {"conversation_detail": {"conversation_id": CONV}}
            if op == "conversation": return {"encoded_message_events": [synthetic_legacy_event(message_id="1234567890")], "has_more": False}
            if op == "inspect": return helper.call(op, **kwargs)
            return original(op, **kwargs)
        self.bridge.call = only_legacy
        result = self.c.history(CONV)
        self.assertEqual(result["messages"][0]["provider_message_id"], "legacy:1234567890")
        self.assertIsNone(self.c.store.get("token:" + CONV))
        self.assertEqual(self.c.history(CONV)["added"], [])

    def test_legacy_duplicate_envelopes_count_once_and_conflicts_fail(self):
        helper=Bridge(); self.addCleanup(helper.close)
        original=self.bridge.call
        copies=[synthetic_legacy_event(),synthetic_legacy_event(wrapped=True)]
        def duplicate_history(op, **kwargs):
            if op == "detail": return {"conversation_detail":{"conversation_id":CONV}}
            if op == "conversation": return {"encoded_message_events":copies,"has_more":False}
            if op == "inspect": return helper.call(op,**kwargs)
            return original(op,**kwargs)
        self.bridge.call=duplicate_history
        result=self.c.history(CONV)
        self.assertEqual(result["raw_count"],2)
        self.assertEqual(len(result["messages"]),1)
        self.assertEqual(result["legacy_message_count"],1)
        checkpoint=self.c.store.get("checkpoint:"+CONV)
        copies[1]=synthetic_legacy_event(wrapped=True,body="conflicting body")
        with self.assertRaisesRegex(ConnectorError,"signed_id_conflict"): self.c.history(CONV)
        self.assertEqual(self.c.store.get("checkpoint:"+CONV),checkpoint)
        self.assertEqual(self.c.messages(CONV)[0]["text"],"synthetic legacy content")

    def test_legacy_malformed_or_disappearing_body_remains_excluded(self):
        for change in ({"malformed": True}, {"ttl": 1000}):
            self.mixed_history(synthetic_legacy_event(**change))
            result = self.c.history(CONV)
            self.assertEqual(result["unsupported_legacy_count"], 1)
            self.assertFalse(result["complete"])
            self.assertEqual(len(result["messages"]), 1)

    def test_legacy_foreign_sender_and_same_batch_downgrade_fail_atomically(self):
        for change in ({"sender": "3333"}, {"message_id": events()[1]["id"]}):
            self.mixed_history(synthetic_legacy_event(**change))
            with self.assertRaises(ConnectorError): self.c.history(CONV)
            self.assertEqual(self.c.messages(CONV), [])
            if self.c.chat is None: self.c.unlock()

    def test_unsigned_encrypted_message_still_stops_the_batch(self):
        self.mixed_history(synthetic_legacy_event(encrypted=True))
        with self.assertRaisesRegex(ConnectorError, "signature_or_decryption_failed"):
            self.c.history(CONV)
        self.assertEqual(self.c.messages(CONV), [])
        self.assertIsNone(self.c.chat)

    def test_signed_plaintext_shape_still_stops_the_batch(self):
        self.mixed_history(synthetic_legacy_event(signed=True))
        with self.assertRaisesRegex(ConnectorError, "signature_or_decryption_failed"):
            self.c.history(CONV)
        self.assertEqual(self.c.messages(CONV), [])

    def test_legacy_event_from_another_conversation_rejected(self):
        self.mixed_history(synthetic_legacy_event(conversation="1234:5678"))
        with self.assertRaisesRegex(ConnectorError, "message_scope_mismatch"):
            self.c.history(CONV)
        self.assertEqual(self.c.messages(CONV), [])

    def test_known_signed_message_cannot_be_relabelled_as_legacy(self):
        self.c.history(CONV)
        message_id = self.c.messages(CONV)[0]["provider_message_id"]
        self.mixed_history(synthetic_legacy_event(message_id=message_id))
        with self.assertRaisesRegex(ConnectorError, "signature_or_decryption_failed"):
            self.c.history(CONV)
        self.assertEqual(len(self.c.messages(CONV)), 1)

    def test_prepare_send_does_not_make_a_send_call(self):
        draft = self.c.prepare_send(CONV, "synthetic draft only")
        self.assertEqual(draft["recipient"], PEER)
        self.assertEqual(self.c.store.get("send:" + draft["id"])["state"], "prepared")

    def test_image_real_sdk_encrypts_upload_and_verifies_signed_ack_once(self):
        from .test_outgoing_images import uri
        from beeperlocal.outgoing_images import decode_image
        image = decode_image(uri())
        original = self.bridge.call
        calls = []
        def string(field, value):
            raw = value.encode()
            return struct.pack('>bhi', 11, field, len(raw)) + raw
        def media_bridge(op, **kwargs):
            if op == 'upload_image':
                calls.append(op)
                self.assertEqual(self.c.store.get('upload:' + kwargs['message_id'])['state'], 'uploading')
                decoded = self.c.chat.decrypt_events([V['event_key_change_b64']])
                key = next(iter(decoded['conversation_keys']['keys'].values()))
                cipher = base64.b64decode(kwargs['data'])
                self.assertNotIn(image.data, cipher)
                self.assertEqual(self.c.chat.decrypt_stream(cipher, bytes(key)), image.data)
                return {'media_hash_key': 'fixture_media_hash'}
            if op == 'send':
                calls.append(op)
                self.assertEqual(self.c.store.get('send:' + kwargs['message_id'])['state'], 'dispatching')
                raw = string(1, '999') + string(2, kwargs['message_id']) + string(3, SELF) + string(4, CONV) + string(6, '1790812345000')
                raw += struct.pack('>bhbh', 12, 7, 12, 1) + base64.b64decode(kwargs['content']) + b'\0'
                raw += struct.pack('>bh', 12, 9) + base64.b64decode(kwargs['signature']) + b'\0'
                return {'event': base64.b64encode(raw).decode()}
            return original(op, **kwargs)
        self.bridge.call = media_bridge
        draft = self.c.prepare_image(CONV, image)
        self.assertEqual(calls, ['upload_image'])
        self.assertEqual(self.c.send_confirmed(draft['id']), 'sent_verified')
        message = next(m for m in self.c.messages(CONV) if m['provider_message_id'] == draft['id'])
        self.assertEqual(message['attachments'][0]['kind'], 'image')
        self.assertEqual(message['attachments'][0]['media_hash_key'], 'fixture_media_hash')
        with self.assertRaisesRegex(ConnectorError, 'send_already_attempted'):
            self.c.send_confirmed(draft['id'])
        self.assertEqual(calls, ['upload_image', 'send'])

    def test_owned_browser_session_keeps_account_and_existing_keys(self):
        self.c.store.close()
        self.c.store = None
        called = []
        def acquire():
            called.append(True)
            return "auth_token=synthetic; ct0=synthetic"
        profile = self.c.login_browser(acquire)
        self.assertEqual(profile["user"], SELF)
        self.assertEqual(called, [True])
        self.c.unlock()
        self.assertEqual(len(self.c.history(CONV)["added"]), 1)

    def test_browser_account_switch_does_not_replace_keychain(self):
        old = self.kc.value
        original = self.bridge.call
        def wrong_account(op, **kwargs):
            if op == "web_login":
                return {"user": "9999"}
            return original(op, **kwargs)
        self.bridge.call = wrong_account
        with self.assertRaisesRegex(ConnectorError, "account_scope_mismatch"):
            self.c.login_browser(lambda: "synthetic-new-session")
        self.assertEqual(self.kc.value, old)
        self.assertIsNone(self.c.chat)

    def registered_spki_response(self):
        rows = self.bridge.call("keys", users=[SELF])
        row = rows["data"]["user_results_by_rest_ids"][0]["result"]["get_public_keys"]["public_keys_with_token_map"][0]
        public = row["public_key_with_metadata"]["public_key"]
        public["public_key"] = spki(public["public_key"])
        public["signing_public_key"] = spki(public["signing_public_key"])
        public["identity_public_key_signature"] = base64.b64encode(chat().sign(base64.b64decode(public["public_key"]))).decode()
        row["token_map"] = {}  # Never sent anywhere by the mocked unlock.
        original = self.bridge.call
        self.bridge.call = lambda op, **kwargs: rows if op == "keys" else original(op, **kwargs)
        return public

    def test_saved_keys_resume_with_real_registration_format(self):
        self.registered_spki_response()
        self.c.unlock(lambda: self.fail("saved keys must not prompt for a PIN"))
        self.assertTrue(self.c.chat.is_unlocked())

    def test_pin_recovery_with_real_registration_format_prompts_once(self):
        self.registered_spki_response()
        self.c.credentials.pop("identity_keys")
        self.c.credentials.pop("key_version")
        prompts = []
        class RecoveredChat:
            def __init__(self, config):
                self.inner = Chat()
            def unlock(self, pin):
                # Recovery network is mocked; matching, binding, export/import
                # and every cryptographic check use the real SDK.
                self.inner.import_keys(base64.b64decode(V["private_keys_concat_b64"]))
            def __getattr__(self, name):
                return getattr(self.inner, name)
        def ask():
            prompts.append(True)
            return "synthetic-pin"
        with patch("beeperlocal.xcrypto.core.Chat", RecoveredChat):
            self.c.unlock(ask)
        self.assertEqual(prompts, [True])
        self.assertTrue(self.c.chat.is_unlocked())
        self.assertEqual(self.c.credentials["identity_keys"], V["private_keys_concat_b64"])
        self.assertNotIn("synthetic-pin", self.kc.value)

    def test_spki_wrong_signing_key_still_rejected(self):
        public = self.registered_spki_response()
        other = ec.generate_private_key(ec.SECP256R1()).public_key()
        public["signing_public_key"] = base64.b64encode(other.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        old = self.kc.value
        with self.assertRaisesRegex(ConnectorError, "identity_key_mismatch"):
            self.c.unlock()
        self.assertIsNone(self.c.chat)
        self.assertEqual(self.kc.value, old)

    def test_spki_binding_signature_remains_required(self):
        public = self.registered_spki_response()
        public["identity_public_key_signature"] = base64.b64encode(bytes(64)).decode()
        old = self.kc.value
        with self.assertRaisesRegex(ConnectorError, "identity_binding_failed"):
            self.c.unlock()
        self.assertIsNone(self.c.chat)
        self.assertEqual(self.kc.value, old)


if __name__ == "__main__":
    unittest.main()
