from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_exit_calibration import fit_empirical_exit_calibrator


def _dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_code": ["S"] * 5,
            "trade_date": pd.to_datetime(
                ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
            ),
            "state_label": ["A"] * 5,
            "state_phase": ["early"] * 5,
            "state_age_days": [1, 2, 3, 4, 5],
            "duration_percentile": [0.2] * 5,
            "horizon_days": [2] * 5,
            "raw_p_exit": [0.2, 0.7, 0.8, 0.4, 0.1],
            "actual_exit_within_h_trading_days": [False, True, True, False, False],
            "target_type": ["state_id_exit"] * 5,
            "raw_p_exit_target_type": ["state_id_exit"] * 5,
            "actual_exit_target_type": ["state_id_exit"] * 5,
            "horizon_end_date": pd.to_datetime(
                ["2024-01-03", "2024-01-04", "2024-01-05", "2024-01-06", "2024-01-07"]
            ),
            "realized_exit_date": [
                pd.NaT,
                pd.Timestamp("2024-01-04"),
                pd.Timestamp("2024-01-05"),
                pd.NaT,
                pd.NaT,
            ],
        }
    )


def test_rows_with_horizon_beyond_train_end_are_excluded_from_training() -> None:
    calibrator = fit_empirical_exit_calibrator(
        _dataset(),
        min_bucket_count=1,
        train_end_date="2024-01-04",
        target_type="state_id_exit",
    )

    assert calibrator.metadata["training_rows"] == 2
    assert calibrator.metadata["excluded_post_train_horizon_count"] == 3
    assert calibrator.metadata["train_label_cutoff_policy"] == "train_end_date_horizon_cutoff"
    assert calibrator.metadata["usable_probability"] is True


def test_realized_exit_after_train_end_is_not_observed_positive_training_label() -> None:
    df = _dataset()
    df.loc[1, "realized_exit_date"] = pd.Timestamp("2024-01-05")

    calibrator = fit_empirical_exit_calibrator(
        df,
        min_bucket_count=1,
        train_end_date="2024-01-04",
        target_type="state_id_exit",
    )

    assert calibrator.metadata["training_rows"] == 1
    assert calibrator.metadata["excluded_post_train_positive_count"] == 2
    assert calibrator.metadata["censored_row_count"] >= 1


def test_target_type_mismatch_fails_closed() -> None:
    df = _dataset()
    df.loc[:, "raw_p_exit_target_type"] = "display_label_exit"

    calibrator = fit_empirical_exit_calibrator(
        df,
        min_bucket_count=1,
        train_end_date="2024-01-04",
        target_type="state_id_exit",
    )

    assert calibrator.metadata["target_type_aligned"] is False
    assert calibrator.metadata["calibration_status"] == "failed"
    assert calibrator.metadata["usable_probability"] is False
