from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation import stage03v_risk_validation as rv


def _stage_doc(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
    }


def _wp5_doc(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "fixed_threshold_mainline_status": "unchanged_primary_target",
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "calibration_boundary_violation_counts": {"calibration_boundary_violation_count_total": 0},
            "boundary_flags": {
                "probability_calibration": "yes",
                "readiness_assigned": "yes_development_only",
                "trading_or_decision_output": "no",
                "holdout_consumed": "no",
            },
        }
    )
    return doc


def _fold_plan() -> dict:
    return {"status": "pass", "fold_count": 3, "purge_violation_count": 0, "embargo_violation_count": 0}


def test_missing_v7_db_returns_blocked_status_and_no_old_db_fallback(tmp_path: Path) -> None:
    report = rv.build_risk_validation_report(
        db_path=tmp_path / "missing_v7.duckdb",
        target_support=tmp_path / "missing_support.json",
        protocol_output=tmp_path / "protocol.md",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        metrics=tmp_path / "metrics.csv",
        downshift_report=tmp_path / "downshift.md",
        downshift_json=tmp_path / "downshift.json",
        candidate_matrix=tmp_path / "candidates.csv",
        clustered_summary=tmp_path / "cluster_summary.csv",
        audit_sample=tmp_path / "audit.csv",
        wp7_manifest=tmp_path / "manifest.json",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_input"
    assert report["old_db_fallback"] is False
    assert report["external_data_fetch"] == "no"


def test_missing_v7_db_blocks_after_inputs_are_available(tmp_path: Path) -> None:
    payloads = {
        "support.json": _stage_doc(),
        "controls.json": _stage_doc(),
        "full.json": _stage_doc(),
        "baseline.json": _stage_doc(),
        "vol.json": _stage_doc(),
        "logistic.json": _stage_doc(),
        "wp5.json": _wp5_doc(),
        "fold.json": _fold_plan(),
        "policy.json": rv.default_policy(),
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    report = rv.build_risk_validation_report(
        db_path=tmp_path / "missing_v7.duckdb",
        target_support=tmp_path / "support.json",
        target_controls=tmp_path / "controls.json",
        full_target_audit=tmp_path / "full.json",
        baseline_diagnostics=tmp_path / "baseline.json",
        vol_scaled_sanity=tmp_path / "vol.json",
        logistic_hazard=tmp_path / "logistic.json",
        calibration_readiness=tmp_path / "wp5.json",
        fold_plan=tmp_path / "fold.json",
        policy=tmp_path / "policy.json",
        protocol_output=tmp_path / "protocol.md",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        metrics=tmp_path / "metrics.csv",
        downshift_report=tmp_path / "downshift.md",
        downshift_json=tmp_path / "downshift.json",
        candidate_matrix=tmp_path / "candidates.csv",
        clustered_summary=tmp_path / "cluster_summary.csv",
        audit_sample=tmp_path / "audit.csv",
        wp7_manifest=tmp_path / "manifest.json",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["source_db_path"] == "missing_v7.duckdb"


def test_failed_wp5_or_holdout_consumption_blocks_wp6() -> None:
    failed = _wp5_doc(status="fail")
    failed["prospective_holdout_rows_evaluated"] = 1
    status, issues = rv.validate_wp6_preconditions(
        target_support=_stage_doc(),
        target_controls=_stage_doc(),
        full_target_audit=_stage_doc(),
        baseline_diagnostics=_stage_doc(),
        vol_scaled_sanity=_stage_doc(),
        logistic_hazard=_stage_doc(),
        calibration_readiness=failed,
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_holdout_consumed"
    assert "wp5_status_not_pass" in issues
    assert "wp5_prospective_holdout_rows_evaluated_not_zero" in issues


def test_calibration_boundary_violations_block_candidates() -> None:
    rows = pd.DataFrame(
        [
            {
                "asof_mode": "close_t_minus_1",
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "calibration_method": "platt_logistic_calibration",
                "readiness_category": "usable_probability_candidate",
                "evaluation_row_count": 900,
                "positive_event_count": 40,
                "negative_event_count": 860,
                "mean_expected_calibration_error": 0.02,
                "mean_auc": 0.72,
                "mean_average_precision": 0.22,
                "clustered_uncertainty_width": 0.10,
                "fold_count": 3,
            }
        ]
    )
    evidence = rv.build_validation_metrics(
        readiness_rows=rows,
        fold_rows=pd.DataFrame(),
        bin_rows=pd.DataFrame(),
        clustered_rows=pd.DataFrame(),
        baseline_report={"metric_summary": {"mean_roc_auc": 0.5, "mean_average_precision": 0.1}},
        vol_report={"metric_sanity_summary": {"metric_sanity_fail_count": 0, "known_high_auc_diagnostic_covered": True}},
        policy=rv.default_policy(),
        leakage_total=0,
        boundary_total=1,
    )

    assert evidence["metrics"][0]["validation_status"] == "blocked_by_boundary_or_leakage"


def test_diagnostic_only_rows_cannot_be_validation_pass_candidates() -> None:
    rows = pd.DataFrame(
        [
            {
                "asof_mode": "close_t_minus_1",
                "horizon": 20,
                "threshold_type": "fixed",
                "threshold_value": 0.03,
                "target_usage": "diagnostic_only",
                "calibration_method": "platt_logistic_calibration",
                "readiness_category": "usable_probability_candidate",
                "evaluation_row_count": 1000,
                "positive_event_count": 100,
                "negative_event_count": 900,
                "mean_expected_calibration_error": 0.01,
                "mean_auc": 0.9,
                "mean_average_precision": 0.4,
                "clustered_uncertainty_width": 0.01,
                "fold_count": 3,
            }
        ]
    )
    evidence = rv.build_validation_metrics(
        readiness_rows=rows,
        fold_rows=pd.DataFrame(),
        bin_rows=pd.DataFrame(),
        clustered_rows=pd.DataFrame(),
        baseline_report={"metric_summary": {"mean_roc_auc": 0.5, "mean_average_precision": 0.1}},
        vol_report={"metric_sanity_summary": {"metric_sanity_fail_count": 0, "known_high_auc_diagnostic_covered": True}},
        policy=rv.default_policy(),
        leakage_total=0,
        boundary_total=0,
    )

    assert evidence["metrics"][0]["validation_status"] == "research_only_evidence"


def test_forbidden_output_terms_are_only_present_as_no_action_guard_columns() -> None:
    machine_columns = set(rv.METRIC_COLUMNS)
    allowed_guard_columns = {"no_position_sizing", "no_buy_sell_recommendation", "no_execution_instruction"}
    for column in machine_columns - allowed_guard_columns:
        lower = column.lower()
        assert "buy" not in lower
        assert "sell" not in lower
        assert "sizing" not in lower
        assert "recommendation" not in lower
        assert "decision" not in lower


def test_no_full_score_matrix_outputs_are_declared() -> None:
    output_names = {
        "risk_validation_metrics.csv",
        "downshift_candidate_matrix.csv",
        "risk_validation_clustered_summary.csv",
        "risk_validation_audit_sample.csv",
    }

    assert not any("raw_score_matrix" in name or "calibrated_score_matrix" in name for name in output_names)


def test_no_external_fetch_is_allowed() -> None:
    with pytest.raises(ValueError, match="no-fetch"):
        rv.build_risk_validation_report(no_fetch=False)
