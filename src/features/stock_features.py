from __future__ import annotations

import numpy as np
import pandas as pd


def add_a_share_limit_flags(stock_ohlcv: pd.DataFrame) -> pd.DataFrame:
    if stock_ohlcv.empty:
        return stock_ohlcv
    out = stock_ohlcv.sort_values(["stock_code", "trade_date"]).copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    for col in ["open", "high", "low", "close", "amount", "volume"]:
        if col not in out.columns:
            out[col] = np.nan
        out[col] = pd.to_numeric(out[col], errors="coerce")
    prev_close = out.groupby("stock_code")["close"].shift(1)
    out["gap_1d"] = out["open"] / prev_close - 1
    out["intraday_ret"] = out["close"] / out["open"] - 1
    daily_ret = out.groupby("stock_code")["close"].pct_change()
    out["is_limit_up"] = daily_ret >= 0.098
    out["is_limit_down"] = daily_ret <= -0.098
    out["is_one_word_limit"] = out["is_limit_up"] & (out["open"] == out["high"]) & (out["high"] == out["low"]) & (out["low"] == out["close"])
    out["is_suspended_or_missing"] = out["close"].isna() | (out["volume"].fillna(0) <= 0)

    def consecutive(mask: pd.Series) -> pd.Series:
        group = (~mask.fillna(False)).cumsum()
        return mask.fillna(False).groupby(group).cumsum().astype(int)

    out["consecutive_limit_up_days"] = out.groupby("stock_code", group_keys=False)["is_limit_up"].apply(consecutive)
    out["consecutive_limit_down_days"] = out.groupby("stock_code", group_keys=False)["is_limit_down"].apply(consecutive)
    return out


def stock_feature_frame(stock_ohlcv: pd.DataFrame, sector_close: pd.DataFrame, benchmark_close: pd.Series | None = None) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    stock_ohlcv = add_a_share_limit_flags(stock_ohlcv)
    sector_ret20 = sector_close.set_index(pd.to_datetime(sector_close["trade_date"]))["close"].pct_change(20)
    if benchmark_close is not None:
        benchmark_ret20 = benchmark_close.copy()
        benchmark_ret20.index = pd.to_datetime(benchmark_ret20.index)
        benchmark_ret20 = benchmark_ret20.pct_change(20)
    else:
        benchmark_ret20 = None

    for code, g in stock_ohlcv.groupby("stock_code", sort=False):
        g = g.sort_values("trade_date").copy()
        g["trade_date"] = pd.to_datetime(g["trade_date"])
        ret = g["close"].pct_change()
        ret20 = g["close"].pct_change(20)
        ma20 = g["close"].rolling(20, min_periods=10).mean()
        amount_mean = g["amount"].rolling(20, min_periods=10).mean()
        amount_std = g["amount"].rolling(20, min_periods=10).std(ddof=0)
        high20 = g["close"].rolling(20, min_periods=10).max()
        g["ret_20d"] = ret20
        g["rs_vs_sector_20d"] = ret20 - sector_ret20.reindex(g["trade_date"]).to_numpy()
        if benchmark_ret20 is None:
            g["rs_vs_index_20d"] = np.nan
        else:
            g["rs_vs_index_20d"] = ret20 - benchmark_ret20.reindex(g["trade_date"]).to_numpy()
        g["amount_z_20d"] = (g["amount"] - amount_mean) / amount_std.replace(0, np.nan)
        g["vol_20d"] = ret.rolling(20, min_periods=10).std(ddof=0) * np.sqrt(20)
        g["drawdown_20d"] = g["close"] / high20 - 1
        g["ma20"] = ma20
        g["ma20_slope"] = ma20 / ma20.shift(5) - 1
        g["trend_quality"] = ((g["close"] > ma20).astype(float) + (g["ma20_slope"] > 0).astype(float)) / 2
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
