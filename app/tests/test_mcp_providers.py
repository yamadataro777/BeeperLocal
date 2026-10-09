"""Three new MCP providers: genuine Core/connector paths, synthetic remote transports only."""
import asyncio
from contextlib import asynccontextmanager, nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
import json
import logging
from pathlib import Path
import socket
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch, AsyncMock
from uuid import uuid4

from beeperlocal.connectors.instagram import InstagramConnector, InstagramAdapter, conversation as ig_conversation
from beeperlocal.connectors.x import XConnector, XAdapter, conversation as x_conversation
from beeperlocal.desktop_instagram import InstagramDesktop
from beeperlocal.desktop_x import XDesktop
from beeperlocal.desktop_messenger import MessengerDesktop
from beeperlocal.errors import AppError
from beeperlocal.mcp_access import SETTINGS_KEY, GRANTS_KEY, default_settings
from beeperlocal.messenger import MessengerSession
from beeperlocal.models import Conversation, StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from . import test_instagram as ig
from . import test_desktop_x as x
from . import test_desktop_messenger as ms
from .test_desktop_instagram import DesktopAdapter
from .support import MemoryStore


class IGTransport(DesktopAdapter):
    async def events(self, request, *, authorize=None):
        if authorize: authorize()
        target = request.get('thread_id', ig.CONVERSATION['id'])
        async for event in super().events(request):
            event = deepcopy(event)
            if 'conversation' in event: event['conversation']['id'] = target
            for row in event.get('messages', []): row['thread_id'] = target
            if 'message' in event: event['message']['thread_id'] = target
            yield event


class XTransport(x.Adapter):
    async def events(self, request, *, authorize=None):
        if authorize: authorize()
        if request['op'] == 'clear_local':
            yield {'type':'result','cleared':True}; return
        target = 'xchat:' + request.get('conversation', x.RAW['raw_id'])
        async for event in super().events(request):
            event = deepcopy(event)
            if 'message' in event: event['message']['conversation_id'] = target
            yield event


class Fixture:
    def __init__(self, provider, folder):
        self.provider, self.path = provider, Path(folder).resolve() / provider / 'messages.db'
        self.transport = {'instagram': IGTransport, 'x': XTransport, 'messenger': ms.Session}[provider]()
        self.credentials = {'instagram': ig.store, 'x': x.store, 'messenger': MemoryStore}[provider]()
        self.core = self.create()

    def create(self, *, initialize=True):
        kwargs = dict(credentials=self.credentials, db_factory=lambda: EncryptedMessageStore(b'm'*32, self.path))
        if self.provider == 'instagram':
            core = InstagramDesktop(**kwargs, connector_factory=lambda c: InstagramConnector(c, adapter=self.transport))
        elif self.provider == 'x':
            core = XDesktop(**kwargs, connector_factory=lambda c: XConnector(c, adapter=self.transport))
        else:
            core = MessengerDesktop(**kwargs, session_factory=lambda: self.transport)
        if self.provider != 'messenger':
            core.supports_all_sync = lambda: False
            core.start_watch = lambda: None
        if initialize:
            core._initialize()
        return core

    async def start(self):
        await self.core.connect()
        self.record = self.core._records()[0]
        if self.provider == 'instagram': conv = ig_conversation({**ig.CONVERSATION, 'id':'444555666'})
        elif self.provider == 'x': conv = x_conversation({'id':'123456:999888', 'raw_id':'123456:999888', 'peer':'999888', 'name':'SECOND_CANARY'}, '123456')
        else: conv = Conversation('888777666@msgr', 'SECOND_CANARY', 'dm', {'jid':'888777666@msgr'})
        self.other = StoredConversation(self.provider, self.core.account_id, conv)
        self.core.db.upsert_conversations([self.other])

    def grant(self, *, other=False, read=True, send=False):
        return self.core.register_client({'name':'CLIENT_CANARY', 'conversationIds':[(self.other if other else self.record).id], 'read':read, 'send':send})

    def enable(self): self.core._save_settings(mcpEnabled=True)
    def args(self, *, other=False):
        return {'conversation_id': (self.other if other else self.record).id, 'text':'SYNTHETIC_MCP_SEND', 'request_id':str(uuid4())}


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.fixtures = [Fixture(p, self.temp.name) for p in ('instagram','x','messenger')]
        for f in self.fixtures: await f.start()
    async def asyncTearDown(self):
        for f in self.fixtures: await f.core.close()
    async def denied(self, operation, code='MCP_ACCESS_DENIED'):
        with self.assertRaises(AppError) as caught: await operation
        self.assertEqual(caught.exception.code, code)

    async def test_old_settings_are_rejected_without_resuming_storage(self):
        self.assertEqual([f.core.settings['port'] for f in self.fixtures], [28644,28645,28646])
        self.assertEqual(len({f.core.settings_key for f in self.fixtures}), 3)
        self.assertEqual(len({f.core.grants_key for f in self.fixtures}), 3)
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                self.assertFalse(f.core.settings['mcpEnabled'])
                f.core.db.private_put(SETTINGS_KEY, {**default_settings(), 'storagePaused':True, 'mcpEnabled':True})
                f.core.db.private_put(GRANTS_KEY, [{'obsolete':'must not inherit'}])
                await f.core.close()
                before = f.path.read_bytes()
                f.core = f.create(initialize=False)
                with self.assertRaises(AppError) as caught:
                    f.core._initialize()
                self.assertEqual(caught.exception.code, 'LOCAL_DB_SCHEMA_UNSUPPORTED')
                self.assertFalse(f.core.started)
                self.assertEqual(f.path.read_bytes(), before)

    async def test_current_paused_settings_survive_restart(self):
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                f.core._save_settings(storagePaused=True)
                await f.core.close(); f.core = f.create()
                self.assertTrue(f.core.settings['storagePaused'])
                self.assertFalse(f.core.settings['mcpEnabled'])
                self.assertEqual(f.core.access.all(), [])

    async def test_scoped_reads_search_tokens_and_account_isolation(self):
        tokens = [f.grant()['token'] for f in self.fixtures]
        for f in self.fixtures: f.enable()
        for index, f in enumerate(self.fixtures):
            with self.subTest(provider=f.provider):
                token = tokens[index]
                listed = await f.core.mcp_call(token, 'list_conversations', {})
                self.assertEqual([c['id'] for c in listed['conversations']], [f.record.id])
                await self.denied(f.core.mcp_call(tokens[(index+1)%3], 'list_conversations', {}))
                await self.denied(f.core.mcp_call(token, 'get_messages', {'conversation_id':f.other.id}))
                rows = f.core.db.recent_messages(provider=f.provider)
                hidden = replace(rows[0], conversation_id=f.other.conversation.id, text='HIDDEN_CANARY')
                foreign = replace(rows[0], account_id='777777', text='HIDDEN_CANARY')
                f.core.db.upsert([hidden,foreign])
                found = await f.core.mcp_call(token,'search_messages',{'query':'HIDDEN_CANARY'})
                self.assertEqual(found['results'], [])
                self.assertEqual(found['scannedPermittedMessages'], 1)
                await self.denied(f.core.mcp_call(token,'send_message',f.args()))
                sender = f.grant(read=False,send=True)['token']
                await self.denied(f.core.mcp_call(sender,'list_conversations',{}))
                f.core.account_id = '777777'
                await self.denied(f.core.mcp_call(token,'list_conversations',{}))
                self.assertEqual(f.transport.sends, 0)

    async def test_saved_pagination_and_invalid_cross_conversation_cursor(self):
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                token=f.grant()['token']; f.enable()
                first=f.core.db.recent_messages(provider=f.provider)[0]
                f.core.db.upsert([replace(first,provider_message_id=f'page-{n}',sent_at=first.sent_at+timedelta(seconds=n+1)) for n in range(120)])
                page=await f.core.mcp_call(token,'get_messages',{'conversation_id':f.record.id})
                older=await f.core.mcp_call(token,'get_messages',{'conversation_id':f.record.id,'before':page['olderCursor']})
                self.assertEqual(len(page['messages']),100); self.assertEqual(len(older['messages']),21)
                self.assertFalse({m['id'] for m in page['messages']} & {m['id'] for m in older['messages']})
                await self.denied(f.core.mcp_call(token,'get_messages',{'conversation_id':f.record.id,'before':'invalid'}),'INVALID_INPUT')
                other_token=f.grant(other=True)['token']
                await self.denied(f.core.mcp_call(other_token,'get_messages',{'conversation_id':f.other.id,'before':page['olderCursor']}),'INVALID_INPUT')

    async def test_other_target_concurrent_send_deduplicates_and_preserves_selection(self):
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                token=f.grant(other=True,send=True)['token']; f.enable(); args=f.args(other=True)
                selected=f.core.selected_id
                before=f.credentials.load(f.provider)
                result=await asyncio.gather(*(f.core.mcp_call(token,'send_message',args) for _ in range(2)))
                self.assertEqual(f.transport.sends,1); self.assertTrue(result[1]['duplicateSuppressed'])
                self.assertEqual(f.core.selected_id,selected)
                self.assertEqual(f.credentials.load(f.provider).get('selections'),before.get('selections'))
                self.assertEqual(len(f.core.messages(f.other.id)['messages']),1)
                await self.denied(f.core.mcp_call(token,'send_message',{**args,'text':'changed'}),'INVALID_INPUT')

    async def test_grants_encrypted_survive_reopen_and_unknown_never_replays(self):
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                grant=f.grant(send=True); token=grant['token']; f.enable(); args=f.args()
                f.transport.send_error=AppError(f.core.send_unknown)
                await self.denied(f.core.mcp_call(token,'send_message',args),f.core.send_unknown)
                await f.core.close(); f.core=f.create(); await f.core.connect()
                await self.denied(f.core.mcp_call(token,'send_message',args),f.core.send_unknown)
                self.assertEqual(f.transport.sends,1)
                self.assertNotIn(token,json.dumps(f.core.management()))
                for secret in (token,'CLIENT_CANARY','SYNTHETIC_MCP_SEND'):
                    self.assertNotIn(secret.encode(),f.path.read_bytes())
                f.core.access.revoke(grant['client']['id'],f.core.account_id)
                await f.core.close(); f.core=f.create(); f.core._initialize()
                await self.denied(f.core.mcp_call(token,'list_conversations',{}))

    async def test_revocation_after_auth_await_prevents_mutation(self):
        for f in self.fixtures:
            with self.subTest(provider=f.provider):
                grant=f.grant(send=True); f.enable(); entered,release=asyncio.Event(),asyncio.Event()
                original=f.core.connector.connect
                async def connect():
                    await original(); entered.set(); await release.wait()
                f.core.connector.connect=connect
                task=asyncio.create_task(f.core.mcp_call(grant['token'],'send_message',f.args()))
                await asyncio.wait_for(entered.wait(),1)
                f.core.access.revoke(grant['client']['id'],f.core.account_id); release.set()
                await self.denied(task); self.assertEqual(f.transport.sends,0)

    async def test_provider_deletion_revokes_only_its_grants(self):
        grants=[f.grant() for f in self.fixtures]
        for f in self.fixtures: f.enable()
        for index,f in enumerate(self.fixtures):
            preview=await f.core.deletion_preview()
            await f.core.delete_local_data(preview['confirmation'])
            await self.denied(f.core.mcp_call(grants[index]['token'],'list_conversations',{}),'MCP_DISABLED')
            for sibling,grant in zip(self.fixtures[index+1:],grants[index+1:]):
                self.assertTrue((await sibling.core.mcp_call(grant['token'],'list_conversations',{}))['conversations'])


class IssuanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_revoke_during_adapter_spawn_never_writes_request(self):
        for adapter,namespace in ((InstagramAdapter(binary='/usr/bin/true'),'instagram'),(XAdapter(command=['/usr/bin/true']),'x')):
            entered,release=asyncio.Event(),asyncio.Event(); written=[]
            process=SimpleNamespace(stdin=SimpleNamespace(write=written.append,drain=AsyncMock()))
            async def spawn(*args,**kwargs): entered.set(); await release.wait(); return process
            revoked=False
            def guard():
                if revoked: raise AppError('MCP_ACCESS_DENIED')
            with patch(f'beeperlocal.connectors.{namespace}.asyncio.create_subprocess_exec',spawn), patch(f'beeperlocal.connectors.{namespace}.stop_process',AsyncMock()):
                stream=adapter.events({'op':'send'},authorize=guard)
                task=asyncio.create_task(anext(stream)); await entered.wait(); revoked=True; release.set()
                with self.assertRaises(AppError): await task
                self.assertEqual(written,[]); await stream.aclose()

    async def test_messenger_rechecks_inside_write_lock(self):
        session=MessengerSession(lock=nullcontext); written=[]
        process=SimpleNamespace(stdin=SimpleNamespace(write=written.append,drain=AsyncMock()))
        await session.write_lock.acquire()
        revoked=False
        def guard():
            if revoked: raise AppError('MCP_ACCESS_DENIED')
        task=asyncio.create_task(session._write(process,{'op':'send'},authorize=guard)); await asyncio.sleep(0)
        revoked=True; session.write_lock.release()
        with self.assertRaises(AppError): await task
        self.assertEqual(written,[])


class HTTPProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_real_http_sdk_connections_and_revocation(self):
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
        logging.disable(logging.CRITICAL); self.addCleanup(logging.disable,logging.NOTSET)
        with tempfile.TemporaryDirectory() as folder:
            fixtures=[Fixture(p,folder) for p in ('instagram','x','messenger')]
            try:
                for f in fixtures: await f.start()
                grants=[f.grant(send=True) for f in fixtures]
                for index,f in enumerate(fixtures):
                    with self.subTest(provider=f.provider):
                        with socket.socket() as probe:
                            probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
                        await f.core.configure_mcp(True,port)
                        url=f'http://127.0.0.1:{port}/mcp'; token=grants[index]['token']
                        @asynccontextmanager
                        async def transport():
                            async with httpx2.AsyncClient(headers={'Authorization':'Bearer '+token},trust_env=False) as http:
                                async with streamable_http_client(url,http_client=http) as streams: yield streams
                        async with Client(transport(),read_timeout_seconds=5) as client:
                            listing=await client.list_tools(); available=listing.tools if hasattr(listing,'tools') else listing
                            self.assertEqual({t.name for t in available},{'list_conversations','get_messages','search_messages','send_message'})
                            for op,args in [('list_conversations',{}),('get_messages',{'conversation_id':f.record.id}),('search_messages',{'query':'CANARY'}),('send_message',f.args())]:
                                self.assertFalse((await client.call_tool(op,args)).is_error)
                            self.assertTrue((await client.call_tool('get_messages',{'conversation_id':f.other.id})).is_error)
                        async with httpx2.AsyncClient(trust_env=False) as http:
                            wrong=grants[(index+1)%3]['token']
                            self.assertEqual((await http.post(url,headers={'Authorization':'Bearer '+wrong},json={})).status_code,401)
                            f.core.access.revoke(grants[index]['client']['id'],f.core.account_id)
                            self.assertEqual((await http.post(url,headers={'Authorization':'Bearer '+token},json={})).status_code,401)
                        self.assertEqual(f.transport.sends,1)
                        await f.core.close(); f.core=f.create()
                        restored=await f.core.dispatch({'op':'management'})
                        self.assertTrue(restored['mcp']['running'])
                        self.assertEqual(restored['mcp']['port'],port)
                        async with httpx2.AsyncClient(trust_env=False) as http:
                            self.assertEqual((await http.post(url,headers={'Authorization':'Bearer '+token},json={})).status_code,401)
            finally:
                for f in fixtures: await f.core.close()
