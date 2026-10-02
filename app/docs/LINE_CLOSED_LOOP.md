# LINE 1対1 text Closed Loop

更新: 2026-09-30

実装本体: `~/Downloads/BeeperLocal_PoC_v0.4_Phase1`

**手動の実機1往復はCLOSED（ユーザーの全手順成功報告に基づく）**。以下の自動回帰コマンドを追加済み。自動コマンド自体の新たな実配送テストはこの実装作業では行っていない。
LINE単体のlogin・history・encrypted send・別アカウントへの実配送・realtime受信はユーザーが検証済みで、再調査対象ではない。

## 既存構造と今回の差分

```text
run.sh → Python cli.py → get_connector()
                         ├─ MatrixConnector / SlackConnector（変更なし）
                         └─ LineConnector → Macのline-cli v0.4.0
                                            ├─ send --stdin --json
                                            └─ watch --json（NDJSONをprivate pipeへ）
       Core ← UnifiedMessage ← normalize_line()
         ↓
       EncryptedMessageStore.upsert()
         ↓
~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3
         ↓
       db-status / search --provider line
```

- 共通`Connector`は既存のlist/fetchを維持。送信・購読は任意の`LiveTextConnector` capability。
- LINEの`conversation.id`と`locator.mid`はraw MID。表示名は既存modelの`title`（UnifiedMessageでは`conversation_title`）というmutable metadata。大文字小文字も変更しない。
- LINEは1アカウント・選択済みDM 1つ・textのみ。C/R MIDや自分自身宛てを拒否。Group、添付、スタンプ、reaction、read receipt、unsendの機能追加はない。
- 既存AES-256-GCM payload、KeychainのDB鍵、schema v1、安定message hashを再利用。既存v1 messagesは維持し、暗号化conversationsテーブルを追加。Matrix/Slackも取得batchへ共通会話metadataを添付する。run.shは変更不要。
- `sync`省略時と`proof`は従来どおりMatrix+Slack。`sync line`と`fetch line`はLINE単独。単独LINEの成功で既存2-provider GateをCLOSEDにはしない。

## 最小の自動回帰確認

実行するコマンド:

```bash
./run.sh line-e2e
```

既存セッションを復元し、未選択なら相手を一覧から選ぶ。1通だけテスト文を送り、相手が**届いた全文をコピーして返信**すると、realtime受信→UnifiedMessage→暗号化保存→DBを開き直して検索、まで確認する。

出力例（実行しない）:

```text
line_e2e=CLOSED | realtime_reply=PASS | local_search=PASS
```

過去の返信、送信echo、他の会話ではCLOSEDにならない。最大300秒、`--timeout 600`で延長可能。本文やMIDは出力しない。

1回の起動で送信は最大1回。専用のresume状態は保存しない。**再実行は新しいテストを1通送る操作**なので、エラーや中断後は相手側で前回の送信結果を確認してから判断する。自動再送は行わない。

通常の`daemon line`が動いている場合は先にCtrl-Cで止める。line-cliのwatchは同時に1つだけ。

通常利用はREADMEの`select / send / daemon / conversations / messages`を使う。自動回帰テストは通常運用を置き換えない。

## Terminalで実行する手順

既存の単体`line watch`は先にCtrl-Cで停止する。line-cliはwatchを同時に1つだけ起動できる。
以下のコードブロックで「コマンド」と記したものだけを実行する。本文・MID・tokenをチャットへ貼らない。

### 1. Terminal A: 実装本体へ移動

コマンド:

```bash
cd "$HOME/Downloads/BeeperLocal_PoC_v0.4_Phase1"
```

### 2. Terminal A: DBの現状を確認

コマンド:

```bash
./run.sh db-status
```

既存Matrix/Slack件数を控える。これは実機DBを開く確認でもある。

### 3. Terminal A: 検証済みline-cliセッションをCoreへ登録

コマンド:

```bash
./run.sh login line
```

既存セッションのwhoamiを確認しaccount MIDだけをBeeperLocal Keychainへ登録する。新規LINEログインは行わない。認証情報やMIDは表示しない。Keychainダイアログが表示されたらMacで操作する。

### 4. Terminal A: 送信先の別LINEアカウントを登録

コマンド:

```bash
./run.sh select line
```

現在は相手一覧から番号で1人を選択する。ユーザーがMIDを調べる必要はない。内部では選んだraw MIDを通信・保存に使い、表示名resolverで送信先を決めない。Coreが送る対象はこの1会話だけ。

### 5. Terminal A: realtime受信を開始して起動したままにする

コマンド:

```bash
./run.sh watch line --from-now --timeout 600
```

出力例（実行しない）:

```text
line_watch=STARTING | 選択した1対1会話のtextを暗号化保存します。
```

STARTINGは子プロセス起動準備を示し、サーバー接続完了を保証しない。Terminal Bへ進む。`--from-now`は今回の新規往復用で、line-cliの既存resume位置を破棄する。普段の再開時は省略する。

### 6. Terminal B: Coreから1通だけ送信

コマンド:

```bash
cd "$HOME/Downloads/BeeperLocal_PoC_v0.4_Phase1"
```

コマンド:

```bash
./run.sh send line
```

非表示入力へ今回専用の識別文を入力してEnterを押す。例: `BEEPERLOCAL_CORE_20260930_01`。本文を引数へ渡さない。

出力例（実行しない）:

```text
line_send=ACKNOWLEDGED | encrypted=true | local_store=WRITTEN | inserted=1
```

watchの送信echoが先に保存された場合はinserted=0にもなる。ACKNOWLEDGEDはLINEの成功応答であり、別アカウントでの実配送確認とは別。

`LINE_SEND_UNKNOWN`または送信中にCtrl-Cとなった場合は、送信済みの可能性がある。**同じsendを繰り返さず**相手側を確認する。`LINE_SENT_NOT_STORED`は送信成功後のDB保存失敗なので、sendせずDB修復後の`sync line`で回収する。

### 7. 別LINEアカウントで受信を確認し、新しいtextを返信

別アカウントで手順6の識別文が届いたことを確認する。その後、同じトークへ普通のtextを1通返す。
返信の例: `BEEPERLOCAL_REPLY_20260930_01`。スタンプや画像ではなくtextを使う。

Terminal Aの出力例（実行しない）:

```text
line_realtime=STORED | direction=incoming | inserted=1 updated=0
```

この表示はrealtimeイベントをUnifiedMessageへ変換し、DB commitを完了した後にだけ出る。outgoing表示だけでは返信受信を満たさない。600秒で停止した場合はwatchを再開してから返信する。

### 8. Terminal B: 保存件数と返信の検索を確認

コマンド:

```bash
./run.sh db-status
```

出力中に`line: 2`以上があり、既存Matrix/Slack件数が維持されていることを確認する。既存LINE行がある場合は全体件数を参考にし、次の検索で今回の返信を確認する。

コマンド:

```bash
./run.sh search --provider line
```

非表示入力へ手順7の返信の識別文を入力する。

出力例（実行しない）:

```text
local_search: matches=1 scanned=2
2026-09-30T... [line] message=... [本文非表示]
```

matches>=1なら既存BeeperLocal検索から確認できた。返信本文を画面で確認したい場合だけ`./run.sh search --provider line --preview`を使う。これは明示的な本文表示で、通常ログではない。

Terminal AをCtrl-Cで停止しても保存済みデータは残る。同じsearchをもう一度実行し、再open後にも見つかることを確認できる。

## CLOSEDの証拠

次の全項目を今回の新規往復で確認してからCLOSEDへ更新する。

1. Core `send line`がACKNOWLEDGED。
2. 別LINEアカウントで今回の識別文を実際に受信。
3. 別アカウントから今回の返信を送信。
4. watchがincomingを取得。
5. normalize_lineでUnifiedMessageへ変換。
6. 指定の既存DBへcommit（4〜6は`line_realtime=STORED direction=incoming`）。
7. 別プロセスの`search --provider line`で今回の返信がヒット。

unit test、historyによる回収だけ、古い行の件数、LINE単体の過去実績だけではこのLoopを閉じない。

## 回収と制限

コマンド（送信を繰り返さずread-only historyを回収）:

```bash
./run.sh sync line --limit 10
```

- line-cliのwatchはJSON出力後に独自cursorを進める。SQLiteのcommitとは原子的でないため、出力〜DB保存の間のクラッシュで保存漏れがあり得る。その場合は上記syncで回収する。今回はACK付きIPCや永続受信queueを追加していない。
- 同一provider/account/conversation/message IDをupsertするのでhistory・送信echo・realtime再配信は同じ行になる。
- 送信ACKにserver timestampは含まれないため、初回outgoing保存時刻はローカル送信開始時刻。後のhistory/live echoでserver時刻に更新される。
- 送信を自動再試行しない。line-cli内のread-only refresh/reconnectは既存動作を使用。
- stderrは継承せず破棄。本文はstdin、JSONはprivate pipe。raw MIDはline-cliの必須argvであり同一OSユーザーのprocess inspectionからは隠せないが、shell history・レポート・デバッグログには出さない。
- LINE sessionは既存line-cliのmacOS Keychainに残す。BeeperLocal側にはaccount IDと選択会話だけをKeychain保存。cookie/token/HMACをコピー・表示しない。
- line-cliがLetter Sealing利用不可と判定するとplaintextへfallbackする既存動作がある。CoreはACKの`encrypted`を正直に表示する。今回の検証済み相手では`encrypted=true`を確認する。
- line-cliのJSON契約はローカルv0.4.0実装で確認。バージョン変更時はadapter互換性の再確認が必要。

会話catalogの`--refresh`は現状最大500件です。既存`select`の一覧上限は既定100件、`--list-limit 500`で拡大できます。`messages`はproviderの最新10,000行を復号して選択会話を抽出する、Phase-1の件数上限を持つローカル読み出しです。
