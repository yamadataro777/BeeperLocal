# Matrix setup — current PoC

GitHub SSO等でMatrixパスワードを持たない場合は、Elementから自分のAccess Tokenを取得し、`login matrix`のAccess Token方式を使う。Tokenはチャットへ貼らずTerminalの非表示入力だけに入力する。

```bash
./run.sh login matrix
./run.sh select matrix
./run.sh fetch matrix --limit 1
```

Phase 0 Gate Aの疎通判定は実message >=1件でよい。50件はGate B（volume/pagination）の別検証。

Phase-0/1のMatrix connectorはE2EE room復号をまだ実装していない。`select matrix`では`[room]`の非暗号化roomを選び、`[encrypted-room]`は選ばない。

Phase 1の保存まで進める場合、MatrixとSlack双方の選択が済んでいれば:

```bash
./run.sh sync --limit 1
```

資格情報・選択roomはmacOS Keychainに保存される。message本文はsync前のfetchでは永続化されず、sync時は暗号化payloadとしてlocal SQLiteへ保存される。
