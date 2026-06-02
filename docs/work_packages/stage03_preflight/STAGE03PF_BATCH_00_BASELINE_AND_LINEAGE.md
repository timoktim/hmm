# STAGE03PF_BATCH_00_BASELINE_AND_LINEAGE

Purpose: establish a frozen preflight baseline and a deterministic lineage hash contract before any Stage03 model work.

This batch contains two sequential packages:

- WP0 Baseline Freeze
- WP1 Lineage Core

Do not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or any new training algorithm in this batch.

## Dependency and branch order

Run WP0 first. After WP0 is accepted and merged, run WP1 from updated `main`.

Suggested branches:

```text
stage03pf/wp0-baseline-freeze
stage03pf/wp1-lineage-core
```

## Shared rules

- Start from updated `main`.
- Use one PR per WP.
- Do not fetch external data.
- Do not commit DuckDB/WAL files.
- Read `docs/runtime/LOCAL_DB_HANDOFF.md` if the local DB is used.
- All new behavior must have synthetic tests.
- Stage03 remains blocked until WP13 produces `Stage03PreflightVerdict: PASS`.

---

## WP0 Baseline Freeze

Level: P0

Goal: freeze the current preflight baseline before hardening changes.

Allowed files:

```text
reports/stage03_preflight/baseline_freeze.md
scripts/stage03_preflight_smoke.sh
```

Codex tasks:

1. Create `reports/stage03_preflight/baseline_freeze.md`.
2. Record current commit, Python command used, pytest command used, DB path policy, and known current blockers.
3. The baseline document must explicitly say: `Stage03 blocked until WP13 passes`.
4. Add `scripts/stage03_preflight_smoke.sh` with:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_*.py tests/test_lifecycle_*.py
```

5. If `python` is missing, support `.venv/bin/python`; if `pytest` is missing, support `.venv/bin/pytest`; do not hide errors.
6. Do not modify model behavior.

Required validation:

```bash
bash scripts/stage03_preflight_smoke.sh
python -m compileall -q src tests
```

PR return format:

```text
WP: STAGE03PF-WP0
status: pass / partial / fail
branch: stage03pf/wp0-baseline-freeze
PR: ...
commands run:
- ...
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP1 Lineage Core

Level: P0

Goal: create a single deterministic lineage payload/hash utility for HMM cache, HSMM run, UI readiness, and future hazard datasets.

Allowed files:

```text
src/utils/lineage.py
src/data_pipeline/storage.py
tests/test_lineage_hash_contract.py
```

Codex tasks:

1. Add `canonical_json(payload: Mapping) -> str`.
   - Use deterministic JSON ordering.
   - Stable handling for date, datetime, pandas Timestamp, Path, numpy scalars, tuples, sets, and nested mappings.
   - No non-deterministic iteration order.
2. Add `hash_payload(payload, algo="sha256", length=32) -> str`.
3. Add `build_model_lineage_payload(...)` with at least:

```text
model_family
model_version
code_version
feature_version
feature_scope_id
feature_columns
model_params
preprocess_params
train_window_policy
state_date_policy
universe_id
universe_membership_hash
custom_basket_membership_hash
data_snapshot_hash
calendar_hash
```

4. In `DuckDBStorage.init_schema()`, add columns idempotently:

```text
walk_forward_cache_runs.lineage_json
walk_forward_cache_runs.lineage_hash
walk_forward_cache_runs.feature_lineage_hash
walk_forward_cache_runs.universe_membership_hash
walk_forward_cache_runs.data_snapshot_hash
walk_forward_cache_runs.cache_status
walk_forward_cache_runs.completed_at
walk_forward_state_cache.lineage_hash
walk_forward_state_cache.feature_lineage_hash
hsmm_model_runs.lineage_json
hsmm_model_runs.lineage_hash
```

5. Legacy rows with `lineage_hash IS NULL` must not be considered valid cache. They can only be legacy/debug.

Tests required:

- Same payload with different key order produces same hash.
- `feature_columns` change changes hash.
- `random_state`, `n_iter`, and `min_train_rows` changes change hash.
- `universe_membership_hash` change changes hash.
- Legacy cache row without `lineage_hash` is invalid.
- Schema migration is idempotent.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_lineage_hash_contract.py
```

PR return format:

```text
WP: STAGE03PF-WP1
status: pass / partial / fail
branch: stage03pf/wp1-lineage-core
PR: ...
commands run:
- ...
lineage hash behavior:
- deterministic: yes/no
- legacy cache invalid by default: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```