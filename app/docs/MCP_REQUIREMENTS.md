# ローカルMCP要件と実装対応

**現行0.9.1:** LINE・Slack・Instagram・X・Messengerの5サービスに対応。使い方・権限・検証は[MCP_0_9_1.md](MCP_0_9_1.md)。以下は0.6.0時点の記録です。

更新: 2026-09-30 / Desktop 0.6.0。製品定義は「メッセージの預け先を増やさず、自分のAIにつなぐ」。LINE → Instagram → 𝕏の順序を維持する。以下はLINE最小実装の受入結果。詳細契約は[ADR_LOCAL_MCP.md](ADR_LOCAL_MCP.md)。

| 要件 | 実装と根拠 | 検証と限界 |
|---|---|---|
| MacからSNSへ直接接続 | GUI → private pipe → Core → 同梱line-cli。新しい運営会社への送信経路なし | source/CSP/依存を確認。通信経路は[COMMUNICATION_PATHS.md](COMMUNICATION_PATHS.md)。全依存の監査・完全な通信captureは未実施 |
| 外部MCP client | 公式SDKのStreamable HTTP、4 toolsを同じCore/DB/ledgerへ接続 | 独立公式SDK clientから実127.0.0.1 HTTPでmodern/legacy handshake、一覧/履歴/検索/送信をfixture検証。特定の商用AI製品との実データ接続は未実施 |
| 明示的な許可 | client別Bearer、account/会話/read/send scope、初期MCP無効・会話未選択・送信OFF | 未許可・別account・別会話・権限違い・失効・再起動後を拒否 |
| 全経路の権限検証 | HTTP入口、Core tool、外部送信直前。resources/promptsは空 | 未許可canaryが検索へ出ない。送信待機中の失効/停止/保存停止を検証 |
| 許可された自動化 | 固定宛先send、共通暗号化ledger、client別UUID名前空間 | GUI会話を変えず別の許可宛先へ送る。重複同時要求は1回、結果不明は再起動後も再送なし。今回の追加実LINE送信は0回 |
| HTTP防御 | 127.0.0.1のみ、正確なHost、Origin/転送ヘッダー/query/重複token拒否、96KiB制限 | 実HTTPによる拒否テスト、chunked body、例外内容を漏らさないことを確認。OAuth自動認可なし、clientは手動Bearerに対応が必要 |
| 暗号化維持 | tokenのhash、client権限、設定を既存AES-GCM鍵で保存。AAD分離、平文FTSなし | 保存fileにtoken/本文/名前/ID canaryなし、改ざんと不正設定を拒否。旧形式を変更しない追加table |
| 保存停止・削除 | 停止を永続化、確認nonce付きaccount限定削除、MCP停止・権限失効 | 再起動後も停止、他account/provider保持、transaction失敗時rollback、10,000件超も削除。実データの削除は未実施 |
| 管理UI | LINE/MCP/保存管理、公開URL、会話選択、token一度表示、失効、保存場所・保持・停止・削除 | 架空データのChrome画面テスト。AI側の保存・処理と回収不能も表示 |
| LINE再接続 | 一時障害/EOFの上限付き再接続、再接続前と開始後/約60秒ごとの100件回収 | fixtureの切断、重複、復号エラー、保存停止中の取得を確認。全履歴/cursor ack/削除同期/長時間実機は未完 |
| 実測の区別 | 0.5.1の基本LINE往復は既存の実機・本人報告。0.6.0の新規MCPはfixture/HTTP証拠 | 0.5.1の成功をMCP実データ成功に転用しない。配布物とMac確認は`desktop-0.6.0-verification.json`へ記録 |

MCPは利用者が設定で有効化する。tokenは権限を持つ秘密情報として外部clientへ設定するが、登録名だけで利用プロセスを特定できるわけではない。アプリ終了でlistenerは停止する。読み取りも止めたい場合はMCP停止か権限取り消しを行う。

今回の最小LINE実装後も、Instagram/𝕏の新規送受信実装・実機Gate、長時間のLINE運転、全履歴・ack契約を残す。当初の追加5〜8日という見積は作業量の概算であり、確定納期ではない。
