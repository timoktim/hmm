from __future__ import annotations

import argparse
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

import pandas as pd
from loguru import logger

from src.config import BoardType
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import universe_items_for_update
from src.data_pipeline.validators import validate_board_type, validate_ohlcv
from src.data_sources.akshare_client import AKShareClient
from src.features.custom_basket_features import build_custom_basket_ohlcv
from src.utils.dates import normalize_yyyymmdd
from src.utils.logging import setup_logging


MAX_WORKERS = 3


@dataclass
class UpdateSummary:
    board_type: BoardType
    sectors_seen: int
    sectors_updated: int
    stale_reads: int
    failures: list[str]
    cache_hits: int = 0
    mode: str = "full"


@dataclass
class UpdateProgress:
    current: int
    total: int
    name: str
    stage: str
    successes: int
    failures: int
    cache_hits: int
    stale_reads: int


ProgressCallback = Callable[[UpdateProgress], None]


@dataclass
class BenchmarkUpdateSummary:
    benchmark_id: str
    rows: int
    stale: bool
    failure: str | None = None


def _bounded_workers(workers: int) -> int:
    return max(1, min(int(workers or 1), MAX_WORKERS))


def _lookback_start(max_trade_date: object, fallback_start: str, end_date: str, lookback_days: int) -> str:
    if pd.isna(max_trade_date):
        return fallback_start
    start_ts = pd.to_datetime(max_trade_date) - pd.Timedelta(days=max(0, int(lookback_days)))
    end_ts = pd.to_datetime(end_date)
    if start_ts > end_ts:
        start_ts = end_ts
    return start_ts.strftime("%Y%m%d")


def _sector_max_dates(storage: DuckDBStorage, sector_ids: list[str]) -> dict[str, object]:
    if not sector_ids:
        return {}
    placeholders = ",".join(["?"] * len(sector_ids))
    df = storage.read_df(
        f"""
        SELECT sector_id, max(trade_date) AS max_trade_date
        FROM sector_ohlcv
        WHERE sector_id IN ({placeholders})
        GROUP BY sector_id
        """,
        sector_ids,
    )
    return {} if df.empty else dict(zip(df["sector_id"].astype(str), df["max_trade_date"], strict=False))


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


def _benchmark_max_date(storage: DuckDBStorage, benchmark_id: str) -> object:
    df = storage.read_df(
        "SELECT max(trade_date) AS max_trade_date FROM market_benchmark_ohlcv WHERE benchmark_id = ?",
        [benchmark_id],
    )
    return pd.NA if df.empty else df.loc[0, "max_trade_date"]


def _select_board_meta(
    board_type: BoardType,
    limit: int | None,
    sector_names: list[str] | None,
    client: AKShareClient,
    storage: DuckDBStorage,
) -> tuple[pd.DataFrame, int, int]:
    meta_res = client.board_names(board_type)  # type: ignore[arg-type]
    full_meta = meta_res.data.copy()
    if not full_meta.empty:
        now = pd.Timestamp.now()
        full_meta["is_active"] = True
        full_meta["active_checked_at"] = now
        with storage.connect() as con:
            con.execute(
                """
                UPDATE sector_meta
                SET is_active = FALSE, active_checked_at = ?
                WHERE sector_type = ?
                """,
                [now, board_type],
            )
        storage.upsert_df("sector_meta", full_meta, ["sector_id"])
    meta = full_meta
    if sector_names:
        wanted = set(sector_names)
        meta = meta[meta["sector_name"].isin(wanted)]
    if limit:
        meta = meta.head(limit)
    return meta, int(meta_res.stale), int(meta_res.from_cache)


def _update_constituents(
    board_type: BoardType,
    sector_name: str,
    client: AKShareClient,
    storage: DuckDBStorage,
) -> tuple[int, int, str | None]:
    try:
        cons_res = client.board_constituents(board_type, sector_name)  # type: ignore[arg-type]
        storage.upsert_df("sector_constituents", cons_res.data, ["sector_id", "stock_code"])
        storage.clear_fetch_failure("sector", board_type, sector_name, "board_constituents")
        return int(cons_res.stale), int(cons_res.from_cache), None
    except Exception as exc:
        storage.record_fetch_failure("sector", board_type, sector_name, "board_constituents", exc)
        logger.exception("更新成分股失败: {}", sector_name)
        return 0, 0, f"{sector_name} 成分股更新失败: {exc}"


def _update_boards_impl(
    board_type: BoardType,
    start: str,
    end: str,
    limit: int | None,
    include_constituents: bool,
    sector_names: list[str] | None,
    incremental: bool,
    lookback_days: int,
    workers: int,
    progress_callback: ProgressCallback | None,
    client: AKShareClient | None,
    storage: DuckDBStorage | None,
) -> UpdateSummary:
    setup_logging()
    board_type = validate_board_type(board_type)  # type: ignore[assignment]
    start_date = normalize_yyyymmdd(start)
    end_date = normalize_yyyymmdd(end)
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or AKShareClient(storage=storage)

    meta, stale_reads, cache_hits = _select_board_meta(board_type, limit, sector_names, client, storage)
    failures: list[str] = []
    requested_count = len(sector_names) if sector_names else len(meta)
    if sector_names:
        matched_names = set(meta["sector_name"].dropna().astype(str).tolist()) if not meta.empty else set()
        missing_names = sorted(set(str(name) for name in sector_names) - matched_names)
        if missing_names:
            msg = "板块名称未在当前数据源列表中找到，无法更新行情：" + "、".join(missing_names)
            failures.append(msg)
            for name in missing_names:
                storage.record_fetch_failure("sector", board_type, name, "board_names_match", msg)
    max_dates = _sector_max_dates(storage, meta["sector_id"].astype(str).tolist()) if incremental else {}
    jobs: list[dict[str, object]] = []
    for row in meta.itertuples(index=False):
        actual_start = _lookback_start(max_dates.get(str(row.sector_id)), start_date, end_date, lookback_days) if incremental else start_date
        jobs.append({"sector_id": row.sector_id, "sector_name": row.sector_name, "start_date": actual_start})

    updated = 0
    total = len(jobs) * (2 if include_constituents else 1)
    completed = 0

    def emit(name: str, stage: str) -> None:
        if progress_callback is not None:
            progress_callback(
                UpdateProgress(
                    current=completed,
                    total=total,
                    name=name,
                    stage=stage,
                    successes=updated,
                    failures=len(failures),
                    cache_hits=cache_hits,
                    stale_reads=stale_reads,
                )
            )

    def fetch_hist(job: dict[str, object]) -> tuple[dict[str, object], object]:
        sector_name = str(job["sector_name"])
        hist_res = client.board_hist(board_type, sector_name, str(job["start_date"]), end_date)  # type: ignore[arg-type]
        validate_ohlcv(hist_res.data, sector_name, entity_key="sector_id")
        return job, hist_res

    worker_count = _bounded_workers(workers)
    if worker_count == 1:
        for job in jobs:
            emit(str(job["sector_name"]), "board_hist")
            try:
                job, hist_res = fetch_hist(job)
                storage.upsert_df("sector_ohlcv", hist_res.data, ["sector_id", "trade_date"])
                storage.clear_fetch_failure("sector", board_type, str(job["sector_name"]), "board_hist")
                stale_reads += int(hist_res.stale)
                cache_hits += int(hist_res.from_cache)
                updated += 1
                logger.info("更新板块完成: {}", job["sector_name"])
            except Exception as exc:
                msg = f"{job['sector_name']}: {exc}"
                failures.append(msg)
                storage.record_fetch_failure("sector", board_type, str(job["sector_name"]), "board_hist", exc)
                logger.exception("更新板块失败: {}", msg)
            completed += 1
            emit(str(job["sector_name"]), "board_hist_done")
    else:
        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_map = {executor.submit(fetch_hist, job): job for job in jobs}
            for future in as_completed(future_map):
                job = future_map[future]
                try:
                    job, hist_res = future.result()
                    storage.upsert_df("sector_ohlcv", hist_res.data, ["sector_id", "trade_date"])
                    storage.clear_fetch_failure("sector", board_type, str(job["sector_name"]), "board_hist")
                    stale_reads += int(hist_res.stale)
                    cache_hits += int(hist_res.from_cache)
                    updated += 1
                    logger.info("更新板块完成: {}", job["sector_name"])
                except Exception as exc:
                    msg = f"{job['sector_name']}: {exc}"
                    failures.append(msg)
                    storage.record_fetch_failure("sector", board_type, str(job["sector_name"]), "board_hist", exc)
                    logger.exception("更新板块失败: {}", msg)
                completed += 1
                emit(str(job["sector_name"]), "board_hist_done")

    if include_constituents:
        for job in jobs:
            emit(str(job["sector_name"]), "board_constituents")
            stale, cached, error = _update_constituents(board_type, str(job["sector_name"]), client, storage)
            stale_reads += stale
            cache_hits += cached
            if error:
                failures.append(error)
            completed += 1
            emit(str(job["sector_name"]), "board_constituents_done")

    return UpdateSummary(
        board_type=board_type,
        sectors_seen=requested_count,
        sectors_updated=updated,
        stale_reads=stale_reads,
        failures=failures,
        cache_hits=cache_hits,
        mode="incremental" if incremental else "full",
    )  # type: ignore[arg-type]


def update_boards(
    board_type: BoardType,
    start: str,
    end: str,
    limit: int | None = None,
    include_constituents: bool = True,
    sector_names: list[str] | None = None,
    workers: int = 1,
    progress_callback: ProgressCallback | None = None,
    client: AKShareClient | None = None,
    storage: DuckDBStorage | None = None,
) -> UpdateSummary:
    return _update_boards_impl(
        board_type,
        start,
        end,
        limit,
        include_constituents,
        sector_names,
        incremental=False,
        lookback_days=0,
        workers=workers,
        progress_callback=progress_callback,
        client=client,
        storage=storage,
    )


def incremental_update_boards(
    board_type: BoardType,
    start: str,
    end: str,
    limit: int | None = None,
    include_constituents: bool = True,
    sector_names: list[str] | None = None,
    lookback_days: int = 10,
    workers: int = 1,
    progress_callback: ProgressCallback | None = None,
    client: AKShareClient | None = None,
    storage: DuckDBStorage | None = None,
) -> UpdateSummary:
    return _update_boards_impl(
        board_type,
        start,
        end,
        limit,
        include_constituents,
        sector_names,
        incremental=True,
        lookback_days=lookback_days,
        workers=workers,
        progress_callback=progress_callback,
        client=client,
        storage=storage,
    )


def update_stock_histories(
    stock_codes: list[str],
    start: str,
    end: str,
    incremental: bool = False,
    lookback_days: int = 10,
    missing_only: bool = False,
    limit: int | None = None,
    progress_callback: ProgressCallback | None = None,
    client: AKShareClient | None = None,
    storage: DuckDBStorage | None = None,
) -> UpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or AKShareClient(storage=storage)
    start_date = normalize_yyyymmdd(start)
    end_date = normalize_yyyymmdd(end)
    seen_codes = list(dict.fromkeys(str(code).zfill(6) for code in stock_codes))
    max_dates = _stock_max_dates(storage, seen_codes)
    if missing_only:
        selected_codes = [code for code in seen_codes if code not in max_dates or pd.isna(max_dates.get(code))]
    else:
        selected_codes = seen_codes
    if limit:
        selected_codes = selected_codes[:limit]
    failures: list[str] = []
    stale_reads = 0
    cache_hits = 0
    updated = 0
    total = len(selected_codes)
    for idx, code in enumerate(selected_codes, start=1):
        actual_start = _lookback_start(max_dates.get(code), start_date, end_date, lookback_days) if incremental else start_date
        if progress_callback is not None:
            progress_callback(
                UpdateProgress(
                    current=idx - 1,
                    total=total,
                    name=code,
                    stage="stock_hist",
                    successes=updated,
                    failures=len(failures),
                    cache_hits=cache_hits,
                    stale_reads=stale_reads,
                )
            )
        try:
            res = client.stock_hist(code, actual_start, end_date)
            validate_ohlcv(res.data, code, entity_key="stock_code")
            storage.upsert_df("stock_ohlcv", res.data, ["stock_code", "trade_date"])
            stale_reads += int(res.stale)
            cache_hits += int(res.from_cache)
            updated += 1
        except Exception as exc:
            failures.append(f"{code}: {exc}")
            logger.exception("更新个股失败: {}", code)
        if progress_callback is not None:
            progress_callback(
                UpdateProgress(
                    current=idx,
                    total=total,
                    name=code,
                    stage="stock_hist_done",
                    successes=updated,
                    failures=len(failures),
                    cache_hits=cache_hits,
                    stale_reads=stale_reads,
                )
            )
    return UpdateSummary(
        board_type="industry",
        sectors_seen=total,
        sectors_updated=updated,
        stale_reads=stale_reads,
        failures=failures,
        cache_hits=cache_hits,
        mode="incremental" if incremental else "full",
    )


def update_market_benchmark(
    benchmark_id: str,
    start: str,
    end: str,
    incremental: bool = True,
    lookback_days: int = 10,
    client: AKShareClient | None = None,
    storage: DuckDBStorage | None = None,
) -> BenchmarkUpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or AKShareClient(storage=storage)
    try:
        start_date = normalize_yyyymmdd(start)
        end_date = normalize_yyyymmdd(end)
        if incremental:
            actual_start = _lookback_start(_benchmark_max_date(storage, benchmark_id), start_date, end_date, lookback_days)
        else:
            actual_start = start_date
        res = client.market_benchmark_hist(benchmark_id, actual_start, end_date, force_refresh=True)
        data = res.data.copy()
        if "benchmark_id" not in data.columns:
            data["benchmark_id"] = benchmark_id
        validate_ohlcv(data, benchmark_id, entity_key="benchmark_id")
        storage.upsert_df("market_benchmark_ohlcv", data, ["benchmark_id", "trade_date"])
        storage.clear_fetch_failure("benchmark", "market", benchmark_id, "market_benchmark_hist")
        return BenchmarkUpdateSummary(benchmark_id=benchmark_id, rows=len(data), stale=res.stale)
    except Exception as exc:
        storage.record_fetch_failure("benchmark", "market", benchmark_id, "market_benchmark_hist", exc)
        logger.exception("更新市场基准失败: {}", benchmark_id)
        return BenchmarkUpdateSummary(benchmark_id=benchmark_id, rows=0, stale=False, failure=str(exc))


def update_universe_data(
    universe_id: str,
    start_date: str,
    end_date: str,
    include_constituents: bool = False,
    incremental: bool = True,
    lookback_days: int = 10,
    workers: int = 1,
    progress_callback: ProgressCallback | None = None,
    client: AKShareClient | None = None,
    storage: DuckDBStorage | None = None,
) -> UpdateSummary:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or AKShareClient(storage=storage)
    items = universe_items_for_update(storage, universe_id)
    if items.empty:
        return UpdateSummary(
            board_type="industry",
            sectors_seen=0,
            sectors_updated=0,
            stale_reads=0,
            failures=[f"板块池 {universe_id} 没有任何条目"],
            cache_hits=0,
            mode="universe",
        )

    failures: list[str] = []
    stale_reads = 0
    cache_hits = 0
    seen = 0
    updated = 0
    updater = incremental_update_boards if incremental else update_boards

    for board_type in ["industry", "concept"]:
        names = items.loc[items["item_type"] == board_type, "item_name"].dropna().astype(str).tolist()
        if not names:
            continue
        summary = updater(
            board_type,  # type: ignore[arg-type]
            start_date,
            end_date,
            include_constituents=include_constituents,
            sector_names=names,
            lookback_days=lookback_days,  # type: ignore[call-arg]
            workers=workers,
            progress_callback=progress_callback,
            client=client,
            storage=storage,
        ) if incremental else updater(
            board_type,  # type: ignore[arg-type]
            start_date,
            end_date,
            include_constituents=include_constituents,
            sector_names=names,
            workers=workers,
            progress_callback=progress_callback,
            client=client,
            storage=storage,
        )
        seen += summary.sectors_seen
        updated += summary.sectors_updated
        stale_reads += summary.stale_reads
        cache_hits += summary.cache_hits
        failures.extend(summary.failures)

    custom_items = items[items["item_type"] == "custom_stock_basket"]
    for idx, row in enumerate(custom_items.itertuples(index=False), start=1):
        basket_id = str(row.item_id)
        members = storage.list_basket_members(basket_id)
        seen += 1
        if members.empty:
            failures.append(f"{row.item_name}: 自定义股票池没有成员")
            continue
        if progress_callback is not None:
            progress_callback(
                UpdateProgress(
                    current=idx - 1,
                    total=len(custom_items),
                    name=str(row.item_name),
                    stage="custom_basket_stock_hist",
                    successes=updated,
                    failures=len(failures),
                    cache_hits=cache_hits,
                    stale_reads=stale_reads,
                )
            )
        stock_summary = update_stock_histories(
            members["stock_code"].astype(str).tolist(),
            start_date,
            end_date,
            incremental=True,
            lookback_days=lookback_days,
            missing_only=False,
            progress_callback=progress_callback,
            client=client,
            storage=storage,
        )
        stale_reads += stock_summary.stale_reads
        cache_hits += stock_summary.cache_hits
        failures.extend([f"{row.item_name} 个股: {failure}" for failure in stock_summary.failures])
        basket_ohlcv = build_custom_basket_ohlcv(basket_id, start_date, end_date, storage=storage)
        if basket_ohlcv.empty:
            failures.append(f"{row.item_name}: 自定义股票池指数生成失败，可能缺少个股行情")
        else:
            updated += 1
        if progress_callback is not None:
            progress_callback(
                UpdateProgress(
                    current=idx,
                    total=len(custom_items),
                    name=str(row.item_name),
                    stage="custom_basket_done",
                    successes=updated,
                    failures=len(failures),
                    cache_hits=cache_hits,
                    stale_reads=stale_reads,
                )
            )

    return UpdateSummary(
        board_type="industry",
        sectors_seen=seen,
        sectors_updated=updated,
        stale_reads=stale_reads,
        failures=failures,
        cache_hits=cache_hits,
        mode="universe_incremental" if incremental else "universe_full",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="更新 A 股行业/概念板块数据")
    parser.add_argument("--board-type", choices=["industry", "concept"], required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="today")
    parser.add_argument("--limit", type=int, default=None, help="MVP 调试用：限制板块数量")
    parser.add_argument("--skip-constituents", action="store_true")
    parser.add_argument("--incremental", action="store_true", help="按本地最大 trade_date 增量更新")
    parser.add_argument("--lookback-days", type=int, default=10, help="增量更新时从最新日期往前回补的自然日数")
    parser.add_argument("--workers", type=int, default=1, help="board_hist 低并发抓取线程数，建议不超过 3")
    args = parser.parse_args()
    if args.incremental:
        summary = incremental_update_boards(
            args.board_type,
            args.start,
            args.end,
            limit=args.limit,
            include_constituents=not args.skip_constituents,
            lookback_days=args.lookback_days,
            workers=args.workers,
        )
    else:
        summary = update_boards(
            args.board_type,
            args.start,
            args.end,
            limit=args.limit,
            include_constituents=not args.skip_constituents,
            workers=args.workers,
        )
    print(pd.Series(summary.__dict__).to_string())


if __name__ == "__main__":
    main()
