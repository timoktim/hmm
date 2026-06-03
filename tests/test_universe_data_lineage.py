from __future__ import annotations

import json

import pandas as pd

from src.backtest.sector_rotation import _build_walk_forward_cache_params
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import (
    compute_calendar_hash,
    compute_custom_basket_membership_hash,
    compute_sector_ohlcv_snapshot_hash,
    compute_universe_membership_hash,
)
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, _config_hash_payload, _hsmm_lineage_digests
from src.models.walk_forward import WalkForwardConfig


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "lineage.duckdb")
    storage.init_schema()
    return storage


def _seed_sector_ohlcv(storage: DuckDBStorage, close: float = 101.0) -> pd.DataFrame:
    dates = pd.to_datetime(["2024-01-01", "2024-01-02"])
    frame = pd.DataFrame(
        {
            "sector_id": ["S", "S"],
            "trade_date": dates.date,
            "open": [100.0, 100.0],
            "high": [101.0, close],
            "low": [99.0, 99.0],
            "close": [100.0, close],
            "volume": [10.0, 11.0],
            "amount": [1000.0, 1111.0],
            "pct_chg": [0.0, close - 100.0],
            "turnover": [1.0, 1.1],
            "source": ["test", "test"],
            "fetched_at": [pd.Timestamp("2024-01-03"), pd.Timestamp("2024-01-03")],
        }
    )
    storage.upsert_df("sector_ohlcv", frame, ["sector_id", "trade_date"])
    return frame


def test_universe_membership_change_changes_hash(tmp_path):
    storage = _storage(tmp_path)
    universe_id = storage.create_universe("lineage-test")
    storage.add_universe_item(universe_id, "industry", "S", "Sector S")

    before = compute_universe_membership_hash(storage, universe_id)
    storage.add_universe_item(universe_id, "concept", "C", "Concept C")
    after = compute_universe_membership_hash(storage, universe_id)

    assert before != after


def test_custom_basket_weight_or_member_change_changes_hash(tmp_path):
    storage = _storage(tmp_path)
    basket_id = storage.create_custom_stock_basket("lineage basket")
    storage.add_basket_members(basket_id, [{"stock_code": "000001", "stock_name": "A", "weight": 1.0}])

    before = compute_custom_basket_membership_hash(storage, [basket_id])
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001", "stock_name": "A", "weight": 2.0},
            {"stock_code": "000002", "stock_name": "B", "weight": 1.0},
        ],
    )
    after = compute_custom_basket_membership_hash(storage, [basket_id])

    assert before != after
    assert compute_custom_basket_membership_hash(storage, []) != compute_custom_basket_membership_hash(storage, [basket_id])


def test_ohlcv_close_change_changes_data_snapshot_hash(tmp_path):
    storage = _storage(tmp_path)
    _seed_sector_ohlcv(storage, close=101.0)
    before = compute_sector_ohlcv_snapshot_hash(storage, ["S"], "2024-01-01", "2024-01-02")

    _seed_sector_ohlcv(storage, close=102.0)
    after = compute_sector_ohlcv_snapshot_hash(storage, ["S"], "2024-01-01", "2024-01-02")

    assert before != after


def test_trade_dates_change_changes_calendar_hash():
    before = compute_calendar_hash(["2024-01-01", "2024-01-02"])
    after = compute_calendar_hash(["2024-01-01", "2024-01-02", "2024-01-03"])

    assert before != after


def test_hmm_cache_params_include_universe_data_calendar_digests(tmp_path):
    storage = _storage(tmp_path)
    ohlcv = _seed_sector_ohlcv(storage)
    trade_dates = pd.Series(pd.to_datetime(ohlcv["trade_date"]))
    features = pd.DataFrame({"sector_id": ["S", "S"], "trade_date": trade_dates})
    config = WalkForwardConfig(n_states=3, train_window_days=120, retrain_frequency="monthly")

    params = _build_walk_forward_cache_params(
        storage=storage,
        ohlcv=ohlcv,
        features=features,
        trade_dates=trade_dates,
        config=config,
        feature_version="test-feature",
        start_ts=pd.Timestamp("2024-01-01"),
        end_ts=pd.Timestamp("2024-01-02"),
        rebalance_days=5,
        state_date_mode="rebalance_signals_v2",
        universe_id=None,
        scope_type="all",
        feature_scope_id="all",
        feature_scope_type="all",
        include_custom_baskets=True,
    )
    lineage = json.loads(str(params["lineage_json"]))

    assert params["universe_membership_hash"] == compute_universe_membership_hash(storage, None, as_of_date="2024-01-02")
    assert params["data_snapshot_hash"] == compute_sector_ohlcv_snapshot_hash(storage, ["S"], "2024-01-01", "2024-01-02")
    assert params["calendar_hash"] == compute_calendar_hash(trade_dates)
    assert params["custom_basket_membership_hash"]
    assert lineage["universe_membership_hash"] == params["universe_membership_hash"]
    assert lineage["custom_basket_membership_hash"] == params["custom_basket_membership_hash"]
    assert lineage["data_snapshot_hash"] == params["data_snapshot_hash"]
    assert lineage["calendar_hash"] == params["calendar_hash"]
    assert lineage["custom_basket_membership_policy"] == "current_snapshot"


def test_hsmm_config_payload_includes_universe_data_calendar_digests(tmp_path):
    storage = _storage(tmp_path)
    ohlcv = _seed_sector_ohlcv(storage)
    trade_dates = pd.Series(pd.to_datetime(ohlcv["trade_date"]))
    config = HSMMWalkForwardConfig(start_date="2024-01-01", end_date="2024-01-02")
    digests = _hsmm_lineage_digests(
        storage,
        config,
        ohlcv,
        trade_dates,
        pd.Timestamp("2024-01-01"),
        pd.Timestamp("2024-01-02"),
    )

    payload = _config_hash_payload(config, "all", "all", digests)

    assert payload["universe_membership_hash"] == compute_universe_membership_hash(storage, None, as_of_date="2024-01-02")
    assert payload["data_snapshot_hash"] == compute_sector_ohlcv_snapshot_hash(storage, ["S"], "2024-01-01", "2024-01-02")
    assert payload["calendar_hash"] == compute_calendar_hash(trade_dates)
    assert payload["custom_basket_membership_policy"] == "current_snapshot"
