from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Callable

import pandas as pd
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import BoardType, settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.data_sources.ths_helpers import em_board_constituents, ths_board_constituents, ths_board_hist, ths_board_names
from src.utils.dates import normalize_yyyymmdd, to_trade_date, today_yyyymmdd


_HEALTH_LOCK = threading.RLock()


BOARD_META_COLUMNS = {
    "板块名称": "sector_name",
    "名称": "sector_name",
    "代码": "code",
    "涨跌幅": "pct_chg",
    "换手率": "turnover",
}

OHLCV_COLUMNS = {
    "date": "trade_date",
    "日期": "trade_date",
    "datetime": "trade_date",
    "time": "trade_date",
    "open": "open",
    "开盘": "open",
    "开盘价": "open",
    "high": "high",
    "最高": "high",
    "最高价": "high",
    "low": "low",
    "最低": "low",
    "最低价": "low",
    "close": "close",
    "收盘": "close",
    "收盘价": "close",
    "volume": "volume",
    "vol": "volume",
    "成交量": "volume",
    "amount": "amount",
    "成交额": "amount",
    "涨跌幅": "pct_chg",
    "换手率": "turnover",
}

CONS_COLUMNS = {
    "代码": "stock_code",
    "名称": "stock_name",
    "最新价": "latest_price",
    "涨跌幅": "pct_chg",
    "成交额": "amount",
}

MARKET_BENCHMARKS = {
    "hs300": {"label": "沪深300", "symbol": "sh000300"},
    "沪深300": {"label": "沪深300", "symbol": "sh000300"},
    "csi_all": {"label": "中证全指", "symbol": "sh000985"},
    "中证全指": {"label": "中证全指", "symbol": "sh000985"},
}

MARKET_INDEXES = {
    "000001": {"index_name": "上证指数", "symbol": "sh000001"},
    "399001": {"index_name": "深证成指", "symbol": "sz399001"},
    "399006": {"index_name": "创业板指", "symbol": "sz399006"},
    "000300": {"index_name": "沪深300", "symbol": "sh000300"},
    "000905": {"index_name": "中证500", "symbol": "sh000905"},
    "000852": {"index_name": "中证1000", "symbol": "sh000852"},
    "000985": {"index_name": "中证全指", "symbol": "sh000985"},
}


def _import_akshare():
    import akshare as ak

    return ak


@contextmanager
def _akshare_network_env() -> Iterator[None]:
    if not settings.bypass_proxy_for_akshare:
        yield
        return
    proxy_keys = ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]
    no_proxy_keys = ["NO_PROXY", "no_proxy"]
    saved = {key: os.environ.get(key) for key in [*proxy_keys, *no_proxy_keys]}
    try:
        for key in proxy_keys:
            os.environ.pop(key, None)
        bypass_hosts = "10jqka.com.cn,q.10jqka.com.cn,d.10jqka.com.cn,finance.qq.com,proxy.finance.qq.com"
        for key in no_proxy_keys:
            previous = saved.get(key)
            os.environ[key] = f"{previous},{bypass_hosts}" if previous else bypass_hosts
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class AKShareClient:
    """Legacy compatibility client for explicit AKShare/THS/EM paths.

    The default confirmed daily data path is Tushare. This client is kept so old
    notebooks/tests can opt in explicitly; it must not be used by default update
    flows.
    """

    def __init__(self, cache_dir: Path | None = None, storage: DuckDBStorage | None = None, use_subprocess_for_ths: bool = True):
        self.cache_dir = Path(cache_dir or settings.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.storage = storage or DuckDBStorage()
        self.storage.init_schema()
        self.cache_ttl_seconds = settings.cache_ttl_seconds
        self.use_subprocess_for_ths = use_subprocess_for_ths

    def _cache_path(self, interface: str, **kwargs: object) -> Path:
        raw = interface + "_" + "_".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
        digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
        return self.cache_dir / f"{interface}_{digest}.pkl"

    def _sleep(self) -> None:
        time.sleep(random.uniform(settings.request_min_sleep, settings.request_max_sleep))

    def _cache_is_fresh(self, path: Path, ttl_seconds: int | float | None) -> bool:
        if not path.exists():
            return False
        if ttl_seconds is None:
            return True
        return (time.time() - path.stat().st_mtime) <= float(ttl_seconds)

    def _read_cache(self, path: Path) -> pd.DataFrame | None:
        if path.exists():
            return pd.read_pickle(path)
        return None

    def _subprocess_env(self) -> dict[str, str]:
        env = os.environ.copy()
        if settings.bypass_proxy_for_akshare:
            for key in ["HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"]:
                env.pop(key, None)
            bypass_hosts = "10jqka.com.cn,q.10jqka.com.cn,d.10jqka.com.cn,finance.qq.com,proxy.finance.qq.com"
            for key in ["NO_PROXY", "no_proxy"]:
                previous = env.get(key)
                env[key] = f"{previous},{bypass_hosts}" if previous else bypass_hosts
        return env

    def _call_akshare_subprocess(self, task: str, **kwargs: object) -> pd.DataFrame:
        code = r'''
import json
import pickle
import sys

import pandas as pd

payload = json.loads(sys.argv[1])
out_path = sys.argv[2]
task = payload["task"]
kwargs = payload["kwargs"]

import akshare as ak
from src.data_sources.ths_helpers import ths_board_constituents, ths_board_hist, ths_board_names


if task == "board_names":
    df = ths_board_names(ak, kwargs["board_type"])
elif task == "board_hist":
    df = ths_board_hist(ak, kwargs["board_type"], kwargs["sector_name"], kwargs["start_date"], kwargs["end_date"])
elif task == "board_constituents":
    df = ths_board_constituents(ak, kwargs["board_type"], kwargs["sector_name"])
else:
    raise ValueError(f"未知 AKShare 子进程任务: {task}")

with open(out_path, "wb") as f:
    pickle.dump(df, f)
'''
        payload = json.dumps({"task": task, "kwargs": kwargs}, ensure_ascii=False)
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as tmp:
            out_path = tmp.name
        try:
            result = subprocess.run(
                [sys.executable, "-c", code, payload, out_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120,
                env=self._subprocess_env(),
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(detail[-2000:] or f"AKShare 子进程退出: {result.returncode}")
            return pd.read_pickle(out_path)
        finally:
            Path(out_path).unlink(missing_ok=True)

    def _default_ttl(self, ttl_seconds: int | float | None) -> int | float | None:
        return self.cache_ttl_seconds if ttl_seconds is None else ttl_seconds

    def _history_ttl(self, end_date: str, ttl_seconds: int | float | None) -> int | float | None:
        if ttl_seconds is not None:
            return ttl_seconds
        return None if normalize_yyyymmdd(end_date) < today_yyyymmdd() else self.cache_ttl_seconds

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=0.8, min=1, max=4), reraise=True)
    def _call_with_retry(self, func: Callable[[], pd.DataFrame]) -> pd.DataFrame:
        self._sleep()
        with _akshare_network_env():
            return func()

    def _fetch(self, interface: str, func: Callable[[], pd.DataFrame], **kwargs: object) -> DataResult:
        cache_today = bool(kwargs.pop("cache_today", True))
        force_refresh = bool(kwargs.pop("force_refresh", False))
        ttl_seconds = kwargs.pop("ttl_seconds", self.cache_ttl_seconds)
        cache_path = self._cache_path(interface, **kwargs)
        if cache_today and not force_refresh and self._cache_is_fresh(cache_path, ttl_seconds):
            df = pd.read_pickle(cache_path)
            with _HEALTH_LOCK:
                self.storage.update_health_success(interface, cache_hit=True)
            return DataResult(df, from_cache=True)
        try:
            df = self._call_with_retry(func)
            if df is None or df.empty:
                raise ValueError(f"{interface} 返回空数据")
            df.to_pickle(cache_path)
            with _HEALTH_LOCK:
                self.storage.update_health_success(interface, cache_hit=False)
            return DataResult(df)
        except Exception as exc:
            logger.exception("AKShare 接口失败: {}", interface)
            with _HEALTH_LOCK:
                self.storage.update_health_failure(interface, exc)
            cached = self._read_cache(cache_path)
            if cached is not None and not cached.empty:
                with _HEALTH_LOCK:
                    self.storage.update_health_success(interface, cache_hit=True, stale=True)
                return DataResult(cached, stale=True, from_cache=True, error=str(exc))
            raise

    @staticmethod
    def _normalize_board_meta(df: pd.DataFrame, board_type: BoardType) -> pd.DataFrame:
        out = df.rename(columns=BOARD_META_COLUMNS).copy()
        if "sector_name" not in out.columns:
            first_text_col = next((c for c in out.columns if out[c].dtype == "object"), None)
            if first_text_col is None:
                raise ValueError("板块名称接口缺少名称列")
            out = out.rename(columns={first_text_col: "sector_name"})
        out["sector_name"] = out["sector_name"].astype(str)
        out["sector_type"] = board_type
        out["sector_id"] = out["sector_type"] + ":" + out["sector_name"]
        out["source"] = settings.default_source
        out["last_update"] = pd.Timestamp.now()
        return out[["sector_id", "sector_type", "sector_name", "source", "last_update"]].drop_duplicates("sector_id")

    @staticmethod
    def _normalize_ohlcv(df: pd.DataFrame, sector_or_stock_id: str | None = None, stock_code: str | None = None) -> pd.DataFrame:
        out = df.rename(columns=OHLCV_COLUMNS).copy()
        if "trade_date" not in out.columns:
            raise ValueError("行情接口缺少日期列")
        out["trade_date"] = to_trade_date(out["trade_date"])
        for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover"]:
            if col not in out.columns:
                out[col] = pd.NA
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out["source"] = settings.default_source
        out["fetched_at"] = pd.Timestamp.now()
        if sector_or_stock_id:
            out["sector_id"] = sector_or_stock_id
            cols = ["sector_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source", "fetched_at"]
        else:
            out["stock_code"] = stock_code
            cols = ["stock_code", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source", "fetched_at"]
        return out[cols].drop_duplicates(cols[:2]).sort_values("trade_date")

    @staticmethod
    def _normalize_constituents(df: pd.DataFrame, sector_id: str) -> pd.DataFrame:
        out = df.rename(columns=CONS_COLUMNS).copy()
        if "stock_code" not in out.columns or "stock_name" not in out.columns:
            raise ValueError("成分股接口缺少代码或名称列")
        out["stock_code"] = out["stock_code"].astype(str).str.zfill(6)
        out["stock_name"] = out["stock_name"].astype(str)
        out["sector_id"] = sector_id
        out["in_sector_date"] = pd.Timestamp.now().date()
        out["source"] = settings.default_source
        out["fetched_at"] = pd.Timestamp.now()
        return out[["sector_id", "stock_code", "stock_name", "in_sector_date", "source", "fetched_at"]].drop_duplicates(["sector_id", "stock_code"])

    @staticmethod
    def _normalize_benchmark_ohlcv(df: pd.DataFrame, benchmark_id: str) -> pd.DataFrame:
        out = df.rename(columns=OHLCV_COLUMNS).copy()
        if "trade_date" not in out.columns:
            raise ValueError("市场基准行情接口缺少日期列")
        out["trade_date"] = to_trade_date(out["trade_date"])
        for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover"]:
            if col not in out.columns:
                out[col] = pd.NA
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out["benchmark_id"] = benchmark_id
        out["source"] = settings.default_source
        out["fetched_at"] = pd.Timestamp.now()
        cols = ["benchmark_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source", "fetched_at"]
        return out[cols].drop_duplicates(["benchmark_id", "trade_date"]).sort_values("trade_date")

    @staticmethod
    def _normalize_market_index_ohlcv(df: pd.DataFrame, index_code: str, index_name: str) -> pd.DataFrame:
        out = df.rename(columns=OHLCV_COLUMNS).copy()
        if "trade_date" not in out.columns:
            raise ValueError("指数行情接口缺少日期列")
        out["trade_date"] = to_trade_date(out["trade_date"])
        for col in ["open", "high", "low", "close", "volume", "amount", "pct_chg"]:
            if col not in out.columns:
                out[col] = pd.NA
            out[col] = pd.to_numeric(out[col], errors="coerce")
        out["index_code"] = index_code
        out["index_name"] = index_name
        out["source"] = settings.default_source
        out["fetched_at"] = pd.Timestamp.now()
        cols = ["index_code", "index_name", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "source", "fetched_at"]
        return out[cols].drop_duplicates(["index_code", "trade_date"]).sort_values("trade_date")

    @staticmethod
    def _is_beijing_stock_code(stock_code: str) -> bool:
        code = str(stock_code).strip().zfill(6)
        return code.startswith(("4", "8", "920"))

    @staticmethod
    def _exchange_for_stock_code(stock_code: str) -> str:
        code = str(stock_code).zfill(6)
        if AKShareClient._is_beijing_stock_code(code):
            return "BJ"
        if code.startswith(("5", "6", "9")):
            return "SH"
        return "SZ"

    @classmethod
    def _normalize_all_a_stock_universe(cls, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        rename_map = {
            "代码": "stock_code",
            "证券代码": "stock_code",
            "股票代码": "stock_code",
            "code": "stock_code",
            "名称": "stock_name",
            "证券简称": "stock_name",
            "股票简称": "stock_name",
            "name": "stock_name",
            "上市日期": "list_date",
            "退市日期": "delist_date",
        }
        out = out.rename(columns=rename_map)
        if "stock_code" not in out.columns or "stock_name" not in out.columns:
            raise ValueError("全 A 股票列表接口缺少代码或名称列")
        out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
        out["stock_name"] = out["stock_name"].astype(str)
        out["exchange"] = out["stock_code"].map(cls._exchange_for_stock_code)
        if "list_status" not in out.columns:
            out["list_status"] = "active"
        if "is_st" not in out.columns:
            out["is_st"] = out["stock_name"].str.contains("ST", case=False, na=False)
        for col in ["list_date", "delist_date"]:
            if col not in out.columns:
                out[col] = pd.NaT
            out[col] = pd.to_datetime(out[col], errors="coerce").dt.date
        out["source"] = settings.default_source
        out["fetched_at"] = pd.Timestamp.now()
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
            ]
        ].drop_duplicates("stock_code")

    @staticmethod
    def _tx_symbol(stock_code: str) -> str:
        code = str(stock_code).strip().zfill(6)
        if AKShareClient._is_beijing_stock_code(code):
            return f"bj{code}"
        if code.startswith(("5", "6", "9")):
            return f"sh{code}"
        return f"sz{code}"

    def board_names(self, board_type: BoardType, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        interface = f"stock_board_{board_type}_name_ths"
        if self.use_subprocess_for_ths:
            func = lambda: self._call_akshare_subprocess("board_names", board_type=board_type)
        else:
            ak = _import_akshare()
            func = lambda: ths_board_names(ak, board_type)
        res = self._fetch(interface, func, force_refresh=force_refresh, ttl_seconds=self._default_ttl(ttl_seconds))
        res.data = res.data.rename(columns={"name": "板块名称", "code": "板块代码"})
        res.data = self._normalize_board_meta(res.data, board_type)
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
        interface = f"stock_board_{board_type}_index_ths"
        if self.use_subprocess_for_ths:
            func = lambda: self._call_akshare_subprocess("board_hist", board_type=board_type, sector_name=sector_name, start_date=start_date, end_date=end_date)
        else:
            ak = _import_akshare()
            func = lambda: ths_board_hist(ak, board_type, sector_name, start_date, end_date)
        res = self._fetch(interface, func, symbol=sector_name, start_date=start_date, end_date=end_date, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end_date, ttl_seconds))
        res.data = self._normalize_ohlcv(res.data, sector_or_stock_id=f"{board_type}:{sector_name}")
        return res

    def board_constituents(self, board_type: BoardType, sector_name: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        interface = f"stock_board_{board_type}_cons_ths"
        def func() -> pd.DataFrame:
            ak = _import_akshare()
            try:
                if self.use_subprocess_for_ths:
                    return self._call_akshare_subprocess("board_constituents", board_type=board_type, sector_name=sector_name)
                return ths_board_constituents(ak, board_type, sector_name)
            except Exception as ths_exc:
                logger.warning("同花顺成分股失败，尝试东方财富 fallback: {} {}", sector_name, ths_exc)
                return em_board_constituents(ak, board_type, sector_name)

        res = self._fetch(interface, func, symbol=sector_name, force_refresh=force_refresh, ttl_seconds=self._default_ttl(ttl_seconds))
        res.data = self._normalize_constituents(res.data, f"{board_type}:{sector_name}")
        return res

    def stock_hist(self, stock_code: str, start_date: str, end_date: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ak = _import_akshare()
        code = str(stock_code).strip().zfill(6)
        if self._is_beijing_stock_code(code):
            interface = "stock_zh_a_daily_bj"
            symbol = f"bj{code}"
            func = lambda: ak.stock_zh_a_daily(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
            res = self._fetch(interface, func, symbol=code, start_date=start_date, end_date=end_date, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end_date, ttl_seconds))
            res.data = self._normalize_ohlcv(res.data, stock_code=code)
            return res

        interface = "stock_zh_a_hist_tx"
        symbol = self._tx_symbol(code)
        func = lambda: ak.stock_zh_a_hist_tx(symbol=symbol, start_date=start_date, end_date=end_date, adjust="qfq")
        res = self._fetch(interface, func, symbol=code, start_date=start_date, end_date=end_date, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end_date, ttl_seconds))
        res.data = self._normalize_ohlcv(res.data, stock_code=code)
        return res

    def market_benchmark_hist(
        self,
        benchmark_id: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        ak = _import_akshare()
        if benchmark_id not in MARKET_BENCHMARKS:
            raise ValueError("market benchmark 仅支持 hs300/沪深300 和 csi_all/中证全指")
        meta = MARKET_BENCHMARKS[benchmark_id]
        canonical_id = "hs300" if meta["label"] == "沪深300" else "csi_all"
        interface = "stock_zh_index_daily_tx"
        func = lambda: ak.stock_zh_index_daily_tx(symbol=meta["symbol"], start_date=start_date, end_date=end_date)
        res = self._fetch(interface, func, benchmark_id=canonical_id, symbol=meta["symbol"], start_date=start_date, end_date=end_date, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end_date, ttl_seconds))
        res.data = self._normalize_benchmark_ohlcv(res.data, canonical_id)
        return res

    index_hist = market_benchmark_hist

    def market_index_list(self) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {"index_code": code, "index_name": meta["index_name"], "symbol": meta["symbol"]}
                for code, meta in MARKET_INDEXES.items()
            ]
        )

    def market_index_hist(
        self,
        index_code: str,
        index_name: str | None = None,
        start_date: str = "20200101",
        end_date: str = "today",
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        ak = _import_akshare()
        code = str(index_code).zfill(6)
        meta = MARKET_INDEXES.get(code, {"index_name": index_name or code, "symbol": f"sh{code}"})
        name = index_name or str(meta["index_name"])
        symbol = str(meta["symbol"])
        start = normalize_yyyymmdd(start_date)
        end = normalize_yyyymmdd(end_date)
        interface = "market_index_daily_tx"
        func = lambda: ak.stock_zh_index_daily_tx(symbol=symbol, start_date=start, end_date=end)
        res = self._fetch(interface, func, index_code=code, symbol=symbol, start_date=start, end_date=end, force_refresh=force_refresh, ttl_seconds=self._history_ttl(end, ttl_seconds))
        res.data = self._normalize_market_index_ohlcv(res.data, code, name)
        return res

    def all_a_stock_universe(self, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ak = _import_akshare()

        def func() -> pd.DataFrame:
            try:
                return ak.stock_info_a_code_name()
            except Exception:
                spot = ak.stock_zh_a_spot_em()
                return spot.rename(columns={"代码": "stock_code", "名称": "stock_name"})[["stock_code", "stock_name"]]

        res = self._fetch(
            "all_a_stock_universe",
            func,
            force_refresh=force_refresh,
            ttl_seconds=self._default_ttl(ttl_seconds),
        )
        res.data = self._normalize_all_a_stock_universe(res.data)
        return res
