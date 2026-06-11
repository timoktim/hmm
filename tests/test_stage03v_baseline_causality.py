from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_baseline_diagnostics import (
    build_price_baseline_features,
    detect_feature_asof_violations,
    validate_baseline_input_columns,
)


def _ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {
            "entity_id": ["industry:A"] * len(closes),
            "trade_date": dates,
            "open": closes,
            "high": [value * 1.02 for value in closes],
            "low": [value * 0.98 for value in closes],
            "close": closes,
        }
    )


def test_rolling_volatility_uses_no_future_price() -> None:
    full = _ohlcv([100, 101, 102, 103, 104, 105, 50])
    truncated = _ohlcv([100, 101, 102, 103, 104, 105])

    full_features, _ = build_price_baseline_features(full)
    truncated_features, _ = build_price_baseline_features(truncated)

    full_score = full_features.loc[
        full_features["trade_date"].eq(pd.Timestamp("2026-01-06")),
        "rolling_close_to_close_vol_20",
    ].iloc[0]
    truncated_score = truncated_features.loc[
        truncated_features["trade_date"].eq(pd.Timestamp("2026-01-06")),
        "rolling_close_to_close_vol_20",
    ].iloc[0]

    assert full_score == truncated_score


def test_range_based_volatility_requires_ohlc_columns() -> None:
    close_only = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 6,
            "trade_date": pd.date_range("2026-01-01", periods=6, freq="D"),
            "close": [100, 101, 102, 103, 104, 105],
        }
    )

    _, availability = build_price_baseline_features(close_only)

    assert availability["range_based_availability_status"].startswith("range_based_unavailable")


def test_drawdown_baseline_uses_no_future_price() -> None:
    full = _ohlcv([100, 105, 104, 103, 102, 60])
    truncated = _ohlcv([100, 105, 104, 103, 102])

    full_features, _ = build_price_baseline_features(full)
    truncated_features, _ = build_price_baseline_features(truncated)

    full_score = full_features.loc[
        full_features["trade_date"].eq(pd.Timestamp("2026-01-05")),
        "rolling_distance_from_high_20",
    ].iloc[0]
    truncated_score = truncated_features.loc[
        truncated_features["trade_date"].eq(pd.Timestamp("2026-01-05")),
        "rolling_distance_from_high_20",
    ].iloc[0]

    assert full_score == truncated_score


def test_feature_asof_date_violations_are_detected() -> None:
    rows = pd.DataFrame(
        [
            {"trade_date": "2026-01-02", "feature_asof_date": "2026-01-02"},
            {"trade_date": "2026-01-02", "feature_asof_date": "2026-01-03"},
        ]
    )

    assert detect_feature_asof_violations(rows) == 1


def test_target_namespace_columns_are_rejected_as_baseline_inputs() -> None:
    result = validate_baseline_input_columns(["trade_date", "event_label", "target_observation_end_date"])

    assert result["target_namespace_input_violation_count"] == 2
    assert "event_label" in result["target_namespace_input_violations"]


def test_future_columns_are_rejected_as_baseline_inputs() -> None:
    result = validate_baseline_input_columns(["close", "future_mae", "future_custom_proxy"])

    assert result["future_column_input_violation_count"] == 2
    assert "future_mae" in result["future_column_input_violations"]
