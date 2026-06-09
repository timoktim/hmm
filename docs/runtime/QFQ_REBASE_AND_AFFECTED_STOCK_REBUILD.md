# Tushare QFQ Rebase and Affected-Stock Rebuild

## Why this exists

`stock_ohlcv` stores Tushare daily bars in a forward-adjusted compatible price basis. Normal daily updates normalize a fetched window with the window's latest `adj_factor`. That is fine for routine append/backfill windows, but it can create a basis break when Tushare later revises historical `adj_factor` values or when a new ex-right/ex-dividend event changes the reference factor outside an older local history window.

The QFQ rebuild flow detects changed `adj_factor` rows, plans only the affected stocks, and rewrites their `stock_ohlcv` rows with an explicit per-stock `reference_factor`.

## Routine Update vs Rebuild

Routine Tushare daily update:

- Fetches all-A daily data by `trade_date`.
- Writes current Tushare QFQ-compatible OHLCV for the requested update window.
- Does not inspect historical `adj_factor` snapshots for older factor revisions.

Affected-stock rebuild:

- Fetches `adj_factor` by `trade_date` for a small detection window.
- Compares it with `tushare_adj_factor_snapshot`.
- Rebuilds only affected `stock_code` windows.
- Uses `adjusted_price = raw_price * adj_factor / reference_factor`.
- Recomputes dependent local aggregates for the affected window.

## Trigger Scenarios

- Tushare `adj_factor` history is revised for one or more stocks.
- A new ex-right or ex-dividend event requires a unified forward-adjustment basis.
- An operator explicitly runs a forced affected-stock rebuild.

## Tables Updated

- `tushare_adj_factor_snapshot`: latest confirmed factor snapshot used for future change detection.
- `qfq_rebuild_runs`: one row per non-dry-run rebuild or no-op baseline run.
- `qfq_rebuild_affected_stocks`: affected stocks and planned rebuild windows.
- `stock_ohlcv`: affected stock rows only, written by upsert.
- `sector_ohlcv`: local sector aggregates containing affected stocks.
- `market_breadth_daily`: `full_market` breadth for the affected date window.
- `custom_basket_ohlcv`: custom baskets containing affected stocks.
- `sector_features`: all-market sector feature cache rows for affected sectors and dates.

Custom universe feature scopes, model run outputs, and walk-forward caches are not silently rewritten. Recompute those explicitly if a downstream analysis depends on the repaired date range.

## What It Does Not Do

- It does not retrain HMM, HSMM, or Hazard models.
- It does not consume final holdout data.
- It does not generate trading signals.
- It does not call AKShare, THS, or EastMoney fallback paths.
- It does not perform an all-market all-history rebuild unless explicitly forced.

## Commands

Detect only:

```bash
python -m src.data_pipeline.qfq_rebuild --start 20260601 --end 20260609 --mode detect-only --summary-json reports/data/qfq_rebuild_summary.json --report reports/data/qfq_rebuild_report.md
```

Dry-run a detect-and-rebuild plan:

```bash
python -m src.data_pipeline.qfq_rebuild --start 20260601 --end 20260609 --mode detect-and-rebuild --dry-run --summary-json reports/data/qfq_rebuild_summary.json --report reports/data/qfq_rebuild_report.md
```

Run the affected-stock rebuild:

```bash
python -m src.data_pipeline.qfq_rebuild --start 20260601 --end 20260609 --mode detect-and-rebuild --summary-json reports/data/qfq_rebuild_summary.json --report reports/data/qfq_rebuild_report.md
```

Forced rebuild is intentionally explicit:

```bash
python -m src.data_pipeline.qfq_rebuild --start 20260601 --end 20260609 --mode rebuild-only --force --max-stocks 20 --dry-run
```

## Token Safety

Live Tushare calls read the token from `ASHARE_HMM_TUSHARE_TOKEN` through the existing runtime settings. The rebuild command prints only status, affected stock count, rebuilt stock count, row count, and validation state. Reports and summaries must not include token values, local private paths, or local worktree paths.

Unit tests use fake clients and synthetic data. CI must not require network access or a real Tushare token.
