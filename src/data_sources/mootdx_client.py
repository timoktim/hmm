from __future__ import annotations

import hashlib
import random
import time
from pathlib import Path
from typing import Callable

import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import BoardType, settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import AKShareClient, MARKET_BENCHMARKS, MARKET_INDEXES
from src.data_sources.base import DataResult
from src.data_sources.tdx_pool import TdxServerPool, parse_tdx_servers
from src.utils.dates import normalize_yyyymmdd


QuotesFactory = Callable[[tuple[str, int]], object]


def _date_text(value: str) -> str:
    text = normalize_yyyymmdd(value)
    return f"{text[:4]}-{text[4:6]}-{text[6:]}"


def _import_mootdx_quotes():
    from mootdx.quotes import Quotes

    return Quotes


class MootdxClient:
    def __init__(
        self,
        cache_dir: Path | None = None,
        storage: DuckDBStorage | None = None,
        server_pool: TdxServerPool | None = None,
        fallback_client: AKShareClient | None = None,
        quotes_factory: QuotesFactory | None = None,
        fallback_to_akshare: bool | None = None,
    ) -> None:
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage or DuckDBStorage()
        self.storage.init_schema()
        self.cache_ttl_seconds = settings.cache_ttl_seconds
        self.server_pool = server_pool or TdxServerPool(
            parse_tdx_servers(settings.tdx_servers),
            per_server_workers=settings.tdx_per_server_workers,
            cooldown_seconds=settings.tdx_server_cooldown_seconds,
            failure_threshold=settings.tdx_failure_threshold,
            acquire_timeout_seconds=settings.tdx_request_timeout_seconds,
        )
        self.fallback_client = fallback_client or AKShareClient(cache_dir=self.cache_dir, storage=self.storage)
        self.quotes_factory = quotes_factory or self._default_quotes_factory
        self.fallback_to_akshare = settings.tdx_fallback_to_akshare if fallback_to_akshare is None else bool(fallback_to_akshare)
        self.bar_count = max(1, int(settings.tdx_bar_count))

    def _default_quotes_factory(self, server: tuple[str, int]) -> object:
        quotes = _import_mootdx_quotes()
        return quotes.factory(
            market="std",
            multithread=True,
            heartbeat=True,
            bestip=False,
            server=server,
            timeout=settings.tdx_request_timeout_seconds,
            quiet=True,
        )

    def _cache_path(self, interface: str, **kwargs: object) -> Path:
        raw = interface + "_" + "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{interface}_{digest}.pkl"

    def _cache_is_fresh(self, path: Path, ttl_seconds: int | float | None) -> bool:
        if not path.exists():
            return False
        if ttl_seconds is None:
            return True
        return (time.time() - path.stat().st_mtime) <= float(ttl_seconds)

    def _history_ttl(self, end_date: str, ttl_seconds: int | float | None) -> int | float | None:
        if ttl_seconds is not None:
            return ttl_seconds
        from src.utils.dates import today_yyyymmdd

        return None if normalize_yyyymmdd(end_date) < today_yyyymmdd() else self.cache_ttl_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.8, min=1, max=4), reraise=True)
    def _call_with_retry(self, func: Callable[[object], pd.DataFrame]) -> pd.DataFrame:
        time.sleep(random.uniform(settings.request_min_sleep, settings.request_max_sleep))
        with self.server_pool.lease() as slot:
            client = self.server_pool.get_or_create_client(slot, self.quotes_factory)
            return func(client)

    def _fetch_tdx(self, interface: str, func: Callable[[object], pd.DataFrame], **kwargs: object) -> DataResult:
        cache_today = bool(kwargs.pop("cache_today", True))
        force_refresh = bool(kwargs.pop("force_refresh", False))
        ttl_seconds = kwargs.pop("ttl_seconds", self.cache_ttl_seconds)
        cache_path = self._cache_path(interface, **kwargs)
        if cache_today and not force_refresh and self._cache_is_fresh(cache_path, ttl_seconds):
            self.storage.update_health_success(interface, cache_hit=True)
            return DataResult(pd.read_pickle(cache_path), from_cache=True)
        try:
            df = self._call_with_retry(func)
            if df is None or df.empty:
                raise ValueError(f"{interface} 返回空数据")
            df.to_pickle(cache_path)
            self.storage.update_health_success(interface, cache_hit=False)
            return DataResult(df)
        except Exception as exc:
            logger.exception("Mootdx/TDX 接口失败: {}", interface)
            self.storage.update_health_failure(interface, exc)
            if cache_path.exists():
                cached = pd.read_pickle(cache_path)
                if not cached.empty:
                    self.storage.update_health_success(interface, cache_hit=True, stale=True)
                    return DataResult(cached, stale=True, from_cache=True, error=str(exc))
            raise

    def _fallback(self, reason: Exception, func: Callable[[], DataResult]) -> DataResult:
        if not self.fallback_to_akshare:
            raise reason
        logger.warning("Mootdx/TDX 失败，回退 AKShare: {}", reason)
        result = func()
        data = result.data.copy()
        if "source" in data.columns:
            data["source"] = "akshare_fallback"
        return DataResult(data, stale=result.stale, from_cache=result.from_cache, error=str(reason))

    def _daily_bars(self, symbol: str, start_date: str, end_date: str, index: bool = False) -> Callable[[object], pd.DataFrame]:
        start_text = _date_text(start_date)
        end_text = _date_text(end_date)

        def call(client: object) -> pd.DataFrame:
            if index and hasattr(client, "index"):
                return client.index(symbol=symbol, frequency=9)
            if hasattr(client, "k"):
                try:
                    return client.k(symbol=symbol, begin=start_text, end=end_text, adjust="qfq")
                except TypeError:
                    return client.k(symbol=symbol, begin=start_text, end=end_text)
            if hasattr(client, "bars"):
                try:
                    return client.bars(symbol=symbol, frequency=9, offset=self.bar_count, adjust="qfq")
                except TypeError:
                    return client.bars(symbol=symbol, frequency=9, offset=self.bar_count)
            raise AttributeError("mootdx quotes client does not expose k/index/bars")

        return call

    @staticmethod
    def _filter_trade_dates(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
        if df.empty or "trade_date" not in df.columns:
            return df
        start = pd.to_datetime(normalize_yyyymmdd(start_date)).date()
        end = pd.to_datetime(normalize_yyyymmdd(end_date)).date()
        dates = pd.to_datetime(df["trade_date"]).dt.date
        return df[(dates >= start) & (dates <= end)].copy()

    def board_names(self, board_type: BoardType, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        return self.fallback_client.board_names(board_type, force_refresh=force_refresh, ttl_seconds=ttl_seconds)

    def board_hist(
        self,
        board_type: BoardType,
        sector_name: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        return self.fallback_client.board_hist(board_type, sector_name, start_date, end_date, force_refresh=force_refresh, ttl_seconds=ttl_seconds)

    def board_constituents(self, board_type: BoardType, sector_name: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        return self.fallback_client.board_constituents(board_type, sector_name, force_refresh=force_refresh, ttl_seconds=ttl_seconds)

    def stock_hist(self, stock_code: str, start_date: str, end_date: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        code = str(stock_code).zfill(6)
        try:
            result = self._fetch_tdx(
                "mootdx_stock_daily",
                self._daily_bars(code, start_date, end_date),
                symbol=code,
                start_date=normalize_yyyymmdd(start_date),
                end_date=normalize_yyyymmdd(end_date),
                force_refresh=force_refresh,
                ttl_seconds=self._history_ttl(end_date, ttl_seconds),
            )
            data = AKShareClient._normalize_ohlcv(result.data, stock_code=code)
            data["source"] = "mootdx"
            data = self._filter_trade_dates(data, start_date, end_date)
            if data.empty:
                raise ValueError("mootdx_stock_daily 请求日期范围内无数据")
            return DataResult(data, stale=result.stale, from_cache=result.from_cache, error=result.error)
        except Exception as exc:
            return self._fallback(exc, lambda: self.fallback_client.stock_hist(code, start_date, end_date, force_refresh=force_refresh, ttl_seconds=ttl_seconds))

    def market_benchmark_hist(
        self,
        benchmark_id: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        if benchmark_id not in MARKET_BENCHMARKS:
            raise ValueError("market benchmark 仅支持 hs300/沪深300 和 csi_all/中证全指")
        meta = MARKET_BENCHMARKS[benchmark_id]
        canonical_id = "hs300" if meta["label"] == "沪深300" else "csi_all"
        code = str(meta["symbol"])[2:]
        try:
            result = self._fetch_tdx(
                "mootdx_market_benchmark_daily",
                self._daily_bars(code, start_date, end_date, index=True),
                benchmark_id=canonical_id,
                symbol=code,
                start_date=normalize_yyyymmdd(start_date),
                end_date=normalize_yyyymmdd(end_date),
                force_refresh=force_refresh,
                ttl_seconds=self._history_ttl(end_date, ttl_seconds),
            )
            data = AKShareClient._normalize_benchmark_ohlcv(result.data, canonical_id)
            data["source"] = "mootdx"
            data = self._filter_trade_dates(data, start_date, end_date)
            if data.empty:
                raise ValueError("mootdx_market_benchmark_daily 请求日期范围内无数据")
            return DataResult(data, stale=result.stale, from_cache=result.from_cache, error=result.error)
        except Exception as exc:
            return self._fallback(
                exc,
                lambda: self.fallback_client.market_benchmark_hist(benchmark_id, start_date, end_date, force_refresh=force_refresh, ttl_seconds=ttl_seconds),
            )

    index_hist = market_benchmark_hist

    def market_index_list(self) -> pd.DataFrame:
        return self.fallback_client.market_index_list()

    def market_index_hist(
        self,
        index_code: str,
        index_name: str | None = None,
        start_date: str = "20200101",
        end_date: str = "today",
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        code = str(index_code).zfill(6)
        meta = MARKET_INDEXES.get(code, {"index_name": index_name or code, "symbol": f"sh{code}"})
        name = index_name or str(meta["index_name"])
        try:
            result = self._fetch_tdx(
                "mootdx_market_index_daily",
                self._daily_bars(code, start_date, end_date, index=True),
                index_code=code,
                start_date=normalize_yyyymmdd(start_date),
                end_date=normalize_yyyymmdd(end_date),
                force_refresh=force_refresh,
                ttl_seconds=self._history_ttl(end_date, ttl_seconds),
            )
            data = AKShareClient._normalize_market_index_ohlcv(result.data, code, name)
            data["source"] = "mootdx"
            data = self._filter_trade_dates(data, start_date, end_date)
            if data.empty:
                raise ValueError("mootdx_market_index_daily 请求日期范围内无数据")
            return DataResult(data, stale=result.stale, from_cache=result.from_cache, error=result.error)
        except Exception as exc:
            return self._fallback(
                exc,
                lambda: self.fallback_client.market_index_hist(code, name, start_date, end_date, force_refresh=force_refresh, ttl_seconds=ttl_seconds),
            )

    def all_a_stock_universe(self, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        return self.fallback_client.all_a_stock_universe(force_refresh=force_refresh, ttl_seconds=ttl_seconds)
