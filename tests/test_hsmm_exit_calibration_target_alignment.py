from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_exit_calibration import (
    apply_exit_calibrator,
    build_exit_calibration_dataset,
    fit_empirical_exit_calibrator,
)
from src.evaluation.hsmm_exit_targets import build_exit_targets


def _states() -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04"])
    return pd.DataFrame(
        {
            "run_id": ["r"] * 4,
            "sector_code": ["S"] * 4,
            "trade_date": dates,
            "state_id": [1, 2, 2, 3],
            "state_label": ["Stress", "Stress", "Stress", "Repair"],
            "state_phase": ["early"] * 4,
            "state_age_days": [1, 1, 2, 1],
            "duration_percentile": [0.2, 0.3, 0.4, 0.5],
            "raw_p_exit_1d": [0.8, 0.2, 0.3, 0.4],
            "raw_p_exit_display_label_exit_1d": [0.1, 0.2, 0.8, 0.4],
        }
    )


def test_adjacent_state_id_exit_can_differ_from_display_label_exit() -> None:
    targets = build_exit_targets(_states(), horizons=(1,), exit_types=("state_id", "display_label"))
    state_row = targets[
        targets["trade_date"].eq(pd.Timestamp("2024-01-01"))
        & targets["exit_type"].eq("state_id")
    ].iloc[0]
    label_row = targets[
        targets["trade_date"].eq(pd.Timestamp("2024-01-01"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]

    assert bool(state_row["actual_exit_within_h"]) is True
    assert bool(label_row["actual_exit_within_h"]) is False
    assert state_row["target_type"] == "state_id_exit"
    assert label_row["target_type"] == "display_label_exit"


def test_raw_p_exit_basis_and_actual_exit_target_type_are_aligned() -> None:
    state_dataset = build_exit_calibration_dataset(_states(), horizons=(1,), target_type="state_id_exit")
    label_dataset = build_exit_calibration_dataset(_states(), horizons=(1,), target_type="display_label_exit")

    assert state_dataset["target_type"].eq("state_id_exit").all()
    assert state_dataset["raw_p_exit_target_type"].eq("state_id_exit").all()
    assert state_dataset["actual_exit_target_type"].eq("state_id_exit").all()
    assert label_dataset["target_type"].eq("display_label_exit").all()
    assert label_dataset["raw_p_exit_target_type"].eq("display_label_exit").all()
    assert label_dataset["actual_exit_target_type"].eq("display_label_exit").all()


def test_display_label_calibration_does_not_reuse_state_id_raw_score() -> None:
    states = _states().drop(columns=["raw_p_exit_display_label_exit_1d"])

    label_dataset = build_exit_calibration_dataset(states, horizons=(1,), target_type="display_label_exit")
    targets = build_exit_targets(states, horizons=(1,), exit_types=("display_label",))

    assert label_dataset.empty
    assert targets["raw_exit_score"].isna().all()
    assert targets["raw_exit_score_target_type"].isna().all()


def test_missing_train_end_fails_closed_and_does_not_emit_usable_probability() -> None:
    dataset = build_exit_calibration_dataset(_states(), horizons=(1,), target_type="state_id_exit")

    calibrator = fit_empirical_exit_calibrator(dataset, min_bucket_count=1)
    scored = apply_exit_calibrator(dataset, calibrator)

    assert calibrator.metadata["calibration_status"] == "failed"
    assert calibrator.metadata["usable_probability"] is False
    assert calibrator.metadata["train_label_cutoff_policy"] == "fail_closed_missing_train_end_date"
    assert scored["calibrated_p_exit"].isna().all()
    assert scored["probability_status"].eq("invalid").all()


def test_allow_in_sample_must_be_explicit() -> None:
    dataset = build_exit_calibration_dataset(_states(), horizons=(1,), target_type="state_id_exit")

    calibrator = fit_empirical_exit_calibrator(dataset, min_bucket_count=1, allow_in_sample=True)
    scored = apply_exit_calibrator(dataset, calibrator)

    assert calibrator.metadata["allow_in_sample"] is True
    assert calibrator.metadata["calibration_status"] == "usable"
    assert scored["calibrated_p_exit"].notna().all()
    assert scored["probability_status"].eq("usable_probability").all()
