from __future__ import annotations

import numpy as np
import pandas as pd

from src.features.sector_features import add_sector_features, equal_weight_benchmark_ret20_from_close
from src.features.stock_features import stock_feature_frame


def test_sector_feature_math_basic():
    dates = pd.date_range("2024-01-01", periods=40, freq="D")
    close = pd.Series(100 * (1.01 ** np.arange(40)))
    df = pd.DataFrame(
        {
            "sector_id": "industry:test",
            "trade_date": dates,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1000,
            "amount": np.linspace(1000, 2000, 40),
            "pct_chg": close.pct_change() * 100,
            "turnover": 1.0,
        }
    )
    features = add_sector_features(df)
    row = features.iloc[-1]
    assert np.isclose(row["ret_5d"], (1.01**5) - 1)
    assert np.isclose(row["ret_20d"], (1.01**20) - 1)
    assert row["vol_20d"] >= 0
    assert np.isfinite(row["amount_z_20d"])


def test_equal_weight_benchmark_is_scale_invariant():
    dates = pd.date_range("2024-01-01", periods=45, freq="D")
    base = pd.DataFrame(
        {
            "low_price_sector": 10 * (1.01 ** np.arange(45)),
            "high_price_sector": 1000 * (0.995 ** np.arange(45)),
        },
        index=dates,
    )
    scaled = base.copy()
    scaled["high_price_sector"] = scaled["high_price_sector"] * 100

    benchmark = equal_weight_benchmark_ret20_from_close(base)
    scaled_benchmark = equal_weight_benchmark_ret20_from_close(scaled)

    assert np.allclose(benchmark.dropna(), scaled_benchmark.dropna())


def test_rs_vs_index_not_equal_sector_when_benchmark_available():
    dates = pd.date_range("2024-01-01", periods=45, freq="D")
    stock_close = pd.Series(100 * (1.012 ** np.arange(45)))
    sector_close = pd.Series(100 * (1.006 ** np.arange(45)))
    benchmark_close = pd.Series(100 * (0.998 ** np.arange(45)), index=dates)
    stock = pd.DataFrame(
        {
            "stock_code": "000001",
            "trade_date": dates,
            "open": stock_close,
            "high": stock_close * 1.01,
            "low": stock_close * 0.99,
            "close": stock_close,
            "amount": np.linspace(1000, 2000, 45),
        }
    )
    sector = pd.DataFrame({"trade_date": dates, "close": sector_close})

    with_benchmark = stock_feature_frame(stock, sector, benchmark_close=benchmark_close)
    latest = with_benchmark.iloc[-1]
    assert not np.isclose(latest["rs_vs_index_20d"], latest["rs_vs_sector_20d"])

    without_benchmark = stock_feature_frame(stock, sector)
    assert np.isnan(without_benchmark.iloc[-1]["rs_vs_index_20d"])
