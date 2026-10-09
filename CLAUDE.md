# BeeperLocal 作業案内

[AGENT.md](AGENT.md) の開発方針に従う。日本語で対応し、主担当だけで作業する。資料を先に更新し、TDDとKISSで現行仕様を直接実装する。開発中の旧版互換・データ移行は維持しない。

## 現在地（2026-10-03）

LINE・Instagram・Slack・X・Messengerを統合したmacOSアプリ。暗号化SQLiteに保存・検索し、権限付きローカルMCPを提供する。通常配置と試用ZIPは公証済み0.9.5。SlackはPKCE・12 user scopes・専用URL `beeperlocal://oauth/slack`・外部ワークスペースへの配布を設定済み。新しい本人認証の完了、別Macで5サービスすべての実ログイン・送受信は未確認。

本体ソースの今回の整理は [DEVELOPMENT_REVIEW_20261003](app/docs/DEVELOPMENT_REVIEW_20261003.md) を参照。ソース変更を配置済み0.9.5へ反映済みと扱わない。

## 場所と根拠

- `app/` — 本体ソース。Python Core、Tauri/React UI、Goアダプタ。追加ルールは `app/AGENTS.md`。
- `BeeperLocal.app` — 通常配置の0.9.5。置換にはビルド・署名・公証・成果物照合が必要。旧版は `archive/app-backups/` に保全する。
- `dist/BeeperLocal-0.9.5-AppleSilicon-beta.zip` — 配布検査済みの試用版。全サービスの別Mac実機確認済みを意味しない。
- `app/docs/PROJECT_STATE.md` — 日付付きの観測・ユーザー報告・未確認範囲。0.9.5の実体は `desktop-0.9.5-{verification,install,package-verification}.json`。
- `app/docs/NEXT_IMPLEMENTATION.md` — 現在の次工程。`IMPLEMENTATION_PLAN.md` は10/1の販売計画、現行実装の一覧ではない。
- `app/docs/DESKTOP_APP.md` — 現行ビルド手順。配布用は公式Python由来の `.release-venv`（3.13.12）、Node22.22.0を使用。壊れた旧 `.desktop-venv` を作り直す必要はない。
- `business/` — 既存の販売準備。今回の開発方針から価格・公開ページを変更しない。
- `workstreams/`・`archive/`・日付付き過去資料 — 履歴。古い候補を現行へ上書きしない。

## 主な検証（app/で実行）

```bash
rtk proxy .release-venv/bin/python -B -m unittest discover -v
rtk proxy .release-venv/bin/python -B -m beeperlocal demo
rtk npm --prefix desktop test
rtk npm --prefix desktop run build
```

実際のビルド・同梱依存の設定は `docs/DESKTOP_APP.md` を参照。全テストの固定件数を手順に埋め込まない。実送信・データ消去・KeychainのACL変更を試験手順だけで許可しない。
