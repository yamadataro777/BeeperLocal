# BeeperLocal — フォルダ案内

2026-10-01 に整理。ファイルは削除せず移動のみ（対応表は末尾）。

| 場所 | 中身 |
| --- | --- |
| `BeeperLocal.app` | 普段起動するアプリ（Desktop 0.8.3、Developer ID署名済み） |
| `app/` | 本体ソース（旧 `BeeperLocal_PoC_v0.4_Phase1`）。Python Core + Tauri/React + 同梱 line-cli / Instagram adapter |
| `app/docs/PROJECT_STATE.md` | 実機検証の記録（source of truth） |
| `docs/spec/` | 設計仕様 v0.1 と Codex 実装指示 |
| `docs/handoff/` | ChatGPT からの引き継ぎメモ |
| `workstreams/` | 本体に未統合・並行中の作業（X、Slack改善、LINE復旧、Instagram統合の作業コピー） |
| `business/` | 販売サイト草案（Stripe）、申請文案、宣伝用スクリプト |
| `tools/` | 補助スクリプト（Instagram接続.command） |
| `archive/` | 旧アプリのバックアップ、統合前スナップショット、使い終わった適用スクリプト、壊れた空git |

設計 v0.2 と販売リスク一覧は Claude のドキュメントとして作成済み。

- 設計 v0.2: https://claude.ai/code/artifact/5603a8ed-451a-4fdf-baf9-7f4928ea6351
- 販売リスク一覧: https://claude.ai/code/artifact/8781c933-8365-463a-8909-3dc78a31fcad

AIエージェント向けの作業ルールは `CLAUDE.md`。

## 移動の対応表

| 旧 | 新 |
| --- | --- |
| `BeeperLocal　検証/BeeperLocal_PoC_v0.4_Phase1` | `app` |
| `BeeperLocal　検証/BeeperLocal.app` | `BeeperLocal.app` |
| `BeeperLocal　検証/{x,slack}-integration-work`, `line-recovery-work`, `instagram-integration`, `instagram-main-merge` | `workstreams/` |
| `BeeperLocal　検証/stripe-site-draft`, `stripe-application-draft.txt`, `beeperlocal-campaign` | `business/` |
| `BeeperLocal　検証/Instagram接続.command` | `tools/`（参照先を `../app` に修正済み） |
| `BeeperLocal　検証/app-backups`, `before-line-*`, `apply_line_*.py`, `*baseline*.json` | `archive/` |
| `BeeperLocal　検証/`（残った `.git`） | `archive/old-verification-root` |
| `BeeperLocal_Design_Spec_v0.1.md`, `CODEX_MVP_IMPLEMENTATION_INSTRUCTIONS.md` | `docs/spec/` |
| `GPT_history/*`, `X_GPT_PROMPT.txt` | `docs/handoff/` |

## 注意

- `archive/old-verification-root/.git` は途中で止まった `git add` の残骸（コミット0件、約1.5GB、`index.lock` 残存）。不要なら削除してよい。
- `workstreams/instagram-integration` と `workstreams/line-recovery-work/release-0.8.3` 内のシンボリックリンクは旧 `~/Documents/ChatGPT/...` を指しており、整理前から切れている。
- 容量の大半はビルドキャッシュ（`app/desktop` 2.4GB、`app/.go-cache` 1GB、各 workstream の build/venv）。
