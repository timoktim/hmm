from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.sector_rotation import _read_walk_forward_cache, _walk_forward_cache_key, _write_walk_forward_cache
from src.data_pipeline.storage import DuckDBStorage


def _base_params(**overrides):
    params = {
        "n_states": 3,
        "train_window_days": 120,
        "retrain_frequency": "monthly",
        "random_state": 42,
        "n_iter": 300,
        "tol": 0.01,
        "min_train_rows": 120,
        "min_sequence_length": 30,
        "feature_columns": ["ret_1d", "ret_5d", "vol_20d"],
        "feature_version": "stage03pf",
        "feature_scope_id": "all",
        "feature_scope_type": "all",
        "include_custom_baskets": True,
        "universe_id": "all",
        "scope_type": "all",
        "state_date_mode": "rebalance_signals_v2",
        "rebalance_days": 5,
        "start_date": pd.Timestamp("2024-01-01").date(),
        "end_date": pd.Timestamp("2024-03-01").date(),
        "data_snapshot_hash": "data-a",
        "universe_membership_hash": "universe-a",
        "custom_basket_membership_hash": "custom-a",
        "calendar_hash": "calendar-a",
        "feature_lineage_hash": "feature-a",
    }
    params.update(overrides)
    return params


def _state_rows(max_observation_date_used=None):
    trade_date = pd.Timestamp("2024-02-01")
    return pd.DataFrame(
        [
            {
                "sector_id": "industry:S",
                "trade_date": trade_date,
                "state_id": 0,
                "state_label": "TrendUp",
                "prob_trend_up": 0.8,
                "prob_neutral": 0.1,
                "prob_risk_off": 0.1,
                "next_state_probs_json": "{}",
                "train_start": pd.Timestamp("2024-01-01"),
                "train_end": trade_date,
                "max_observation_date_used": max_observation_date_used or trade_date,
                "probability_type": "filtered",
                "state_source": "causal_backtest",
            }
        ]
    )


def _seed_completed_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "cache.duckdb")
    storage.init_schema()
    params = _base_params()
    cache_key = _walk_forward_cache_key(params)
    _write_walk_forward_cache(storage, cache_key, _state_rows(), params, signal_count=1)
    metadata = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key]).iloc[0]
    return storage, cache_key, str(metadata["lineage_hash"])


def test_cache_key_changes_when_n_iter_changes():
    assert _walk_forward_cache_key(_base_params()) != _walk_forward_cache_key(_base_params(n_iter=301))


def test_cache_key_changes_when_feature_columns_change():
    assert _walk_forward_cache_key(_base_params()) != _walk_forward_cache_key(_base_params(feature_columns=["ret_1d", "rs_20d"]))


def test_cache_key_changes_when_random_state_changes():
    assert _walk_forward_cache_key(_base_params()) != _walk_forward_cache_key(_base_params(random_state=7))


def test_write_then_read_completed_cache_with_lineage(tmp_path):
    storage, cache_key, lineage_hash = _seed_completed_cache(tmp_path)

    states = _read_walk_forward_cache(storage, cache_key, expected_lineage_hash=lineage_hash)
    metadata = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key]).iloc[0]
    state_metadata = storage.read_df("SELECT lineage_hash, feature_lineage_hash FROM walk_forward_state_cache WHERE cache_key = ?", [cache_key])

    assert cache_key.endswith(lineage_hash)
    assert metadata["cache_status"] == "completed"
    assert metadata["lineage_json"]
    assert metadata["feature_lineage_hash"] == "feature-a"
    assert not states.empty
    assert state_metadata["lineage_hash"].eq(lineage_hash).all()
    assert state_metadata["feature_lineage_hash"].eq("feature-a").all()


def test_running_cache_is_rejected(tmp_path):
    storage, cache_key, lineage_hash = _seed_completed_cache(tmp_path)
    with storage.connect() as con:
        con.execute("UPDATE walk_forward_cache_runs SET cache_status = 'running' WHERE cache_key = ?", [cache_key])

    assert _read_walk_forward_cache(storage, cache_key, expected_lineage_hash=lineage_hash).empty


def test_mismatched_lineage_hash_is_rejected(tmp_path):
    storage, cache_key, _ = _seed_completed_cache(tmp_path)

    assert _read_walk_forward_cache(storage, cache_key, expected_lineage_hash="different").empty


def test_future_observation_boundary_is_rejected(tmp_path):
    storage, cache_key, lineage_hash = _seed_completed_cache(tmp_path)
    with storage.connect() as con:
        con.execute("UPDATE walk_forward_state_cache SET max_observation_date_used = DATE '2024-02-02' WHERE cache_key = ?", [cache_key])

    assert _read_walk_forward_cache(storage, cache_key, expected_lineage_hash=lineage_hash).empty


def test_legacy_cache_without_lineage_hash_is_rejected(tmp_path):
    storage, cache_key, lineage_hash = _seed_completed_cache(tmp_path)
    with storage.connect() as con:
        con.execute("UPDATE walk_forward_cache_runs SET lineage_hash = NULL WHERE cache_key = ?", [cache_key])

    assert _read_walk_forward_cache(storage, cache_key, expected_lineage_hash=lineage_hash).empty


def test_row_count_mismatch_is_rejected(tmp_path):
    storage, cache_key, lineage_hash = _seed_completed_cache(tmp_path)
    with storage.connect() as con:
        con.execute("UPDATE walk_forward_cache_runs SET row_count = 2 WHERE cache_key = ?", [cache_key])

    assert _read_walk_forward_cache(storage, cache_key, expected_lineage_hash=lineage_hash).empty


def test_state_write_failure_does_not_leave_completed_metadata(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "cache.duckdb")
    storage.init_schema()
    params = _base_params()
    cache_key = _walk_forward_cache_key(params)
    original_upsert = storage.upsert_df

    def failing_upsert(table, df, key_cols):
        if table == "walk_forward_state_cache":
            raise RuntimeError("state write failed")
        return original_upsert(table, df, key_cols)

    monkeypatch.setattr(storage, "upsert_df", failing_upsert)

    with pytest.raises(RuntimeError, match="state write failed"):
        _write_walk_forward_cache(storage, cache_key, _state_rows(), params, signal_count=1)

    metadata = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key])
    assert metadata.empty
