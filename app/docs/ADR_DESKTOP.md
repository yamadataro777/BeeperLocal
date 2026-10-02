# ADR: デスクトップは固定Coreとprivate pipeで接続する

決定日: 2026-09-30

Tauri 2 / React / TypeScriptの画面と、既存Python Coreを同梱したmacOSアプリを作る。PyInstallerでCoreを単一実行ファイルにし、検証済みline-cli v0.4.0とともにTauri bundleへ入れる。providerの資格情報・セッション・メッセージDBはbundleに入れない。

## IPCと秘密情報

Rustが固定パスのCoreを子プロセスとして起動し、継承したstdin/stdoutのNDJSONだけで通信する。ローカルHTTP listener、任意shell command、UIからのファイルパス指定は提供しない。

Tauri commandは`core_request`だけ。requestは`Snapshot / Connect / Select / Messages / Refresh / Stop / Search / Send`のtyped enumに固定し、余分なfieldを拒否する。Pythonでも同じrequest schemaを検証する。`ping`は配布物の起動診断用で、UIには公開しない。

UIへはaccountでscopeしたopaque ID・本文・表示名・状態だけを返す。Keychain鍵、token、raw LINE MIDをIPC responseへ渡さない。画面はReactのtextとして描画し、外部HTMLを挿入しない。CSPとcapabilityはlocal main windowのevent listen/unlistenだけを許可し、外部HTTP・filesystem・shell pluginを公開しない。

本文・相手名・検索語をconsole、localStorage、ログ、エラーレポートへ保存しない。Core stderrはUIに表示せず、provider例外は固定codeへ変換する。保存先・暗号化方式・Keychain serviceは既存CLIと共通。

## 送信

送信直前に現在のaccount・選択相手を検証する。UUIDのrequest ID、本文、宛先、状態を暗号化した`outgoing_requests`へ保存してからproviderを呼ぶ。providerから受付が返った後、messageと受付結果を同一transactionで保存する。

同一request IDの再実行は既存結果を返すか`LINE_SEND_UNKNOWN`で止める。未確定の送信は再起動しても自動再送しない。送信受付後の保存失敗も、送信成功を失敗とみなして再送しない。UIは下書きを保持し、履歴確認を案内する。新しい明示的送信は別のrequest IDになるため、ユーザーが同じ文章を再度送ること自体を禁止するものではない。

ledgerの平文列はrequest IDのhash・providerだけ。本文、raw ID、状態、時刻は既存DB鍵で暗号化し、`BeeperLocalPoC/outgoing/v1/`をprefixとするAADを使う。DB全体暗号化ではなく、件数等のmetadataは残る。

## 受信と終了

選択中の1対1会話だけをwatchする。会話変更時は旧watchを終了し、generationとaccount・conversation scopeを確認して保存する。開始時と60秒ごとに直近100件のbounded recoveryを行う。履歴上限やcursorとDB commit間の非原子性を完全同期と表現しない。

Coreの多重起動はstate directory内の`flock`で拒否する。正常終了ではpipe EOFを受けてwatchを閉じる。SIGTERM/SIGINTでも終了処理を行う。異常終了時の外部process・長時間運転は追加の実機確認が必要。

## 参照

- [Tauri sidecar](https://v2.tauri.app/develop/sidecar/)
- [Phase-1暗号化のADR](ADR_PHASE1_PERSISTENCE.md)
- [履歴回収のADR](ADR_LINE_RECOVERY.md)
