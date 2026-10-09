from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from beeperlocal.models import UnifiedMessage, Conversation, StoredConversation
from beeperlocal.outbox import OutgoingRequest
from beeperlocal.storage import EncryptedMessageStore


class DeletionTests(unittest.TestCase):
    def test_each_provider_deletes_only_its_account_and_retires_requests(self):
        for provider in ('line', 'slack', 'instagram', 'x', 'messenger'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as folder:
                db = EncryptedMessageStore(b'd' * 32, Path(folder).resolve() / 'private/db')
                try:
                    now = datetime.now(timezone.utc)
                    record = StoredConversation(provider, 'ACCOUNT', Conversation('CHAT', 'CANARY_TITLE', 'dm', {}))
                    message = UnifiedMessage(provider, 'ACCOUNT', 'CHAT', 'MSG', 'SENDER', now, 'CANARY_BODY')
                    other = replace(message, account_id='OTHER')
                    sibling = replace(message, provider='slack' if provider != 'slack' else 'line')
                    request = OutgoingRequest(str(uuid4()), provider, 'ACCOUNT', 'CHAT', 'CANARY_OUTBOX', 'unknown', now)
                    db.upsert([message, other, sibling], conversations=[record], outgoing_requests=[request])
                    db.private_put('sync.v1.' + record.id, {'cursor': 'CANARY_CURSOR'})
                    db.private_put('messenger.registered_account', 'ACCOUNT')
                    counts = db.provider_data_counts(provider, 'ACCOUNT')
                    deleted = db.clear_provider_data(provider, 'ACCOUNT', private_updates={}, expected_counts=counts)
                    self.assertEqual(deleted['messages'], 1)
                    self.assertIsNone(db.get_message(message.id))
                    self.assertIsNotNone(db.get_message(other.id)); self.assertIsNotNone(db.get_message(sibling.id))
                    self.assertTrue(db.request_retired(request.request_id))
                    self.assertIsNone(db.private_get('sync.v1.' + record.id))
                    self.assertEqual(db.private_get('messenger.registered_account'), 'ACCOUNT')
                finally:
                    db.close()
