# Stage04-WP2 Break Diagnostic Casebook

- status: pass
- report_version: stage04_wp2_break_casebook_v1
- index_id: STAGE04-WP2
- source_wp1_report_version: stage04_wp1_break_detector_v1

This report is annotation infrastructure only and does not provide trading, sizing, ranking, or decision output.

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

## Split Registry Lock
- status: locked
- evidence_cutoff_date: 2026-05-28
- future_holdout_start_rule: strictly_after_evidence_cutoff_date
- expected_horizons: [1, 3, 5, 10, 20]
- minimum_candidate_holdout_start_date: 2026-05-29
- final_holdout_consumed: no
- final_holdout_consumption_count: 0
- threshold_tuning_after_lock: no
- model_retraining_after_lock: no
- decision_layer_output: no
- external_data_fetch: no

## Input Summary
- db_available: yes
- db_path: <local:a_share_hmm.duckdb>
- wp1_summary_path: reports/stage04/stage04_wp1_break_detector_report.json
- split_registry_path: reports/stage04/split_registry.json
- wp1_committed_status: pass
- wp1_regenerated_status: pass
- wp1_committed_latest_trade_date: 2026-05-28
- wp1_regenerated_latest_trade_date: 2026-06-04
- diagnostic_rows: 1550
- latest_diagnostic_trade_date: 2026-05-28
- latest_break_warning_level: normal

## Episode Summary
- episode_count: 216
- peak_warning_level_counts: {'elevated': 85, 'high': 28, 'watch': 103}
- earliest_episode_start: 2020-02-24
- latest_episode_end: 2026-05-27

## Casebook Sample
| episode_id | start_date | end_date | duration | peak_warning_level | dominant_components |
|---|---:|---:|---:|---|---|
| stage04-wp2-episode-212 | 2026-03-02 | 2026-04-21 | 36 | high | breadth,market,hmm_confidence,sector |
| stage04-wp2-episode-207 | 2026-01-05 | 2026-01-16 | 10 | high | breadth,sector |
| stage04-wp2-episode-202 | 2025-11-18 | 2025-12-09 | 16 | high | breadth,hmm_confidence,sector |
| stage04-wp2-episode-196 | 2025-08-08 | 2025-09-30 | 38 | high | market,breadth,hmm_confidence,sector |
| stage04-wp2-episode-193 | 2025-07-17 | 2025-07-25 | 7 | high | breadth,sector,hmm_confidence |
| stage04-wp2-episode-178 | 2025-04-03 | 2025-05-07 | 21 | high | market,breadth,sector,hmm_confidence |
| stage04-wp2-episode-172 | 2025-02-05 | 2025-02-19 | 11 | high | breadth,sector,hmm_confidence |
| stage04-wp2-episode-162 | 2024-10-08 | 2024-11-01 | 19 | high | market,sector,breadth |
| stage04-wp2-episode-161 | 2024-09-24 | 2024-09-30 | 5 | high | breadth,market,sector,hmm_confidence |
| stage04-wp2-episode-155 | 2024-07-31 | 2024-08-20 | 15 | high | market,breadth,sector,hmm_confidence |
| stage04-wp2-episode-137 | 2024-02-19 | 2024-03-05 | 12 | high | market,breadth,sector,hmm_confidence |
| stage04-wp2-episode-136 | 2024-01-17 | 2024-02-08 | 17 | high | market,breadth,sector |
| stage04-wp2-episode-126 | 2023-10-18 | 2023-10-31 | 10 | high | breadth,hmm_confidence,sector |
| stage04-wp2-episode-121 | 2023-07-25 | 2023-09-07 | 33 | high | breadth,market,hmm_confidence,sector |
| stage04-wp2-episode-116 | 2023-06-19 | 2023-06-29 | 7 | high | breadth,market,hmm_confidence,sector |
| stage04-wp2-episode-090 | 2022-10-10 | 2022-11-24 | 34 | high | market,breadth,sector,hmm_confidence |
| stage04-wp2-episode-089 | 2022-08-24 | 2022-09-30 | 27 | high | breadth,sector |
| stage04-wp2-episode-087 | 2022-08-02 | 2022-08-05 | 4 | high | breadth,sector,hmm_confidence |
| stage04-wp2-episode-073 | 2022-04-21 | 2022-04-29 | 7 | high | breadth,sector,market |
| stage04-wp2-episode-071 | 2022-02-07 | 2022-03-01 | 17 | high | market,breadth,sector,hmm_confidence |

## Prospective Annotation Protocol
- schema_version: stage04_break_annotation_v1
- record_type: template
- template_path: reports/stage04/prospective_break_annotation.template.jsonl
- local_annotation_path: reports/stage04/prospective_break_annotation.local.jsonl
- local_annotations_gitignored: yes
- required_fields: ['schema_version', 'record_type', 'annotation_date', 'diagnostic_trade_date', 'break_warning_level', 'component_stress_labels', 'available_component_count', 'analyst_annotation', 'observed_market_context', 'followup_required', 'forbidden_use_notice', 'boundary_flags']
- forbidden_use_notice: Research annotation only; not a trading signal, not a decision layer, and not empirical promotion evidence.

## Prospective Validation Status
annotation_only

## Causal Boundary
- source_wp1_index_id: STAGE04-WP1
- source_wp1_rolling_baseline_excludes_current_row: yes
- future_rows_used: no
- casebook_source: full_in_memory_wp1_diagnostic
- casebook_capped_to_committed_wp1_range: yes
- full_diagnostic_csv_written: no

## Recommended Next Stage
Collect local prospective annotations before any later package considers promotion criteria.
