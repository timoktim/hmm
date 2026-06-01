from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline.market_updater import update_market_breadth
from src.data_pipeline.storage import DuckDBStorage
from src.features.market_features import build_market_features
from src.models.market_hmm import label_market_states, train_market_hmm
from src.ui.help_texts import COLUMN_LABELS, HELP_TEXTS, display_state_label, rename_columns_for_display


def _market_index_frame(code: str, name: str, dates: pd.DatetimeIndex, drift: float, vol_scale: float = 0.002) -> pd.DataFrame:
    idx = np.arange(len(dates))
    ret = drift + vol_scale * np.sin(idx / 6)
    close = 1000 * np.cumprod(1 + ret)
    open_ = np.r_[close[0], close[:-1]]
    return pd.DataFrame(
        {
            "index_code": code,
            "index_name": name,
            "trade_date": dates.date,
            "open": open_,
            "high": np.maximum(open_, close) * 1.01,
            "low": np.minimum(open_, close) * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": 10_000_000 + idx * 1000,
            "pct_chg": ret * 100,
            "source": "test",
            "fetched_at": pd.Timestamp("2024-06-01"),
        }
    )


def _seed_market_indices(storage: DuckDBStorage, days: int = 100) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    df = pd.concat(
        [
            _market_index_frame("000300", "沪深300", dates, 0.0010),
            _market_index_frame("000905", "中证500", dates, 0.0006),
            _market_index_frame("000852", "中证1000", dates, 0.0002),
        ],
        ignore_index=True,
    )
    storage.upsert_df("market_index_ohlcv", df, ["index_code", "trade_date"])
    return dates


def test_market_index_storage(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = _market_index_frame("000300", "沪深300", dates, 0.001)
    storage.upsert_df("market_index_ohlcv", df, ["index_code", "trade_date"])

    out = storage.read_df("SELECT * FROM market_index_ohlcv WHERE index_code = '000300'")

    assert len(out) == 3
    assert out.loc[0, "index_name"] == "沪深300"


def test_market_feature_generation(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_market_indices(storage, days=60)

    features = build_market_features(storage)
    latest = features.dropna(subset=["hs300_ret_20d"]).iloc[-1]

    assert "hs300_ret_20d" in features.columns
    assert "hs300_drawdown_20d" in features.columns
    assert "hs300_ma20_slope" in features.columns
    assert np.isfinite(latest["hs300_ret_20d"])
    assert latest["hs300_drawdown_20d"] <= 0


def test_market_breadth_uses_close_returns_when_pct_chg_missing(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    rows: list[dict[str, object]] = []
    for stock_code, daily_ret in [("000001", 0.01), ("000002", -0.01), ("000003", 0.0)]:
        close = 10.0
        for date in dates:
            close *= 1 + daily_ret
            rows.append(
                {
                    "stock_code": stock_code,
                    "trade_date": date.date(),
                    "open": close,
                    "high": close,
                    "low": close,
                    "close": close,
                    "volume": 1000,
                    "amount": 10000,
                    "pct_chg": np.nan,
                    "turnover": np.nan,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-02-01"),
                }
            )
    storage.upsert_df("stock_ohlcv", pd.DataFrame(rows), ["stock_code", "trade_date"])

    summary = update_market_breadth("20240101", "20240130", incremental=False, storage=storage)
    out = storage.read_df("SELECT * FROM market_breadth_daily ORDER BY trade_date")
    latest = out.iloc[-1]

    assert summary.rows == 30
    assert int(latest["up_count"]) == 1
    assert int(latest["down_count"]) == 1
    assert int(latest["unchanged_count"]) == 1
    assert latest["coverage_level"] == "insufficient"
    assert "本地股票样本" in latest["coverage_warning"]


def test_market_breadth_amount_z_uses_calc_window(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    rows: list[dict[str, object]] = []
    close = 10.0
    for i, date in enumerate(dates):
        close *= 1.01
        rows.append(
            {
                "stock_code": "000001",
                "trade_date": date.date(),
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 1000,
                "amount": 1000 + i * 100,
                "pct_chg": np.nan,
                "turnover": np.nan,
                "source": "test",
                "fetched_at": pd.Timestamp("2024-02-01"),
            }
        )
    storage.upsert_df("stock_ohlcv", pd.DataFrame(rows), ["stock_code", "trade_date"])
    storage.upsert_df("market_breadth_daily", pd.DataFrame({"trade_date": [pd.Timestamp("2024-01-25").date()], "breadth_mode": ["local_sample"]}), ["trade_date", "breadth_mode"])

    update_market_breadth("20240101", "20240130", incremental=True, lookback_days=5, storage=storage)
    out = storage.read_df("SELECT trade_date, amount_z_20d FROM market_breadth_daily WHERE trade_date = DATE '2024-01-20'")
    expected_window = pd.Series([1000 + i * 100 for i in range(20)], dtype=float)
    expected = (expected_window.iloc[-1] - expected_window.mean()) / expected_window.std(ddof=0)

    assert not out.empty
    assert np.isclose(out.loc[0, "amount_z_20d"], expected)


def test_market_breadth_uses_effective_count_denominator(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    rows = [
        {"stock_code": "000001", "trade_date": pd.Timestamp("2024-01-01").date(), "close": 10.0, "amount": 1000},
        {"stock_code": "000001", "trade_date": pd.Timestamp("2024-01-02").date(), "close": 11.0, "amount": 1000},
        {"stock_code": "000002", "trade_date": pd.Timestamp("2024-01-01").date(), "close": 10.0, "amount": 1000},
        {"stock_code": "000002", "trade_date": pd.Timestamp("2024-01-02").date(), "close": 9.0, "amount": 1000},
        {"stock_code": "000003", "trade_date": pd.Timestamp("2024-01-02").date(), "close": 10.0, "amount": 1000},
    ]
    df = pd.DataFrame(rows)
    for col in ["open", "high", "low"]:
        df[col] = df["close"]
    df["volume"] = 1000
    df["pct_chg"] = np.nan
    df["turnover"] = np.nan
    df["source"] = "test"
    df["fetched_at"] = pd.Timestamp("2024-02-01")
    storage.upsert_df("stock_ohlcv", df, ["stock_code", "trade_date"])

    update_market_breadth("20240101", "20240102", incremental=False, storage=storage)
    latest = storage.read_df("SELECT * FROM market_breadth_daily WHERE trade_date = DATE '2024-01-02'").iloc[0]

    assert int(latest["total_count"]) == 3
    assert int(latest["effective_count"]) == 2
    assert int(latest["up_count"]) == 1
    assert np.isclose(latest["up_ratio"], 0.5)


def test_market_breadth_above_ma20_uses_valid_ma20_denominator(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=20, freq="D")
    rows: list[dict[str, object]] = []
    for i, date in enumerate(dates):
        rows.extend(
            [
                {"stock_code": "000001", "trade_date": date.date(), "close": 10 + i, "amount": 1000},
                {"stock_code": "000002", "trade_date": date.date(), "close": 30 - i, "amount": 1000},
            ]
        )
    rows.append({"stock_code": "000003", "trade_date": dates[-1].date(), "close": 10.0, "amount": 1000})
    df = pd.DataFrame(rows)
    for col in ["open", "high", "low"]:
        df[col] = df["close"]
    df["volume"] = 1000
    df["pct_chg"] = np.nan
    df["turnover"] = np.nan
    df["source"] = "test"
    df["fetched_at"] = pd.Timestamp("2024-02-01")
    storage.upsert_df("stock_ohlcv", df, ["stock_code", "trade_date"])

    update_market_breadth("20240101", "20240120", incremental=False, storage=storage)
    latest = storage.read_df("SELECT * FROM market_breadth_daily WHERE trade_date = DATE '2024-01-20'").iloc[0]

    assert int(latest["total_count"]) == 3
    assert int(latest["ma20_valid_count"]) == 2
    assert int(latest["above_ma20_count"]) == 1
    assert np.isclose(latest["above_ma20_ratio"], 0.5)


def test_market_state_labeling():
    df = pd.DataFrame(
        {
            "state_id": [0, 0, 1, 1, 2, 2],
            "hs300_ret_20d": [0.10, 0.12, 0.01, 0.00, -0.10, -0.12],
            "zz500_ret_20d": [0.08, 0.09, 0.00, 0.01, -0.08, -0.10],
            "zz1000_ret_20d": [0.07, 0.08, -0.01, 0.01, -0.09, -0.11],
            "hs300_vol_20d": [0.03, 0.03, 0.06, 0.06, 0.12, 0.13],
            "zz500_vol_20d": [0.04, 0.04, 0.07, 0.07, 0.14, 0.15],
            "zz1000_vol_20d": [0.05, 0.05, 0.08, 0.08, 0.16, 0.17],
            "hs300_drawdown_20d": [-0.01, -0.02, -0.05, -0.04, -0.18, -0.20],
            "zz1000_drawdown_20d": [-0.01, -0.02, -0.06, -0.05, -0.22, -0.24],
            "up_ratio": [0.70, 0.72, 0.50, 0.48, 0.25, 0.22],
            "above_ma20_ratio": [0.75, 0.76, 0.48, 0.50, 0.20, 0.18],
        }
    )

    labels = label_market_states(df)

    assert labels[0] == "RiskOn"
    assert labels[2] == "RiskOff"


def test_market_labeling_ignores_missing_major_index_zero_fill():
    df = pd.DataFrame(
        {
            "state_id": [0, 0, 1, 1, 2, 2],
            "hs300_ret_20d": [0.60, 0.60, 0.00, 0.00, -0.20, -0.20],
            "zz500_ret_20d": [0.60, 0.60, 0.00, 0.00, -0.20, -0.20],
            "hs300_vol_20d": [0.0, 0.0, 0.0, 0.0, 0.10, 0.10],
            "zz500_vol_20d": [0.0, 0.0, 0.0, 0.0, 0.10, 0.10],
            "hs300_drawdown_20d": [0.0, 0.0, 0.0, 0.0, -0.20, -0.20],
            "zz500_drawdown_20d": [0.0, 0.0, 0.0, 0.0, -0.20, -0.20],
            "up_ratio": [0.0, 0.0, 0.50, 0.50, 0.20, 0.20],
            "above_ma20_ratio": [0.0, 0.0, 0.50, 0.50, 0.20, 0.20],
        }
    )

    labels = label_market_states(df)

    assert labels[0] == "RiskOn"


def test_market_hmm_labeling_ignores_breadth_when_disabled():
    df = pd.DataFrame(
        {
            "state_id": [0, 0, 1, 1, 2, 2],
            "hs300_ret_20d": [0.12, 0.12, 0.01, 0.01, -0.08, -0.08],
            "zz500_ret_20d": [0.10, 0.10, 0.01, 0.01, -0.08, -0.08],
            "zz1000_ret_20d": [0.08, 0.08, 0.01, 0.01, -0.08, -0.08],
            "hs300_vol_20d": [0.02, 0.02, 0.02, 0.02, 0.10, 0.10],
            "zz500_vol_20d": [0.02, 0.02, 0.02, 0.02, 0.10, 0.10],
            "zz1000_vol_20d": [0.02, 0.02, 0.02, 0.02, 0.10, 0.10],
            "hs300_drawdown_20d": [0.0, 0.0, 0.0, 0.0, -0.18, -0.18],
            "zz1000_drawdown_20d": [0.0, 0.0, 0.0, 0.0, -0.18, -0.18],
            "up_ratio": [0.0, 0.0, 0.95, 0.95, 0.1, 0.1],
            "above_ma20_ratio": [0.0, 0.0, 0.95, 0.95, 0.1, 0.1],
        }
    )

    without_breadth = label_market_states(df, use_breadth=False)
    with_breadth = label_market_states(df, use_breadth=True)

    assert without_breadth[0] == "RiskOn"
    assert with_breadth[1] == "RiskOn"


def test_market_hmm_training(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=100)
    breadth = pd.DataFrame(
        {
            "trade_date": dates.date,
            "up_count": 2000,
            "down_count": 1000,
            "unchanged_count": 100,
            "limit_up_count": 50,
            "limit_down_count": 20,
            "above_ma20_count": 1800,
            "below_ma20_count": 1200,
            "total_count": 3000,
            "effective_count": 3000,
            "ma20_valid_count": 3000,
            "expected_count": 3000,
            "coverage_ratio": 1.0,
            "breadth_mode": "full_market",
            "up_ratio": np.linspace(0.45, 0.65, len(dates)),
            "above_ma20_ratio": np.linspace(0.40, 0.70, len(dates)),
            "amount_total": np.linspace(1e10, 1.5e10, len(dates)),
            "amount_z_20d": np.sin(np.arange(len(dates)) / 10),
            "coverage_level": "full_market",
            "coverage_warning": "",
            "source": "test",
            "fetched_at": pd.Timestamp("2024-06-01"),
        }
    )
    storage.upsert_df("market_breadth_daily", breadth, ["trade_date", "breadth_mode"])

    result = train_market_hmm("20240101", "20240430", n_states=3, use_breadth=True, n_iter=5, storage=storage)
    out = storage.read_df("SELECT * FROM market_regime_daily WHERE run_id = ?", [result.run_id])

    assert not out.empty
    assert {"prob_risk_on", "prob_neutral", "prob_risk_off", "state_label"}.issubset(out.columns)
    assert result.used_breadth


def test_market_hmm_degrades_when_breadth_is_partial(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=100)
    breadth = pd.DataFrame(
        {
            "trade_date": dates.date,
            "up_count": 400,
            "down_count": 600,
            "unchanged_count": 0,
            "limit_up_count": 10,
            "limit_down_count": 5,
            "above_ma20_count": 450,
            "below_ma20_count": 550,
            "total_count": 1000,
            "effective_count": 1000,
            "ma20_valid_count": 1000,
            "expected_count": 3000,
            "coverage_ratio": 1 / 3,
            "breadth_mode": "local_sample",
            "up_ratio": np.linspace(0.45, 0.65, len(dates)),
            "above_ma20_ratio": np.linspace(0.40, 0.70, len(dates)),
            "amount_total": np.linspace(1e10, 1.5e10, len(dates)),
            "amount_z_20d": np.sin(np.arange(len(dates)) / 10),
            "coverage_level": "partial_sample",
            "coverage_warning": "当前市场宽度不是全市场宽度，只反映本地股票样本。",
            "source": "test",
            "fetched_at": pd.Timestamp("2024-06-01"),
        }
    )
    storage.upsert_df("market_breadth_daily", breadth, ["trade_date", "breadth_mode"])

    result = train_market_hmm("20240101", "20240430", n_states=3, use_breadth=True, n_iter=5, storage=storage)
    run = storage.read_df("SELECT metrics_json FROM market_regime_runs WHERE run_id = ?", [result.run_id])
    metrics = json.loads(run.loc[0, "metrics_json"])

    assert not result.used_breadth
    assert "纯指数特征" in result.breadth_coverage_warning
    assert "up_ratio" not in metrics["feature_columns"]


def test_market_hmm_requires_major_index_override_when_only_one_major_index(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=100, freq="D")
    storage.upsert_df("market_index_ohlcv", _market_index_frame("000300", "沪深300", dates, 0.0010), ["index_code", "trade_date"])

    with pytest.raises(ValueError, match="允许指数覆盖不足"):
        train_market_hmm("20240101", "20240430", n_states=3, use_breadth=False, n_iter=5, storage=storage)

    result = train_market_hmm(
        "20240101",
        "20240430",
        n_states=3,
        use_breadth=False,
        n_iter=5,
        allow_insufficient_index_coverage=True,
        storage=storage,
    )

    assert result.index_coverage_warning


def test_help_texts_complete():
    for key in [
        "trend_up_threshold",
        "top_n",
        "rebalance_every",
        "train_window",
        "transaction_cost",
        "max_drawdown_threshold",
        "amount_z_min",
        "market_regime",
        "use_breadth",
    ]:
        assert HELP_TEXTS.get(key)


def test_ui_column_rename_mapping():
    df = pd.DataFrame(
        {
            "sector_type": ["industry"],
            "sector_name": ["半导体"],
            "prob_trend_up": [0.8],
            "score": [1.2],
            "state_label": ["RiskOn"],
            "strategy": ["baseline_1_rs20_top_n"],
        }
    )
    renamed = rename_columns_for_display(df)

    assert "板块类型" in renamed.columns
    assert "板块名称" in renamed.columns
    assert "趋势状态置信度" in renamed.columns
    assert "个股评分" in renamed.columns
    assert renamed.loc[0, "板块类型"] == "行业"
    assert renamed.loc[0, "当前状态"] == "风险偏好"
    assert renamed.loc[0, "策略"] == "20日相对强弱轮动"
    assert display_state_label("RiskOff") == "风险回避"
    assert COLUMN_LABELS["last_network_success"] == "最近网络成功"
