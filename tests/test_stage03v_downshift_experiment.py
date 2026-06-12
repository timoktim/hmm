from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_downshift_experiment import (
    _baseline_scores_for_rows,
    exposure_from_bucket,
    simulate_downshift_scores,
)


def _score_rows(*, no_skill: bool = False) -> pd.DataFrame:
    rows = []
    dates = pd.bdate_range("2024-01-02", periods=80)
    for day_idx, trade_date in enumerate(dates):
        stress_day = day_idx % 20 in {10, 11, 12}
        for entity_idx in range(5):
            realized = -0.045 - entity_idx * 0.001 if stress_day else 0.006
            baseline_score = ((day_idx * 7 + entity_idx * 3) % 29) / 29.0
            model_score = baseline_score if no_skill else (0.95 if stress_day else 0.05 + entity_idx * 0.005)
            rows.append(
                {
                    "slice_id": "close_t_minus_1:h5:fixed:0.0300:eligible:platt_logistic_calibration",
                    "entity_id": f"industry:{entity_idx}",
                    "trade_date": trade_date,
                    "apply_trade_date": trade_date + pd.offsets.BDay(1),
                    "realized_open_to_open_return": realized,
                    "baseline_score": baseline_score,
                    "model_score": model_score,
                    "asof_mode": "close_t_minus_1",
                    "horizon": 5,
                    "threshold_type": "fixed",
                    "threshold_value": 0.03,
                    "target_usage": "eligible",
                    "calibration_method": "platt_logistic_calibration",
                    "baseline_name": "synthetic_baseline",
                }
            )
    return pd.DataFrame(rows)


def _primary_delta(result: dict, metric: str) -> float:
    rows = [
        row
        for row in result["pair_metrics"]
        if row["arm_pair"] == "model_minus_baseline" and row["metric"] == metric
    ]
    assert len(rows) == 1
    return float(rows[0]["delta"])


def test_exposure_rule_uses_registered_high_and_extreme_buckets() -> None:
    assert exposure_from_bucket("extreme") == 0.5
    assert exposure_from_bucket("high") == 0.75
    assert exposure_from_bucket("medium") == 1.0


def test_known_good_model_score_reduces_drawdown_vs_baseline() -> None:
    result = simulate_downshift_scores(_score_rows(), bootstrap_iterations=50, random_seed=7)

    assert _primary_delta(result, "max_drawdown") < 0
    assert _primary_delta(result, "cvar_95") < 0
    assert _primary_delta(result, "realized_volatility") < 0
    assert result["daily_exposure_sample"]


def test_no_skill_model_score_matches_baseline_delta_near_zero() -> None:
    result = simulate_downshift_scores(_score_rows(no_skill=True), bootstrap_iterations=50, random_seed=7)

    assert abs(_primary_delta(result, "max_drawdown")) < 1e-12
    assert abs(_primary_delta(result, "cvar_95")) < 1e-12
    assert abs(_primary_delta(result, "realized_volatility")) < 1e-12


def test_baseline_scores_use_feature_source_when_validation_has_same_column() -> None:
    validation_rows = pd.DataFrame(
        {
            "entity_id": ["industry:1", "industry:2"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "rolling_close_to_close_vol_60": [99.0, 99.0],
        }
    )
    feature_rows = pd.DataFrame(
        {
            "entity_id": ["industry:1", "industry:2"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-03"]),
            "rolling_close_to_close_vol_60": [0.12, 0.34],
        }
    )

    scores = _baseline_scores_for_rows(
        validation_rows,
        pd.DataFrame(),
        feature_rows,
        baseline_name="rolling_close_to_close_vol_60",
    )

    assert scores.tolist() == [0.12, 0.34]
