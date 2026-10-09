# Messenger本体統合 — 開発版

現行通常アプリは公証済み0.9.5。1対1送信・MCP・画像送信を含む。仕様は [INBOX](INBOX_0_9.md)、[MCP](MCP_0_9_1.md)、[保存ADR](ADR_MESSENGER_PERSISTENCE.md)。現行ソースでは旧PoC本文とKeychain会話選択の自動取込みを廃止した（[見直し](DEVELOPMENT_REVIEW_20261003.md)）。この変更は配置済み0.9.5へ未反映。

以下は初期統合時点の観測履歴で、現行操作手順・未対応一覧ではない。

2026-10-02。サービス一覧にMessengerを追加した。本人の専用Facebookログイン、既存E2EE端末の復元、取得できた会話の一覧、受信テキスト表示、新着の暗号化保存、保存済み検索、再接続、保存停止に対応する。通常アプリへの配置は別工程。

## 操作

Messengerを選択して接続する。以前の検証ログイン・端末鍵・保存済み本文があれば引き継ぐ。初回はアプリの案内から専用WebKitウィンドウを開き、本人がFacebookにログインする。普段のブラウザやBeeperの資格情報は読み出さない。Keychainの本人確認はMac側で行う。

接続中はこの登録端末へ届く1対1E2EEテキストを受信する。会話の選択変更では受信セッションを再起動しない。「受信を再接続」は端末を復元して接続し直す操作で、古い暗号化バックアップの復元ではない。

接続設定から受信停止・保存停止・同じアカウントの再ログインができる。送信UIとMCPの権限設定は提供せず、Coreも該当操作を拒否する。LINE/Slack等のMCP許可はMessengerへ適用しない。

## 保存

本文は専用のAES-GCM暗号化SQLite、資格情報・端末鍵・DB鍵はnative Keychain。検証版の本文200件上限を通常の保存履歴へ適用しない。1会話100件表示、最新10,000件検索、最大50結果。端末snapshotの4 MiB上限は残し、超過や保存異常では停止する。詳細と保存ACKの順序は[ADR](ADR_MESSENGER_PERSISTENCE.md)。

Goは`messenger-adapter/`の独立したMessenger専用CLIを使う。`instagram-adapter/meta`の固定messagix sourceを利用し、Instagram専用CLIのplatform変更では実装しない。専用Swiftログインとともに本体へ同梱・署名する。[同梱出典](../desktop/src-tauri/resources/MESSENGER-PROVENANCE.md)。

## 確認済みと未確認

- 架空データ: 新規Core境界22件、Go8件、Swiftログイン境界検査。Core全432件・GUI全39件、offline demo、shell6ファイル、production buildを確認。
- ソース版Coreと署名済みGo接続部で実接続し、保存履歴2件・会話2件を本体の暗号化DBへ取り込んだ。CoreとGoを終了して別プロセスへ切り替え、オフライン検索1件一致と再接続を確認した。本文・相手・ID・検索語はレポートへ出していない。
- 完全な本体Coreの同時起動は、稼働中Coreの排他ロックで`DESKTOP_ALREADY_RUNNING`として停止した。稼働中アプリを終了せず、専用provider検証へ切り替えた。ソース版Coreの実測を、通常アプリGUIの実測とは扱わない。
- 統合後の追加新着受信・通常GUI実データ表示・物理スリープ/回線断・長時間運転・公証・別Macは未確認。実送信0回。過去の検証で受信した2件の引き継ぎを、新しい受信の証拠へ数えない。

最終build hash・署名と実測ファイルへの参照は[messenger-integration-verification.json](messenger-integration-verification.json)。[架空データの画面](messenger-integration-fixture.png)。既存の独立検証は[元の記録](../../workstreams/messenger-verification/README.md)を維持する。

## 初期統合時の再現用コマンド（履歴）

```sh
rtk proxy .desktop-venv/bin/python -B -m unittest tests.test_desktop_messenger -v
rtk proxy .desktop-venv/bin/python -B scripts/build-messenger-adapter.py
rtk proxy .desktop-venv/bin/python -B scripts/verify-messenger-desktop.py
```

最後のコマンドは実データを使う受信専用確認で、ログイン・送信・鍵リセットは行わない。別Coreが起動中なら停止する。`--source-core`指定ではMessenger専用ロック下の別Pythonプロセスと署名済みtransportを使い、他providerのCoreを停止しない。再実行は接続が必要なときだけ行う。
