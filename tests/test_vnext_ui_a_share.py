from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data_pipeline.market_updater import update_all_a_stock_universe, update_market_breadth
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import DataResult
from src.features.stock_features import add_a_share_limit_flags
from src.models.hmm_model import train_hmm
from src.models.market_hmm import train_market_hmm
from src.ui.components.data_status_bar import build_data_status_bar_summary
from src.ui.components.operation_result import operation_summary_line
from src.ui.formatters import format_probability, parse_next_state_probs
from src.ui.market_regime_page import breadth_chart_diagnostics, latest60_full_market_breadth_available


class FakeUniverseClient:
    def all_a_stock_universe(self, force_refresh: bool = False):
        return DataResult(
            pd.DataFrame(
                {
                    "stock_code": ["000001", "600000"],
                    "stock_name": ["平安银行", "浦发银行"],
                }
            )
        )


def _stock_rows(codes: list[str], dates: pd.DatetimeIndex) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for code_i, code in enumerate(codes):
        close = 10 + code_i
        for i, date in enumerate(dates):
            close *= 1 + (0.01 if (i + code_i) % 2 == 0 else -0.005)
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": date.date(),
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1000,
                    "amount": 10000 + i,
                    "pct_chg": np.nan,
                    "turnover": np.nan,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-02-01"),
                }
            )
    return pd.DataFrame(rows)


def test_format_probability_tiny_values():
    assert format_probability(np.nan) == "无"
    assert format_probability(0.0) == "0.00%"
    assert format_probability(0.00001) == "<0.01%"
    assert format_probability(0.99999) == "99.99%+"


def test_next_state_probs_are_parsed_for_display():
    parsed = parse_next_state_probs(json.dumps({"TrendUp": 0.6, "Neutral": 0.3, "RiskOff": 0.1}), model_type="sector")
    assert parsed["next_prob_trend_up"] == 0.6
    assert parsed["next_prob_neutral"] == 0.3
    assert parsed["next_prob_risk_off"] == 0.1


def test_operation_result_collapsed_by_default():
    line = operation_summary_line({"updated": 3, "failures": ["x"], "cache_hits": 2, "stale_reads": 1, "rows": 20, "skipped": 5})
    assert "成功 3" in line
    assert "失败 1" in line
    assert "跳过 5" in line
    assert "写入行数 20" in line


def test_all_a_universe_storage(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()

    summary = update_all_a_stock_universe(client=FakeUniverseClient(), storage=storage)
    out = storage.read_df("SELECT * FROM all_a_stock_universe ORDER BY stock_code")

    assert summary.rows == 2
    assert out["stock_code"].tolist() == ["000001", "600000"]
    assert out["exchange"].tolist() == ["SZ", "SH"]


def test_full_market_breadth_requires_universe(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    summary = update_market_breadth("20240101", "20240102", incremental=False, mode="full_market", storage=storage)
    assert summary.failures
    assert "全 A 股票池" in summary.failures[0]


def test_coverage_ratio_calculation(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    codes = [f"{i:06d}" for i in range(10)]
    universe = pd.DataFrame(
        {
            "stock_code": codes,
            "stock_name": codes,
            "exchange": "SZ",
            "list_status": "active",
            "is_st": False,
            "source": "test",
            "fetched_at": pd.Timestamp("2024-02-01"),
        }
    )
    storage.upsert_df("all_a_stock_universe", universe, ["stock_code"])
    dates = pd.date_range("2024-01-01", periods=25, freq="D")
    storage.upsert_df("stock_ohlcv", _stock_rows(codes[:5], dates), ["stock_code", "trade_date"])

    update_market_breadth("20240101", "20240125", incremental=False, mode="full_market", storage=storage)
    latest = storage.read_df("SELECT * FROM market_breadth_daily ORDER BY trade_date DESC LIMIT 1").iloc[0]

    assert int(latest["expected_count"]) == 10
    assert int(latest["effective_count"]) == 5
    assert np.isclose(float(latest["coverage_ratio"]), 0.5)
    assert latest["breadth_mode"] == "full_market"
    assert latest["coverage_level"] == "partial_sample"


def test_local_sample_not_marked_full_market(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    codes = [f"{i:06d}" for i in range(600)]
    dates = pd.date_range("2024-01-01", periods=2, freq="D")
    storage.upsert_df("stock_ohlcv", _stock_rows(codes, dates), ["stock_code", "trade_date"])

    update_market_breadth("20240101", "20240102", incremental=False, mode="local_sample", storage=storage)
    latest = storage.read_df("SELECT coverage_level, breadth_mode FROM market_breadth_daily ORDER BY trade_date DESC LIMIT 1").iloc[0]

    assert latest["breadth_mode"] == "local_sample"
    assert latest["coverage_level"] != "full_market"


def test_market_width_disabled_when_not_full_market(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=60, freq="D")
    storage.upsert_df(
        "market_breadth_daily",
        pd.DataFrame(
            {
                "trade_date": dates.date,
                "coverage_level": "partial_sample",
                "breadth_mode": "local_sample",
                "effective_count": 100,
                "coverage_ratio": 1.0,
            }
        ),
        ["trade_date", "breadth_mode"],
    )

    ready, message = latest60_full_market_breadth_available(storage)

    assert not ready
    assert "纯指数特征" in message


def test_breadth_chart_diagnostics_flat_line():
    df = pd.DataFrame({"up_ratio": [0.5] * 30, "effective_count": [100] * 30, "total_count": [100] * 30, "ma20_valid_count": [90] * 30})
    diagnostics = breadth_chart_diagnostics(df)
    assert diagnostics["flat_warning"] is True
    assert diagnostics["up_ratio_std"] == 0


def test_market_hmm_disables_breadth_when_coverage_low(tmp_path):
    from tests.test_market_regime import _seed_market_indices

    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=100)
    storage.upsert_df(
        "market_breadth_daily",
        pd.DataFrame(
            {
                "trade_date": dates.date,
                "up_count": 50,
                "down_count": 50,
                "unchanged_count": 0,
                "limit_up_count": 0,
                "limit_down_count": 0,
                "above_ma20_count": 50,
                "below_ma20_count": 50,
                "total_count": 100,
                "effective_count": 100,
                "ma20_valid_count": 100,
                "expected_count": 5000,
                "coverage_ratio": 0.02,
                "breadth_mode": "full_market",
                "up_ratio": np.linspace(0.45, 0.55, len(dates)),
                "above_ma20_ratio": np.linspace(0.40, 0.50, len(dates)),
                "amount_total": np.linspace(1e10, 1.2e10, len(dates)),
                "amount_z_20d": np.sin(np.arange(len(dates)) / 10),
                "coverage_level": "insufficient",
                "coverage_warning": "低覆盖",
                "source": "test",
                "fetched_at": pd.Timestamp("2024-06-01"),
            }
        ),
        ["trade_date", "breadth_mode"],
    )
    result = train_market_hmm("20240101", "20240430", n_states=3, use_breadth=True, n_iter=5, storage=storage)
    assert not result.used_breadth


def test_hmm_training_progress_callback(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = pd.date_range("2024-01-01", periods=70, freq="D")
    rows: list[dict[str, object]] = []
    for sector_i in range(3):
        close = 100 + sector_i * 10
        for i, date in enumerate(dates):
            close *= 1 + 0.001 * np.sin((i + sector_i) / 4)
            rows.append(
                {
                    "sector_id": f"industry:S{sector_i}",
                    "trade_date": date.date(),
                    "open": close,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1,
                    "amount": 10000 + i,
                    "pct_chg": 0,
                    "turnover": 0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-02-01"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])
    events: list[tuple[int, str]] = []

    train_hmm("20240101", "20240331", n_states=2, n_iter=2, n_init=1, storage=storage, progress_callback=lambda p, s, _: events.append((p, s)))

    assert events[0][0] == 10
    assert events[-1][0] == 100
    assert any(stage == "训练 HMM" for _, stage in events)


def test_a_share_limit_flags():
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    df = pd.DataFrame(
        {
            "stock_code": ["000001", "000001", "000001"],
            "trade_date": dates,
            "open": [10, 11, 12.1],
            "high": [10, 11, 12.1],
            "low": [10, 11, 12.1],
            "close": [10, 11, 12.1],
            "volume": [100, 100, 100],
            "amount": [1000, 1000, 1000],
        }
    )
    out = add_a_share_limit_flags(df)

    assert bool(out.iloc[1]["is_limit_up"])
    assert bool(out.iloc[1]["is_one_word_limit"])
    assert int(out.iloc[2]["consecutive_limit_up_days"]) == 2


def test_data_status_bar_turns_yellow_for_local_width(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "market_breadth_daily",
        pd.DataFrame([{"trade_date": pd.Timestamp("2024-01-01").date(), "coverage_level": "partial_sample", "breadth_mode": "local_sample"}]),
        ["trade_date", "breadth_mode"],
    )
    summary = build_data_status_bar_summary(storage, run_id="missing")
    assert summary.level in {"yellow", "red"}
