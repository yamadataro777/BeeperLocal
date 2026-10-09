from contextlib import redirect_stderr, redirect_stdout
import io
import logging
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from beeperlocal import instagram_setup
from beeperlocal.connectors.instagram import login_instagram
from beeperlocal.errors import AppError
from .support import MemoryStore
from .test_instagram import FakeAdapter, SESSION_EVENT


class Terminal(io.StringIO):
    def isatty(self):
        return True


class InstagramSetupTests(unittest.TestCase):
    def test_login_uses_native_provider_store_and_only_requests_login(self):
        target = MemoryStore()
        adapter = FakeAdapter(SESSION_EVENT, {'type': 'result', 'account_id': '123456', 'own_fbid': '654321'})
        async def login(store):
            await login_instagram(store, adapter=adapter)
        out, err = Terminal(), Terminal()
        previous = logging.root.manager.disable
        with patch.object(instagram_setup, 'MacKeychain', return_value=target) as keychain, \
             patch.object(instagram_setup, 'login_instagram', side_effect=login), \
             patch('sys.stdin', Terminal()), redirect_stdout(out), redirect_stderr(err):
            self.assertEqual(instagram_setup.main(), 0)
        keychain.assert_called_once_with(service='BeeperLocalInstagramIntegration.v1')
        self.assertEqual(adapter.requests, [{'op': 'login'}])
        self.assertEqual(target.writes, ['instagram'])
        self.assertNotIn('FAKE_IG_SESSION_CANARY', out.getvalue() + err.getvalue())
        self.assertEqual(logging.root.manager.disable, previous)

    def test_noninteractive_invocation_never_accesses_credentials_or_provider(self):
        for stdin, stderr in [(io.StringIO(), Terminal()), (Terminal(), io.StringIO())]:
            with self.subTest(), patch('sys.stdin', stdin), redirect_stderr(stderr), \
                 patch.object(instagram_setup, 'MacKeychain') as keychain, \
                 patch.object(instagram_setup, 'login_instagram') as login:
                self.assertEqual(instagram_setup.main(), 1)
                self.assertIn('INTERACTIVE_REQUIRED', stderr.getvalue())
                keychain.assert_not_called()
                login.assert_not_called()

    def test_errors_do_not_leak_secrets_and_login_is_never_retried(self):
        for error, code, result in [(RuntimeError('PRIVATE_SECRET_CANARY'), 'UNEXPECTED_ERROR', 1),
                                    (AppError('CREDENTIALS_INVALID'), 'CREDENTIALS_INVALID', 1),
                                    (KeyboardInterrupt(), '中止', 130)]:
            out, err = Terminal(), Terminal()
            with self.subTest(code=code), patch('sys.stdin', Terminal()), \
                 redirect_stdout(out), redirect_stderr(err), \
                 patch.object(instagram_setup, 'MacKeychain'), \
                 patch.object(instagram_setup, 'login_instagram', side_effect=error) as login:
                self.assertEqual(instagram_setup.main(), result)
                login.assert_called_once()
            output = out.getvalue() + err.getvalue()
            self.assertIn(code, output)
            self.assertNotIn('PRIVATE_SECRET_CANARY', output)
            self.assertNotIn('Traceback', output)

    def test_runtime_probe_uses_only_an_unsupported_offline_operation(self):
        adapter = FakeAdapter(AppError('INVALID_INPUT'))
        process = AsyncMock()
        process.returncode = 0
        process.communicate.return_value = (b'native_login_boundary_checks_passed\n', None)
        out = io.StringIO()
        with patch.object(instagram_setup, 'InstagramAdapter', return_value=adapter), \
             patch.object(instagram_setup, 'login_binary', return_value='/fixture/native-login'), \
             patch('asyncio.create_subprocess_exec', return_value=process) as spawn, \
             patch('beeperlocal.native_keychain.NativeKeychain') as native, \
             patch.object(instagram_setup, 'MacKeychain') as keychain, redirect_stdout(out):
            self.assertEqual(instagram_setup.verify_runtime(), 0)
        native.assert_called_once_with()
        native.return_value.get.assert_not_called()
        keychain.assert_not_called()
        self.assertEqual(adapter.requests, [{'op': 'unsupported'}])
        self.assertEqual(spawn.call_args.args, ('/fixture/native-login', '--self-test'))
        self.assertIn('true', out.getvalue())


class PortableInstagramCommandTests(unittest.TestCase):
    def run_helper(self, core_script, args=(), nested=False):
        with tempfile.TemporaryDirectory(prefix='IG 日本語 ') as temp:
            root = Path(temp)
            directory = root / 'tools' if nested else root
            directory.mkdir(exist_ok=True)
            helper = directory / 'Instagram接続.command'
            shutil.copyfile(Path(__file__).resolve().parents[2] / 'tools/Instagram接続.command', helper)
            core = root / 'BeeperLocal.app/Contents/MacOS/beeperlocal-core'
            core.parent.mkdir(parents=True)
            core.write_text('#!/bin/bash\n' + core_script)
            core.chmod(0o700)
            return subprocess.run(['/bin/bash', str(helper), *args], input='', capture_output=True,
                                  text=True, timeout=10, cwd='/private/tmp',
                                  env={'PATH': '/usr/bin:/bin', 'HOME': str(root)})

    def test_app_only_copy_works_without_development_python_including_tools_layout(self):
        for nested in (False, True):
            with self.subTest(nested=nested):
                result = self.run_helper('[[ "$1" = --verify-instagram-login ]]\n', ['--check'], nested)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('準備OK', result.stdout)

    def test_incompatible_app_stops_before_login_with_actionable_message(self):
        result = self.run_helper('exit 2\n')
        self.assertEqual(result.returncode, 1)
        self.assertIn('修正版のBeeperLocal.app', result.stderr)
        self.assertNotIn('python', result.stderr.lower())

    def test_failed_login_exit_code_is_preserved(self):
        result = self.run_helper('if [[ "$1" = --verify-instagram-login ]]; then exit 0; fi\nexit 130\n')
        self.assertEqual(result.returncode, 130)

    def test_extra_arguments_are_rejected_before_running_core(self):
        result = self.run_helper('echo CORE_SHOULD_NOT_RUN\n', ['--check', 'PRIVATE_SECRET_CANARY'])
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('CORE_SHOULD_NOT_RUN', result.stdout)
        self.assertNotIn('PRIVATE_SECRET_CANARY', result.stdout + result.stderr)
