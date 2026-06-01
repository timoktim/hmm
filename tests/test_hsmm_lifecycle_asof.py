from __future__ import annotations

import json

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_display_lifecycle import filter_profile_episodes, write_lifecycle_ui_outputs


def _episodes() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "run_id": "r",
                "sector_code": "S1",
                "state_label": "Stress",
                "episode_end_date": pd.Timestamp("2024-01-10"),
                "duration_trading_days": 5,
                "is_left_censored": False,
                "is_right_censored": False,
                "is_open_episode": False,
            },
            {
                "run_id": "r",
                "sector_code": "S1",
                "state_label": "Neutral",
                "episode_end_date": pd.Timestamp("2024-02-10"),
                "duration_trading_days": 8,
                "is_left_censored": False,
                "is_right_censored": False,
                "is_open_episode": False,
            },
            {
                "run_id": "r",
                "sector_code": "S1",
                "state_label": "Trend",
                "episode_end_date": pd.Timestamp("2024-03-10"),
                "duration_trading_days": 13,
                "is_left_censored": False,
                "is_right_censored": False,
                "is_open_episode": False,
            },
        ]
    )


def _seed_states(storage: DuckDBStorage, run_id: str = "asof_run") -> None:
    labels = ["Stress", "Stress", "Neutral", "Neutral", "Trend", "Trend", "Stress", "Stress"]
    dates = pd.bdate_range("2024-01-02", periods=len(labels))
    rows = []
    for i, (date, label) in enumerate(zip(dates, labels, strict=False)):
        rows.append(
            {
                "run_id": run_id,
                "checkpoint_id": f"c{i // 2}",
                "trade_date": date.date(),
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": i % 3,
                "state_label": label,
                "raw_p_exit_1d": 0.2,
                "max_observation_date_used": date.date(),
                "state_source": "causal_hsmm",
                "created_at": pd.Timestamp("2024-01-01"),
            }
        )
    storage.upsert_df("hsmm_state_daily", pd.DataFrame(rows), ["run_id", "trade_date", "sector_code"])


def test_latest_asof_uses_only_completed_episodes_before_cutoff():
    filtered = filter_profile_episodes(_episodes(), "latest_asof", "2024-02-01")

    assert filtered["episode_end_date"].max() < pd.Timestamp("2024-02-01")
    assert filtered["state_label"].tolist() == ["Stress"]


def test_retrospective_uses_full_run():
    filtered = filter_profile_episodes(_episodes(), "retrospective", "2024-02-01")

    assert filtered["state_label"].tolist() == ["Stress", "Neutral", "Trend"]


def test_profile_metadata_contains_cutoff(tmp_path):
    storage = DuckDBStorage(tmp_path / "asof.duckdb")
    storage.init_schema()
    _seed_states(storage)
    output = tmp_path / "out"

    write_lifecycle_ui_outputs(
        storage,
        "asof_run",
        output,
        horizons=(1,),
        profile_mode="latest_asof",
        profile_cutoff_date="2024-01-10",
    )
    metadata = json.loads((output / "profile_metadata.json").read_text(encoding="utf-8"))

    assert metadata["profile_mode"] == "latest_asof"
    assert metadata["profile_cutoff_date"] == "2024-01-10"
