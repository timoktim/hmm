from __future__ import annotations

import plotly.express as px
import streamlit as st

from src.backtest.sector_rotation import estimate_backtest_signal_count, run_sector_rotation_backtest
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.data_trust_card import render_data_trust_card
from src.ui.components.model_workflow import render_model_workflow
from src.ui.help_texts import HELP_TEXTS, display_value, rename_columns_for_display
from src.ui.run_context import render_run_scope_status


def render_backtest(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("板块轮动回测")
    render_model_workflow(storage, universe_id=universe_id, active_step="backtest")
    scope_options = ["all"]
    if universe_id:
        scope_options.append("universe")
    scope = st.radio("回测范围", scope_options, horizontal=True, format_func=lambda x: "全市场" if x == "all" else "当前板块池")
    active_universe = universe_id if scope == "universe" else None
    run_id = render_run_scope_status(storage, active_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=active_universe, walk_forward_causal=True)
    st.info("大盘状态过滤尚未因果接入回测，本页不展示可操作开关，避免误解为已经影响结果。")
    st.subheader("基础参数")
    threshold = st.slider("趋势状态置信度阈值", 0.30, 0.90, 0.55, 0.05, help=HELP_TEXTS["trend_up_threshold"])
    top_n = st.number_input("持有板块数量", min_value=1, max_value=20, value=5, help=HELP_TEXTS["top_n"])
    rebalance_days = st.number_input("调仓间隔（交易日）", min_value=1, max_value=30, value=5, help=HELP_TEXTS["rebalance_every"])
    n_states = st.number_input("HMM 隐藏状态数", min_value=2, max_value=6, value=3, help="板块模型将每个板块划分为几个隐藏状态。默认 3 个状态：趋势上行、中性震荡、风险回避。")
    train_window_days = st.number_input("滚动训练窗口（交易日）", min_value=60, max_value=1500, value=504, help=HELP_TEXTS["train_window"])
    ohlcv_scope = load_sector_like_ohlcv(storage, universe_id=active_universe, include_custom_baskets=True)
    if ohlcv_scope.empty:
        default_start = ""
        default_end = ""
    else:
        dates = ohlcv_scope["trade_date"]
        default_start = str(dates.min())
        default_end = str(dates.max())
    start_date = st.text_input("回测开始日期", value=default_start)
    end_date = st.text_input("回测结束日期", value=default_end)
    st.subheader("高级参数")
    retrain_frequency = st.selectbox("HMM 重训频率", ["monthly", "quarterly", "signal"], index=0, format_func=lambda x: {"monthly": "每月", "quarterly": "每季度", "signal": "每个调仓信号日（最慢）"}[x])
    state_mode = st.selectbox("状态来源", ["causal_backtest", "in_sample_display"], index=0, format_func=lambda x: "因果滚动训练（用于策略回测）" if x == "causal_backtest" else "训练样本内状态（非因果演示）")
    execution_price = st.selectbox("执行价格", ["open", "close"], index=0, format_func=lambda x: "次日开盘" if x == "open" else "次日收盘")
    transaction_cost = st.number_input("单边交易成本", min_value=0.0, max_value=0.01, value=0.001, step=0.0005, format="%.4f", help=HELP_TEXTS["transaction_cost"])
    estimate = estimate_backtest_signal_count(storage, start_date or None, end_date or None, int(rebalance_days), universe_id=active_universe)
    st.caption(f"预计调仓信号日：{estimate['rebalance_signals']}；候选交易日：{estimate.get('candidate_trade_dates', estimate['state_dates'])}。因果滚动只会为调仓信号日训练/推断，并按参数缓存。")
    if retrain_frequency == "signal":
        st.warning("每个调仓信号日都重训会明显变慢。一般先用“每月”或“每季度”重训。")
    if state_mode == "in_sample_display":
        st.warning("训练样本内状态是非因果展示，不能作为真实策略评估；此模式仅用于演示对照。")
        if not run_id:
            st.warning("当前范围没有可用的训练样本内 run。")
    if st.button("运行回测"):
        try:
            progress_bar = st.progress(0)
            progress_text = st.empty()

            def update_progress(done: int, total: int, signal_date, retrained: bool) -> None:
                progress_bar.progress(min(done / max(total, 1), 1.0))
                marker = "重训" if retrained else "推断"
                progress_text.caption(f"{marker} {signal_date.date()} ({done}/{total})")

            result = run_sector_rotation_backtest(
                run_id=run_id,
                threshold=threshold,
                top_n=int(top_n),
                rebalance_days=int(rebalance_days),
                start_date=start_date or None,
                end_date=end_date or None,
                n_states=int(n_states),
                train_window_days=int(train_window_days),
                retrain_frequency=retrain_frequency,
                execution_price=execution_price,
                transaction_cost=float(transaction_cost),
                walk_forward=state_mode == "causal_backtest",
                allow_in_sample_demo=state_mode == "in_sample_display",
                universe_id=active_universe,
                progress_callback=update_progress,
                storage=storage,
            )
            progress_bar.progress(1.0)
            progress_text.caption("回测完成")
        except Exception as exc:
            st.error(str(exc))
            return
        st.subheader("回测结果")
        metrics = result["metrics"]
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("年化收益", f"{metrics['annual_return']:.2%}")
        c2.metric("最大回撤", f"{metrics['max_drawdown']:.2%}")
        c3.metric("夏普比率", f"{metrics['sharpe']:.2f}")
        c4.metric("Calmar", f"{metrics['calmar']:.2f}")
        c5.metric("换手率", f"{metrics['turnover']:.2%}")
        curve = result["curve"]
        st.caption(f"状态来源：{display_value(result['state_source'])}；重训频率：{display_value(result['retrain_frequency'])}；缓存命中：{'是' if result['cache_hit'] else '否'}")
        net_cols = [c for c in curve.columns if c.endswith("_nav_net")]
        plot_df = curve[["trade_date", *net_cols]].rename(columns={"trade_date": "交易日期"})
        renamed_net_cols: list[str] = []
        for col in net_cols:
            strategy = col[: -len("_nav_net")]
            label = f"{display_value(strategy)}（扣费后）"
            plot_df = plot_df.rename(columns={col: label})
            renamed_net_cols.append(label)
        fig_nav = px.line(plot_df, x="交易日期", y=renamed_net_cols, title="扣费后净值曲线")
        fig_nav.update_layout(legend_title_text="策略", yaxis_title="净值")
        st.plotly_chart(fig_nav, width="stretch")
        st.subheader("对照回测指标")
        st.dataframe(rename_columns_for_display(result["comparison"]), width="stretch")
        st.subheader("持仓板块变化")
        st.dataframe(rename_columns_for_display(result["trades"]), width="stretch")
        st.subheader("回测数据质量")
        render_data_trust_card(storage, run_id=run_id, universe_id=active_universe, walk_forward_causal=state_mode == "causal_backtest")
