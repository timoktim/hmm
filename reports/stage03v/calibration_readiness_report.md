## Magnitude Overview

- fold_plan_source: full_labeled_historical_development_rows
- fold_count: 10
- validation_start_date: 2016-01-04
- validation_end_date: 2026-06-08
- total_validation_trade_dates: 2531
- validation_date_span_ratio: 0.8386173491853809
- min_fold_validation_trade_dates: 253
- min_fold_slice_train_rows: 57479
- prospective_holdout_label_consumed_count: 0

| fold_id | train_start | train_end | validation_start | validation_end | validation_dates | train_rows | validation_rows | min_slice_train_rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fold_1 | 2014-01-02 | 2015-12-31 | 2016-01-04 | 2017-01-16 | 254 | 1179592 | 626620 | 57479 |
| fold_2 | 2014-01-02 | 2017-01-16 | 2017-01-17 | 2018-01-26 | 253 | 1806056 | 627440 | 88790 |
| fold_3 | 2014-01-02 | 2018-01-26 | 2018-01-29 | 2019-02-18 | 253 | 2433496 | 627440 | 120162 |
| fold_4 | 2014-01-02 | 2019-02-18 | 2019-02-19 | 2020-03-03 | 253 | 3060936 | 627440 | 151534 |
| fold_5 | 2014-01-02 | 2020-03-03 | 2020-03-04 | 2021-03-17 | 253 | 3688376 | 627440 | 182906 |
| fold_6 | 2014-01-02 | 2021-03-17 | 2021-03-18 | 2022-03-31 | 253 | 4315816 | 627440 | 214278 |
| fold_7 | 2014-01-02 | 2022-03-31 | 2022-04-01 | 2023-04-17 | 253 | 4943256 | 627440 | 245650 |
| fold_8 | 2014-01-02 | 2023-04-17 | 2023-04-18 | 2024-05-07 | 253 | 5570696 | 627440 | 277022 |
| fold_9 | 2014-01-02 | 2024-05-07 | 2024-05-08 | 2025-05-22 | 253 | 6198136 | 627440 | 308394 |
| fold_10 | 2014-01-02 | 2025-05-22 | 2025-05-23 | 2026-06-08 | 253 | 6825576 | 610576 | 339766 |

# Stage03V WP5 Calibration Readiness

- index_id: STAGE03V-WP5-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- wp4_logistic_hazard_status: pass
- calibration_methods_evaluated: identity_uncalibrated_reference, platt_logistic_calibration, isotonic_calibration
- primary_calibration_method: platt_logistic_calibration
- evaluation_row_count_total: 6279824
- prospective_holdout_rows_evaluated: 0
- calibration_model_count: 768
- skipped_calibration_count: 32
- usable_probability_candidate_count: 5
- ordinal_only_candidate_count: 27
- baseline_only_candidate_count: 22
- research_only_count: 66
- insufficient_data_count: 0
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

- usable_probability_candidate: 5
- ordinal_only_candidate: 27
- baseline_only_candidate: 22
- research_only: 66
- insufficient_data: 0
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
