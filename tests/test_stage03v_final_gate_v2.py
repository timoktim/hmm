from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.evaluation.stage03v_final_gate_v2 import (
    ALLOWED_FINAL_VERDICTS,
    BOUNDARY_FLAGS,
    DEFAULT_DOWNSHIFT_EXPERIMENT,
    DEFAULT_FOLD_PLAN_V2,
    DEFAULT_LOGISTIC_HAZARD,
    build_final_gate_report,
    build_rerun1_input_manifest,
    default_policy,
    summarize_b2_downshift,
    validate_policy,
)


def _output_paths(tmp_path: Path) -> dict[str, Path]:
    return {
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


def _b2_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "slice_id": "close_t:h5:fixed:0.0300:eligible:platt",
                "baseline_name": "rolling_close_to_close_vol_60",
                "asof_mode": "close_t",
                "horizon": 5,
                "threshold_value": 0.03,
                "arm_pair": "model_minus_baseline",
                "metric": "max_drawdown",
                "delta": 0.04,
                "confidence_interval_low": 0.01,
                "confidence_interval_high": 0.08,
                "ci_status": "pass",
            },
            {
                "slice_id": "close_t:h5:fixed:0.0300:eligible:platt",
                "baseline_name": "rolling_close_to_close_vol_60",
                "asof_mode": "close_t",
                "horizon": 5,
                "threshold_value": 0.03,
                "arm_pair": "model_minus_baseline",
                "metric": "cvar_95",
                "delta": 0.002,
                "confidence_interval_low": 0.001,
                "confidence_interval_high": 0.003,
                "ci_status": "pass",
            },
            {
                "slice_id": "close_t:h5:fixed:0.0300:eligible:platt",
                "baseline_name": "rolling_close_to_close_vol_60",
                "asof_mode": "close_t",
                "horizon": 5,
                "threshold_value": 0.03,
                "arm_pair": "model_minus_baseline",
                "metric": "realized_volatility",
                "delta": 0.001,
                "confidence_interval_low": 0.0001,
                "confidence_interval_high": 0.002,
                "ci_status": "pass",
            },
            {
                "slice_id": "close_t:h5:fixed:0.0300:eligible:platt",
                "baseline_name": "rolling_close_to_close_vol_60",
                "asof_mode": "close_t",
                "horizon": 5,
                "threshold_value": 0.03,
                "arm_pair": "model_minus_baseline",
                "metric": "total_return",
                "delta": 0.25,
                "confidence_interval_low": 0.03,
                "confidence_interval_high": 0.50,
                "ci_status": "pass",
            },
        ]
    )


def test_b2_baseline_superior_primary_risk_separates_secondary_return() -> None:
    summary = summarize_b2_downshift({"status": "pass"}, _b2_metrics())

    assert summary["primary_risk_metric_comparison_status"] == "baseline_superior_on_primary_risk_metrics"
    assert summary["secondary_return_metric_status"] == "model_retains_more_return_secondary_metric"
    assert summary["significant_model_better_primary_risk_delta_count"] == 0
    assert summary["significant_baseline_better_primary_risk_delta_count"] == 3
    assert summary["secondary_return_metric_summary"]["significant_model_positive_return_delta_count"] == 1


def test_failed_rerun1_downshift_blocks_b2_evidence() -> None:
    summary = summarize_b2_downshift({"status": "fail"}, pd.DataFrame())

    assert summary["primary_risk_metric_comparison_status"] == "blocked_missing_b2_evidence"
    assert summary["model_minus_baseline_delta_count"] == 0


def test_policy_uses_registered_120_and_2_holdout_thresholds() -> None:
    policy = default_policy()

    assert validate_policy(policy) == []
    assert policy["prospective_holdout_min_complete_20d_label_trade_dates"] == 120
    assert policy["prospective_holdout_min_market_event_blocks"] == 2


def test_forbidden_60_or_1_holdout_policy_fails_validation() -> None:
    policy = default_policy()
    policy["prospective_holdout_min_complete_20d_label_trade_dates"] = 60
    policy["prospective_holdout_min_market_event_blocks"] = 1

    issues = validate_policy(policy)

    assert "forbidden_active_holdout_minimum_60_days" in issues
    assert "forbidden_active_holdout_minimum_1_block" in issues
    assert "prospective_holdout_min_complete_20d_label_trade_dates_not_120" in issues
    assert "prospective_holdout_min_market_event_blocks_not_2" in issues


def test_missing_v7_db_blocks_without_old_db_fallback(tmp_path: Path) -> None:
    report = build_final_gate_report(
        db_path=tmp_path / "missing_v7.duckdb",
        policy_path=Path("configs/stage03v_final_gate_policy_v2.yaml"),
        output_paths=_output_paths(tmp_path),
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["final_gate_verdict"] == "BLOCKED_INPUTS_NOT_READY"
    assert report["old_db_fallback"] is False
    assert report["source_db_path"].endswith("missing_v7.duckdb")
    assert report["boundary_flags"]["external_data_fetch"] == "no"


def test_rerun1_input_manifest_points_to_v2_and_downshift_artifacts() -> None:
    report = {
        "blocking_reasons": [],
        "rerun1_fold_plan_v2_status": "pass",
        "rerun1_magnitude_gate_status": "pass",
        "trial_accounting_invalidation_recorded": "yes",
        "rerun1_logistic_hazard_status": "pass",
        "rerun1_calibration_readiness_status": "pass",
        "rerun1_downshift_experiment_status": "pass",
        "created_at": "2026-06-12T00:00:00+00:00",
    }

    manifest = build_rerun1_input_manifest(report)

    assert manifest["inputs"]["fold_plan_v2"]["path"] == "reports/stage03v/purge_embargo_fold_plan_v2.json"
    assert manifest["inputs"]["logistic_hazard"]["path"] == "reports/stage03v/logistic_hazard_report.json"
    assert manifest["inputs"]["downshift_experiment"]["path"] == "reports/stage03v/downshift_experiment_report.json"
    assert "reports/stage03v/downshift_research_report.json" in manifest["legacy_invalidated_inputs_forbidden_as_evidence"]
    assert manifest["legacy_invalidated_inputs_used_as_final_evidence"] == []


def test_default_verdict_and_boundaries_are_contractual() -> None:
    assert "PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE" in ALLOWED_FINAL_VERDICTS
    assert DEFAULT_FOLD_PLAN_V2.as_posix().endswith("purge_embargo_fold_plan_v2.json")
    assert DEFAULT_LOGISTIC_HAZARD.as_posix().endswith("logistic_hazard_report.json")
    assert DEFAULT_DOWNSHIFT_EXPERIMENT.as_posix().endswith("downshift_experiment_report.json")
    assert BOUNDARY_FLAGS["model_training"] == "no"
    assert BOUNDARY_FLAGS["probability_recalibration"] == "no"
    assert BOUNDARY_FLAGS["readiness_reassigned"] == "no"
    assert BOUNDARY_FLAGS["prospective_holdout_performance_consumed"] == "no"
    assert BOUNDARY_FLAGS["trading_or_decision_output"] == "no"
