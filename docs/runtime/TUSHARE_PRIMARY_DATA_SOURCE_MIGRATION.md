# Tushare Primary Daily Data Source Migration

## Scope

This migration makes Tushare the default confirmed daily market data source for the data center and all-A daily update pipeline. It does not retrain models, change HMM/HSMM/Hazard semantics, consume final holdout artifacts, or change downstream feature contracts.

## Audit Summary

- `src/config.py`: default source changed from `akshare` to `tushare`; Tushare token/rate/qfq settings added.
- `src/data_sources/factory.py`: default `create_data_client()` now returns `TushareClient`; `akshare` is only an explicit legacy source.
- `src/data_pipeline/market_updater.py`: all-A Tushare path updates by `trade_date` batches and no longer calls `stock_hist()` per stock.
- `src/data_sources/mootdx_client.py`: mootdx remains an explicit stock/index provisional source; default AKShare fallback is disabled and board fallback is unsupported.
- `src/ui/data_center_page.py`: data center task labels and controls now describe Tushare stock pool, trade-date bulk daily updates, index updates, market breadth, and industry local aggregation.
- `requirements.txt` and `src/utils/dependency_guard.py`: Tushare is core; AKShare is not a core dependency.

## Source Roles

- Primary confirmed daily data: `tushare_qfq`.
- Industry constituents: Tushare SW classification/member interfaces where available.
- Industry OHLCV: local aggregation from Tushare-confirmed constituent stock OHLCV, recorded as `tushare_local_aggregate`.
- Concept boards: unsupported by default in the Tushare 2000-point primary chain; legacy data may remain in DuckDB but is not refreshed silently.
- AKShare/THS/EastMoney: legacy compatibility only; not used by default factory or default UI update tasks.
- mootdx/TDX: optional explicit stock/index provisional source; no default AKShare fallback.

## Tushare 2000-Point Boundary

The default configuration assumes 200 requests per minute and leaves safety margin via `ASHARE_HMM_TUSHARE_REQUEST_MIN_INTERVAL_SECONDS=0.31` plus jitter. Minute, realtime, news/sentiment, and separately permissioned specialty APIs are not default dependencies.

## Token Handling

The token is read only from `ASHARE_HMM_TUSHARE_TOKEN`, and only when a live Tushare request is made. Code, tests, docs, logs, errors, and PR text must not contain a real token.

## OHLCV Contract

`stock_ohlcv` keeps the existing前复权-compatible feature contract. Tushare `daily` rows are merged with `adj_factor`; prices are adjusted within the fetched window before upsert and recorded with audit columns including `source`, `fetched_at`, `source_priority`, `is_provisional`, and `validation_status`.
