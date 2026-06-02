# Stage 01 Integration Summary

index_id: STAGE01-WP-D-v1
status: pass
final_verdict: Stage01PassWithTrackedRisks
branch: stage01/wp-d-integration-summary
generated_at: 2026-06-02T02:00:35Z

## Local DB Validation

- db path used: data/db/a_share_hmm.duckdb
- resolved path: /Users/tianxiwang/Documents/HMM高阶分析器/.codex_worktrees/stage01_wp_c/data/db/a_share_hmm.duckdb
- preflight: pass
- opened read-only where applicable: yes
- model_runs: 25
- sector_state_daily: 2655935
- walk_forward_cache_runs: 7
- walk_forward_state_cache: 226810
- hsmm_lifecycle_ui_daily: 557104
- external data fetch: no
- DuckDB committed: no

## Merged PRs Checked

- PR #6: merged, WP-A confidence metrics, merge commit b452ec3b
- PR #7: merged, WP-B label alignment, merge commit f58b470
- PR #5: merged, WP-C churn/dwell diagnostics, merge commit 953c831

## Core Metrics

- shared run_id: bea7ff20106a
- confidence rows: 584981
- confidence readiness: internal_only
- posterior columns found: yes
- label alignment run pairs: 5
- alignment method: hungarian
- ambiguous_match_share: 0.8666666666666667
- label_preserved_share: 1.0
- high_drift_share: 0.0
- churn/dwell rows: 42210
- churn_bucket: low
- confidence_integration_status: available_confidence
- alignment_integration_status: available_alignment
- causal_cache_available: false
- readiness/display action: research_only / research_only

## Hard Issue Result

- blocking issues: none
- tracked risks:
  - No GitHub Actions CI.
  - Causal cache unavailable, so readiness remains research_only.
  - Label alignment ambiguity is high.
  - Diagnostics rely on local V0 DB validation rather than CI-managed DB artifact.

Stage 01 is accepted as diagnostic/research-only work with tracked risks. It does not make HMM outputs decision-ready.
