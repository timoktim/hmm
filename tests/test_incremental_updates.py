from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import incremental_update_boards, update_stock_histories
from src.data_sources.base import DataResult


def _sector_row(sector_id: str, trade_date: str) -> dict[str, object]:
    return {
        "sector_id": sector_id,
        "trade_date": pd.Timestamp(trade_date).date(),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 1000.0,
        "amount": 10000.0,
        "pct_chg": 1.0,
        "turnover": 1.0,
        "source": "test",
        "fetched_at": pd.Timestamp("2024-03-01"),
    }


def _stock_row(stock_code: str, trade_date: str) -> dict[str, object]:
    row = _sector_row("industry:test", trade_date)
    row.pop("sector_id")
    row["stock_code"] = stock_code
    return row


class FakeBoardClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def board_names(self, board_type: str) -> DataResult:
        return DataResult(
            pd.DataFrame(
                [
                    {"sector_id": "industry:a", "sector_type": board_type, "sector_name": "a", "source": "test", "last_update": pd.Timestamp("2024-03-01")},
                    {"sector_id": "industry:b", "sector_type": board_type, "sector_name": "b", "source": "test", "last_update": pd.Timestamp("2024-03-01")},
                ]
            )
        )

    def board_hist(self, board_type: str, sector_name: str, start_date: str, end_date: str) -> DataResult:
        self.calls.append((sector_name, start_date, end_date))
        return DataResult(pd.DataFrame([_sector_row(f"{board_type}:{sector_name}", start_date)]))


class FakeStockClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
        self.calls.append((stock_code, start_date, end_date))
        return DataResult(pd.DataFrame([_stock_row(stock_code, start_date)]))


class TushareClient(FakeBoardClient):
    def board_constituents(self, board_type: str, sector_name: str) -> DataResult:
        if sector_name == "b":
            raise ValueError("index_member_all 返回空数据")
        return DataResult(
            pd.DataFrame(
                [
                    {
                        "sector_id": f"{board_type}:{sector_name}",
                        "stock_code": "000001",
                        "stock_name": "A",
                        "in_sector_date": pd.Timestamp("2024-01-01").date(),
                        "source": "test",
                        "fetched_at": pd.Timestamp("2024-03-01"),
                    }
                ]
            )
        )


def test_incremental_update_boards_uses_local_max_trade_date(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df("sector_ohlcv", pd.DataFrame([_sector_row("industry:a", "2024-02-20")]), ["sector_id", "trade_date"])
    client = FakeBoardClient()

    summary = incremental_update_boards(
        "industry",
        "20200101",
        "20240301",
        lookback_days=10,
        include_constituents=False,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )

    assert summary.sectors_updated == 2
    assert ("a", "20240210", "20240301") in client.calls
    assert ("b", "20200101", "20240301") in client.calls


def test_incremental_update_boards_reports_unmatched_sector_names(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    client = FakeBoardClient()

    summary = incremental_update_boards(
        "industry",
        "20200101",
        "20240301",
        include_constituents=False,
        sector_names=["a", "missing"],
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )
    failures = storage.read_df("SELECT * FROM fetch_failures WHERE target_name = 'missing'")

    assert summary.sectors_seen == 2
    assert summary.sectors_updated == 1
    assert summary.failures
    assert "missing" in summary.failures[0]
    assert not failures.empty
    assert failures.loc[0, "interface"] == "board_names_match"


def test_update_boards_marks_legacy_sector_meta_inactive(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame(
            [
                {
                    "sector_id": "industry:legacy",
                    "sector_type": "industry",
                    "sector_name": "legacy",
                    "source": "test",
                    "last_update": pd.Timestamp("2024-01-01"),
                    "is_active": True,
                }
            ]
        ),
        ["sector_id"],
    )
    client = FakeBoardClient()

    incremental_update_boards(
        "industry",
        "20200101",
        "20240301",
        include_constituents=False,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )
    meta = storage.read_df("SELECT sector_name, is_active FROM sector_meta ORDER BY sector_name")

    legacy = meta[meta["sector_name"] == "legacy"].iloc[0]
    active = meta[meta["sector_name"] == "a"].iloc[0]
    assert bool(active["is_active"])
    assert not bool(legacy["is_active"])


def test_tushare_local_aggregate_skips_hist_when_constituents_missing(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    client = TushareClient()

    summary = incremental_update_boards(
        "industry",
        "20200101",
        "20240301",
        include_constituents=True,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )
    failures = storage.read_df("SELECT target_name, interface FROM fetch_failures ORDER BY target_name, interface")

    assert summary.sectors_updated == 1
    assert summary.failures == ["b 成分股更新失败: index_member_all 返回空数据"]
    assert ("a", "20200101", "20240301") in client.calls
    assert not any(call[0] == "b" for call in client.calls)
    assert failures.to_dict("records") == [{"target_name": "b", "interface": "board_constituents"}]


def test_storage_read_df_serializes_concurrent_duckdb_file_reads(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "sector_constituents",
        pd.DataFrame(
            [
                {
                    "sector_id": "industry:a",
                    "stock_code": "000001",
                    "stock_name": "A",
                    "in_sector_date": pd.Timestamp("2024-01-01").date(),
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-03-01"),
                }
            ]
        ),
        ["sector_id", "stock_code"],
    )
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame([_stock_row("000001", "2024-03-01")]),
        ["stock_code", "trade_date"],
    )
    query = """
        SELECT stock_code, trade_date, open, high, low, close, volume, amount
        FROM stock_ohlcv
        WHERE stock_code IN (
          SELECT stock_code FROM sector_constituents WHERE sector_id = ?
        )
    """

    with ThreadPoolExecutor(max_workers=3) as executor:
        counts = list(executor.map(lambda _: len(storage.read_df(query, ["industry:a"])), range(9)))

    assert counts == [1] * 9


def test_update_stock_histories_incremental_and_missing_only(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df("stock_ohlcv", pd.DataFrame([_stock_row("000001", "2024-02-20")]), ["stock_code", "trade_date"])
    client = FakeStockClient()

    summary = update_stock_histories(
        ["000001", "000002"],
        "20230101",
        "20240301",
        incremental=True,
        lookback_days=10,
        missing_only=False,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )

    assert summary.sectors_updated == 2
    assert ("000001", "20240210", "20240301") in client.calls
    assert ("000002", "20230101", "20240301") in client.calls

    missing_client = FakeStockClient()
    update_stock_histories(
        ["000001", "000003"],
        "20230101",
        "20240301",
        incremental=True,
        missing_only=True,
        client=missing_client,  # type: ignore[arg-type]
        storage=storage,
    )

    assert missing_client.calls == [("000003", "20230101", "20240301")]
