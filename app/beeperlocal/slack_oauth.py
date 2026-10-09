"""Slack public-client PKCE. Codes, verifiers and tokens never enter the WebView."""
from __future__ import annotations

import asyncio
import base64
from hashlib import sha256
import json
import re
import secrets
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPSHandler, ProxyHandler

from .errors import AppError
from .connectors.slack import NoRedirect, SlackAPI, account_identity
from .release_config import SLACK_CLIENT_ID, SLACK_REDIRECT_URI
from .tls import client_context
from .slack_web_login import authorization_code

SCOPES = 'channels:read,channels:history,groups:read,groups:history,im:read,im:history,mpim:read,mpim:history,users:read,chat:write,files:read,files:write'


def challenge(verifier):
    return base64.urlsafe_b64encode(sha256(verifier.encode('ascii')).digest()).decode('ascii').rstrip('=')


def exchange(fields, *, opener=None):
    opener = opener or build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=client_context()))
    request = Request('https://slack.com/api/oauth.v2.access', data=urlencode(fields).encode('ascii'),
                      headers={'Content-Type': 'application/x-www-form-urlencoded'}, method='POST')
    try:
        with opener.open(request, timeout=25) as response:
            raw = response.read(65537)
        if len(raw) > 65536:
            raise ValueError()
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError()
        if data.get('ok') is not True:
            codes = {'invalid_client_id': 'SLACK_OAUTH_NOT_CONFIGURED',
                     'bad_client_secret': 'SLACK_OAUTH_NOT_CONFIGURED',
                     'invalid_client_secret': 'SLACK_OAUTH_NOT_CONFIGURED',
                     'invalid_redirect_uri': 'SLACK_OAUTH_NOT_CONFIGURED',
                     'invalid_scope': 'SLACK_OAUTH_PERMISSIONS_REQUIRED',
                     'invalid_refresh_token': 'SLACK_LOGIN_REQUIRED'}
            code = data.get('error')
            raise AppError(codes.get(code, 'SLACK_OAUTH_FAILED') if isinstance(code, str) else 'SLACK_OAUTH_FAILED')
        return data
    except HTTPError as exc:
        exc.close()
        raise AppError('SLACK_OAUTH_FAILED') from None
    except (URLError, OSError, ValueError, TypeError):
        raise AppError('SLACK_OAUTH_FAILED') from None


def token_fields(data, *, client_id, now=None):
    user = data.get('authed_user', data)
    if not isinstance(user, dict) or user.get('token_type') != 'user':
        raise AppError('BOT_TOKEN_NOT_SUPPORTED')
    token = user.get('access_token')
    if not isinstance(token, str) or not token.startswith(('xoxp-', 'xoxe.xoxp-')) or any(c.isspace() for c in token):
        raise AppError('SLACK_OAUTH_FAILED')
    result = {'token': token, 'oauth_client_id': client_id}
    refresh = user.get('refresh_token')
    expires = user.get('expires_in')
    if refresh is not None or expires is not None:
        if (not isinstance(refresh, str) or not refresh.startswith('xoxe-') or len(refresh) > 4096
                or any(c.isspace() for c in refresh) or type(expires) is not int or not 60 <= expires <= 86400):
            raise AppError('SLACK_OAUTH_FAILED')
        result.update(refresh_token=refresh, expires_at=(time.time() if now is None else now) + expires)
    return result


def refresh_credentials(store, current, *, exchange_fn=exchange, now=None):
    stamp = time.time() if now is None else now
    if 'expires_at' not in current:
        return current
    expires = current['expires_at']
    if not isinstance(expires, (int, float)) or isinstance(expires, bool):
        raise AppError('CREDENTIALS_CORRUPT')
    if expires > stamp + 120:
        return current
    refresh, client = current.get('refresh_token'), current.get('oauth_client_id')
    if not isinstance(refresh, str) or not isinstance(client, str) or not re.fullmatch(r'\d+\.\d+', client):
        raise AppError('SLACK_LOGIN_REQUIRED')
    data = exchange_fn({'grant_type': 'refresh_token', 'refresh_token': refresh, 'client_id': client})
    updated = {**current, **token_fields(data, client_id=client, now=stamp)}
    if not updated.get('refresh_token') or updated.get('refresh_token') == refresh:
        raise AppError('SLACK_OAUTH_FAILED')
    store.save('slack', updated)  # One native Keychain replacement, including the new refresh token.
    return updated


class SlackOAuth:
    def __init__(self, store, *, client_id=SLACK_CLIENT_ID, redirect_uri=SLACK_REDIRECT_URI,
                 exchange_fn=exchange, api_factory=SlackAPI, native_browser=authorization_code):
        self.store, self.client_id, self.redirect_uri = store, client_id, redirect_uri
        self.exchange, self.api_factory, self.native_browser = exchange_fn, api_factory, native_browser

    def check_configuration(self):
        if (not isinstance(self.client_id, str) or not re.fullmatch(r'\d+\.\d+', self.client_id)
                or self.redirect_uri != 'beeperlocal://oauth/slack'):
            raise AppError('SLACK_OAUTH_NOT_CONFIGURED')

    async def login(self, account=''):
        self.check_configuration()
        verifier, state = secrets.token_urlsafe(64), secrets.token_urlsafe(32)
        url = 'https://slack.com/oauth/v2/authorize?' + urlencode({
            'client_id': self.client_id, 'user_scope': SCOPES, 'scope': '',
            'redirect_uri': self.redirect_uri, 'state': state,
            'code_challenge': challenge(verifier), 'code_challenge_method': 'S256'})
        code = await self.native_browser(url, state)
        return await self._exchange_and_save(code, verifier, account)

    async def _exchange_and_save(self, code, verifier, account):
        data = await asyncio.to_thread(self.exchange, {'client_id': self.client_id, 'code': code,
            'redirect_uri': self.redirect_uri, 'code_verifier': verifier})
        fields = token_fields(data, client_id=self.client_id)
        scopes = data.get('authed_user', {}).get('scope')
        if not isinstance(scopes, str) or not set(SCOPES.split(',')) <= set(scopes.split(',')):
            raise AppError('SLACK_OAUTH_PERMISSIONS_REQUIRED')
        auth = await asyncio.to_thread(self.api_factory(fields['token']).call, 'auth.test')
        identity = account_identity(auth)
        if account and identity != account:
            raise AppError('ACCOUNT_CHANGED')
        try:
            old = self.store.load('slack')
        except AppError as exc:
            if exc.code != 'CREDENTIALS_MISSING':
                raise
            old = {}
        if old.get('account_id') not in {None, identity}:
            raise AppError('ACCOUNT_CHANGED')
        self.store.save('slack', {**fields, 'account_id': identity, 'selections': old.get('selections', [])})
        return identity
