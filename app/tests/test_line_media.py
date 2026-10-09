"""Synthetic media receipt, encryption, preview and IPC isolation regressions."""
import asyncio
import base64
from contextlib import aclosing
from dataclasses import replace
from io import BytesIO
import json
import unittest
from unittest.mock import AsyncMock, patch

from PIL import Image

from beeperlocal.connectors.line import LineCLI, LineConnector, normalize_line, MAX_IMAGE_BYTES
from beeperlocal.desktop_media import image_preview, download_sticker
from beeperlocal.errors import AppError
from .test_line import SELF, PEER, CONV, raw, event, store, FakeCLI
from . import test_desktop as fixtures


def png(size=(240, 160)):
    output = BytesIO()
    Image.new("RGBA", size, (29, 160, 120, 180)).save(output, format="PNG")
    return output.getvalue()


class MediaNormalizationTests(unittest.IsolatedAsyncioTestCase):
    async def test_images_stickers_history_and_watch_use_same_identity_and_order(self):
        rows = [raw(), raw(id="1234567891", content_type=1, status="attachment", text=""),
                raw(id="1234567892", content_type=7, status="attachment", text="", sticker_id="52002734")]
        cli = FakeCLI(rows=rows, events=[event(message=m) for m in rows])
        connector = LineConnector(store(), cli=cli)
        batch = await connector.fetch()
        self.assertFalse(batch.errors)
        self.assertEqual(batch.excluded_events, 0)
        self.assertEqual([m.text for m in batch.messages], [rows[0]["text"], "画像", "スタンプ"])
        async with aclosing(connector.watch()) as stream:
            received = [m async for m in stream]
        self.assertEqual(received, batch.messages)
        self.assertEqual(received[2].media, {"kind": "sticker", "sticker_id": "52002734"})
        self.assertEqual(normalize_line(raw(content_type=1, **{"from":SELF, "to":PEER}), SELF, CONV).direction, "outgoing")

    def test_missing_or_untrusted_sticker_id_keeps_placeholder_without_copying_metadata(self):
        for value in (None, "https://evil.test/private", "../secret", "1?token=secret", "9"*21, False):
            message = normalize_line(raw(content_type=7, sticker_id=value, content_metadata={"private":"never_copy"}),SELF,CONV)
            self.assertEqual(message.media, {"kind":"sticker"})
            self.assertEqual(message.attachment_count,1)
            self.assertNotIn("never_copy",repr(message))
        with self.assertRaises(AppError):
            normalize_line(raw(content_type=1,to="unrelated"),SELF,CONV)


class PreviewTests(unittest.IsolatedAsyncioTestCase):
    def test_large_image_is_resized_and_transparency_preserved(self):
        result = image_preview(png((2000, 1000)))
        self.assertTrue(result.startswith("data:image/png;base64,"))
        with Image.open(BytesIO(base64.b64decode(result.split(",")[1]))) as image:
            self.assertEqual(image.size, (1600,800))
            self.assertEqual(image.mode, "RGBA")
        with self.assertRaises(Exception):
            image_preview(b'<svg><script>alert(1)</script></svg>')

    async def test_sticker_fixed_host_no_redirects_and_bounded_bytes(self):
        class Response:
            status_code=200
            headers={"content-type":"image/png"}
            body=png()
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
        with patch('httpx2.AsyncClient', Client):
            for value in ("../file", "https://evil.test", "1?x=secret", None):
                self.assertIsNone(await download_sticker(value))
            self.assertEqual(calls,[])
            self.assertEqual(await download_sticker('52002734'),response.body)
            self.assertEqual(calls[-1],('GET','https://stickershop.line-scdn.net/stickershop/v1/sticker/52002734/iPhone/sticker_key@2x.png'))
            self.assertFalse(calls[0]['follow_redirects'])
            self.assertFalse(calls[0]['trust_env'])
            response.status_code=302
            self.assertIsNone(await download_sticker('52002734'))
            response.status_code=200;response.body=b'x'*(2*1024*1024+1)
            self.assertIsNone(await download_sticker('52002734'))

    async def test_binary_cli_size_failure_and_cancellation_reap_process(self):
        cli=object.__new__(LineCLI)
        process=type('Process',(),{})()
        process.stdout=type('Output',(),{})()
        process.stdout.read=AsyncMock(side_effect=[b'x'*(MAX_IMAGE_BYTES+1)])
        cli._start=AsyncMock(return_value=process)
        with patch('beeperlocal.connectors.line.stop_process',new_callable=AsyncMock) as stop:
            with self.assertRaises(AppError): await cli.download_image(PEER,'1234')
            stop.assert_awaited_once_with(process)
        with self.assertRaises(AppError): await cli.download_image(PEER,'--help')
        self.assertEqual(cli._start.await_count,1)


class DesktopMediaTests(unittest.IsolatedAsyncioTestCase):
    setUp=fixtures.DesktopTests.setUp
    db=fixtures.DesktopTests.db
    new_core=fixtures.DesktopTests.new_core
    asyncTearDown=fixtures.DesktopTests.asyncTearDown
    connect=fixtures.DesktopTests.connect

    async def prepare(self,kind=1):
        self.backend.rows=[raw(id='1234567891',content_type=kind,status='attachment',text='',sticker_id='52002734')]
        self.backend.download_image=AsyncMock(return_value=png())
        await self.connect()
        await self.core.stop_watch()
        self.message=normalize_line(self.backend.rows[0],SELF,CONV)
        self.request={'op':'line_media','conversationId':self.record.id,'messageId':self.message.id,'retry':False}

    async def complete(self):
        tasks=list(self.core.media_tasks.values())
        if tasks: await asyncio.wait_for(asyncio.gather(*tasks),3)

    async def test_preview_is_private_scoped_deduplicated_and_never_stored_plaintext(self):
        await self.prepare()
        for _ in range(2): self.assertTrue((await self.core.dispatch(self.request))['pending'])
        await self.complete()
        result=await self.core.dispatch(self.request)
        self.assertTrue(result['image'].startswith('data:image/png;base64,'))
        self.backend.download_image.assert_awaited_once_with(PEER,'1234567891')
        view=self.core.messages(self.record.id)['messages'][0]
        self.assertEqual(view['media'],{'kind':'image'})
        self.assertNotIn('data:image',json.dumps(self.core.snapshot()))
        for private in (PEER,'1234567891',result['image']): self.assertNotIn(private.encode(),self.path.read_bytes())
        self.assertNotIn('image',json.dumps(self.events))
        for request in ({**self.request,'conversationId':self.other.id}, {**self.request,'messageId':'1234567891'},
                        {**self.request,'messageId':'f'*64}, {**self.request,'url':'https://evil.test'}):
            with self.assertRaises(AppError): await self.core.dispatch(request)
        self.assertEqual(self.backend.send_calls,0)

    async def test_encrypted_sticker_metadata_reopens_but_no_ids_in_ui(self):
        await self.prepare(7)
        self.core.sticker_fetcher=AsyncMock(return_value=png())
        self.assertTrue((await self.core.dispatch(self.request))['pending'])
        await self.complete()
        self.core.sticker_fetcher.assert_awaited_once_with('52002734')
        self.assertNotIn('52002734',json.dumps(self.core.messages(self.record.id)))
        self.assertNotIn(b'52002734',self.path.read_bytes())
        await self.core.close()
        self.core=self.new_core()
        await self.core.dispatch({'op':'snapshot'})
        self.assertEqual(self.core.db.get_message(self.message.id).media,{'kind':'sticker','sticker_id':'52002734'})
        self.assertFalse((await self.core.dispatch(self.request))['pending'])

    async def test_failure_does_not_hide_message_and_manual_retry_can_recover(self):
        await self.prepare()
        self.backend.download_image.side_effect=AppError('LINE_MEDIA_UNAVAILABLE')
        await self.core.dispatch(self.request)
        await self.complete()
        self.assertEqual(await self.core.dispatch(self.request),{'image':None,'pending':False})
        self.assertEqual(self.core.messages(self.record.id)['messages'][0]['text'],'画像')
        self.assertEqual(self.core.connection,'connected')
        self.backend.download_image.side_effect=None
        await self.core.dispatch({**self.request,'retry':True})
        await self.complete()
        self.assertTrue((await self.core.dispatch(self.request))['image'])
        self.assertEqual(self.backend.download_image.await_count,2)

    async def test_pause_cancels_download_and_clears_bytes(self):
        await self.prepare()
        started=asyncio.Event()
        cancelled=asyncio.Event()
        async def delayed(*args):
            started.set()
            try: await asyncio.Event().wait()
            finally: cancelled.set()
        self.backend.download_image.side_effect=delayed
        await self.core.dispatch(self.request)
        await asyncio.wait_for(started.wait(),1)
        await self.core.pause_storage(True)
        self.assertTrue(cancelled.is_set())
        self.assertFalse(self.core.media_tasks)
        self.assertFalse(self.core.media_cache)
        self.assertEqual(self.core.media_cache_bytes,0)
        self.assertEqual(await self.core.dispatch(self.request),{'image':None,'pending':False})

    async def test_selection_cancels_old_media_work(self):
        await self.prepare()
        await self.core.dispatch(self.request)
        await self.complete()
        self.assertTrue(self.core.media_cache)
        await self.core.dispatch({'op':'select','conversationId':self.other.id})
        self.assertFalse(self.core.media_cache)

    async def test_media_cache_byte_budget_evicts_old_previews(self):
        await self.prepare()
        await self.core.dispatch(self.request)
        await self.complete()
        size=self.core.media_cache_bytes
        second=replace(self.message,provider_message_id='1234567892')
        self.core.db.upsert([second])
        with patch('beeperlocal.desktop_media.MAX_CACHE_BYTES',size+1):
            await self.core.dispatch({**self.request,'messageId':second.id})
            await self.complete()
        self.assertEqual(len(self.core.media_cache),1)
        self.assertEqual(self.core.media_cache_bytes,size)
        self.assertIn((self.record.id,second.id),self.core.media_cache)
