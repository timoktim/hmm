from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import build_display_label_episodes, build_lifecycle_ui_frame


def _states() -> pd.DataFrame:
    labels = ["Stress", "Stress", "Neutral", "Neutral", "Trend", "Trend"]
    dates = pd.bdate_range("2025-10-27", periods=len(labels))
    return pd.DataFrame(
        {
            "run_id": "policy_date_run",
            "checkpoint_id": [f"c{i // 2}" for i in range(len(labels))],
            "trade_date": dates,
            "sector_code": "S1",
            "sector_name": "S1",
            "state_id": [i % 3 for i in range(len(labels))],
            "state_label": labels,
            "raw_p_exit_1d": [0.2] * len(labels),
            "max_observation_date_used": dates,
            "state_source": "causal_hsmm",
            "created_at": pd.Timestamp("2025-10-01"),
        }
    )


def test_cutoff_only_limits_daily_state_rows_to_cutoff():
    states = _states()
    episodes = build_display_label_episodes(states)

    ui, *_ = build_lifecycle_ui_frame(
        states,
        episodes,
        horizons=(1,),
        profile_mode="latest_asof",
        profile_cutoff_date="2025-10-31",
        state_date_policy="cutoff_only",
    )

    assert pd.to_datetime(ui["trade_date"]).max() <= pd.Timestamp("2025-10-31")
    assert ui["state_date_policy"].eq("cutoff_only").all()


def test_full_run_keeps_full_daily_state_rows_with_cutoff_profile():
    states = _states()
    episodes = build_display_label_episodes(states)

    ui, *_ = build_lifecycle_ui_frame(
        states,
        episodes,
        horizons=(1,),
        profile_mode="latest_asof",
        profile_cutoff_date="2025-10-31",
        state_date_policy="full_run",
    )

    assert pd.to_datetime(ui["trade_date"]).max() == pd.to_datetime(states["trade_date"]).max()
    assert ui["profile_cutoff_date"].astype(str).eq("2025-10-31").all()
    assert ui["state_date_policy"].eq("full_run").all()
