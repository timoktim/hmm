from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from src.config import project_relative_path, settings
from src.data_pipeline.clean_tushare_snapshot import DEFAULT_REPORT, DEFAULT_SUMMARY_JSON, SNAPSHOT_PROFILE, STAGE_NAMES
from src.data_pipeline.storage import DuckDBStorage
from src.runtime.clean_snapshot_jobs import TERMINAL_STATUSES, has_tushare_token, list_clean_snapshot_jobs, read_job_progress, start_clean_snapshot_job
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


def _running_snapshot_target_paths(jobs: list[dict[str, object]]) -> list[Path]:
    paths: list[Path] = []
    for job in jobs:
        if str(job.get("status") or "").lower() in TERMINAL_STATUSES:
            continue
        raw_target = str(job.get("target_db") or "").strip()
        if not raw_target:
            continue
        try:
            paths.append(project_safe_db_path(raw_target))
        except Exception:
            continue
    return paths


def _render_open_existing(active_path: Path, *, exclude_paths: list[Path] | None = None) -> None:
    st.subheader("打开已有数据库")
    items = list_database_files(exclude_paths=exclude_paths)
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


def _bounded_progress(value: object) -> float:
    try:
        return min(1.0, max(0.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _format_percent(value: object) -> str:
    return f"{_bounded_progress(value) * 100:.1f}%"


def _render_tushare_rate_note() -> None:
    min_interval = max(float(settings.tushare_request_min_interval_seconds), 0.0)
    jitter = max(float(settings.tushare_request_jitter_seconds), 0.0)
    safe_per_minute = 0.0 if min_interval <= 0 else 60.0 / min_interval
    expected_per_minute = 0.0 if min_interval + jitter / 2 <= 0 else 60.0 / (min_interval + jitter / 2)
    st.caption(
        "Tushare 2000 积分限速：当前配置 "
        f"{min_interval:.2f}s/request + 0-{jitter:.2f}s jitter；"
        f"理论上限约 {safe_per_minute:.1f}/min，平均约 {expected_per_minute:.1f}/min，"
        "属于安全余量设计，不会完全打满 200/min。"
    )


def _render_clean_snapshot_job_progress(job: dict[str, object] | None) -> None:
    if not job:
        st.info("暂无后台 Clean Snapshot Build 任务。")
        return
    status = str(job.get("status") or "unknown")
    stage = str(job.get("stage") or "unknown")
    message = str(job.get("message") or "")
    stage_index = int(job.get("stage_index") or 0)
    stage_total = int(job.get("stage_total") or len(STAGE_NAMES))
    overall = _bounded_progress(job.get("overall_progress"))
    stock_progress = _bounded_progress(job.get("stock_progress"))

    st.caption(f"任务：{job.get('job_id')}；状态：{status}；阶段：{stage} ({stage_index}/{stage_total})")
    st.progress(overall)
    st.caption(f"总进度：{_format_percent(overall)}；{message}")
    st.progress(stock_progress)
    stock_label = str(job.get("stock_level_label") or "个股日线批量拉取（按交易日/API，不逐股循环）")
    current = int(job.get("stock_current") or 0)
    total = int(job.get("stock_total") or 0)
    api_name = str(job.get("stock_api") or "")
    trade_date = str(job.get("stock_trade_date") or "")
    st.caption(f"{stock_label}：{_format_percent(stock_progress)} ({current}/{total})；{api_name} {trade_date}".strip())

    rows = [
        ("目标 DB", job.get("target_db") or ""),
        ("源 DB", job.get("source_db") or ""),
        ("PID", job.get("pid") or ""),
        ("创建时间", job.get("created_at") or ""),
        ("更新时间", job.get("updated_at") or ""),
        ("摘要", job.get("summary_json") or ""),
        ("报告", job.get("report") or ""),
        ("日志", job.get("log") or ""),
    ]
    st.dataframe(pd.DataFrame(rows, columns=["项目", "值"]), width="stretch", hide_index=True)
    failures = job.get("failures") or []
    warnings = job.get("warnings") or []
    if failures:
        st.error("；".join(str(item) for item in failures))
    if warnings:
        st.warning("；".join(str(item) for item in warnings))


def _render_clean_snapshot_plan(active_path: Path, *, jobs: list[dict[str, object]] | None = None) -> None:
    st.subheader("Clean Tushare Snapshot Plan")
    _render_tushare_rate_note()
    target_name = st.text_input("目标 DB", value="a_share_hmm_tushare_v1.duckdb", help="必须位于 data/db 下，build 模式不会覆盖当前 active DB。")
    start_date = st.text_input("起始日期", value="20140101")
    end_date = st.text_input("结束日期", value="today")
    copy_assets = st.checkbox("复制用户资产 allowlist", value=True)
    max_trade_dates = st.number_input("max trade dates", min_value=0, value=0, step=1, help="0 表示不限制，仅用于测试或 smoke。")
    max_stocks = st.number_input("max stocks", min_value=0, value=0, step=1, help="0 表示不限制，仅用于测试或 smoke。")
    allow_existing = False
    target_path: Path | None = None
    target_error: str | None = None

    try:
        target_path = project_safe_db_path(target_name)
        target_display = f"data/db/{target_path.relative_to(DEFAULT_DB_DIR).as_posix()}"
        st.caption(f"目标：{target_display}")
        if target_path == active_path:
            st.warning("目标 DB 不能等于当前 active DB。")
        elif target_path.exists():
            st.warning("目标 DB 已存在。正式 build 需要显式 --allow-existing，且只能用于空库或 clean snapshot profile。")
            allow_existing = st.checkbox("允许继续已有 clean snapshot 目标 DB", value=False)
    except Exception as exc:
        target_display = ""
        target_error = str(exc)
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

    st.divider()
    st.subheader("后台 Clean Snapshot Build")
    token_ready = has_tushare_token()
    if not token_ready:
        st.warning("未检测到 ASHARE_HMM_TUSHARE_TOKEN，后台 build 会在 preflight/token 初始化处失败。")
    target_invalid = target_path is None or target_error is not None
    target_is_active = bool(target_path is not None and target_path == active_path)
    target_exists_without_confirm = bool(target_path is not None and target_path.exists() and not allow_existing)
    confirmed = st.checkbox("确认启动后台 build（会写入目标 DB，不会切换 active DB）", value=False)
    disabled = target_invalid or target_is_active or target_exists_without_confirm or not token_ready or not confirmed
    if st.button("启动后台 Clean Snapshot Build", disabled=disabled):
        try:
            job = start_clean_snapshot_job(
                target_db=target_path or target_name,
                source_db=active_path,
                start=start_date,
                end=end_date,
                copy_user_assets=copy_assets,
                max_trade_dates=int(max_trade_dates or 0) or None,
                max_stocks=int(max_stocks or 0) or None,
                allow_existing=allow_existing,
            )
            st.success(f"后台任务已启动：{job.get('job_id')}")
        except Exception as exc:
            st.error(f"启动失败：{exc}")

    jobs = list_clean_snapshot_jobs() if jobs is None else jobs
    if st.button("刷新后台进度"):
        pass
    if jobs:
        labels = [
            f"{item.get('job_id')} | {item.get('status')} | {item.get('updated_at')} | {item.get('target_db')}"
            for item in jobs
        ]
        selected = st.selectbox("后台任务", options=list(range(len(jobs))), format_func=lambda idx: labels[idx])
        _render_clean_snapshot_job_progress(read_job_progress(str(jobs[int(selected)].get("job_id"))))
    else:
        _render_clean_snapshot_job_progress(None)

    st.divider()
    running_targets = _running_snapshot_target_paths(jobs)
    manifests = _recent_clean_snapshot_manifests(list_database_files(exclude_paths=running_targets))
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
    st.caption("查看、创建、打开、归档和校验本地 DuckDB 工作区，并管理 clean Tushare snapshot 的计划与后台 build。")
    clean_snapshot_jobs = list_clean_snapshot_jobs()
    running_snapshot_targets = _running_snapshot_target_paths(clean_snapshot_jobs)

    current_tab, open_tab, create_tab, archive_tab, validate_tab, snapshot_tab = st.tabs(["当前数据库", "打开已有数据库", "新建数据库", "归档当前数据库", "校验当前数据库", "Clean Snapshot Plan"])
    with current_tab:
        _render_current_database(summary)
    with open_tab:
        _render_open_existing(active_path, exclude_paths=running_snapshot_targets)
    with create_tab:
        _render_create_database()
    with archive_tab:
        _render_archive_current(active_path, summary)
    with validate_tab:
        _render_validate_current(active_path, summary)
    with snapshot_tab:
        _render_clean_snapshot_plan(active_path, jobs=clean_snapshot_jobs)
