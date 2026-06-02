from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import build_display_label_episodes, build_lifecycle_ui_frame


def _states() -> pd.DataFrame:
    dates = pd.bdate_range("2024-02-01", periods=7)
    return pd.DataFrame(
        {
            "run_id": "strict_run",
            "config_hash": "strict_config",
            "lineage_hash": "strict_lineage",
            "feature_scope_id": "strict_scope",
            "checkpoint_id": ["c"] * len(dates),
            "trade_date": dates,
            "sector_code": ["S1"] * len(dates),
            "sector_name": ["Sector"] * len(dates),
            "state_id": [1] * len(dates),
            "state_label": ["Stress"] * len(dates),
            "display_state_age_days": list(range(1, len(dates) + 1)),
            "duration_percentile": [0.2, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75],
            "raw_p_exit_1d": [0.1, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65],
            "calibrated_p_exit_1d": [0.12, 0.16, 0.27, 0.36, 0.44, 0.52, 0.63],
            "max_observation_date_used": dates,
            "state_source": ["causal_hsmm"] * len(dates),
        }
    )


def _matrix(status: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": "strict_run",
                "config_hash": "strict_config",
                "lineage_hash": "strict_lineage",
                "profile_mode": "retrospective",
                "profile_cutoff_date": "2024-02-09",
                "state_date_policy": "full_run",
                "feature_scope_id": "strict_scope",
                "exit_type": "display_label",
                "state_label": "Stress",
                "horizon_days": 1,
                "probability_status": status,
                "selected_method": "raw" if status in {"raw_only", "ordinal_only"} else "none",
                "created_at": "2024-02-10T00:00:00",
            }
        ]
    )


def _ui(probability_status: pd.DataFrame) -> pd.DataFrame:
    states = _states()
    episodes = build_display_label_episodes(states)
    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,), probability_status=probability_status)
    return ui


def test_ordinal_only_disables_raw_rank() -> None:
    ui = _ui(_matrix("ordinal_only"))

    assert not ui["raw_score_used_1d"].any()
    assert not ui["exit_tendency_1d_raw_score_used"].any()
    assert ui["exit_tendency_1d_readiness_status"].eq("ordinal_only").all()
    assert ui["exit_tendency_1d_raw_basis"].eq("raw_rank_excluded_ordinal_only").all()


def test_invalid_missing_and_insufficient_sample_disable_raw_rank() -> None:
    for status in ["invalid", "insufficient_sample", "missing"]:
        ui = _ui(_matrix(status))

        assert not ui["raw_score_used_1d"].any()
        assert not ui["exit_tendency_1d_raw_score_used"].any()
        assert ui["exit_tendency_1d_readiness_status"].eq(status).all()


def test_missing_readiness_contract_disables_raw_rank() -> None:
    legacy_matrix = pd.DataFrame(
        [{"state_label": "Stress", "horizon_days": 1, "probability_status": "raw_only"}]
    )

    ui = _ui(legacy_matrix)

    assert not ui["raw_score_used_1d"].any()
    assert ui["exit_tendency_1d_readiness_status"].eq("invalid").all()
    assert ui["exit_tendency_1d_raw_basis"].eq("raw_rank_excluded_invalid").all()


def test_raw_and_calibrated_p_exit_do_not_appear_in_lifecycle_ui_output() -> None:
    ui = _ui(_matrix("usable_probability"))

    assert not any(column.startswith("raw_p_exit") for column in ui.columns)
    assert not any(column.startswith("calibrated_p_exit") for column in ui.columns)
    assert "p_exit_1d" not in ui.columns
