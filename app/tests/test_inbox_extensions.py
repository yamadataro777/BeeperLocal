"""New inbox behavior against synthetic provider pages and the real X crypto SDK."""
import asyncio
import base64
from contextlib import aclosing, nullcontext
from copy import deepcopy
from dataclasses import replace
from io import BytesIO
import importlib.util
from pathlib import Path
import struct
import unittest
from unittest.mock import patch

from beeperlocal.desktop_media import allowed_attachment_url, attachment_preview, download_attachment
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from beeperlocal.xcrypto.core import conversation_members, deletion_rules, verified_messages, ConnectorError
from . import test_desktop_messenger as ms
from . import test_desktop_sync as sync
from . import test_x_crypto as x
from .test_line_media import png
from .test_instagram import InstagramConnector, FakeAdapter, store as ig_store, history as ig_history, message as ig_message, conversation, CONVERSATION
from .test_slack_extension import SlackBackend, SlackConnector, slack_store, CONV, slack_message


class AttachmentTests(unittest.IsolatedAsyncioTestCase):
    def test_private_hosts_credentials_ports_and_scripts_cannot_be_rendered(self):
        for provider in ('x','instagram'):
            for bad in ('http://cdninstagram.com/a','https://127.0.0.1/a','file:///etc/passwd','https://cdninstagram.com.evil.test/a','https://fbcdn.net@evil.test/a','https://user:secret@pbs.twimg.com/a','https://pbs.twimg.com:44/a','https://pbs.twimg.com/a#fragment', None):
                self.assertFalse(allowed_attachment_url(provider,bad))
        self.assertTrue(allowed_attachment_url('instagram','https://scontent.xx.fbcdn.net/a?sig=fixture'))
        self.assertTrue(allowed_attachment_url('x','https://pbs.twimg.com/media/a'))
        for kind in ('video','audio','file'):
            self.assertIsNone(attachment_preview(b'<svg><script>bad</script></svg>',kind))
        self.assertIsNone(attachment_preview(b'x'*(4*1024*1024+1),'image'))
        self.assertTrue(attachment_preview(png(),'image').startswith('data:image/png;base64,'))
        self.assertTrue(attachment_preview(b'RIFF1234WAVEfixture','audio').startswith('data:audio/wav;'))

    async def test_download_has_no_redirect_proxy_or_unbounded_body(self):
        class Response:
            status_code=200
            body=png()
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def aiter_bytes(self): yield self.body
        response=Response(); calls=[]
        class Client:
            def __init__(self,**kwargs): calls.append(kwargs)
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def stream(self,*args): return response
        with patch('httpx2.AsyncClient',Client):
            self.assertIsNone(await download_attachment('x',{'url':'https://localhost/private'}))
            self.assertEqual(calls,[])
            self.assertEqual(await download_attachment('instagram',{'url':'https://a.fbcdn.net/fixture'}),response.body)
            self.assertFalse(calls[0]['follow_redirects']); self.assertFalse(calls[0]['trust_env'])
            response.status_code=302
            self.assertIsNone(await download_attachment('instagram',{'url':'https://a.fbcdn.net/fixture'}))
            response.status_code=200; response.body=b'x'*(4*1024*1024+1)
            self.assertIsNone(await download_attachment('instagram',{'url':'https://a.fbcdn.net/fixture'}))


class ProviderPagesTests(unittest.IsolatedAsyncioTestCase):
    async def test_ig_group_pages_keep_cursor_media_and_provenance(self):
        group={**CONVERSATION,'kind':'group'}
        m=ig_message(attachments=[{'kind':'image','url':'https://a.fbcdn.net/fixture'}])
        connector=InstagramConnector(ig_store(),adapter=FakeAdapter(ig_history(m,conversation=group,next_cursor='older',page_complete=False)))
        page=await connector.fetch_page(conversation(group))
        self.assertEqual(page.cursor,{'after':'older'}); self.assertFalse(page.complete)
        self.assertEqual(page.record.conversation.kind,'group')
        self.assertEqual(page.messages[0].attachments[0]['kind'],'image')
        connector.adapter=FakeAdapter(ig_history(ig_message(id='older'),conversation=group,next_cursor='',page_complete=True))
        last=await connector.fetch_page(conversation(group),cursor=page.cursor)
        self.assertTrue(last.complete); self.assertIsNone(last.cursor)
        self.assertEqual(connector.adapter.requests[0]['cursor'],'older')

    async def test_ig_account_stream_routes_other_group_and_explicit_deletion(self):
        other=conversation({**CONVERSATION,'id':'888999','kind':'group'})
        adapter=FakeAdapter({'type':'message','source':'realtime','message':ig_message(thread_id=other.id)},
            {'type':'change','action':'delete','thread_id':other.id,'message_id':'fixture-deleted'}, {'type':'done'})
        connector=InstagramConnector(ig_store(),adapter=adapter); connector.catalog[other.id]=other
        changes=[]
        async with aclosing(connector.watch(from_now=True,all_conversations=True,on_change=lambda c,e:changes.append((c,e)))) as stream:
            rows=[row async for row in stream]
        self.assertEqual(rows[0].conversation_id,other.id)
        self.assertEqual(changes[0][0],other)
        self.assertTrue(adapter.requests[0]['all_conversations'])

    async def test_slack_history_threads_continue_before_next_channel_page(self):
        backend=SlackBackend(); connector=SlackConnector(slack_store(),api=backend)
        root=slack_message(reply_count=2); backend.rows=[root]
        original=backend.call
        def call(method,**kw):
            if method=='conversations.history': return {'messages':[root], 'response_metadata':{'next_cursor':'older-channel'}}
            return original(method,**kw)
        backend.call=call
        page=await connector.fetch_page(CONV)
        self.assertEqual(page.cursor['thread'],root['ts'])
        self.assertIsNone(page.followup['history'])
        backend.replies=[{'messages':[root,slack_message(1,thread_ts=root['ts'])], 'response_metadata':{'next_cursor':'older-thread'}}, {'messages':[slack_message(2,thread_ts=root['ts'])]}]
        next_page=await connector.fetch_page(CONV,cursor=page.cursor)
        self.assertEqual(next_page.cursor['thread_cursor'],'older-thread')
        last=await connector.fetch_page(CONV,cursor=next_page.cursor)
        self.assertEqual(last.cursor,{'cursor':'older-channel'})
        self.assertEqual(last.messages[0].reply_to_message_id,root['ts'])
        self.assertFalse(last.complete)

    async def test_slack_tombstone_does_not_become_blank_message(self):
        backend=SlackBackend(); backend.rows=[{'subtype':'message_deleted','deleted_ts':slack_message()['ts']}]
        page=await SlackConnector(slack_store(),api=backend).fetch_page(CONV)
        self.assertEqual(page.messages,[]); self.assertEqual(page.deletions,[slack_message()['ts']])


class RecentFollowupTests(unittest.IsolatedAsyncioTestCase):
    setUp=sync.SyncTests.setUp
    asyncTearDown=sync.SyncTests.asyncTearDown
    until=sync.SyncTests.until
    msg=sync.SyncTests.msg
    async def test_known_parent_does_not_skip_new_replies_and_old_backfill_stays_read(self):
        r=self.records[0]; self.core.db.private_put(self.core.catalog_key(),[r.id])
        self.core.ingest([self.msg(1)],records=[r],historical=True)
        def page(c,cursor):
            if cursor: return sync.HistoryPage(r,[self.msg(1),self.msg(2)],complete=True)
            return sync.HistoryPage(r,[self.msg(1)],cursor={'thread':'fixture'},followup={'thread':'fixture'})
        self.page=page; self.core.start_all_sync()
        await self.until(lambda:self.core.db.total_count()==2)
        self.assertEqual(self.core.snapshot()['unreadCount'],1)


class MessengerRevokeTests(unittest.IsolatedAsyncioTestCase):
    setUp=ms.DesktopTests.setUp
    make_core=ms.DesktopTests.make_core
    asyncTearDown=ms.DesktopTests.asyncTearDown
    async def test_revoke_before_body_is_durable_and_wrong_author_cannot_delete(self):
        await self.core.dispatch({'op':'connect'})
        self.core._persist(ms.checkpoint(deletions=[{'conversation':ms.CHAT,'id':'later','sender':ms.CHAT}]),ms.ACCOUNT)
        self.core._persist(ms.checkpoint(ms.message(id='later')),ms.ACCOUNT)
        self.assertEqual(self.core.db.total_count(),1)
        self.core._persist(ms.checkpoint(deletions=[{'conversation':ms.CHAT,'id':'fixture-message-1','sender':ms.ACCOUNT+'@msgr'}]),ms.ACCOUNT)
        self.assertEqual(self.core.db.total_count(),1)
        self.core._persist(ms.checkpoint(deletions=[{'conversation':ms.CHAT,'id':'fixture-message-1','sender':ms.CHAT}]),ms.ACCOUNT)
        self.assertEqual(self.core.db.total_count(),0)
        self.core._persist(ms.checkpoint(ms.message()),ms.ACCOUNT)
        self.assertEqual(self.core.db.total_count(),0)
        identity=self.core._records()[0].id
        preview=await self.core.deletion_preview(); await self.core.delete_local_data(preview['confirmation'])
        self.assertIsNone(self.core.db.private_get('delete.v1.'+identity))

    async def test_local_deletion_does_not_touch_device_keychain(self):
        await self.core.dispatch({'op': 'connect'})
        self.session.clear_local_cache = lambda *args: self.fail('local deletion must not rewrite device')
        preview = await self.core.deletion_preview()
        await self.core.delete_local_data(preview['confirmation'])
        self.assertEqual(self.core.db.total_count(), 0)
        self.assertEqual(self.core.db.private_get('messenger.registered_account'), ms.ACCOUNT)


def string_field(n,value):
    raw=value.encode() if isinstance(value,str) else value
    return struct.pack('>bhi',11,n,len(raw))+raw

def event_envelope(conv,mid,detail,signature):
    return base64.b64encode(string_field(1,'1')+string_field(2,mid)+string_field(3,x.SELF)+string_field(4,conv)+string_field(6,'1790910000000')+struct.pack('>bh',12,7)+detail+struct.pack('>bh',12,9)+signature+b'\0').decode()


class XGroupCryptoTests(unittest.TestCase):
    def test_actual_sdk_group_message_media_authentication_and_scope(self):
        c=x.chat(); key=bytes(range(32)); conv='g123'
        members=conversation_members(conv,x.SELF,{'conversation_id':conv,'participants_results':[{'rest_id':x.SELF},{'rest_id':x.PEER}]})
        p=c.encrypt_message(conv,'fixture',conversation_key=key,conversation_key_version='1',attachments=[{'attachment_type':'media','media_type':1,'media_hash_key':'fixturehash','filename':'fixture.png','width':10,'height':10,'filesize_bytes':24}])
        raw=event_envelope(conv,p.message_id,struct.pack('>bh',12,1)+base64.b64decode(p.encrypted_content)+b'\0',base64.b64decode(p.encoded_event_signature))
        event=c.decrypt_event(raw,{'1':key})
        rows=verified_messages([event],conv,x.SELF,members)
        self.assertEqual(rows[0]['attachments'][0],{'kind':'image','name':'fixture.png','media_hash_key':'fixturehash','key_version':'1'})
        with self.assertRaises(ConnectorError): verified_messages([event],'g124',x.SELF,members)
        with self.assertRaises(ConnectorError): conversation_members(conv,x.SELF,{'conversation_id':conv,'participants_results':[{'rest_id':x.PEER}]})
        data=c.encrypt_stream(png(),key)
        self.assertEqual(c.decrypt_stream(data,key),png())
        for corrupt in (data[:-1],data[:-1]+bytes([data[-1]^1])):
            with self.assertRaises(Exception): c.decrypt_stream(corrupt,key)

    def test_actual_sdk_signed_delete_and_unverified_rejection(self):
        c=x.chat(); d=c.prepare_message_delete(x.CONV,['1'],True)
        signature=string_field(1,d['signature'])+string_field(2,d['public_key_version'])+string_field(3,d['signature_version'])+b'\0'
        raw=event_envelope(x.CONV,d['message_id'],base64.b64decode(d['encoded_message_event_detail']),signature)
        event=c.decrypt_event(raw)
        self.assertEqual(deletion_rules([event],x.CONV,x.SELF,[x.SELF,x.PEER]),[{'actor':x.SELF,'sequences':['1'],'all':True}])
        with self.assertRaises(ConnectorError): deletion_rules([{**event,'verified':False}],x.CONV,x.SELF,[x.SELF,x.PEER])


class XDeletionPersistenceTests(unittest.TestCase):
    setUp=x.StorageTests.setUp
    tearDown=x.StorageTests.tearDown
    def test_deleted_body_never_returns_from_replayed_backfill_and_retired_send_keeps_no_body(self):
        row=verified_messages(x.events(),x.CONV,x.SELF)[0]
        self.connector._commit(x.CONV,[row],[],None,{})
        self.connector._commit(x.CONV,[],[],None,{},rules=[{'actor':x.PEER,'sequences':[row['sequence_id']],'all':True}])
        self.assertEqual(len(self.connector.messages(x.CONV)),1)
        self.connector._commit(x.CONV,[],[],None,{},rules=[{'actor':x.SELF,'sequences':[row['sequence_id']],'all':True}])
        self.connector._commit(x.CONV,[row],[],None,{})
        self.assertEqual(self.connector.messages(x.CONV),[])
        self.store.put('send:fixture',{'state':'unknown','text':'PRIVATE_CACHE_CANARY'})
        self.store.put('key-events:'+x.CONV,['signed-envelope']); self.store.put('key-floor:'+x.CONV,2)
        self.store.clear_message_data()
        self.assertEqual(self.store.get('send:fixture'),{'state':'retired'})
        self.assertEqual(self.store.get('key-events:'+x.CONV),['signed-envelope'])
        self.assertEqual(self.store.get('key-floor:'+x.CONV),2)

class ReleaseSignerTests(unittest.TestCase):
    def test_actual_packager_matches_fixture_verified_by_rust_and_rejects_version_injection(self):
        import json
        from hashlib import blake2b
        root=Path(__file__).resolve().parents[1]
        spec=importlib.util.spec_from_file_location('update_packager',root/'scripts/build-update.py')
        module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        fixture=json.loads((root/'tests/fixtures/update-signature.json').read_text())
        seed=bytes(range(32)); key_id=b'fixture1'
        self.assertEqual(module.public_key(seed,key_id),fixture['publicKey'])
        self.assertEqual(module.sign_digest(blake2b(fixture['body'].encode(),digest_size=64).digest(),seed,key_id,'0.0.2','fixture.tar.gz',1),fixture['signature'])
        for version in ('0.9.0\tversion:9.9.9','0.9.0\nprivate','latest'):
            with self.assertRaises(ValueError): module.sign_digest(bytes(64),seed,key_id,version,'fixture.tar.gz',1)

class SlackOldThreadTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_thread_inventory_survives_restart_and_recent_history_is_not_starved(self):
        backend=SlackBackend(); root=slack_message(reply_count=2); backend.rows=[root]
        connector=SlackConnector(slack_store(),api=backend)
        first=await connector.fetch_sync_page(CONV)
        self.assertEqual(first.poll_metadata['threads'],[root['ts']])
        # A different connector after restart uses only the persisted encrypted inventory.
        restored=SlackConnector(slack_store(),api=backend)
        backend.rows=[slack_message(20)]
        backend.replies=[{'messages':[root,slack_message(21,thread_ts=root['ts'])]}]
        second=await restored.fetch_sync_page(CONV,metadata=first.poll_metadata)
        self.assertEqual(second.messages[-1].reply_to_message_id,root['ts'])
        self.assertEqual(backend.calls[-1][0],'conversations.replies')
        third=await restored.fetch_sync_page(CONV,metadata=second.poll_metadata)
        self.assertEqual(backend.calls[-1][0],'conversations.history')
        self.assertEqual(third.messages[0].provider_message_id,slack_message(20)['ts'])
