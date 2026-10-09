from contextlib import redirect_stderr, redirect_stdout
import io
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from beeperlocal import slack_setup
from beeperlocal.errors import AppError
from .test_instagram_setup import Terminal


class SlackSetupTests(unittest.TestCase):
    def test_login_is_interactive_and_uses_native_store_once(self):
        out, err = Terminal(), Terminal()
        previous = logging.root.manager.disable
        with patch('sys.stdin', Terminal()), redirect_stdout(out), redirect_stderr(err), \
             patch.object(slack_setup, 'MacKeychain') as keychain, \
             patch.object(slack_setup, 'login_slack', new_callable=AsyncMock) as login:
            self.assertEqual(slack_setup.main(), 0)
            keychain.assert_called_once_with()
            login.assert_awaited_once_with(keychain.return_value)
        self.assertEqual(logging.root.manager.disable, previous)

    def test_noninteractive_login_never_reads_or_writes_credentials(self):
        for stdin, stderr in [(io.StringIO(), Terminal()), (Terminal(), io.StringIO())]:
            with self.subTest(), patch('sys.stdin', stdin), redirect_stderr(stderr), \
                 patch.object(slack_setup, 'MacKeychain') as keychain, \
                 patch.object(slack_setup, 'login_slack') as login:
                self.assertEqual(slack_setup.main(), 1)
                keychain.assert_not_called()
                login.assert_not_called()
                self.assertIn('INTERACTIVE_REQUIRED', stderr.getvalue())

    def test_failure_is_redacted_and_never_retried(self):
        for cause in (RuntimeError('TOKEN_CANARY'), AppError('CREDENTIALS_INVALID')):
            out, err = Terminal(), Terminal()
            with patch('sys.stdin', Terminal()), redirect_stdout(out), redirect_stderr(err), \
                 patch.object(slack_setup, 'MacKeychain'), \
                 patch.object(slack_setup, 'login_slack', side_effect=cause) as login:
                self.assertEqual(slack_setup.main(), 1)
                login.assert_called_once()
            self.assertNotIn('TOKEN_CANARY', out.getvalue() + err.getvalue())
            self.assertNotIn('Traceback', err.getvalue())

    def test_probe_does_not_access_keychain_items_or_network(self):
        with patch('beeperlocal.native_keychain.NativeKeychain') as native, \
             patch.object(slack_setup, 'MacKeychain') as store, \
             patch.object(slack_setup, 'login_binary', return_value='/fixture/slack-login'), \
             patch.object(slack_setup.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '{"selfTest":true}', '')), \
             patch.object(slack_setup, 'login_slack') as login, redirect_stdout(io.StringIO()):
            self.assertEqual(slack_setup.verify_runtime(), 0)
            native.return_value.get.assert_not_called()
            store.assert_not_called()
            login.assert_not_called()


class BundledSetupTests(unittest.TestCase):
    def test_helpers_work_inside_app_with_spaces_and_no_development_runtime(self):
        for name, provider in [('Instagram', 'instagram'), ('Slack', 'slack')]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory(prefix='beta 日本語 ') as temp:
                bundle = Path(temp) / 'BeeperLocal.app/Contents'
                scripts = bundle / 'Resources/resources'
                scripts.mkdir(parents=True)
                core = bundle / 'MacOS/beeperlocal-core'
                core.parent.mkdir()
                core.write_text(f'#!/bin/bash\n[[ "$1" = --verify-{provider}-login ]]\n')
                core.chmod(0o700)
                source = Path(__file__).resolve().parents[1] / f'desktop/src-tauri/resources/{name}接続.command'
                helper = scripts / source.name
                shutil.copyfile(source, helper)
                result = subprocess.run(['/bin/bash', str(helper), '--check'], input='',
                    capture_output=True, text=True, timeout=10, cwd='/private/tmp',
                    env={'PATH': '/usr/bin:/bin', 'HOME': temp})
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('準備OK', result.stdout)
                invalid = subprocess.run(['/bin/bash', str(helper), '--arbitrary'], input='',
                    capture_output=True, text=True, timeout=10, env={'PATH': '/usr/bin:/bin', 'HOME': temp})
                self.assertEqual(invalid.returncode, 2)
