#!/bin/bash
set -uo pipefail
umask 077
finish() {
  local result="$1"
  if [ -t 0 ]; then read -r -p 'Enterで閉じる' || true; fi
  exit "$result"
}
if [ "$#" -gt 1 ] || { [ "$#" -eq 1 ] && [ "$1" != '--check' ]; }; then
  echo 'このファイルはBeeperLocalの接続設定から開いてください。' >&2
  finish 2
fi
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)" || finish 1
CORE="$SCRIPT_DIR/../../MacOS/beeperlocal-core"
if [ ! -x "$CORE" ]; then
  echo 'アプリの接続機能が見つかりません。BeeperLocal.app全体をコピーし直してください。' >&2
  finish 1
fi
if ! "$CORE" --verify-slack-login >/dev/null 2>&1; then
  echo '接続機能を起動できません。修正版のBeeperLocal.appが必要です。' >&2
  finish 1
fi
if [ "${1:-}" = '--check' ]; then
  echo 'Slack接続機能: 準備OK（ログイン・通信は行っていません）'
  exit 0
fi
echo 'Slackへ本人ログインします。BeeperLocalでの受信を停止してから進んでください。'
"$CORE" --slack-login
finish "$?"
