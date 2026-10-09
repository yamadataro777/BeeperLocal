"""Slack GUI profile scoping, caching and image transport; no real accounts."""
import asyncio
import json
import unittest
from unittest.mock import AsyncMock, patch

from beeperlocal.connectors.slack import SlackConnector
from beeperlocal.errors import AppError
from beeperlocal.slack_profiles import download_slack_avatar, profile_view, valid_avatar_url
from . import test_slack_extension as extension
from .support import CONV, FakeAPI, slack_store

URL = "https://avatars.slack-edge.com/2026-10-02/profile_fixture_72.png"
PROFILE = {"user": {"id": "U002", "name": "fallback", "profile": {
    "display_name": "PROFILE_NAME_CANARY", "real_name": "unused", "image_72": URL,
    "email": "PRIVATE_EMAIL_CANARY", "status_text": "PRIVATE_STATUS_CANARY"}}}


class SlackProfileValidationTests(unittest.TestCase):
    def test_only_name_and_allowlisted_image_are_retained(self):
        self.assertEqual(profile_view(PROFILE, "U002"), {"name": "PROFILE_NAME_CANARY", "url": URL})
        altered = {"user": {"id": "U002", "name": "fallback", "profile": {"display_name": " ",
            "real_name": "Real name", "image_72": "https://untrusted.invalid/photo"}}}
        self.assertEqual(profile_view(altered, "U002"), {"name": "Real name", "url": None})
        with self.assertRaises(AppError):
            profile_view(PROFILE, "U999")

    def test_image_sources_cannot_redirect_credentials_to_another_host(self):
        self.assertTrue(valid_avatar_url(URL))
        self.assertTrue(valid_avatar_url("https://secure.gravatar.com/avatar/fixture?s=72"))
        for url in ("http://avatars.slack-edge.com/p", "https://avatars.slack-edge.com.evil.invalid/p",
                    "https://user:secret@avatars.slack-edge.com/p", "https://127.0.0.1/p",
                    "https://avatars.slack-edge.com:444/p", "https://avatars.slack-edge.com/p#fragment",
                    "file:///private/fixture", "data:image/png;base64,x", "https://avatars.slack-edge.com/p\n"):
            self.assertFalse(valid_avatar_url(url), url)


class SlackProfileConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_lookup_requires_current_account_and_valid_user(self):
        api = FakeAPI()
        store = slack_store()
        connector = SlackConnector(store, api=api)
        with self.assertRaises(AppError):
            await connector.fetch_user_profile("https://untrusted.invalid")
        self.assertEqual(api.calls, [])
        store.save("slack", {**store.load("slack"), "account_id": "TOTHER:U001"})
        with self.assertRaises(AppError) as ctx:
            await connector.fetch_user_profile("U002")
        self.assertEqual(ctx.exception.code, "ACCOUNT_CHANGED")
        self.assertEqual(api.calls, [])

    async def test_dm_peer_is_preserved_without_fetching_a_directory(self):
        api = FakeAPI(lists=[{"channels": [{"id": "D002", "is_im": True, "user": "U002"}]}])
        rows = await SlackConnector(slack_store(), api=api).list_conversations()
        self.assertEqual(rows[0].locator["peer_user_id"], "U002")
        self.assertNotIn("users.info", [method for method,params in api.calls])

    async def test_avatar_download_uses_no_auth_redirect_or_proxy(self):
        class Response:
            status_code = 200
            headers = {"content-type": "image/png"}
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            async def aiter_bytes(self): yield b"\x89PNG\r\n\x1a\nfixture"
        calls = []
        class Client:
            def __init__(self, **kwargs): calls.append(kwargs)
            async def __aenter__(self): return self
            async def __aexit__(self, *args): pass
            def stream(self, method, url): calls.append((method,url)); return Response()
        with patch("httpx2.AsyncClient", Client):
            self.assertIsNone(await download_slack_avatar("https://untrusted.invalid/photo"))
            self.assertEqual(calls, [])
            self.assertTrue((await download_slack_avatar(URL)).startswith("data:image/png;base64,"))
        self.assertFalse(calls[0]["follow_redirects"])
        self.assertFalse(calls[0]["trust_env"])
        self.assertNotIn("headers", calls[0])
        self.assertEqual(calls[1], ("GET", URL))


class SlackProfileCoreTests(unittest.IsolatedAsyncioTestCase):
    setUp = extension.SlackCoreTests.setUp
    make_core = extension.SlackCoreTests.make_core
    asyncTearDown = extension.SlackCoreTests.asyncTearDown
    until = extension.SlackCoreTests.until

    async def setup_profile(self, *, missing_scope=False):
        self.core.poll_interval = 999
        await self.core.dispatch({"op":"connect"})
        self.profile_calls = []
        original = self.backend.call
        def call(method, **params):
            if method == "users.info":
                self.profile_calls.append(params)
                if missing_scope: raise AppError("MISSING_SCOPE")
                return PROFILE
            return original(method, **params)
        self.backend.call = call
        self.core.slack_avatar_fetcher = AsyncMock(return_value="data:image/png;base64,fixture")
        message = self.core.messages(self.record.id)["messages"][0]
        return {"op":"slack_profile", "conversationId": self.record.id, "messageId": message["id"]}

    async def test_known_author_is_deduplicated_cached_and_not_written_plaintext(self):
        request = await self.setup_profile()
        self.assertTrue((await self.core.dispatch(request))["pending"])
        self.assertTrue((await self.core.dispatch(request))["pending"])
        await self.until(lambda: not self.core.slack_profile_tasks)
        result = await self.core.dispatch(request)
        self.assertEqual(result["name"], "PROFILE_NAME_CANARY")
        self.assertTrue(result["image"].startswith("data:"))
        self.assertFalse(result["pending"])
        self.assertEqual(self.profile_calls, [{"user":"U002"}])
        self.assertEqual(self.core.slack_avatar_fetcher.await_count, 1)
        for private in ["PRIVATE_EMAIL_CANARY", "PRIVATE_STATUS_CANARY", URL, "U002"]:
            self.assertNotIn(private, json.dumps(result))
        self.assertNotIn(b"PROFILE_NAME_CANARY", self.path.read_bytes())

    async def test_missing_scope_is_explicit_without_stopping_messages_or_repeated_lookups(self):
        request = await self.setup_profile(missing_scope=True)
        await self.core.dispatch(request)
        await self.until(lambda: not self.core.slack_profile_tasks)
        self.assertEqual((await self.core.dispatch(request))["errorCode"], "MISSING_SCOPE")
        self.assertEqual(self.core.snapshot()["profileErrorCode"], "MISSING_SCOPE")
        self.assertEqual(self.core.connection, "connected")
        self.assertEqual(len(self.core.messages(self.record.id)["messages"]), 1)
        self.assertEqual(len(self.profile_calls), 1)
        self.assertEqual(self.core.slack_avatar_fetcher.await_count, 0)

    async def test_arbitrary_user_url_or_unknown_message_cannot_be_requested(self):
        request = await self.setup_profile()
        for bad in ({**request, "user":"U999"}, {**request, "url":URL},
                    {**request, "messageId":"f"*64}, {**request, "conversationId": "f"*64}):
            with self.assertRaises(AppError): await self.core.dispatch(bad)
        self.assertEqual(self.profile_calls, [])

    async def test_storage_pause_cancels_pending_profile_and_clears_images(self):
        request = await self.setup_profile()
        gate = asyncio.Event()
        async def wait_for_image(url):
            gate.set()
            await asyncio.Event().wait()
        self.core.slack_avatar_fetcher = wait_for_image
        await self.core.dispatch(request)
        await asyncio.wait_for(gate.wait(), 2)
        await self.core.dispatch({"op":"storage_pause","paused":True})
        self.assertFalse(self.core.slack_profile_tasks)
        self.assertFalse(self.core.slack_profiles)
        self.assertFalse((await self.core.dispatch(request))["pending"])
        self.assertIsNone((await self.core.dispatch(request))["image"])

    async def test_dm_title_and_image_use_the_same_scoped_profile(self):
        await self.setup_profile()
        request = {"op":"slack_profile", "conversationId":self.other.id}
        self.assertEqual(next(v for v in self.core.snapshot()["conversations"] if v["id"]==self.other.id)["avatarVersion"], "slack-profile")
        await self.core.dispatch(request)
        await self.until(lambda: not self.core.slack_profile_tasks)
        self.assertEqual(next(v for v in self.core.snapshot()["conversations"] if v["id"]==self.other.id)["title"], "PROFILE_NAME_CANARY")
        self.assertTrue((await self.core.dispatch(request))["image"])
