from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


def _seed_sector_ohlcv(storage: DuckDBStorage, sectors: int = 4, days: int = 90) -> None:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows = []
    for sector in range(sectors):
        close = 100.0 + sector
        for i, date in enumerate(dates):
            drift = 0.001 * ((sector % 2) * 2 - 1) + 0.002 * np.sin(i / 7 + sector)
            open_price = close * (1 + drift / 2)
            close = max(1.0, close * (1 + drift))
            rows.append(
                {
                    "sector_id": f"S{sector}",
                    "trade_date": date.date(),
                    "open": open_price,
                    "high": max(open_price, close) * 1.01,
                    "low": min(open_price, close) * 0.99,
                    "close": close,
                    "volume": 1000 + i,
                    "amount": 10000 + 10 * i + sector,
                    "pct_chg": drift,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-04-01"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def test_hsmm_walk_forward_outputs_causal_rows(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)

    result = run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / "hsmm.duckdb"),
            start_date="2024-02-20",
            end_date="2024-03-20",
            n_states=4,
            max_duration=12,
            train_window_days=45,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=10,
            snapshot_frequency="daily",
            rebalance_days=10,
            min_sequence_length=20,
            n_iter=2,
            run_id="hsmm_test_run",
        ),
        storage=storage,
    )

    states = result["states"]
    assert not states.empty
    assert states["state_source"].eq("causal_hsmm").all()
    assert (pd.to_datetime(states["train_end_date"]) <= pd.to_datetime(states["trade_date"])).all()
    assert (pd.to_datetime(states["max_observation_date_used"]) <= pd.to_datetime(states["trade_date"])).all()
    assert states["checkpoint_id"].fillna("").astype(str).ne("").all()
    assert states["decode_mode"].eq("causal_prefix_viterbi").all()
    assert states["snapshot_frequency"].eq("daily").all()
    assert states["sector_code"].nunique() == 4
    snapshot_days = pd.date_range("2024-02-20", "2024-03-20", freq="D")
    assert states["trade_date"].nunique() == len(snapshot_days)
    stored = storage.read_df("SELECT COUNT(*) AS n FROM hsmm_state_daily WHERE run_id = 'hsmm_test_run'")
    assert int(stored.loc[0, "n"]) == len(states)
    checkpoints = storage.read_df("SELECT * FROM hsmm_model_checkpoints WHERE run_id = 'hsmm_test_run'")
    assert not checkpoints.empty
    assert states["checkpoint_id"].isin(set(checkpoints["checkpoint_id"])).all()
    assert int(checkpoints["train_trade_day_count"].max()) <= 45
    params = storage.read_df("SELECT * FROM hsmm_parameters WHERE run_id = 'hsmm_test_run'")
    assert not params.empty
    performance = storage.read_df("SELECT * FROM hsmm_run_performance WHERE run_id = 'hsmm_test_run'")
    assert not performance.empty
    assert (performance["fit_seconds"] >= 0).all()


def test_hsmm_episodes_use_trading_rows_not_calendar_days(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage, sectors=4, days=70)

    run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / "hsmm.duckdb"),
            start_date="2024-02-15",
            end_date="2024-02-25",
            n_states=4,
            max_duration=10,
            train_window_days=35,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=5,
            snapshot_frequency="daily",
            min_sequence_length=20,
            n_iter=2,
            run_id="hsmm_episode_run",
        ),
        storage=storage,
    )
    episodes = storage.read_df("SELECT * FROM hsmm_state_episodes WHERE run_id = 'hsmm_episode_run'")
    assert not episodes.empty
    assert (episodes["duration_calendar_days"] >= episodes["duration_trading_days"]).all()
    open_rows = episodes[episodes["is_open_episode"] == True]  # noqa: E712
    assert not open_rows.empty
