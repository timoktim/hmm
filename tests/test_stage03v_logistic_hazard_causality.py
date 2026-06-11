from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.evaluation.stage03v_logistic_hazard import (
    default_policy,
    detect_asof_violations,
    fit_logistic_model,
    fit_train_only_preprocessor,
    split_fold_rows,
    validate_feature_columns,
)


def _rows() -> pd.DataFrame:
    labels = [False, True, False, True, False, True, False, True]
    rows = []
    for idx, label in enumerate(labels):
        trade_date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx)
        rows.append(
            {
                "entity_id": f"industry:{idx % 2}",
                "trade_date": trade_date,
                "feature_asof_date": trade_date - pd.Timedelta(days=1),
                "split_role": "historical_development",
                "target_usage": "eligible",
                "horizon": 1,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "event_label": label,
                "future_mae": -0.06 if label else -0.01,
                "future_mdd": 0.06 if label else 0.01,
                "future_return": -0.02 if label else 0.01,
                "censoring_status": "labeled",
                "target_observation_end_date": trade_date + pd.Timedelta(days=1),
                "rolling_close_to_close_vol_20": 0.01 + idx * 0.01,
                "rolling_close_to_close_vol_60": 0.02 + idx * 0.01,
            }
        )
    return pd.DataFrame(rows)


def _fold() -> dict:
    return {
        "fold_id": "fold_1",
        "train_start_date": "2026-01-01",
        "train_end_date": "2026-01-05",
        "validation_start_date": "2026-01-07",
        "validation_end_date": "2026-01-08",
    }


def test_validation_labels_do_not_affect_fitted_coefficients() -> None:
    train = _rows().iloc[:6].copy()
    validation = _rows().iloc[6:].copy()
    mutated_validation = validation.copy()
    mutated_validation["event_label"] = ~mutated_validation["event_label"].astype(bool)

    result_a = fit_logistic_model(
        train,
        validation,
        ["rolling_close_to_close_vol_20", "rolling_close_to_close_vol_60"],
        default_policy(),
    )
    result_b = fit_logistic_model(
        train,
        mutated_validation,
        ["rolling_close_to_close_vol_20", "rolling_close_to_close_vol_60"],
        default_policy(),
    )

    np.testing.assert_allclose(result_a["coefficients"], result_b["coefficients"])
    np.testing.assert_allclose(result_a["scores"], result_b["scores"])


def test_same_row_event_label_is_not_an_allowed_feature() -> None:
    result = validate_feature_columns(["rolling_close_to_close_vol_20", "event_label"])

    assert result["target_namespace_input_violation_count"] == 1
    assert "event_label" in result["target_namespace_input_violations"]


def test_future_columns_and_target_namespace_columns_are_rejected() -> None:
    result = validate_feature_columns(["future_return", "future_realized_vol", "target_observation_end_date"])

    assert result["future_column_input_violation_count"] == 2
    assert result["target_namespace_input_violation_count"] == 3


def test_feature_asof_rules_differ_by_mode() -> None:
    rows = pd.DataFrame(
        [
            {"trade_date": "2026-01-03", "feature_asof_date": "2026-01-02"},
            {"trade_date": "2026-01-03", "feature_asof_date": "2026-01-03"},
            {"trade_date": "2026-01-03", "feature_asof_date": "2026-01-04"},
        ]
    )

    assert detect_asof_violations(rows, asof_mode="close_t") == 1
    assert detect_asof_violations(rows, asof_mode="close_t_minus_1") == 2


def test_scaler_and_imputer_fit_on_training_rows_only() -> None:
    train = pd.DataFrame(
        {
            "x": [1.0, np.nan, 3.0, 5.0],
            "event_label": [False, True, False, True],
        }
    )
    validation = pd.DataFrame({"x": [1000.0, 2000.0], "event_label": [False, True]})
    validation_changed = pd.DataFrame({"x": [-1000.0, -2000.0], "event_label": [True, False]})

    prep_a = fit_train_only_preprocessor(train, validation, ["x"])
    prep_b = fit_train_only_preprocessor(train, validation_changed, ["x"])

    assert prep_a["imputer_statistics"][0] == pytest.approx(3.0)
    assert prep_a["scaler_mean"][0] == pytest.approx(3.0)
    np.testing.assert_allclose(prep_a["imputer_statistics"], prep_b["imputer_statistics"])
    np.testing.assert_allclose(prep_a["scaler_mean"], prep_b["scaler_mean"])
    np.testing.assert_allclose(prep_a["scaler_scale"], prep_b["scaler_scale"])
    assert prep_a["fit_on_validation_rows_count"] == 0


def test_training_uses_train_fold_only_and_excludes_purged_rows() -> None:
    rows = _rows()
    extra = rows.iloc[[5]].copy()
    extra["trade_date"] = pd.Timestamp("2026-01-06")
    extra["target_observation_end_date"] = pd.Timestamp("2026-01-07")
    rows = pd.concat([rows, extra], ignore_index=True)

    split = split_fold_rows(rows, _fold())
    train_dates = set(pd.to_datetime(split["train_rows"]["trade_date"]).dt.strftime("%Y-%m-%d"))

    assert "2026-01-06" not in train_dates
    assert "2026-01-07" not in train_dates
    assert split["training_boundary_violation_counts"]["training_boundary_violation_count_total"] == 0


def test_prospective_holdout_rows_are_withheld_not_scored_or_evaluated() -> None:
    rows = _rows().iloc[[0]].copy()
    rows["trade_date"] = pd.Timestamp("2026-06-11")
    rows["target_observation_end_date"] = pd.Timestamp("2026-06-12")
    rows["split_role"] = "prospective_final_holdout"
    fold = {
        "fold_id": "fold_holdout",
        "train_start_date": "2026-06-01",
        "train_end_date": "2026-06-10",
        "validation_start_date": "2026-06-11",
        "validation_end_date": "2026-06-11",
    }

    split = split_fold_rows(rows, fold)

    assert split["prospective_holdout_rows_withheld"] == 1
    assert split["validation_rows"].empty
    assert split["train_rows"].empty
