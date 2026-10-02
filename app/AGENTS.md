# Development rules — BeeperLocal v0.4+

1. Read `README.md`, `docs/PROJECT_STATE.md`, `docs/ADR_PHASE1_PERSISTENCE.md`, and `docs/SECURITY.md` first.
2. Gate A (Matrix+Slack live connectivity/integration) was CLOSED on the user's Mac on 2026-09-27 with >=1 real message each. 50 messages is only Gate B volume/pagination.
3. Never infer live success from mocks/demo. Preserve PROJECT_STATE evidence accurately.
4. Never extract browser/Beeper credentials, use Discord self-bots, bypass provider authorization, or ask for secrets in chat.
5. Provider credentials and local DB key must remain in native macOS Keychain; no file/env fallback.
6. Message identity includes provider + account + conversation + provider-message ID.
7. Message body/title/sender/provider-side identifiers must not be written plaintext to SQLite/FTS/log/report. Phase-1 SQLite payload is AES-256-GCM encrypted.
8. Do not add plaintext FTS without a new security ADR. Current local search decrypts bounded rows in memory.
9. A multi-provider `sync` failure must not silently persist a partial requested run.
10. Run `python3 -B -m unittest discover -v`, shell syntax checks, and offline demo after changes. Separate local tests from Mac/live-provider evidence.
11. Do not log raw SDK exceptions, API responses, tokens, message bodies, auth codes, or search queries.
12. Before GUI work, close the Phase-1 live persistence/search loop and then implement incremental sync/reconciliation.
