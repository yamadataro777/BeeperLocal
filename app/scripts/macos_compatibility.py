#!/usr/bin/env python3
"""Fail packaging when a bundled Mach-O requires a newer OS or a developer library."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

MAGIC = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}


def version(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d+\.\d+(?:\.\d+)?', value):
        raise ValueError('INVALID_MINIMUM_OS')
    return tuple(int(v) for v in value.split('.')) + (0,) * (3 - len(value.split('.')))


def load_commands(output):
    minimum, libraries, rpaths = [], [], []
    for command in re.split(r'Load command \d+\s*\n', output)[1:]:
        kind = re.search(r'^\s*cmd (\S+)', command, re.M)
        if not kind:
            continue
        kind = kind[1]
        if kind in {'LC_BUILD_VERSION', 'LC_VERSION_MIN_MACOSX'}:
            key = 'minos' if kind == 'LC_BUILD_VERSION' else 'version'
            match = re.search(r'^\s*' + key + r' (\S+)', command, re.M)
            if match:
                minimum.append(match[1])
        if kind in {'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB', 'LC_LAZY_LOAD_DYLIB'}:
            match = re.search(r'^\s*name (.+) \(offset \d+\)', command, re.M)
            if match:
                libraries.append(match[1])
        if kind == 'LC_RPATH':
            match = re.search(r'^\s*path (.+) \(offset \d+\)', command, re.M)
            if match:
                rpaths.append(match[1])
    if len(minimum) != 1:
        raise ValueError('MISSING_OR_AMBIGUOUS_MINIMUM_OS')
    version(minimum[0])
    return minimum[0], libraries, rpaths


def portable_reference(value, *, rpath=False):
    return (rpath and value in {'@loader_path', '@executable_path'}) or value.startswith(
        ('/usr/lib/', '/System/Library/', '@rpath/', '@loader_path/', '@executable_path/'))


def inspect_binary(path, name, target):
    arch = subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split()
    if 'arm64' not in arch:
        return {'binary': name, 'issues': ['ARM64_MISSING']}
    output = subprocess.check_output(['/usr/bin/otool', '-arch', 'arm64', '-l', str(path)], text=True)
    minimum, libraries, rpaths = load_commands(output)
    issues = []
    if version(minimum) > version(target):
        issues.append('MINIMUM_OS_EXCEEDS_BUNDLE')
    if (any(not portable_reference(v) for v in libraries)
            or any(not portable_reference(v, rpath=True) for v in rpaths)):
        issues.append('EXTERNAL_LIBRARY_OR_RPATH')
    return {'binary': name, 'minimumOS': minimum, 'architectures': arch, 'issues': issues}


def verify(app):
    from PyInstaller.archive.readers import CArchiveReader
    app = Path(app).resolve()
    with (app / 'Contents/Info.plist').open('rb') as source:
        info = plistlib.load(source)
    target = info.get('LSMinimumSystemVersion')
    version(target)
    rows = []
    for path in sorted((app / 'Contents/MacOS').iterdir()):
        rows.append(inspect_binary(path, path.name, target))
    executable_count = len(rows)
    archive = CArchiveReader(str(app / 'Contents/MacOS/beeperlocal-core'))
    # The Python framework and extensions are compressed inside the onefile Core.
    with tempfile.TemporaryDirectory(prefix='beeperlocal-compatibility-') as folder:
        for name, entry in archive.toc.items():
            if entry[-1] != 'b':
                continue
            payload = archive.extract(name)
            if payload[:4] not in MAGIC:
                continue
            path = Path(folder) / 'native'
            path.write_bytes(payload)
            rows.append(inspect_binary(path, 'core/' + name, target))
    if len(rows) == executable_count:
        raise ValueError('EMBEDDED_RUNTIME_NOT_FOUND')
    return {'passed': not any(row['issues'] for row in rows), 'minimumOS': target,
            'executables': executable_count, 'embeddedBinaries': len(rows) - executable_count, 'binaries': rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('app', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = verify(args.app)
    if args.report:
        args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'binaries'}))
    for row in result['binaries']:
        if row['issues']:
            print(json.dumps(row))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
