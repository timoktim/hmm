# TDX Data Source Pool

## Purpose

The default market data source remains AKShare. The primary market OHLCV path can opt in to `mootdx` over multiple TDX servers while keeping AKShare as a fallback for board metadata, board constituents, and failed TDX OHLCV recovery.

This improves throughput by spreading requests across TDX server nodes and by batching stock-code updates. It does not change the local DuckDB schema, model training, HMM/HSMM semantics, or research gates.

## Configuration

Environment variables use the `ASHARE_HMM_` prefix:

- `ASHARE_HMM_MARKET_DATA_SOURCE=mootdx` to enable the TDX path. If unset, the default is AKShare.
- `ASHARE_HMM_TDX_SERVERS=119.147.212.81:7709,221.194.181.176:7709`
- `ASHARE_HMM_TDX_GLOBAL_WORKERS=8`
- `ASHARE_HMM_TDX_MAX_WORKERS=16`
- `ASHARE_HMM_TDX_PER_SERVER_WORKERS=1`
- `ASHARE_HMM_TDX_BATCH_SIZE=80`
- `ASHARE_HMM_TDX_BATCH_SLEEP_SECONDS=3`
- `ASHARE_HMM_TDX_REQUEST_TIMEOUT_SECONDS=15`
- `ASHARE_HMM_TDX_SERVER_COOLDOWN_SECONDS=120`
- `ASHARE_HMM_TDX_FAILURE_THRESHOLD=3`
- `ASHARE_HMM_TDX_FALLBACK_TO_AKSHARE=true`

## Runtime Shape

```text
stock code queue
  -> batches of 50-100 codes
  -> bounded thread pool inside each batch
  -> TDX server pool round-robin lease
  -> single-threaded DuckDB upsert in the caller
  -> sleep between batches
```

## Stability Notes

- Multiple TDX servers reduce pressure on any one TDX node but do not change the local public IP.
- Cooldown is tracked per pool slot. With `TDX_PER_SERVER_WORKERS=1`, this is effectively server-level cooldown. If `TDX_PER_SERVER_WORKERS` is greater than `1`, a failed slot cools down while sibling slots for the same server may still be leased.
- Keep `TDX_PER_SERVER_WORKERS` at `1` unless the selected servers are known to tolerate more.
- Increase `TDX_GLOBAL_WORKERS` gradually. If failures rise, reduce workers or increase batch sleep.
- DuckDB writes remain outside worker threads, so network concurrency does not become concurrent database writes.
- Board metadata and board constituents still use AKShare. If `mootdx` is enabled and a TDX OHLCV request fails without usable cache, the client falls back to AKShare when `TDX_FALLBACK_TO_AKSHARE=true`.
