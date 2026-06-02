# STAGE03PF_BATCH_02_HSMM_ASOF_ATOMICITY

Purpose: harden HSMM lifecycle generation before Stage03. This batch prevents as-of target leakage, partial-run reads, stale downstream rows, and misleading tail probability semantics.

This batch contains:

- WP4 HSMM As-of Exit Target Contract, P0
- WP6 HSMM Run Status and Atomicity, P0
- WP7 HSMM Cascade Cleanup / Rerun Policy, P0
- WP5 HSMM p_exit Tail Semantics + Prefix Causality Tests, P1

WP4 and WP6 can run in parallel after WP0. WP7 must wait for WP6. WP5 should wait for WP4, but can run before later readiness/UI packages.

Do not implement Duration Hazard, BOCPD, Decision Engine, or new HSMM training algorithms.

## Shared rules

- Start from updated `main`.
- One PR per WP.
- Synthetic tests are required.
- No external data fetch.
- No DuckDB/WAL commit.
- HSMM lifecycle remains internal diagnostic only.
- Numeric `p_exit` cannot bypass readiness gates.

---

## WP4 HSMM As-of Exit Target Contract

Level: P0

Goal: ensure `latest_asof` lifecycle profile targets do not use outcomes realized after the cutoff date.

Allowed files:

```text
src/evaluation/hsmm_exit_targets.py
src/evaluation/hsmm_display_lifecycle.py
tests/test_hsmm_lifecycle_asof_targets.py
```

Codex tasks:

1. Add `asof_cutoff_date: date | None` to `build_exit_targets()`.
2. Output:

```text
horizon_end_date
realized_exit_date
target_observation_status
```

3. Use these target statuses:

```text
observed_positive
observed_negative
right_censored_by_cutoff
unknown
```

4. As-of target rules:

```text
observed_positive: realized_exit_date <= asof_cutoff_date and exit is inside horizon
observed_negative: horizon_end_date <= asof_cutoff_date and no exit inside horizon
right_censored_by_cutoff: horizon_end_date > asof_cutoff_date or realized exit after cutoff
unknown: missing source data
```

5. `_exit_tendency_long()` must pass `profile_cutoff_date` to target builder.
6. Empirical profile target source must use only `observed_positive` and `observed_negative` rows.
7. Full-run daily states may still output full dates, but profile targets must be cutoff-safe.

Tests required:

- Trade date before cutoff, realized exit after cutoff: not observed positive.
- Trade date before cutoff, horizon end after cutoff and no exit: not observed negative.
- Trade date before cutoff, horizon end before cutoff and no exit: observed negative.
- Realized exit before cutoff and inside horizon: observed positive.
- Latest-asof empirical exit rate does not change when only post-cutoff episodes change.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_lifecycle_asof_targets.py tests/test_lifecycle_*.py
```

PR return format:

```text
WP: STAGE03PF-WP4
status: pass / partial / fail
branch: stage03pf/wp4-hsmm-asof-exit-targets
PR: ...
commands run:
- ...
asof target behavior:
- post-cutoff positive excluded: yes/no
- censored rows excluded from empirical rate: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP6 HSMM Run Status and Atomicity

Level: P0

Goal: prevent interrupted incremental HSMM runs from being read by UI, lifecycle profile generation, or downstream model code.

Allowed files:

```text
src/models/hsmm_walk_forward.py
src/data_pipeline/storage.py
src/evaluation/hsmm_display_lifecycle.py
src/ui/lifecycle_page.py
tests/test_hsmm_run_atomicity.py
```

Codex tasks:

1. Add idempotent `hsmm_model_runs` columns:

```text
run_status
started_at
completed_at
failed_at
failure_message
expected_snapshot_count
actual_snapshot_count
expected_state_row_count
actual_state_row_count
lineage_hash
```

2. Before a run starts, write metadata with `run_status='running'`.
3. After states, episodes, parameters, and performance are written, update to `completed` as the final step.
4. On exception, update to `failed` with `failure_message`. Never leave a failed run as completed.
5. All HSMM readers must default to completed runs only.
6. `read_hsmm_states()` must default to `require_completed=True`.
7. UI latest selector must select only completed runs.

Tests required:

- A running run with state rows is hidden or rejected by `read_hsmm_states(require_completed=True)`.
- Failed run is absent from lifecycle latest run selector.
- Completed run remains readable.
- Simulated exception records failed status and failure message.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_run_atomicity.py tests/test_lifecycle_*.py
```

PR return format:

```text
WP: STAGE03PF-WP6
status: pass / partial / fail
branch: stage03pf/wp6-hsmm-run-atomicity
PR: ...
commands run:
- ...
run status:
- running hidden: yes/no
- failed hidden: yes/no
- completed readable: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP7 HSMM Cascade Cleanup / Rerun Policy

Level: P0

Goal: prevent stale downstream lifecycle/profile/next-state rows when the same HSMM `run_id` is rerun.

Dependency: WP6.

Allowed files:

```text
src/models/hsmm_walk_forward.py
src/evaluation/hsmm_display_lifecycle.py
src/data_pipeline/storage.py
tests/test_hsmm_cascade_cleanup.py
```

Codex tasks:

1. Implement `storage.clear_hsmm_run_cascade(run_id, include_reports=False)`.
2. The cascade cleanup must delete run-scoped rows from:

```text
hsmm_state_daily
hsmm_state_episodes
hsmm_model_checkpoints
hsmm_run_performance
hsmm_model_parameters
hsmm_model_runs
hsmm_display_label_episodes
hsmm_lifecycle_ui_daily
hsmm_lifecycle_profile_metadata
hsmm_lifecycle_duration_profile
hsmm_next_state_tendency_profile
```

3. Reusing an existing completed `run_id` must fail by default.
4. If `overwrite=True`, cascade cleanup must run first and record a cleanup summary.
5. Lifecycle report regeneration must avoid stale rows for the same run/profile/cutoff/policy.

Tests required:

- Insert rows for all downstream tables, run cascade cleanup, and all counts become zero for that run.
- Duplicate completed run id fails by default.
- `overwrite=True` cleans first and then writes.
- Lifecycle report rerun does not keep old profile rows.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_cascade_cleanup.py tests/test_hsmm_run_atomicity.py
```

PR return format:

```text
WP: STAGE03PF-WP7
status: pass / partial / fail
branch: stage03pf/wp7-hsmm-cascade-cleanup
PR: ...
commands run:
- ...
cascade cleanup:
- all downstream tables covered: yes/no
- duplicate completed run blocked: yes/no
- overwrite cleans first: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## WP5 HSMM p_exit Tail Semantics + Prefix Causality Tests

Level: P1

Goal: remove false certainty when age exceeds duration support, and lock prefix causality behavior with tests.

Dependency: WP4 recommended.

Allowed files:

```text
src/models/hsmm_model.py
src/evaluation/hsmm_display_lifecycle.py
tests/test_hsmm_duration_tail_semantics.py
tests/test_hsmm_prefix_causality.py
```

Codex tasks:

1. Change `p_exit_h(age > max_duration)` to return `np.nan` or a structured status such as `beyond_duration_support`.
2. Lifecycle/UI/report output for beyond support must show `unavailable` or `tail_censored`, not `100% exit`.
3. `duration_percentile(age >= max_duration)` may remain 1.0 only with `duration_percentile_status='beyond_support'` or equivalent documentation.
4. Add synthetic prefix causality test: identical prefix with different future suffix must produce identical prefix snapshot output.

Tests required:

- `age=max_duration+1` p_exit is not 1.0.
- Lifecycle UI/report does not show beyond-support 100% exit.
- Prefix snapshot state, age, label, and p_exit fields do not change when only future suffix changes.

Required validation:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_duration_tail_semantics.py tests/test_hsmm_prefix_causality.py
```

PR return format:

```text
WP: STAGE03PF-WP5
status: pass / partial / fail
branch: stage03pf/wp5-hsmm-tail-prefix-causality
PR: ...
commands run:
- ...
tail semantics:
- beyond support p_exit not 1.0: yes/no
- prefix causality locked: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```