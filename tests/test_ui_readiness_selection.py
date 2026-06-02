from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.ui.components.model_workflow import build_model_workflow_status
from src.ui.lifecycle_page import _latest_lifecycle_run
from src.ui.run_context import latest_completed_hsmm_lifecycle_run, list_completed_hsmm_lifecycle_profiles
from src.ui.state_screener_page import walk_forward_cache_options_for_scope


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "wp9_ui_selection.duckdb")
    storage.init_schema()
    return storage


def _seed_hsmm_run(storage: DuckDBStorage, run_id: str, status: str, created_at: str) -> None:
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
                    "lineage_hash": f"lineage-{run_id}",
                }
            ]
        ),
        ["run_id"],
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
                    "profile_cutoff_date": pd.Timestamp("2024-01-05").date(),
                    "trade_date": pd.Timestamp("2024-01-05").date(),
                    "sector_code": "S1",
                    "sector_name": "S1",
                    "state_label": "Trend",
                    "created_at": pd.Timestamp(created_at),
                }
            ]
        ),
        ["run_id", "profile_mode", "profile_cutoff_date", "state_date_policy", "trade_date", "sector_code"],
    )


def _seed_profile(storage: DuckDBStorage, run_id: str, created_at: str, readiness_status: str | None = None) -> None:
    row = {
        "run_id": run_id,
        "profile_run_id": f"{run_id}:latest_asof:2024-01-05:full_run",
        "profile_mode": "latest_asof",
        "profile_cutoff_date": pd.Timestamp("2024-01-05").date(),
        "state_date_policy": "full_run",
        "completed_episode_count": 10,
        "created_at": pd.Timestamp(created_at),
    }
    if readiness_status is not None:
        row["readiness_status"] = readiness_status
    storage.upsert_df("hsmm_lifecycle_profile_metadata", pd.DataFrame([row]), ["run_id", "profile_run_id"])


def _seed_cache(storage: DuckDBStorage, cache_key: str, *, universe_id: str | None = None, valid: bool = True) -> None:
    lineage_hash = "lineage-a" if valid else None
    feature_lineage_hash = "feature-a" if valid else None
    storage.upsert_df(
        "walk_forward_cache_runs",
        pd.DataFrame(
            [
                {
                    "cache_key": cache_key,
                    "n_states": 3,
                    "train_window_days": 60,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": pd.Timestamp("2024-01-01").date(),
                    "end_date": pd.Timestamp("2024-01-03").date(),
                    "universe_id": universe_id,
                    "scope_type": "universe" if universe_id else "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": universe_id or "all",
                    "lineage_hash": lineage_hash,
                    "feature_lineage_hash": feature_lineage_hash,
                    "cache_status": "completed" if valid else None,
                    "signal_count": 1,
                    "row_count": 1,
                    "created_at": pd.Timestamp("2024-02-01"),
                }
            ]
        ),
        ["cache_key"],
    )
    storage.upsert_df(
        "walk_forward_state_cache",
        pd.DataFrame(
            [
                {
                    "cache_key": cache_key,
                    "sector_id": "S1",
                    "trade_date": pd.Timestamp("2024-01-03").date(),
                    "state_id": 1,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "max_observation_date_used": pd.Timestamp("2024-01-03").date(),
                    "state_source": "causal_backtest",
                    "lineage_hash": lineage_hash,
                    "feature_lineage_hash": feature_lineage_hash,
                }
            ]
        ),
        ["cache_key", "sector_id", "trade_date"],
    )


def test_latest_lifecycle_selector_ignores_running_failed_and_missing_profile(tmp_path) -> None:
    storage = _storage(tmp_path)
    for run_id, status, created_at in [
        ("completed_with_profile", "completed", "2024-01-01"),
        ("completed_missing_profile", "completed", "2024-01-04"),
        ("running_with_profile", "running", "2024-01-05"),
        ("failed_with_profile", "failed", "2024-01-06"),
    ]:
        _seed_hsmm_run(storage, run_id, status, created_at)
        _seed_lifecycle_ui(storage, run_id, created_at)
    _seed_profile(storage, "completed_with_profile", "2024-01-01")
    _seed_profile(storage, "running_with_profile", "2024-01-05")
    _seed_profile(storage, "failed_with_profile", "2024-01-06")

    assert latest_completed_hsmm_lifecycle_run(storage) == "completed_with_profile"
    assert _latest_lifecycle_run(storage, require_profile_metadata=True) == "completed_with_profile"


def test_lifecycle_selector_ignores_invalid_readiness_metadata(tmp_path) -> None:
    storage = _storage(tmp_path)
    with storage.connect() as con:
        con.execute("ALTER TABLE hsmm_lifecycle_profile_metadata ADD COLUMN IF NOT EXISTS readiness_status TEXT")
    _seed_hsmm_run(storage, "valid_run", "completed", "2024-01-01")
    _seed_hsmm_run(storage, "invalid_run", "completed", "2024-01-03")
    _seed_lifecycle_ui(storage, "valid_run", "2024-01-01")
    _seed_lifecycle_ui(storage, "invalid_run", "2024-01-03")
    _seed_profile(storage, "valid_run", "2024-01-01", readiness_status="internal_only")
    _seed_profile(storage, "invalid_run", "2024-01-03", readiness_status="invalid")

    profiles = list_completed_hsmm_lifecycle_profiles(storage)

    assert profiles["run_id"].tolist() == ["valid_run"]
    assert latest_completed_hsmm_lifecycle_run(storage) == "valid_run"


def test_state_screener_cache_options_hide_legacy_by_default(tmp_path) -> None:
    storage = _storage(tmp_path)
    _seed_cache(storage, "valid_cache", valid=True)
    _seed_cache(storage, "legacy_cache", valid=False)

    default_options = walk_forward_cache_options_for_scope(storage)
    debug_options = walk_forward_cache_options_for_scope(storage, include_legacy_debug=True)

    assert default_options["cache_key"].tolist() == ["valid_cache"]
    assert set(debug_options["cache_key"]) == {"valid_cache", "legacy_cache"}
    assert debug_options.set_index("cache_key").loc["legacy_cache", "legacy_debug_allowed"]


def test_model_workflow_uses_only_valid_cache(tmp_path) -> None:
    storage = _storage(tmp_path)
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
    _seed_cache(storage, "legacy_cache", valid=False)

    status_without_valid_cache = build_model_workflow_status(storage)
    assert status_without_valid_cache.causal_cache_key is None

    _seed_cache(storage, "valid_cache", valid=True)
    status_with_valid_cache = build_model_workflow_status(storage)

    assert status_with_valid_cache.causal_cache_key == "valid_cache"
