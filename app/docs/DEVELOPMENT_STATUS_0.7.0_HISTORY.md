> 履歴: 2026-10-01の販売初版計画への改訂前の記録。現在の作業順・完了判定・委任許可として使わない。現行計画は[IMPLEMENTATION_PLAN](IMPLEMENTATION_PLAN.md)。

# 開発状況 / Closed Loops

更新: 2026-09-30 / Desktop version `0.7.0`

| Loop / Gate | 状態 | Evidence |
|---|---|---|
| Mac実行環境 | CLOSED | Python 3.14.7 / arm64 Macでdoctor成功 |
| Keychain backend | CLOSED | write/read/delete probe成功 |
| Matrix live connector basic | CLOSED | 選択roomから実message 1件取得 |
| Slack live connector basic | CLOSED | test-channelから実message 1件取得 |
| Cross-provider integration Gate A | **CLOSED** | `proof --limit 1`でMatrix+Slack各1件を同一timelineへmerge |
| Volume/Pagination Gate B | OPEN | 各50件は未実施。Phase 1のblockerではない |
| 暗号化保存・再起動・検索 | CLOSED_BY_USER_REPORT | Phase-1成功のユーザー報告。詳細はPROJECT_STATE |
| LINE Core 1対1text 1往復 | CLOSED_BY_USER_REPORT | 送信→相手受信→返信→Core受信→保存→確認の成功報告 |
| LINE会話catalog | LIVE_VERIFIED | 実機500件、別プロセスで復号・canonical MID確認 |
| LINE起動時履歴回収・receipt | IMPLEMENTED_LOCAL_TESTED | 直近50〜100件、原子的保存。0.6.0の同梱Coreで実履歴取得とreceipt・検索を確認 |
| Coreのincremental cursor/ack | OPEN | bounded回収は実装。line-cli cursorとの原子性は未達 |
| 編集 / 削除reconciliation | PARTIAL | 再取得の同一ID更新。削除・unsendは対象外、履歴不在で削除しない |
| Macアプリ / UI | BUILT_AND_LAUNCHED | 0.7.0を普段開くappへ配置し署名・起動確認。fixture UI 15件PASS |
| Desktop Core / 送信ledger | IMPLEMENTED_LOCAL_TESTED | 0.7.0は全230 tests PASS。再起動後の同一request抑止・結果不明時の自動再送禁止 |
| アプリのLINE live連携 | PARTIAL_LIVE_VERIFIED | Mac再起動後に会話500件・実履歴・検索・受信待機。承認済みテスト送信1回のLINE受付とアプリ再起動後の復元・検索を確認 |
| アプリのLINE基本送受信 | CLOSED_BY_USER_REPORT | 相手側着信と正常な返信受信・順番をユーザーが確認。直前の正確性の懸念は撤回。再起動検索は送信テスト文で独立実測 |
| LINEの自動再接続 | IMPLEMENTED_FIXTURE_TESTED | 一時切断/EOF/致命的エラー/上限/保存停止を検証。長時間の実断線・スリープは未確認 |
| ローカルMCP | IMPLEMENTED_HTTP_FIXTURE_VERIFIED | 独立公式SDKで4 tools、認証・scope・失効。実機初期無効、商用clientへの実データ設定は未実施 |
| 保存停止・account限定削除 | IMPLEMENTED_FIXTURE_TESTED | 永続停止、確認nonce、10,000件超削除、他account/provider保持。実データ削除なし |
| IG | PARTIAL_FEASIBILITY | 関連タスクに履歴3件取得のユーザー証拠。新着受信・送信・Core統合は未完了 |
| 𝕏 | NOT_STARTED | 接続方法の確定・DM検証から着手予定 |

## Phase 1 acceptance

最小Closed Loop:

1. Matrix+Slackから実データを取得。
2. 暗号化SQLiteに保存。
3. プロセス再起動後にDBを再open。
4. 既知の実メッセージ語をlocal searchで発見。
5. 同一messageを再syncしてrow数が不必要に増えない。

Phase-1はユーザー報告でCLOSED。[実装スケジュール・タイムライン](IMPLEMENTATION_PLAN.md)の順で進める。fixture、ユーザー報告、エージェント自身の実機確認は別の証拠として扱う。

## 0.7.0のLINE初回連携と会話一覧

- アプリ内QR・スマートフォン承認・PIN表示・中止・失敗時の再試行を実装。
- 左の会話一覧をproviderの最終更新時刻で並べ、友だち以外の名前とプロフィール画像を取得。選択時に古いmetadataへ戻さない。
- 実機では保存済み500会話の復元と、無効セッションの再連携案内を確認。再連携後、同梱Coreで現在の46会話の更新順・名前・画像情報と画像3件の読み込みを確認。
