# Stage03V1 Final Gate v2 Report

- index_id: STAGE03V-WP7-v2
- status: pass
- final_gate_verdict: PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass

## Gate Status

- engineering_gate_status: pass
- causality_gate_status: pass
- rerun1_magnitude_gate_status: pass
- model_discrimination_status: model_discrimination_pass
- primary_risk_metric_comparison_status: baseline_superior_on_primary_risk_metrics
- secondary_return_status: model_retains_more_return_secondary_metric
- prospective_holdout_readiness_gate_status: defer_or_insufficient
- decision_support_promotion_gate_status: defer_or_reject_model_as_primary_downshift_driver

## Claims

- model_discrimination_claim: model_has_validated_discrimination_on_full_scale_rerun
- primary_risk_downshift_claim: volatility_baseline_superior_for_primary_risk_reduction
- secondary_return_claim: model_retains_more_return_secondary_metric
- recommended_use_after_gate: research_only_model_overlay_or_volatility_baseline_primary

Model discrimination and primary risk downshift control are separate claims. RERUN1 validates model discrimination, while the pre-registered primary-risk downshift comparison favors the volatility baseline.

## RERUN1 Summary

- candidate_slice_count: 32
- scored_candidate_slice_count: 32
- validation_entity_day_count: 5021776
- wp4_validation_rows_evaluated: 6256716
- wp5_usable_probability_candidate_count: 5
- model_minus_baseline_delta_count: 160
- significant_model_better_primary_risk_delta_count: 0
- significant_baseline_better_primary_risk_delta_count: 26

## Prospective Holdout

- prospective_holdout_complete_20d_label_trade_dates: 0
- prospective_holdout_market_event_block_count: 0
- registered_min_complete_20d_label_trade_dates: 120
- registered_min_market_event_blocks: 2
- prospective_holdout_rows_evaluated: 0
- prospective_holdout_consumption_count: 0
- prospective_holdout_gate_status: defer_or_insufficient

## Boundaries

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_raw_score_matrix_committed: no
- full_calibrated_score_matrix_committed: no
- full_exposure_matrix_committed: no
- model_training: no
- probability_recalibration: no
- readiness_reassigned: no
- final_gate_executed: yes
- prospective_holdout_performance_consumed: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Remaining Risks

- Prospective holdout performance remains unconsumed and must be reviewed only by a future authorized package.
- RERUN1 B2 supports model discrimination as a separate claim but favors the volatility baseline on primary risk downshift metrics.
