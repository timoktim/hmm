from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.analysis.sector_cycles import build_state_segments, load_sector_states_for_analysis, screen_state_transitions
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import universe_sector_ids
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.formatters import format_probability_columns
from src.ui.help_texts import display_state_label, rename_columns_for_display
from src.ui.run_context import render_run_scope_status
from src.ui.state_colors import SECTOR_STATE_COLORS


TEMPLATES = {
    "刚从中性震荡进入趋势上行": {"from_state": "Neutral", "to_state": "TrendUp", "prob_trend_up_min": 0.55, "prob_risk_off_max": 0.30},
    "从趋势上行转为中性震荡": {"from_state": "TrendUp", "to_state": "Neutral", "prob_trend_up_min": 0.0, "prob_risk_off_max": 1.0},
    "从趋势上行转为风险回避": {"from_state": "TrendUp", "to_state": "RiskOff", "prob_trend_up_min": 0.0, "prob_risk_off_max": 1.0},
    "从风险回避修复到中性震荡": {"from_state": "RiskOff", "to_state": "Neutral", "prob_trend_up_min": 0.0, "prob_risk_off_max": 0.60},
    "自定义": {},
}


def walk_forward_cache_options_for_scope(storage: DuckDBStorage, universe_id: str | None = None) -> pd.DataFrame:
    scope_filter = "WHERE (r.universe_id IS NULL OR r.universe_id IN ('', 'all'))"
    params: list[object] = []
    if universe_id:
        scope_filter = "WHERE r.universe_id = ?"
        params.append(universe_id)
    return storage.read_df(
        f"""
        SELECT r.cache_key, r.start_date, r.end_date, r.created_at, r.signal_count, r.row_count,
               r.universe_id, r.scope_type,
               count(DISTINCT s.sector_id) AS cached_sectors,
               min(s.trade_date) AS min_state_date,
               max(s.trade_date) AS max_state_date
        FROM walk_forward_cache_runs r
        LEFT JOIN walk_forward_state_cache s USING(cache_key)
        {scope_filter}
        GROUP BY r.cache_key, r.start_date, r.end_date, r.created_at, r.signal_count,
                 r.row_count, r.universe_id, r.scope_type
        ORDER BY r.created_at DESC
        """,
        params,
    )


def render_state_screener(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("状态筛选器")
    st.caption("状态切换筛选用于发现值得研究的板块，不等于操作依据。")
    scope_options = ["all"]
    if universe_id:
        scope_options.append("universe")
    scope_options.extend(["industry", "concept", "custom"])
    scope = st.selectbox(
        "板块范围",
        scope_options,
        format_func=lambda x: {"all": "全市场", "universe": "当前板块池", "industry": "仅行业", "concept": "仅概念", "custom": "仅自定义股票池"}[x],
        help="用于限制状态切换筛选的观察范围。",
        key="state_screener_scope",
    )
    active_universe = universe_id if scope == "universe" else None
    run_id = render_run_scope_status(storage, active_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=active_universe)
    if not run_id:
        return

    source = st.radio(
        "状态来源",
        ["in_sample_display", "walk_forward"],
        index=1,
        format_func=lambda x: "样本内展示状态" if x == "in_sample_display" else "因果 walk-forward 状态",
        horizontal=True,
        help="样本内状态适合观察模型如何划分状态；walk-forward 状态更适合用于回测和有效性判断。",
        key="state_screener_source",
    )
    cache_key = None
    if source == "in_sample_display":
        st.warning("样本内状态适合观察模型如何划分状态，不等同于历史可执行依据。")
    else:
        st.info("因果 walk-forward 状态更适合用于回测和有效性判断。")
        caches = walk_forward_cache_options_for_scope(storage, active_universe)
        if caches.empty:
            st.warning("缺少与当前范围匹配的 walk-forward 状态缓存，请先在回测页按当前范围运行因果回测。")
            return
        labels = caches.apply(
            lambda r: (
                f"{r['cache_key']} | 覆盖 {int(r['cached_sectors'] or 0)} 个板块 | "
                f"范围 {'当前板块池' if pd.notna(r.get('universe_id')) and str(r.get('universe_id')) not in {'', 'all'} else '全市场'} | "
                f"状态 {r['min_state_date']} 至 {r['max_state_date']} | 创建 {r['created_at']}"
            ),
            axis=1,
        ).tolist()
        default_cache_index = 0
        if scope == "all" and "cached_sectors" in caches.columns:
            default_cache_index = int(pd.to_numeric(caches["cached_sectors"], errors="coerce").fillna(0).idxmax())
        selected_cache = st.selectbox("walk-forward 缓存", labels, index=default_cache_index)
        cache_key = selected_cache.split(" | ")[0]

    st.subheader("筛选条件")
    template_name = st.selectbox("筛选模板", list(TEMPLATES.keys()), help="预设常见状态切换场景，可切到自定义后手动调整。", key="state_screener_template")
    template = TEMPLATES[template_name]
    is_custom_template = template_name == "自定义"
    c1, c2 = st.columns(2)
    state_choices = ["任意", "TrendUp", "Neutral", "RiskOff"]
    from_state = c1.selectbox(
        "起始状态",
        state_choices,
        index=state_choices.index(template.get("from_state", "Neutral") if template_name != "自定义" else "任意"),
        format_func=lambda x: "任意" if x == "任意" else display_state_label(x),
        disabled=not is_custom_template,
        key=f"state_screener_from_{template_name}",
    )
    to_state = c2.selectbox(
        "目标状态",
        state_choices,
        index=state_choices.index(template.get("to_state", "TrendUp") if template_name != "自定义" else "TrendUp"),
        format_func=lambda x: "任意" if x == "任意" else display_state_label(x),
        disabled=not is_custom_template,
        key=f"state_screener_to_{template_name}",
    )
    c5, c6, c7 = st.columns(3)
    prob_trend_min = c5.slider("趋势上行概率下限", 0.0, 1.0, float(template.get("prob_trend_up_min", 0.55)), 0.05)
    prob_risk_max = c6.slider("风险回避概率上限", 0.0, 1.0, float(template.get("prob_risk_off_max", 0.30)), 0.05)
    only_current = c7.checkbox("只看当前仍处于目标状态", value=True)

    states = load_sector_states_for_analysis(storage, run_id, universe_id=active_universe, source=source, cache_key=cache_key)
    if states.empty:
        st.warning("当前状态来源没有可筛选数据。")
        return
    if scope == "universe" and active_universe:
        expected_scope_count = len(universe_sector_ids(storage, active_universe, include_custom_baskets=True))
    elif scope in {"industry", "concept"}:
        expected_df = storage.read_df("SELECT count(DISTINCT sector_id) AS n FROM sector_meta WHERE sector_type = ?", [scope])
        expected_scope_count = 0 if expected_df.empty else int(expected_df.loc[0, "n"] or 0)
    elif scope == "custom":
        expected_df = storage.read_df("SELECT count(DISTINCT basket_id) AS n FROM custom_stock_basket")
        expected_scope_count = 0 if expected_df.empty else int(expected_df.loc[0, "n"] or 0)
    else:
        expected_df = storage.read_df("SELECT count(DISTINCT sector_id) AS n FROM sector_meta")
        expected_scope_count = 0 if expected_df.empty else int(expected_df.loc[0, "n"] or 0)
    actual_state_count = int(states["sector_id"].nunique())
    if source == "walk_forward" and expected_scope_count and actual_state_count < expected_scope_count:
        st.warning(
            f"当前 walk-forward 缓存只覆盖 {actual_state_count}/{expected_scope_count} 个板块。"
            "这不是完整全市场因果结果；若要全市场因果筛选，请先在回测页生成覆盖全市场的 walk-forward 状态缓存。"
        )
    segments = build_state_segments(states)
    latest_states = states.sort_values(["sector_id", "trade_date"]).groupby("sector_id", as_index=False).tail(1)
    filters = {
        "from_state": from_state,
        "to_state": to_state,
        "current_segment_max_days": None,
        "min_previous_segment_days": None,
        "prob_trend_up_min": float(prob_trend_min),
        "prob_risk_off_max": float(prob_risk_max),
        "only_current_state": bool(only_current),
        "sector_type": scope if scope in {"industry", "concept", "custom"} else "all",
        "universe_id": active_universe,
        "state_source": source,
        "storage": storage,
        "run_id": run_id,
    }
    result = screen_state_transitions(segments, latest_states, filters)
    counted_segments = segments.copy()
    if only_current and not counted_segments.empty:
        latest_segment = counted_segments.groupby("sector_id")["segment_id"].transform("max")
        counted_segments = counted_segments[counted_segments["segment_id"].eq(latest_segment)]
    transition_candidates = counted_segments.copy()
    if from_state != "任意":
        transition_candidates = transition_candidates[transition_candidates["prev_state_label"].astype(str).eq(from_state)]
    if to_state != "任意":
        transition_candidates = transition_candidates[transition_candidates["state_label"].astype(str).eq(to_state)]
    stat_cols = st.columns(4)
    stat_cols[0].metric("当前状态数据板块数", int(latest_states["sector_id"].nunique()))
    stat_cols[1].metric("参与筛选状态段", int(len(counted_segments)))
    stat_cols[2].metric("状态切换命中", int(len(transition_candidates)))
    stat_cols[3].metric("最终入选", int(len(result)))
    st.caption(
        f"当前筛选口径：{dict(all='全市场', universe='当前板块池', industry='仅行业', concept='仅概念', custom='仅自定义股票池').get(scope, scope)}；"
        f"状态来源：{'样本内展示' if source == 'in_sample_display' else '因果 walk-forward'}；"
        f"状态数据覆盖：{actual_state_count}/{expected_scope_count or actual_state_count}；"
        f"状态切换：{display_state_label(from_state) if from_state != '任意' else '任意'} -> {display_state_label(to_state) if to_state != '任意' else '任意'}；"
        f"run：{run_id}"
    )
    if active_universe:
        st.caption("当前结果只来自所选板块池。若想查看所有行业和概念，请把“板块范围”切换为“全市场”。")
    elif scope == "all":
        st.caption("当前结果来自全市场板块。若只想看自选范围，请把“板块范围”切换为“当前板块池”。")
    if result.empty:
        st.info("没有符合条件的板块。可以放宽概率阈值，或关闭“只看当前仍处于目标状态”查看历史切换。")
        return
    display = format_probability_columns(result, ["prob_trend_up", "prob_neutral", "prob_risk_off"])
    preview_names = display["sector_name"].fillna(display["sector_id"]).astype(str).head(60).tolist()
    st.caption(f"命中板块预览（共 {len(display)} 个）：{'、'.join(preview_names)}")
    st.table(rename_columns_for_display(display))
    labels = result.apply(lambda r: f"{r.get('sector_name') or r['sector_id']} | {r['sector_id']}", axis=1).tolist()
    selected_label = st.selectbox("选择要研究的板块", labels)
    selected_sector_id = selected_label.split(" | ")[-1]
    if st.button("研究该板块"):
        st.session_state["selected_sector_id_for_detail"] = selected_sector_id
        st.success("已设为当前研究板块。请切换到“板块详情”查看完整周期研究。")

    selected_segments = segments[segments["sector_id"].astype(str).eq(selected_sector_id)].copy()
    if not selected_segments.empty:
        st.markdown("**简版周期研究图**")
        selected_segments["状态"] = selected_segments["state_label"].map(display_state_label)
        color_map = {display_state_label(k): v for k, v in SECTOR_STATE_COLORS.items()}
        fig = px.timeline(selected_segments, x_start="start_date", x_end="end_date", y="sector_id", color="状态", color_discrete_map=color_map, title="状态周期时间轴")
        fig.update_yaxes(title="")
        st.plotly_chart(fig, width="stretch")
