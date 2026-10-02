# セキュリティ境界・制限 — Phase 1

## Desktop 0.8.0 / Instagram統合

LINEとInstagramの操作をproviderで明示的に分け、異なるprovider・account・conversation宛ての送信要求を拒否する。Instagramは本人が連携した既存のKeychain serviceと暗号化DBを継続利用し、資格情報・本文を移行用ファイルや環境変数へ出さない。画面のlocalStorageに残すのは選択サービス名のみ。下書きはメモリ上でサービス・会話別に分離する。

Instagram adapterとの通信はprivate stdin/stdout pipeのみ。ログインsessionはKeychainへ保存してからackし、watch開始時の履歴は暗号化DBへcommitしてからackする。送信はledgerを先に保存し、送信APIのretry・redirect・GraphQL reload retryを無効化する。結果不明の送信を自動再送しない。session更新が衝突しないよう、GUI送信中は同じproviderのwatchを停止する。

InstagramはMCP・LINEログイン・LINEプロフィール画像取得・保存データ削除の操作を許可しない。LINEのMCP権限はInstagramに適用しない。受信cursorとDB commitの完全な同期、全履歴回収、長時間のsession更新、独立した複数プロセス間のsession更新調整は未完了。通常利用中に別CLIのwatchを並行起動しない。

このPoCはセキュリティ監査済み製品ではありません。Local-first、Keychain、AES-GCMはリスク削減策であり、完全な安全性の保証ではありません。

## Secret / credential

- Matrix/Slack/Telegramの資格情報はmacOS Keychainのみ。平文`.env`/JSONへのfallbackなし。
- DB専用暗号鍵もKeychainに別entryとして保存。
- 検索語はCLI引数として受けず、TTY非表示入力。shell historyへ残さない。
- Provider SDKの生エラー/API応答/tokenをTerminalへ出さない。

## Message persistence

SQLiteのmessage rowは以下だけを平文で持つ。

- SHA-256由来のstable message ID
- provider (`matrix` / `slack` 等)
- UTC timestamp（整数）
- AES-256-GCM ciphertext

ciphertext内には本文、会話名、sender ID、account ID、conversation ID、provider message ID、reply ID等を格納する。

AES-GCM nonceはmessage保存ごとにランダム12 bytes。Associated Dataにstable message IDを使用するため、ciphertextのrow入れ替え・改ざんは復号時に検出する。

## SQLite hardening used

- state directory `0700`
- DB file `0600`
- symlink database/sidecar拒否
- `journal_mode=DELETE`
- `synchronous=FULL`
- `secure_delete=ON`
- `temp_store=MEMORY`
- `trusted_schema=OFF`

ただしSSD/ファイルシステム上の過去ブロック完全消去を保証しない。

## plaintext FTSを作らない理由

SQLite FTSへ本文を投入すると検索indexが平文になる。Phase 1では検索性能よりデータ境界を優先し、最大10,000rowsをメモリ上で復号しsubstring検索する。

将来の大規模運用では、SQLCipher等のDB全体暗号化や安全なindex方式を別Gateで評価する。

## metadata leakage

DB全体暗号化ではないため、provider、timestamp、件数、DBサイズ、更新日時、stable hashはローカルファイルから観察できる。本文やprovider-side identityは暗号化payload内。

## Runtime leakage

本文は実行中にRAMへ復号される。OS swap、debugger、crash dump、マルウェア、Terminalの`--preview`、スクリーンショットや画面共有まで完全に防がない。

Keychainも同一ユーザーの任意コードを完全隔離するsandboxではない。製品化時はネイティブ署名、entitlements、IPC、update trust chain、supply-chain reviewを独立実施する。

## Partial sync policy

`sync`で要求したproviderのどれかが取得/正規化に失敗した場合、そのrunでは**部分保存しない**。成功したように見せるために片方だけDBへ入れない。

## Deletion / edits

同一stable IDはupsertされるので再取得時の更新payloadは置き換わる。一方、provider側で削除されたmessageをローカルから削除するreconciliationは未実装。次工程の独立Gate。

## LINEと会話catalog

LINE session/Letter Sealing鍵は既存line-cliのmacOS Keychainで管理する。BeeperLocalはproviderのaccount・選択会話をKeychainへ登録し、認証tokenをコピーしない。

conversationsテーブルの平文列はscoped hashとproviderのみ。raw canonical MID、account、title、locatorは既存DB鍵によるAES-256-GCM payload内に置く。conversation用AADをmessage用AADから分離する。既存message暗号形式は変更しない。

`line-e2e`はテスト状態をKeychainへ保存しない。1回の起動で1回だけ送る。停止後に再起動すれば新しい送信になるため、送信結果不明時は相手側確認が先。

## LINE履歴回収の保存状態（2026-09-30）

`sync_receipts`はscoped conversation hash、provider、AES-256-GCM ciphertextのみを平文列として持つ。account/conversation ID、最終回収時刻、件数・上限到達は暗号化payload内。AADは`sync-receipt/v1`として他テーブルと分離する。message・conversation・receiptは同一transactionで保存し、いずれかが失敗するとすべて巻き戻す。

receiptは直近履歴の取得記録であり、providerの受信cursorや全件取得保証ではない。通常watch開始前に回収するが、line-cli cursorとSQLite保存の原子性はまだない。上限外や削除・unsendは回収できない。仕様は[ADR_LINE_RECOVERY.md](ADR_LINE_RECOVERY.md)を参照。

## Desktop 0.5.0

アプリにCoreとline-cliの実行ファイルを同梱し、セッション・資格情報・DBを同梱しない。画面は固定typed commandとprivate pipeを使い、任意shell・filesystem・外部HTTPを公開しない。Keychainアクセス失敗時は既存データを再初期化せず停止する。

送信ledgerもAES-GCMで暗号化し、providerを呼ぶ前に保存する。未確定送信は再起動後も自動再送しない。本文・宛先等をlocalStorageやログに保存しない。詳細は[ADR_DESKTOP.md](ADR_DESKTOP.md)。一般配布用の署名・公証、完全な推移依存hash-lock、セキュリティ監査は未実施。

## Desktop 0.6.0 / local MCP

client権限・token hash・設定は既存鍵のAES-GCMで`private_settings`へ保存し、token原文は発行時のみ返す。MCPは初期無効で127.0.0.1限定。HTTP入口とCore tool、外部送信直前で現在の許可を確認する。詳細は[ADR_LOCAL_MCP.md](ADR_LOCAL_MCP.md)、通信確認は[COMMUNICATION_PATHS.md](COMMUNICATION_PATHS.md)。

保存停止は永続化する。確認付き削除は現在のLINE accountだけを対象にし、権限も同一transactionで失効する。二重送信防止のため内容を含まない要求hashだけは残す。MCP read許可を残したままの保存停止は、外部clientによる保存済み内容の閲覧停止ではない。

## Desktop 0.7.0 / 初回LINE連携・プロフィール

QR/PINはprivate subprocess pipeとメモリ上の状態だけで保持し、各段階の切替・中止・失敗時に消去する。QRの生成には既存CLIのローカルencoderを使用し、第三者のQRサービスを使わない。既存ログインの置換はUIで明示選択された場合のみ--forceを渡す。native Keychain、login snapshot、session lock、スマートフォン承認を維持する。LINEから最終承認後の結果が不明な場合は自動で再ログインしない。

会話の更新時刻・PicturePathも既存の暗号化payload内に保存する。画像は固定HTTPS CDNから上限付きで取得しメモリに一時cacheする。外部URL・query・redirect・SVGを受け付けない。GUIのCSPに新しいネットワーク接続先を追加しない。MCPにloginやavatarの操作を追加しない。

## キーチェーン許可の維持・署名準備（2026-10-01）

接続情報・DB鍵の保存backendをSecurity.framework直接呼出しへ変更。既存項目は値のみ更新し、削除再作成でアクセス許可を失わない。許可拒否・ロック時は既存項目を保持して停止する。新規項目のアクセスはmacOS標準の作成元に限定し、既存ACLの一括変更・全アプリ許可・秘密のファイル保存を追加しない。

製品用buildではDeveloper ID Application・同一Team・固定Identifierを必須とし、Core内蔵runtimeを含め署名と検証を行う。0.8.1で正式署名を適用し、4実行対象・67内蔵ライブラリを検証済み。同じDeveloper IDで署名した異なるテストプログラム間では、確認UIを禁止した6回のKeychain操作が成功。公証・別Macでの製品更新検証は未実施。詳細と受入条件は[KEYCHAIN_SIGNING.md](KEYCHAIN_SIGNING.md)。
