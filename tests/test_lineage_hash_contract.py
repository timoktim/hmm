from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.utils.lineage import build_model_lineage_payload, canonical_json, hash_payload, is_valid_cache_metadata


def _lineage_payload(**overrides):
    payload = build_model_lineage_payload(
        model_family="GaussianHMM",
        model_version="v1",
        code_version="abc123",
        feature_version="stage03pf",
        feature_scope_id="all",
        feature_columns=["ret_1d", "ret_5d", "vol_20d"],
        model_params={"n_states": 3, "random_state": 42, "n_iter": 100},
        preprocess_params={"min_train_rows": 120, "winsorize": False},
        train_window_policy={"train_window_days": 252, "retrain_frequency": "monthly"},
        state_date_policy={"mode": "rebalance_signals_v2"},
        universe_id="all",
        universe_membership_hash="universe-a",
        custom_basket_membership_hash="basket-a",
        data_snapshot_hash="snapshot-a",
        calendar_hash="calendar-a",
    )
    for key, value in overrides.items():
        if key == "model_params":
            payload[key] = {**payload[key], **value}
        elif key == "preprocess_params":
            payload[key] = {**payload[key], **value}
        else:
            payload[key] = value
    return payload


def test_canonical_json_and_hash_are_deterministic_for_key_order():
    payload_a = {
        "z": (3, 2, 1),
        "a": {"when": pd.Timestamp("2024-01-01"), "path": Path("data/db/a_share_hmm.duckdb")},
        "set": {"b", "a"},
        "dates": [date(2024, 1, 2), datetime(2024, 1, 3, 4, 5, 6)],
        "numpy": {"integer": np.int64(7), "floating": np.float64(1.25)},
    }
    payload_b = {
        "set": {"a", "b"},
        "dates": [date(2024, 1, 2), datetime(2024, 1, 3, 4, 5, 6)],
        "numpy": {"floating": np.float64(1.25), "integer": np.int64(7)},
        "a": {"path": Path("data/db/a_share_hmm.duckdb"), "when": pd.Timestamp("2024-01-01")},
        "z": (3, 2, 1),
    }

    assert canonical_json(payload_a) == canonical_json(payload_b)
    assert hash_payload(payload_a) == hash_payload(payload_b)


def test_feature_column_change_changes_hash():
    base = _lineage_payload()
    changed = _lineage_payload(feature_columns=["ret_1d", "ret_5d", "amount_z_20d"])

    assert hash_payload(base) != hash_payload(changed)


def test_training_and_preprocess_params_change_hash():
    base = _lineage_payload()

    assert hash_payload(base) != hash_payload(_lineage_payload(model_params={"random_state": 7}))
    assert hash_payload(base) != hash_payload(_lineage_payload(model_params={"n_iter": 200}))
    assert hash_payload(base) != hash_payload(_lineage_payload(preprocess_params={"min_train_rows": 240}))


def test_universe_membership_hash_change_changes_hash():
    base = _lineage_payload()
    changed = _lineage_payload(universe_membership_hash="universe-b")

    assert hash_payload(base) != hash_payload(changed)


def test_legacy_cache_without_lineage_hash_is_invalid_by_default():
    legacy_row = {"cache_key": "legacy", "cache_status": "completed", "lineage_hash": None}
    valid_row = {"cache_key": "valid", "cache_status": "completed", "lineage_hash": "abc123"}

    assert not is_valid_cache_metadata(legacy_row)
    assert is_valid_cache_metadata(valid_row)
    assert not is_valid_cache_metadata(valid_row, expected_lineage_hash="different")


def test_schema_migration_adds_lineage_columns_idempotently(tmp_path):
    db_path = tmp_path / "lineage.duckdb"
    storage = DuckDBStorage(db_path)
    storage.init_schema()
    storage.init_schema()

    con = duckdb.connect(str(db_path))
    try:
        cache_columns = set(con.execute("DESCRIBE walk_forward_cache_runs").fetchdf()["column_name"])
        state_columns = set(con.execute("DESCRIBE walk_forward_state_cache").fetchdf()["column_name"])
        hsmm_columns = set(con.execute("DESCRIBE hsmm_model_runs").fetchdf()["column_name"])
    finally:
        con.close()

    assert {
        "lineage_json",
        "lineage_hash",
        "feature_lineage_hash",
        "universe_membership_hash",
        "data_snapshot_hash",
        "cache_status",
        "completed_at",
    }.issubset(cache_columns)
    assert {"lineage_hash", "feature_lineage_hash"}.issubset(state_columns)
    assert {"lineage_json", "lineage_hash"}.issubset(hsmm_columns)
