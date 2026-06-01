from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import build_display_label_episodes, build_lifecycle_ui_frame


def _states() -> pd.DataFrame:
    labels = (["Trend", "Trend", "Repair", "Repair"] * 35) + (["Trend", "Trend", "Neutral", "Neutral"] * 25)
    dates = pd.bdate_range("2024-01-02", periods=len(labels))
    rows = []
    for i, (date, label) in enumerate(zip(dates, labels, strict=False)):
        rows.append(
            {
                "run_id": "next_ui_run",
                "checkpoint_id": f"c{i // 10}",
                "trade_date": date,
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": i % 4,
                "state_label": label,
                "raw_p_exit_1d": 0.2,
                "max_observation_date_used": date,
                "state_source": "causal_hsmm",
                "created_at": pd.Timestamp("2024-01-01"),
            }
        )
    return pd.DataFrame(rows)


def test_next_state_status_sample_and_top_share_written_to_ui_daily():
    states = _states()
    episodes = build_display_label_episodes(states)

    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,), profile_mode="retrospective")

    required = {
        "next_state_tendency_label",
        "next_state_tendency_label_status",
        "next_state_tendency_label_sample_count",
        "next_state_tendency_label_top_share",
        "next_state_tendency_phase_aware",
        "next_state_tendency_phase_status",
        "next_state_tendency_phase_sample_count",
        "next_state_tendency_phase_top_share",
        "next_state_tendency_age_bucket",
        "next_state_tendency_age_status",
        "next_state_tendency_age_sample_count",
        "next_state_tendency_age_top_share",
    }
    assert required.issubset(ui.columns)
    assert ui["next_state_tendency_label_status"].isin(["usable", "mixed", "insufficient_sample", "unavailable"]).all()
    assert pd.to_numeric(ui["next_state_tendency_label_sample_count"], errors="coerce").ge(0).all()
