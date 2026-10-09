# ADR: Phase 1は平文FTSより先に暗号化payload保存＋メモリ検索を採用する

決定日: 2026-09-27。現行DBの開発方針を2026-10-03に更新。

## 現行schemaの扱い

新規DBは8テーブルと必要なindexを一括作成する。既存DBはschema version・全テーブルの列・鍵fingerprint・scope index値を検証し、旧形式は `LOCAL_DB_SCHEMA_UNSUPPORTED` で停止する。起動時のALTER、欠落テーブルの補完、既存本文の復号によるscope書換え、versionの上書きを行わない。非対応DBを勝手に初期化しない。[開発方針](../../AGENT.md)。

以下の背景と次Gateは9/27時点の記録。現在の実機検証状態は [PROJECT_STATE](PROJECT_STATE.md)。

## 背景

Phase 0では、MatrixとSlackから実メッセージを取得・正規化・統合できることが実機で確認できた。次の目的は、再起動後にもメッセージを使えるローカル永続化と検索を成立させること。

一方、通常のSQLite + FTS5へ本文をそのまま入れると、`messages.db`やFTS indexに本文が平文で残る。Local-firstを掲げるアプリとして、UIを作る前にこの境界を決める。

## 決定

Phase 1では以下を採用する。

1. メッセージpayloadをJSON化する。
2. 256-bitランダム鍵をmacOS Keychainに保存する。
3. 各messageごとにランダム96-bit nonceを生成し、AES-256-GCMでpayloadを認証付き暗号化する。
4. Associated Dataに安定message IDを結びつけ、ciphertextの取り違えを検出する。
5. SQLiteにはmessage hash、会話scopeのhash、provider、timestamp、ciphertextを保存する。
6. plaintext FTS indexは作らない。
7. 検索時は最大10,000件を時系列順に読み、payloadをメモリ上で復号して部分文字列検索する。
8. 検索語はCLI引数にせず、TTYの非表示入力で受ける。shell historyへの残存を避ける。

## 理由

この段階の主要目的は「再起動後の永続化」と「local searchが成立するか」の検証であり、大規模検索性能ではない。メッセージ数が少ない段階で平文FTSを導入するより、データ保護境界を先に固定する。

また、SQLCipherを即座に採用するとビルド・配布・ネイティブ依存が増える。Phase 1ではPython `cryptography`のAESGCMを使用し、DB本体の全文暗号化を将来の独立Gateに残す。

## 明示的な制約

これはDB全体暗号化ではない。provider名、timestamp、message IDのSHA-256 hash、レコード件数等のmetadataはSQLite上で見える。ファイル名・サイズ・更新時刻もOSから見える。

OS swap、クラッシュダンプ、実行中プロセスのメモリ、`--preview`のTerminal表示までは保護しない。Keychain鍵へアクセスできる同一ユーザー環境の悪性コードから完全隔離するものでもない。

## 検索方針

Phase 1の検索は日本語の形態素解析やranked retrievalを行わない。Unicode文字列の単純な部分一致。英字は`casefold()`する。10,000件を超える運用になったら、SQLCipher・暗号化検索index・blind index等を別途比較する。

## 次Gate

実機で以下を確認する。

- `sync --limit 1`でMatrix+Slackの実メッセージが暗号化DBへ保存される。
- 同一messagesを再syncしてrow数が増えずupsertになる。
- プロセス終了後の`db-status`で同一DBを再openできる。
- 実本文の既知語を`search --preview`で見つけられる。
- DBファイルを文字列検索して本文が平文で含まれないことを確認する（自動fixtureテスト済み、実データは本文を外部へ出さずローカル確認のみ）。
