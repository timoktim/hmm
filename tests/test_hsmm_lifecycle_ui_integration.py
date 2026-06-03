from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_display_lifecycle import EXIT_TENDENCIES, write_lifecycle_ui_outputs


def _seed_states(storage: DuckDBStorage, run_id: str = "lifecycle_ui_run") -> int:
    rows = []
    labels = ["Stress"] * 4 + ["Neutral"] * 4 + ["Trend"] * 4 + ["Repair"] * 4 + ["Stress"] * 4
    dates = pd.bdate_range("2024-01-02", periods=len(labels))
    for sector in ["S1", "S2"]:
        for i, (date, label) in enumerate(zip(dates, labels, strict=False)):
            rows.append(
                {
                    "run_id": run_id,
                    "checkpoint_id": f"c{i // 5}",
                    "trade_date": date.date(),
                    "sector_code": sector,
                    "sector_name": sector,
                    "state_id": i % 4,
                    "state_label": label,
                    "state_probability": 0.8,
                    "state_phase": "early",
                    "state_age_days": i + 1,
                    "state_age_days_by_id": i + 1,
                    "state_age_days_by_label": i + 1,
                    "model_state_age_days": i + 1,
                    "label_state_age_days": i + 1,
                    "duration_model_age_days": i + 1,
                    "display_state_age_days": i + 1,
                    "duration_percentile": 0.5,
                    "expected_remaining_days": 4,
                    "p_stay_1d": 0.8,
                    "p_stay_3d": 0.6,
                    "p_stay_5d": 0.5,
                    "p_stay_10d": 0.2,
                    "p_exit_1d": 0.2,
                    "p_exit_3d": 0.4,
                    "p_exit_5d": 0.5,
                    "p_exit_10d": 0.8,
                    "p_exit_20d": 0.9,
                    "raw_p_exit_1d": 0.2 + (i % 5) * 0.02,
                    "raw_p_exit_3d": 0.3 + (i % 5) * 0.02,
                    "raw_p_exit_5d": 0.4 + (i % 5) * 0.02,
                    "raw_p_exit_10d": 0.5 + (i % 5) * 0.02,
                    "raw_p_exit_20d": 0.6 + (i % 5) * 0.02,
                    "duration_tail_status": "within_duration_support",
                    "raw_p_exit_1d_status": "available",
                    "raw_p_exit_3d_status": "available",
                    "raw_p_exit_5d_status": "available",
                    "raw_p_exit_10d_status": "available",
                    "raw_p_exit_20d_status": "available",
                    "p_exit_1d_status": "available",
                    "p_exit_3d_status": "available",
                    "p_exit_5d_status": "available",
                    "p_exit_10d_status": "available",
                    "p_exit_20d_status": "available",
                    "most_likely_next_state_id": (i + 1) % 4,
                    "most_likely_next_state_label": labels[min(i + 1, len(labels) - 1)],
                    "next_state_probability": 0.6,
                    "confidence": 0.7,
                    "train_start_date": dates[0].date(),
                    "train_end_date": date.date(),
                    "max_observation_date_used": date.date(),
                    "state_source": "causal_hsmm",
                    "feature_scope_id": "all",
                    "decode_mode": "causal_prefix_viterbi",
                    "snapshot_frequency": "daily",
                    "created_at": pd.Timestamp("2024-01-01"),
                }
            )
    df = pd.DataFrame(rows)
    storage.upsert_df("hsmm_state_daily", df, ["run_id", "trade_date", "sector_code"])
    return len(df)


def test_lifecycle_cli_outputs_and_ui_contract(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    expected_rows = _seed_states(storage)
    output = tmp_path / "display_lifecycle"

    result = write_lifecycle_ui_outputs(
        storage,
        "lifecycle_ui_run",
        output,
        horizons=(1, 3, 5),
        profile_mode="latest_asof",
        profile_cutoff_date="2024-02-01",
    )
    ui = result["lifecycle_ui_daily"]

    for filename in [
        "summary.md",
        "display_label_episodes.csv",
        "duration_profile_by_display_label.csv",
        "exit_tendency_profile.csv",
        "exit_tendency_distribution.csv",
        "exit_tendency_policy_audit.csv",
        "next_state_tendency_profile.csv",
        "next_state_tendency_by_phase.csv",
        "next_state_tendency_by_age_bucket.csv",
        "lifecycle_ui_daily.csv",
        "ui_field_policy.csv",
        "ui_text_policy_audit.csv",
        "profile_metadata.json",
        "config.json",
    ]:
        assert (output / filename).exists(), filename
    assert len(ui) == expected_rows
    assert not ui.duplicated(["run_id", "profile_mode", "trade_date", "sector_code"]).any()
    assert ui["profile_mode"].eq("latest_asof").all()
    for col in ["exit_tendency_1d", "exit_tendency_3d", "exit_tendency_5d"]:
        assert ui[col].isin(EXIT_TENDENCIES).all()
    assert ui["state_phase"].isin(["early", "mature", "late", "unknown"]).all()
    assert {"next_state_tendency_phase_aware", "next_state_tendency_age_bucket", "source_run_id"}.issubset(ui.columns)
    required_status_cols = {
        "duration_tail_status_1d",
        "duration_tail_status_3d",
        "duration_tail_status_5d",
        "raw_p_exit_1d_status",
        "raw_p_exit_3d_status",
        "raw_p_exit_5d_status",
        "p_exit_1d_status",
        "p_exit_3d_status",
        "p_exit_5d_status",
    }
    assert required_status_cols.issubset(ui.columns)
    assert ui["duration_tail_status_1d"].eq("within_duration_support").all()

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "not a price prediction" in summary
    assert "trading signal" in summary
    for forbidden in ["上涨概率", "买入", "卖出", "推荐"]:
        assert forbidden not in summary

    stored_ui = storage.read_df("SELECT COUNT(*) AS n FROM hsmm_lifecycle_ui_daily WHERE run_id = 'lifecycle_ui_run' AND profile_mode = 'latest_asof'")
    stored_eps = storage.read_df("SELECT COUNT(*) AS n FROM hsmm_display_label_episodes WHERE run_id = 'lifecycle_ui_run'")
    stored_meta = storage.read_df("SELECT COUNT(*) AS n FROM hsmm_lifecycle_profile_metadata WHERE run_id = 'lifecycle_ui_run'")
    stored_next = storage.read_df("SELECT COUNT(*) AS n FROM hsmm_next_state_tendency_profile WHERE run_id = 'lifecycle_ui_run'")
    stored_cols = storage.read_df(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'hsmm_lifecycle_ui_daily'
        """
    )
    persisted_status_cols = {
        f"duration_tail_status_{horizon}d"
        for horizon in (1, 3, 5, 10, 20)
    } | {
        f"raw_p_exit_{horizon}d_status"
        for horizon in (1, 3, 5, 10, 20)
    } | {
        f"p_exit_{horizon}d_status"
        for horizon in (1, 3, 5, 10, 20)
    }
    assert int(stored_ui.loc[0, "n"]) == expected_rows
    assert int(stored_eps.loc[0, "n"]) > 0
    assert int(stored_meta.loc[0, "n"]) == 1
    assert int(stored_next.loc[0, "n"]) >= 0
    assert persisted_status_cols.issubset(set(stored_cols["column_name"].astype(str)))
