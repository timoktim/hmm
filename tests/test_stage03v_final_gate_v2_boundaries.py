from __future__ import annotations

from pathlib import Path

from src.evaluation.stage03v_final_gate_v2 import (
    BOUNDARY_FLAGS,
    FORBIDDEN_LEGACY_INPUTS,
    build_artifact_manifest,
    default_policy,
    summarize_holdout,
    validate_policy,
)


def test_legacy_invalidated_wp6_tier_reports_are_forbidden_as_evidence() -> None:
    policy = default_policy()

    forbidden = set(policy["legacy_invalidated_inputs_forbidden_as_evidence"])

    assert set(FORBIDDEN_LEGACY_INPUTS).issubset(forbidden)
    assert "reports/stage03v/risk_validation_report.json" in forbidden
    assert "reports/stage03v/downshift_research_report.json" in forbidden
    assert "reports/stage03v/wp7_final_gate_input_manifest.json" in forbidden


def test_policy_rejects_non_rerun1_required_inputs() -> None:
    policy = default_policy()
    policy["required_inputs"]["fold_plan"] = "reports/stage03v/purge_embargo_fold_plan.json"
    policy["required_inputs"]["downshift_experiment"] = "reports/stage03v/downshift_research_report.json"

    issues = validate_policy(policy)

    assert "required_input_fold_plan_not_rerun1" in issues
    assert "required_input_downshift_experiment_not_rerun1" in issues


def test_holdout_status_defers_without_consuming_performance() -> None:
    holdout = summarize_holdout(
        v7_price_frame=__import__("pandas").DataFrame(),
        ledger={"consumption_count": 0},
        policy=default_policy(),
    )

    assert holdout["prospective_holdout_complete_20d_label_trade_dates"] == 0
    assert holdout["prospective_holdout_market_event_block_count"] == 0
    assert holdout["prospective_holdout_rows_evaluated"] == 0
    assert holdout["prospective_holdout_consumption_count"] == 0
    assert holdout["prospective_holdout_gate_status"] == "defer_or_insufficient"
    assert holdout["prospective_holdout_performance_consumed"] == "no"


def test_artifact_manifest_does_not_commit_full_score_or_exposure_matrices(tmp_path: Path) -> None:
    report = {
        "status": "pass",
        "created_at": "2026-06-12T00:00:00+00:00",
        "boundary_flags": dict(BOUNDARY_FLAGS),
    }
    paths = {
        "output": tmp_path / "report.md",
        "summary_json": tmp_path / "report.json",
        "verdict_json": tmp_path / "verdict.json",
        "evidence_matrix": tmp_path / "evidence.csv",
        "artifact_manifest": tmp_path / "artifacts.json",
        "rerun1_input_manifest": tmp_path / "inputs.json",
        "holdout_status": tmp_path / "holdout.json",
        "post_gate_action_plan": tmp_path / "actions.md",
        "audit_sample": tmp_path / "audit.csv",
    }

    manifest = build_artifact_manifest(report, paths)
    generated = " ".join(str(value) for value in manifest["generated_artifacts"].values())

    assert "raw_score_matrix" not in generated
    assert "calibrated_score_matrix" not in generated
    assert "exposure_matrix" not in generated
    assert manifest["boundary_flags"]["full_raw_score_matrix_committed"] == "no"
    assert manifest["boundary_flags"]["full_calibrated_score_matrix_committed"] == "no"
    assert manifest["boundary_flags"]["full_exposure_matrix_committed"] == "no"


def test_no_trading_or_decision_output_flags_are_emitted() -> None:
    assert BOUNDARY_FLAGS["trading_or_decision_output"] == "no"
    assert BOUNDARY_FLAGS["final_gate_executed"] == "yes"
    assert BOUNDARY_FLAGS["stage03v2_implemented"] == "no"
    assert BOUNDARY_FLAGS["stage03v3_implemented"] == "no"
