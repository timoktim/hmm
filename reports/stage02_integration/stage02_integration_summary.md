# Stage 02 Integration Summary

index_id: STAGE02-WP-D-v1
status: pass
final_verdict: Stage02PassWithTrackedRisks
branch: stage02/wp-d-final-integration-acceptance
generated_at: 2026-06-02

## Merged PRs Checked

- PR #9: merged, WP-B CI-safe validation artifacts, merge commit 62f6264
- PR #10: merged, WP-A causal cache contract audit, merge commit cfc7c59
- PR #11: merged, WP-C readiness gate integration, merge commit 19c5bdf

## Acceptance Checks

- WP-A causal cache audit exists and is machine-readable: yes
- WP-B CI validation summary exists: yes
- WP-B workflow exists: yes
- WP-C readiness gate report exists and is machine-readable: yes
- Stage 02 HMM/HSMM training modified: no
- Stage 02 `src/models/` or `src/features/` modified: no
- DuckDB/WAL committed: no
- external data fetch: no
- private path hygiene: pass
- readiness upgraded to validated or decision_ready: no

## Commands Run

- git fetch origin: pass, origin/main at 6a23696
- git checkout main: blocked by pre-existing untracked files in the primary local worktree; no files moved or deleted
- git worktree add -b stage02/wp-d-final-integration-acceptance <clean local worktree> origin/main: pass
- git diff --check: pass
- python -m compileall -q src tests: failed, python unavailable
- .venv/bin/python -m compileall -q src tests: pass
- pytest -q tests/test_readiness_gate.py tests/test_causal_cache_audit.py tests/test_private_path_hygiene.py: failed, pytest unavailable
- .venv/bin/pytest -q tests/test_readiness_gate.py tests/test_causal_cache_audit.py tests/test_private_path_hygiene.py: pass, 16 passed
- bash scripts/check_no_private_paths.sh: pass, PRIVATE_PATH_HYGIENE=pass scanned_files=56
- bash scripts/validate_stage01_no_private_db.sh: pass, CI_SAFE_STAGE01_VALIDATION=pass private_db_required=no external_data_fetch=no

## Core Evidence

- resolved_run_id: bea7ff20106a
- causal_cache_available: true
- causal_cache_status: partial
- causal_cache_reason: cache_not_linked_to_resolved_run_id
- causal_cache_coverage_ratio: 0.052885
- causal_cache_state_count: 30937
- expected_state_rows: 584981
- leakage_violation_count: 0
- duplicate_key_count: 0
- missing_metadata_count: 1
- CI private DB required: no
- CI DB-backed validation artifact: no
- readiness_status: research_only
- display_action: research_only

## Readiness Conclusion

HMM output remains research_only / diagnostic. Stage 02 added gates and evidence, but did not make outputs validated or decision-ready.

## Blocking Issues

- none

## Tracked Risks

- Causal cache rows exist but are not linked to the resolved HMM run id.
- Causal cache coverage is partial.
- Label alignment ambiguity remains high.
- CI is private-DB-free and is not a DB-backed validation artifact.
- Stage 00 registry tables are missing in the local V0 DB, so some evidence remains seed-payload-based.

external data fetch: no
training algorithm modified: no
DuckDB committed: no
