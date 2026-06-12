from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.signals.signal_panel_snapshot import NO_CURRENT_STAGE03V_SCORE_SOURCE
from src.ui.navigation import page_config, page_labels_for_group
from src.ui.signal_panel_page import WARNING_TEXT, _compact_counts, _display_value, _localize_readiness_text, _signal_display_frame


ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
CONTRACT_DOC = ROOT / "docs/runtime/STAGE03V_SIGNAL_PANEL_CONTRACT.md"
CONTRACT_JSON = ROOT / "reports/stage03v/phase2_signal_panel_contract.json"


def test_navigation_exposes_signal_panel_under_current_status() -> None:
    labels = page_labels_for_group("当前状态", show_advanced=False)
    config = page_config("信号面板")

    assert "信号面板" in labels
    assert config is not None
    assert config.group == "当前状态"
    assert config.advanced is False


def test_app_routes_signal_panel_to_renderer() -> None:
    text = APP.read_text(encoding="utf-8")

    assert "from src.ui.signal_panel_page import render_signal_panel_page" in text
    assert 'elif page == "信号面板":' in text
    assert "render_signal_panel_page(storage, universe_id=selected_universe_id)" in text


def test_signal_panel_warning_text_matches_contract() -> None:
    assert WARNING_TEXT == "此页面为研究信号与人工判断参考，不构成交易、仓位、买卖或执行建议。"


def test_signal_panel_ui_labels_are_localized_for_display() -> None:
    frame = pd.DataFrame(
        [
            {
                "signal_date": "2026-01-02",
                "volatility_band": "high",
                "stage03v_probability_display_status": "hidden_no_current_per_entity_score_source",
                "model_baseline_alignment_status": "baseline_high_model_low",
                "human_review_note": "possible baseline false-alarm / overlay disagreement",
                "not_trading_output": "yes",
            }
        ]
    )

    display = _signal_display_frame(frame)

    assert "信号日期" in display.columns
    assert "波动率分层" in display.columns
    assert display.loc[0, "波动率分层"] == "高"
    assert display.loc[0, "Stage03V 概率显示状态"] == "隐藏：缺少当前实体级分数来源"
    assert display.loc[0, "模型-基准一致性"] == "基准高风险，模型偏低"
    assert display.loc[0, "人工复核提示"] == "可能是基准误报，或模型覆盖不一致"
    assert display.loc[0, "非交易输出"] == "是"


def test_signal_panel_summary_values_are_localized() -> None:
    snapshot = pd.DataFrame({"volatility_band": ["high", "unavailable", "high"]})

    assert _display_value("available_current_per_entity_score_source") == "当前实体级分数来源可用"
    assert _compact_counts(snapshot, "volatility_band") == "高:2 / 不可用:1"
    assert _localize_readiness_text(
        "usable_probability_candidate=1; ordinal_only_candidate=2; probability_source_status=unavailable_current_per_entity_score_source"
    ) == "可显示概率候选=1；仅序数候选=2；概率来源状态=当前实体级分数来源不可用"


def test_runtime_contract_artifacts_exist_and_keep_research_only_boundaries() -> None:
    assert CONTRACT_DOC.exists()
    assert CONTRACT_JSON.exists()
    report = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))

    assert report["index_id"] == "STAGE03V-PHASE2-WP0-v1"
    assert report["status"] == "pass"
    assert report["baseline_first"] == "yes"
    assert report["primary_baseline_family"] == "realized_volatility"
    assert report["model_role"] == "research_only_hazard_overlay"
    assert report["stage03v1_decision_support_status"] == "not_promoted"
    assert report["stage03v_probability_source_status_default"] == NO_CURRENT_STAGE03V_SCORE_SOURCE
    for value in report["boundary_flags"].values():
        assert value == "no"


def test_contract_forbids_invalidated_sources_and_requires_snapshot_schema() -> None:
    report = json.loads(CONTRACT_JSON.read_text(encoding="utf-8"))
    accepted_sources = "\n".join(report["accepted_signal_source_paths"].values())
    required = set(report["required_schema_columns"])

    assert "reports/stage03v/downside_readiness_matrix.csv" in accepted_sources
    assert "reports/stage03v/risk_validation_report.json" not in accepted_sources
    assert "reports/stage03v/downshift_research_report.json" not in accepted_sources
    assert "not_trading_output" in required
    assert "stage03v_probability_source_status" in required
    assert "model_baseline_alignment_status" in required
