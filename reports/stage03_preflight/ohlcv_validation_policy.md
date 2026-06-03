# OHLCV Ingestion Validation Policy

WP: STAGE03PF-WP0A
Status: implemented

## Scope

This policy hardens OHLCV validation before repository ingestion paths write rows into durable tables. It does not fetch external data, train models, modify HMM/HSMM training behavior, or commit DuckDB/WAL artifacts.

## Covered Ingestion Paths

- `sector_ohlcv`: board history is validated before upsert.
- `stock_ohlcv`: stock history is validated before upsert.
- `market_benchmark_ohlcv`: benchmark history is validated before upsert; `benchmark_id` is filled before validation when needed.
- `custom_basket_ohlcv`: source stock rows and generated basket rows are validated with a reduced schema.

## Hard Fail Checks

- Required columns are present.
- DataFrame is not empty.
- `trade_date` is non-null and parseable.
- `entity_key + trade_date` is unique when `entity_key` is supplied; otherwise `trade_date` is unique.
- Present OHLC numeric columns are numeric, finite, and positive.
- `high >= low`, `high >= open`, `high >= close`, `low <= open`, and `low <= close` when those columns exist.
- `volume >= 0` and `amount >= 0` when those columns exist.

Hard validation failures raise `ValueError` before storage upsert, and updater summaries record the entity and reason.

## Warning Checks

- Large `close.pct_change().abs()` gaps are warnings by default.
- Large `open / previous close` gaps are warnings by default.
- `strict=True` upgrades warnings to `ValueError`.

Large gaps are not rejected by default because legitimate market discontinuities can occur.

## Reduced Custom Basket Schema

Custom baskets may only provide `trade_date`, `close`, `daily_ret`, `volume`, and `amount`. They are therefore validated with a reduced required column set that still enforces date uniqueness, finite/positive close, and non-negative optional volume/amount.
