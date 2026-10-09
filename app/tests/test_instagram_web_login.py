import copy
import unittest
from unittest.mock import AsyncMock

from beeperlocal.instagram_web_login import login_instagram_web, validate_result
from beeperlocal.errors import AppError
from .support import MemoryStore
from .test_instagram import FakeAdapter, SESSION_EVENT


class WebLoginTests(unittest.IsolatedAsyncioTestCase):
    def cookies(self): return copy.deepcopy(SESSION_EVENT['session']['cookies'])

    async def test_own_browser_session_is_verified_before_save_and_preserves_selection(self):
        store = MemoryStore()
        store.save('instagram', {'account_id': '123456', 'selections': [{'fixture': 'selection'}]})
        writes = list(store.writes)
        class VerifyAdapter(FakeAdapter):
            async def events(inner, request, **kwargs):
                self.assertEqual(store.writes, writes)
                self.assertEqual(request['op'], 'whoami')
                self.assertEqual(request['account_id'], '123456')
                yield copy.deepcopy(SESSION_EVENT)
                self.assertEqual(store.load('instagram')['selections'], [{'fixture': 'selection'}])
                yield {'type': 'result', 'account_id': '123456', 'own_fbid': '654321'}
        await login_instagram_web(store, adapter=VerifyAdapter(), browser=AsyncMock(return_value=self.cookies()))
        self.assertEqual(len(store.writes), len(writes) + 1)

    async def test_cancel_failed_identity_and_account_mismatch_never_overwrite_saved_login(self):
        for failure in ('cancel', 'unverified', 'mismatch'):
            with self.subTest(failure=failure):
                store = MemoryStore()
                store.save('instagram', {'account_id': 'old', 'selections': []})
                event = copy.deepcopy(SESSION_EVENT)
                event['account_id'] = '999999'
                adapter = FakeAdapter(event if failure == 'mismatch' else AppError('IG_AUTH_ACTION_REQUIRED'))
                browser = AsyncMock(side_effect=AppError('IG_LOGIN_CANCELLED')) if failure == 'cancel' else AsyncMock(return_value=self.cookies())
                with self.assertRaises(AppError): await login_instagram_web(store, adapter=adapter, browser=browser)
                self.assertEqual(store.writes, ['instagram'])
                self.assertEqual(store.load('instagram')['account_id'], 'old')
                self.assertEqual(len(adapter.requests), 0 if failure == 'cancel' else 1)

    async def test_rejects_untrusted_cookie_names_controls_and_missing_identity(self):
        for changed in ({'external_token': 'secret'}, {'sessionid': 'x\nsecret'}, {'ds_user_id': 'not-a-number'}, {'csrftoken': ''}):
            with self.subTest(changed=tuple(changed)), self.assertRaises(AppError):
                validate_result({'ok': True, 'cookies': {**self.cookies(), **changed}})
        with self.assertRaises(AppError) as caught:
            validate_result({'ok': False, 'error': 'cancelled'})
        self.assertEqual(caught.exception.code, 'IG_LOGIN_CANCELLED')
