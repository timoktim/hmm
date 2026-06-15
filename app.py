from __future__ import annotations

from pathlib import Path

from src.utils.runtime import configure_numeric_runtime

configure_numeric_runtime()

import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import default_universe_id
from src.runtime.db_workspace import resolve_active_db_path
from src.ui.backtest_page import render_backtest
from src.ui.components.app_style import render_app_layout_css
from src.ui.components.data_trust_card import build_data_trust_summary
from src.ui.components.help_dock import render_help_dock
from src.ui.data_center_page import render_data_center
from src.ui.database_workspace_page import render_database_workspace, render_sidebar_database_status
from src.ui.dashboard import render_dashboard
from src.ui.data_health_page import render_data_health
from src.ui.market_regime_page import render_market_regime
from src.ui.model_evaluation_page import render_model_evaluation
from src.ui.model_training_page import render_model_training
from src.ui.navigation import DEFAULT_NAV_GROUP, DEFAULT_PAGE, NAV_GROUPS, page_labels_for_group
from src.ui.lifecycle_page import render_lifecycle_page
from src.ui.sector_detail import render_sector_detail
from src.ui.signal_panel_page import render_signal_panel_page
from src.ui.state_screener_page import render_state_screener
from src.ui.stock_filter_page import render_stock_filter
from src.ui.universe_manager import render_universe_manager


def build_active_storage(active_db_path: Path | None = None) -> tuple[DuckDBStorage | None, Path]:
    path = active_db_path or resolve_active_db_path()
    if not path.exists() or path.is_dir():
        return None, path
    storage = DuckDBStorage(path)
    storage.init_schema()
    return storage, path


st.set_page_config(page_title="A股板块 HMM 状态分析器", layout="wide")
render_app_layout_css()
render_help_dock()
storage, active_db_path = build_active_storage()

with st.sidebar:
    render_sidebar_database_status(active_db_path)
    st.divider()
    st.header("导航")
    show_advanced_pages = st.checkbox(
        "显示高级页面",
        value=False,
        help="开启后显示数据健康、状态筛选器等高级诊断/研究入口。普通使用建议先保持关闭。",
    )
    nav_group = st.radio(
        "工作区",
        NAV_GROUPS,
        index=NAV_GROUPS.index(DEFAULT_NAV_GROUP),
        help="按用户任务组织页面，减少普通路径里的入口噪音。",
    )
    page_options = page_labels_for_group(nav_group, show_advanced=show_advanced_pages)
    default_page_index = page_options.index(DEFAULT_PAGE) if DEFAULT_PAGE in page_options else 0
    page = st.radio("当前页面", page_options, index=default_page_index)
    st.divider()
    selected_universe_id = None
    if storage is None:
        st.warning("当前 active DB 文件不存在。请先在“数据库工作区”中新建或切换数据库。")
    else:
        st.subheader("板块池")
        universes = storage.list_universes()
        default_id = default_universe_id(storage)
        if universes.empty:
            st.caption("暂无板块池，可在“板块池管理”中创建。")
        else:
            labels = ["全市场（不使用板块池）"]
            labels.extend(universes.apply(lambda r: f"{r['universe_name']} | {r['universe_id']}", axis=1).tolist())
            default_index = 0
            if default_id:
                for idx, label in enumerate(labels):
                    if label.endswith(f"| {default_id}"):
                        default_index = idx
                        break
            selected_label = st.selectbox(
                "当前观察范围",
                labels,
                index=default_index,
                help="选择“全市场”时，覆盖率、总览、训练和回测都按全市场口径；选择板块池时才按该板块池口径。",
            )
            if selected_label != "全市场（不使用板块池）":
                selected_universe_id = selected_label.split(" | ")[-1]
            st.caption("当前口径：" + ("全市场" if selected_universe_id is None else selected_label.split(" | ")[0]))
        st.divider()
        st.subheader("当前 run")
        latest_run_id = storage.latest_run_for_current_scope(selected_universe_id)
        if latest_run_id:
            run = storage.get_model_run(latest_run_id)
            row = run.iloc[0]
            st.caption(f"{latest_run_id} | {row.get('scope_type')} | {row.get('train_end')}")
        else:
            st.caption("当前范围暂无 HMM run")
        st.divider()
        st.subheader("数据状态")
        trust_summary = build_data_trust_summary(storage, run_id=latest_run_id, universe_id=selected_universe_id)
        st.caption(f"最近成功：{trust_summary.last_network_success}")
        st.caption(f"当前 stale 接口：{trust_summary.stale_reads}")
        if trust_summary.historical_stale_reads:
            st.caption(f"历史 stale 次数：{trust_summary.historical_stale_reads}")

if storage is None:
    render_database_workspace(storage, active_db_path=active_db_path)
elif page == "数据中心":
    render_data_center(storage, universe_id=selected_universe_id)
elif page == "数据库工作区":
    render_database_workspace(storage, active_db_path=active_db_path)
elif page == "板块池管理":
    render_universe_manager(storage)
elif page == "总览":
    render_dashboard(storage, universe_id=selected_universe_id)
elif page == "状态生命周期":
    render_lifecycle_page(storage, universe_id=selected_universe_id)
elif page == "状态筛选器":
    render_state_screener(storage, universe_id=selected_universe_id)
elif page == "板块详情":
    render_sector_detail(storage, universe_id=selected_universe_id)
elif page == "个股过滤":
    render_stock_filter(storage, universe_id=selected_universe_id)
elif page == "模型训练":
    render_model_training(storage, universe_id=selected_universe_id)
elif page == "模型评估":
    render_model_evaluation(storage, universe_id=selected_universe_id)
elif page == "回测":
    render_backtest(storage, universe_id=selected_universe_id)
elif page == "大盘状态":
    render_market_regime(storage, universe_id=selected_universe_id)
elif page == "信号面板":
    render_signal_panel_page(storage, universe_id=selected_universe_id)
else:
    render_data_health(storage)
