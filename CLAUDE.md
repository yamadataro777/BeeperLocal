# CLAUDE.md — BeeperLocal

LINE・Instagram・Slack（Xは別作業）を1つのMacアプリに統合し、メッセージを端末内の暗号化SQLiteに保存・検索し、ローカルMCPでAIにつなぐ個人開発プロダクト。12/1販売予定（買い切り）。ユーザーとのやり取りは日本語。

## どこに何があるか

- `app/` — 本体ソース。作業は基本ここ。`app/AGENTS.md` の開発ルールも従う。
- `BeeperLocal.app` — ユーザーが普段起動する配置済みアプリ（0.8.3）。`app/` からビルドしたものを置き換える。置換前に `archive/app-backups/` へ退避するのが慣例。
- `app/docs/PROJECT_STATE.md` — 実機検証の source of truth。`NEXT_IMPLEMENTATION.md`・`IMPLEMENTATION_PLAN.md` が現行計画。
- `docs/spec/` — 仕様 v0.1（現状と大きくずれている）。再設計案 v0.2 と販売リスク一覧はClaudeのドキュメント:
  - 設計 v0.2: https://claude.ai/code/artifact/5603a8ed-451a-4fdf-baf9-7f4928ea6351
  - 販売リスク一覧: https://claude.ai/code/artifact/8781c933-8365-463a-8909-3dc78a31fcad
- `workstreams/` — 未統合の並行作業（`x-integration-work` はX単体版、`slack-integration-work` はSlack改善パッチ、`line-recovery-work` は0.8.3の検証）。本体へ取り込むときは差分を確認してから。
- `business/` — 販売サイト（`stripe-site-draft/`、公開中）とStripe申請メモ。
- `archive/` — 触らない。旧アプリ・統合前スナップショット・壊れた空git。

## 構成（app/）

- `beeperlocal/` — Python Core（3.11+、実ビルドは3.13）。`connectors/`（line, instagram, slack, matrix, telegram, `base.py`, `registry.py`）、`storage.py`（AES-256-GCM行暗号化SQLite）、`outbox.py`（送信台帳）、`mcp_server.py`/`mcp_access.py`（認証付きloopback MCP）、`desktop*.py`（GUI用Core。`desktop_router.py` がproviderごとに振り分け）、`cli.py`。
- `desktop/` — Tauri 2 + React 19 + TypeScript + Vite。`src-tauri/src/main.rs` がPyInstaller化したCore（`beeperlocal-core`）を子プロセスで起動し、stdin/stdoutのJSONで通信。要求は `CoreRequest` enumの許可リストのみ（Python側でも検証）。
- `vendor/line-cli/` — line-cli v0.4.0（Go、MIT）の固定ソース＋desktop拡張。Chrome拡張LINE 3.7.2として接続する。
- `instagram-adapter/meta/` — mautrix-meta由来（AGPL-3.0）のGoアダプタ。
- `tests/`（Python unittest）、`desktop/tests/`（Playwright、架空データ）。

## コマンド（app/ で実行）

```bash
.desktop-venv/bin/python -B -m unittest discover -v     # Core全テスト（約330件）
.desktop-venv/bin/python -B -m unittest tests.test_line -v  # 単体ファイル
npm --prefix desktop test                               # 画面テスト（ローカルChrome使用）
npm --prefix desktop run build                          # tsc + vite
bash scripts/build-desktop.sh                           # Core/line/IGをビルドしTauriでapp作成・署名
./run.sh <cmd>                                          # CLI: doctor, sync, search, send, watch, db-status ...
bash -n run.sh scripts/*.sh                             # shell構文確認
```

ビルドには Python 3.13 の `.desktop-venv`、Node 20.19+、Rust、Go 1.26+ が必要（`docs/DESKTOP_APP.md`）。

**注意: `app/.desktop-venv` は壊れている。** venvは移動できない作りで、console スクリプト（`pip`, `pyi-*`, `activate`）のshebangに旧パス `~/Documents/ChatGPT/.../.desktop-venv/bin/python` が焼き込まれている（整理前からの状態）。`run.sh` 経由（`.desktop-venv/bin/python` → Homebrew Python へのsymlink）は動くが、`pip` やビルドの pyinstaller を直接叩くと失敗する。Mac上で作り直すこと:

```bash
cd app && rm -rf .desktop-venv && python3.13 -m venv .desktop-venv \
  && .desktop-venv/bin/python -m pip install -r requirements-desktop.txt
```

## 守ること

- **実送信はユーザーが宛先と本文を明示承認したときだけ、1回だけ。** 送信系の自動再試行は禁止。応答が失われても「未送信」とは限らない。まず履歴で確認する。
- **本文・相手名・ID・トークン・検索語をログ、レポート、ターミナル、チャットに出さない。** 診断は件数・固定コード・bool・HTTP status程度にする。
- 資格情報とDB鍵はmacOS Keychainのみに置く。ファイルや環境変数への退避は禁止。Keychainの迂回・ACL変更・DB/鍵のリセットは、ユーザーの明示指示なしに行わない。
- 平文FTSは追加しない（v0.2でSQLCipher+FTS5へ移る案があるが、ADR承認前）。
- モックや架空データの成功を実機成功として記録しない。PROJECT_STATEには「エージェントが観測した」「ユーザー報告」を分けて書く。
- ブラウザの資格情報の抜き取り、Discordのself-bot、認証回避はしない。
- 既存のLINE/Instagram/Slackの動作を壊さない。通常アプリを置き換える前に、Core全テスト・画面テスト・ビルド・署名検証を通す。

## ユーザーのMacで作業するとき

- 削除はできない（`rm` は不可）。不要物は `_to_delete/` へ移すか、ユーザーに頼む。
- 対話シェルで裸の `set -e` を使わない（ユーザーのTerminalが閉じた前例あり）。必要ならサブシェルで使う。
- パスに全角スペースが混じらないよう注意する（旧フォルダ名「BeeperLocal　検証」で失敗した前例）。
- ユーザーに実行してもらうコマンドは、「実行するコマンド」と「期待される出力」を分けて示す。

## データの保存先（実行時）

- LINE / Matrix / Slack: Keychain service `BeeperLocalPoC.v1`、DB `~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3`
- Instagram: Keychain `BeeperLocalInstagramIntegration.v1`、DB `~/Library/Application Support/BeeperLocalInstagramIntegration/messages-v1.sqlite3`
