from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.sector_rotation import (
    LineageMismatchError,
    _attach_feature_lineage_hash,
    _read_walk_forward_cache,
    _validate_state_feature_merge,
    _walk_forward_cache_key,
    _write_walk_forward_cache,
)
from src.data_pipeline.storage import DuckDBStorage


def _params(**overrides):
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
        "feature_scope_id": "scope-a",
        "feature_scope_type": "universe",
        "include_custom_baskets": True,
        "universe_id": "u1",
        "scope_type": "universe",
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


def _features(feature_lineage_hash="feature-a", feature_scope_id="scope-a", universe_id="u1", dates=None):
    dates = dates or [pd.Timestamp("2024-02-01")]
    features = pd.DataFrame(
        [
            {
                "sector_id": "industry:S",
                "trade_date": date,
                "ret_20d": 0.1,
                "rs_20d": 0.2,
                "amount_z_20d": 0.3,
                "vol_20d": 0.05,
                "drawdown_20d": -0.01,
                "ma20_slope": 0.02,
                "feature_version": "stage03pf",
                "feature_scope_id": feature_scope_id,
                "feature_scope_type": "universe",
            }
            for date in dates
        ]
    )
    return _attach_feature_lineage_hash(features, feature_lineage_hash, universe_id=universe_id)


def _states(feature_lineage_hash="feature-a", trade_date=pd.Timestamp("2024-02-01")):
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
                "max_observation_date_used": trade_date,
                "probability_type": "filtered",
                "state_source": "causal_backtest",
                "feature_lineage_hash": feature_lineage_hash,
            }
        ]
    )


def test_matching_feature_state_lineage_can_merge():
    _validate_state_feature_merge(_states(), _features(), _params())


def test_changed_current_features_hash_rejects_merge():
    with pytest.raises(LineageMismatchError, match="current features feature_lineage_hash mismatch"):
        _validate_state_feature_merge(_states(), _features(feature_lineage_hash="feature-b"), _params())


def test_universe_or_scope_change_rejects_merge():
    with pytest.raises(LineageMismatchError, match="current features feature_scope_id mismatch"):
        _validate_state_feature_merge(_states(), _features(feature_scope_id="scope-b"), _params())
    with pytest.raises(LineageMismatchError, match="current features universe_id mismatch"):
        _validate_state_feature_merge(_states(), _features(universe_id="u2"), _params())


def test_missing_feature_date_coverage_rejects_merge():
    with pytest.raises(LineageMismatchError, match="current features do not cover cached state dates"):
        _validate_state_feature_merge(_states(trade_date=pd.Timestamp("2024-02-02")), _features(), _params())


def test_legacy_cache_missing_feature_lineage_hash_is_rejected_for_backtest(tmp_path):
    storage = DuckDBStorage(tmp_path / "cache.duckdb")
    storage.init_schema()
    params = _params()
    cache_key = _walk_forward_cache_key(params)
    _write_walk_forward_cache(storage, cache_key, _states().drop(columns=["feature_lineage_hash"]), params, signal_count=1)
    lineage_hash = storage.read_df("SELECT lineage_hash FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key]).loc[0, "lineage_hash"]
    with storage.connect() as con:
        con.execute("UPDATE walk_forward_cache_runs SET feature_lineage_hash = NULL WHERE cache_key = ?", [cache_key])
        con.execute("UPDATE walk_forward_state_cache SET feature_lineage_hash = NULL WHERE cache_key = ?", [cache_key])

    states = _read_walk_forward_cache(
        storage,
        cache_key,
        expected_lineage_hash=str(lineage_hash),
        expected_feature_lineage_hash="feature-a",
        expected_feature_scope_id="scope-a",
        expected_universe_id="u1",
    )

    assert states.empty
