from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation.stage03v_calibration_readiness import (
    apply_calibrator,
    clustered_inference_rows,
    default_policy,
    detect_calibration_boundary_violations,
    fit_calibrator,
    split_calibration_evaluation_rows,
)
from src.evaluation.stage03v_logistic_hazard import split_fold_rows


def _scored_rows() -> pd.DataFrame:
    rows = []
    for day in range(4):
        trade_date = pd.Timestamp("2026-01-07") + pd.Timedelta(days=day)
        for entity_idx in range(2):
            label = bool((day + entity_idx) % 2)
            rows.append(
                {
                    "fold_id": "fold_1",
                    "asof_mode": "close_t_minus_1",
                    "model_variant": "sklearn_logistic_regression_l2_lbfgs",
                    "entity_id": f"industry:{entity_idx}",
                    "trade_date": trade_date,
                    "horizon": 1,
                    "threshold_type": "fixed",
                    "threshold_value": 0.05,
                    "target_usage": "eligible",
                    "raw_score": 0.2 + 0.6 * int(label) + day * 0.01,
                    "event_label": label,
                    "future_mae": -0.06 if label else -0.01,
                    "future_mdd": 0.06 if label else 0.01,
                    "future_return": -0.02 if label else 0.01,
                }
            )
    return pd.DataFrame(rows)


def _target_rows_with_holdout() -> pd.DataFrame:
    rows = []
    for trade_date, split_role in [
        (pd.Timestamp("2026-06-10"), "historical_development"),
        (pd.Timestamp("2026-06-11"), "prospective_final_holdout"),
    ]:
        rows.append(
            {
                "entity_id": "industry:0",
                "trade_date": trade_date,
                "split_role": split_role,
                "target_usage": "eligible",
                "horizon": 1,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "event_label": False,
                "future_mae": -0.01,
                "future_mdd": 0.01,
                "future_return": 0.01,
                "censoring_status": "labeled",
                "target_observation_end_date": trade_date,
            }
        )
    return pd.DataFrame(rows)


def test_calibration_rows_are_strictly_before_evaluation_rows() -> None:
    split = split_calibration_evaluation_rows(_scored_rows())

    calibration_max = pd.to_datetime(split["calibration_rows"]["trade_date"]).max()
    evaluation_min = pd.to_datetime(split["evaluation_rows"]["trade_date"]).min()

    assert split["protocol"] == "validation_time_ordered_calibration_then_evaluation"
    assert calibration_max < evaluation_min
    assert detect_calibration_boundary_violations(
        split["calibration_rows"],
        split["evaluation_rows"],
    )["calibration_boundary_violation_count_total"] == 0


def test_platt_calibration_fit_ignores_evaluation_labels() -> None:
    split = split_calibration_evaluation_rows(_scored_rows())
    evaluation = split["evaluation_rows"].copy()
    evaluation_changed = evaluation.copy()
    evaluation_changed["event_label"] = ~evaluation_changed["event_label"].astype(bool)

    fit = fit_calibrator(split["calibration_rows"], method="platt_logistic_calibration", policy=default_policy())
    scores_a = apply_calibrator(evaluation, method="platt_logistic_calibration", calibrator=fit["calibrator"])
    scores_b = apply_calibrator(evaluation_changed, method="platt_logistic_calibration", calibrator=fit["calibrator"])

    np.testing.assert_allclose(scores_a, scores_b)


def test_isotonic_calibration_fit_ignores_evaluation_labels() -> None:
    split = split_calibration_evaluation_rows(_scored_rows())
    evaluation = split["evaluation_rows"].copy()
    evaluation_changed = evaluation.copy()
    evaluation_changed["event_label"] = ~evaluation_changed["event_label"].astype(bool)

    fit = fit_calibrator(split["calibration_rows"], method="isotonic_calibration", policy=default_policy())
    scores_a = apply_calibrator(evaluation, method="isotonic_calibration", calibrator=fit["calibrator"])
    scores_b = apply_calibrator(evaluation_changed, method="isotonic_calibration", calibrator=fit["calibrator"])

    np.testing.assert_allclose(scores_a, scores_b)


def test_prospective_holdout_rows_are_withheld_not_calibrated_or_evaluated() -> None:
    fold = {
        "fold_id": "fold_holdout",
        "train_start_date": "2026-06-01",
        "train_end_date": "2026-06-10",
        "validation_start_date": "2026-06-11",
        "validation_end_date": "2026-06-11",
    }

    split = split_fold_rows(_target_rows_with_holdout(), fold)

    assert split["prospective_holdout_rows_withheld"] == 1
    assert split["validation_rows"].empty


def test_clustered_inference_is_deterministic() -> None:
    rows = _scored_rows().copy()
    rows["calibration_method"] = "identity_uncalibrated_reference"
    rows["calibrated_score"] = rows["raw_score"]

    first = clustered_inference_rows(rows)
    second = clustered_inference_rows(rows)

    assert first == second
    assert {row["cluster_type"] for row in first} == {"entity_id", "trade_date", "fold_id", "slice_key"}


def test_no_trading_or_decision_fields_are_present_in_scored_rows() -> None:
    forbidden = {"buy", "sell", "sizing", "recommendation", "decision"}
    columns = {column.lower() for column in _scored_rows().columns}

    assert forbidden.isdisjoint(columns)
