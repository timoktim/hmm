# Stage 01 Final Integration Summary

Index ID: STAGE01-WP-D-v1
Branch: stage01/wp-d-integration-summary
Generated: 2026-06-02T02:00:35Z
Verdict: Stage01PassWithTrackedRisks

## Scope

This review closes Stage 01 HMM baseline strengthening after the three diagnostic PRs were merged into `main`.

- PR #6 / WP-A: HMM confidence metrics, merge commit `b452ec3b`, head `560aad7`.
- PR #7 / WP-B: HMM label alignment and state identity audit, merge commit `f58b470`, head `e7cfe2e`.
- PR #5 / WP-C: HMM churn/dwell diagnostics and readiness downgrade, merge commit `953c831`, head `928704f`.

The review started from latest `origin/main` at `dbc1f304811fe2ce75e3a8b879b73c3ace743e85`.

## Local DB

- Path used by commands: `data/db/a_share_hmm.duckdb`
- Preflight result: pass (`LOCAL_DB_FOUND=data/db/a_share_hmm.duckdb`)
- Read-only schema sanity check: yes
- Key table counts:
  - `model_runs`: 25
  - `sector_state_daily`: 2655935
  - `walk_forward_cache_runs`: 7
  - `walk_forward_state_cache`: 226810
  - `hsmm_lifecycle_ui_daily`: 557104
- DB/WAL committed: no
- External data fetch: no

## Commands Run

- `git fetch origin` -> updated `origin/main` through PR #5 merge.
- `git worktree add -b stage01/wp-d-integration-summary <local worktree> origin/main` -> branch created from latest `main`.
- `git pull --ff-only` -> already up to date.
- `.venv/bin/python -m compileall -q src tests` -> passed.
- `.venv/bin/pytest -q tests/test_hmm_confidence.py tests/test_hmm_label_alignment.py tests/test_hmm_churn_dwell.py` -> 20 passed.
- `.venv/bin/pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py` -> 20 passed.
- `.venv/bin/pytest -q -m "not slow"` -> 251 passed, 2 deselected, 25 warnings.
- `.venv/bin/python -m src.evaluation.hmm_confidence --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_confidence/stage01_wp_a_confidence_report.md --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json --no-fetch` -> pass.
- `.venv/bin/python -m src.evaluation.hmm_label_alignment --db data/db/a_share_hmm.duckdb --run-id latest --compare-mode recent-runs --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json --no-fetch` -> pass.
- `.venv/bin/python -m src.evaluation.hmm_churn_dwell --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.md --summary-json reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json --no-fetch` -> pass.

`python` and `pytest` were not available in this shell, so `.venv/bin/python` and `.venv/bin/pytest` were used.

## Core Metrics

WP-A confidence:

- status: pass
- run_id: `bea7ff20106a`
- confidence rows generated: 584981
- posterior columns found: yes (`prob_trend_up`, `prob_neutral`, `prob_risk_off`)
- confidence readiness: `internal_only`
- posterior semantic statement: state confidence diagnostics only, not return/rising/falling/profit/buy/sell probabilities

WP-B label alignment:

- status: pass
- resolved_run_id: `bea7ff20106a`
- run pairs compared: 5
- alignment method: `hungarian`
- label_preserved_share: 1.0
- ambiguous_match_share: 0.8666666666666667
- high_drift_share: 0.0
- state identity readiness: `research_only`

WP-C churn/dwell:

- status: pass
- run_id: `bea7ff20106a`
- state row coverage: 584981 rows, 464 sectors
- date coverage: 2020-02-07 .. 2026-05-28
- churn/dwell rows generated: 42210
- transition_rate_1d: 0.07142
- mean_dwell_days: 13.858825
- median_dwell_days: 9.0
- single_day_episode_share: 0.107581
- churn_bucket: `low`
- confidence_integration_status: `available_confidence`
- alignment_integration_status: `available_alignment`
- causal_cache_available: false
- readiness/display action: `research_only` / `research_only`

## Integration Result

All three diagnostics ran successfully against the same local V0 DB and resolved to the same active run id, `bea7ff20106a`. WP-C can read the WP-A confidence tables and the WP-B alignment audit output from the same DB.

No Stage 01 changes touched `src/models/` or `src/features/`, and no DuckDB/WAL files are tracked. The diagnostic commands were all run with `--no-fetch`, and the report payloads record no external data fetch and no training algorithm modification.

Stage 01 remains diagnostic and research-only. It does not make HMM outputs validated trading signals, decision-ready outputs, or return probabilities. Because causal cache metadata is still unavailable, readiness remains `research_only` even though confidence and alignment integration are now readable.

## Tracked Risks

- No GitHub Actions CI is present for this repository.
- Causal cache metadata is unavailable, so readiness remains `research_only`.
- Label alignment ambiguity is high (`ambiguous_match_share=0.8666666666666667`) and must keep state identity interpretation conservative.
- Diagnostics were validated against a local V0 DB, not a CI-managed DB artifact.

## Blocking Issues

None.

## Next Recommended Stage

Proceed to Stage 02 only after preserving the Stage 01 boundary: treat HMM confidence, label alignment, and churn/dwell as diagnostics. Stage 02 should focus on causal cache/readiness evidence or CI-managed validation artifacts before any stronger display or decision-support claim is allowed.
