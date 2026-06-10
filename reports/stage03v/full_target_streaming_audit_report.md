# Stage03V WP2.1 Full Target Streaming Audit

- index_id: STAGE03V-WP2.1-v1
- status: pass
- wp1_support_status: pass
- wp2_controls_status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- full_target_rows_checked: 7474840
- expected_target_row_count: 7474840
- row_count_delta: 0
- entity_count_checked: 124
- slice_count_checked: 20
- chunk_count: 30
- max_chunk_size: 250000
- memory_safety_status: pass
- violation_count_total: 0
- recompute_violation_count_total: 0
- purge_embargo_input_compatibility_status: pass
- feature_namespace_policy_status: pass
- ci_gate_status: pass

## Boundary Flags

- external_data_fetch: no
- target_dataset_modified: no
- persistent_db_table_written: no
- full_target_dataset_committed: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no

## Blocking Reasons

- none
