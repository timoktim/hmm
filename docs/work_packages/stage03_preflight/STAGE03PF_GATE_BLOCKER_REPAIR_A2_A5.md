# STAGE03PF_GATE_BLOCKER_REPAIR_A2_A5

Purpose: repair the remaining blockers found by `STAGE03PF-WP13-RERUN` after WP0A and audit hardening A1-A6 were merged.

This is not Stage03 model work. Do not implement Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or new training algorithms.

## Current gate result

The rerun report says:

```text
Stage03PreflightVerdict: BLOCKED
BlockingPackages: [A2, A5]
```

Current blockers:

1. A2 / WP7 integration: lifecycle output emits `duration_tail_status_*` fields, but the persisted `hsmm_lifecycle_ui_daily` schema does not contain those columns.
2. A5: forward-return causal semantics and legacy state_source expectations remain inconsistent in legacy tests.

## Execution order

Run two independent repair PRs:

```text
B1: stage03pf/fix-a2-lifecycle-tail-status-schema
B2: stage03pf/fix-a5-forward-return-causal-legacy-tests
```

They can run in parallel. Re-run WP13 gate after both merge.

## Shared rules

- Start from updated `main`.
- One PR per blocker.
- No external data fetch.
- No DuckDB/WAL commit.
- Synthetic tests required.
- Do not weaken the A2/A5 causal semantics to satisfy old tests.
- Update stale tests to the new contract only when the old expectation is invalid.

---

## B1 Fix A2 Lifecycle Tail Status Persistence Schema

Index ID: STAGE03PF-GATEFIX-B1
Branch: `stage03pf/fix-a2-lifecycle-tail-status-schema`

### Goal

Persist the duration tail/status fields emitted after A2 duration-tail hardening into `hsmm_lifecycle_ui_daily` and ensure lifecycle report reruns do not fail on missing columns.

### Problem evidence

Failed tests:

```text
tests/test_hsmm_cascade_cleanup.py::test_lifecycle_report_rerun_does_not_keep_old_profile_rows
tests/test_hsmm_lifecycle_asof.py::test_profile_metadata_contains_cutoff
tests/test_hsmm_lifecycle_ui_integration.py::test_lifecycle_cli_outputs_and_ui_contract
```

Failure reason:

```text
hsmm_lifecycle_ui_daily does not contain duration_tail_status_1d emitted by lifecycle output after duration-tail hardening.
```

### Allowed files

```text
src/data_pipeline/storage.py
src/evaluation/hsmm_display_lifecycle.py
tests/test_hsmm_lifecycle_asof.py
tests/test_hsmm_lifecycle_ui_integration.py
tests/test_hsmm_cascade_cleanup.py
```

### Tasks

1. Add missing lifecycle UI daily columns idempotently. At minimum support emitted fields such as:

```text
duration_tail_status_1d
duration_tail_status_3d
duration_tail_status_5d
duration_tail_status_10d
duration_tail_status_20d
raw_p_exit_1d_status
raw_p_exit_3d_status
raw_p_exit_5d_status
raw_p_exit_10d_status
raw_p_exit_20d_status
p_exit_1d_status
p_exit_3d_status
p_exit_5d_status
p_exit_10d_status
p_exit_20d_status
```

If the actual emitted names differ, derive the full list from lifecycle output and tests. Do not silently drop emitted status fields before persistence unless the field is explicitly report-only and documented.

2. Ensure `DuckDBStorage.init_schema()` migrates existing DBs with `ADD COLUMN IF NOT EXISTS`.
3. Ensure lifecycle report generation writes these fields without failing.
4. Ensure rerunning lifecycle report does not leave stale profile rows.
5. Do not remove the A2 semantics: beyond-support or undefined tail rows must remain status-coded and must not become numeric 100% exit.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_cascade_cleanup.py::test_lifecycle_report_rerun_does_not_keep_old_profile_rows
pytest -q tests/test_hsmm_lifecycle_asof.py::test_profile_metadata_contains_cutoff
pytest -q tests/test_hsmm_lifecycle_ui_integration.py::test_lifecycle_cli_outputs_and_ui_contract
pytest -q tests/test_hsmm_duration_right_censoring.py tests/test_hsmm_duration_tail_semantics.py tests/test_hsmm_prefix_causality.py
```

If `python` is unavailable, use `.venv/bin/python` and `.venv/bin/pytest` and report it.

### Return format

```text
WP: STAGE03PF-GATEFIX-B1
status: pass / partial / fail
branch: stage03pf/fix-a2-lifecycle-tail-status-schema
PR: ...
commands run:
- ...
A2 schema repair:
- duration_tail_status columns persisted: yes/no
- raw_p_exit status columns persisted: yes/no
- p_exit status columns persisted: yes/no
- lifecycle rerun stale rows prevented: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## B2 Fix A5 Forward-Return Causal Semantics Legacy Tests

Index ID: STAGE03PF-GATEFIX-B2
Branch: `stage03pf/fix-a5-forward-return-causal-legacy-tests`

### Goal

Align forward-return evaluation tests and compatibility behavior with the A5 causal semantics contract without weakening the fail-closed rule.

### Problem evidence

Failed tests:

```text
tests/test_vnext_convergence.py::test_model_evaluation_forward_returns
tests/test_vnext_state_screener.py::test_evaluate_forward_returns_uses_walk_forward_cache
```

Failure reasons:

```text
forward-return evaluation now returns no rows for legacy in-sample state input used by the test
state source semantics now emit causal_walk_forward while legacy test expects walk_forward
```

### Allowed files

```text
src/evaluation/model_evaluation.py
src/ui/model_evaluation_page.py
src/ui/state_screener_page.py
tests/test_model_evaluation_causal_guard.py
tests/test_vnext_convergence.py
tests/test_vnext_state_screener.py
```

### Tasks

1. Keep A5 semantics intact:

```text
causal mode requires causal cache metadata or state_source=causal_walk_forward
in-sample mode is explicit and research_only
script/function layer must fail closed, not only UI warning
```

2. Update stale tests that still expect `walk_forward` instead of `causal_walk_forward`.
3. For tests using legacy in-sample input, either:
   - explicitly set `evaluation_mode='in_sample_display'` and assert `readiness_status='research_only'`, or
   - provide synthetic causal walk-forward state input and assert causal mode returns rows.
4. Do not make causal mode accept in-sample or legacy state sources merely to satisfy old tests.
5. Ensure UI/state screener still surfaces the right readiness/source metadata.

### Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_model_evaluation_causal_guard.py
pytest -q tests/test_vnext_convergence.py::test_model_evaluation_forward_returns
pytest -q tests/test_vnext_state_screener.py::test_evaluate_forward_returns_uses_walk_forward_cache
pytest -q tests/test_backtest_execution_price_semantics.py tests/test_model_evaluation_causal_guard.py
```

If `python` is unavailable, use `.venv/bin/python` and `.venv/bin/pytest` and report it.

### Return format

```text
WP: STAGE03PF-GATEFIX-B2
status: pass / partial / fail
branch: stage03pf/fix-a5-forward-return-causal-legacy-tests
PR: ...
commands run:
- ...
A5 semantic repair:
- stale walk_forward expectation updated: yes/no
- legacy in-sample test explicit research_only: yes/no
- causal mode still rejects in-sample states: yes/no
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```

---

## After B1 and B2

After both repair PRs are merged, re-run:

```text
STAGE03PF-WP13-RERUN
```

Expected result:

```text
Stage03PreflightVerdict: PASS
```

If still blocked, the report must list exact remaining failing tests and packages.