# Messengerの端末状態と本文保存（2026-10-02）

本体統合の依頼に基づき、Phase 1のAES-256-GCM保存をMessengerへ拡張する。検証版の200件・4 MiBの本文保存方式を製品のメッセージDBとして流用しない。

## 保存先と既存端末の維持

- 新規に受信した本文・相手・provider側ID・会話名は、共通`UnifiedMessage` / `StoredConversation`に正規化し、`~/Library/Application Support/BeeperLocalMessengerIntegration/messages-v1.sqlite3`に暗号化保存する。平文FTSは追加しない。検索は最新10,000件をメモリで復号、最大50結果。表示は1会話の直近100件。
- 本体のDB鍵とアカウントmetadataはnative macOS Keychain `BeeperLocalMessengerIntegration.v1`。他providerの資格情報やDBは開かない。
- Messengerのcookies・端末鍵・ratchet stateは、登録済み端末のKeychain項目`local.beeperlocal.messenger-verification.v1` / `bounded-receive-state`を継続利用する。別項目へのdevice identityコピーや自動再登録はしない。
- 端末SQLiteはGoプロセスのRAM上だけで使用し、そのsnapshotをKeychainへ保存する。署名済みprivate stdin/stdout pipeでのみCoreと受け渡す。SDKの復号済み再配信バッファがsnapshotに一時的に含まれ得る。これを通常の本文履歴DBとは扱わない。
- 現行ソースは検証版の本文キャッシュを取り込まない。非空の旧`messages`が残る端末状態は`MESSENGER_DEVICE_INVALID`で拒否し、本文・鍵をそのまま保全する。現行受信checkpointにはsender/directionを必須とし、欠落を推測で補わない。0.9.5までは取込み処理があったが、2026-10-03の[開発方針](../../AGENT.md)により廃止した。

## 保存順序と停止

1. 受信checkpoint全体のprovider/account/conversation/message scopeとサイズを検証する。
2. 本文と会話をAES-GCM暗号化し、SQLiteへ同一transactionでcommitする。
3. 登録済みアカウントmarkerを暗号化private settingsへ保存する。端末状態が失われても初回ログインと誤認しない。
4. 端末snapshotとcookiesをnative Keychainへ更新し、同じbytesを読み戻して確認する。
5. その後にのみprivate pipeへACKする。Goは成功ACK後に正常受信callbackを返す。

DB・Keychain・protocol・アカウント・復号の異常では停止し、正常受信としてACKしない。DB commit後にKeychain保存が失敗しても本文は残り、再配信時は同一IDへupsertする。失敗を通信エラーへ読み替えて再試行しない。

初回の端末登録は本人が専用画面でログインした後だけ行う。登録前に`registration_pending`をKeychainへ保存する。登録結果不明、既存端末DBの破損、登録済みmarkerがあるのに端末状態が欠落している場合は自動再登録しない。ログイン更新は同じアカウントのcookiesだけを置き換え、既存端末鍵を保つ。reset/delete/ACL緩和の操作は提供しない。

通信終了・heartbeat timeoutに限り1/2/4/8/16/30秒、その後60秒間隔で受信を再接続する。明示停止・保存停止・終了時は再試行も中止する。Go側の自動再接続は無効にし、再接続ごとに最新のKeychain状態を読み直す。

本体と検証用PoCは共通の`session.lock`を使い、同じ端末鍵への同時書き込みを拒否する。ソース実行時は従来の`probe.lock`も取得する。古いコピーのPoCとの同時実行はサポートしない。

## 制約

Keychain snapshotは引き続き4 MiB未満の上限を持つ。端末状態の大規模・長期運用向け保存方式が完成したとの判断ではない。上限到達時は鍵を切り捨てず停止する。DBとKeychainをまたぐ共通transactionはなく、強制電源断の全タイミングで欠落ゼロを保証しない。SDKが復号失敗時に行う再配信要求等は、正常本文の保存ACKとは区別する。

初期統合時点の取得対象は、この登録端末へ配送される通常の1対1E2EEテキスト。現在は1対1送信・取消反映・MCP・画像送信を追加済み（[INBOX](INBOX_0_9.md)、[MCP](MCP_0_9_1.md)、[画像送信](USER_FEEDBACK_0_9_3.md)）。グループ・消えるメッセージ・旧暗号化バックアップ復元・全会話/全過去履歴は保証しない。会話名は明示的なFacebook/E2EE thread mappingが取得できた範囲で表示し、不明なら「Messengerの会話」と表示する。別会話のIDを推測して結び付けない。

同梱messagixと専用GoアダプタのAGPL由来を保持する。商用配布の条件・適用範囲を解決済みとは扱わない。

## 0.9.0での拡張（2026-10-03）

保存形式・native Keychain・端末の排他制御・checkpoint ACKの境界は維持する。登録済みaccount markerは受信本文の取り込み前に保存する。本文・会話・取消ルール・未読はSQLite transactionでcommitし、その後に端末snapshotをKeychainへ保存・読み戻し、最後にACKする。markerだけの保存成功を受信成功とは扱わない。

1対1送信は既存接続へ要求し、共通の暗号化outboxを送信前に保存する。送信後のratchet stateと結果をcheckpointで保存してから完了を返す。不明結果は再送しない。認証済み送信者の自己取消は対象scopeと本文の送信者を照合し、先行した取消も保存して後着の本文が表示されるのを防ぐ。

保存済み履歴を100件ずつ過去へ表示できる。本人確認付きのローカル削除は暗号化DBの本文・会話・権限を対象とし、端末Keychainを書き換えない。cookies・端末snapshot・登録markerを保つ。旧Keychain本文キャッシュの削除処理も2026-10-03に廃止した。DB/Keychainの非原子性と4 MiB上限は残る。詳細は[0.9.0の範囲](INBOX_0_9.md)。

## 会話選択（2026-10-03）

選択会話はアカウントごとに暗号化DBへ保存する。旧Keychain選択の自動取込みは行わない。現行選択は再起動で復元し、会話切替によるKeychainアクセスを発生させない。
