"""Restart/offline cache regression tests using synthetic profiles only."""
import asyncio
from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from beeperlocal.desktop import DesktopCore
from beeperlocal.desktop_instagram import InstagramDesktop
from beeperlocal.desktop_profiles import profile_version
from beeperlocal.models import Conversation, StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore

PHOTO = 'data:image/png;base64,PRIVATE_PROFILE_CANARY'

class ProfilePersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_line_instagram_offline_restart_and_version_change(self):
        for provider, cls, locator in [('line', DesktopCore, {'picture_path': '/fixture/photo'}),
                ('instagram', InstagramDesktop, {'picture_url': 'https://scontent.cdninstagram.com/fixture/photo.jpg?token=1'})]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as folder:
                path = Path(folder).resolve() / 'private/messages.sqlite3'
                conv = Conversation('fixture', 'fixture', 'dm', locator)
                record = StoredConversation(provider, 'account', conv)
                credentials = MemoryStore({provider: {'account_id': 'account', 'selections': [conv.selection()]}})
                def make():
                    core = cls(credentials=credentials, db_factory=lambda: EncryptedMessageStore(b'k'*32, path))
                    core._initialize(); core.db.upsert([], conversations=[record]); return core
                core = make()
                core.connection = 'connected'; core.avatar_fetcher = AsyncMock(return_value=PHOTO)
                with patch('beeperlocal.desktop_profiles.download_raster', AsyncMock(return_value=PHOTO)):
                    self.assertTrue(core.avatar(record.id)['pending'])
                    await asyncio.gather(*list(core.avatar_tasks.values()))
                self.assertEqual(core.avatar(record.id)['image'], PHOTO)
                await core.close()
                core = make()
                try:
                    core.avatar_fetcher = AsyncMock(side_effect=AssertionError('network forbidden'))
                    self.assertEqual(core.avatar(record.id), {'image': PHOTO, 'pending': False})
                    self.assertNotIn(PHOTO.encode(), path.read_bytes())
                    self.assertFalse(core.avatar_tasks)
                    changed_locator = {'picture_path': '/fixture/new'} if provider == 'line' else {'picture_url': 'https://scontent.cdninstagram.com/fixture/new.jpg'}
                    core.db.upsert([], conversations=[replace(record, conversation=replace(conv, locator=changed_locator))])
                    self.assertIsNone(core.avatar(record.id)['image'])
                    core.db.clear_provider_data(provider, 'account', private_updates={})
                    self.assertIsNone(core.db.private_get('profile.v1.' + record.id))
                finally: await core.close()

    async def test_cache_bound_and_account_deletion_do_not_cross_accounts(self):
        with tempfile.TemporaryDirectory() as folder:
            db = EncryptedMessageStore(b'k'*32, Path(folder).resolve()/'private/messages.sqlite3')
            try:
                db.profile_cache_put('slack', 'other', 'slack-profile.v1.other', {'image': PHOTO})
                for n in range(130): db.profile_cache_put('slack', 'account', 'slack-profile.v1.' + str(n), {'image': PHOTO})
                self.assertIsNone(db.private_get('slack-profile.v1.0'))
                self.assertIsNotNone(db.private_get('slack-profile.v1.129'))
                db.clear_provider_data('slack', 'account', private_updates={})
                self.assertIsNone(db.private_get('slack-profile.v1.129'))
                self.assertIsNotNone(db.private_get('slack-profile.v1.other'))
            finally: db.close()

    def test_instagram_cdn_token_rotation_preserves_photo_version(self):
        first = {'picture_url': 'https://scontent.cdninstagram.com/fixture/photo.jpg?token=1'}
        second = {'picture_url': 'https://scontent.cdninstagram.com/fixture/photo.jpg?token=2'}
        self.assertIsNotNone(profile_version('instagram', first))
        self.assertEqual(profile_version('instagram', first), profile_version('instagram', second))
        self.assertIsNone(profile_version('instagram', {'picture_url': 'https://untrusted.invalid/photo.jpg'}))
