from __future__ import annotations

import hashlib
import os
import random
import threading
import time
from collections.abc import Callable, Iterable
from pathlib import Path

import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import BoardType, settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.utils.dates import normalize_yyyymmdd, to_trade_date, today_yyyymmdd


_HEALTH_LOCK = threading.RLock()
_RATE_LOCK = threading.RLock()
_LAST_REQUEST_AT = 0.0

SOURCE_PRIMARY = "tushare_qfq"
SOURCE_PRIORITY_PRIMARY = 0
SOURCE_PRIORITY_DERIVED = 10

MARKET_BENCHMARKS = {
    "hs300": {"label": "沪深300", "ts_code": "000300.SH", "index_code": "000300"},
    "沪深300": {"label": "沪深300", "ts_code": "000300.SH", "index_code": "000300"},
    "csi_all": {"label": "中证全指", "ts_code": "000985.CSI", "index_code": "000985"},
    "中证全指": {"label": "中证全指", "ts_code": "000985.CSI", "index_code": "000985"},
}

MARKET_INDEXES = {
    "000001": {"index_name": "上证指数", "ts_code": "000001.SH"},
    "399001": {"index_name": "深证成指", "ts_code": "399001.SZ"},
    "399006": {"index_name": "创业板指", "ts_code": "399006.SZ"},
    "000300": {"index_name": "沪深300", "ts_code": "000300.SH"},
    "000905": {"index_name": "中证500", "ts_code": "000905.SH"},
    "000852": {"index_name": "中证1000", "ts_code": "000852.SH"},
    "000985": {"index_name": "中证全指", "ts_code": "000985.CSI"},
}


def _import_tushare():
    import tushare as ts

    return ts


def _stock_code_from_ts_code(value: object) -> str:
    raw = str(value or "").strip()
    return raw.split(".", 1)[0].zfill(6)


def _exchange_from_ts_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    if "." in raw:
        return raw.split(".")[-1]
    code = _stock_code_from_ts_code(raw)
    if code.startswith(("4", "8", "920")):
        return "BJ"
    if code.startswith(("5", "6", "9")):
        return "SH"
    return "SZ"


def _ts_code_from_stock_code(stock_code: str) -> str:
    code = str(stock_code).strip().zfill(6)
    if code.startswith(("4", "8", "920")):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _safe_numeric(df: pd.DataFrame, cols: Iterable[str]) -> pd.DataFrame:
    for col in cols:
        if col not in df.columns:
            df[col] = pd.NA
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _audit_columns(
    df: pd.DataFrame,
    *,
    source: str,
    source_priority: int,
    is_provisional: bool,
    validation_status: str,
) -> pd.DataFrame:
    out = df.copy()
    now = pd.Timestamp.now()
    out["source"] = source
    out["fetched_at"] = now
    out["source_priority"] = int(source_priority)
    out["is_provisional"] = bool(is_provisional)
    out["validation_status"] = validation_status
    if "vendor_update_time" not in out.columns:
        out["vendor_update_time"] = pd.NaT
    return out


def _safe_error(exc: Exception) -> str:
    return type(exc).__name__


class TushareClient:
    """Tushare Pro client for confirmed daily data.

    The token is intentionally read only when an API call is made. Importing or
    constructing the client is safe in CI and does not require a private token.
    """

    def __init__(self, cache_dir: Path | None = None, storage: DuckDBStorage | None = None) -> None:
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage or DuckDBStorage()
        self.storage.init_schema()
        self.cache_ttl_seconds = settings.cache_ttl_seconds
        self._pro = None
        self._board_code_by_name: dict[tuple[str, str], str] = {}

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

    def _default_ttl(self, ttl_seconds: int | float | None) -> int | float | None:
        return self.cache_ttl_seconds if ttl_seconds is None else ttl_seconds

    def _history_ttl(self, end_date: str, ttl_seconds: int | float | None) -> int | float | None:
        if ttl_seconds is not None:
            return ttl_seconds
        return None if normalize_yyyymmdd(end_date) < today_yyyymmdd() else self.cache_ttl_seconds

    def _token(self) -> str:
        token = (os.getenv("ASHARE_HMM_TUSHARE_TOKEN") or settings.tushare_token or "").strip()
        if not token:
            raise RuntimeError("缺少 Tushare token，请配置环境变量 ASHARE_HMM_TUSHARE_TOKEN。")
        return token

    def _rate_limit(self) -> None:
        global _LAST_REQUEST_AT
        min_interval = max(float(settings.tushare_request_min_interval_seconds), 0.0)
        jitter = max(float(settings.tushare_request_jitter_seconds), 0.0)
        with _RATE_LOCK:
            now = time.monotonic()
            wait = (_LAST_REQUEST_AT + min_interval) - now
            if wait > 0:
                time.sleep(wait)
            if jitter:
                time.sleep(random.uniform(0.0, jitter))
            _LAST_REQUEST_AT = time.monotonic()

    def _api(self):
        if self._pro is None:
            ts = _import_tushare()
            self._pro = ts.pro_api(self._token())
        return self._pro

    def _query_once(self, api_name: str, **params: object) -> pd.DataFrame:
        self._rate_limit()
        pro = self._api()
        method = getattr(pro, api_name, None)
        if callable(method):
            return method(**params)
        return pro.query(api_name, **params)

    @retry(
        stop=stop_after_attempt(max(1, int(settings.tushare_max_retries))),
        wait=wait_exponential(multiplier=0.8, min=1, max=5),
        reraise=True,
    )
    def _call_with_retry(self, api_name: str, **params: object) -> pd.DataFrame:
        return self._query_once(api_name, **params)

    def _fetch(self, interface: str, func: Callable[[], pd.DataFrame], **kwargs: object) -> DataResult:
        force_refresh = bool(kwargs.pop("force_refresh", False))
        ttl_seconds = kwargs.pop("ttl_seconds", self.cache_ttl_seconds)
        cache_today = bool(kwargs.pop("cache_today", True))
        cache_path = self._cache_path(interface, **kwargs)
        if cache_today and not force_refresh and self._cache_is_fresh(cache_path, ttl_seconds):
            with _HEALTH_LOCK:
                self.storage.update_health_success(interface, cache_hit=True)
            return DataResult(pd.read_pickle(cache_path), from_cache=True)
        try:
            df = func()
            if df is None or df.empty:
                raise ValueError(f"{interface} 返回空数据")
            df.to_pickle(cache_path)
            with _HEALTH_LOCK:
                self.storage.update_health_success(interface, cache_hit=False)
            return DataResult(df)
        except Exception as exc:
            logger.warning("Tushare 接口失败: {} ({})", interface, type(exc).__name__)
            with _HEALTH_LOCK:
                self.storage.update_health_failure(interface, _safe_error(exc))
            if cache_path.exists():
                cached = pd.read_pickle(cache_path)
                if not cached.empty:
                    with _HEALTH_LOCK:
                        self.storage.update_health_success(interface, cache_hit=True, stale=True)
                    return DataResult(cached, stale=True, from_cache=True, error=_safe_error(exc))
            raise RuntimeError(f"{interface} 调用失败: {_safe_error(exc)}") from None

    def trade_dates(self, start_date: str, end_date: str, force_refresh: bool = False) -> list[str]:
        start = normalize_yyyymmdd(start_date)
        end = normalize_yyyymmdd(end_date)

        def func() -> pd.DataFrame:
            return self._call_with_retry("trade_cal", exchange="", start_date=start, end_date=end, is_open="1")

        res = self._fetch("tushare_trade_cal", func, start_date=start, end_date=end, force_refresh=force_refresh, ttl_seconds=None)
        if "cal_date" not in res.data.columns:
            raise ValueError("Tushare trade_cal 缺少 cal_date")
        return res.data["cal_date"].dropna().astype(str).sort_values().tolist()

    @staticmethod
    def _normalize_all_a_stock_universe(df: pd.DataFrame) -> pd.DataFrame:
        out = df.rename(columns={"symbol": "stock_code", "name": "stock_name"}).copy()
        if "stock_code" not in out.columns:
            if "ts_code" in out.columns:
                out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
            else:
                raise ValueError("Tushare stock_basic 缺少 symbol/ts_code")
        if "stock_name" not in out.columns:
            raise ValueError("Tushare stock_basic 缺少 name")
        out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
        out["stock_name"] = out["stock_name"].astype(str)
        if "exchange" in out.columns:
            out["exchange"] = out["exchange"].astype(str).replace({"SSE": "SH", "SZSE": "SZ", "BSE": "BJ"})
        elif "ts_code" in out.columns:
            out["exchange"] = out["ts_code"].map(_exchange_from_ts_code)
        else:
            out["exchange"] = out["stock_code"].map(_exchange_from_ts_code)
        out["list_status"] = out.get("list_status", "active")
        out["list_status"] = out["list_status"].replace({"L": "active", "D": "delisted", "P": "paused"}).fillna("active")
        out["is_st"] = out["stock_name"].str.contains("ST", case=False, na=False)
        for col in ["list_date", "delist_date"]:
            if col not in out.columns:
                out[col] = pd.NaT
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
        out = _audit_columns(
            out,
            source="tushare",
            source_priority=SOURCE_PRIORITY_PRIMARY,
            is_provisional=False,
            validation_status="validated",
        )
        return out[
            [
                "stock_code",
                "stock_name",
                "exchange",
                "list_status",
                "is_st",
                "list_date",
                "delist_date",
                "source",
                "fetched_at",
                "source_priority",
                "is_provisional",
                "validation_status",
                "vendor_update_time",
            ]
        ].drop_duplicates("stock_code")

    def all_a_stock_universe(self, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        fields = "ts_code,symbol,name,exchange,market,list_status,list_date,delist_date,is_hs"

        def func() -> pd.DataFrame:
            return self._call_with_retry("stock_basic", exchange="", list_status="L", fields=fields)

        res = self._fetch("tushare_stock_basic", func, force_refresh=force_refresh, ttl_seconds=self._default_ttl(ttl_seconds), fields=fields)
        res.data = self._normalize_all_a_stock_universe(res.data)
        return res

    def _daily_raw_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        date = normalize_yyyymmdd(trade_date)
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

        def func() -> pd.DataFrame:
            return self._call_with_retry("daily", trade_date=date, fields=fields)

        return self._fetch("tushare_daily_by_trade_date", func, trade_date=date, fields=fields, force_refresh=force_refresh, ttl_seconds=self._history_ttl(date, None))

    def _daily_basic_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        date = normalize_yyyymmdd(trade_date)
        fields = "ts_code,trade_date,turnover_rate,volume_ratio,total_mv,circ_mv"

        def func() -> pd.DataFrame:
            return self._call_with_retry("daily_basic", trade_date=date, fields=fields)

        return self._fetch("tushare_daily_basic_by_trade_date", func, trade_date=date, fields=fields, force_refresh=force_refresh, ttl_seconds=self._history_ttl(date, None))

    def _adj_factor_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        date = normalize_yyyymmdd(trade_date)

        def func() -> pd.DataFrame:
            return self._call_with_retry("adj_factor", trade_date=date)

        return self._fetch("tushare_adj_factor_by_trade_date", func, trade_date=date, force_refresh=force_refresh, ttl_seconds=self._history_ttl(date, None))

    @staticmethod
    def _normalize_qfq_stock_daily(
        daily: pd.DataFrame,
        adj: pd.DataFrame,
        basic: pd.DataFrame | None = None,
        *,
        validation_status: str = "validated",
    ) -> pd.DataFrame:
        if daily.empty:
            return pd.DataFrame(
                columns=[
                    "stock_code",
                    "trade_date",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "amount",
                    "pct_chg",
                    "turnover",
                    "source",
                    "fetched_at",
                    "source_priority",
                    "is_provisional",
                    "validation_status",
                    "vendor_update_time",
                ]
            )
        out = daily.rename(columns={"vol": "volume"}).copy()
        if "ts_code" not in out.columns or "trade_date" not in out.columns:
            raise ValueError("Tushare daily 缺少 ts_code/trade_date")
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
        out["trade_date"] = to_trade_date(out["trade_date"])
        _safe_numeric(out, ["open", "high", "low", "close", "volume", "amount", "pct_chg"])
        adj_work = adj.copy()
        if not adj_work.empty:
            if "ts_code" not in adj_work.columns or "trade_date" not in adj_work.columns or "adj_factor" not in adj_work.columns:
                raise ValueError("Tushare adj_factor 缺少 ts_code/trade_date/adj_factor")
            adj_work["trade_date"] = to_trade_date(adj_work["trade_date"])
            adj_work["adj_factor"] = pd.to_numeric(adj_work["adj_factor"], errors="coerce")
            out = out.merge(adj_work[["ts_code", "trade_date", "adj_factor"]], on=["ts_code", "trade_date"], how="left")
        else:
            out["adj_factor"] = pd.NA
        if settings.tushare_qfq_adjustment_enabled:
            latest_factor = out.sort_values("trade_date").groupby("stock_code")["adj_factor"].transform("last")
            scale = pd.to_numeric(out["adj_factor"], errors="coerce") / pd.to_numeric(latest_factor, errors="coerce")
            scale = scale.where(scale.notna() & scale.gt(0), 1.0)
            for col in ["open", "high", "low", "close"]:
                out[col] = pd.to_numeric(out[col], errors="coerce") * scale
        if basic is not None and not basic.empty:
            basic_work = basic.rename(columns={"turnover_rate": "turnover"}).copy()
            basic_work["trade_date"] = to_trade_date(basic_work["trade_date"])
            keep = [col for col in ["ts_code", "trade_date", "turnover", "volume_ratio", "total_mv", "circ_mv"] if col in basic_work.columns]
            out = out.merge(basic_work[keep], on=["ts_code", "trade_date"], how="left")
        if "turnover" not in out.columns:
            out["turnover"] = pd.NA
        _safe_numeric(out, ["turnover"])
        out = _audit_columns(
            out,
            source=SOURCE_PRIMARY if settings.tushare_qfq_adjustment_enabled else "tushare_raw_daily",
            source_priority=SOURCE_PRIORITY_PRIMARY,
            is_provisional=False,
            validation_status=validation_status,
        )
        cols = [
            "stock_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pct_chg",
            "turnover",
            "source",
            "fetched_at",
            "source_priority",
            "is_provisional",
            "validation_status",
            "vendor_update_time",
        ]
        return out[cols].drop_duplicates(["stock_code", "trade_date"]).sort_values(["stock_code", "trade_date"])

    def stock_daily_by_trade_date(
        self,
        trade_date: str,
        include_basic: bool = True,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        date = normalize_yyyymmdd(trade_date)
        daily_res = self._daily_raw_by_trade_date(date, force_refresh=force_refresh)
        adj_res = self._adj_factor_by_trade_date(date, force_refresh=force_refresh)
        basic: pd.DataFrame | None = None
        status = "validated"
        stale = daily_res.stale or adj_res.stale
        from_cache = daily_res.from_cache and adj_res.from_cache
        error = daily_res.error or adj_res.error
        if include_basic:
            try:
                basic_res = self._daily_basic_by_trade_date(date, force_refresh=force_refresh)
                basic = basic_res.data
                stale = stale or basic_res.stale
                from_cache = from_cache and basic_res.from_cache
            except Exception as exc:
                status = "partial_daily_basic_unavailable"
                error = _safe_error(exc)
                logger.warning("Tushare daily_basic 不可用，继续写入日线和复权因子: {}", type(exc).__name__)
        return DataResult(
            self._normalize_qfq_stock_daily(daily_res.data, adj_res.data, basic, validation_status=status),
            stale=stale,
            from_cache=from_cache,
            error=error,
        )

    def stock_daily_by_trade_dates(
        self,
        trade_dates: list[str],
        *,
        include_basic: bool = True,
        force_refresh: bool = False,
        progress_callback: Callable[[dict[str, object]], None] | None = None,
    ) -> DataResult:
        dates = [normalize_yyyymmdd(date) for date in trade_dates]
        daily_frames: list[pd.DataFrame] = []
        adj_frames: list[pd.DataFrame] = []
        basic_frames: list[pd.DataFrame] = []
        errors: list[str] = []
        stale = False
        from_cache = True
        for idx, date in enumerate(dates, start=1):
            if progress_callback:
                progress_callback({"phase": "fetch", "api": "daily", "current": idx - 1, "total": len(dates), "name": date})
            daily_res = self._daily_raw_by_trade_date(date, force_refresh=force_refresh)
            daily_frames.append(daily_res.data)
            stale = stale or daily_res.stale
            from_cache = from_cache and daily_res.from_cache
            if progress_callback:
                progress_callback({"phase": "fetch", "api": "adj_factor", "current": idx - 1, "total": len(dates), "name": date})
            adj_res = self._adj_factor_by_trade_date(date, force_refresh=force_refresh)
            adj_frames.append(adj_res.data)
            stale = stale or adj_res.stale
            from_cache = from_cache and adj_res.from_cache
            if include_basic:
                try:
                    if progress_callback:
                        progress_callback({"phase": "fetch", "api": "daily_basic", "current": idx - 1, "total": len(dates), "name": date})
                    basic_res = self._daily_basic_by_trade_date(date, force_refresh=force_refresh)
                    basic_frames.append(basic_res.data)
                    stale = stale or basic_res.stale
                    from_cache = from_cache and basic_res.from_cache
                except Exception as exc:
                    errors.append(f"{date}: daily_basic unavailable ({_safe_error(exc)})")
            if progress_callback:
                progress_callback({"phase": "fetch", "api": "daily", "current": idx, "total": len(dates), "name": date})
        status = "validated" if not errors else "partial_daily_basic_unavailable"
        data = self._normalize_qfq_stock_daily(
            pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame(),
            pd.concat(adj_frames, ignore_index=True) if adj_frames else pd.DataFrame(),
            pd.concat(basic_frames, ignore_index=True) if basic_frames else None,
            validation_status=status,
        )
        return DataResult(data, stale=stale, from_cache=from_cache, error="; ".join(errors) if errors else None)

    def stock_hist(self, stock_code: str, start_date: str, end_date: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        code = str(stock_code).zfill(6)
        ts_code = _ts_code_from_stock_code(code)
        start = normalize_yyyymmdd(start_date)
        end = normalize_yyyymmdd(end_date)
        fields = "ts_code,trade_date,open,high,low,close,pre_close,change,pct_chg,vol,amount"

        def daily_func() -> pd.DataFrame:
            return self._call_with_retry("daily", ts_code=ts_code, start_date=start, end_date=end, fields=fields)

        def adj_func() -> pd.DataFrame:
            return self._call_with_retry("adj_factor", ts_code=ts_code, start_date=start, end_date=end)

        daily_res = self._fetch("tushare_daily_by_stock", daily_func, ts_code=ts_code, start_date=start, end_date=end, fields=fields, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end, ttl_seconds))
        adj_res = self._fetch("tushare_adj_factor_by_stock", adj_func, ts_code=ts_code, start_date=start, end_date=end, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end, ttl_seconds))
        data = self._normalize_qfq_stock_daily(daily_res.data, adj_res.data, validation_status="validated")
        return DataResult(data, stale=daily_res.stale or adj_res.stale, from_cache=daily_res.from_cache and adj_res.from_cache, error=daily_res.error or adj_res.error)

    @staticmethod
    def _normalize_index_daily(df: pd.DataFrame, index_code: str, index_name: str) -> pd.DataFrame:
        out = df.rename(columns={"vol": "volume"}).copy()
        if "trade_date" not in out.columns:
            raise ValueError("Tushare index_daily 缺少 trade_date")
        out["trade_date"] = to_trade_date(out["trade_date"])
        _safe_numeric(out, ["open", "high", "low", "close", "volume", "amount", "pct_chg"])
        out["index_code"] = index_code
        out["index_name"] = index_name
        out = _audit_columns(out, source="tushare_index_daily", source_priority=SOURCE_PRIORITY_PRIMARY, is_provisional=False, validation_status="validated")
        cols = ["index_code", "index_name", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "source", "fetched_at", "source_priority", "is_provisional", "validation_status", "vendor_update_time"]
        return out[cols].drop_duplicates(["index_code", "trade_date"]).sort_values("trade_date")

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
        meta = MARKET_INDEXES.get(code, {"index_name": index_name or code, "ts_code": f"{code}.SH"})
        name = index_name or str(meta["index_name"])
        ts_code = str(meta["ts_code"])
        start = normalize_yyyymmdd(start_date)
        end = normalize_yyyymmdd(end_date)
        fields = "ts_code,trade_date,close,open,high,low,pre_close,change,pct_chg,vol,amount"

        def func() -> pd.DataFrame:
            return self._call_with_retry("index_daily", ts_code=ts_code, start_date=start, end_date=end, fields=fields)

        res = self._fetch("tushare_index_daily", func, ts_code=ts_code, start_date=start, end_date=end, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end, ttl_seconds))
        res.data = self._normalize_index_daily(res.data, code, name)
        return res

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
        res = self.market_index_hist(str(meta["index_code"]), str(meta["label"]), start_date, end_date, force_refresh=force_refresh, ttl_seconds=ttl_seconds)
        out = res.data.rename(columns={"index_code": "benchmark_id"}).copy()
        out["benchmark_id"] = canonical_id
        out["turnover"] = pd.NA
        cols = ["benchmark_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source", "fetched_at", "source_priority", "is_provisional", "validation_status", "vendor_update_time"]
        res.data = out[cols].drop_duplicates(["benchmark_id", "trade_date"]).sort_values("trade_date")
        return res

    index_hist = market_benchmark_hist

    def board_names(self, board_type: BoardType, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        if board_type != "industry":
            raise NotImplementedError("Tushare 2000 积分主链路暂不默认刷新概念板块；请使用 legacy 显式路径或本地历史数据。")
        src_candidates = [settings.tushare_sw_source]
        if settings.tushare_sw_source != "SW":
            src_candidates.append("SW")
        last_exc: Exception | None = None
        for src in src_candidates:
            def func(src: str = src) -> pd.DataFrame:
                return self._call_with_retry("index_classify", level=settings.tushare_sw_level, src=src)

            try:
                res = self._fetch("tushare_index_classify", func, level=settings.tushare_sw_level, src=src, force_refresh=force_refresh, ttl_seconds=self._default_ttl(ttl_seconds))
                raw = res.data.copy()
                name_col = "industry_name" if "industry_name" in raw.columns else "name"
                code_col = "index_code" if "index_code" in raw.columns else "industry_code"
                if name_col not in raw.columns or code_col not in raw.columns:
                    raise ValueError("index_classify 缺少 industry_name/index_code")
                rows = []
                for row in raw.itertuples(index=False):
                    name = str(getattr(row, name_col)).strip()
                    code = str(getattr(row, code_col)).strip()
                    self._board_code_by_name[("industry", name)] = code
                    rows.append({"sector_id": f"industry:{name}", "sector_type": "industry", "sector_name": name})
                out = pd.DataFrame(rows).drop_duplicates("sector_id")
                out = _audit_columns(out, source="tushare_sw_classify", source_priority=SOURCE_PRIORITY_PRIMARY, is_provisional=False, validation_status="validated")
                out["last_update"] = out["fetched_at"]
                res.data = out[["sector_id", "sector_type", "sector_name", "source", "last_update"]]
                return res
            except Exception as exc:
                last_exc = exc
        raise RuntimeError(f"Tushare 申万行业列表获取失败: {last_exc}")

    def _sector_code(self, board_type: BoardType, sector_name: str) -> str:
        key = (str(board_type), str(sector_name))
        if key not in self._board_code_by_name:
            self.board_names(board_type)
        if key not in self._board_code_by_name:
            raise ValueError(f"Tushare 缺少板块代码: {board_type}:{sector_name}")
        return self._board_code_by_name[key]

    def board_constituents(self, board_type: BoardType, sector_name: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        if board_type != "industry":
            raise NotImplementedError("Tushare 主链路暂不默认刷新概念成分股。")
        code = self._sector_code("industry", sector_name)
        fields = "l1_code,l1_name,l2_code,l2_name,l3_code,l3_name,ts_code,con_code,con_name,in_date,out_date,is_new"

        def func() -> pd.DataFrame:
            params = {"is_new": "Y", "fields": fields}
            if settings.tushare_sw_level == "L1":
                params["l1_code"] = code
            elif settings.tushare_sw_level == "L2":
                params["l2_code"] = code
            else:
                params["l3_code"] = code
            return self._call_with_retry("index_member_all", **params)

        res = self._fetch("tushare_index_member_all", func, sector_name=sector_name, code=code, level=settings.tushare_sw_level, force_refresh=force_refresh, ttl_seconds=self._default_ttl(ttl_seconds))
        raw = res.data.copy()
        raw["sector_id"] = f"industry:{sector_name}"
        if "stock_code" not in raw.columns:
            if "con_code" in raw.columns:
                raw["stock_code"] = raw["con_code"].map(_stock_code_from_ts_code)
            elif "ts_code" in raw.columns:
                raw["stock_code"] = raw["ts_code"].map(_stock_code_from_ts_code)
            else:
                raise ValueError("index_member_all 缺少 con_code/ts_code")
        raw["stock_name"] = raw.get("con_name", raw.get("stock_name", ""))
        raw["stock_code"] = raw["stock_code"].astype(str).str.zfill(6)
        raw["stock_name"] = raw["stock_name"].astype(str)
        if "in_date" in raw.columns:
            raw["in_sector_date"] = pd.to_datetime(raw["in_date"], errors="coerce").dt.date
        else:
            raw["in_sector_date"] = pd.NaT
        raw["in_sector_date"] = raw["in_sector_date"].fillna(pd.Timestamp.now().date())
        raw = _audit_columns(raw, source="tushare_sw_members", source_priority=SOURCE_PRIORITY_PRIMARY, is_provisional=False, validation_status="validated")
        cols = ["sector_id", "stock_code", "stock_name", "in_sector_date", "source", "fetched_at", "source_priority", "is_provisional", "validation_status", "vendor_update_time"]
        res.data = raw[cols].drop_duplicates(["sector_id", "stock_code"])
        return res

    def board_hist(
        self,
        board_type: BoardType,
        sector_name: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        if board_type != "industry":
            raise NotImplementedError("Tushare 主链路暂不默认刷新概念板块行情。")
        return self._local_sector_basket_hist(board_type, sector_name, start_date, end_date)

    def _local_sector_basket_hist(self, board_type: BoardType, sector_name: str, start_date: str, end_date: str) -> DataResult:
        sector_id = f"{board_type}:{sector_name}"
        start = pd.to_datetime(normalize_yyyymmdd(start_date)).date()
        end = pd.to_datetime(normalize_yyyymmdd(end_date)).date()
        members = self.storage.read_df("SELECT DISTINCT stock_code FROM sector_constituents WHERE sector_id = ?", [sector_id])
        if members.empty:
            raise ValueError(f"缺少 {sector_id} 成分股，无法生成 Tushare 本地聚合板块行情。")
        codes = members["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist()
        placeholders = ",".join(["?"] * len(codes))
        calc_start = (pd.to_datetime(start) - pd.Timedelta(days=15)).date()
        stocks = self.storage.read_df(
            f"""
            SELECT stock_code, trade_date, open, high, low, close, volume, amount
            FROM stock_ohlcv
            WHERE stock_code IN ({placeholders})
              AND trade_date BETWEEN ? AND ?
            ORDER BY stock_code, trade_date
            """,
            [*codes, calc_start, end],
        )
        if stocks.empty:
            raise ValueError(f"缺少 {sector_id} 的 Tushare 日频个股行情，不能构造本地聚合板块。")
        stocks["trade_date"] = pd.to_datetime(stocks["trade_date"])
        stocks = stocks.sort_values(["stock_code", "trade_date"])
        for col in ["open", "high", "low", "close", "volume", "amount"]:
            stocks[col] = pd.to_numeric(stocks[col], errors="coerce")
        stocks["prev_close"] = stocks.groupby("stock_code")["close"].shift(1)
        valid = stocks["prev_close"].notna() & stocks["prev_close"].gt(0)
        for col in ["open", "high", "low", "close"]:
            stocks[f"{col}_ret"] = (stocks[col] / stocks["prev_close"] - 1.0).where(valid)
        grouped = stocks.groupby("trade_date").agg(
            open_ret=("open_ret", "mean"),
            high_ret=("high_ret", "mean"),
            low_ret=("low_ret", "mean"),
            close_ret=("close_ret", "mean"),
            volume=("volume", "sum"),
            amount=("amount", "sum"),
        ).sort_index()
        grouped = grouped[(grouped.index.date >= start) & (grouped.index.date <= end)]
        if grouped.empty:
            raise ValueError(f"{sector_id} 在目标区间没有可构造的本地聚合行情。")
        rows = []
        prev_close = self._previous_sector_close(sector_id, start)
        for date, row in grouped.iterrows():
            close_ret = 0.0 if pd.isna(row.close_ret) else float(row.close_ret)
            open_ret = close_ret if pd.isna(row.open_ret) else float(row.open_ret)
            high_ret = max(open_ret, close_ret) if pd.isna(row.high_ret) else float(row.high_ret)
            low_ret = min(open_ret, close_ret) if pd.isna(row.low_ret) else float(row.low_ret)
            close = prev_close * (1.0 + close_ret)
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": date.date(),
                    "open": prev_close * (1.0 + open_ret),
                    "high": prev_close * (1.0 + high_ret),
                    "low": prev_close * (1.0 + low_ret),
                    "close": close,
                    "volume": row.volume,
                    "amount": row.amount,
                    "pct_chg": close_ret * 100.0,
                    "turnover": pd.NA,
                }
            )
            prev_close = close
        out = _audit_columns(pd.DataFrame(rows), source="tushare_local_aggregate", source_priority=SOURCE_PRIORITY_DERIVED, is_provisional=True, validation_status="local_aggregate")
        return DataResult(out)

    def _previous_sector_close(self, sector_id: str, start: object) -> float:
        previous = self.storage.read_df(
            """
            SELECT close
            FROM sector_ohlcv
            WHERE sector_id = ?
              AND trade_date < ?
              AND close IS NOT NULL
            ORDER BY trade_date DESC
            LIMIT 1
            """,
            [sector_id, start],
        )
        if not previous.empty:
            close = pd.to_numeric(previous["close"], errors="coerce").dropna()
            if not close.empty and float(close.iloc[0]) > 0:
                return float(close.iloc[0])
        return 1000.0
