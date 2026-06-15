from __future__ import annotations

from src.ui.components.help_dock import build_help_chip_row_html, help_term_html
from src.ui.components.status_display import StatusItem, build_status_grid_html
from src.ui.help_texts import explain_term


def test_help_dictionary_covers_signal_panel_volatility_terms() -> None:
    assert "指数加权" in str(explain_term("ewma_vol"))
    assert "近期波动" in str(explain_term("EWMA 波动率"))
    assert "最新可得行情" in str(explain_term("数据新鲜度"))


def test_help_term_renders_hover_metadata() -> None:
    html = help_term_html("EWMA 波动率", key="ewma_vol")

    assert "hmm-help-term" in html
    assert "data-help=" in html
    assert "指数加权移动波动率" in html


def test_status_grid_labels_are_hover_help_terms() -> None:
    html = build_status_grid_html([StatusItem("数据新鲜度", "已用最新可得数据:131")])

    assert "hmm-status-card" in html
    assert "hmm-help-term" in html
    assert "最新可得行情" in html


def test_help_chip_row_uses_column_labels_and_explanations() -> None:
    html = build_help_chip_row_html(["ewma_vol"], labels={"ewma_vol": "EWMA 波动率"})

    assert "hmm-help-chip-row" in html
    assert "EWMA 波动率" in html
    assert "指数加权移动波动率" in html
