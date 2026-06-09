from __future__ import annotations

import inspect
import time
from pathlib import Path

import pandas as pd
import pytest

from src.data_pipeline import clean_snapshot_sql as sql
from src.data_pipeline import clean_tushare_snapshot as snap
from src.data_pipeline.storage import DuckDBStorage
from src.features.sector_features import add_sector_features, equal_weight_benchmark_ret20_from_close
from src.runtime import db_workspace


def _storage(tmp_path: Path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "clean_sql.duckdb")
    storage.init_schema()
    return storage


def _stock_rows(codes: list[str], dates: list[str]) -> pd.DataFrame:
    rows = []
    for code_idx, code in enumerate(codes, start=1):
        for day_idx, trade_date in enumerate(dates):
            close = 10.0 * code_idx + day_idx
            rows.append(
                {
                    "stock_code": code,
                    "trade_date": pd.Timestamp(trade_date).date(),
                    "open": close - 0.1,
                    "high": close + 0.5,
                    "low": close - 0.5,
                    "close": close,
                    "volume": 1000.0,
                    "amount": close * 1000.0,
                    "pct_chg": 0.0,
                    "turnover": 1.0,
                    "source": "tushare_qfq_rebased",
                    "fetched_at": pd.Timestamp("2024-01-31"),
                    "source_priority": 0,
                    "is_provisional": False,
                    "validation_status": "validated_rebased",
                    "vendor_update_time": pd.NaT,
                }
            )
    return pd.DataFrame(rows)


def _universe_rows(codes: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "stock_code": codes,
            "stock_name": [f"Stock {code}" for code in codes],
            "exchange": ["SZ"] * len(codes),
            "list_status": ["active"] * len(codes),
            "is_st": [False] * len(codes),
            "list_date": [pd.Timestamp("2020-01-01").date()] * len(codes),
            "delist_date": [pd.NaT] * len(codes),
            "source": ["tushare"] * len(codes),
            "fetched_at": [pd.Timestamp("2024-01-31")] * len(codes),
            "source_priority": [0] * len(codes),
            "is_provisional": [False] * len(codes),
            "validation_status": ["validated"] * len(codes),
            "vendor_update_time": [pd.NaT] * len(codes),
        }
    )


def test_staging_tables_receive_batched_daily_adj_basic(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    build_id = "unit-stage"
    sql.clear_clean_snapshot_staging(storage, build_id)
    sql.stage_selected_stock_codes(storage, build_id, ["000001", "000002"])

    result_1 = sql.append_clean_snapshot_stage_batch(
        storage,
        build_id,
        daily_frames=[
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000002.SZ", "000003.SZ"],
                    "trade_date": ["20240102"] * 3,
                    "open": [10.0, 20.0, 30.0],
                    "high": [11.0, 21.0, 31.0],
                    "low": [9.0, 19.0, 29.0],
                    "close": [10.5, 20.5, 30.5],
                    "vol": [1.0, 2.0, 3.0],
                    "amount": [10.0, 20.0, 30.0],
                    "pct_chg": [0.1, 0.2, 0.3],
                }
            )
        ],
        adj_frames=[pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": ["20240102"] * 2, "adj_factor": [1.0, 2.0]})],
        basic_frames=[pd.DataFrame({"ts_code": ["000001.SZ", "000002.SZ"], "trade_date": ["20240102"] * 2, "turnover_rate": [1.1, 1.2]})],
        selected_stock_codes=["000001", "000002"],
    )
    result_2 = sql.append_clean_snapshot_stage_batch(
        storage,
        build_id,
        daily_frames=[
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "trade_date": ["20240103"],
                    "open": [11.0],
                    "high": [12.0],
                    "low": [10.0],
                    "close": [11.5],
                    "vol": [1.0],
                    "amount": [11.0],
                    "pct_chg": [1.0],
                }
            )
        ],
        adj_frames=[pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240103"], "adj_factor": [2.0]})],
        basic_frames=[],
        selected_stock_codes=["000001", "000002"],
    )

    assert result_1["daily_raw_rows"] == 2
    assert result_2["daily_raw_rows"] == 1
    counts = storage.read_df(
        """
        SELECT
          (SELECT count(*) FROM clean_snapshot_daily_raw_stage WHERE snapshot_build_id = ?) AS daily_rows,
          (SELECT count(*) FROM clean_snapshot_adj_factor_stage WHERE snapshot_build_id = ?) AS adj_rows,
          (SELECT count(*) FROM clean_snapshot_daily_basic_stage WHERE snapshot_build_id = ?) AS basic_rows
        """,
        [build_id, build_id, build_id],
    )
    assert counts.loc[0, "daily_rows"] == 3
    assert counts.loc[0, "adj_rows"] == 3
    assert counts.loc[0, "basic_rows"] == 2


def test_cleanup_clean_snapshot_staging_deletes_only_requested_build_id(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    for build_id in ["cleanup-a", "cleanup-b"]:
        sql.clear_clean_snapshot_staging(storage, build_id)
        sql.stage_selected_stock_codes(storage, build_id, ["000001"])
        sql.append_clean_snapshot_stage_batch(
            storage,
            build_id,
            daily_frames=[
                pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "trade_date": ["20240102"],
                        "open": [10.0],
                        "high": [11.0],
                        "low": [9.0],
                        "close": [10.5],
                        "vol": [1.0],
                        "amount": [10.0],
                    }
                )
            ],
            adj_frames=[pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240102"], "adj_factor": [1.0]})],
            basic_frames=[],
            selected_stock_codes=["000001"],
        )

    result = sql.cleanup_clean_snapshot_staging(storage, "cleanup-a")
    counts = storage.read_df(
        """
        SELECT
          (SELECT count(*) FROM clean_snapshot_daily_raw_stage WHERE snapshot_build_id = 'cleanup-a') AS a_daily,
          (SELECT count(*) FROM clean_snapshot_daily_raw_stage WHERE snapshot_build_id = 'cleanup-b') AS b_daily,
          (SELECT count(*) FROM clean_snapshot_selected_stock_stage WHERE snapshot_build_id = 'cleanup-a') AS a_selected,
          (SELECT count(*) FROM clean_snapshot_selected_stock_stage WHERE snapshot_build_id = 'cleanup-b') AS b_selected
        """
    )

    assert result["rows"] == 3
    assert result["duration_seconds"] >= 0
    assert int(counts.loc[0, "a_daily"]) == 0
    assert int(counts.loc[0, "a_selected"]) == 0
    assert int(counts.loc[0, "b_daily"]) == 1
    assert int(counts.loc[0, "b_selected"]) == 1


def test_qfq_sql_uses_reference_factor(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    build_id = "unit-qfq"
    sql.clear_clean_snapshot_staging(storage, build_id)
    sql.stage_selected_stock_codes(storage, build_id, ["000001"])
    sql.append_clean_snapshot_stage_batch(
        storage,
        build_id,
        daily_frames=[
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ"],
                    "trade_date": ["20240103"],
                    "open": [20.0],
                    "high": [20.0],
                    "low": [20.0],
                    "close": [20.0],
                    "vol": [1.0],
                    "amount": [20.0],
                    "pct_chg": [0.0],
                }
            )
        ],
        adj_frames=[
            pd.DataFrame(
                {
                    "ts_code": ["000001.SZ", "000001.SZ"],
                    "trade_date": ["20240103", "20240104"],
                    "adj_factor": [2.0, 4.0],
                }
            )
        ],
        basic_frames=[pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240103"], "turnover_rate": [1.5]})],
        selected_stock_codes=["000001"],
    )

    ref = sql.build_reference_factor_table(storage, build_id, "20240104", ["000001"])
    result = sql.build_stock_ohlcv_from_staging_sql(storage, build_id)
    out = storage.read_df("SELECT close, turnover, source, validation_status FROM stock_ohlcv")

    assert ref["rows"] == 1
    assert result["write_mode"] == "bulk_insert"
    assert out.loc[0, "close"] == pytest.approx(10.0)
    assert out.loc[0, "turnover"] == pytest.approx(1.5)
    assert out.loc[0, "source"] == "tushare_qfq_rebased"
    assert out.loc[0, "validation_status"] == "validated_rebased"


def test_qfq_sql_repairs_vendor_ohlc_bounds_before_validation(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    build_id = "unit-qfq-repair"
    sql.clear_clean_snapshot_staging(storage, build_id)
    sql.stage_selected_stock_codes(storage, build_id, ["920489"])
    sql.append_clean_snapshot_stage_batch(
        storage,
        build_id,
        daily_frames=[
            pd.DataFrame(
                {
                    "ts_code": ["920489.BJ"],
                    "trade_date": ["20140618"],
                    "open": [10.88],
                    "high": [10.88],
                    "low": [10.88],
                    "close": [10.81],
                    "vol": [410.0],
                    "amount": [439.5],
                    "pct_chg": [3.1489],
                }
            )
        ],
        adj_frames=[pd.DataFrame({"ts_code": ["920489.BJ"], "trade_date": ["20140618"], "adj_factor": [1.0]})],
        basic_frames=[],
        selected_stock_codes=["920489"],
    )

    sql.build_reference_factor_table(storage, build_id, "20140618", ["920489"])
    result = sql.build_stock_ohlcv_from_staging_sql(storage, build_id)
    out = storage.read_df("SELECT open, high, low, close FROM stock_ohlcv")

    assert result["ohlc_bound_repaired_rows"] == 1
    assert out.loc[0, "open"] == pytest.approx(10.88)
    assert out.loc[0, "high"] == pytest.approx(10.88)
    assert out.loc[0, "low"] == pytest.approx(10.81)
    assert out.loc[0, "close"] == pytest.approx(10.81)


def test_qfq_sql_rejects_missing_reference_factor(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    build_id = "unit-missing-ref"
    sql.clear_clean_snapshot_staging(storage, build_id)
    sql.stage_selected_stock_codes(storage, build_id, ["000001", "000002"])
    sql.append_clean_snapshot_stage_batch(
        storage,
        build_id,
        daily_frames=[pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240103"], "open": [1], "high": [1], "low": [1], "close": [1], "vol": [1], "amount": [1]})],
        adj_frames=[pd.DataFrame({"ts_code": ["000001.SZ"], "trade_date": ["20240103"], "adj_factor": [1.0]})],
        basic_frames=[],
        selected_stock_codes=["000001", "000002"],
    )

    with pytest.raises(ValueError, match="missing reference_factor"):
        sql.build_reference_factor_table(storage, build_id, "20240103", ["000001", "000002"])


def test_sql_validation_detects_invalid_ohlcv_without_full_select(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.insert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {
                    "stock_code": "000001",
                    "trade_date": pd.Timestamp("2024-01-02").date(),
                    "open": 10.0,
                    "high": 9.0,
                    "low": 8.0,
                    "close": 10.0,
                    "volume": 1.0,
                    "amount": 1.0,
                    "source": "akshare",
                    "validation_status": None,
                }
            ]
        ),
    )

    result = sql.validate_clean_snapshot_sql(storage, ["20240102"], ["000001"])

    assert result["invalid_ohlcv_count"] == 1
    assert result["legacy_source_count"] == 1
    assert result["null_validation_status_count"] == 1
    assert len(result["sample_invalid_rows"]) == 1


def test_sql_validation_detects_duplicate_keys(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    with storage.connect() as con:
        con.execute("DROP TABLE stock_ohlcv")
        con.execute(
            """
            CREATE TABLE stock_ohlcv (
              stock_code VARCHAR,
              trade_date DATE,
              open DOUBLE,
              high DOUBLE,
              low DOUBLE,
              close DOUBLE,
              volume DOUBLE,
              amount DOUBLE,
              source VARCHAR,
              validation_status TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO stock_ohlcv VALUES
            ('000001', DATE '2024-01-02', 1, 1, 1, 1, 1, 1, 'tushare_qfq_rebased', 'validated_rebased'),
            ('000001', DATE '2024-01-02', 1, 1, 1, 1, 1, 1, 'tushare_qfq_rebased', 'validated_rebased')
            """
        )

    result = sql.validate_clean_snapshot_sql(storage, ["20240102"], ["000001"])

    assert result["duplicate_stock_trade_date_count"] == 1
    assert any("duplicate" in failure for failure in result["failures"])


def test_sql_validation_coverage_uses_date_eligible_universe(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.insert_df(
        "all_a_stock_universe",
        pd.DataFrame(
            {
                "stock_code": ["000001", "000002", "000003"],
                "stock_name": ["One", "Two", "Future"],
                "exchange": ["SZ", "SZ", "SZ"],
                "list_status": ["active", "active", "active"],
                "is_st": [False, False, False],
                "list_date": [
                    pd.Timestamp("2020-01-01").date(),
                    pd.Timestamp("2020-01-01").date(),
                    pd.Timestamp("2024-01-03").date(),
                ],
                "delist_date": [pd.NaT, pd.NaT, pd.NaT],
                "source": ["tushare", "tushare", "tushare"],
                "fetched_at": [pd.Timestamp("2024-01-31")] * 3,
                "source_priority": [0, 0, 0],
                "is_provisional": [False, False, False],
                "validation_status": ["validated", "validated", "validated"],
                "vendor_update_time": [pd.NaT, pd.NaT, pd.NaT],
            }
        ),
    )
    storage.insert_df("stock_ohlcv", _stock_rows(["000001", "000002"], ["20240102"]))

    result = sql.validate_clean_snapshot_sql(storage, ["20240102"], ["000001", "000002", "000003"])

    assert result["low_coverage_dates"] == []
    assert not any("universe coverage below" in failure for failure in result["failures"])


def test_sql_validation_low_trading_coverage_is_warning_not_failure(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    codes = [f"{idx:06d}" for idx in range(1, 11)]
    storage.insert_df("all_a_stock_universe", _universe_rows(codes))
    storage.insert_df("stock_ohlcv", _stock_rows(codes[:5], ["20240102"]))

    result = sql.validate_clean_snapshot_sql(storage, ["20240102"], codes)

    assert result["low_coverage_dates"] == ["20240102"]
    assert result["severe_low_coverage_dates"] == []
    assert any("trading coverage below 80%" in warning for warning in result["warnings"])
    assert not any("universe coverage below 80%" in failure for failure in result["failures"])


def test_market_breadth_sql_matches_pandas_baseline_on_synthetic_data(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    codes = ["000001", "000002"]
    dates = ["20240102", "20240103", "20240104"]
    storage.insert_df("all_a_stock_universe", _universe_rows(codes))
    storage.insert_df("stock_ohlcv", _stock_rows(codes, dates))

    result = sql.rebuild_market_breadth_sql(storage, "20240102", "20240104")
    out = storage.read_df("SELECT * FROM market_breadth_daily ORDER BY trade_date")
    out["trade_date"] = pd.to_datetime(out["trade_date"])

    assert result["rows"] == 3
    assert out.loc[out["trade_date"] == pd.Timestamp("2024-01-03"), "up_count"].iloc[0] == 2
    assert out.loc[out["trade_date"] == pd.Timestamp("2024-01-03"), "effective_count"].iloc[0] == 2
    assert out.loc[out["trade_date"] == pd.Timestamp("2024-01-04"), "amount_total"].iloc[0] == pytest.approx((12.0 + 22.0) * 1000.0)


def test_sector_ohlcv_sql_uses_single_aggregate_path_with_base_1000(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    storage.insert_df("stock_ohlcv", _stock_rows(["000001", "000002"], ["20240102", "20240103"]))
    storage.insert_df(
        "sector_meta",
        pd.DataFrame(
            [
                {
                    "sector_id": "industry:Tech",
                    "sector_type": "industry",
                    "sector_name": "Tech",
                    "source": "unit",
                    "last_update": pd.Timestamp("2024-01-03"),
                    "is_active": True,
                    "active_checked_at": pd.Timestamp("2024-01-03"),
                }
            ]
        ),
    )
    storage.insert_df(
        "sector_constituents",
        pd.DataFrame(
            [
                {"sector_id": "industry:Tech", "stock_code": "000001", "stock_name": "A", "in_sector_date": pd.Timestamp("2020-01-01").date()},
                {"sector_id": "industry:Tech", "stock_code": "000002", "stock_name": "B", "in_sector_date": pd.Timestamp("2020-01-01").date()},
            ]
        ),
    )

    result = sql.rebuild_sector_ohlcv_sql(storage, "20240102", "20240103")
    out = storage.read_df("SELECT trade_date, close, source, validation_status FROM sector_ohlcv ORDER BY trade_date")

    assert result["rows"] == 2
    assert out.loc[0, "close"] == pytest.approx(1000.0)
    assert out.loc[1, "close"] == pytest.approx(1000.0 * (1 + (((11 / 10) - 1) + ((21 / 20) - 1)) / 2))
    assert set(out["source"]) == {"tushare_local_aggregate"}
    assert set(out["validation_status"]) == {"local_aggregate"}


def test_sector_features_sql_produces_window_features(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    dates = pd.bdate_range("2024-01-01", periods=25)
    rows = []
    for idx, date in enumerate(dates):
        close = 1000.0 + idx * 10.0
        rows.append(
            {
                "sector_id": "industry:Tech",
                "trade_date": date.date(),
                "open": close - 2.0,
                "high": close + 3.0,
                "low": close - 4.0,
                "close": close,
                "volume": 1000.0,
                "amount": 10000.0 + idx,
                "pct_chg": 0.0,
                "turnover": None,
                "source": "tushare_local_aggregate",
                "validation_status": "local_aggregate",
            }
        )
    ohlcv = pd.DataFrame(rows)
    storage.insert_df("sector_ohlcv", ohlcv)

    result = sql.rebuild_sector_features_sql(storage, dates[0].strftime("%Y%m%d"), dates[-1].strftime("%Y%m%d"))
    out = storage.read_df("SELECT * FROM sector_features ORDER BY trade_date")
    daily_close = ohlcv.assign(trade_date=pd.to_datetime(ohlcv["trade_date"])).pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmark_ret20 = equal_weight_benchmark_ret20_from_close(daily_close)
    expected = add_sector_features(ohlcv, benchmark_ret20=benchmark_ret20, apply_winsorize=False)
    compare_cols = [
        "ret_1d",
        "ret_5d",
        "ret_20d",
        "vol_20d",
        "amount_z_20d",
        "rs_20d",
        "drawdown_20d",
        "ma20_slope",
        "gap_1d",
        "intraday_ret",
        "amount_shock_z",
    ]
    actual_cmp = out[["sector_id", "trade_date", *compare_cols]].copy()
    expected_cmp = expected[["sector_id", "trade_date", *compare_cols]].copy()
    actual_cmp["trade_date"] = pd.to_datetime(actual_cmp["trade_date"])
    expected_cmp["trade_date"] = pd.to_datetime(expected_cmp["trade_date"])

    assert result["rows"] == 25
    assert out["ret_1d"].notna().sum() > 0
    assert out["ret_20d"].notna().sum() > 0
    assert out["gap_1d"].notna().sum() > 0
    assert out["intraday_ret"].notna().sum() > 0
    pd.testing.assert_frame_equal(
        actual_cmp.sort_values(["sector_id", "trade_date"]).reset_index(drop=True),
        expected_cmp.sort_values(["sector_id", "trade_date"]).reset_index(drop=True),
        check_dtype=False,
        atol=1e-12,
        rtol=1e-12,
    )


def test_no_stock_hist_called_by_sql_clean_snapshot_paths() -> None:
    assert "stock_hist" not in inspect.getsource(sql)


def test_report_has_perf_metrics_and_no_private_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_dir = tmp_path / "project" / "data" / "db"
    db_dir.mkdir(parents=True)
    monkeypatch.setattr(db_workspace, "DEFAULT_DB_DIR", db_dir)
    monkeypatch.setattr(db_workspace, "WORKSPACE_CONFIG_PATH", db_dir / "workspace_config.json")
    monkeypatch.setattr(db_workspace.settings, "db_path", db_dir / "a_share_hmm.duckdb")
    source = db_dir / "source.duckdb"
    DuckDBStorage(source).init_schema()
    summary_json = tmp_path / "summary.json"
    report = tmp_path / "report.md"

    snap.run_clean_tushare_snapshot(
        target_db=db_dir / "target.duckdb",
        source_db=source,
        start="20240102",
        end="20240104",
        mode="plan-only",
        summary_json=summary_json,
        report=report,
    )

    text = summary_json.read_text(encoding="utf-8") + "\n" + report.read_text(encoding="utf-8")
    assert "qfq_sql_transform_duration_seconds" in text
    assert "memory_safety_note" in text
    assert str(tmp_path) not in text


def test_large_synthetic_build_does_not_timeout_small_threshold(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    build_id = "unit-large"
    codes = [f"{idx:06d}" for idx in range(1, 51)]
    dates = pd.bdate_range("2024-01-01", periods=20).strftime("%Y%m%d").tolist()
    sql.clear_clean_snapshot_staging(storage, build_id)
    sql.stage_selected_stock_codes(storage, build_id, codes)
    started = time.monotonic()
    for trade_date in dates:
        daily_rows = []
        adj_rows = []
        for code_idx, code in enumerate(codes, start=1):
            close = 10.0 + code_idx / 100.0
            daily_rows.append({"ts_code": f"{code}.SZ", "trade_date": trade_date, "open": close, "high": close, "low": close, "close": close, "vol": 1.0, "amount": close})
            adj_rows.append({"ts_code": f"{code}.SZ", "trade_date": trade_date, "adj_factor": 1.0})
        sql.append_clean_snapshot_stage_batch(
            storage,
            build_id,
            daily_frames=[pd.DataFrame(daily_rows)],
            adj_frames=[pd.DataFrame(adj_rows)],
            basic_frames=[],
            selected_stock_codes=codes,
        )
    sql.build_reference_factor_table(storage, build_id, dates[-1], codes)
    result = sql.build_stock_ohlcv_from_staging_sql(storage, build_id)

    assert result["rows"] == 1000
    assert time.monotonic() - started < 10.0
