# Stage04-WP3 Annotation Label Completeness Gate

- status: pass
- report_version: stage04_wp3_annotation_label_gate_v1
- index_id: STAGE04-WP3
- source_wp2_report_version: stage04_wp2_break_casebook_v1

This report validates annotation records and label completeness only. It does not evaluate predictive performance, provide trading output, define a decision layer, or consume final holdout.

## Boundary Flags
- external_data_fetch: no
- model_retrained: no
- hmm_hsmm_training_changed: no
- hazard_model_changed: no
- threshold_tuning: no
- final_holdout_consumed: no
- decision_engine_output: no
- trading_output: no
- duckdb_schema_changed: no
- duckdb_committed: no

## Split Registry Lock Summary
- status: locked
- evidence_cutoff_date: 2026-05-28
- future_holdout_start_rule: strictly_after_evidence_cutoff_date
- expected_horizons: [1, 3, 5, 10, 20]
- final_holdout_consumption_count: 0
- threshold_tuning_after_lock: no
- model_retraining_after_lock: no
- hmm_hsmm_retraining_after_lock: no
- hsmm_exit_probability_review_use: no
- analysis_layer_output: no
- external_data_fetch: no
- private_db_required_in_ci: no

## WP2 Source Summary
- status: pass
- index_id: STAGE04-WP2
- report_version: stage04_wp2_break_casebook_v1
- prospective_validation_status: annotation_only
- final_holdout_consumed: no
- final_holdout_consumption_count: 0
- threshold_tuning_after_lock: no
- model_retraining_after_lock: no

## Annotation Ledger Summary
- annotation_ledger_path: reports/stage04/prospective_break_annotation.local.jsonl
- annotation_ledger_exists: no
- local_annotations_gitignored: yes
- line_count: 0
- blank_line_count: 0
- template_record_count: 0
- annotation_record_count: 0
- invalid_line_count: 0
- allowed_record_types: ['annotation', 'candidate_check', 'review']
- required_fields: ['schema_version', 'record_type', 'annotation_date', 'diagnostic_trade_date', 'break_warning_level', 'component_stress_labels', 'available_component_count', 'analyst_annotation', 'observed_market_context', 'followup_required', 'forbidden_use_notice', 'boundary_flags']
- boundary_violation_count: 0

## Label Completeness Summary
- required_horizons: [1, 3, 5, 10, 20]
- annotation_record_count: 0
- label_completeness_status_counts: {}
- complete_record_count: 0
- pending_record_count: 0
- unknown_db_missing_record_count: 0
- pre_lock_violation_record_count: 0
- invalid_date_record_count: 0
- calendar:
  - db_available: no
  - db_path: data/db/a_share_hmm.duckdb
  - calendar_status: db_missing
  - selected_market_index_code: None
  - calendar_trade_date_count: 0
  - calendar_min_trade_date: None
  - calendar_max_trade_date: None

## Bounded Annotation Record Sample
- none

## Prospective Validation Status
not_started

## Causal Boundary
- external_data_fetch: no
- local_db_calendar_only: yes
- performance_metrics_computed: no
- returns_or_outcomes_computed: no
- threshold_tuning_after_lock: no
- model_retraining_after_lock: no
- hmm_hsmm_training_changed: no
- hazard_model_changed: no
- final_holdout_consumed: no
- label_check_scope: future trading day availability only

## Recommended Next Stage
Continue local annotation collection and rerun this annotation gate when required future horizons are available.
