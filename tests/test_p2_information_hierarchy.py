from __future__ import annotations

import inspect

from src.ui import dashboard, sector_detail, stock_filter_page


def test_dashboard_has_three_core_summary_sections():
    assert dashboard.SUMMARY_SECTIONS == ["当前市场环境", "候选板块", "结果可信度"]
    source = inspect.getsource(dashboard.render_dashboard)

    assert source.count("st.subheader(SUMMARY_SECTIONS[") == 3
    assert "高级观察：高风险板块与最近状态切换" in source


def test_stock_filter_keeps_data_update_optional():
    source = inspect.getsource(stock_filter_page.render_stock_filter)

    assert stock_filter_page.OPTIONAL_DATA_UPDATE_LABEL == "数据更新（可选）"
    assert "with st.expander(OPTIONAL_DATA_UPDATE_LABEL" in source
    assert "筛选漏斗" in source
    assert "未入选原因样例" in source


def test_sector_detail_marks_stock_tabs_as_advanced():
    source = inspect.getsource(sector_detail.render_sector_detail)

    assert "高级：个股叠加" in source
    assert "高级：成分股排名" in source
