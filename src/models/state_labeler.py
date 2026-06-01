from __future__ import annotations

import pandas as pd


def label_states(feature_df: pd.DataFrame, state_col: str = "state_id") -> dict[int, str]:
    if feature_df.empty:
        return {}
    stats = feature_df.groupby(state_col).agg(
        ret_20d=("ret_20d", "mean"),
        rs_20d=("rs_20d", "mean"),
        ma20_slope=("ma20_slope", "mean"),
        vol_20d=("vol_20d", "mean"),
        drawdown_20d=("drawdown_20d", "mean"),
    )
    stats = stats.fillna(0)
    trend_score = stats["ret_20d"] + stats["rs_20d"] + stats["ma20_slope"] - 0.25 * stats["vol_20d"]
    risk_score = -stats["ret_20d"] - stats["rs_20d"] - stats["drawdown_20d"] + 0.5 * stats["vol_20d"]
    labels = {int(i): "Neutral" for i in stats.index}
    trend_state = int(trend_score.idxmax())
    risk_state = int(risk_score.idxmax())
    labels[trend_state] = "TrendUp"
    if risk_state == trend_state and len(stats) > 1:
        risk_state = int(risk_score.drop(index=trend_state).idxmax())
    labels[risk_state] = "RiskOff"
    return labels


def summarize_state_history(feature_with_states: pd.DataFrame) -> pd.DataFrame:
    if feature_with_states.empty:
        return pd.DataFrame()
    return feature_with_states.groupby("state_label").agg(
        sample_count=("state_id", "size"),
        avg_ret_20d=("ret_20d", "mean"),
        avg_vol_20d=("vol_20d", "mean"),
        avg_drawdown_20d=("drawdown_20d", "mean"),
    ).reset_index()

