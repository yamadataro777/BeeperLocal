#!/bin/bash
set -euo pipefail
umask 077
PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_ROOT"
BUILD_PYTHON="$PROJECT_ROOT/.desktop-venv/bin/python"
if [ ! -x "$BUILD_PYTHON" ]; then
  echo 'Create .desktop-venv and install desktop build dependencies first.' >&2
  exit 1
fi
BUILD_MODE=development
case "${1:---development}" in
  --development) ;;
  --release) BUILD_MODE=release ;;
  *) echo 'Usage: build-desktop.sh [--development|--release]' >&2; exit 2 ;;
esac
if [ "$#" -gt 1 ]; then
  echo 'Usage: build-desktop.sh [--development|--release]' >&2
  exit 2
fi
"$BUILD_PYTHON" -B scripts/macos_signing.py preflight --mode "$BUILD_MODE"
PYI_ARGS=(--noconfirm --clean --onefile)
if [ "$BUILD_MODE" = release ]; then
  # Includes the Python runtime and native extensions INSIDE the onefile archive.
  PYI_ARGS+=(--codesign-identity "$BEEPERLOCAL_SIGN_IDENTITY")
fi
export PYINSTALLER_CONFIG_DIR="$PROJECT_ROOT/desktop/.pyinstaller-cache"
"$BUILD_PYTHON" -B -m PyInstaller "${PYI_ARGS[@]}" \
  --name beeperlocal-core --paths "$PROJECT_ROOT" \
  --collect-submodules uvicorn --collect-submodules mcp.server --collect-data jsonschema_specifications \
  --distpath "$PROJECT_ROOT/desktop/core-dist" \
  --workpath "$PROJECT_ROOT/desktop/core-build" \
  --specpath "$PROJECT_ROOT/desktop/core-build" \
  "$PROJECT_ROOT/scripts/desktop_entry.py"
BUILD_TRIPLE="$(rustc --print host-tuple)"
mkdir -p "$PROJECT_ROOT/desktop/src-tauri/binaries"
cp "$PROJECT_ROOT/desktop/core-dist/beeperlocal-core" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-core-$BUILD_TRIPLE"
# Build the pinned desktop extension; no session or user data is packaged.
export GOCACHE="${GOCACHE:-$PROJECT_ROOT/.go-cache}"
(cd "$PROJECT_ROOT/vendor/line-cli" && go build -trimpath -ldflags '-s -w -X main.version=v0.4.0-beeperlocal.1' \
  -o "$PROJECT_ROOT/desktop/src-tauri/binaries/line-$BUILD_TRIPLE" ./cmd/line)
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/line-$BUILD_TRIPLE"
(cd "$PROJECT_ROOT/instagram-adapter/meta" && go build -trimpath -ldflags '-s -w' \
  -o "$PROJECT_ROOT/bin/beeperlocal-ig" ./cmd/beeperlocal-ig)
cp "$PROJECT_ROOT/bin/beeperlocal-ig" "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-ig-$BUILD_TRIPLE"
chmod u+w "$PROJECT_ROOT/desktop/src-tauri/binaries/beeperlocal-ig-$BUILD_TRIPLE"
cd "$PROJECT_ROOT/desktop"
# Explicit local staging signature; the final, verified signature is applied below.
# Credentials in the caller's environment must not trigger an implicit upload.
env -u APPLE_ID -u APPLE_PASSWORD -u APPLE_API_KEY -u APPLE_API_ISSUER \
  -u APPLE_API_KEY_PATH APPLE_SIGNING_IDENTITY=- npm run tauri -- build --bundles app
BUILD_APP="$PROJECT_ROOT/desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app"
"$BUILD_PYTHON" -B "$PROJECT_ROOT/scripts/macos_signing.py" sign --mode "$BUILD_MODE" --app "$BUILD_APP"
