# HSMM_PERF0_1_2_profile_presets_numba_parallel

Project area: HSMM performance optimization

Work package: PERF0 + PERF1 + PERF2

Index id: `HSMM-PERF0-1-2-v1`

Suggested branch: `hsmm/perf0-1-2-profile-presets-numba-parallel`

Codex instruction: `docs/codex_instructions/hsmm/CODEX_HSMM_PERF0_1_2_profile_presets_numba_parallel.md`

Date: 2026-06-12

## Objective

Implement the first HSMM performance optimization bundle:

```text
PERF0: Profile matrix and bottleneck attribution
PERF1: Maintenance presets and runtime configuration hardening
PERF2: Numba / joblib parallel hardening and fallback visibility
```

This bundle must answer where HSMM runtime is being spent, provide safe fast/standard/full presets, and ensure the existing numba/joblib acceleration path is observable and not silently falling back.

This package must not change HSMM model semantics, lifecycle probability meanings, readiness policy, Stage03V conclusions, targets, or downstream decision outputs.

## Background anchors

Read these first:

```text
docs/runtime/HSMM_PERFORMANCE.md
src/models/hsmm_core.py
src/models/hsmm_model.py
src/models/hsmm_walk_forward.py
scripts/hsmm_performance_profile.sh
scripts/check_hsmm_numba_engine.sh
scripts/hsmm_benchmark_matrix.sh
```

Known current infrastructure:

```text
DiscreteDurationGaussianHSMM.fit accepts n_jobs and sequence_chunk_size.
HSMM walk-forward config exposes n_jobs, fit_n_jobs, fit_sequence_chunk_size, hsmm_engine, max_duration, n_iter, train_frequency, snapshot_decode_mode.
Viterbi DP supports python / auto / numba engine selection.
Numba unavailable or failed runtime can fall back to python unless hsmm_engine='numba' is required.
Joblib process parallel fit decode can fall back to serial and records fallback flags.
Existing diagnostics include fit_decode_seconds, fit_update_seconds, decode_seconds, engine_used, engine_fallback_reason, fit_parallel_enabled, fit_parallel_fallback.
```

## Scope

Allowed:

- Add profile-matrix tooling that runs no-DB synthetic profiles and optional local-DB profile-only runs.
- Add a checked HSMM maintenance preset config.
- Add tests that validate preset semantics and acceleration diagnostics.
- Add a gate script that verifies profile tools, numba check behavior, no silent fallback metadata, JSON validity, and private path hygiene.
- Improve diagnostics/reporting around engine fallback and fit parallel fallback.
- Harden existing scripts so profile outputs are explicit, reproducible, and not accidentally committed if local/private.

Forbidden:

- Do not change HSMM statistical semantics.
- Do not add approximate/pruned Viterbi.
- Do not change duration probability meaning, lifecycle probability meaning, readiness policy, or display semantics.
- Do not change default model outputs without an explicit profile/preset mode.
- Do not train production HSMM models as part of CI.
- Do not require private DuckDB for CI.
- Do not write persistent DuckDB tables in profile-only mode.
- Do not modify Stage03V target/model/readiness artifacts.
- Do not consume prospective holdout.
- Do not create trading, buy/sell, sizing, recommendation, execution, or portfolio-action outputs.

## PERF0 requirements: profile matrix

Create a deterministic HSMM profile matrix runner.

Required deliverables:

```text
src/evaluation/hsmm_performance_matrix.py
scripts/hsmm_performance_matrix_gate.sh
tests/test_hsmm_performance_matrix.py
reports/hsmm_diagnostics/hsmm_performance_matrix_report.md
reports/hsmm_diagnostics/hsmm_performance_matrix_report.json
reports/hsmm_diagnostics/hsmm_performance_matrix_summary.csv
```

The default profile matrix must be safe without DuckDB. It should use deterministic synthetic sequences and report at least:

```text
profile_id
profile_mode
sequence_count
sequence_length
n_states
max_duration
n_iter
engine_requested
engine_used
engine_fallback_reason
numba_available
numba_compile_warmed
n_jobs
fit_n_jobs
sequence_chunk_size
fit_parallel_enabled
fit_parallel_fallback
fit_parallel_warning
fit_iteration_count
fit_decode_seconds
fit_update_seconds
fit_total_seconds
snapshot_decode_mode
snapshot_decode_seconds_if_available
total_runtime_seconds
status
```

Optional local DB profile mode may be supported, but it must:

```text
require explicit HSMM_PERF_LOCAL_DB or HSMM_PROFILE_DB
print missing_db as skipped when absent
not fail CI when private DB is absent
not write model rows when profile_only=true
write local/private profile outputs only under ignored locations unless explicitly requested
```

Required profile matrix dimensions:

```text
engine: python, auto
n_iter: 2 or 3 for synthetic CI-safe runs; document 8/10/20 for local mode
max_duration: 20, 40 for CI-safe runs; document 30/40/60 for local mode
fit_n_jobs: 1, auto or bounded auto for CI-safe runs
sequence_chunk_size: 8, 32
```

The report must identify bottleneck class:

```text
fit_decode_dominant
fit_update_dominant
snapshot_decode_dominant
balanced_or_inconclusive
```

Use ratios such as:

```text
fit_decode_share
fit_update_share
snapshot_decode_share
```

## PERF1 requirements: maintenance presets

Create a preset policy config:

```text
configs/hsmm_performance_presets_v1.yaml
```

Minimum presets:

```text
fast_maintenance:
  n_iter: 8-10
  max_duration: 40
  train_frequency: monthly
  snapshot_decode_mode: prefix
  hsmm_engine: auto
  n_jobs: auto
  fit_n_jobs: auto

standard_maintenance:
  n_iter: 20
  max_duration: 60
  train_frequency: monthly
  snapshot_decode_mode: prefix
  hsmm_engine: auto
  n_jobs: auto
  fit_n_jobs: auto

full_research_maintenance:
  n_iter: explicit high value only when requested
  max_duration: 60 or higher only when justified
  train_frequency: explicit maintenance window
  snapshot_decode_mode: prefix
  hsmm_engine: auto_or_numba_required_by_operator
```

Add a small helper if useful:

```text
src/models/hsmm_performance_presets.py
```

It should expose deterministic parsing/validation of preset config and return a config overlay without mutating unrelated settings.

Required validation:

```text
fast_maintenance max_duration <= standard_maintenance max_duration
fast_maintenance n_iter <= standard_maintenance n_iter
all presets use snapshot_decode_mode=prefix unless explicitly documented
all presets preserve HSMM probability semantics
no preset enables approximate/pruned Viterbi
```

Update docs:

```text
docs/runtime/HSMM_PERFORMANCE.md
```

The doc must explain:

```text
when to use fast maintenance
when to use standard maintenance
when to reserve full maintenance
how to read fit_decode_seconds / fit_update_seconds / snapshot_decode_seconds
how to detect numba/joblib fallback
```

## PERF2 requirements: numba and parallel hardening

Harden the current acceleration path without changing model semantics.

Required behavior:

```text
check_hsmm_numba_engine.sh reports requested engine, resolved engine, fallback reason, numba availability, compile warmed.
hsmm_performance_matrix includes engine_used and fallback fields for every row.
If HSMM_ENGINE_REQUIRED=1 and numba is requested but unavailable, the check must fail clearly.
If auto falls back to python, profile status remains pass but report must mark fallback clearly.
Fit parallel fallback must be visible in report fields.
No silent fallback is allowed in summary reports.
```

If needed, update:

```text
scripts/check_hsmm_numba_engine.sh
scripts/hsmm_benchmark_matrix.sh
scripts/hsmm_performance_profile.sh
src/models/hsmm_core.py
src/models/hsmm_model.py
src/models/hsmm_walk_forward.py
```

Keep changes minimal. Do not rewrite the Viterbi algorithm in this package.

## Required CLI

Implement:

```bash
python -m src.evaluation.hsmm_performance_matrix \
  --output reports/hsmm_diagnostics/hsmm_performance_matrix_report.md \
  --summary-json reports/hsmm_diagnostics/hsmm_performance_matrix_report.json \
  --summary-csv reports/hsmm_diagnostics/hsmm_performance_matrix_summary.csv \
  --preset-config configs/hsmm_performance_presets_v1.yaml \
  --mode synthetic \
  --no-db-write
```

Optional local mode:

```bash
HSMM_PERF_LOCAL_DB=data/db/a_share_hmm.duckdb \
python -m src.evaluation.hsmm_performance_matrix \
  --mode local \
  --db "$HSMM_PERF_LOCAL_DB" \
  --profile-only \
  --output reports/hsmm_diagnostics/local/hsmm_performance_matrix_report.md \
  --summary-json reports/hsmm_diagnostics/local/hsmm_performance_matrix_report.json \
  --summary-csv reports/hsmm_diagnostics/local/hsmm_performance_matrix_summary.csv
```

Local output paths under `reports/hsmm_diagnostics/local/` should be gitignored unless a future package explicitly promotes them.

## Gate script

Create:

```text
scripts/hsmm_perf0_1_2_gate.sh
```

It must run:

```bash
python -m compileall -q src tests
pytest -q tests/test_hsmm_performance_matrix.py
bash scripts/check_hsmm_numba_engine.sh
python -m src.evaluation.hsmm_performance_matrix --mode synthetic --no-db-write ...
python -m json.tool reports/hsmm_diagnostics/hsmm_performance_matrix_report.json
python -m json.tool configs/hsmm_performance_presets_v1.yaml
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

Stable marker:

```text
HSMM_PERF0_1_2_GATE=<status> profiles=<n> bottleneck=<class> numba_status=<status> fallback_rows=<n> report=<path> summary_json=<path> no_db_write=yes
```

## Tests

Create:

```text
tests/test_hsmm_performance_matrix.py
```

Minimum synthetic tests:

- Profile matrix returns required columns.
- Synthetic mode does not require DuckDB.
- Missing local DB returns skipped in local mode and does not fail CI.
- Preset config validates fast / standard / full maintenance semantics.
- No preset enables approximate or pruned Viterbi.
- Numba unavailable in auto mode is recorded as fallback, not silent.
- Required numba mode can fail clearly when numba is unavailable.
- Fit parallel fallback fields are present.
- Bottleneck classification is deterministic for synthetic mock timings.
- Reports contain no private local paths.
- No trading/decision output fields are created.

## Acceptance criteria

This package passes if:

- Synthetic profile matrix runs without private DB.
- Profile matrix report, JSON, and CSV are emitted.
- Maintenance preset config exists and validates.
- Numba/joblib fallback state is explicit in reports.
- No silent fallback remains in profile summaries.
- No model semantics, lifecycle meaning, readiness policy, or Stage03V artifacts are changed.
- No production HSMM model rows are written in profile-only/synthetic runs.
- CI and gate pass.

## Return format

```text
index_id: HSMM-PERF0-1-2-v1
branch: hsmm/perf0-1-2-profile-presets-numba-parallel
PR: ...
status: pass / partial / fail

commands run:
- ...

files changed:
- ...

profile matrix mode: synthetic/local/both
synthetic profile count: ...
local profile status: skipped/pass/not_run
preset config path: configs/hsmm_performance_presets_v1.yaml
fast preset: ...
standard preset: ...
full preset: ...
numba check status: pass/fallback/fail
engine fallback rows: ...
fit parallel fallback rows: ...
bottleneck classification: ...
report path: ...
summary json path: ...
summary csv path: ...

model semantics changed: no
approximate/pruned viterbi added: no
production HSMM model rows written: no
persistent DB writes: no
Stage03V artifacts modified: no
holdout consumed: no
trading or decision output: no

remaining risks:
- ...
```
