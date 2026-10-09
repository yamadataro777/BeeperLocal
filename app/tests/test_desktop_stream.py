"""Exercise the actual NDJSON dispatcher with delayed provider replies."""
import asyncio
import json
import unittest

from beeperlocal.desktop import serve_stream
from beeperlocal.desktop_router import DesktopRouter


class Lane:
    def __init__(self, gate=None, started=None, prepared=None, emit=None):
        self.gate, self.started, self.prepared = gate, started, prepared
        self.operation_lock = asyncio.Lock()
    async def dispatch(self, request):
        if request['op'] == 'connect':
            self.started.set()
            await self.gate.wait()
        return {'op': request['op']}
    async def cancel_login(self): pass
    async def _stop_mcp(self): pass
    async def clear_media(self): pass
    async def stop_watch(self):
        if self.prepared is not None: self.prepared.append(True)
    def _notify(self, *args, **kwargs): pass
    def _status(self): return {}


class StreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_provider_keeps_other_service_responsive_and_update_is_a_barrier(self):
        gate, started = asyncio.Event(), asyncio.Event()
        prepared, replies = [], []
        router = DesktopRouter(line_factory=lambda **kw: Lane(gate, started, prepared, **kw), x_factory=Lane)
        reader = asyncio.StreamReader()
        changed = asyncio.Event()
        def emit(value):
            replies.append(value); changed.set()
        runner = asyncio.create_task(serve_stream(reader, router, emit))
        def write(identity, request):
            reader.feed_data(json.dumps({'id': identity, 'request': request}).encode() + b'\n')
        try:
            write(1, {'provider': 'line', 'op': 'connect'})
            await asyncio.wait_for(started.wait(), 1)
            write(2, {'provider': 'line', 'op': 'snapshot'})
            write(3, {'provider': 'x', 'op': 'snapshot'})
            await asyncio.wait_for(changed.wait(), 1)
            self.assertEqual([r['id'] for r in replies], [3])
            write(4, {'op': 'prepare_update'})
            write(5, {'provider': 'x', 'op': 'snapshot'})
            reader.feed_eof()
            await asyncio.sleep(0)
            self.assertEqual(prepared, [])
            gate.set()
            await asyncio.wait_for(runner, 1)
            self.assertEqual([r['id'] for r in replies], [3, 1, 2, 4, 5])
            self.assertTrue(all(r['ok'] for r in replies))
            self.assertEqual(prepared, [True])
        finally:
            gate.set()
            runner.cancel()
            await asyncio.gather(runner, return_exceptions=True)

    async def test_invalid_frames_do_not_prevent_subsequent_startup_ping(self):
        reader = asyncio.StreamReader()
        replies = []
        reader.feed_data(b'not-json\n' + json.dumps({'id': 7, 'request': {'op': 'ping'}}).encode() + b'\n')
        reader.feed_eof()
        await serve_stream(reader, DesktopRouter(), replies.append)
        self.assertEqual(replies[0]['error'], 'UNEXPECTED_ERROR')
        self.assertTrue(replies[1]['result']['ready'])
