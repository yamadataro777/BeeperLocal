import json
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from beeperlocal.models import FetchBatch, make_report, finish_batch, unique_latest, iso
from beeperlocal.cli import demo_batches
from .support import unified

class ModelsTests(unittest.TestCase):
    def test_id_scopes_conversation(self):
        self.assertNotEqual(unified().id, unified(conversation_id="other").id)
    def test_id_scopes_account(self):
        self.assertNotEqual(unified().id, unified(account_id="other").id)
    def test_id_scopes_provider(self):
        self.assertNotEqual(unified().id, unified(provider="slack").id)
    def test_separator_does_not_create_id_collision(self):
        self.assertNotEqual(unified(account_id="a:b", conversation_id="c").id,
                            unified(account_id="a", conversation_id="b:c").id)
    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):
            unified(sent_at=datetime(2026, 1, 1))
    def test_missing_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            unified(sent_at=None)
    def test_invalid_text_rejected(self):
        with self.assertRaises(ValueError):
            unified(text={"not": "text"})
    def test_iso_preserves_microseconds(self):
        when = datetime(2026, 1, 1, 9, 0, 0, 123, tzinfo=timezone(timedelta(hours=9)))
        self.assertEqual(iso(when), "2026-01-01T00:00:00.000123Z")
    def test_dedup_retains_latest_edit(self):
        original = unified()
        edit = replace(original, edited_at=original.sent_at + timedelta(seconds=5), text="edited")
        result, duplicates = unique_latest([edit, original], 50)
        self.assertEqual(result[0].text, "edited")
        self.assertEqual(duplicates, 1)
    def test_latest_window_is_chronological(self):
        result, _ = unique_latest([unified(i) for i in reversed(range(60))], 50)
        self.assertEqual(len(result), 50)
        self.assertEqual(result[0].provider_message_id, "10")
        self.assertEqual(result[-1].provider_message_id, "59")
    def test_same_message_id_in_two_chats_not_deduped(self):
        result, dup = unique_latest([unified(), unified(conversation_id="other")], 50)
        self.assertEqual((len(result), dup), (2, 0))
    def test_body_not_in_dataclass_repr(self):
        self.assertNotIn("PRIVATE_BODY_CANARY", repr(unified()))
    def test_handoff_contract_has_scoped_id_and_microsecond_date(self):
        m = unified()
        self.assertEqual(m.to_contract()["id"], m.id)
        self.assertTrue(m.to_contract()["sentAt"].endswith(".000000Z"))

class AcceptanceTests(unittest.TestCase):
    def batches(self, count=50, requested_limit=None):
        requested_limit = count if requested_limit is None else requested_limit
        return [FetchBatch(p, True, requested_limit, [unified(i, p) for i in range(count)],
                           conversations_requested=1, conversations_fetched=1) for p in ("matrix", "slack")]

    def test_two_real_one_closes_connectivity_gate(self):
        report = make_report(self.batches(1, 1))
        self.assertEqual(report["loop_status"], "CLOSED")
        self.assertEqual(report["volume_loop_status"], "OPEN")
        self.assertTrue(all(row["status"] == "PASS" for row in report["providers"]))
        self.assertTrue(all(row["volume_status"] == "INSUFFICIENT_MESSAGES" for row in report["providers"]))

    def test_two_real_50_closes_both_gates(self):
        report = make_report(self.batches(50, 50))
        self.assertEqual(report["loop_status"], "CLOSED")
        self.assertEqual(report["volume_loop_status"], "CLOSED")

    def test_one_provider_does_not_close(self):
        self.assertEqual(make_report(self.batches()[:1])["loop_status"], "OPEN")

    def test_mock_with_real_provider_labels_never_closes(self):
        self.assertEqual(make_report(demo_batches())["loop_status"], "OPEN")

    def test_demo_flag_never_closes_even_with_live_batches(self):
        self.assertEqual(make_report(self.batches(), demo=True)["loop_status"], "DEMO_NOT_EVIDENCE")

    def test_zero_messages_does_not_close_connectivity(self):
        b = self.batches(1, 1)
        b[0].messages = []
        report = make_report(b)
        self.assertEqual(report["loop_status"], "OPEN")
        self.assertEqual(report["providers"][0]["status"], "NO_REAL_MESSAGES")

    def test_49_closes_connectivity_but_not_volume(self):
        report = make_report(self.batches(49, 49))
        self.assertEqual(report["loop_status"], "CLOSED")
        self.assertEqual(report["volume_loop_status"], "OPEN")
        self.assertTrue(all(row["volume_status"] == "INSUFFICIENT_MESSAGES" for row in report["providers"]))

    def test_duplicated_messages_do_not_fake_connectivity_or_volume(self):
        b = self.batches(50, 50)
        b[0].messages = [unified(provider="matrix")] * 50
        report = make_report(b)
        self.assertEqual(report["loop_status"], "CLOSED")  # one unique real message is enough for Gate A
        self.assertEqual(report["volume_loop_status"], "OPEN")

    def test_missing_credentials_explicitly_blocked(self):
        b = self.batches(); b[0].errors = ["CREDENTIALS_MISSING"]
        self.assertEqual(make_report(b)["providers"][0]["status"], "BLOCKED_BY_USER_CREDENTIALS")

    def test_normalization_error_blocks(self):
        b = self.batches(); b[0].normalization_errors = 1
        self.assertEqual(make_report(b)["loop_status"], "OPEN")

    def test_fetch_error_blocks_even_with_50_rows(self):
        b = self.batches(); b[0].errors = ["RATE_LIMITED"]
        self.assertEqual(make_report(b)["loop_status"], "OPEN")

    def test_wrong_provider_in_batch_blocks(self):
        b = self.batches(); b[0].messages = [unified(i, "slack") for i in range(50)]
        self.assertEqual(make_report(b)["loop_status"], "OPEN")

    def test_unfetched_selected_conversation_blocks(self):
        b = self.batches(); b[0].conversations_requested = 2
        self.assertEqual(make_report(b)["loop_status"], "OPEN")

    def test_same_provider_twice_does_not_close(self):
        b = self.batches()
        self.assertEqual(make_report([b[0], b[0]])["loop_status"], "OPEN")

    def test_report_has_no_body_title_sender_or_account(self):
        text = json.dumps(make_report(self.batches()))
        for forbidden in ["PRIVATE_BODY_CANARY", "PRIVATE_TITLE_CANARY", '"account_id"', '"sender_id"']:
            self.assertNotIn(forbidden, text)

    def test_demo_has_zero_real_messages(self):
        r = make_report(demo_batches(), demo=True)
        self.assertTrue(all(p["real_messages"] == 0 for p in r["providers"]))
