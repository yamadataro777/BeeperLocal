#!/bin/bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
if ! node -e 'const [major, minor] = process.versions.node.split(".").map(Number); process.exit((major === 20 && minor >= 19) || (major === 22 && minor >= 12) || major > 22 ? 0 : 1)' >/dev/null 2>&1; then
  echo 'Node.js 20.19+ or 22.12+ is required. Select a supported Node version before building (desktop/.nvmrc: 22).' >&2
  exit 1
fi
BUILD_PYTHON="${BEEPERLOCAL_BUILD_PYTHON:-$PROJECT_ROOT/.release-venv/bin/python}"
if [ ! -x "$BUILD_PYTHON" ]; then
  echo 'Create .release-venv with a macOS 13-compatible Python and install requirements-desktop.txt first. See docs/DESKTOP_APP.md.' >&2
  exit 1
fi
BUILD_MODE=development
BUILD_DISTRIBUTION=0
case "${1:---development}" in
  --development) ;;
  --release) BUILD_MODE=release ;;
  --distribution) BUILD_MODE=release; BUILD_DISTRIBUTION=1 ;;
  *) echo 'Usage: build-desktop.sh [--development|--release|--distribution]' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo 'Usage: build-desktop.sh [--development|--release|--distribution]' >&2
  exit 2
fi
if [ "$BUILD_DISTRIBUTION" = 1 ]; then
  "$BUILD_PYTHON" -B scripts/release_preflight.py
fi
"$BUILD_PYTHON" -B scripts/macos_signing.py preflight --mode "$BUILD_MODE"
PYI_ARGS=(--noconfirm --clean --onefile --target-architecture arm64)
if [ "$BUILD_MODE" = release ]; then
  # Includes the Python runtime and native extensions INSIDE the onefile archive.
  PYI_ARGS+=(--codesign-identity "$BEEPERLOCAL_SIGN_IDENTITY")
fi
export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/desktop/.pyinstaller-cache"
"$BUILD_PYTHON" -B -m PyInstaller "${PYI_ARGS[@]}" \
  --name beeperlocal-core --paths "$PROJECT_ROOT" \
  --collect-submodules uvicorn --collect-submodules mcp.server --collect-data jsonschema_specifications --collect-all chat_xdk \
  --exclude-module telethon \
  --distpath "$PROJECT_ROOT/desktop/core-dist" \
  --workpath "$PROJECT_ROOT/desktop/core-build" \
  --specpath "$PROJECT_ROOT/desktop/core-build" \
  "$PROJECT_ROOT/scripts/desktop_entry.py"
BUILD_TRIPLE="$(rustc --print host-tuple)"
mkdir -p "$PROJECT_ROOT/desktop/src-tauri/binaries"
cp "$PROJECT_ROOT/desktop/core-dist/beeperlocal-core" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-core-$BUILD_TRIPLE"
# Build the pinned desktop extension; no session or user data is packaged.
export GOCACHE="${GOCACHE:-$PROJECT_ROOT/.go-cache}"
export MACOSX_DEPLOYMENT_TARGET=13.0
export CGO_CFLAGS="${CGO_CFLAGS:-} -mmacosx-version-min=13.0"
export CGO_LDFLAGS="${CGO_LDFLAGS:-} -mmacosx-version-min=13.0"
(cd "$PROJECT_ROOT/vendor/line-cli" && go build -trimpath -ldflags '-s -w -X main.version=v0.4.0-beeperlocal.2' \
  -o "$PROJECT_ROOT/desktop/src-tauri/binaries/line-$BUILD_TRIPLE" ./cmd/line)
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/line-$BUILD_TRIPLE"
(cd "$PROJECT_ROOT/instagram-adapter/meta" && go build -trimpath -ldflags '-s -w' \
  -o "$PROJECT_ROOT/bin/beeperlocal-ig" ./cmd/beeperlocal-ig)
cp "$PROJECT_ROOT/bin/beeperlocal-ig" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-ig-$BUILD_TRIPLE"
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-ig-$BUILD_TRIPLE"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/build-instagram-login.py"
cp "$PROJECT_ROOT/bin/beeperlocal-instagram-login" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-instagram-login-$BUILD_TRIPLE"
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-instagram-login-$BUILD_TRIPLE"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/build-slack-login.py"
cp "$PROJECT_ROOT/bin/beeperlocal-slack-login" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-slack-login-$BUILD_TRIPLE"
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-slack-login-$BUILD_TRIPLE"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/build-x-adapter.py"
for X_HELPER in beeperlocal-x beeperlocal-x-login; do
  cp "$PROJECT_ROOT/bin/$X_HELPER" "$PROJECT_ROOT/desktop/src-tauri/binaries/$X_HELPER-$BUILD_TRIPLE"
  chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/$X_HELPER-$BUILD_TRIPLE"
done
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/build-messenger-adapter.py"
for MESSENGER_HELPER in beeperlocal-messenger beeperlocal-messenger-login; do
  cp "$PROJECT_ROOT/bin/$MESSENGER_HELPER" "$PROJECT_ROOT/desktop/src-tauri/binaries/$MESSENGER_HELPER-$BUILD_TRIPLE"
  chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/$MESSENGER_HELPER-$BUILD_TRIPLE"
done
cd "$PROJECT_ROOT/desktop"
# Explicit local staging signature; the final, verified signature is applied below.
# Credentials in the caller's environment must not trigger an implicit upload.
env -u APPLE_ID -u APPLE_PASSWORD -u APPLE_API_KEY -u APPLE_API_ISSUER \
  -u APPLE_API_KEY_PATH APPLE_SIGNING_IDENTITY=- npm run tauri -- build --bundles app
BUILD_APP="$PROJECT_ROOT/desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/macos_signing.py" sign --mode "$BUILD_MODE" --app "$BUILD_APP"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/macos_compatibility.py" "$BUILD_APP"
if [ "$BUILD_DISTRIBUTION" = 1 ]; then
  "$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/release_preflight.py" --app "$BUILD_APP"
fi
