from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import project_relative_path
from src.data_pipeline.clean_tushare_snapshot import DEFAULT_REPORT, DEFAULT_SUMMARY_JSON, SNAPSHOT_PROFILE, STAGE_NAMES
from src.data_pipeline.storage import DuckDBStorage
from src.runtime.db_workspace import (
    DEFAULT_DB_DIR,
    DatabaseInfo,
    DatabaseSummary,
    archive_database,
    create_database,
    database_summary,
    list_database_files,
    project_safe_db_path,
    resolve_active_db_path,
    set_active_db_path,
    validate_database,
)


def _format_size(size_bytes: int) -> str:
    value = float(size_bytes or 0)
    for unit in ["B", "KB", "MB", "GB"]:
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} GB"


def _schema_status_label(summary: DatabaseSummary) -> str:
    validation = summary.validation
    if not validation.exists:
        return "文件不存在"
    if not validation.suffix_ok:
        return "后缀异常"
    if not validation.can_connect:
        return "无法打开"
    if validation.schema_initialized:
        return "核心 schema 完整"
    return f"缺少 {len(validation.missing_tables)} 张核心表"


def _source_label(source: str) -> str:
    normalized = str(source or "").lower()
    if normalized in {"tushare", "ts"}:
        return "Tushare"
    if normalized in {"mootdx", "tdx"}:
        return "mootdx/TDX fallback"
    return source or "unknown"


def render_sidebar_database_status(active_db_path: Path | None = None) -> None:
    path = active_db_path or resolve_active_db_path()
    summary = database_summary(path)
    st.subheader("当前数据库")
    st.caption(summary.path_display)
    st.caption(f"大小：{_format_size(summary.size_bytes)}")
    st.caption(f"schema：{_schema_status_label(summary)}")
    st.caption(f"股票最新交易日：{summary.latest_stock_trade_date or '暂无'}")
    st.caption(f"板块最新交易日：{summary.latest_sector_trade_date or '暂无'}")
    st.caption(f"数据源：{_source_label(summary.active_source)}")


def _info_frame(items: list[DatabaseInfo]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "当前": "是" if item.active else "",
                "数据库": item.display_path,
                "大小": _format_size(item.size_bytes),
                "修改时间": item.modified_at or "暂无",
                "schema": item.schema_status,
            }
            for item in items
        ]
    )


def _render_current_database(summary: DatabaseSummary) -> None:
    st.subheader("当前数据库")
    cols = st.columns(4)
    cols[0].metric("DB", summary.path_display)
    cols[1].metric("大小", _format_size(summary.size_bytes))
    cols[2].metric("schema", _schema_status_label(summary))
    cols[3].metric("active source", _source_label(summary.active_source))

    detail_rows = [
        ("最后修改时间", summary.modified_at or "暂无"),
        ("是否可读写", "是" if summary.can_read_write else "否"),
        ("最新 stock_ohlcv trade_date", summary.latest_stock_trade_date or "暂无"),
        ("最新 sector_ohlcv trade_date", summary.latest_sector_trade_date or "暂无"),
        ("最新 market_breadth_daily trade_date", summary.latest_breadth_trade_date or "暂无"),
        ("重复 stock_code + trade_date", str(summary.duplicate_stock_trade_date_count)),
        ("data_health 当前失败数", str(summary.data_health_failure_count)),
        ("legacy/fallback source", ", ".join(summary.legacy_sources) if summary.legacy_sources else "未发现"),
    ]
    st.table(pd.DataFrame(detail_rows, columns=["项目", "状态"]))

    left, right = st.columns(2)
    with left:
        st.caption("核心表行数")
        if summary.row_counts:
            st.dataframe(pd.DataFrame(summary.row_counts.items(), columns=["table", "rows"]), width="stretch", hide_index=True)
        else:
            st.info("暂无核心表行数。")
    with right:
        st.caption("stock_ohlcv source 分布")
        if summary.source_distribution:
            st.dataframe(pd.DataFrame(summary.source_distribution.items(), columns=["source", "rows"]), width="stretch", hide_index=True)
        else:
            st.info("暂无 source 分布。")


def _render_open_existing(active_path: Path) -> None:
    st.subheader("打开已有数据库")
    items = list_database_files()
    if not items:
        st.info("data/db 下暂未发现 .duckdb 文件。")
        return
    st.dataframe(_info_frame(items), width="stretch", hide_index=True)
    options = [item.display_path for item in items]
    selected = st.selectbox("选择数据库", options, index=0)
    selected_info = next(item for item in items if item.display_path == selected)
    validation = validate_database(selected_info.path)
    if validation.missing_tables:
        st.caption("schema 检查：" + ", ".join(validation.missing_tables[:8]) + (" ..." if len(validation.missing_tables) > 8 else ""))
    else:
        st.caption("schema 检查：核心表完整")
    disabled = not validation.exists or not validation.suffix_ok or not validation.can_connect
    if st.button("切换到此数据库", disabled=disabled or selected_info.path == active_path):
        set_active_db_path(selected_info.path, session_state=st.session_state)
        st.success(f"已切换到 {selected_info.display_path}")
        st.rerun()


def _render_create_database() -> None:
    st.subheader("新建数据库")
    db_name = st.text_input("DB 名称", value="a_share_hmm_tushare_v1.duckdb")
    st.selectbox("profile", ["tushare_empty"], index=0)
    initialize_schema = st.checkbox("立即初始化 schema", value=True)
    make_active = st.checkbox("创建后设为 active DB", value=True)
    preview = ""
    try:
        preview = project_safe_db_path(db_name).relative_to(DEFAULT_DB_DIR).as_posix()
        st.caption(f"目标：data/db/{preview}")
    except Exception as exc:
        st.warning(str(exc))
    if st.button("新建数据库", disabled=not preview):
        try:
            info = create_database(Path(db_name), label=db_name, initialize_schema=initialize_schema)
            st.success(f"已新建 {info.display_path}")
            if make_active:
                set_active_db_path(info.path, session_state=st.session_state)
                st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _render_archive_current(active_path: Path, summary: DatabaseSummary) -> None:
    st.subheader("归档当前数据库")
    if not summary.exists:
        st.info("当前数据库文件不存在，无法归档。")
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_preview = f"data/db/archive/{active_path.stem}_backup_{timestamp}.duckdb"
    st.table(
        pd.DataFrame(
            [
                ("源数据库", summary.path_display),
                ("默认归档位置", target_preview),
                ("文件大小", _format_size(summary.size_bytes)),
                ("归档方式", "copy，active DB 保持不变"),
            ],
            columns=["项目", "值"],
        )
    )
    confirmed = st.checkbox("确认创建归档副本")
    if st.button("创建归档副本", disabled=not confirmed):
        try:
            info = archive_database(active_path)
            st.success(f"已创建归档副本：{info.display_path}")
        except Exception as exc:
            st.error(str(exc))


def _render_validate_current(active_path: Path, summary: DatabaseSummary) -> None:
    st.subheader("校验当前数据库")
    run_initialize = st.checkbox("执行 schema 初始化幂等检查", value=False, help="仅在你希望允许 init_schema 补齐缺失核心表时开启。")
    if st.button("校验当前数据库"):
        validation = validate_database(active_path, initialize=run_initialize)
        if validation.errors:
            st.error("；".join(validation.errors))
        elif validation.warnings:
            st.warning("；".join(validation.warnings))
        else:
            st.success("校验通过")
        st.table(
            pd.DataFrame(
                [
                    ("文件存在", "是" if validation.exists else "否"),
                    ("后缀 .duckdb", "是" if validation.suffix_ok else "否"),
                    ("可打开", "是" if validation.can_connect else "否"),
                    ("核心 schema 完整", "是" if validation.schema_initialized else "否"),
                    ("缺失核心表", ", ".join(validation.missing_tables) if validation.missing_tables else "无"),
                    ("重复 stock_code + trade_date", str(database_summary(active_path).duplicate_stock_trade_date_count)),
                    ("data_health 当前失败数", str(database_summary(active_path).data_health_failure_count)),
                ],
                columns=["检查项", "结果"],
            )
        )
        if summary.latest_qfq_rebuild:
            st.caption("最新 QFQ rebuild audit")
            st.json(summary.latest_qfq_rebuild)


def _recent_clean_snapshot_manifests(items: list[DatabaseInfo]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for item in items:
        if not item.exists or item.schema_status == "unreadable":
            continue
        try:
            storage = DuckDBStorage(item.path)
            if not validate_database(item.path).can_connect:
                continue
            meta = storage.read_df("SELECT key, value FROM database_workspace_metadata")
        except Exception:
            continue
        if meta.empty:
            continue
        values = dict(zip(meta["key"].astype(str), meta["value"].astype(str), strict=False))
        if values.get("db_profile") != SNAPSHOT_PROFILE:
            continue
        rows.append(
            {
                "数据库": item.display_path,
                "状态": values.get("build_status", "unknown"),
                "起始": values.get("snapshot_start_date", ""),
                "结束": values.get("snapshot_end_date", ""),
                "QFQ": values.get("qfq_policy", ""),
            }
        )
    return pd.DataFrame(rows)


def _render_clean_snapshot_plan(active_path: Path) -> None:
    st.subheader("Clean Tushare Snapshot Plan")
    target_name = st.text_input("目标 DB", value="a_share_hmm_tushare_v1.duckdb", help="必须位于 data/db 下，build 模式不会覆盖当前 active DB。")
    start_date = st.text_input("起始日期", value="20140101")
    end_date = st.text_input("结束日期", value="today")
    copy_assets = st.checkbox("复制用户资产 allowlist", value=True)
    max_trade_dates = st.number_input("max trade dates", min_value=0, value=0, step=1, help="0 表示不限制，仅用于测试或 smoke。")
    max_stocks = st.number_input("max stocks", min_value=0, value=0, step=1, help="0 表示不限制，仅用于测试或 smoke。")

    try:
        target_path = project_safe_db_path(target_name)
        target_display = f"data/db/{target_path.relative_to(DEFAULT_DB_DIR).as_posix()}"
        st.caption(f"目标：{target_display}")
        if target_path == active_path:
            st.warning("目标 DB 不能等于当前 active DB。")
        elif target_path.exists():
            st.warning("目标 DB 已存在。正式 build 需要显式 --allow-existing，且只能用于空库或 clean snapshot profile。")
    except Exception as exc:
        target_display = ""
        st.warning(str(exc))

    command = [
        "python -m src.data_pipeline.clean_tushare_snapshot",
        f"--target-db {target_display or 'data/db/a_share_hmm_tushare_v1.duckdb'}",
        f"--source-db {project_relative_path(active_path)}",
        f"--start {start_date}",
        f"--end {end_date}",
        "--mode plan-only",
    ]
    if not copy_assets:
        command.append("--skip-user-assets")
    if int(max_trade_dates or 0) > 0:
        command.append(f"--max-trade-dates {int(max_trade_dates)}")
    if int(max_stocks or 0) > 0:
        command.append(f"--max-stocks {int(max_stocks)}")
    command.append(f"--summary-json {project_relative_path(DEFAULT_SUMMARY_JSON)}")
    command.append(f"--report {project_relative_path(DEFAULT_REPORT)}")
    st.code(" \\\n  ".join(command), language="bash")

    st.caption("计划阶段")
    st.dataframe(pd.DataFrame({"stage": STAGE_NAMES}), width="stretch", hide_index=True)
    manifests = _recent_clean_snapshot_manifests(list_database_files())
    st.caption("最近 clean snapshot manifest")
    if manifests.empty:
        st.info("暂无 clean Tushare snapshot manifest。")
    else:
        st.dataframe(manifests, width="stretch", hide_index=True)


def render_database_workspace(storage: DuckDBStorage | None = None, active_db_path: Path | None = None) -> None:
    del storage
    active_path = active_db_path or resolve_active_db_path()
    summary = database_summary(active_path)
    st.title("数据库工作区")
    st.caption("查看、创建、打开、归档和校验本地 DuckDB 工作区，并生成 clean Tushare snapshot 的 plan-only CLI 命令。")

    current_tab, open_tab, create_tab, archive_tab, validate_tab, snapshot_tab = st.tabs(["当前数据库", "打开已有数据库", "新建数据库", "归档当前数据库", "校验当前数据库", "Clean Snapshot Plan"])
    with current_tab:
        _render_current_database(summary)
    with open_tab:
        _render_open_existing(active_path)
    with create_tab:
        _render_create_database()
    with archive_tab:
        _render_archive_current(active_path, summary)
    with validate_tab:
        _render_validate_current(active_path, summary)
    with snapshot_tab:
        _render_clean_snapshot_plan(active_path)
