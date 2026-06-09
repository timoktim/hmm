from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
import time
from typing import Any

import pandas as pd
import streamlit as st

from src.config import settings
from src.data_pipeline.market_updater import (
    DEFAULT_MARKET_INDEX_CODES,
    stock_worker_defaults_for_source,
    update_all_a_stock_ohlcv,
    update_all_a_stock_universe,
    update_market_breadth,
    update_market_indices,
)
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import (
    UpdateProgress,
    incremental_update_boards,
    update_boards,
    update_market_benchmark,
    update_stock_histories,
    update_universe_data,
)
from src.ui.components.data_coverage import render_data_coverage_overview
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.operation_result import render_operation_result
from src.ui.help_texts import rename_columns_for_display
from src.utils.dates import today_yyyymmdd


TASK_OPTIONS = [
    "更新 Tushare 股票池",
    "更新 Tushare 全 A 日频行情",
    "更新 Tushare 指数与市场基准",
    "更新全 A 市场宽度",
    "更新 Tushare 行业/本地聚合板块",
    "重试失败任务",
]


@dataclass
class CombinedUpdateResult:
    task: str
    updated: int = 0
    rows: int = 0
    cache_hits: int = 0
    stale_reads: int = 0
    failures: list[str] | None = None
    summaries: list[dict[str, Any]] | None = None
    message: str = ""


ProgressDictCallback = Callable[[dict[str, object]], None]

ALL_A_STAGE_SPANS = {
    "universe": (0.00, 0.05),
    "stock": (0.05, 0.88),
    "breadth": (0.93, 0.07),
    "done": (1.00, 0.00),
}


def _data_source_display_name(source: str | None = None) -> str:
    raw = str(source if source is not None else (settings.market_data_source or settings.default_source or "tushare")).strip()
    normalized = raw.lower()
    if normalized in {"tushare", "ts"}:
        return "Tushare"
    if normalized in {"mootdx", "tdx"}:
        return "mootdx/TDX"
    if normalized in {"akshare", "legacy-akshare"}:
        return "AKShare legacy"
    return raw or "unknown"


def _bounded_ratio(current: object, total: object) -> float:
    try:
        denominator = max(float(total or 0), 1.0)
        return max(0.0, min(float(current or 0) / denominator, 1.0))
    except (TypeError, ValueError):
        return 0.0


def all_a_progress_event(
    phase: str,
    stage: str,
    stage_index: int,
    current: int = 0,
    total: int = 1,
    name: str = "",
    successes: int = 0,
    failures: int = 0,
    cache_hits: int = 0,
    stale_reads: int = 0,
    skipped: int = 0,
    latest_source_trade_date: object | None = None,
    data_source: str | None = None,
) -> dict[str, object]:
    stage_progress = _bounded_ratio(current, total)
    span_start, span_width = ALL_A_STAGE_SPANS.get(phase, (0.0, 0.0))
    overall_progress = max(0.0, min(span_start + span_width * stage_progress, 1.0))
    return {
        "phase": phase,
        "stage": stage,
        "stage_index": stage_index,
        "stage_total": 3,
        "current": int(current),
        "total": int(total or 1),
        "stage_progress": stage_progress,
        "overall_progress": overall_progress,
        "name": name,
        "successes": int(successes or 0),
        "failures": int(failures or 0),
        "cache_hits": int(cache_hits or 0),
        "stale_reads": int(stale_reads or 0),
        "skipped": int(skipped or 0),
        "latest_source_trade_date": latest_source_trade_date,
        "data_source": _data_source_display_name(data_source),
    }


def _format_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "估算中"
    seconds = int(seconds)
    minutes, sec = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}小时{minutes}分"
    if minutes:
        return f"{minutes}分{sec}秒"
    return f"{sec}秒"


def _progress_widgets(data_source_label: str | None = None):
    progress_bar = st.progress(0)
    progress_text = st.empty()
    stats_text = st.empty()
    source_text = _data_source_display_name(data_source_label)
    stage_labels = {
        "board_hist": "板块行情",
        "board_hist_done": "板块行情完成",
        "board_constituents": "成分股",
        "board_constituents_done": "成分股完成",
        "stock_hist": "个股行情",
        "stock_hist_done": "个股行情完成",
        "custom_basket_stock_hist": "自定义股票池个股",
        "custom_basket_done": "自定义股票池指数",
    }

    def on_progress(progress: UpdateProgress) -> None:
        progress_bar.progress(min(progress.current / max(progress.total, 1), 1.0))
        stage = stage_labels.get(progress.stage, progress.stage)
        progress_text.caption(f"数据源：{source_text}；{stage}：{progress.name}（{progress.current}/{progress.total}）")
        stats_text.caption(f"成功 {progress.successes}，失败 {progress.failures}，缓存命中 {progress.cache_hits}，过期缓存 {progress.stale_reads}")

    return progress_bar, progress_text, stats_text, on_progress


def _all_a_progress_widgets(data_source_label: str | None = None) -> ProgressDictCallback:
    st.markdown("**Tushare 全 A 日频数据进度**")
    overall_label = st.empty()
    overall_bar = st.progress(0)
    stage_label = st.empty()
    stage_bar = st.progress(0)
    stats_label = st.empty()
    started_at = time.monotonic()
    widget_source_text = _data_source_display_name(data_source_label)

    def on_progress(payload: dict[str, object]) -> None:
        overall = max(0.0, min(float(payload.get("overall_progress", 0.0) or 0.0), 1.0))
        stage_progress = max(0.0, min(float(payload.get("stage_progress", 0.0) or 0.0), 1.0))
        elapsed = time.monotonic() - started_at
        eta = None if overall <= 0.01 else elapsed * (1.0 - overall) / max(overall, 0.001)
        stage = str(payload.get("stage") or "更新中")
        name = str(payload.get("name") or "")
        current = int(payload.get("current", 0) or 0)
        total = int(payload.get("total", 1) or 1)
        stage_index = int(payload.get("stage_index", 1) or 1)
        stage_total = int(payload.get("stage_total", 3) or 3)
        source_text = str(payload.get("data_source") or widget_source_text)
        overall_bar.progress(overall)
        stage_bar.progress(stage_progress)
        overall_label.caption(f"总进度：{overall:.1%}；数据源：{source_text}；已耗时：{_format_duration(elapsed)}；预计剩余：{_format_duration(eta)}")
        current_text = f"；当前：{name}" if name else ""
        stage_label.caption(f"阶段 {stage_index}/{stage_total}：{stage}；阶段进度：{current}/{total}{current_text}")
        stats_label.caption(
            f"成功 {payload.get('successes', 0)}，失败 {payload.get('failures', 0)}，"
            f"跳过 {payload.get('skipped', 0)}，缓存命中 {payload.get('cache_hits', 0)}，"
            f"过期缓存 {payload.get('stale_reads', 0)}，数据源最新交易日 {payload.get('latest_source_trade_date') or '探测中'}"
        )

    return on_progress


def _dict_summary(summary: Any) -> dict[str, Any]:
    if summary is None:
        return {}
    if hasattr(summary, "__dataclass_fields__"):
        return asdict(summary)
    if isinstance(summary, dict):
        return dict(summary)
    if hasattr(summary, "__dict__"):
        return dict(summary.__dict__)
    return {"result": summary}


def _combine(task: str, summaries: list[Any], message: str = "") -> CombinedUpdateResult:
    updated = 0
    rows = 0
    cache_hits = 0
    stale_reads = 0
    failures: list[str] = []
    details: list[dict[str, Any]] = []
    for summary in summaries:
        data = _dict_summary(summary)
        details.append(data)
        updated += int(data.get("updated", data.get("sectors_updated", 0)) or 0)
        rows += int(data.get("rows", 0) or 0)
        cache_hits += int(data.get("cache_hits", 0) or 0)
        stale_reads += int(data.get("stale_reads", int(bool(data.get("stale", False)))) or 0)
        raw_failures = data.get("failures", data.get("failure", []))
        if isinstance(raw_failures, list):
            failures.extend(str(item) for item in raw_failures if item)
        elif raw_failures:
            failures.append(str(raw_failures))
    return CombinedUpdateResult(
        task=task,
        updated=updated,
        rows=rows,
        cache_hits=cache_hits,
        stale_reads=stale_reads,
        failures=failures,
        summaries=details,
        message=message,
    )


def collect_universe_stock_codes(storage: DuckDBStorage, universe_id: str | None) -> list[str]:
    if not universe_id:
        return []
    items = storage.list_universe_items(universe_id)
    if items.empty:
        return []
    codes: set[str] = set()
    board_ids = items.loc[items["item_type"].isin(["industry", "concept"]), "item_id"].dropna().astype(str).tolist()
    if board_ids:
        placeholders = ",".join(["?"] * len(board_ids))
        cons = storage.read_df(
            f"SELECT DISTINCT stock_code FROM sector_constituents WHERE sector_id IN ({placeholders})",
            board_ids,
        )
        if not cons.empty:
            codes.update(cons["stock_code"].astype(str).str.zfill(6).tolist())
    basket_ids = items.loc[items["item_type"] == "custom_stock_basket", "item_id"].dropna().astype(str).tolist()
    if basket_ids:
        placeholders = ",".join(["?"] * len(basket_ids))
        members = storage.read_df(
            f"SELECT DISTINCT stock_code FROM custom_stock_basket_members WHERE basket_id IN ({placeholders})",
            basket_ids,
        )
        if not members.empty:
            codes.update(members["stock_code"].astype(str).str.zfill(6).tolist())
    return sorted(codes)


def run_all_a_width_pipeline(
    start: str,
    end: str,
    incremental: bool,
    skip_completed: bool,
    lookback_days: int,
    all_a_lookback_days: int,
    max_stocks: int | None,
    workers: int,
    force_refresh: bool,
    storage: DuckDBStorage,
    batch_size: int | None = None,
    batch_sleep_seconds: float | None = None,
    progress_callback: ProgressDictCallback | None = None,
) -> CombinedUpdateResult:
    summaries: list[Any] = []
    if progress_callback:
        progress_callback(all_a_progress_event("universe", "更新 Tushare 股票池", 1, current=0, total=1))
    universe_summary = update_all_a_stock_universe(storage=storage, force_refresh=force_refresh)
    summaries.append(universe_summary)
    if progress_callback:
        progress_callback(
            all_a_progress_event(
                "universe",
                "更新 Tushare 股票池",
                1,
                current=1,
                total=1,
                successes=int(getattr(universe_summary, "updated", 0) or 0),
                failures=len(getattr(universe_summary, "failures", []) or []),
                cache_hits=int(getattr(universe_summary, "cache_hits", 0) or 0),
                stale_reads=int(getattr(universe_summary, "stale_reads", 0) or 0),
            )
        )
        progress_callback(all_a_progress_event("stock", "按交易日批量更新 Tushare 全 A 日线", 2, current=0, total=max_stocks or 1))

    def on_stock_progress(payload: dict[str, object]) -> None:
        if progress_callback:
            progress_callback(
                all_a_progress_event(
                    "stock",
                    "按交易日批量更新 Tushare 全 A 日线",
                    2,
                    current=int(payload.get("current", 0) or 0),
                    total=int(payload.get("total", 1) or 1),
                    name=str(payload.get("name", "") or ""),
                    successes=int(payload.get("successes", 0) or 0),
                    failures=int(payload.get("failures", 0) or 0),
                    cache_hits=int(payload.get("cache_hits", 0) or 0),
                    stale_reads=int(payload.get("stale_reads", 0) or 0),
                    skipped=int(payload.get("skipped", 0) or 0),
                    latest_source_trade_date=payload.get("latest_source_trade_date"),
                )
            )

    stock_summary = update_all_a_stock_ohlcv(
        start,
        end,
        incremental=incremental,
        lookback_days=int(all_a_lookback_days),
        max_stocks=max_stocks,
        workers=int(workers),
        batch_size=batch_size,
        batch_sleep_seconds=batch_sleep_seconds,
        skip_completed=skip_completed,
        force_refresh=force_refresh,
        progress_callback=on_stock_progress,
        storage=storage,
    )
    summaries.append(stock_summary)

    if progress_callback:
        progress_callback(
            all_a_progress_event(
                "stock",
                "按交易日批量更新 Tushare 全 A 日线",
                2,
                current=int(getattr(stock_summary, "seen", 0) or 1),
                total=int(getattr(stock_summary, "seen", 0) or 1),
                successes=int(getattr(stock_summary, "updated", 0) or 0),
                failures=len(getattr(stock_summary, "failures", []) or []),
                cache_hits=int(getattr(stock_summary, "cache_hits", 0) or 0),
                stale_reads=int(getattr(stock_summary, "stale_reads", 0) or 0),
                skipped=int(getattr(stock_summary, "skipped", 0) or 0),
                latest_source_trade_date=getattr(stock_summary, "latest_source_trade_date", None),
            )
        )
        progress_callback(all_a_progress_event("breadth", "计算全 A 市场宽度", 3, current=0, total=1))
    breadth_summary = update_market_breadth(
        start,
        end,
        incremental=incremental,
        lookback_days=int(lookback_days),
        mode="full_market",
        storage=storage,
    )
    summaries.append(breadth_summary)
    if progress_callback:
        progress_callback(
            all_a_progress_event(
                "breadth",
                "计算全 A 市场宽度",
                3,
                current=1,
                total=1,
                successes=int(getattr(breadth_summary, "updated", 0) or 0),
                failures=len(getattr(breadth_summary, "failures", []) or []),
                cache_hits=int(getattr(breadth_summary, "cache_hits", 0) or 0),
                stale_reads=int(getattr(breadth_summary, "stale_reads", 0) or 0),
            )
        )
        progress_callback(all_a_progress_event("done", "Tushare 全 A 日频与宽度更新完成", 3, current=1, total=1))
    return _combine("更新 Tushare 全 A 日频与宽度", summaries)


def retry_failed_tasks(
    storage: DuckDBStorage,
    start: str,
    end: str,
    incremental: bool,
    lookback_days: int,
    workers: int,
    progress_callback: Callable[[UpdateProgress], None] | None = None,
) -> CombinedUpdateResult:
    failures_df = storage.read_df(
        """
        SELECT target_type, board_type, target_name, interface, last_error
        FROM fetch_failures
        ORDER BY last_failure DESC
        """
    )
    if failures_df.empty:
        return CombinedUpdateResult(task="重试失败任务", failures=[], message="暂无失败任务。")

    summaries: list[Any] = []
    unsupported: list[str] = []
    board_failures = failures_df[(failures_df["target_type"] == "sector") & failures_df["interface"].isin(["board_hist", "board_constituents"])]
    updater = incremental_update_boards if incremental else update_boards
    for board_type, group in board_failures.groupby("board_type"):
        names = group["target_name"].dropna().astype(str).drop_duplicates().tolist()
        if not names:
            continue
        kwargs: dict[str, Any] = {
            "include_constituents": bool((group["interface"] == "board_constituents").any()),
            "sector_names": names,
            "limit": None,
            "workers": workers,
            "progress_callback": progress_callback,
            "storage": storage,
        }
        if incremental:
            kwargs["lookback_days"] = lookback_days
        summaries.append(updater(str(board_type), start, end, **kwargs))

    benchmark_failures = failures_df[failures_df["target_type"] == "benchmark"]
    for row in benchmark_failures.itertuples(index=False):
        summaries.append(update_market_benchmark(str(row.target_name), start, end, incremental=incremental, lookback_days=lookback_days, storage=storage))

    handled = pd.concat([board_failures, benchmark_failures], ignore_index=True) if not benchmark_failures.empty else board_failures
    handled_keys = set(zip(handled["target_type"], handled["board_type"], handled["target_name"], handled["interface"], strict=False)) if not handled.empty else set()
    for row in failures_df.itertuples(index=False):
        key = (row.target_type, row.board_type, row.target_name, row.interface)
        if key not in handled_keys:
            unsupported.append(f"{row.target_type}/{row.interface}/{row.target_name}: 暂不支持自动重试")
    result = _combine("重试失败任务", summaries, message=f"已按失败清单重试 {len(failures_df)} 条。")
    result.failures = (result.failures or []) + unsupported
    return result


def render_data_overview(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.subheader("数据覆盖概览")
    if universe_id:
        universe = storage.get_universe(universe_id)
        universe_name = universe.loc[0, "universe_name"] if not universe.empty else universe_id
        st.info(f"当前统计口径：板块池 `{universe_name}`。覆盖率只统计该板块池内的数据，不代表全市场。")
    else:
        st.info("当前统计口径：全市场。覆盖率按全库行业、概念、个股和指数数据统计。")
    st.caption("这里展示数据库中各类数据的覆盖率、最新日期和宽度口径，用来判断下一步该补哪类数据。")
    render_data_coverage_overview(storage, universe_id=universe_id)
    run_id = storage.latest_run_for_current_scope(universe_id)
    with st.expander("当前 HMM run 摘要", expanded=False):
        if not run_id:
            st.info("当前范围暂无 HMM run。模型训练入口已从数据中心主流程移出。")
        else:
            st.dataframe(rename_columns_for_display(storage.get_model_run(run_id)), width="stretch")


def _board_type_selection() -> list[str]:
    label = st.selectbox("板块类型", ["行业 + 概念", "仅行业", "仅概念"], index=0)
    if label == "仅行业":
        return ["industry"]
    if label == "仅概念":
        return ["concept"]
    return ["industry", "concept"]


def render_data_update_tasks(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
    start = c1.text_input("起始日期", value="20200101")
    end = c2.text_input("结束日期", value=today_yyyymmdd())
    update_mode = c3.selectbox("更新模式", ["incremental", "full"], index=0, format_func=lambda x: "增量更新" if x == "incremental" else "全量回填")
    lookback_days = c4.number_input("回补天数", min_value=0, max_value=120, value=10, help="增量更新时向前回补的自然日数，用于覆盖最近几天可能修订的数据。")
    selected_source = str(settings.market_data_source or settings.default_source or "tushare").strip().lower()
    is_tushare_source = selected_source in {"tushare", "ts"}

    with st.expander("高级参数", expanded=False):
        a1, a2, a3 = st.columns(3)
        board_workers = a1.number_input("板块并发数", min_value=1, max_value=3, value=1, help="只用于板块行情抓取。并发过高可能导致接口失败。")
        stock_workers = 1
        source_display = _data_source_display_name(selected_source)
        if is_tushare_source:
            token_configured = bool(str(settings.tushare_token or "").strip())
            a2.metric("Tushare token", "已配置" if token_configured else "未配置")
            a3.metric("主数据源", source_display)
            st.caption(
                f"2000 积分默认按 {int(settings.tushare_rate_limit_per_minute)} 次/分钟设计，"
                f"当前最小请求间隔 {float(settings.tushare_request_min_interval_seconds):.2f}s；"
                f"全 A 日频按交易日批量拉取，stock_ohlcv 写入前复权兼容 OHLCV。"
            )
            if not token_configured:
                st.warning("未配置 Tushare token。请设置环境变量 ASHARE_HMM_TUSHARE_TOKEN；页面不会显示 token 值。")
        else:
            stock_worker_default, stock_worker_max = stock_worker_defaults_for_source()
            stock_workers = a2.number_input(
                "个股并发数",
                min_value=1,
                max_value=int(stock_worker_max),
                value=int(stock_worker_default),
                help="仅用于 legacy/mootdx 兼容路径。Tushare 主链路按交易日串行限速，不使用个股并发。",
            )
            a3.metric("主数据源", source_display)
        include_constituents = a3.checkbox("同时更新成分股", value=is_tushare_source, help="Tushare 行业本地聚合需要先写入行业成分股；legacy 源开启后总耗时会明显增加。")
        b1, b2, b3 = st.columns(3)
        test_limit_enabled = b1.checkbox("启用测试数量限制", value=False, help="仅用于小范围试跑。关闭后更新全部目标。")
        test_limit = b2.number_input("测试限制数量", min_value=1, max_value=6000, value=30, disabled=not test_limit_enabled)
        force_refresh = b3.checkbox("强制刷新", value=False, help="尽量绕过缓存重新请求。日常增量更新通常不需要开启。")
        tdx_batch_size: int | None = None
        tdx_batch_sleep: float | None = None
        if not is_tushare_source:
            d1, d2 = st.columns(2)
            tdx_batch_size = int(d1.number_input("TDX 批大小", min_value=10, max_value=300, value=int(settings.tdx_batch_size), step=10, help="仅用于 legacy/mootdx 全 A 兼容路径。"))
            tdx_batch_sleep = float(d2.number_input("批次休眠秒数", min_value=0.0, max_value=30.0, value=float(settings.tdx_batch_sleep_seconds), step=0.5, help="仅用于 legacy/mootdx 批次之间暂停。"))

    task = st.radio("选择更新任务", TASK_OPTIONS, horizontal=False)
    board_types: list[str] = ["industry"]
    all_a_lookback = 60
    all_a_skip_completed = True
    if task == "更新 Tushare 股票池":
        st.info("从 Tushare stock_basic 更新全 A 股票基础列表；不触发 AKShare、同花顺或东方财富。")
    elif task == "更新 Tushare 全 A 日频行情":
        st.info("按交易日批量调用 Tushare daily、adj_factor 和可选 daily_basic，写入前复权兼容 stock_ohlcv。")
        c5, c6 = st.columns(2)
        all_a_lookback = c5.number_input("Tushare 日频回补天数", min_value=10, max_value=180, value=60)
        all_a_skip_completed = c6.checkbox(
            "跳过已完成交易日",
            value=True,
            help="按本地 trade_date 覆盖情况跳过已完整写入的交易日，不再逐股探测最新日期。",
        )
    elif task == "更新 Tushare 指数与市场基准":
        st.info("使用 Tushare index_daily 更新主要大盘指数，并同步沪深300与中证全指市场基准。")
    elif task == "更新全 A 市场宽度":
        st.info("基于本地 Tushare 确认日频 stock_ohlcv 计算全 A 市场宽度；不联网抓取旧网页源。")
    elif task == "更新 Tushare 行业/本地聚合板块":
        board_types = ["industry"]
        st.info("默认只更新 Tushare 申万行业：先取行业成分，再用本地 Tushare 个股 OHLCV 聚合行业行情。概念板块为 legacy/unsupported，不静默回退网页源。")
    else:
        failures_count = storage.read_df("SELECT count(*) AS n FROM fetch_failures")
        n = 0 if failures_count.empty else int(failures_count.loc[0, "n"] or 0)
        if n == 0:
            st.info("暂无失败任务。")
        else:
            st.warning(f"将只重试失败清单中的 {n} 条任务，不会抓取“前 10 个板块”。")

    progress_area = st.container()
    if st.button("开始更新", type="primary"):
        if task in {"更新 Tushare 全 A 日频行情"}:
            progress_bar = progress_text = stats_text = None
            on_progress = None
        else:
            progress_bar, progress_text, stats_text, on_progress = _progress_widgets(source_display)
        limit = int(test_limit) if test_limit_enabled else None
        incremental = update_mode == "incremental"
        result: Any
        with progress_area:
            try:
                if task == "更新 Tushare 股票池":
                    result = update_all_a_stock_universe(storage=storage, force_refresh=force_refresh)
                elif task == "更新 Tushare 行业/本地聚合板块":
                    updater = incremental_update_boards if incremental else update_boards
                    summaries = []
                    for board_type in board_types:
                        kwargs: dict[str, Any] = {
                            "limit": limit,
                            "include_constituents": include_constituents,
                            "workers": int(board_workers),
                            "progress_callback": on_progress,
                            "storage": storage,
                        }
                        if incremental:
                            kwargs["lookback_days"] = int(lookback_days)
                        summaries.append(updater(board_type, start, end, **kwargs))
                    result = _combine(task, summaries)
                elif task == "更新 Tushare 全 A 日频行情":
                    result = update_all_a_stock_ohlcv(
                        start,
                        end,
                        incremental=incremental,
                        lookback_days=int(all_a_lookback),
                        max_stocks=limit,
                        workers=int(stock_workers),
                        batch_size=tdx_batch_size,
                        batch_sleep_seconds=tdx_batch_sleep,
                        skip_completed=bool(all_a_skip_completed),
                        force_refresh=force_refresh,
                        progress_callback=_all_a_progress_widgets(source_display),
                        storage=storage,
                    )
                elif task == "更新 Tushare 指数与市场基准":
                    summaries = [
                        update_market_indices(start, end, index_codes=DEFAULT_MARKET_INDEX_CODES, incremental=incremental, lookback_days=int(lookback_days), storage=storage),
                        update_market_benchmark("hs300", start, end, incremental=incremental, lookback_days=int(lookback_days), storage=storage),
                        update_market_benchmark("csi_all", start, end, incremental=incremental, lookback_days=int(lookback_days), storage=storage),
                    ]
                    result = _combine(task, summaries)
                elif task == "更新全 A 市场宽度":
                    result = update_market_breadth(start, end, incremental=incremental, lookback_days=int(lookback_days), mode="full_market", storage=storage)
                else:
                    result = retry_failed_tasks(
                        storage,
                        start,
                        end,
                        incremental=incremental,
                        lookback_days=int(lookback_days),
                        workers=int(board_workers),
                        progress_callback=on_progress,
                    )
                if progress_bar is not None and progress_text is not None:
                    progress_bar.progress(1.0)
                    progress_text.caption(f"数据源：{source_display}；更新任务完成")
                if stats_text is not None and hasattr(result, "failures"):
                    failures = getattr(result, "failures") or []
                    stats_text.caption(f"失败 {len(failures)}")
                render_operation_result(result, f"{task}完成")
            except Exception as exc:
                st.error(f"更新失败：{exc}")


def render_update_logs(storage: DuckDBStorage) -> None:
    st.subheader("最近更新摘要")
    latest = storage.read_df(
        """
        SELECT interface, last_network_success, last_network_failure, last_cache_hit,
               cache_hits, stale_reads, last_error
        FROM data_health
        ORDER BY COALESCE(last_network_success, last_cache_hit, last_network_failure) DESC NULLS LAST
        LIMIT 30
        """
    )
    if latest.empty:
        st.info("暂无更新日志。")
    else:
        st.dataframe(rename_columns_for_display(latest), width="stretch")

    st.subheader("失败任务")
    failures = storage.read_df(
        """
        SELECT target_type, board_type, interface, count(*) AS failure_count,
               max(last_failure) AS latest_failure
        FROM fetch_failures
        GROUP BY target_type, board_type, interface
        ORDER BY latest_failure DESC NULLS LAST
        """
    )
    if failures.empty:
        st.success("暂无失败任务。")
    else:
        st.warning("如需重试，请切换到“数据更新”tab，选择“重试失败任务”。")
        st.dataframe(rename_columns_for_display(failures), width="stretch")
        with st.expander("查看失败明细", expanded=False):
            detail = storage.read_df("SELECT * FROM fetch_failures ORDER BY last_failure DESC")
            st.dataframe(rename_columns_for_display(detail), width="stretch")

    with st.expander("详细接口健康表", expanded=False):
        health = storage.read_df("SELECT * FROM data_health ORDER BY interface")
        if health.empty:
            st.info("暂无接口健康记录。")
        else:
            st.dataframe(rename_columns_for_display(health), width="stretch")

    with st.expander("Tushare 前复权重基准记录", expanded=False):
        st.caption("当 Tushare adj_factor 历史修订或除权除息后需要统一前复权基准时，先通过 CLI 执行 detect-only 或 dry-run，再按 affected stocks 定向重建。")
        qfq_runs = storage.read_df(
            """
            SELECT rebuild_run_id, trigger_reason, start_date, end_date,
                   affected_stock_count, affected_row_count, status, created_at, completed_at
            FROM qfq_rebuild_runs
            ORDER BY created_at DESC
            LIMIT 20
            """
        )
        if qfq_runs.empty:
            st.info("暂无前复权重基准任务记录。")
        else:
            st.dataframe(rename_columns_for_display(qfq_runs), width="stretch")


def render_data_center(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("数据中心")
    st.caption("数据中心现在只负责数据覆盖、更新任务和更新日志；模型训练已从主流程中移出。")
    run_id = storage.latest_run_for_current_scope(universe_id)
    render_data_status_bar(storage, run_id=run_id, universe_id=universe_id)

    overview_tab, update_tab, log_tab = st.tabs(["数据概览", "数据更新", "更新日志"])
    with overview_tab:
        render_data_overview(storage, universe_id=universe_id)
    with update_tab:
        render_data_update_tasks(storage, universe_id=universe_id)
    with log_tab:
        render_update_logs(storage)
