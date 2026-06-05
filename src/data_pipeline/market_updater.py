from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import time

import pandas as pd

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import _lookback_start
from src.data_pipeline.validators import validate_ohlcv
from src.data_sources.akshare_client import AKShareClient, MARKET_INDEXES
from src.data_sources.base import MarketDataClient
from src.data_sources.factory import create_data_client
from src.utils.dates import normalize_yyyymmdd


DEFAULT_MARKET_INDEX_CODES = ["000001", "399001", "399006", "000300", "000905", "000852", "000985"]


@dataclass
class MarketUpdateSummary:
    seen: int
    updated: int
    rows: int
    failures: list[str]
    stale_reads: int = 0
    cache_hits: int = 0
    skipped: int = 0
    latest_source_trade_date: object | None = None


ProgressCallback = Callable[[dict[str, object]], None]


def _index_max_dates(storage: DuckDBStorage, codes: list[str]) -> dict[str, object]:
    if not codes:
        return {}
    placeholders = ",".join(["?"] * len(codes))
    df = storage.read_df(
        f"""
        SELECT index_code, max(trade_date) AS max_trade_date
        FROM market_index_ohlcv
        WHERE index_code IN ({placeholders})
        GROUP BY index_code
        """,
        codes,
    )
    return {} if df.empty else dict(zip(df["index_code"].astype(str), df["max_trade_date"], strict=False))


def _breadth_max_date(storage: DuckDBStorage, mode: str | None = None) -> object:
    if mode:
        df = storage.read_df(
            "SELECT max(trade_date) AS max_trade_date FROM market_breadth_daily WHERE breadth_mode = ?",
            [mode],
        )
    else:
        df = storage.read_df("SELECT max(trade_date) AS max_trade_date FROM market_breadth_daily")
    return pd.NA if df.empty else df.loc[0, "max_trade_date"]


def _stock_max_dates(storage: DuckDBStorage, stock_codes: list[str]) -> dict[str, object]:
    if not stock_codes:
        return {}
    placeholders = ",".join(["?"] * len(stock_codes))
    df = storage.read_df(
        f"""
        SELECT stock_code, max(trade_date) AS max_trade_date
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
        GROUP BY stock_code
        """,
        stock_codes,
    )
    return {} if df.empty else dict(zip(df["stock_code"].astype(str), df["max_trade_date"], strict=False))


def _infer_latest_source_trade_date(
    client: MarketDataClient,
    stock_codes: list[str],
    max_dates: dict[str, object],
    fallback_start: str,
    end_date: str,
    lookback_days: int,
) -> object | None:
    for code in stock_codes[: min(len(stock_codes), 5)]:
        try:
            probe_start = _lookback_start(max_dates.get(code), fallback_start, end_date, min(int(lookback_days), 10))
            res = client.stock_hist(code, probe_start, end_date)
            if not res.data.empty and "trade_date" in res.data.columns:
                return pd.to_datetime(res.data["trade_date"]).max().date()
        except Exception:
            continue
    return None


def _active_all_a_universe(storage: DuckDBStorage) -> pd.DataFrame:
    return storage.read_df(
        """
        SELECT stock_code, stock_name, exchange, list_status, is_st
        FROM all_a_stock_universe
        WHERE COALESCE(list_status, 'active') = 'active'
        ORDER BY stock_code
        """
    )


def _append_warning(base: str, warning: str) -> str:
    base = "" if pd.isna(base) else str(base)
    return warning if not base else f"{base}；{warning}"


def _coverage_level(
    mode: str,
    effective_count: float,
    expected_count: float | None,
    full_market_coverage_ratio: float | None,
) -> str:
    effective = 0 if pd.isna(effective_count) else int(effective_count)
    ratio = None if full_market_coverage_ratio is None or pd.isna(full_market_coverage_ratio) else float(full_market_coverage_ratio)
    if mode == "full_market":
        if expected_count is None or pd.isna(expected_count) or ratio is None:
            return "unavailable"
        if ratio >= 0.8 and effective >= 2500:
            return "full_market"
        if ratio >= 0.4:
            return "partial_sample"
        return "insufficient"
    if mode == "local_sample":
        if effective >= 500:
            return "local_sample"
        return "insufficient"
    return "unknown"


def _ensure_market_breadth_coverage_columns(storage: DuckDBStorage) -> None:
    with storage.connect() as con:
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS coverage_mode TEXT")
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS local_sample_internal_coverage DOUBLE")
        con.execute("ALTER TABLE market_breadth_daily ADD COLUMN IF NOT EXISTS full_market_coverage_ratio DOUBLE")


def update_all_a_stock_universe(
    client: MarketDataClient | None = None,
    storage: DuckDBStorage | None = None,
    force_refresh: bool = False,
) -> MarketUpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or create_data_client(storage=storage)
    try:
        res = client.all_a_stock_universe(force_refresh=force_refresh)
        data = AKShareClient._normalize_all_a_stock_universe(res.data)
        storage.upsert_df("all_a_stock_universe", data, ["stock_code"])
        return MarketUpdateSummary(
            seen=len(data),
            updated=len(data),
            rows=len(data),
            failures=[],
            stale_reads=int(res.stale),
            cache_hits=int(res.from_cache),
        )
    except Exception as exc:
        return MarketUpdateSummary(seen=0, updated=0, rows=0, failures=[f"全 A 股票池更新失败: {exc}"])


def update_all_a_stock_ohlcv(
    start_date: str,
    end_date: str,
    incremental: bool = True,
    lookback_days: int = 60,
    max_stocks: int | None = None,
    workers: int | None = None,
    batch_size: int | None = None,
    batch_sleep_seconds: float | None = None,
    skip_completed: bool = False,
    probe_latest: bool = True,
    client: MarketDataClient | None = None,
    storage: DuckDBStorage | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MarketUpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or create_data_client(storage=storage)
    universe = _active_all_a_universe(storage)
    if universe.empty:
        return MarketUpdateSummary(seen=0, updated=0, rows=0, failures=["缺少全 A 股票池，请先更新全 A 股票池列表。"])
    codes = universe["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist()
    start = normalize_yyyymmdd(start_date)
    end = normalize_yyyymmdd(end_date)
    max_dates = _stock_max_dates(storage, codes) if incremental else {}
    latest_source_trade_date = None
    if incremental and skip_completed and probe_latest and codes:
        latest_source_trade_date = _infer_latest_source_trade_date(client, codes, max_dates, start, end, lookback_days)
    if latest_source_trade_date is None:
        latest_source_trade_date = pd.to_datetime(end).date()
    jobs: list[dict[str, str]] = []
    skipped = 0
    for code in codes:
        max_date = max_dates.get(code)
        if incremental and skip_completed and not pd.isna(max_date):
            try:
                if pd.to_datetime(max_date).date() >= pd.to_datetime(latest_source_trade_date).date():
                    skipped += 1
                    continue
            except Exception:
                pass
        jobs.append(
            {
                "stock_code": code,
                "start_date": _lookback_start(max_date, start, end, lookback_days) if incremental else start,
            }
        )
    if max_stocks:
        jobs = jobs[: int(max_stocks)]
    configured_workers = settings.tdx_global_workers if workers is None else workers
    worker_count = max(1, min(int(configured_workers or 1), max(1, int(settings.tdx_max_workers or 1))))
    effective_batch_size = max(1, int(batch_size or settings.tdx_batch_size or len(jobs) or 1))
    effective_batch_sleep = max(0.0, float(settings.tdx_batch_sleep_seconds if batch_sleep_seconds is None else batch_sleep_seconds))
    failures: list[str] = []
    rows = 0
    updated = 0
    stale_reads = 0
    cache_hits = 0
    completed = 0

    def emit(code: str, batch_index: int = 0, batch_count: int = 1) -> None:
        if progress_callback is not None:
            progress_callback(
                {
                    "current": completed,
                    "total": len(jobs),
                    "name": code,
                    "batch_index": batch_index,
                    "batch_count": batch_count,
                    "batch_size": effective_batch_size,
                    "worker_count": worker_count,
                    "successes": updated,
                    "failures": len(failures),
                    "cache_hits": cache_hits,
                    "stale_reads": stale_reads,
                    "skipped": skipped,
                    "latest_source_trade_date": latest_source_trade_date,
                }
            )

    def fetch(job: dict[str, str]):
        code = job["stock_code"]
        return code, client.stock_hist(code, job["start_date"], end)

    batches = [jobs[i : i + effective_batch_size] for i in range(0, len(jobs), effective_batch_size)]
    for batch_number, batch in enumerate(batches, start=1):
        if worker_count == 1:
            iterator = [(job, None) for job in batch]
        else:
            executor = ThreadPoolExecutor(max_workers=worker_count)
            future_map = {executor.submit(fetch, job): job for job in batch}
            iterator = [(job, future) for future, job in ((future, future_map[future]) for future in as_completed(future_map))]
        try:
            for job, future in iterator:
                code = str(job["stock_code"])
                emit(code, batch_number, len(batches))
                try:
                    if future is None:
                        _, res = fetch(job)
                    else:
                        _, res = future.result()
                    data = res.data.copy()
                    if "stock_code" not in data.columns:
                        data["stock_code"] = code
                    validate_ohlcv(data, code, entity_key="stock_code")
                    storage.upsert_df("stock_ohlcv", data, ["stock_code", "trade_date"])
                    updated += 1
                    rows += len(data)
                    stale_reads += int(res.stale)
                    cache_hits += int(res.from_cache)
                except Exception as exc:
                    failures.append(f"{code}: {exc}")
                completed += 1
                emit(code, batch_number, len(batches))
        finally:
            if worker_count > 1:
                executor.shutdown(wait=True)
        if batch_number < len(batches) and effective_batch_sleep > 0:
            time.sleep(effective_batch_sleep)

    return MarketUpdateSummary(
        seen=len(jobs),
        updated=updated,
        rows=rows,
        failures=failures,
        stale_reads=stale_reads,
        cache_hits=cache_hits,
        skipped=skipped,
        latest_source_trade_date=latest_source_trade_date,
    )


def update_market_indices(
    start_date: str,
    end_date: str,
    index_codes: list[str] | None = None,
    incremental: bool = True,
    lookback_days: int = 10,
    client: MarketDataClient | None = None,
    storage: DuckDBStorage | None = None,
) -> MarketUpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or create_data_client(storage=storage)
    start = normalize_yyyymmdd(start_date)
    end = normalize_yyyymmdd(end_date)
    codes = [str(code).zfill(6) for code in (index_codes or DEFAULT_MARKET_INDEX_CODES)]
    max_dates = _index_max_dates(storage, codes) if incremental else {}
    failures: list[str] = []
    updated = 0
    rows = 0
    stale_reads = 0
    cache_hits = 0
    for code in codes:
        meta = MARKET_INDEXES.get(code, {"index_name": code})
        actual_start = _lookback_start(max_dates.get(code), start, end, lookback_days) if incremental else start
        try:
            res = client.market_index_hist(code, str(meta["index_name"]), actual_start, end)
            storage.upsert_df("market_index_ohlcv", res.data, ["index_code", "trade_date"])
            updated += 1
            rows += len(res.data)
            stale_reads += int(res.stale)
            cache_hits += int(res.from_cache)
        except Exception as exc:
            failures.append(f"{code} {meta.get('index_name', '')}: {exc}")
    return MarketUpdateSummary(seen=len(codes), updated=updated, rows=rows, failures=failures, stale_reads=stale_reads, cache_hits=cache_hits)


def update_market_breadth(
    start_date: str,
    end_date: str,
    incremental: bool = True,
    lookback_days: int = 10,
    mode: str = "local_sample",
    storage: DuckDBStorage | None = None,
) -> MarketUpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    _ensure_market_breadth_coverage_columns(storage)
    if mode not in {"local_sample", "full_market"}:
        raise ValueError("market breadth mode must be local_sample or full_market")
    start = normalize_yyyymmdd(start_date)
    end = normalize_yyyymmdd(end_date)
    actual_start = _lookback_start(_breadth_max_date(storage, mode), start, end, lookback_days) if incremental else start
    calc_start = (pd.to_datetime(actual_start) - pd.Timedelta(days=45)).strftime("%Y%m%d")
    expected_count: int | None = None
    code_params: list[str] = []
    code_filter = ""
    if mode == "full_market":
        universe = _active_all_a_universe(storage)
        if universe.empty:
            return MarketUpdateSummary(seen=0, updated=0, rows=0, failures=["缺少全 A 股票池，不能计算全市场宽度。"])
        codes = universe["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist()
        expected_count = len(codes)
        placeholders = ",".join(["?"] * len(codes))
        code_filter = f" AND stock_code IN ({placeholders})"
        code_params = codes
    stocks = storage.read_df(
        f"""
        SELECT stock_code, trade_date, close, amount
        FROM stock_ohlcv
        WHERE trade_date BETWEEN ? AND ?
        {code_filter}
        ORDER BY stock_code, trade_date
        """,
        [pd.to_datetime(calc_start).date(), pd.to_datetime(end).date(), *code_params],
    )
    if stocks.empty:
        target = "全 A 股票池" if mode == "full_market" else "本地股票样本"
        return MarketUpdateSummary(seen=0, updated=0, rows=0, failures=[f"缺少{target}个股行情，无法计算宽度"])
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"])
    stocks = stocks.sort_values(["stock_code", "trade_date"])
    stocks["close"] = pd.to_numeric(stocks["close"], errors="coerce")
    stocks["amount"] = pd.to_numeric(stocks["amount"], errors="coerce")
    stocks["daily_ret"] = stocks.groupby("stock_code")["close"].pct_change()
    stocks["ma20"] = stocks.groupby("stock_code")["close"].transform(lambda s: s.rolling(20, min_periods=10).mean())
    stocks["above_ma20"] = (stocks["ma20"].notna()) & (stocks["close"] > stocks["ma20"])
    daily = stocks.groupby("trade_date").agg(
        up_count=("daily_ret", lambda s: int((pd.to_numeric(s, errors="coerce") > 0).sum())),
        down_count=("daily_ret", lambda s: int((pd.to_numeric(s, errors="coerce") < 0).sum())),
        unchanged_count=("daily_ret", lambda s: int((pd.to_numeric(s, errors="coerce") == 0).sum())),
        limit_up_count=("daily_ret", lambda s: int((pd.to_numeric(s, errors="coerce") >= 0.098).sum())),
        limit_down_count=("daily_ret", lambda s: int((pd.to_numeric(s, errors="coerce") <= -0.098).sum())),
        above_ma20_count=("above_ma20", "sum"),
        total_count=("stock_code", "nunique"),
        effective_count=("daily_ret", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        ma20_valid_count=("ma20", lambda s: int(pd.to_numeric(s, errors="coerce").notna().sum())),
        amount_total=("amount", "sum"),
    )
    daily["below_ma20_count"] = daily["ma20_valid_count"] - daily["above_ma20_count"]
    daily["up_ratio"] = daily["up_count"] / daily["effective_count"].replace(0, pd.NA)
    daily["above_ma20_ratio"] = daily["above_ma20_count"] / daily["ma20_valid_count"].replace(0, pd.NA)
    amount_mean = daily["amount_total"].rolling(20, min_periods=10).mean()
    amount_std = daily["amount_total"].rolling(20, min_periods=10).std(ddof=0)
    daily["amount_z_20d"] = (daily["amount_total"] - amount_mean) / amount_std.replace(0, pd.NA)
    daily["coverage_mode"] = mode
    daily["expected_count"] = int(expected_count) if expected_count is not None else pd.NA
    daily["local_sample_internal_coverage"] = daily["effective_count"] / daily["total_count"].replace(0, pd.NA)
    daily["full_market_coverage_ratio"] = pd.NA
    if mode == "full_market":
        daily["full_market_coverage_ratio"] = daily["effective_count"] / daily["expected_count"].replace(0, pd.NA)
    daily["coverage_ratio"] = daily["full_market_coverage_ratio"]
    daily["breadth_mode"] = mode
    daily["coverage_level"] = [
        _coverage_level(mode, row.effective_count, row.expected_count, row.full_market_coverage_ratio)
        for row in daily.itertuples(index=False)
    ]
    daily["coverage_warning"] = ""
    if mode == "local_sample":
        sample_warning = "当前宽度只代表本地股票样本 / 本地已抓取股票样本，不代表全 A 市场。"
        daily["coverage_warning"] = sample_warning
    else:
        low_coverage = daily["coverage_level"] != "full_market"
        daily.loc[low_coverage, "coverage_warning"] = daily.loc[low_coverage].apply(
            lambda row: (
                f"全 A 宽度覆盖不足：应覆盖 {int(row['expected_count']) if pd.notna(row['expected_count']) else 0} 只，"
                f"有效 {int(row['effective_count']) if pd.notna(row['effective_count']) else 0} 只，"
                f"覆盖率 {float(row['full_market_coverage_ratio']) if pd.notna(row['full_market_coverage_ratio']) else 0.0:.1%}。"
            ),
            axis=1,
        )
    ma_warning = "均线宽度样本不足，above_ma20_ratio 可能失真。"
    ma_sparse = (daily["effective_count"] > 0) & (daily["ma20_valid_count"] < daily["effective_count"] * 0.8)
    daily.loc[ma_sparse, "coverage_warning"] = daily.loc[ma_sparse, "coverage_warning"].apply(lambda text: _append_warning(text, ma_warning))
    daily = daily[(daily.index >= pd.to_datetime(actual_start)) & (daily.index <= pd.to_datetime(end))].copy()
    out = daily.reset_index()
    out["trade_date"] = out["trade_date"].dt.date
    out["source"] = "all_a_stock_universe" if mode == "full_market" else "local_stock_sample"
    out["fetched_at"] = pd.Timestamp.now()
    out = out[
        [
            "trade_date",
            "up_count",
            "down_count",
            "unchanged_count",
            "limit_up_count",
            "limit_down_count",
            "above_ma20_count",
            "below_ma20_count",
            "total_count",
            "effective_count",
            "ma20_valid_count",
            "expected_count",
            "coverage_ratio",
            "coverage_mode",
            "local_sample_internal_coverage",
            "full_market_coverage_ratio",
            "breadth_mode",
            "up_ratio",
            "above_ma20_ratio",
            "amount_total",
            "amount_z_20d",
            "coverage_level",
            "coverage_warning",
            "source",
            "fetched_at",
        ]
    ]
    storage.upsert_df("market_breadth_daily", out, ["trade_date", "breadth_mode"])
    return MarketUpdateSummary(seen=len(out), updated=len(out), rows=len(out), failures=[])


def update_full_market_breadth(
    start_date: str,
    end_date: str,
    incremental: bool = True,
    lookback_days: int = 10,
    storage: DuckDBStorage | None = None,
) -> MarketUpdateSummary:
    return update_market_breadth(
        start_date,
        end_date,
        incremental=incremental,
        lookback_days=lookback_days,
        mode="full_market",
        storage=storage,
    )
