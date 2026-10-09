#!/usr/bin/env python3
"""Extract an official Python package locally; never install into /Library or change system Python."""
import argparse
import hashlib
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess

VERSION = '3.13.12'
PACKAGE_SHA256 = 'b8d2eb5b6eabf583dce703027f6d4ed4b71c9bd1b05ad35d1f0c23f78e9aea76'
PACKAGE_URL = 'https://www.python.org/ftp/python/3.13.12/python-3.13.12-macos11.pkg'


def relocate_framework(version):
    """Keep standard-library dylibs in this extraction, not an installed /Library Python."""
    prefix = '/Library/Frameworks/Python.framework/Versions/3.13/'
    changed = 0
    for path in version.rglob('*'):
        if path.is_symlink() or not path.is_file():
            continue
        with path.open('rb') as source:
            if source.read(4) not in {b'\xcf\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}:
                continue
        if 'arm64' not in subprocess.check_output(['/usr/bin/lipo', '-archs', str(path)], text=True).split():
            continue  # The optional python3.13-intel64 launcher is never used for this build.
        output = subprocess.check_output(['/usr/bin/otool', '-arch', 'arm64', '-l', str(path)], text=True)
        flags = []
        for command in re.split(r'Load command \d+\s*\n', output)[1:]:
            kind = re.search(r'^\s*cmd (\S+)', command, re.M)
            if not kind:
                continue
            field = 'path' if kind[1] == 'LC_RPATH' else 'name'
            match = re.search(r'^\s*' + field + r' (.+) \(offset \d+\)', command, re.M)
            if not match or not match[1].startswith(prefix):
                continue
            old = match[1]
            target = version / old[len(prefix):]
            relative = '@loader_path/' + os.path.relpath(target, path.parent)
            if kind[1] == 'LC_RPATH':
                flags.extend(['-rpath', old, relative])
            elif kind[1] in {'LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB'}:
                flags.extend(['-change', old, relative])
        if flags:
            subprocess.run(['/usr/bin/install_name_tool', *flags, str(path)], check=True, capture_output=True)
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True, capture_output=True)
            changed += 1
    return changed


def prepare(package, root):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('NATIVE_APPLE_SILICON_REQUIRED')
    with package.open('rb') as source:
        if hashlib.file_digest(source, 'sha256').hexdigest() != PACKAGE_SHA256:
            raise ValueError('OFFICIAL_PYTHON_HASH_MISMATCH')
    build = root / '.build-python'
    expanded, framework, venv = build / ('python-' + VERSION + '-pkg'), build / 'Python.framework', root / '.release-venv'
    if any(path.exists() for path in (expanded, framework, venv)):
        raise ValueError('BUILD_RUNTIME_ALREADY_EXISTS')
    build.mkdir(exist_ok=True)
    subprocess.run(['/usr/sbin/pkgutil', '--expand-full', str(package), str(expanded)], check=True)
    shutil.copytree(expanded / 'Python_Framework.pkg/Payload', framework, symlinks=True)
    version = framework / 'Versions/3.13'
    executable, library = version / 'bin/python3.13', version / 'Python'
    # The official bin launcher otherwise forwards into /Library/Frameworks.
    executable.rename(executable.with_name('python3.13-original-launcher'))
    shutil.copy2(version / 'Resources/Python.app/Contents/MacOS/Python', executable)
    subprocess.run(['/usr/bin/install_name_tool', '-change', '/Library/Frameworks/Python.framework/Versions/3.13/Python',
                    str(library), str(executable)], check=True)
    subprocess.run(['/usr/bin/install_name_tool', '-id', str(library), str(library)], check=True)
    for path in (library, executable):
        subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(path)], check=True)
    relocate_framework(version)
    # These local build tools are re-signed for extraction, not distributed.
    subprocess.run([str(executable), '-c', 'import sys; assert sys.version_info[:3] == (3, 13, 12)'], check=True)
    subprocess.run([str(executable), '-m', 'venv', str(venv)], check=True)
    print('LOCAL_RELEASE_PYTHON_READY')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path, help=PACKAGE_URL)
    args = parser.parse_args()
    prepare(args.package.resolve(), Path(__file__).resolve().parents[1])
