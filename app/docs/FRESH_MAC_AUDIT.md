# 0.9.2 初回インストール再監査

2026-10-03 / Apple Silicon / このMacのmacOS 26.5.2でエージェントが観測。

**判定：一般配布は保留。** コード・ビルド上の問題を修正した0.9.2内部検証候補を作成した。Apple公証とSlackの公開認証設定が未完了で、別Macの本人ログインも未検証。過去の「署名済み」「空HOMEでping成功」は、その条件下の成功であり、初回インストール全体の成功ではない。

## 再現して修正した問題

| 問題 | 0.9.1での根拠 | 0.9.2の修正 |
|---|---|---|
| 表記はmacOS 13以降だが起動コードが26を要求する | メイン・補助実行ファイル8個とCore内87個を検査。LINE、Messenger、Python本体と標準ライブラリなど65個の最低OSが26.0 | Go/cgoのdeployment targetを13.0に固定。Homebrew版Pythonの同梱をやめ、同じ3.13.12の公式macOS配布からプロジェクト内だけに配布用環境を作成。全Mach-Oの最低OS・arm64・外部参照をビルドと梱包で検査し、不適合なら停止 |
| 再ビルド時の依存収集がビルドMacの別Python・Intel OpenSSLを混入させる | 新ランタイムの初回ビルドで追加検査が署名なしIntelライブラリを検出し停止。公式framework内のリンクもインストール済みPythonを参照していた | frameworkをビルドフォルダ内で完結するリンクへ修正。GUIが提供しないTelegram SDKをdesktop同梱から除外し、その任意SSL探索を収集対象から外す。CLI側のTelegramは維持 |
| 開発用CAがない新しいMacでHTTPSが失敗する | CAファイル・ディレクトリを存在しない場所にしたTLSハンドシェイクで、既存方式はSSLCertVerificationError。ユーザー認証やAPI呼出しは行わない | Slack API/OAuthとMatrixでmacOSの信頼ストアを直接使う。修正方式は同じ条件でSlack公開証明書を検証できた。未信頼の自己署名証明書を拒否するloopbackテストも成功 |
| Coreの起動失敗が画面購読より早いと原因を失う | Rustはfatalをイベントとして出すだけで、後からの要求には常にCORE_STOPPEDを返す。要求登録と終了にも競合があった | 終了原因と応答待ちを同じロックで管理。既存と後着の要求へ同じ原因を返し、最初の原因を保持 |
| 一つのサービスの接続待ちが全サービスの操作を止める | NDJSON読取ループが各要求を完了するまで次の要求を処理しない。Messenger接続は最大150秒待機 | サービス内の順序を維持しながらサービス間を並行処理。待機要求数に上限。更新準備は既存処理の終了を待つ。再起動時のサービス復帰も個別に開始 |
| Slack新規ログインが未設定でも「承認待ち」を表示する | 公開Client IDが空のままログインタスクを開始し、受信を止めた後で失敗 | 画面に未提供を表示しボタンを無効化。Coreでも開始前に設定を検査し、既存の接続を停止しない。Slack公開設定そのものは未完了 |

## 初回状態として確認した範囲

- 実Core・実暗号化SQLiteを、テスト専用の空ディレクトリ・空の資格情報境界で起動。5サービスの履歴なし、アカウントなし、MCP停止・権限なし、ログイン要求、設定表示、保存停止後の再起動を確認。
- LINE/Xの接続相手は未ログイン応答のfixture。Messengerは空のテスト用Keychainインターフェース、Instagram/Slackは空の資格情報。テスト中に本番Keychainや子プロセスへアクセスしたら失敗させる。これは新しいOSユーザーのKeychainの実測ではない。
- 画面は架空データ用の空状態。5サービスのログイン入口、キャンセル後の設定、MCP初期状態を確認。既存の検索・下書き・送信結果不明・権限分離も回帰検証。
- 署名後の配布物は、OS標準PATH、空HOME、日本語と空白を含む展開先で検査する。`HOME`を変えてもmacOS KeychainやWebViewの全状態は隔離されないため、認証情報を読む要求は実行しない。

## 確認結果

| 確認 | 結果 |
|---|---|
| Python Core | 489件成功。配布用の新しいPython環境で実行 |
| 画面 | Chrome / Playwright 65件成功。架空データ |
| 版番号更新後の画面再確認 | 初回状態・β版基本動作の16件成功 |
| Rust | 5件成功。IPC境界・起動エラー・署名付き更新検証 |
| 同梱されたCoreコード | 署名済み実行ファイルから32モジュールを読み出し、初回状態・サービス間並行処理・TLSの7件成功。資格情報はfixture、依存ライブラリはビルド環境 |
| macOS互換性の静的検査 | 8実行ファイル＋Core内85 Mach-Oすべてにarm64があり、最低OSは13.0以下。開発Mac固有のライブラリ参照なし。macOS 13実機の動作確認とは異なる |
| Developer ID署名 | 8実行ファイル＋Core内85 Mach-Oで成功。通常0.8.5との署名要件の相互互換性も成功 |
| 信頼済みTLS | 開発用CAを参照できない状態で公開サーバーの証明書検証に成功 |
| 未信頼TLS | 自己署名のローカルサーバーを拒否 |
| 署名・内部ランタイム・ZIP | 最終結果は `desktop-0.9.2-verification.json` と `desktop-0.9.2-package-verification.json` に記録 |

## 未完了の配布条件

1. **Apple公証。** 修正後の0.9.2でも `spctl --assess` は `rejected / Unnotarized Developer ID`、`stapler validate` はチケットなし。Developer ID署名だけでは新規Mac向け一般配布の条件を満たさない。公証済み成果物で再評価する。OS保護機能を無効化して代用しない。
2. **Slackの公開認証設定。** 公開Client ID、PKCEとリダイレクト設定、配布設定が必要。架空値を入れて有効にしない。設定後に新規ワークスペースの本人承認から再試験する。
3. **別Mac/別OSユーザーでの本人ログイン。** 空HOMEやfixtureでは、初回Keychain承認、アプリ隔離・初回起動、通知承認、サービス側の本人確認まで実証できない。macOS 13実機、実回線断、スリープ、長時間運転も未実測。
4. **新しい実送信・実MCPクライアント接続。** 今回は実メッセージを送信せず、本番MCP権限も発行していない。0.9.0/0.9.1の追加機能を含め、実サービス経路は別途確認する。

自動更新の公開先・公開鍵も未設定。手動で署名済みアプリを入れ替える配布方式は選べるが、その場合も公証と初回環境での確認は必要。

通常使用中の0.8.5アプリ、本番Keychain、メッセージDBは今回の検証で置き換え・削除・初期化していない。既存認証のログアウトやKeychain ACL変更も行っていない。

## 再検査と根拠

互換性検査は `scripts/macos_compatibility.py`。署名を変更せず、アプリ本体と圧縮Core内のMach-Oを検査する。Python準備は `scripts/prepare-release-python.py`。公式インストーラーのSHA-256を検証し、OSへインストールせずにビルド用フォルダへ展開する。

- [Python 3.13.12公式配布・macOS対応範囲とSHA-256](https://www.python.org/downloads/release/python-31312/)
- [Truststore：macOS Security frameworkを使うSSLContext](https://truststore.readthedocs.io/en/stable/index.html)
- [Apple：公証、notarytool、staplerの工程](https://developer.apple.com/documentation/security/customizing-the-notarization-workflow)

これらの資料は修正方式の根拠であり、別Macでの実行成功を示すものではない。
