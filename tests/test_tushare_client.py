from __future__ import annotations

import inspect

import pandas as pd
import pytest

import src.data_sources.tushare_client as tushare_module
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.tushare_client import TushareClient


def test_tushare_token_is_read_from_env_only(tmp_path, monkeypatch) -> None:
    seen: dict[str, str] = {}

    class FakeTs:
        @staticmethod
        def pro_api(token: str):
            seen["token"] = token
            return object()

    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", "<placeholder>")
    monkeypatch.setattr(tushare_module, "_import_tushare", lambda: FakeTs)
    storage = DuckDBStorage(tmp_path / "token.duckdb")

    client = TushareClient(cache_dir=tmp_path / "cache", storage=storage)
    client._api()

    assert "token" not in inspect.signature(TushareClient).parameters
    assert seen["token"] == "<placeholder>"


def test_ci_does_not_require_live_tushare_token(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ASHARE_HMM_TUSHARE_TOKEN", raising=False)
    storage = DuckDBStorage(tmp_path / "no_token_construct.duckdb")

    client = TushareClient(cache_dir=tmp_path / "cache", storage=storage)

    assert isinstance(client, TushareClient)


def test_tushare_client_does_not_log_token(tmp_path, monkeypatch) -> None:
    secret = "<redacted-secret>"

    class FakePro:
        def daily(self, **kwargs):
            raise RuntimeError(f"upstream echoed {secret}")

    class FakeTs:
        @staticmethod
        def pro_api(token: str):
            return FakePro()

    messages: list[str] = []
    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", secret)
    monkeypatch.setattr(tushare_module, "_import_tushare", lambda: FakeTs)
    monkeypatch.setattr(tushare_module.logger, "warning", lambda *args, **kwargs: messages.append(" ".join(str(arg) for arg in args)))
    storage = DuckDBStorage(tmp_path / "no_leak.duckdb")
    client = TushareClient(cache_dir=tmp_path / "cache", storage=storage)

    with pytest.raises(RuntimeError) as excinfo:
        client._daily_raw_by_trade_date("20240110")

    health = storage.read_df("SELECT last_error FROM data_health WHERE interface = 'tushare_daily_by_trade_date'")
    health_error = "" if health.empty else str(health.loc[0, "last_error"])
    assert secret not in str(excinfo.value)
    assert secret not in "\n".join(messages)
    assert secret not in health_error


def test_tushare_qfq_adjustment_preserves_current_stock_ohlcv_semantics() -> None:
    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20240109", "20240110"],
            "open": [10.0, 12.0],
            "high": [11.0, 13.0],
            "low": [9.0, 11.0],
            "close": [10.0, 12.0],
            "vol": [100.0, 110.0],
            "amount": [1000.0, 1320.0],
            "pct_chg": [0.0, 20.0],
        }
    )
    adj = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20240109", "20240110"],
            "adj_factor": [1.0, 2.0],
        }
    )

    out = TushareClient._normalize_qfq_stock_daily(daily, adj)

    first = out[out["trade_date"] == pd.Timestamp("2024-01-09").date()].iloc[0]
    second = out[out["trade_date"] == pd.Timestamp("2024-01-10").date()].iloc[0]
    assert first["source"] == "tushare_qfq"
    assert first["close"] == 5.0
    assert second["close"] == 12.0
    assert first["validation_status"] == "validated"


def _seed_local_sector_aggregate_inputs(storage: DuckDBStorage, sector_id: str = "industry:TestIndustry") -> None:
    storage.upsert_df(
        "sector_constituents",
        pd.DataFrame(
            [
                {
                    "sector_id": sector_id,
                    "stock_code": "000001",
                    "stock_name": "Test Stock",
                    "in_sector_date": pd.Timestamp("2024-01-01").date(),
                }
            ]
        ),
        ["sector_id", "stock_code"],
    )
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {
                    "stock_code": "000001",
                    "trade_date": pd.Timestamp("2024-01-09").date(),
                    "open": 10.0,
                    "high": 10.0,
                    "low": 10.0,
                    "close": 10.0,
                    "volume": 100.0,
                    "amount": 1000.0,
                },
                {
                    "stock_code": "000001",
                    "trade_date": pd.Timestamp("2024-01-10").date(),
                    "open": 11.0,
                    "high": 12.0,
                    "low": 10.5,
                    "close": 11.5,
                    "volume": 120.0,
                    "amount": 1320.0,
                },
            ]
        ),
        ["stock_code", "trade_date"],
    )


def test_local_sector_basket_hist_continues_from_previous_sector_close(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "sector_anchor.duckdb")
    storage.init_schema()
    sector_id = "industry:TestIndustry"
    _seed_local_sector_aggregate_inputs(storage, sector_id)
    storage.upsert_df(
        "sector_ohlcv",
        pd.DataFrame(
            [
                {
                    "sector_id": sector_id,
                    "trade_date": pd.Timestamp("2024-01-09").date(),
                    "open": 1200.0,
                    "high": 1250.0,
                    "low": 1190.0,
                    "close": 1234.0,
                    "volume": 100.0,
                    "amount": 1000.0,
                }
            ]
        ),
        ["sector_id", "trade_date"],
    )
    client = TushareClient(cache_dir=tmp_path / "cache", storage=storage)

    result = client._local_sector_basket_hist("industry", "TestIndustry", "20240110", "20240110")

    row = result.data.iloc[0]
    assert row["trade_date"] == pd.Timestamp("2024-01-10").date()
    assert row["open"] == pytest.approx(1234.0 * 1.10)
    assert row["high"] == pytest.approx(1234.0 * 1.20)
    assert row["low"] == pytest.approx(1234.0 * 1.05)
    assert row["close"] == pytest.approx(1234.0 * 1.15)
    assert row["open"] != pytest.approx(1000.0 * 1.10)
    assert row["close"] != pytest.approx(1000.0 * 1.15)


def test_local_sector_basket_hist_uses_1000_without_previous_sector_close(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "sector_initial_anchor.duckdb")
    storage.init_schema()
    _seed_local_sector_aggregate_inputs(storage)
    client = TushareClient(cache_dir=tmp_path / "cache", storage=storage)

    result = client._local_sector_basket_hist("industry", "TestIndustry", "20240110", "20240110")

    row = result.data.iloc[0]
    assert row["open"] == pytest.approx(1000.0 * 1.10)
    assert row["high"] == pytest.approx(1000.0 * 1.20)
    assert row["low"] == pytest.approx(1000.0 * 1.05)
    assert row["close"] == pytest.approx(1000.0 * 1.15)
