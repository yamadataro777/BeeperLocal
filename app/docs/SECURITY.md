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

## X Chat desktop boundary (0.8.5)

X credentials/private keys stay in its original native Keychain service. The shared adapter database and GUI database have separate Keychain-backed keys, encrypted payloads and private filesystem permissions. The worker has an exclusive session lock, bounded private IPC, discarded stderr and native authentication prompts. X Chat text crosses to the common model only after signature verification. Legacy DM text may cross only when neither a signature nor an encryption marker is present, with explicit verified=false/source=legacy provenance, scoped stable legacy: IDs and validated sender/time metadata. Legacy provenance relies on authenticated server history, not end-to-end signatures. History receipt acknowledgement follows persistence. Durable outbox and one-shot transport prevent replay after ambiguous sends. X has no MCP grant surface. Legacy support never downgrades a signed/encrypted event or acknowledges a send. Conflicting identities fail the entire batch; disappearing and unsupported content stays excluded. See [X integration](X_INTEGRATION.md).

## Desktop 0.8.5 / LINEメディア

画像・スタンプの種別と数値スタンプIDのみを既存の暗号化message payloadへ追加。画像本体はprivate pipeとRAMのみを通り、ディスクへ平文保存しない。GUIから指定できるのはローカルの会話hash・message hashで、保存済みのprovider/account/conversationと照合する。LINE添付の認証・復号は同梱CLIの既存実装を使用。スタンプCDNは固定HTTPS host、数値ID、redirect拒否、最大2 MiB。Pillowで実画像を検証・縮小・再生成し、EXIF等を継承しない。キャッシュ24 MiB、同時1取得に制限し、保存停止・ログイン更新・会話切替・終了で中止する。CSPやMCPの外部権限を拡張しない。詳細は[LINE_MEDIA.md](LINE_MEDIA.md)。


## Messenger受信統合（2026-10-02）

Messenger専用Keychain/device identityと本体用の暗号化SQLiteを分離。本文・会話commit→端末snapshotのKeychain更新・読み戻し→受信ACKの順序を守り、保存異常では停止する。既存端末DBが欠落・破損した場合や登録結果不明時は自動再登録しない。登録済みアカウントmarkerは暗号化DBにも保持する。専用プロセス間lockでPoCとの同時更新を拒否する。

本文履歴は共通のscoped identityで暗号化保存・検索し、端末SQLiteはRAMとKeychain snapshotに限定。復号済み再配信バッファが一時的にsnapshotへ含まれ得る。snapshotの4 MiB上限とDB/Keychain間の非原子性は残る。送信・MCP・他providerログイン・鍵リセットのIPCは拒否する。詳しくは[保存ADR](ADR_MESSENGER_PERSISTENCE.md)と[統合範囲](MESSENGER_INTEGRATION.md)。

## Desktop 0.9.0 / 全会話取得・OAuth・送信・更新（2026-10-03）

この節は0.9.0候補の変更を記録し、上記の旧版での未対応事項を次の範囲だけ更新する。実プロバイダーでの新機能受入や一般公開を示すものではない。

- SlackのブラウザOAuthはS256 PKCEを使用する。state/verifier/codeをメモリに限定し、127.0.0.1の固定パス・Host・stateを確認する。トークン交換とローテーションはCore内で行い、macOS Keychainへ一括保存する。Client Secretの配布、WebViewへのトークン転送、資格情報のファイル・環境変数fallbackは行わない。公開Client IDとSlack側設定は未構成。
- 全会話の巡回と履歴ページ取得は、表示・送信先の選択とは独立する。ページ本文・会話・取得cursor・ローカル未読を同じ暗号化DB transactionに保存する。CLIの複数provider一括syncの部分保存禁止は維持する。LINEのprovider受信cursorとの完全な原子性、取得できない過去履歴の回復は未対応。
- 削除は明示的なイベントだけを反映し、取得ページにないことを削除理由にしない。削除識別情報はprovider/account/conversationで限定する。Xは署名と送信者、Messengerは認証済み送信者の自己取消を照合する。取消より後の履歴再取得で本文が復活しないよう保持する。Instagramは接続中のイベント、SlackはAPIの明示的な削除情報の範囲であり、全サービスの完全な削除同期ではない。
- Messengerの1対1テキスト送信は既存の端末・受信プロセスを使い、共通の暗号化outboxを先にcommitする。端末snapshotと送信結果の保存確認後に完了を返す。SDKの再接続・送信再試行を抑止し、不明結果を自動再送しない。グループ送信とMCPは未対応。DB/Keychain間の非原子性とsnapshot上限は残る。
- X/Instagram添付はCoreから許可したHTTPS配信先へ取得し、redirect・認証情報付きURL・環境proxyを使わない。1添付4 MiB、固定MIMEと形式検証、画像再生成を行う。X暗号化添付は署名済み鍵を使用し、ストリーム認証失敗・切断・改ざんを拒否する。外部URLや鍵をWebViewの取得APIに渡さない。動画・音声は検証済みデータURLとしてメモリ内で扱う。
- 全5サービスのローカル削除は対象accountを確認し、受信停止後に実行する。本文・会話・取得情報・権限・送信内容と、Xの内部本文を削除する。Messenger旧受信キャッシュの削除は0.9.5までの処理で、現行ソースでは取り込まず、端末Keychainも書き換えない。ログイン・端末鍵・登録markerは保持し、二重送信防止の要求hashも残す。媒体上の完全消去保証は従来どおり行わない。
- macOS通知は本人が有効化した場合にサービス名だけを表示する。未読はこのMacの状態であり、元サービスの既読状態は変更しない。
- 更新はHTTPS manifestと最終Apple署名後のアーカイブを使用し、Ed25519署名・署名されたversion・サイズ上限を検証する。署名秘密鍵はKeychainのみ。適用は本人操作で、下書き・操作中は停止する。検証済みの更新を適用する直前にCoreとMCPを終了する。配布先・公開鍵は未構成で、実配布・インストール・再起動の受入は未実施。

根拠・取得制限・公開設定・検証範囲は[INBOX_0_9.md](INBOX_0_9.md)と[desktop-0.9.0-verification.json](desktop-0.9.0-verification.json)。資格情報の移行・ACL緩和・本番データ削除は実施していない。


## 2026-10-03 / 0.9.1 MCP拡張

Instagram・X・MessengerのMCPを追加。サービス別の設定・暗号化grantキー・listener portを使用し、同じ数値account IDでも別サービスのtokenは通らない。0.9.5までは保存停止だけ旧設定から引き継いだ。現行ソースは旧設定だけが残る状態を拒否し、自動取込み・収集再開を行わない。旧LINE grantやMCP有効状態も流用しない。許可済み保存履歴のcursorは会話scopeを照合する。送信は明示的な対象・永続outbox・UUID重複抑止を維持し、認証待機・adapter起動・Messenger書き込みロック後の権限取り消しも反映する。原文tokenは再表示・永続化しない。

新3サービスの公式SDK HTTP往復、別token拒否、再起動、失効、送信待機中の権限取り消しを架空データで検証。実送信・実資格情報へのMCP grant登録は実施していない。[利用範囲](MCP_0_9_1.md)。

## 2026-10-03 / 0.9.3 画像送信・プロフィール保存

GUIの画像送信は宛先・アカウント・本人操作に限定し、4MiB・2,500万画素以内のJPEG/PNGをメモリでデコード、向きを補正してメタデータを除く。画像の平文一時ファイルは作らない。プレビューとプロフィールは既存のAES-GCM private recordsへ保存し、本文と同じ削除範囲に含める。画像ハッシュとUUIDの送信台帳を先に記録し、不明結果の自動再送・HTTPリダイレクトによる書き込み再試行を抑止する。MCPの送信対象は従来のテキストのみ。

LINE・X・Messengerは既存の暗号化経路を利用する。Xの会話鍵・署名鍵はGoヘルパーへ渡さず、XDKで暗号化・署名検証する。Slackは公式の外部アップロードAPIを使用し、アップロード先へOAuthトークンを転送しない。プロフィールはサービス別に許可した画像配信先から、認証ヘッダー・環境プロキシ・リダイレクトなしで取得し、OSのTLS検証を使用する。

Native Keychainの読み取りはGUIプロセス内だけで共用する。メモリキャッシュは最大32項目で終了時に破棄し、ファイル・環境変数へ資格情報を移さない。キャンセルや認証拒否は記憶して再接続操作まで同じOS要求を繰り返さない。既存アイテムのACL、署名要件、DB鍵は変更しない。今回の自動試験は架空データであり、実サービスの着信・別Mac固有の許可状態は未検証。[詳細](USER_FEEDBACK_0_9_3.md)。

## 0.9.4 / Messenger会話切替のKeychain確認抑止

Messengerの選択会話は認証情報から分離し、既存AES-GCMの`private_settings`にアカウント別で保存する。会話を切り替える処理からKeychainの読み書きを除いた。0.9.5までは旧選択を初回に取り込んだが、現行ソースでは自動取込みを廃止した。古い選択や他アカウントの選択は復元しない。

認証情報、端末情報、DB鍵の保管先と受信commit/ACK順序は従来どおり。OSのアクセス許可は本人が操作し、ACLを変更して確認画面を抑制する処理は追加していない。起動時に必要なOS許可と、会話切替による不要な許可要求を区別する。

## 0.9.3追加: 本人確認とログイン失効

Instagramの新しいネイティブログインhelperは、専用の非永続WKWebViewを毎回作成する。既存ブラウザ／BeeperのプロファイルやCookie DBは参照しない。本人が完了ボタンを押した時だけ、そのセッションの許可したCookieを非公開pipeへ渡す。HTTPSのInstagramドメインだけをメインフレームに許可し、任意URL引数やCookie貼り付けの入口は持たない。アダプタのLoadIndexでアカウント・Directを検証してから従来のKeychain serviceへ保存する。キャンセルや検証前の失敗は保存済みログインを保持。Cookie／例外本文をTerminal・GUI・ログ・平文ファイルへ出力しない。

LINEのwatch状態は固定状態と固定エラーコードのみ。ログイン失効時は世代を更新して受信・回収・全会話同期を停止する。遅延した旧処理の成功で失効状態を解除しない。自動ログインや他クライアントのセッション取り戻しは行わない。ログイン失効は保存履歴の削除を意味しない。

## 現行形式のみの受付（2026-10-03、開発ソース）

既存DBのschema・version・鍵を検証してから開く。旧DBのALTER・自動補完・version上書きをしない。Messenger旧本文キャッシュは保全して停止する。Slackは専用native OAuthだけを受け付け、localhost認証serverを起動しない。これらはソースの変更で、配置済み0.9.5・配布ZIPの変更ではない。[受入条件と検証](DEVELOPMENT_REVIEW_20261003.md)。
