from __future__ import annotations

from src.evaluation.hsmm_display_lifecycle import build_ui_text_policy_audit, summarize_text_policy_audit


def test_legacy_warning_count_reduced_and_lifecycle_clean():
    audit = build_ui_text_policy_audit()
    summary = summarize_text_policy_audit(audit)

    assert summary["lifecycle_page_error_count"] == 0
    assert summary["text_audit_error_count"] == 0
    assert summary["legacy_warning_count"] < 20
