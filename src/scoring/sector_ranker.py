from __future__ import annotations

import numpy as np
import pandas as pd


def _series_or_default(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce")
    return pd.Series(default, index=df.index, dtype="float64")


def _norm(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / std).clip(-3, 3)


def _safe_float(value: object, default: float = 0.0) -> float:
    if value is None or pd.isna(value):
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def rank_sectors(df: pd.DataFrame, market_state_label: str | None = None) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["prob_trend_up"] = _series_or_default(out, "prob_trend_up")
    out["prob_neutral"] = _series_or_default(out, "prob_neutral")
    out["prob_risk_off"] = _series_or_default(out, "prob_risk_off")
    out["normalized_rs_20d"] = _norm(_series_or_default(out, "rs_20d"))
    out["normalized_ret_20d"] = _norm(_series_or_default(out, "ret_20d"))
    out["normalized_amount_z_20d"] = _norm(_series_or_default(out, "amount_z_20d"))
    out["normalized_vol_20d"] = _norm(_series_or_default(out, "vol_20d"))
    out["sector_score"] = (
        0.35 * out["prob_trend_up"].fillna(0)
        + 0.25 * out["normalized_rs_20d"]
        + 0.15 * out["normalized_ret_20d"]
        + 0.15 * out["normalized_amount_z_20d"]
        - 0.10 * out["normalized_vol_20d"]
        - 0.10 * out["prob_risk_off"].fillna(0)
    )
    out["sector_tag"] = out.apply(tag_sector, axis=1)
    return out.sort_values("sector_score", ascending=False)


def tag_sector(row: pd.Series) -> str:
    prob_trend = _safe_float(row.get("prob_trend_up", 0))
    prob_neutral = _safe_float(row.get("prob_neutral", 0))
    prob_risk = _safe_float(row.get("prob_risk_off", 0))
    rs = _safe_float(row.get("rs_20d", 0))
    amount_z = _safe_float(row.get("amount_z_20d", 0))
    ret20 = _safe_float(row.get("ret_20d", 0))
    vol20 = _safe_float(row.get("vol_20d", 0))
    dd = _safe_float(row.get("drawdown_20d", 0))
    if prob_risk >= 0.45 or dd <= -0.18 or vol20 >= 0.20:
        return "风险回避"
    if prob_trend >= 0.60 and amount_z > 1.5 and ret20 > 0.20 and vol20 > 0.12:
        return "趋势但过热"
    if prob_trend >= 0.60 and prob_risk <= 0.25 and rs > 0:
        return "强趋势观察"
    if prob_neutral >= max(prob_trend, prob_risk) and prob_trend < 0.55:
        return "中性等待"
    return "观察"
