from __future__ import annotations

import numpy as np
import pandas as pd

from src.analysis.sector_cycles import build_state_segments, build_stock_overlay_normalized_series, screen_state_transitions
from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.model_evaluation import evaluate_forward_returns
from src.models.market_hmm import train_market_hmm
from src.ui.sector_detail import _prefilled_sector_choice
from src.ui.state_screener_page import walk_forward_cache_options_for_scope


def _states() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=9, freq="D")
    labels = ["Neutral", "Neutral", "Neutral", "TrendUp", "TrendUp", "TrendUp", "RiskOff", "RiskOff", "Neutral"]
    return pd.DataFrame(
        {
            "run_id": "r",
            "sector_id": "S",
            "trade_date": dates,
            "state_label": labels,
            "prob_trend_up": [0.2, 0.3, 0.35, 0.7, 0.75, 0.8, 0.1, 0.1, 0.4],
            "prob_neutral": [0.7, 0.6, 0.55, 0.2, 0.15, 0.1, 0.2, 0.2, 0.5],
            "prob_risk_off": [0.1, 0.1, 0.1, 0.1, 0.1, 0.1, 0.7, 0.7, 0.1],
        }
    )


def _ohlcv() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=9, freq="D")
    close = [100, 101, 102, 104, 106, 105, 100, 98, 99]
    return pd.DataFrame({"sector_id": "S", "trade_date": dates, "close": close})


def test_market_breadth_daily_supports_multiple_modes(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    date = pd.Timestamp("2024-01-02").date()
    rows = pd.DataFrame(
        [
            {"trade_date": date, "breadth_mode": "local_sample", "coverage_level": "partial_sample", "effective_count": 100},
            {"trade_date": date, "breadth_mode": "full_market", "coverage_level": "full_market", "coverage_ratio": 0.9, "effective_count": 3000},
        ]
    )
    storage.upsert_df("market_breadth_daily", rows, ["trade_date", "breadth_mode"])
    out = storage.read_df("SELECT trade_date, breadth_mode, effective_count FROM market_breadth_daily WHERE trade_date = ? ORDER BY breadth_mode", [date])

    assert len(out) == 2
    assert set(out["breadth_mode"]) == {"local_sample", "full_market"}


def test_market_hmm_uses_only_full_market_breadth(tmp_path):
    from tests.test_market_regime import _seed_market_indices

    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=100)
    breadth = pd.DataFrame(
        {
            "trade_date": dates.date,
            "breadth_mode": "local_sample",
            "coverage_level": "partial_sample",
            "coverage_ratio": 1.0,
            "effective_count": 3000,
            "total_count": 3000,
            "up_ratio": np.linspace(0.4, 0.7, len(dates)),
            "above_ma20_ratio": np.linspace(0.4, 0.7, len(dates)),
            "amount_z_20d": np.sin(np.arange(len(dates)) / 10),
        }
    )
    storage.upsert_df("market_breadth_daily", breadth, ["trade_date", "breadth_mode"])

    result = train_market_hmm("20240101", "20240430", n_states=3, use_breadth=True, n_iter=5, storage=storage)

    assert not result.used_breadth
    assert "全 A 市场宽度" in result.breadth_coverage_warning


def test_evaluate_forward_returns_uses_walk_forward_cache(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = [100 + i for i in range(len(dates))]
    ohlcv = pd.DataFrame({"sector_id": "S", "trade_date": dates.date, "open": close, "high": close, "low": close, "close": close, "volume": 1, "amount": 1, "pct_chg": 0, "turnover": 0, "source": "test", "fetched_at": pd.Timestamp("2024-02-01")})
    storage.upsert_df("sector_ohlcv", ohlcv, ["sector_id", "trade_date"])
    storage.upsert_df("model_runs", pd.DataFrame([{"run_id": "r", "model_type": "GaussianHMM", "n_states": 3, "train_start": dates[0].date(), "train_end": dates[-1].date(), "feature_version": "v", "model_path": "", "scaler_path": "", "scope_type": "all", "include_custom_baskets": True, "feature_scope_id": "all", "feature_scope_type": "all", "created_at": pd.Timestamp("2024-02-01"), "metrics_json": "{}"}]), ["run_id"])
    storage.upsert_df("sector_state_daily", pd.DataFrame({"run_id": "r", "sector_id": "S", "trade_date": dates[:5].date, "state_id": 0, "state_label": "TrendUp", "prob_trend_up": 1, "prob_neutral": 0, "prob_risk_off": 0, "next_state_probs_json": "{}", "state_source": "in_sample_display"}), ["run_id", "sector_id", "trade_date"])
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
            ]
        ),
        ["cache_key"],
    )
    storage.upsert_df("walk_forward_state_cache", pd.DataFrame({"cache_key": "cache", "sector_id": "S", "trade_date": dates[:5].date, "state_id": 2, "state_label": "RiskOff", "prob_trend_up": 0, "prob_neutral": 0, "prob_risk_off": 1, "next_state_probs_json": "{}", "state_source": "causal_walk_forward"}), ["cache_key", "sector_id", "trade_date"])

    out = evaluate_forward_returns(storage, "r", horizons=(5,), state_source="walk_forward", cache_key="cache", evaluation_mode="causal")

    assert set(out["state_label"]) == {"RiskOff"}
    assert out["state_source"].eq("causal_walk_forward").all()
    assert out["readiness_status"].eq("validated").all()
    assert out.attrs["state_source"] == "causal_walk_forward"


def test_state_screener_cache_options_are_scope_filtered(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "walk_forward_cache_runs",
        pd.DataFrame(
            [
                {
                    "cache_key": "all_cache",
                    "n_states": 3,
                    "train_window_days": 60,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": pd.Timestamp("2024-01-01").date(),
                    "end_date": pd.Timestamp("2024-02-01").date(),
                    "params_json": "{}",
                    "params_hash": "a",
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": "all",
                    "lineage_hash": "lineage-all",
                    "feature_lineage_hash": "feature-all",
                    "cache_status": "completed",
                    "signal_count": 1,
                    "row_count": 1,
                    "created_at": pd.Timestamp("2024-02-01"),
                },
                {
                    "cache_key": "u_cache",
                    "n_states": 3,
                    "train_window_days": 60,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": pd.Timestamp("2024-01-01").date(),
                    "end_date": pd.Timestamp("2024-02-01").date(),
                    "params_json": "{}",
                    "params_hash": "u",
                    "universe_id": "u1",
                    "scope_type": "universe",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": "universe:u1:with_custom",
                    "lineage_hash": "lineage-u1",
                    "feature_lineage_hash": "feature-u1",
                    "cache_status": "completed",
                    "signal_count": 1,
                    "row_count": 1,
                    "created_at": pd.Timestamp("2024-02-02"),
                },
            ]
        ),
        ["cache_key"],
    )
    storage.upsert_df(
        "walk_forward_state_cache",
        pd.DataFrame(
            [
                {
                    "cache_key": "all_cache",
                    "sector_id": "S1",
                    "trade_date": pd.Timestamp("2024-02-01").date(),
                    "state_id": 1,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "max_observation_date_used": pd.Timestamp("2024-02-01").date(),
                    "state_source": "causal_walk_forward",
                    "lineage_hash": "lineage-all",
                    "feature_lineage_hash": "feature-all",
                },
                {
                    "cache_key": "u_cache",
                    "sector_id": "S1",
                    "trade_date": pd.Timestamp("2024-02-01").date(),
                    "state_id": 1,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "max_observation_date_used": pd.Timestamp("2024-02-01").date(),
                    "state_source": "causal_walk_forward",
                    "lineage_hash": "lineage-u1",
                    "feature_lineage_hash": "feature-u1",
                },
            ]
        ),
        ["cache_key", "sector_id", "trade_date"],
    )

    all_options = walk_forward_cache_options_for_scope(storage)
    universe_options = walk_forward_cache_options_for_scope(storage, "u1")

    assert set(all_options["cache_key"]) == {"all_cache"}
    assert set(universe_options["cache_key"]) == {"u_cache"}


def test_build_state_segments():
    out = build_state_segments(_states(), _ohlcv())

    assert out["state_label"].tolist() == ["Neutral", "TrendUp", "RiskOff", "Neutral"]
    assert out["trading_days"].tolist() == [3, 3, 2, 1]
    assert out.loc[1, "prev_state_label"] == "Neutral"
    assert out.loc[1, "next_state_label"] == "RiskOff"


def test_screen_neutral_to_trendup():
    states = _states()
    segments = build_state_segments(states, _ohlcv())
    latest = states[states["trade_date"].eq(pd.Timestamp("2024-01-06"))].copy()
    latest["state_label"] = "TrendUp"
    result = screen_state_transitions(
        segments[segments["segment_id"].le(2)],
        latest,
        {"from_state": "Neutral", "to_state": "TrendUp", "current_segment_max_days": 5, "min_previous_segment_days": 3, "prob_trend_up_min": 0.55, "prob_risk_off_max": 0.3, "only_current_state": True},
    )

    assert len(result) == 1
    assert result.iloc[0]["from_state"] == "Neutral"
    assert result.iloc[0]["to_state"] == "TrendUp"


def test_sector_cycle_stats():
    out = build_state_segments(_states(), _ohlcv())
    trend = out[out["state_label"].eq("TrendUp")].iloc[0]

    assert trend["trading_days"] == 3
    assert np.isclose(float(trend["segment_return"]), 105 / 104 - 1)
    assert float(trend["max_drawdown"]) <= 0


def test_stock_overlay_normalized_series():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    sector = pd.DataFrame({"trade_date": dates, "close": [100, 110, 121]})
    stocks = pd.DataFrame({"stock_code": ["000001"] * 3, "trade_date": dates, "close": [10, 11, 12]})

    out = build_stock_overlay_normalized_series(sector, stocks, stock_names={"000001": "测试"})

    assert out.groupby("label")["normalized_close"].first().eq(100).all()
    assert "000001 测试" in set(out["label"])


def test_sector_detail_prefills_selected_sector_from_session_state():
    meta = pd.DataFrame(
        [
            {"sector_id": "industry:A", "sector_type": "industry", "sector_name": "A行业"},
            {"sector_id": "concept:B", "sector_type": "concept", "sector_name": "B概念"},
        ]
    )

    sector_type, sector_name = _prefilled_sector_choice(meta, "concept:B")

    assert sector_type == "concept"
    assert sector_name == "B概念"
