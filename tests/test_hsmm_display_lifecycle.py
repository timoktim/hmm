from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import (
    EXIT_TENDENCIES,
    assign_state_phase,
    attach_display_episode_context,
    build_display_label_episodes,
    build_lifecycle_ui_frame,
    build_ui_field_policy,
    compute_display_duration_profile,
    compute_empirical_exit_tendency,
    compute_next_state_tendency,
    filter_profile_episodes,
)


def _states(labels: list[str] | None = None, checkpoints: list[str] | None = None) -> pd.DataFrame:
    labels = labels or ["Stress", "Stress", "Neutral", "Neutral", "Stress"]
    checkpoints = checkpoints or ["c1", "c2", "c2", "c3", "c3"]
    dates = pd.bdate_range("2024-01-02", periods=len(labels))
    rows = []
    for i, (date, label, checkpoint) in enumerate(zip(dates, labels, checkpoints, strict=False)):
        rows.append(
            {
                "run_id": "r",
                "checkpoint_id": checkpoint,
                "trade_date": date,
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": i % 3,
                "state_label": label,
                "display_state_age_days": i + 1,
                "raw_p_exit_1d": 0.2 + i * 0.01,
                "raw_p_exit_3d": 0.3 + i * 0.01,
                "raw_p_exit_5d": 0.4 + i * 0.01,
                "raw_p_exit_10d": 0.5 + i * 0.01,
                "raw_p_exit_20d": 0.6 + i * 0.01,
                "max_observation_date_used": date,
                "state_source": "causal_hsmm",
                "created_at": pd.Timestamp("2024-01-01"),
            }
        )
    return pd.DataFrame(rows)


def test_display_label_episode_does_not_break_on_checkpoint_change():
    states = _states(labels=["Stress", "Stress", "Stress"], checkpoints=["c1", "c2", "c3"])
    episodes = build_display_label_episodes(states)

    assert len(episodes) == 1
    assert episodes.loc[0, "duration_days"] == 3
    assert episodes.loc[0, "duration_trading_days"] == 3


def test_hidden_state_change_same_label_not_display_exit():
    states = _states(labels=["Stress", "Stress", "Stress", "Stress"], checkpoints=["c1", "c1", "c2", "c2"])
    states["state_id"] = [0, 1, 2, 0]
    episodes = build_display_label_episodes(states)

    assert len(episodes) == 1
    assert episodes.loc[0, "state_label"] == "Stress"
    assert episodes.loc[0, "next_state_label"] is None


def test_display_age_increments_and_resets_on_label_change():
    states = _states(labels=["Stress", "Stress", "Neutral", "Neutral", "Stress"])
    episodes = build_display_label_episodes(states)
    with_context = attach_display_episode_context(states, episodes)

    assert with_context["display_state_age_days"].tolist() == [1, 2, 1, 2, 1]


def test_run_edges_are_marked_censored():
    states = _states(labels=["Stress", "Stress", "Neutral", "Neutral", "Stress"])
    episodes = build_display_label_episodes(states)

    first = episodes.iloc[0]
    last = episodes.iloc[-1]
    assert bool(first["is_left_censored"])
    assert first["left_censor_reason"] == "run_start"
    assert bool(last["is_right_censored"])
    assert last["right_censor_reason"] == "run_end"


def test_duration_profile_excludes_censored_episodes():
    episodes = pd.DataFrame(
        [
            {"state_label": "Stress", "end_date": pd.Timestamp("2024-01-03"), "duration_days": 2, "duration_trading_days": 2, "is_open_episode": False, "is_left_censored": False, "is_right_censored": False},
            {"state_label": "Stress", "end_date": pd.Timestamp("2024-01-08"), "duration_days": 4, "duration_trading_days": 4, "is_open_episode": False, "is_left_censored": False, "is_right_censored": False},
            {"state_label": "Stress", "end_date": pd.Timestamp("2024-05-20"), "duration_days": 100, "duration_trading_days": 100, "is_open_episode": True, "is_left_censored": False, "is_right_censored": True},
        ]
    )
    profile = compute_display_duration_profile(filter_profile_episodes(episodes), min_samples=1)

    assert profile.loc[0, "completed_episode_count"] == 2
    assert profile.loc[0, "median_duration_days"] == 3.0


def test_state_phase_uses_p33_p66_thresholds():
    states = pd.DataFrame(
        {
            "state_label": ["Stress", "Stress", "Stress", "Stress"],
            "display_state_age_days": [1, 3, 5, 9],
        }
    )
    profile = pd.DataFrame(
        {
            "state_label": ["Stress"],
            "completed_episode_count": [10],
            "p33_duration_days": [3.0],
            "p66_duration_days": [6.0],
        }
    )
    phased = assign_state_phase(states, profile)

    assert phased["state_phase"].tolist() == ["early", "early", "mature", "late"]


def test_exit_tendency_unavailable_when_lifecycle_basis_missing():
    states = _states(labels=["Stress", "Stress", "Stress"])
    episodes = build_display_label_episodes(states)
    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,))

    assert set(ui["exit_tendency_1d"]) == {"unavailable"}


def test_lifecycle_ui_daily_unique_sector_date_and_row_count():
    states = _states(labels=["Stress", "Stress", "Neutral", "Neutral", "Stress"])
    episodes = build_display_label_episodes(states)

    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,))

    assert len(ui) == len(states)
    assert not ui.duplicated(["run_id", "profile_mode", "trade_date", "sector_code"]).any()


def test_exit_tendency_outputs_only_allowed_values():
    rows = []
    labels = ["Stress"] * 6 + ["Neutral"] * 6 + ["Stress"] * 6 + ["Repair"] * 6
    for i, label in enumerate(labels):
        rows.append(
            {
                "run_id": "r",
                "checkpoint_id": "c",
                "trade_date": pd.Timestamp("2024-01-02") + pd.offsets.BDay(i),
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": i % 4,
                "state_label": label,
                "raw_p_exit_1d": (i % 5) / 5,
                "max_observation_date_used": pd.Timestamp("2024-01-02") + pd.offsets.BDay(i),
                "state_source": "causal_hsmm",
                "created_at": pd.Timestamp("2024-01-01"),
            }
        )
    states = pd.DataFrame(rows)
    episodes = build_display_label_episodes(states)
    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,))

    assert set(ui["exit_tendency_1d"]).issubset(set(EXIT_TENDENCIES))


def test_next_state_tendency_insufficient_sample_is_unavailable():
    states = _states(labels=["Stress", "Stress", "Neutral", "Neutral", "Stress"])
    episodes = build_display_label_episodes(states)
    profile = compute_next_state_tendency(episodes)

    assert profile["next_state_tendency"].eq("Unavailable").all()


def test_ui_policy_forbids_raw_and_calibrated_probability_display():
    policy = build_ui_field_policy()
    hidden = policy[policy["field_name"].isin(["raw_p_exit_*", "calibrated_p_exit_*", "next_state_probability"])]

    assert not hidden["display_allowed"].any()
    assert hidden["display_type"].eq("hide").all()


def test_compute_empirical_exit_tendency_returns_profile_shape():
    states = _states(labels=["Stress", "Stress", "Neutral", "Neutral", "Stress", "Stress"])
    episodes = build_display_label_episodes(states)
    profile = compute_empirical_exit_tendency(states, episodes, horizons=(1,))

    assert {"state_label", "age_bucket", "horizon_days", "sample_count", "empirical_exit_rate"}.issubset(profile.columns)
