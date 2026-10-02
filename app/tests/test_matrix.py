import io
import unittest
from urllib.error import HTTPError, URLError

from beeperlocal.connectors.matrix import MatrixAPI, MatrixConnector, normalize_homeserver, normalize_matrix, NoRedirect
from beeperlocal.errors import AppError
from .support import MATRIX_CONV, matrix_store, matrix_message, FakeMatrixAPI, FakeOpener, Response


class MatrixNormalizationTests(unittest.TestCase):
    def test_normal_message(self):
        m = normalize_matrix(matrix_message(1), "@me:example.org", MATRIX_CONV)
        self.assertEqual(m.provider, "matrix")
        self.assertEqual(m.text, "fixture-1")
        self.assertEqual(m.direction, "incoming")

    def test_outgoing_direction(self):
        raw = matrix_message(1, sender="@me:example.org")
        self.assertEqual(normalize_matrix(raw, "@me:example.org", MATRIX_CONV).direction, "outgoing")

    def test_non_message_excluded(self):
        raw = matrix_message(1, type="m.room.member")
        self.assertIsNone(normalize_matrix(raw, "@me:example.org", MATRIX_CONV))

    def test_attachment_count(self):
        raw = matrix_message(1, content={"msgtype": "m.image", "body": "photo.jpg"})
        self.assertEqual(normalize_matrix(raw, "@me:example.org", MATRIX_CONV).attachment_count, 1)

    def test_reply(self):
        raw = matrix_message(1, content={"msgtype": "m.text", "body": "reply", "m.relates_to": {"m.in_reply_to": {"event_id": "$root"}}})
        self.assertEqual(normalize_matrix(raw, "@me:example.org", MATRIX_CONV).reply_to_message_id, "$root")

    def test_bad_timestamp_rejected(self):
        with self.assertRaises(ValueError):
            normalize_matrix(matrix_message(1, origin_server_ts="bad"), "@me:example.org", MATRIX_CONV)


class MatrixTransportTests(unittest.TestCase):
    def test_https_origin_only(self):
        self.assertEqual(normalize_homeserver("https://matrix.example.org/"), "https://matrix.example.org")
        for bad in ["http://matrix.example.org", "https://user@matrix.example.org", "https://matrix.example.org/path"]:
            with self.assertRaises(AppError):
                normalize_homeserver(bad)

    def test_token_only_in_authorization_header(self):
        opener = FakeOpener(Response({"user_id": "@me:example.org"}))
        api = MatrixAPI("https://matrix.example.org", "PRIVATE_TOKEN_CANARY", opener=opener)
        api.get("/_matrix/client/v3/account/whoami")
        req = opener.requests[0]
        self.assertNotIn("PRIVATE_TOKEN_CANARY", req.full_url)
        self.assertIn("PRIVATE_TOKEN_CANARY", req.get_header("Authorization"))

    def test_redirect_handler_blocks(self):
        self.assertIsNone(NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))

    def test_401_redacted(self):
        err = HTTPError("https://matrix.example.org/_matrix/client/v3/account/whoami", 401, "PRIVATE", {}, io.BytesIO(b"PRIVATE"))
        api = MatrixAPI("https://matrix.example.org", "SECRET", opener=FakeOpener(err))
        with self.assertRaises(AppError) as ctx:
            api.get("/_matrix/client/v3/account/whoami")
        self.assertEqual(ctx.exception.code, "CREDENTIALS_INVALID")
        self.assertNotIn("PRIVATE", str(ctx.exception))

    def test_network_error_redacted(self):
        api = MatrixAPI("https://matrix.example.org", "SECRET", opener=FakeOpener(URLError("SECRET")))
        with self.assertRaises(AppError) as ctx:
            api.get("/_matrix/client/v3/account/whoami")
        self.assertEqual(ctx.exception.code, "NETWORK_ERROR")


class MatrixConnectorTests(unittest.IsolatedAsyncioTestCase):
    async def test_fetch_50(self):
        api = FakeMatrixAPI(pages=[{"chunk": [matrix_message(i) for i in range(50)], "end": "next"}])
        batch = await MatrixConnector(matrix_store(), api=api).fetch()
        self.assertEqual(len(batch.messages), 50)
        self.assertEqual(batch.errors, [])
        self.assertEqual(batch.conversations_fetched, 1)

    async def test_paginates_until_50(self):
        api = FakeMatrixAPI(pages=[
            {"chunk": [matrix_message(i) for i in range(25)], "end": "p2"},
            {"chunk": [matrix_message(i) for i in range(25, 50)], "end": "p3"},
        ])
        batch = await MatrixConnector(matrix_store(), api=api).fetch()
        self.assertEqual(len(batch.messages), 50)
        calls = [(p, q) for p, q in api.calls if "/messages" in p]
        self.assertNotIn("from", calls[0][1])
        self.assertEqual(calls[1][1]["from"], "p2")

    async def test_repeated_end_stops(self):
        api = FakeMatrixAPI(pages=[
            {"chunk": [matrix_message(1)], "end": "same"},
            {"chunk": [matrix_message(2)], "end": "same"},
        ])
        batch = await MatrixConnector(matrix_store(), api=api).fetch()
        self.assertIn("PAGINATION_STALLED", batch.errors)

    async def test_account_change_blocks(self):
        api = FakeMatrixAPI(whoami={"user_id": "@other:example.org"})
        batch = await MatrixConnector(matrix_store(), api=api).fetch()
        self.assertEqual(batch.errors, ["ACCOUNT_CHANGED"])

    async def test_encrypted_selection_blocked(self):
        encrypted = MATRIX_CONV.__class__(MATRIX_CONV.id, MATRIX_CONV.title, "encrypted-room", MATRIX_CONV.locator)
        batch = await MatrixConnector(matrix_store([encrypted.selection()]), api=FakeMatrixAPI()).fetch()
        self.assertEqual(batch.errors, ["MATRIX_ENCRYPTED_ROOM"])

    async def test_list_marks_encryption(self):
        sync = {"rooms": {"join": {
            "!plain:example.org": {"state": {"events": [{"type": "m.room.name", "content": {"name": "Plain"}}]}},
            "!enc:example.org": {"state": {"events": [{"type": "m.room.encryption", "content": {"algorithm": "m.megolm.v1.aes-sha2"}}]}},
        }}}
        choices = await MatrixConnector(matrix_store(), api=FakeMatrixAPI(sync=sync)).list_conversations()
        kinds = {c.id: c.kind for c in choices}
        self.assertEqual(kinds["!plain:example.org"], "room")
        self.assertEqual(kinds["!enc:example.org"], "encrypted-room")
