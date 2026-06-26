# BACKTESTPERF_WP1_backtest_speedup

Stage: Perf / Backtest and signal-validation throughput

Work package: BACKTEST-PERF-WP1

Index id: BACKTEST-PERF-WP1-v1

Suggested branch: `perf/backtest-wp1-speedup`

Codex instruction: `docs/codex_instructions/perf/CODEX_BACKTESTPERF_WP1_backtest_speedup.md`

Date: 2026-06-26

## Background

`run_signal_validation` is slow (tens of minutes) because it multiplies a
single backtest by roughly 28x:

- `evaluate_cost_sensitivity` loops 5 transaction costs, each calling
  `run_sector_rotation_backtest(walk_forward=True, ...)`.
- `evaluate_selection_grid` loops `threshold_grid` (5) x `top_n_grid` (4) = 20
  combinations, each calling `run_sector_rotation_backtest(walk_forward=True, ...)`.
- `evaluate_random_baseline` runs ~200 random portfolio simulations.

Audit (2026-06-26) established the key fact: in BOTH grids the parameters that
affect HMM states are held fixed at the config value
(`n_states`, `train_window_days`, `retrain_frequency`, `rebalance_days`). Only
parameters that affect ranking and portfolio simulation vary
(`threshold`, `top_n`, `transaction_cost`). Therefore every grid call recomputes
the SAME HMM walk-forward state path — 24 redundant retrains (or, when the
walk-forward cache hits, 24 redundant feature rebuilds + I/O + state reads).

This package removes that redundancy with no change to any backtest number.
Speed-ups must come only from eliminating duplicated computation and from
parallelism — NOT from reducing statistical work.

## Hard prohibition (non-negotiable)

This package MUST NOT change any backtest output value and MUST NOT weaken any
statistical mechanism. Specifically forbidden:

- reducing `random_trials` (200), `bootstrap_rounds` (1000), or any grid size;
- reducing HMM `n_iter` or changing convergence tolerance;
- changing seeds, initialization, feature definitions, ranking logic, cost
  model, or portfolio simulation math;
- changing which dates, sectors, or universe are evaluated.

Any of these would alter results and is out of scope. The acceptance gate is
bit-for-bit (within floating tolerance) identical outputs versus current main.

## Objective

1. Compute the HMM walk-forward state path ONCE per state-affecting parameter
   set, then run the threshold/top_n/cost grids by re-ranking and re-simulating
   on the cached states only.
2. Parallelize the independent grid / cost / random-baseline iterations.
3. Prove via an equivalence gate that optimized outputs match current main
   exactly (within floating tolerance).

## The correctness boundary (the critical design constraint)

State-reuse is valid ONLY across parameters that do not change the HMM states.

```text
STATE-AFFECTING (must force a fresh walk-forward state computation):
  n_states, train_window_days, retrain_frequency, rebalance_days,
  start_date, end_date, universe_id, include_custom_baskets, execution_price-if-it-feeds-states

STATE-NEUTRAL (safe to vary while reusing the same cached states):
  threshold, top_n, transaction_cost
```

Implementation rule: structure the work as an OUTER layer keyed by the
state-affecting tuple (compute states once per distinct tuple) and an INNER
layer over state-neutral params (rank + simulate on the reused states). Add an
explicit guard/assertion: if a grid is ever extended to vary a state-affecting
parameter in the inner layer, the code must recompute states, never silently
reuse. A wrong reuse here produces SILENTLY INCORRECT backtest numbers, which
is worse than being slow — treat this guard as the heart of the package.

If you are uncertain whether a parameter affects states (e.g. `rebalance_days`,
`execution_price`), classify it as state-affecting (outer layer). Correctness
first.

## Required changes

### B1. Separate state computation from rank/simulate

- Provide a path that computes the walk-forward state frame once (reusing the
  existing `walk_forward_state_cache` / lineage hash mechanism), and a
  rank+simulate step that takes a precomputed state frame plus
  (threshold, top_n, transaction_cost) and returns the same comparison/curve
  outputs `run_sector_rotation_backtest` produces today.
- Refactor `evaluate_selection_grid` and `evaluate_cost_sensitivity` to compute
  states once and loop the state-neutral params on the reused states.
- Do not change the public outputs of these functions (same columns, same
  values).

### B2. Parallelize independent iterations

- Parallelize the inner state-neutral grid, the cost loop, and the random
  baseline with joblib, following the same process-then-thread fallback pattern
  used in HSMM-PERF-WP1 (`prefer="processes"`, fall back to threads on failure,
  record the fallback). Preserve a serial fallback and deterministic ordering
  of results.
- Ensure DuckDB access is safe under parallelism (separate connections or
  read-only snapshots); if safe parallel DB access is not achievable, parallelize
  only the pure-Python rank/simulate stage on in-memory state frames and keep DB
  reads serial.

### B3. Avoid redundant feature rebuild / I/O per grid call

- The state frame and the per-sector feature frame should be built once for a
  given state-affecting tuple, not rebuilt inside every inner-loop iteration.

## Required tests and gates

### T1. End-to-end equivalence gate (the contract that proves results are unchanged)

A deterministic test (synthetic or small fixed local fixture) that runs the
FULL `run_signal_validation` (or the two grid functions plus random baseline)
both ways — current main path vs optimized path — and asserts every output
table matches within floating tolerance:

- `evaluate_selection_grid` output: all 20 rows, all metric columns
  (`annual_return_net`, `max_drawdown_net`, `sharpe_net`, `calmar_net`,
  `turnover`, excess metrics) equal within `atol=1e-9`;
- `evaluate_cost_sensitivity` output: all cost rows equal within `atol=1e-9`;
- random-baseline distribution: identical given the same seed (this guards that
  parallelism did not change RNG streams — seed each trial deterministically by
  index so order/backend cannot change results).

This test is the heart of acceptance. Without it the refactor cannot be merged.

### T2. State-reuse guard test

A test asserting that varying a state-neutral param reuses the same state frame
(e.g. state computation invoked once for the whole inner grid) AND that varying
a state-affecting param triggers recomputation. This locks the correctness
boundary against future regressions.

### T3. Speed gate

A script (`scripts/backtest_speedup_gate.sh`) that runs the full signal
validation on the local DB before/after (or just after, comparing to a recorded
baseline) and reports:

```text
BACKTEST_SPEEDUP_GATE_STATUS=pass|fail
states_computed_count=<n>        # must equal the number of distinct state-affecting tuples, not 25
parallel_enabled=yes|no
walltime_seconds=<n>
equivalence_atol=1e-9
results_identical=yes|no
```

`results_identical=no` fails the gate unconditionally.

## Deliverables

```text
src/backtest/sector_rotation.py        (state/rank-simulate separation)
src/evaluation/signal_validation.py    (compute-once grids + parallel + guard)
scripts/backtest_speedup_gate.sh
tests/test_backtest_equivalence.py
tests/test_backtest_state_reuse_guard.py
docs/runtime/ (a short perf note, or extend an existing one)
docs/work_packages/perf/BACKTESTPERF_WP1_backtest_speedup.md
```

## Acceptance

- [x] States computed once per distinct state-affecting tuple; grid/cost inner
      loops reuse them.
- [x] Grid, cost, and random-baseline iterations parallelized with serial
      fallback and deterministic trial-indexed random-baseline events.
- [x] T1 equivalence gate passes: all signal-validation outputs identical to
      current main within `atol=1e-9`. **This is the proof results did not change.**
- [x] T2 state-reuse guard passes.
- [x] No reduction of `random_trials`, `bootstrap_rounds`, grid sizes, `n_iter`,
      or any statistical mechanism.
- [x] No change to seeds, features, ranking, cost model, or simulation math.
- [x] Speed gate reports the realistic speed-up and `results_identical=yes`.
- [x] Full not-slow suite result reported.

## Execution note 2026-06-26

- Targeted tests: `6 passed`.
- Default local V7 speed gate: `BACKTEST_SPEEDUP_GATE_STATUS=pass`,
  `states_computed_count=1`, `parallel_enabled=yes`,
  `results_identical=yes`, `walltime_improvement_factor=1.690`.
- Random baseline preserves the legacy seed/RNG stream by materializing
  trial-indexed events before parallel simulation.
- Full `pytest -q -m "not slow"` result: `929 passed, 4 failed, 3 deselected`.
  The failures were pre-existing/out of scope for this package:
  `.venv/bin/python` missing numpy in `scripts/stage03r_final_holdout_artifact.sh`,
  and UI text-policy findings for `src/ui/help_texts.py`.

## Return contract

Report PR link, commands run, the speed-gate output block (walltime,
states_computed_count, results_identical), T1/T2 results, and explicit yes/no
flags:

```text
states computed once and reused across state-neutral grid
grid/cost/random-baseline parallelized
random_trials / bootstrap_rounds / grid sizes reduced   (must be: no)
any backtest output value changed                        (must be: no)
equivalence gate passes at atol 1e-9
walltime improvement (report factor)
```

## Out of scope (do not do here)

Anything that changes backtest numbers for speed: reducing random/bootstrap
counts, shrinking grids, lowering `n_iter`, approximating the simulation. These
remove the project's anti-self-deception statistical machinery and are not an
acceptable way to go faster.
