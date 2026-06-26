# CODEX_BACKTESTPERF_WP1_backtest_speedup

Repository: timoktim/hmm

Index id: BACKTEST-PERF-WP1-v1

Work package: `docs/work_packages/perf/BACKTESTPERF_WP1_backtest_speedup.md`

Suggested branch: `perf/backtest-wp1-speedup`

## Instruction

Start from updated `main`. Read the work package in full. Execute only
`BACKTEST-PERF-WP1-v1`.

The goal is to make `run_signal_validation` much faster by eliminating
redundant HMM walk-forward recomputation and by parallelizing independent
iterations — WITHOUT changing any backtest output value and WITHOUT weakening
any statistical mechanism.

Root cause: `evaluate_cost_sensitivity` (5 costs) and `evaluate_selection_grid`
(threshold x top_n = 20) each call `run_sector_rotation_backtest(walk_forward=True)`
while the HMM-state-affecting parameters (`n_states`, `train_window_days`,
`retrain_frequency`, `rebalance_days`) are fixed. So the SAME state path is
recomputed ~24 times. Compute it once; loop the state-neutral params
(`threshold`, `top_n`, `transaction_cost`) on the reused states.

## Absolute prohibitions

Do NOT reduce `random_trials` (200), `bootstrap_rounds` (1000), any grid size,
HMM `n_iter`, or convergence tolerance. Do NOT change seeds, initialization,
features, ranking logic, cost model, portfolio simulation math, or the set of
dates/sectors/universe evaluated. Speed must come only from removing duplicate
computation and from parallelism. If a change would alter any output number, it
is out of scope.

## The correctness boundary (most important part)

State-reuse is valid ONLY across state-neutral params (threshold, top_n,
transaction_cost). State-affecting params (n_states, train_window_days,
retrain_frequency, rebalance_days, start/end, universe_id,
include_custom_baskets) must force fresh state computation. Structure as an
OUTER layer keyed by the state-affecting tuple and an INNER layer over
state-neutral params. Add an explicit guard so that if a grid ever varies a
state-affecting parameter in the inner layer, states are recomputed, never
silently reused — a wrong reuse produces silently incorrect numbers. If unsure
whether a param affects states, treat it as state-affecting.

## Required work

1. Separate "compute walk-forward state frame once" from "rank + simulate given
   a state frame and (threshold, top_n, transaction_cost)". Reuse the existing
   walk_forward_state_cache / lineage mechanism. Refactor
   `evaluate_selection_grid` and `evaluate_cost_sensitivity` to compute states
   once and loop state-neutral params on reused states. Keep identical output
   columns and values.
2. Parallelize the inner grid, the cost loop, and the random baseline with
   joblib (process-then-thread fallback as in HSMM-PERF-WP1), with a serial
   fallback and deterministic ordering. Seed each random-baseline trial by its
   index so parallelism/backend cannot change the RNG result.
3. Build the per-tuple state frame and feature frame once, not per inner
   iteration. Ensure DuckDB access is parallel-safe; if not, parallelize only
   the pure in-memory rank/simulate stage and keep DB reads serial.

## Required tests and gate

- `tests/test_backtest_equivalence.py`: run the full validation (or both grids
  + random baseline) the current way vs the optimized way on a fixed
  synthetic/small fixture; assert every output table (selection grid rows, cost
  rows, random-baseline distribution) matches within `atol=1e-9` given the same
  seed. THIS PROVES NO RESULT CHANGED.
- `tests/test_backtest_state_reuse_guard.py`: varying a state-neutral param
  reuses one state computation; varying a state-affecting param recomputes.
- `scripts/backtest_speedup_gate.sh`: run on the local DB, emit
  `BACKTEST_SPEEDUP_GATE_STATUS`, `states_computed_count` (must equal number of
  distinct state-affecting tuples, not 25), `parallel_enabled`,
  `walltime_seconds`, `results_identical`. Fail if `results_identical=no`.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_backtest_equivalence.py tests/test_backtest_state_reuse_guard.py
bash scripts/backtest_speedup_gate.sh
pytest -q -m "not slow"
```

Document the measured walltime improvement and core count in the PR body.

## Return format

Use the return contract in the work package. Include the PR link, commands run,
the speed-gate output block, T1/T2 results, and explicit yes/no flags:

```text
states computed once and reused across state-neutral grid
grid/cost/random-baseline parallelized
random_trials / bootstrap_rounds / grid sizes reduced   (must be: no)
any backtest output value changed                        (must be: no)
equivalence gate passes at atol 1e-9
walltime improvement (report factor)
```
