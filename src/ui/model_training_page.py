from __future__ import annotations

import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.models.hmm_model import train_hmm
from src.models.market_hmm import train_market_hmm
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.model_workflow import render_model_workflow
from src.ui.components.operation_result import render_operation_result
from src.ui.help_texts import HELP_TEXTS
from src.ui.market_regime_page import latest60_full_market_breadth_available
from src.utils.dates import today_yyyymmdd


def _training_progress():
    bar = st.progress(0)
    text = st.empty()
    stats = st.empty()

    def on_progress(percent: int, stage: str, payload: dict[str, object]) -> None:
        bar.progress(min(max(percent, 0) / 100, 1.0))
        text.caption(f"{stage}（{percent}%）")
        if payload:
            stats.caption("；".join(f"{k}: {v}" for k, v in payload.items()))

    return on_progress


def render_model_training(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("模型训练")
    st.caption("这里集中训练板块 HMM 和大盘 HMM。数据更新请回到“数据中心”。")
    run_id = storage.latest_run_for_current_scope(universe_id)
    render_model_workflow(storage, universe_id=universe_id, active_step="train")
    render_data_status_bar(storage, run_id=run_id, universe_id=universe_id)

    tab_sector, tab_market = st.tabs(["板块 HMM", "大盘 HMM"])

    with tab_sector:
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        start = c1.text_input("训练起始日期", value="20200101", key="sector_train_start")
        end = c2.text_input("训练结束日期", value=today_yyyymmdd(), key="sector_train_end")
        states = c3.selectbox("隐藏状态数量", [2, 3, 4], index=1, key="sector_hmm_states")
        n_iter = c4.number_input("最大迭代次数", min_value=20, max_value=500, value=300, step=20, key="sector_hmm_iter")
        with st.expander("高级训练参数", expanded=False):
            a1, a2 = st.columns(2)
            random_state = a1.number_input("随机种子", min_value=0, max_value=9999, value=42, key="sector_hmm_seed", help=HELP_TEXTS["random_state"])
            n_init = a2.number_input("随机重启次数", min_value=1, max_value=10, value=3, step=1, key="sector_hmm_n_init", help=HELP_TEXTS["hmm_n_init"])
        train_current_universe = st.checkbox("只训练当前板块池", value=universe_id is not None, disabled=universe_id is None)
        if universe_id is None:
            st.caption("当前未选择板块池，将按全市场范围训练。")
        if st.button("开始训练板块 HMM", type="primary"):
            try:
                result = train_hmm(
                    start,
                    end,
                    int(states),
                    storage=storage,
                    universe_id=universe_id if train_current_universe else None,
                    n_iter=int(n_iter),
                    random_state=int(random_state),
                    n_init=int(n_init),
                    progress_callback=_training_progress(),
                )
                render_operation_result(result, "板块 HMM 训练完成")
            except Exception as exc:
                st.error(str(exc))

    with tab_market:
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        start = c1.text_input("训练起始日期", value="20200101", key="market_train_start")
        end = c2.text_input("训练结束日期", value=today_yyyymmdd(), key="market_train_end")
        states = c3.selectbox("隐藏状态数量", [2, 3, 4], index=1, key="market_hmm_states")
        random_state = c4.number_input("随机种子", min_value=0, max_value=9999, value=42, key="market_hmm_seed")
        breadth_ready, breadth_message = latest60_full_market_breadth_available(storage)
        use_breadth = st.checkbox(
            "使用全 A 市场宽度",
            value=breadth_ready,
            disabled=not breadth_ready,
            help="只有最近 60 日 full_market 宽度覆盖达标时，才会用于大盘 HMM。",
        )
        if not breadth_ready:
            st.warning(breadth_message)
        if st.button("开始训练大盘 HMM", type="primary"):
            try:
                result = train_market_hmm(
                    start,
                    end,
                    n_states=int(states),
                    use_breadth=bool(use_breadth),
                    random_state=int(random_state),
                    storage=storage,
                    progress_callback=_training_progress(),
                )
                render_operation_result(result, "大盘 HMM 训练完成")
            except Exception as exc:
                st.error(str(exc))
