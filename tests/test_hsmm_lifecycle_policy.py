from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import (
    LifecycleDisplayConfig,
    build_display_label_episodes,
    build_exit_tendency_distribution,
    build_lifecycle_ui_frame,
)


def _states(label: str = "Stress", rows: int = 8) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=rows)
    return pd.DataFrame(
        {
            "run_id": "policy_run",
            "checkpoint_id": [f"c{i // 3}" for i in range(rows)],
            "trade_date": dates,
            "sector_code": "S1",
            "sector_name": "S1",
            "state_id": [i % 2 for i in range(rows)],
            "state_label": label,
            "raw_p_exit_1d": [0.1 + i * 0.01 for i in range(rows)],
            "max_observation_date_used": dates,
            "state_source": "causal_hsmm",
            "created_at": pd.Timestamp("2024-01-01"),
        }
    )


def test_invalid_probability_slice_excludes_raw_rank():
    states = _states()
    episodes = build_display_label_episodes(states)
    probability_status = pd.DataFrame(
        [{"state_label": "Stress", "horizon_days": 1, "probability_status": "invalid"}]
    )

    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,), probability_status=probability_status)

    assert not ui["raw_score_used_1d"].any()
    assert ui["exit_tendency_basis_1d"].str.contains("raw_rank_excluded_invalid").all()


def test_ordinal_probability_slice_allows_raw_rank_as_ordinal():
    states = _states()
    episodes = build_display_label_episodes(states)
    probability_status = pd.DataFrame(
        [{"state_label": "Stress", "horizon_days": 1, "probability_status": "ordinal_only"}]
    )

    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,), probability_status=probability_status)

    assert ui["raw_score_used_1d"].all()
    assert ui["exit_tendency_basis_1d"].str.contains("raw_rank_used_as_ordinal").all()


def test_exit_tendency_distribution_not_all_high_for_5d_10d_when_samples_sufficient():
    exit_long = pd.DataFrame(
        {
            "horizon_days": [5] * 90 + [10] * 90,
            "state_label": ["Stress"] * 180,
            "exit_tendency": (["low"] * 30 + ["medium"] * 30 + ["high"] * 30) * 2,
        }
    )

    distribution = build_exit_tendency_distribution(exit_long, LifecycleDisplayConfig())

    assert not distribution["low_discrimination"].any()
    assert set(distribution["exit_tendency"]) == {"low", "medium", "high"}


def test_20d_low_discrimination_warning():
    exit_long = pd.DataFrame(
        {
            "horizon_days": [20] * 100,
            "state_label": ["Stress"] * 100,
            "exit_tendency": ["high"] * 96 + ["medium"] * 4,
        }
    )

    distribution = build_exit_tendency_distribution(exit_long, LifecycleDisplayConfig())

    assert distribution["low_discrimination"].all()
