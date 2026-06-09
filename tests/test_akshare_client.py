from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pandas as pd
import src.data_sources.akshare_client as ak_client
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import AKShareClient, _akshare_network_env


def test_akshare_board_names_success(monkeypatch, tmp_path):
    fake_ak = SimpleNamespace(stock_board_industry_name_ths=lambda: pd.DataFrame({"name": ["测试板块"], "code": ["881001"]}))
    monkeypatch.setattr(ak_client, "_import_akshare", lambda: fake_ak)
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage, use_subprocess_for_ths=False)
    monkeypatch.setattr(client, "_sleep", lambda: None)
    res = client.board_names("industry")
    assert not res.stale
    assert res.data.loc[0, "sector_id"] == "industry:测试板块"


def test_akshare_failure_uses_stale_cache(monkeypatch, tmp_path):
    calls = {"n": 0}

    def unstable():
        calls["n"] += 1
        if calls["n"] == 1:
            return pd.DataFrame({"板块名称": ["缓存板块"]})
        raise RuntimeError("network down")

    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage)
    monkeypatch.setattr(client, "_sleep", lambda: None)
    first = client._fetch("demo", unstable, cache_today=False)
    assert first.data.loc[0, "板块名称"] == "缓存板块"
    second = client._fetch("demo", unstable, cache_today=False)
    assert second.stale
    assert second.from_cache
    assert second.data.loc[0, "板块名称"] == "缓存板块"


def test_cache_ttl_refresh(monkeypatch, tmp_path):
    calls = {"n": 0}

    def changing():
        calls["n"] += 1
        return pd.DataFrame({"value": [calls["n"]]})

    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage)
    monkeypatch.setattr(client, "_sleep", lambda: None)

    first = client._fetch("demo_ttl", changing, ttl_seconds=60)
    second = client._fetch("demo_ttl", changing, ttl_seconds=60)
    assert first.data.loc[0, "value"] == 1
    assert second.data.loc[0, "value"] == 1
    assert calls["n"] == 1

    cache_path = client._cache_path("demo_ttl")
    old_time = time.time() - 3600
    os.utime(cache_path, (old_time, old_time))
    third = client._fetch("demo_ttl", changing, ttl_seconds=1)
    assert third.data.loc[0, "value"] == 2
    assert calls["n"] == 2

    def failing():
        raise RuntimeError("network down")

    os.utime(cache_path, (old_time, old_time))
    stale = client._fetch("demo_ttl", failing, ttl_seconds=1)
    assert stale.stale
    health = storage.read_df("SELECT * FROM data_health WHERE interface = 'demo_ttl'")
    assert health.loc[0, "last_error"] == "network down"
    assert pd.notna(health.loc[0, "last_network_failure"])
    assert pd.notna(health.loc[0, "last_cache_hit"])
    assert int(health.loc[0, "stale_reads"]) == 1


def test_historical_stock_request_uses_permanent_cache(monkeypatch, tmp_path):
    calls = {"n": 0}

    def fake_stock_hist_tx(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        calls["n"] += 1
        return pd.DataFrame(
            {
                "date": [pd.Timestamp(start_date).strftime("%Y-%m-%d")],
                "open": [10.0],
                "high": [11.0],
                "low": [9.0],
                "close": [10.5],
                "volume": [1000],
                "amount": [10000],
            }
        )

    fake_ak = SimpleNamespace(stock_zh_a_hist_tx=fake_stock_hist_tx)
    monkeypatch.setattr(ak_client, "_import_akshare", lambda: fake_ak)
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage)
    monkeypatch.setattr(client, "_sleep", lambda: None)

    first = client.stock_hist("000001", "20240101", "20240110")
    cache_path = client._cache_path("stock_zh_a_hist_tx", symbol="000001", start_date="20240101", end_date="20240110")
    old_time = time.time() - 365 * 24 * 3600
    os.utime(cache_path, (old_time, old_time))
    second = client.stock_hist("000001", "20240101", "20240110")

    assert calls["n"] == 1
    assert not first.from_cache
    assert second.from_cache


def test_920_stock_routes_to_beijing_exchange_and_daily_provider(monkeypatch, tmp_path):
    calls: dict[str, object] = {}

    def fake_stock_daily(symbol: str, start_date: str, end_date: str, adjust: str) -> pd.DataFrame:
        calls["symbol"] = symbol
        calls["start_date"] = start_date
        calls["end_date"] = end_date
        calls["adjust"] = adjust
        return pd.DataFrame(
            {
                "date": [pd.Timestamp(start_date).strftime("%Y-%m-%d")],
                "open": [20.0],
                "high": [21.0],
                "low": [19.0],
                "close": [20.5],
                "volume": [1000],
                "amount": [10000],
            }
        )

    fake_ak = SimpleNamespace(stock_zh_a_daily=fake_stock_daily)
    monkeypatch.setattr(ak_client, "_import_akshare", lambda: fake_ak)
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    client = AKShareClient(cache_dir=tmp_path / "cache", storage=storage)
    monkeypatch.setattr(client, "_sleep", lambda: None)

    assert AKShareClient._exchange_for_stock_code("920022") == "BJ"
    assert AKShareClient._tx_symbol("920022") == "bj920022"

    result = client.stock_hist("920022", "20240101", "20240110")

    assert calls == {"symbol": "bj920022", "start_date": "20240101", "end_date": "20240110", "adjust": "qfq"}
    assert result.data.loc[0, "stock_code"] == "920022"
    assert result.data.loc[0, "close"] == 20.5


def test_akshare_network_env_temporarily_bypasses_proxy(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:1082")
    monkeypatch.setenv("ALL_PROXY", "http://127.0.0.1:1082")
    with _akshare_network_env():
        assert "HTTPS_PROXY" not in ak_client.os.environ
        assert "ALL_PROXY" not in ak_client.os.environ
        assert "10jqka.com.cn" in ak_client.os.environ["NO_PROXY"]
    assert ak_client.os.environ["HTTPS_PROXY"] == "http://127.0.0.1:1082"
    assert ak_client.os.environ["ALL_PROXY"] == "http://127.0.0.1:1082"
