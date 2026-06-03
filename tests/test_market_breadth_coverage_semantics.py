from __future__ import annotations

import numpy as np
import pandas as pd
from pathlib import Path

from src.data_pipeline.market_updater import _coverage_level, _ensure_market_breadth_coverage_columns, update_market_breadth
from src.data_pipeline.storage import DuckDBStorage
from src.features.market_features import build_market_features


def _market_index_frame(code: str, name: str, dates: pd.DatetimeIndex, drift: float) -> pd.DataFrame:
    idx = np.arange(len(dates))
    ret = drift + 0.001 * np.sin(idx / 7)
    close = 1000 * np.cumprod(1 + ret)
    return pd.DataFrame(
        {
            "index_code": code,
            "index_name": name,
            "trade_date": dates.date,
            "open": np.r_[close[0], close[:-1]],
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": 1_000_000,
            "amount": 10_000_000 + idx * 1000,
            "pct_chg": ret * 100,
            "source": "test",
            "fetched_at": pd.Timestamp("2026-06-03"),
        }
    )


def _seed_market_indices(storage: DuckDBStorage, days: int = 100) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    storage.upsert_df(
        "market_index_ohlcv",
        pd.concat(
            [
                _market_index_frame("000300", "沪深300", dates, 0.0010),
                _market_index_frame("000905", "中证500", dates, 0.0006),
                _market_index_frame("000852", "中证1000", dates, 0.0002),
            ],
            ignore_index=True,
        ),
        ["index_code", "trade_date"],
    )
    return dates


def _seed_local_stock_sample(storage: DuckDBStorage, days: int = 30) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
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
                    "fetched_at": pd.Timestamp("2026-06-03"),
                }
            )
    storage.upsert_df("stock_ohlcv", pd.DataFrame(rows), ["stock_code", "trade_date"])
    return dates


def _full_market_breadth_frame(dates: pd.DatetimeIndex, *, bad_day: int | None = None, expected_missing: bool = False) -> pd.DataFrame:
    n = len(dates)
    expected = np.full(n, 3000, dtype=float)
    effective = np.full(n, 3000, dtype=float)
    level = np.array(["full_market"] * n, dtype=object)
    warning = np.array([""] * n, dtype=object)
    if bad_day is not None:
        effective[bad_day] = 900
        level[bad_day] = "insufficient"
        warning[bad_day] = "全 A 宽度覆盖不足。"
    if expected_missing:
        expected[:] = np.nan
        full_ratio = np.full(n, np.nan)
        level[:] = "unavailable"
    else:
        full_ratio = effective / expected
    return pd.DataFrame(
        {
            "trade_date": dates.date,
            "up_count": 2000,
            "down_count": 1000,
            "unchanged_count": 0,
            "limit_up_count": 50,
            "limit_down_count": 20,
            "above_ma20_count": 1800,
            "below_ma20_count": 1200,
            "total_count": 3000,
            "effective_count": effective,
            "ma20_valid_count": 3000,
            "expected_count": expected,
            "coverage_ratio": full_ratio,
            "coverage_mode": "full_market",
            "local_sample_internal_coverage": np.nan,
            "full_market_coverage_ratio": full_ratio,
            "breadth_mode": "full_market",
            "up_ratio": np.linspace(0.45, 0.65, n),
            "above_ma20_ratio": np.linspace(0.40, 0.70, n),
            "amount_total": np.linspace(1e10, 1.5e10, n),
            "amount_z_20d": np.sin(np.arange(n) / 10),
            "coverage_level": level,
            "coverage_warning": warning,
            "source": "test",
            "fetched_at": pd.Timestamp("2026-06-03"),
        }
    )


def _upsert_breadth(storage: DuckDBStorage, breadth: pd.DataFrame) -> None:
    _ensure_market_breadth_coverage_columns(storage)
    storage.upsert_df("market_breadth_daily", breadth, ["trade_date", "breadth_mode"])


def test_local_sample_does_not_report_fake_full_market_coverage(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    _seed_local_stock_sample(storage)

    update_market_breadth("20240101", "20240130", incremental=False, mode="local_sample", storage=storage)
    latest = storage.read_df("SELECT * FROM market_breadth_daily ORDER BY trade_date DESC LIMIT 1").iloc[0]

    assert latest["coverage_mode"] == "local_sample"
    assert pd.isna(latest["full_market_coverage_ratio"])
    assert pd.isna(latest["coverage_ratio"])
    assert np.isclose(float(latest["local_sample_internal_coverage"]), 1.0)
    assert "不代表全 A" in latest["coverage_warning"]


def test_missing_expected_count_makes_full_market_coverage_unavailable(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=70)
    _upsert_breadth(storage, _full_market_breadth_frame(dates, expected_missing=True))

    features = build_market_features(storage, "20240101", "20240315", breadth_mode="full_market")

    assert _coverage_level("full_market", effective_count=3000, expected_count=None, full_market_coverage_ratio=None) == "unavailable"
    assert "full_market_coverage_ratio" in features.columns
    assert features["full_market_coverage_ratio"].isna().all()
    assert features["up_ratio"].isna().all()


def test_ui_warning_says_local_sample_is_not_full_a_coverage():
    source = Path("src/ui/market_regime_page.py").read_text(encoding="utf-8")

    assert "local_sample" in source
    assert "不代表全 A 覆盖" in source
    assert "样本内部覆盖率不代表全 A 覆盖" in source


def test_market_hmm_does_not_treat_local_sample_as_full_market_pass():
    source = Path("src/models/market_hmm.py").read_text(encoding="utf-8")

    assert "normalize_breadth_coverage_columns" in source
    assert "breadth_readiness.can_use_breadth" in source
    assert "coverage_mode" in source
    assert "breadth_mode = 'full_market'" in source
    assert "缺少全 A 市场宽度数据" in source


def test_one_bad_coverage_day_does_not_disable_entire_breadth_range_without_strict_policy(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_market_indices(storage, days=100)
    _upsert_breadth(storage, _full_market_breadth_frame(dates, bad_day=80))

    features = build_market_features(storage, "20240101", "20240430", breadth_mode="full_market")
    bad_date = dates[80]
    bad_row = features[pd.to_datetime(features["trade_date"]).eq(bad_date)]
    source = Path("src/models/market_hmm.py").read_text(encoding="utf-8")

    assert features["up_ratio"].notna().sum() >= 20
    assert not bad_row.empty
    assert pd.isna(bad_row.iloc[0]["up_ratio"])
    assert "strict_breadth_coverage" in source
    assert "训练将仅在具备全市场覆盖的日期使用宽度特征" in source
