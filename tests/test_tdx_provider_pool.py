from __future__ import annotations

import pandas as pd

from src.data_pipeline.market_updater import update_all_a_stock_ohlcv
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.data_sources.mootdx_client import MootdxClient
from src.data_sources.tdx_pool import TdxServerPool, parse_tdx_servers


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


def test_all_a_stock_ohlcv_batches_and_sleeps(tmp_path, monkeypatch) -> None:
    from src.data_pipeline import market_updater

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
                        "close": 11.0,
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
