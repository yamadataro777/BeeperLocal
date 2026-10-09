"""Slack scopes, single-attempt writes, threads and durable Core integration (fixtures only)."""
import asyncio
from contextlib import asynccontextmanager, redirect_stdout
from dataclasses import replace
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from uuid import uuid4
from types import SimpleNamespace

from beeperlocal.connectors.slack import SlackAPI, SlackConnector, normalize_slack
from beeperlocal.desktop_slack import SlackDesktop
from beeperlocal.errors import AppError
from beeperlocal.mcp_access import AccessManager, default_settings, SETTINGS_KEY
from beeperlocal.models import Conversation, StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from .support import CONV, FakeAPI, FakeOpener, Response, slack_store, slack_message


class SlackBackend(FakeAPI):
    def __init__(self):
        super().__init__()
        self.rows = [slack_message(text="SLACK_BODY_CANARY")]
        self.replies = []
        self.sends = 0
        self.send_error = None
        self.history_error = None
        self.before_send = lambda: None
        self.before_replies = lambda: None
        self.other = Conversation("D002", "SLACK_DM_CANARY", "dm", {"channel_id": "D002"})

    def call(self, method, **params):
        if method == "conversations.history":
            self.calls.append((method, params))
            if self.history_error:
                raise self.history_error
            return {"messages": list(self.rows)}
        if method == "conversations.list":
            return {"channels": [{"id": "C001", "name": CONV.title, "is_member": True},
                                 {"id": "D002", "user": "U002", "is_im": True}]}
        if method == "conversations.replies":
            self.calls.append((method, params))
            self.before_replies()
            value = self.replies.pop(0)
            if isinstance(value, Exception):
                raise value
            return value
        return super().call(method, **params)

    def post_message(self, **params):
        self.sends += 1
        self.before_send()
        if self.send_error:
            raise self.send_error
        raw = slack_message(9, text=params["text"], user="U001")
        return {"ok": True, "channel": params["channel"], "ts": raw["ts"], "message": raw}


class SlackWriteTransportTests(unittest.TestCase):
    def test_post_body_no_credentials_or_text_in_url_and_user_auth(self):
        opener = FakeOpener(Response({"ok": True}))
        api = SlackAPI("xoxp-TOKEN_CANARY", opener=opener)
        api.post_message(channel="C001", text="SLACK_BODY_CANARY")
        req = opener.requests[0]
        self.assertEqual(req.method, "POST")
        self.assertEqual(req.full_url, "https://slack.com/api/chat.postMessage")
        body = json.loads(req.data)
        self.assertFalse(body["mrkdwn"])
        self.assertFalse(body["link_names"])
        self.assertNotIn("token", body)
        self.assertNotIn("username", body)
        self.assertNotIn("as_user", body)
        self.assertEqual(req.get_header("Authorization"), "Bearer xoxp-TOKEN_CANARY")

    def test_every_ambiguous_post_failure_is_single_attempt_and_sanitized(self):
        for failure in (URLError("PRIVATE_CANARY"), Response({"ok": False, "error": "internal_error"}),
                        io.BytesIO(b"not json"), *[
                HTTPError("https://slack.com", n, "PRIVATE_CANARY", {"Retry-After": "1"}, io.BytesIO(b"PRIVATE_CANARY"))
                for n in (302, 429, 500, 503)]):
            with self.subTest(kind=type(failure).__name__):
                opener = FakeOpener(failure)
                api = SlackAPI("xoxp-TOKEN_CANARY", opener=opener, sleep=lambda _: self.fail("must not retry"))
                with self.assertRaises(AppError) as ctx:
                    api.post_message(channel="C001", text="BODY_CANARY")
                self.assertEqual(ctx.exception.code, "SLACK_SEND_UNKNOWN")
                self.assertEqual(len(opener.requests), 1)
                self.assertNotIn("CANARY", str(ctx.exception))

    def test_retry_after_survives_next_operation(self):
        opener = FakeOpener(HTTPError("https://slack.com", 429, "private", {"Retry-After": "120"}, io.BytesIO()))
        cooldowns = {}
        with self.assertRaises(AppError):
            SlackAPI("xoxp-test", opener=opener, max_wait=0, cooldowns=cooldowns).call("conversations.history")
        with self.assertRaises(AppError) as ctx:
            SlackAPI("xoxp-test", opener=opener, max_wait=0, cooldowns=cooldowns).call("conversations.history")
        self.assertEqual(ctx.exception.code, "RATE_LIMITED")
        self.assertEqual(len(opener.requests), 1)


class SlackExtensionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.backend = SlackBackend()
        self.store = slack_store()
        self.connector = SlackConnector(self.store, api=self.backend)

    async def test_send_is_user_not_bot_and_validates_response(self):
        result = await self.connector.send_text("fixture")
        self.assertEqual(result.message.sender_id, "U001")
        self.assertEqual(result.message.direction, "outgoing")
        self.assertFalse(result.encrypted)  # Slack transport TLS is not message E2EE.
        for raw in (slack_message(9, user="UBOT", bot_id="B1"), slack_message(9, user="U999"),
                    slack_message(9, user="U001", bot_id="B1", subtype="bot_message")):
            with patch.object(self.backend, "post_message", return_value={"channel": "C001", "ts": raw["ts"], "message": raw}):
                with self.assertRaises(AppError) as ctx:
                    await self.connector.send_text("fixture")
                self.assertEqual(ctx.exception.code, "SLACK_SEND_UNKNOWN")

    async def test_self_user_message_with_app_attribution_is_acknowledged(self):
        # Live User OAuth history carries bot_id/app_id while user remains the human.
        raw = slack_message(9, user="U001", text="fixture", bot_id="B001", app_id="A001")
        response = {"ok": True, "channel": CONV.id, "ts": raw["ts"], "message": raw}
        with patch.object(self.backend, "post_message", return_value=response) as post:
            result = await self.connector.send_text("fixture")
        self.assertEqual(post.call_count, 1)
        self.assertEqual(result.message.sender_id, "U001")
        self.assertEqual(result.message.direction, "outgoing")


    async def test_account_change_prevents_write_and_fetch(self):
        self.store.save("slack", {**self.store.load("slack"), "account_id": "T999:U001"})
        with self.assertRaises(AppError) as ctx:
            await self.connector.send_text("fixture")
        self.assertEqual(ctx.exception.code, "ACCOUNT_CHANGED")
        self.assertEqual(self.backend.sends, 0)
        self.assertEqual((await self.connector.fetch()).errors, ["ACCOUNT_CHANGED"])

    async def test_bot_auth_response_and_unjoined_channel_never_write(self):
        self.backend.identity["bot_id"] = "B001"
        with self.assertRaises(AppError): await self.connector.send_text("fixture")
        del self.backend.identity["bot_id"]
        original = self.backend.call
        def call(method, **params):
            if method == "conversations.info":
                return {"channel": {"id": params["channel"], "is_member": False}}
            return original(method, **params)
        with patch.object(self.backend, "call", side_effect=call):
            with self.assertRaises(AppError): await self.connector.send_text("fixture")
        self.assertEqual(self.backend.sends, 0)

    async def test_send_authorization_is_rechecked_immediately_before_post(self):
        def denied(): raise AppError("MCP_ACCESS_DENIED")
        with self.assertRaises(AppError):
            await self.connector.send_to(CONV, "fixture", authorize=denied)
        self.assertEqual(self.backend.sends, 0)

    async def test_threads_page_deduplicate_and_retain_parent(self):
        root = slack_message()["ts"]
        parent = slack_message(thread_ts=root)
        reply = slack_message(1, thread_ts=root)
        self.backend.replies = [{"messages": [parent, reply], "response_metadata": {"next_cursor": "next"}},
                                {"messages": [reply, slack_message(2, thread_ts=root)]}]
        batch = await self.connector.fetch_thread(CONV, root)
        self.assertEqual(len(batch.messages), 3)
        self.assertIsNone(batch.messages[0].reply_to_message_id)
        self.assertEqual(batch.messages[1].reply_to_message_id, root)
        self.assertEqual([p["limit"] for m,p in self.backend.calls if m == "conversations.replies"], [15,15])

    async def test_thread_time_pagination_and_bound(self):
        root = slack_message()["ts"]
        self.backend.replies = [{"messages": [slack_message(thread_ts=root)], "has_more": True},
                                {"messages": [slack_message(1, thread_ts=root)], "has_more": True}]
        batch = await self.connector.fetch_thread(CONV, root, limit=2)
        self.assertTrue(batch.history_limited)
        calls = [p for m,p in self.backend.calls if m == "conversations.replies"]
        self.assertEqual(calls[1]["oldest"], root)

    async def test_thread_wrong_parent_and_repeated_cursor_fail_closed(self):
        root = slack_message()["ts"]
        for pages in ([{"messages": [slack_message(2, thread_ts=slack_message(1)["ts"])]}],
            [{"messages": [], "response_metadata": {"next_cursor": "same"}}]*2):
            self.backend.replies = pages
            with self.assertRaises(AppError): await self.connector.fetch_thread(CONV, root)

    async def test_membership_scope_failure_is_not_hidden(self):
        self.backend.replies = [AppError("MISSING_SCOPE")]
        with self.assertRaises(AppError) as ctx:
            await self.connector.fetch_thread(CONV, slack_message()["ts"])
        self.assertEqual(ctx.exception.code, "MISSING_SCOPE")

    async def test_private_explicit_nonmembership_and_archived_channels_are_excluded(self):
        api = FakeAPI(lists=[{"channels": [
            {"id":"C001", "is_private":True, "is_member":False},
            {"id":"C002", "is_member":True, "is_archived":True},
            {"id":"D001", "is_im":True},
            {"id":"G001", "is_mpim":True},
        ]}])
        rows = await SlackConnector(self.store,api=api).list_conversations()
        self.assertEqual({r.id for r in rows},{"D001","G001"})

    async def test_multi_selection_still_fetches_but_never_chooses_send_recipient(self):
        self.store.save("slack", {**self.store.load("slack"), "selections": [CONV.selection(), self.backend.other.selection()]})
        batch = await self.connector.fetch()
        self.assertEqual(batch.conversations_fetched, 2)
        with self.assertRaises(AppError) as ctx: await self.connector.send_text("fixture")
        self.assertEqual(ctx.exception.code, "SLACK_SELECT_ONE")
        self.assertEqual(self.backend.sends, 0)

    def test_workspace_identity_prevents_duplicate_collision(self):
        a = normalize_slack(slack_message(), "T001:U001", "U001", CONV)
        b = replace(a, account_id="T002:U001")
        self.assertNotEqual(a.id, b.id)
        self.assertNotEqual(StoredConversation("slack", a.account_id, CONV).id,
                            StoredConversation("slack", b.account_id, CONV).id)


class SlackCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()/"state"/"messages.sqlite3"
        self.store = slack_store()
        self.backend = SlackBackend()
        self.events = []
        self.core = self.make_core()
        self.record = StoredConversation("slack", "T001:U001", CONV)
        self.other = StoredConversation("slack", "T001:U001", self.backend.other)

    def make_core(self):
        core = SlackDesktop(credentials=self.store, db_factory=lambda: EncryptedMessageStore(b"k"*32, self.path),
            connector_factory=lambda store: SlackConnector(store, api=self.backend), emit=self.events.append)
        core.poll_interval = .015
        core.supports_all_sync = lambda: False  # Legacy receiver contract; all-conversation tests are separate.
        core.retry_delays = (.005, .01)
        return core

    async def asyncTearDown(self):
        await self.core.close()

    async def connect(self):
        return await self.core.dispatch({"op": "connect"})

    async def until(self, predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(.01)
        self.fail("Expected fixture state was not reached")

    def grant(self, *, read=True, send=False):
        self.core._save_settings(mcpEnabled=True)
        return self.core.register_client({"name": "fixture", "conversationIds": [self.record.id], "read": read, "send": send})

    async def test_poll_restart_dedup_encryption_search(self):
        await self.connect()
        self.assertEqual(self.core.messages(self.record.id)["historyLimit"],15)
        self.backend.rows += [slack_message(2, text="SLACK_NEW_CANARY")]
        await self.until(lambda: self.core.db.total_count() == 2)
        await asyncio.sleep(.035)
        self.assertEqual(self.core.db.total_count(), 2)
        await self.core.close()
        self.core = self.make_core()
        await self.core.dispatch({"op":"snapshot"})
        self.assertEqual(len(self.core.search("SLACK_NEW_CANARY")["results"]), 1)
        for value in (b"SLACK_NEW_CANARY", b"T001:U001", b"SLACK_BODY_CANARY", CONV.title.encode()):
            self.assertNotIn(value, self.path.read_bytes())

    async def test_transient_poll_failure_recovers_and_auth_stops(self):
        await self.connect()
        self.backend.history_error = AppError("NETWORK_ERROR")
        await self.until(lambda: self.core.receiving == "reconnecting")
        self.backend.history_error = None
        await self.until(lambda: self.core.receiving == "waiting")
        self.assertIsNone(self.core.error_code)
        self.backend.history_error = AppError("CREDENTIALS_INVALID")
        await self.until(lambda: self.core.receiving == "error")
        calls = len(self.backend.calls)
        await asyncio.sleep(.04)
        self.assertEqual(calls, len(self.backend.calls))

    async def test_poll_slow_retries_recover_and_stop_cancels(self):
        await self.connect()
        self.core.reconnect_interval = .03
        self.backend.history_error = AppError("NETWORK_ERROR")
        await self.until(lambda: self.core.error_code == "SLACK_RECONNECT_WAITING")
        self.assertEqual(self.core.receiving, "reconnecting")
        self.backend.history_error = None
        await self.until(lambda: self.core.receiving == "waiting")
        self.assertIsNone(self.core.error_code)
        await self.core.dispatch({"op":"stop"})
        before = len(self.backend.calls)
        await asyncio.sleep(.04)
        self.assertEqual(before, len(self.backend.calls))

    async def test_stop_cancels_slow_retry_before_another_request(self):
        await self.connect()
        self.core.retry_delays = ()
        self.core.reconnect_interval = .04
        self.backend.history_error = AppError("NETWORK_ERROR")
        await self.until(lambda: self.core.error_code == "SLACK_RECONNECT_WAITING")
        await self.core.dispatch({"op": "stop"})
        before = len(self.backend.calls)
        await asyncio.sleep(.06)
        self.assertEqual(before, len(self.backend.calls))

    async def test_send_intent_committed_before_one_post_and_restart_unknown_no_resend(self):
        await self.connect()
        rid = str(uuid4())
        def before_send():
            with EncryptedMessageStore(b"k"*32, self.path) as db:
                self.assertEqual(db.get_outgoing(rid).status, "sending")
        self.backend.before_send = before_send
        self.backend.send_error = AppError("SLACK_SEND_UNKNOWN")
        request = {"op":"send", "conversationId":self.record.id,"text":"fixture","requestId":rid}
        with self.assertRaises(AppError): await self.core.dispatch(request)
        await self.core.close()
        self.core = self.make_core()
        await self.connect()
        with self.assertRaises(AppError): await self.core.dispatch(request)
        self.assertEqual(self.backend.sends, 1)

    async def test_acknowledged_send_duplicate_suppressed(self):
        await self.connect()
        request = {"op":"send", "conversationId":self.record.id,"text":"fixture","requestId":str(uuid4())}
        one = await self.core.dispatch(request)
        two = await self.core.dispatch(request)
        self.assertEqual(one["messageId"], two["messageId"])
        self.assertTrue(two["duplicateSuppressed"])
        self.assertEqual(self.backend.sends, 1)

    async def test_app_attributed_self_send_ack_survives_restart_without_resend(self):
        await self.connect()
        original_post = self.backend.post_message
        def app_attributed_post(**params):
            result = original_post(**params)
            result["message"].update(bot_id="B001", app_id="A001")
            return result
        request = {"op":"send", "conversationId":self.record.id,
                   "text":"APP_ATTRIBUTED_CANARY", "requestId":str(uuid4())}
        with patch.object(self.backend, "post_message", side_effect=app_attributed_post):
            one = await self.core.dispatch(request)
        self.assertEqual(one["status"], "acknowledged")
        self.assertEqual(self.core.db.get_outgoing(request["requestId"]).status, "acknowledged")
        await self.core.close()
        self.core = self.make_core()
        await self.connect()
        two = await self.core.dispatch(request)
        self.assertTrue(two["duplicateSuppressed"])
        self.assertEqual(one["messageId"], two["messageId"])
        self.assertEqual(len(self.core.search("APP_ATTRIBUTED_CANARY")["results"]), 1)
        self.assertEqual(self.backend.sends, 1)
        self.assertNotIn(b"APP_ATTRIBUTED_CANARY", self.path.read_bytes())

    async def test_cli_send_uses_same_outbox_without_printing_private_data(self):
        from beeperlocal.slack_cli import run_slack
        output = io.StringIO()
        with patch("beeperlocal.slack_cli.SlackDesktop", return_value=self.core), \
                patch("beeperlocal.slack_cli.secret_prompt", return_value="CLI_PRIVATE_CANARY"), \
                redirect_stdout(output):
            self.assertEqual(await run_slack(SimpleNamespace(command="send")), 0)
        self.assertEqual(self.backend.sends, 1)
        self.assertNotIn("CANARY", output.getvalue())
        self.assertNotIn(self.record.account_id, output.getvalue())
        with EncryptedMessageStore(b"k"*32, self.path) as db:
            self.assertEqual(db.conn.execute("SELECT COUNT(*) FROM outgoing_requests").fetchone()[0], 1)
            self.assertEqual(db.total_count(), 1)

    async def test_db_failure_prevents_remote_send_and_stops_poll(self):
        await self.connect()
        with patch.object(self.core.db,"upsert",side_effect=AppError("LOCAL_DB_UNAVAILABLE")):
            with self.assertRaises(AppError):
                await self.core.dispatch({"op":"send","conversationId":self.record.id,"text":"fixture","requestId":str(uuid4())})
            await self.until(lambda: self.core.receiving == "error")
        self.assertEqual(self.backend.sends, 0)

    async def test_read_send_grants_cross_provider_and_other_conversation_isolation(self):
        await self.connect()
        read = self.grant()
        result = await self.core.mcp_call(read["token"], "list_conversations", {})
        self.assertEqual([c["id"] for c in result["conversations"]], [self.record.id])
        self.assertEqual(result["conversations"][0]["provider"], "slack")
        self.assertEqual(len((await self.core.mcp_call(read["token"],"search_messages",{"query":"SLACK_BODY_CANARY"}))["results"]),1)
        for op, args in [("get_messages",{"conversation_id":self.other.id}),
            ("send_message",{"conversation_id":self.record.id,"text":"fixture","request_id":str(uuid4())})]:
            with self.assertRaises(AppError): await self.core.mcp_call(read["token"],op,args)
        line = AccessManager(self.core.db)
        _, wrong = line.create(name="LINE",account_id=self.core.account_id,conversations=[self.record.id],read=True,send=True,available={self.record.id})
        with self.assertRaises(AppError): await self.core.mcp_call(wrong,"list_conversations",{})
        write = self.grant(read=False, send=True)
        args = {"conversation_id":self.record.id,"text":"fixture","request_id":str(uuid4())}
        await self.core.mcp_call(write["token"],"send_message",args)
        await self.core.mcp_call(write["token"],"send_message",args)
        self.assertEqual(self.backend.sends, 1)
        self.core.access.revoke(write["client"]["id"], self.core.account_id)
        with self.assertRaises(AppError): await self.core.mcp_call(write["token"],"send_message",args)

    async def test_mcp_send_does_not_change_gui_selection(self):
        await self.connect()
        grant = self.grant(send=True)
        await self.core.dispatch({"op":"select","conversationId":self.other.id})
        await self.core.mcp_call(grant["token"], "send_message", {"conversation_id":self.record.id,
            "text":"fixture","request_id":str(uuid4())})
        self.assertEqual(self.core.selected_id, self.other.id)
        self.assertEqual(self.core.connector.selected_conversation().id,self.other.conversation.id)

    async def test_thread_scope_revocation_and_parent_opaque_id(self):
        await self.connect()
        grant = self.grant()
        root = self.core.db.list_messages("slack",self.core.account_id,CONV.id)[0]
        reply = slack_message(1,thread_ts=root.provider_message_id)
        self.backend.replies = [{"messages":[slack_message(),reply]}]
        result = await self.core.mcp_call(grant["token"],"get_thread",{"conversation_id":self.record.id,"message_id":root.id})
        self.assertEqual(result["messages"][1]["replyToMessageId"],root.id)
        self.assertEqual(result["limit"],15)
        self.assertEqual(self.core.db.total_count(),2)
        self.backend.replies = [{"messages":[slack_message(3,thread_ts=root.provider_message_id)]}]
        original = self.core.connector.fetch_thread
        async def revoke_during_fetch(*args, **kwargs):
            batch = await original(*args, **kwargs)
            self.core.access.revoke(grant["client"]["id"], self.core.account_id)
            return batch
        self.core.connector.fetch_thread = revoke_during_fetch
        with self.assertRaises(AppError):
            await self.core.mcp_call(grant["token"],"get_thread",{"conversation_id":self.record.id,"message_id":root.id})
        self.assertEqual(self.core.db.total_count(),2)

    async def test_slack_pause_does_not_modify_line_settings_and_survives_restart(self):
        await self.connect()
        self.core.db.private_put(SETTINGS_KEY, default_settings())
        await self.core.dispatch({"op":"storage_pause","paused":True})
        self.assertFalse(self.core.db.private_get(SETTINGS_KEY)["storagePaused"])
        await self.core.close()
        self.core = self.make_core()
        state = await self.core.dispatch({"op":"snapshot"})
        self.assertTrue(state["storagePaused"])
        for op in ("line_login_start","avatar"):
            with self.assertRaises(AppError): await self.core.dispatch({"op":op})


class SlackHTTPTests(unittest.IsolatedAsyncioTestCase):
    setUp = SlackCoreTests.setUp
    make_core = SlackCoreTests.make_core
    connect = SlackCoreTests.connect
    grant = SlackCoreTests.grant
    asyncTearDown = SlackCoreTests.asyncTearDown

    async def test_real_http_sdk_scopes_thread_and_single_send(self):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        await self.connect()
        self.core.poll_interval = 999
        granted = self.grant(send=True)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1",0))
            port = probe.getsockname()[1]
        await self.core.configure_mcp(True,port)
        url = f"http://127.0.0.1:{port}/mcp"
        @asynccontextmanager
        async def transport():
            async with httpx2.AsyncClient(headers={"Authorization":"Bearer "+granted["token"]},trust_env=False) as http:
                async with streamable_http_client(url,http_client=http) as streams:
                    yield streams
        async with Client(transport(),read_timeout_seconds=5) as client:
            listing = await client.list_tools()
            tool_list = listing.tools if hasattr(listing,"tools") else listing
            self.assertEqual({t.name for t in tool_list},
                             {"list_conversations","get_messages","search_messages","send_message","get_thread"})
            result = await client.call_tool("get_messages",{"conversation_id":self.record.id})
            self.assertFalse(result.is_error)
            root = json.loads(result.content[0].text)["messages"][0]
            self.backend.replies = [{"messages":[slack_message(),slack_message(1,thread_ts=slack_message()["ts"])]}]
            thread = await client.call_tool("get_thread",{"conversation_id":self.record.id,"message_id":root["id"]})
            self.assertFalse(thread.is_error)
            denied = await client.call_tool("get_thread",{"conversation_id":self.other.id,"message_id":root["id"]})
            self.assertTrue(denied.is_error)
            args={"conversation_id":self.record.id,"text":"HTTP_FIXTURE","request_id":str(uuid4())}
            self.assertFalse((await client.call_tool("send_message",args)).is_error)
            self.assertFalse((await client.call_tool("send_message",args)).is_error)
            self.assertEqual(self.backend.sends,1)
            self.core.access.revoke(granted["client"]["id"],self.core.account_id)
        async with httpx2.AsyncClient(trust_env=False) as http:
            response = await http.post(url,headers={"Authorization":"Bearer "+granted["token"]},json={})
            self.assertEqual(response.status_code,401)
