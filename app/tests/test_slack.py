import io
import unittest
from urllib.error import HTTPError, URLError
from beeperlocal.connectors.slack import SlackAPI, SlackConnector, normalize_slack, parse_ts, NoRedirect
from beeperlocal.errors import AppError
from beeperlocal.models import Conversation
from .support import CONV, slack_store, slack_message, FakeAPI, FakeOpener, Response

class SlackNormalizationTests(unittest.TestCase):
    def test_microseconds_are_exact(self):
        self.assertEqual(parse_ts("1700000000.000001").microsecond, 1)
    def test_nan_timestamp_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_ts("NaN")
    def test_normal_message_and_direction(self):
        m = normalize_slack(slack_message(user="U001"), "T001:U001", "U001", CONV)
        self.assertEqual(m.direction, "outgoing")
    def test_join_event_excluded(self):
        self.assertIsNone(normalize_slack(slack_message(subtype="channel_join"), "A", "U", CONV))
    def test_tombstone_excluded(self):
        self.assertIsNone(normalize_slack(slack_message(subtype="tombstone"), "A", "U", CONV))
    def test_hidden_event_excluded(self):
        self.assertIsNone(normalize_slack(slack_message(hidden=True), "A", "U", CONV))
    def test_attachment_only_message_counted_without_downloading(self):
        m = normalize_slack(slack_message(text="", files=[{"id": "F1"}]), "A", "U", CONV)
        self.assertEqual(m.attachment_count, 1)
        self.assertIsNone(m.text)
    def test_thread_root_does_not_reply_to_itself(self):
        raw = slack_message(); raw["thread_ts"] = raw["ts"]
        self.assertIsNone(normalize_slack(raw, "A", "U", CONV).reply_to_message_id)
    def test_bot_message_is_real_content(self):
        raw = slack_message(subtype="bot_message", user=None, bot_id="B001")
        self.assertEqual(normalize_slack(raw, "A", "U", CONV).sender_id, "B001")

class SlackTransportTests(unittest.TestCase):
    def api(self, *responses, **kwargs):
        opener = FakeOpener(*responses)
        return SlackAPI("xoxp-PRIVATE_TOKEN_CANARY", opener=opener, **kwargs), opener
    def http_error(self, code, retry="60"):
        return HTTPError("https://slack.com/api/test", code, "PRIVATE_ERROR_CANARY", {"Retry-After": retry}, io.BytesIO(b"PRIVATE_BODY_CANARY"))
    def test_token_only_in_authorization_header(self):
        api, opener = self.api(Response({"ok": True}))
        api.call("auth.test")
        request = opener.requests[0]
        self.assertNotIn("PRIVATE_TOKEN_CANARY", request.full_url)
        self.assertIn("PRIVATE_TOKEN_CANARY", request.get_header("Authorization"))
    def test_write_method_is_denied(self):
        api, _ = self.api()
        with self.assertRaises(AppError):
            api.call("chat.postMessage", text="never")
    def test_token_query_is_denied(self):
        api, _ = self.api()
        with self.assertRaises(AppError):
            api.call("auth.test", token="secret")
    def test_bot_token_denied(self):
        with self.assertRaises(AppError):
            SlackAPI("xoxb-NOT-A-REAL-TOKEN", opener=FakeOpener())
    def test_retry_after_respected(self):
        waits = []
        api, opener = self.api(self.http_error(429, "2"), Response({"ok": True}), max_wait=2, sleep=waits.append)
        self.assertTrue(api.call("auth.test")["ok"])
        self.assertEqual(waits, [2.0])
        self.assertEqual(len(opener.requests), 2)
    def test_retry_budget_not_exceeded(self):
        waits = []
        api, _ = self.api(self.http_error(429, "60"), max_wait=1, sleep=waits.append)
        with self.assertRaises(AppError) as ctx:
            api.call("auth.test")
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(waits, [])
    def test_missing_scope_safe_error(self):
        api, _ = self.api(Response({"ok": False, "error": "missing_scope", "detail": "PRIVATE_BODY_CANARY"}))
        with self.assertRaises(AppError) as ctx:
            api.call("conversations.history", channel="C001")
        self.assertEqual(ctx.exception.code, "MISSING_SCOPE")
        self.assertNotIn("PRIVATE_BODY_CANARY", str(ctx.exception))
    def test_transport_error_redacts_original(self):
        api, _ = self.api(URLError("PRIVATE_TOKEN_CANARY"))
        with self.assertRaises(AppError) as ctx:
            api.call("auth.test")
        self.assertEqual(str(ctx.exception), "NETWORK_ERROR")
    def test_500_retried_for_get_only(self):
        waits = []
        api, _ = self.api(self.http_error(500), Response({"ok": True}), sleep=waits.append)
        self.assertTrue(api.call("auth.test")["ok"])
        self.assertEqual(waits, [1.0])
    def test_request_budget(self):
        api, _ = self.api(max_requests=0)
        with self.assertRaises(AppError) as ctx:
            api.call("auth.test")
        self.assertEqual(ctx.exception.code, "REQUEST_BUDGET_EXCEEDED")
    def test_redirect_handler_never_creates_request(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))
    def test_redirect_http_error_not_retried(self):
        api, opener = self.api(self.http_error(302))
        with self.assertRaises(AppError):
            api.call("auth.test")
        self.assertEqual(len(opener.requests), 1)

class SlackConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_four_pages_fetch_50(self):
        pages = []
        for i in range(4):
            pages.append({"messages": [slack_message(n) for n in range(i * 15, i * 15 + 15)],
                          "response_metadata": {"next_cursor": f"cursor-{i + 1}" if i < 3 else ""}})
        api = FakeAPI(history=pages)
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.errors, [])
        self.assertEqual(batch.conversations_fetched, 1)
        history_calls = [p for method, p in api.calls if method == "conversations.history"]
        self.assertEqual([p["limit"] for p in history_calls], [15] * 4)
        self.assertEqual(history_calls[1]["cursor"], "cursor-1")
    async def test_empty_filtered_page_with_next_cursor_is_not_eof(self):
        api = FakeAPI(history=[{"messages": [], "response_metadata": {"next_cursor": "next"}},
                               {"messages": [slack_message(1)]}])
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertEqual(len(batch.messages), 1)
        self.assertFalse(batch.errors)
    async def test_repeated_cursor_stops(self):
        page = {"messages": [slack_message(1)], "response_metadata": {"next_cursor": "same"}}
        batch = await SlackConnector(slack_store(), api=FakeAPI(history=[page, page])).fetch()
        self.assertIn("PAGINATION_STALLED", batch.errors)
    async def test_time_pagination_without_cursor(self):
        api = FakeAPI(history=[{"messages": [slack_message(2)], "has_more": True}, {"messages": [slack_message(1)]}])
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertEqual(len(batch.messages), 2)
        calls = [p for m, p in api.calls if m == "conversations.history"]
        self.assertEqual(calls[1]["latest"], "1700000000.000002")
    async def test_duplicate_does_not_satisfy_limit(self):
        raw = slack_message(1)
        batch = await SlackConnector(slack_store(), api=FakeAPI(history=[{"messages": [raw] * 50}])).fetch()
        self.assertEqual(len(batch.messages), 1)
        self.assertEqual(batch.duplicates_removed, 49)
    async def test_scope_error_is_not_silently_skipped(self):
        batch = await SlackConnector(slack_store(), api=FakeAPI(history=[AppError("MISSING_SCOPE")])).fetch()
        self.assertEqual(batch.errors, ["MISSING_SCOPE"])
    async def test_missing_selection_no_api_calls(self):
        api = FakeAPI()
        batch = await SlackConnector(slack_store([]), api=api).fetch()
        self.assertEqual(batch.errors, ["NO_SELECTION"])
        self.assertFalse(api.calls)
    async def test_account_change_blocks_history(self):
        api = FakeAPI(identity={"ok": True, "team_id": "T999", "user_id": "U001"})
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertEqual(batch.errors, ["ACCOUNT_CHANGED"])
        self.assertEqual([m for m, _ in api.calls], ["auth.test"])
    async def test_malformed_message_counted(self):
        api = FakeAPI(history=[{"messages": [slack_message(ts="bad")]}])
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertEqual(batch.normalization_errors, 1)
        self.assertEqual(len(batch.messages), 0)
    async def test_history_limit_is_reported(self):
        api = FakeAPI(history=[{"messages": [slack_message(1)], "is_limited": True}])
        batch = await SlackConnector(slack_store(), api=api).fetch()
        self.assertTrue(batch.history_limited)
    async def test_list_filters_unjoined_public_channels_and_continues(self):
        api = FakeAPI(lists=[{"channels": [{"id": "C999", "name": "not-joined", "is_member": False}],
                             "response_metadata": {"next_cursor": "next"}},
                            {"channels": [{"id": "C001", "name": "joined", "is_member": True}]}])
        choices = await SlackConnector(slack_store(), api=api).list_conversations()
        self.assertEqual([c.id for c in choices], ["C001"])
    async def test_two_selected_chats_with_same_timestamps_preserve_identity(self):
        other = Conversation("C002", "Other", "channel", {"channel_id": "C002"})
        page = {"messages": [slack_message(i) for i in range(25)]}
        api = FakeAPI(history=[page, page])
        batch = await SlackConnector(slack_store([CONV.selection(), other.selection()]), api=api).fetch()
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.duplicates_removed, 0)
        self.assertEqual(batch.conversations_fetched, 2)
