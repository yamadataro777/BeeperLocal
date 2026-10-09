"""Build pinned X helpers without opening a session or accessing user data."""
from pathlib import Path
import os
import platform
import subprocess

root = Path(__file__).resolve().parent.parent
env = dict(os.environ)
env.setdefault("GOCACHE", str(root / ".go-cache"))
env["MACOSX_DEPLOYMENT_TARGET"] = "13.0"
for name in ("CGO_CFLAGS", "CGO_LDFLAGS"):
    env[name] = env.get(name, "") + " -mmacosx-version-min=13.0"
(root / "bin").mkdir(exist_ok=True)
subprocess.run(["go", "build", "-mod=readonly", "-trimpath", "-ldflags", "-s -w",
                "-o", str(root / "bin/beeperlocal-x"), "."], cwd=root / "x-adapter/bridge", env=env, check=True)
arch = "arm64" if platform.machine() in {"arm64", "aarch64"} else "x86_64"
subprocess.run(["xcrun", "swiftc", "-swift-version", "5", "-O", "-target", arch + "-apple-macosx13.0",
                "-module-cache-path", str(root / ".swift-cache"), "-framework", "AppKit", "-framework", "WebKit",
                str(root / "x-adapter/native-login/main.swift"), "-o", str(root / "bin/beeperlocal-x-login")], check=True)
