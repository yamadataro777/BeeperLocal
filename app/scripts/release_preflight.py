#!/usr/bin/env python3
"""Fail closed before producing a friend-distribution build or archive."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SCOPES = {'channels:read', 'channels:history', 'groups:read', 'groups:history',
                   'im:read', 'im:history', 'mpim:read', 'mpim:history', 'users:read',
                   'chat:write', 'files:read', 'files:write'}
REDIRECT = 'beeperlocal://oauth/slack'


def source_settings(root=ROOT):
    # Parse literals instead of executing a source file during release verification.
    values = {}
    for node in ast.parse((root / 'beeperlocal/release_config.py').read_text()).body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            values[node.targets[0].id] = ast.literal_eval(node.value)
    return values


def validate_settings(settings, manifest, *, distribution=True):
    client = settings.get('SLACK_CLIENT_ID')
    if not isinstance(client, str) or not re.fullmatch(r'[0-9]{1,32}\.[0-9]{1,32}', client):
        raise ValueError('SLACK_PUBLIC_CLIENT_ID_REQUIRED')
    oauth = manifest.get('oauth_config', {})
    if (settings.get('SLACK_REDIRECT_URI') != REDIRECT or oauth.get('redirect_urls') != [REDIRECT]
            or oauth.get('pkce_enabled') is not True or oauth.get('scopes', {}).get('bot')
            or set(oauth.get('scopes', {}).get('user', [])) != REQUIRED_SCOPES
            or manifest.get('settings', {}).get('token_rotation_enabled') is not True):
        raise ValueError('SLACK_PUBLIC_CLIENT_MANIFEST_MISMATCH')
    if distribution and settings.get('SLACK_DISTRIBUTION_READY') is not True:
        raise ValueError('SLACK_SERVER_CONFIGURATION_NOT_VERIFIED')
    return {'slackOAuthConfigured': True, 'slackClientId': client, 'slackRedirectUri': REDIRECT,
            'slackDistributionReady': settings.get('SLACK_DISTRIBUTION_READY') is True}


def verify(app=None, *, root=ROOT, distribution=True):
    expected = validate_settings(source_settings(root), json.loads((root / 'slack-send-app-manifest.json').read_text()),
                                 distribution=distribution)
    if app:
        core = app / 'Contents/MacOS/beeperlocal-core'
        # Test the frozen artifact with an empty home and no development environment.
        with tempfile.TemporaryDirectory(prefix='beeperlocal-release-check-') as home:
            try:
                proc = subprocess.run([str(core), '--release-status'], capture_output=True, text=True, timeout=45,
                                      env={'HOME': home, 'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'TMPDIR': home})
                actual = json.loads(proc.stdout)
            except (OSError, ValueError, subprocess.TimeoutExpired):
                raise ValueError('FROZEN_RELEASE_SETTINGS_UNAVAILABLE') from None
        if proc.returncode or actual != expected:
            raise ValueError('FROZEN_RELEASE_SETTINGS_MISMATCH')
    return expected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.app.resolve() if args.app else None)))
    except (ValueError, OSError, SyntaxError):
        print('{"ready":false,"error":"RELEASE_SETTINGS_INCOMPLETE"}')
        raise SystemExit(1)
