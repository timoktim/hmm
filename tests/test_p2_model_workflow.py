from __future__ import annotations

import inspect

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.ui import backtest_page, model_evaluation_page, model_training_page
from src.ui.components.model_workflow import build_model_workflow_status


def test_model_workflow_status_without_run(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()

    status = build_model_workflow_status(storage)

    assert status.scope_label == "全市场"
    assert status.sector_run_id is None
    assert status.causal_cache_key is None
    assert "训练板块 HMM" in status.next_action


def test_model_workflow_status_with_run_and_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    date = pd.Timestamp("2024-02-01").date()
    storage.upsert_df(
        "model_runs",
        pd.DataFrame(
            [
                {
                    "run_id": "run1",
                    "model_type": "GaussianHMM",
                    "n_states": 3,
                    "train_start": date,
                    "train_end": date,
                    "feature_version": "v",
                    "model_path": "",
                    "scaler_path": "",
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "feature_scope_id": "all",
                    "feature_scope_type": "all",
                    "created_at": pd.Timestamp("2024-02-01"),
                    "metrics_json": "{}",
                }
            ]
        ),
        ["run_id"],
    )
    storage.upsert_df(
        "walk_forward_cache_runs",
        pd.DataFrame(
            [
                {
                    "cache_key": "cache1",
                    "n_states": 3,
                    "train_window_days": 120,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": date,
                    "end_date": date,
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": "all",
                    "signal_count": 1,
                    "row_count": 10,
                    "created_at": pd.Timestamp("2024-02-02"),
                }
            ]
        ),
        ["cache_key"],
    )

    status = build_model_workflow_status(storage)

    assert status.sector_run_id == "run1"
    assert status.causal_cache_key == "cache1"
    assert status.causal_cache_rows == 10
    assert "评估" in status.next_action or "大盘" in status.next_action


def test_model_workflow_pages_render_common_component():
    assert "render_model_workflow" in inspect.getsource(model_training_page.render_model_training)
    assert "render_model_workflow" in inspect.getsource(model_evaluation_page.render_model_evaluation)
    assert "render_model_workflow" in inspect.getsource(backtest_page.render_backtest)
