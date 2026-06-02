from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_display_lifecycle import (
    _read_probability_status,
    build_display_label_episodes,
    build_lifecycle_ui_frame,
)


def _states() -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=6)
    return pd.DataFrame(
        {
            "run_id": "run_a",
            "config_hash": "config_a",
            "lineage_hash": "lineage_a",
            "feature_scope_id": "scope_a",
            "checkpoint_id": ["c"] * len(dates),
            "trade_date": dates,
            "sector_code": ["S1"] * len(dates),
            "sector_name": ["Sector"] * len(dates),
            "state_id": [1] * len(dates),
            "state_label": ["Stress"] * len(dates),
            "display_state_age_days": list(range(1, len(dates) + 1)),
            "duration_percentile": [0.2, 0.3, 0.4, 0.5, 0.6, 0.7],
            "raw_p_exit_1d": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "calibrated_p_exit_1d": [0.11, 0.19, 0.31, 0.39, 0.51, 0.59],
            "max_observation_date_used": dates,
            "state_source": ["causal_hsmm"] * len(dates),
        }
    )


def _matrix(**overrides: object) -> pd.DataFrame:
    row = {
        "run_id": "run_a",
        "config_hash": "config_a",
        "lineage_hash": "lineage_a",
        "profile_mode": "retrospective",
        "profile_cutoff_date": "2024-01-09",
        "state_date_policy": "full_run",
        "feature_scope_id": "scope_a",
        "exit_type": "display_label",
        "state_label": "Stress",
        "horizon_days": 1,
        "probability_status": "raw_only",
        "selected_method": "raw",
        "created_at": "2024-01-10T00:00:00",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def _ui(probability_status: pd.DataFrame) -> pd.DataFrame:
    states = _states()
    episodes = build_display_label_episodes(states)
    ui, *_ = build_lifecycle_ui_frame(states, episodes, horizons=(1,), probability_status=probability_status)
    return ui


def test_matching_readiness_contract_allows_internal_raw_rank() -> None:
    ui = _ui(_matrix())

    assert ui["raw_score_used_1d"].all()
    assert ui["exit_tendency_1d_raw_score_used"].all()
    assert ui["exit_tendency_1d_readiness_status"].eq("raw_only").all()
    assert ui["exit_tendency_1d_raw_basis"].eq("raw_rank_used_as_internal_diagnostic").all()


def test_readiness_matrix_run_id_mismatch_disables_raw_score() -> None:
    ui = _ui(_matrix(run_id="other_run"))

    assert not ui["raw_score_used_1d"].any()
    assert not ui["exit_tendency_1d_raw_score_used"].any()
    assert ui["exit_tendency_1d_readiness_status"].eq("invalid").all()


def test_readiness_matrix_config_hash_mismatch_disables_raw_score() -> None:
    ui = _ui(_matrix(config_hash="other_config"))

    assert not ui["raw_score_used_1d"].any()
    assert ui["exit_tendency_1d_readiness_status"].eq("invalid").all()


def test_readiness_matrix_lineage_hash_mismatch_disables_raw_score() -> None:
    ui = _ui(_matrix(lineage_hash="other_lineage"))

    assert not ui["raw_score_used_1d"].any()
    assert ui["exit_tendency_1d_readiness_status"].eq("invalid").all()


def test_read_probability_status_validates_expected_metadata(tmp_path) -> None:
    _matrix(config_hash="wrong_config").to_csv(tmp_path / "ui_readiness_matrix.csv", index=False)

    matrix = _read_probability_status(
        "run_a",
        tmp_path,
        expected_metadata={
            "run_id": "run_a",
            "config_hash": "config_a",
            "lineage_hash": "lineage_a",
            "profile_mode": "retrospective",
            "profile_cutoff_date": "2024-01-09",
            "state_date_policy": "full_run",
            "feature_scope_id": "scope_a",
        },
    )

    assert matrix["probability_status"].eq("invalid").all()
    assert matrix["readiness_contract_status"].eq("invalid").all()
    assert matrix["readiness_mismatch_reason"].str.contains("config_hash_mismatch").all()
