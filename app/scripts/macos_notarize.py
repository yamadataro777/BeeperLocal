#!/usr/bin/env python3
"""Explicit, resumable notarization of a private copy; never modifies the installed app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

try:
    from . import macos_signing
except ImportError:
    import macos_signing


class NotaryError(Exception):
    pass


def run(*args, timeout=120):
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        raise NotaryError('NOTARY_COMMAND_UNAVAILABLE_OR_TIMEOUT') from None
    if result.returncode:
        raise NotaryError('NOTARY_COMMAND_FAILED: ' + Path(args[0]).name)
    return result.stdout + result.stderr


def notary(operation, profile, *args):
    if not profile or len(profile) > 128 or any(ord(c) < 32 for c in profile):
        raise NotaryError('NOTARY_KEYCHAIN_PROFILE_REQUIRED')
    raw = run('/usr/bin/xcrun', 'notarytool', operation, *args,
              '--keychain-profile', profile, '--output-format', 'json', '--no-progress', timeout=600)
    try:
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise NotaryError('NOTARY_INVALID_RESPONSE') from None


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def submission_id(value):
    try:
        return str(uuid.UUID(value))
    except (ValueError, TypeError, AttributeError):
        raise NotaryError('NOTARY_INVALID_SUBMISSION_ID') from None


def signature(app):
    run('/usr/bin/codesign', '--verify', '--deep', '--strict', str(app))
    details = run('/usr/bin/codesign', '--display', '--verbose=4', str(app))
    team = re.search(r'^TeamIdentifier=([A-Z0-9]{10})$', details, re.M)
    cdhash = re.search(r'^CDHash=([a-f0-9]{40})$', details, re.M)
    if not team or not cdhash:
        raise NotaryError('DEVELOPER_ID_REQUIRED')
    macos_signing.inspect_signature(app, 'release', team[1], macos_signing.APP_ID)
    return {'team_id': team[1], 'cdhash': cdhash[1]}


def save(folder, state):
    temporary = folder / 'state.json.tmp'
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(state, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(folder / 'state.json')


def load(folder):
    if folder.is_symlink():
        raise NotaryError('NOTARY_INVALID_WORK_DIRECTORY')
    state = json.loads((folder / 'state.json').read_text())
    if state.get('schema') != 1:
        raise NotaryError('NOTARY_INVALID_STATE')
    if digest(folder / 'upload.zip') != state['archive_sha256']:
        raise NotaryError('NOTARY_ARCHIVE_CHANGED')
    if signature(folder / 'BeeperLocal.app') != state['signature']:
        raise NotaryError('NOTARY_APP_CHANGED')
    return state


def prepare(app, folder):
    if folder.exists():
        raise NotaryError('NOTARY_WORK_DIRECTORY_EXISTS')
    signed = signature(app)
    macos_signing.verify(app, 'release', signed['team_id'])
    folder.mkdir(parents=True, mode=0o700)
    staged = folder / 'BeeperLocal.app'
    run('/usr/bin/ditto', str(app), str(staged))
    if signature(staged) != signed:
        raise NotaryError('NOTARY_COPY_CHANGED')
    archive = folder / 'upload.zip'
    run('/usr/bin/ditto', '-c', '-k', '--keepParent', str(staged), str(archive))
    state = {'schema': 1, 'status': 'prepared', 'archive_sha256': digest(archive), 'signature': signed}
    save(folder, state)
    return state


def submit(folder, profile):
    state = load(folder)
    if state['status'] != 'prepared':
        # An interrupted submission may already exist remotely. Never submit twice.
        raise NotaryError('NOTARY_ALREADY_SUBMITTED_OR_UNKNOWN: use status or recover')
    notary('history', profile)  # Validate the named profile before entering an unknown-outcome state.
    state['status'] = 'submitting'
    save(folder, state)
    result = notary('submit', profile, str(folder / 'upload.zip'), '--no-wait')
    state.update(submission_id=submission_id(result.get('id')), status='submitted')
    save(folder, state)
    return state


def status(folder, profile, recover=None):
    state = load(folder)
    if recover:
        if state['status'] != 'submitting' or state.get('submission_id'):
            raise NotaryError('NOTARY_RECOVERY_NOT_NEEDED')
        identity = submission_id(recover)
    else:
        identity = submission_id(state.get('submission_id'))
    result = notary('info', profile, identity)
    if submission_id(result.get('id')) != identity:
        raise NotaryError('NOTARY_SUBMISSION_MISMATCH')
    value = result.get('status')
    if value not in {'Accepted', 'Invalid', 'Rejected', 'In Progress'}:
        raise NotaryError('NOTARY_UNKNOWN_STATUS')
    if value in {'Accepted', 'Invalid', 'Rejected'}:
        report = notary('log', profile, identity)
        if (report.get('sha256') != state['archive_sha256'] or
                submission_id(report.get('jobId')) != identity or report.get('status') != value):
            raise NotaryError('NOTARY_ARCHIVE_MISMATCH')
        # Retain fixed fields only; raw Apple logs are never copied to app logs.
        state['issue_count'] = len(report.get('issues') or [])
    elif recover:
        raise NotaryError('NOTARY_RECOVERY_PENDING: retry when Apple processing completes')
    state.update(submission_id=identity, status=value)
    save(folder, state)
    return state


def verify_distribution(app):
    signed = signature(app)
    run('/usr/bin/xcrun', 'stapler', 'validate', str(app))
    assessed = run('/usr/sbin/spctl', '--assess', '--type', 'execute', '--verbose=4', str(app))
    if 'source=Notarized Developer ID' not in assessed:
        raise NotaryError('NOTARY_GATEKEEPER_NOT_ACCEPTED')
    return {'notarization': 'accepted', 'ticket': 'valid', 'gatekeeper': 'accepted', **signed}


def staple(folder, profile):
    state = status(folder, profile)
    if state['status'] != 'Accepted':
        raise NotaryError('NOTARY_NOT_ACCEPTED')
    app = folder / 'BeeperLocal.app'
    run('/usr/bin/xcrun', 'stapler', 'staple', str(app))
    result = verify_distribution(app)
    state.update(distribution=result)
    save(folder, state)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare', 'submit', 'status', 'recover', 'staple', 'verify'])
    parser.add_argument('--app', type=Path)
    parser.add_argument('--work', type=Path)
    parser.add_argument('--profile', default=os.environ.get('BEEPERLOCAL_NOTARY_PROFILE', ''))
    parser.add_argument('--submission-id')
    args = parser.parse_args()
    try:
        if args.operation in {'prepare', 'verify'} and not args.app:
            parser.error('--app is required')
        if args.operation != 'verify' and not args.work:
            parser.error('--work is required')
        if args.operation == 'recover' and not args.submission_id:
            parser.error('--submission-id is required')
        if args.operation == 'prepare': result = prepare(args.app.resolve(), args.work.absolute())
        elif args.operation == 'verify': result = verify_distribution(args.app.resolve())
        elif args.operation == 'submit': result = submit(args.work.absolute(), args.profile)
        elif args.operation == 'staple': result = staple(args.work.absolute(), args.profile)
        else: result = status(args.work.absolute(), args.profile, args.submission_id if args.operation == 'recover' else None)
        print(json.dumps(result))
        return 0
    except (NotaryError, macos_signing.SigningError, OSError, ValueError, KeyError, ImportError) as exc:
        print(json.dumps({'error': str(exc) if isinstance(exc, (NotaryError, macos_signing.SigningError)) else 'NOTARY_FAILED'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
