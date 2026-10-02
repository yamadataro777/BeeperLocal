# BeeperLocal / LINE連携 調査コンテキスト

更新日: 2026-09-30  
用途: 次のChatGPT/Codex/開発セッションへの引き継ぎ用コンテキスト

---

## 1. プロジェクトの目的

Beeperのような統合メッセージング体験を、できるだけローカル実行・ローカル保存中心で作る「BeeperLocal」構想を進めている。

日本で使ってもらううえでLINE連携は必須条件と考えており、今回の最優先テーマは以下だった。

> **LINEをBeeperLocalへ実際に双方向接続できるかを、推測ではなく実機検証で潰す。**

Closed Loopの考え方を使い、

仮説 → 最小実行 → 外部（LINE server / 実アカウント） → 結果取得 → 継続/修正/撤退判断

まで閉じることを重視している。

---

## 2. 現在の結論

### 結論

**LINE連携のコア可否Gateは閉じた。**

実機で以下が成立した。

- LINEログイン
- アカウント情報取得
- Chat一覧取得
- リアルタイム受信
- 履歴取得
- 1対1 E2EE / Letter Sealing送信準備
- `TalkService/sendMessage` RPC生成
- Access Token / Cookie付与
- HMAC署名生成
- LINE serverへの`sendMessage`到達
- LINE serverによるrequest処理
- 正常recipientへの実送信
- 相手アカウントへの実配送
- CLI側success acknowledgement

最終実送信ではCLIに以下が表示され、実際に相手LINEアカウントへ届いた。

```text
Sent to UXXXX... · encrypted
```

したがって、

> **「BeeperLocalからLINEへ暗号化メッセージを送り、LINEから受信する」というコア経路は成立する。**

と判断してよい。

---

## 3. 現在の開発環境

### OS / Shell

- macOS
- zsh

### line-cli

利用中のCLI:

```text
line v0.4.0
```

Homebrewの実行バイナリ:

```text
/opt/homebrew/bin/line
```

### Go

当初Goが未導入だったが、Homebrew経由で導入済み。

確認済み例:

```text
go version go1.27.1 darwin/arm64
```

### 作業repo

現在使っているline-cli repoは一時clone由来。

当時のpath:

```text
/var/folders/5g/013fjts916x85frj1r2k4xjm0000gn/T/tmp.9Kn4VMknUp/line-cli
```

`git status`はcleanだった。

```text
On branch main
Your branch is up to date with 'origin/main'.

nothing to commit, working tree clean
```

※ tmp pathなので再起動等で消える可能性あり。今後は恒久的な作業repoへcloneし直す方がよい。

---

## 4. BeeperLocal側の既存PoC

BeeperLocal PoCではローカルDBがすでに動作している。

確認済み例:

```text
./run.sh db-status
local_db=OK | total=3
matrix: 1
slack: 2
```

DB:

```text
~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3
```

保存方針:

- message payload: AES-256-GCM
- key: macOS Keychain
- plaintext FTSなし

LINE connectorをこのローカルcoreへ接続するのが次の段階。

---

## 5. LINE側で実証済みのGate

| Gate | 状態 | 備考 |
|---|---:|---|
| Login | ✅ | 実アカウントで成功 |
| whoami / account取得 | ✅ | 成功 |
| Chat一覧取得 | ✅ | 約58 chats取得実績あり |
| Realtime receive | ✅ | 別アカウントからsentinel messageを受信 |
| History取得 | ✅ | raw `U...` MIDを直接指定すると成功 |
| E2EE送信準備 | ✅ | Letter Sealing chunks生成成功 |
| `sendMessage` payload生成 | ✅ | wire parse成功 |
| Access Token header | ✅ | dry-runで確認 |
| Cookie | ✅ | dry-runで確認 |
| HMAC署名 | ✅ | dry-runで確認 |
| sendMessage endpoint到達 | ✅ | negative-controlでserver response取得 |
| server側application validation | ✅ | invalid recipientでTalkException取得 |
| 正常Message server受理 | ✅ | 実送信成功 |
| 相手への実配送 | ✅ | 別LINEアカウントで受信確認 |
| CLI success response | ✅ | `Sent to U... · encrypted` |

---

## 6. 履歴取得で起きていた問題

### 当初症状

`line messages ...`が以下のgeneric errorになっていた。

```text
line: LINE request failed; check your connection and LINE account settings
```

### 重要な発見

名前指定では診断が進まなかったが、**LINEのraw Chat MID (`U...`)を直接指定すると履歴取得が成功**した。

実行イメージ:

```bash
/tmp/line-server-diag messages 'Uxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx' -limit 1
```

結果: 履歴取得成功。

### 現時点の解釈

- `getRecentMessagesV2`自体は壊れていない。
- raw MID直接指定なら動く。
- display name → MIDの解決経路、もしくは名前指定時の前処理は未解決。
- 本番BeeperLocalでは**LINE MIDをcanonical IDとして永続保存**し、通信キーにするのが安全。

### 重要

「名前resolverが原因」と完全確定したわけではない。

確定しているのは、

> raw `U...` MIDならHistoryが通る

という点。

---

## 7. line-cli内部で確認した主要送信経路

### `SendMessage`

概略:

```go
func (c *Client) SendMessage(reqSeq int64, msg *Message) (*Message, error) {
    resp, err := c.callRPC("TalkService", "sendMessage", reqSeq, msg)
    ...
}
```

### HTTP / RPC

`callRPC`系は最終的に以下へ進む。

```text
callRPC
→ callRPCContext
→ callRPCWithBaseURLContext
```

送信requestでは以下が設定される。

```text
Content-Type: application/json
User-Agent
x-line-chrome-version
x-line-application: CHROMEOS\t3.7.2\tChrome_OS
x-lal: en_US
x-line-access
Cookie: lct=<access token>
x-hmac
```

Base endpoint:

```text
https://line-chrome-gw.line-apps.com/api/talk/thrift/Talk
```

LINE Chrome互換fingerprintとして当時確認したもの:

```text
ExtensionVersion 3.7.2
Chrome 143系UA
x-line-application: CHROMEOS\t3.7.2\tChrome_OS
```

### HMAC

request bodyとpath + tokenからHMAC署名を生成し、

```text
x-hmac
```

へ設定してからHTTP送信する。

---

## 8. Session wrapper / error handling

### `Session.Do`

read-only向け。

```text
Do → do(..., retry=true)
```

### `Session.Mutate`

mutation向け。

```text
Mutate → do(..., retry=false)
```

mutationは「response loss時にすでにserver側で成立している可能性」があるため、**自動リプレイしない**設計。

これは送信テスト時に重要。

### generic errorの正体

`RemoteError.Error()`は下層のprotocol detailsをterminalに出さず、安全なgeneric messageへ丸める。

例:

```text
LINE request failed; check your connection and LINE account settings
```

そのため、下層原因を調べるには一時diagnostic buildが必要だった。

### Auth error分類

line-cliには概ね以下の分類がある。

- refresh required
- logged out
- request need login
- invalid sender key
- unauthorized status

今回のnegative-controlでは:

```text
server_auth=false
server_refresh_required=false
server_logged_out=false
```

が取れた。

---

## 9. 送信Dry-run検証

### 目的

実メッセージを送らず、正常なsend payload/HMACまで生成できるか確認。

### 方法

一時worktreeでのみコードをpatchし、

```text
HTTPClient.Do(req)
```

の直前で強制停止。

元repoは変更しない。

### 結果

```text
DRY_RUN_SEND_READY
network_sent=false
service=TalkService
method=sendMessage
wire_parse_ok=true
req_seq=1818704288
recipient_kind="U"
recipient_len=44
encrypted=true
chunks=5
content_type=0
body_bytes=402
auth_header=true
cookie=true
hmac_ready=true
hmac_len=44
```

さらに:

```text
DRY_RUN_OK
NETWORK_SENT=false
```

### この結果から確定したこと

- 実Chat MID認識
- Letter Sealing暗号化
- chunks=5生成
- Message payload生成
- `TalkService/sendMessage` wire生成
- Access Token header設定
- Cookie設定
- HMAC生成
- HTTP送信直前まで正常

---

## 10. Server Negative Control #1: null Message

### 目的

LINE serverへ`sendMessage`を実際に到達させるが、正常Messageは作らせない。

### wire

```text
[syntheticReqSeq, null]
```

HTTP前にこのwireであることをguardし、違えばabortする設計。

### 結果

```text
NEG_CONTROL_SERVER
server_response=true
http=500
envelope_parse_ok=true
envelope_code=99999
exception=""
exception_code=0
server_auth=false
server_refresh_required=false
server_logged_out=false
response_bytes=40
```

```text
NEGATIVE_CONTROL_OK
```

### 解釈

- `TalkService/sendMessage` requestがLINE serverへ到達
- LINE serverがJSON envelopeでresponse
- 認証失効ではない
- malformed/null Messageなのでserver-side failureしたのは想定内

---

## 11. Server Negative Control #2: invalid recipient

### 目的

**正常な暗号化Message objectを作った上で、recipientだけを無効MIDへ置換**し、LINE server側のapplication validationまで進むか確認。

### 固定invalid recipient

```text
U!BEEPERLOCAL_INVALID_RECIPIENT_DO_NOT_ROUTE!
```

実recipientが`sendMessage`へ流れないよう、HTTP直前でもguardした。

### 結果

```text
INVALID_RECIPIENT_SERVER
server_response=true
http=400
envelope_parse_ok=true
envelope_code=10051
exception="TalkException"
exception_code=0
server_auth=false
server_refresh_required=false
server_logged_out=false
response_bytes=160
```

```text
INVALID_RECIPIENT_CONTROL_OK
```

### 解釈

これはnull Message testより強い。

- Message object自体は正常に構築
- E2EE payloadも正常
- `sendMessage` handlerへ到達
- LINE側application layerがrecipient validationを実行
- invalid recipientとしてTalkExceptionを返した
- auth/session rejectionではない

`exception_code=0`は簡易parserで詳細codeを拾えていない可能性があり、重要視していない。

---

## 12. 最終実送信テスト

### テスト方法

自分で管理する別LINEアカウントの`U...` MIDをrecipientに使用。

テストメッセージ例:

```text
BEEPERLOCAL_E2E_TEST_20260930_01
```

実行:

```bash
line send "$TEST_CHAT" --text "$TEST_MSG"
```

### 結果

CLI:

```text
Sent to UIXXXX... · encrypted
```

実際に別アカウント側LINEへ届いた。

### 最終判定

**正常Messageのserver accept + 実配送まで実証済み。**

LINE send Gate = CLOSED。

---

## 13. Realtime receive

以前のPoCで別アカウントからsentinel messageを送信し、local clientでリアルタイム受信に成功している。

したがって現在は、

```text
LINE → Local Mac
```

も成立済み。

これと最終実送信結果を合わせると、

```text
LINE ↔ Local Mac client
```

の双方向コア通信が実証済み。

---

## 14. 現在残っている主要リスク / 未検証項目

### P0/P1候補

#### 1. Session persistence / 再起動耐性

- CLI再起動後もlogin不要で使えるか
- Mac再起動後もKeychain/session復元できるか
- 長時間停止→再開が安定するか

#### 2. Token refresh

- access token expiry時のrefresh
- refresh failure時の回復
- 長時間daemon運用での安定性

これは本番運用上かなり重要。

#### 3. MID resolver / display name handling

raw `U...` MIDならhistory/sendが通る。

名前指定の経路は未解決。

MVPでは内部DBにMIDを保存し、UI表示名と通信IDを分離すれば回避可能。

#### 4. Group Chat (`C...`)

未検証。

- group history
- group receive
- group send
- group Letter Sealing key
- key register / rotate

#### 5. Room (`R...`)

必要性含め未検証。

#### 6. Media

未検証。

- 画像
- ファイル
- スタンプ
- 動画
- 音声

#### 7. Unsend / reaction / read receipt

本番UXで必要なら後続検証。

#### 8. Rate limit / anti-abuse / account restriction

短時間PoCでは不明。

長期運用、複数アカウント、大量sync時のLINE側制限は別Gate。

---

## 15. BeeperLocalの推奨LINEアーキテクチャ

### 原則

**LINE MIDをcanonical IDとして保存する。**

表示名はmutable metadata扱い。

例:

```text
conversation.id          = Uxxxxxxxx... / Cxxxxxxxx...
conversation.displayName = "友人A"
connector                = line
```

### Mac-native connectorを推奨

今回のLINE sessionはmacOS Keychainやローカル環境に依存する。

したがって初期PoCではDockerへ入れず、

```text
LINE Connector (Mac native)
        ↓ localhost IPC/API
BeeperLocal Core
        ↓
SQLite
        ↓
UI
```

が安全。

Docker化は後でよい。

---

## 16. 次のClosed Loop

LINE可否調査は十分進んだため、次は「CLI単体」ではなく**BeeperLocal統合**へ進む。

### 次の仮説

> BeeperLocal UI/CoreからLINE connectorを通して、1通送信し、1通受信し、SQLiteへ保存できる。

### 最小実行

#### Outbound

```text
BeeperLocal UI / local command
→ BeeperLocal Core
→ LINE connector
→ line SendMessage
→ LINE test accountへ配送
→ message ID保存
```

#### Inbound

```text
LINE test account
→ realtime stream
→ LINE connector
→ BeeperLocal Core
→ SQLite保存
→ UI表示
```

### Closed条件

- UI/CoreからLINEへ1通送信成功
- 相手LINEで受信確認
- 相手から1通返信
- realtimeで受信
- SQLiteへ保存
- BeeperLocal UIで表示

ここまで通れば、

> **BeeperLocal LINE Integration PoC = CLOSED**

と扱える。

---

## 17. 実装優先順位

### Phase A: 1対1 text only

最初はこれだけでよい。

```text
Login/session restore
Chats/MID mapping
History sync
Realtime receive
Text send
SQLite persistence
```

### Phase B

```text
Group chat
Token refresh robustness
Reconnect/backoff
Deduplication
Message ordering
```

### Phase C

```text
Images/files/stickers
Reactions
Unsend
Read state
Attachments
```

---

## 18. 安全ルール / 今回学んだこと

### 1. interactive Terminalで裸の`set -e`を使わない

以前、diagnostic scriptでinteractive shellに`set -e`を入れ、期待されたfailure codeでTerminal/tabが終了した。

今後は禁止。

必要なら:

```bash
(
  ...
)
```

のsubshellを使う。

### 2. mutationは安易にretryしない

送信responseが失われた場合、server側では成立している可能性がある。

```text
send error
≠
未送信確定
```

まずhistory / recipient側を確認する。

### 3. Full-width spaceに注意

過去に:

```text
cd　/path
```

のような全角spaceで失敗した。

ASCII spaceを使う。

### 4. Terminalで`\n`は改行ではない

例:

```text
pwd \n git status
```

は別コマンドにならない。

複数コマンドは:

```bash
pwd && git status
```

などを使う。

### 5. 出力例をコマンドとして見せない

以前ユーザーが

```text
M pkg/line/client.go
```

のような「例示output」をcommandとして入力してしまった。

今後は

- `実行するコマンド`
- `期待される出力例`

を明確に分離する。

### 6. raw secretをterminalへ出さない

診断では以下を表示しない。

- Access Token
- Cookie
- HMAC本体
- raw response body
- message body
- 実MID全文（必要時のみユーザー自身のterminalで扱う）

表示するのは:

- HTTP status
- envelope code
- exception type/code
- bool classification
- byte length

程度。

---

## 19. 重要な技術的観察

### Letter Sealing

実送信で:

```text
encrypted=true
chunks=5
```

が確認され、その後実際に相手へ配送成功。

したがって1対1text E2EEの実装はPoCとして成立。

### line-cliのerror設計

内部protocol errorは安全のためgeneric messageへ変換される。

そのため「generic errorが出た」だけではserver failure原因を判断できない。

診断時はtemporary worktree + diagnostic buildが有効だった。

### temporary worktree方式

以下の運用が安全だった。

```text
original repo = clean
        ↓
git worktree add --detach temporary
        ↓
patch diagnostic code
        ↓
build /tmp/... binary
        ↓
run diagnostic
        ↓
worktree remove
        ↓
original repo remains clean
```

今後も破壊的diagnosticではこの方式を推奨。

---

## 20. いま「やらなくてよいこと」

以下はLINE接続可否を証明するためにはもう不要。

- LINE unofficial clientが全面的にblockedかを延々調査
- sendMessage endpointの存在可否を推測
- HMAC生成可否を推測
- Letter Sealing送信可否を推測
- 実配送可否を推測

すべて主要部分は実機で通った。

今後の時間は、

> **BeeperLocal統合 / session durability / group / media / product UX**

へ使う方がよい。

---

## 21. 現在のClosed Loop判定

### Loop: 「BeeperLocalでLINEを双方向接続できるか」

**Status: CLOSED / 仮説支持**

#### 仮説

BeeperLocalのローカルconnectorからLINEへ双方向接続可能。

#### 最小実行

line-cliを使った実アカウント検証。

#### 外部

LINE server + 別LINEアカウント。

#### 結果

- receive成功
- history成功
- encrypted send成功
- LINE server accept
- 別アカウント配送成功

#### 意思決定

**継続。LINE connectorをBeeperLocalへ統合する。**

---

## 22. 次セッションへの最短指示

次回ChatGPT/Codexに渡す場合、以下だけでも十分。

```text
BeeperLocalのLINE連携PoCでは、line-cli v0.4.0をmacOS上で使い、
Login / chats / realtime receive / history(raw U... MID) / Letter Sealing encrypted send / LINE server accept / 実配送
まで実機で成功済み。

最終実送信では:
Sent to U... · encrypted
と表示され、別LINEアカウントで受信確認済み。

raw U... MIDでhistory/sendは通る。display-name resolver経路は未解決なので、
BeeperLocalではMIDをcanonical conversation IDとして保存する。

次のClosed Loopは:
BeeperLocal Core/UI → LINE connector → LINE送信 → 返信をrealtime受信 → SQLite保存 → UI表示
を1往復通すこと。

Mac-native LINE connectorを推奨。Docker化は後回し。
Mutation sendはresponse loss時のduplicate riskがあるので自動retryしない。
```

---

## 23. 最重要まとめ

一文でまとめると:

> **LINEをBeeperLocalへつなげられるかという最大リスクは、1対1テキスト通信については実機検証でほぼ解消され、次の課題は「接続可否」ではなく「BeeperLocalへ安定統合すること」に移った。**

