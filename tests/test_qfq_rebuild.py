from __future__ import annotations

import os

import pandas as pd
import pytest

from src.data_pipeline.qfq_rebuild import (
    detect_changed_adj_factors,
    rebuild_dependent_aggregates,
    rebuild_qfq_stock_ohlcv,
    run_qfq_rebuild,
    update_adj_factor_snapshot,
)
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.data_sources.tushare_client import TushareClient


def _adj_row(stock_code: str, trade_date: str, adj_factor: float) -> dict[str, object]:
    code = str(stock_code).zfill(6)
    exchange = "SH" if code.startswith("6") else "SZ"
    return {
        "ts_code": f"{code}.{exchange}",
        "stock_code": code,
        "trade_date": trade_date,
        "adj_factor": adj_factor,
    }


def _stock_row(stock_code: str, trade_date: str, close: float) -> dict[str, object]:
    return {
        "stock_code": str(stock_code).zfill(6),
        "trade_date": pd.Timestamp(trade_date).date(),
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": 100.0,
        "amount": close * 100.0,
        "pct_chg": 0.0,
        "turnover": pd.NA,
        "source": "test",
        "fetched_at": pd.Timestamp("2024-01-03"),
        "source_priority": 0,
        "is_provisional": False,
        "validation_status": "validated",
        "vendor_update_time": pd.NaT,
    }


def _plan(stock_code: str = "000001", start: str = "20240101", end: str = "20240102") -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "stock_code": stock_code,
                "earliest_affected_date": pd.Timestamp(start).date(),
                "latest_checked_date": pd.Timestamp(end).date(),
                "old_factor": 1.0,
                "new_factor": 2.0,
                "factor_change_count": 1,
                "rebuild_start_date": pd.Timestamp(start).date(),
                "rebuild_end_date": pd.Timestamp(end).date(),
            }
        ]
    )


class FakeQfqClient:
    def __init__(self, adj_rows: list[dict[str, object]], qfq_frames: dict[str, pd.DataFrame] | None = None) -> None:
        self.adj = pd.DataFrame(adj_rows)
        self.qfq_frames = qfq_frames or {}

    def trade_dates(self, start_date: str, end_date: str, force_refresh: bool = False) -> list[str]:
        dates = pd.to_datetime(self.adj["trade_date"], errors="coerce").dt.strftime("%Y%m%d").dropna().drop_duplicates().sort_values()
        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)
        return [date for date in dates if start <= pd.Timestamp(date) <= end]

    def _adj_factor_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        mask = pd.to_datetime(self.adj["trade_date"], errors="coerce").dt.strftime("%Y%m%d") == str(trade_date)
        return DataResult(self.adj.loc[mask].copy())

    def stock_qfq_hist_with_reference(
        self,
        stock_code: str,
        start_date: str,
        end_date: str,
        reference_factor: float | None = None,
        force_refresh: bool = False,
    ) -> DataResult:
        code = str(stock_code).zfill(6)
        frame = self.qfq_frames.get(code, pd.DataFrame([_stock_row(code, "2024-01-01", 10.0), _stock_row(code, "2024-01-02", 11.0)]))
        data = frame.copy()
        data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.date
        start = pd.Timestamp(start_date).date()
        end = pd.Timestamp(end_date).date()
        data = data[(data["stock_code"].astype(str).str.zfill(6) == code) & (data["trade_date"] >= start) & (data["trade_date"] <= end)]
        return DataResult(data)


def test_detect_changed_adj_factors_marks_affected_stock(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "detect_changed.duckdb")
    storage.init_schema()
    update_adj_factor_snapshot(
        storage,
        pd.DataFrame([_adj_row("000001", "20240102", 1.0), _adj_row("000002", "20240102", 3.0)]),
    )

    affected = detect_changed_adj_factors(
        storage,
        pd.DataFrame([_adj_row("000001", "20240102", 2.0), _adj_row("000002", "20240102", 3.0)]),
    )

    assert affected["stock_code"].tolist() == ["000001"]
    assert affected.loc[0, "factor_change_count"] == 1
    assert affected.loc[0, "old_factor"] == pytest.approx(1.0)
    assert affected.loc[0, "new_factor"] == pytest.approx(2.0)


def test_detect_changed_adj_factors_noop_when_unchanged(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "detect_noop.duckdb")
    storage.init_schema()
    factors = pd.DataFrame([_adj_row("000001", "20240102", 1.0), _adj_row("000002", "20240102", 3.0)])
    update_adj_factor_snapshot(storage, factors)

    affected = detect_changed_adj_factors(storage, factors)

    assert affected.empty


def test_qfq_rebuild_uses_reference_factor_not_window_last_factor() -> None:
    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": ["20240101", "20240102", "20240103"],
            "open": [10.0, 20.0, 30.0],
            "high": [10.0, 20.0, 30.0],
            "low": [10.0, 20.0, 30.0],
            "close": [10.0, 20.0, 30.0],
            "vol": [100.0, 100.0, 100.0],
            "amount": [1000.0, 2000.0, 3000.0],
            "pct_chg": [0.0, 100.0, 50.0],
        }
    )
    adj = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": ["20240101", "20240102", "20240103"],
            "adj_factor": [1.0, 2.0, 3.0],
        }
    )

    out = TushareClient.normalize_qfq_stock_daily_with_reference(daily, adj, {"000001": 6.0})

    assert out["close"].tolist() == pytest.approx([10.0 / 6.0, 20.0 * 2.0 / 6.0, 30.0 * 3.0 / 6.0])
    assert out["close"].iloc[-1] != pytest.approx(30.0)
    assert out["source"].unique().tolist() == ["tushare_qfq_rebased"]


def test_rebuild_preserves_stock_ohlcv_primary_key(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "primary_key.duckdb")
    storage.init_schema()
    storage.upsert_df("stock_ohlcv", pd.DataFrame([_stock_row("000001", "2024-01-01", 9.0)]), ["stock_code", "trade_date"])
    client = FakeQfqClient([], {"000001": pd.DataFrame([_stock_row("000001", "2024-01-01", 10.0), _stock_row("000001", "2024-01-02", 11.0)])})

    summary = rebuild_qfq_stock_ohlcv(storage, client, _plan())
    duplicates = storage.read_df(
        """
        SELECT stock_code, trade_date, count(*) AS n
        FROM stock_ohlcv
        GROUP BY stock_code, trade_date
        HAVING count(*) > 1
        """
    )

    assert summary["rows"] == 2
    assert duplicates.empty
    assert int(storage.read_df("SELECT count(*) AS n FROM stock_ohlcv").loc[0, "n"]) == 2


def test_rebuild_does_not_touch_unaffected_stocks(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "unaffected.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame([_stock_row("000001", "2024-01-01", 9.0), _stock_row("000002", "2024-01-01", 99.0)]),
        ["stock_code", "trade_date"],
    )
    client = FakeQfqClient([], {"000001": pd.DataFrame([_stock_row("000001", "2024-01-01", 10.0)])})

    rebuild_qfq_stock_ohlcv(storage, client, _plan(end="20240101"))

    other = storage.read_df("SELECT close, source FROM stock_ohlcv WHERE stock_code = '000002'").iloc[0]
    assert other["close"] == pytest.approx(99.0)
    assert other["source"] == "test"


def test_dry_run_does_not_write_stock_ohlcv(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "dry_run.duckdb")
    storage.init_schema()
    update_adj_factor_snapshot(storage, pd.DataFrame([_adj_row("000001", "20240102", 1.0)]))
    client = FakeQfqClient(
        [_adj_row("000001", "20240102", 2.0)],
        {"000001": pd.DataFrame([_stock_row("000001", "2024-01-02", 10.0)])},
    )

    summary = run_qfq_rebuild(start="20240102", end="20240102", dry_run=True, storage=storage, client=client)

    assert summary["status"] == "DRY_RUN"
    assert int(storage.read_df("SELECT count(*) AS n FROM stock_ohlcv").loc[0, "n"]) == 0
    assert int(storage.read_df("SELECT count(*) AS n FROM market_breadth_daily").loc[0, "n"]) == 0
    assert int(storage.read_df("SELECT count(*) AS n FROM qfq_rebuild_runs").loc[0, "n"]) == 0


def test_qfq_rebuild_run_is_audited(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "audited.duckdb")
    storage.init_schema()
    storage.upsert_df("all_a_stock_universe", pd.DataFrame([{"stock_code": "000001", "stock_name": "A", "list_status": "active"}]), ["stock_code"])
    storage.upsert_df("stock_ohlcv", pd.DataFrame([_stock_row("000001", "2024-01-01", 9.0)]), ["stock_code", "trade_date"])
    update_adj_factor_snapshot(storage, pd.DataFrame([_adj_row("000001", "20240102", 1.0)]))
    client = FakeQfqClient(
        [_adj_row("000001", "20240102", 2.0)],
        {"000001": pd.DataFrame([_stock_row("000001", "2024-01-01", 10.0), _stock_row("000001", "2024-01-02", 11.0)])},
    )

    summary = run_qfq_rebuild(start="20240102", end="20240102", storage=storage, client=client)
    runs = storage.read_df("SELECT * FROM qfq_rebuild_runs")
    affected = storage.read_df("SELECT * FROM qfq_rebuild_affected_stocks")

    assert summary["status"] == "PASS"
    assert len(runs) == 1
    assert runs.loc[0, "status"] == "PASS"
    assert len(affected) == 1
    assert affected.loc[0, "stock_code"] == "000001"


def test_max_stocks_updates_snapshot_only_for_rebuilt_stocks(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "max_stocks_snapshot.duckdb")
    storage.init_schema()
    codes = ["000001", "000002", "000003"]
    storage.upsert_df(
        "all_a_stock_universe",
        pd.DataFrame([{"stock_code": code, "stock_name": code, "list_status": "active"} for code in codes]),
        ["stock_code"],
    )
    old_adj = pd.DataFrame([_adj_row(code, "20240102", 1.0) for code in codes])
    new_adj = pd.DataFrame([_adj_row(code, "20240102", 2.0) for code in codes])
    update_adj_factor_snapshot(storage, old_adj)
    client = FakeQfqClient(
        new_adj.to_dict(orient="records"),
        {"000001": pd.DataFrame([_stock_row("000001", "2024-01-01", 10.0), _stock_row("000001", "2024-01-02", 11.0)])},
    )

    summary = run_qfq_rebuild(start="20240102", end="20240102", max_stocks=1, storage=storage, client=client)
    snapshot = storage.read_df("SELECT stock_code, adj_factor FROM tushare_adj_factor_snapshot ORDER BY stock_code")
    factors = dict(zip(snapshot["stock_code"], snapshot["adj_factor"], strict=False))
    detected_again = detect_changed_adj_factors(storage, new_adj)

    assert summary["status"] == "PASS"
    assert summary["affected_total_count"] == 3
    assert summary["planned_stock_count"] == 1
    assert summary["skipped_affected_count"] == 2
    assert [row["stock_code"] for row in summary["skipped_affected_preview"]] == ["000002", "000003"]
    assert factors == {"000001": pytest.approx(2.0), "000002": pytest.approx(1.0), "000003": pytest.approx(1.0)}
    assert set(detected_again["stock_code"]) == {"000002", "000003"}


def test_max_stocks_zero_noop_does_not_update_changed_snapshot(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "max_zero_snapshot.duckdb")
    storage.init_schema()
    codes = ["000001", "000002", "000003"]
    old_adj = pd.DataFrame([_adj_row(code, "20240102", 1.0) for code in codes])
    new_adj = pd.DataFrame([_adj_row(code, "20240102", 2.0) for code in codes])
    update_adj_factor_snapshot(storage, old_adj)
    client = FakeQfqClient(new_adj.to_dict(orient="records"))

    summary = run_qfq_rebuild(start="20240102", end="20240102", max_stocks=0, storage=storage, client=client)
    snapshot = storage.read_df("SELECT stock_code, adj_factor FROM tushare_adj_factor_snapshot ORDER BY stock_code")
    detected_again = detect_changed_adj_factors(storage, new_adj)

    assert summary["status"] == "NOOP"
    assert summary["affected_total_count"] == 3
    assert summary["planned_stock_count"] == 0
    assert summary["skipped_affected_count"] == 3
    assert summary["snapshot_rows"] == 0
    assert snapshot["adj_factor"].tolist() == pytest.approx([1.0, 1.0, 1.0])
    assert set(detected_again["stock_code"]) == set(codes)
    assert int(storage.read_df("SELECT count(*) AS n FROM stock_ohlcv").loc[0, "n"]) == 0


def test_dependent_market_breadth_recomputed_for_affected_window(tmp_path) -> None:
    storage = DuckDBStorage(tmp_path / "breadth.duckdb")
    storage.init_schema()
    storage.upsert_df("all_a_stock_universe", pd.DataFrame([{"stock_code": "000001", "stock_name": "A", "list_status": "active"}]), ["stock_code"])
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame([_stock_row("000001", "2024-01-01", 10.0), _stock_row("000001", "2024-01-02", 11.0)]),
        ["stock_code", "trade_date"],
    )

    summary = rebuild_dependent_aggregates(storage, ["000001"], "20240101", "20240102")
    breadth = storage.read_df("SELECT up_count, source FROM market_breadth_daily WHERE trade_date = DATE '2024-01-02' AND breadth_mode = 'full_market'")

    assert summary["market_breadth_rows"] == 2
    assert int(breadth.loc[0, "up_count"]) == 1
    assert breadth.loc[0, "source"] == "tushare_stock_ohlcv_width"


def test_no_token_required_for_unit_tests(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ASHARE_HMM_TUSHARE_TOKEN", raising=False)
    storage = DuckDBStorage(tmp_path / "no_token.duckdb")
    storage.init_schema()

    affected = detect_changed_adj_factors(storage, pd.DataFrame([_adj_row("000001", "20240102", 2.0)]))

    assert affected.empty


def test_rebuild_report_has_no_private_path_or_token(tmp_path, monkeypatch) -> None:
    secret = "secret-token-for-test"
    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", secret)
    storage = DuckDBStorage(tmp_path / "report.duckdb")
    storage.init_schema()
    update_adj_factor_snapshot(storage, pd.DataFrame([_adj_row("000001", "20240102", 1.0)]))
    client = FakeQfqClient([_adj_row("000001", "20240102", 2.0)])
    report = tmp_path / "qfq_rebuild_report.md"
    summary_json = tmp_path / "qfq_rebuild_summary.json"

    run_qfq_rebuild(
        start="20240102",
        end="20240102",
        dry_run=True,
        storage=storage,
        client=client,
        report=report,
        summary_json=summary_json,
    )

    text = report.read_text(encoding="utf-8") + "\n" + summary_json.read_text(encoding="utf-8")
    assert secret not in text
    assert os.path.expanduser("~") not in text
    assert "/Users/" not in text
    assert ".codex_worktrees" not in text
