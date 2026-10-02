#!/bin/bash
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
source "$ROOT/scripts/python-select.sh"
if ! PYTHON="$(find_python)"; then
  echo 'Python 3.11以上が必要です。docs/SETUP_JA.mdのPython準備を確認してください。' >&2
  exit 1
fi
if [ -L .venv ]; then
  echo '.venvがシンボリックリンクのため中止しました。既存環境は変更していません。' >&2
  exit 1
fi
if [ ! -d .venv ]; then
  "$PYTHON" -m venv .venv
fi
if [ ! -x .venv/bin/python ]; then
  echo '.venvが不完全です。既存フォルダを退避してから再実行してください。自動削除はしません。' >&2
  exit 1
fi
.venv/bin/python -c 'import sys; assert sys.version_info >= (3,11)'
echo 'プロジェクト内 .venv に依存パッケージを導入します。システムPythonは変更しません。'
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
# Provenance record only; not a hash-verified cross-platform lockfile.
.venv/bin/python -m pip freeze > .venv/installed-requirements.txt
chmod +x run.sh scripts/setup.sh
echo 'Setup完了。次: ./run.sh doctor --check-keychain'
