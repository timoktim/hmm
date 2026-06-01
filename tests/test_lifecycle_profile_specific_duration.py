from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import (
    build_profile_specific_duration_profile,
    compute_display_duration_profile,
    filter_profile_episodes,
)


def _episodes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"run_id": "r", "sector_code": "S1", "state_label": "Stress", "episode_end_date": pd.Timestamp("2025-09-01"), "duration_trading_days": 3, "duration_days": 3, "is_open_episode": False, "is_left_censored": False, "is_right_censored": False},
            {"run_id": "r", "sector_code": "S1", "state_label": "Stress", "episode_end_date": pd.Timestamp("2025-10-01"), "duration_trading_days": 5, "duration_days": 5, "is_open_episode": False, "is_left_censored": False, "is_right_censored": False},
            {"run_id": "r", "sector_code": "S1", "state_label": "Stress", "episode_end_date": pd.Timestamp("2025-11-15"), "duration_trading_days": 99, "duration_days": 99, "is_open_episode": False, "is_left_censored": False, "is_right_censored": False},
            {"run_id": "r", "sector_code": "S1", "state_label": "Stress", "episode_end_date": pd.Timestamp("2025-12-01"), "duration_trading_days": 7, "duration_days": 7, "is_open_episode": True, "is_left_censored": False, "is_right_censored": True},
        ]
    )


def test_profile_specific_duration_uses_only_completed_episodes_before_cutoff():
    episodes = _episodes()
    profile_episodes = filter_profile_episodes(episodes, "latest_asof", "2025-10-31")
    duration = compute_display_duration_profile(profile_episodes, min_samples=1)
    metadata = {
        "run_id": "r",
        "profile_mode": "latest_asof",
        "profile_cutoff_date": "2025-10-31",
        "profile_window_start": "2025-09-01",
        "profile_window_end": "2025-10-01",
    }

    profile = build_profile_specific_duration_profile(duration, episodes, profile_episodes, metadata)

    assert int(profile.loc[0, "completed_episode_count"]) == 2
    assert float(profile.loc[0, "median_duration_days"]) == 4.0
    assert int(profile.loc[0, "right_censored_count"]) == 1
    assert str(profile.loc[0, "profile_sample_window_end"]) == "2025-10-01"
