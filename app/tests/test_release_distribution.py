"""Release gates exercise external-tool failures with fixtures, never upload to Apple."""
from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import macos_notarize as notarize
from scripts.release_preflight import REQUIRED_SCOPES, REDIRECT, validate_settings, verify
from scripts import macos_compatibility, macos_signing, release_preflight

IDENTITY = 'f328cc05-252b-4b5f-9484-47aaed4d604b'
STATE = {'schema': 1, 'status': 'prepared', 'signature': {'cdhash': 'a' * 40, 'team_id': 'AAAAAAAAAA'},
         'archive_sha256': 'b' * 64}
SETTINGS = {'SLACK_CLIENT_ID': '123.456', 'SLACK_REDIRECT_URI': REDIRECT, 'SLACK_DISTRIBUTION_READY': True}
MANIFEST = {'oauth_config': {'pkce_enabled': True, 'redirect_urls': [REDIRECT],
                          'scopes': {'user': sorted(REQUIRED_SCOPES)}},
            'settings': {'token_rotation_enabled': True}}


class ReleaseSettingsTests(unittest.TestCase):
    def test_missing_or_unverified_slack_cannot_be_distributed(self):
        for change in [{'SLACK_CLIENT_ID': ''}, {'SLACK_CLIENT_ID': 'token:SECRET'},
                       {'SLACK_REDIRECT_URI': 'https://example.com'}, {'SLACK_DISTRIBUTION_READY': False}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings({**SETTINGS, **change}, MANIFEST)
        self.assertTrue(validate_settings(SETTINGS, MANIFEST)['slackDistributionReady'])

    def test_bot_secret_client_and_missing_image_scopes_are_rejected(self):
        for change in [{'pkce_enabled': False}, {'scopes': {'bot': ['chat:write'], 'user': sorted(REQUIRED_SCOPES)}},
                       {'scopes': {'user': sorted(REQUIRED_SCOPES - {'files:write'})}}]:
            manifest = deepcopy(MANIFEST)
            manifest['oauth_config'].update(change)
            with self.subTest(change=change), self.assertRaises(ValueError):
                validate_settings(SETTINGS, manifest)

    def test_frozen_settings_must_match_source_not_just_a_success_exit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'beeperlocal').mkdir()
            (root / 'beeperlocal/release_config.py').write_text('\n'.join(f'{k} = {v!r}' for k, v in SETTINGS.items()))
            (root / 'slack-send-app-manifest.json').write_text(json.dumps(MANIFEST))
            result = type('Result', (), {'returncode': 0, 'stdout': json.dumps({'slackOAuthConfigured': False})})()
            with patch('scripts.release_preflight.subprocess.run', return_value=result), self.assertRaisesRegex(ValueError, 'FROZEN_RELEASE_SETTINGS_MISMATCH'):
                verify(root / 'BeeperLocal.app', root=root)


class NotarizationTests(unittest.TestCase):
    def test_upload_failure_is_persisted_as_unknown_and_cannot_resubmit(self):
        state = deepcopy(STATE)
        saved = []
        def save(folder, value): saved.append(deepcopy(value))
        with patch.object(notarize, 'load', return_value=state), patch.object(notarize, 'save', side_effect=save), \
             patch.object(notarize, 'notary', side_effect=[{}, notarize.NotaryError('TIMEOUT')]):
            with self.assertRaises(notarize.NotaryError): notarize.submit(Path('/fixture'), 'fixture-profile')
        self.assertEqual(saved[-1]['status'], 'submitting')
        with patch.object(notarize, 'load', return_value=saved[-1]), patch.object(notarize, 'notary') as upload:
            with self.assertRaises(notarize.NotaryError): notarize.submit(Path('/fixture'), 'fixture-profile')
            upload.assert_not_called()

    def test_accepted_job_must_match_uploaded_archive_before_stapling(self):
        state = {**STATE, 'status': 'submitted', 'submission_id': IDENTITY}
        for digest in ['c' * 64, STATE['archive_sha256']]:
            with self.subTest(digest=digest), patch.object(notarize, 'load', return_value=deepcopy(state)), \
                 patch.object(notarize, 'save') as save, patch.object(notarize, 'notary', side_effect=[
                    {'id': IDENTITY, 'status': 'Accepted'},
                    {'jobId': IDENTITY, 'status': 'Accepted', 'sha256': digest, 'issues': None}]):
                if digest != STATE['archive_sha256']:
                    with self.assertRaisesRegex(notarize.NotaryError, 'ARCHIVE_MISMATCH'):
                        notarize.status(Path('/fixture'), 'fixture-profile')
                    save.assert_not_called()
                else:
                    self.assertEqual(notarize.status(Path('/fixture'), 'fixture-profile')['status'], 'Accepted')

    def test_pending_and_invalid_jobs_never_staple(self):
        for status in ['In Progress', 'Invalid']:
            with self.subTest(status=status), patch.object(notarize, 'status', return_value={'status': status}), \
                 patch.object(notarize, 'run') as native:
                with self.assertRaisesRegex(notarize.NotaryError, 'NOT_ACCEPTED'):
                    notarize.staple(Path('/fixture'), 'fixture-profile')
                native.assert_not_called()

    def test_accepted_ticket_still_requires_gatekeeper_acceptance(self):
        with patch.object(notarize, 'signature', return_value=STATE['signature']), \
             patch.object(notarize, 'run', side_effect=['ticket OK', 'source=Developer ID']):
            with self.assertRaisesRegex(notarize.NotaryError, 'GATEKEEPER'):
                notarize.verify_distribution(Path('/fixture/BeeperLocal.app'))

    def test_resume_known_job_does_not_reupload(self):
        state = {**STATE, 'status': 'submitted', 'submission_id': IDENTITY}
        with patch.object(notarize, 'load', return_value=state), patch.object(notarize, 'save'), \
             patch.object(notarize, 'notary', return_value={'id': IDENTITY, 'status': 'In Progress'}) as api:
            self.assertEqual(notarize.status(Path('/fixture'), 'fixture-profile')['status'], 'In Progress')
            self.assertEqual(api.call_args.args[0], 'info')

    def test_changed_staged_app_or_zip_is_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state.json').write_text(json.dumps(STATE))
            (root / 'upload.zip').write_bytes(b'changed')
            with self.assertRaisesRegex(notarize.NotaryError, 'ARCHIVE_CHANGED'):
                notarize.load(root)

    def test_native_failures_do_not_print_account_or_secret_output(self):
        result = type('Result', (), {'returncode': 1, 'stdout': 'SECRET', 'stderr': 'PRIVATE_ACCOUNT'})()
        with patch.object(notarize.subprocess, 'run', return_value=result), self.assertRaises(notarize.NotaryError) as caught:
            notarize.run('/usr/bin/xcrun', 'notarytool', 'history')
        self.assertNotIn('SECRET', str(caught.exception))
        self.assertNotIn('PRIVATE_ACCOUNT', str(caught.exception))


class ArchivePublicationTests(unittest.TestCase):
    def test_final_zip_name_is_never_published_before_extracted_app_passes(self):
        script = Path(__file__).resolve().parents[1] / 'scripts/package-beta.py'
        spec = importlib.util.spec_from_file_location('release_package_fixture', script)
        package = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {'macos_compatibility': macos_compatibility, 'macos_signing': macos_signing,
                                      'macos_notarize': notarize, 'release_preflight': release_preflight}):
            spec.loader.exec_module(package)
        for extraction_passes in [False, True]:
            with self.subTest(extraction_passes=extraction_passes), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                app = root / 'input/BeeperLocal.app'
                (app / 'Contents').mkdir(parents=True)
                (app / 'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier': 'local.beeperlocal.desktop',
                                                                        'CFBundleShortVersionString': '0.9.4'}))
                (root / 'docs').mkdir()
                for name in ['BETA_INSTALL.md', 'INBOX_0_9.md', 'BETA_READINESS.md', 'desktop-0.9.4-verification.json',
                             'MCP_0_9_1.md', 'BEEPER_UI_UX_REFERENCE.md', 'FRESH_MAC_AUDIT.md', 'USER_FEEDBACK_0_9_3.md']:
                    (root / 'docs' / name).write_text('{}')
                def native(*args):
                    if '-c' in args and '-k' in args:
                        Path(args[-1]).write_bytes(b'fixture archive')
                passed = {'notarization': 'accepted'}
                verification = [passed, passed, passed if extraction_passes else notarize.NotaryError('BAD_TICKET')]
                output = root / 'output'
                archive = output / 'BeeperLocal-0.9.4-AppleSilicon-beta.zip'
                with patch.object(package, '__file__', str(root / 'scripts/package-beta.py')), \
                     patch.object(package, 'sources', return_value=[]), patch.object(package, 'run', side_effect=native), \
                     patch.object(package, 'verify_compatibility', return_value={'passed': True}), \
                     patch.object(package, 'verify_release_settings', return_value={'slackDistributionReady': True}), \
                     patch.object(package, 'verify_distribution', side_effect=verification):
                    if extraction_passes:
                        self.assertEqual(package.package(app, output, '0.9.4')['audience'], 'friends')
                        self.assertTrue(archive.exists())
                        self.assertTrue(archive.with_suffix('.sha256').exists())
                    else:
                        with self.assertRaises(notarize.NotaryError): package.package(app, output, '0.9.4')
                        self.assertFalse(archive.exists())
                        self.assertFalse(archive.with_suffix('.sha256').exists())
                    self.assertFalse(list(output.glob('.beeperlocal-package-*')))
