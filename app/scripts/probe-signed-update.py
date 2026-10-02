#!/usr/bin/env python3
"""Two different signed binaries must share only their own disposable Keychain item."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile
from uuid import uuid4

from macos_signing import identity, inspect_signature, run, SigningError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", required=True)
    parser.parse_args()
    certificate, team = identity("release")
    with tempfile.TemporaryDirectory(prefix="beeperlocal-signed-update-") as folder:
        binaries = [Path(folder) / "before", Path(folder) / "after"]
        hashes, requirements = [], []
        for revision, path in enumerate(binaries, 1):
            run("/usr/bin/xcrun", "clang", "-Wno-deprecated-declarations", f"-DPROBE_REVISION={revision}",
                str(Path(__file__).with_name("keychain-update-probe.c")),
                "-framework", "Security", "-framework", "CoreFoundation", "-o", str(path))
            run("/usr/bin/codesign", "--force", "--sign", certificate, "--identifier",
                "local.beeperlocal.keychain-update-probe", "--options", "runtime", "--timestamp", str(path))
            details = inspect_signature(path, "release", team, "local.beeperlocal.keychain-update-probe")
            hashes.append(re.search(r"^CDHash=(.+)$", details, re.M).group(1))
            requirements.append(re.search(r"(?:# )?designated => (.+)", details).group(1))
        if hashes[0] == hashes[1]:
            raise SigningError("PROBE_BINARIES_MUST_DIFFER")
        for requirement, path in zip(requirements, reversed(binaries)):
            run("/usr/bin/codesign", "--verify", "--strict", "-R", "=" + requirement, str(path))
        service = "local.beeperlocal.signed-update-test." + uuid4().hex
        results = []
        try:
            for binary, operation in [(binaries[0], "create"), (binaries[0], "read"),
                                      (binaries[1], "read"), (binaries[1], "update"),
                                      (binaries[1], "read"), (binaries[0], "read")]:
                result = subprocess.run([str(binary), service, operation], capture_output=True, text=True, timeout=15)
                if result.returncode:
                    raise SigningError("SIGNED_UPDATE_KEYCHAIN_PROBE_FAILED")
                results.append(json.loads(result.stdout))
        finally:
            run(str(binaries[0]), service, "delete")
        # A non-interactive read now fails because the fixture item was removed.
        removed = subprocess.run([str(binaries[1]), service, "read"], capture_output=True, text=True, timeout=15)
        if json.loads(removed.stdout).get("status") != -25300:
            raise SigningError("PROBE_CLEANUP_FAILED")
        return {"different_code_hashes": True, "mutual_requirements_verified": True,
                "keychain_operations_without_prompts": len(results), "cleanup_verified": True,
                "production_items_accessed": False}


if __name__ == "__main__":
    try:
        print(json.dumps(main()))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc) if isinstance(exc, SigningError) else "SIGNED_UPDATE_PROBE_FAILED"}))
        raise SystemExit(1)
