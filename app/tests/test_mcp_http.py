"""Real loopback HTTP + independent official MCP SDK, with fixture-only LINE backend."""
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
import io
import json
import logging
import socket
from uuid import uuid4
import unittest

try:
    import httpx2
    from mcp import Client
    from mcp.client.streamable_http import streamable_http_client
    from beeperlocal.mcp_server import MAX_HTTP_BODY
    HAS_MCP = True
except ImportError:
    HAS_MCP = False

from .test_mcp_controls import ControlFixture


@unittest.skipUnless(HAS_MCP, 'desktop dependencies required')
class HTTPTests(ControlFixture):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        logging.disable(logging.CRITICAL)
        self.addCleanup(logging.disable, logging.NOTSET)
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        self.granted = self.grant(send=True)
        self.token = self.granted['token']
        self.url = f'http://127.0.0.1:{self.port}/mcp'
        await self.core.configure_mcp(True, self.port)

    def headers(self, **updates):
        return {'Authorization': 'Bearer ' + self.token, 'Accept': 'application/json, text/event-stream', **updates}

    async def test_modern_and_legacy_sdk_handshake_tools_and_scopes(self):
        # Transport is an independent client connection, not an in-process server shortcut.
        class AuthTransport:
            @asynccontextmanager
            async def connect(inner):
                async with httpx2.AsyncClient(headers=self.headers(), trust_env=False) as http:
                    async with streamable_http_client(self.url, http_client=http) as streams:
                        yield streams
        for mode in ('auto', 'legacy'):
            async with Client(AuthTransport().connect(), mode=mode, read_timeout_seconds=5) as client:
                listing = await client.list_tools()
                tools = listing.tools if hasattr(listing, 'tools') else listing
                self.assertEqual({t.name for t in tools}, {'list_conversations', 'get_messages', 'search_messages', 'send_message'})
                self.assertEqual((await client.list_resources()).resources, [])
                self.assertEqual((await client.list_prompts()).prompts, [])
                result = await client.call_tool('list_conversations', {})
                self.assertFalse(result.is_error)
                value = json.loads(result.content[0].text)
                self.assertEqual([c['id'] for c in value['conversations']], [self.record.id])
                saved = await client.call_tool('get_messages', {'conversation_id': self.record.id})
                self.assertFalse(saved.is_error)
                self.assertTrue(json.loads(saved.content[0].text)['messages'])
                found = await client.call_tool('search_messages', {'query': 'LINE_PRIVATE_BODY_CANARY'})
                self.assertFalse(found.is_error)
                self.assertEqual(len(json.loads(found.content[0].text)['results']), 1)
                denied = await client.call_tool('get_messages', {'conversation_id': self.other.id})
                self.assertTrue(denied.is_error)
                self.assertIn('MCP_ACCESS_DENIED', denied.content[0].text)
                sent = await client.call_tool('send_message', {'conversation_id': self.record.id, 'text': 'HTTP_SEND_CANARY', 'request_id': str(uuid4())})
                self.assertFalse(sent.is_error)
        self.assertEqual(self.backend.send_calls, 2)

    async def test_http_auth_host_origin_proxy_query_and_body_boundaries(self):
        async with httpx2.AsyncClient(trust_env=False) as client:
            for headers, status in [({}, 401), ({'Authorization': 'Bearer bad'}, 401),
                (self.headers(Origin='https://example.invalid'), 403),
                (self.headers(Host='evil.invalid'), 403), (self.headers(Forwarded='for=127.0.0.1'), 403),
                (self.headers(**{'X-Forwarded-For': '127.0.0.1'}), 403)]:
                response = await client.post(self.url, headers=headers, json={})
                self.assertEqual(response.status_code, status)
                self.assertNotIn(self.token, response.text)
            self.assertEqual((await client.post(self.url + '?token=x', headers=self.headers(), json={})).status_code, 404)
            self.assertEqual((await client.post(self.url, headers=self.headers(), content=b'x' * (MAX_HTTP_BODY + 1))).status_code, 413)
            self.assertEqual((await client.get(self.url + '/admin', headers=self.headers())).status_code, 404)
            duplicate = [('Host', f'127.0.0.1:{self.port}'), ('Authorization', 'Bearer ' + self.token), ('Authorization', 'Bearer ' + self.token)]
            self.assertEqual((await client.post(self.url, headers=duplicate, json={})).status_code, 400)

    async def test_revocation_and_restart_reject_old_token_immediately(self):
        async with httpx2.AsyncClient(trust_env=False) as client:
            self.core.access.revoke(self.granted['client']['id'], self.core.account_id)
            self.assertEqual((await client.post(self.url, headers=self.headers(), json={})).status_code, 401)
            await self.core.configure_mcp(False, self.port)
            await self.core.configure_mcp(True, self.port)
            self.assertEqual((await client.post(self.url, headers=self.headers(), json={})).status_code, 401)

    async def test_port_in_use_fails_closed_without_stopping_core(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0)); occupied.listen()
            await self.denied(self.core.configure_mcp(True, occupied.getsockname()[1]), 'MCP_PORT_IN_USE')
        self.assertFalse(self.core.settings['mcpEnabled'])
        self.assertEqual(len(self.core.snapshot()['conversations']), 2)

    async def test_chunked_body_limit_and_unexpected_server_error_are_sanitized(self):
        async def chunks():
            for _ in range(110): yield b'x' * 1024
        async with httpx2.AsyncClient(trust_env=False) as client:
            response = await client.post(self.url, headers=self.headers(), content=chunks())
            self.assertEqual(response.status_code, 413)
            original = self.core.mcp_call
            async def fail(*args, **kwargs):
                raise RuntimeError('PRIVATE_EXCEPTION_CANARY')
            self.core.mcp_call = fail
            response = await client.post(self.url, headers=self.headers(**{'MCP-Protocol-Version': '2025-11-25'}),
                json={'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': 'list_conversations', 'arguments': {}}})
            self.core.mcp_call = original
            self.assertNotIn('PRIVATE_EXCEPTION_CANARY', response.text)
            self.assertIn('UNEXPECTED_ERROR', response.text)
