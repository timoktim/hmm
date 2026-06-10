# Stage03V WP2 Target Controls

- index_id: STAGE03V-WP2-v1
- status: pass
- contract_status: pass
- wp1_support_status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- db_opened_read_only: yes
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- entity_count_after_silent_break_handling: 124
- target_row_count_checked: 500
- label_window_violation_count: 0
- cross_cutoff_regression_passed: yes
- cross_cutoff_violation_count: 0
- prospective_holdout_label_consumed_count: 0
- fold_count: 3
- purge_violation_count: 0
- embargo_violation_count: 0
- feature_namespace_policy_status: pass
- ci_gate_status: pass

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no

## Blocking Reasons

- none

## Feature Namespace Policy

- event_label
- future_return
- future_mae
- future_mdd
- future_realized_vol
- future_downside_vol
- target_observation_start_date
- target_observation_end_date
- censoring_status
- exclusion_reason
- holdout_label_status
- future_*
- target_*
- post_trade_date_price_derived_fields
