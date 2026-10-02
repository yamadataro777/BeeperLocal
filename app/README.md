# BeeperLocal — Macデスクトップアプリ

Desktop version: `0.8.3` / updated 2026-10-01

**Slack開発差分:** 追加対象をSlack優先、Discordを次候補へ変更。既存Slack User OAuth・暗号化保存・検索を再利用し、本人送信・スレッド取得・定期取得・GUI/MCPを追加しました。定期取得は選択1会話の直近15件、スレッドはMCPから個別取得です。公開チャンネル1会話で本人送信・成功応答、本人のSlack側新着投稿の自動取得、暗号化保存・再オープン検索・重複送信抑止を確認しました。実DM・相手からの返信・商用適合は未確認です。この時点のSlack実装は、LINE復旧修正を含む通常アプリ0.8.3にも同梱済みです。最新方針と範囲は[Slack実装記録](docs/SLACK_IMPLEMENTATION.md)を参照してください。以下に0.8.3と過去の検証記録を示します。


`../BeeperLocal.app`をダブルクリックして起動します。Python・Node・Terminalの常駐は不要です。LINEとInstagramを左のサービスボタンで切り替え、会話一覧・履歴・受信・テキスト送信・ローカル検索を同じアプリで操作できます。既存のログインと暗号化保存データを引き継ぎます。初回のKeychain確認はMacの画面で本人が許可してください。

0.8.3でLINEが一時的な通信障害の再試行上限に達すると永久停止する問題を修正しました。短い再試行の後も1分間隔で自動復旧を続け、認証・保存異常や明示停止では停止します。Core325件・画面25件成功。正式署名した通常アプリでLINE受信子プロセスを7回連続で終了し、最後の中断から約61秒で本体再起動・手動再接続なしに復帰、45会話と受信待機を確認。Instagramの既存返信・停止中返信・受信待機も維持しました。選択中のLINE会話は履歴0件だったため、この実機試験でのLINE履歴維持は未判定です。物理的なスリープ・回線断・長時間運転は引き続き未検証です。[修正と検証](docs/LINE_RECEIVER_RECOVERY.md)、[結果](docs/desktop-0.8.3-verification.json)。

0.8.2でInstagram受信の再接続と履歴回収、復旧後のエラー表示を改善し、正式署名付きの通常アプリへ更新しました。Core 287件・画面21件・production build・offline demo・shell構文が成功。実機でLINEとInstagramの受信子プロセスを各1回終了し、本体再起動や手動操作なしの復帰と履歴維持を確認しました。LINEは45会話・履歴・待機も確認済みです。0.8.1で承認済み送信1回、相手側着信と返信の本人確認、返信の表示・アプリ再起動後の検索1件を確認済みです。0.8.2では本体・受信プロセスを変えず新着返信1件を受信し、再起動後の検索1件を確認。停止中の追加返信も起動時に回収・検索1件を確認し、Instagram統合の実往復Gateを閉じました。実スリープ・実回線断・長時間運転は未確認です。正式署名は検証済み、公証と別Mac検証は未実施。詳細は[0.8.2検証記録](docs/desktop-0.8.2-verification.json)。

0.8.0で既存の通常アプリへInstagramを統合しました。LINEのQR連携・会話順・相手名・プロフィール画像・MCPは維持しています。既存のInstagramアカウントと保存履歴を引き継ぎ、実アプリで履歴9件・検索・受信待機を確認しました。LINEも45会話・履歴・プロフィール画像・受信待機を確認済みです。Instagramの取得範囲は直近1ページ（最大20件）。MCP接続・画像・グループ・全履歴同期は未対応で、今回の統合後の実送信・新着受信は未検証です。キーチェーン改善を含めた内部テスト280件・画面テスト19件成功。配布物と実機結果は[0.8.0検証記録](docs/desktop-0.8.0-verification.json)を参照してください。

0.7.0でアプリ内の初回LINE連携（QR・スマホ承認）を追加し、左の会話一覧をLINE側の最終更新順へ修正しました。友だち以外も含む相手名とプロフィール画像を表示します。初回連携・更新手順は[Macアプリ](docs/DESKTOP_APP.md)を参照してください。別の人のスマートフォンによる本番の初回承認は未確認です。

0.6.0でLINEの上限付き自動再接続、権限付きローカルMCP、保存停止・確認付き削除を追加しました。MCPは初期状態で停止し、接続設定から会話ごとの閲覧／送信を許可できます。内部テスト219件と画面テスト11件が成功。独立した公式SDK clientとのローカルHTTP往復は架空データで確認済みです。使い方は[Macアプリ](docs/DESKTOP_APP.md)、権限と制限は[MCP要件](docs/MCP_REQUIREMENTS.md)を参照してください。

0.5.1では実LINE接続、会話500件、実履歴、承認済み送信1回、再起動後の復元・検索を確認済み。相手側着信・返信受信・順番はユーザー報告で正常確認済みです。これは新規MCPの実データ接続の証拠とは分けています。長時間運転、全履歴、cursorと保存の原子的な同期は未確認／未実装です。

利用・ビルド手順: [DESKTOP_APP.md](docs/DESKTOP_APP.md)。実装順: [LINE → Instagram → 𝕏](docs/IMPLEMENTATION_PLAN.md)。画面仕様: [UI_DESIGN.md](docs/UI_DESIGN.md)。

MatrixとSlackの実データをローカルで取得・共通形式に正規化し、**メッセージpayloadをAES-256-GCMで暗号化してSQLiteへ保存し、端末内で検索する**PoCです。独自クラウドは使いません。

## 既に閉じたGate

2026-09-27のMac実機実行で、同一の`proof --limit 1`からMatrix 1件＋Slack 1件を取得し、同一タイムラインへ正規化・時系列統合できました。したがって **Gate A: Connectivity / Integration はCLOSED** です。

50件条件は基本接続の成否ではなく、Gate B（Volume / Pagination）として分離しています。まだOPENで問題ありません。

## Phase 1で追加したもの

```text
Matrix / Slack
      ↓
UnifiedMessage
      ↓
AES-256-GCM authenticated encryption
      ↓
SQLite (local only)
      ↓
decrypt in memory
      ↓
substring search
```

- `sync`: 選択済みMatrix/Slack会話を取得し、暗号化SQLiteへupsert。
- `db-status`: 本文を出さず保存件数確認。
- `search`: 検索語をTTYの非表示入力で受け、DB内容をメモリ上で復号して部分文字列検索。
- `reset-local`: ローカルDBとDB専用暗号鍵だけを削除。
- DB専用256-bit鍵はmacOS Keychainに保存。
- plaintext FTSは**作らない**。本文・会話名・sender/account/provider-side IDsは暗号化payload内。
- SQLiteに平文で残るのは安定message hash、provider名、時系列用timestamp、スキーマmetadataです。

これはSQLCipherのようなDB全体暗号化ではありません。詳細は `docs/ADR_PHASE1_PERSISTENCE.md` と `docs/SECURITY.md` を参照してください。

## v0.3からの移行

v0.3のフォルダやDBをコピーする必要はありません。Matrix/Slackのログイン情報と会話選択はmacOS Keychainの同じservice (`BeeperLocalPoC.v1`) を使うため、Keychain情報が残っていれば再ログイン・再選択せず続行できます。

新しいフォルダで:

```bash
chmod +x run.sh
bash scripts/setup.sh
./run.sh doctor --check-keychain
```

その後、今の最短Closed Loopは:

```bash
# 現在選択済みのMatrix + Slackから1件ずつでもよい
./run.sh sync --limit 1

# 再起動相当でDBを再度開けることを確認
./run.sh db-status

# 検索語はコマンド引数にせず、非表示プロンプトで入力
./run.sh search --preview
```

`search --preview`はマッチ本文をTerminalに表示します。画面共有・スクロールバックへ残したくない場合は`--preview`を付けません。

## 既存コマンド

```bash
./run.sh proof --limit 1      # Matrix + Slackのlive integration gate
./run.sh fetch matrix --limit 1
./run.sh fetch slack --limit 1
./run.sh report
./run.sh test
```

`proof`のGate Aは各provider >=1件でCLOSED。`volume_loop_status`は各provider >=50件でCLOSEDです。

## 保存先

| データ | 保存先 |
|---|---|
| Matrix/Slack資格情報・選択会話 | macOS Keychain `BeeperLocalPoC.v1` |
| ローカルDB暗号鍵 | 同Keychainの専用entry `local-db-key-v1` |
| 暗号化メッセージDB | `~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3` |
| body-free proof/sync report | `~/Library/Application Support/BeeperLocalPoC/*.json` |

`reset-local`はメッセージDBとDB鍵だけ削除し、Matrix/Slackログイン資格情報は残します。

## 今回まだ証明していないこと

- 50件以上のvolume/pagination実機テスト
- 増分sync cursorによる「新規分だけ」の同期
- provider側での削除の反映
- 編集履歴の完全同期
- Matrix E2EEルーム復号
- 添付本文・ファイルの保存
- LINE以外のリアルタイム購読・メッセージ送信
- デスクトップアプリ経由の実LINE送受信1往復（Core経由は過去にユーザー確認済み）
- SQLCipher等によるDBファイル全体の暗号化
- 製品レベルのセキュリティ監査・署名・自動更新

最新状態は `docs/PROJECT_STATE.md` をsource of truthとして扱ってください。

## LINE 1対1 text統合（2026-09-30）

Mac-nativeの`LineConnector`を追加。検証済みline-cli v0.4.0の既存セッションを使い、`send line` / `watch line`を同じUnifiedMessage・暗号化SQLiteへ接続します。`sync line` / `search --provider line`も利用できます。

手動の実機1往復は、ユーザーの全手順成功報告を根拠にCLOSEDです。回帰確認は`./run.sh line-e2e`にまとめました。通常利用は下記、詳細は[LINE手順書](docs/LINE_CLOSED_LOOP.md)を参照してください。

## LINEの通常利用

`line-cli`の既存セッションは起動時に自動復元します。相手は一度選択すればKeychainに残り、毎回login/selectする必要はありません。LINE sessionが無い場合だけ、先にline-cliで本人操作のログインが必要です。

```bash
./run.sh select line
```

会話一覧から番号で相手を選択します。MIDの手入力は不要です。

受信を続けるTerminal:

```bash
./run.sh daemon line
```

既存watchの別名で、既定では無期限。開始前に選択した会話の直近50件を取得し、textと回収記録を暗号化して一括保存します。`--recovery-limit 100`で100件まで指定できます。取得・保存が失敗した場合は受信を開始しません。`--from-now`指定時だけ履歴回収を省略します。Ctrl-Cで停止します。別Terminalから通常送信:

```bash
./run.sh send line
```

保存データを読む:

```bash
./run.sh conversations line
./run.sh messages line
./run.sh search --provider line
./run.sh sync-status line
```

`conversations line --refresh`で会話一覧を更新・暗号化保存。表示名は`--names`、本文は`messages line --preview`を明示したときだけ表示します。会話のidentityは常にraw LINE MIDで、DB内では暗号化payloadに保存します。

`capabilities`で各connectorの対応操作を確認できます。Matrix/Slack/LINEの生成・list/fetch・保存は共通経路。送信とrealtimeは現状LINEのみで、未対応providerは明示的にエラーになります。

reconnect・token refreshはMacで動くline-cliの既存実装を使用します。Coreは独自の認証や送信リトライを追加しません。LINE側の強制ログアウトは本人の再ログインが必要です。

`sync-status line`は前回の履歴回収結果をローカルから読みます。現在の接続状態ではありません。回収は直近の件数制限付きで、完全な増分同期・全履歴取得・削除反映は未実装です。詳細は[履歴回収のADR](docs/ADR_LINE_RECOVERY.md)を参照してください。
