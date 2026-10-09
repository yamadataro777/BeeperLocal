# BeeperLocal — Macデスクトップアプリ

LINE・Instagram・Slack・X・Messengerのメッセージを1つのMacアプリで扱い、端末内の暗号化SQLiteへ保存・検索します。サービス・アカウント・会話ごとの権限付きローカルMCPでAIへ接続します。

## 配置済みアプリと開発ソース

通常配置は**公証済み0.9.5**（2026-10-03）。Slackの専用URL `beeperlocal://oauth/slack`、PKCE、12 user scopes、token rotation、外部ワークスペース配布と公開Client IDを設定済み。Messenger会話切替時のKeychainアクセス削減、画像送信、プロフィール保存も含みます。[配置記録](docs/desktop-0.9.5-install.json)、[検証記録](docs/desktop-0.9.5-verification.json)。

[試用ZIP](../dist/BeeperLocal-0.9.5-AppleSilicon-beta.zip)は署名・公証・梱包・展開後起動と対応ソース一致を検証済み。Slackの新しい本人認証完了、別Macでの全5サービスの実ログイン・送受信、画像着信、長時間運転は未確認です。[ZIP検証](docs/desktop-0.9.5-package-verification.json)。

**現在の開発ソースには、0.9.5以後の簡素化を反映済みです。** 旧DB自動更新、旧設定・Messenger本文/会話選択の取込み、Slackの旧localhost認証を除きました。非対応データは書き換えず停止します。これらは配置済みアプリとZIPには未反映です。[変更と検証](docs/DEVELOPMENT_REVIEW_20261003.md)。

## 利用と対応範囲

`../BeeperLocal.app`を起動し、サービスを選んで本人のログイン画面から連携します。Python・NodeのインストールやTerminal常駐は不要です。ログイン時のサービス承認とmacOS Keychainの許可は本人が行います。

- [導入手順](docs/BETA_INSTALL.md)、[試用ガイド](docs/BETA_GUIDE.md)
- [履歴取得・通知・削除・更新の範囲](docs/INBOX_0_9.md)、[MCPの会話別権限](docs/MCP_0_9_1.md)
- [LINEメディア](docs/LINE_MEDIA.md)、[画像送信と本人確認](docs/USER_FEEDBACK_0_9_3.md)
- [セキュリティ](docs/SECURITY.md)、[暗号化保存ADR](docs/ADR_PHASE1_PERSISTENCE.md)、[Messenger端末状態](docs/ADR_MESSENGER_PERSISTENCE.md)

資格情報とDB鍵はnative macOS Keychainに保存します。本文・相手名・provider側IDはAES-256-GCMで暗号化し、検索は上限付きでメモリ上の復号結果を使います。平文FTSはありません。DB全体の暗号化ではなく、件数・provider・時刻・安定hash等は見えます。

完全な過去履歴、全サービスの削除同期、LINEの他クライアントとの同時利用、Messengerの旧暗号化バックアップ復元を保証しません。サービスごとの制限と、fixture・実機・本人報告の区別は各仕様と [PROJECT_STATE](docs/PROJECT_STATE.md)を参照してください。

## 開発

[AGENT.md](../AGENT.md)と[本体ルール](AGENTS.md)に従い、資料更新 → 必要なテストの失敗確認 → 最小実装 → 不要コード・矛盾の点検の順に進めます。主担当だけで作業し、開発中は後方互換・データ移行を維持しません。旧形式を黙って初期化することもありません。

現行ビルド手順は [DESKTOP_APP](docs/DESKTOP_APP.md)、署名・公証・Slack設定は [RELEASE_DISTRIBUTION](docs/RELEASE_DISTRIBUTION.md)。配布用Pythonは `.release-venv`（3.13.12）、Node22.22.0を使用します。

`app/` での基本確認:

```bash
rtk proxy .release-venv/bin/python -B -m unittest discover -v
rtk proxy .release-venv/bin/python -B -m beeperlocal demo
rtk npm --prefix desktop test
rtk npm --prefix desktop run build
```

CLIの操作一覧は `rtk proxy .release-venv/bin/python -B -m beeperlocal --help` で確認します。実送信やDB/鍵の削除を、開発テストの一部として自動実行しません。

次工程は [NEXT_IMPLEMENTATION](docs/NEXT_IMPLEMENTATION.md)。[販売計画](docs/IMPLEMENTATION_PLAN.md)は10/1時点の事業前提資料、[旧README](docs/README_BEFORE_KISS_20261003.md)は過去の実装履歴です。過去の未対応事項・移行手順・候補版を現行指示として扱わないでください。
