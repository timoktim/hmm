# Stage03V WP6 Risk Validation Protocol

- index_id: STAGE03V-WP6-v1
- status: pass
- information_cutoff_date: 2026-06-10
- holdout_start: 2026-06-11
- historical_development_only: True
- final_holdout_policy: withheld_not_scored
- primary_target_family: fixed_threshold_stage03v1_downside_event
- vol_scaled_candidate_policy: tracked_reference_only

## Validation Dimensions

- coverage and support
- calibration stability
- fold stability
- clustered uncertainty
- lead-time and event capture
- false alarm concentration
- drawdown/event lift by score bin
- threshold sensitivity
- entity concentration
- calendar-date concentration
- baseline comparison
- known WP3/WP3.5 anomaly handling

## Validation Statuses

- validation_pass_candidate
- validation_watchlist
- research_only_evidence
- insufficient_validation_support
- blocked_by_boundary_or_leakage

## Downshift Research Tiers

- research_downshift_watch: research_only=yes; not_trading_output=yes
- research_downshift_candidate: research_only=yes; not_trading_output=yes
- research_downshift_insufficient: research_only=yes; not_trading_output=yes
- research_downshift_blocked: research_only=yes; not_trading_output=yes

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- fixed_threshold_mainline_modified: no
- persistent_db_table_written: no
- full_target_matrix_committed: no
- full_feature_matrix_committed: no
- full_raw_score_matrix_committed: no
- full_calibrated_score_matrix_committed: no
- model_training: no
- probability_recalibration: no
- readiness_reassigned: no
- validation_protocol_created: yes
- research_report_created: yes
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
- trading_or_decision_output: no
