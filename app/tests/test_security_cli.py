import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
from beeperlocal.cli import main, parse_selection, demo_batches
from beeperlocal.credentials import MacKeychain, MacLocalKeyStore
from beeperlocal.errors import AppError
from beeperlocal.models import make_report
from beeperlocal.privacy import safe_text, preview_line, secret_prompt
from beeperlocal.reporting import save_report
from .support import unified

class PrivacyTests(unittest.TestCase):
    def test_terminal_escape_and_bidi_removed(self):
        text = safe_text("abc\x1b[31m\x07\u202edef\r\nxyz")
        for bad in ["\x1b", "\x07", "\u202e", "\r", "\n"]:
            self.assertNotIn(bad, text)
    def test_preview_opt_in(self):
        self.assertNotIn("PRIVATE_BODY_CANARY", preview_line(unified()))
        self.assertNotIn("PRIVATE_TITLE_CANARY", preview_line(unified()))
        self.assertIn("PRIVATE_BODY_CANARY", preview_line(unified(), preview=True))
    def test_long_preview_is_bounded(self):
        self.assertLessEqual(len(safe_text("x" * 10000)), 161)
    def test_secret_rejected_on_pipe(self):
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(AppError) as ctx:
                secret_prompt("secret: ")
        self.assertEqual(ctx.exception.code, "INTERACTIVE_REQUIRED")
    def test_keychain_refuses_non_macos(self):
        with patch("sys.platform", "linux"):
            with self.assertRaises(AppError) as ctx:
                MacKeychain()
        self.assertEqual(ctx.exception.code, "UNSUPPORTED_PLATFORM")
    def test_keychain_failure_does_not_fallback(self):
        store = MacKeychain.__new__(MacKeychain)
        class BrokenBackend:
            def get_password(self, *args):
                raise RuntimeError("PRIVATE_SECRET_CANARY")
        store.backend = BrokenBackend()
        with self.assertRaises(AppError) as ctx:
            store.load("slack")
        self.assertEqual(str(ctx.exception), "KEYCHAIN_UNAVAILABLE")
    def test_keychain_roundtrip_validation(self):
        store = MacKeychain.__new__(MacKeychain)
        class BadBackend:
            def set_password(self, *args):
                pass
            def get_password(self, *args):
                return "wrong"
        store.backend = BadBackend()
        with self.assertRaises(AppError) as ctx:
            store.save("slack", {"token": "secret"})
        self.assertEqual(ctx.exception.code, "KEYCHAIN_WRITE_FAILED")
    def test_local_db_key_create_and_load(self):
        store = MacLocalKeyStore.__new__(MacLocalKeyStore)
        class Backend:
            def __init__(self): self.value = None
            def get_password(self, *args): return self.value
            def set_password(self, service, account, value): self.value = value
            def delete_password(self, *args): self.value = None
        store.backend = Backend()
        key = store.load_or_create()
        self.assertEqual(len(key), 32)
        self.assertEqual(store.load(), key)
        store.delete()
        with self.assertRaises(AppError) as ctx:
            store.load()
        self.assertEqual(ctx.exception.code, "LOCAL_DB_KEY_MISSING")

    def test_local_db_key_invalid_is_refused(self):
        store = MacLocalKeyStore.__new__(MacLocalKeyStore)
        class Backend:
            def get_password(self, *args): return "not-valid-base64%%%"
        store.backend = Backend()
        with self.assertRaises(AppError) as ctx:
            store.load()
        self.assertEqual(ctx.exception.code, "LOCAL_DB_KEY_INVALID")

class ReportTests(unittest.TestCase):
    def test_private_atomic_report_and_no_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp).resolve() / "state"
            report = make_report(demo_batches(), demo=True)
            path = save_report(report, directory=directory)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode), 0o700)
            self.assertNotIn("TEST FIXTURE", path.read_text())
            self.assertEqual(json.loads(path.read_text())["loop_status"], "DEMO_NOT_EVIDENCE")
    def test_report_rejects_unexpected_payload(self):
        report = make_report(demo_batches(), demo=True)
        report["raw_messages"] = ["PRIVATE_BODY_CANARY"]
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(AppError):
                save_report(report, directory=Path(tmp).resolve() / "state")
    def test_symlink_report_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            victim = root / "victim"; victim.write_text("unchanged")
            directory = root / "state"; directory.mkdir()
            (directory / "last-proof.json").symlink_to(victim)
            with self.assertRaises(AppError):
                save_report(make_report(demo_batches(), demo=True), directory=directory)
            self.assertEqual(victim.read_text(), "unchanged")
    def test_symlink_parent_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            (root / "real").mkdir(); (root / "link").symlink_to(root / "real")
            with self.assertRaises(AppError):
                save_report(make_report(demo_batches(), demo=True), directory=root / "link" / "state")

class CLITests(unittest.TestCase):
    def test_selection_dedup_and_bounds(self):
        self.assertEqual(parse_selection("1, 3,1", 4), [0, 2])
        for value in ["0", "5", "1;echo BAD", "", "1,2,3,4,5,6"]:
            with self.assertRaises(AppError):
                parse_selection(value, 4)
    def test_demo_offline_no_keychain_or_report_write(self):
        output = io.StringIO()
        with patch("beeperlocal.cli.MacKeychain", side_effect=AssertionError()), patch("beeperlocal.cli.save_report", side_effect=AssertionError()), contextlib.redirect_stdout(output):
            result = main(["demo", "--limit", "2", "--preview"])
        self.assertEqual(result, 0)
        self.assertIn("DEMO_NOT_EVIDENCE", output.getvalue())
        self.assertNotIn("loop_status=CLOSED", output.getvalue())
    def test_default_demo_does_not_print_body(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = main(["demo", "--limit", "2"])
        self.assertEqual(result, 0)
        self.assertNotIn("TEST FIXTURE:", output.getvalue())
    def test_unknown_argument_does_not_echo_secret(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            main(["login", "slack", "xoxp-PRIVATE_TOKEN_CANARY"])
        self.assertNotIn("PRIVATE_TOKEN_CANARY", error.getvalue())
    def test_low_limit_does_not_close_live_proof(self):
        error, output = io.StringIO(), io.StringIO()
        with patch("beeperlocal.cli.MacKeychain", side_effect=AppError("CREDENTIALS_MISSING")), patch("beeperlocal.cli.save_report", return_value=Path("report.json")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = main(["proof", "--limit", "1"])
        self.assertEqual(result, 1)
        self.assertIn("loop_status=OPEN", output.getvalue())
        self.assertIn("BLOCKED_BY_USER_CREDENTIALS", output.getvalue())
    def test_unexpected_exception_not_leaked(self):
        output, error = io.StringIO(), io.StringIO()
        with patch("beeperlocal.cli.MacKeychain", side_effect=RuntimeError("PRIVATE_TOKEN_CANARY")), patch("beeperlocal.cli.save_report", return_value=Path("report.json")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
            result = main(["proof"])
        self.assertEqual(result, 1)
        self.assertNotIn("PRIVATE_TOKEN_CANARY", output.getvalue() + error.getvalue())
    def test_unsafe_limit_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(["proof", "--limit", "1000000"])

class SDKSmokeTests(unittest.IsolatedAsyncioTestCase):
    @unittest.skipUnless(importlib.util.find_spec("telethon"), "Telethon not installed; SDK import/constructor must be verified on the Mac after setup")
    async def test_installed_telethon_constructor_without_network(self):
        from beeperlocal.connectors.telegram import create_client
        client = create_client({"api_id": 1, "api_hash": "0" * 32, "session": ""})
        self.assertEqual(type(client.session).__name__, "StringSession")

class Phase1CLITests(unittest.TestCase):
    def test_search_query_is_not_a_positional_argument(self):
        error = io.StringIO()
        with contextlib.redirect_stderr(error), self.assertRaises(SystemExit):
            main(["search", "PRIVATE_QUERY_CANARY"])
        self.assertNotIn("PRIVATE_QUERY_CANARY", error.getvalue())

    def test_sync_refuses_partial_batch_persistence(self):
        from beeperlocal.models import FetchBatch
        bad = FetchBatch("matrix", True, 1, conversations_requested=1, conversations_fetched=0, errors=["NETWORK_ERROR"])
        good = FetchBatch("slack", True, 1, messages=[unified(1, "slack")], conversations_requested=1, conversations_fetched=1)
        output = io.StringIO()
        async def fake_fetch(*args, **kwargs):
            return [bad, good]
        with patch("beeperlocal.cli.fetch_live", new=fake_fetch), patch("beeperlocal.cli.save_report", return_value=Path("report.json")), patch("beeperlocal.credentials.MacLocalKeyStore", side_effect=AssertionError("must not touch key")), contextlib.redirect_stdout(output), contextlib.redirect_stderr(io.StringIO()):
            result = main(["sync", "--limit", "1"])
        self.assertEqual(result, 1)
        self.assertIn("local_store=NOT_WRITTEN", output.getvalue())
