# HSMM Performance Matrix Report

- index_id: HSMM-PERF0-1-2-v1
- status: pass
- mode: synthetic
- profile_count: 32
- pass_profile_count: 32
- fallback_rows: 16
- fit_parallel_fallback_rows: 16
- bottleneck_classification: fit_decode_dominant
- numba_status: fallback
- numba_engine_used: python
- numba_fallback_reason: numba unavailable
- local_profile_status: not_run
- no_db_write: yes
- persistent_db_writes: no

## Preset Validation

- preset_config_path: configs/hsmm_performance_presets_v1.yaml
- preset_validation_status: pass

## Numba Check

- requested_engine: numba
- resolved_engine: python
- fallback_reason: numba unavailable
- numba_available: no
- compile_warmed: no

## Boundary Flags

- model_semantics_changed: no
- approximate_pruned_viterbi_added: no
- production_hsmm_model_rows_written: no
- persistent_db_writes: no
- stage03v_artifacts_modified: no
- holdout_consumed: no
- trading_or_decision_output: no

## Profiles

|profile_id|status|engine_requested|engine_used|engine_fallback_reason|fit_n_jobs|fit_n_jobs_resolved|max_duration|n_iter|total_runtime_seconds|bottleneck_classification|
|---|---|---|---|---|---|---|---|---|---|---|
|synthetic__engine_python__iter_2__dur_20__fitjobs_1__chunk_8|pass|python|python|none|1|1|20|2|0.032321|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_20__fitjobs_1__chunk_32|pass|python|python|none|1|1|20|2|0.017212|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_20__fitjobs_auto__chunk_8|pass|python|python|none|auto|2|20|2|0.025262|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_20__fitjobs_auto__chunk_32|pass|python|python|none|auto|2|20|2|0.019602|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_40__fitjobs_1__chunk_8|pass|python|python|none|1|1|40|2|0.019069|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_40__fitjobs_1__chunk_32|pass|python|python|none|1|1|40|2|0.019087|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_40__fitjobs_auto__chunk_8|pass|python|python|none|auto|2|40|2|0.01868|fit_decode_dominant|
|synthetic__engine_python__iter_2__dur_40__fitjobs_auto__chunk_32|pass|python|python|none|auto|2|40|2|0.018665|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_20__fitjobs_1__chunk_8|pass|python|python|none|1|1|20|3|0.017669|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_20__fitjobs_1__chunk_32|pass|python|python|none|1|1|20|3|0.018625|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_20__fitjobs_auto__chunk_8|pass|python|python|none|auto|2|20|3|0.017755|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_20__fitjobs_auto__chunk_32|pass|python|python|none|auto|2|20|3|0.01861|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_40__fitjobs_1__chunk_8|pass|python|python|none|1|1|40|3|0.017983|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_40__fitjobs_1__chunk_32|pass|python|python|none|1|1|40|3|0.01962|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_40__fitjobs_auto__chunk_8|pass|python|python|none|auto|2|40|3|0.01842|fit_decode_dominant|
|synthetic__engine_python__iter_3__dur_40__fitjobs_auto__chunk_32|pass|python|python|none|auto|2|40|3|0.017851|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_20__fitjobs_1__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|20|2|0.018013|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_20__fitjobs_1__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|20|2|0.019249|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_20__fitjobs_auto__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|20|2|0.019142|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_20__fitjobs_auto__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|20|2|0.018135|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_40__fitjobs_1__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|40|2|0.017584|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_40__fitjobs_1__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|40|2|0.017965|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_40__fitjobs_auto__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|40|2|0.018229|fit_decode_dominant|
|synthetic__engine_auto__iter_2__dur_40__fitjobs_auto__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|40|2|0.017939|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_20__fitjobs_1__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|20|3|0.017321|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_20__fitjobs_1__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|20|3|0.017299|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_20__fitjobs_auto__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|20|3|0.017945|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_20__fitjobs_auto__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|20|3|0.017582|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_40__fitjobs_1__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|40|3|0.018306|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_40__fitjobs_1__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|1|1|40|3|0.018325|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_40__fitjobs_auto__chunk_8|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|40|3|0.019238|fit_decode_dominant|
|synthetic__engine_auto__iter_3__dur_40__fitjobs_auto__chunk_32|pass|auto|python|ModuleNotFoundError: No module named 'numba'|auto|2|40|3|0.019087|fit_decode_dominant|
