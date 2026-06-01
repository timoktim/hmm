from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import settings


HSMM_FEATURE_COLUMNS = [
    "ret_1d",
    "ret_3d",
    "ret_5d",
    "ret_10d",
    "ret_20d",
    "excess_ret_5d",
    "excess_ret_10d",
    "excess_ret_20d",
    "rs_5d",
    "rs_10d",
    "rs_20d",
    "vol_5d",
    "vol_10d",
    "vol_20d",
    "downside_vol_5d",
    "downside_vol_10d",
    "drawdown_5d",
    "drawdown_10d",
    "drawdown_20d",
    "ma5_slope",
    "ma10_slope",
    "ma20_slope",
    "amount_z_5d",
    "amount_z_10d",
    "amount_z_20d",
]


def _compound_equal_weight_return(close: pd.DataFrame, window: int) -> pd.Series:
    daily_ret = close.sort_index().pct_change(fill_method=None)
    equal_weight_daily_ret = daily_ret.mean(axis=1, skipna=True)
    out = (1 + equal_weight_daily_ret).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1
    out.name = f"equal_weight_ret_{window}d"
    return out


def _zscore(values: pd.Series, window: int) -> pd.Series:
    mean = values.rolling(window, min_periods=max(3, window // 2)).mean()
    std = values.rolling(window, min_periods=max(3, window // 2)).std(ddof=0)
    return (values - mean) / std.replace(0, np.nan)


def build_hsmm_features(
    ohlcv: pd.DataFrame,
    feature_version: str = settings.default_feature_version,
    feature_scope_id: str = "all",
    feature_scope_type: str = "all",
) -> pd.DataFrame:
    """Build causal, multi-horizon sector features for the HSMM lifecycle model."""
    if ohlcv.empty:
        return pd.DataFrame()
    required = {"sector_id", "trade_date", "open", "close", "amount"}
    missing = sorted(required - set(ohlcv.columns))
    if missing:
        raise ValueError(f"HSMM feature input missing columns: {missing}")

    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    work = work.sort_values(["sector_id", "trade_date"])
    daily_close = work.pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmarks = {
        window: _compound_equal_weight_return(daily_close, window)
        for window in (5, 10, 20)
    }

    frames: list[pd.DataFrame] = []
    for sector_id, group in work.groupby("sector_id", sort=False):
        g = group.sort_values("trade_date").copy()
        close = pd.to_numeric(g["close"], errors="coerce")
        amount = pd.to_numeric(g["amount"], errors="coerce")
        ret = close.pct_change(fill_method=None)
        downside = ret.where(ret < 0, 0.0)

        for window in (1, 3, 5, 10, 20):
            g[f"ret_{window}d"] = close.pct_change(window, fill_method=None)
        for window in (5, 10, 20):
            bench = benchmarks[window].reindex(g["trade_date"]).to_numpy()
            g[f"excess_ret_{window}d"] = g[f"ret_{window}d"] - bench
            g[f"rs_{window}d"] = g[f"excess_ret_{window}d"]
            g[f"vol_{window}d"] = ret.rolling(window, min_periods=max(3, window // 2)).std(ddof=0) * np.sqrt(window)
            rolling_high = close.rolling(window, min_periods=max(3, window // 2)).max()
            g[f"drawdown_{window}d"] = close / rolling_high - 1
            g[f"ma{window}_slope"] = close.rolling(window, min_periods=max(3, window // 2)).mean().pct_change(max(1, window // 4), fill_method=None)
            g[f"amount_z_{window}d"] = _zscore(amount, window)
        for window in (5, 10):
            g[f"downside_vol_{window}d"] = downside.rolling(window, min_periods=max(3, window // 2)).std(ddof=0) * np.sqrt(window)

        g["feature_version"] = feature_version
        g["feature_scope_id"] = feature_scope_id
        g["feature_scope_type"] = feature_scope_type
        frames.append(g[["sector_id", "trade_date", *HSMM_FEATURE_COLUMNS, "feature_version", "feature_scope_id", "feature_scope_type"]])

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    out.replace([np.inf, -np.inf], np.nan, inplace=True)
    return out
