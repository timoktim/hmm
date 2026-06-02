# Stage03 Preflight Baseline Freeze

WP: STAGE03PF-WP0
Branch: stage03pf/wp0-baseline-freeze
Baseline commit: `047243abbd1998572e7a65ab9e9566a5710ed815`
Status: pass

Stage03 blocked until WP13 passes.

## Scope

This baseline freezes the repository state before Stage03 preflight hardening continues. It does not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or any new training algorithm.

## Runtime Commands

- Python command policy: use `python` when available; otherwise use `.venv/bin/python`.
- Pytest command policy: use `pytest` when available; otherwise use `.venv/bin/pytest`.
- Smoke command: `bash scripts/stage03_preflight_smoke.sh`.
- Compile command: `python -m compileall -q src tests`, with `.venv/bin/python` fallback when `python` is unavailable.

## DB Path Policy

- Local DB handoff document read: `docs/runtime/LOCAL_DB_HANDOFF.md`.
- Canonical local DB path: `data/db/a_share_hmm.duckdb`.
- External data fetch: no.
- DuckDB/WAL committed: no.
- WP0 does not require DB-backed validation and does not read or mutate the local DuckDB.

## Known Current Blockers

- Stage03 must remain blocked until WP13 produces `Stage03PreflightVerdict: PASS`.
- Stage02 WP-E lineage result must remain fail-closed unless a native or strict inferred causal cache linkage exists.
- Legacy causal cache rows without strong lineage must remain legacy/debug evidence, not valid causal cache evidence.
- Duration Hazard, BOCPD, and Decision Engine work must not start during Stage03 preflight.

## Validation Results

- `bash scripts/stage03_preflight_smoke.sh`: pass.
  - `python`: `.venv/bin/python`
  - `pytest`: `.venv/bin/pytest`
  - result: 76 passed
- `python -m compileall -q src tests`: failed because `python` is unavailable in this shell.
- `.venv/bin/python -m compileall -q src tests`: pass.

## Boundary Confirmation

- Duration Hazard implemented: no
- BOCPD implemented: no
- Decision Engine implemented: no
- New model training: no
- External data fetch: no
- Model behavior modified: no
- DuckDB/WAL committed: no
