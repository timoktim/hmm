from __future__ import annotations

import math

import pandas as pd

from src.evaluation.stage03v_risk_target_dataset import (
    SliceSpec,
    _detect_silent_break_entities,
    compute_path_metrics,
    compute_path_target_rows,
)


SLICE = SliceSpec(
    horizon=2,
    threshold_value=0.05,
    threshold_type="fixed",
    source_target_kind="sw2021_l2_downside_event",
    feasibility_verdict="eligible",
    target_usage="eligible",
)


def test_path_metrics_mae_mdd_future_return_and_volatility_are_correct() -> None:
    metrics = compute_path_metrics([100.0, 110.0, 90.0, 95.0], base_index=0, horizon=3)

    assert metrics is not None
    assert round(metrics["future_return"], 6) == -0.05
    assert round(metrics["future_mae"], 6) == -0.10
    assert round(metrics["future_mdd"], 6) == round(1.0 - 90.0 / 110.0, 6)
    expected_realized = pd.Series([0.10, 90.0 / 110.0 - 1.0, 95.0 / 90.0 - 1.0]).std(ddof=0)
    assert math.isclose(metrics["future_realized_vol"], float(expected_realized), rel_tol=1e-12)
    assert metrics["future_downside_vol"] == 0.0


def test_horizon_uses_t_plus_1_through_t_plus_n_not_t() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "close": [100.0, 101.0, 90.0],
        }
    )
    rows = compute_path_target_rows(prices, [{**SLICE.__dict__, "horizon": 1}], cutoff_date="2026-01-03")
    jan1 = rows[rows["trade_date"].astype(str).eq("2026-01-01")].iloc[0]

    assert jan1["event_label"] is False
    assert round(float(jan1["future_mae"]), 6) == 0.01


def test_same_day_drop_at_t_is_not_counted_in_future_mae() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "close": [100.0, 90.0, 89.0],
        }
    )
    rows = compute_path_target_rows(prices, [{**SLICE.__dict__, "horizon": 1}], cutoff_date="2026-01-03")
    jan2 = rows[rows["trade_date"].astype(str).eq("2026-01-02")].iloc[0]

    assert jan2["event_label"] is False
    assert round(float(jan2["future_mae"]), 6) == round(89.0 / 90.0 - 1.0, 6)


def test_last_rows_without_future_path_are_censored_not_labeled_non_events() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "close": [100.0, 101.0, 102.0],
        }
    )
    rows = compute_path_target_rows(prices, [SLICE], cutoff_date="2026-01-03")
    last = rows[rows["trade_date"].astype(str).eq("2026-01-03")].iloc[0]

    assert pd.isna(last["event_label"])
    assert pd.isna(last["future_mae"])
    assert last["censoring_status"] == "insufficient_future_prices"


def test_cross_cutoff_rows_are_not_backfilled_after_post_cutoff_prices_exist() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.to_datetime(["2026-06-09", "2026-06-10", "2026-06-11"]),
            "close": [100.0, 99.0, 80.0],
        }
    )
    rows = compute_path_target_rows(prices, [SLICE], cutoff_date="2026-06-10")
    row = rows[rows["trade_date"].astype(str).eq("2026-06-09")].iloc[0]

    assert pd.isna(row["event_label"])
    assert pd.isna(row["future_mae"])
    assert row["target_observation_end_date"].isoformat() == "2026-06-11"
    assert row["censoring_status"] == "cross_cutoff_censored"


def test_silent_break_entities_are_detected_and_excluded_from_target_rows() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3 + ["industry:B"] * 3,
            "trade_date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-04-15", "2026-01-01", "2026-01-02", "2026-01-03"]
            ),
            "close": [100.0, 99.0, 98.0, 100.0, 99.0, 98.0],
        }
    )
    breaks = _detect_silent_break_entities(prices)
    break_ids = {item["entity_id"] for item in breaks}
    rows = compute_path_target_rows(prices, [SLICE], cutoff_date="2026-04-15", excluded_entity_ids=break_ids)

    assert break_ids == {"industry:A"}
    assert set(rows["entity_id"]) == {"industry:B"}
