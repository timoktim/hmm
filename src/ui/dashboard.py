from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.models.market_hmm import latest_market_regime
from src.models.inference import latest_causal_sector_states, latest_in_sample_sector_states, recent_causal_switches
from src.scoring.market_filter import market_regime_risk_message
from src.scoring.sector_ranker import rank_sectors
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.data_trust_card import build_data_trust_summary
from src.ui.formatters import format_probability_columns
from src.ui.help_texts import display_state_label, rename_columns_for_display
from src.ui.run_context import render_run_scope_status


SUMMARY_SECTIONS = ["当前市场环境", "候选板块", "结果可信度"]


def _universe_name(storage: DuckDBStorage, universe_id: str | None) -> str:
    if not universe_id:
        return "全市场"
    df = storage.get_universe(universe_id)
    return "全市场" if df.empty else str(df.loc[0, "universe_name"])


def _causal_cache_options(storage: DuckDBStorage, universe_id: str | None) -> pd.DataFrame:
    if universe_id:
        return storage.read_df(
            """
            SELECT cache_key, start_date, end_date, created_at, signal_count, row_count, universe_id,
                   feature_version, feature_scope_id
            FROM walk_forward_cache_runs
            WHERE universe_id = ?
              AND row_count > 0
            ORDER BY created_at DESC
            """,
            [universe_id],
        )
    return storage.read_df(
        """
        SELECT cache_key, start_date, end_date, created_at, signal_count, row_count, universe_id,
               feature_version, feature_scope_id
        FROM walk_forward_cache_runs
        WHERE (universe_id IS NULL OR universe_id IN ('', 'all'))
          AND row_count > 0
        ORDER BY created_at DESC
        """
    )


def render_dashboard(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("A股板块 HMM 状态分析器")
    st.caption(f"当前板块池：{_universe_name(storage, universe_id)}")
    use_universe = False
    if universe_id:
        use_universe = st.checkbox("只显示当前板块池", value=True, key="dashboard_use_universe")
    active_universe = universe_id if use_universe else None
    run_id = render_run_scope_status(storage, active_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=active_universe)

    st.subheader(SUMMARY_SECTIONS[0])
    market = latest_market_regime(storage)
    market_state = None if market.empty else str(market.loc[0, "state_label"])
    if market_state:
        st.info(market_regime_risk_message(market_state))
    else:
        st.caption("尚未训练大盘 HMM；总览不会显示大盘风险提示。")
    cache_key = None
    caches = _causal_cache_options(storage, active_universe)
    if caches.empty:
        st.warning("暂无因果 walk-forward 状态。总览不会使用训练样本内状态作为默认排行榜；请先在回测页运行因果 walk-forward 回测生成状态缓存。")
    else:
        cache_labels = caches.apply(
            lambda r: f"{r['cache_key']} | {r['start_date']} 至 {r['end_date']} | 行数 {int(r['row_count'] or 0)} | {r['created_at']}",
            axis=1,
        ).tolist()
        selected_cache = st.selectbox("因果状态缓存", cache_labels, help="总览排行榜只使用选中的 walk-forward 因果状态缓存。")
        cache_key = selected_cache.split(" | ")[0]
    latest_states = latest_causal_sector_states(storage, cache_key=cache_key, universe_id=active_universe) if cache_key else pd.DataFrame()
    ranked = rank_sectors(latest_states)

    st.subheader(SUMMARY_SECTIONS[2])
    health = storage.read_df("SELECT * FROM data_health ORDER BY interface")
    c1, c2, c3, c4 = st.columns(4)
    meta_count = storage.read_df("SELECT sector_type, count(*) AS n FROM sector_meta GROUP BY sector_type")
    c1.metric("行业板块", int(meta_count.query("sector_type == 'industry'")["n"].sum()) if not meta_count.empty else 0)
    c2.metric("概念板块", int(meta_count.query("sector_type == 'concept'")["n"].sum()) if not meta_count.empty else 0)
    c3.metric("当前模型", run_id or "无")
    if health.empty:
        health_label = "待更新"
    else:
        health_label = "正常" if health["last_error"].fillna("").eq("").all() else "需检查"
    c4.metric("数据接口", health_label)

    if not health.empty:
        trust = build_data_trust_summary(storage, run_id=run_id, universe_id=active_universe)
        if trust.stale_reads > 0:
            st.error(f"当前有 {trust.stale_reads} 个接口最近一次可用结果来自过期缓存，数据可能过期。")
        elif trust.historical_stale_reads > 0:
            st.caption(f"历史累计过期缓存读取 {trust.historical_stale_reads} 次；当前没有接口因 stale 缓存判为异常。")
        success_col = "last_network_success" if "last_network_success" in health.columns else "last_success"
        st.caption(f"最近网络成功：{health[success_col].dropna().max() if health[success_col].notna().any() else '暂无'}")

    st.subheader(SUMMARY_SECTIONS[1])
    if ranked.empty:
        st.info("暂无可展示的因果状态结果。若已经有样本内训练结果，它只会在下方折叠区展示，不作为当前排行榜。")
        if run_id:
            with st.expander("训练样本内展示（非因果）", expanded=False):
                demo_states = latest_in_sample_sector_states(storage, run_id=run_id, universe_id=active_universe)
                demo_ranked = rank_sectors(demo_states)
                if demo_ranked.empty:
                    st.caption("当前 run 没有样本内状态。")
                else:
                    st.warning("这部分来自训练样本内状态，仅用于观察模型拟合，不是因果信号。")
                    demo_display = format_probability_columns(
                        demo_ranked.head(30),
                        ["prob_trend_up", "prob_neutral", "prob_risk_off"],
                    )
                    st.dataframe(rename_columns_for_display(demo_display), width="stretch")
        return
    state_source = ranked["state_source"].dropna().iloc[0] if "state_source" in ranked.columns and ranked["state_source"].notna().any() else "in_sample_display"
    st.info(f"当前总览状态来源为因果滚动训练推断：{state_source}。")

    counts = ranked["state_label"].value_counts().reset_index()
    counts.columns = ["state_label", "count"]
    counts["状态"] = counts["state_label"].map(display_state_label)
    left, right = st.columns([1, 2])
    left_fig = px.pie(counts, names="状态", values="count", title="状态分布")
    left_fig.update_layout(legend_title_text="状态")
    left.plotly_chart(left_fig, width="stretch")
    right_fig = px.bar(counts, x="状态", y="count", title="状态数量", labels={"count": "数量", "状态": "状态"})
    right.plotly_chart(right_fig, width="stretch")

    st.markdown("**板块排行榜**")
    display_cols = [
        "sector_type",
        "sector_name",
        "state_label",
        "state_source",
        "prob_trend_up",
        "prob_neutral",
        "prob_risk_off",
        "sector_score",
        "sector_tag",
        "feature_scope_id",
        "feature_scope_type",
    ]
    ranked_display = format_probability_columns(
        ranked[
            [
                col for col in display_cols if col in ranked.columns
            ]
        ].head(50),
        ["prob_trend_up", "prob_neutral", "prob_risk_off"],
    )
    st.dataframe(
        rename_columns_for_display(ranked_display),
        width="stretch",
    )

    with st.expander("高级观察：高风险板块与最近状态切换", expanded=False):
        st.markdown("**高风险板块**")
        high_risk = format_probability_columns(ranked[ranked["sector_tag"] == "风险回避"].head(30), ["prob_trend_up", "prob_neutral", "prob_risk_off"])
        st.dataframe(rename_columns_for_display(high_risk), width="stretch")

        recent_switch = recent_causal_switches(storage, cache_key=cache_key, universe_id=active_universe)
        st.markdown("**最近状态切换**")
        st.dataframe(rename_columns_for_display(recent_switch), width="stretch")
