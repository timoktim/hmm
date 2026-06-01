from __future__ import annotations

import json

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models.hsmm_walk_forward import params_hash


def test_hsmm_schema_upsert_and_run_isolation(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    storage.init_schema()
    schema = storage.read_df(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_name IN (
          'hsmm_model_runs',
          'hsmm_model_checkpoints',
          'hsmm_run_performance',
          'hsmm_state_daily',
          'hsmm_state_episodes',
          'hsmm_display_label_episodes',
          'hsmm_lifecycle_ui_daily',
          'hsmm_lifecycle_profile_metadata',
          'hsmm_next_state_tendency_profile',
          'hsmm_lifecycle_duration_profile'
        )
        """
    )
    cols = set(zip(schema["table_name"], schema["column_name"], strict=False))
    assert ("hsmm_model_runs", "config_hash") in cols
    assert ("hsmm_model_runs", "snapshot_frequency") in cols
    assert ("hsmm_model_checkpoints", "checkpoint_id") in cols
    assert ("hsmm_run_performance", "fit_seconds") in cols
    assert ("hsmm_state_daily", "checkpoint_id") in cols
    assert ("hsmm_state_daily", "decode_mode") in cols
    assert ("hsmm_state_daily", "model_state_age_days") in cols
    assert ("hsmm_state_daily", "label_state_age_days") in cols
    assert ("hsmm_state_daily", "duration_model_age_days") in cols
    assert ("hsmm_state_daily", "display_state_age_days") in cols
    assert ("hsmm_state_daily", "raw_p_exit_20d") in cols
    assert ("hsmm_state_daily", "calibrated_p_exit_20d") in cols
    assert ("hsmm_state_episodes", "duration_trading_days") in cols
    assert ("hsmm_state_episodes", "is_left_censored") in cols
    assert ("hsmm_state_episodes", "right_censor_reason") in cols
    assert ("hsmm_display_label_episodes", "episode_id") in cols
    assert ("hsmm_display_label_episodes", "duration_trading_days") in cols
    assert ("hsmm_display_label_episodes", "is_open_episode") in cols
    assert ("hsmm_lifecycle_ui_daily", "profile_mode") in cols
    assert ("hsmm_lifecycle_ui_daily", "state_date_policy") in cols
    assert ("hsmm_lifecycle_ui_daily", "profile_cutoff_date") in cols
    assert ("hsmm_lifecycle_ui_daily", "exit_tendency_10d") in cols
    assert ("hsmm_lifecycle_ui_daily", "raw_score_used_10d") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_label_status") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_label_top_share") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_phase_aware") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_phase_status") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_phase_top_share") in cols
    assert ("hsmm_lifecycle_ui_daily", "next_state_tendency_age_status") in cols
    assert ("hsmm_lifecycle_ui_daily", "source_probability_run_id") in cols
    assert ("hsmm_lifecycle_ui_daily", "probability_display_policy") in cols
    assert ("hsmm_lifecycle_profile_metadata", "profile_run_id") in cols
    assert ("hsmm_lifecycle_profile_metadata", "state_date_policy") in cols
    assert ("hsmm_lifecycle_profile_metadata", "horizons") in cols
    assert ("hsmm_lifecycle_duration_profile", "profile_cutoff_date") in cols
    assert ("hsmm_lifecycle_duration_profile", "p25_duration_days") in cols
    assert ("hsmm_next_state_tendency_profile", "state_phase") in cols
    assert ("hsmm_next_state_tendency_profile", "profile_cutoff_date") in cols
    assert ("hsmm_next_state_tendency_profile", "age_bucket") in cols

    payload = {"run_id": "run_a", "n_states": 4}
    run = pd.DataFrame(
        [
            {
                "run_id": "run_a",
                "model_family": "hsmm",
                "model_version": "hsmm_v1",
                "created_at": pd.Timestamp("2024-01-01"),
                "universe_id": None,
                "include_custom_baskets": True,
                "feature_scope_id": "all",
                "feature_version": "v1",
                "start_date": pd.Timestamp("2024-01-01").date(),
                "end_date": pd.Timestamp("2024-02-01").date(),
                "train_window_days": 30,
                "rebalance_days": 5,
                "train_frequency": "monthly",
                "train_every_n_trade_days": None,
                "snapshot_frequency": "daily",
                "n_states": 4,
                "max_duration": 20,
                "duration_smoothing": 1.0,
                "emission_type": "diag_gaussian",
                "feature_columns_json": json.dumps(["ret_1d"]),
                "config_json": json.dumps(payload, sort_keys=True),
                "config_hash": params_hash(payload),
                "run_hash": params_hash({**payload, "run_id": "run_a"}),
                "params_json": json.dumps(payload, sort_keys=True),
                "params_hash": params_hash(payload),
                "code_version": "test",
                "notes": "",
            }
        ]
    )
    storage.upsert_df("hsmm_model_runs", run, ["run_id"])

    state = pd.DataFrame(
        [
            {
                "run_id": "run_a",
                "checkpoint_id": "ckpt_a",
                "trade_date": pd.Timestamp("2024-01-02").date(),
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": 1,
                "state_label": "Trend",
                "state_probability": None,
                "state_phase": "early",
                "state_age_days": 2,
                "state_age_days_by_id": 2,
                "state_age_days_by_label": 2,
                "duration_percentile": 0.2,
                "expected_remaining_days": 5.0,
                "p_stay_1d": 0.8,
                "p_stay_3d": 0.6,
                "p_stay_5d": 0.5,
                "p_stay_10d": 0.2,
                "p_exit_1d": 0.2,
                "p_exit_3d": 0.4,
                "p_exit_5d": 0.5,
                "p_exit_10d": 0.8,
                "most_likely_next_state_id": 2,
                "most_likely_next_state_label": "Neutral",
                "next_state_probability": 0.7,
                "confidence": None,
                "train_start_date": pd.Timestamp("2024-01-01").date(),
                "train_end_date": pd.Timestamp("2024-01-02").date(),
                "max_observation_date_used": pd.Timestamp("2024-01-02").date(),
                "state_source": "causal_hsmm",
                "feature_scope_id": "all",
                "decode_mode": "causal_prefix_viterbi",
                "snapshot_frequency": "daily",
                "created_at": pd.Timestamp("2024-01-03"),
            }
        ]
    )
    storage.upsert_df("hsmm_state_daily", state, ["run_id", "trade_date", "sector_code"])
    state2 = state.copy()
    state2["state_label"] = "Stress"
    storage.upsert_df("hsmm_state_daily", state2, ["run_id", "trade_date", "sector_code"])
    other = state.copy()
    other["run_id"] = "run_b"
    storage.upsert_df("hsmm_state_daily", other, ["run_id", "trade_date", "sector_code"])

    rows = storage.read_df("SELECT run_id, state_label FROM hsmm_state_daily ORDER BY run_id")
    assert rows.to_dict(orient="records") == [
        {"run_id": "run_a", "state_label": "Stress"},
        {"run_id": "run_b", "state_label": "Trend"},
    ]
    stored_run = storage.read_df("SELECT params_hash FROM hsmm_model_runs WHERE run_id = 'run_a'")
    assert stored_run.loc[0, "params_hash"] == params_hash(payload)
