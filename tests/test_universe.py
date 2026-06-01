from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline.storage import DuckDBStorage, json_dumps
from src.features.custom_basket_features import build_custom_basket_ohlcv
from src.models.hmm_model import train_hmm


def _stock_ohlcv(code: str, closes: list[float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_code": code,
            "trade_date": dates.date,
            "open": closes,
            "high": np.asarray(closes) * 1.01,
            "low": np.asarray(closes) * 0.99,
            "close": closes,
            "volume": 1000,
            "amount": 10000,
            "pct_chg": pd.Series(closes).pct_change().fillna(0).to_numpy() * 100,
            "turnover": 1.0,
            "source": "test",
            "fetched_at": pd.Timestamp("2024-01-10"),
        }
    )


def _sector_ohlcv(sector_id: str, dates: pd.DatetimeIndex, drift: float) -> pd.DataFrame:
    idx = np.arange(len(dates))
    daily_ret = drift + 0.004 * np.sin(idx / 7)
    close = 100 * np.cumprod(1 + daily_ret)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "sector_id": sector_id,
            "trade_date": dates.date,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": 10_000_000 + idx * 1000,
            "pct_chg": daily_ret * 100,
            "turnover": 1.0,
            "source": "test",
            "fetched_at": pd.Timestamp("2024-06-01"),
        }
    )


def test_create_universe(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    universe_id = storage.create_universe("AI 算力链", "测试板块池")
    basket_id = storage.create_custom_stock_basket("光模块核心")

    storage.add_universe_item(universe_id, "industry", "industry:半导体", "半导体")
    storage.add_universe_item(universe_id, "concept", "concept:CPO概念", "CPO概念")
    storage.add_universe_item(universe_id, "custom_stock_basket", basket_id, "光模块核心")

    items = storage.list_universe_items(universe_id)
    assert set(items["item_type"]) == {"industry", "concept", "custom_stock_basket"}
    assert set(items["item_name"]) == {"半导体", "CPO概念", "光模块核心"}


def test_custom_basket_ohlcv_equal_weight(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    basket_id = storage.create_custom_stock_basket("等权测试")
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001", "stock_name": "A"},
            {"stock_code": "000002", "stock_name": "B"},
            {"stock_code": "000003", "stock_name": "C"},
        ],
    )
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    stocks = pd.concat(
        [
            _stock_ohlcv("000001", [100, 110, 121], dates),
            _stock_ohlcv("000002", [100, 90, 99], dates),
            _stock_ohlcv("000003", [100, 100, 100], dates),
        ],
        ignore_index=True,
    )
    storage.upsert_df("stock_ohlcv", stocks, ["stock_code", "trade_date"])

    out = build_custom_basket_ohlcv(basket_id, "20240101", "20240103", storage=storage)

    assert len(out) == 3
    assert np.isclose(out.loc[0, "close"], 1000.0)
    assert np.isclose(out.loc[1, "daily_ret"], 0.0)
    assert np.isclose(out.loc[2, "daily_ret"], (0.1 + 0.1 + 0.0) / 3)
    assert np.isclose(out.loc[2, "close"], 1000.0 * (1 + (0.1 + 0.1 + 0.0) / 3))


def test_custom_basket_weighted_index(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    basket_id = storage.create_custom_stock_basket("加权测试", index_method="custom_weight")
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001", "stock_name": "A", "weight": 2.0},
            {"stock_code": "000002", "stock_name": "B", "weight": 1.0},
        ],
    )
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    stocks = pd.concat(
        [
            _stock_ohlcv("000001", [100, 110, 121], dates),
            _stock_ohlcv("000002", [100, 100, 90], dates),
        ],
        ignore_index=True,
    )
    storage.upsert_df("stock_ohlcv", stocks, ["stock_code", "trade_date"])

    out = build_custom_basket_ohlcv(basket_id, "20240101", "20240103", storage=storage)

    expected_day1 = (2.0 * 0.10 + 1.0 * 0.0) / 3.0
    expected_day2 = (2.0 * 0.10 + 1.0 * -0.10) / 3.0
    assert np.isclose(out.loc[1, "daily_ret"], expected_day1)
    assert np.isclose(out.loc[2, "daily_ret"], expected_day2)
    assert np.isclose(out.loc[2, "close"], 1000.0 * (1 + expected_day1) * (1 + expected_day2))


@pytest.mark.slow
def test_universe_filter_for_training(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    meta = pd.DataFrame(
        [
            {"sector_id": "industry:a", "sector_type": "industry", "sector_name": "a", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
            {"sector_id": "industry:b", "sector_type": "industry", "sector_name": "b", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
            {"sector_id": "industry:c", "sector_type": "industry", "sector_name": "c", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
        ]
    )
    storage.upsert_df("sector_meta", meta, ["sector_id"])
    dates = pd.date_range("2024-01-01", periods=140, freq="D")
    ohlcv = pd.concat(
        [
            _sector_ohlcv("industry:a", dates, 0.0010),
            _sector_ohlcv("industry:b", dates, 0.0015),
            _sector_ohlcv("industry:c", dates, -0.0005),
        ],
        ignore_index=True,
    )
    storage.upsert_df("sector_ohlcv", ohlcv, ["sector_id", "trade_date"])
    universe_id = storage.create_universe("训练过滤")
    storage.add_universe_item(universe_id, "industry", "industry:a", "a")
    storage.add_universe_item(universe_id, "industry", "industry:b", "b")

    result = train_hmm("20240101", "20240520", n_states=2, universe_id=universe_id, storage=storage, n_iter=30, n_init=1)
    states = storage.read_df("SELECT DISTINCT sector_id FROM sector_state_daily WHERE run_id = ?", [result.run_id])
    run = storage.get_model_run(result.run_id)

    assert set(states["sector_id"]) == {"industry:a", "industry:b"}
    assert run.loc[0, "universe_id"] == universe_id
    assert run.loc[0, "scope_type"] == "universe"
    assert bool(run.loc[0, "include_custom_baskets"])


def test_universe_export_import(tmp_path):
    source = DuckDBStorage(tmp_path / "source.duckdb")
    source.init_schema()
    universe_id = source.create_universe("AI 算力链", "导出测试")
    basket_id = source.create_custom_stock_basket("算力核心")
    source.add_basket_members(basket_id, [{"stock_code": "300308", "stock_name": "中际旭创"}])
    source.add_universe_item(universe_id, "industry", "industry:通信设备", "通信设备")
    source.add_universe_item(universe_id, "custom_stock_basket", basket_id, "算力核心")
    payload = json.loads(json_dumps(source.export_universe_json(universe_id)))

    target = DuckDBStorage(tmp_path / "target.duckdb")
    target.init_schema()
    imported_id = target.import_universe_json(payload)

    imported = target.get_universe(imported_id)
    items = target.list_universe_items(imported_id)
    members = target.list_basket_members(basket_id)
    assert imported.loc[0, "universe_name"] == "AI 算力链"
    assert set(items["item_type"]) == {"industry", "custom_stock_basket"}
    assert members.loc[0, "stock_code"] == "300308"
