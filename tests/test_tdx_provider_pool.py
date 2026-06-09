from __future__ import annotations

import pandas as pd
import pytest

from src.data_pipeline import market_updater
from src.data_pipeline.market_updater import update_all_a_stock_ohlcv
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources import factory as factory_module
from src.data_sources.akshare_client import AKShareClient
from src.data_sources.base import DataResult
from src.data_sources.factory import create_data_client
from src.data_sources.mootdx_client import MootdxClient
from src.data_sources.tdx_pool import TdxServerPool, parse_tdx_servers
from src.data_sources.tushare_client import TushareClient


def _raw_ohlcv(date_text: str = "2024-01-02") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "date": date_text,
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "vol": 1000.0,
                "amount": 10000.0,
            }
        ]
    )


def test_parse_tdx_servers_accepts_host_port_strings() -> None:
    assert parse_tdx_servers("1.1.1.1:7709,2.2.2.2") == (("1.1.1.1", 7709), ("2.2.2.2", 7709))


def test_tdx_server_pool_round_robin_and_cooldown() -> None:
    now = 0.0

    def clock() -> float:
        return now

    pool = TdxServerPool([("s1", 7709), ("s2", 7709)], cooldown_seconds=10, failure_threshold=1, clock=clock, sleeper=lambda _: None)

    with pool.lease() as first:
        assert first.server == ("s1", 7709)
    with pool.lease() as second:
        assert second.server == ("s2", 7709)

    try:
        with pool.lease() as failed:
            assert failed.server == ("s1", 7709)
            raise RuntimeError("boom")
    except RuntimeError:
        pass

    with pool.lease() as after_cooldown_skip:
        assert after_cooldown_skip.server == ("s2", 7709)

    snapshots = pool.snapshots()
    s1 = [snapshot for snapshot in snapshots if snapshot.server == "s1"][0]
    assert s1.failures == 1
    assert s1.cooldown_until == 10.0


def test_mootdx_stock_hist_uses_pool_and_normalizes(tmp_path, monkeypatch) -> None:
    from src.data_sources import mootdx_client as mootdx_module

    monkeypatch.setattr(mootdx_module.time, "sleep", lambda _: None)
    used_servers: list[tuple[str, int]] = []

    class FakeQuotes:
        def k(self, **kwargs):
            assert kwargs["symbol"] == "000001"
            return _raw_ohlcv()

    def factory(server: tuple[str, int]) -> FakeQuotes:
        used_servers.append(server)
        return FakeQuotes()

    storage = DuckDBStorage(tmp_path / "tdx.duckdb")
    storage.init_schema()
    client = MootdxClient(
        cache_dir=tmp_path / "cache",
        storage=storage,
        server_pool=TdxServerPool([("s1", 7709), ("s2", 7709)], per_server_workers=1),
        quotes_factory=factory,
        fallback_to_akshare=False,
    )

    result = client.stock_hist("000001", "20240101", "20240103")

    assert used_servers == [("s1", 7709)]
    assert result.data.loc[0, "stock_code"] == "000001"
    assert result.data.loc[0, "source"] == "mootdx"
    assert result.data.loc[0, "volume"] == 1000.0


def test_mootdx_stock_hist_falls_back_to_akshare(tmp_path, monkeypatch) -> None:
    from src.data_sources import mootdx_client as mootdx_module

    monkeypatch.setattr(mootdx_module.time, "sleep", lambda _: None)

    class FailingQuotes:
        def k(self, **kwargs):
            raise RuntimeError("tdx down")

    class Fallback:
        def stock_hist(self, stock_code: str, start_date: str, end_date: str, **kwargs) -> DataResult:
            data = pd.DataFrame(
                [
                    {
                        "stock_code": stock_code,
                        "trade_date": pd.Timestamp("2024-01-02").date(),
                        "close": 10.0,
                        "source": "akshare",
                    }
                ]
            )
            return DataResult(data)

    storage = DuckDBStorage(tmp_path / "fallback.duckdb")
    storage.init_schema()
    client = MootdxClient(
        cache_dir=tmp_path / "cache",
        storage=storage,
        server_pool=TdxServerPool([("s1", 7709)], per_server_workers=1, cooldown_seconds=0),
        fallback_client=Fallback(),  # type: ignore[arg-type]
        quotes_factory=lambda server: FailingQuotes(),
        fallback_to_akshare=True,
    )

    result = client.stock_hist("000001", "20240101", "20240103")

    assert result.data.loc[0, "source"] == "akshare_fallback"
    assert "tdx down" in str(result.error)


def test_mootdx_market_benchmark_prefers_index_method(tmp_path, monkeypatch) -> None:
    from src.data_sources import mootdx_client as mootdx_module

    monkeypatch.setattr(mootdx_module.time, "sleep", lambda _: None)
    calls: list[str] = []

    class FakeQuotes:
        def index(self, **kwargs):
            calls.append(f"index:{kwargs['symbol']}")
            return _raw_ohlcv()

        def k(self, **kwargs):
            calls.append(f"k:{kwargs['symbol']}")
            return _raw_ohlcv()

    storage = DuckDBStorage(tmp_path / "benchmark_index.duckdb")
    storage.init_schema()
    client = MootdxClient(
        cache_dir=tmp_path / "cache",
        storage=storage,
        server_pool=TdxServerPool([("s1", 7709)], per_server_workers=1),
        quotes_factory=lambda server: FakeQuotes(),
        fallback_to_akshare=False,
    )

    result = client.market_benchmark_hist("hs300", "20240101", "20240103")

    assert calls == ["index:000300"]
    assert result.data.loc[0, "benchmark_id"] == "hs300"
    assert result.data.loc[0, "source"] == "mootdx"


def test_mootdx_market_index_prefers_index_method(tmp_path, monkeypatch) -> None:
    from src.data_sources import mootdx_client as mootdx_module

    monkeypatch.setattr(mootdx_module.time, "sleep", lambda _: None)
    calls: list[str] = []

    class FakeQuotes:
        def index(self, **kwargs):
            calls.append(f"index:{kwargs['symbol']}")
            return _raw_ohlcv()

        def k(self, **kwargs):
            calls.append(f"k:{kwargs['symbol']}")
            return _raw_ohlcv()

    storage = DuckDBStorage(tmp_path / "market_index.duckdb")
    storage.init_schema()
    client = MootdxClient(
        cache_dir=tmp_path / "cache",
        storage=storage,
        server_pool=TdxServerPool([("s1", 7709)], per_server_workers=1),
        quotes_factory=lambda server: FakeQuotes(),
        fallback_to_akshare=False,
    )

    result = client.market_index_hist("000001", "上证指数", "20240101", "20240103")

    assert calls == ["index:000001"]
    assert result.data.loc[0, "index_code"] == "000001"
    assert result.data.loc[0, "source"] == "mootdx"


def test_create_data_client_defaults_to_tushare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(factory_module.settings, "market_data_source", "tushare")
    monkeypatch.setattr(factory_module.settings, "default_source", "tushare")
    storage = DuckDBStorage(tmp_path / "default_tushare.duckdb")

    client = create_data_client(storage=storage, cache_dir=tmp_path / "cache")

    assert isinstance(client, TushareClient)


def test_legacy_board_sources_not_called_in_default_pipeline(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(factory_module.settings, "market_data_source", "tushare")
    monkeypatch.setattr(factory_module.settings, "default_source", "tushare")

    def fail_legacy_init(*args, **kwargs):
        raise AssertionError("default pipeline must not construct AKShareClient")

    monkeypatch.setattr(factory_module.AKShareClient, "__init__", fail_legacy_init)
    storage = DuckDBStorage(tmp_path / "default_no_akshare.duckdb")

    client = create_data_client(storage=storage, cache_dir=tmp_path / "cache")

    assert isinstance(client, TushareClient)


def test_create_data_client_explicit_legacy_akshare(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "legacy_akshare.duckdb")

    client = create_data_client(source="legacy-akshare", storage=storage, cache_dir=tmp_path / "cache")

    assert isinstance(client, AKShareClient)


def test_create_data_client_explicit_mootdx(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "explicit_mootdx.duckdb")

    client = create_data_client(source="mootdx", storage=storage, cache_dir=tmp_path / "cache")

    assert isinstance(client, MootdxClient)


def test_mootdx_no_longer_falls_back_to_akshare_by_default(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "mootdx_no_fallback.duckdb")

    client = create_data_client(source="mootdx", storage=storage, cache_dir=tmp_path / "cache")

    assert isinstance(client, MootdxClient)
    assert client.fallback_to_akshare is False
    assert client.fallback_client is None


def test_create_data_client_invalid_source_raises(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "invalid_source.duckdb")

    with pytest.raises(ValueError, match="未知数据源"):
        create_data_client(source="bogus", storage=storage, cache_dir=tmp_path / "cache")


def test_all_a_stock_ohlcv_batches_and_sleeps(tmp_path, monkeypatch) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(market_updater.time, "sleep", sleeps.append)
    storage = DuckDBStorage(tmp_path / "batch.duckdb")
    storage.init_schema()
    codes = ["000001", "000002", "000003", "000004", "000005"]
    storage.upsert_df(
        "all_a_stock_universe",
        pd.DataFrame(
            {
                "stock_code": codes,
                "stock_name": codes,
                "exchange": "SZ",
                "list_status": "active",
                "is_st": False,
                "source": "test",
                "fetched_at": pd.Timestamp("2024-01-10"),
            }
        ),
        ["stock_code"],
    )

    class FakeClient:
        def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
            data = pd.DataFrame(
                [
                    {
                        "stock_code": stock_code,
                        "trade_date": pd.Timestamp("2024-01-10").date(),
                        "open": 10.0,
                        "high": 12.0,
                        "low": 9.0,
                        "close": 11.0,
                        "volume": 1000.0,
                        "amount": 11000.0,
                    }
                ]
            )
            return DataResult(data)

    progress: list[dict[str, object]] = []
    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        workers=1,
        batch_size=2,
        batch_sleep_seconds=0.25,
        probe_latest=False,
        client=FakeClient(),  # type: ignore[arg-type]
        storage=storage,
        progress_callback=progress.append,
    )

    assert summary.updated == 5
    assert sleeps == [0.25, 0.25]
    assert {event["batch_count"] for event in progress} == {3}


def _seed_all_a_universe(storage: DuckDBStorage, codes: list[str]) -> None:
    storage.upsert_df(
        "all_a_stock_universe",
        pd.DataFrame(
            {
                "stock_code": codes,
                "stock_name": codes,
                "exchange": "SZ",
                "list_status": "active",
                "is_st": False,
                "source": "test",
                "fetched_at": pd.Timestamp("2024-01-10"),
            }
        ),
        ["stock_code"],
    )


class FakeAllAStockClient:
    def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
        return DataResult(
            pd.DataFrame(
                [
                    {
                        "stock_code": stock_code,
                        "trade_date": pd.Timestamp("2024-01-10").date(),
                        "open": 10.0,
                        "high": 12.0,
                        "low": 9.0,
                        "close": 11.0,
                        "volume": 1000.0,
                        "amount": 11000.0,
                    }
                ]
            )
        )


class FakeTushareBulkClient:
    def __init__(self) -> None:
        self.bulk_dates: list[str] = []
        self.stock_hist_calls = 0

    def trade_dates(self, start_date: str, end_date: str, force_refresh: bool = False) -> list[str]:
        return ["20240109", "20240110"]

    def stock_daily_by_trade_dates(self, trade_dates: list[str], **kwargs: object) -> DataResult:
        self.bulk_dates.extend(trade_dates)
        callback = kwargs.get("progress_callback")
        rows = []
        for idx, date in enumerate(trade_dates, start=1):
            if callback:
                callback({"api": "daily", "current": idx - 1, "total": len(trade_dates), "name": date})
            for code in ["000001", "000002"]:
                close = 10.0 + idx
                rows.append(
                    {
                        "stock_code": code,
                        "trade_date": pd.Timestamp(date).date(),
                        "open": close - 0.2,
                        "high": close + 0.5,
                        "low": close - 0.5,
                        "close": close,
                        "volume": 1000.0,
                        "amount": 10000.0,
                        "pct_chg": 1.0,
                        "turnover": 2.0,
                        "source": "tushare_qfq",
                        "fetched_at": pd.Timestamp("2024-01-11"),
                        "source_priority": 0,
                        "is_provisional": False,
                        "validation_status": "validated",
                        "vendor_update_time": pd.NaT,
                    }
                )
            if callback:
                callback({"api": "daily", "current": idx, "total": len(trade_dates), "name": date})
        return DataResult(pd.DataFrame(rows))

    def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
        self.stock_hist_calls += 1
        raise AssertionError("Tushare all-A update must not call stock_hist per code")


def test_all_a_tushare_update_uses_trade_date_bulk_path(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_updater.settings, "market_data_source", "tushare")
    storage = DuckDBStorage(tmp_path / "tushare_bulk.duckdb")
    storage.init_schema()
    _seed_all_a_universe(storage, ["000001", "000002"])
    client = FakeTushareBulkClient()
    progress: list[dict[str, object]] = []

    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        skip_completed=True,
        client=client,  # type: ignore[arg-type]
        storage=storage,
        progress_callback=progress.append,
    )

    stored = storage.read_df("SELECT * FROM stock_ohlcv ORDER BY trade_date, stock_code")
    assert summary.updated == 2
    assert summary.rows == 4
    assert client.bulk_dates == ["20240109", "20240110"]
    assert client.stock_hist_calls == 0
    assert set(stored["source"]) == {"tushare_qfq"}
    assert {event["name"] for event in progress if event.get("name")} >= {"20240109", "20240110"}


def test_all_a_tushare_update_does_not_call_stock_hist_per_code(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_updater.settings, "market_data_source", "tushare")
    storage = DuckDBStorage(tmp_path / "tushare_no_stock_hist.duckdb")
    storage.init_schema()
    _seed_all_a_universe(storage, ["000001", "000002"])
    client = FakeTushareBulkClient()

    update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )

    assert client.stock_hist_calls == 0


def test_all_a_stock_ohlcv_akshare_default_workers_do_not_use_tdx_global(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_updater.settings, "market_data_source", "akshare")
    monkeypatch.setattr(market_updater.settings, "tdx_global_workers", 8)
    monkeypatch.setattr(market_updater.settings, "tdx_max_workers", 16)
    storage = DuckDBStorage(tmp_path / "akshare_default_workers.duckdb")
    storage.init_schema()
    _seed_all_a_universe(storage, ["000001", "000002", "000003", "000004"])
    progress: list[dict[str, object]] = []

    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        workers=None,
        batch_size=10,
        batch_sleep_seconds=0,
        probe_latest=False,
        client=FakeAllAStockClient(),  # type: ignore[arg-type]
        storage=storage,
        progress_callback=progress.append,
    )

    assert summary.updated == 4
    assert {event["worker_count"] for event in progress} == {3}


def test_all_a_stock_ohlcv_tdx_default_workers_keep_tdx_global(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_updater.settings, "market_data_source", "mootdx")
    monkeypatch.setattr(market_updater.settings, "tdx_global_workers", 8)
    monkeypatch.setattr(market_updater.settings, "tdx_max_workers", 16)
    storage = DuckDBStorage(tmp_path / "tdx_default_workers.duckdb")
    storage.init_schema()
    _seed_all_a_universe(storage, ["000001", "000002", "000003", "000004"])
    progress: list[dict[str, object]] = []

    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        workers=None,
        batch_size=10,
        batch_sleep_seconds=0,
        probe_latest=False,
        client=FakeAllAStockClient(),  # type: ignore[arg-type]
        storage=storage,
        progress_callback=progress.append,
    )

    assert summary.updated == 4
    assert {event["worker_count"] for event in progress} == {8}


def test_all_a_stock_ohlcv_explicit_workers_are_not_replaced_by_source_default(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(market_updater.settings, "market_data_source", "akshare")
    monkeypatch.setattr(market_updater.settings, "tdx_global_workers", 8)
    storage = DuckDBStorage(tmp_path / "explicit_workers.duckdb")
    storage.init_schema()
    _seed_all_a_universe(storage, ["000001", "000002", "000003", "000004"])
    progress: list[dict[str, object]] = []

    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=False,
        workers=4,
        batch_size=10,
        batch_sleep_seconds=0,
        probe_latest=False,
        client=FakeAllAStockClient(),  # type: ignore[arg-type]
        storage=storage,
        progress_callback=progress.append,
    )

    assert summary.updated == 4
    assert {event["worker_count"] for event in progress} == {4}
