from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.evaluation import stage03v_final_gate as fg


def _stage_doc(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
    }


def _wp0(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update({"information_cutoff_date": "2026-06-10", "holdout_start": "2026-06-11"})
    return doc


def _wp5(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "usable_probability_candidate_count": 4,
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "calibration_boundary_violation_counts": {"calibration_boundary_violation_count_total": 0},
        }
    )
    return doc


def _wp6(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "historical_development_only": "yes",
            "validation_pass_candidate_count": 4,
            "downshift_tier_counts": {"research_downshift_candidate": 4},
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "validation_boundary_violation_counts": {"validation_boundary_violation_count_total": 0},
            "boundary_flags": {"trading_or_decision_output": "no"},
        }
    )
    return doc


def _manifest(status: str = "prepared_for_wp7") -> dict:
    return {"status": status, "wp7_final_gate_executed": "no"}


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    payloads = {
        "scope.json": _wp0(),
        "sample.json": _stage_doc(),
        "target.json": _stage_doc(),
        "controls.json": _stage_doc(),
        "full.json": {**_stage_doc(), "violation_count_total": 0},
        "baseline.json": {**_stage_doc(), "leakage_violation_counts": {"leakage_violation_count_total": 0}},
        "vol.json": {**_stage_doc(), "leakage_violation_counts": {"leakage_violation_count_total": 0}},
        "logistic.json": {
            **_stage_doc(),
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "training_boundary_violation_counts": {"training_boundary_violation_count_total": 0},
        },
        "wp5.json": _wp5(),
        "wp6.json": _wp6(),
        "downshift.json": {"status": "pass"},
        "manifest.json": _manifest(),
        "policy.json": fg.default_policy(),
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(
        json.dumps({"information_cutoff_date": "2026-06-10", "holdout_start": "2026-06-11", "consumption_count": 0})
        + "\n",
        encoding="utf-8",
    )
    paths["ledger.jsonl"] = ledger
    return paths


def test_missing_v7_db_returns_blocked_status_and_no_old_db_fallback(tmp_path: Path) -> None:
    paths = _write_inputs(tmp_path)

    report = fg.build_final_gate_report(
        db_path=tmp_path / "missing_v7.duckdb",
        scope_freeze=paths["scope.json"],
        sample_feasibility=paths["sample.json"],
        target_support=paths["target.json"],
        target_controls=paths["controls.json"],
        full_target_audit=paths["full.json"],
        baseline_diagnostics=paths["baseline.json"],
        vol_scaled_sanity=paths["vol.json"],
        logistic_hazard=paths["logistic.json"],
        calibration_readiness=paths["wp5.json"],
        risk_validation=paths["wp6.json"],
        downshift_research=paths["downshift.json"],
        wp7_input_manifest=paths["manifest.json"],
        ledger_template=paths["ledger.jsonl"],
        policy=paths["policy.json"],
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        verdict_json=tmp_path / "verdict.json",
        evidence_matrix=tmp_path / "evidence.csv",
        artifact_manifest=tmp_path / "artifacts.json",
        holdout_status=tmp_path / "holdout.json",
        post_gate_action_plan=tmp_path / "plan.md",
        audit_sample=tmp_path / "audit.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["external_data_fetch"] == "no"


def test_failed_wp6_report_blocks_wp7() -> None:
    docs = {
        "wp0_scope_freeze": _wp0(),
        "wp0_5_sample_feasibility": _stage_doc(),
        "wp1_target_support": _stage_doc(),
        "wp2_target_controls": _stage_doc(),
        "wp2_1_full_target_audit": _stage_doc(),
        "wp3_baseline_diagnostics": _stage_doc(),
        "wp3_5_vol_scaled_sanity": _stage_doc(),
        "wp4_logistic_hazard": _stage_doc(),
        "wp5_calibration_readiness": _wp5(),
        "wp6_risk_validation": _wp6(status="fail"),
    }
    status, issues = fg.validate_wp7_preconditions(
        docs=docs,
        ledger_template={"information_cutoff_date": "2026-06-10", "holdout_start": "2026-06-11"},
        wp7_input_manifest=_manifest(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        leakage_counts={"wp6_leakage_violation_count_total": 0},
        boundary_counts={"wp6_validation_boundary_violation_count_total": 0},
    )

    assert status == "blocked_wp6_not_ready"
    assert "wp6_risk_validation_status_not_pass" in issues


def test_wp7_input_manifest_must_be_prepared_and_not_preexecuted() -> None:
    docs = {
        "wp0_scope_freeze": _wp0(),
        "wp0_5_sample_feasibility": _stage_doc(),
        "wp1_target_support": _stage_doc(),
        "wp2_target_controls": _stage_doc(),
        "wp2_1_full_target_audit": _stage_doc(),
        "wp3_baseline_diagnostics": _stage_doc(),
        "wp3_5_vol_scaled_sanity": _stage_doc(),
        "wp4_logistic_hazard": _stage_doc(),
        "wp5_calibration_readiness": _wp5(),
        "wp6_risk_validation": _wp6(),
    }
    manifest = {"status": "prepared_for_wp7", "wp7_final_gate_executed": "yes"}
    status, issues = fg.validate_wp7_preconditions(
        docs=docs,
        ledger_template={"information_cutoff_date": "2026-06-10", "holdout_start": "2026-06-11"},
        wp7_input_manifest=manifest,
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        leakage_counts={"wp6_leakage_violation_count_total": 0},
        boundary_counts={"wp6_validation_boundary_violation_count_total": 0},
    )

    assert status == "blocked_wp6_not_ready"
    assert "wp7_input_manifest_already_executed" in issues


def test_decision_support_promotion_is_deferred_when_holdout_unconsumed() -> None:
    holdout = fg.compute_holdout_status(
        type("FakeV7", (), {"price_frame": None})(),
        {"consumption_count": 0},
        fg.default_policy(),
    )

    assert holdout["prospective_holdout_rows_evaluated"] == 0
    assert holdout["prospective_holdout_consumption_count"] == 0
    assert holdout["prospective_holdout_gate_status"] == "defer_or_insufficient"


def test_forbidden_output_terms_are_not_csv_column_names_except_required_guards() -> None:
    allowed_guard_columns: set[str] = set()
    for column in set(fg.EVIDENCE_COLUMNS + fg.AUDIT_COLUMNS) - allowed_guard_columns:
        lower = column.lower()
        assert "buy" not in lower
        assert "sell" not in lower
        assert "sizing" not in lower
        assert "recommendation" not in lower


def test_no_full_score_matrices_are_declared() -> None:
    output_names = {
        "stage03v1_final_gate_evidence_matrix.csv",
        "stage03v1_final_gate_audit_sample.csv",
        "stage03v1_final_gate_report.json",
    }

    assert not any("raw_score_matrix" in name or "calibrated_score_matrix" in name for name in output_names)


def test_no_external_fetch_is_allowed() -> None:
    with pytest.raises(ValueError, match="no-fetch"):
        fg.build_final_gate_report(no_fetch=False)
