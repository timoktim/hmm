from __future__ import annotations

from pathlib import Path

from src.evaluation.hsmm_display_lifecycle import build_ui_text_policy_audit, summarize_text_policy_audit


def test_text_audit_summary_counts_lifecycle_errors(tmp_path):
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    (ui_root / "lifecycle_page.py").write_text('st.write("买入")\n', encoding="utf-8")
    (ui_root / "legacy_page.py").write_text('st.write("买入")\n', encoding="utf-8")

    audit = build_ui_text_policy_audit(ui_root)
    summary = summarize_text_policy_audit(audit)

    assert summary["text_audit_error_count"] == 1
    assert summary["lifecycle_page_error_count"] == 1
    assert summary["legacy_warning_count"] == 1


def test_text_audit_summary_zero_when_clean(tmp_path):
    ui_root = tmp_path / "ui"
    ui_root.mkdir()
    (ui_root / "lifecycle_page.py").write_text('st.write("状态生命周期")\n', encoding="utf-8")

    audit = build_ui_text_policy_audit(Path(ui_root))
    summary = summarize_text_policy_audit(audit)

    assert summary["text_audit_error_count"] == 0
    assert summary["text_audit_warning_count"] == 0
