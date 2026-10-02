# BeeperLocal Project State

Updated: 2026-10-01

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
