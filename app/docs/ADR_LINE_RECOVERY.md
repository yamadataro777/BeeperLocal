# ADR: LINE起動時のbounded history回収

決定日: 2026-09-30。L1の最初の実装。

## 問題

line-cliは自分の受信cursorを保存する。CoreのSQLite commitと同一transactionではないため、line-cliが進んでからCore保存前に終了すると欠落が残り得る。現在は手動`sync line`で直近履歴を取り直す運用。

## 決定

- 通常の`watch line` / `daemon line`は受信開始前に直近50件（CLI指定で1–100件）を回収する。
- `--from-now`は従来どおり現在から受信する明示操作なので、開始前の履歴回収を行わない。過去の回収記録は更新しない。
- 回収は選択済み1対1会話のtextのみ。履歴取得・正規化・provenance検証が完了してから、message・conversation・sync receiptを同じtransactionで保存する。
- sync receiptはprovider/account/conversationでscopeし、AES-256-GCMで暗号化。AADはmessage/conversationから分離する。既存v1テーブル・暗号形式を維持して新しいtableを追加する。
- receiptには実行時刻、取得件数、保存text件数、除外件数、上限到達を記録。provider cursorや「この時刻まで完全」という意味は持たせない。
- 空会話や非textだけの履歴も成功した回収として記録できる。受信成功や1往復成功とは扱わない。
- 取得失敗時はwatchを開始せず、既存の成功receiptと履歴を維持する。
- 上限内に見えなくなったmessageを削除と推定しない。再取得した同一IDのtextは既存upsertで更新する。unsend/deleteは未対応。
- `sync line`も同じ保存経路を使う。Matrix/Slack複数provider syncの部分保存禁止は維持する。
- `sync-status line`はローカルの最終回収結果のみを表示する。稼働中・接続中とは断定しない。

## 残る制限

直近100件より古い欠落、取得とwatch開始の間の競合、provider側削除、Coreとline-cliの原子的ackは未解決。件数が上限未満でも完全性は証明できない。真のincremental syncはadapterのcursor/ack契約確定後の別段階。送信のリトライ・認証処理は変更しない。

## 検証

fixtureで再open・再回収の重複防止、取得失敗・DB commit失敗時の巻き戻し、改ざん検出、account/conversation分離、平文漏洩なし、空履歴、上限到達、`--from-now`、履歴件数と新規受信件数の分離を確認する。live成功は別途記録する。
