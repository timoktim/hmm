# Stage03V WP3 Baseline Diagnostics

- index_id: STAGE03V-WP3-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- wp1_support_status: pass
- wp2_controls_status: pass
- wp2_1_full_target_audit_status: pass
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- fold_plan_status: pass
- baseline_policy_status: pass
- row_count_scored: 43920
- validation_row_count_evaluated: 43920
- prospective_holdout_rows_evaluated: 0
- slice_count_evaluated: 20
- fold_count_evaluated: 3
- baseline_count: 24
- range_based_availability_status: pass
- continuous_diagnostic_status: pass
- ci_gate_status: pass

## Leakage Counts

- feature_asof_violation_count: 0
- target_namespace_input_violation_count: 0
- future_column_input_violation_count: 0
- same_row_label_leakage_count: 0
- validation_label_leakage_count: 0
- prospective_holdout_score_count: 0
- prospective_holdout_metric_count: 0
- leakage_violation_count_total: 0

## Baseline Families

- continuous_target_proxy
- cross_sectional_market_event_share
- empirical_event_rate
- entity_empirical_event_rate
- range_based_volatility
- realized_volatility
- recent_drawdown

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- persistent_db_table_written: no
- full_feature_matrix_committed: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no

## Blocking Reasons

- none
