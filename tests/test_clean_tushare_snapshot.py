from __future__ import annotations

import inspect
import json
from pathlib import Path

import duckdb
import pandas as pd
import pytest

from src.data_pipeline import clean_tushare_snapshot as snap
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.runtime import db_workspace


class FakeTushareSnapshotClient:
    def __init__(self, *, missing_adj: bool = False) -> None:
        self.missing_adj = missing_adj
        self.trade_date_calls: list[str] = []
        self.stock_hist_calls: list[str] = []
        self._trade_dates = ["20240102", "20240103", "20240104"]
        self._codes = ["000001", "000002", "000003"]

    def trade_dates(self, start_date: str, end_date: str, force_refresh: bool = False) -> list[str]:
        del start_date, end_date, force_refresh
        return list(self._trade_dates)

    def all_a_stock_universe(self, force_refresh: bool = False) -> DataResult:
        del force_refresh
        return DataResult(
            pd.DataFrame(
                {
                    "stock_code": self._codes,
                    "stock_name": ["Alpha", "Beta", "Gamma"],
                    "exchange": ["SZ", "SZ", "SH"],
                    "list_status": ["active", "active", "active"],
                    "is_st": [False, False, False],
                    "list_date": [pd.Timestamp("2020-01-01").date()] * 3,
                    "delist_date": [pd.NaT] * 3,
                    "source": ["tushare"] * 3,
                    "fetched_at": [pd.Timestamp("2024-01-04")] * 3,
                    "source_priority": [0] * 3,
                    "is_provisional": [False] * 3,
                    "validation_status": ["validated"] * 3,
                    "vendor_update_time": [pd.NaT] * 3,
                }
            )
        )

    def _daily_raw_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        del force_refresh
        self.trade_date_calls.append(trade_date)
        day_offset = self._trade_dates.index(trade_date)
        rows = []
        for code_index, code in enumerate(self._codes, start=1):
            close = 10.0 * code_index + day_offset
            rows.append(
                {
                    "ts_code": f"{code}.SZ" if code != "000003" else f"{code}.SH",
                    "trade_date": trade_date,
                    "open": close - 0.2,
                    "high": close + 0.8,
                    "low": close - 0.8,
                    "close": close,
                    "pre_close": close - 1.0,
                    "change": 1.0,
                    "pct_chg": 1.0,
                    "vol": 1000.0 + code_index,
                    "amount": close * 1000.0,
                }
            )
        return DataResult(pd.DataFrame(rows))

    def _adj_factor_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        del force_refresh
        factors_by_date = {
            "20240102": [1.0, 2.0, 1.0],
            "20240103": [2.0, 4.0, 1.5],
            "20240104": [4.0, 8.0, 2.0],
        }
        rows = []
        for code, factor in zip(self._codes, factors_by_date[trade_date], strict=True):
            if self.missing_adj and code == "000002":
                continue
            rows.append(
                {
                    "ts_code": f"{code}.SZ" if code != "000003" else f"{code}.SH",
                    "trade_date": trade_date,
                    "adj_factor": factor,
                }
            )
        return DataResult(pd.DataFrame(rows))

    def _daily_basic_by_trade_date(self, trade_date: str, force_refresh: bool = False) -> DataResult:
        del force_refresh
        return DataResult(
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "000003.SH"],
                    "trade_date": [trade_date] * 3,
                    "turnover_rate": [1.1, 1.2, 1.3],
                    "volume_ratio": [0.9, 1.0, 1.1],
                    "total_mv": [100.0, 200.0, 300.0],
                    "circ_mv": [90.0, 180.0, 270.0],
                }
            )
        )

    def market_index_hist(
        self,
        index_code: str,
        index_name: str | None = None,
        start_date: str = "20240102",
        end_date: str = "20240104",
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        del start_date, end_date, force_refresh, ttl_seconds
        rows = []
        for idx, trade_date in enumerate(self._trade_dates):
            close = 100.0 + idx
            rows.append(
                {
                    "index_code": str(index_code).zfill(6),
                    "index_name": index_name or index_code,
                    "trade_date": pd.to_datetime(trade_date).date(),
                    "open": close - 0.5,
                    "high": close + 0.5,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 10000.0,
                    "amount": 100000.0,
                    "pct_chg": 1.0,
                    "source": "tushare_index_daily",
                    "fetched_at": pd.Timestamp("2024-01-04"),
                    "source_priority": 0,
                    "is_provisional": False,
                    "validation_status": "validated",
                    "vendor_update_time": pd.NaT,
                }
            )
        return DataResult(pd.DataFrame(rows))

    def market_benchmark_hist(
        self,
        benchmark_id: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        del start_date, end_date, force_refresh, ttl_seconds
        rows = []
        for idx, trade_date in enumerate(self._trade_dates):
            close = 200.0 + idx
            rows.append(
                {
                    "benchmark_id": benchmark_id,
                    "trade_date": pd.to_datetime(trade_date).date(),
                    "open": close - 0.5,
                    "high": close + 0.5,
                    "low": close - 1.0,
                    "close": close,
                    "volume": 10000.0,
                    "amount": 100000.0,
                    "pct_chg": 1.0,
                    "turnover": pd.NA,
                    "source": "tushare_index_daily",
                    "fetched_at": pd.Timestamp("2024-01-04"),
                    "source_priority": 0,
                    "is_provisional": False,
                    "validation_status": "validated",
                    "vendor_update_time": pd.NaT,
                }
            )
        return DataResult(pd.DataFrame(rows))

    def board_names(self, board_type: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        del force_refresh, ttl_seconds
        assert board_type == "industry"
        return DataResult(
            pd.DataFrame(
                [
                    {
                        "sector_id": "industry:Tech",
                        "sector_type": "industry",
                        "sector_name": "Tech",
                        "source": "tushare_sw_classify",
                        "last_update": pd.Timestamp("2024-01-04"),
                    }
                ]
            )
        )

    def board_constituents(self, board_type: str, sector_name: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        del force_refresh, ttl_seconds
        assert board_type == "industry"
        assert sector_name == "Tech"
        return DataResult(
            pd.DataFrame(
                [
                    {
                        "sector_id": "industry:Tech",
                        "stock_code": "000001",
                        "stock_name": "Alpha",
                        "in_sector_date": pd.Timestamp("2020-01-01").date(),
                        "source": "tushare_sw_members",
                        "fetched_at": pd.Timestamp("2024-01-04"),
                        "source_priority": 0,
                        "is_provisional": False,
                        "validation_status": "validated",
                        "vendor_update_time": pd.NaT,
                    },
                    {
                        "sector_id": "industry:Tech",
                        "stock_code": "000002",
                        "stock_name": "Beta",
                        "in_sector_date": pd.Timestamp("2020-01-01").date(),
                        "source": "tushare_sw_members",
                        "fetched_at": pd.Timestamp("2024-01-04"),
                        "source_priority": 0,
                        "is_provisional": False,
                        "validation_status": "validated",
                        "vendor_update_time": pd.NaT,
                    },
                ]
            )
        )

    def stock_hist(self, stock_code: str, start_date: str, end_date: str) -> DataResult:
        self.stock_hist_calls.append(stock_code)
        raise AssertionError("clean snapshot must not fetch full-market daily data stock-by-stock")


@pytest.fixture()
def workspace_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_dir = tmp_path / "project" / "data" / "db"
    db_dir.mkdir(parents=True)
    monkeypatch.setattr(db_workspace, "DEFAULT_DB_DIR", db_dir)
    monkeypatch.setattr(db_workspace, "WORKSPACE_CONFIG_PATH", db_dir / "workspace_config.json")
    monkeypatch.setattr(db_workspace.settings, "db_path", db_dir / "a_share_hmm.duckdb")
    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", "<placeholder>")
    return db_dir


@pytest.fixture()
def source_db(workspace_paths: Path) -> Path:
    source = workspace_paths / "source.duckdb"
    storage = DuckDBStorage(source)
    storage.init_schema()
    universe_id = storage.create_universe("Research")
    storage.add_universe_item(universe_id, "industry", "industry:Tech", "Tech")
    basket_id = storage.create_custom_stock_basket("Watch")
    storage.add_basket_members(basket_id, [{"stock_code": "000001", "stock_name": "Alpha"}])
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {
                    "stock_code": "000001",
                    "trade_date": pd.Timestamp("2023-12-29").date(),
                    "open": 9.0,
                    "high": 10.0,
                    "low": 8.0,
                    "close": 9.5,
                    "volume": 1.0,
                    "amount": 1.0,
                    "source": "akshare",
                }
            ]
        ),
        ["stock_code", "trade_date"],
    )
    with duckdb.connect(str(source)) as con:
        con.execute("CREATE TABLE final_holdout_secret(id INTEGER)")
        con.execute("INSERT INTO final_holdout_secret VALUES (1)")
    return source


def _target(workspace_paths: Path, name: str = "target.duckdb") -> Path:
    return workspace_paths / name


def _run_build(target: Path, source: Path, **kwargs: object) -> dict[str, object]:
    return snap.run_clean_tushare_snapshot(
        target_db=target,
        source_db=source,
        start="20240102",
        end="20240104",
        mode="build",
        client=kwargs.pop("client", FakeTushareSnapshotClient()),
        **kwargs,
    )


def test_preflight_refuses_target_equal_source(source_db: Path) -> None:
    config = snap.CleanSnapshotConfig(
        target_db=source_db,
        source_db=source_db,
        start="20240102",
        end="20240104",
    )

    with pytest.raises(ValueError, match="target_db must not equal source_db"):
        snap.preflight_clean_snapshot(config)


def test_preflight_refuses_existing_target_without_allow_existing(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)
    DuckDBStorage(target).init_schema()
    config = snap.CleanSnapshotConfig(target_db=target, source_db=source_db, start="20240102", end="20240104")

    with pytest.raises(ValueError, match="target_db already exists"):
        snap.preflight_clean_snapshot(config)


def test_plan_only_does_not_create_or_write_target_db(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = snap.run_clean_tushare_snapshot(
        target_db=target,
        source_db=source_db,
        start="20240102",
        end="20240104",
        mode="plan-only",
    )

    assert summary["status"] == "PLAN_ONLY"
    assert not target.exists()


def test_create_target_db_initializes_schema_and_metadata(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = _run_build(target, source_db)
    metadata = DuckDBStorage(target).read_df("SELECT key, value FROM database_workspace_metadata")
    values = dict(zip(metadata["key"], metadata["value"], strict=False))

    assert summary["status"] == "PASS"
    assert values["db_profile"] == snap.SNAPSHOT_PROFILE
    assert values["created_by"] == "clean_tushare_snapshot"
    assert values["qfq_policy"] == "explicit_reference_factor"


def test_copy_user_assets_allowlist_only(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    _run_build(target, source_db)
    storage = DuckDBStorage(target)

    assert int(storage.read_df("SELECT count(*) AS n FROM user_universe").loc[0, "n"]) == 1
    assert int(storage.read_df("SELECT count(*) AS n FROM custom_stock_basket").loc[0, "n"]) == 1
    assert int(storage.read_df("SELECT count(*) AS n FROM qfq_rebuild_runs").loc[0, "n"]) == 0


def test_market_tables_not_copied_from_source(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    _run_build(target, source_db)
    storage = DuckDBStorage(target)
    legacy = storage.read_df("SELECT * FROM stock_ohlcv WHERE source = 'akshare' OR trade_date = DATE '2023-12-29'")

    assert legacy.empty


def test_reference_factor_uses_end_date_latest_factor() -> None:
    adj = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ", "000001.SZ"],
            "trade_date": ["20240102", "20240103", "20240105"],
            "adj_factor": [1.0, 2.0, 5.0],
        }
    )

    refs = snap.build_reference_factors(adj, "20240104", ["000001"])

    assert refs == {"000001": 2.0}


def test_clean_snapshot_qfq_uses_reference_factor_not_window_last_factor() -> None:
    daily = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20240102", "20240103"],
            "open": [10.0, 20.0],
            "high": [10.0, 20.0],
            "low": [10.0, 20.0],
            "close": [10.0, 20.0],
            "vol": [1.0, 1.0],
            "amount": [10.0, 20.0],
            "pct_chg": [0.0, 100.0],
        }
    )
    adj = pd.DataFrame(
        {
            "ts_code": ["000001.SZ", "000001.SZ"],
            "trade_date": ["20240102", "20240103"],
            "adj_factor": [1.0, 2.0],
        }
    )

    out = snap.normalize_all_qfq_with_reference(daily, adj, {"000001": 4.0})

    assert out.loc[out["trade_date"] == pd.Timestamp("2024-01-03").date(), "close"].iloc[0] == pytest.approx(10.0)
    assert out["source"].unique().tolist() == ["tushare_qfq_rebased"]


def test_stock_ohlcv_written_without_duplicate_stock_trade_date(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    _run_build(target, source_db)
    duplicates = DuckDBStorage(target).read_df(
        """
        SELECT stock_code, trade_date, count(*) AS n
        FROM stock_ohlcv
        GROUP BY stock_code, trade_date
        HAVING count(*) > 1
        """
    )

    assert duplicates.empty


def test_clean_snapshot_progress_callback_emits_overall_and_stock_levels(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths, "progress.duckdb")
    events: list[dict[str, object]] = []

    summary = _run_build(target, source_db, progress_callback=events.append, job_id="unit-progress")

    assert summary["status"] == "PASS"
    assert events
    assert events[-1]["status"] == "pass"
    assert events[-1]["overall_progress"] == pytest.approx(1.0)
    stock_events = [event for event in events if event.get("stage") == "fetch_stock_ohlcv_qfq" and "stock_total" in event]
    assert stock_events
    assert stock_events[-1]["stock_current"] == stock_events[-1]["stock_total"]
    assert stock_events[-1]["stock_progress"] == pytest.approx(1.0)
    assert {event.get("stock_api") for event in stock_events} >= {"daily", "adj_factor", "daily_basic"}
    assert {event.get("stock_api") for event in stock_events} >= {"reference_factors", "normalize_qfq", "upsert_stock_ohlcv", "stock_ohlcv_written"}
    assert all(0.0 <= float(event.get("overall_progress", 0.0)) <= 1.0 for event in events)


def test_progress_json_writer_merges_runtime_metadata_without_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASHARE_HMM_TUSHARE_TOKEN", "<placeholder>")
    progress_json = tmp_path / "progress.json"

    snap._write_progress_json(
        progress_json,
        {
            "job_id": "unit-job",
            "pid": 12345,
            "target_db": "data/db/target.duckdb",
            "source_db": "data/db/source.duckdb",
        },
    )
    snap._write_progress_json(progress_json, {"status": "running", "overall_progress": 0.5})
    payload = json.loads(progress_json.read_text(encoding="utf-8"))
    text = progress_json.read_text(encoding="utf-8")

    assert payload["pid"] == 12345
    assert payload["status"] == "running"
    assert payload["overall_progress"] == 0.5
    assert "<placeholder>" not in text
    assert "ASHARE_HMM_TUSHARE_TOKEN" not in text


def test_clean_snapshot_rejects_missing_adj_factor(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    with pytest.raises(ValueError, match="missing reference_factor|缺少有效"):
        _run_build(target, source_db, client=FakeTushareSnapshotClient(missing_adj=True))


def test_clean_snapshot_rejects_legacy_source_rows(workspace_paths: Path) -> None:
    target = _target(workspace_paths)
    storage = DuckDBStorage(target)
    storage.init_schema()
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {
                    "stock_code": "000001",
                    "trade_date": pd.Timestamp("2024-01-02").date(),
                    "open": 1.0,
                    "high": 1.0,
                    "low": 1.0,
                    "close": 1.0,
                    "volume": 1.0,
                    "amount": 1.0,
                    "source": "akshare",
                    "validation_status": "validated",
                }
            ]
        ),
        ["stock_code", "trade_date"],
    )

    validation = snap.validate_clean_snapshot(storage, ["20240102"], ["000001"])

    assert validation["validation_status"] == "failed"
    assert any("legacy source" in failure for failure in validation["failures"])


def test_market_breadth_rebuilt_from_target_stock_ohlcv(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = _run_build(target, source_db)
    rows = DuckDBStorage(target).read_df("SELECT count(*) AS n FROM market_breadth_daily")

    assert summary["market_breadth_rows"] > 0
    assert int(rows.loc[0, "n"]) > 0


def test_sector_ohlcv_rebuilt_from_target_stock_ohlcv(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = _run_build(target, source_db)
    rows = DuckDBStorage(target).read_df("SELECT source, count(*) AS n FROM sector_ohlcv GROUP BY source")

    assert summary["sector_ohlcv_rows"] > 0
    assert dict(zip(rows["source"], rows["n"], strict=False))["tushare_local_aggregate"] > 0


def test_sector_features_rebuilt_after_sector_ohlcv(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = _run_build(target, source_db)
    rows = DuckDBStorage(target).read_df("SELECT count(*) AS n FROM sector_features")

    assert summary["sector_feature_rows"] > 0
    assert int(rows.loc[0, "n"]) > 0


def test_summary_report_has_no_token_or_private_paths(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)
    summary_json = workspace_paths.parent / "summary.json"
    report = workspace_paths.parent / "report.md"

    snap.run_clean_tushare_snapshot(
        target_db=target,
        source_db=source_db,
        start="20240102",
        end="20240104",
        mode="plan-only",
        summary_json=summary_json,
        report=report,
    )
    text = summary_json.read_text(encoding="utf-8") + "\n" + report.read_text(encoding="utf-8")

    assert "<placeholder>" not in text
    assert str(workspace_paths.parent) not in text
    assert ".codex_worktrees" not in text


def test_set_active_requires_successful_validation(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)
    DuckDBStorage(target).init_schema()

    with pytest.raises(RuntimeError, match="set-active requires successful validation"):
        snap.run_clean_tushare_snapshot(
            target_db=target,
            source_db=source_db,
            start="20240102",
            end="20240104",
            mode="validate-only",
            set_active=True,
        )


def test_no_hmm_hsmm_hazard_training_called() -> None:
    source = inspect.getsource(snap)

    assert "src.models" not in source
    assert "train_hmm" not in source
    assert "train_hsmm" not in source
    assert "train_hazard" not in source
    assert "hazard_model" not in source


def test_final_holdout_not_accessed(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    _run_build(target, source_db)
    with duckdb.connect(str(target), read_only=True) as con:
        tables = {row[0] for row in con.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'").fetchall()}

    assert "final_holdout_secret" not in tables


def test_max_trade_dates_limits_for_unit_tests(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)
    client = FakeTushareSnapshotClient()

    summary = _run_build(target, source_db, client=client, max_trade_dates=2)

    assert summary["trade_day_count"] == 2
    assert client.trade_date_calls == ["20240102", "20240103"]


def test_max_stocks_limits_for_unit_tests(workspace_paths: Path, source_db: Path) -> None:
    target = _target(workspace_paths)

    summary = _run_build(target, source_db, max_stocks=1)
    storage = DuckDBStorage(target)
    universe_rows = storage.read_df("SELECT count(*) AS n FROM all_a_stock_universe")
    stock_count = storage.read_df("SELECT count(DISTINCT stock_code) AS n FROM stock_ohlcv")

    assert summary["stock_count"] == 1
    assert int(universe_rows.loc[0, "n"]) == 1
    assert int(stock_count.loc[0, "n"]) == 1
