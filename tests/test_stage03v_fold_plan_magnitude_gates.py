from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_fold_plan_magnitude import build_fold_plan_v2_from_target_rows


def _target_rows() -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2014-01-02", "2021-12-31")
    for entity_idx in range(3):
        for date_idx, trade_date in enumerate(dates):
            for threshold in [0.03, 0.05]:
                label = bool((date_idx + entity_idx) % 11 == 0)
                rows.append(
                    {
                        "entity_id": f"industry:{entity_idx}",
                        "trade_date": trade_date,
                        "split_role": "historical_development",
                        "target_usage": "eligible",
                        "horizon": 5,
                        "threshold_type": "fixed",
                        "threshold_value": threshold,
                        "event_label": label,
                        "future_mae": -0.06 if label else -0.01,
                        "future_mdd": 0.06 if label else 0.01,
                        "future_return": -0.02 if label else 0.01,
                        "censoring_status": "labeled",
                        "target_observation_end_date": trade_date,
                        "sample_weight": 1.0,
                    }
                )
    return pd.DataFrame(rows)


def test_fold_plan_v2_passes_configured_magnitude_gates_on_full_like_rows() -> None:
    plan, overview = build_fold_plan_v2_from_target_rows(
        _target_rows(),
        fold_count=8,
        validation_start="2016-01-01",
        validation_end="2021-12-31",
        min_validation_span_ratio=0.5,
        min_total_validation_trade_dates=100,
        min_train_rows_per_slice=100,
        min_validation_trade_dates_per_fold=50,
    )

    assert plan["status"] == "pass"
    assert 8 <= plan["fold_count"] <= 10
    assert plan["prospective_holdout_label_consumed_count"] == 0
    assert plan["magnitude_hard_gates"]["per_fold_per_slice_train_rows_ge_5000"] is True
    assert overview
    assert all(row["validation_market_event_block_count"] >= 1 for row in overview)


def test_fold_plan_v2_blocks_when_train_rows_are_below_gate() -> None:
    plan, _ = build_fold_plan_v2_from_target_rows(
        _target_rows(),
        fold_count=8,
        validation_start="2016-01-01",
        validation_end="2021-12-31",
        min_validation_span_ratio=0.5,
        min_total_validation_trade_dates=100,
        min_train_rows_per_slice=1_000_000,
        min_validation_trade_dates_per_fold=50,
    )

    assert plan["status"] == "fail"
    assert plan["magnitude_hard_gates"]["per_fold_per_slice_train_rows_ge_5000"] is False
    assert "per_fold_per_slice_train_rows_ge_5000" in plan["blocking_reasons"]
