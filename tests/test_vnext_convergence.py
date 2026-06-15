from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation import model_evaluation
from src.evaluation.model_evaluation import evaluate_forward_returns
from src.models.inference import latest_sector_states
from src.scoring.stock_filter import filter_sector_stocks
from src.ui.components.data_status_bar import build_data_status_bar_summary
from src.ui.components.data_trust_card import build_data_trust_summary
from src.ui.market_regime_page import market_width_visibility_by_coverage


def test_sector_features_scope_isolated(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    date = pd.Timestamp("2024-02-01").date()
    features = pd.DataFrame(
        [
            {"sector_id": "A", "trade_date": date, "ret_1d": 0, "ret_5d": 0, "ret_20d": 0.1, "vol_20d": 0.1, "amount_z_20d": 0, "rs_20d": 0.30, "drawdown_20d": 0, "ma20_slope": 0.01, "feature_version": "v", "feature_scope_id": "scope:one", "feature_scope_type": "universe"},
            {"sector_id": "A", "trade_date": date, "ret_1d": 0, "ret_5d": 0, "ret_20d": 0.1, "vol_20d": 0.1, "amount_z_20d": 0, "rs_20d": -0.20, "drawdown_20d": 0, "ma20_slope": 0.01, "feature_version": "v", "feature_scope_id": "scope:two", "feature_scope_type": "universe"},
        ]
    )
    storage.upsert_df("sector_features", features, ["sector_id", "trade_date", "feature_version", "feature_scope_id"])
    states = pd.DataFrame(
        [
            {"run_id": "run_one", "sector_id": "A", "trade_date": date, "state_id": 0, "state_label": "TrendUp", "prob_trend_up": 0.9, "prob_neutral": 0.1, "prob_risk_off": 0.0, "next_state_probs_json": "{}", "state_source": "in_sample_display"},
            {"run_id": "run_two", "sector_id": "A", "trade_date": date, "state_id": 0, "state_label": "TrendUp", "prob_trend_up": 0.9, "prob_neutral": 0.1, "prob_risk_off": 0.0, "next_state_probs_json": "{}", "state_source": "in_sample_display"},
        ]
    )
    storage.upsert_df("sector_state_daily", states, ["run_id", "sector_id", "trade_date"])
    runs = pd.DataFrame(
        [
            {"run_id": "run_one", "model_type": "GaussianHMM", "n_states": 3, "train_start": date, "train_end": date, "feature_version": "v", "model_path": "", "scaler_path": "", "universe_id": "u1", "scope_type": "universe", "include_custom_baskets": True, "feature_scope_id": "scope:one", "feature_scope_type": "universe", "created_at": pd.Timestamp("2024-02-01"), "metrics_json": "{}"},
            {"run_id": "run_two", "model_type": "GaussianHMM", "n_states": 3, "train_start": date, "train_end": date, "feature_version": "v", "model_path": "", "scaler_path": "", "universe_id": "u2", "scope_type": "universe", "include_custom_baskets": True, "feature_scope_id": "scope:two", "feature_scope_type": "universe", "created_at": pd.Timestamp("2024-02-02"), "metrics_json": "{}"},
        ]
    )
    storage.upsert_df("model_runs", runs, ["run_id"])

    one = latest_sector_states(storage, run_id="run_one")
    two = latest_sector_states(storage, run_id="run_two")

    assert one.loc[0, "rs_20d"] == 0.30
    assert two.loc[0, "rs_20d"] == -0.20


def test_model_evaluation_forward_returns(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    close = [100 + i for i in range(len(dates))]
    ohlcv = pd.DataFrame({"sector_id": "A", "trade_date": dates.date, "open": close, "high": close, "low": close, "close": close, "volume": 1, "amount": 1, "pct_chg": 0, "turnover": 0, "source": "test", "fetched_at": pd.Timestamp("2024-02-01")})
    storage.upsert_df("sector_ohlcv", ohlcv, ["sector_id", "trade_date"])
    state_rows = pd.DataFrame({"run_id": "r", "sector_id": "A", "trade_date": dates[:10].date, "state_id": 0, "state_label": "TrendUp", "prob_trend_up": 1.0, "prob_neutral": 0.0, "prob_risk_off": 0.0, "next_state_probs_json": "{}", "state_source": "in_sample_display"})
    storage.upsert_df("sector_state_daily", state_rows, ["run_id", "sector_id", "trade_date"])
    storage.upsert_df("model_runs", pd.DataFrame([{"run_id": "r", "model_type": "GaussianHMM", "n_states": 3, "train_start": dates[0].date(), "train_end": dates[-1].date(), "feature_version": "v", "model_path": "", "scaler_path": "", "universe_id": None, "scope_type": "all", "include_custom_baskets": True, "feature_scope_id": "all", "feature_scope_type": "all", "created_at": pd.Timestamp("2024-02-01"), "metrics_json": "{}"}]), ["run_id"])

    out = evaluate_forward_returns(storage, "r", horizons=(5,), evaluation_mode="in_sample_display")

    assert not out.empty
    assert out.loc[0, "state_label"] == "TrendUp"
    assert out.loc[0, "sample_count"] == 10
    assert out.loc[0, "mean_return"] > 0
    assert out["state_source"].eq("in_sample_explanation").all()
    assert out["readiness_status"].eq("research_only").all()
    assert out.attrs["readiness_status"] == "research_only"


def test_model_evaluation_baseline_compare(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()

    def fake_backtest(**kwargs):
        return {"comparison": pd.DataFrame({"strategy": ["model", "baseline_1_rs20_top_n", "baseline_2_equal_weight"], "annual_return_net": [0.1, 0.08, 0.05]})}

    monkeypatch.setattr(model_evaluation, "run_sector_rotation_backtest", fake_backtest)
    out = model_evaluation.evaluate_strategy_comparison(storage, "r", universe_id="u")

    assert set(out["strategy"]) == {"model", "baseline_1_rs20_top_n", "baseline_2_equal_weight"}
    assert out["causal_walk_forward"].all()
    assert out["uses_transaction_cost"].all()


def test_stock_filter_funnel_counts(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    cons = pd.DataFrame(
        [
            {"sector_id": "S", "stock_code": "000001", "stock_name": "通过股份"},
            {"sector_id": "S", "stock_code": "000002", "stock_name": "ST风险"},
        ]
    )
    storage.upsert_df("sector_constituents", cons, ["sector_id", "stock_code"])
    sector = pd.DataFrame({"sector_id": "S", "trade_date": dates.date, "open": 100, "high": 100, "low": 100, "close": 100, "volume": 1, "amount": 1, "pct_chg": 0, "turnover": 0, "source": "test", "fetched_at": pd.Timestamp("2024-02-01")})
    storage.upsert_df("sector_ohlcv", sector, ["sector_id", "trade_date"])
    rows = []
    for code, base in [("000001", 10), ("000002", 10)]:
        for i, date in enumerate(dates):
            close = base + i
            rows.append({"stock_code": code, "trade_date": date.date(), "open": close, "high": close, "low": close, "close": close, "volume": 1, "amount": 1000 + i * 10, "pct_chg": 0, "turnover": 0, "source": "test", "fetched_at": pd.Timestamp("2024-02-01")})
    storage.upsert_df("stock_ohlcv", pd.DataFrame(rows), ["stock_code", "trade_date"])

    _, diagnostics = filter_sector_stocks("S", min_amount_z=-99, require_rs_vs_index_positive=False, return_diagnostics=True, storage=storage)

    assert diagnostics["total"] == 2
    assert diagnostics["filters"][0]["condition"] == "排除 ST / 退市风险名称"
    assert diagnostics["filters"][0]["after"] == 1
    assert diagnostics["failed_examples"][0]["failed_reason"] == "ST / 退市风险"


def test_dashboard_data_trust_card(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df("market_breadth_daily", pd.DataFrame([{"trade_date": pd.Timestamp("2024-01-01").date(), "coverage_level": "partial_sample", "breadth_mode": "local_sample"}]), ["trade_date", "breadth_mode"])

    summary = build_data_trust_summary(storage)

    assert summary.market_width_level == "本地样本/部分样本"
    assert summary.stale_reads == 0


def test_data_status_uses_latest_breadth_date_before_full_market_preference(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "market_breadth_daily",
        pd.DataFrame(
            [
                {
                    "trade_date": pd.Timestamp("2024-01-01").date(),
                    "coverage_level": "full_market",
                    "breadth_mode": "full_market",
                    "coverage_ratio": 0.9,
                    "effective_count": 3000,
                    "fetched_at": pd.Timestamp("2024-01-01 10:00:00"),
                },
                {
                    "trade_date": pd.Timestamp("2024-01-02").date(),
                    "coverage_level": "partial_sample",
                    "breadth_mode": "local_sample",
                    "coverage_ratio": 1.0,
                    "effective_count": 100,
                    "fetched_at": pd.Timestamp("2024-01-02 10:00:00"),
                },
            ]
        ),
        ["trade_date", "breadth_mode"],
    )

    trust = build_data_trust_summary(storage)
    bar = build_data_status_bar_summary(storage)

    assert trust.market_width_level == "本地样本/部分样本"
    assert "宽度：本地样本/部分样本" in bar.message
    assert any(item.label == "宽度" and item.value == "本地样本/部分样本" for item in bar.items)


def test_historical_stale_cache_not_current_problem(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "data_health",
        pd.DataFrame(
            [
                {
                    "interface": "stock_zh_a_hist_tx",
                    "last_network_success": pd.Timestamp("2024-01-02 10:00:00"),
                    "last_network_failure": pd.Timestamp("2024-01-01 10:00:00"),
                    "last_cache_hit": pd.Timestamp("2024-01-01 10:00:01"),
                    "stale_reads": 3239,
                    "cache_hits": 3239,
                    "network_hits": 1,
                }
            ]
        ),
        ["interface"],
    )

    summary = build_data_trust_summary(storage)

    assert summary.stale_reads == 0
    assert summary.historical_stale_reads == 3239


def test_market_width_visibility_by_coverage():
    assert market_width_visibility_by_coverage("full_market")[0]
    visible, message = market_width_visibility_by_coverage("partial_sample")
    assert not visible
    assert "本地已抓取股票样本" in message


def test_market_regime_delegates_global_data_updates_to_data_center():
    source = Path("src/ui/market_regime_page.py").read_text(encoding="utf-8")

    assert "更新本地样本宽度" in source
    assert "底层数据更新已统一归口到“数据中心”" in source
    assert "更新大盘指数数据" not in source
    assert "更新全 A 股票池" not in source
    assert "更新全 A 市场宽度" not in source
    assert "update_market_indices" not in source
    assert "update_all_a_stock_universe" not in source
