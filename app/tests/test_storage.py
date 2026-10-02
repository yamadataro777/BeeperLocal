from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import stat
import tempfile
import unittest

from beeperlocal.errors import AppError
from beeperlocal.storage import EncryptedMessageStore, delete_database_files
from .support import unified


class EncryptedStorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.path = self.root / "state" / "messages-v1.sqlite3"
        self.key = bytes(range(32))

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip_and_plaintext_body_not_in_db(self):
        message = unified(1, provider="matrix", text="PRIVATE_BODY_CANARY_日本語", conversation_title="PRIVATE_TITLE_CANARY")
        with EncryptedMessageStore(self.key, self.path) as db:
            stats = db.upsert([message])
            self.assertEqual(stats, {"processed": 1, "inserted": 1, "updated": 0})
            results, scanned = db.search("BODY_CANARY", limit=20)
        self.assertEqual(scanned, 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].text, "PRIVATE_BODY_CANARY_日本語")
        raw = self.path.read_bytes()
        self.assertNotIn(b"PRIVATE_BODY_CANARY", raw)
        self.assertNotIn("PRIVATE_TITLE_CANARY".encode(), raw)
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.path.parent.stat().st_mode), 0o700)

    def test_restart_with_same_key_and_upsert_is_idempotent(self):
        original = unified(2, provider="slack", text="before")
        with EncryptedMessageStore(self.key, self.path) as db:
            self.assertEqual(db.upsert([original])["inserted"], 1)
        changed = unified(2, provider="slack", text="after")
        with EncryptedMessageStore(self.key, self.path) as db:
            stats = db.upsert([changed])
            self.assertEqual(stats["inserted"], 0)
            self.assertEqual(stats["updated"], 1)
            self.assertEqual(db.total_count(), 1)
            results, _ = db.search("after")
            self.assertEqual(results[0].text, "after")

    def test_provider_filter_and_japanese_substring_search(self):
        messages = [
            unified(1, provider="matrix", text="東京で会議"),
            unified(2, provider="slack", text="東京でランチ"),
            unified(3, provider="slack", text="大阪"),
        ]
        with EncryptedMessageStore(self.key, self.path) as db:
            db.upsert(messages)
            results, scanned = db.search("東京", provider="slack")
        self.assertEqual(scanned, 2)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].provider, "slack")
        self.assertEqual(results[0].text, "東京でランチ")

    def test_wrong_key_refuses_existing_database(self):
        with EncryptedMessageStore(self.key, self.path) as db:
            db.upsert([unified(1, provider="matrix")])
        with self.assertRaises(AppError) as ctx:
            EncryptedMessageStore(b"x" * 32, self.path)
        self.assertEqual(ctx.exception.code, "LOCAL_DB_KEY_MISMATCH")

    def test_ciphertext_tamper_is_detected(self):
        with EncryptedMessageStore(self.key, self.path) as db:
            msg = unified(1, provider="matrix")
            db.upsert([msg])
        conn = sqlite3.connect(self.path)
        row = conn.execute("SELECT id,ciphertext FROM messages").fetchone()
        blob = bytearray(row[1]); blob[-1] ^= 1
        conn.execute("UPDATE messages SET ciphertext=? WHERE id=?", (bytes(blob), row[0]))
        conn.commit(); conn.close()
        with EncryptedMessageStore(self.key, self.path) as db:
            with self.assertRaises(AppError) as ctx:
                db.search("PRIVATE")
        self.assertEqual(ctx.exception.code, "LOCAL_DB_CORRUPT")

    def test_duplicate_input_batch_is_refused(self):
        msg = unified(1, provider="matrix")
        with EncryptedMessageStore(self.key, self.path) as db:
            with self.assertRaises(AppError) as ctx:
                db.upsert([msg, msg])
        self.assertEqual(ctx.exception.code, "INVALID_INPUT")

    def test_symlink_database_is_refused(self):
        self.path.parent.mkdir(parents=True)
        victim = self.root / "victim"
        victim.write_bytes(b"do not touch")
        self.path.symlink_to(victim)
        with self.assertRaises(AppError) as ctx:
            EncryptedMessageStore(self.key, self.path)
        self.assertEqual(ctx.exception.code, "UNSAFE_PATH")
        self.assertEqual(victim.read_bytes(), b"do not touch")

    def test_delete_removes_db_but_not_other_files(self):
        with EncryptedMessageStore(self.key, self.path) as db:
            db.upsert([unified(1, provider="matrix")])
        other = self.path.parent / "keep.txt"; other.write_text("keep")
        removed = delete_database_files(self.path)
        self.assertGreaterEqual(removed, 1)
        self.assertFalse(self.path.exists())
        self.assertEqual(other.read_text(), "keep")


if __name__ == "__main__":
    unittest.main()
