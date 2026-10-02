# Slack追加実装・範囲と検証

更新: 2026-10-01（日本時間）。日本の顧客向けローカルMCP接続基盤として、次の対象をSlack、次候補をDiscordに変更する。LINE・Instagram・Xはユーザー指示上の既存実装として扱い、再実装しない。iMessage・WhatsAppは対象外。サービス数の増加を目標にしない。作業は主担当のみで実施した。

## 着手前に確認した状態

コードは `beeperlocal/connectors/slack.py`、`auth.py`、`cli.py`、`models.py`、`storage.py`、`connectors/registry.py`、`desktop_control.py`、`mcp_server.py`、`tests/test_slack.py` を確認。根拠記録は `PROJECT_STATE.md`、`ADR_PHASE1_PERSISTENCE.md`、`SECURITY.md`、`TEST_REPORT.md`、`GATES_v0.3.md`、過去desktop試験記録。

2026-09-27のSlack User OAuth接続・会話一覧・実履歴1件取得と、Matrixとの同一タイムライン統合のGate AはCLOSED。9/30追記には実Slack保存・検索成功のユーザー報告がある。これを未実装扱いに戻さず、同じ認証・DB鍵・保存形式・message identityを再利用した。50件ページング実機Gateは別で未確認。

| 確認項目 | 着手前の分類 | 根拠・正確な範囲 |
|---|---|---|
| 認証 | 実装済み／制約あり | 本人のUser OAuth Token `xoxp-`を非表示入力しKeychain保存。`auth.test`でteam/userを照合。Bot token／bot identityは拒否。自動OAuth認可画面・token rotationは未実装 |
| 本人の既存DM・グループDM | 実装済み／未検証 | `im,mpim`の一覧・選択・history経路は存在。本人のトークンでアクセスできる会話に限る。実DM取得の証拠はなかった。Bot宛てDMをこの証拠の代わりにしない |
| チャンネル | 実装済み／制約あり | 参加済み公開チャンネル、APIが返す本人参加の非公開チャンネル。未参加公開チャンネルを一覧・取得で除外。実チャンネル1件の成功証拠あり |
| スレッド | 未実装 | 親との関連を正規化するフィールドはあるが、`conversations.replies`呼び出しがなく、全返信取得は不可 |
| 送信・送信名義 | 未実装 | GETのmethod allowlistしかなく送信不可。既存Bot送信の実績ではない |
| 履歴 | 実装済み／制約あり | 最大5つの選択会話を件数上限付きで取得。1ページ15件、cursor/time paging、429待機、budget、途中失敗検出あり |
| 新着受信 | 未実装 | 手動fetch/syncで最近の履歴を再取得できるだけ。watch、Events API、Socket Modeなし |
| ワークスペース | 実装済み／制約あり | account=`team_id:user_id`を安定IDに含める。別workspaceの衝突防止あり。KeychainのSlack接続枠は1つで同時複数workspace接続は不可 |
| Core・暗号化SQLite・検索 | 実装済み | 共通モデル・registry・CLI sync/searchへ統合済み。AES-256-GCM payload、Keychain鍵、最大10,000件をメモリ復号して検索。DB全体暗号化ではない |
| デスクトップ・MCP | 未実装 | SlackのGUI経路なし。既存MCPはLINE固定 |
| 再起動・重複排除 | 実装済み／未検証 | 認証・選択・暗号化DBの復元、provider/account/conversation/message IDによるupsertあり。Slack継続受信・再接続や送信の再起動試験はなかった |
| 配布・権限・承認 | 制約あり／未検証 | PoC用User read/history scopesのmanifestあり。顧客向けOAuth・Marketplace承認・商用提供許可の証拠なし |

## 今回の追加

- `SlackConnector`の履歴経路を維持し、既存認証の再利用、会話選択、User tokenによるテキスト送信、明示的なスレッド取得を追加した。
- `SlackDesktop`を既存Coreから拡張。送信前の暗号化outbox保存、結果不明時の停止、同一要求の二重送信防止、保存失敗時の停止を再利用した。送信のPOSTにはHTTP 429/5xx/redirect/timeoutでも自動再試行を付けない。provider応答の本人ID・会話・正式message IDを照合する。任意の名前やアイコンを指定するBot擬装はしない。
- Slackボタン・会話・履歴・検索・テキスト送信・定期取得・保存停止・MCP権限設定を追加した。ログインは既存CLIのまま。Slackだけの保存データ削除はまだない。
- 約65秒ごとの定期取得で選択中の1会話の直近1ページ（入退室などの除外イベントを含め最大15件）を取得し、メッセージ・会話・回収receiptを一括保存する。再起動時も同じ回収経路を使う。一時的なネットワーク／HTTP障害は上限付きで再試行し、認証・保存・不正応答では停止。SlackのRetry-Afterは次の操作にも保持する。
- MCPはSlack専用の設定・grant保存名と既定ポート28642を使用する。LINEの28641・既存grantを変更／流用しない。loopback、Bearer token、会話ごとのread/send、送信直前の再認可、失効を共通基盤で適用する。初期状態は停止、実データ用clientは未登録。
- MCP tools: `list_conversations`、`get_messages`、`search_messages`、`send_message`、Slack専用`get_thread`。通常readは保存済みデータのみ。`get_thread`だけはread許可会話についてSlackにアクセスし、最大15件を暗号化保存して返す。応答前にも権限を再確認する。
- 既存read-only manifestを残し、送信用User `chat:write`を加えた `slack-send-app-manifest.json` を別ファイルで用意した。後続検証で既存アプリのUser側の要求scopeへ`chat:write`を追加し、ユーザーが追加権限を承認。再開時に保存済みtokenへの権限反映を確認した。Bot tokenへの変更や認証情報の再入力はしていない。

## 読み書きできる会話

| 対象 | 読み取り | 書き込み |
|---|---|---|
| 本人が参加する既存1対1DM | User tokenの`im:read`/`im:history`とAPIの許可範囲。実DM E2Eは未検証 | 同じ本人のUser `chat:write`と宛先への投稿許可が必要。既存の会話IDを使う。実DM送信は未検証 |
| 本人の既存グループDM | `mpim:read`/`mpim:history`。実機未検証 | 本人名義の通常テキスト。実機未検証 |
| 参加済み公開チャンネル | `channels:read`/`channels:history`。履歴取得に加え、本人がSlack側で新規投稿した1件の自動取得・保存・再オープン検索も成功 | User `chat:write`と投稿許可。初回の応答判定を修正後、別途承認された新しいテスト1回で本人名義の成功応答・履歴・再オープン検索・重複送信抑止を確認 |
| 本人参加の非公開チャンネル | `groups:read`/`groups:history`。実機未検証 | User `chat:write`と投稿許可。実機未検証 |
| 上記会話のスレッド | 保存済みの親メッセージを指定して明示取得。MCP入口はその会話の保存済み最新100件内の親を対象とし、親を含む先頭最大15件。通常履歴だけで全返信を取得したとは扱わない | 今回は通常投稿のみ。スレッド返信の送信・返信broadcastは未実装 |
| 未参加公開チャンネル、参加権限のない非公開会話、他人同士のDM | 対象外。User tokenが一部未参加公開チャンネルを読める場合もアプリ側で除外 | 対象外。DM開設・招待・チャンネル参加を自動実行しない |
| Bot宛てDM | Bot経路は実装しない。User tokenの本人参加会話としてAPIに返る場合でも、他の既存DMの取得成功を意味しない | Bot名義では送らない |

読み取りはSlack自身の保持期間・プラン・権限・管理者設定に従う。ファイルは件数だけで本体は取得しない。SlackメッセージのE2EEを提供するものではない。ローカル保存は暗号化する。画面／MCPの出力は必要な本文をメモリで扱うため、許可したAIクライアントに渡った内容はそのサービス側でも処理され得る。

## 検証状態を分離

| 判定 | 状態 |
|---|---|
| コード実装 | 今回列挙した追加機能を実装済み。未実装項目は下記に残す |
| ローカルテスト | Core・Slack追加分・ローカルHTTP MCP・画面・既存3サービスの回帰を実行。最終件数と結果は `SLACK_VERIFICATION.json` |
| 実アカウントE2E | **公開チャンネル1会話の送信・新着取得を確認**。修正後の本人送信1回で成功応答、履歴、暗号化保存、Core再作成/DB再オープン検索、同一要求の再送抑止が成功。本人がSlack側で別途投稿した新着1件も65秒間隔の自動取得で保存・再オープン検索に成功。別の相手からの受信、DM・グループDM・非公開チャンネル・実スレッド返信、Mac再起動・回線断復旧は未検証 |
| 商用配布条件 | 公式条件の確認済み、**BeeperLocalへの適合性・承認は未確認**。販売可能と判定しない |
| 配布物 | ソースとローカルbuild/checkまで。普段使うBeeperLocal.appの置換・公証・他Mac配布は今回未実施 |

今回の読み取り確認スクリプトは `scripts/slack-live-read-check.py`。現在のKeychain・選択済み会話を使い、本文・名前・生ID・検索語・tokenを結果に出さない。送信コードを呼ばない。結果は `../../slack-integration-work/live-read-check.json`。ここでの再オープンはDBを閉じて同じ鍵で開き直した結果であり、Mac再起動の確認ではない。

### 承認済み送信の実機検証（同日追記）

画像だけの段階では送信せず、後続の「送信してよい」で指定テスト先・本文の1回送信を承認された。最初はUser `chat:write`不足を確認しPOST前に停止。管理画面のログイン、既存アプリのUser要求scopeへの追加、権限付与の承認後、保存済みtokenに`chat:write`が反映されたことを確認した。workspace・チャンネル名・参加状態を再照合してから1回だけ送信した。Bot scopeやBot tokenへ切り替えていない。

送信Coreは`SLACK_SEND_UNKNOWN`で停止したが、追加POSTせずに直近履歴を読み、要求作成時刻付近の承認済み本文と一致する投稿を**1件**確認した。投稿の`user`は`auth.test`の本人IDに一致し、`type=message`、`bot_message` subtypeではない。`bot_id`と`app_id`というアプリ帰属情報も付いていた。一致するテスト投稿を既存暗号化DBへ保存し、Coreの閉鎖・再作成とDB再オープン後の検索も成功した。Mac再起動の確認ではない。

本人IDが一致していても`bot_id`があるだけで拒否する判定があったため、この応答形状を使うローカル試験2件で失敗を再現し修正した。認証時のBot拒否、投稿者ID・会話・timestampの一致確認、明示的な`bot_message`拒否は維持する。修正後のCore全体**321件が成功**（Slack 61件を含む）。検証中に同じ作業領域へ追加されていたLINE再接続試験6件も最終実行に含む。この送信判定修正で変更した実装はSlack Connectorのみ。

この初回実送信のoutboxは`unknown`のまま保持した。履歴本文・時刻の一致だけで、取得できなかった元の成功応答を遡って作成しない。同じrequest IDの送信要求は、provider呼び出しを行わず拒否されることを再オープン後に確認した。初回要求の実POSTは1回で再送していない。以下の修正後試験は、後続の承認に基づく別のテスト要求である。

初回結果は`../../slack-integration-work/approved-send-check.json`と`inspect-approved-send.json`、回帰結果は`core-tests-after-live-send-loopback.txt`。送信後の元の補助レポートは送信回数1を記録しつつ状態ラベルを未実行のままにしていたため、元ファイルを`approved-send-check-original.json`に保全し、結果不明へ訂正した。認証情報や私的会話本文を検証レポートへ保存していない。

### 修正後の送信・新着取得の実機検証（同日追記）

後続の「検証しよう」を受け、同じ承認済みチャンネルに識別できる別のテスト文を、新しいrequest IDで1回送信した。本人ID・チャンネルが一致する成功応答を正常に受理し、Slack履歴から同じmessage IDを取得。暗号化保存後にCoreを再作成して検索でき、同じrequest IDの再実行はproviderアクセスを禁止した状態で重複抑止された。修正後テストのPOSTは1回、初回を含む本作業の送信POSTは計2回。初回の`unknown`要求を再送したものではない。

続けて、ユーザーがSlack側の同じチャンネルへ通常投稿した受信確認文1件を、本番の`start_watch`による65秒間隔の定期取得で検出した。受信補助スクリプトは送信も手動fetchも実行していない。待ち受け開始後の投稿であることを確認し、1回目の取得で暗号化DBへ保存、Core再作成後の検索も成功した。投稿者は認証中の本人と同じなので、**別クライアントからの新着取り込み**の証拠であり、別の相手からの返信・DM受信の証拠ではない。これはCore/DBの再オープンであり、Mac再起動ではない。

結果は`../../slack-integration-work/fixed-send-check.json`と`fixed-receive-check.json`。この実機検証時点では実装コードを変更せず、当時のCore321件成功の回帰結果を維持した。通常アプリの置換、実データMCP client登録、実DM・非公開チャンネル・スレッド返信は未実施。

### 日常利用の安定性改善（実機確認後の同日追記）

ユーザー指示によりDM・別の相手からの返信の実機検証を後回しとし、次の2点をローカルで再現して修正した。

- **除外イベントが混ざった新着取得:** 旧処理は本文メッセージが15件に達するまで古いページも取得したため、入退室通知を含むページから続けて要求し、レート制限で取得全体を保存できなくなり得た。Slack Desktop/daemonの取得を`fetch_recent`へ分け、通知や空ページがあっても履歴要求を1ページで止める。続きがあることはreceiptの`history_limited`へ保存する。明示的なCLI `sync slack`の複数会話・ページングは既存の`fetch`を維持する。共通Coreへの変更は取得メソッドの呼び分けだけで、LINE/Instagramの既定処理は同じ。
- **記号を含む文章の保存・検索:** `&`、`<`、`>`を送信時にSlackの対応する表記へ変換し、履歴取得時にその3種類だけを一度復元する。文字列として入力した`&lt;`等を二重に復元せず、通知用の記法も通常の文字として送る。履歴更新で元の文章の検索が失敗していたケースを再現し、同じmessage IDと送信記録を保ったまま再オープン検索に成功することを確認した。根拠は[Slack公式の文字エスケープ仕様](https://docs.slack.dev/messaging/formatting-message-text/#escaping-text)。HTML全体の解析や表示は追加していない。

新規回帰試験6件、Slack関連合計67件を含む全331件が成功。全体件数には同じ作業領域で別途追加されたLINE再接続試験10件を含む。shell構文6ファイルとoffline demoも成功。修正前の再現ログは`../../slack-integration-work/reliability-before-tests.txt`、修正後の全体結果は`reliability-core-tests.txt`。この改善作業での実Slack送信・受信試験は0回であり、前項の実機成功を新しい修正の実機成功へ置き換えない。通常アプリの配布物は置換していない。

## 技術上の残り

- 接続中workspaceは1つ。これは現在のBeeperLocal実装の制約。`MacKeychain`はprovider名`slack`の単一枠を読み書きし、`login_slack`はその枠を置き換える。`DesktopRouter.cores`もprovider単位でSlack Coreを1つ持ち、Core/Connectorの`account_id`は単一値。別workspaceへloginすると接続枠が置き換わるが、保存済みデータのidentityは`team_id:user_id`で分離する。複数同時接続・切り替えUIは未実装。後続確認でworkspace衝突防止、認証変更時の読書停止、poll再起動・重複排除、同一送信要求抑止の既存5試験が成功。複数workspaceの同時実機試験を行ったという意味ではない。
- 自動OAuth認可フロー、短期tokenのrefresh/rotation、Slack内の認証UIは未実装。失効したら本人の再認可が必要。
- 定期取得は選択1会話・直近15件。取得間隔中に15件を超える流入や長い停止中の欠落を保証しない。既存CLI `sync slack`の上限付きページングは維持するが完全履歴の保証はない。
- 古いスレッドへの新着返信の自動発見、全スレッド巡回、push受信、incremental cursor/DB commitの完全同期は未実装。MCP threadは先頭最大15件までで、続きのページ指定UI／MCPは未実装。Connector自体のcursor/time pagingはfixtureで検証済み。
- 再取得範囲内の編集は同じIDへupsertする。削除・送信取り消しのreconciliationは未実装。ローカルMCP readは保存済みデータであり、現在のSlackの所属／保持期限を毎回照合するものではない。
- Slack専用の保存データ削除・保持期間設定、長時間・スリープ・実回線断、実アカウントの同時操作、商用セキュリティ監査は未完了。
- Xは `../../x-integration-work/` の既存Python/Go connectorで回帰確認した。調査時の通常アプリ側ソースと記録にはX未統合の記述が残っていたが、今回Xコードや通常アプリを変更して整合させる作業は行わない。

## 商用配布・必要な承認

2026-10-01に以下の公式資料を確認した。これは条件の整理であり、Slackからの承認・法的適合判断を取得したものではない。

1. [API Terms](https://slack.com/terms-of-service/api)は商用配布にSlack/Salesforceとの別契約を要求し、通常はMarketplace agreementを含む承認経路を示す。カスタムアプリやテンプレートも対象。単一第三者専用の例外を、多数の日本顧客向け商品に適用できるとは推定しない。組織のAPIデータ使用・処理・保存の明示的許可、最小限の保持、プライバシーポリシー等も必要。LLM学習や一般的な一括exportには制約がある。
2. [Marketplaceガイドライン](https://docs.slack.dev/slack-marketplace/slack-marketplace-app-guidelines-and-requirements/)はメッセージexport/backup等を不適切なアプリの例に挙げる。Automation platform分類にはUser `*:history`での収集を認めない等の追加条件がある。**ローカル保存＋外部AIへのMCP接続がどの分類に該当し、受理されるかは未確認で、実質的な配布上の課題である。** SlackbotをMCP clientとする別種の規定や、Agent/Assistant UI・Data Access API専用条件を、そのまま現経路の許可として引用しない。
3. [配布ガイド](https://docs.slack.dev/app-management/distribution/)に従い、第三者向けOAuth、workspace管理者のアプリ導入許可、scope追加時の再承認が必要。本人トークンの手動入力PoCを、顧客が安全に導入できる配布フローの完成とは扱わない。GUI一覧は現状4種類をまとめて取得するため、read-only manifestにある8つのUser read/history scopesを前提とし、不足時は明示的に停止する。
4. [history](https://docs.slack.dev/reference/methods/conversations.history/)と[replies](https://docs.slack.dev/reference/methods/conversations.replies/)は、対象となるMarketplace外の新規商用アプリ／導入では1分1リクエスト・最大15件という制約を示す。内部向けやMarketplace承認済み等は別枠であり、どの枠がBeeperLocalに適用されるかは未確定。レート枠が使えることは商用提供許可を意味しない。
5. [User token](https://docs.slack.dev/authentication/tokens/)は認可した本人として動作する。[User対応のchat:write](https://docs.slack.dev/reference/scopes/chat.write/)を送信時だけ追加する。Bot scopeや`chat:write.customize`への切り替えはしていない。

販売に進む前に、Slackへローカル保持・本人DM取得・外部AIへの会話別提供・削除／権限失効追従を含む用途を説明し、配布とデータ利用の許可範囲を確認する必要がある。Botへの変更やSlack側検索だけの方式への変更は商品範囲を変えるため、実装前にユーザーへ報告し判断を得る。

## 開発版で使う入口

既存資格情報が有効なら再ログイン不要。初回／失効時は `./run.sh login slack`、会話選択は `./run.sh select slack`。認証情報をチャットやファイルに貼らない。通常履歴保存は `./run.sh sync slack --limit 15`。`./run.sh daemon slack` は1会話の定期取得で、LINE用の `--from-now` / `--max-messages` はSlackでは拒否する。`./run.sh send slack` は非表示入力したテキストを選択会話へ1回だけ送信するため、承認済みテスト先だけで実行する。

SlackのMCPはSlack接続設定から明示的に有効化し、必要な会話だけread/sendを指定して登録する。初期grantはゼロ。tokenは発行時だけ表示し、ログや報告へ転記しない。MCP readは保存済み最大100件・検索最大10,000件／50結果で、全履歴／全workspace検索ではない。
