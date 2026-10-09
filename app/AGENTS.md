# BeeperLocal 本体の作業指示

[開発方針](../AGENT.md) を最初に読む。資料更新 → 必要なテストの失敗確認 → 最小実装 → 不要コード・資料矛盾の点検の順で、主担当だけで進める。開発中は旧版互換・データ移行を維持しない。

- 現行仕様は `README.md` と `docs/NEXT_IMPLEMENTATION.md`、検証の証拠は `docs/PROJECT_STATE.md`。保存方式は `docs/ADR_PHASE1_PERSISTENCE.md` と `docs/SECURITY.md`。日付付き履歴を現在の作業指示として再実行しない。
- Message identity includes provider + account + conversation + provider-message ID.
- Provider credentials and DB keys remain in native macOS Keychain. No file/env fallback, credential extraction, authorization bypass, or unrequested ACL/key reset.
- Message body/title/sender/provider-side identifiers must not be written plaintext to SQLite/FTS/log/report. Use AES-256-GCM encrypted payloads and bounded in-memory search; no plaintext FTS without a new security ADR.
- A multi-provider sync failure must not silently persist a partial requested run. Preserve permission checks, outbox duplicate suppression, and commit-before-ACK ordering.
- Never log raw SDK exceptions, API responses, tokens, auth codes, message bodies, or search queries. Never infer live success from fixtures/demo.
- Core変更後は `.release-venv/bin/python -B -m unittest discover -v`、変更対象のshell構文検査とoffline demoを実行する。UI変更には対象画面テストとproduction buildを追加する。配布時の必須検査は `docs/DESKTOP_APP.md` に従う。コマンドには `rtk` を付ける。
