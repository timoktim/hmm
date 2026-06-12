from __future__ import annotations

import math

import pandas as pd

from src.evaluation.stage03v_logistic_hazard import (
    date_aware_sample_weights,
    default_policy,
    fit_logistic_model,
)


def _rows(labels: list[bool], dates: list[str]) -> pd.DataFrame:
    rows = []
    for idx, (label, date) in enumerate(zip(labels, dates, strict=True)):
        rows.append(
            {
                "entity_id": f"industry:{idx}",
                "trade_date": pd.Timestamp(date),
                "feature_asof_date": pd.Timestamp(date) - pd.Timedelta(days=1),
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "event_label": label,
                "rolling_close_to_close_vol_20": 0.01 + 0.01 * int(label) + idx * 0.001,
            }
        )
    return pd.DataFrame(rows)


def test_date_aware_sample_weights_bound_each_trade_date_total() -> None:
    train = _rows(
        [False, True, False, True],
        ["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-02"],
    )

    weights = date_aware_sample_weights(train)
    by_date = train.assign(weight=weights).groupby("trade_date")["weight"].sum()

    assert math.isclose(float(by_date.loc[pd.Timestamp("2026-01-01")]), 1.0)
    assert math.isclose(float(by_date.loc[pd.Timestamp("2026-01-02")]), 1.0)


def test_logistic_fit_exposes_date_aware_weighting_status() -> None:
    train = _rows(
        [False, True, False, True, False, True],
        ["2026-01-01", "2026-01-01", "2026-01-01", "2026-01-02", "2026-01-03", "2026-01-03"],
    )
    validation = _rows(
        [False, True, False, True],
        ["2026-01-04", "2026-01-05", "2026-01-06", "2026-01-07"],
    )

    result = fit_logistic_model(train, validation, ["rolling_close_to_close_vol_20"], default_policy())

    assert result["status"] == "fitted"
    assert result["date_aware_weighting_status"] == "implemented"
    assert result["date_weight_min"] < result["date_weight_max"]
