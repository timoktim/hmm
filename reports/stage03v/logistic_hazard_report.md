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
- validation_row_count_evaluated: 6256716
- prospective_holdout_rows_evaluated: 0
- fitted_model_count: 400
- insufficient_data_slice_count: 0
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
