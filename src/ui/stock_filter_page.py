from __future__ import annotations

import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import UpdateProgress, update_market_benchmark, update_stock_histories
from src.features.custom_basket_features import build_custom_basket_ohlcv, custom_basket_quality_frame
from src.scoring.stock_filter import _constituents_for_sector, filter_sector_stocks, load_market_benchmark_close
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.operation_result import render_operation_result
from src.ui.help_texts import HELP_TEXTS, rename_columns_for_display
from src.ui.run_context import render_run_scope_status
from src.ui.sector_detail import _select_sector
from src.utils.dates import today_yyyymmdd


OPTIONAL_DATA_UPDATE_LABEL = "数据更新（可选）"


def render_stock_filter(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("个股过滤")
    selected_universe = universe_id
    if universe_id:
        use_universe = st.checkbox("只显示当前板块池中的板块", value=True, key="stock_use_universe")
        selected_universe = universe_id if use_universe else None
    run_id = render_run_scope_status(storage, selected_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=selected_universe)
    sector_id = _select_sector(storage, "stock", universe_id=selected_universe)
    if not sector_id:
        return
    drawdown = st.slider("最大回撤阈值", 0.05, 0.35, 0.18, 0.01, help=HELP_TEXTS["max_drawdown_threshold"])
    min_amount_z = st.slider("成交额热度下限", -2.0, 2.0, -0.5, 0.1, help=HELP_TEXTS["amount_z_min"])
    st.subheader("硬性筛选条件")
    col_a, col_b, col_c = st.columns(3)
    require_close_above_ma20 = col_a.checkbox("收盘价高于20日均线", value=True, help="要求股票最新收盘价站上20日均线，是较直接的趋势过滤条件。")
    require_ma20_slope_positive = col_b.checkbox("20日均线向上", value=True, help="要求20日均线本身向上，过滤更严格，但可能错过刚启动的股票。")
    require_rs_vs_index_positive = col_c.checkbox("20日相对大盘强弱为正", value=True, help="要求股票近20日收益强于市场基准。缺少市场基准时会自动跳过。")
    info_container = st.popover("为什么这三个条件特殊？") if hasattr(st, "popover") else st.expander("为什么这三个条件特殊？")
    with info_container:
        st.markdown(
            """
            - 收盘价高于20日均线是趋势过滤，会快速排除均线下方的股票，因此在震荡或刚启动阶段可能过严。
            - 20日均线向上要求均线本身已经拐头，比单纯站上均线更慢，适合确认趋势但会牺牲早期信号。
            - 20日相对大盘强弱为正依赖市场基准数据；如果沪深300或中证全指缺失，本页会明确跳过该项，避免把板块相对强弱误当市场相对强弱。
            """
        )
    benchmark_label = st.selectbox("市场基准", ["沪深300", "中证全指"], index=0)
    benchmark_id = "hs300" if benchmark_label == "沪深300" else "csi_all"
    cons = _constituents_for_sector(storage, sector_id)
    with st.expander(OPTIONAL_DATA_UPDATE_LABEL, expanded=False):
        st.caption("日常使用建议先在数据中心更新数据；这里仅用于当前板块或当前市场基准的临时补抓。")
        if st.button("更新市场基准"):
            with st.spinner(f"正在更新{benchmark_label}..."):
                summary = update_market_benchmark(benchmark_id, "20200101", today_yyyymmdd(), incremental=True, lookback_days=10, storage=storage)
                if summary.failure:
                    st.error(f"市场基准更新失败：{summary.failure}")
                else:
                    st.success(f"市场基准已更新：{summary.rows} 行")
        stock_start = st.text_input("个股行情起始日期", value="20230101", help=HELP_TEXTS["stock_start_date"])
        stock_limit = st.number_input("最多更新个股数量", min_value=1, max_value=1000, value=100, help=HELP_TEXTS["max_stocks_to_update"])
        missing_only = st.checkbox("仅更新缺失个股", value=True, help=HELP_TEXTS["missing_only"])
        if not cons.empty and st.button("更新该板块/股票池个股行情"):
            with st.spinner("正在更新个股行情，时间取决于成分股数量..."):
                try:
                    progress_bar = st.progress(0)
                    progress_text = st.empty()
                    stats_text = st.empty()

                    def on_progress(progress: UpdateProgress) -> None:
                        progress_bar.progress(min(progress.current / max(progress.total, 1), 1.0))
                        progress_text.caption(f"正在更新 {progress.name}：{progress.current}/{progress.total}")
                        stats_text.caption(
                            f"成功 {progress.successes}，失败 {progress.failures}，缓存命中 {progress.cache_hits}，过期缓存 {progress.stale_reads}"
                        )

                    summary = update_stock_histories(
                        cons["stock_code"].astype(str).tolist(),
                        stock_start,
                        today_yyyymmdd(),
                        incremental=True,
                        lookback_days=10,
                        missing_only=missing_only,
                        limit=int(stock_limit),
                        progress_callback=on_progress,
                        storage=storage,
                    )
                    progress_bar.progress(1.0)
                    progress_text.caption("个股行情更新完成")
                    stats_text.caption(f"成功 {summary.sectors_updated}，失败 {len(summary.failures)}，缓存命中 {summary.cache_hits}，过期缓存 {summary.stale_reads}")
                    render_operation_result(summary, "个股行情更新完成")
                    if sector_id.startswith("custom:"):
                        basket_ohlcv = build_custom_basket_ohlcv(sector_id, stock_start, today_yyyymmdd(), storage=storage)
                        quality = custom_basket_quality_frame(sector_id, storage=storage)
                        st.success(f"自定义股票池指数已生成：{len(basket_ohlcv)} 行")
                        if not quality.empty:
                            latest = quality.iloc[-1]
                            low_quality_days = int(quality["low_quality"].sum())
                            st.caption(
                                f"最近有效成员数：{int(latest['member_count'])}，"
                                f"覆盖率：{float(latest['coverage']):.1%}；覆盖率低于 50% 日期数：{low_quality_days}"
                            )
                except Exception as exc:
                    st.error(f"个股行情更新失败：{exc}")

    if load_market_benchmark_close(storage, benchmark_id=benchmark_id) is None:
        st.warning(f"缺少{benchmark_label}市场基准，已跳过“20日相对大盘强弱”评分项。")
    scores, diagnostics = filter_sector_stocks(
        sector_id,
        drawdown_threshold=drawdown,
        min_amount_z=min_amount_z,
        benchmark_id=benchmark_id,
        require_close_above_ma20=require_close_above_ma20,
        require_ma20_slope_positive=require_ma20_slope_positive,
        require_rs_vs_index_positive=require_rs_vs_index_positive,
        return_diagnostics=True,
        storage=storage,
    )
    filters = diagnostics.get("filters", [])
    if filters:
        st.subheader("筛选漏斗")
        st.dataframe(rename_columns_for_display(filters), width="stretch")
    failed_examples = diagnostics.get("failed_examples", [])
    if failed_examples:
        st.subheader("未入选原因样例")
        st.dataframe(rename_columns_for_display(failed_examples), width="stretch")
    if scores.empty:
        st.warning("暂无符合条件的数据。可先更新成分股和个股行情，或放宽过滤阈值。")
        return
    st.caption("涨跌停相关风险提示使用近似阈值，暂未精确区分 ST、创业板、科创板、北交所涨跌幅限制。")
    st.dataframe(rename_columns_for_display(scores), width="stretch")
