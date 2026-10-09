"""Public-client OAuth fixtures: no real browser, Keychain or provider requests."""
from copy import deepcopy
import unittest
from urllib.parse import parse_qs, urlsplit

from beeperlocal.errors import AppError
from beeperlocal.slack_oauth import SCOPES, SlackOAuth, challenge, exchange, refresh_credentials
from .support import MemoryStore, FakeOpener, Response
from beeperlocal.slack_web_login import validate_result


TOKEN = {'ok': True, 'authed_user': {'token_type': 'user', 'access_token': 'xoxe.xoxp-FIXTURE',
          'refresh_token': 'xoxe-FIXTURE-NEW', 'expires_in': 43200, 'scope': SCOPES}}


class TokenTests(unittest.TestCase):
    def test_native_callback_requires_matching_state_and_fixed_error(self):
        self.assertEqual(validate_result({'ok': True, 'state': 'fixture-state', 'code': 'fixture-code'}, 'fixture-state'), 'fixture-code')
        for result in [{'ok': True, 'state': 'wrong', 'code': 'fixture-code'},
                       {'ok': True, 'state': 'fixture-state', 'code': 'bad\ncode'},
                       {'ok': False, 'error': 'PRIVATE_REMOTE_ERROR'}]:
            with self.subTest(result=result), self.assertRaises(AppError): validate_result(result, 'fixture-state')
    def test_standard_challenge(self):
        self.assertEqual(challenge('dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'),
                         'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM')

    def test_token_exchange_uses_post_without_client_secret(self):
        opener = FakeOpener(Response(TOKEN))
        exchange({'code': 'FIXTURE_CODE', 'code_verifier': 'FIXTURE_VERIFIER', 'client_id': '123.456'}, opener=opener)
        req = opener.requests[0]
        self.assertEqual(req.full_url, 'https://slack.com/api/oauth.v2.access')
        self.assertEqual(req.method, 'POST')
        self.assertNotIn(b'client_secret', req.data)
        self.assertNotIn('FIXTURE', req.full_url)

    def test_refresh_updates_pair_once_and_preserves_selection(self):
        current = {'token': 'xoxe.xoxp-OLD', 'refresh_token': 'xoxe-OLD', 'oauth_client_id': '123.456',
                   'account_id': 'T001:U001', 'selections': [{'fixture': True}], 'expires_at': 900}
        store = MemoryStore({'slack': deepcopy(current)})
        calls = []
        def exchange_fn(fields):
            calls.append(fields)
            return TOKEN
        result = refresh_credentials(store, current, exchange_fn=exchange_fn, now=1000)
        self.assertEqual(result['selections'], current['selections'])
        self.assertEqual(result['refresh_token'], 'xoxe-FIXTURE-NEW')
        self.assertEqual(result['expires_at'], 44200)
        self.assertNotIn('client_secret', calls[0])
        refresh_credentials(store, result, exchange_fn=exchange_fn, now=1001)
        self.assertEqual(len(calls), 1)

    def test_provider_error_is_reduced_to_fixed_codes(self):
        for source, expected in [('invalid_client_secret', 'SLACK_OAUTH_NOT_CONFIGURED'),
                                 ('invalid_scope', 'SLACK_OAUTH_PERMISSIONS_REQUIRED'),
                                 ('PRIVATE_REMOTE_VALUE', 'SLACK_OAUTH_FAILED')]:
            with self.subTest(source=source), self.assertRaises(AppError) as caught:
                exchange({}, opener=FakeOpener(Response({'ok': False, 'error': source})))
            self.assertEqual(caught.exception.code, expected)


class BrowserTests(unittest.IsolatedAsyncioTestCase):
    async def test_native_browser_pkce_path_saves_only_after_identity_and_grants(self):
        observed = {}
        async def browser(url, state):
            observed.update(parse_qs(urlsplit(url).query))
            self.assertEqual(observed['state'], [state])
            self.assertEqual(observed['redirect_uri'], ['beeperlocal://oauth/slack'])
            self.assertNotIn('code_verifier', observed)
            return 'FIXTURE_CODE'
        def exchange_fn(fields):
            self.assertEqual(observed['code_challenge'], [challenge(fields['code_verifier'])])
            self.assertNotIn('client_secret', fields)
            self.assertEqual(fields['redirect_uri'], 'beeperlocal://oauth/slack')
            return TOKEN
        class API:
            def __init__(self, token): pass
            def call(self, method): return {'team_id': 'T001', 'user_id': 'U001'}
        store = MemoryStore()
        result = await SlackOAuth(store, client_id='123.456', redirect_uri='beeperlocal://oauth/slack',
                                 native_browser=browser, exchange_fn=exchange_fn, api_factory=API).login()
        self.assertEqual(result, 'T001:U001')
        self.assertEqual(store.load('slack')['account_id'], result)
    async def test_missing_grants_keep_existing_credentials_and_do_not_call_auth_test(self):
        old = {'token': 'xoxp-FIXTURE-OLD', 'account_id': 'T001:U001'}
        store = MemoryStore({'slack': deepcopy(old)})
        async def browser(url, state): return 'FIXTURE_CODE'
        response = deepcopy(TOKEN)
        response['authed_user']['scope'] = 'chat:write'
        def never_api(token): self.fail('API called without required grants')
        with self.assertRaises(AppError) as caught:
            await SlackOAuth(store, client_id='123.456', native_browser=browser,
                             exchange_fn=lambda fields: response, api_factory=never_api).login()
        self.assertEqual(caught.exception.code, 'SLACK_OAUTH_PERMISSIONS_REQUIRED')
        self.assertEqual(store.load('slack'), old)

    async def test_native_failure_never_exchanges_or_changes_credentials(self):
        old = {'token': 'xoxp-FIXTURE-OLD', 'account_id': 'T001:U001'}
        for result, expected in [({'ok': True, 'state': 'WRONG', 'code': 'FIXTURE_CODE'}, 'SLACK_OAUTH_FAILED'),
                                 ({'ok': False, 'error': 'cancelled'}, 'SLACK_OAUTH_CANCELLED')]:
            store = MemoryStore({'slack': deepcopy(old)})
            async def browser(url, state): return validate_result(result, state)
            def never(fields): self.fail('exchange called after native failure')
            with self.subTest(expected=expected), self.assertRaises(AppError) as caught:
                await SlackOAuth(store, client_id='123.456', native_browser=browser, exchange_fn=never).login()
            self.assertEqual(caught.exception.code, expected)
            self.assertEqual(store.load('slack'), old)

    async def test_only_configured_native_redirect_is_accepted_before_login(self):
        async def never(*args): self.fail('browser called with unsupported configuration')
        for client, redirect in [('', 'beeperlocal://oauth/slack'),
                                 ('123.456', 'http://localhost:28647/oauth/slack'),
                                 ('123.456', 'https://example.test/oauth/slack'),
                                 ('123.456', 'beeperlocal://oauth/slack?state=other')]:
            oauth = SlackOAuth(MemoryStore(), client_id=client, redirect_uri=redirect, native_browser=never)
            with self.subTest(redirect=redirect):
                with self.assertRaises(AppError) as caught:
                    oauth.check_configuration()
                self.assertEqual(caught.exception.code, 'SLACK_OAUTH_NOT_CONFIGURED')

    async def test_account_change_never_overwrites_existing_credentials(self):
        old = {'token': 'xoxp-FIXTURE-OLD', 'account_id': 'T001:U001'}
        store = MemoryStore({'slack': deepcopy(old)})
        async def browser(url, state): return 'FIXTURE_CODE'
        class API:
            def __init__(self, token): pass
            def call(self, method): return {'team_id': 'T001', 'user_id': 'U002'}
        with self.assertRaises(AppError) as caught:
            await SlackOAuth(store, client_id='123.456', native_browser=browser,
                             exchange_fn=lambda fields: TOKEN, api_factory=API).login()
        self.assertEqual(caught.exception.code, 'ACCOUNT_CHANGED')
        self.assertEqual(store.load('slack'), old)
