# Clean Tushare DB Snapshot Rebuild

`Stage04-DATA-WP3B` adds a staged CLI for building a clean Tushare-only DuckDB snapshot in a new database workspace. It creates a target DB, fetches core Tushare market data, writes front-adjusted `stock_ohlcv` with an explicit reference factor policy, rebuilds derived market tables from the target DB, and emits an auditable summary/report.

It does not retrain HMM, HSMM, or Hazard models. It does not consume final holdout artifacts. It does not delete, clear, or overwrite the active DB.

## CLI

Plan only:

```bash
python -m src.data_pipeline.clean_tushare_snapshot \
  --target-db data/db/a_share_hmm_tushare_v1.duckdb \
  --start 20140101 \
  --end today \
  --mode plan-only
```

Build:

```bash
python -m src.data_pipeline.clean_tushare_snapshot \
  --target-db data/db/a_share_hmm_tushare_v1.duckdb \
  --source-db data/db/a_share_hmm.duckdb \
  --start 20140101 \
  --end today \
  --mode build
```

Useful test/smoke limiters:

```bash
python -m src.data_pipeline.clean_tushare_snapshot \
  --target-db data/db/a_share_hmm_tushare_smoke.duckdb \
  --start 20260601 \
  --end 20260609 \
  --max-trade-dates 2 \
  --max-stocks 20 \
  --mode build \
  --summary-json reports/data/clean_tushare_snapshot_smoke.local.json \
  --report reports/data/clean_tushare_snapshot_smoke.local.md
```

`.local` reports and smoke DB files are local runtime artifacts and must not be committed.

## Safety Rules

- `target_db` must be a `.duckdb` file under `data/db`.
- `target_db` must not equal `source_db`.
- `target_db` must not equal the current active DB, except for `validate-only`.
- Existing targets are rejected unless `--allow-existing` is passed and the file is empty or already marked as `clean_tushare_snapshot`.
- `plan-only` and `--dry-run` do not create or write the target DB.
- `--set-active` only runs after successful validation.

## User Asset Copy

The first implementation uses an allowlist copy. It copies only:

- `user_universe`
- `user_universe_items`
- `custom_stock_basket`
- `custom_stock_basket_members`

It does not copy old market data, feature caches, model artifacts, walk-forward cache, QFQ rebuild audits, or old adj-factor snapshots.

## Tushare And QFQ Policy

The stock daily build path fetches full-market data by `trade_date`:

- `trade_cal`
- `stock_basic`
- `daily(trade_date=...)`
- `adj_factor(trade_date=...)`
- `daily_basic(trade_date=...)` when available

It does not loop stock-by-stock for full-market daily data. The clean snapshot uses an explicit per-stock reference factor: the latest valid `adj_factor` at or before the snapshot end date. All `stock_ohlcv` rows are then normalized with that fixed reference factor and written as `tushare_qfq_rebased`.

## Rebuilt Tables

After `stock_ohlcv` is written, the pipeline rebuilds:

- `market_index_ohlcv`
- `market_benchmark_ohlcv`
- `sector_constituents`
- `sector_ohlcv` from target DB local aggregation
- `market_breadth_daily` from target DB `stock_ohlcv`
- `sector_features` from target DB `sector_ohlcv`

## Reports

Default CLI outputs:

- `reports/data/clean_tushare_snapshot_summary.json`
- `reports/data/clean_tushare_snapshot_report.md`

Reports use project-relative display paths, include stage status/rows/duration/failures, and do not include tokens or private absolute paths.

## Model Artifact Status

Clean snapshot DBs do not copy old model artifacts. The summary records:

```text
old_model_artifacts_status = not_copied
reason = clean_tushare_snapshot_rebuild
```

When no model rows exist in the target DB, the status is `no_model_artifacts_in_clean_db`. Retraining and downstream model regeneration are separate explicit steps.
