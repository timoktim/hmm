# Backtest Performance

`BACKTEST-PERF-WP1` separates walk-forward HMM state preparation from
state-neutral rank/simulation loops used by signal validation.

## Reuse Boundary

State-affecting parameters still require a distinct state context:

- `n_states`
- `train_window_days`
- `retrain_frequency`
- `rebalance_days`
- `start_date`
- `end_date`
- `universe_id`
- `include_custom_baskets`
- `feature_version`

State-neutral loops reuse the same prepared state frame:

- `threshold`
- `top_n`
- `transaction_cost`

`run_sector_rotation_backtest(...)` remains the compatibility entry point. New
callers that need to sweep state-neutral parameters can prepare a
`SectorRotationBacktestContext` once and call
`run_sector_rotation_backtest_from_context(...)` repeatedly.

## Parallel Loops

`evaluate_selection_grid`, `evaluate_cost_sensitivity`, and
`evaluate_random_baseline` use joblib with process-first, thread-fallback, and
serial fallback behavior. Set `BACKTEST_PERF_N_JOBS` to control worker count;
`auto` uses the available CPU count capped by task count.

The random baseline preserves the legacy RNG stream by generating each trial's
events in trial-index order before parallel portfolio simulation. This keeps
random-baseline output identical while making backend completion order
irrelevant.

## Speed Gate

Run:

```bash
bash scripts/backtest_speedup_gate.sh
```

The gate uses `data/db/a_share_hmm_tushare_v7.duckdb` by default and leaves the
start date unset so the backtest context follows the local data's first
available trade date. Override with `BACKTEST_SPEEDUP_DB`,
`BACKTEST_SPEEDUP_START_DATE`, `BACKTEST_SPEEDUP_END_DATE`, and
`BACKTEST_PERF_N_JOBS`.

Required pass fields:

```text
BACKTEST_SPEEDUP_GATE_STATUS=pass
states_computed_count=1
parallel_enabled=yes
equivalence_atol=1e-09
results_identical=yes
```
