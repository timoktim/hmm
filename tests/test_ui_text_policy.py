from __future__ import annotations

from pathlib import Path

UI_TEXT_FILES = [
    Path("src/ui/sector_detail.py"),
    Path("src/ui/help_texts.py"),
]

FORBIDDEN_PHRASES = [
    "上涨概率",
    "下跌概率",
    "收益概率",
    "买入",
    "卖出",
    "推荐",
    "下一状态概率",
    "趋势上行概率",
]


def _ui_text() -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in UI_TEXT_FILES)


def test_ui_forbidden_terms_do_not_appear_in_allowed_wp12_files():
    text = _ui_text()

    findings = {phrase: text.count(phrase) for phrase in FORBIDDEN_PHRASES}

    assert findings == {phrase: 0 for phrase in FORBIDDEN_PHRASES}


def test_hmm_probability_copy_uses_posterior_and_transition_distribution_terms():
    text = _ui_text()

    assert "TrendUp 状态后验" in text
    assert "压力状态后验" in text
    assert "模型迁移分布" in text
    assert "趋势状态置信度" not in text
    assert "风险回避状态置信度" not in text
    assert "下一状态置信度" not in text


def test_legacy_riskoff_display_wording_is_hidden_from_allowed_ui_files():
    text = _ui_text()

    assert '"RiskOff": "压力状态"' in text
    assert "风险回避" not in text
