from __future__ import annotations

import pytest
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage, HSMM_RUN_CASCADE_TABLES
from src.evaluation.hsmm_display_lifecycle import write_lifecycle_ui_outputs
from src.models import hsmm_walk_forward
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "hsmm_cascade.duckdb")
    storage.init_schema()
    return storage


def _insert_run_scoped_rows(storage: DuckDBStorage, run_id: str = "cascade_run") -> None:
    now = pd.Timestamp("2024-01-10")
    with storage.connect() as con:
        con.execute(
            """
            INSERT INTO hsmm_model_runs (run_id, model_family, model_version, created_at, run_status)
            VALUES (?, 'hsmm', 'hsmm_v1', ?, 'completed')
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_model_checkpoints (run_id, checkpoint_id, train_date, created_at)
            VALUES (?, 'checkpoint_1', DATE '2024-01-02', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_run_performance (run_id, checkpoint_id, created_at)
            VALUES (?, 'checkpoint_1', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_state_daily (
              run_id, checkpoint_id, trade_date, sector_code, sector_name, state_id,
              state_label, max_observation_date_used, state_source, created_at
            )
            VALUES (?, 'checkpoint_1', DATE '2024-01-03', 'S1', 'S1', 1,
                    'Trend', DATE '2024-01-03', 'causal_hsmm', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_state_episodes (
              run_id, sector_code, state_id, state_label, episode_id, start_date,
              end_date, duration_days, created_at
            )
            VALUES (?, 'S1', 1, 'Trend', 'episode_1', DATE '2024-01-03',
                    DATE '2024-01-03', 1, ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_parameters (run_id, created_at)
            VALUES (?, ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_display_label_episodes (
              run_id, sector_code, sector_name, state_label, episode_id, start_date,
              end_date, duration_days, created_at
            )
            VALUES (?, 'S1', 'S1', 'Trend', 'display_1', DATE '2024-01-03',
                    DATE '2024-01-03', 1, ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_ui_daily (
              run_id, profile_mode, state_date_policy, profile_cutoff_date,
              trade_date, sector_code, sector_name, state_label, created_at
            )
            VALUES (?, 'latest_asof', 'full_run', DATE '2024-01-05',
                    DATE '2024-01-03', 'S1', 'S1', 'Trend', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_profile_metadata (
              run_id, profile_run_id, profile_mode, profile_cutoff_date,
              state_date_policy, created_at
            )
            VALUES (?, 'profile_1', 'latest_asof', DATE '2024-01-05',
                    'full_run', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_duration_profile (
              run_id, profile_mode, profile_cutoff_date, state_label, created_at
            )
            VALUES (?, 'latest_asof', DATE '2024-01-05', 'Trend', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_next_state_tendency_profile (
              run_id, profile_mode, profile_cutoff_date, state_label,
              state_phase, age_bucket, created_at
            )
            VALUES (?, 'latest_asof', DATE '2024-01-05', 'Trend',
                    '__ALL__', '__ALL__', ?)
            """,
            [run_id, now],
        )


def _count_run_rows(storage: DuckDBStorage, table: str, run_id: str = "cascade_run") -> int:
    return int(storage.read_df(f"SELECT COUNT(*) AS n FROM {table} WHERE run_id = ?", [run_id]).loc[0, "n"])


def _mock_hsmm_inputs(monkeypatch) -> None:
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    ohlcv = pd.DataFrame({"sector_id": ["S1"] * len(dates), "trade_date": dates})
    features = pd.DataFrame({"sector_id": ["S1"] * len(dates), "trade_date": dates})
    for column in hsmm_walk_forward.HSMM_FEATURE_COLUMNS:
        features[column] = 0.0
    monkeypatch.setattr(hsmm_walk_forward, "load_sector_like_ohlcv", lambda *args, **kwargs: ohlcv)
    monkeypatch.setattr(hsmm_walk_forward, "feature_scope_for_universe", lambda *args, **kwargs: ("all", "all"))
    monkeypatch.setattr(hsmm_walk_forward, "build_hsmm_features", lambda *args, **kwargs: features.copy())


def _walk_forward_config(tmp_path, *, overwrite: bool = False) -> HSMMWalkForwardConfig:
    return HSMMWalkForwardConfig(
        db_path=str(tmp_path / "hsmm_cascade.duckdb"),
        start_date="2024-01-02",
        end_date="2024-01-04",
        train_frequency="every_n_trade_days",
        train_every_n_trade_days=1,
        min_sequence_length=50,
        min_train_sequences=50,
        run_id="cascade_run",
        overwrite=overwrite,
    )


def _seed_lifecycle_states(storage: DuckDBStorage, run_id: str = "lifecycle_rerun") -> None:
    labels = ["Stress", "Stress", "Neutral", "Neutral", "Trend", "Trend"]
    rows = []
    for sector in ["S1", "S2"]:
        for idx, date in enumerate(pd.bdate_range("2024-01-02", periods=len(labels))):
            rows.append(
                {
                    "run_id": run_id,
                    "checkpoint_id": "checkpoint_1",
                    "trade_date": date.date(),
                    "sector_code": sector,
                    "sector_name": sector,
                    "state_id": idx % 3,
                    "state_label": labels[idx],
                    "state_age_days": idx + 1,
                    "state_age_days_by_id": idx + 1,
                    "state_age_days_by_label": idx + 1,
                    "model_state_age_days": idx + 1,
                    "label_state_age_days": idx + 1,
                    "duration_model_age_days": idx + 1,
                    "display_state_age_days": idx + 1,
                    "max_observation_date_used": date.date(),
                    "state_source": "causal_hsmm",
                    "feature_scope_id": "all",
                    "decode_mode": "causal_prefix_viterbi",
                    "snapshot_frequency": "daily",
                    "created_at": pd.Timestamp("2024-01-10"),
                }
            )
    storage.upsert_df("hsmm_state_daily", pd.DataFrame(rows), ["run_id", "trade_date", "sector_code"])


def _insert_stale_lifecycle_profile_rows(storage: DuckDBStorage, run_id: str = "lifecycle_rerun") -> None:
    now = pd.Timestamp("2024-01-10")
    with storage.connect() as con:
        con.execute(
            """
            INSERT INTO hsmm_display_label_episodes (
              run_id, sector_code, sector_name, state_label, episode_id, start_date,
              end_date, duration_days, created_at
            )
            VALUES (?, 'STALE', 'STALE', 'Stale', 'stale_episode', DATE '2023-01-01',
                    DATE '2023-01-01', 1, ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_ui_daily (
              run_id, profile_mode, state_date_policy, profile_cutoff_date,
              trade_date, sector_code, sector_name, state_label, created_at
            )
            VALUES (?, 'latest_asof', 'full_run', DATE '2024-01-12',
                    DATE '2023-01-01', 'STALE', 'STALE', 'Stale', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_profile_metadata (
              run_id, profile_run_id, profile_mode, profile_cutoff_date,
              state_date_policy, created_at
            )
            VALUES (?, 'stale_profile', 'latest_asof', DATE '2024-01-12',
                    'full_run', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_lifecycle_duration_profile (
              run_id, profile_mode, profile_cutoff_date, state_label, created_at
            )
            VALUES (?, 'latest_asof', DATE '2024-01-12', 'Stale', ?)
            """,
            [run_id, now],
        )
        con.execute(
            """
            INSERT INTO hsmm_next_state_tendency_profile (
              run_id, profile_mode, profile_cutoff_date, state_label,
              state_phase, age_bucket, created_at
            )
            VALUES (?, 'latest_asof', DATE '2024-01-12', 'Stale',
                    '__ALL__', '__ALL__', ?)
            """,
            [run_id, now],
        )


def test_clear_hsmm_run_cascade_removes_all_run_scoped_rows(tmp_path):
    storage = _storage(tmp_path)
    _insert_run_scoped_rows(storage)

    summary = storage.clear_hsmm_run_cascade("cascade_run")

    assert set(summary["tables"]) == set(HSMM_RUN_CASCADE_TABLES)
    for table in [
        "hsmm_state_daily",
        "hsmm_state_episodes",
        "hsmm_model_checkpoints",
        "hsmm_run_performance",
        "hsmm_parameters",
        "hsmm_model_runs",
        "hsmm_display_label_episodes",
        "hsmm_lifecycle_ui_daily",
        "hsmm_lifecycle_profile_metadata",
        "hsmm_lifecycle_duration_profile",
        "hsmm_next_state_tendency_profile",
    ]:
        assert _count_run_rows(storage, table) == 0
        assert summary["tables"][table]["deleted_count"] == 1


def test_duplicate_completed_run_id_fails_by_default(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _mock_hsmm_inputs(monkeypatch)
    _insert_run_scoped_rows(storage)

    with pytest.raises(ValueError, match="already completed"):
        run_hsmm_walk_forward(_walk_forward_config(tmp_path), storage=storage)


def test_overwrite_cleans_first_and_then_writes_completed_run(tmp_path, monkeypatch):
    storage = _storage(tmp_path)
    _mock_hsmm_inputs(monkeypatch)
    _insert_run_scoped_rows(storage)

    result = run_hsmm_walk_forward(_walk_forward_config(tmp_path, overwrite=True), storage=storage)

    assert result["cleanup_summary"]["deleted_total"] > 0
    stale_ui = _count_run_rows(storage, "hsmm_lifecycle_ui_daily")
    assert stale_ui == 0
    run = storage.read_df("SELECT run_status FROM hsmm_model_runs WHERE run_id = 'cascade_run'")
    assert run.loc[0, "run_status"] == "completed"


def test_lifecycle_report_rerun_does_not_keep_old_profile_rows(tmp_path):
    storage = _storage(tmp_path)
    _seed_lifecycle_states(storage)
    _insert_stale_lifecycle_profile_rows(storage)

    result = write_lifecycle_ui_outputs(
        storage,
        "lifecycle_rerun",
        tmp_path / "lifecycle",
        horizons=(1, 3),
        profile_mode="latest_asof",
        profile_cutoff_date="2024-01-12",
        state_date_policy="full_run",
    )

    cleanup = result["lifecycle_cleanup_summary"]
    assert cleanup["hsmm_lifecycle_ui_daily"] == 1
    assert cleanup["hsmm_lifecycle_profile_metadata"] == 1
    assert cleanup["hsmm_lifecycle_duration_profile"] == 1
    assert cleanup["hsmm_next_state_tendency_profile"] == 1
    assert cleanup["hsmm_display_label_episodes"] == 1
    for table, predicate in [
        ("hsmm_display_label_episodes", "sector_code = 'STALE'"),
        ("hsmm_lifecycle_ui_daily", "sector_code = 'STALE'"),
        ("hsmm_lifecycle_profile_metadata", "profile_run_id = 'stale_profile'"),
        ("hsmm_lifecycle_duration_profile", "state_label = 'Stale'"),
        ("hsmm_next_state_tendency_profile", "state_label = 'Stale'"),
    ]:
        count = storage.read_df(f"SELECT COUNT(*) AS n FROM {table} WHERE run_id = 'lifecycle_rerun' AND {predicate}")
        assert int(count.loc[0, "n"]) == 0
