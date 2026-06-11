# Stage03V WP5 Calibration Readiness

- index_id: STAGE03V-WP5-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- wp4_logistic_hazard_status: pass
- calibration_methods_evaluated: identity_uncalibrated_reference, platt_logistic_calibration, isotonic_calibration
- primary_calibration_method: platt_logistic_calibration
- evaluation_row_count_total: 19032
- prospective_holdout_rows_evaluated: 0
- calibration_model_count: 28
- skipped_calibration_count: 280
- usable_probability_candidate_count: 4
- ordinal_only_candidate_count: 2
- baseline_only_candidate_count: 10
- research_only_count: 24
- insufficient_data_count: 20
- ci_gate_status: pass

## Leakage Counts

- feature_asof_violation_count: 0
- target_namespace_input_violation_count: 0
- future_column_input_violation_count: 0
- same_row_label_leakage_count: 0
- evaluation_label_leakage_count: 0
- prospective_holdout_score_count: 0
- prospective_holdout_metric_count: 0
- fixed_threshold_mainline_mutation_count: 0
- persistent_db_write_count: 0
- external_fetch_count: 0
- leakage_violation_count_total: 0

## Calibration Boundary Counts

- calibration_rows_on_or_after_evaluation_start_count: 0
- evaluation_rows_used_for_calibrator_fit_count: 0
- holdout_rows_used_for_calibration_count: 0
- holdout_rows_used_for_evaluation_count: 0
- serialized_calibration_model_count: 0
- new_non_logistic_model_family_count: 0
- trading_or_decision_output_count: 0
- calibration_boundary_violation_count_total: 0

## Readiness Category Counts

- usable_probability_candidate: 4
- ordinal_only_candidate: 2
- baseline_only_candidate: 10
- research_only: 24
- insufficient_data: 20
- blocked_by_leakage: 0

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_score_matrix_committed: no
- calibration_model_serialized: no
- model_training: no_new_non_logistic_model
- probability_calibration: yes
- readiness_assigned: yes_development_only
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Remaining Risks

- Readiness labels are development-only candidates and are not final decision-support approval.
- Prospective final holdout remains unconsumed; WP6/WP7 must handle later validation protocol work.
- Volatility-scaled candidates remain reference-only and do not replace fixed-threshold Stage03V1 labels.

## Blocking Reasons

- none
