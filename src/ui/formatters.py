from __future__ import annotations

import json
from collections.abc import Iterable

import pandas as pd

from src.ui.help_texts import display_state_label


SECTOR_NEXT_STATE_KEYS = {
    "TrendUp": "next_prob_trend_up",
    "Neutral": "next_prob_neutral",
    "RiskOff": "next_prob_risk_off",
}
MARKET_NEXT_STATE_KEYS = {
    "RiskOn": "next_prob_risk_on",
    "Neutral": "next_prob_neutral",
    "RiskOff": "next_prob_risk_off",
}


def format_probability(p: object, decimals: int = 2, tiny_threshold: float = 0.0001) -> str:
    value = pd.to_numeric(pd.Series([p]), errors="coerce").iloc[0]
    if pd.isna(value):
        return "无"
    value = float(value)
    if value <= 0:
        return f"{0:.{decimals}%}"
    if 0 < value < tiny_threshold:
        return "<0.01%"
    if value > 1 - tiny_threshold:
        return "99.99%+"
    return f"{value:.{decimals}%}"


def format_probability_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in columns:
        if col in out.columns:
            out[col] = out[col].map(format_probability)
    return out


def parse_next_state_probs(next_state_probs_json: object, model_type: str = "sector") -> dict[str, float]:
    mapping = MARKET_NEXT_STATE_KEYS if model_type == "market" else SECTOR_NEXT_STATE_KEYS
    empty = {key: 0.0 for key in mapping.values()}
    if next_state_probs_json is None:
        return empty
    try:
        if isinstance(next_state_probs_json, dict):
            parsed = next_state_probs_json
        elif pd.isna(next_state_probs_json):
            return empty
        else:
            parsed = json.loads(str(next_state_probs_json))
    except Exception:
        return empty
    out = empty.copy()
    for state_label, column in mapping.items():
        out[column] = float(parsed.get(state_label, 0.0) or 0.0)
    return out


def add_next_state_probability_columns(df: pd.DataFrame, model_type: str = "sector") -> pd.DataFrame:
    if df is None or df.empty or "next_state_probs_json" not in df.columns:
        return df
    out = df.copy()
    parsed = out["next_state_probs_json"].map(lambda value: parse_next_state_probs(value, model_type=model_type))
    for column in (MARKET_NEXT_STATE_KEYS if model_type == "market" else SECTOR_NEXT_STATE_KEYS).values():
        out[column] = parsed.map(lambda row: row.get(column, 0.0))
    return out.drop(columns=["next_state_probs_json"])


def next_state_probability_display(probabilities: dict[str, float], model_type: str = "sector") -> list[tuple[str, str]]:
    labels = ["RiskOn", "Neutral", "RiskOff"] if model_type == "market" else ["TrendUp", "Neutral", "RiskOff"]
    mapping = MARKET_NEXT_STATE_KEYS if model_type == "market" else SECTOR_NEXT_STATE_KEYS
    return [(display_state_label(label), format_probability(probabilities.get(mapping[label], 0.0))) for label in labels]
