from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_calibration_readiness import (
    build_readiness_matrix,
    compute_calibration_metrics,
    default_policy,
)


def test_negative_brier_retention_forbids_usable_probability() -> None:
    scored = pd.DataFrame(
        {
            "event_label": [False, False, True, True],
            "raw_score": [0.05, 0.10, 0.90, 0.95],
            "calibrated_score": [0.95, 0.90, 0.10, 0.05],
            "horizon": [5] * 4,
            "threshold_type": ["fixed"] * 4,
            "threshold_value": [0.05] * 4,
            "target_usage": ["eligible"] * 4,
        }
    )

    metrics = compute_calibration_metrics(
        scored,
        calibration_row_count=4,
        method="platt_logistic_calibration",
        protocol="validation_time_ordered_calibration_then_evaluation",
        fit_status="fitted",
        skip_reason=None,
    )

    assert metrics["brier_identity_uncalibrated"] < metrics["brier_calibrated"]
    assert metrics["brier_retention"] < 0

    slice_row = {
        **metrics,
        "asof_mode": "close_t_minus_1",
        "horizon": 5,
        "threshold_type": "fixed",
        "threshold_value": 0.05,
        "target_usage": "eligible",
        "evaluation_row_count": 600,
        "positive_event_count": 40,
        "negative_event_count": 560,
        "expected_calibration_error": 0.01,
        "roc_auc": 0.72,
        "average_precision": 0.22,
        "validation_market_event_block_count": 2,
        "fold_count": 1,
    }

    readiness = build_readiness_matrix([slice_row], [], policy=default_policy(), leakage_total=0)

    assert readiness[0]["readiness_category"] != "usable_probability_candidate"
    assert readiness[0]["readiness_reason"] == "calibration_worsened_brier_score"
