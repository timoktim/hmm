from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline.storage import DuckDBStorage
from src.features.custom_basket_features import (
    POLICY_DYNAMIC_AVAILABLE,
    POLICY_FIXED_ZERO_RETURN,
    build_custom_basket_ohlcv,
    custom_basket_quality_frame,
)


def _stock_ohlcv(stock_code: str, closes: list[float], dates: pd.DatetimeIndex) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_code": [stock_code] * len(closes),
            "trade_date": [d.date() for d in dates],
            "close": closes,
            "volume": [1000.0] * len(closes),
            "amount": [10000.0] * len(closes),
        }
    )


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "basket.duckdb")
    storage.init_schema()
    return storage


def test_fixed_weight_zero_return_does_not_redistribute_missing_weight(tmp_path):
    storage = _storage(tmp_path)
    basket_id = storage.create_custom_stock_basket(
        "fixed",
        index_method="custom_weight",
        membership_policy=POLICY_FIXED_ZERO_RETURN,
    )
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001", "weight": 1.0},
            {"stock_code": "000002", "weight": 1.0},
        ],
    )
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df(
        "stock_ohlcv",
        pd.concat(
            [
                _stock_ohlcv("000001", [100.0, 110.0], dates),
                _stock_ohlcv("000002", [100.0], dates[:1]),
            ],
            ignore_index=True,
        ),
        ["stock_code", "trade_date"],
    )

    out = build_custom_basket_ohlcv(basket_id, "20240101", "20240102", storage=storage)

    assert np.isclose(out.loc[1, "daily_ret"], 0.05)
    assert out.loc[1, "member_count"] == 1
    assert out.loc[1, "missing_member_count"] == 1
    assert out.loc[1, "membership_policy"] == POLICY_FIXED_ZERO_RETURN
    assert out.loc[1, "index_method_effective"] == f"custom_weight:{POLICY_FIXED_ZERO_RETURN}"


def test_dynamic_and_fixed_policies_differ_on_missing_member_day(tmp_path):
    storage = _storage(tmp_path)
    fixed_id = storage.create_custom_stock_basket(
        "fixed",
        index_method="custom_weight",
        membership_policy=POLICY_FIXED_ZERO_RETURN,
    )
    dynamic_id = storage.create_custom_stock_basket(
        "dynamic",
        index_method="custom_weight",
        membership_policy=POLICY_DYNAMIC_AVAILABLE,
    )
    members = [
        {"stock_code": "000001", "weight": 1.0},
        {"stock_code": "000002", "weight": 1.0},
    ]
    storage.add_basket_members(fixed_id, members)
    storage.add_basket_members(dynamic_id, members)
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df(
        "stock_ohlcv",
        pd.concat(
            [
                _stock_ohlcv("000001", [100.0, 110.0], dates),
                _stock_ohlcv("000002", [100.0], dates[:1]),
            ],
            ignore_index=True,
        ),
        ["stock_code", "trade_date"],
    )

    fixed = build_custom_basket_ohlcv(fixed_id, "20240101", "20240102", storage=storage)
    dynamic = build_custom_basket_ohlcv(dynamic_id, "20240101", "20240102", storage=storage)

    assert np.isclose(fixed.loc[1, "daily_ret"], 0.05)
    assert np.isclose(dynamic.loc[1, "daily_ret"], 0.10)
    assert dynamic.loc[1, "membership_policy"] == POLICY_DYNAMIC_AVAILABLE
    assert dynamic.loc[1, "index_method_effective"] == f"custom_weight:{POLICY_DYNAMIC_AVAILABLE}"


def test_low_coverage_warning_is_recorded_without_strict_block(tmp_path):
    storage = _storage(tmp_path)
    basket_id = storage.create_custom_stock_basket("coverage", membership_policy=POLICY_FIXED_ZERO_RETURN)
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001"},
            {"stock_code": "000002"},
            {"stock_code": "000003"},
        ],
    )
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df(
        "stock_ohlcv",
        pd.concat(
            [
                _stock_ohlcv("000001", [100.0, 101.0], dates),
                _stock_ohlcv("000002", [100.0], dates[:1]),
                _stock_ohlcv("000003", [100.0], dates[:1]),
            ],
            ignore_index=True,
        ),
        ["stock_code", "trade_date"],
    )

    out = build_custom_basket_ohlcv(basket_id, "20240101", "20240102", storage=storage)
    quality = custom_basket_quality_frame(basket_id, storage=storage)

    assert np.isclose(out.loc[1, "coverage_ratio"], 1 / 3)
    assert out.loc[1, "missing_member_count"] == 2
    assert bool(out.loc[1, "low_coverage_warning"]) is True
    quality_day = quality[pd.to_datetime(quality["trade_date"]) == pd.Timestamp("2024-01-02")]
    assert bool(quality_day["low_quality"].iloc[0]) is True


def test_strict_low_coverage_blocks_output_and_upsert(tmp_path):
    storage = _storage(tmp_path)
    basket_id = storage.create_custom_stock_basket("strict", membership_policy=POLICY_FIXED_ZERO_RETURN)
    storage.add_basket_members(
        basket_id,
        [
            {"stock_code": "000001"},
            {"stock_code": "000002"},
            {"stock_code": "000003"},
        ],
    )
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df(
        "stock_ohlcv",
        pd.concat(
            [
                _stock_ohlcv("000001", [100.0, 101.0], dates),
                _stock_ohlcv("000002", [100.0], dates[:1]),
                _stock_ohlcv("000003", [100.0], dates[:1]),
            ],
            ignore_index=True,
        ),
        ["stock_code", "trade_date"],
    )

    with pytest.raises(ValueError, match="blocked by strict=True"):
        build_custom_basket_ohlcv(basket_id, "20240101", "20240102", storage=storage, strict=True)

    saved = storage.read_df("SELECT * FROM custom_basket_ohlcv WHERE basket_id = ?", [basket_id])
    assert saved.empty


def test_zfilled_stock_codes_join_to_source_rows(tmp_path):
    storage = _storage(tmp_path)
    basket_id = storage.create_custom_stock_basket("zfill", membership_policy=POLICY_FIXED_ZERO_RETURN)
    storage.add_basket_members(basket_id, [{"stock_code": "000001.SZ"}])
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df("stock_ohlcv", _stock_ohlcv("1", [100.0, 105.0], dates), ["stock_code", "trade_date"])

    out = build_custom_basket_ohlcv(basket_id, "20240101", "20240102", storage=storage)

    assert len(out) == 2
    assert out.loc[1, "member_count"] == 1
    assert out.loc[1, "missing_member_count"] == 0
    assert np.isclose(out.loc[1, "daily_ret"], 0.05)
