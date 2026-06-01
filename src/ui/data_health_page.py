from __future__ import annotations

import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import incremental_update_boards
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.operation_result import render_operation_result
from src.ui.help_texts import rename_columns_for_display
from src.utils.dates import today_yyyymmdd


def render_data_health(storage: DuckDBStorage) -> None:
    st.title("数据健康")
    render_data_status_bar(storage)
    health = storage.read_df("SELECT * FROM data_health ORDER BY interface")
    if health.empty:
        st.info("暂无接口健康记录。")
    else:
        preferred = [
            "interface",
            "last_network_success",
            "last_network_failure",
            "last_cache_hit",
            "last_error",
            "cache_hits",
            "network_hits",
            "stale_reads",
        ]
        st.dataframe(rename_columns_for_display(health[[c for c in preferred if c in health.columns]]), width="stretch")

    lengths = storage.read_df(
        """
        SELECT m.sector_type, m.sector_name, count(o.trade_date) AS rows,
               min(o.trade_date) AS first_date, max(o.trade_date) AS last_date
        FROM sector_meta m
        LEFT JOIN sector_ohlcv o USING(sector_id)
        GROUP BY m.sector_type, m.sector_name
        ORDER BY rows ASC, m.sector_type, m.sector_name
        """
    )
    st.subheader("板块数据长度")
    st.dataframe(rename_columns_for_display(lengths), width="stretch")

    missing_stock = storage.read_df(
        """
        SELECT c.sector_id, count(*) AS constituents,
               sum(CASE WHEN s.stock_code IS NULL THEN 1 ELSE 0 END) AS missing_stock_ohlcv,
               sum(CASE WHEN s.stock_code IS NULL THEN 1 ELSE 0 END)::DOUBLE / nullif(count(*), 0) AS missing_ratio
        FROM sector_constituents c
        LEFT JOIN (SELECT DISTINCT stock_code FROM stock_ohlcv) s USING(stock_code)
        GROUP BY c.sector_id
        ORDER BY missing_stock_ohlcv DESC
        LIMIT 100
        """
    )
    st.subheader("个股数据缺失比例")
    st.dataframe(rename_columns_for_display(missing_stock), width="stretch")

    failures = storage.read_df("SELECT * FROM fetch_failures ORDER BY last_failure DESC")
    st.subheader("失败抓取记录")
    if failures.empty:
        st.info("暂无失败板块记录。")
    else:
        st.dataframe(rename_columns_for_display(failures), width="stretch")

    c1, c2 = st.columns(2)
    industry_failures = failures[(failures["target_type"] == "sector") & (failures["board_type"] == "industry")]["target_name"].drop_duplicates().tolist() if not failures.empty else []
    concept_failures = failures[(failures["target_type"] == "sector") & (failures["board_type"] == "concept")]["target_name"].drop_duplicates().tolist() if not failures.empty else []

    industry_label = "重新抓取行业失败板块" if industry_failures else "重新抓取前 10 个行业板块"
    concept_label = "重新抓取概念失败板块" if concept_failures else "重新抓取前 10 个概念板块"
    if c1.button(industry_label):
        try:
            summary = incremental_update_boards(
                "industry",
                "20200101",
                today_yyyymmdd(),
                limit=None if industry_failures else 10,
                include_constituents=bool(industry_failures),
                sector_names=industry_failures or None,
                lookback_days=10,
                storage=storage,
            )
            render_operation_result(summary, "行业板块重新抓取完成")
        except Exception as exc:
            st.error(f"行业板块重新抓取失败：{exc}")
    if c2.button(concept_label):
        try:
            summary = incremental_update_boards(
                "concept",
                "20200101",
                today_yyyymmdd(),
                limit=None if concept_failures else 10,
                include_constituents=bool(concept_failures),
                sector_names=concept_failures or None,
                lookback_days=10,
                storage=storage,
            )
            render_operation_result(summary, "概念板块重新抓取完成")
        except Exception as exc:
            st.error(f"概念板块重新抓取失败：{exc}")
