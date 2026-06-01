from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models.inference import latest_causal_sector_states, recent_causal_switches


def _seed_cache(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    date1 = pd.Timestamp("2024-02-01").date()
    date2 = pd.Timestamp("2024-02-02").date()
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame([{"sector_id": "A", "sector_type": "industry", "sector_name": "甲行业", "source": "test"}]),
        ["sector_id"],
    )
    storage.upsert_df(
        "sector_features",
        pd.DataFrame(
            [
                {
                    "sector_id": "A",
                    "trade_date": date2,
                    "ret_1d": 0.01,
                    "ret_5d": 0.02,
                    "ret_20d": 0.08,
                    "vol_20d": 0.1,
                    "amount_z_20d": 0.3,
                    "rs_20d": 0.2,
                    "drawdown_20d": -0.02,
                    "ma20_slope": 0.01,
                    "feature_version": "v",
                    "feature_scope_id": universe_id or "all",
                    "feature_scope_type": "universe" if universe_id else "all",
                }
            ]
        ),
        ["sector_id", "trade_date", "feature_version", "feature_scope_id"],
    )
    storage.upsert_df(
        "walk_forward_cache_runs",
        pd.DataFrame(
            [
                {
                    "cache_key": "cache",
                    "n_states": 3,
                    "train_window_days": 60,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": date1,
                    "end_date": date2,
                    "params_json": "{}",
                    "params_hash": "hash",
                    "universe_id": universe_id,
                    "scope_type": "universe" if universe_id else "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": universe_id or "all",
                    "signal_count": 2,
                    "row_count": 2,
                    "created_at": pd.Timestamp("2024-02-03"),
                }
            ]
        ),
        ["cache_key"],
    )
    storage.upsert_df(
        "walk_forward_state_cache",
        pd.DataFrame(
            [
                {
                    "cache_key": "cache",
                    "sector_id": "A",
                    "trade_date": date1,
                    "state_id": 1,
                    "state_label": "Neutral",
                    "prob_trend_up": 0.3,
                    "prob_neutral": 0.6,
                    "prob_risk_off": 0.1,
                    "next_state_probs_json": "{}",
                    "train_start": date1,
                    "train_end": date1,
                    "max_observation_date_used": date1,
                    "probability_type": "filtered",
                    "state_source": "causal_backtest",
                },
                {
                    "cache_key": "cache",
                    "sector_id": "A",
                    "trade_date": date2,
                    "state_id": 0,
                    "state_label": "TrendUp",
                    "prob_trend_up": 0.8,
                    "prob_neutral": 0.15,
                    "prob_risk_off": 0.05,
                    "next_state_probs_json": "{}",
                    "train_start": date1,
                    "train_end": date2,
                    "max_observation_date_used": date2,
                    "probability_type": "filtered",
                    "state_source": "causal_backtest",
                },
            ]
        ),
        ["cache_key", "sector_id", "trade_date"],
    )


def test_latest_causal_sector_states_returns_empty_without_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    date = pd.Timestamp("2024-02-01").date()
    storage.upsert_df(
        "sector_state_daily",
        pd.DataFrame(
            [
                {
                    "run_id": "r",
                    "sector_id": "A",
                    "trade_date": date,
                    "state_id": 0,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "state_source": "in_sample_display",
                }
            ]
        ),
        ["run_id", "sector_id", "trade_date"],
    )

    out = latest_causal_sector_states(storage)

    assert out.empty


def test_latest_causal_sector_states_reads_walk_forward_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_cache(storage)

    out = latest_causal_sector_states(storage, cache_key="cache")

    assert len(out) == 1
    assert out.loc[0, "sector_name"] == "甲行业"
    assert out.loc[0, "state_source"] == "causal_backtest"
    assert out.loc[0, "rs_20d"] == 0.2


def test_recent_switches_use_same_state_source_as_dashboard(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_cache(storage)

    out = recent_causal_switches(storage, cache_key="cache")

    assert len(out) == 1
    assert out.loc[0, "prev_label"] == "Neutral"
    assert out.loc[0, "state_label"] == "TrendUp"
    assert out.loc[0, "state_source"] == "causal_backtest"
