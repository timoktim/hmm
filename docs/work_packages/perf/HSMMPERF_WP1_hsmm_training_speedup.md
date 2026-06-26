# HSMMPERF_WP1_hsmm_training_speedup

Stage: Perf / HSMM training throughput

Work package: HSMM-PERF-WP1

Index id: HSMM-PERF-WP1-v1

Suggested branch: `perf/hsmm-wp1-training-speedup`

Codex instruction: `docs/codex_instructions/perf/CODEX_HSMMPERF_WP1_hsmm_training_speedup.md`

Date: 2026-06-12

## Background

HSMM walk-forward training currently takes hours. Audit (2026-06-12) found the
cause is not algorithmic but configuration:

- `numba` is not installed and is not in `requirements.txt`. The numba Viterbi
  kernel, its diagnostics, the `check_hsmm_numba_engine.sh` script, and the
  benchmark harness already exist in the repo but are never exercised in normal
  runs.
- `hsmm_engine` defaults to `"auto"`, and `auto` silently falls back to the
  pure-Python kernel when numba cannot be imported (`hsmm_core.resolve_hsmm_engine`).
  There is no warning, so every run has been executing the O(T·N²·D) dynamic
  program in the Python interpreter.
- `n_jobs` / `fit_n_jobs` default to 1, so checkpoint-fit and snapshot-decode
  are single-core even though sectors/sequences are independent.
- `_emission_logprob` (`hsmm_model.py`) loops over states in Python instead of
  vectorizing.

The numba kernel and the Python kernel compute the same dynamic program, and
joblib parallelism only distributes independent sequences. Therefore the
speed-ups in this package are **pure acceleration with no change to model
output**. Target: full walk-forward training in under 10 minutes on the local
V7 database, with bit-for-bit (within floating tolerance) identical results
versus the current Python engine.

## Objective

Make the numba engine and parallelism the effective default for HSMM training,
vectorize the emission kernel, and prove via a benchmark gate that training
runs under 10 minutes **and** produces output equivalent to the Python
reference engine.

This package must NOT change any model semantics: no change to `n_states`,
`max_duration`, `n_iter`, `train_window_days`, `train_frequency`, convergence
tolerance, random seeding, initialization, or feature definitions. Anything
that would alter trained parameters or decoded paths is out of scope and
deferred to HSMM-PERF-WP2.

## Stage boundary

Allowed:

- Add `numba` to dependencies as an optional/perf extra and ensure the runtime
  resolves it.
- Change default engine resolution so a normal run uses numba when available
  and emits a visible warning (not silent) when it falls back.
- Turn on sensible parallel defaults for fit and snapshot decode, or document
  the recommended invocation; either way the benchmark must demonstrate the
  result.
- Vectorize `_emission_logprob` over states.
- Add an output-equivalence test and a benchmark timing gate.

Forbidden:

- Any change to `n_states`, `max_duration`, `n_iter`, `train_window_days`,
  `train_frequency`, `tol`, initialization (KMeans/quantile), random seeds, or
  feature construction.
- Any change to the numba kernel's or Python kernel's numerical formulas.
- Retraining/altering committed Stage03V or Stage03R model artifacts.
- Consuming prospective holdout data.
- Any UI, decision, trading, or sizing output.

## Required changes

### P1. numba as a resolvable dependency

- Add `numba` to `requirements.txt` (or a documented `requirements-perf.txt` /
  optional extra), version-pinned compatibly with the pinned `numpy`.
- Decide and document the policy: numba is required for the fast path but the
  Python kernel remains the correctness reference. CI may stay numba-free
  (fallback path), but a training/benchmark run must use numba.

### P2. Visible fallback, not silent

- When `hsmm_engine="auto"` falls back to Python because numba is unavailable,
  emit a clear warning via the existing logger (the diagnostic struct already
  carries `fallback_reason`). A silent multi-hour Python run must not be
  possible without an explicit log line stating the fast path was unavailable.
- Do not change the contract that `engine="numba"` raises when unavailable and
  `engine="python"` always uses the reference kernel.

### P3. Parallel defaults that the benchmark actually exercises

- Provide a recommended training invocation (config defaults and/or the
  benchmark/profile scripts) where `fit_n_jobs` and decode `n_jobs` resolve
  above 1 on a multi-core machine, with a chunk size that yields more than one
  chunk for a typical sector count.
- Preserve the existing serial fallback and its diagnostic flags.

### P4. Vectorize emission log-probability

- Replace the per-state Python loop in `_emission_logprob` with a vectorized
  diagonal-Gaussian computation over all states at once. Result must match the
  loop version within floating tolerance (covered by P5 equivalence test).

## Required tests and gates

### T1. Engine output equivalence (correctness guard, the critical test)

A deterministic test that runs the SAME synthetic training input through the
Python engine and the numba engine (and the vectorized vs loop emission) and
asserts:

- decoded Viterbi paths are identical;
- fitted `means_`, `vars_`, transition matrix, duration PMF, start probs match
  within tight floating tolerance (e.g. `atol=1e-8`);
- final score matches within tolerance.

This test is the contract that "pure acceleration" is true. It must be
CI-safe (skips numba assertions cleanly when numba is absent, but the
numba-present path is exercised in the benchmark run).

### T2. Emission vectorization unit test

Synthetic `x`, known means/vars: vectorized `_emission_logprob` equals the
former per-state loop within `atol=1e-10`.

### T3. Benchmark timing gate

A script (extend `scripts/hsmm_benchmark_matrix.sh` / `hsmm_performance_profile.sh`
or add `scripts/hsmm_training_speedup_gate.sh`) that, on the local V7 DB with
numba + parallel enabled and the UNCHANGED default model config
(`n_states=4`, `max_duration=60`, `n_iter=20`, `train_window_days=504`,
`train_frequency=monthly`), runs a representative walk-forward training and
asserts wall-clock under 10 minutes. It must record:

```text
HSMM_SPEEDUP_GATE_STATUS=pass|fail
engine_used=numba|python
resolved_engine_is_numba=yes|no
fit_parallel_enabled=yes|no
walltime_seconds=<n>
target_seconds=600
config_unchanged=yes
```

If `resolved_engine_is_numba=no`, the gate fails (this prevents the silent
Python regression from ever recurring). The gate documents the machine
(core count) it was measured on.

## Deliverables

```text
requirements.txt (or requirements-perf.txt) with numba
src/models/hsmm_core.py            (visible fallback warning)
src/models/hsmm_model.py           (vectorized emission; parallel-friendly defaults if applicable)
src/models/hsmm_walk_forward.py    (recommended parallel defaults / invocation)
scripts/hsmm_training_speedup_gate.sh
tests/test_hsmm_engine_equivalence.py
tests/test_hsmm_emission_vectorization.py
docs/runtime/HSMM_PERFORMANCE.md   (updated: numba required for fast path, gate usage, measured numbers)
docs/work_packages/perf/HSMMPERF_WP1_hsmm_training_speedup.md
```

## Acceptance

- [ ] numba is a resolvable dependency and a training run resolves
      `engine_used=numba`.
- [ ] `auto` fallback to Python emits a visible warning; silent fallback is
      impossible.
- [ ] Emission vectorized; T2 passes.
- [ ] T1 engine-equivalence test passes: numba vs python produce identical
      paths and parameters within tolerance. **This is the gate that proves no
      model output changed.**
- [ ] T3 benchmark gate reports walltime < 600s on the local V7 DB with the
      unchanged default config, and `resolved_engine_is_numba=yes`.
- [ ] No change to any model hyperparameter, initialization, seed, or feature.
- [ ] No Stage03V/Stage03R artifact regenerated; no holdout consumed.
- [ ] Full not-slow suite result reported.

## Return contract

Report PR link, commands run, the benchmark gate output block (engine_used,
walltime_seconds, resolved_engine_is_numba, core count), T1/T2 results, and
explicit yes/no flags:

```text
numba resolved as engine in training run
auto fallback now emits visible warning
emission vectorized
model hyperparameters or seeds changed   (must be: no)
engine equivalence test passes
walltime under 10 minutes
holdout consumed                          (must be: no)
```

## Out of scope (deferred to HSMM-PERF-WP2)

Anything that changes model output for additional speed:
`max_duration` reduction, `n_iter` reduction / dynamic early stopping,
warm-start across checkpoints, unified scaler across checkpoints. These each
constitute a new model configuration and require re-validation of dependent
evidence; they must not be bundled into the pure-acceleration package.
