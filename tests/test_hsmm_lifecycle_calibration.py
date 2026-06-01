from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_lifecycle_calibration import (
    CalibrationConfig,
    select_probability_status,
    time_split_targets,
    ui_readiness_matrix,
)


def _target_rows(n: int = 30) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=n, freq="D")
    rows = []
    for i, date in enumerate(dates):
        rows.append(
            {
                "run_id": "r",
                "trade_date": date,
                "sector_code": f"S{i % 3}",
                "state_id": 1,
                "state_label": "Stress",
                "model_state_age_days": i % 10 + 1,
                "label_state_age_days": i % 10 + 1,
                "display_state_age_days": i % 10 + 1,
                "duration_percentile": 0.5,
                "expected_remaining_days": 4,
                "horizon_days": 5,
                "exit_type": "display_label",
                "actual_exit_within_h": i % 3 == 0,
                "is_right_censored_for_horizon": False,
                "raw_exit_score": 0.8 if i % 3 == 0 else 0.2,
            }
        )
    return pd.DataFrame(rows)


def test_time_split_is_chronological_and_non_random():
    split = time_split_targets(_target_rows(30), (0.6, 0.2, 0.2))

    train_max = split[split["split"].eq("train")]["trade_date"].max()
    validation_min = split[split["split"].eq("validation")]["trade_date"].min()
    validation_max = split[split["split"].eq("validation")]["trade_date"].max()
    test_min = split[split["split"].eq("test")]["trade_date"].min()

    assert train_max < validation_min
    assert validation_max < test_min


def test_insufficient_sample_status():
    summary = pd.DataFrame(
        [
            {
                "split": "validation",
                "state_label": "Stress",
                "horizon_days": 5,
                "exit_type": "display_label",
                "method": "raw",
                "sample_count": 10,
                "positive_events": 2,
                "brier_score": 0.2,
                "ece_equal_frequency": 0.02,
                "mce": 0.05,
                "bucket_monotonicity_passed": True,
                "spearman_pred_vs_realized_bucket_rate": 1.0,
            }
        ]
    )
    selected = select_probability_status(summary, CalibrationConfig(min_sample_per_state_horizon=100, min_positive_events=20))

    assert selected.loc[0, "status"] == "insufficient_sample"


def test_calibrated_worse_than_raw_does_not_select_calibrated():
    summary = pd.DataFrame(
        [
            {
                "split": "validation",
                "state_label": "Neutral",
                "horizon_days": 5,
                "exit_type": "state_id",
                "method": "raw",
                "sample_count": 1000,
                "positive_events": 300,
                "brier_score": 0.10,
                "ece_equal_frequency": 0.03,
                "mce": 0.10,
                "bucket_monotonicity_passed": True,
                "spearman_pred_vs_realized_bucket_rate": 1.0,
            },
            {
                "split": "validation",
                "state_label": "Neutral",
                "horizon_days": 5,
                "exit_type": "state_id",
                "method": "logistic",
                "sample_count": 1000,
                "positive_events": 300,
                "brier_score": 0.12,
                "ece_equal_frequency": 0.02,
                "mce": 0.08,
                "bucket_monotonicity_passed": True,
                "spearman_pred_vs_realized_bucket_rate": 1.0,
            },
        ]
    )
    selected = select_probability_status(summary, CalibrationConfig(min_sample_per_state_horizon=100, min_positive_events=20))

    assert selected.loc[0, "selected_method"] == "raw"
    assert selected.loc[0, "status"] == "raw_only"


def test_invalid_probability_is_hidden_in_ui_matrix():
    summary = pd.DataFrame(
        [
            {
                "split": "validation",
                "state_label": "Trend",
                "horizon_days": 10,
                "exit_type": "display_label",
                "method": "raw",
                "sample_count": 1000,
                "positive_events": 300,
                "brier_score": 0.3,
                "ece_equal_frequency": 0.2,
                "mce": 0.4,
                "bucket_monotonicity_passed": False,
                "spearman_pred_vs_realized_bucket_rate": -0.2,
            }
        ]
    )
    selected = select_probability_status(summary, CalibrationConfig(min_sample_per_state_horizon=100, min_positive_events=20))
    matrix = ui_readiness_matrix(selected)

    assert selected.loc[0, "status"] == "invalid"
    assert bool(matrix.loc[0, "must_hide"])

