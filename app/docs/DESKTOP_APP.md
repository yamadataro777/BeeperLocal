# BeeperLocal.app — Macで使う

更新: 2026-10-03 / 0.9.3 / Apple Silicon向け内部検証候補。今回の修正は [USER_FEEDBACK_0_9_3.md](USER_FEEDBACK_0_9_3.md)、一般配布の条件は [FRESH_MAC_AUDIT.md](FRESH_MAC_AUDIT.md)。

初回利用は[BETA_GUIDE.md](BETA_GUIDE.md)、今回の修正点と残る条件は[BETA_READINESS.md](BETA_READINESS.md)を参照。最新の実測は[PROJECT_STATE.md](PROJECT_STATE.md)。

## 起動

通常配置の`BeeperLocal.app`は0.8.5。0.9.3は`dist/`の別候補で、通常版を自動置換しない。Python・Node.jsの追加インストールは利用者には不要。候補はまだApple公証がなく、新規MacのGatekeeperを通過しないため一般配布を保留する。未連携の状態ではLINE初回連携の案内を表示する。

左の「LINE」「Instagram」「Slack」「𝕏」「Messenger」でサービスを切り替える。接続状態・会話・検索・下書きはサービスごとに分かれる。対応する会話を順番に同期し、画面を切り替えた後も続ける。取得範囲・巡回頻度は [INBOX_0_9.md](INBOX_0_9.md)。MCP権限はサービス別。

初回にmacOSからKeychainアクセス確認が出た場合は本人が許可する。アプリでKeychainエラーが出た後は「LINEへ再接続」を押す。鍵が利用できない状態でDBを初期化したり、Keychainの設定を広く緩めたりしない。

9/30の0.5.1配置直後はMacのKeychain認証エラーで停止したが、ユーザーによるMac再起動後にLINE接続・実データ表示へ復帰した。最初に残っていた会話選択時の保存エラーも、再接続後のテスト会話選択では再発しなかった。Keychainや保存データのリセット・削除は行っていない。

## 初めてLINEを連携する

1. 未連携のMacで起動すると「LINEを連携」が開く。「QRコードを表示して連携」を押す。
2. スマートフォンのLINEのQRコードリーダーで読み取り、スマートフォンでログインを承認する。
3. 確認コードが表示された場合は、スマートフォンのLINEに入力する。
4. 完了後「会話一覧を開く」を押す。

「接続設定」→「LINE接続」→「QRコードでLINEを連携・再ログイン」からも始められる。既存のログインを更新するときは画面のチェックが必要。本家Beeper・Chrome版LINEとの同一アカウントでの同時利用はできない。連携を切り替えると、もう一方がログアウトする場合がある。0.9.3はログイン失効を受信処理から通知し、接続済み表示・自動再試行・履歴同期を止める。保存履歴と下書きから手動で再連携できる。通常の回線切断は再接続中として区別する。

QRと確認コードはメモリとアプリ内の一時表示のみで扱い、保存・ログ出力しない。中止・期限切れ・失敗・完了時に表示を消す。認証情報は引き続きネイティブKeychainに保存する。連携開始時にはMCPを停止し、別アカウントの権限・会話を引き継がない。スマートフォンで承認済みのログインは、画面の中止では取り消せない。

このMacでは実QRを経た再連携と会話・画像の取得に成功。別ユーザー・別Macでの完全な初回承認は未実施。QR描画の独立復号、初回状態遷移、キャンセル、失敗、既存ログインの置換確認は架空データでも検証済み。既存ユーザーをログアウトさせて初回検証を代用しない。

## 操作

- 左側の会話一覧はLINE側の最終更新時刻と取得済みメッセージの新しい方を基準に、新しい会話を上に並べる。未開封の会話も同じ基準。相手の名前は友だち一覧に限定せず、会話の連絡先情報から取得する。
- LINE・Instagramのプロフィール画像とSlackプロフィールは、各アカウント最大128件を暗号化して保存する。再起動・オフライン時も保存済み画像を表示する。未設定・取得失敗の場合は名前の頭文字を表示する。
- 一覧上部で相手名を絞り込める。一覧情報は起動・再接続時に更新する。設定の「再接続・一覧更新」から手動更新できる。
- 選択した会話の保存済み履歴を表示し、LINEから直近100件まで回収する。「履歴を更新」で再取得できる。
- 対応する会話の新着を巡回し、LINEの一時的な切断は1・2・4・8・16・30秒の待ち時間で再接続を試み、その後も約1分ごとに再確認する。履歴回収は直近100件まで。認証・復号・保存の異常は自動で無視せず停止する。
- Enterは改行。送信ボタンまたは⌘Enterで送信する。日本語変換中は送らない。
- 画像は選択・貼り付け・ドロップ後、プレビューで確認して明示的に送信する。5サービスでJPEG・PNG、4MiB・2,500万画素まで。送信経路と実機未検証の範囲は `USER_FEEDBACK_0_9_3.md` を参照する。
- 下書きは会話ごとに分離し、アプリを終了すると消える。送信結果不明の記録は暗号化して残し、自動再送しない。同じ未確定本文の手動再送にも履歴確認のチェックが必要。
- ⌘Kで選択中サービス・現在のアカウントの保存済みメッセージを検索する。最新一覧から外れた保存済み会話も対象。最新10,000件を走査し最大50件を表示する。
- 接続設定の「受信を停止」でネットワーク受信を止め、保存済み履歴を読める。
- アプリ終了時にCoreと受信プロセスを終了する。通常利用でTerminal daemonを並行起動する必要はない。

LINEは1対1テキストと画像・静止画スタンプ表示に対応。会話一覧は最大500件。グループ・既読・取り消し反映・全過去履歴の同期は未対応。サービスが送信を受け付けたという表示は、相手側の受信や既読を保証するものではない。

## Instagramを使う

このMacで連携済みのInstagramは、左の「Instagram」を押すとログインと保存済み履歴を読み込む。同じ画面で会話選択・履歴更新・受信待機・テキスト送信・保存済み検索ができる。送信上限はUTF-8で4,000 bytes。0.9.0から会話の巡回と追加履歴のページ取得に対応する。

履歴は1ページ最大20件を追加取得できる。既存グループと取得可能な小容量添付の表示にも対応するが、全履歴やE2EE会話を保証しない。消えるメッセージ、動画・その他のファイル送信、新規グループ作成は未対応。画像送信は0.9.3で追加した。実送受信の過去の証拠はPROJECT_STATEを参照。自動試験を別Macでの接続成功の証拠にはしない。

設定の「受信を停止」「保存を停止／再開」「保存データの削除」とMCPはInstagramの範囲に作用する。「Instagramにログイン」ボタンは対象の受信を停止してから同梱の接続ファイルを開く。0.9.3はTerminalからInstagram公式サイトの専用ログインウィンドウを起動する。本人確認は同じ非永続WebKitセッション内で進め、通知が届かない場合は公式画面に提示される別の方法を選ぶ。本人が「ログイン完了・接続する」を押すと、その専用ウィンドウの認証情報だけを非公開パイプでアダプタへ渡し、アカウントとDirectへの接続を検証した後に既存のKeychainへ保存する。Terminalの保存成功表示後、アプリへ戻り再接続する。アプリだけのコピーで利用でき、開発用Pythonは不要。

既存データを移し替えず、InstagramのKeychain service `BeeperLocalInstagramIntegration.v1`と`~/Library/Application Support/BeeperLocalInstagramIntegration/messages-v1.sqlite3`を引き続き利用する。LINEの保存先・鍵は変更しない。旧`instagram-integration/BeeperLocal.app`は過去版として残っているが、通常の起動先はプロジェクトの1つ上にある`BeeperLocal.app`に統一する。

## Slack・X・Messenger

SlackのブラウザOAuthは公開設定が未完了で、新規ログインのボタンは理由を表示して無効にする。既存のKeychain連携は再接続できる。X・Messengerは専用の本人ログイン画面を使う。Messengerは1対1テキストの受信・送信に対応し、過去の暗号化バックアップ復元は未対応。各サービスの取得範囲・制限はアプリ内の「使い方・対応範囲」にまとめている。

## AIクライアントとつなぐ

5サービスで利用できる。許可はサービスごとに独立し、初期ポートはLINE 28641、Slack 28642、Instagram 28644、X 28645、Messenger 28646。28643はSlack本人認証用。詳しくは [MCP_0_9_1.md](MCP_0_9_1.md)。

1. 「接続設定」→「MCP接続」を開き、「MCPを有効にする」を押す。
2. クライアント名を付け、許可する会話を選ぶ。閲覧・検索と送信は別々に許可する。送信は初期状態でOFF。
3. 「この権限で登録」で一度だけ表示されるトークンを、接続するAIクライアントへ設定する。
4. 接続方式はStreamable HTTP、URLは画面に表示された`http://127.0.0.1:28641/mcp`（初期ポート）。認証ヘッダーは`Authorization: Bearer <トークン>`。
5. 不要になったら登録済みクライアントの「取り消す」を押す。アプリ終了時もMCPは停止する。

AIクライアント側はカスタムBearerに対応している必要がある。OAuthによる自動接続には対応しない。特定の商用AI製品への設定は今回行っていない。秘密トークンをチャットやログへ貼り付けない。MCPは許可済みの保存データを読むため、選択して履歴取得していない会話や上限外の履歴が自動で揃うものではない。

送信を許可したクライアントは、アプリで毎回確認せず指定会話へ送信できる。GUIの選択会話は変えない。同一UUIDの要求は再送を抑止し、結果不明は自動再送しない。クライアントが別UUIDで同じ文章を指定することまで防ぐ仕組みではない。

## 保存管理

「保存管理」で保存を停止すると受信・履歴取得・送信が止まり、再起動後も停止を保つ。保存済みの閲覧・検索は続けられる。再開後は「LINE接続」から再接続する。「受信を停止」はその起動中の停止で、永続的な保存停止とは異なる。

保存期間は削除するまで。削除対象の確認を押すと保存を停止し、現在のLINEアカウントの対象件数を表示する。確認チェックと最終ボタンで削除する（有効期限2分）。会話・本文・取得記録・送信記録を削除し、MCPを止めてそのアカウントの権限を取り消す。他アカウント・他サービス・LINEログイン・共通の暗号鍵は残す。送信要求の内容を含まないhashは二重送信防止のため残す。削除後も保存は停止し、再接続すると直近履歴が再び保存される。

外部AIへ既に渡した内容、OSバックアップ、SSDの過去領域はこの操作で回収・完全消去できない。LINE側のメッセージを削除する操作でもない。

## 過去版で確認済みの範囲（0.8.0以前）

以下は過去版の証拠。0.8.7の試験結果とは分けて扱う。

| 確認 | 結果 |
|---|---|
| macOS `.app`ビルド | Tauri 2 + React + frozen Python Core + line-cli + Instagram adapterを同梱 |
| Macのウィンドウ起動 | 成功、最終配置の実アプリの画面を確認 |
| 開発用署名の整合性 | app全体にad-hoc署名し、`codesign --verify --deep --strict`成功 |
| Coreの自動テスト | Instagram統合で265件、キーチェーン・署名改善を含め280件成功。実サービス通信の証拠ではない |
| 画面の自動テスト | 0.8.0でChrome / Playwright 19件成功。架空データのみ |
| shell構文 / offline demo | 成功 |
| 0.8.0統合後の実LINE | 接続・会話45件・既存履歴・相手名・プロフィール画像・受信待機 |
| 0.8.0統合後の実Instagram | 接続・会話1件・履歴9件・ローカル検索1件・受信待機。実送信は未実施 |
| 同じアプリ内のサービス切り替え | Instagram → LINE → Instagramの往復に成功 |
| 同梱CoreのIPC `ping` | 成功 |
| MCPのローカルHTTP往復 | 独立公式SDKのmodern/legacy clientで4 tools、権限拒否・失効・body制限を確認。架空データのみ |
| 同梱Coreの実データ読み込み | Mac再起動後に会話500件・実履歴を表示、既存テスト文のローカル検索1件 |
| アプリからの実LINE接続 | 0.5.1で接続・履歴更新・受信待機を確認 |
| 0.5.1での実メッセージ送信 | ユーザー承認済みの宛先・本文で1回。LINEの受付成功と履歴表示を確認 |
| 0.5.1での再起動後の復元・検索 | 再接続・受信待機・テスト文の復元と検索1件を確認 |
| 0.5.1の相手側着信と返信 | ユーザー報告で着信・返信受信・順番が正常と確認。基本送受信はCLOSED_BY_USER_REPORT |

テストは、送信前の永続記録、同一requestの再実行抑止、クラッシュ後の未確定状態、誤った宛先・accountの拒否、暗号化と改ざん検知、会話切り替え・検索・下書き分離を含む。従来の送受信の実機結果は`desktop-0.5.1-post-reboot-verification.json`。0.6.0の配布・読み取り確認は`desktop-0.6.0-verification.json`。0.7.0の初回連携・実一覧46件・画像確認は`desktop-0.7.0-verification.json`。基本送受信はユーザー報告を含めて確認済み。再起動・検索の実測対象は送信テスト文で、特定の返信に対する同じ確認ではない。長時間運転、強制ログアウト、全履歴同期は引き続き別の確認項目。

## 開発と再ビルド

必要な開発環境はApple Silicon Mac、Xcode Command Line Tools、Rust、Node 20.19以降または22.12以降、Python 3.13、Go 1.26以降。LINE CLIはvendor/line-cliの固定ソース（v0.4.0 + desktop拡張）、Instagram adapterはinstagram-adapter/metaの固定ソースからビルドする。各ライセンスと出典をappへ同梱する。実行ユーザー向けの依存ではなくビルド時の依存。

`app/`を作業ディレクトリにする。[公式Python 3.13.12 macOS installer](https://www.python.org/downloads/release/python-31312/)をダウンロードする。`prepare-release-python.py`にその保存先を渡す。スクリプトは公式SHA-256を検証し、プロジェクト内の`.build-python/`と`.release-venv/`へ展開する。macOSへのインストール、既存Python、既存venvの置換は行わない。公式frameworkの絶対リンクも展開先に対して修正する。

```bash
python3 scripts/prepare-release-python.py /path/to/python-3.13.12-macos11.pkg
.release-venv/bin/python -m pip install -r requirements-desktop.txt -c requirements-desktop-constraints.txt --cert /etc/ssl/cert.pem
npm --prefix desktop ci
bash scripts/build-desktop.sh
```

出力先は`desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app`。このMacの0.9.2ビルドは公式Python 3.13.12、Node 22.22.0、PyInstaller 6.22.3。npmとCargoのlockfile、Pythonのバージョン制約を同梱するが、Pythonの推移依存はhash-lockではない。GUI未対応のTelegram SDKはdesktop成果物から除外する。CLIソースのTelegram対応は維持する。

ビルドは`.release-venv/bin/python`を使う。`BEEPERLOCAL_BUILD_PYTHON`で変更できるが、最終的なアプリ本体と圧縮Core内部のarm64・最低OS・外部ライブラリ参照の検査を必ず通す。Homebrew Pythonをそのまま同梱するとビルドMacのOSを要求し得る。Go/cgoもmacOS 13 targetを明示する。最低OSの静的検査は、macOS 13実機での動作確認の代わりではない。

```bash
.release-venv/bin/python -B -m unittest discover -v
npm --prefix desktop test
```

画面テストはローカルにインストールされたChromeを利用する。開発用`npm --prefix desktop run dev`の`?demo=1`は架空データ専用。製品ビルドではこの経路を除去する。

アプリを終了した状態で、実送信なしの接続確認を行うには:

```bash
python3 scripts/desktop-smoke.py desktop/src-tauri/target/release/bundle/macos/BeeperLocal.app
```

結果には固定code・件数・boolだけを出し、本文・相手名・検索語・認証情報は出さない。UIで同じCoreが起動中の場合は多重起動ロックで拒否される。

Developer ID署名の工程は実装済み。リリース候補は `bash scripts/build-desktop.sh --release` で作成し、証明書がなければ停止する。Apple公証と別Macでの初回起動、自動更新は別の未完了項目。設計の詳細は[ADR_DESKTOP.md](ADR_DESKTOP.md)。

過去の共有用ZIP: `releases/BeeperLocal-0.7.0-AppleSilicon.zip`（Instagram統合前）。現在の配置先・候補版の場所・署名検証の結果はPROJECT_STATEで確認する。
