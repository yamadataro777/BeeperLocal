# BeeperLocal Project State

最新の通常配置は **0.9.5、公証済み・Slack公開設定を同梱**（2026-10-03）。MessengerのKeychain確認反復修正も含む。詳細は末尾「0.9.5 Slack専用URL・外部配布・通常配置更新」および [配置記録](desktop-0.9.5-install.json)。開発ソースには下記の方針見直しを反映済みで、通常配置とZIPは更新していない。以下の各節は、その時点の観測記録。

## Messenger受信の本体統合候補（2026-10-02）

本人の「Messengerは別のチャットルームで実装開始して」を受け、専用Messenger接続部・本人ログイン・サービス切替・会話/本文表示・新着受信・暗号化保存/検索・再接続を本体ソースへ追加した。既存のLINE/Instagram/Slack/X差分を維持。送信・MCPは提供せず、既存provider権限も転用しない。端末登録結果不明、既存device snapshot欠落/破損、Keychain異常では停止し、自動再登録しない。

最終Core432件・GUI39件、Go8件、Swift境界検査、shell6ファイル・offline demo・production build成功。Developer IDで8実行体・87内包binary、通常アプリとの相互署名要件を検証。候補を`workstreams/messenger-integration/BeeperLocal.app`へ保存し、19ファイルのhash一致とdeep/strict署名検査を確認した。通常アプリはこのチャットでは置き換えていない。

エージェント観測: ソース版Coreと署名済み接続部で既存端末を復元し、検証時の本文2件を本体暗号化DBへ引き継いだ。CoreとGoを別プロセスで起動し直し、オフライン検索1件一致・再接続に成功。実送信0回。通常の同梱Coreを別に起動する試験は`DESKTOP_ALREADY_RUNNING`で停止したため、稼働中Coreを終了させず専用provider検証へ切り替えた。ソース版の実測を通常GUIでの確認として扱わない。

追加新着受信、通常GUIでの実データ表示、スリープ/実回線断、長時間、公証・別Macは未確認。このチャットでの新しい本人報告はない。旧PoCの受信2件と本人報告は元記録を保持する。端末snapshotの4 MiB上限、DB/Keychain間の非原子性、AGPL/商用配布条件の未解決は残る。[統合範囲](MESSENGER_INTEGRATION.md)、[保存ADR](ADR_MESSENGER_PERSISTENCE.md)、[検証結果](messenger-integration-verification.json)。


## Slackプロフィール表示（2026-10-02）

Slackの投稿者名・画像、DM一覧・見出しの名前と画像を実装した。Core384件・GUI32件成功。通常アプリ0.8.5への同梱と試験済みSlackコードとの一致を確認。実認証にはプロフィール閲覧権限users:readがまだなく、実画像取得は追加承認の反映待ち。送信0回、DM・別の相手からの返信の検証は後回しを維持。[表示と設定手順](SLACK_PROFILES.md)、[検証記録](slack-profiles-verification-20261002.json)。


Updated: 2026-10-02

## LINE画像・スタンプ（Desktop 0.8.5、2026-10-02）

画像・スタンプを取り込み時に除外していたテキスト専用処理を修正。履歴と受信へメディア種別を保持し、既存AES-GCM保存、画像取得・復号、静止画スタンプ、遅延表示、拡大、取得失敗時の再読み込みを追加した。画像本体は容量を制限したメモリ内のみで、再起動後は再取得する。

Core401件・画面35件・Go関連3package、shell構文・offline demo・production buildが成功。公開スタンプ1点のCDN取得・画像生成を確認。正式署名6実行対象・87内蔵binary、旧版との相互署名要件、配置16ファイルのhash一致を確認し、通常アプリを0.8.5へ更新した。旧0.8.4はarchive/app-backupsへ保全。

初回はLINE_LOGIN_REQUIREDで止まったが、本人のスマートフォン再連携後、通常アプリのnative GUIでLINE接続・受信待機、実画像2件・実スタンプ1件の表示と、それぞれのクリック拡大を確認した。確認後は元の会話へ戻した。実送信0回。詳細と制約は[LINE_MEDIA.md](LINE_MEDIA.md)、実接続記録は[line-media-live-20261002.json](line-media-live-20261002.json)。

## X旧形式DMの本文表示（2026-10-02、通常アプリ0.8.5に反映済み）

本人の「中身が見れない状態」の報告は、旧形式DMを一律除外していたことが原因。固定済みThrift parserで旧形式の本文を読み取る処理を追加。署名と暗号化マーカーが両方ないイベントのみ対象にし、sender/会話/account/安定ID/時刻を検査。verified=false・source=legacy・legacy: IDで区別する。署名付き/暗号化イベントは従来通り検証し、同一IDの旧形式への降格を拒否。送信成功判定にも旧形式を使用しない。保存は従来通り暗号化する。

実会話の読み取り: 更新前は保存本文0件・旧形式除外2件。修正版の署名付きCoreで本文1件・除外0件を確認し、受信待機とCore再起動後の検索1件も成功。本文・相手名・IDは出力していない。追加送信0回。native GUIの実画面はこのチャットでは未観測。

並行更新: X専用コピー（workstreams/x-integration-work/legacy-fix-0.8.5）を0.8.4基準で作成して検証中に、LINEメディア側が通常アプリを0.8.5へ更新した。現在のアプリのX本文処理が、実確認済みのものと正規化バイトコードで同一、Go parserも署名CDHashで同一と確認。現行のLINEメディアとSlackプロフィールを保全し、X専用コピーでは通常アプリを上書きしていない。現行署名は6実行体・87内包バイナリ・旧版相互要件を確認。LINE再連携画面を開いたまま保持した。

検証: 最新app/でCore410件成功。X専用コピーでCore381件・GUI29件、Go/Swift/shell6件/offline demo成功。[本文表示の記録](x-legacy-text-verification-20261002.json)、[実確認](desktop-0.8.5-x-live-initial.json)、[配置コード照合](x-legacy-installed-code-20261002.json)。

小さな追加修正: 同一メッセージが直接形式/入れ子形式の2通りで返るため、現在の通常アプリでは本文1件に対しフッターの旧形式件数が2になる場合がある。衝突検査後に重複をまとめる修正はapp/とX専用コピーへ適用・テスト済み。通常アプリへのこの追加修正の反映は次の本体ビルド待ち。次回リリースでは最新app/のLINE/Slack/IG変更を保持して組み込む。X専用候補は旧0.8.4基準であり現行版への差し替えには使用しない。

## X Chat本体統合（Desktop 0.8.4、2026-10-02）

本人の「組み込もう」「続きを実装して」に基づき、単独検証済みX Chatを本体へ統合して通常アプリを0.8.4へ更新した。1対1の署名確認済みテキスト履歴・受信・手動送信・暗号化保存・検索と、専用nativeログイン／Chatパスコード入力を追加。旧形式DMは除外件数を表示し、暗号メッセージの署名確認失敗は停止。結果不明の送信は本体の永続outboxに残して自動再送しない。XのMCPは未対応。

デスクトップへの移動後の `app/` でCore374件（skipなし）・GUI28件、offline demo、shell構文6ファイルが成功。最終production build、6実行ファイル・68内蔵binaryの正式署名、0.8.3との相互署名要件を確認。旧0.8.3を `archive/app-backups/` へ保全し、通常アプリへ配置した16ファイルのhash一致と本体・Coreの起動を確認した。

実データは署名付きの同梱Coreから、X接続・会話181件・以前に検証した会話の履歴7件・旧形式除外2件・履歴保存記録・受信待機を確認。Coreを終了して再起動し、オフラインの保存履歴から検索1件と会話scope一致を確認した。本文・相手名・IDは診断出力しない。単独版と本体は同じ暗号化adapter保存先・排他ロックを使用し、元の暗号化DBは退避保持する。

今回の新規送信は0回。本体統合後の新着受信・相手側着信・native GUIの実画面表示はこの確認には含まない（GUIは架空データで検証済み）。単独版の新着・手動送信・相手側着信の本人確認は過去証拠として維持。長時間・物理回線断・公証・別Macも未完了。[検証](desktop-0.8.4-verification.json)、[配置](desktop-0.8.4-install.json)、[対応範囲](X_INTEGRATION.md)。以下の販売計画・既存実機記録は保持する。

## 販売初版に向けた計画再設計（2026-10-01）

ユーザーが次の到達点に「販売できる最初の製品」を選択。既存の販売準備（12/1予定、買い切り9,800円・先着20人4,900円）を引き継ぎ、LINE中心の初版案について、配布条件→実AI接続→日常運用→公証・導入・購入後配布→試用→発売判定の順に再設計した。初版の対象は条件確認後に確定する。サービス追加の中ではSlackを優先候補として維持する。主担当のみで進める。

現行計画は[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)、着手順は[NEXT_IMPLEMENTATION](NEXT_IMPLEMENTATION.md)。これは文書の再設計で、販売許可・実機Gateの追加達成ではない。既存のLINE/Instagram/X/Slackの実装と証拠を保持し、別Mac検証は本人指定どおり後半。以下の「Slack優先」は接続部追加時点の方針・記録として読む。

## 1時間連続運転検証の中断（2026-10-01）

15:54:55開始、16:01:42に通常アプリ本体の不在を検出し約6分47秒で観測終了。28サンプル中、終了直前までの27件ではLINE受信プロセスが存在し、受信PID変更0・観測欠落0。最後の動作確認は16:01:27。終了理由は未特定で、手動終了・クラッシュのいずれとも断定しない。現在アプリと観測プロセスは停止、一時スリープ抑止も終了済み。自動再起動は行わず、定期確認を停止する。**1時間運転のGateは未完了**。[観測結果](desktop-0.8.3-long-run-20261001.json)。

## LINE受信の継続復旧（Desktop 0.8.3、2026-10-01）

最新の通常アプリは正式署名付き0.8.3。LINEの一時障害が続くと受信・回収タスクを終了していた原因を修正し、短い再試行後も60秒間隔で継続する。開始通知と即時EOFによる誤った待機表示も修正。認証／保存異常・明示停止時は停止し、結果不明送信は再送しない。最初の通信失敗の原因は未特定で、スリープ起因とは断定しない。

Core325件、画面25件、production build、offline demo、shell構文成功。固定ソースのビルド前テストでskipしたIG binary2件は、ビルド後に成功を補完。4実行ファイル・67内蔵binaryの署名、旧版互換性、配置hash一致を確認。実機でLINE受信子プロセスを7回連続終了し、7回目から61.03秒で自動復帰、本体PIDを維持して20秒以上の継続を観測。手動再接続・本試験からの送信は0回。45会話と受信待機、IG既存返信・停止中返信の表示と待機を確認。LINEの選択会話は履歴0件のため、この実機試験はその履歴保持を証明しない。実スリープ・物理回線断・長時間・完全同期は未完了。

この時点のSlackソースを含む固定版を配布物へ同梱した。Slackの実機試験証拠は下記の別記録を参照。[LINE修正詳細](LINE_RECEIVER_RECOVERY.md)、[検証](desktop-0.8.3-verification.json)、[実機](desktop-0.8.3-line-live.json)、[配置](desktop-0.8.3-install.json)。

## Slack優先の追加実装（最新の作業差分）

ユーザー方針: LINE・Instagram・Xを既存実装として保護し、Slack優先・Discord次候補。iMessage/WhatsAppは対象外。主担当のみで実行。

既存Slack User OAuth・取得・暗号化保存・検索経路を維持し、本人テキスト送信、明示スレッド取得、約65秒ごとの選択1会話・直近15件の回収、GUI、Slack専用MCP権限を追加。実チャンネル1会話で、修正後の本人送信・成功応答・履歴取得・暗号化保存・DB再オープン検索・重複送信抑止を確認。本人がSlack側で投稿した新着1件の自動取得と再オープン検索も成功。Core321件成功。別の相手からの受信、DM・非公開チャンネル・スレッド返信等は未確認。MCP実データ用grantは発行していない。公式配布条件は調査済みだが、Marketplace審査・商品用途適合は未確認。通常BeeperLocal.appは今回置換していない。

分類表・正確な範囲・残制約は[SLACK_IMPLEMENTATION.md](SLACK_IMPLEMENTATION.md)、試験結果は[SLACK_VERIFICATION.json](SLACK_VERIFICATION.json)。以下の既存成功証拠は維持する。

最新改善: DM・別の相手からの返信の実機検証はユーザー指示で後回し。定期取得が入退室通知等を除外した件数を埋めるために古い履歴へ進む不具合を、選択1会話・直近1ページの専用取得で修正した。記号`&`/`<`/`>`を含む文が履歴更新で変わり検索できなくなる不具合も、送受信の文字変換をそろえて修正。新規回帰6件を含む全331件成功（Slack67件、別途追加されたLINE再接続10件を含む）、shell構文6ファイル・offline demo成功。この改善での実Slackアクセス・追加送信は行わず、通常アプリの置換も未実施。以下はそれ以前の実機成功記録。

同日追記: 「同時1ワークスペース」は単一のSlack Keychain枠・provider単位のCore・単一account_idによる現実装上の制約と確認。関連5試験成功。User chat:write追加と再認可後の初回送信では、本人IDに付いたアプリ帰属情報bot_id/app_idを旧判定が拒否した。履歴で投稿1件を確認し、元outboxはunknownを保持して再送拒否を検証。Slack Connectorの修正と再現試験2件を追加し、Core全321件成功。続く「検証しよう」の承認に基づく別のテスト1回で、修正後の実成功応答・保存・再オープン検索・重複抑止まで成功した。本作業の送信POSTは計2回で、初回の再送なし。本人のSlack側新着投稿も65秒間隔の自動取得1回目で検出し保存・再オープン検索に成功。別の相手からの返信確認ではない。Bot経路への変更なし。


このファイルは長いチャット履歴への依存を減らすための継続用source of truth。

直前安定化版（履歴）: Desktop 0.8.2を通常アプリへ配置。Instagram watchの一時的終了に上限付き再接続（1/2/4/8/16/30秒）を追加し、最新20件の回収・重複upsertを経て再開する。認証／保存／protocol異常は停止し、結果不明の送信を再試行しない。復旧時に接続エラー表示が残る問題も修正。Core 287 / UI 21、production build、offline demo、shell構文成功。同じDeveloper IDによる4実行ファイル・67内蔵binary、旧版との相互署名要件、配置hashを検証。実機のIGとLINEの受信子プロセスをそれぞれ1回終了し、いずれも本体再起動・手動再接続なしに復帰。LINEは45会話・履歴・待機、IGは返信履歴を維持。[検証記録](desktop-0.8.2-verification.json)、[配置](desktop-0.8.2-install.json)、[接続復帰](desktop-0.8.2-stability-live.json)。

Instagram実往復: 0.8.1で本人が宛先・本文を承認した送信を1回だけ実行。provider受付・送信文表示・draft消去・待機を確認し、本人が相手側着信と指定返信を報告。その返信をアプリで表示し、明示再起動後のローカル検索1件も確認した。最初の返信観測前にアプリの起動し直しがあったため、0.8.2で新たな返信を追加確認した。本体・受信adapterのPIDが変わらず、手動更新なしで新着返信1件を表示し、明示再起動後のローカル検索1件まで成功。**Instagram統合の実往復GateはCLOSED**。[往復全体の記録](instagram-integrated-roundtrip-20261001.json)。さらにアプリ終了中の返信を本人が送信し、終了したままを確認してから再起動、自動回収・表示1件・ローカル検索1件を確認。これは直近20件以内の単発試験であり、大量受信の取りこぼし保証ではない。実スリープ・回線断・長時間、完全なcursor/ack同期は未確認／未実装。

正式署名の初回導入（履歴）: Desktop 0.8.1。Developer ID署名・既存Keychain項目を維持する更新・署名検証を完了。通常アプリへ配置しLINE/Instagramの接続を確認。詳細は[keychain-signing-20261001-verification.json](keychain-signing-20261001-verification.json)。公証と別Macの検証は未実施。

統合初版（履歴）: Desktop 0.8.0を通常の`../BeeperLocal.app`へ配置し、LINEとInstagramを同じアプリに統合した。0.7.0のLINE QR連携・会話順・相手名・プロフィール画像・MCPを維持。既存InstagramのKeychainと暗号化DBを引き継ぎ、移行・鍵のリセットはしていない。統合後の実アプリでLINE接続・45会話・既存履歴・プロフィール画像・受信待機、Instagram接続・1会話・履歴9件・ローカル検索1件・受信待機、両サービスの往復切り替えを確認した。過去の8件に加え、履歴回収で9件を表示したもので、今回の新着realtime受信成功とは扱わない。実送信0回。Instagram統合のCore 265件・UI 19件、並行して加わったキーチェーン／署名改善を含めたCore 280件、Instagram adapter 8件と送信5ケースに成功。最終appは4実行ファイル・内部runtime 67個の署名を検証し、配置前後のhash一致を確認。旧0.7.0をapp-backupsへ保全。[0.8.0検証記録](desktop-0.8.0-verification.json)、[配置記録](desktop-0.8.0-install.json)。

直前（0.7.0）: Desktop 0.7.0を配置し、アプリ内QR連携、LINE側の最終更新順の会話一覧、友だち以外も含む相手名、プロフィール画像を実装。Core 230件・UI 15件・同梱CLIのrace回帰テストと独立QR復号に成功。署名と配布物hashを確認。既存LINEセッションの無効化を検出して実QR連携画面を開いた。再連携後、同梱Coreで現在の46会話すべての更新時刻・名前・画像情報、新しい順の並び、画像3件中3件の読み込みを確認。旧キャッシュを現在の一覧へ混ぜず、保存済み履歴は保持する。0.7.0時点ではInstagramは未統合だった。[0.7.0検証記録](desktop-0.7.0-verification.json)。

直前: Desktop 0.6.0を普段開くBeeperLocal.appへ配置し、署名・同一hash・同梱runtime・実起動を確認した。LINEの上限付き再接続、認証・会話別権限付きMCP、永続保存停止・確認付きaccount限定削除を実装。Core 219件とUI 11件PASS。MCPは独立公式SDKから実HTTPで4 toolsをfixture検証。実機ではLINE接続・会話500件の取得・保存履歴検索とGUI受信待機を確認。MCPは無効・client未登録のまま、今回の追加実送信・実データ削除・外部AI設定は行っていない。完全なcursor/ack同期・全履歴・長時間実運転は残る。詳細は[0.6.0検証記録](desktop-0.6.0-verification.json)と[ローカルMCP契約](ADR_LOCAL_MCP.md)。

前回（0.5.1）: Mac再起動後、Desktop 0.5.1でLINE接続・会話一覧500件・実履歴表示・ローカル検索・受信待機を確認。ユーザーが宛先と本文を明示承認したテスト送信を1回行い、LINEの受付成功と送信文表示を確認。さらにアプリ再起動後の再接続・テスト文の復元・検索1件を確認した。相手側の実着信はユーザー報告で確認済み。その後ユーザーが返信受信と順番が正常と確認し、アプリの基本送受信はCLOSED_BY_USER_REPORT。再起動検索は送信テスト文で実測済みで、特定の返信について同じ確認を行ったという意味ではない。直近の既存テスト記録はCore 198件、fixture UI 8件PASS。詳細は末尾と[DESKTOP_APP.md](DESKTOP_APP.md)。

## 2026-10-01: スリープ復帰確認の途中経過

本人が手動スリープから復帰したと報告。本体は試験前と同じプロセスで動作し、Instagramの受信待機と既存返信の表示を確認。復帰後の新着返信を依頼中。電源ログには試験区間のsleep/wake記録を確認できず、スリープ自体の根拠は本人報告と区別する。LINEは受信の再試行上限に達して停止していた。試験前にもLINE子プロセスは不在だったため、今回のスリープが原因とは断定しない。画面の再接続を1回実行後、45会話・履歴・受信待機へ復帰した。**両サービスのスリープ後自動復帰が完了したとは扱わない。** [確認記録](desktop-0.8.2-sleep-live.json)。

## Live evidence obtained on the user's Mac

### Runtime / Keychain
- Python 3.14.7 / macOS Darwin 25.5.0 / arm64.
- Telethon 1.45.0 imported and offline constructor check passed.
- keyring 25.7.0 installed.
- macOS Keychain write/read/delete probe passed.

### Matrix
- GitHub SSO account was connected via manually copied Matrix Access Token.
- Login verification and Keychain save succeeded.
- Joined-room listing succeeded.
- `Matrix.org (Official Account)` selected.
- `fetch matrix` returned 1 live message.

### Slack
- User OAuth based Slack connection succeeded.
- Conversation listing succeeded.
- `test-channel` selected.
- `fetch slack` returned 1 live message.

### Cross-provider proof
User ran:

```text
./run.sh proof --limit 1
```

Result contained one Slack live message and one Matrix live message in the same chronological merged timeline. The old v0.2 binary printed OPEN only because it still used a 50-message threshold.

Decision: **Gate A / Connectivity + Integration = CLOSED.**

Gate B / 50-message-per-provider volume & pagination = OPEN and intentionally non-blocking for Phase 1.

## Current implementation

`0.4.0-poc` adds:
- encrypted local SQLite persistence;
- AES-256-GCM message payload encryption;
- random local DB key in macOS Keychain;
- local sync/upsert;
- local substring search with in-memory decryption;
- no plaintext FTS;
- local DB reset and status commands.

## Current next action on the user's Mac

以下はPhase-1当時の手順。9/30のユーザー報告で実行済み。現在の次工程は末尾のL1と`docs/NEXT_IMPLEMENTATION.md`を参照。

```bash
bash scripts/setup.sh
./run.sh doctor --check-keychain
./run.sh sync --limit 1
./run.sh db-status
./run.sh search --preview
```

No need to re-login Matrix/Slack or re-select conversations if the existing Keychain entries remain under `BeeperLocalPoC.v1`.

## Next engineering loop after live Phase-1 validation

1. Incremental sync state/cursors and idempotent repeat sync.
2. Edit/delete reconciliation semantics.
3. Tauri 2 + React/TypeScript UI reading only the local common model via narrow IPC.
4. Send path as an independent, explicit-confirmation safety gate.

## 2026-09-30: LINE Core integration

ユーザー提供の実機証拠では、Phase-1 Matrix/Slack保存・検索も成功済み。line-cli v0.4.0単体のencrypted送信・実配送・realtime受信の成立性は検証済みで再調査しない。

追加: Mac-native LINE connector、raw MID選択、Core send/watch、既存暗号化DB保存、LINE providerのsync/search。Matrix/Slack connector・暗号化storage・run.shは変更なし。

LINE Core 1往復: **CLOSED / ユーザーの全手順成功報告に基づく**。エージェントが7条件を個別に再観測したという意味ではない。fixtureの成功をlive成功に置き換えない。手順と限界は`docs/LINE_CLOSED_LOOP.md`。

ローカル検証: 既存126件 + LINE追加22件 = 148件PASS（skipなし）。`python -B -m unittest discover -v`、shell構文確認、offline demo成功。実行ログは`docs/line-test-run.txt`。fixtureを使ったCore送信→受信→暗号化保存→再open→既存searchもPASS。

### 初回反映時点の実機確認（履歴、2026-09-30）

- Downloads内の既存PoC本体へ差分を反映済み。事前のsource hashを照合し、変更前のsourceのみを作業領域へバックアップ。
- `./run.sh db-status`: `local_db=OK | total=3`、matrix=1、slack=2。指定の既存messages-v1.sqlite3をCoreとKeychain鍵でopen成功。
- `./run.sh login line`: 既存line-cliセッションのwhoamiをCore経由で確認し、BeeperLocal Keychainへのaccount登録成功。認証情報やMIDを出力していない。
- 相手のMIDは未選択。今回のCore経由の実送信は0回。別アカウントの受信確認・返信・realtime実保存・今回の返信検索は未実施。
- 次: `select line` → `watch line --from-now --timeout 600` → 別Terminalで`send line` → 別アカウントの受信確認・返信 → `db-status` / `search --provider line`。全条件成立まではOPEN。

## 通常利用へのLINE統合（2026-09-30）

ユーザーは手動手順が「すべて上手く行った」と報告。これを根拠に当初のClosed LoopをCLOSEDと記録した。今回の反映前にエージェントが独立確認したDB件数はline=1 / matrix=1 / slack=2、合計4件（本文・MIDは表示していない）。件数だけを7条件の再検証とは扱わない。

実装:
- 既存ConversationをStoredConversation（provider/accountでscope）として暗号化DBへ永続化。
- raw MIDはconversation.idのまま。表示名変更でidentityは変わらない。
- v1 messagesのスキーマ・ciphertextを維持し、暗号化conversationsテーブルを追加。sync時の会話とmessageは同一transaction。
- `select line`を相手一覧の番号選択へ変更。`conversations`はローカル一覧、`--refresh`でproviderから更新。`messages line`は選択会話のローカル履歴。
- 通常`send line`と`daemon line`（watchの別名、既定無期限）で送受信。
- 既存line-cliセッションから初回metadataを自動復元。BeeperLocal専用loginを毎回行う必要なし。
- LINEの再接続、保存済みcursor再開、token refreshはline-cli既存実装を利用。強制ログアウト、resync_required、復号不可は固定エラーとして停止。
- Matrix/Slack/LINEを共通registryとConnector interfaceで生成。send/watchはoptional capabilityとして明示。Matrix/Slackに未実装の送信・realtimeを実装済みとは扱わない。
- `line-e2e`は1回のsend、今回の識別文に一致するrealtime返信、SQLite再open検索だけ。専用Keychain状態、resume、一般化したテスト基盤は追加しない。

検証: 155 tests PASS（追加7件）、shell構文・offline demo・CLI help/capabilities確認。詳細は`docs/line-core-test-run.txt`。

制約: 1対1textのみ。Group/media等は未実装。SQLite commitとline-cli cursorは原子的でないので、停止時の保存漏れは`sync line`で回収。強制token失効や長時間運転を今回改めて誘発してはいない。

### 今回の通常利用経路の実機結果

- `conversations line --refresh`: CoreからLINE会話500件（今回の取得上限）を取得し、暗号化catalogへ保存成功。
- 別プロセスで500件を復号・再取得。全件のcanonical IDがraw LINE MID形式であること、およびそれらのMIDがDBファイルに平文で存在しないことを確認（出力はbool/countのみ）。
- message件数はline=1 / matrix=1 / slack=2で反映前と同じ。
- `daemon line --timeout 5`: 既存セッションで起動・5秒で停止。incoming_unique=0。有限watchは受信0件でexit 1を返す仕様であり、この起動確認を新規の実配送・token refresh実測の証拠にはしていない。
- 新しいsend / line-e2eでの実送信は今回追加実行していない。ユーザーの手動Closed Loop成功報告と、今回のコード・catalog動作確認を分けて記録する。

通常利用の入口: `select line`（必要時だけ）→ `daemon line` + 別Terminalで`send line`。ローカル確認は`conversations line` / `messages line` / `search --provider line`。

## 実装計画・UI設計とL1着手（2026-09-30）

ユーザー指定の実装順をLINE → Instagram → 𝕏に固定した。`IMPLEMENTATION_PLAN.md`に日程案とMermaidタイムライン、`UI_DESIGN.md`に画面構成・状態・送信・検索・IPC・受入条件を記録。

LINEの新差分:
- 通常`daemon line` / `watch line`開始前に直近50件を回収。`--recovery-limit`で1〜100件を指定可能。
- message・conversation・暗号化sync receiptを同一transactionで保存。取得不完全または保存失敗時はwatchを開始しない。
- `sync line`も同じ保存経路を使い、正常に取得できた空履歴も回収結果として記録する。実受信0件は1往復成功と扱わない。
- `sync-status line`で選択会話の前回回収結果をローカル確認。本文・raw IDは出力しない。
- `--from-now`は履歴回収を明示的に省略。送信・認証・line-e2eの仕様は変更しない。

これはbounded recoveryの実装であり、L1全体のCLOSEDではない。line-cliのcursorとCore commitの原子性、100件より古い欠落の回収、削除反映は未解決。新しい経路でのlive再開確認は未実施。今回の変更はこの作業領域に保存し、Downloads内の旧実行コピーへはまだ反映していない。

IGの関連タスク「LINE接続検証継続」では9/30、ユーザーが履歴3件・identity/timestamp各3件の成功結果を報告した。その後、新着DM送信で反応がないと報告している。これを履歴取得の証拠として引き継ぐが、realtime受信・送信・Core統合の成功とは扱わない。𝕏の実機証拠は未確認。

今回の検証: 既存155 + 新規16 = **171 tests PASS、skipなし**。既存Downloads版のPython 3.14.7 venvを実行環境として使い、cwdはこの作業コピーにして`python -B -m unittest discover -v`を実行。run.sh / setup.sh / python-select.shのshell構文、offline demo、daemon/sync-statusのhelpも成功。ログは`docs/line-recovery-test-run.txt`。fixtureの再取得・再open・保存失敗・改ざん・scope分離を確認したもので、実LINE通信の証拠ではない。

## Macデスクトップアプリ（2026-09-30）

ユーザーの追加依頼「実際に開くアプリケーションになるところまで実装して。Lineと接続・連携ができる状態まで」を受け、L2を前倒し。完全なcursor/ack同期は未完了のまま、bounded recoveryの範囲を明示した初期GUIを作成した。

- Tauri 2 + React/TypeScript、macOS `.app`、アプリアイコン、Pythonとline-cliを同梱。実行時にTerminalやPythonの手動起動は不要。
- 既存Keychainと暗号化DBをそのまま利用。LINE会話一覧、履歴、選択会話の受信、text送信、保存済み検索、設定・再接続を実装。
- Rust/Pythonの両方でrequestをallowlistに限定し、private pipeだけで通信する。
- 送信前に暗号化ledgerを永続化。同一requestの再実行・再起動時の自動再送を抑止。結果不明の送信はUIで通知する。
- 会話一覧500件・履歴100件まで、選択中の1会話だけをwatch。60秒ごとの回収は完全な全履歴同期ではない。
- Instagramと𝕏は準備中。Matrix/Slackの既存CLIと保存・検索経路は維持。

配布物: 作業領域直下の`BeeperLocal.app`。ソースのビルド出力は`desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app`。ユーザーが明示的にアプリ起動を許可し、ビルド出力・最終配置の両方から起動した。macOSで実ウィンドウの表示とKeychainエラーからの再接続操作を確認済み。最終配置に起動先を統一済み。

最終配布物確認で、内部実行ファイルは署名検証に通るがapp全体にresource sealがないことを検出。ビルドスクリプトへad-hoc署名と検証を追加し、配布物も修正。元bundleと配置後のappの両方が`codesign --verify --deep --strict`に成功した。これはDeveloper ID署名・公証ではなく、Keychain問題の原因を確定する証拠でもない。production JSにfixtureデータが含まれないことも確認した。

ローカル検証: **187 Python tests PASS / skipなし**（既存171 + Desktop 16）、shell構文、offline demo、TypeScriptチェックとVite build、Rust release build成功。Playwright/Chromeの**6 tests PASS**は架空データのみで、改行・1回送信、会話別下書き、検索移動、結果不明時の保持、オフライン、狭い画面を確認。ログは`desktop-test-run.txt`、`desktop-tauri-build-run.txt`。`desktop-ui-fixture.png`は架空データの画面。

今回のlive確認: 配布物Coreの`ping`成功。その後の`snapshot`は`KEYCHAIN_UNAVAILABLE`（Keychain APIの固定数値は-25293）。GUI起動後も同じ固定エラーを表示。LINEネットワーク接続・実一覧・履歴・検索・受信は今回の新アプリ経路では未確認。実送信0回。過去のCLI 1往復成功のユーザー証拠を、新アプリの成功証拠へ転用しない。

ユーザーはKeychain確認画面が出るが許可できず、「許可」を押しても通らない・繰り返すと回答。Appleの公式説明を参照し、1回限りの許可と常に許可の違いを案内した。画面が保護対象なのでエージェントは操作できない。Keychainの迂回、エージェントによるACL変更、平文fallback、DBや鍵のリセットはしていない。次は本人のKeychain許可→アプリの再接続→実データの読み取り確認。実送信はユーザー指定の宛先・本文が必要。

## Desktop 0.5.1の配置と再接続確認（2026-09-30）

ユーザーの「1からやろう」を受け、既存の0.5.1ビルドを普段開く作業領域直下の`BeeperLocal.app`へ反映した。旧0.5.0は`../app-backups/BeeperLocal-0.5.0-20260930-165612.app.backup`へ退避。元ビルド・配置前コピー・配置後appの署名検証が成功し、desktop/Core/lineの3実行ファイルのSHA-256一致と配置後version 0.5.1を確認した。

- 旧アプリを通常終了し、配置後のパスから修正版を起動。Macの実ウィンドウを確認。
- 初期読み込みと「LINEに接続する」の明示操作で、Macのキーチェーン自体の認証エラーと再起動案内を表示。画面上の会話件数は0件で、DBが空になったという意味ではない。
- 直近の既存ログはCore 198件・UI 8件成功。今回はアプリ配置と実画面の確認であり、テストを新たに再実行したものではない。
- 修正版からの実LINE一覧・履歴・検索・受信は未確認。実送信0回。OS認証の復旧成功とは扱わない。
- Keychain/DBの削除・リセット、ACL変更、平文fallbackは行っていない。

次はユーザーが作業を保存してMacを再起動し、本人ログイン後に作業領域直下のアプリから再接続すること。実データ表示・保存済み検索・受信を確認し、その後、本人指定の宛先と本文で送受信を確認する。再起動で必ず復旧することを保証するものではない。検証記録は`desktop-0.5.1-verification.json`。

## Mac再起動後のDesktop live確認（2026-09-30）

ユーザーのMac再起動報告を受け、配置済み0.5.1の実UIを確認した。

- LINE接続済みと会話500件を表示。最初に会話選択時のKeychain保存エラーが残っていたが、再接続後に既存のテスト会話の実履歴を表示し、受信待機へ復帰した。
- 既存テスト文をローカル検索し1件一致。検索結果からテスト会話を開き直した際はKeychain保存エラーが再発せず、履歴更新と受信待機が成功した。他の全会話での選択成功を保証するものではない。
- ユーザーが現在のテスト会話・指定文の1回送信を明示承認。アプリの送信ボタンを1回操作し「LINEが送信を受け付けました」、指定文の履歴表示、入力欄のクリアを確認。追加送信・自動再送は行っていない。
- アプリを通常終了して同じ配置先から再起動。再接続・受信待機・送信テスト文の復元を確認し、同文のローカル検索で1件一致した。
- ユーザーが「届いたが、返信はまだ」と報告。相手側着信はこの報告を根拠に確認済み。今回の返信表示は未確認で、アプリ1往復GateはOPENのまま。
- Keychain/DBのリセット・削除、権限設定の緩和は行っていない。実データ本文・相手名・IDを検証ファイルへ保存せず、件数・固定状態・boolのみ記録した。

追記: ユーザーは返信がBeeperLocalに届くと報告し、その後「順番大丈夫だったし、ちゃんと届いてる」と訂正・確認した。直前の欠落・重複・遅延の懸念は取り消し、これを根拠に不具合として扱わない。相手側の着信と返信受信をユーザー報告として記録し、アプリの基本送受信確認をCLOSED_BY_USER_REPORTとする。再起動・検索は送信テスト文で独立に確認済みで、特定の返信を再起動後検索した証拠ではない。長時間運転・停止中の大量受信・全履歴同期は引き続き別工程。

証拠: `desktop-0.5.1-post-reboot-verification.json`。①のアプリ更新・接続復旧・基本送受信確認は完了。次はLINEの同期・再接続の安定化とローカルMCP実装。今回の訂正を受けてアプリのコード変更や追加送信は行っていない。

## Desktop 0.6.0 — 再接続と権限付きローカルMCP

2026-09-30、ユーザーが次の作業「2」を選択したため実装。主担当だけで完結し、サブエージェントは使用していない。

- watchの一時切断/EOFで上限付き再接続。再接続前・開始後と約60秒ごとの直近100件回収。致命的な認証・復号・保存エラーは停止。
- 公式MCP SDKの認証付きloopback HTTP。list/get/search/send、account/会話/read/send scope、token一度表示、hash暗号化、失効と外部送信直前の再検証。
- 共通送信ledgerを使用し、GUI選択を変えない宛先固定送信と再起動後の二重送信抑止。
- 保存停止を永続化。対象件数を確認した現在LINE accountだけの削除、権限のtransaction内失効。他account/provider/session/key保持。
- 219 Core tests（198既存+21追加）、11 UI tests（8既存+3追加）。HTTPは架空adapter+一時DBだが実TCP socket。全体ログと5 HTTPテストの最終追試を保存。
- 配置した同梱CoreでLINEの会話500件・選択会話の保存履歴1件・ローカル検索を確認。短時間smokeはwatch起動前に停止したため、そのflagはfalse。続けた実GUI確認で受信待機・新設定UI・0.6.0表示を確認。
- 実GUIでMCP停止・登録clientなし・送信初期OFF・保存管理を確認。新規の実メッセージ送信、実データ削除、実データを許可したMCP登録はなし。
- 旧0.5.1アプリは`app-backups/BeeperLocal-0.5.1-before-0.6.0-20260930-175928.app`として保持。source backupも保持。DB/Keychainのリセットなし。

全履歴、削除/unsend、commitとline-cli cursorの原子性、長時間/スリープ/強制ログアウトはこの結果で完了とはしない。この時点では一般配布署名・公証、通信全経路capture、依存hash-lock、第三者監査は未実施。

## 2026-10-01: キーチェーン更新と署名工程

ユーザーは署名・アクセス権整備を指示し、別Mac検証は後回しと指定。Apple Developer Programには加入済みだが、このMacへの証明書設定は未実施。有効なcodesigning identityが0件であることを確認。

BeeperLocalのKeychain backendを、削除再作成するkeyring方式から、既存項目の値のみをSecItemUpdateするnative実装へ変更。既存service/account/DB鍵/保存形式を維持し、アクセス許可を広げない。旧新backendが作成した一時項目について、更新前後のpersistent reference一致・互換読み出し・削除をこのMacで確認。本番項目はこのprobeで触っていない。

`build-desktop.sh --release`に証明書必須チェック、Core/LINE/Instagram helperの固定Identifier、内蔵Python/native libraryを含むDeveloper ID署名と最終検証を追加。開発buildで4実行対象＋67内蔵Mach-Oの署名検証成功。その後ユーザーがXcodeにサインインし、Developer ID Application証明書を設定。0.8.1の全4実行対象・内蔵67 Mach-Oへ正式署名を適用・検証し、普段のBeeperLocal.appへ配置した。異なるcode hashの署名済みテストプログラム2本で署名要件が相互に成立し、確認UIを禁止したKeychain操作6回が成功。本番アプリでLINE 45会話の接続・受信待機、Instagramの接続・受信待機を確認。移行時の本番確認画面の回数は測定していない。281件の回帰テスト成功。Apple公証・別Macでの受入確認は未実施。詳細は[KEYCHAIN_SIGNING.md](KEYCHAIN_SIGNING.md)。


## 2026-10-02: Messenger / Discord の独立検証

本人の依頼でMessengerを先に、Discordを続いて検証。通常アプリのコード・配置・既存providerのDB/Keychainは変更していない。

Messengerは `workstreams/messenger-verification/` に独立した受信専用PoCを作成。専用の非永続WebKit画面で本人ログインし、エージェントが受信箱認証、E2EE端末登録、暗号化接続、テキスト計2件のKeychain保存を観測。先に保存した1件は保存ACK後の子プロセス停止を挟み、別プロセスで同じ端末鍵と本文を復元、メモリ検索1件一致・再接続を確認した。ユーザーも普段のMessengerでテスト文の受信を報告。送信0回。セッション・端末状態・最大200件の検証メッセージは専用Keychain項目に置き、SQLiteはメモリ内だけ。これは本体統合や製品用の永続化方式を承認した記録ではない。

追加Python4件・Go5件とSwift境界検査成功、2helperのDeveloper ID署名検証成功。本体回帰401件のうち395件が成功し、sandboxでlocalhost待受を拒否された6件は権限下の再実行ですべて成功。shell構文6ファイルとoffline demo成功。古い暗号化履歴・送信・本体/MCP統合・長時間/スリープ等・商用配布条件は未確認。

DiscordはMac ARM64のC++20実測を通過。ユーザー報告で開発者アプリは未作成。公式Social SDKの取得・認可・実DM接続は未実施。公式文書にあるゲーム利用者向けの履歴条件と、非ゲームの個人DM統合・保存・MCP用途の適用確認が次の条件。`workstreams/discord-verification/` に根拠・準備手順・未送信の問い合わせ草案を保存。Botや抽出した個人tokenによる代替接続は行っていない。

証拠: `../../workstreams/messenger-verification/verification-summary.json`、`../../workstreams/discord-verification/verification.json`。


## 2026-10-02: 別Mac向けInstagram接続ファイルの修正（配布セット0.8.6）

- ユーザー報告: 別MacでInstagram接続.commandを開いた直後に失敗。対象はM1・macOS 27とのこと。エラー全文と対象Macでの画面は未観測。
- ローカル確認: 旧補助ファイルは開発フォルダの `.desktop-venv/bin/python` を直接実行しており、アプリだけをコピーしたMacでは動作しない構成だった。
- 修正: 署名済み同梱Coreに `--instagram-login` / `--verify-instagram-login` を追加。補助ファイルは近傍またはApplicationsのアプリを使用する。対話Terminal以外では資格情報へのアクセス前に停止。認証の保存先は従来どおりInstagram用のnative Keychain。失敗時は説明と固定エラーコードを表示してEnterを待つ。
- 配布物: `../../dist/BeeperLocal-0.8.6-AppleSilicon-IG.zip`。アプリ・実行可能な補助ファイル・日本語手順を同梱。通常配置のBeeperLocal.appはこの作業では置換していない。配布版は隔離したソースからビルドし、並行作業中の追加変更は追従していない。
- エージェント観測: Core 398件、画面32件、offline demo、shell 7ファイルが成功。ZIPを開発フォルダとは別の場所へ展開し、PATHをOS標準のみ・HOMEを空フォルダにして補助ファイルのオフライン確認とCore runtime検証が成功。非対話ログインは資格情報を読む前に拒否した。
- Developer ID署名は6実行ファイルと内包runtimeで確認し、通常アプリとの相互要件互換性も確認。全実行ファイルarm64。Apple公証は未実施。
- 別Mac上での実ログイン・macOS 27上の起動・実送受信は未確認。オフライン検証を実機ログイン成功の根拠にはしない。
- 詳細: `desktop-0.8.6-ig-portable-verification.json`。

## 2026-10-02: ベータ提供に向けた点検・改善（Desktop 0.8.7候補）

ユーザーの「改善点を発見して実装」という依頼に対し、主担当1名で既存の未コミット変更を維持して実装した。対象と残件は[BETA_READINESS.md](BETA_READINESS.md)。

- 実装: LINE専用IPCと画面のprovider指定の不整合、Instagram/Slackの長引く通信障害からの復帰、結果不明送信の手動再送確認、Core終了時の表示、検索失敗時の古い結果、最新一覧から外れた保存済み会話の検索・表示、保存停止時の案内、最小幅のエラー表示、初回ログインの同梱導線、MCPトークン表示の取りこぼし、アプリ内ガイドと本文を含まない診断、Nodeのビルド前検査を改善。
- Instagram/Slackのログインは、設定ボタンが対象サービスの受信を止めて、アプリ内の固定された接続ファイルをTerminalで開く。秘密をWebViewへ渡さず、CLI引数・環境変数へも格納しない。Slackは引き続き承認済みUser OAuthトークンの本人入力が必要。
- 自動検証: **Python 440件・Playwright 49件・Rust IPC 3件が成功**。最初にサンドボックスで拒否されたローカルHTTP 6件も、許可された実行環境で通過。shell構文・offline demo・TypeScript/Vite build・Rust release buildも成功。受信障害・初回利用の試験は架空データ。
- エージェント観測: 架空データのガイド表示をブラウザで目視し、640×500でも説明と閉じるボタンが表示されることを確認。
- Developer ID署名: **8実行対象・内蔵87 Mach-O**を検証。通常アプリ0.8.5との署名要件の相互互換性を確認。全実行対象arm64。
- 空のHOME・OS標準PATH・開発フォルダ外のcwdで、同梱Coreのruntime/MCP/X crypto、InstagramとSlackログインのオフラインprobe、2つの同梱接続ファイルを確認。非対話ログインはKeychain項目アクセス前に拒否。
- 配布候補: `../../dist/BeeperLocal-0.8.7-AppleSilicon-beta.zip`。アプリ、日本語の初回案内、改善点・残件、検証結果、対応ソースを同梱。**通常配置のBeeperLocal.appは置換していない**。
- 最終ZIPを別フォルダへ展開して署名を再検証し、全8実行ファイルのハッシュがビルド成果物と一致した。展開後のログイン用2ファイルもOS標準PATHでオフライン検証成功。対応ソース756ファイルにはGoの埋込素材23件も含む。ZIPのSHA-256は検証JSONへ保存した。
- 実送信0回。本番データ削除・Keychainのリセット・権限緩和なし。Apple公証、別Mac/別アカウントの初回ログインと実往復、物理スリープ・実回線断・長時間運転は未確認。自動試験の成功だけで「友人に配布済み・受入完了」とはしない。

証拠: [desktop-0.8.7-beta-verification.json](desktop-0.8.7-beta-verification.json)。利用案内: [BETA_GUIDE.md](BETA_GUIDE.md)。

## 2026-10-03: OAuth・全会話取得・送信・更新の拡張（Desktop 0.9.0候補）

ユーザーの追加依頼に基づき主担当だけで実装した。通常配置アプリ0.8.5は置換していない。今回の新機能の実機往復は確認しておらず、従来版の実機記録とは分ける。

- Slackの公開クライアント向けブラウザPKCE OAuthと、Keychainでのトークン更新を追加した。Client Secretは配布しない。公開Client IDとSlackアプリ側のPKCE・redirect・配布設定は未構成で、一般ユーザーの初回OAuth接続はまだ使える状態ではない。
- 接続したサービスで取得済みの会話一覧を継続巡回し、ローカル未読集計・サービス別合計・本人選択後の通知を追加した。選択・送信先をバックグラウンド取得で変更しない。通知はサービス名のみ。元サービスとの既読同期は行わない。
- 保存済み履歴を100件ずつ追加表示し、Instagram・Slack・Xの過去ページをカーソルから再開する。Slackの発見済みスレッドも巡回する。最後に、過去取得を開始しても表示中の古いページと添付を保持する修正を行った。
- Messengerの既存E2EE端末・同じ接続を使う1対1テキスト送信と、送信前の暗号化outbox保存・不明結果の再送抑止を追加した。実送信は0回。グループ・添付送信は未対応。
- X/Instagramの参加済みグループと、受信画像・動画・音声の表示を追加した。1添付4 MiBまで。Xの暗号化添付は署名済み鍵とストリーム認証を確認する。新規グループ作成・添付送信は対象外。
- 全5サービスの確認付きローカル削除を追加した。X内部の保存本文とMessengerの旧受信キャッシュも対象にし、ログイン・端末鍵は保持する。削除同期はInstagramの接続中イベント、Xの署名済み削除、Messengerの認証済み送信者取消、Slack APIの明示的な削除情報の範囲。
- 起動時・6時間ごとの更新確認と、署名済みversion・更新アーカイブを確認後に本人操作で適用する機能を追加した。下書き・接続や送信等の操作中は適用を止める。更新配布URL・公開鍵は未設定で、秘密鍵の新規作成・公開・実適用は行っていない。
- **Python全470件・Playwright全56件・Rust 4件・Instagram/Messenger/XのGo検証が成功**。履歴UIの最後の変更後に対象7件を再実行し成功。shell構文6ファイル、offline demo、production buildを確認した。
- 最終候補で**8実行対象・内蔵87 Mach-OのDeveloper ID署名**と通常アプリ0.8.5との相互署名要件を確認。全実行対象arm64。最終フロントエンド変更を再ビルドして再署名済み。
- 空HOME・OS標準PATH・開発フォルダ外で同梱runtime/MCP/X crypto、Instagram/Slackの接続用オフライン確認、非接続のprivate pipe pingを確認した。最初のsandboxのセマフォ拒否と、検証側のsymlink HOME・NDJSON全体読みの不備は切り分けた。初回の補助スクリプト確認1回の失敗と、その後の再確認成功も検証JSONへ記録した。
- 配布候補は`../../dist/BeeperLocal-0.9.0-AppleSilicon-beta.zip`（63,068,920 bytes）。日本語ガイド・範囲説明・検証記録・対応ソース783ファイルを同梱した。別フォルダへZIPを展開し、署名・全8実行ファイルの一致・ソース全件一致・Go埋込素材23件・OS標準PATHでの接続用2スクリプトとruntimeを確認した。空白を含む配置パスでも確認した。

残件: LINEの直近範囲以前の全履歴と取消同期、Messengerの暗号化バックアップ復元、全サービスの完全な削除・編集同期は未実装。公開OAuthと更新の構成、今回追加した経路の実プロバイダー往復、長時間・多数会話・スリープ復帰、別Mac、Apple公証、実アップデートの受入は未確認。本番データ削除・資格情報の移行・ACL緩和・通常アプリ置換は行っていない。

範囲・公開設定: [INBOX_0_9.md](INBOX_0_9.md)。ビルド検証: [desktop-0.9.0-verification.json](desktop-0.9.0-verification.json)。ZIP検証・SHA-256: [desktop-0.9.0-package-verification.json](desktop-0.9.0-package-verification.json)。


## 2026-10-03: 0.9.1候補 — Instagram・X・MessengerのMCPとUI/UX分析

- 依頼に基づきInstagram・X・MessengerへMCP接続を追加。初期無効、サービス別のURL・設定・暗号化grant、会話単位のread/send、send初期OFFを維持。5サービスの設定を「サービス接続／MCP接続／保存管理」へ統一。詳細: [MCP_0_9_1.md](MCP_0_9_1.md)。
- 明示的な対象へ送るconnector処理を追加し、GUI会話選択は維持。既存outboxへ先に保存し、同一UUIDの重複を抑止、結果不明は再送しない。IG/Xの子プロセス起動後、IG session ACK前、Messenger write lock内でも権限を再確認する。
- 保存済みMCP履歴をbefore/olderCursorでページ取得。新規provider設定へは旧storagePausedのみ引き継ぎ、旧LINE MCP設定・grantは流用しない。
- エージェントが観測: Core480件、Playwright59件、Rust4件、production build、shell6ファイル、offline demoが成功。新3サービスの公式SDKとloopback HTTP往復、tokenのサービス分離、失効・再起動、権限外検索、121件のページ取得、別宛先送信・重複・unknown、送信前の取消を架空データで検証。最初のUI一括実行は途中のfixture更新によるHMRとMessengerボタン名の誤りで失敗。修正・開発サーバー再起動後の全59件は成功。
- 通常配置0.8.5の置換、実送信、個人データへのMCP権限登録、実データ削除は実施していない。実AIクライアントからの本番接続・新3サービスのMCP実送信は未検証。
- 公式ヘルプ・公式Desktop画像から[本家BeeperのUI/UXと採用案](BEEPER_UI_UX_REFERENCE.md)を作成。最優先は統合Inbox＋未読／下書き、次に横断検索・通常時の表示整理。アーカイブ・ピン・ラベル等の条件も定義。このInbox再設計は提案段階で未実装。
- 0.9.0で残したSlack公開OAuth Client ID・更新配布設定、LINEの全過去履歴、Messengerの暗号化バックアップ、完全な削除同期等の制約は維持。署名と同梱runtimeは `desktop-0.9.1-verification.json`、配布ZIPは `desktop-0.9.1-package-verification.json` に記録する。

- 0.9.1署名付き候補を作成。Developer ID、8実行ファイル、87埋込Mach-O、通常0.8.5との相互designated requirementを確認。空HOME・OS標準PATHで同梱Core/MCP/X暗号処理・IG/Slack設定補助を確認し、5providerのIPC pingが0.9.1を返した。
- 配布: `../dist/BeeperLocal-0.9.1-AppleSilicon-beta.zip`（63,099,224 bytes）。SHA-256: `c302c5551f5a883895e921233ac9bce0c0925df0d2474e085bfb0a2a3d614f14`。ZIPを空白入りの一時パスへ展開し、署名、8実行ファイル一致、対応ソース789ファイルの現行内容一致、Go埋込23ファイル、2設定補助、同梱Core起動を確認。削除確認fixtureの順序整理後の該当UI4件も成功。通常アプリは0.8.5のまま。公証・別Mac確認は未実施。

## 2026-10-03: 0.9.2候補 — 新規Macを想定した再監査と修正

ユーザーの再監査・不具合修正の依頼を、主担当だけで実施。**一般配布はまだ保留**。以下はこのMacのmacOS 26.5.2でエージェントが観測した結果であり、別Mac・新OSユーザーでの本人ログインは未実測。

- 0.9.1の最低OSを実行ファイルと圧縮Core内まで検査したところ、95対象中65個がmacOS 26.0を要求し、表記の13.0と不一致だった。Go/cgoを13.0へ固定し、配布用Pythonを公式3.13.12からプロジェクト内だけに展開。frameworkの参照先を自己完結させ、GUI未提供のTelegram SDKによる任意SSLライブラリ収集を除外。現行CLIのTelegramは維持。全Mach-OのOS・arm64・外部参照検査をビルド／梱包へ追加した。
- 開発用CAがない状態で旧SSLContextが証明書検証に失敗することを再現。Slack API/OAuth・MatrixをmacOSの信頼ストアへ変更。同じ条件の公開TLSハンドシェイクが成功し、未信頼の自己署名サーバーは拒否した。
- WebViewの購読前に発生したCore起動エラーを保持し、要求登録との終了競合を修正。一つのサービスの接続待ちが他サービスの設定・接続を止めないよう、サービスごとの順序を守ってIPC要求を並行処理。更新準備は先行処理を待つ。
- Slackの公開OAuth設定がない場合は開始前に停止し、既存の受信接続を維持。画面も新規ログイン未提供を説明して無効化。公開OAuth設定そのものは未完了。
- **Core 489件・画面65件・Rust 5件が成功**。版番号更新後の画面16件、署名済みCoreから読み出した32モジュールを用いる初回状態／並行処理／TLSの7件も成功。後者の依存ライブラリはビルド環境。shell構文6ファイル・offline demo・production buildを確認。
- 初回状態は空の資格情報fixtureと実暗号化SQLite、GUI fixtureで検証。5サービスの未ログイン・履歴なし・MCP停止／権限なし・設定表示・保存停止の再起動を確認。本番Keychainや子プロセスへのアクセスを拒否するテスト境界を使用。実際の初回Keychain承認やWebView本人ログインを再現したものではない。
- 署名済み0.9.2の**8実行ファイル＋Core内85 Mach-O**にDeveloper ID署名を確認。全93個にarm64があり、最低OSは13.0以下、開発環境固有の外部ライブラリ参照なし。通常0.8.5との相互署名要件も成功。macOS 13実機での動作確認とは区別する。
- `spctl --assess` は0.9.2でも `rejected / Unnotarized Developer ID`。`stapler validate` も公証チケットなし。OS保護機能を解除して代用しない。
- ZIPを日本語・空白を含む別フォルダへ展開し、署名と互換性を再検査。アプリ内全23ファイル（実行ファイル8個含む）がビルド成果物と一致。対応ソース800ファイルが現行ソースと一致し、Go埋込素材23件も含む。空HOME・OS標準PATH・開発用CAなしでCore/MCP/X暗号処理/TLSと設定補助2個が成功。DBは作成されていない。HOME変更によるKeychain隔離は主張しない。

内部検証候補: `../../dist/BeeperLocal-0.9.2-AppleSilicon-beta.zip`（60,174,350 bytes）。SHA-256: `445f966d6c9e2f77eb6b55f0cbd0ab12387fc7b7326147029794c1d3d7dc5508`。通常配置0.8.5の置換、資格情報の読取り・移行、実送信、本番MCP権限追加、本番DB削除は行っていない。

一般配布の残件はApple公証、Slack公開認証の構成、別Mac／別OSユーザーでの本人ログインと実経路の受入確認。追加した送信／MCP経路、長時間運転・実回線断・スリープ・macOS 13での受入も未確認。監査詳細: [FRESH_MAC_AUDIT.md](FRESH_MAC_AUDIT.md)。ビルド検証: [desktop-0.9.2-verification.json](desktop-0.9.2-verification.json)。ZIP検証: [desktop-0.9.2-package-verification.json](desktop-0.9.2-package-verification.json)。


## 2026-10-03: 0.9.3候補 — 利用者フィードバックとLINE／Instagram認証

利用者報告の画像送信、アイコンの再取得、Instagramの認証案内、Keychain確認の反復に加え、「別のLINE接続後にLocalが切れても接続表示が残る」「Instagramの認証通知が来ない」を主担当だけで修正した。通常配置は0.8.5のまま。詳細は [USER_FEEDBACK_0_9_3.md](USER_FEEDBACK_0_9_3.md)。

- LINE・Instagram・Slack・X・Messengerへ、プレビュー後に本人が送信する画像経路を追加。JPEG／PNG、1枚ずつ4MiB・2,500万画素まで。EXIF等を除去し、宛先・アカウントを確認、送信前に暗号化outboxへ記録、結果不明や同じ要求IDを自動再送しない。実アカウントへの画像送信は未実施。
- LINE・InstagramアイコンとSlackプロフィールを暗号化保存して再利用。同じKeychainデータの反復書込みを省き、GUI内で読み取りを共用。キャンセル後は本人の再接続まで同じアクセスを繰り返さない。OSのACL・資格情報・暗号鍵は変更しない。友人のMacでの確認回数の改善は未実測。
- LINE CLIに明示的な受信状態通知を追加。実際のストリーム応答前は準備中、内部再接続中は再接続表示にする。無通信状態の定期probeでも強制ログアウトを検出し、Coreの接続・受信・同期を停止、画面を「再ログインが必要」へ切り替える。遅延応答が状態を復活させないことを回帰試験で確認。履歴と下書きは残し、本人が手動でQR再連携する。
- 本家Beeper・Chrome版LINEと本アプリは同じChrome Extension枠で競合し得る。これは同時利用を可能にする修正ではない。スマートフォン利用やすべての公式Mac／PC版と同一視せず、報告された正確な公式アプリ種別は未確認。実アカウントをログアウトさせる再現操作はしていない。
- Instagramは同梱Terminal補助から公式サイトの専用ネイティブウィンドウへ進む。新規の非永続WebKitセッション内で本人確認し、公式画面に表示される別の確認方法を使える。本人の完了操作後、そのセッションだけを非公開pipeで渡し、アカウント・Direct接続検証後に従来のKeychainへ保存。既存ブラウザやBeeperのCookieを抽出せず、キャンセル・検証失敗で保存済みログインを上書きしない。この新経路での実本人認証は未検証。

エージェントが観測した検証結果:

- Core全515件成功。ローカルHTTP用のsandbox制約を解消して再実行した結果。画面は全75ケースのうち74件が初回成功し、新規テストのinnerText比較を修正して対象12件を再実行し成功（累計75ケース。単一実行で75成功とは記録しない）。Rust6件、関連Go試験、shell7ファイル、offline demo、production buildが成功。
- 署名済みCoreの実bytecode 41モジュールを読み込む33件も成功。依存ライブラリとfixtureはビルド環境。native Instagram helperのドメイン・非永続境界チェックも成功。GUI・画像の検証は架空データ。
- 同じDeveloper IDで9実行ファイル＋Core内85 Mach-Oを検証。全94個にarm64があり、最低OS13.0以下、開発環境の外部ライブラリ参照なし。通常0.8.5との相互署名要件も成功。macOS13実機の動作成功は未確認。
- 空HOME・OS標準PATH・開発用CAなしでCore/MCP/X暗号処理、Instagram新規helper、Slack補助、公開TLS、5サービスのIPC pingが成功。資格情報やDB鍵の項目を読み書きせず、DBは作成されていない。HOME変更によるKeychain隔離は主張しない。
- ZIPを日本語・空白のある一時フォルダへ展開し、署名・互換性を再確認。アプリ全24ファイル（実行ファイル9個）が署名済みビルドと一致。対応ソース820ファイルが現行ソースとbyte単位で一致し、Go埋込素材23個も収録。設定補助2個とCore/TLSの展開後検査も成功。

内部検証候補: `../../dist/BeeperLocal-0.9.3-AppleSilicon-beta.zip`（60,420,154 bytes）。SHA-256: `0d531c4c367d0a38ecb253dd4bf80144c020eca44dfc0e7e287f5604f5196d4f`。検証は [desktop-0.9.3-verification.json](desktop-0.9.3-verification.json) と [desktop-0.9.3-package-verification.json](desktop-0.9.3-package-verification.json)。

通常版の置換、実メッセージ送信、本番MCP権限追加、本番データ削除・資格情報移行は実施していない。Apple公証は未実施でGatekeeperはUnnotarized Developer IDとして拒否。Slack公開OAuth設定、別Mac／別OSユーザーでの本人ログインと実送受信も残り、一般配布は保留。


## 2026-10-03: 0.9.3最終判定 — 友人に5サービスすべてを使ってもらう基準

ユーザーは最終点検で「5サービスすべて」を指定した。この基準に対する判定は **未合格**。515件の自動テストと累計75画面ケースの確認は、初めてのMacで本人認証から実送受信まで完了した証拠ではない。

今回改めて配布ZIPのSHA-256一致、展開済みアプリのdeep/strict署名検証成功を確認した。一方、Gatekeeperはexit 3 / Unnotarized Developer ID、公証チケット検査はexit 65。同梱Coreの実bytecodeを直接読んでもSlackの公開Client IDは空で、新規利用者はSlackを連携できない。これらは推測ではなく配布物の検査結果。

新しいInstagram helperを配布物から起動し、公式サイトの本人確認コード画面が表示されることをCuaで観測。エージェントは資格情報やコードを入力せず、保存／アダプタ取込みは実行しない。検査後にキャンセルし、exit 0・cancelled=true・login_completed=falseを確認した。認証完了や受信成功の証拠には数えない。画面のアカウント名・メール・認証URLはレポートへ記録しない。

未完了の必須項目は、Apple公証を済ませた最終成果物の新Mac起動、実Slack公開認証設定、新しい環境での5サービス本人ログイン・テキスト送受信・画像送信と相手側確認・再起動後の履歴保持、および実回線断／スリープ復帰・Keychain初回承認。既存版での接続・受信実績を今回の新規経路の実測に流用しない。自動更新未設定は、明示した手動更新手順で補えるため単独のβ不可理由とはしない。

[最終点検の機械可読記録](desktop-0.9.3-final-readiness.json)。今回は配布ZIP・アプリ・製品コードを変更しない。利用可能性の判定を記録する点検であり、Appleへの提出やSlack設定の変更はしていない。


## 0.9.4 公証・Slack配布の実装（2026-10-03、外部適用を継続中）

- 公証のprepare/submit/status/recover/staple/verifyを追加。Appleの申請IDとアーカイブSHA-256を照合し、通信断時の二重提出を禁止。署名・チケット・Gatekeeper・ZIP展開後の同梱設定を検査する配布ゲートを追加。
- `notary-profile`でApple認証成功。Appleへの提出はSlack設定を含む最終ビルド後に実施する。
- 承認済みのSlackアプリA0C5L6H2Q8YへPKCE、12 User scopes、token rotation、localhost redirectを保存済み。ただしSlackの外部配布画面がHTTP redirectを拒否したため、macOS ASWebAuthenticationSessionとbeeperlocal専用URLの受取処理を追加。専用URLへの変更は別途明示確認待ち。Public Distributionはまだ無効。
- Python全530件、関連GUI19件、ネイティブSlack認証の入力・callback self-test、シェル7ファイル、offline demo50件が成功。実ログイン・実送受信の成功とは区別する。
- native Slack helper追加前の0.9.4候補で9 native+85 embeddedのDeveloper ID署名・macOS13互換・空HOME runtime・公証用コピー作成を確認済み。最新ソースは10 nativeとなるため再ビルドが必要。通常アプリ0.8.5と既存0.9.3 ZIPは維持。
- 友人向け0.9.4 ZIPは未作成、公証とSlack配布の実完了を待つ。別Macで5サービスすべての実ログイン・送受信も未検証。詳細: RELEASE_DISTRIBUTION.md、desktop-0.9.4-distribution-implementation.json。

## 0.9.4 Keychain反復修正と通常配置更新（2026-10-03）

ユーザー報告: `beeperlocal-core`がMessenger統合用Keychainへのアクセスを繰り返し求める画面が再び出る。エージェントが確認した通常配置は0.8.5で、候補に実装済みのGUI内Keychainキャッシュが含まれていなかった。添付画面を出した実行ファイルのパスまでは特定していない。

追加でMessengerの会話切替が認証metadataを書き換えていたことを確認し、選択状態を既存AES-GCM DBのアカウント別private settingへ移した。会話切替はKeychainを読まず・書かず、再起動時に選択を復元する。旧選択の取込みでKeychainを更新せず、無効な選択や別アカウントの選択を無視する。端末情報・認証情報・DB鍵の保存先と受信commit/ACKは維持。

エージェントが観測した検証結果:

- Python全532件・Messenger/beta画面14件が成功。署名済みCoreの実bytecodeを読み込む45件／43モジュールでも成功。後者のfixture・依存ライブラリは開発環境であり、実アカウントの試験ではない。
- production build・shell8ファイル・offline demo成功。10実行ファイル＋85内蔵binaryのDeveloper ID署名・旧0.8.5との相互署名要件・arm64/最低OS13.0設定を確認。macOS13実機の成功とは区別する。
- 空HOME・OS標準PATH・開発CAなしでCore/MCP/X暗号処理・Instagram/Slack補助・公開TLS・5サービスのIPC pingと二重起動拒否が成功。Keychain項目にアクセスせず、DBも作成されていない。HOME変更でKeychainを隔離したとは扱わない。
- 修正版をAppleへ提出し、`Accepted`・issue_count=0を確認。申請IDとZIP SHA-256を照合した。公証チケット添付・検証とGatekeeperの`Notarized Developer ID`受理も成功。
- 通常`../../BeeperLocal.app`を公証済み0.9.4へ更新。旧0.8.5は`../../archive/app-backups/BeeperLocal-0.8.5-before-0.9.4-keychain-20261003T164956.app`へ保全した。配置した26ファイルのhashが公証済み成果物と一致し、バックアップも旧版と一致。配置後のチケット・Gatekeeper検査も成功。

インストール時に利用者データ・資格情報・Keychain ACLを操作せず、実メッセージも送っていない。更新後の実利用で確認画面が再発しないかは未確認。初回のOS許可は本人操作であり、アプリが自動許可しない。

Apple公証の残件は今回の成果物で完了。Slackは専用URL変更の明示承認待ちでPublic Distribution未完了、公開Client IDも未同梱。別Macでの5サービス本人認証・実送受信も未検証で、友人向けZIPは作成していない。詳細: [更新検証](desktop-0.9.4-keychain-verification.json)、[配置記録](desktop-0.9.4-install.json)、[配布実装と残件](desktop-0.9.4-distribution-implementation.json)。

## 0.9.5 Slack専用URL・外部配布・通常配置更新（2026-10-03）

本人の承認を受け、SlackアプリA0C5L6H2Q8Yの接続先を`beeperlocal://oauth/slack`へ保存した。再表示した保存済みmanifestで専用URL・PKCE・12 user scopes・token rotationを確認し、Manage Distributionの有効化を実行。「Share Your App with Any Workspace」と「Deactivate Public Distribution」を観測した。公開Client IDを本体へ同梱し、配布検査フラグも実設定に基づいて有効化。Slack Marketplace掲載や本人OAuth完了は意味しない。

エージェントが観測した検証:

- Python全532件、Slack/beta/初回画面19件、署名済みCoreの実bytecode45件／43モジュールが成功。fixture試験と実アカウントの成功を区別する。
- 0.9.5の配布モードビルド、shell8ファイル、offline demoが成功。10実行ファイル＋85内蔵binary、旧0.9.4との相互署名要件、arm64/最低OS13.0設定を確認。空HOME・OS標準PATH・開発CAなしの起動、MCP/X暗号処理/TLS、5サービスIPC ping、二重起動拒否、同梱Slack設定とソースの一致を確認。
- MacのSlack認証ウィンドウを起動してキャンセルし、exit 0・cancelled=true・codeなしを確認。Slackの権限承認・トークン交換・新規認証保存は実行していない。UI検査時に通常GUIも一時起動したため、既存アカウントの自動読み込みがあり得る。個人情報を観測レポートに記録せず、検査後の全BeeperLocalプロセス終了を確認した。
- 0.9.5をAppleへ新たに提出し、Accepted・issue_count=0を確認。申請IDと提出ZIPのSHAを照合し、公証チケット添付・検証とGatekeeper受理が成功。
- 通常`../../BeeperLocal.app`を公証済み0.9.5へ更新し、旧0.9.4を`../../archive/app-backups/BeeperLocal-0.9.4-before-0.9.5-slack-20261003T170156.app`へ保全。配置26ファイルの一致、バックアップの旧版一致、配置後のチケット・Gatekeeperを確認。インストール処理は利用者DB・Keychain値・ACLを操作しない。

Apple公証とSlack公開設定の2つの阻害要因は今回の本体で解消。残るのは、新しいSlack OAuthの本人承認・トークン交換・更新、別Macで5サービスすべての実ログイン・実送受信・画像着信・再起動後の履歴、長時間・回線断・スリープ復帰の受入。これらが未確認のため、5サービスの実利用合格とは記録しない。

[Slack実設定の記録](desktop-0.9.5-slack-configuration.json)、[ビルド検証](desktop-0.9.5-verification.json)、[配置記録](desktop-0.9.5-install.json)。

試用ZIP `../../dist/BeeperLocal-0.9.5-AppleSilicon-beta.zip` を作成した（60,473,137 bytes、SHA-256 `f68e35e4b1c2003c4e4bf998976a17d02c7c47913438911e5db888a36b337e7b`）。導入手順・対応ソース829ファイル・公証/Slack設定の検査結果を同梱。日本語・空白を含む別フォルダへの展開後に、アプリ全26ファイル・実行ファイル10個の一致、ソース829ファイルの一致、Go埋込素材23件、署名・チケット・Gatekeeper・Slack設定を確認した。空HOME・OS標準PATH・開発CAなしで同梱設定補助2個・Core/MCP/X暗号処理・公開TLSが成功し、DBは生成されていない。[ZIP検証](desktop-0.9.5-package-verification.json)。別Macの本人認証・実送受信が未完了のため、記録上の`public_beta_ready`は引き続きfalse。


## 2026-10-03 開発方針の見直し（ソースのみ）

ユーザー指定の資料先行・TDD・KISS・開発中は後方互換/データ移行を維持しない方針をルートAGENT.mdへ記した。AGENTS.mdから参照し、単独作業を継続する。旧DB自動更新、旧保存設定、Messenger旧本文/会話選択の自動取込み、Slack localhost認証を取り除いた。非対応データを勝手に削除・再作成せず停止する。使われていないX移行スクリプトは `_to_delete/20261003-kiss/` に退避。

資料 → 受入テストの失敗14件 → 最小実装 → 対象70件成功 → 全体回帰の順で実施。Core全537件、関連UI13件、TypeScript/Vite build、shell8件、offline demoが成功。README・CLAUDE・次工程と関係ADRの矛盾を整理し、過去記録を分離した。[受入条件と検証](DEVELOPMENT_REVIEW_20261003.md)。

通常アプリ・試用ZIPは公証済み0.9.5を維持。今回のソースを配布するビルド・公証は未実施。実アカウント接続、実送信、利用者DB/Keychainの更新は行っていない。販売対象・料金・公開設定も変更していない。
