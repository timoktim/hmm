from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.backtest import sector_rotation
from src.backtest.sector_rotation import validate_state_neutral_backtest_params
from src.data_pipeline.storage import DuckDBStorage
from src.evaluation import signal_validation
from src.evaluation.signal_validation import SignalValidationConfig


def _seed_sector_ohlcv(storage: DuckDBStorage, days: int = 84, sectors: int = 4) -> None:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows: list[dict[str, object]] = []
    for sector_idx in range(sectors):
        close = 100.0 + sector_idx
        for idx, date in enumerate(dates):
            ret = 0.001 * np.sin(idx / 6 + sector_idx) + sector_idx * 0.0002
            open_price = close * (1 + ret / 3)
            close = close * (1 + ret)
            rows.append(
                {
                    "sector_id": f"industry:s{sector_idx}",
                    "trade_date": date.date(),
                    "open": float(open_price),
                    "high": float(max(open_price, close) * 1.01),
                    "low": float(min(open_price, close) * 0.99),
                    "close": float(close),
                    "volume": 1000 + idx,
                    "amount": 10000 + idx * 10 + sector_idx,
                    "pct_chg": float(ret * 100),
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-04-01"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def _fake_walk_forward_with_counter(counter: dict[str, int]):
    def fake(features: pd.DataFrame, state_dates: list[pd.Timestamp], config, progress_callback=None) -> pd.DataFrame:
        counter["calls"] += 1
        sectors = sorted(features["sector_id"].dropna().astype(str).unique())
        rows: list[dict[str, object]] = []
        for date in state_dates:
            for idx, sector_id in enumerate(sectors):
                prob_trend = 0.4 + idx * 0.12
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

    return fake


def _config() -> SignalValidationConfig:
    return SignalValidationConfig(
        start_date="2024-02-05",
        end_date="2024-03-15",
        train_window_days=30,
        n_states=2,
        rebalance_days=5,
        threshold_grid=(0.45, 0.55, 0.65),
        top_n_grid=(1, 2),
        cost_grid=(0.0, 0.001, 0.002),
        transaction_cost=0.001,
    )


def test_state_reuse_guard_only_allows_state_neutral_params():
    validate_state_neutral_backtest_params(["threshold", "top_n", "transaction_cost"])

    with pytest.raises(ValueError, match="train_window_days"):
        validate_state_neutral_backtest_params(["threshold", "train_window_days"])


def test_selection_grid_prepares_walk_forward_states_once(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "reuse.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    counter = {"calls": 0}
    monkeypatch.setattr(sector_rotation, "walk_forward_hmm_state_frame", _fake_walk_forward_with_counter(counter))

    result = signal_validation.evaluate_selection_grid(_config(), storage, n_jobs=1)

    assert counter["calls"] == 1
    assert result.attrs["state_context_reused"] is True
    assert not result.empty


def test_cost_grid_prepares_walk_forward_states_once(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "cost_reuse.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    counter = {"calls": 0}
    monkeypatch.setattr(sector_rotation, "walk_forward_hmm_state_frame", _fake_walk_forward_with_counter(counter))

    result = signal_validation.evaluate_cost_sensitivity(_config(), storage, _config().cost_grid, n_jobs=1)

    assert counter["calls"] == 1
    assert result.attrs["state_context_reused"] is True
    assert not result.empty


def test_state_affecting_param_change_uses_distinct_state_context(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "state_affecting.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    counter = {"calls": 0}
    monkeypatch.setattr(sector_rotation, "walk_forward_hmm_state_frame", _fake_walk_forward_with_counter(counter))

    first = _config()
    second = SignalValidationConfig(**{**first.__dict__, "train_window_days": 35})

    signal_validation.evaluate_selection_grid(first, storage, n_jobs=1)
    signal_validation.evaluate_selection_grid(second, storage, n_jobs=1)

    assert counter["calls"] == 2
