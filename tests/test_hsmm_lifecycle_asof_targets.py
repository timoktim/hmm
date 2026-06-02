from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import LifecycleDisplayConfig, build_lifecycle_ui_frame
from src.evaluation.hsmm_exit_targets import build_exit_targets


def _states(labels: list[str]) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-01", "2024-01-03", "2024-01-05", "2024-01-08"])
    rows = []
    for i, (date, label) in enumerate(zip(dates, labels, strict=True), start=1):
        rows.append(
            {
                "run_id": "r",
                "sector_code": "S",
                "sector_name": "Sector",
                "trade_date": date,
                "state_id": 1 if label == "Calm" else 2,
                "state_label": label,
                "model_state_age_days": i,
                "label_state_age_days": i,
                "display_state_age_days": i,
                "duration_percentile": 0.5,
                "expected_remaining_days": 3,
                "raw_p_exit_1d": 0.2,
                "raw_p_exit_2d": 0.3,
            }
        )
    return pd.DataFrame(rows)


def _episodes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": "r",
                "sector_code": "S",
                "state_label": "Calm",
                "episode_start_date": pd.Timestamp("2023-12-20"),
                "episode_end_date": pd.Timestamp("2023-12-28"),
                "duration_trading_days": 4,
                "duration_days": 4,
                "is_open_episode": False,
                "is_left_censored": False,
                "is_right_censored": False,
                "next_state_label": "Calm",
            }
        ]
    )


def _target_row(states: pd.DataFrame, trade_date: str, horizon: int = 2, cutoff: str = "2024-01-05") -> pd.Series:
    targets = build_exit_targets(
        states,
        horizons=(horizon,),
        exit_types=("display_label",),
        asof_cutoff_date=pd.Timestamp(cutoff),
    )
    return targets[targets["trade_date"].eq(pd.Timestamp(trade_date))].iloc[0]


def test_post_cutoff_realized_exit_is_not_observed_positive():
    row = _target_row(_states(["Calm", "Calm", "Calm", "Risk"]), "2024-01-03", horizon=2)

    assert bool(row["actual_exit_within_h"]) is True
    assert row["realized_exit_date"] == pd.Timestamp("2024-01-08")
    assert row["target_observation_status"] == "right_censored_by_cutoff"


def test_horizon_after_cutoff_without_exit_is_not_observed_negative():
    row = _target_row(_states(["Calm", "Calm", "Calm", "Calm"]), "2024-01-03", horizon=2)

    assert bool(row["actual_exit_within_h"]) is False
    assert row["horizon_end_date"] == pd.Timestamp("2024-01-08")
    assert row["target_observation_status"] == "right_censored_by_cutoff"


def test_horizon_before_cutoff_without_exit_is_observed_negative():
    row = _target_row(_states(["Calm", "Calm", "Calm", "Calm"]), "2024-01-01", horizon=1)

    assert bool(row["actual_exit_within_h"]) is False
    assert row["horizon_end_date"] == pd.Timestamp("2024-01-03")
    assert row["target_observation_status"] == "observed_negative"


def test_pre_cutoff_realized_exit_inside_horizon_is_observed_positive():
    row = _target_row(_states(["Calm", "Risk", "Risk", "Risk"]), "2024-01-01", horizon=2)

    assert bool(row["actual_exit_within_h"]) is True
    assert row["realized_exit_date"] == pd.Timestamp("2024-01-03")
    assert row["target_observation_status"] == "observed_positive"


def test_latest_asof_empirical_rate_ignores_post_cutoff_suffix_changes():
    config = LifecycleDisplayConfig(min_empirical_bucket_sample=1, min_empirical_label_sample=1)
    base = _states(["Calm", "Calm", "Calm", "Calm"])
    changed_future = _states(["Calm", "Calm", "Calm", "Risk"])
    kwargs = {
        "episodes": _episodes(),
        "horizons": (2,),
        "probability_status": pd.DataFrame(),
        "config": config,
        "profile_mode": "latest_asof",
        "profile_cutoff_date": "2024-01-05",
        "state_date_policy": "full_run",
    }

    _, _, profile_a, _, _, _ = build_lifecycle_ui_frame(base, **kwargs)
    _, _, profile_b, _, _, _ = build_lifecycle_ui_frame(changed_future, **kwargs)
    cols = ["state_label", "age_bucket", "horizon_days", "sample_count", "empirical_exit_rate", "profile_exit_rate_used"]

    pd.testing.assert_frame_equal(
        profile_a[cols].sort_values(cols[:3]).reset_index(drop=True),
        profile_b[cols].sort_values(cols[:3]).reset_index(drop=True),
        check_dtype=False,
    )
