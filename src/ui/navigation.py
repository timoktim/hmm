from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageConfig:
    label: str
    group: str
    advanced: bool = False


NAV_GROUPS = ["当前状态", "数据与质量", "板块和个股", "模型实验"]
DEFAULT_NAV_GROUP = "当前状态"
DEFAULT_PAGE = "总览"

PAGE_CONFIGS = [
    PageConfig("总览", "当前状态"),
    PageConfig("大盘状态", "当前状态"),
    PageConfig("状态生命周期", "当前状态", advanced=True),
    PageConfig("数据中心", "数据与质量"),
    PageConfig("数据健康", "数据与质量", advanced=True),
    PageConfig("板块池管理", "板块和个股"),
    PageConfig("板块详情", "板块和个股"),
    PageConfig("个股过滤", "板块和个股"),
    PageConfig("状态筛选器", "板块和个股", advanced=True),
    PageConfig("模型训练", "模型实验"),
    PageConfig("模型评估", "模型实验"),
    PageConfig("回测", "模型实验"),
]


def page_labels_for_group(group: str, show_advanced: bool = False) -> list[str]:
    return [
        page.label
        for page in PAGE_CONFIGS
        if page.group == group and (show_advanced or not page.advanced)
    ]


def page_config(label: str) -> PageConfig | None:
    for page in PAGE_CONFIGS:
        if page.label == label:
            return page
    return None


def visible_page_labels(show_advanced: bool = False) -> list[str]:
    labels: list[str] = []
    for group in NAV_GROUPS:
        labels.extend(page_labels_for_group(group, show_advanced=show_advanced))
    return labels
