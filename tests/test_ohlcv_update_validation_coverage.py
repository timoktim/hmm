from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline import updater
from src.data_pipeline.updater import update_boards, update_market_benchmark, update_stock_histories
from src.data_sources.akshare_client import DataResult
from src.features import custom_basket_features


def _ohlcv_row(identifier_column: str, identifier: str, trade_date: str = "2024-01-01") -> dict[str, object]:
    return {
        identifier_column: identifier,
        "trade_date": pd.Timestamp(trade_date).date(),
        "open": 10.0,
        "high": 11.0,
        "low": 9.0,
        "close": 10.5,
        "volume": 1000.0,
        "amount": 10000.0,
    }


class FakeStockClient:
    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        self.frame = frame

    def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
        frame = self.frame if self.frame is not None else pd.DataFrame([_ohlcv_row("stock_code", stock_code)])
        return DataResult(frame.copy())


class FakeBenchmarkClient:
    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        self.frame = frame

    def market_benchmark_hist(self, benchmark_id: str, start_date: str, end_date: str, force_refresh: bool = False) -> DataResult:
        frame = self.frame if self.frame is not None else pd.DataFrame([_ohlcv_row("benchmark_id", benchmark_id)])
        return DataResult(frame.copy())


class FakeBoardClient:
    def board_names(self, board_type: str) -> DataResult:
        return DataResult(
            pd.DataFrame(
                [
                    {
                        "sector_id": f"{board_type}:a",
                        "sector_type": board_type,
                        "sector_name": "a",
                        "source": "test",
                        "last_update": pd.Timestamp("2024-01-01"),
                    }
                ]
            )
        )

    def board_hist(self, board_type: str, sector_name: str, start_date: str, end_date: str) -> DataResult:
        return DataResult(pd.DataFrame([_ohlcv_row("sector_id", f"{board_type}:{sector_name}")]))


def test_update_stock_histories_validates_before_upsert(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "stock.duckdb")
    storage.init_schema()
    events: list[str] = []
    original_validate = updater.validate_ohlcv
    original_upsert = storage.upsert_df

    def spy_validate(*args, **kwargs):
        events.append(f"validate:{kwargs.get('entity_key')}")
        return original_validate(*args, **kwargs)

    def spy_upsert(*args, **kwargs):
        events.append(f"upsert:{args[0]}")
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(updater, "validate_ohlcv", spy_validate)
    monkeypatch.setattr(storage, "upsert_df", spy_upsert)

    summary = update_stock_histories(["000001"], "20240101", "20240102", client=FakeStockClient(), storage=storage)

    assert summary.sectors_updated == 1
    assert events[:2] == ["validate:stock_code", "upsert:stock_ohlcv"]


def test_update_market_benchmark_validates_before_upsert(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "benchmark.duckdb")
    storage.init_schema()
    events: list[str] = []
    original_validate = updater.validate_ohlcv
    original_upsert = storage.upsert_df

    def spy_validate(*args, **kwargs):
        events.append(f"validate:{kwargs.get('entity_key')}")
        return original_validate(*args, **kwargs)

    def spy_upsert(*args, **kwargs):
        events.append(f"upsert:{args[0]}")
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(updater, "validate_ohlcv", spy_validate)
    monkeypatch.setattr(storage, "upsert_df", spy_upsert)

    summary = update_market_benchmark("hs300", "20240101", "20240102", client=FakeBenchmarkClient(), storage=storage)

    assert summary.failure is None
    assert events[:2] == ["validate:benchmark_id", "upsert:market_benchmark_ohlcv"]


def test_board_hist_still_validates(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "board.duckdb")
    storage.init_schema()
    calls: list[str | None] = []
    original_validate = updater.validate_ohlcv

    def spy_validate(*args, **kwargs):
        calls.append(kwargs.get("entity_key"))
        return original_validate(*args, **kwargs)

    monkeypatch.setattr(updater, "validate_ohlcv", spy_validate)

    summary = update_boards(
        "industry",
        "20240101",
        "20240102",
        include_constituents=False,
        client=FakeBoardClient(),  # type: ignore[arg-type]
        storage=storage,
    )

    assert summary.sectors_updated == 1
    assert calls == ["sector_id"]


def test_custom_basket_source_and_output_validation_are_called(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "basket.duckdb")
    storage.init_schema()
    basket_id = storage.create_custom_stock_basket("quality")
    storage.add_basket_members(basket_id, [{"stock_code": "000001", "stock_name": "A"}])
    stock = pd.DataFrame(
        [
            {
                "stock_code": "000001",
                "trade_date": pd.Timestamp("2024-01-01").date(),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.0,
                "volume": 1000.0,
                "amount": 10000.0,
            },
            {
                "stock_code": "000001",
                "trade_date": pd.Timestamp("2024-01-02").date(),
                "open": 10.0,
                "high": 11.0,
                "low": 9.0,
                "close": 10.5,
                "volume": 1100.0,
                "amount": 11000.0,
            },
        ]
    )
    storage.upsert_df("stock_ohlcv", stock, ["stock_code", "trade_date"])
    calls: list[tuple[str, str | None, set[str] | None]] = []
    original_validate = custom_basket_features.validate_ohlcv

    def spy_validate(df, name, **kwargs):
        calls.append((name, kwargs.get("entity_key"), kwargs.get("required_columns")))
        return original_validate(df, name, **kwargs)

    monkeypatch.setattr(custom_basket_features, "validate_ohlcv", spy_validate)

    out = custom_basket_features.build_custom_basket_ohlcv(basket_id, "20240101", "20240102", storage=storage)

    assert not out.empty
    assert calls[0][1:] == ("stock_code", {"stock_code", "trade_date", "close"})
    assert calls[1][1:] == ("basket_id", {"basket_id", "trade_date", "close"})


def test_validation_failure_prevents_upsert(tmp_path, monkeypatch) -> None:
    storage = DuckDBStorage(tmp_path / "bad.duckdb")
    storage.init_schema()
    bad = pd.DataFrame([_ohlcv_row("stock_code", "000001")])
    bad.loc[0, "close"] = 0.0
    upserts: list[str] = []

    def spy_upsert(*args, **kwargs):
        upserts.append(args[0])

    monkeypatch.setattr(storage, "upsert_df", spy_upsert)

    summary = update_stock_histories(["000001"], "20240101", "20240102", client=FakeStockClient(bad), storage=storage)

    assert summary.sectors_updated == 0
    assert upserts == []
    assert summary.failures
    assert "000001" in summary.failures[0]
