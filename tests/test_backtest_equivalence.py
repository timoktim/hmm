from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest import sector_rotation
from src.data_pipeline.storage import DuckDBStorage
from src.evaluation import signal_validation
from src.evaluation.signal_validation import SignalValidationConfig


def _sector_ohlcv_frame(days: int = 96, sectors: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(17)
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows: list[dict[str, object]] = []
    for sector_idx in range(sectors):
        drift = 0.0012 - sector_idx * 0.00025
        seasonal = 0.003 * np.sin(np.arange(days) / (7 + sector_idx))
        noise = rng.normal(0, 0.001, days)
        returns = drift + seasonal + noise
        close = 100 * np.cumprod(1 + returns)
        open_ = np.r_[close[0] * (1 - returns[0] / 3), close[:-1] * (1 + returns[1:] / 4)]
        for idx, dt in enumerate(dates):
            rows.append(
                {
                    "sector_id": f"industry:s{sector_idx}",
                    "trade_date": dt.date(),
                    "open": float(open_[idx]),
                    "high": float(max(open_[idx], close[idx]) * 1.01),
                    "low": float(min(open_[idx], close[idx]) * 0.99),
                    "close": float(close[idx]),
                    "volume": 1_000_000 + idx * 1000,
                    "amount": 10_000_000 + idx * 10_000 + sector_idx * 1000,
                    "pct_chg": float(returns[idx] * 100),
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-04-30"),
                }
            )
    return pd.DataFrame(rows)


def _seed_storage(tmp_path, name: str) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / f"{name}.duckdb")
    storage.init_schema()
    storage.upsert_df("sector_ohlcv", _sector_ohlcv_frame(), ["sector_id", "trade_date"])
    return storage


def _fake_walk_forward(features: pd.DataFrame, state_dates: list[pd.Timestamp], config, progress_callback=None) -> pd.DataFrame:
    sectors = sorted(features["sector_id"].dropna().astype(str).unique())
    rows: list[dict[str, object]] = []
    for date in state_dates:
        for idx, sector_id in enumerate(sectors):
            prob_trend = 0.35 + idx * 0.15
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": pd.Timestamp(date),
                    "state_id": idx % max(1, int(config.n_states)),
                    "state_label": "TrendUp" if prob_trend >= 0.55 else "RiskOff",
                    "prob_trend_up": prob_trend,
                    "prob_neutral": 0.1,
                    "prob_risk_off": max(0.0, 0.9 - prob_trend),
                    "next_state_probs_json": "{}",
                    "train_start": pd.Timestamp(date) - pd.Timedelta(days=30),
                    "train_end": pd.Timestamp(date),
                    "max_observation_date_used": pd.Timestamp(date),
                    "probability_type": "filtered",
                    "state_source": "causal_backtest",
                }
            )
    return pd.DataFrame(rows)


def _config() -> SignalValidationConfig:
    return SignalValidationConfig(
        start_date="2024-02-10",
        end_date="2024-03-20",
        train_window_days=30,
        n_states=2,
        rebalance_days=5,
        threshold=0.55,
        top_n=2,
        transaction_cost=0.001,
        cost_grid=(0.0, 0.001),
        threshold_grid=(0.45, 0.55),
        top_n_grid=(1, 2),
    )


def _assert_frame_equal_atol(left: pd.DataFrame, right: pd.DataFrame) -> None:
    left = left.reset_index(drop=True).copy()
    right = right.reset_index(drop=True).copy()
    left.attrs.clear()
    right.attrs.clear()
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, atol=1e-9, rtol=0)


def test_state_neutral_grid_and_cost_outputs_match_direct_path(tmp_path, monkeypatch):
    monkeypatch.setattr(sector_rotation, "walk_forward_hmm_state_frame", _fake_walk_forward)
    config = _config()

    legacy_selection = signal_validation._evaluate_selection_grid_direct(config, _seed_storage(tmp_path, "legacy_selection"))
    optimized_selection = signal_validation.evaluate_selection_grid(config, _seed_storage(tmp_path, "optimized_selection"), n_jobs=1)
    _assert_frame_equal_atol(legacy_selection, optimized_selection)

    legacy_cost = signal_validation._evaluate_cost_sensitivity_direct(config, _seed_storage(tmp_path, "legacy_cost"), config.cost_grid)
    optimized_cost = signal_validation.evaluate_cost_sensitivity(config, _seed_storage(tmp_path, "optimized_cost"), config.cost_grid, n_jobs=1)
    _assert_frame_equal_atol(legacy_cost, optimized_cost)


def test_random_baseline_outputs_match_direct_path_atol_1e_9():
    ohlcv = _sector_ohlcv_frame(days=50, sectors=5)
    signal_dates = list(pd.date_range("2024-01-20", periods=5, freq="5D"))

    legacy, legacy_summary = signal_validation._evaluate_random_baseline_direct(
        ohlcv,
        signal_dates,
        top_n=3,
        transaction_cost=0.001,
        random_trials=30,
        random_state=42,
    )
    optimized, optimized_summary = signal_validation.evaluate_random_baseline(
        ohlcv,
        signal_dates,
        top_n=3,
        transaction_cost=0.001,
        random_trials=30,
        random_state=42,
        n_jobs=1,
    )

    _assert_frame_equal_atol(legacy, optimized)
    _assert_frame_equal_atol(legacy_summary, optimized_summary)
