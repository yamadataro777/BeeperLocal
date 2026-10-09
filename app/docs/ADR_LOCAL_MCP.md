# ADR: scoped local MCP and bounded LINE reconnect (0.6.0)

日付: 2026-09-30。LINEの同期・再接続安定化と権限付きローカルMCPの実装をユーザーが選択したため追加。既存のGUI、Core、暗号化DB、送信ledgerを共有する。

## Transport / trust boundary

公式Python SDK `mcp==2.2.0`、`uvicorn==0.54.0`。MCP Streamable HTTPを127.0.0.1だけにbindする。初期状態は無効、明示的な有効化とclient登録が必要。UIのprivate pipeとは別の入口であり、HTTPに管理操作・資格情報操作・任意コマンドは公開しない。

client毎に256bitランダムBearer tokenを発行し、発行時のprivate IPC応答に一度だけ返す。保存するのはSHA-256 hashとclient名・account・会話・read/send権限・日時。既存AES-GCM鍵で暗号化し`private_settings`へ保存する。設定も暗号化する。AADは他のpayloadと分離する。元のv1形式は変更せず、追加テーブルだけを作る。client名は利用者による登録名であり、使用プロセスやAI製品の認証済み名称ではない。

HTTP毎に認証する。Coreのtool処理でも現在account、権限、会話を検証し、sendでは外部へ発行する直前にも再検証する。HTTP Hostは`127.0.0.1:設定ポート`だけ。Origin付き要求、Forwarded/X-Forwarded-*、URL query、重複認証ヘッダー、96KiBを超えるbodyを拒否。proxy解釈・CORS・HTTPアクセスログは無効。Core入口でSDK/Python loggingも無効化する。clientへ返す例外は固定codeだけ。

これは手動Bearer設定を使うローカル認証であり、OAuthの自動登録・自動認可には対応しない。対応clientにはStreamable HTTPとカスタムAuthorizationヘッダーが必要。LAN・トンネルへ公開する設計ではない。同一Macの悪意あるコード、OS管理者、debuggerからの完全隔離は提供しない。

## Tool contract

- `list_conversations()` — 許可した保存済み会話のopaque IDと名前。
- `get_messages(conversation_id)` — 許可会話の保存済み直近100件まで。
- `search_messages(query)` — 保存済み最新10,000件の走査範囲のうち、許可会話だけを検索。最大50結果。未許可の件数・本文を返さない。
- `send_message(conversation_id, text, request_id)` — 許可した固定宛先へ送る。request_idは正規形のUUID。GUIの選択・watch宛先は変更しない。

resources/promptsは空。一覧・検索はaccountと会話の許可を通ってから結果を構築する。message本文は信頼しないデータとして説明する。read権限とsend権限は独立し、送信の初期値はOFF。利用者が送信を許可したclientに毎回のGUI承認を追加しない。外部AI側の処理・保存と回収不能について登録画面に説明する。

request_idはclient IDとともにUUID5で名前空間を分け、共通の暗号化送信ledgerへ記録してから外部へ送る。同じUUID・内容は再送しない。同じUUIDで内容が違えば拒否する。結果不明は再起動後も再試行しない。LINE受付と相手の着信・既読は区別する。

## Storage control

永続的な保存停止ではwatchと履歴回収を止め、connect/refresh/sendと取得後の保存を拒否する。すでに外部へ発行済みの送信結果だけは、二重送信を防ぐためledgerへ記録する。保存済みの閲覧・検索は可能であり、MCPのreadも止めたい場合はMCP停止または権限取り消しを行う。

削除対象確認では保存を停止し、処理中の送信結果を待って件数を表示する。account・件数と結び付いた120秒のnonceで最終確認を行う。現在のLINE accountのmessage/conversation/receipt/outboxとclient権限を1 transactionで削除し、MCPを停止する。他account・他provider・共有DB鍵・LINE sessionは保持する。検索走査の10,000件上限は削除には適用しない。

削除された送信要求のhashだけを`retired_requests`へ残す。これは本文・宛先を含まず、同じrequest_idによる再送を防ぐため。SSDの過去ブロック、OSバックアップ、既に外部AIへ渡した内容の消去は保証しない。

## Reconnect boundary

選択中の1会話だけをwatchする。一時的なLINE/network失敗・EOFは1,2,4,8,16,30秒の上限付き再接続。再接続前、watch開始後、約60秒ごとに直近100件を再取得し、message/catalog/receiptを原子的にupsertする。新着を受け取るか60秒以上継続した後は試行数をリセット。認証・復号・resync・保存エラー等は自動で無視せず停止する。会話変更・保存停止時には古い処理をcancelし、取得後もgenerationと保存状態を検証する。

line-cli v0.4.0はSQLiteのcommitを待つack契約を持たず、取得も最大100件。したがって大量欠落の完全回復、全過去履歴、削除/unsendの同期、cursorとDBの原子性は未提供。watchプロセスが起動した状態を「待機」と表示するが、providerがオンラインとackした保証ではない。長時間・実断線・スリープ・強制ログアウトは別の実機確認を要する。

## Verification and sources

`tests/test_mcp_controls.py`、`tests/test_mcp_http.py`は架空LINE adapterと一時DBを使用する。HTTPは実127.0.0.1 socketと独立した公式SDK clientを利用し、modern/legacy handshake、4 tools、空resources/prompts、拒否境界を確認する。`desktop/tests/settings.spec.ts`はChrome上の架空データで登録・token一度表示・取り消し・停止・確認付き削除を検証する。

参照: [公式Python SDK](https://github.com/modelcontextprotocol/python-sdk)、[MCP transport仕様](https://modelcontextprotocol.io/specification/latest/basic/transports)。実際の呼び出し契約はビルドに固定したSDKのローカルsourceで照合した。商用client全製品との互換性、OAuth、セキュリティ監査済みを意味しない。


## 2026-10-03: 0.9.1のサービス拡張

Instagram・X・Messengerへ同じMCP契約を適用。各Coreのsettings/grantsキーとportを分離し、28644/28645/28646を既定にする（28643はSlack OAuth）。旧設定からはstoragePausedだけを移行し、既存MCP設定・権限は引き継がない。閲覧はローカルDB限定で、get_messagesにscope検証付きbeforeカーソルを追加。送信は既存暗号化outbox・client別UUID名前空間を使用し、GUI選択を変えないexplicit send_toを各connectorへ追加する。

Instagramはセッションロック取得後、adapter生成後、およびsession_saved ACK前に権限を再確認。Xはaccount照合後とworker生成後、Messengerは既存セッションのwrite lock内で再確認する。発行済み送信の回収は保証しない。Messengerの既存deviceを増設・リセットせず、同じ受信プロセスから送る。設定画面は5サービスで共通化し、read/sendを分離、send初期OFF・会話初期未選択を維持。

[実装範囲・検証](MCP_0_9_1.md)。UI/UX調査による統合Inbox案は将来の表示変更であり、MCP許可範囲を自動拡大する根拠にしない。
