# Stage04-WP1 Structural Break Diagnostic

Stage04-WP1 is a read-only, offline diagnostic package for low-cost structural break warnings. It reads existing local DuckDB tables and writes public-safe reports under `reports/stage04`.

This package does not fetch external data, retrain HMM/HSMM models, alter hazard models, consume final holdout data, create a decision engine, or change DuckDB schema.

## Inputs

The detector uses available local tables when present:

- `market_index_ohlcv`
- `market_breadth_daily`
- `sector_features`
- `walk_forward_state_cache`

Missing or sparse inputs degrade the affected component to `unavailable`, `data_limited`, or `insufficient_history`. The report does not invent replacement scores.

## Causality

Rolling baselines are causal. For trade date `T`, rolling mean and standard deviation use observations strictly before `T`. The current row and future rows are excluded from baseline estimation.

The default baseline is:

- `rolling_window=60`
- `min_periods=20`

The HMM confidence component excludes rows where `max_observation_date_used > trade_date`.

## Components

- Market volatility: selected from `000300`, then `000001`, then the most populated index.
- Breadth stress: selected from `full_market`, then `local_sample`.
- Sector dispersion: cross-sectional dispersion from `sector_features`.
- HMM confidence: aggregate confidence and entropy from walk-forward state cache.

The aggregate warning levels are:

- `normal`
- `watch`
- `elevated`
- `high`
- `insufficient_data`

These are structural break diagnostics only, not trading outputs.

## Run

```bash
python -m src.evaluation.stage04_break_detector \
  --db data/db/a_share_hmm.duckdb \
  --output reports/stage04/stage04_wp1_break_detector_report.md \
  --summary-json reports/stage04/stage04_wp1_break_detector_report.json \
  --sample-csv reports/stage04/stage04_wp1_break_detector_sample.csv \
  --no-fetch
```

Or use:

```bash
bash scripts/stage04_break_detector.sh
```

If `data/db/a_share_hmm.duckdb` is absent, the script writes to a temporary directory so committed public reports are not overwritten.
