from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import (
    LifecycleDisplayConfig,
    compute_next_state_tendency_profiles,
)


def _episodes(next_labels: list[str], state_label: str = "Stress") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": "next_run",
            "sector_code": [f"S{i % 5}" for i in range(len(next_labels))],
            "state_label": [state_label] * len(next_labels),
            "duration_trading_days": [5 + (i % 4) for i in range(len(next_labels))],
            "is_right_censored": [False] * len(next_labels),
            "next_state_label": next_labels,
        }
    )


def test_next_state_tendency_uses_realized_next_label():
    episodes = _episodes(["Repair"] * 80 + ["Neutral"] * 40)

    profiles = compute_next_state_tendency_profiles(episodes, pd.DataFrame())
    by_label = profiles["by_label"]

    assert by_label.loc[0, "top_next_state_label"] == "Repair"
    assert by_label.loc[0, "next_state_tendency"] == "Repair"


def test_low_sample_outputs_unavailable():
    episodes = _episodes(["Repair"] * 10)

    profiles = compute_next_state_tendency_profiles(episodes, pd.DataFrame())

    assert profiles["by_label"].loc[0, "next_state_tendency"] == "Unavailable"
    assert profiles["by_label"].loc[0, "status"] == "insufficient_sample"


def test_low_top_share_outputs_mixed():
    episodes = _episodes(["Trend"] * 48 + ["Neutral"] * 36 + ["Stress"] * 36)

    profiles = compute_next_state_tendency_profiles(episodes, pd.DataFrame(), LifecycleDisplayConfig())

    assert profiles["by_label"].loc[0, "next_state_tendency"] == "Mixed"
    assert profiles["by_label"].loc[0, "status"] == "mixed"
