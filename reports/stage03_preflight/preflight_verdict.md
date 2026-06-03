# Stage03 Preflight Verdict

WP: STAGE03PF-WP13
Branch: stage03pf/wp13-stage03-preflight-gate
Base: origin/main at f84b5d0
Status: fail

Stage03PreflightVerdict: BLOCKED
BlockingPackages: [WP6, WP7, WP10, WP12]
DeferredPackages: []

## Summary

Stage03 preflight hardening is not ready to open true Stage03 work. The final gate script compiled successfully and completed the private-path and no-private-DB checks, but the required focused pytest gate failed in the integrated HSMM run atomicity, cascade cleanup, and universe/data lineage path. The optional full-suite validation also failed and found one stale UI text expectation.

No Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, or new training algorithm work is activated by this verdict.

## Package Status

P0 package status: blocked

- WP0 Baseline Freeze: accepted on main.
- WP1 Lineage Core: accepted on main.
- WP2 HMM Walk-forward Cache Contract: accepted on main.
- WP3 Cached State / Feature Merge Guard: accepted on main.
- WP4 HSMM As-of Exit Target Contract: accepted on main.
- WP6 HSMM Run Status and Atomicity: reopened by WP13 gate.
- WP7 HSMM Cascade Cleanup / Rerun Policy: reopened by WP13 gate.

P1 package status: blocked

- WP5 HSMM p_exit Tail Semantics and Prefix Causality Tests: accepted on main.
- WP8 Probability Readiness Lineage: accepted on main.
- WP9 UI and Analysis Selection Gate: accepted on main.
- WP10 Universe/Data Snapshot Lineage: reopened by WP13 gate.
- WP11 Evidence Registry Minimal Contract: accepted on main.

P2/P3 package status: blocked

- WP12 SQL Identifier Hardening and Legacy Probability Wording: reopened by WP13 gate because full pytest still contains a stale UI label expectation.

## Gate Status

legacy/debug cache status: pass

- Legacy cache rows remain fail-closed by policy and are not treated as valid backtest or readiness artifacts.
- Stage02 causal cache lineage risk remains fail-closed unless native or strict inferred linkage exists.

HMM cache read policy status: pass

- Focused HMM cache and feature-guard tests passed in the WP13 gate.
- Legacy, mismatched, running, row-count-mismatched, and causal-violating cache rows remain rejected by the covered gate tests.

HSMM latest_asof target status: pass

- Focused as-of target tests passed in the WP13 gate.
- latest_asof empirical targets remain limited to observed positive or observed negative outcomes.

HSMM run atomicity status: blocked

- `tests/test_hsmm_run_atomicity.py::test_hsmm_walk_forward_marks_failed_on_exception` failed.
- The synthetic failure is preempted by universe/data snapshot lineage digest construction before the intended run-status failure path is asserted.

probability readiness gate status: pass

- Focused probability readiness lineage and strictness tests passed in the WP13 gate.
- Raw or calibrated p_exit remains gated by readiness metadata.

UI/analysis selector status: pass with full-suite follow-up

- Focused UI readiness selector and analysis cache selector tests passed in the WP13 gate.
- Full pytest failed `tests/test_market_regime.py::test_ui_column_rename_mapping` because the legacy expected label is stale against the current posterior wording policy.

universe/data lineage status: blocked

- `tests/test_hsmm_run_atomicity.py::test_hsmm_walk_forward_marks_failed_on_exception` failed with `ValueError: No objects to concatenate`.
- `tests/test_hsmm_cascade_cleanup.py::test_duplicate_completed_run_id_fails_by_default` failed with the same lineage digest precondition error.
- `tests/test_hsmm_cascade_cleanup.py::test_overwrite_cleans_first_and_then_writes_completed_run` failed with the same lineage digest precondition error.
- The integrated gate shows that empty synthetic snapshot frames are not handled before HSMM atomicity and cascade behavior can be validated.

evidence registry status: pass

- Focused evidence registry contract tests passed in the WP13 gate.
- Invalid readiness artifacts remain excluded by the covered selectors.

private path hygiene status: pass

- `bash scripts/check_no_private_paths.sh`: pass, scanned_files=60.
- `bash scripts/validate_stage01_no_private_db.sh`: pass, private_db_required=no, external_data_fetch=no.

## Validation Commands

- `git fetch origin`: pass.
- `git worktree add -b stage03pf/wp13-stage03-preflight-gate <clean-worktree> origin/main`: pass.
- `git diff --check`: pass.
- `bash scripts/stage03_preflight_gate.sh`: fail.
  - compileall: pass.
  - focused pytest: 63 passed, 3 failed.
  - private path hygiene: pass.
  - no-private-DB Stage01 validation: pass.
- `.venv/bin/pytest -q`: fail, 335 passed, 2 skipped, 5 failed, 25 warnings.

The local shell did not provide global `python` or `pytest`, so the gate script used `.venv/bin/python` and `.venv/bin/pytest`.

## BlockingPackages

- WP6: HSMM run atomicity failure path is preempted by missing persisted OHLCV snapshot lineage in synthetic tests.
- WP7: completed-run duplicate and overwrite cascade tests fail before cascade policy can be asserted.
- WP10: universe/data snapshot hash handling raises on empty synthetic snapshot frames.
- WP12: full-suite UI text expectation still references the old probability label.

## DeferredPackages

- none

## Boundary Confirmation

- external data fetch: no
- training algorithm modified: no
- DuckDB committed: no
- source code modified: no
