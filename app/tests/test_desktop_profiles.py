"""Synthetic onboarding, profile, ordering and isolation regressions; no live login/send."""
import asyncio
import base64
from dataclasses import replace
from datetime import datetime, timezone
import json
from unittest.mock import AsyncMock, patch
import unittest

from beeperlocal.connectors.line import LineCLI, LineConnector, normalize_line
from beeperlocal.desktop_profiles import download_avatar, picture_version
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from .support import MemoryStore
from . import test_desktop as desktop_fixtures
from .test_line import SELF, PEER, OTHER, CONV, raw


class ProfileTests(unittest.IsolatedAsyncioTestCase):
    setUp = desktop_fixtures.DesktopTests.setUp
    db = desktop_fixtures.DesktopTests.db
    new_core = desktop_fixtures.DesktopTests.new_core
    asyncTearDown = desktop_fixtures.DesktopTests.asyncTearDown
    connect = desktop_fixtures.DesktopTests.connect

    async def until(self, predicate):
        for _ in range(100):
            if predicate(): return
            await asyncio.sleep(.01)
        self.fail("fixture task did not reach expected state")

    async def test_unopened_conversation_sorts_by_provider_time_and_selection_keeps_profiles(self):
        original = self.backend.request
        async def request(*args, **kwargs):
            if args[0] == 'chats':
                return [dict(id=PEER, name='Renamed', updated_at=1700000000000, picture_path='/new-profile'),
                        dict(id=OTHER, name='Recent nonfriend', updated_at=1900000000000, picture_path='/other-profile')]
            return await original(*args, **kwargs)
        self.backend.request = request
        result = await self.connect()
        self.assertEqual(result['conversations'][0]['id'], self.other.id)
        self.assertEqual(result['conversations'][0]['preview'], '')
        self.assertEqual(self.core._record(self.record.id).conversation.title, 'Renamed')
        await self.core.dispatch({'op':'select','conversationId':self.other.id})
        self.assertEqual(self.core.connector.selected_conversation().locator['picture_path'], '/other-profile')
        await self.core.dispatch({'op':'select','conversationId':self.record.id})
        self.assertEqual(self.core._record(self.record.id).conversation.title, 'Renamed')
        self.assertEqual(self.core.snapshot()['conversations'][0]['id'],self.other.id)
        await self.core.close()
        self.core = self.new_core()
        saved = await self.core.dispatch({'op':'snapshot'})
        self.assertEqual(saved['conversations'][0]['title'],'Recent nonfriend')
        self.assertEqual(saved['conversations'][0]['lastMessageAt'], '2030-03-17T17:46:40.000000Z')
        for secret in (OTHER, 'Renamed', '/new-profile'):
            self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.assertNotIn('/other-profile', json.dumps(saved))

    async def test_catalog_refresh_hides_stale_rows_without_deleting_saved_history(self):
        hidden = replace(self.other, conversation=replace(self.other.conversation, id="U"+"d"*43, locator={"mid":"U"+"d"*43}))
        msg = replace(normalize_line(raw(),SELF,CONV), conversation_id=hidden.conversation.id)
        with self.db() as db: db.upsert([msg], conversations=[hidden])
        result = await self.connect()
        self.assertEqual(len(result['conversations']),2)
        self.assertNotIn(hidden.id,[r['id'] for r in result['conversations']])
        self.assertEqual(len(self.core.db.list_messages('line',SELF,hidden.conversation.id)),1)
        await self.core.close()
        self.core=self.new_core()
        offline=await self.core.dispatch({'op':'snapshot'})
        self.assertEqual(len(offline['conversations']),2)

    async def test_new_local_message_moves_chat_above_provider_timestamp(self):
        await self.connect()
        recent = replace(self.other, conversation=replace(self.other.conversation,locator={'mid':OTHER,'updated_at':1800000000000}))
        self.core.db.upsert_conversations([recent])
        self.assertEqual(self.core.snapshot()['conversations'][0]['id'],self.other.id)
        msg = replace(normalize_line(raw(),SELF,CONV), sent_at=datetime(2040,1,1,tzinfo=timezone.utc))
        self.core.db.upsert([msg])
        self.assertEqual(self.core.snapshot()['conversations'][0]['id'],self.record.id)

    def fake_login(self):
        queue = asyncio.Queue()
        self.closed = False
        self.replacement = None
        async def events(*, replace):
            self.replacement = replace
            try:
                while True:
                    event = await queue.get()
                    yield event
                    if event['event'] == 'completed': return
            finally: self.closed = True
        self.backend.login_events = events
        return queue

    async def test_new_user_qr_pin_completed_and_secret_lifetime(self):
        self.credentials = MemoryStore()
        self.core.credentials = self.credentials
        queue = self.fake_login()
        result = await self.core.dispatch({'op':'line_login_start','replace':False})
        self.assertEqual(result['stage'],'starting')
        await queue.put({'event':'code','matrix':[[False]*21 for _ in range(21)]})
        await self.until(lambda:self.core.login_state['stage']=='code')
        self.assertTrue((await self.core.dispatch({'op':'line_login_status'}))['matrix'])
        self.assertFalse(self.credentials.records)
        await queue.put({'event':'pin','pin':'987654'})
        await self.until(lambda:self.core.login_state['stage']=='pin')
        self.assertNotIn('matrix',self.core.login_state)
        self.assertNotIn('987654',json.dumps(self.events))
        self.assertNotIn('987654',json.dumps(self.core.snapshot()))
        await queue.put({'event':'completed'})
        await self.until(lambda:self.core.login_state['stage']=='completed')
        self.assertFalse(self.replacement)
        self.assertTrue(self.closed)
        self.assertEqual(self.credentials.records['line']['account_id'],SELF)
        self.assertEqual(set(self.core.login_state),{'stage'})
        self.assertNotIn(b'987654',self.path.read_bytes())
        self.assertEqual((await self.connect())['connection'],'connected')

    async def test_cancel_stops_login_and_blocks_send_connect_and_mcp(self):
        await self.connect()
        previous = dict(self.credentials.records)
        self.fake_login()
        await self.core.dispatch({'op':'line_login_start','replace':True})
        await asyncio.sleep(.01)
        for operation in ({'op':'connect'}, {'op':'mcp_configure','enabled':True,'port':28641}):
            with self.assertRaises(AppError) as err: await self.core.dispatch(operation)
            self.assertEqual(err.exception.code,'LINE_LOGIN_IN_PROGRESS')
        result = await self.core.dispatch({'op':'line_login_cancel'})
        self.assertEqual(result,{'stage':'cancelled'})
        self.assertTrue(self.closed)
        self.assertEqual(self.credentials.records,previous)
        self.assertFalse(self.core.settings['mcpEnabled'])

    async def test_failed_replacement_preserves_credentials_and_removes_pin(self):
        queue = self.fake_login()
        previous = dict(self.credentials.records)
        await self.core.dispatch({'op':'line_login_start','replace':False})
        await queue.put({'event':'pin','pin':'987654'})
        await queue.put({'event':'failed','code':'LINE_LOGIN_REPLACEMENT_REQUIRED','private':'never copy'})
        await self.until(lambda:self.core.login_state['stage']=='failed')
        self.assertEqual(self.core.login_state,{'stage':'failed','errorCode':'LINE_LOGIN_REPLACEMENT_REQUIRED'})
        self.assertEqual(self.credentials.records,previous)
        self.assertNotIn('never copy',json.dumps(self.events))
        self.assertTrue(self.closed)

    async def test_avatar_cache_scope_pause_and_stale_completion(self):
        await self.connect()
        await self.core.stop_watch()
        record = replace(self.record,conversation=replace(CONV,locator={'mid':PEER,'picture_path':'/fixture'}))
        self.core.db.upsert_conversations([record])
        self.core.avatar_fetcher=AsyncMock(return_value='data:image/png;base64,fixture')
        self.assertTrue(self.core.avatar(self.record.id)['pending'])
        await self.until(lambda:not self.core.avatar_tasks)
        self.assertTrue(self.core.avatar(self.record.id)['image'])
        self.core.avatar(self.record.id)
        self.assertEqual(self.core.avatar_fetcher.await_count,1)
        with self.assertRaises(AppError): self.core.avatar(PEER)
        await self.core.pause_storage(True)
        self.assertIsNone(self.core.avatar(self.record.id)['image'])
        self.assertFalse(self.core.avatar(self.record.id)['pending'])
        self.assertEqual(self.core.avatar_fetcher.await_count,1)

    async def test_bad_login_matrix_does_not_attach_session(self):
        queue=self.fake_login()
        await self.core.dispatch({'op':'line_login_start','replace':False})
        await queue.put({'event':'code','matrix':[['script']]})
        await self.until(lambda:self.core.login_state['stage']=='failed')
        self.assertEqual(self.core.login_state['errorCode'],'LINE_LOGIN_FAILED')
        self.assertTrue(self.closed)


class AvatarDownloadTests(unittest.IsolatedAsyncioTestCase):
    async def test_remote_images_only_use_fixed_host_and_bounded_raster_response(self):
        png = b'\x89PNG\r\n\x1a\nfixture'
        class Response:
            status_code=200
            headers={'content-type':'image/png'}
            body=png
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            async def aiter_bytes(self): yield self.body
        response=Response()
        calls=[]
        class Client:
            def __init__(self,**kwargs): calls.append(kwargs)
            async def __aenter__(self): return self
            async def __aexit__(self,*args): pass
            def stream(self,method,url): calls.append((method,url));return response
        with patch('httpx2.AsyncClient',Client):
            for path in ['https://evil.test/p','//evil.test/p','/../private','/ok?secret=x','/ok#fragment','/bad%2Fpath']:
                self.assertIsNone(await download_avatar(path))
                self.assertIsNone(picture_version(path))
            self.assertEqual(calls,[])
            self.assertEqual(await download_avatar('/fixture'),'data:image/png;base64,'+base64.b64encode(png).decode())
            self.assertEqual(calls[-1],('GET','https://profile.line-scdn.net/fixture'))
            self.assertFalse(calls[0]['follow_redirects'])
            self.assertFalse(calls[0]['trust_env'])
            response.status_code=302
            self.assertIsNone(await download_avatar('/fixture'))
            response.status_code=200;response.headers={'content-type':'image/svg+xml'}
            self.assertIsNone(await download_avatar('/fixture'))
            response.headers={'content-type':'image/png'};response.body=b'x'*(512*1024+1)
            self.assertIsNone(await download_avatar('/fixture'))
            response.body=b'<html>not an image</html>'
            self.assertIsNone(await download_avatar('/fixture'))

    async def test_missing_provider_session_is_explicit_not_generic_network_failure(self):
        cli=object.__new__(LineCLI)
        cli.request=AsyncMock(return_value={'configured':'none','reason':'no_session'})
        with self.assertRaises(AppError) as err: await cli.whoami()
        self.assertEqual(err.exception.code,'LINE_LOGIN_REQUIRED')
        self.assertEqual(cli.request.await_count,1)

    async def test_invalidated_session_routes_to_qr_without_repeated_network_calls(self):
        cli=object.__new__(LineCLI)
        cli.request=AsyncMock(return_value={'configured':'present','line_validity':'invalidated'})
        with self.assertRaises(AppError) as err: await cli.whoami()
        self.assertEqual(err.exception.code,'LINE_LOGIN_REQUIRED')
        self.assertEqual(cli.request.await_count,1)
