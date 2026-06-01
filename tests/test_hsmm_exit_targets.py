from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_exit_targets import build_exit_targets


def _states() -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-02", "2024-01-04", "2024-01-08", "2024-01-09", "2024-01-12"])
    rows = []
    specs = [
        ("A", [1, 2, 2, 3, 3], ["Stress", "Stress", "Trend", "Stress", "Stress"]),
        ("B", [1, 1, 1, 1, 1], ["Neutral", "Neutral", "Neutral", "Repair", "Repair"]),
    ]
    for sector, state_ids, labels in specs:
        for i, date in enumerate(dates):
            rows.append(
                {
                    "run_id": "r",
                    "sector_code": sector,
                    "trade_date": date,
                    "state_id": state_ids[i],
                    "state_label": labels[i],
                    "model_state_age_days": i + 1,
                    "label_state_age_days": i + 1,
                    "display_state_age_days": i + 1,
                    "duration_percentile": 0.5,
                    "expected_remaining_days": 3,
                    "raw_p_exit_1d": 0.2,
                    "raw_p_exit_3d": 0.5,
                }
            )
    return pd.DataFrame(rows)


def test_state_id_exit_differs_from_display_label_exit():
    targets = build_exit_targets(_states(), horizons=(1,), exit_types=("state_id", "display_label"))
    row_state = targets[
        targets["sector_code"].eq("A")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-02"))
        & targets["exit_type"].eq("state_id")
    ].iloc[0]
    row_label = targets[
        targets["sector_code"].eq("A")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-02"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]

    assert bool(row_state["actual_exit_within_h"]) is True
    assert bool(row_label["actual_exit_within_h"]) is False


def test_label_change_after_weekend_uses_trading_rows_not_calendar_days():
    targets = build_exit_targets(_states(), horizons=(2,), exit_types=("display_label",))
    row = targets[
        targets["sector_code"].eq("A")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-02"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]

    assert bool(row["actual_exit_within_h"]) is True
    assert row["realized_exit_lag_days"] == 2
    assert row["realized_exit_date"] == pd.Timestamp("2024-01-08")


def test_label_changes_then_back_counts_first_exit_only():
    targets = build_exit_targets(_states(), horizons=(3,), exit_types=("display_label",))
    row = targets[
        targets["sector_code"].eq("A")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-04"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]

    assert bool(row["actual_exit_within_h"]) is True
    assert row["actual_next_state_label"] == "Trend"
    assert row["realized_exit_lag_days"] == 1


def test_horizon_censoring_and_sector_isolation():
    targets = build_exit_targets(_states(), horizons=(3,), exit_types=("display_label",))
    censored = targets[
        targets["sector_code"].eq("B")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-09"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]
    first_a = targets[
        targets["sector_code"].eq("A")
        & targets["trade_date"].eq(pd.Timestamp("2024-01-12"))
        & targets["exit_type"].eq("display_label")
    ].iloc[0]

    assert bool(censored["is_right_censored_for_horizon"]) is True
    assert pd.isna(first_a["actual_next_state_label"])
