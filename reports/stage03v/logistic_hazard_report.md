# Stage03V WP4 Logistic Downside-Risk Hazard

- index_id: STAGE03V-WP4-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- wp1_support_status: pass
- wp2_controls_status: pass
- wp2_1_full_target_audit_status: pass
- wp3_baseline_diagnostics_status: pass
- wp3_5_vol_scaled_sanity_status: pass
- model_family: logistic_regression
- primary_asof_mode: close_t_minus_1
- validation_row_count_evaluated: 43920
- prospective_holdout_rows_evaluated: 0
- fitted_model_count: 52
- insufficient_data_slice_count: 68
- feature_count: 16
- vol_scaled_candidate_tracking_status: tracked_reference_only
- fixed_threshold_mainline_status: unchanged_primary_target
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

## Training Boundary Counts

- train_rows_after_validation_start_count: 0
- train_target_end_on_or_after_validation_start_count: 0
- validation_rows_used_for_fit_count: 0
- scaler_fit_on_validation_rows_count: 0
- imputer_fit_on_validation_rows_count: 0
- training_boundary_violation_count_total: 0

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_score_matrix_committed: no
- model_training: yes
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Remaining Risks

- WP4 scores are raw uncalibrated logistic outputs; probability calibration and readiness remain explicitly deferred.
- Outperformance versus WP3 baselines is diagnostic only and is not required for WP4 acceptance.
- Volatility-scaled candidates remain tracked reference metadata only and do not replace fixed-threshold labels.

## Blocking Reasons

- none
