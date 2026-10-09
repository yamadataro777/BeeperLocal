#!/usr/bin/env python3
"""Package a signed candidate with corresponding source, without touching the installed app."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tarfile
import tempfile
from macos_compatibility import verify as verify_compatibility
from macos_notarize import NotaryError, verify_distribution
from macos_signing import SigningError
from release_preflight import verify as verify_release_settings


SOURCE_TREES = (
    "beeperlocal", "scripts", "tests", "desktop/src", "desktop/tests",
    "desktop/src-tauri/src", "desktop/src-tauri/icons", "desktop/src-tauri/resources",
    "desktop/src-tauri/capabilities", "vendor/line-cli", "instagram-adapter/meta", "instagram-adapter/native-login",
    "messenger-adapter", "x-adapter", "slack-adapter",
)
SKIP = {".git", ".idea", "__pycache__", "node_modules", "target", "dist", "build", "bin", "_to_delete"}
SUFFIXES = {
    ".py", ".tsx", ".ts", ".js", ".mjs", ".cjs", ".css", ".html", ".go", ".rs",
    ".toml", ".lock", ".json", ".c", ".h", ".m", ".swift", ".mod", ".sum", ".md",
    ".txt", ".sh", ".command", ".yaml", ".yml", ".sql", ".thrift", ".fbs", ".proto",
    ".bin", ".png", ".ico", ".icns", ".ogg", ".xml", ".exceptions",
}
SOURCE_FILES = (
    "README.md", "AGENTS.md", "run.sh", "requirements.txt", "requirements-desktop.txt", "requirements-desktop-constraints.txt",
    "slack-send-app-manifest.json", "desktop/.nvmrc", "desktop/index.html",
    "desktop/package.json", "desktop/package-lock.json", "desktop/tsconfig.json",
    "desktop/vite.config.ts", "desktop/playwright.config.ts", "desktop/src-tauri/build.rs",
    "desktop/src-tauri/Cargo.toml", "desktop/src-tauri/Cargo.lock",
    "desktop/src-tauri/tauri.conf.json", "desktop/src-tauri/update-channel.json",
    "docs/DESKTOP_APP.md", "docs/INBOX_0_9.md", "docs/SECURITY.md",
    "docs/MCP_0_9_1.md", "docs/BEEPER_UI_UX_REFERENCE.md", "docs/MCP_REQUIREMENTS.md", "docs/ADR_LOCAL_MCP.md",
    "docs/FRESH_MAC_AUDIT.md",
    "docs/USER_FEEDBACK_0_9_3.md",
    "docs/RELEASE_DISTRIBUTION.md", "docs/BETA_INSTALL.md",
    "docs/ADR_PHASE1_PERSISTENCE.md", "docs/ADR_MESSENGER_PERSISTENCE.md",
    "docs/MESSENGER_INTEGRATION.md", "docs/X_INTEGRATION.md", "docs/SLACK_IMPLEMENTATION.md",
)


def sources(root: Path) -> list[Path]:
    selected = {root / name for name in SOURCE_FILES}
    for tree in SOURCE_TREES:
        for directory, folders, files in os.walk(root / tree, followlinks=False):
            folders[:] = [name for name in folders if name not in SKIP and not name.startswith(".")]
            for name in files:
                path = Path(directory) / name
                if not name.startswith(".") and (path.suffix in SUFFIXES or name in {"LICENSE", "Dockerfile"}):
                    selected.add(path)
    for path in selected:
        if path.is_symlink() or not path.is_file():
            raise ValueError("SOURCE_MISSING_OR_LINKED")
    return sorted(selected)


def run(*command: str) -> None:
    result = subprocess.run(command, capture_output=True)
    if result.returncode:
        raise RuntimeError("PACKAGE_COMMAND_FAILED: " + Path(command[0]).name)


def package(app: Path, output: Path, version: str, *, candidate: bool = False) -> dict:
    root = Path(__file__).resolve().parents[1]
    with (app / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if (app.is_symlink() or info.get("CFBundleIdentifier") != "local.beeperlocal.desktop"
            or info.get("CFBundleShortVersionString") != version):
        raise ValueError("UNEXPECTED_APP")
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
    if not verify_compatibility(app)['passed']:
        raise ValueError('MACOS_COMPATIBILITY_FAILED')
    release_checks = None
    if not candidate:
        release_checks = {'apple': verify_distribution(app), 'slack': verify_release_settings(app)}
    suffix = 'internal-candidate' if candidate else 'beta'
    folder = output / f"BeeperLocal-{version}-{suffix}"
    archive = output / f"BeeperLocal-{version}-AppleSilicon-{suffix}.zip"
    checksum = archive.with_suffix(".sha256")
    if folder.exists() or archive.exists() or checksum.exists():
        raise ValueError("PACKAGE_ALREADY_EXISTS")
    paths = sources(root)
    # All input files are selected before any output is created.
    guide = (root / 'docs' / ('BETA_GUIDE.md' if candidate else 'BETA_INSTALL.md')).read_bytes()
    scope = (root / "docs/INBOX_0_9.md").read_bytes()
    audit = (root / "docs/BETA_READINESS.md").read_bytes()
    verification = (root / f"docs/desktop-{version}-verification.json").read_bytes()
    folder.mkdir(parents=True)
    run("/usr/bin/ditto", str(app), str(folder / "BeeperLocal.app"))
    (folder / "はじめに.txt").write_bytes(guide)
    (folder / "INBOX_0_9.md").write_bytes(scope)
    for name in ("MCP_0_9_1.md", "BEEPER_UI_UX_REFERENCE.md", "FRESH_MAC_AUDIT.md", "USER_FEEDBACK_0_9_3.md"):
        (folder / name).write_bytes((root / "docs" / name).read_bytes())
    (folder / "改善点と残る確認事項.md").write_bytes(audit)
    (folder / f"desktop-{version}-verification.json").write_bytes(verification)
    if release_checks:
        (folder / 'distribution-checks.json').write_text(json.dumps(release_checks, indent=2) + '\n')
    source_archive = folder / "対応ソース.tar.gz"
    with tarfile.open(source_archive, "w:gz", format=tarfile.PAX_FORMAT) as bundle:
        for path in paths:
            info = bundle.gettarinfo(str(path), arcname="app/" + path.relative_to(root).as_posix())
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            with path.open("rb") as contents:
                bundle.addfile(info, contents)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(folder / "BeeperLocal.app"))
    if not candidate:
        verify_distribution(folder / 'BeeperLocal.app')
    # Publish the final ZIP name only after checking the actual extracted artifact.
    with tempfile.TemporaryDirectory(prefix='.beeperlocal-package-', dir=output) as temporary:
        pending = Path(temporary) / 'archive.zip'
        run('/usr/bin/ditto', '-c', '-k', '--keepParent', str(folder), str(pending))
        if not candidate:
            unpacked = Path(temporary) / 'extracted'
            run('/usr/bin/ditto', '-x', '-k', str(pending), str(unpacked))
            extracted = unpacked / folder.name / 'BeeperLocal.app'
            verify_distribution(extracted)
            verify_release_settings(extracted)
        with pending.open('rb') as contents:
            digest = hashlib.file_digest(contents, 'sha256').hexdigest()
        pending.replace(archive)
    checksum.write_text(f"{digest}  {archive.name}\n")
    return {"file": archive.name, "size_bytes": archive.stat().st_size, "sha256": digest,
            "source_files": len(paths), "source_archive_bytes": source_archive.stat().st_size,
            "audience": 'internal_candidate' if candidate else 'friends', 'distribution_checks': release_checks}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument('--candidate', action='store_true', help='Explicitly produce an internal-only candidate without distribution approval')
    args = parser.parse_args()
    try:
        print(json.dumps(package(args.app.resolve(), args.output.resolve(), args.version, candidate=args.candidate), ensure_ascii=False))
    except (NotaryError, SigningError, RuntimeError, ValueError, OSError):
        print('{"ready":false,"error":"PACKAGE_DISTRIBUTION_CHECK_FAILED"}')
        raise SystemExit(1)
