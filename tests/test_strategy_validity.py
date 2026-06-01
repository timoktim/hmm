from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest.sector_rotation import run_sector_rotation_backtest, simulate_portfolio_returns
from src.data_pipeline.storage import DuckDBStorage
from src.features.sector_features import FEATURE_COLUMNS
from src.models.walk_forward import WalkForwardConfig, walk_forward_hmm_state_frame


def _feature_frame(days: int = 90, sectors: int = 3) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows: list[dict[str, object]] = []
    for sector_idx in range(sectors):
        phase = sector_idx * 0.5
        for i, dt in enumerate(dates):
            rows.append(
                {
                    "sector_id": f"industry:s{sector_idx}",
                    "trade_date": dt,
                    "ret_1d": 0.002 * np.sin(i / 5 + phase) + sector_idx * 0.0005,
                    "ret_5d": 0.006 * np.sin(i / 8 + phase),
                    "ret_20d": 0.02 * np.sin(i / 13 + phase) + sector_idx * 0.01,
                    "vol_20d": 0.03 + 0.004 * sector_idx + 0.002 * np.cos(i / 7),
                    "amount_z_20d": np.sin(i / 9 + phase),
                    "rs_20d": 0.01 * np.cos(i / 11 + phase) + sector_idx * 0.005,
                    "drawdown_20d": -0.02 * abs(np.sin(i / 10 + phase)),
                    "ma20_slope": 0.003 * np.sin(i / 12 + phase) + sector_idx * 0.001,
                }
            )
    return pd.DataFrame(rows)


def test_walk_forward_no_future_data():
    features = _feature_frame()
    signal_date = pd.Timestamp("2024-03-10")
    config = WalkForwardConfig(n_states=2, train_window_days=45, min_train_rows=60, min_sequence_length=20)

    baseline = walk_forward_hmm_state_frame(features, [signal_date], config)
    shocked = features.copy()
    future_mask = pd.to_datetime(shocked["trade_date"]) > signal_date
    shocked.loc[future_mask, FEATURE_COLUMNS] = shocked.loc[future_mask, FEATURE_COLUMNS] * 1000 + 1000
    with_future_changed = walk_forward_hmm_state_frame(shocked, [signal_date], config)

    assert not baseline.empty
    assert (baseline["train_end"] <= baseline["trade_date"]).all()
    assert (baseline["max_observation_date_used"] <= baseline["trade_date"]).all()
    prob_cols = ["prob_trend_up", "prob_neutral", "prob_risk_off"]
    left = baseline.sort_values("sector_id")[prob_cols].to_numpy()
    right = with_future_changed.sort_values("sector_id")[prob_cols].to_numpy()
    assert np.allclose(left, right)


def test_first_return_after_execution():
    dates = pd.date_range("2024-01-01", periods=5, freq="D")
    close_prices = pd.DataFrame({"industry:test": [100.0, 110.0, 121.0, 133.1, 146.41]}, index=dates)
    open_prices = close_prices.copy()
    events = pd.DataFrame(
        [
            {
                "signal_date": dates[0],
                "exec_date": dates[1],
                "weights": {"industry:test": 1.0},
            }
        ]
    )

    curve, _ = simulate_portfolio_returns(open_prices, close_prices, events, execution_price="close", transaction_cost=0.0)

    exec_row = curve[curve["trade_date"] == dates[1]].iloc[0]
    first_holding_row = curve[curve["trade_date"] == dates[2]].iloc[0]
    assert exec_row["gross_return"] == 0.0
    assert np.isclose(first_holding_row["gross_return"], close_prices.iloc[2, 0] / close_prices.iloc[1, 0] - 1)


def _sector_ohlcv_frame(days: int = 130, sectors: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows: list[dict[str, object]] = []
    for sector_idx in range(sectors):
        drift = 0.0015 - sector_idx * 0.0004
        seasonal = 0.004 * np.sin(np.arange(days) / (8 + sector_idx))
        noise = rng.normal(0, 0.003, days)
        returns = drift + seasonal + noise
        close = 100 * np.cumprod(1 + returns)
        open_ = np.r_[close[0] * (1 - returns[0] / 2), close[:-1] * (1 + returns[1:] / 3)]
        for i, dt in enumerate(dates):
            rows.append(
                {
                    "sector_id": f"industry:s{sector_idx}",
                    "trade_date": dt.date(),
                    "open": float(open_[i]),
                    "high": float(max(open_[i], close[i]) * 1.01),
                    "low": float(min(open_[i], close[i]) * 0.99),
                    "close": float(close[i]),
                    "volume": 1_000_000 + i * 1000 + sector_idx * 100,
                    "amount": 10_000_000 + i * 10_000 + sector_idx * 1000,
                    "pct_chg": float(returns[i] * 100),
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-06-01"),
                }
            )
    return pd.DataFrame(rows)


@pytest.mark.slow
def test_synthetic_backtest_end_to_end(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    ohlcv = _sector_ohlcv_frame()
    storage.upsert_df("sector_ohlcv", ohlcv, ["sector_id", "trade_date"])

    result = run_sector_rotation_backtest(
        threshold=0.0,
        top_n=2,
        rebalance_days=10,
        start_date="2024-03-15",
        end_date="2024-05-05",
        train_window_days=60,
        n_states=2,
        execution_price="close",
        transaction_cost=0.001,
        storage=storage,
    )
    cached = run_sector_rotation_backtest(
        threshold=0.0,
        top_n=2,
        rebalance_days=10,
        start_date="2024-03-15",
        end_date="2024-05-05",
        train_window_days=60,
        n_states=2,
        execution_price="close",
        transaction_cost=0.001,
        storage=storage,
    )

    assert set(result["comparison"]["strategy"]) == {"model", "baseline_1_rs20_top_n", "baseline_2_equal_weight"}
    assert not result["curve"].empty
    assert "model_nav_gross" in result["curve"].columns
    assert "model_nav_net" in result["curve"].columns
    assert result["comparison"]["turnover"].ge(0).all()
    assert not result["cache_hit"]
    assert cached["cache_hit"]
