# Stage 01 WP-B HMM Label Alignment Report

- index_id: STAGE01-WP-B-v1
- generated_at: 2026-06-01T16:57:44Z
- status: pass
- db_path: data/db/a_share_hmm.duckdb
- db_used: true
- requested_run_id: latest
- resolved_run_id: bea7ff20106a
- comparison_mode: recent-runs
- alignment_method: hungarian
- run_pairs_compared: 5
- label_preserved_share: 1.0
- ambiguous_match_share: 0.8666666666666667
- high_drift_share: 0.0
- state_identity_readiness_status: research_only
- external_data_fetch: no
- training_algorithm_modified: no

## State Signature Fields Used

- avg_dwell_days
- avg_future_ret_10d
- avg_future_ret_20d
- avg_future_ret_5d
- median_amount_z_20d
- median_drawdown_20d
- median_ma20_slope
- median_ret_20d
- median_ret_5d
- median_rs_20d
- median_vol_20d
- occupancy_share
- transition_out_share

## Drift Severity Distribution

- medium: 13
- none: 2

## Run Pairs

- bea7ff20106a -> b59117f64b8e
- bea7ff20106a -> 1e8e3264c723
- bea7ff20106a -> 3976f04da5bb
- bea7ff20106a -> 521f828df14b
- bea7ff20106a -> 229c00a04097

## Coverage Limitations

- none

## Boundary

- Forward returns, when available, are empirical realized outcomes used only for state signatures.
- HMM posterior values are not interpreted as return probabilities.
- No HMM or HSMM training algorithm was modified by this diagnostic.
