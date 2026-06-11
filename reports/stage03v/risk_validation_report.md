# Stage03V WP6 Risk Validation Report

- index_id: STAGE03V-WP6-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- historical_development_only: yes
- prospective_holdout_rows_evaluated: 0
- readiness_rows_evaluated: 60
- candidate_rows_evaluated: 60
- ci_gate_status: pass

## Validation Status Counts

- validation_pass_candidate: 4
- validation_watchlist: 2
- research_only_evidence: 34
- insufficient_validation_support: 20
- blocked_by_boundary_or_leakage: 0

## Downshift Tier Counts

- research_downshift_watch: 2
- research_downshift_candidate: 4
- research_downshift_insufficient: 54
- research_downshift_blocked: 0

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_raw_score_matrix_committed: no
- full_calibrated_score_matrix_committed: no
- model_training: no
- probability_recalibration: no
- readiness_reassigned: no
- validation_protocol_created: yes
- research_report_created: yes
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Remaining Risks

- WP6 validates historical-development evidence only; WP7 must run the final gate before any Stage03V1 acceptance claim.
- Downshift tiers are research-only evidence labels and are not trading, sizing, portfolio, or execution outputs.
- Volatility-scaled candidates remain tracked references and do not replace the fixed-threshold Stage03V1 target family.

## Blocking Reasons

- none
