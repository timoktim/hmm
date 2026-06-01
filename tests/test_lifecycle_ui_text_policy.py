from __future__ import annotations

from pathlib import Path

from src.evaluation.hsmm_display_lifecycle import build_ui_text_policy_audit


def test_ui_visible_strings_do_not_contain_trading_language():
    audit = build_ui_text_policy_audit()
    errors = audit[(audit["severity"].eq("error")) & (~audit["allowed_exception"].astype(bool))]

    assert errors.empty


def test_riskoff_not_used_as_primary_display_label():
    lifecycle_page = Path("src/ui/lifecycle_page.py").read_text(encoding="utf-8")

    assert "RiskOff" not in lifecycle_page
    assert "买入" not in lifecycle_page
    assert "卖出" not in lifecycle_page
    assert "推荐" not in lifecycle_page
