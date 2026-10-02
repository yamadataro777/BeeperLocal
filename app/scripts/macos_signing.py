#!/usr/bin/env python3
"""Sign and verify the desktop and its helpers; never silently downgrade a release.

Signing identities refer to private keys already installed in macOS Keychain.
No private-key export, password argument, ACL edits or hand-written DR is used.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess
import tempfile

APP_ID = "local.beeperlocal.desktop"
HELPERS = {"beeperlocal-core": APP_ID + ".core", "line": APP_ID + ".line"}
OPTIONAL_HELPERS = {"beeperlocal-ig": APP_ID + ".instagram"}


class SigningError(Exception):
    pass


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, check=False)
    if result.returncode:
        # Native output can contain signing/account information; keep errors fixed.
        raise SigningError("MACOS_SIGNING_COMMAND_FAILED: " + Path(args[0]).name)
    return result.stdout + result.stderr


def identity(mode):
    if mode == "development":
        return "-", None
    certificate = os.environ.get("BEEPERLOCAL_SIGN_IDENTITY", "")
    team = os.environ.get("BEEPERLOCAL_TEAM_ID", "")
    if not re.fullmatch(r"[A-Fa-f0-9]{40}", certificate) or not re.fullmatch(r"[A-Z0-9]{10}", team):
        raise SigningError("DEVELOPER_ID_REQUIRED: set BEEPERLOCAL_SIGN_IDENTITY (SHA-1) and BEEPERLOCAL_TEAM_ID")
    available = run("/usr/bin/security", "find-identity", "-v", "-p", "codesigning")
    matches = re.findall(r'\b([A-Fa-f0-9]{40})\s+"(Developer ID Application: [^"\n]+)"', available)
    if not any(digest.lower() == certificate.lower() and name.endswith(f"({team})")
               for digest, name in matches):
        raise SigningError("DEVELOPER_ID_NOT_AVAILABLE: install the matching certificate and private key in Keychain")
    return certificate, team


def bundle_paths(app):
    app = Path(app)
    if app.is_symlink() or not app.is_dir() or app.suffix != ".app":
        raise SigningError("INVALID_APP_BUNDLE")
    with (app / "Contents/Info.plist").open("rb") as source:
        info = plistlib.load(source)
    if info.get("CFBundleIdentifier") != APP_ID:
        raise SigningError("UNEXPECTED_BUNDLE_IDENTIFIER")
    main = info.get("CFBundleExecutable", "")
    if not main or Path(main).name != main:
        raise SigningError("INVALID_MAIN_EXECUTABLE")
    executables = app / "Contents/MacOS"
    names = {p.name for p in executables.iterdir()}
    if names - {main, *HELPERS, *OPTIONAL_HELPERS}:
        raise SigningError("UNRECOGNIZED_BUNDLED_EXECUTABLE")
    helpers = {**HELPERS, **{name: identifier for name, identifier in OPTIONAL_HELPERS.items() if name in names}}
    paths = [(executables / name, identifier) for name, identifier in helpers.items()]
    for path in [app / "Contents/MacOS" / main, *(p for p, _ in paths)]:
        if path.is_symlink() or not path.is_file():
            raise SigningError("MISSING_OR_LINKED_EXECUTABLE")
    return app, paths


def inspect_signature(path, mode, team, expected_identifier=None):
    run("/usr/bin/codesign", "--verify", "--strict", str(path))
    details = run("/usr/bin/codesign", "--display", "--verbose=4", "-r-", str(path))
    if expected_identifier and f"Identifier={expected_identifier}\n" not in details:
        raise SigningError("SIGNATURE_IDENTIFIER_MISMATCH")
    if mode == "release":
        run("/usr/bin/codesign", "--verify", "--strict", "-R", "=anchor apple generic", str(path))
        if (f"TeamIdentifier={team}\n" not in details or
                "Authority=Developer ID Application:" not in details or
                "(runtime)" not in details or "Timestamp=" not in details):
            raise SigningError("RELEASE_SIGNATURE_INCOMPLETE")
        if expected_identifier and "designated => cdhash" in details:
            raise SigningError("UNSTABLE_RELEASE_REQUIREMENT")
    elif "Signature=adhoc" not in details:
        raise SigningError("EXPECTED_DEVELOPMENT_SIGNATURE")
    return details


def verify_embedded_runtime(core, mode, team):
    # A onefile helper contains Mach-O libraries inside its archive. Signing just
    # the outer executable cannot fix their Team ID or library validation.
    from PyInstaller.archive.readers import CArchiveReader
    archive = CArchiveReader(str(core))
    count = 0
    with tempfile.TemporaryDirectory(prefix="beeperlocal-signature-check-") as directory:
        for name, entry in archive.toc.items():
            if entry[-1] != "b":
                continue
            payload = archive.extract(name)
            if payload[:4] not in {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}:
                continue
            path = Path(directory) / f"runtime-{count}"
            path.write_bytes(payload)
            inspect_signature(path, mode, team)
            count += 1
    if not count:
        raise SigningError("EMBEDDED_RUNTIME_NOT_FOUND")
    return count


def verify(app, mode, team, previous=None):
    app, helpers = bundle_paths(app)
    run("/usr/bin/codesign", "--verify", "--deep", "--strict", str(app))
    for path, identifier in helpers + [(app, APP_ID)]:
        inspect_signature(path, mode, team, identifier)
    count = verify_embedded_runtime(helpers[0][0], mode, team)
    compatibility = "not_checked"
    if previous:
        old_app, old_helpers = bundle_paths(previous)
        current = {identifier: path for path, identifier in helpers + [(app, APP_ID)]}
        for old, identifier in old_helpers + [(old_app, APP_ID)]:
            if identifier not in current:
                raise SigningError("PREVIOUS_HELPER_MISSING")
            new = current[identifier]
            old_details = inspect_signature(old, "release", team, identifier)
            new_details = inspect_signature(new, "release", team, identifier)
            for source, target in [(old_details, new), (new_details, old)]:
                requirement = re.search(r"(?:# )?designated => (.+)", source)
                if not requirement:
                    raise SigningError("MISSING_DESIGNATED_REQUIREMENT")
                run("/usr/bin/codesign", "--verify", "--strict", "-R", "=" + requirement.group(1), str(target))
        compatibility = "mutual_requirements_verified"
    return {"mode": mode, "executables_verified": 1 + len(helpers), "embedded_binaries_verified": count,
            "update_compatibility": compatibility, "notarization": "not_checked"}


def sign(app, mode, certificate, team, previous=None):
    app, helpers = bundle_paths(app)
    flags = ["--options", "runtime", "--timestamp"] if mode == "release" else ["--timestamp=none"]
    for path, identifier in helpers + [(app, APP_ID)]:
        # Sign from inside out. --deep is for verification only.
        run("/usr/bin/codesign", "--force", "--sign", certificate,
            "--identifier", identifier, *flags, str(path))
    return verify(app, mode, team, previous)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["preflight", "sign", "verify"])
    parser.add_argument("--mode", choices=["development", "release"], required=True)
    parser.add_argument("--app", type=Path)
    parser.add_argument("--previous-app", type=Path)
    args = parser.parse_args()
    try:
        certificate, team = identity(args.mode)
        if args.operation == "preflight":
            result = {"mode": args.mode, "identity_available": True}
        else:
            if not args.app or (args.previous_app and args.mode != "release"):
                raise SigningError("APP_OR_RELEASE_MODE_REQUIRED")
            result = (sign(args.app, args.mode, certificate, team, args.previous_app)
                      if args.operation == "sign" else verify(args.app, args.mode, team, args.previous_app))
        print(json.dumps(result))
    except (SigningError, OSError, ValueError, ImportError) as exc:
        print(str(exc) if isinstance(exc, SigningError) else "MACOS_SIGNING_FAILED")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
