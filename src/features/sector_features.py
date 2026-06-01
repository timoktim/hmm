from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import universe_sector_ids


FEATURE_COLUMNS = [
    "ret_1d",
    "ret_5d",
    "ret_20d",
    "vol_20d",
    "amount_z_20d",
    "rs_20d",
    "drawdown_20d",
    "ma20_slope",
]
STRUCTURE_FEATURE_COLUMNS = [
    "gap_1d",
    "intraday_ret",
    "amount_shock_z",
]


def feature_scope_for_universe(
    storage: DuckDBStorage | None = None,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
) -> tuple[str, str]:
    if not universe_id:
        return ("all", "all")
    storage = storage or DuckDBStorage()
    sector_ids = universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets)
    custom_count = sum(str(sector_id).startswith("custom:") for sector_id in sector_ids)
    board_count = len(sector_ids) - custom_count
    if custom_count and not board_count:
        scope_type = "custom_only"
    elif custom_count and board_count:
        scope_type = "mixed_universe"
    else:
        scope_type = "universe"
    custom_flag = "with_custom" if include_custom_baskets else "no_custom"
    return (f"{scope_type}:{universe_id}:{custom_flag}", scope_type)


def winsorize_features(df: pd.DataFrame, columns: list[str] = FEATURE_COLUMNS, lower: float = 0.01, upper: float = 0.99) -> pd.DataFrame:
    out = df.copy()
    for col in columns:
        if col in out.columns and out[col].notna().sum() > 10:
            lo, hi = out[col].quantile([lower, upper])
            out[col] = out[col].clip(lo, hi)
    return out


def equal_weight_benchmark_ret20_from_close(daily_close: pd.DataFrame, window: int = 20) -> pd.Series:
    close = daily_close.copy()
    close.index = pd.to_datetime(close.index)
    daily_ret = close.sort_index().pct_change(fill_method=None)
    equal_weight_daily_ret = daily_ret.mean(axis=1, skipna=True)
    benchmark_ret = (1 + equal_weight_daily_ret).rolling(window, min_periods=window).apply(np.prod, raw=True) - 1
    benchmark_ret.name = f"equal_weight_ret_{window}d"
    return benchmark_ret


def add_sector_features(
    ohlcv: pd.DataFrame,
    benchmark_ret20: pd.Series | None = None,
    feature_version: str = settings.default_feature_version,
    apply_winsorize: bool = False,
    feature_scope_id: str = "all",
    feature_scope_type: str = "all",
) -> pd.DataFrame:
    df = ohlcv.sort_values(["sector_id", "trade_date"]).copy()
    frames: list[pd.DataFrame] = []
    if benchmark_ret20 is not None:
        benchmark_ret20 = benchmark_ret20.copy()
        benchmark_ret20.index = pd.to_datetime(benchmark_ret20.index)

    for sector_id, g in df.groupby("sector_id", sort=False):
        g = g.sort_values("trade_date").copy()
        g["trade_date"] = pd.to_datetime(g["trade_date"])
        ret = g["close"].pct_change()
        amount_mean = g["amount"].rolling(20, min_periods=10).mean()
        amount_std = g["amount"].rolling(20, min_periods=10).std(ddof=0)
        ma20 = g["close"].rolling(20, min_periods=10).mean()
        rolling_high = g["close"].rolling(20, min_periods=10).max()
        prev_close = g["close"].shift(1)

        g["ret_1d"] = ret
        g["ret_5d"] = g["close"].pct_change(5)
        g["ret_20d"] = g["close"].pct_change(20)
        g["vol_20d"] = ret.rolling(20, min_periods=10).std(ddof=0) * np.sqrt(20)
        g["amount_z_20d"] = (g["amount"] - amount_mean) / amount_std.replace(0, np.nan)
        if benchmark_ret20 is None:
            g["rs_20d"] = g["ret_20d"]
        else:
            aligned = benchmark_ret20.reindex(g["trade_date"]).to_numpy()
            g["rs_20d"] = g["ret_20d"] - aligned
        g["drawdown_20d"] = g["close"] / rolling_high - 1
        g["ma20_slope"] = ma20 / ma20.shift(5) - 1
        g["gap_1d"] = g["open"] / prev_close - 1
        g["intraday_ret"] = g["close"] / g["open"] - 1
        g["amount_shock_z"] = g["amount_z_20d"]
        g["feature_version"] = feature_version
        g["feature_scope_id"] = feature_scope_id
        g["feature_scope_type"] = feature_scope_type
        frames.append(g[["sector_id", "trade_date", *FEATURE_COLUMNS, *STRUCTURE_FEATURE_COLUMNS, "feature_version", "feature_scope_id", "feature_scope_type"]])

    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if apply_winsorize:
        out = winsorize_features(out)
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    return out


def build_sector_features_from_storage(
    storage: DuckDBStorage | None = None,
    feature_version: str = settings.default_feature_version,
    apply_winsorize: bool = False,
    store: bool = True,
) -> pd.DataFrame:
    """Legacy all-market feature builder.

    Model training and walk-forward paths keep raw features here and apply
    train-window winsorization/scaling through ``FeaturePreprocessor``.
    """
    storage = storage or DuckDBStorage()
    ohlcv = storage.read_df(
        """
        SELECT sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover
        FROM sector_ohlcv
        ORDER BY sector_id, trade_date
        """
    )
    if ohlcv.empty:
        return pd.DataFrame()
    tmp = ohlcv.copy()
    tmp["trade_date"] = pd.to_datetime(tmp["trade_date"])
    daily_close = tmp.pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmark_ret20 = equal_weight_benchmark_ret20_from_close(daily_close)
    features = add_sector_features(
        ohlcv,
        benchmark_ret20=benchmark_ret20,
        feature_version=feature_version,
        apply_winsorize=apply_winsorize,
        feature_scope_id="all",
        feature_scope_type="all",
    )
    if store:
        storage.upsert_df("sector_features", features, ["sector_id", "trade_date", "feature_version", "feature_scope_id"])
    return features
