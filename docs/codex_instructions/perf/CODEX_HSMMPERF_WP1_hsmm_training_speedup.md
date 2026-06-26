# CODEX_HSMMPERF_WP1_hsmm_training_speedup

Repository: timoktim/hmm

Index id: HSMM-PERF-WP1-v1

Work package: `docs/work_packages/perf/HSMMPERF_WP1_hsmm_training_speedup.md`

Suggested branch: `perf/hsmm-wp1-training-speedup`

## Instruction

Start from updated `main`. Read the work package in full. Execute only
`HSMM-PERF-WP1-v1`.

The goal is to make HSMM walk-forward training run in under 10 minutes by
enabling the EXISTING numba kernel and parallelism, and by vectorizing the
emission kernel — WITHOUT changing any model output. The root cause is that
`numba` is not installed / not in `requirements.txt`, so `hsmm_engine="auto"`
silently falls back to the pure-Python O(T·N²·D) dynamic program, single-core.

This is a pure-acceleration package. You must NOT change `n_states`,
`max_duration`, `n_iter`, `train_window_days`, `train_frequency`, convergence
tolerance, initialization (KMeans/quantile), random seeds, or feature
construction. Anything that alters trained parameters or decoded paths is out
of scope (deferred to HSMM-PERF-WP2). Do not regenerate Stage03V/Stage03R
artifacts, do not consume prospective holdout, do not create UI/decision/
trading output.

## Required work

1. Add `numba` as a resolvable dependency (in `requirements.txt` or a
   documented `requirements-perf.txt` / optional extra), version-compatible
   with the pinned numpy. Document that numba is required for the fast path
   while the Python kernel stays the correctness reference and CI may remain
   numba-free via the fallback path.
2. Make the `auto`-mode fallback to Python emit a VISIBLE logger warning
   carrying `fallback_reason`. Silent multi-hour Python fallback must be
   impossible. Keep `engine="numba"` raising when unavailable and
   `engine="python"` always using the reference kernel.
3. Provide a recommended training invocation / config defaults where
   `fit_n_jobs` and decode `n_jobs` resolve above 1 on a multi-core machine
   with a chunk size that produces more than one chunk for a typical sector
   count. Preserve the serial fallback and its diagnostic flags.
4. Vectorize `_emission_logprob` in `src/models/hsmm_model.py` over states
   (diagonal Gaussian), matching the former per-state loop within tolerance.

## Required tests and gate

- `tests/test_hsmm_engine_equivalence.py`: same synthetic training input
  through python vs numba engines → identical Viterbi paths and fitted
  parameters (`means_`, `vars_`, transition, duration PMF, start) within
  `atol=1e-8`, final score within tolerance. CI-safe when numba absent, but
  the numba path is exercised in the benchmark run. THIS IS THE PROOF THAT NO
  MODEL OUTPUT CHANGED.
- `tests/test_hsmm_emission_vectorization.py`: vectorized vs loop emission
  within `atol=1e-10`.
- `scripts/hsmm_training_speedup_gate.sh`: on the local V7 DB with numba +
  parallel and the UNCHANGED default config (n_states=4, max_duration=60,
  n_iter=20, train_window_days=504, monthly), run representative walk-forward
  training and assert walltime < 600s. Emit machine-readable lines including
  `engine_used`, `resolved_engine_is_numba`, `fit_parallel_enabled`,
  `walltime_seconds`, `target_seconds=600`, `config_unchanged=yes`,
  `HSMM_SPEEDUP_GATE_STATUS`. Fail the gate if `resolved_engine_is_numba=no`.

## Required commands

```bash
python -m pip install numba          # fast path dependency
python -m compileall -q src tests
bash scripts/check_hsmm_numba_engine.sh          # expect engine_used=numba
HSMM_ENGINE_REQUIRED=1 bash scripts/check_hsmm_numba_engine.sh
pytest -q tests/test_hsmm_engine_equivalence.py tests/test_hsmm_emission_vectorization.py
bash scripts/hsmm_training_speedup_gate.sh       # expect HSMM_SPEEDUP_GATE_STATUS=pass, walltime<600
pytest -q -m "not slow"
```

Document the measured walltime and the machine core count in the PR body.

## Return format

Use the return contract in the work package. Include the PR link, commands
run, the benchmark gate output block, T1/T2 results, and explicit yes/no flags:

```text
numba resolved as engine in training run
auto fallback now emits visible warning
emission vectorized
model hyperparameters or seeds changed   (must be: no)
engine equivalence test passes
walltime under 10 minutes
holdout consumed                          (must be: no)
```
