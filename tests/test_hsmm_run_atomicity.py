from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_display_lifecycle import read_hsmm_states
from src.models import hsmm_walk_forward
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward
from src.ui.lifecycle_page import _latest_lifecycle_run


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "hsmm_atomicity.duckdb")
    storage.init_schema()
    return storage


def _seed_run(storage: DuckDBStorage, run_id: str, status: str, created_at: str = "2024-01-01") -> None:
    storage.upsert_df(
        "hsmm_model_runs",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "model_family": "hsmm",
                    "model_version": "hsmm_v1",
                    "created_at": pd.Timestamp(created_at),
                    "run_status": status,
                }
            ]
        ),
        ["run_id"],
    )


def _seed_state(storage: DuckDBStorage, run_id: str, created_at: str = "2024-01-01") -> None:
    storage.upsert_df(
        "hsmm_state_daily",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "trade_date": pd.Timestamp("2024-01-02").date(),
                    "sector_code": "S1",
                    "sector_name": "S1",
                    "state_id": 1,
                    "state_label": "Trend",
                    "max_observation_date_used": pd.Timestamp("2024-01-02").date(),
                    "state_source": "causal_hsmm",
                    "created_at": pd.Timestamp(created_at),
                }
            ]
        ),
        ["run_id", "trade_date", "sector_code"],
    )


def _seed_lifecycle_ui(storage: DuckDBStorage, run_id: str, created_at: str) -> None:
    storage.upsert_df(
        "hsmm_lifecycle_ui_daily",
        pd.DataFrame(
            [
                {
                    "run_id": run_id,
                    "profile_mode": "latest_asof",
                    "state_date_policy": "full_run",
                    "profile_cutoff_date": pd.Timestamp("2024-01-02").date(),
                    "trade_date": pd.Timestamp("2024-01-02").date(),
                    "sector_code": "S1",
                    "sector_name": "S1",
                    "state_label": "Trend",
                    "created_at": pd.Timestamp(created_at),
                }
            ]
        ),
        ["run_id", "profile_mode", "profile_cutoff_date", "state_date_policy", "trade_date", "sector_code"],
    )


def test_read_hsmm_states_hides_running_and_failed_runs(tmp_path):
    storage = _storage(tmp_path)
    for run_id, status in [("running_run", "running"), ("failed_run", "failed")]:
        _seed_run(storage, run_id, status)
        _seed_state(storage, run_id)

    assert read_hsmm_states(storage, "running_run").empty
    assert read_hsmm_states(storage, "failed_run").empty
    assert not read_hsmm_states(storage, "running_run", require_completed=False).empty


def test_completed_run_is_readable(tmp_path):
    storage = _storage(tmp_path)
    _seed_run(storage, "completed_run", "completed")
    _seed_state(storage, "completed_run")

    states = read_hsmm_states(storage, "completed_run")

    assert len(states) == 1
    assert states.loc[0, "run_id"] == "completed_run"


def test_lifecycle_latest_selector_uses_completed_runs_only(tmp_path):
    storage = _storage(tmp_path)
    _seed_run(storage, "completed_run", "completed")
    _seed_run(storage, "failed_run", "failed")
    _seed_run(storage, "running_run", "running")
    _seed_lifecycle_ui(storage, "completed_run", "2024-01-01")
    _seed_lifecycle_ui(storage, "failed_run", "2024-01-03")
    _seed_lifecycle_ui(storage, "running_run", "2024-01-04")

    assert _latest_lifecycle_run(storage) == "completed_run"


def test_hsmm_walk_forward_marks_failed_on_exception(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    ohlcv = pd.DataFrame({"sector_id": ["S1"] * len(dates), "trade_date": dates})
    features = pd.DataFrame(
        {
            "sector_id": ["S1"] * len(dates),
            "trade_date": dates,
            "ret_1d": 0.0,
            "ret_5d": 0.0,
            "ret_20d": 0.0,
            "vol_20d": 1.0,
            "amount_z_20d": 0.0,
            "rs_20d": 0.0,
            "drawdown_20d": 0.0,
            "ma20_slope": 0.0,
        }
    )

    monkeypatch.setattr(hsmm_walk_forward, "load_sector_like_ohlcv", lambda *args, **kwargs: ohlcv)
    monkeypatch.setattr(hsmm_walk_forward, "feature_scope_for_universe", lambda *args, **kwargs: ("all", "all"))
    monkeypatch.setattr(hsmm_walk_forward, "build_hsmm_features", lambda *args, **kwargs: features.copy())

    def _raise_training_sequences(*args, **kwargs):
        raise RuntimeError("synthetic training failure")

    monkeypatch.setattr(hsmm_walk_forward, "_training_sequences", _raise_training_sequences)

    config = HSMMWalkForwardConfig(
        db_path=str(tmp_path / "hsmm_atomicity.duckdb"),
        start_date="2024-01-02",
        end_date="2024-01-05",
        train_frequency="every_n_trade_days",
        train_every_n_trade_days=1,
        min_sequence_length=1,
        min_train_sequences=1,
        run_id="failed_atomic_run",
    )
    try:
        run_hsmm_walk_forward(config, storage=storage)
    except RuntimeError as exc:
        assert "synthetic training failure" in str(exc)
    else:
        raise AssertionError("expected synthetic training failure")

    run = storage.read_df(
        """
        SELECT run_status, started_at, completed_at, failed_at, failure_message,
               expected_snapshot_count, actual_state_row_count
        FROM hsmm_model_runs
        WHERE run_id = 'failed_atomic_run'
        """
    )
    assert run.loc[0, "run_status"] == "failed"
    assert pd.notna(run.loc[0, "started_at"])
    assert pd.isna(run.loc[0, "completed_at"])
    assert pd.notna(run.loc[0, "failed_at"])
    assert "synthetic training failure" in run.loc[0, "failure_message"]
    assert int(run.loc[0, "expected_snapshot_count"]) == 4
    assert int(run.loc[0, "actual_state_row_count"]) == 0
