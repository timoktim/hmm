# Stage 00 V0 Baseline Freeze Summary

- index_id: STAGE00-WP-B-v1
- work_package: STAGE00_WP_B_baseline_freeze
- status: pass
- verdict: BaselineFreezePassWithLocalDbInventory
- created_at: 2026-06-01T12:48:53+00:00
- external_fetch_attempted: no

## Environment

- python_version: 3.12.13
- duckdb_version: 1.5.3
- platform: macOS-26.4.1-arm64-arm-64bit
- working_directory: /private/tmp/hmm-wp-b
- is_git_repo: True
- git_sha: a74a3567934b410c83ed166bef030df5719a35c3

## Local DB Usage

- DB found: yes
- DB path: data/db/a_share_hmm.duckdb
- DB file size: 760492032
- DuckDB opened read-only: yes
- External fetch attempted=no
- db_available: True
- db_open_error: None
- evidence_registration: {'registered': False, 'reason': 'wp_a_registry_tables_missing'}

## HMM / Signal Validation Boundary

- Current positioning: causal nowcast / state context / weak auxiliary signal.
- Not accepted as a standalone trading decision engine.
- Default evidence_level: internal_diagnostic or research_only.
- Current HMM outputs are not promoted to validated_signal or decision_support.
- Sample-in states remain historical explanation only; causal walk-forward evidence is required for strategy claims.

## HSMM Lifecycle Boundary

- State age is displayable as an internal diagnostic.
- State phase is displayable as an internal diagnostic.
- Low/medium/high exit tendency is internal diagnostic ordinal tendency.
- Numeric p_exit is hidden unless usable_probability/readiness passes.
- Next-state tendency is a realized-profile tendency, not a predicted probability.
- HSMM lifecycle is not used for ranking or trading recommendations.

## UI Readiness Snapshot

- Probability displays remain restricted by evidence/readiness level.
- Causal and sample-in outputs must not be mixed for strategy evaluation.
- No UI readiness logic was modified by this work package.

## DB Table Inventory

- model_runs: rows=25, date_range=None..None, runs=25, sectors=None
- sector_state_daily: rows=2655935, date_range=2020-02-07..2026-05-28, runs=25, sectors=464
- walk_forward_cache_runs: rows=7, date_range=None..None, runs=None, sectors=None
- walk_forward_state_cache: rows=226810, date_range=2020-03-20..2026-05-27, runs=None, sectors=464
- hsmm_model_runs: rows=8, date_range=None..None, runs=8, sectors=None
- hsmm_model_checkpoints: rows=36, date_range=None..None, runs=8, sectors=None
- hsmm_state_daily: rows=244532, date_range=2025-01-02..2026-05-28, runs=8, sectors=464
- hsmm_state_episodes: rows=56806, date_range=None..None, runs=8, sectors=464
- hsmm_display_label_episodes: rows=29199, date_range=None..None, runs=1, sectors=464
- hsmm_lifecycle_ui_daily: rows=557104, date_range=2025-01-02..2026-05-28, runs=1, sectors=464
- hsmm_lifecycle_duration_profile: rows=8, date_range=2025-10-31..2026-05-28, runs=1, sectors=None
- hsmm_next_state_tendency_profile: rows=96, date_range=2025-10-31..2026-05-28, runs=1, sectors=None
- market_breadth_daily: rows=3092, date_range=2020-01-02..2026-05-26, runs=None, sectors=None
- sector_features: rows=632756, date_range=2020-01-02..2026-05-28, runs=None, sectors=465

## V0 Fact Checks

Reference points are recorded in baseline_snapshot.json and are not hard-coded pass criteria.
- fact_check_status: {"reference_notes": {"hsmm_run_id": "hsmm_lifecycle_primary_v1", "full_run_lifecycle_rows_reference": 155118, "date_range_reference": ["2025-01-02", "2026-05-28"], "sector_count_reference": 464, "trade_day_count_reference": 337, "duplicate_sector_date_reference": 0, "future_episode_leakage_reference": 0, "raw_score_used_violation_reference": 0}, "hsmm_lifecycle_ui_daily": {"run_id": "hsmm_lifecycle_primary_v1", "profile_mode": "latest_asof", "state_date_policy": "full_run", "row_count_for_run": 155118, "min_trade_date_for_run": "2025-01-02", "max_trade_date_for_run": "2026-05-28", "sector_count_for_run": 464, "trade_day_count_for_run": 337, "duplicate_sector_date_keys": 0, "raw_score_used_violation_count": 0}}

## Missing Artifacts

- none

## Validation Commands

- command: None
  result: not_run
  reason: --run-tests no
