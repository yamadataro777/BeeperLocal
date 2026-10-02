# Test Report — v0.4.0-poc

Date: 2026-09-27

## Local automated checks in build environment

Command:

```bash
python3 -B -m unittest discover -v
```

Result: **126 tests run, 125 passed, 1 skipped, 0 failed**.

Skip: installed Telethon constructor smoke test because Telethon is not installed in this build container. The user's Mac already previously passed Telethon 1.45.0 constructor verification under v0.2/v0.3.

New Phase-1 coverage includes:
- AES-256-GCM roundtrip;
- body/title canary absent from raw SQLite bytes;
- DB file 0600 / directory 0700;
- restart with same key;
- idempotent upsert;
- Japanese substring search;
- provider-filtered search;
- wrong-key refusal;
- ciphertext tamper detection;
- duplicate batch refusal;
- symlink DB refusal;
- local DB deletion containment;
- search query cannot be supplied as a positional CLI argument;
- failed/partial multi-provider sync does not write partial local data.

## Shell / offline demo

`bash -n run.sh scripts/setup.sh scripts/python-select.sh`: PASS.

`python3 -B -m beeperlocal demo --limit 2`: PASS, remains explicitly `DEMO_NOT_EVIDENCE`.

## Live provider evidence from user's Mac

Already obtained before v0.4:
- Matrix live fetch: 1 real message.
- Slack live fetch: 1 real message.
- same-run Matrix+Slack chronological merge: success.
- Gate A is CLOSED.

Not yet executed on the user's Mac under v0.4:
- installation of `cryptography==46.0.4` in the new project `.venv`;
- live `sync --limit 1` into encrypted SQLite;
- process-restart `db-status`;
- live local search;
- repeated live sync idempotency.

Do not report those as completed until the user executes them.
