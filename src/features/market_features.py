from __future__ import annotations

import numpy as np
import pandas as pd

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage


MARKET_FEATURE_VERSION = "market_v1"
INDEX_ALIASES = {
    "000001": "sse",
    "399001": "szse",
    "399006": "chinext",
    "000300": "hs300",
    "000905": "zz500",
    "000852": "zz1000",
    "000985": "csi_all",
}
BASE_MARKET_FEATURE_COLUMNS = [
    "hs300_ret_20d",
    "zz500_ret_20d",
    "zz1000_ret_20d",
    "hs300_vol_20d",
    "zz500_vol_20d",
    "zz1000_vol_20d",
    "hs300_drawdown_20d",
    "zz1000_drawdown_20d",
    "small_vs_large_20d",
    "cross_index_dispersion_20d",
]
BREADTH_FEATURE_COLUMNS = ["up_ratio", "above_ma20_ratio", "amount_z_20d"]
COVERAGE_MODE_FULL_MARKET = "full_market"
COVERAGE_MODE_LOCAL_SAMPLE = "local_sample"
COVERAGE_MODE_UNKNOWN = "unknown"
COVERAGE_MODES = {COVERAGE_MODE_FULL_MARKET, COVERAGE_MODE_LOCAL_SAMPLE, COVERAGE_MODE_UNKNOWN}


def _index_features(df: pd.DataFrame, alias: str) -> pd.DataFrame:
    g = df.sort_values("trade_date").copy()
    g["trade_date"] = pd.to_datetime(g["trade_date"])
    close = pd.to_numeric(g["close"], errors="coerce")
    amount = pd.to_numeric(g["amount"], errors="coerce")
    ret = close.pct_change()
    ma20 = close.rolling(20, min_periods=10).mean()
    high20 = close.rolling(20, min_periods=10).max()
    amount_mean = amount.rolling(20, min_periods=10).mean()
    amount_std = amount.rolling(20, min_periods=10).std(ddof=0)
    return pd.DataFrame(
        {
            "trade_date": g["trade_date"],
            f"{alias}_close": close,
            f"{alias}_ret_1d": ret,
            f"{alias}_ret_5d": close.pct_change(5),
            f"{alias}_ret_20d": close.pct_change(20),
            f"{alias}_vol_20d": ret.rolling(20, min_periods=10).std(ddof=0) * np.sqrt(20),
            f"{alias}_drawdown_20d": close / high20 - 1,
            f"{alias}_ma20_slope": ma20 / ma20.shift(5) - 1,
            f"{alias}_amount_z_20d": (amount - amount_mean) / amount_std.replace(0, np.nan),
        }
    )


def available_market_feature_columns(features: pd.DataFrame, use_breadth: bool = True) -> list[str]:
    suffixes = ("_ret_20d", "_vol_20d", "_drawdown_20d", "_ma20_slope", "_amount_z_20d")
    candidates = [
        col
        for col in features.columns
        if col in BASE_MARKET_FEATURE_COLUMNS or col.endswith(suffixes)
    ]
    if use_breadth:
        candidates += [c for c in BREADTH_FEATURE_COLUMNS if c in features.columns]
    seen: set[str] = set()
    out: list[str] = []
    for col in candidates:
        if col in seen:
            continue
        seen.add(col)
        if col in features.columns and features[col].notna().sum() >= 20:
            out.append(col)
    return out


def normalize_coverage_mode(value: object) -> str:
    text = "" if pd.isna(value) else str(value).strip()
    if text in {COVERAGE_MODE_FULL_MARKET, COVERAGE_MODE_LOCAL_SAMPLE}:
        return text
    return COVERAGE_MODE_UNKNOWN


def normalize_breadth_coverage_columns(breadth: pd.DataFrame) -> pd.DataFrame:
    if breadth.empty:
        return breadth.copy()
    out = breadth.copy()
    if "coverage_mode" not in out.columns:
        if "breadth_mode" in out.columns:
            out["coverage_mode"] = out["breadth_mode"].map(normalize_coverage_mode)
        else:
            out["coverage_mode"] = COVERAGE_MODE_UNKNOWN
    else:
        out["coverage_mode"] = out["coverage_mode"].map(normalize_coverage_mode)

    legacy_ratio = pd.to_numeric(out.get("coverage_ratio", pd.Series(pd.NA, index=out.index)), errors="coerce")
    if "full_market_coverage_ratio" not in out.columns:
        out["full_market_coverage_ratio"] = pd.NA
    out["full_market_coverage_ratio"] = pd.to_numeric(out["full_market_coverage_ratio"], errors="coerce")
    full_mask = out["coverage_mode"].eq(COVERAGE_MODE_FULL_MARKET) & out["full_market_coverage_ratio"].isna()
    out.loc[full_mask, "full_market_coverage_ratio"] = legacy_ratio.loc[full_mask]

    if "local_sample_internal_coverage" not in out.columns:
        out["local_sample_internal_coverage"] = pd.NA
    out["local_sample_internal_coverage"] = pd.to_numeric(out["local_sample_internal_coverage"], errors="coerce")
    local_mask = out["coverage_mode"].eq(COVERAGE_MODE_LOCAL_SAMPLE) & out["local_sample_internal_coverage"].isna()
    if local_mask.any():
        total = pd.to_numeric(out.get("total_count", pd.Series(pd.NA, index=out.index)), errors="coerce")
        effective = pd.to_numeric(out.get("effective_count", pd.Series(pd.NA, index=out.index)), errors="coerce")
        derived_local = effective / total.replace(0, pd.NA)
        out.loc[local_mask, "local_sample_internal_coverage"] = legacy_ratio.where(legacy_ratio.notna(), derived_local).loc[local_mask]

    coverage_level = out.get("coverage_level", pd.Series("", index=out.index)).fillna("").astype(str)
    out["full_market_coverage_usable"] = (
        out["coverage_mode"].eq(COVERAGE_MODE_FULL_MARKET)
        & coverage_level.eq("full_market")
        & pd.to_numeric(out["full_market_coverage_ratio"], errors="coerce").ge(0.8)
    )
    return out


def build_market_features(
    storage: DuckDBStorage | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    feature_version: str = MARKET_FEATURE_VERSION,
    breadth_mode: str | None = None,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    indices = storage.read_df(
        """
        SELECT index_code, index_name, trade_date, close, amount
        FROM market_index_ohlcv
        ORDER BY index_code, trade_date
        """
    )
    if indices.empty:
        return pd.DataFrame()
    if start_date:
        indices = indices[pd.to_datetime(indices["trade_date"]) >= pd.to_datetime(start_date)]
    if end_date:
        indices = indices[pd.to_datetime(indices["trade_date"]) <= pd.to_datetime(end_date)]
    frames: list[pd.DataFrame] = []
    ret20_frames: list[pd.Series] = []
    for code, alias in INDEX_ALIASES.items():
        g = indices[indices["index_code"].astype(str).str.zfill(6) == code]
        if g.empty:
            continue
        feat = _index_features(g, alias)
        frames.append(feat)
        ret20_frames.append(feat.set_index("trade_date")[f"{alias}_ret_20d"])
    if not frames:
        available = indices["index_code"].astype(str).str.zfill(6).drop_duplicates().tolist()
        for code in available:
            g = indices[indices["index_code"].astype(str).str.zfill(6) == code]
            if g.empty:
                continue
            alias = f"idx_{code}"
            feat = _index_features(g, alias)
            frames.append(feat)
            ret20_frames.append(feat.set_index("trade_date")[f"{alias}_ret_20d"])
        if not frames:
            return pd.DataFrame()
    features = frames[0]
    for frame in frames[1:]:
        features = features.merge(frame, on="trade_date", how="outer")
    if "zz1000_ret_20d" in features.columns and "hs300_ret_20d" in features.columns:
        features["small_vs_large_20d"] = features["zz1000_ret_20d"] - features["hs300_ret_20d"]
    if ret20_frames:
        ret20 = pd.concat(ret20_frames, axis=1)
        features = features.merge(ret20.std(axis=1, ddof=0).rename("cross_index_dispersion_20d").reset_index(), on="trade_date", how="left")
    breadth = pd.DataFrame()
    if breadth_mode:
        breadth = storage.read_df(
            """
            SELECT *
            FROM market_breadth_daily
            WHERE breadth_mode = ?
            ORDER BY trade_date
            """,
            [breadth_mode],
        )
    if not breadth.empty:
        breadth["trade_date"] = pd.to_datetime(breadth["trade_date"])
        breadth = normalize_breadth_coverage_columns(breadth)
        breadth = breadth.drop_duplicates(subset=["trade_date"], keep="last")
        if breadth_mode == COVERAGE_MODE_FULL_MARKET:
            unusable = ~breadth["full_market_coverage_usable"].fillna(False)
            for column in BREADTH_FEATURE_COLUMNS:
                if column in breadth.columns:
                    breadth.loc[unusable, column] = pd.NA
        breadth_columns = [
            "trade_date",
            "up_ratio",
            "above_ma20_ratio",
            "amount_z_20d",
            "limit_up_count",
            "limit_down_count",
            "total_count",
            "effective_count",
            "expected_count",
            "coverage_mode",
            "local_sample_internal_coverage",
            "full_market_coverage_ratio",
            "full_market_coverage_usable",
            "coverage_level",
            "coverage_warning",
        ]
        breadth_columns = [column for column in breadth_columns if column in breadth.columns]
        features = features.merge(
            breadth[breadth_columns],
            on="trade_date",
            how="left",
        )
    features["feature_version"] = feature_version or settings.default_feature_version
    features = features.sort_values("trade_date").reset_index(drop=True)
    return features


def latest_market_index_status(storage: DuckDBStorage | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    features = build_market_features(storage)
    if features.empty:
        return pd.DataFrame()
    indices = storage.read_df("SELECT DISTINCT index_code, index_name FROM market_index_ohlcv")
    rows: list[dict[str, object]] = []
    for code, alias in INDEX_ALIASES.items():
        if f"{alias}_close" not in features.columns:
            continue
        valid = features.dropna(subset=[f"{alias}_close"])
        if valid.empty:
            continue
        row = valid.iloc[-1]
        name_df = indices[indices["index_code"].astype(str).str.zfill(6) == code]
        rows.append(
            {
                "index_code": code,
                "index_name": code if name_df.empty else str(name_df.iloc[0]["index_name"]),
                "latest_close": row.get(f"{alias}_close"),
                "ret_20d": row.get(f"{alias}_ret_20d"),
                "vol_20d": row.get(f"{alias}_vol_20d"),
                "drawdown_20d": row.get(f"{alias}_drawdown_20d"),
                "ma20_slope": row.get(f"{alias}_ma20_slope"),
                "amount_z_20d": row.get(f"{alias}_amount_z_20d"),
            }
        )
    return pd.DataFrame(rows)
