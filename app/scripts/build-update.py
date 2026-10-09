#!/usr/bin/env python3
"""Package the FINAL Apple-signed app. Ed25519 seed lives only in native Keychain.

No secret CLI arguments, key files, or environment signing keys are accepted.
The public update channel must be compiled into the app before publication.
"""
import argparse
import base64
from hashlib import blake2b
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import sys
import tarfile
import time
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from beeperlocal.native_keychain import NativeKeychain

SERVICE = 'local.beeperlocal.update-signing.v1'
ACCOUNT = 'ed25519'
CHANNEL = ROOT / 'desktop' / 'src-tauri' / 'update-channel.json'

def encode(value): return base64.b64encode(value).decode('ascii')

def public_key(seed, key_id):
    raw = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
    return 'untrusted comment: BeeperLocal update signing public key\n' + encode(b'Ed' + key_id + raw) + '\n'

def sign_digest(digest, seed, key_id, version, filename, timestamp):
    if len(digest) != 64 or len(seed) != 32 or len(key_id) != 8 or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+(?:-[a-zA-Z0-9.-]+)?', version) or not re.fullmatch(r'[a-zA-Z0-9._-]+', filename):
        raise ValueError('UPDATE_SIGN_INPUT_INVALID')
    key = Ed25519PrivateKey.from_private_bytes(seed)
    signature = key.sign(digest)
    comment = f'timestamp:{timestamp}\tfile:{filename}\tversion:{version}'
    return ('untrusted comment: BeeperLocal update signature\n' + encode(b'ED' + key_id + signature) + '\n'
            + 'trusted comment: ' + comment + '\n' + encode(key.sign(signature + comment.encode())) + '\n')

def read_key(keychain):
    value = keychain.get_password(SERVICE, ACCOUNT)
    if value is None: raise ValueError('UPDATE_SIGN_KEY_MISSING')
    data = json.loads(value)
    seed, key_id = base64.b64decode(data['seed'], validate=True), base64.b64decode(data['id'], validate=True)
    if len(seed) != 32 or len(key_id) != 8: raise ValueError('UPDATE_SIGN_KEY_INVALID')
    return seed, key_id

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init-key', 'package'])
    parser.add_argument('--app', type=Path)
    parser.add_argument('--output', type=Path, default=ROOT / 'desktop' / 'update-dist')
    parser.add_argument('--url', help='Public HTTPS URL of the .app.tar.gz')
    args = parser.parse_args()
    keychain = NativeKeychain()
    config = json.loads(CHANNEL.read_text())
    if args.action == 'init-key':
        if keychain.get_password(SERVICE, ACCOUNT) is None:
            seed, key_id = os.urandom(32), os.urandom(8)
            keychain.set_password(SERVICE, ACCOUNT, json.dumps({'seed':encode(seed), 'id':encode(key_id)}))
        seed, key_id = read_key(keychain)
        configured = encode(public_key(seed, key_id).encode())
        if config['publicKey'] and config['publicKey'] != configured: raise ValueError('UPDATE_PUBLIC_KEY_MISMATCH')
        config['publicKey'] = configured
        CHANNEL.write_text(json.dumps(config, indent=2) + '\n')
        print('UPDATE_SIGN_KEY_READY')
        return
    seed, key_id = read_key(keychain)
    if config['publicKey'] != encode(public_key(seed, key_id).encode()): raise ValueError('UPDATE_PUBLIC_KEY_MISMATCH')
    for raw in (config['endpoint'], args.url):
        parsed = urlsplit(raw or '')
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
            raise ValueError('UPDATE_URL_INVALID')
    app = args.app.resolve(strict=True)
    if app.suffix != '.app' or args.app.is_symlink(): raise ValueError('UPDATE_APP_INVALID')
    if json.loads((app/'Contents'/'Resources'/'update-channel.json').read_text()) != config:
        raise ValueError('UPDATE_APP_CONFIG_MISMATCH')
    for command in (['/usr/bin/codesign', '--verify', '--deep', '--strict', str(app)],
                    ['/usr/bin/codesign', '--verify', '-R=anchor apple generic and certificate leaf[field.1.2.840.113635.100.6.1.13] exists', str(app)]):
        if subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
            raise ValueError('UPDATE_APP_SIGNATURE_INVALID')
    version = plistlib.loads((app/'Contents'/'Info.plist').read_bytes())['CFBundleShortVersionString']
    args.output.mkdir(parents=True, exist_ok=True)
    filename = f'BeeperLocal-{version}-darwin-aarch64.app.tar.gz'
    target = args.output / filename
    if target.exists(): raise ValueError('UPDATE_OUTPUT_EXISTS')
    # Built-in Tauri packaging precedes final Developer ID signing; package here instead.
    with tarfile.open(target, 'x:gz', dereference=False) as archive:
        archive.add(app, arcname='BeeperLocal.app')
    digest = blake2b(digest_size=64)
    with target.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b''): digest.update(chunk)
    signature = sign_digest(digest.digest(), seed, key_id, version, filename, int(time.time()))
    target.with_suffix(target.suffix + '.sig').write_text(encode(signature.encode()))
    manifest = {'version':version, 'platforms':{'darwin-aarch64':{'url':args.url, 'signature':encode(signature.encode())}}}
    (args.output/'latest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print('UPDATE_PACKAGE_SIGNED')

if __name__ == '__main__':
    try: main()
    except Exception as exc:
        code = str(exc) if isinstance(exc, ValueError) and re.fullmatch(r'UPDATE_[A-Z_]+', str(exc)) else 'UPDATE_PACKAGE_FAILED'
        print(code, file=sys.stderr)
        sys.exit(1)
