from __future__ import annotations

import pandas as pd

from src.backtest import sector_rotation
from src.backtest.sector_rotation import _walk_forward_cache_key, _write_walk_forward_cache, run_sector_rotation_backtest
from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.model_evaluation import evaluate_forward_returns
from src.features.sector_features import feature_scope_for_universe
from src.models.inference import latest_causal_sector_states


def _seed_eval_base(storage: DuckDBStorage, universe_id: str | None = None) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = [100 + i for i in range(len(dates))]
    storage.upsert_df(
        "sector_ohlcv",
        pd.DataFrame(
            {
                "sector_id": "S",
                "trade_date": dates.date,
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1,
                "amount": 1,
                "pct_chg": 0,
                "turnover": 0,
                "source": "test",
                "fetched_at": pd.Timestamp("2024-02-01"),
            }
        ),
        ["sector_id", "trade_date"],
    )
    if universe_id:
        storage.upsert_df(
            "user_universe",
            pd.DataFrame(
                [
                    {
                        "universe_id": universe_id,
                        "universe_name": universe_id,
                        "description": "",
                        "created_at": pd.Timestamp("2024-01-01"),
                        "updated_at": pd.Timestamp("2024-01-01"),
                        "is_default": False,
                    }
                ]
            ),
            ["universe_id"],
        )
        storage.upsert_df(
            "user_universe_items",
            pd.DataFrame(
                [
                    {
                        "universe_id": universe_id,
                        "item_type": "industry",
                        "item_id": "S",
                        "item_name": "S",
                        "weight": 1.0,
                        "note": "",
                        "created_at": pd.Timestamp("2024-01-01"),
                    }
                ]
            ),
            ["universe_id", "item_id"],
        )
    storage.upsert_df(
        "model_runs",
        pd.DataFrame(
            [
                {
                    "run_id": "r",
                    "model_type": "GaussianHMM",
                    "n_states": 3,
                    "train_start": dates[0].date(),
                    "train_end": dates[-1].date(),
                    "feature_version": "v",
                    "model_path": "",
                    "scaler_path": "",
                    "universe_id": universe_id,
                    "scope_type": "universe" if universe_id else "all",
                    "include_custom_baskets": True,
                    "feature_scope_id": universe_id or "all",
                    "feature_scope_type": "universe" if universe_id else "all",
                    "created_at": pd.Timestamp("2024-02-01"),
                    "metrics_json": "{}",
                }
            ]
        ),
        ["run_id"],
    )
    return dates


def test_evaluate_forward_returns_requires_cache_key_for_walk_forward(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_eval_base(storage)

    out = evaluate_forward_returns(storage, "r", state_source="walk_forward")

    assert out.empty
    assert "必须指定 cache_key" in out.attrs["warning"]


def test_evaluate_forward_returns_rejects_mismatched_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_eval_base(storage, universe_id="u1")
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
                    "start_date": dates[0].date(),
                    "end_date": dates[-1].date(),
                    "params_json": "{}",
                    "params_hash": "hash",
                    "universe_id": "u2",
                    "scope_type": "universe",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": "u2",
                    "signal_count": 1,
                    "row_count": 1,
                    "created_at": pd.Timestamp("2024-02-02"),
                }
            ]
        ),
        ["cache_key"],
    )

    out = evaluate_forward_returns(storage, "r", state_source="walk_forward", cache_key="cache", universe_id="u1", scope="universe")

    assert out.empty
    assert "板块池不匹配" in out.attrs["warning"]


def test_walk_forward_cache_run_stores_full_params(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    params = {
        "n_states": 3,
        "train_window_days": 120,
        "retrain_frequency": "monthly",
        "feature_version": "v",
        "start_date": pd.Timestamp("2024-01-01").date(),
        "end_date": pd.Timestamp("2024-03-01").date(),
        "rebalance_days": 5,
        "state_date_mode": "rebalance_signals_v2",
        "universe_id": "u1",
        "scope_type": "universe",
        "feature_scope_id": "u1",
        "include_custom_baskets": True,
    }
    cache_key = _walk_forward_cache_key(params)
    states = pd.DataFrame(
        [
            {
                "sector_id": "S",
                "trade_date": pd.Timestamp("2024-02-01"),
                "state_id": 0,
                "state_label": "TrendUp",
                "prob_trend_up": 0.8,
                "prob_neutral": 0.1,
                "prob_risk_off": 0.1,
                "next_state_probs_json": "{}",
                "train_start": pd.Timestamp("2024-01-01"),
                "train_end": pd.Timestamp("2024-02-01"),
                "max_observation_date_used": pd.Timestamp("2024-02-01"),
                "probability_type": "filtered",
                "state_source": "causal_backtest",
            }
        ]
    )

    _write_walk_forward_cache(storage, cache_key, states, params, signal_count=1)
    row = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key]).iloc[0]

    assert row["params_hash"]
    assert row["universe_id"] == "u1"
    assert row["feature_scope_id"] == "u1"
    assert int(row["rebalance_days"]) == 5


def test_walk_forward_cache_key_changes_when_universe_changes():
    base = {
        "n_states": 3,
        "train_window_days": 120,
        "retrain_frequency": "monthly",
        "feature_version": "v",
        "start_date": "2024-01-01",
        "end_date": "2024-03-01",
        "rebalance_days": 5,
        "state_date_mode": "rebalance_signals_v2",
        "feature_scope_id": "all",
        "include_custom_baskets": True,
    }

    key_all = _walk_forward_cache_key({**base, "universe_id": "all", "scope_type": "all"})
    key_u1 = _walk_forward_cache_key({**base, "universe_id": "u1", "scope_type": "universe", "feature_scope_id": "u1"})

    assert key_all != key_u1


def test_backtest_cache_uses_same_feature_scope_as_universe_training(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    universe_id = "u1"
    sector_id = "industry:S"
    dates = pd.date_range("2024-01-01", periods=70, freq="D")
    close = [100 + i * 0.5 for i in range(len(dates))]
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame([{"sector_id": sector_id, "sector_type": "industry", "sector_name": "S行业", "source": "test"}]),
        ["sector_id"],
    )
    storage.upsert_df(
        "user_universe",
        pd.DataFrame(
            [
                {
                    "universe_id": universe_id,
                    "universe_name": "测试池",
                    "description": "",
                    "created_at": pd.Timestamp("2024-01-01"),
                    "updated_at": pd.Timestamp("2024-01-01"),
                    "is_default": False,
                }
            ]
        ),
        ["universe_id"],
    )
    storage.upsert_df(
        "user_universe_items",
        pd.DataFrame(
            [
                {
                    "universe_id": universe_id,
                    "item_type": "industry",
                    "item_id": sector_id,
                    "item_name": "S行业",
                    "weight": 1.0,
                    "note": "",
                    "created_at": pd.Timestamp("2024-01-01"),
                }
            ]
        ),
        ["universe_id", "item_id"],
    )
    storage.upsert_df(
        "sector_ohlcv",
        pd.DataFrame(
            {
                "sector_id": sector_id,
                "trade_date": dates.date,
                "open": close,
                "high": [v * 1.01 for v in close],
                "low": [v * 0.99 for v in close],
                "close": close,
                "volume": 1_000_000,
                "amount": [10_000_000 + i * 1000 for i in range(len(dates))],
                "pct_chg": 0.0,
                "turnover": 1.0,
                "source": "test",
                "fetched_at": pd.Timestamp("2024-03-15"),
            }
        ),
        ["sector_id", "trade_date"],
    )

    def fake_walk_forward(features, state_dates, config, progress_callback=None):
        return pd.DataFrame(
            [
                {
                    "sector_id": sector_id,
                    "trade_date": pd.Timestamp(date),
                    "state_id": 0,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "train_start": pd.Timestamp(date) - pd.Timedelta(days=20),
                    "train_end": pd.Timestamp(date),
                    "max_observation_date_used": pd.Timestamp(date),
                    "probability_type": "filtered",
                    "state_source": "causal_backtest",
                }
                for date in state_dates
            ]
        )

    monkeypatch.setattr(sector_rotation, "walk_forward_hmm_state_frame", fake_walk_forward)
    run_sector_rotation_backtest(
        threshold=0.0,
        top_n=1,
        rebalance_days=5,
        start_date="2024-02-05",
        end_date="2024-03-01",
        train_window_days=20,
        n_states=2,
        universe_id=universe_id,
        include_custom_baskets=True,
        storage=storage,
    )

    expected_scope_id, _ = feature_scope_for_universe(storage, universe_id, include_custom_baskets=True)
    cache = storage.read_df("SELECT cache_key, feature_scope_id FROM walk_forward_cache_runs").iloc[0]
    feature_rows = storage.read_df("SELECT count(*) AS n FROM sector_features WHERE feature_scope_id = ?", [expected_scope_id])
    latest = latest_causal_sector_states(storage, cache_key=str(cache["cache_key"]), universe_id=universe_id)

    assert cache["feature_scope_id"] == expected_scope_id
    assert int(feature_rows.loc[0, "n"]) > 0
    assert not latest.empty
    assert latest["feature_scope_id"].eq(expected_scope_id).all()
