"""Synthetic rasters, encrypted stores and fake provider ACKs; no live sends."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from urllib.error import HTTPError, URLError

from PIL import Image, PngImagePlugin
from beeperlocal.connectors.slack import SlackAPI, normalize_slack
from beeperlocal.desktop import DesktopCore
from beeperlocal.desktop_instagram import InstagramDesktop
from beeperlocal.desktop_slack import SlackDesktop
from beeperlocal.desktop_x import XDesktop
from beeperlocal.desktop_messenger import MessengerDesktop
from beeperlocal.errors import AppError
from beeperlocal.models import Conversation, StoredConversation, UnifiedMessage, SendResult
from beeperlocal.outgoing_images import decode_image, image_from_wire
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore, FakeOpener, Response


def raster(format='PNG', size=(12, 8), color='tomato', metadata=False):
    picture = Image.new('RGB', size, color)
    stream = BytesIO()
    kwargs = {}
    if metadata:
        if format == 'PNG':
            info = PngImagePlugin.PngInfo(); info.add_text('Location', 'PRIVATE_GPS_CANARY')
            kwargs['pnginfo'] = info
        else:
            exif = Image.Exif(); exif[0x010e] = 'PRIVATE_GPS_CANARY'; exif[0x0112] = 6
            kwargs['exif'] = exif
    picture.save(stream, format=format, **kwargs)
    return stream.getvalue()


def uri(data=None, mime='image/png'):
    return 'data:' + mime + ';base64,' + base64.b64encode(data or raster()).decode()


class RasterTests(unittest.TestCase):
    def test_png_and_jpeg_strip_metadata_and_apply_orientation(self):
        for format, mime in [('PNG', 'image/png'), ('JPEG', 'image/jpeg')]:
            raw = raster(format, metadata=True)
            result = decode_image(uri(raw, mime))
            self.assertEqual(result.digest, sha256(raw).hexdigest())
            self.assertNotIn(b'PRIVATE_GPS_CANARY', result.data)
            self.assertEqual((result.width, result.height), (8, 12) if format == 'JPEG' else (12, 8))
            self.assertEqual(image_from_wire(result.wire()).data, result.data)
            self.assertTrue(result.preview.startswith('data:image/'))

    def test_mismatched_types_limits_and_damaged_files_rejected(self):
        for value in [None, uri(b'invalid'), uri(raster(), 'image/jpeg'), 'file:///tmp/private',
                      'data:image/svg+xml;base64,PHN2Zz4=', uri(raster('GIF')),
                      uri(raster(size=(16385, 1))), uri(b'x' * (4*1024*1024 + 1))]:
            with self.subTest(kind=type(value).__name__), self.assertRaises(AppError):
                decode_image(value)
        value = decode_image(uri()).wire()
        with self.assertRaises(AppError): image_from_wire({**value, 'width': 999})
        with self.assertRaises(AppError): image_from_wire({**value, 'height': True})


CLASSES = {'line': DesktopCore, 'instagram': InstagramDesktop, 'slack': SlackDesktop, 'x': XDesktop, 'messenger': MessengerDesktop}


class ImageCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cores = []

    async def asyncTearDown(self):
        for core in self.cores: await core.close()
        self.tmp.cleanup()

    def core(self, provider, suffix=''):
        path = Path(self.tmp.name).resolve() / (provider + suffix) / 'messages.sqlite3'
        conv = Conversation('fixture-chat', 'PRIVATE_RECIPIENT_CANARY', 'dm', {})
        record = StoredConversation(provider, 'fixture-account', conv)
        credentials = MemoryStore({provider: {'account_id': record.account_id, 'selections': [conv.selection()]}})
        core = CLASSES[provider](credentials=credentials, db_factory=lambda: EncryptedMessageStore(b'k'*32, path))
        core._initialize()
        core.db.upsert([], conversations=[record])
        core.selected_id = record.id
        core.connection = 'connected'
        core.receiving = 'waiting'
        class Sender:
            account_id = record.account_id
            catalog_limited = False
            calls = 0
            request_id = None
            error = None
            async def connect(self): pass
            def selected_conversation(self): return conv
            async def send_image_to(sender, selected, image, *, authorize):
                authorize()
                saved = core.db.get_outgoing(sender.request_id)
                self.assertEqual(saved.status, 'sending')
                self.assertEqual(saved.image_digest, image.digest)
                sender.calls += 1
                if sender.error: raise sender.error
                message = UnifiedMessage(provider, record.account_id, conv.id, 'fixture-ack', 'fixture-account',
                    datetime.now(timezone.utc), '', conv.title, direction='outgoing', attachment_count=1)
                return SendResult(message, encrypted=provider in {'line', 'x', 'messenger'})
        core.connector = Sender()
        self.cores.append(core)
        return core, record

    async def send(self, core, record, *, request_id=None, data=None):
        identity = request_id or str(uuid4())
        core.connector.request_id = identity
        return await core.dispatch({'op': 'send_image', 'conversationId': record.id, 'dataUrl': data or uri(), 'requestId': identity})

    async def test_all_five_provider_dispatches_durable_once_and_offline_encrypted_preview(self):
        for provider in CLASSES:
            with self.subTest(provider=provider):
                core, record = self.core(provider)
                request_id = str(uuid4())
                ack = await self.send(core, record, request_id=request_id)
                self.assertEqual(ack['status'], 'acknowledged')
                again = await self.send(core, record, request_id=request_id)
                self.assertTrue(again['duplicateSuppressed'])
                self.assertEqual(core.connector.calls, 1)
                core.connection = 'offline'
                view = core.messages(record.id)['messages'][0]
                self.assertTrue(view['attachments'][0]['local'])
                media = core.attachment_media(record.id, view['id'], 0, False)
                self.assertTrue(media['media'].startswith('data:image/'))
                preview = media['media']
                self.assertNotIn(preview.encode(), core.db.path.read_bytes())
                self.assertNotIn(b'PRIVATE_RECIPIENT_CANARY', core.db.path.read_bytes())
                core.db.close(); core.db = EncryptedMessageStore(b'k'*32, core.db.path)
                self.assertEqual(core.attachment_media(record.id, view['id'], 0, False)['media'], preview)
                core.connection = 'connected'
                self.assertTrue((await self.send(core, record, request_id=request_id))['duplicateSuppressed'])
                with self.assertRaises(AppError):
                    await self.send(core, record, request_id=request_id, data=uri(raster(color='blue')))
                self.assertEqual(core.connector.calls, 1)

    async def test_unknown_send_cannot_replay_and_digest_survives_snapshot(self):
        for provider in CLASSES:
            core, record = self.core(provider)
            core.connector.error = AppError(core.send_unknown)
            request_id = str(uuid4())
            for _ in range(2):
                with self.assertRaises(AppError): await self.send(core, record, request_id=request_id)
            self.assertEqual(core.connector.calls, 1)
            self.assertEqual(core.db.get_outgoing(request_id).status, 'unknown')
            self.assertEqual(core.snapshot()['pendingSends'][0]['imageDigest'], sha256(raster()).hexdigest())
            self.assertEqual(core.db.total_count(), 0)

    async def test_pause_target_and_invalid_image_block_before_network(self):
        core, record = self.core('line')
        core.settings['storagePaused'] = True
        with self.assertRaises(AppError): await self.send(core, record)
        core.settings['storagePaused'] = False
        core.selected_id = None
        with self.assertRaises(AppError): await self.send(core, record)
        core.selected_id = record.id
        with self.assertRaises(AppError): await self.send(core, record, data=uri(b'invalid'))
        self.assertEqual(core.connector.calls, 0)
        self.assertEqual(core.db.pending_outgoing(record.account_id, provider='line'), [])

    async def test_delete_removes_local_image_and_preserves_retired_request(self):
        core, record = self.core('line')
        request_id = str(uuid4())
        ack = await self.send(core, record, request_id=request_id)
        core.db.clear_provider_data('line', record.account_id, private_updates={})
        self.assertIsNone(core.db.private_get('image.v1.' + ack['messageId']))
        self.assertTrue(core.db.request_retired(request_id))


class UploadResponse(BytesIO):
    status = 200


class SlackImageTests(unittest.TestCase):
    def test_three_step_share_scoped_and_tokens_never_forwarded_to_upload(self):
        opener = FakeOpener(Response({'ok': True, 'file_id': 'F123', 'upload_url': 'https://files.slack.com/upload/v1/fixture'}),
                            UploadResponse(b'ok'), Response({'ok': True, 'files': [{'id': 'F123'}]}))
        image = decode_image(uri())
        result = SlackAPI('xoxp-synthetic-token', opener=opener).upload_image(channel='C123', image=image)
        self.assertEqual(result, 'F123')
        self.assertEqual(len(opener.requests), 3)
        self.assertNotIn('synthetic-token', opener.requests[1].full_url)
        self.assertIsNone(opener.requests[1].get_header('Authorization'))
        self.assertEqual(opener.requests[1].data, image.data)
        self.assertEqual(json.loads(opener.requests[2].data), {'files': [{'id': 'F123', 'title': 'image.png'}], 'channel_id': 'C123'})
        self.assertTrue(all(r.get_method() == 'POST' for r in opener.requests))

    def test_upload_failure_redirect_and_scope_do_not_retry(self):
        initial = lambda: Response({'ok': True, 'file_id': 'F123', 'upload_url': 'https://files.slack.com/upload/v1/fixture'})
        cases = [(Response({'ok': False, 'error': 'missing_scope'}), 1, 'SLACK_IMAGE_SCOPE_REQUIRED'),
                 (Response({'ok': True, 'file_id': 'F123', 'upload_url': 'https://untrusted.invalid/upload/x'}), 1, 'SLACK_SEND_UNKNOWN')]
        for response, calls, code in cases:
            opener = FakeOpener(response)
            with self.assertRaises(AppError) as error:
                SlackAPI('xoxp-fixture', opener=opener).upload_image(channel='C123', image=decode_image(uri()))
            self.assertEqual(error.exception.code, code); self.assertEqual(len(opener.requests), calls)
        for failure in [URLError('PRIVATE_CANARY'), HTTPError('https://files.slack.com/upload/x', 307, 'PRIVATE_CANARY', {}, BytesIO())]:
            opener = FakeOpener(initial(), failure)
            with self.assertRaises(AppError) as error:
                SlackAPI('xoxp-fixture', opener=opener).upload_image(channel='C123', image=decode_image(uri()))
            self.assertEqual(str(error.exception), str(AppError('SLACK_SEND_UNKNOWN')))
            self.assertEqual(len(opener.requests), 2)

    def test_provisional_share_merges_with_history_without_other_scope_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            db = EncryptedMessageStore(b'k'*32, Path(folder).resolve()/'state/messages.sqlite3')
            self.addCleanup(db.close)
            conv = Conversation('C001', 'Fixture', 'channel', {'channel_id': 'C001'})
            record = StoredConversation('slack', 'T001:U001', conv)
            provisional = UnifiedMessage('slack', record.account_id, conv.id, 'file:F123', 'U001', datetime.now(timezone.utc), '',
                conv.title, direction='outgoing', attachment_count=1, attachments=[{'kind': 'image', 'file_id': 'F123', 'url': ''}])
            other = replace(provisional, account_id='T002:U001')
            db.upsert([provisional, other], conversations=[record], private_updates={'image.v1.'+provisional.id: 'private-preview'})
            actual = replace(provisional, provider_message_id='1700000000.000001')
            db.upsert([actual], conversations=[record])
            self.assertIsNone(db.get_message(provisional.id))
            self.assertIsNotNone(db.get_message(other.id))
            self.assertEqual(db.private_get('image.v1.'+actual.id), 'private-preview')
            self.assertIsNone(db.private_get('image.v1.'+provisional.id))
