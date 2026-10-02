"""Regression cases for bounded recent history and literal Slack text; fixtures only."""
import json
import unittest
from unittest.mock import patch
from uuid import uuid4

from beeperlocal.connectors.slack import SlackAPI, SlackConnector, normalize_slack
from beeperlocal.errors import AppError
from .support import CONV, FakeAPI, FakeOpener, Response, slack_message, slack_store
from . import test_slack_extension as extension


class SlackLiteralTextTests(unittest.TestCase):
    def test_outbound_control_characters_remain_literal_text(self):
        opener = FakeOpener(Response({"ok": True}))
        original = 'A & B < 3 > 1; <@U001> <!channel> &amp; <tag>'
        SlackAPI("xoxp-fixture", opener=opener).post_message(channel="C001", text=original)
        body = json.loads(opener.requests[0].data)
        self.assertEqual(body["text"],
            'A &amp; B &lt; 3 &gt; 1; &lt;@U001&gt; &lt;!channel&gt; &amp;amp; &lt;tag&gt;')
        self.assertFalse(body["mrkdwn"])
        self.assertFalse(body["link_names"])
        self.assertEqual(len(opener.requests), 1)

    def test_history_decodes_only_slack_entities_exactly_once(self):
        raw = slack_message(text='A &amp; B &lt; 3 &gt; 1; &amp;lt; &quot; &#65; &lt;tag&gt;')
        message = normalize_slack(raw, "T001:U001", "U001", CONV)
        self.assertEqual(message.text, 'A & B < 3 > 1; &lt; &quot; &#65; <tag>')


class SlackRecentHistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_recent_page_never_pages_past_filtered_events(self):
        for first_page in (
            {"messages": [slack_message(1), slack_message(2, subtype="channel_join")],
             "response_metadata": {"next_cursor": "older"}},
            {"messages": [slack_message(2, subtype="channel_join")], "has_more": True},
            {"messages": [], "response_metadata": {"next_cursor": "older"}},
        ):
            with self.subTest(first_page=first_page):
                api = FakeAPI(history=[first_page, AppError("RATE_LIMITED")])
                batch = await SlackConnector(slack_store(), api=api).fetch_recent(15)
                self.assertFalse(batch.errors)
                self.assertEqual(batch.conversations_fetched, 1)
                self.assertTrue(batch.history_limited)
                self.assertEqual(len([m for m,p in api.calls if m == "conversations.history"]), 1)

    async def test_recent_page_rejects_multiple_selection_before_network(self):
        store = slack_store(selections=[CONV.selection(), CONV.selection()])
        api = FakeAPI()
        batch = await SlackConnector(store, api=api).fetch_recent(15)
        self.assertEqual(batch.errors, ["SLACK_SELECT_ONE"])
        self.assertEqual(api.calls, [])


class SlackReliabilityCoreTests(unittest.IsolatedAsyncioTestCase):
    setUp = extension.SlackCoreTests.setUp
    make_core = extension.SlackCoreTests.make_core
    asyncTearDown = extension.SlackCoreTests.asyncTearDown

    async def test_core_commits_recent_page_with_events_without_second_history_call(self):
        self.core.poll_interval = 999
        history_calls = []
        original_call = self.backend.call
        def call(method, **params):
            if method != "conversations.history":
                return original_call(method, **params)
            history_calls.append(params)
            if len(history_calls) > 1:
                raise AppError("RATE_LIMITED")
            return {"messages": [slack_message(1, text="RECENT_PAGE_CANARY"),
                                  slack_message(2, subtype="channel_join")],
                    "response_metadata": {"next_cursor": "older"}}
        with patch.object(self.backend, "call", side_effect=call):
            state = await self.core.dispatch({"op": "connect"})
        self.assertEqual(state["connection"], "connected")
        self.assertEqual(state["receiving"], "waiting")
        self.assertEqual(len(history_calls), 1)
        receipt = self.core.db.get_sync_receipt(self.record)
        self.assertEqual(receipt.raw_items, 2)
        self.assertEqual(receipt.excluded_events, 1)
        self.assertTrue(receipt.history_limited)
        await self.core.close()
        self.core = self.make_core()
        await self.core.dispatch({"op": "snapshot"})
        self.assertEqual(len(self.core.search("RECENT_PAGE_CANARY")["results"]), 1)
        self.assertNotIn(b"RECENT_PAGE_CANARY", self.path.read_bytes())

    async def test_symbol_text_keeps_identity_and_search_after_history_refresh(self):
        self.core.poll_interval = 999
        await self.core.dispatch({"op": "connect"})
        text = 'LITERAL_TEXT_CANARY A & B < 3; &lt;'
        request_id = str(uuid4())
        sent = await self.core.dispatch({"op": "send", "conversationId": self.record.id,
            "text": text, "requestId": request_id})
        self.backend.rows = [slack_message(9, user="U001",
            text='LITERAL_TEXT_CANARY A &amp; B &lt; 3; &amp;lt;')]
        await self.core.dispatch({"op": "refresh"})
        await self.core.close()
        self.core = self.make_core()
        await self.core.dispatch({"op": "snapshot"})
        matches = self.core.search(text)["results"]
        self.assertEqual([m["id"] for m in matches], [sent["messageId"]])
        self.assertEqual(matches[0]["text"], text)
        self.assertEqual(self.core.db.get_outgoing(request_id).status, "acknowledged")
        self.assertEqual(self.backend.sends, 1)
        self.assertNotIn(b"LITERAL_TEXT_CANARY", self.path.read_bytes())
