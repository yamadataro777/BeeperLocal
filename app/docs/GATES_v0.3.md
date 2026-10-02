# Phase-0 Gates — v0.3

## Gate A: Connectivity / Integration

Purpose: prove the BeeperLocal core integration hypothesis as cheaply as possible.

Pass criteria:
- Matrix and Slack are both live providers.
- Each returns at least 1 unique real message from a user-selected conversation.
- Selected conversations are actually fetched.
- No fetch error.
- No normalization error.
- Provider provenance is correct.
- Both providers are normalized and chronologically merged in the same run.

CLI field: `loop_status=CLOSED`.

## Gate B: Volume / Pagination

Purpose: test bounded history traversal and pagination, not basic feasibility.

Pass criteria: Gate A plus at least 50 unique real messages from each provider.

CLI field: `volume_loop_status=CLOSED`.

Gate B is intentionally separate from Gate A. A new account with one message can prove integration feasibility but cannot prove pagination or larger-history behavior.

## Evidence obtained on 2026-09-27

The user's live run produced one Slack message and one Matrix message in the same `proof --limit 1` execution, with both normalized into one chronological timeline and no reported fetch/normalization error. Under Gate A this is a CLOSED integration loop. The old v0.2 binary printed OPEN only because it still used the earlier 50-message acceptance threshold.
