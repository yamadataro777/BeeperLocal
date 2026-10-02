#!/bin/bash
set -euo pipefail
umask 077
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
unset PYTHONPATH PYTHONHOME
export PYTHONNOUSERSITE=1
export PYTHONDONTWRITEBYTECODE=1
if [ -L .venv ]; then
  echo '.venvがシンボリックリンクのため中止しました。' >&2
  exit 1
fi
if [ -x .venv/bin/python ]; then
  PYTHON="$ROOT/.venv/bin/python"
else
  source "$ROOT/scripts/python-select.sh"
  if ! PYTHON="$(find_python)"; then
    echo 'Python 3.11以上が必要です。docs/SETUP_JA.mdを確認してください。' >&2
    exit 1
  fi
fi
exec "$PYTHON" -B -m beeperlocal "$@"
