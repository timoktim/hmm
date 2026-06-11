# Stage03V WP3.5 Volatility-Scaled Threshold Sanity

- index_id: STAGE03V-WP3.5-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- wp1_support_status: pass
- wp2_controls_status: pass
- wp2_1_full_target_audit_status: pass
- wp3_baseline_diagnostics_status: pass
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- fixed_threshold_mainline_status: unchanged_reference_only
- volatility_scaled_threshold_status: candidate_for_wp4_research_tracking
- baseline_sanity_status: warning
- wp4_entry_recommendation: proceed_with_vol_scaled_candidate_tracking
- validation_row_count_evaluated: 43920
- prospective_holdout_rows_evaluated: 0
- vol_scaled_candidate_count: 48
- asof_mode_count: 2
- flagged_metric_row_count: 2378
- ci_gate_status: pass

## Leakage Counts

- feature_asof_violation_count: 0
- target_namespace_input_violation_count: 0
- future_column_input_violation_count: 0
- same_row_label_leakage_count: 0
- validation_label_leakage_count: 0
- prospective_holdout_score_count: 0
- prospective_holdout_metric_count: 0
- fixed_threshold_mainline_mutation_count: 0
- persistent_db_write_count: 0
- external_fetch_count: 0
- leakage_violation_count_total: 0

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_score_matrix_committed: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Blocking Reasons

- none
