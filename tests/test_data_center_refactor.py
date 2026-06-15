from __future__ import annotations

import inspect
from pathlib import Path

import pandas as pd

from src.data_pipeline.market_updater import update_all_a_stock_ohlcv
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.base import DataResult
from src.ui import data_center_page
from src.ui.components.data_coverage import _width_metric_text, build_data_coverage_snapshot
from src.ui.help_texts import rename_columns_for_display


def test_data_coverage_snapshot_sector_counts(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame(
            [
                {"sector_id": "industry:A", "sector_type": "industry", "sector_name": "A", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
                {"sector_id": "industry:B", "sector_type": "industry", "sector_name": "B", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
                {"sector_id": "concept:C", "sector_type": "concept", "sector_name": "C", "source": "test", "last_update": pd.Timestamp("2024-01-01")},
            ]
        ),
        ["sector_id"],
    )
    storage.upsert_df(
        "sector_ohlcv",
        pd.DataFrame(
            [
                {"sector_id": "industry:A", "trade_date": pd.Timestamp("2024-01-01").date(), "close": 100},
                {"sector_id": "concept:C", "trade_date": pd.Timestamp("2024-01-02").date(), "close": 100},
            ]
        ),
        ["sector_id", "trade_date"],
    )

    snapshot = build_data_coverage_snapshot(storage)
    industry = snapshot[snapshot["dimension"] == "行业板块行情"].iloc[0]
    concept = snapshot[snapshot["dimension"] == "概念板块行情"].iloc[0]

    assert int(industry["expected_count"]) == 2
    assert int(industry["stored_count"]) == 1
    assert float(industry["coverage_ratio"]) == 0.5
    assert "缺少行情 1 个" in industry["note"]
    assert int(concept["expected_count"]) == 1
    assert int(concept["stored_count"]) == 1


def test_data_coverage_uses_active_sector_meta_for_all_market(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    now = pd.Timestamp("2024-01-10")
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame(
            [
                {"sector_id": "industry:active", "sector_type": "industry", "sector_name": "active", "source": "test", "last_update": now, "is_active": True, "active_checked_at": now},
                {"sector_id": "industry:legacy", "sector_type": "industry", "sector_name": "legacy", "source": "test", "last_update": now, "is_active": False, "active_checked_at": now},
            ]
        ),
        ["sector_id"],
    )
    storage.upsert_df(
        "sector_ohlcv",
        pd.DataFrame([{"sector_id": "industry:active", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 100}]),
        ["sector_id", "trade_date"],
    )

    snapshot = build_data_coverage_snapshot(storage)
    industry = snapshot[snapshot["dimension"] == "行业板块行情"].iloc[0]

    assert int(industry["expected_count"]) == 1
    assert int(industry["stored_count"]) == 1
    assert float(industry["coverage_ratio"]) == 1.0


def test_data_coverage_snapshot_stock_counts(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "all_a_stock_universe",
        pd.DataFrame(
            {
                "stock_code": ["000001", "000002", "000003"],
                "stock_name": ["A", "B", "C"],
                "exchange": ["SZ", "SZ", "SZ"],
                "list_status": ["active", "active", "active"],
                "is_st": [False, False, False],
                "source": ["test", "test", "test"],
                "fetched_at": [pd.Timestamp("2024-01-10")] * 3,
            }
        ),
        ["stock_code"],
    )
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {"stock_code": "000001", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
                {"stock_code": "000002", "trade_date": pd.Timestamp("2024-01-01").date(), "close": 10},
                {"stock_code": "999999", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
            ]
        ),
        ["stock_code", "trade_date"],
    )

    snapshot = build_data_coverage_snapshot(storage)
    stock = snapshot[snapshot["dimension"] == "个股行情"].iloc[0]

    assert int(stock["expected_count"]) == 3
    assert int(stock["stored_count"]) == 2
    assert int(stock["recent_count"]) == 1
    assert float(stock["coverage_ratio"]) <= 1.0


def test_data_coverage_stock_counts_use_same_universe_scope(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    universe_id = storage.create_universe("测试池")
    storage.add_universe_item(universe_id, "industry", "industry:A", "A")
    storage.upsert_df(
        "sector_constituents",
        pd.DataFrame(
            [
                {"sector_id": "industry:A", "stock_code": "000001", "stock_name": "A"},
                {"sector_id": "industry:A", "stock_code": "000002", "stock_name": "B"},
            ]
        ),
        ["sector_id", "stock_code"],
    )
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {"stock_code": "000001", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
                {"stock_code": "999999", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
            ]
        ),
        ["stock_code", "trade_date"],
    )

    snapshot = build_data_coverage_snapshot(storage, universe_id=universe_id)
    stock = snapshot[snapshot["dimension"] == "个股行情"].iloc[0]

    assert int(stock["expected_count"]) == 2
    assert int(stock["stored_count"]) == 1
    assert float(stock["coverage_ratio"]) == 0.5


def test_data_coverage_breadth_modes(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    rows = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2024-01-10").date(),
                "breadth_mode": "local_sample",
                "effective_count": 300,
                "expected_count": 300,
                "coverage_ratio": 1.0,
                "coverage_level": "partial_sample",
            },
            {
                "trade_date": pd.Timestamp("2024-01-10").date(),
                "breadth_mode": "full_market",
                "effective_count": 3500,
                "expected_count": 4300,
                "coverage_ratio": 3500 / 4300,
                "coverage_level": "full_market",
            },
        ]
    )
    storage.upsert_df("market_breadth_daily", rows, ["trade_date", "breadth_mode"])

    snapshot = build_data_coverage_snapshot(storage)
    local = snapshot[snapshot["dimension"] == "市场宽度：本地样本"].iloc[0]
    full = snapshot[snapshot["dimension"] == "市场宽度：全 A"].iloc[0]

    assert local["breadth_mode"] == "local_sample"
    assert full["breadth_mode"] == "full_market"
    assert int(local["stored_count"]) == 300
    assert int(full["stored_count"]) == 3500


def test_data_coverage_breadth_display_has_unique_columns(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "market_breadth_daily",
        pd.DataFrame(
            [
                {
                    "trade_date": pd.Timestamp("2024-01-10").date(),
                    "breadth_mode": "full_market",
                    "effective_count": 3500,
                    "expected_count": 4300,
                    "coverage_ratio": 3500 / 4300,
                    "coverage_level": "full_market",
                }
            ]
        ),
        ["trade_date", "breadth_mode"],
    )
    snapshot = build_data_coverage_snapshot(storage)
    width_rows = snapshot[snapshot["breadth_mode"].notna()][["dimension", "stored_count", "expected_count", "coverage_level"]].copy()
    width_rows["覆盖率"] = snapshot.loc[snapshot["breadth_mode"].notna(), "coverage_ratio"].map(lambda x: "无" if pd.isna(x) else f"{float(x):.1%}").to_list()
    display = rename_columns_for_display(width_rows)

    assert display.columns.is_unique


def test_width_metric_text_is_user_facing_chinese():
    full_label, full_delta = _width_metric_text(
        pd.Series({"coverage_level": "full_market", "coverage_ratio": 0.837, "stored_count": 3600, "expected_count": 4300}),
        "full_market",
    )
    local_label, local_delta = _width_metric_text(
        pd.Series({"coverage_level": "partial_sample", "coverage_ratio": 1.0, "stored_count": 5189, "expected_count": 5189}),
        "local_sample",
    )

    assert full_label == "全市场覆盖达标"
    assert "覆盖 83.7%" in full_delta
    assert "有效 3600/4300 只" in full_delta
    assert local_label == "本地样本观察"
    assert "不代表全 A" in local_delta
    assert "full_market" not in full_label + full_delta + local_label + local_delta
    assert "partial_sample" not in full_label + full_delta + local_label + local_delta


def test_data_center_hides_manual_stock_input_by_default():
    source = inspect.getsource(data_center_page.render_data_update_tasks)
    assert "个股代码（每行一个）" not in source
    assert "更新输入个股行情" not in source


def test_data_center_single_update_action():
    source = inspect.getsource(data_center_page.render_data_update_tasks)
    assert source.count('st.button("开始更新"') == 1
    assert data_center_page.TASK_OPTIONS == [
        "更新 Tushare 股票池",
        "更新 Tushare 全 A 日频行情",
        "更新 Tushare 指数与市场基准",
        "更新全 A 市场宽度",
        "更新 Tushare 行业/本地聚合板块",
        "重试失败任务",
    ]


def test_data_center_stock_worker_defaults_are_source_aware(monkeypatch):
    monkeypatch.setattr(data_center_page.settings, "market_data_source", "tushare")
    assert data_center_page.stock_worker_defaults_for_source() == (1, 1)

    monkeypatch.setattr(data_center_page.settings, "market_data_source", "akshare")
    monkeypatch.setattr(data_center_page.settings, "tdx_global_workers", 8)
    monkeypatch.setattr(data_center_page.settings, "tdx_max_workers", 16)
    assert data_center_page.stock_worker_defaults_for_source() == (3, 3)

    monkeypatch.setattr(data_center_page.settings, "market_data_source", "mootdx")
    assert data_center_page.stock_worker_defaults_for_source() == (8, 16)


def test_data_center_progress_source_display_names():
    assert data_center_page._data_source_display_name("tushare") == "Tushare"
    assert data_center_page._data_source_display_name("ts") == "Tushare"
    assert data_center_page._data_source_display_name("mootdx") == "mootdx/TDX"
    assert data_center_page._data_source_display_name("legacy-akshare") == "AKShare legacy"


def test_retry_failures_does_not_fetch_first_10_when_no_failures(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()

    def fail_if_called(*args, **kwargs):
        raise AssertionError("没有失败项时不应调用抓取函数")

    monkeypatch.setattr(data_center_page, "incremental_update_boards", fail_if_called)
    result = data_center_page.retry_failed_tasks(storage, "20240101", "20240110", incremental=True, lookback_days=10, workers=1)

    assert result.message == "暂无失败任务。"
    assert result.updated == 0
    assert result.failures == []


def test_retry_failures_skips_stable_empty_tushare_constituents(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    storage.record_fetch_failure(
        "sector",
        "industry",
        "社交Ⅱ",
        "board_constituents",
        "tushare_index_member_all 调用失败: ValueError: index_member_all 返回空数据",
    )
    storage.record_fetch_failure(
        "sector",
        "industry",
        "社交Ⅱ",
        "board_hist",
        "缺少 industry:社交Ⅱ 成分股，无法生成 Tushare 本地聚合板块行情。",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("稳定空成分股失败不应自动重试")

    monkeypatch.setattr(data_center_page, "incremental_update_boards", fail_if_called)
    result = data_center_page.retry_failed_tasks(storage, "20240101", "20240110", incremental=True, lookback_days=10, workers=1)

    assert result.updated == 0
    assert result.skipped == 2
    assert result.failures == []
    assert "跳过稳定失败 2 条" in result.message


def test_data_center_tushare_labels_and_controls():
    source = inspect.getsource(data_center_page.render_data_update_tasks)
    assert "ASHARE_HMM_TUSHARE_TOKEN" in source
    assert "按交易日批量" in source
    assert "stock_ohlcv 写入前复权兼容 OHLCV" in source
    assert "TDX 批大小" in source
    assert "if not is_tushare_source" in source


def test_sidebar_has_explicit_all_market_scope():
    app_source = Path("app.py").read_text()
    assert "全市场（不使用板块池）" in app_source
    assert "当前观察范围" in app_source
    assert "选择“全市场”时" in app_source


def test_market_regime_status_bar_uses_current_scope_run():
    app_source = Path("app.py").read_text(encoding="utf-8")
    page_source = Path("src/ui/market_regime_page.py").read_text(encoding="utf-8")

    assert "render_market_regime(storage, universe_id=selected_universe_id)" in app_source
    assert "latest_run_for_current_scope(universe_id)" in page_source
    assert "render_data_status_bar(storage, run_id=run_id, universe_id=universe_id)" in page_source


def test_all_a_width_pipeline_sequence(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    calls: list[str] = []
    progress_events: list[dict[str, object]] = []

    def fake_universe(**kwargs):
        calls.append("update_all_a_stock_universe")
        return {"updated": 1, "rows": 1, "failures": []}

    def fake_ohlcv(*args, **kwargs):
        calls.append("update_all_a_stock_ohlcv")
        callback = kwargs.get("progress_callback")
        callback({"current": 0, "total": 4, "name": "000001", "successes": 0, "failures": 0, "cache_hits": 0, "stale_reads": 0})
        callback({"current": 2, "total": 4, "name": "000002", "successes": 2, "failures": 0, "cache_hits": 1, "stale_reads": 0})
        callback({"current": 4, "total": 4, "name": "000004", "successes": 4, "failures": 0, "cache_hits": 1, "stale_reads": 0})
        return {"updated": 2, "rows": 20, "failures": []}

    def fake_breadth(*args, **kwargs):
        calls.append(f"update_market_breadth:{kwargs.get('mode')}")
        return {"updated": 3, "rows": 3, "failures": []}

    monkeypatch.setattr(data_center_page, "update_all_a_stock_universe", fake_universe)
    monkeypatch.setattr(data_center_page, "update_all_a_stock_ohlcv", fake_ohlcv)
    monkeypatch.setattr(data_center_page, "update_market_breadth", fake_breadth)

    result = data_center_page.run_all_a_width_pipeline(
        "20240101",
        "20240110",
        incremental=True,
        skip_completed=True,
        lookback_days=10,
        all_a_lookback_days=60,
        max_stocks=None,
        workers=3,
        force_refresh=False,
        storage=storage,
        progress_callback=progress_events.append,
    )

    assert calls == ["update_all_a_stock_universe", "update_all_a_stock_ohlcv", "update_market_breadth:full_market"]
    assert result.updated == 6
    assert result.rows == 24
    assert progress_events[0]["stage"] == "更新 Tushare 股票池"
    assert any(event["stage"] == "按交易日批量更新 Tushare 全 A 日线" and event["current"] == 2 for event in progress_events)
    assert progress_events[-1]["stage"] == "Tushare 全 A 日频与宽度更新完成"
    overall = [float(event["overall_progress"]) for event in progress_events]
    assert overall == sorted(overall)
    assert overall[-1] == 1.0


def test_all_a_progress_event_weighted_progress():
    start = data_center_page.all_a_progress_event("universe", "更新 Tushare 股票池", 1, current=1, total=1)
    middle = data_center_page.all_a_progress_event("stock", "按交易日批量更新 Tushare 全 A 日线", 2, current=50, total=100, data_source="mootdx")
    end = data_center_page.all_a_progress_event("breadth", "计算全 A 市场宽度", 3, current=1, total=1)

    assert start["overall_progress"] == 0.05
    assert 0.05 < float(middle["overall_progress"]) < 0.93
    assert end["overall_progress"] == 1.0
    assert middle["stage_progress"] == 0.5
    assert middle["data_source"] == "mootdx/TDX"


def test_all_a_stock_ohlcv_skip_completed_stocks(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    codes = ["000001", "000002", "000003"]
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
    storage.upsert_df(
        "stock_ohlcv",
        pd.DataFrame(
            [
                {"stock_code": "000001", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
                {"stock_code": "000002", "trade_date": pd.Timestamp("2024-01-10").date(), "close": 10},
            ]
        ),
        ["stock_code", "trade_date"],
    )

    class FakeClient:
        def __init__(self):
            self.calls: list[str] = []

        def stock_hist(self, stock_code: str, start_date: str, end_date: str):
            self.calls.append(stock_code)
            return DataResult(
                pd.DataFrame(
                    [
                        {
                            "stock_code": stock_code,
                            "trade_date": pd.Timestamp("2024-01-10").date(),
                            "open": 10.0,
                            "high": 12.0,
                            "low": 9.0,
                            "close": 11,
                            "volume": 1000.0,
                            "amount": 11000.0,
                        }
                    ]
                )
            )

    client = FakeClient()
    summary = update_all_a_stock_ohlcv(
        "20240101",
        "20240110",
        incremental=True,
        skip_completed=True,
        probe_latest=True,
        client=client,  # type: ignore[arg-type]
        storage=storage,
    )

    assert summary.skipped == 2
    assert summary.updated == 1
    assert client.calls[0] == "000001"
    assert client.calls[-1] == "000003"
