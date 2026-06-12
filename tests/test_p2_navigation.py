from __future__ import annotations

from src.ui.navigation import DEFAULT_NAV_GROUP, DEFAULT_PAGE, NAV_GROUPS, page_config, page_labels_for_group, visible_page_labels


def test_p2_navigation_default_focuses_current_status():
    assert DEFAULT_NAV_GROUP == "当前状态"
    assert DEFAULT_PAGE == "总览"
    assert page_labels_for_group(DEFAULT_NAV_GROUP) == ["总览", "大盘状态", "信号面板"]


def test_p2_navigation_hides_advanced_pages_by_default():
    visible = visible_page_labels(show_advanced=False)

    assert "数据健康" not in visible
    assert "状态筛选器" not in visible
    assert "数据中心" in visible
    assert "模型评估" in visible


def test_p2_navigation_reveals_advanced_pages_when_enabled():
    visible = visible_page_labels(show_advanced=True)

    assert "数据健康" in visible
    assert "状态筛选器" in visible
    assert page_config("数据健康").advanced
    assert page_config("状态筛选器").advanced


def test_p2_navigation_groups_are_task_oriented():
    assert NAV_GROUPS == ["当前状态", "数据与质量", "板块和个股", "模型实验"]
    assert page_labels_for_group("数据与质量") == ["数据中心", "数据库工作区"]
    assert page_labels_for_group("数据与质量", show_advanced=True) == ["数据中心", "数据库工作区", "数据健康"]
