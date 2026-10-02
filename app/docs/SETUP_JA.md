# BeeperLocal v0.4 Mac setup

## 前提

- macOS
- Python 3.11+
- Matrix account（現在はAccess Tokenで接続済みでも可）
- Slack workspace + User OAuth Token

Telegram connectorもコードには残っているが、現在の既定proof/sync対象は **Matrix + Slack**。

## 1. setup

```bash
chmod +x run.sh
bash scripts/setup.sh
./run.sh doctor --check-keychain
```

v0.4では`cryptography`も導入される。

## 2. 既存v0.3から続ける場合

Matrix/Slack資格情報と選択会話はmacOS Keychainの同じserviceを使う。Keychain entriesが残っていれば再login/selectは不要。

確認だけする場合:

```bash
./run.sh proof --limit 1
```

Gate AはMatrix/Slack各1 real messageでCLOSED。各50件は`volume_loop_status`の別Gate。

## 3. login/selectが必要な場合

Matrix:

```bash
./run.sh login matrix
./run.sh select matrix
```

Slack:

```bash
./run.sh login slack
./run.sh select slack
```

Token/Password/API secretはChatGPTへ貼らない。

## 4. Phase 1: encrypted local persistence

```bash
./run.sh sync --limit 1
./run.sh db-status
```

`sync`は要求したproviderのどれかが取得/正規化に失敗した場合、そのrunでは部分保存しない。

保存先:

```text
~/Library/Application Support/BeeperLocalPoC/messages-v1.sqlite3
```

DB鍵はKeychainの`local-db-key-v1`。本文等はAES-256-GCM payload内。plaintext FTSは作らない。

## 5. local search

```bash
./run.sh search --preview
```

検索語は非表示プロンプトに入力するのでshell historyには残らない。`--preview`を付けるとmatch本文がTerminalに出る。画面共有等へ残したくなければ省略する。

Phase 1は単純substring search。日本語は入力した文字列をそのまま探す。形態素解析/ranking/semantic searchは未実装。

## 6. repeat sync / idempotency check

```bash
./run.sh db-status
./run.sh sync --limit 1
./run.sh db-status
```

同じprovider/account/conversation/provider-message IDは同じstable IDになるためupsertされる。まったく同じ2messageしかない場合、total row countは増えないはず。

## 7. local dataを削除

```bash
./run.sh reset-local
```

確認文字列`DELETE LOCAL`が必要。暗号化message DBとDB専用keyのみ削除し、Matrix/Slack provider credentialsは残す。

Provider credential自体をKeychainから消す場合:

```bash
./run.sh forget matrix
./run.sh forget slack
```

これはprovider側token revokeではない。必要なら各provider側でもsession/tokenを失効する。

## 主なエラー

| Code | 意味 |
|---|---|
| `CREDENTIALS_MISSING` | provider未login |
| `NO_SELECTION` | 会話未選択 |
| `MATRIX_ENCRYPTED_ROOM` | Matrix E2EE roomでPhase-1未対応 |
| `LOCAL_DB_KEY_MISSING` | 既存DBに対応するKeychain keyがない |
| `LOCAL_DB_KEY_MISMATCH` | DBとKeychain keyが一致しない。上書きしない |
| `LOCAL_DB_CORRUPT` | DB/ciphertext認証に失敗 |
| `LOCAL_DB_UNAVAILABLE` | DBを安全にopen/writeできない |

詳細は`docs/SECURITY.md`。
