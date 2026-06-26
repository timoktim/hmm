# HSMM Numba Engine

HSMM can use a numba backend for the per-sequence Viterbi dynamic programming kernel. The Python engine remains the reference implementation, while numba is the required fast path for local HSMM training speed gates.

Engine modes:

- `python`: always use the reference Python kernel.
- `numba`: require the numba kernel and raise a clear runtime error when unavailable.
- `auto`: prefer numba when it can be imported and executed, otherwise fall back to Python.

To enable the fast path in a local profiling environment:

```bash
python -m pip install numba
```

`requirements.txt` includes a numba version range compatible with the supported NumPy range. A missing numba package in `auto` mode is still a safe fallback to the Python kernel, not a semantic change, but the fallback now emits a visible warning carrying `fallback_reason`. That warning means the run should not be interpreted as a numba speedup measurement.

The kernel receives NumPy arrays only:

- emission log likelihoods
- log start probabilities
- log transition matrix
- log duration PMF

Pandas frames, model objects, storage handles, and database writers are not passed into the jitted function.

The first numba call includes JIT compilation overhead. Use `warm_hsmm_numba_engine()` in tests or controlled profiling if a warm compile is needed before measuring. Normal imports do not compile the kernel.

## Operational Check

Run the no-DB check before a benchmark or local maintenance profile:

```bash
bash scripts/check_hsmm_numba_engine.sh
```

It prints machine-readable lines:

```text
HSMM_NUMBA_CHECK_STATUS=pass|fallback|failed
numba_importable=yes|no
engine_used=numba|python|unavailable|failed
fallback_reason=<text-or-none>
compile_warmed=yes|no
```

`fallback` exits successfully by default so targeted CI can verify the fallback path without installing numba. Set `HSMM_ENGINE_REQUIRED=1` when a local benchmark must fail unless the numba engine is importable and warmed:

```bash
HSMM_ENGINE_REQUIRED=1 bash scripts/check_hsmm_numba_engine.sh
```

The check imports `src.models.hsmm_core`, exercises `warm_hsmm_numba_engine()`, and does not touch DuckDB, network fetches, caches, or local data files.

## Benchmark Matrix

Use the synthetic no-DB benchmark for a small operational sample:

```bash
bash scripts/hsmm_benchmark_matrix.sh
```

By default it compares `python`, `auto`, and `numba` requests across serial and parallel fit settings on deterministic synthetic sequences, then writes JSONL under `reports/hsmm_diagnostics/benchmark_sample/`. The `reports/` tree is gitignored, so sample outputs should remain local.

Useful local overrides:

```bash
HSMM_BENCHMARK_N_ITER=5 \
HSMM_BENCHMARK_MAX_DURATION=40 \
HSMM_BENCHMARK_SEQUENCE_LENGTH=96 \
bash scripts/hsmm_benchmark_matrix.sh
```

Local DB mode is opt-in only:

```bash
HSMM_BENCHMARK_MODE=local HSMM_BENCHMARK_DB=data/db/a_share_hmm.duckdb bash scripts/hsmm_benchmark_matrix.sh
```

If the requested DB is missing, the script prints `HSMM_BENCHMARK_STATUS=skipped reason=missing_db` and exits successfully.

Diagnostics are lightweight:

- requested engine
- resolved engine
- fallback reason
- numba availability
- compile warmed status

Walk-forward performance output may include the resolved engine and fallback reason, but DuckDB schema is not migrated by this package. Speedup is not guaranteed; it depends on sequence count, sequence length, state count, duration support, JIT warmup, and worker overhead.

This package changes runtime execution only. It does not change HSMM model semantics, lifecycle probability interpretation, readiness policy, thresholds, Stage04 validation behavior, or storage schema.

## WP1 Local Speed Gate

Use the local V7 speed gate when validating the HSMM-PERF-WP1 fast path:

```bash
PYTHON_BIN=.venv_service312/bin/python bash scripts/hsmm_training_speedup_gate.sh
```

The gate keeps the default model configuration unchanged:

- `n_states=4`
- `max_duration=60`
- `n_iter=20`
- `train_window_days=504`
- `train_frequency=monthly`

It enables the acceleration controls through invocation defaults:

- `hsmm_engine=auto`, which must resolve to `numba`
- `n_jobs=auto`
- `fit_n_jobs=auto`
- `sector_chunk_size=32`
- `fit_sequence_chunk_size=32`

The gate emits machine-readable lines:

```text
HSMM_SPEEDUP_GATE_STATUS=pass|fail
engine_used=numba|python|...
resolved_engine_is_numba=yes|no
fit_parallel_enabled=yes|no
fit_n_jobs=<value>
decode_n_jobs=<value>
walltime_seconds=<n>
target_seconds=600
config_unchanged=yes
core_count=<n>
run_id=<run-id>
db_path=<project-relative-path>
checkpoint_count=<n>
```

It fails if `resolved_engine_is_numba=no`, if fit parallelism is not exercised, or if wall time is at least 600 seconds.
