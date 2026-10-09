"""Build the dedicated, ephemeral Instagram official-site login window."""
from pathlib import Path
import platform
import subprocess

root = Path(__file__).resolve().parent.parent
(root / 'bin').mkdir(exist_ok=True)
arch = 'arm64' if platform.machine() in {'arm64', 'aarch64'} else 'x86_64'
subprocess.run(['xcrun', 'swiftc', '-swift-version', '5', '-O', '-target', arch + '-apple-macosx13.0',
    '-module-cache-path', str(root / '.swift-cache'), '-framework', 'AppKit', '-framework', 'WebKit',
    str(root / 'instagram-adapter/native-login/main.swift'), '-o', str(root / 'bin/beeperlocal-instagram-login')], check=True)
subprocess.run([str(root / 'bin/beeperlocal-instagram-login'), '--self-test'], check=True)
