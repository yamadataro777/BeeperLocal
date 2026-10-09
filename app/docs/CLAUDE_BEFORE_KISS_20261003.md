# 過去の作業案内（現行指示ではない）

2026-10-03の整理前のCLAUDE.md。現行方針はルートのAGENT.md・CLAUDE.mdを参照。

# CLAUDE.md — BeeperLocal

LINE・Instagram・Slack・X Chatを1つのMacアプリに統合し、メッセージを端末内の暗号化SQLiteに保存・検索し、ローカルMCPでAIにつなぐ個人開発プロダクト。12/1販売予定（買い切り）。ユーザーとのやり取りは日本語。

## どこに何があるか

- `app/` — 本体ソース。作業は基本ここ。`app/AGENTS.md` の開発ルールも従う。
- `BeeperLocal.app` — ユーザーが普段起動する配置済みアプリ（0.9.5、公証済み、Slack公開設定を同梱）。`app/` からビルドしたものを置き換える。置換前に `archive/app-backups/` へ退避するのが慣例。
- `app/docs/PROJECT_STATE.md` — 実機検証の source of truth。`NEXT_IMPLEMENTATION.md`・`IMPLEMENTATION_PLAN.md` が現行計画。
- `docs/spec/` — 仕様 v0.1（現状と大きくずれている）。再設計案 v0.2 と販売リスク一覧はClaudeのドキュメント:
  - 設計 v0.2: https://claude.ai/code/artifact/5603a8ed-451a-4fdf-baf9-7f4928ea6351
  - 販売リスク一覧: https://claude.ai/code/artifact/8781c933-8365-463a-8909-3dc78a31fcad
- `workstreams/` — 未統合の並行作業（`x-integration-work` はX単体版と0.8.4統合検証の記録、`slack-integration-work` はSlack改善パッチ、`line-recovery-work` は0.8.3の検証）。本体へ取り込むときは差分を確認してから。
- `business/` — 販売サイト（`stripe-site-draft/`、公開中）とStripe申請メモ。
- `archive/` — 触らない。旧アプリ・統合前スナップショット・壊れた空git。

## 構成（app/）

- `beeperlocal/` — Python Core（3.11+、実ビルドは3.13）。`connectors/`（line, instagram, slack, matrix, telegram, `base.py`, `registry.py`）、`storage.py`（AES-256-GCM行暗号化SQLite）、`outbox.py`（送信台帳）、`mcp_server.py`/`mcp_access.py`（認証付きloopback MCP）、`desktop*.py`（GUI用Core。`desktop_router.py` がproviderごとに振り分け）、`cli.py`。
- `desktop/` — Tauri 2 + React 19 + TypeScript + Vite。`src-tauri/src/main.rs` がPyInstaller化したCore（`beeperlocal-core`）を子プロセスで起動し、stdin/stdoutのJSONで通信。要求は `CoreRequest` enumの許可リストのみ（Python側でも検証）。
- `vendor/line-cli/` — line-cli v0.4.0（Go、MIT）の固定ソース＋desktop拡張。Chrome拡張LINE 3.7.2として接続する。
- `instagram-adapter/meta/` — mautrix-meta由来（AGPL-3.0）のGoアダプタ。
- `tests/`（Python unittest）、`desktop/tests/`（Playwright、架空データ）。

## コマンド（app/ で実行）

```bash
.desktop-venv/bin/python -B -m unittest discover -v     # Core全テスト（2026-10-02最終確認410件）
.desktop-venv/bin/python -B -m unittest tests.test_line -v  # 単体ファイル
npm --prefix desktop test                               # 画面テスト（ローカルChrome使用）
npm --prefix desktop run build                          # tsc + vite
bash scripts/build-desktop.sh                           # Core/line/IG/XをビルドしTauriでapp作成・署名
./run.sh <cmd>                                          # CLI: doctor, sync, search, send, watch, db-status ...
bash -n run.sh scripts/*.sh                             # shell構文確認
```

ビルドには Python 3.13 の `.desktop-venv`、Node 20.19+、Rust、Go 1.26+ が必要（`docs/DESKTOP_APP.md`）。

**注意: `app/.desktop-venv` は壊れている。** venvは移動できない作りで、console スクリプト（`pip`, `pyi-*`, `activate`）のshebangに旧パス `~/Documents/ChatGPT/.../.desktop-venv/bin/python` が焼き込まれている（整理前からの状態）。`run.sh` 経由（`.desktop-venv/bin/python` → Homebrew Python へのsymlink）は動くが、`pip` やビルドの pyinstaller を直接叩くと失敗する。Mac上で作り直すこと:

```bash
cd app && rm -rf .desktop-venv && python3.13 -m venv .desktop-venv \
  && .desktop-venv/bin/python -m pip install -r requirements-desktop.txt
```

## 守ること

- **実送信はユーザーが宛先と本文を明示承認したときだけ、1回だけ。** 送信系の自動再試行は禁止。応答が失われても「未送信」とは限らない。まず履歴で確認する。
- **本文・相手名・ID・トークン・検索語をログ、レポート、ターミナル、チャットに出さない。** 診断は件数・固定コード・bool・HTTP status程度にする。
- 資格情報とDB鍵はmacOS Keychainのみに置く。ファイルや環境変数への退避は禁止。Keychainの迂回・ACL変更・DB/鍵のリセットは、ユーザーの明示指示なしに行わない。
- 平文FTSは追加しない（v0.2でSQLCipher+FTS5へ移る案があるが、ADR承認前）。
- モックや架空データの成功を実機成功として記録しない。PROJECT_STATEには「エージェントが観測した」「ユーザー報告」を分けて書く。
- ブラウザの資格情報の抜き取り、Discordのself-bot、認証回避はしない。
- 既存のLINE/Instagram/Slackの動作を壊さない。通常アプリを置き換える前に、Core全テスト・画面テスト・ビルド・署名検証を通す。

## ユーザーのMacで作業するとき

- 削除はできない（`rm` は不可）。不要物は `_to_delete/` へ移すか、ユーザーに頼む。
- 対話シェルで裸の `set -e` を使わない（ユーザーのTerminalが閉じた前例あり）。必要ならサブシェルで使う。
- パスに全角スペースが混じらないよう注意する（旧フォルダ名「BeeperLocal　検証」で失敗した前例）。
- ユーザーに実行してもらうコマンドは、「実行するコマンド」と「期待される出力」を分けて示す。

## データの保存先（実行時）

- LINE / Matrix / Slack: Keychain service `BeeperLocalPoC.v1`、DB `~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3`
- Instagram: Keychain `BeeperLocalInstagramIntegration.v1`、DB `~/Library/Application Support/BeeperLocalInstagramIntegration/messages-v1.sqlite3`

- X Chat（0.8.4で統合済み）: Keychain `local.beeperlocal.xconnector.v1`（元のセッション・鍵）と `BeeperLocalXIntegration.v1`（本体metadata・DB鍵）。保存先 `~/Library/Application Support/BeeperLocalXIntegration/`。X向けMCP未対応。実機と未確認範囲は `app/docs/desktop-0.8.4-verification.json`。

## 2026-10-02のX本文修正と並行更新

通常アプリ0.8.5はLINEメディア・Slackプロフィールに加え、X旧形式DMの本文表示修正も同梱済み（配置コード照合済み）。Xの件数重複をまとめる追加修正はapp/へ適用・検証済みで、次の本体ビルド待ち。`workstreams/x-integration-work/legacy-fix-0.8.5` は旧0.8.4基準のX検証専用コピーであり、新しい通常アプリへ置き換えてはいけない。次回配置は最新app/の並行変更を維持してビルドする。根拠は `app/docs/x-legacy-text-verification-20261002.json`。


## 2026-10-03のMCP拡張とUI/UX分析

app/の最新ソースは0.9.1候補。Instagram・X・MessengerにもMCPを追加し、5サービスの設定画面を共通化した。通常配置アプリは引き続き0.8.5で、候補を自動配置しない。現在のMCP範囲は `app/docs/MCP_0_9_1.md`、本家BeeperのUI/UXと将来の採用案は `app/docs/BEEPER_UI_UX_REFERENCE.md` を参照する。下の過去記録にある「X向けMCP未対応」は0.8.4/0.8.5当時の状態。統合Inbox等の提案はまだ実装していない。実送信・実データのMCP権限追加は今回実施していない。

## 2026-10-03の初回インストール再監査（0.9.2時点）

この監査時点のソースと署名済み内部候補は0.9.2。通常配置アプリは0.8.5を維持。一般配布はまだ保留で、Apple公証・Slack公開OAuth設定・別Macまたは別OSユーザーでの本人ログインが残る。詳細は `app/docs/FRESH_MAC_AUDIT.md` と `app/docs/desktop-0.9.2-verification.json`。空HOMEではKeychainは隔離できない。fixtureや資格情報を読まないruntime検査を新しいMacでのログイン成功と扱わない。

配布用ビルドではHomebrew Pythonを同梱しない。`app/scripts/prepare-release-python.py` で公式Python 3.13.12をOSへインストールせず展開し、`.release-venv` と `requirements-desktop-constraints.txt` を使う。現行ビルド手順は `app/docs/DESKTOP_APP.md`。最低OS・arm64・外部ライブラリ参照の検査はビルドと梱包の必須工程。上の `.desktop-venv` の記述は旧開発環境の注意で、現在の配布用手順ではない。


## 2026-10-03の利用者フィードバック（最新0.9.3候補）

最新ソース・署名済み候補は0.9.3。`dist/BeeperLocal-0.9.3-AppleSilicon-beta.zip`へ、対応ソース820ファイル・説明書・検証結果を同梱した。通常配置0.8.5は維持。5サービスの画像送信、相手アイコンの暗号化キャッシュ、Keychain重複確認の抑止、LINEログイン失効の状態通知／同期停止、Instagram公式サイトの専用本人確認ウィンドウを追加。詳しくは `app/docs/USER_FEEDBACK_0_9_3.md` と `PROJECT_STATE.md`。

現在の検証環境は `app/.release-venv/bin/python`（Python3.13.12）、Node22.22.0。Core515件、画面75ケース（74成功＋対象12件再実行）、Rust6件、関連Go試験、frozen Core33件／41モジュール、native IG境界チェックが成功。9実行ファイル＋85埋込Mach-O、通常版との署名互換性、macOS最低13.0設定、ZIP全24アプリファイル・対応ソース一致・展開後runtimeを検証した。

本家Beeper・Chrome版LINEとの同一アカウント並行利用は提供できない。切断表示修正をサーバー側の単一セッション制限の解消と混同しない。Instagramの新ウィンドウは本人が毎回新しい非永続セッションでログインする方式で、既存ブラウザのCookieは抽出しない。友人の実環境、画像の実着信、新IG本人認証、別Mac／macOS13実機は未検証。Apple公証・Slack公開OAuth設定も残り、一般配布は保留。

## 2026-10-03のKeychain反復修正・通常アプリ更新（最新0.9.4）

ユーザーのKeychain確認反復の報告を受け、Messengerの会話選択保存を既存の暗号化DBへ移した。会話切替からKeychainアクセスを除き、旧選択を資格情報の書換えなしで引き継ぐ。資格情報・DB鍵・端末情報の保管と受信commit/ACK順序は維持。通常配置に未反映だったGUI内Keychainキャッシュも今回含めた。

Core532件、対象GUI14件、署名済みCoreの実bytecode45件／43モジュール、shell8ファイル、offline demo、production buildが成功。10実行ファイル＋85内蔵binary、旧版との相互署名要件、最低OS13.0を確認。Apple公証Accepted・チケット・Gatekeeper検査を完了し、通常`BeeperLocal.app`を0.9.4へ更新した。旧0.8.5は`archive/app-backups/BeeperLocal-0.8.5-before-0.9.4-keychain-20261003T164956.app`に保全。26ファイル一致を確認。詳細は`app/docs/desktop-0.9.4-install.json`と`desktop-0.9.4-keychain-verification.json`。

更新時に利用者データやKeychainの値・ACLを操作していない。更新後の実アカウントでの確認反復は未検証で、初回のOS許可は本人操作。SlackはPKCE・12scope・token rotationを保存済みだが、HTTP redirectで外部配布を拒否された。追加した専用URL `beeperlocal://oauth/slack` の保存はユーザーの明示確認待ち。公開Client IDはまだ同梱していない。友人向けZIPは未作成、別Macで5サービスすべての本人ログイン・実送受信も未確認。

## 2026-10-03のSlack公開設定反映（最新0.9.5）

上の0.9.4時点で確認待ちだった専用URLへの変更を本人が承認した。Slackの保存済みmanifestで`beeperlocal://oauth/slack`・PKCE・12 user scopes・token rotationを確認し、Manage Distributionで外部ワークスペースへの配布を有効化した。公開Client ID `11683442969584.12190221092304`と配布設定確認フラグを0.9.5へ同梱。Client Secretは同梱しない。`app/docs/desktop-0.9.5-slack-configuration.json`に観測を記録。

Core532件・対象GUI19件・frozen Core45件／43モジュール・shell8件・offline demo・配布モードビルドが成功。10実行ファイル＋85内蔵binaryの署名、旧0.9.4との互換、空HOME・OS標準PATHでの5サービスIPCと同梱Slack設定を確認。native Slackウィンドウの起動・キャンセルを確認し、権限承認やトークン交換は行っていない。ウィンドウ検査時に通常GUIも一時起動したため、既存連携の自動読み込みはあり得る。検査後に終了し、残存プロセスなしを確認した。

新ビルドを改めてAppleへ提出し、Accepted・issue_count=0・SHA照合・チケット・Gatekeeperを確認。通常アプリを0.9.5へ更新し、旧0.9.4は`archive/app-backups/BeeperLocal-0.9.4-before-0.9.5-slack-20261003T170156.app`へ保全。配置26ファイルが公証済み成果物と一致。Slackの新しい本人認証の完了、別Macで5サービスすべての実ログイン・送受信・画像着信・スリープ復帰は未確認。現在の根拠は`app/docs/desktop-0.9.5-verification.json`と`desktop-0.9.5-install.json`。

`dist/BeeperLocal-0.9.5-AppleSilicon-beta.zip`に導入手順・対応ソース829ファイルを同梱し、展開後の全26アプリファイル・ソース一致・Go埋込素材23件・署名・公証・同梱Slack設定・空環境runtimeを確認した。検証は`app/docs/desktop-0.9.5-package-verification.json`。これは試用用の成果物で、別Macの5サービス実利用は未確認のまま。既存0.9.3 ZIPは更新していない。
