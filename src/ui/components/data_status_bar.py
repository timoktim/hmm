from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.ui.components.data_trust_card import build_data_trust_summary, render_data_trust_card
from src.ui.components.status_display import StatusItem, render_status_grid
from src.ui.help_texts import display_value


@dataclass
class DataStatusBarSummary:
    level: str
    status_label: str
    message: str
    items: tuple[StatusItem, ...]


def build_data_status_bar_summary(
    storage: DuckDBStorage,
    run_id: str | None = None,
    universe_id: str | None = None,
    walk_forward_causal: bool | None = None,
) -> DataStatusBarSummary:
    trust = build_data_trust_summary(storage, run_id=run_id, universe_id=universe_id, walk_forward_causal=walk_forward_causal)
    breadth = storage.read_df(
        """
        SELECT coverage_level, breadth_mode, coverage_ratio, effective_count
        FROM market_breadth_daily
        WHERE breadth_mode IN ('full_market', 'local_sample')
        ORDER BY
          trade_date DESC,
          CASE WHEN breadth_mode = 'full_market' THEN 0 ELSE 1 END,
          fetched_at DESC NULLS LAST
        LIMIT 1
        """
    )
    breadth_mode = "无"
    breadth_level = trust.market_width_level
    if not breadth.empty:
        row = breadth.iloc[0]
        breadth_mode = "全 A 市场" if str(row.get("breadth_mode")) == "full_market" else "本地样本"
        breadth_level = str(row.get("coverage_level") or "insufficient")

    run = storage.get_model_run(run_id) if run_id else pd.DataFrame()
    run_scope = trust.run_scope
    feature_scope = trust.feature_scope
    if not run.empty:
        row = run.iloc[0]
        run_scope = display_value(row.get("scope_type") or "all")
        feature_scope = str(row.get("feature_scope_id") or "all")

    market_run = storage.read_df("SELECT metrics_json FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")
    market_uses_breadth = "无大盘模型"
    if not market_run.empty:
        metrics = json.loads(market_run.loc[0, "metrics_json"])
        market_uses_breadth = "是" if metrics.get("used_breadth") else "否"

    problems: list[str] = []
    warnings: list[str] = []
    if run_id is None:
        problems.append("缺少当前 HMM run")
    if trust.stale_reads >= 10:
        problems.append(f"当前过期缓存接口 {trust.stale_reads}")
    elif trust.stale_reads > 0:
        warnings.append(f"当前过期缓存接口 {trust.stale_reads}")
    if breadth_level not in {"full_market", "无宽度数据"}:
        warnings.append("宽度不是全市场")
    if trust.market_regime_uses_breadth == "无大盘模型":
        warnings.append("缺少大盘模型")

    if problems:
        level = "red"
        status_label = "不完整"
    elif warnings:
        level = "yellow"
        status_label = "需检查"
    else:
        level = "green"
        status_label = "正常"

    message = (
        f"数据状态：{status_label} | 最近网络成功：{trust.last_network_success} | "
        f"当前 stale 接口：{trust.stale_reads} | 历史 stale 次数：{trust.historical_stale_reads} | run 范围：{run_scope} | "
        f"feature scope：{feature_scope} | 宽度：{breadth_mode}/{display_value(breadth_level)} | "
        f"大盘模型用宽度：{market_uses_breadth}"
    )
    if problems:
        message += " | 问题：" + "、".join(problems)
    elif warnings:
        message += " | 提示：" + "、".join(warnings)

    status_tone = {"green": "green", "yellow": "yellow", "red": "red"}[level]
    items = [
        StatusItem("数据状态", status_label, status_tone),
        StatusItem("最近网络成功", trust.last_network_success, "blue"),
        StatusItem("当前 stale 接口", trust.stale_reads, "green" if trust.stale_reads == 0 else status_tone),
        StatusItem("历史 stale 次数", trust.historical_stale_reads, "neutral"),
        StatusItem("run 范围", run_scope, "neutral"),
        StatusItem("feature scope", feature_scope, "neutral"),
        StatusItem("宽度", f"{breadth_mode}/{display_value(breadth_level)}", "yellow" if breadth_level not in {"full_market", "无宽度数据"} else "green"),
        StatusItem("大盘模型用宽度", market_uses_breadth, "green" if market_uses_breadth == "是" else "yellow"),
    ]
    if problems:
        items.append(StatusItem("问题", "、".join(problems), "red"))
    elif warnings:
        items.append(StatusItem("提示", "、".join(warnings), "yellow"))
    return DataStatusBarSummary(level=level, status_label=status_label, message=message, items=tuple(items))


def render_data_status_bar(
    storage: DuckDBStorage,
    run_id: str | None = None,
    universe_id: str | None = None,
    walk_forward_causal: bool | None = None,
) -> None:
    summary = build_data_status_bar_summary(storage, run_id=run_id, universe_id=universe_id, walk_forward_causal=walk_forward_causal)
    if summary.level == "green":
        st.success(f"数据状态：{summary.status_label}")
    elif summary.level == "yellow":
        st.warning(f"数据状态：{summary.status_label}")
    else:
        st.error(f"数据状态：{summary.status_label}")
    render_status_grid(summary.items, dense=True)
    with st.expander("查看数据状态详情", expanded=False):
        render_data_trust_card(storage, run_id=run_id, universe_id=universe_id, walk_forward_causal=walk_forward_causal)
