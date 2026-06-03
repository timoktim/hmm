# Stage03 Preflight Rerun Verdict

WP: STAGE03PF-WP13-RERUN
Branch: stage03pf/wp13-rerun-after-audit-hardening
Base: origin/main at d6d2a79
Status: fail

Stage03PreflightVerdict: BLOCKED
ready_for_stage03: false
BlockingPackages: [A2, A5]
DeferredPackages: []

## Summary

Stage03 preflight remains blocked after WP0A and audit hardening A1-A6 merged. The original WP13 blockers were reduced, but the rerun still found hard failures in HSMM lifecycle persistence after A2 tail-status outputs and in A5 forward-return causal semantics.

This rerun does not activate true Stage03 work. Duration Hazard, BOCPD, Decision Engine, Robust HMM, Sticky HMM, and new training work remain blocked until a later WP13 gate reports `Stage03PreflightVerdict: PASS`.

## WP0-WP13 Status

- WP0: accepted_on_main
- WP1: accepted_on_main
- WP2: accepted_on_main
- WP3: accepted_on_main
- WP4: accepted_on_main
- WP5: accepted_on_main
- WP6: accepted_on_main
- WP7: affected_by_A2_lifecycle_schema_blocker
- WP8: accepted_on_main
- WP9: accepted_on_main
- WP10: accepted_on_main
- WP11: accepted_on_main
- WP12: accepted_on_main
- WP13: rerun_blocked

## WP0A Status

- WP0A OHLCV Ingestion Validation Contract: accepted_on_main

## A1-A6 Status

- A1 HSMM Exit Calibration Target and Horizon Safety: accepted_on_main
- A2 HSMM Duration Tail and Right-Censoring Semantics: blocked_by_gate_failure
- A3 Market Breadth Coverage Semantics: accepted_on_main
- A4 Custom Basket Index Semantics and Low-Coverage Guard: accepted_on_main
- A5 Backtest Evaluation Causal Semantics: blocked_by_full_pytest_failure
- A6 CI Dependency and Private API Guard: accepted_on_main

## Gate Status

- legacy/debug cache status: pass
- HMM cache read policy status: pass
- HSMM latest_asof target status: blocked
- HSMM run atomicity status: pass
- probability readiness gate status: pass
- UI/analysis selector status: pass
- universe/data lineage status: pass
- evidence registry status: pass
- private path hygiene status: pass

## Failed Tests

Focused gate failed:

- `tests/test_hsmm_cascade_cleanup.py::test_lifecycle_report_rerun_does_not_keep_old_profile_rows`
  - package: A2 / WP7 integration
  - reason: `hsmm_lifecycle_ui_daily` does not contain `duration_tail_status_1d` emitted by lifecycle output after duration-tail hardening.

Full pytest additionally failed:

- `tests/test_hsmm_lifecycle_asof.py::test_profile_metadata_contains_cutoff`
  - package: A2
  - reason: same missing lifecycle persistence column family for `duration_tail_status_*`.
- `tests/test_hsmm_lifecycle_ui_integration.py::test_lifecycle_cli_outputs_and_ui_contract`
  - package: A2
  - reason: same missing lifecycle persistence column family for `duration_tail_status_*`.
- `tests/test_vnext_convergence.py::test_model_evaluation_forward_returns`
  - package: A5
  - reason: forward-return evaluation now returns no rows for the legacy in-sample state input used by the test.
- `tests/test_vnext_state_screener.py::test_evaluate_forward_returns_uses_walk_forward_cache`
  - package: A5
  - reason: state source semantics now emit `causal_walk_forward` while the legacy test expects `walk_forward`.

## Validation Commands

- `git fetch origin`: pass.
- `git worktree add -b stage03pf/wp13-rerun-after-audit-hardening <clean-worktree> origin/main`: pass.
- `git diff --check`: pass.
- `.venv/bin/python -m compileall -q src tests`: pass.
- `bash scripts/stage03_preflight_gate.sh`: fail.
  - focused pytest: 66 passed, 1 failed.
  - private path hygiene inside script: pass.
  - no-private-DB validation inside script: pass.
- `bash scripts/check_no_private_paths.sh`: pass, scanned_files=65.
- `bash scripts/validate_stage01_no_private_db.sh`: pass, private_db_required=no, external_data_fetch=no.
- `.venv/bin/pytest -q`: fail, 394 passed, 2 skipped, 5 failed, 27 warnings.

The local shell did not provide global `python` or `pytest`, so this rerun used `.venv/bin/python` and `.venv/bin/pytest`.

## BlockingPackages

- A2: lifecycle output emits duration-tail status columns that are missing from the persisted `hsmm_lifecycle_ui_daily` schema.
- A5: forward-return causal semantics and legacy state_source expectations remain inconsistent.

## DeferredPackages

- none

## Boundary Confirmation

- external data fetch: no
- training algorithm modified: no
- DuckDB committed: no
- source code modified: no
