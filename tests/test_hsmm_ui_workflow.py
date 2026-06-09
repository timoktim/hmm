from __future__ import annotations

import inspect

import pandas as pd
import pytest

from src.data_pipeline.storage import DuckDBStorage
from src.ui import model_training_page


def test_hsmm_horizon_parser_deduplicates_and_accepts_chinese_comma() -> None:
    assert model_training_page._parse_hsmm_horizons("1, 3，5,3") == (1, 3, 5)


@pytest.mark.parametrize("value", ["", "1,x", "0", "251"])
def test_hsmm_horizon_parser_rejects_invalid_values(value: str) -> None:
    with pytest.raises(ValueError):
        model_training_page._parse_hsmm_horizons(value)


def test_hsmm_lifecycle_output_dir_is_stable_and_sanitized() -> None:
    path = model_training_page._hsmm_lifecycle_output_dir("run/a b", "latest_asof", "full_run")

    assert str(path) == "reports/hsmm_display_lifecycle/run_a_b_latest_asof_full_run"


def test_hsmm_run_summary_includes_lifecycle_rows(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "hsmm_ui.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "hsmm_model_runs",
        pd.DataFrame(
            [
                {
                    "run_id": "hsmm_completed",
                    "model_family": "HSMM",
                    "model_version": "hsmm_v1",
                    "created_at": pd.Timestamp("2024-03-01"),
                    "completed_at": pd.Timestamp("2024-03-02"),
                    "run_status": "completed",
                    "start_date": pd.Timestamp("2024-01-01").date(),
                    "end_date": pd.Timestamp("2024-02-01").date(),
                    "n_states": 4,
                    "max_duration": 60,
                    "train_window_days": 120,
                    "actual_snapshot_count": 20,
                    "actual_state_row_count": 80,
                }
            ]
        ),
        ["run_id"],
    )
    storage.upsert_df(
        "hsmm_lifecycle_ui_daily",
        pd.DataFrame(
            [
                {
                    "run_id": "hsmm_completed",
                    "profile_mode": "latest_asof",
                    "state_date_policy": "full_run",
                    "profile_cutoff_date": pd.Timestamp("2024-02-01").date(),
                    "trade_date": pd.Timestamp("2024-02-01").date(),
                    "sector_code": "S1",
                    "state_label": "TrendUp",
                    "created_at": pd.Timestamp("2024-03-03"),
                },
                {
                    "run_id": "hsmm_completed",
                    "profile_mode": "latest_asof",
                    "state_date_policy": "full_run",
                    "profile_cutoff_date": pd.Timestamp("2024-02-01").date(),
                    "trade_date": pd.Timestamp("2024-02-01").date(),
                    "sector_code": "S2",
                    "state_label": "Neutral",
                    "created_at": pd.Timestamp("2024-03-03"),
                },
            ]
        ),
        ["run_id", "profile_mode", "profile_cutoff_date", "state_date_policy", "trade_date", "sector_code"],
    )

    summary = model_training_page._load_hsmm_run_summary(storage)

    assert len(summary) == 1
    assert summary.loc[0, "run_id"] == "hsmm_completed"
    assert int(summary.loc[0, "lifecycle_ui_rows"]) == 2
    assert int(summary.loc[0, "actual_state_row_count"]) == 80


def test_model_training_page_exposes_hsmm_lifecycle_actions() -> None:
    source = inspect.getsource(model_training_page.render_model_training)

    assert "HSMM 生命周期" in source
    assert "运行 HSMM walk-forward 并生成生命周期 UI 数据" in source
    assert "仅生成生命周期 UI 数据" in source
    assert "run_hsmm_walk_forward" in source
    assert "_write_hsmm_lifecycle_for_ui" in source
