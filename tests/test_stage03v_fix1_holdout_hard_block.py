from __future__ import annotations

from src.evaluation.stage03v_calibration_readiness import validate_wp5_preconditions
from src.evaluation.stage03v_risk_validation import validate_wp6_preconditions


def _stage_doc(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
    }


def _wp4_doc() -> dict:
    doc = _stage_doc()
    doc.update(
        {
            "fixed_threshold_mainline_status": "unchanged_primary_target",
            "training_boundary_violation_counts": {"training_boundary_violation_count_total": 0},
            "boundary_flags": {
                "model_training": "yes",
                "probability_calibration": "no",
                "readiness_assigned": "no",
                "holdout_consumed": "no",
            },
        }
    )
    return doc


def _wp5_doc() -> dict:
    doc = _stage_doc()
    doc.update(
        {
            "fixed_threshold_mainline_status": "unchanged_primary_target",
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
    return {"status": "pass", "fold_count": 1, "purge_violation_count": 0, "embargo_violation_count": 0}


def test_wp5_preconditions_hard_block_any_holdout_consumption_counter() -> None:
    logistic = _wp4_doc()
    logistic["prospective_holdout_rows_evaluated"] = 1

    status, issues = validate_wp5_preconditions(
        target_support=_stage_doc(),
        target_controls=_stage_doc(),
        full_target_audit=_stage_doc(),
        baseline_diagnostics=_stage_doc(),
        vol_scaled_sanity=_stage_doc(),
        logistic_hazard=logistic,
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_holdout_consumed"
    assert "wp4_prospective_holdout_rows_evaluated_not_zero" in issues


def test_wp6_preconditions_hard_block_nested_holdout_consumption_counter() -> None:
    calibration = _wp5_doc()
    calibration["calibration_boundary_violation_counts"]["holdout_rows_used_for_calibration_count"] = 1

    status, issues = validate_wp6_preconditions(
        target_support=_stage_doc(),
        target_controls=_stage_doc(),
        full_target_audit=_stage_doc(),
        baseline_diagnostics=_stage_doc(),
        vol_scaled_sanity=_stage_doc(),
        logistic_hazard=_stage_doc(),
        calibration_readiness=calibration,
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_holdout_consumed"
    assert "wp5_calibration_boundary_violation_counts_holdout_rows_used_for_calibration_count_not_zero" in issues
