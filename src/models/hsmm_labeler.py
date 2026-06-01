from __future__ import annotations

import numpy as np
import pandas as pd


def _safe_z(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    std = s.std(ddof=0)
    if not np.isfinite(std) or std == 0:
        return pd.Series(0.0, index=s.index)
    return (s - s.mean()) / std


def label_hsmm_states(labeled_features: pd.DataFrame) -> dict[int, str]:
    """Assign stable lifecycle labels from contemporaneous feature profiles only."""
    if labeled_features.empty or "state_id" not in labeled_features.columns:
        return {}
    profile = labeled_features.groupby("state_id").mean(numeric_only=True)
    if profile.empty:
        return {}

    def col(name: str) -> pd.Series:
        return profile[name] if name in profile.columns else pd.Series(0.0, index=profile.index)

    trend_score = (
        _safe_z(col("excess_ret_20d"))
        + _safe_z(col("excess_ret_10d"))
        + _safe_z(col("ma20_slope"))
        - _safe_z(col("drawdown_20d").abs())
    )
    stress_score = (
        -_safe_z(col("excess_ret_20d"))
        - _safe_z(col("excess_ret_5d"))
        + _safe_z(col("drawdown_20d").abs())
        + _safe_z(col("downside_vol_10d"))
    )
    repair_score = (
        _safe_z(col("excess_ret_5d"))
        + _safe_z(col("ret_5d"))
        + 0.5 * _safe_z(col("drawdown_20d").abs())
        + 0.25 * _safe_z(col("vol_20d"))
    )
    compression_score = -_safe_z(col("vol_20d").abs()) - _safe_z(col("amount_z_20d").abs())

    labels: dict[int, str] = {}
    remaining = set(int(x) for x in profile.index)

    def assign(label: str, score: pd.Series) -> None:
        nonlocal remaining
        candidates = [idx for idx in score.sort_values(ascending=False).index if int(idx) in remaining]
        if candidates:
            state_id = int(candidates[0])
            labels[state_id] = label
            remaining.remove(state_id)

    assign("Trend", trend_score)
    assign("Stress", stress_score)
    if len(profile) >= 4:
        assign("Repair", repair_score)
    if len(profile) >= 5:
        assign("Compression", compression_score)
    for state_id in sorted(remaining):
        labels[int(state_id)] = "Neutral"
    return labels
