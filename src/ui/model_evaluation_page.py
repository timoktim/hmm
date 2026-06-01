from __future__ import annotations

import plotly.express as px
import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.model_evaluation import evaluate_forward_returns, evaluate_state_stability, evaluate_strategy_comparison
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.model_workflow import render_model_workflow
from src.ui.help_texts import display_value, rename_columns_for_display
from src.ui.run_context import render_run_scope_status
from src.ui.state_screener_page import walk_forward_cache_options_for_scope


def render_model_evaluation(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("模型评估")
    render_model_workflow(storage, universe_id=universe_id, active_step="evaluate")
    scope_options = ["all"]
    if universe_id:
        scope_options.append("universe")
    scope_options.extend(["industry", "concept", "custom"])
    scope = st.selectbox(
        "评估适用范围",
        scope_options,
        format_func=lambda x: {
            "all": "全市场",
            "universe": "当前板块池",
            "industry": "仅行业板块",
            "concept": "仅概念板块",
            "custom": "仅自定义股票池",
        }[x],
    )
    active_universe = universe_id if scope == "universe" else None
    run_id = render_run_scope_status(storage, active_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=active_universe, walk_forward_causal=None)
    if not run_id:
        st.info("当前范围没有可评估的 HMM run。请先训练模型。")
        return

    st.subheader("状态后未来收益分析")
    state_eval_mode = st.radio(
        "状态来源",
        ["in_sample_display", "walk_forward"],
        index=1,
        format_func=lambda x: "样本内状态评估" if x == "in_sample_display" else "因果 walk-forward 状态评估",
        horizontal=True,
        help="样本内状态只能观察模型如何划分状态；walk-forward 状态更适合用于回测和有效性判断。",
    )
    cache_key = None
    if state_eval_mode == "in_sample_display":
        st.warning("当前状态后收益基于样本内状态，只能观察状态区分度，不能作为样本外有效性证据。")
    else:
        caches = walk_forward_cache_options_for_scope(storage, active_universe)
        if caches.empty:
            st.warning("缺少与当前范围匹配的 walk-forward 状态缓存，请先在回测页按当前范围运行因果回测。")
            forward = pd.DataFrame()
        else:
            labels = caches.apply(lambda r: f"{r['cache_key']} | {r['start_date']} 至 {r['end_date']} | {r['created_at']}", axis=1).tolist()
            selected_cache = st.selectbox("walk-forward 缓存", labels)
            cache_key = selected_cache.split(" | ")[0]
            forward = evaluate_forward_returns(storage, run_id, universe_id=active_universe, scope=scope, state_source="walk_forward", cache_key=cache_key)
    if state_eval_mode == "in_sample_display":
        forward = evaluate_forward_returns(storage, run_id, universe_id=active_universe, scope=scope, state_source="in_sample_display")
    if forward.empty:
        warning = str(forward.attrs.get("warning", "") or "")
        if warning:
            st.warning(warning)
        if state_eval_mode == "walk_forward":
            st.warning("当前 walk-forward 缓存没有可评估样本；不会用样本内状态替代。")
        else:
            st.warning("暂无状态后未来收益样本。请检查板块行情和 run 范围是否一致。")
    else:
        display_forward = forward.copy()
        display_forward["state_label"] = display_forward["state_label"].map(display_value)
        st.dataframe(rename_columns_for_display(display_forward), width="stretch")
        fig = px.bar(
            display_forward,
            x="state_label",
            y="mean_return",
            color="horizon_days",
            barmode="group",
            title="不同状态后的平均未来收益",
            labels={"state_label": "状态", "mean_return": "平均收益", "horizon_days": "未来天数"},
        )
        fig.update_layout(yaxis_tickformat=".1%")
        st.plotly_chart(fig, width="stretch")
        st.caption("这里检验的是状态对未来收益分布是否有区分度，不是预测明天涨跌。")

    st.subheader("策略对照分析")
    st.caption("对照策略使用相同回测范围；walk-forward 回测只使用信号日前可见数据。")
    c1, c2, c3 = st.columns(3)
    top_n = c1.number_input("持有板块数量", min_value=1, max_value=20, value=5)
    threshold = c2.slider("趋势上行概率阈值", 0.30, 0.90, 0.55, 0.05)
    transaction_cost = c3.number_input("单边交易成本", min_value=0.0, max_value=0.01, value=0.001, step=0.0005, format="%.4f")
    if st.button("运行策略对照评估"):
        try:
            progress_bar = st.progress(0)
            progress_text = st.empty()
            progress_bar.progress(0.1)
            progress_text.caption("正在运行因果 walk-forward 策略对照...")
            comparison = evaluate_strategy_comparison(
                storage,
                run_id,
                universe_id=active_universe,
                top_n=int(top_n),
                threshold=float(threshold),
                transaction_cost=float(transaction_cost),
            )
            progress_bar.progress(1.0)
            progress_text.caption("策略对照评估完成")
            if comparison.empty:
                st.warning("没有生成对照回测结果。")
            else:
                st.dataframe(rename_columns_for_display(comparison), width="stretch")
        except Exception as exc:
            st.error(f"策略对照评估失败：{exc}")

    st.subheader("状态稳定性分析")
    stability, transitions = evaluate_state_stability(storage, run_id)
    if stability.empty:
        st.warning("暂无状态稳定性数据。")
    else:
        stability_display = stability.copy()
        stability_display["state_label"] = stability_display["state_label"].map(display_value)
        st.dataframe(rename_columns_for_display(stability_display), width="stretch")
        fig_share = px.pie(stability_display, names="state_label", values="state_share", title="状态占比")
        st.plotly_chart(fig_share, width="stretch")
    if not transitions.empty:
        st.markdown("**状态转移矩阵**")
        transitions_display = transitions.copy()
        transitions_display["state_label"] = transitions_display["state_label"].map(display_value)
        st.dataframe(rename_columns_for_display(transitions_display), width="stretch")

    st.subheader("数据质量影响说明")
    st.write(
        "评估结果会受到板块数量、Universe 范围、过期缓存、市场宽度覆盖等级、自定义股票池覆盖率和是否使用因果 walk-forward 的影响。"
        "若可信度摘要出现过期缓存或本地样本宽度提示，建议先去数据中心刷新关键数据。"
    )
