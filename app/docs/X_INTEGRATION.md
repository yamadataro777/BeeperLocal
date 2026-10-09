# X Chat integration — Desktop 0.8.5

0.9.0候補は参加済みグループ、受信添付、カーソル履歴取得、署名済み削除の反映、内部キャッシュを含むローカル削除を追加した。最新の実装範囲・未検証事項は[INBOX_0_9.md](INBOX_0_9.md)。以下は0.8.5時点の記録であり、新規経路の実機成功は示さない。

2026-10-01の「組み込もう」に基づく本体統合。無料の非公式X Web接続で、Beeperサービスや有料公式APIは利用しない。単独検証版で本人が確認済みの既存1対1X Chat接続、署名検証付き履歴、新着受信、手動送信・相手側着信を基にした。本体での実機結果は `desktop-0.8.4-verification.json` に分けて記録する。

## アプリでの操作

左の「𝕏」を選ぶ。保存済みの同一アカウントのログイン・暗号鍵を引き継ぐ。未ログイン時は専用のMacウィンドウで本人がXへログインし、必要な場合だけMacの保護された入力欄でChatパスコードを1回入力する。秘密情報をチャットや本体Web画面へ入力しない。

既存1対1会話を選択して直近のテキストを読む。X Chatは署名を検証し、旧形式DMは署名のない本文として区別して表示する。上限100件、ローカル検索は暗号化保存済みデータが対象。選択会話の受信中はWebSocket通知を手掛かりに署名検証付き履歴を再取得する。認証・鍵・署名・保存異常では停止。一時的な切断は1/2/4/8/16/30秒の上限付き再接続。停止・保存停止・別会話選択で受信を終了する。

手動送信は本体の永続outboxへ先に記録し、暗号化・署名した1回のリクエストを送る。署名付き受付の宛先・本人・本文・signed UUIDを照合する。結果不明は再起動後も自動再送しない。相手側の着信は別の確認を必要とする。

## 対応範囲

- 既存1対1のX Chatテキスト、受信、手動送信、暗号化保存、検索。
- 旧形式の平文DMの本文読み取り・暗号化保存・検索（0.8.5）。
- グループ、画像・添付、リアクション、編集・削除、既読、消えるメッセージ、全履歴、複数アカウントは未対応。
- 旧形式の本文と署名がないこと、未対応履歴の除外件数を画面に表示する。署名または暗号化マーカーがあるイベントは旧形式の処理へ回さない。旧形式の応答を送信成功として扱わない。
- X向けMCP・AI権限は未提供。LINE/SlackのMCP権限をXへ適用しない。
- 長時間運転・実スリープ・大量受信・物理回線断・別Macは未検証。

## 保存と更新

セッション・本人の暗号鍵・adapter DB鍵は既存のnative Keychain `local.beeperlocal.xconnector.v1` / `primary`。本体選択情報と本体DB鍵は `BeeperLocalXIntegration.v1`。パスワードやChatパスコードそのものは保存しない。

本体の履歴は `~/Library/Application Support/BeeperLocalXIntegration/messages-v1.sqlite3`。暗号セッション用の履歴・key envelope・送信intentは同ディレクトリの `adapter/history.sqlite3`。どちらも暗号化され、本文・名前・サービス側IDを平文で出力しない。

単独版 `.state/history.sqlite3` は停止・排他ロック確認後に暗号化されたままコピーし、元を退避用に保持した。単独版も同じ共有adapter保存先・排他ロックへ更新し、同時実行による鍵・セッション上書きを防ぐ。旧コピーへ戻ると古い送信intentや鍵になるため、通常運用では共有保存先を利用する。

## 構成と再現

本体Python Coreから同じ署名付きCoreの `--x-worker` を非公開pipeで起動し、Goの `beeperlocal-x` とSwiftの `beeperlocal-x-login` を利用する。秘密はworker内部でKeychainから読み、コマンド引数・環境変数へ渡さない。UIへ渡す認証状態は固定stage/codeのみ。履歴の本体保存完了を受けてからworkerへackする。

固定したmautrix-twitter commit `5282873f8a8941c11e6e0aa66aeb9c0e0d9fab3d` と `chatxdk==0.5.0`。ソースとライセンスは `x-adapter/` と同梱 `X-PROVENANCE.md` / `X-THIRD-PARTY-NOTICES.txt`。`scripts/build-desktop.sh --release` で既存と同じDeveloper IDによる正式署名を行う。公証は別工程で未実施。

検証（2026-10-02）: 最終本体ソースでCore374件・GUI28件成功。X暗号・保存回帰30件はCoreに含む。Go bridge試験、Swift自己診断、production build、offline demo、shell構文を確認した。

署名付き同梱CoreからX接続・会話181件・既存の検証会話の履歴7件・旧形式除外2件・受信待機・Core再起動後の保存済み検索1件を確認。今回の実送信は0回。本体の新着受信と相手側着信、native GUIの実画面は別の未確認項目。通常アプリ0.8.4を配置し、本体とCoreの起動を確認。旧版0.8.3は `archive/app-backups/` へ退避済み。詳細は `desktop-0.8.4-verification.json` と `desktop-0.8.4-install.json`。

0.8.5: 旧形式DMの本文表示は通常アプリにも反映済み。同じメッセージの形式違いによる件数重複をまとめる追加修正はソースへ反映・検証済みで、次回本体ビルド待ち。並行更新のLINEメディア・Slackプロフィールを保全した。詳細は `x-legacy-text-verification-20261002.json`。
