# Stage03V1 Phase 1 Closeout Report

- index_id: STAGE03V-CLOSEOUT1-v1
- status: pass
- wp7_v2_merged: yes
- wp7_v2_final_gate_verdict: PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass

## Final Interpretation

- engineering_result: pass
- causality_result: pass
- model_discrimination_result: pass
- primary_risk_downshift_result: baseline_superior_on_primary_risk_metrics
- secondary_return_result: model_retains_more_return_secondary_metric
- prospective_holdout_result: defer_or_insufficient
- stage03v1_decision_support_status: not_promoted
- stage03v1_model_usage_status: research_only_overlay
- stage03v1_baseline_usage_status: volatility_baseline_primary_for_risk_control_research

Stage03V1 phase-one engineering, causality, and model-discrimination gates pass. The accepted historical-development interpretation is not model promotion: RERUN1/WP7-v2 show model discrimination as a research claim, while the realized-volatility baseline is superior on the pre-registered primary risk downshift metrics. Prospective holdout review remains deferred and unconsumed.

## WP7-v2 Headline Evidence

- candidate_slice_count: 32
- scored_candidate_slice_count: 32
- validation_entity_day_count: 5021776
- wp4_validation_rows_evaluated: 6256716
- wp5_usable_probability_candidate_count: 5
- model_minus_baseline_delta_count: 160
- model_better_primary_risk_delta_count: 11
- baseline_better_primary_risk_delta_count: 85
- significant_model_better_primary_risk_delta_count: 0
- significant_baseline_better_primary_risk_delta_count: 26
- registered_holdout_min_complete_20d_label_trade_dates: 120
- registered_holdout_min_market_event_blocks: 2
- prospective_holdout_rows_evaluated: 0
- prospective_holdout_consumption_count: 0

## Artifact Freeze

- artifact_freeze_manifest_path: reports/stage03v/stage03v1_artifact_freeze_manifest.json
- canonical_artifact_count: 91
- invalidated_artifact_registry_path: reports/stage03v/stage03v1_invalidated_artifact_registry.json
- invalidated_artifact_count: 7

Canonical Stage03V1 phase-one evidence must use WP0-WP3.5, FIX1, RERUN1, and WP7-v2 artifacts listed in the freeze manifest. Old microfold WP4-WP6 empirical artifacts and old WP7-v1 evidence are non-canonical and must not be cited as evidence of signal strength or weakness.

## Phase 2 Handoff

- recommended_phase2_direction: baseline_first_risk_control_architecture
- phase2_immediate_next_package: PHASE2-WP0
- phase2_handoff_path: reports/stage03v/stage03v1_phase2_handoff.json

Phase 2 should start with a baseline-first risk-control roadmap. The hazard model remains a research-only overlay unless a future authorized package creates and accepts a new pre-registered hypothesis.

## Boundaries

- external_data_fetch: no
- new_experiment_run: no
- model_training: no
- probability_recalibration: no
- readiness_reassigned: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- prospective_holdout_performance_consumed: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no

## Remaining Risks

- Prospective holdout performance remains unconsumed and insufficient for promotion until a future authorized quarterly review package meets the registered 120 trade-date and 2 event-block minimums.
- RERUN1 validates model discrimination as a research claim, but the realized-volatility baseline is superior on pre-registered primary risk downshift metrics.
- Stage03V2 and Stage03V3 remain placeholders and require new pre-registered hypotheses before implementation.
