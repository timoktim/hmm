# HSMM Performance Profile

HSMM walk-forward cost has two large parts:

- checkpoint fit: each EM iteration decodes every training sequence with Viterbi, then updates the duration, transition, and emission parameters;
- snapshot decode: each trained checkpoint produces lifecycle snapshots for the dates it serves.

`DiscreteDurationGaussianHSMM.fit()` now accepts `n_jobs` and `sequence_chunk_size`. When `n_jobs` resolves above 1 and there is more than one training sequence, each EM iteration serializes the current fitted parameter payload and decodes sequence chunks with joblib process workers. If joblib import or execution fails, fit falls back to the serial path and marks the fallback in diagnostics.

The existing prefix snapshot decoder still uses `n_jobs` and `sector_chunk_size`. In walk-forward config, `fit_n_jobs` controls checkpoint fit decode; when it is omitted, fit decode uses the same value as `n_jobs`. `fit_sequence_chunk_size` controls how many training sequences each fit worker receives.

Performance diagnostics are returned in the walk-forward result and written to public profile reports:

- `fit_n_jobs`
- `fit_parallel_enabled`
- `fit_parallel_fallback`
- `fit_iteration_count`
- `fit_decode_seconds`
- `fit_update_seconds`
- `decode_n_jobs`
- `sector_chunk_size`
- `snapshot_decode_mode`
- `hsmm_engine`
- `engine_used`
- `engine_fallback_reason`

The DuckDB table `hsmm_run_performance` is not migrated by this package. Runtime returns and CSV/profile outputs may contain the extended diagnostics, while DB persistence keeps the existing table columns.

## Profile Only

Use profile-only mode to estimate scale without writing HSMM model rows:

```bash
bash scripts/hsmm_performance_profile.sh
```

The script reads these optional environment variables:

- `HSMM_PROFILE_DB`: DuckDB path; defaults to `ASHARE_HMM_DB_PATH` or `data/db/a_share_hmm.duckdb`
- `HSMM_PROFILE_START_DATE`: defaults to `20250101`
- `HSMM_PROFILE_END_DATE`: defaults to `today`
- `HSMM_PROFILE_N_JOBS`: defaults to `auto`
- `HSMM_PROFILE_FIT_N_JOBS`: defaults to `HSMM_PROFILE_N_JOBS`
- `HSMM_PROFILE_ENGINE`: defaults to `HSMM_ENGINE` or `auto`
- `HSMM_PROFILE_MAX_DURATION`: defaults to `40`
- `HSMM_PROFILE_N_ITER`: defaults to `10`
- `HSMM_PROFILE_RUN_ID`: optional run id

The shorter aliases `HSMM_ENGINE`, `HSMM_N_JOBS`, `HSMM_FIT_N_JOBS`, `HSMM_MAX_DURATION`, and `HSMM_N_ITER` are also accepted for quick local profiling.

If the DB path is missing, the script prints a skipped status and exits successfully.

The script also prints the requested engine and a fallback reminder before it checks the DB path. In `auto` mode, a missing or unusable numba runtime falls back to the Python Viterbi kernel. That fallback is safe, but it means the run should not be interpreted as a numba speedup measurement.

## Numba Operational Checks

The optional numba engine has a no-DB operational check:

```bash
bash scripts/check_hsmm_numba_engine.sh
```

The check reports whether numba can be imported, which engine was actually warmed, the fallback reason, and whether compilation was warmed. Missing numba exits successfully as `HSMM_NUMBA_CHECK_STATUS=fallback` unless `HSMM_ENGINE_REQUIRED=1` is set.

For a small benchmark matrix that is safe to run without DuckDB:

```bash
bash scripts/hsmm_benchmark_matrix.sh
```

The default mode uses deterministic synthetic sequences and writes a local JSONL sample under `reports/hsmm_diagnostics/benchmark_sample/`. That output path is gitignored and should not be committed.

Local DB profiling through the benchmark wrapper is explicit:

```bash
HSMM_BENCHMARK_MODE=local HSMM_BENCHMARK_DB=data/db/a_share_hmm.duckdb bash scripts/hsmm_benchmark_matrix.sh
```

If the DB path is missing, local DB mode prints `HSMM_BENCHMARK_STATUS=skipped reason=missing_db` and exits successfully.

## Presets

Fast maintenance:

- `n_iter`: 8 to 10
- `max_duration`: 40
- `train_frequency`: monthly
- `snapshot_decode_mode`: prefix
- `n_jobs`: auto

Standard maintenance:

- `n_iter`: 20
- `max_duration`: 60
- `train_frequency`: monthly
- `snapshot_decode_mode`: prefix
- `n_jobs`: auto

Full maintenance should be reserved for explicit research maintenance windows where longer duration support or higher iteration counts are needed.

HSMM remains lifecycle interpretation infrastructure. These settings only affect runtime and diagnostics; they do not change lifecycle probability meaning, readiness policy, thresholds, or downstream outputs.
