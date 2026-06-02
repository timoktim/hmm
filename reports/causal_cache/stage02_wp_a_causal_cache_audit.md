# Stage 02 WP-A Causal Cache Contract Audit

- index_id: STAGE02-WP-A-v1
- status: partial
- report_status: cache_not_linked_to_resolved_run_id
- db_path: data/db/a_share_hmm.duckdb
- local_db_used: true
- run_id_requested: latest
- resolved_run_id: bea7ff20106a
- causal_cache_available: true
- causal_cache_id: dbefc30c9c4c2328fea7
- cache_run_id: n/a
- cache_linkage_status: latest_unlinked_cache
- state_source: causal_backtest
- state_count: 30937
- sector_count: 464
- date_range: 2025-01-02 to 2026-05-27
- coverage_ratio: 0.052885
- readiness_status: research_only
- readiness_reason: cache_not_linked_to_resolved_run_id
- external_data_fetch: false
- training_algorithm_modified: false

## Contract Checks

- expected_state_rows: 584981
- unique_cache_state_rows: 30937
- duplicate_key_count: 0
- leakage_violation_count: 0
- train_end_violation_count: 0
- max_observation_date_used_violation_count: 0
- exec_date_violation_count: 0
- missing_metadata_count: 1
- train_end_max: 2026-05-06
- max_observation_date_used_max: 2026-05-27
- state_source_mix_found: false

## Tables Checked

| table | present | rows |
|---|---:|---:|
| walk_forward_cache_runs | true | 7 |
| walk_forward_state_cache | true | 226810 |
| sector_state_daily | true | 2655935 |
| model_runs | true | 25 |
| model_evidence_registry | false | n/a |
| validation_runs | false | n/a |

## Registry

- registry_written: false
- evidence_id: n/a
- validation_run_id: n/a
- registry_seed_payload_written: true

## Readiness Boundary

This audit is evidence for causal cache availability only. It does not train a model, fetch data, or make HMM outputs decision-ready.

## Warnings

- walk_forward_cache_runs lacks run_id linkage metadata
- audited latest walk-forward cache because no cache row can be proven to belong to the resolved HMM run
- execution metadata absent; exec_date > signal_date was not audited
- Stage 00 registry tables missing; wrote registry seed payload to summary JSON
