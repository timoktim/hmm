from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.model_evaluation import evaluate_forward_returns


def _seed_eval_base(storage: DuckDBStorage) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = [100 + i for i in range(len(dates))]
    ohlcv = pd.DataFrame(
        {
            "sector_id": "industry:test",
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
    )
    storage.upsert_df("sector_ohlcv", ohlcv, ["sector_id", "trade_date"])
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
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "feature_scope_id": "all",
                    "feature_scope_type": "all",
                    "created_at": pd.Timestamp("2024-02-01"),
                    "metrics_json": "{}",
                }
            ]
        ),
        ["run_id"],
    )
    storage.upsert_df(
        "sector_state_daily",
        pd.DataFrame(
            {
                "run_id": "r",
                "sector_id": "industry:test",
                "trade_date": dates[:10].date,
                "state_id": 0,
                "state_label": "TrendUp",
                "prob_trend_up": 1.0,
                "prob_neutral": 0.0,
                "prob_risk_off": 0.0,
                "next_state_probs_json": "{}",
                "state_source": "in_sample_display",
            }
        ),
        ["run_id", "sector_id", "trade_date"],
    )
    return dates


def _seed_cache(storage: DuckDBStorage, dates: pd.DatetimeIndex, *, state_source: str = "causal_walk_forward", metadata: bool = True) -> None:
    cache_row = {
        "cache_key": "cache",
        "n_states": 3,
        "train_window_days": 60,
        "retrain_frequency": "monthly",
        "feature_version": "v",
        "start_date": dates[0].date(),
        "end_date": dates[-1].date(),
        "params_json": "{}" if metadata else None,
        "params_hash": "hash" if metadata else None,
        "universe_id": None,
        "scope_type": "all",
        "include_custom_baskets": True,
        "rebalance_days": 5,
        "state_date_mode": "rebalance_signals_v2",
        "feature_scope_id": "all",
        "signal_count": 5,
        "row_count": 5,
        "created_at": pd.Timestamp("2024-02-02"),
    }
    storage.upsert_df("walk_forward_cache_runs", pd.DataFrame([cache_row]), ["cache_key"])
    storage.upsert_df(
        "walk_forward_state_cache",
        pd.DataFrame(
            {
                "cache_key": "cache",
                "sector_id": "industry:test",
                "trade_date": dates[:5].date,
                "state_id": 2,
                "state_label": "RiskOff",
                "prob_trend_up": 0.0,
                "prob_neutral": 0.0,
                "prob_risk_off": 1.0,
                "next_state_probs_json": "{}",
                "state_source": state_source,
            }
        ),
        ["cache_key", "sector_id", "trade_date"],
    )


def test_evaluate_forward_returns_without_mode_fails_closed(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_eval_base(storage)

    out = evaluate_forward_returns(storage, "r")

    assert out.empty
    assert out.attrs["evaluation_mode"] == "missing"
    assert out.attrs["evidence_level"] == "exploratory"
    assert out.attrs["readiness_status"] == "research_only"


def test_in_sample_mode_is_research_only_explanation(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_eval_base(storage)

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="in_sample_display")

    assert not out.empty
    assert out["state_source"].eq("in_sample_explanation").all()
    assert out["evidence_level"].eq("exploratory").all()
    assert out["readiness_status"].eq("research_only").all()
    assert out.attrs["state_source"] == "in_sample_explanation"


def test_causal_mode_requires_cache_metadata(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_eval_base(storage)
    _seed_cache(storage, dates, metadata=False)

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="causal", cache_key="cache")

    assert out.empty
    assert out.attrs["readiness_status"] == "research_only"
    assert "causal cache metadata" in out.attrs["warning"]


def test_causal_mode_rejects_in_sample_states(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_eval_base(storage)
    _seed_cache(storage, dates, state_source="in_sample_display")

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="causal", cache_key="cache")

    assert out.empty
    assert out.attrs["readiness_status"] == "research_only"
    assert out.attrs["state_source"] == "in_sample_explanation"


def test_causal_mode_rejects_legacy_walk_forward_state_source(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_eval_base(storage)
    _seed_cache(storage, dates, state_source="causal_backtest")

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="causal", cache_key="cache")

    assert out.empty
    assert out.attrs["readiness_status"] == "research_only"
    assert out.attrs["state_source"] == "unknown_due_to_missing_metadata"
    assert "causal_walk_forward" in out.attrs["warning"]


def test_causal_mode_records_causal_walk_forward_metadata(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_eval_base(storage)
    _seed_cache(storage, dates)

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="causal", cache_key="cache")

    assert not out.empty
    assert out["state_source"].eq("causal_walk_forward").all()
    assert out["evaluation_mode"].eq("causal").all()
    assert out.attrs["causal_cache_id"] == "cache"
