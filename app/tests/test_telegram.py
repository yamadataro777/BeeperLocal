import unittest
from types import SimpleNamespace
from unittest.mock import patch
from beeperlocal.connectors.telegram import TelegramConnector, normalize_telegram
from beeperlocal.errors import AppError, telegram_error
from beeperlocal.models import Conversation
from .support import MemoryStore, telegram_raw

TG_CONV = Conversation("100", "Test Telegram", "dm", {"kind": "user", "id": "100", "access_hash": "999"})

def tg_store():
    return MemoryStore({"telegram": {"schema_version": 1, "api_id": 1, "api_hash": "0" * 32,
                                     "session": "FAKE_SESSION", "account_id": "1",
                                     "selections": [TG_CONV.selection()]}})

class FakeClient:
    def __init__(self, raws=None, authorized=True, account=1, failure=None):
        self.raws = raws or []
        self.authorized = authorized
        self.account = account
        self.failure = failure
        self.disconnected = False
        self.session = SimpleNamespace(save=lambda: "FAKE_SESSION")
    async def connect(self):
        if self.failure:
            raise self.failure
    async def is_user_authorized(self):
        return self.authorized
    async def get_me(self):
        return SimpleNamespace(id=self.account, bot=False)
    async def disconnect(self):
        self.disconnected = True
    async def iter_messages(self, peer, limit, wait_time):
        for raw in self.raws[:limit]:
            yield raw

class TelegramNormalizationTests(unittest.TestCase):
    def test_normalize_real_shape(self):
        m = normalize_telegram(telegram_raw(), "1", TG_CONV)
        self.assertEqual(m.provider, "telegram")
        self.assertEqual(m.provider_message_id, "1")
        self.assertEqual(m.direction, "incoming")
    def test_service_message_excluded(self):
        self.assertIsNone(normalize_telegram(telegram_raw(action=object()), "1", TG_CONV))
    def test_empty_message_excluded(self):
        self.assertIsNone(normalize_telegram(telegram_raw(message=None), "1", TG_CONV))
    def test_media_only_preserved(self):
        m = normalize_telegram(telegram_raw(message=None, media=object()), "1", TG_CONV)
        self.assertEqual(m.attachment_count, 1)
    def test_missing_date_rejected(self):
        with self.assertRaises(ValueError):
            normalize_telegram(telegram_raw(date=None), "1", TG_CONV)
    def test_reply_preserved(self):
        m = normalize_telegram(telegram_raw(reply_to=SimpleNamespace(reply_to_msg_id=10)), "1", TG_CONV)
        self.assertEqual(m.reply_to_message_id, "10")
    def test_flood_error_is_safe(self):
        FloodWaitError = type("FloodWaitError", (Exception,), {})
        error = telegram_error(FloodWaitError("PRIVATE_SESSION_CANARY"))
        self.assertEqual(error.code, "RATE_LIMITED")
        self.assertNotIn("PRIVATE_SESSION_CANARY", str(error))

class TelegramConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def get_batch(self, client, store=None):
        connector = TelegramConnector(store or tg_store(), client_factory=lambda _: client)
        with patch.object(TelegramConnector, "peer_from_selection", return_value="fake-peer"):
            return await connector.fetch()
    async def test_fetch_50_and_disconnect(self):
        client = FakeClient([telegram_raw(i) for i in range(1, 70)])
        batch = await self.get_batch(client)
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.errors, [])
        self.assertTrue(client.disconnected)
    async def test_service_events_not_counted(self):
        raws = [telegram_raw(i, action=object()) for i in range(1, 11)] + [telegram_raw(i) for i in range(11, 61)]
        batch = await self.get_batch(FakeClient(raws))
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.excluded_events, 10)
    async def test_expired_session_blocks(self):
        client = FakeClient(authorized=False)
        batch = await self.get_batch(client)
        self.assertEqual(batch.errors, ["CREDENTIALS_INVALID"])
        self.assertTrue(client.disconnected)
    async def test_wrong_account_blocks(self):
        batch = await self.get_batch(FakeClient(account=999))
        self.assertEqual(batch.errors, ["ACCOUNT_CHANGED"])
    async def test_changed_session_saved_only_to_store(self):
        store = tg_store()
        client = FakeClient([telegram_raw()])
        client.session = SimpleNamespace(save=lambda: "NEW_FAKE_SESSION")
        await self.get_batch(client, store)
        self.assertEqual(store.records["telegram"]["session"], "NEW_FAKE_SESSION")
        self.assertEqual(store.writes, ["telegram"])
    async def test_no_selection_no_connection(self):
        store = tg_store(); store.records["telegram"]["selections"] = []
        batch = await self.get_batch(FakeClient(failure=AssertionError("must not connect")), store)
        self.assertEqual(batch.errors, ["NO_SELECTION"])
    async def test_malformed_message_reported(self):
        batch = await self.get_batch(FakeClient([telegram_raw(date=None)]))
        self.assertEqual(batch.normalization_errors, 1)
    async def test_duplicates_do_not_count(self):
        raws = [telegram_raw(1)] * 10 + [telegram_raw(i) for i in range(2, 51)]
        batch = await self.get_batch(FakeClient(raws))
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.duplicates_removed, 9)
    async def test_network_error_disconnects(self):
        client = FakeClient(failure=OSError("PRIVATE_SESSION_CANARY"))
        batch = await self.get_batch(client)
        self.assertEqual(batch.errors, ["NETWORK_ERROR"])
        self.assertTrue(client.disconnected)
