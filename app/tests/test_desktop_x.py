"""X integration regression tests; all accounts/messages are synthetic."""
import asyncio
from contextlib import aclosing
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import sys
import tempfile
import unittest
from uuid import uuid4
from beeperlocal.connectors.x import XAdapter, XConnector, conversation, normalize_x
from beeperlocal.desktop_x import XDesktop
from beeperlocal.desktop_router import DesktopRouter
from beeperlocal.errors import AppError
from beeperlocal.models import StoredConversation
from beeperlocal.storage import EncryptedMessageStore
from .support import MemoryStore

RAW = {"raw_id": "123456:789012", "id": "123456:789012", "peer": "789012", "name": "X_PRIVATE_TITLE_CANARY"}
CONV = conversation(RAW, "123456")
def message(**changes):
    return {"provider": "x", "account_id": "123456", "conversation_id": CONV.id,
            "provider_message_id": "12345678-1234-4234-8234-123456789012", "sender_id": "789012",
            "direction": "peer", "created_at_msec": 1790812345000, "text": "X_PRIVATE_BODY_CANARY", "verified": True, **changes}
def history(*rows, **changes):
    return {"type": "result", "messages": list(rows), "raw_items": len(rows)+2, "excluded_events": 2,
            "unsupported_legacy_count": 1, "legacy_message_count": sum(r.get("source") == "legacy" for r in rows), "history_limited": True, **changes}
def store():
    return MemoryStore({"x": {"account_id": "123456", "selections": [CONV.selection()]}})
class Adapter:
    def __init__(self):
        self.queue = asyncio.Queue(); self.ready = asyncio.Event(); self.live = self.sends = 0
        self.requests = []; self.send_error = None; self.before_send = lambda: None
        self.rows = [message()]
    async def events(self, request):
        self.requests.append(deepcopy(request)); op = request["op"]
        if op == "connect": yield {"type": "result", "account_id": "123456"}
        elif op == "conversations": yield {"type": "result", "items": [RAW], "limited": False}
        elif op == "history": yield history(*self.rows)
        elif op == "send":
            self.sends += 1; self.before_send()
            if self.send_error: raise self.send_error
            yield {"type": "result", "encrypted": True, "message": message(sender_id="123456", direction="self", text=request["text"])}
        elif op == "watch":
            self.live += 1
            try:
                yield history(*self.rows, type="history")
                yield {"type": "status", "code": "connected"}; self.ready.set()
                while True:
                    event = await self.queue.get()
                    if event is None: return
                    if isinstance(event, Exception): raise event
                    yield event
            finally: self.live -= 1

class NormalizeTests(unittest.TestCase):
    def test_unverified_and_cross_scope_never_normalize(self):
        for change in ({"verified": 1}, {"provider": "line"}, {"account_id": "000"}, {"sender_id": "000"},
                       {"conversation_id": "xchat:123456:000"}, {"direction": "self"},
                       {"provider_message_id": "unsigned-sequence"}, {"created_at_msec": True}):
            with self.subTest(change=change), self.assertRaises(AppError): normalize_x(message(**change), "123456", CONV)
        self.assertEqual(normalize_x(message(), "123456", CONV).direction, "incoming")

    def test_legacy_requires_explicit_history_provenance_and_never_normalizes_as_send(self):
        row=message(verified=False, source="legacy", provider_message_id="legacy:1234567890")
        self.assertEqual(normalize_x(row,"123456",CONV,allow_legacy=True).provider_message_id,"legacy:1234567890")
        with self.assertRaises(AppError): normalize_x(row,"123456",CONV)
        for changes in ({"verified":True},{"verified":0},{"source":"signed"},{"provider_message_id":"1234567890"},
                        {"sender_id":"999"},{"conversation_id":"xchat:123456:999"}):
            with self.assertRaises(AppError): normalize_x({**row,**changes},"123456",CONV,allow_legacy=True)

class DesktopTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name).resolve()/"private"/"messages.db"
        self.credentials = store(); self.adapter = Adapter(); self.events = []
        self.record = StoredConversation("x", "123456", CONV); self.core = self.make_core()
    def make_core(self):
        core = XDesktop(credentials=self.credentials, db_factory=lambda: EncryptedMessageStore(b"x"*32, self.path),
                        connector_factory=lambda c: XConnector(c, adapter=self.adapter), emit=self.events.append)
        core.supports_all_sync = lambda: False  # Event receiver regression tests; new polling has separate fixtures.
        return core
    async def asyncTearDown(self): await self.core.close()
    async def connect(self):
        self.adapter.ready.clear(); result = await self.core.dispatch({"op":"connect"})
        await asyncio.wait_for(self.adapter.ready.wait(), 1); return result
    async def until(self, condition):
        for _ in range(100):
            if condition(): return
            await asyncio.sleep(.01)
        self.fail("Expected fixture state was not reached")
    def request(self, **changes):
        return {"op":"send", "conversationId":self.record.id, "text":"X送信テスト", "requestId":str(uuid4()), **changes}
    async def test_receive_restart_search_and_encrypted_scope(self):
        await self.connect()
        await self.adapter.queue.put(history(message(provider_message_id=str(uuid4()), text="X新着canary"), type="history"))
        await self.until(lambda:self.core.db.total_count()==2)
        self.assertEqual(self.core.messages(self.record.id)["unsupportedLegacyCount"],1)
        await self.core.close(); self.core=self.make_core()
        self.assertEqual((await self.core.dispatch({"op":"snapshot"}))["connection"],"offline")
        self.assertEqual(len((await self.core.dispatch({"op":"search","query":"X新着canary"}))["results"]),1)
        for canary in (b"X_PRIVATE_BODY_CANARY",b"X_PRIVATE_TITLE_CANARY",b"123456", "X新着canary".encode()):
            self.assertNotIn(canary,self.path.read_bytes())
    async def test_legacy_receive_reopen_search_and_no_partial_unverified_batch(self):
        self.adapter.rows=[message(verified=False,source="legacy",provider_message_id="legacy:1234567890")]
        await self.connect()
        self.assertEqual(len(self.core.messages(self.record.id)["messages"]),1)
        self.assertEqual(self.core.messages(self.record.id)["legacyMessageCount"],1)
        await self.core.close(); self.core=self.make_core()
        await self.core.dispatch({"op":"snapshot"})
        self.assertEqual(len((await self.core.dispatch({"op":"search","query":"X_PRIVATE_BODY_CANARY"}))["results"]),1)
        self.assertNotIn(b"X_PRIVATE_BODY_CANARY",self.path.read_bytes())
        connector=XConnector(self.credentials,adapter=self.adapter)
        with self.assertRaises(AppError): connector._history_batch(history(self.adapter.rows[0],message(verified=False)),CONV,100)

    async def test_legacy_reply_cannot_acknowledge_encrypted_send(self):
        class LegacySend(Adapter):
            async def events(self,request):
                yield {"type":"result","encrypted":True,"message":message(verified=False,source="legacy",
                       provider_message_id="legacy:1234567890",sender_id="123456",direction="self",text=request["text"])}
        with self.assertRaises(AppError) as caught: await XConnector(self.credentials,adapter=LegacySend()).send_text("fixture")
        self.assertEqual(caught.exception.code,"X_SEND_UNKNOWN")

    async def test_send_once_durable_before_dispatch_and_watch_is_closed(self):
        await self.connect(); request=self.request()
        def check():
            self.assertEqual(self.adapter.live,0)
            self.assertEqual(self.core.db.get_outgoing(request["requestId"]).status,"sending")
        self.adapter.before_send=check
        first=await self.core.dispatch(request); again=await self.core.dispatch(request)
        self.assertTrue(first["encrypted"]); self.assertTrue(again["duplicateSuppressed"]); self.assertEqual(self.adapter.sends,1)
    async def test_unknown_is_not_replayed_after_restart(self):
        await self.connect(); request=self.request(); self.adapter.send_error=AppError("X_SEND_UNKNOWN")
        with self.assertRaises(AppError): await self.core.dispatch(request)
        await self.core.close(); self.core=self.make_core(); result=await self.connect()
        self.assertEqual(len(result["pendingSends"]),1)
        with self.assertRaises(AppError): await self.core.dispatch(request)
        self.assertEqual(self.adapter.sends,1)
    async def test_failed_storage_and_wrong_provider_never_send(self):
        await self.connect()
        for request in (self.request(conversationId=replace(self.record,provider="line").id),self.request(text="あ"*3334)):
            with self.assertRaises(AppError): await self.core.dispatch(request)
        original=self.core.db.upsert
        def fail(*args,**kwargs):
            if kwargs.get("outgoing_requests"): raise AppError("LOCAL_DB_UNAVAILABLE")
            return original(*args,**kwargs)
        self.core.db.upsert=fail
        with self.assertRaises(AppError): await self.core.dispatch(self.request())
        self.assertEqual(self.adapter.sends,0)
    async def test_pause_stops_and_no_mcp_or_line_login(self):
        await self.connect(); await self.core.dispatch({"op":"storage_pause","paused":True})
        self.assertEqual(self.adapter.live,0)
        self.assertTrue((await self.core.dispatch({'op':'management'}))['storage']['paused'])
        for op in ("connect","mcp_configure","line_login_start","storage_delete","avatar"):
            with self.assertRaises(AppError): await self.core.dispatch({"op":op})
        await self.core.close(); self.core=self.make_core()
        self.assertTrue((await self.core.dispatch({"op":"snapshot"}))["storagePaused"])
    async def test_watch_failure_recovers_and_signature_error_stops(self):
        await self.connect(); self.core.retry_delays=(.001,)
        self.adapter.rows.append(message(provider_message_id=str(uuid4()),text="offline fixture"))
        await self.adapter.queue.put(None)
        await self.until(lambda:self.core.db.total_count()==2 and self.core.receiving=="waiting")
        await self.adapter.queue.put(AppError("X_VERIFY_FAILED"))
        await self.until(lambda:self.core.receiving=="error")
        before=len(self.adapter.requests); await asyncio.sleep(.03)
        self.assertEqual(len(self.adapter.requests),before); self.assertEqual(self.adapter.sends,0)
    async def test_account_change_stops_retry_before_worker(self):
        await self.connect(); self.core.retry_delays=(.001,)
        self.credentials.save("x",{"account_id":"999","selections":[]})
        await self.adapter.queue.put(None)
        await self.until(lambda:self.core.error_code=="ACCOUNT_CHANGED")
        self.assertEqual(sum(r["op"]=="watch" for r in self.adapter.requests),1)
    async def test_stop_cancels_pending_retry(self):
        await self.connect(); self.core.retry_delays=(.05,)
        await self.adapter.queue.put(None); await self.until(lambda:self.core.receiving=="reconnecting")
        await self.core.dispatch({"op":"stop"}); await asyncio.sleep(.07)
        self.assertEqual(sum(r["op"]=="watch" for r in self.adapter.requests),1)
    async def test_fresh_account_has_metadata_only(self):
        target=MemoryStore(); connector=XConnector(target,adapter=self.adapter)
        await connector.connect(); self.assertEqual(set(target.load("x")),{"account_id","selections"})

class WorkerPipeTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_reply_and_eof_are_unknown_for_send(self):
        for reply in ("print('bad json',flush=True)","pass"):
            adapter=XAdapter([sys.executable,"-c","import sys; sys.stdin.readline(); "+reply])
            with self.assertRaises(AppError) as caught:
                async for _ in adapter.events({"op":"send"}): self.fail("Unexpected event")
            self.assertEqual(caught.exception.code,"X_SEND_UNKNOWN")
    async def test_ack_only_after_consumer_saved_history(self):
        code="import json,sys;sys.stdin.readline();print(json.dumps({'type':'history'}),flush=True);assert json.loads(sys.stdin.readline())=={'history_saved':True};print(json.dumps({'type':'done'}),flush=True)"
        events=[]
        async for event in XAdapter([sys.executable,"-c",code]).events({"op":"watch"}): events.append(event["type"])
        self.assertEqual(events,["history","done"])
    async def test_router_x_event_scope_and_no_cross_provider_operation(self):
        class Fake:
            def __init__(self,emit): self.emit=emit
            async def dispatch(self,request): self.emit({"event":"status"});return request
            async def close(self): pass
        events=[];router=DesktopRouter(emit=events.append,line_factory=Fake,x_factory=Fake)
        self.assertEqual(await router.dispatch({"op":"snapshot","provider":"x"}),{"op":"snapshot"})
        self.assertEqual(events[-1]["provider"],"x"); await router.close()
