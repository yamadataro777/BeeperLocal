# 通信経路の確認 — Desktop 0.7.0

2026-09-30。実装の静的確認、架空データの実HTTPテスト、Mac実機確認を分けて記録する。

| 経路 | データ | 宛先・制約 | 確認 |
|---|---|---|---|
| Tauri画面 → Rust | 固定typed request、画面データ | main window限定のIPC。外部fetchを許すCSPなし | `tauri.conf.json`、`main.rs`、production JSを確認 |
| Rust → frozen Python Core | NDJSON request/event | 子processのprivate stdin/stdout。資格情報を引数にしない。stderrを閉じる | 固定allowlist、任意command/pathなし |
| Core → LINE adapter | 履歴/受信/送信、canonical MID | 同梱line-cli v0.4.0。本人sessionはmacOS Keychain | `connectors/line.py`、同梱binaryのversion/hash。raw SDK例外や本文をログに出さない |
| Core → Keychain/SQLite | 認証metadata、DB鍵、暗号化payload | ローカルOS/ローカルfile | 平文canary不在、改ざん・鍵不一致・scope tests |
| MCP client → Core | Bearer、tool引数/結果、許可した会話 | 127.0.0.1のみ。Streamable HTTP。clientごとのaccount/会話/read/send制限 | 独立公式SDKから実socket往復、認証/Host/Origin/query/bodyの拒否 |
| 外部AI client → AI提供先 | 利用者が許可して取得した内容 | client側の設定・契約による。BeeperLocalから宛先を制御しない | 登録UIに処理・保存・回収不能の説明。今回外部AIへ実データ接続なし |

新しく追加したMCP/Core/画面に、運営会社のAPI・分析SDK・自動更新・外部fetch・telemetry送信を追加していない。MCP SDKにclient用HTTP等の依存は含まれるが、server実装はlocal listenerを作る。起動時のpackage診断もsocket/Keychain/DBへアクセスしない。

LINE通信は同梱line-cliに委譲する。LINE側の宛先制御、SDK内部のすべての分岐、OSサービスによる通信まで包括的に監査したものではない。パケットを含む配布物全経路のcapture、漏えいが絶対に起きない保証、一般配布の安全性を示す証拠ではない。今回の新規MCPについては実データtokenの発行・実メッセージ送信・実データ削除を行わず、架空adapterと一時DBで検証した。

固定依存: MCP 2.2.0、uvicorn 0.54.0、line-cli 0.4.0。Python推移依存の一覧は`desktop-0.6.0-python-dependencies.txt`。npm/Cargo lockfileを保存。Python推移依存の完全なhash-lock、Developer ID署名・公証、第三者セキュリティ監査は別工程。

## 0.7.0で追加した経路

- GUI → private IPC → Core → 同梱LINE CLIのQRログイン → LINE公式のログイン・スマホ承認 → native Keychain。生のQR URLや認証tokenはCoreへ返さず、描画用matrixとPINだけをprivate pipeで一時表示する。
- 名前と更新時刻: 同梱CLIのmessage boxesとGetContactsV2 → Core → 暗号化conversation metadata。友だち一覧への限定を解除し、名前でroutingしない。
- プロフィール画像: Core → `https://profile.line-scdn.net` + validated PicturePath。認証headerなし、redirect/proxyなし、512 KiB上限、PNG/JPEG/GIF/WebPのみ。GUIにはdata URIを渡し、WebViewの外部通信許可は拡張しない。
- 画像は起動中のメモリだけに最大128件保持。画面周辺の画像のみ要求し、同時通信4件、待機最大64件。停止・アカウント切替・終了時に取得を止めてcacheを破棄。
- QR/PINをMCP、ログ、DB、レポートに含めない。連携開始時にMCPを停止。古いアカウントのMCP grantを新しいaccountに転用しない。
- 同梱CLIは upstream v0.4.0 commit 80d945ba582c0d1a59dbb4054d5c11e567021ab6 + CLI層の拡張。生成暗号code・protocol・send処理は変更していない。出典とMIT licenseをbundleへ収録。
