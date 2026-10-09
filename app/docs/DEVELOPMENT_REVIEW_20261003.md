# 開発方針に基づく見直し

更新: 2026-10-03。仕様と受入条件を実装に先行して定める。方針の正本は [AGENT.md](../../AGENT.md)。

## 今回の対象

| 対象 | 現行仕様・受入条件 |
|---|---|
| SQLite初期化 | 新規DBは完成した現行schemaを一度で作る。既存DBは現行schema・version・鍵を検証し、旧形式をALTER/補完/復号書換えしない。拒否したDBの内容は変わらない。現行DBの再読込み・暗号化・削除権限は維持する。 |
| 保存設定 | provider固有の現行設定だけを利用する。旧共通設定だけが残る状態は拒否し、保存停止を捨てて収集再開しない。 |
| Messenger | 会話選択は暗号化DBのみ。Keychainの旧選択やPoC本文キャッシュを自動取込みしない。端末鍵・本人認証・受信commit/ACKは維持する。未保存の旧本文キャッシュは拒否して保全する。 |
| Slack OAuth | 専用nativeウィンドウと `beeperlocal://oauth/slack` の1経路。旧localhost callback serverと外部ブラウザ分岐を除く。PKCE、state検証、scope、本人アカウント照合、失敗時の未保存を維持する。 |
| X移行スクリプト | 使われていない旧独立版の取込みスクリプトを現行のscriptsから退避する。外部Xが現在返す旧形式DMの読取りは維持する。 |
| 資料 | ルートAGENT.mdへ方針を集約。AGENTS.mdから参照する。CLAUDE.mdと次工程を0.9.5に合わせ、古い状態は履歴と明示する。 |

DBの削除・初期化、Keychain書換え、実送信、外部公開設定の変更は今回の作業に含めない。通常アプリと配布ZIPは検証済み0.9.5のまま。今回のソース変更は次のリリース時に改めてビルド・検証・公証する。

## 検証記録

- 仕様と方針を先に更新。受入テスト70件の実行で、旧schemaの自動修復・旧設定取込み・旧localhost受付等による14失敗を確認してから実装した。
- 対象70件が成功。全体検証で見つかった旧移行前提の2テストも現行仕様へ更新し、最終Core全537件が成功。暗号化・保存停止・MCP認可/失効・ページ表示・送信重複防止・受信commit/ACKを含む。
- Slack・Messenger・初回導入のPlaywright画面13件、TypeScript/Vite production build、shell構文8ファイル、offline demoが成功。
- 旧schemaの拒否前後でDB bytesが一致すること、旧Messenger本文の拒否でKeychainを書き換えないこと、現行の会話選択と保存停止が再起動で復元することを架空データで検証した。
- `migrate-x-standalone.py` は [退避先](../../_to_delete/20261003-kiss/migrate-x-standalone.py)へ移動。現行scripts・梱包対象から外した。
- Xが返す旧形式DM、LINEの複数ID形式、Telegramのサーバー移動、catalog取得前の保存済み会話表示、署名/Keychain identity、端末排他制御は現在の要件として維持する。
- AGENT/AGENTS、CLAUDE、README、次工程、関係ADRの矛盾を整理し、古い説明は日付付き履歴へ分離した。

全検証は合成データ・ローカルHTTP・テスト専用ブラウザで実施。実アカウントへ接続せず、通常アプリ・配布ZIP・利用者DB・Keychainを更新していない。今回の変更を配布済みと扱わない。
