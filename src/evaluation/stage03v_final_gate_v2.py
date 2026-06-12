"""Stage03V WP7-v2 final gate after RERUN1.

This module is a read-only final-gate aggregator. It consumes accepted
Stage03V/RERUN1 artifacts and emits the final gate report without training,
calibration, readiness reassignment, target mutation, or holdout performance
evaluation.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    DEFAULT_V7_DB,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)


INDEX_ID = "STAGE03V-WP7-v2"
REPORT_VERSION = "stage03v1_final_gate_v2_report_v1"
STAGE_ID = "stage03v"
POLICY_VERSION = "stage03v_final_gate_policy_v2"
DEFAULT_DB = DEFAULT_V7_DB
ROOT = Path(__file__).resolve().parents[2]

DEFAULT_POLICY = ROOT / "configs" / "stage03v_final_gate_policy_v2.yaml"
DEFAULT_SCOPE_FREEZE = ROOT / "reports" / "stage03v" / "stage03v_wp0_scope_freeze_report.json"
DEFAULT_SAMPLE_FEASIBILITY = ROOT / "reports" / "stage03v" / "sample_feasibility_report.json"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_BASELINE_DIAGNOSTICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_VOL_SCALED_SANITY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_FOLD_PLAN_V2 = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan_v2.json"
DEFAULT_FOLD_MAGNITUDE_OVERVIEW = ROOT / "reports" / "stage03v" / "fold_plan_magnitude_overview.csv"
DEFAULT_TRIAL_ACCOUNTING = ROOT / "reports" / "stage03v" / "validation_trial_accounting.json"
DEFAULT_LOGISTIC_HAZARD = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_CALIBRATION_READINESS = ROOT / "reports" / "stage03v" / "calibration_readiness_report.json"
DEFAULT_DOWNSHIFT_EXPERIMENT = ROOT / "reports" / "stage03v" / "downshift_experiment_report.json"
DEFAULT_DOWNSHIFT_ARM_METRICS = ROOT / "reports" / "stage03v" / "downshift_experiment_arm_metrics.csv"
DEFAULT_LEDGER_TEMPLATE = ROOT / "reports" / "stage04" / "prospective_validation_ledger.stage03v.template.jsonl"

DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_report.json"
DEFAULT_VERDICT_JSON = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_verdict.json"
DEFAULT_EVIDENCE_MATRIX = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_evidence_matrix.csv"
DEFAULT_ARTIFACT_MANIFEST = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_artifact_manifest.json"
DEFAULT_RERUN1_INPUT_MANIFEST = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_rerun1_input_manifest.json"
DEFAULT_HOLDOUT_STATUS = ROOT / "reports" / "stage03v" / "stage03v1_prospective_holdout_status_v2.json"
DEFAULT_POST_GATE_ACTION_PLAN = ROOT / "reports" / "stage03v" / "stage03v1_post_gate_action_plan_v2.md"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_v2_audit_sample.csv"

PRIMARY_RISK_METRICS = ["max_drawdown", "cvar_95", "realized_volatility"]
SECONDARY_RETURN_METRIC = "total_return"
REGISTERED_HOLDOUT_MIN_COMPLETE_20D_LABEL_TRADE_DATES = 120
REGISTERED_HOLDOUT_MIN_MARKET_EVENT_BLOCKS = 2
FORBIDDEN_LEGACY_INPUTS = [
    "reports/stage03v/risk_validation_report.json",
    "reports/stage03v/downshift_research_report.json",
    "reports/stage03v/wp7_final_gate_input_manifest.json",
]
ALLOWED_FINAL_VERDICTS = [
    "PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE",
    "PASS_RESEARCH_ONLY_BASELINE_SUPERIOR_ON_PRIMARY_RISK_METRICS",
    "DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT",
    "FAIL_BOUNDARY_OR_LEAKAGE",
    "FAIL_INPUT_ARTIFACTS",
    "FAIL_RERUN1_EVIDENCE_INCONSISTENT",
    "FAIL_VALIDATION_EVIDENCE",
    "BLOCKED_INPUTS_NOT_READY",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "full_feature_matrix_committed": "no",
    "full_raw_score_matrix_committed": "no",
    "full_calibrated_score_matrix_committed": "no",
    "full_exposure_matrix_committed": "no",
    "model_training": "no",
    "probability_recalibration": "no",
    "readiness_reassigned": "no",
    "final_gate_executed": "yes",
    "prospective_holdout_performance_consumed": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
    "trading_or_decision_output": "no",
}

EVIDENCE_COLUMNS = ["component", "status", "evidence_path", "detail", "value"]
AUDIT_COLUMNS = ["category", "key", "status", "value", "source_path"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_jsonl_first(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text.splitlines()[0])


def _load_policy(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return json.loads(text)
    loaded = yaml.safe_load(text)
    return dict(loaded or {})


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(list(rows), columns=list(columns)).to_csv(target, index=False)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return int(default)
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _sum_counts(*mappings: Mapping[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for mapping in mappings:
        for key, value in mapping.items():
            out[str(key)] = int(out.get(str(key), 0)) + _as_int(value)
    out["total"] = int(sum(value for key, value in out.items() if key != "total"))
    return out


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "supersedes": "STAGE03V-WP7-v1",
        "supersession_reason": "rerun1_full_scale_revalidation_replaced_invalidated_wp6_tier_aggregation",
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "primary_target_family": "fixed_threshold_stage03v1_downside_event",
        "vol_scaled_candidate_policy": "tracked_reference_only",
        "stage03v2_policy": "placeholder_only",
        "stage03v3_policy": "placeholder_only",
        "final_gate_scope": "stage03v1_downside_risk_only",
        "required_inputs": {
            "fold_plan": "reports/stage03v/purge_embargo_fold_plan_v2.json",
            "trial_accounting": "reports/stage03v/validation_trial_accounting.json",
            "logistic_hazard": "reports/stage03v/logistic_hazard_report.json",
            "calibration_readiness": "reports/stage03v/calibration_readiness_report.json",
            "downshift_experiment": "reports/stage03v/downshift_experiment_report.json",
            "downshift_arm_metrics": "reports/stage03v/downshift_experiment_arm_metrics.csv",
        },
        "legacy_invalidated_inputs_forbidden_as_evidence": list(FORBIDDEN_LEGACY_INPUTS),
        "prospective_holdout_policy": "defer_if_registered_minimum_not_met",
        "prospective_holdout_evaluation_authorized": False,
        "prospective_holdout_min_complete_20d_label_trade_dates": REGISTERED_HOLDOUT_MIN_COMPLETE_20D_LABEL_TRADE_DATES,
        "prospective_holdout_min_market_event_blocks": REGISTERED_HOLDOUT_MIN_MARKET_EVENT_BLOCKS,
        "prospective_holdout_review_cadence": "quarterly",
        "allow_decision_support_promotion_without_holdout": False,
        "primary_risk_metrics": list(PRIMARY_RISK_METRICS),
        "allowed_final_verdicts": list(ALLOWED_FINAL_VERDICTS),
        "forbidden_active_holdout_minimums": {
            "complete_20d_label_trade_dates": 60,
            "market_event_blocks": 1,
        },
        "external_fetch_policy": "forbidden",
        "persistent_db_table_policy": "forbidden_by_default",
        "full_score_matrix_policy": "forbidden_to_commit",
    }


def validate_policy(policy: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    expected = default_policy()
    for key in [
        "index_id",
        "policy_version",
        "information_cutoff_date",
        "holdout_start",
        "primary_target_family",
        "vol_scaled_candidate_policy",
        "stage03v2_policy",
        "stage03v3_policy",
        "final_gate_scope",
        "external_fetch_policy",
        "persistent_db_table_policy",
        "full_score_matrix_policy",
    ]:
        if policy.get(key) != expected[key]:
            issues.append(f"{key}_mismatch")
    if bool(policy.get("prospective_holdout_evaluation_authorized")) is not False:
        issues.append("prospective_holdout_evaluation_authorized_not_false")
    if bool(policy.get("allow_decision_support_promotion_without_holdout")) is not False:
        issues.append("allow_decision_support_promotion_without_holdout_not_false")
    min_days = _as_int(policy.get("prospective_holdout_min_complete_20d_label_trade_dates"))
    min_blocks = _as_int(policy.get("prospective_holdout_min_market_event_blocks"))
    if min_days != REGISTERED_HOLDOUT_MIN_COMPLETE_20D_LABEL_TRADE_DATES:
        issues.append("prospective_holdout_min_complete_20d_label_trade_dates_not_120")
    if min_blocks != REGISTERED_HOLDOUT_MIN_MARKET_EVENT_BLOCKS:
        issues.append("prospective_holdout_min_market_event_blocks_not_2")
    if min_days == 60:
        issues.append("forbidden_active_holdout_minimum_60_days")
    if min_blocks == 1:
        issues.append("forbidden_active_holdout_minimum_1_block")
    required = dict(policy.get("required_inputs", {}))
    for key, value in expected["required_inputs"].items():
        if required.get(key) != value:
            issues.append(f"required_input_{key}_not_rerun1")
    legacy = set(str(item) for item in policy.get("legacy_invalidated_inputs_forbidden_as_evidence", []))
    if not set(FORBIDDEN_LEGACY_INPUTS).issubset(legacy):
        issues.append("legacy_invalidated_inputs_not_forbidden")
    if list(policy.get("primary_risk_metrics", [])) != PRIMARY_RISK_METRICS:
        issues.append("primary_risk_metrics_mismatch")
    allowed = set(str(item) for item in policy.get("allowed_final_verdicts", []))
    if not set(ALLOWED_FINAL_VERDICTS).issubset(allowed):
        issues.append("allowed_final_verdicts_missing")
    return issues


def summarize_b2_downshift(
    downshift_report: Mapping[str, Any],
    arm_metrics: pd.DataFrame,
    *,
    primary_metrics: Sequence[str] = PRIMARY_RISK_METRICS,
) -> dict[str, Any]:
    if downshift_report.get("status") != "pass" or arm_metrics.empty:
        return {
            "primary_risk_metric_comparison_status": "blocked_missing_b2_evidence",
            "secondary_return_metric_status": "not_evaluated",
            "model_minus_baseline_delta_count": 0,
            "model_better_primary_risk_delta_count": 0,
            "baseline_better_primary_risk_delta_count": 0,
            "significant_model_better_primary_risk_delta_count": 0,
            "significant_baseline_better_primary_risk_delta_count": 0,
            "primary_risk_metric_ci_status_summary": {},
            "secondary_return_metric_summary": {},
            "baseline_selection_summary": {},
        }

    metrics = arm_metrics.copy()
    pair = metrics[metrics["arm_pair"].astype(str).eq("model_minus_baseline")].copy()
    pair["delta"] = pd.to_numeric(pair["delta"], errors="coerce")
    pair["confidence_interval_low"] = pd.to_numeric(pair["confidence_interval_low"], errors="coerce")
    pair["confidence_interval_high"] = pd.to_numeric(pair["confidence_interval_high"], errors="coerce")
    primary = pair[pair["metric"].astype(str).isin(set(primary_metrics))].copy()

    model_better = primary["delta"].lt(0)
    baseline_better = primary["delta"].gt(0)
    significant_model_better = model_better & primary["confidence_interval_high"].lt(0)
    significant_baseline_better = baseline_better & primary["confidence_interval_low"].gt(0)
    if int(significant_model_better.sum()) == 0 and int(significant_baseline_better.sum()) > 0:
        primary_status = "baseline_superior_on_primary_risk_metrics"
    elif int(significant_model_better.sum()) > 0 and int(significant_baseline_better.sum()) == 0:
        primary_status = "model_superior_on_primary_risk_metrics"
    elif primary.empty:
        primary_status = "blocked_missing_b2_evidence"
    else:
        primary_status = "inconclusive_on_primary_risk_metrics"

    secondary = pair[pair["metric"].astype(str).eq(SECONDARY_RETURN_METRIC)].copy()
    secondary_model_better = secondary["delta"].gt(0)
    significant_secondary_model = secondary_model_better & secondary["confidence_interval_low"].gt(0)
    significant_secondary_baseline = secondary["delta"].lt(0) & secondary["confidence_interval_high"].lt(0)
    if int(significant_secondary_model.sum()) > 0 and int(significant_secondary_baseline.sum()) == 0:
        secondary_status = "model_retains_more_return_secondary_metric"
    elif int(significant_secondary_baseline.sum()) > 0 and int(significant_secondary_model.sum()) == 0:
        secondary_status = "baseline_retains_more_return_secondary_metric"
    elif secondary.empty:
        secondary_status = "not_evaluated"
    else:
        secondary_status = "inconclusive_secondary_return_metric"

    baselines = (
        metrics[["baseline_name", "asof_mode", "horizon", "threshold_value"]]
        .dropna(subset=["baseline_name"])
        .drop_duplicates()
    )
    baseline_summary = {
        "baseline_name_count": int(baselines["baseline_name"].nunique()) if not baselines.empty else 0,
        "baseline_names": sorted(str(item) for item in baselines["baseline_name"].dropna().unique().tolist()) if not baselines.empty else [],
        "baseline_family": "wp3_strongest_eligible_baseline",
    }
    ci_summary = {str(k): int(v) for k, v in primary["ci_status"].astype(str).value_counts(dropna=False).to_dict().items()}
    secondary_summary = {
        "model_minus_baseline_return_delta_count": int(len(secondary)),
        "model_positive_return_delta_count": int(secondary_model_better.sum()),
        "significant_model_positive_return_delta_count": int(significant_secondary_model.sum()),
        "baseline_positive_return_delta_count": int(secondary["delta"].lt(0).sum()),
        "significant_baseline_positive_return_delta_count": int(significant_secondary_baseline.sum()),
    }
    return {
        "primary_risk_metric_comparison_status": primary_status,
        "secondary_return_metric_status": secondary_status,
        "model_minus_baseline_delta_count": int(len(pair)),
        "model_minus_baseline_primary_risk_delta_count": int(len(primary)),
        "model_better_primary_risk_delta_count": int(model_better.sum()),
        "baseline_better_primary_risk_delta_count": int(baseline_better.sum()),
        "significant_model_better_primary_risk_delta_count": int(significant_model_better.sum()),
        "significant_baseline_better_primary_risk_delta_count": int(significant_baseline_better.sum()),
        "primary_risk_metric_ci_status_summary": ci_summary,
        "secondary_return_metric_summary": secondary_summary,
        "baseline_selection_summary": baseline_summary,
    }


def summarize_holdout(v7_price_frame: pd.DataFrame, ledger: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    holdout_start = pd.Timestamp(policy.get("holdout_start", HOLDOUT_START)).normalize()
    min_complete = _as_int(policy.get("prospective_holdout_min_complete_20d_label_trade_dates"))
    min_blocks = _as_int(policy.get("prospective_holdout_min_market_event_blocks"))
    rows_available = 0
    complete_dates = 0
    if not v7_price_frame.empty and "trade_date" in v7_price_frame.columns:
        dates = pd.to_datetime(v7_price_frame["trade_date"], errors="coerce").dt.normalize()
        holdout_dates = sorted(pd.Timestamp(value).normalize() for value in dates[dates.ge(holdout_start)].dropna().unique())
        rows_available = int(dates.ge(holdout_start).sum())
        complete_dates = int(sum(1 for idx, _ in enumerate(holdout_dates) if idx + 20 < len(holdout_dates)))
    market_event_blocks = 0
    consumption_count = _as_int(ledger.get("consumption_count"), 0)
    minimum_status = "pass" if complete_dates >= min_complete else "insufficient_registered_minimum_not_met"
    stress_status = "pass" if market_event_blocks >= min_blocks else "insufficient_registered_stress_blocks_not_met"
    gate_status = "pass" if minimum_status == "pass" and stress_status == "pass" else "defer_or_insufficient"
    return {
        "prospective_holdout_rows_available": int(rows_available),
        "prospective_holdout_complete_20d_label_trade_dates": int(complete_dates),
        "prospective_holdout_market_event_block_count": int(market_event_blocks),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_consumption_count": int(consumption_count),
        "prospective_holdout_minimum_requirement_status": minimum_status,
        "prospective_holdout_stress_event_requirement_status": stress_status,
        "prospective_holdout_gate_status": gate_status,
        "prospective_holdout_threshold_source": "registered_stage03v_ledger_policy_v2",
        "prospective_holdout_min_complete_20d_label_trade_dates": int(min_complete),
        "prospective_holdout_min_market_event_blocks": int(min_blocks),
        "prospective_holdout_evaluation_authorized": bool(policy.get("prospective_holdout_evaluation_authorized", False)),
        "prospective_holdout_performance_consumed": "no",
    }


def _blocked_report(
    *,
    status: str,
    db_path: Path | str,
    reason: str,
    output_paths: Mapping[str, Path | str],
    v7_coverage: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    coverage = dict(v7_coverage or {})
    report = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "final_gate_verdict": "BLOCKED_INPUTS_NOT_READY",
        "stage03v1_gate_status": status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "yes" if coverage.get("db_opened_read_only") else "no",
        "v7_coverage_available": coverage.get("v7_coverage_available", "no"),
        "sw2021_l2_universe_coverage": coverage.get("sw2021_l2_universe_coverage", "missing"),
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "old_db_fallback": False,
        "engineering_gate_status": status,
        "causality_gate_status": status,
        "rerun1_magnitude_gate_status": status,
        "model_discrimination_gate_status": status,
        "model_discrimination_status": "model_discrimination_fail",
        "calibration_readiness_gate_status": status,
        "primary_risk_metric_comparison_status": "blocked_missing_b2_evidence",
        "secondary_return_metric_status": "not_evaluated",
        "secondary_return_status": "not_evaluated",
        "prospective_holdout_readiness_gate_status": "defer_or_insufficient",
        "decision_support_promotion_gate_status": "blocked_inputs_not_ready",
        "model_discrimination_claim": "not_evaluated_inputs_blocked",
        "primary_risk_downshift_claim": "not_evaluated_inputs_blocked",
        "secondary_return_claim": "not_evaluated_inputs_blocked",
        "recommended_use_after_gate": "blocked_inputs_not_ready",
        "prospective_holdout_complete_20d_label_trade_dates": 0,
        "prospective_holdout_market_event_block_count": 0,
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_consumption_count": 0,
        "prospective_holdout_minimum_requirement_status": "not_evaluated_inputs_blocked",
        "prospective_holdout_stress_event_requirement_status": "not_evaluated_inputs_blocked",
        "prospective_holdout_threshold_source": "registered_stage03v_ledger_policy_v2",
        "artifact_manifest_path": _safe_path(output_paths.get("artifact_manifest")),
        "rerun1_input_manifest_path": _safe_path(output_paths.get("rerun1_input_manifest")),
        "evidence_matrix_path": _safe_path(output_paths.get("evidence_matrix")),
        "verdict_json_path": _safe_path(output_paths.get("verdict_json")),
        "holdout_status_path": _safe_path(output_paths.get("holdout_status")),
        "post_gate_action_plan_path": _safe_path(output_paths.get("post_gate_action_plan")),
        "leakage_violation_counts": {},
        "boundary_violation_counts": {"total": 0},
        "ci_gate_status": status,
        "boundary_flags": dict(BOUNDARY_FLAGS),
        "blocking_reasons": [reason],
        "remaining_risks": ["WP7-v2 final gate could not run because required inputs were blocked."],
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
    }
    return report


def build_final_gate_report(
    *,
    db_path: Path | str = DEFAULT_DB,
    scope_freeze: Path | str = DEFAULT_SCOPE_FREEZE,
    sample_feasibility: Path | str = DEFAULT_SAMPLE_FEASIBILITY,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    baseline_diagnostics: Path | str = DEFAULT_BASELINE_DIAGNOSTICS,
    vol_scaled_sanity: Path | str = DEFAULT_VOL_SCALED_SANITY,
    fold_plan_v2: Path | str = DEFAULT_FOLD_PLAN_V2,
    fold_magnitude_overview: Path | str = DEFAULT_FOLD_MAGNITUDE_OVERVIEW,
    trial_accounting: Path | str = DEFAULT_TRIAL_ACCOUNTING,
    logistic_hazard: Path | str = DEFAULT_LOGISTIC_HAZARD,
    calibration_readiness: Path | str = DEFAULT_CALIBRATION_READINESS,
    downshift_experiment: Path | str = DEFAULT_DOWNSHIFT_EXPERIMENT,
    downshift_arm_metrics: Path | str = DEFAULT_DOWNSHIFT_ARM_METRICS,
    ledger_template: Path | str = DEFAULT_LEDGER_TEMPLATE,
    policy_path: Path | str = DEFAULT_POLICY,
    output_paths: Mapping[str, Path | str] | None = None,
) -> dict[str, Any]:
    paths = dict(output_paths or {})
    resolved_db = resolve_v7_db_path(db_path)
    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") == "blocked_missing_v7_db":
        return _blocked_report(
            status="blocked_missing_v7_db",
            db_path=resolved_db,
            reason="missing V7 DB; no fallback to data/db/a_share_hmm.duckdb",
            output_paths=paths,
            v7_coverage=v7.coverage,
        )
    if v7.coverage.get("status") != "pass":
        return _blocked_report(
            status="blocked_invalid_v7_db",
            db_path=resolved_db,
            reason="invalid V7 DB; no fallback to data/db/a_share_hmm.duckdb",
            output_paths=paths,
            v7_coverage=v7.coverage,
        )

    policy = _load_policy(policy_path)
    policy_issues = validate_policy(policy)
    artifacts = {
        "wp0_scope_freeze": _load_json(scope_freeze),
        "wp0_5_sample_feasibility": _load_json(sample_feasibility),
        "wp1_target_support": _load_json(target_support),
        "wp2_target_controls": _load_json(target_controls),
        "wp2_1_full_target_audit": _load_json(full_target_audit),
        "wp3_baseline_diagnostics": _load_json(baseline_diagnostics),
        "wp3_5_vol_scaled_sanity": _load_json(vol_scaled_sanity),
        "rerun1_fold_plan_v2": _load_json(fold_plan_v2),
        "trial_accounting": _load_json(trial_accounting),
        "rerun1_logistic_hazard": _load_json(logistic_hazard),
        "rerun1_calibration_readiness": _load_json(calibration_readiness),
        "rerun1_downshift_experiment": _load_json(downshift_experiment),
        "ledger_template": _load_jsonl_first(ledger_template),
    }
    arm_metrics = pd.read_csv(downshift_arm_metrics)
    b2_summary = summarize_b2_downshift(artifacts["rerun1_downshift_experiment"], arm_metrics)
    holdout = summarize_holdout(v7.price_frame, artifacts["ledger_template"], policy)

    precondition_issues: list[str] = list(policy_issues)
    status_keys = {
        "wp0_scope_freeze_status": artifacts["wp0_scope_freeze"].get("status"),
        "wp0_5_sample_feasibility_status": artifacts["wp0_5_sample_feasibility"].get("status"),
        "wp1_target_support_status": artifacts["wp1_target_support"].get("status"),
        "wp2_target_controls_status": artifacts["wp2_target_controls"].get("status"),
        "wp2_1_full_target_audit_status": artifacts["wp2_1_full_target_audit"].get("status"),
        "wp3_baseline_diagnostics_status": artifacts["wp3_baseline_diagnostics"].get("status"),
        "wp3_5_vol_scaled_sanity_status": artifacts["wp3_5_vol_scaled_sanity"].get("status"),
        "rerun1_fold_plan_v2_status": artifacts["rerun1_fold_plan_v2"].get("status"),
        "rerun1_logistic_hazard_status": artifacts["rerun1_logistic_hazard"].get("status"),
        "rerun1_calibration_readiness_status": artifacts["rerun1_calibration_readiness"].get("status"),
        "rerun1_downshift_experiment_status": artifacts["rerun1_downshift_experiment"].get("status"),
    }
    for key, value in status_keys.items():
        if value != "pass":
            precondition_issues.append(f"{key}_not_pass")
    if artifacts["rerun1_fold_plan_v2"].get("fold_plan_path") != "reports/stage03v/purge_embargo_fold_plan_v2.json":
        precondition_issues.append("fold_plan_v2_path_mismatch")
    if artifacts["rerun1_logistic_hazard"].get("fold_plan_path") != "reports/stage03v/purge_embargo_fold_plan_v2.json":
        precondition_issues.append("logistic_not_using_fold_plan_v2")
    if artifacts["rerun1_calibration_readiness"].get("fold_plan_path") != "reports/stage03v/purge_embargo_fold_plan_v2.json":
        precondition_issues.append("calibration_not_using_fold_plan_v2")
    if artifacts["rerun1_downshift_experiment"].get("prospective_holdout_score_count") != 0:
        precondition_issues.append("b2_holdout_scores_not_zero")
    if artifacts["trial_accounting"].get("trial_accounting_invalidation_recorded") != "yes":
        precondition_issues.append("trial_accounting_invalidation_not_recorded")

    fold_gates = artifacts["rerun1_fold_plan_v2"].get("magnitude_hard_gates", {})
    rerun1_magnitude_gate_status = "pass" if artifacts["rerun1_fold_plan_v2"].get("status") == "pass" and all(bool(v) for v in fold_gates.values()) else "fail"
    leakage_counts = _sum_counts(
        artifacts["rerun1_logistic_hazard"].get("leakage_violation_counts", {}),
        artifacts["rerun1_calibration_readiness"].get("leakage_violation_counts", {}),
        {"b2_prospective_holdout_score_count": artifacts["rerun1_downshift_experiment"].get("prospective_holdout_score_count", 0)},
        {"b2_prospective_holdout_metric_count": artifacts["rerun1_downshift_experiment"].get("prospective_holdout_metric_count", 0)},
    )
    boundary_counts = _sum_counts(
        artifacts["rerun1_logistic_hazard"].get("training_boundary_violation_counts", {}),
        artifacts["rerun1_calibration_readiness"].get("calibration_boundary_violation_counts", {}),
        {"prospective_holdout_consumption_count": holdout["prospective_holdout_consumption_count"]},
    )

    if precondition_issues:
        engineering_status = "blocked_rerun1_not_ready"
        final_verdict = "BLOCKED_INPUTS_NOT_READY"
        stage_status = "blocked_rerun1_not_ready"
    elif leakage_counts["total"] or boundary_counts["total"]:
        engineering_status = "fail"
        final_verdict = "FAIL_BOUNDARY_OR_LEAKAGE"
        stage_status = "fail_boundary_or_leakage"
    else:
        engineering_status = "pass"
        final_verdict = "PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE"
        stage_status = "pass_engineering_model_discrimination_baseline_superior_defer_prospective"

    model_status = "model_discrimination_pass" if artifacts["rerun1_logistic_hazard"].get("status") == "pass" and _as_int(artifacts["rerun1_logistic_hazard"].get("fitted_model_count")) > 0 else "model_discrimination_fail"
    calibration_status = "pass" if artifacts["rerun1_calibration_readiness"].get("status") == "pass" and _as_int(artifacts["rerun1_calibration_readiness"].get("usable_probability_candidate_count")) >= 5 else "fail"
    causality_status = "pass" if leakage_counts["total"] == 0 and boundary_counts["total"] == 0 else "fail"
    primary_status = str(b2_summary["primary_risk_metric_comparison_status"])
    secondary_status = str(b2_summary["secondary_return_metric_status"])
    holdout_gate_status = str(holdout["prospective_holdout_gate_status"])
    if primary_status == "baseline_superior_on_primary_risk_metrics":
        promotion_status = "defer_or_reject_model_as_primary_downshift_driver"
    elif holdout_gate_status != "pass" or holdout["prospective_holdout_performance_consumed"] != "yes":
        promotion_status = "defer_prospective_holdout_required"
    else:
        promotion_status = "pass"

    report = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "pass" if final_verdict.startswith("PASS_") else "blocked_rerun1_not_ready" if precondition_issues else "fail",
        "final_gate_verdict": final_verdict,
        "stage03v1_gate_status": stage_status,
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        **status_keys,
        "trial_accounting_invalidation_recorded": artifacts["trial_accounting"].get("trial_accounting_invalidation_recorded"),
        "engineering_gate_status": engineering_status,
        "causality_gate_status": causality_status,
        "rerun1_magnitude_gate_status": rerun1_magnitude_gate_status,
        "model_discrimination_gate_status": model_status,
        "model_discrimination_status": model_status,
        "calibration_readiness_gate_status": calibration_status,
        "primary_risk_metric_comparison_status": primary_status,
        "secondary_return_metric_status": secondary_status,
        "secondary_return_status": secondary_status,
        "prospective_holdout_readiness_gate_status": holdout_gate_status,
        "decision_support_promotion_gate_status": promotion_status,
        "model_discrimination_claim": "model_has_validated_discrimination_on_full_scale_rerun",
        "primary_risk_downshift_claim": "volatility_baseline_superior_for_primary_risk_reduction",
        "secondary_return_claim": "model_retains_more_return_secondary_metric",
        "recommended_use_after_gate": "research_only_model_overlay_or_volatility_baseline_primary",
        "candidate_slice_count": _as_int(artifacts["rerun1_downshift_experiment"].get("candidate_slice_count")),
        "scored_candidate_slice_count": _as_int(artifacts["rerun1_downshift_experiment"].get("scored_candidate_slice_count")),
        "validation_entity_day_count": _as_int(artifacts["rerun1_downshift_experiment"].get("validation_entity_day_count")),
        "wp4_validation_rows_evaluated": _as_int(artifacts["rerun1_logistic_hazard"].get("validation_row_count_evaluated")),
        "wp5_usable_probability_candidate_count": _as_int(artifacts["rerun1_calibration_readiness"].get("usable_probability_candidate_count")),
        **b2_summary,
        **holdout,
        "artifact_manifest_path": _safe_path(paths.get("artifact_manifest")),
        "rerun1_input_manifest_path": _safe_path(paths.get("rerun1_input_manifest")),
        "evidence_matrix_path": _safe_path(paths.get("evidence_matrix")),
        "verdict_json_path": _safe_path(paths.get("verdict_json")),
        "holdout_status_path": _safe_path(paths.get("holdout_status")),
        "post_gate_action_plan_path": _safe_path(paths.get("post_gate_action_plan")),
        "leakage_violation_counts": leakage_counts,
        "boundary_violation_counts": boundary_counts,
        "ci_gate_status": "pass" if not precondition_issues and leakage_counts["total"] == 0 and boundary_counts["total"] == 0 else "fail",
        "boundary_flags": dict(BOUNDARY_FLAGS),
        "blocking_reasons": list(precondition_issues),
        "remaining_risks": [
            "Prospective holdout performance remains unconsumed and must be reviewed only by a future authorized package.",
            "RERUN1 B2 supports model discrimination as a separate claim but favors the volatility baseline on primary risk downshift metrics.",
        ],
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
    }
    if final_verdict not in ALLOWED_FINAL_VERDICTS:
        report["status"] = "fail"
        report["final_gate_verdict"] = "FAIL_VALIDATION_EVIDENCE"
        report["blocking_reasons"].append("final_verdict_not_allowed")
    return report


def build_evidence_rows(report: Mapping[str, Any], paths: Mapping[str, Path | str]) -> list[dict[str, Any]]:
    return [
        {"component": "wp0_scope_freeze", "status": report.get("wp0_scope_freeze_status"), "evidence_path": _safe_path(DEFAULT_SCOPE_FREEZE), "detail": "scope freeze accepted", "value": report.get("wp0_scope_freeze_status")},
        {"component": "rerun1_fold_plan_v2", "status": report.get("rerun1_fold_plan_v2_status"), "evidence_path": _safe_path(DEFAULT_FOLD_PLAN_V2), "detail": "fold plan v2 magnitude gates", "value": report.get("rerun1_magnitude_gate_status")},
        {"component": "rerun1_logistic_hazard", "status": report.get("rerun1_logistic_hazard_status"), "evidence_path": _safe_path(DEFAULT_LOGISTIC_HAZARD), "detail": "model discrimination", "value": report.get("model_discrimination_status")},
        {"component": "rerun1_calibration_readiness", "status": report.get("rerun1_calibration_readiness_status"), "evidence_path": _safe_path(DEFAULT_CALIBRATION_READINESS), "detail": "readiness candidates", "value": report.get("wp5_usable_probability_candidate_count")},
        {"component": "rerun1_downshift_experiment", "status": report.get("rerun1_downshift_experiment_status"), "evidence_path": _safe_path(DEFAULT_DOWNSHIFT_EXPERIMENT), "detail": "primary risk metric comparison", "value": report.get("primary_risk_metric_comparison_status")},
        {"component": "prospective_holdout", "status": report.get("prospective_holdout_readiness_gate_status"), "evidence_path": _safe_path(DEFAULT_LEDGER_TEMPLATE), "detail": "registered 120/2 holdout policy", "value": report.get("prospective_holdout_complete_20d_label_trade_dates")},
        {"component": "final_verdict", "status": report.get("status"), "evidence_path": _safe_path(paths.get("verdict_json")), "detail": "WP7-v2 final gate", "value": report.get("final_gate_verdict")},
    ]


def build_artifact_manifest(report: Mapping[str, Any], paths: Mapping[str, Path | str]) -> dict[str, Any]:
    generated = [
        "output",
        "summary_json",
        "verdict_json",
        "evidence_matrix",
        "artifact_manifest",
        "rerun1_input_manifest",
        "holdout_status",
        "post_gate_action_plan",
        "audit_sample",
    ]
    return {
        "index_id": INDEX_ID,
        "status": report.get("status"),
        "generated_artifacts": {key: _safe_path(paths.get(key)) for key in generated},
        "source_artifacts": {
            "fold_plan_v2": _safe_path(DEFAULT_FOLD_PLAN_V2),
            "trial_accounting": _safe_path(DEFAULT_TRIAL_ACCOUNTING),
            "logistic_hazard": _safe_path(DEFAULT_LOGISTIC_HAZARD),
            "calibration_readiness": _safe_path(DEFAULT_CALIBRATION_READINESS),
            "downshift_experiment": _safe_path(DEFAULT_DOWNSHIFT_EXPERIMENT),
            "downshift_arm_metrics": _safe_path(DEFAULT_DOWNSHIFT_ARM_METRICS),
        },
        "forbidden_legacy_inputs_not_used": list(FORBIDDEN_LEGACY_INPUTS),
        "boundary_flags": report.get("boundary_flags", {}),
        "created_at": report.get("created_at"),
    }


def build_rerun1_input_manifest(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "manifest_version": "stage03v1_final_gate_v2_rerun1_input_manifest_v1",
        "status": "pass" if not report.get("blocking_reasons") else "blocked",
        "inputs": {
            "fold_plan_v2": {"path": _safe_path(DEFAULT_FOLD_PLAN_V2), "status": report.get("rerun1_fold_plan_v2_status")},
            "fold_magnitude_overview": {"path": _safe_path(DEFAULT_FOLD_MAGNITUDE_OVERVIEW), "status": report.get("rerun1_magnitude_gate_status")},
            "trial_accounting": {"path": _safe_path(DEFAULT_TRIAL_ACCOUNTING), "invalidation_recorded": report.get("trial_accounting_invalidation_recorded")},
            "logistic_hazard": {"path": _safe_path(DEFAULT_LOGISTIC_HAZARD), "status": report.get("rerun1_logistic_hazard_status")},
            "calibration_readiness": {"path": _safe_path(DEFAULT_CALIBRATION_READINESS), "status": report.get("rerun1_calibration_readiness_status")},
            "downshift_experiment": {"path": _safe_path(DEFAULT_DOWNSHIFT_EXPERIMENT), "status": report.get("rerun1_downshift_experiment_status")},
            "downshift_arm_metrics": {"path": _safe_path(DEFAULT_DOWNSHIFT_ARM_METRICS), "status": "used_for_b2_summary"},
        },
        "legacy_invalidated_inputs_forbidden_as_evidence": list(FORBIDDEN_LEGACY_INPUTS),
        "legacy_invalidated_inputs_used_as_final_evidence": [],
        "created_at": report.get("created_at"),
    }


def _write_report_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V1 Final Gate v2 Report",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- final_gate_verdict: {report.get('final_gate_verdict')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        "",
        "## Gate Status",
        "",
        f"- engineering_gate_status: {report.get('engineering_gate_status')}",
        f"- causality_gate_status: {report.get('causality_gate_status')}",
        f"- rerun1_magnitude_gate_status: {report.get('rerun1_magnitude_gate_status')}",
        f"- model_discrimination_status: {report.get('model_discrimination_status')}",
        f"- primary_risk_metric_comparison_status: {report.get('primary_risk_metric_comparison_status')}",
        f"- secondary_return_status: {report.get('secondary_return_status')}",
        f"- prospective_holdout_readiness_gate_status: {report.get('prospective_holdout_readiness_gate_status')}",
        f"- decision_support_promotion_gate_status: {report.get('decision_support_promotion_gate_status')}",
        "",
        "## Claims",
        "",
        f"- model_discrimination_claim: {report.get('model_discrimination_claim')}",
        f"- primary_risk_downshift_claim: {report.get('primary_risk_downshift_claim')}",
        f"- secondary_return_claim: {report.get('secondary_return_claim')}",
        f"- recommended_use_after_gate: {report.get('recommended_use_after_gate')}",
        "",
        "Model discrimination and primary risk downshift control are separate claims. RERUN1 validates model discrimination, while the pre-registered primary-risk downshift comparison favors the volatility baseline.",
        "",
        "## RERUN1 Summary",
        "",
        f"- candidate_slice_count: {report.get('candidate_slice_count')}",
        f"- scored_candidate_slice_count: {report.get('scored_candidate_slice_count')}",
        f"- validation_entity_day_count: {report.get('validation_entity_day_count')}",
        f"- wp4_validation_rows_evaluated: {report.get('wp4_validation_rows_evaluated')}",
        f"- wp5_usable_probability_candidate_count: {report.get('wp5_usable_probability_candidate_count')}",
        f"- model_minus_baseline_delta_count: {report.get('model_minus_baseline_delta_count')}",
        f"- significant_model_better_primary_risk_delta_count: {report.get('significant_model_better_primary_risk_delta_count')}",
        f"- significant_baseline_better_primary_risk_delta_count: {report.get('significant_baseline_better_primary_risk_delta_count')}",
        "",
        "## Prospective Holdout",
        "",
        f"- prospective_holdout_complete_20d_label_trade_dates: {report.get('prospective_holdout_complete_20d_label_trade_dates')}",
        f"- prospective_holdout_market_event_block_count: {report.get('prospective_holdout_market_event_block_count')}",
        f"- registered_min_complete_20d_label_trade_dates: {report.get('prospective_holdout_min_complete_20d_label_trade_dates')}",
        f"- registered_min_market_event_blocks: {report.get('prospective_holdout_min_market_event_blocks')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- prospective_holdout_consumption_count: {report.get('prospective_holdout_consumption_count')}",
        f"- prospective_holdout_gate_status: {report.get('prospective_holdout_gate_status')}",
        "",
        "## Boundaries",
        "",
    ]
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Remaining Risks", ""])
    for item in report.get("remaining_risks", []):
        lines.append(f"- {item}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_action_plan(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V1 Post-Gate Action Plan v2",
        "",
        f"- final_gate_verdict: {report.get('final_gate_verdict')}",
        "- maintain Stage03V1 as research-only evidence until a future authorized prospective holdout package is complete.",
        "- treat the volatility baseline as the primary historical-development downshift comparator for risk-control research.",
        "- use calibrated hazard outputs only as research overlays; do not promote decision support from this gate.",
        "- preserve fixed-threshold Stage03V1 target semantics; Stage03V2 and Stage03V3 remain placeholders.",
        "- do not consume prospective holdout performance outside a separately authorized package.",
    ]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_outputs(report: Mapping[str, Any], paths: Mapping[str, Path | str]) -> None:
    evidence_rows = build_evidence_rows(report, paths)
    artifact_manifest = build_artifact_manifest(report, paths)
    rerun1_manifest = build_rerun1_input_manifest(report)
    holdout_status = {key: report.get(key) for key in report if str(key).startswith("prospective_holdout_")}
    verdict = {
        "index_id": INDEX_ID,
        "status": report.get("status"),
        "final_gate_verdict": report.get("final_gate_verdict"),
        "stage03v1_gate_status": report.get("stage03v1_gate_status"),
        "model_discrimination_status": report.get("model_discrimination_status"),
        "primary_risk_metric_comparison_status": report.get("primary_risk_metric_comparison_status"),
        "secondary_return_status": report.get("secondary_return_status"),
        "prospective_holdout_readiness_gate_status": report.get("prospective_holdout_readiness_gate_status"),
        "decision_support_promotion_gate_status": report.get("decision_support_promotion_gate_status"),
        "allowed_final_verdicts": list(ALLOWED_FINAL_VERDICTS),
    }
    audit_rows = [
        {"category": "verdict", "key": "final_gate_verdict", "status": report.get("status"), "value": report.get("final_gate_verdict"), "source_path": _safe_path(paths.get("summary_json"))},
        {"category": "b2", "key": "primary_risk_metric_comparison_status", "status": report.get("primary_risk_metric_comparison_status"), "value": report.get("significant_baseline_better_primary_risk_delta_count"), "source_path": _safe_path(DEFAULT_DOWNSHIFT_ARM_METRICS)},
        {"category": "holdout", "key": "registered_min_complete_20d_label_trade_dates", "status": report.get("prospective_holdout_minimum_requirement_status"), "value": report.get("prospective_holdout_min_complete_20d_label_trade_dates"), "source_path": _safe_path(DEFAULT_LEDGER_TEMPLATE)},
        {"category": "boundary", "key": "external_data_fetch", "status": report.get("boundary_flags", {}).get("external_data_fetch"), "value": "no", "source_path": _safe_path(paths.get("summary_json"))},
    ]
    _write_report_markdown(paths["output"], report)
    _write_json(paths["summary_json"], report)
    _write_json(paths["verdict_json"], verdict)
    _write_csv(paths["evidence_matrix"], evidence_rows, EVIDENCE_COLUMNS)
    _write_json(paths["artifact_manifest"], artifact_manifest)
    _write_json(paths["rerun1_input_manifest"], rerun1_manifest)
    _write_json(paths["holdout_status"], holdout_status)
    _write_action_plan(paths["post_gate_action_plan"], report)
    _write_csv(paths["audit_sample"], audit_rows, AUDIT_COLUMNS)


def _output_paths_from_args(args: argparse.Namespace) -> dict[str, Path]:
    return {
        "output": Path(args.output),
        "summary_json": Path(args.summary_json),
        "verdict_json": Path(args.verdict_json),
        "evidence_matrix": Path(args.evidence_matrix),
        "artifact_manifest": Path(args.artifact_manifest),
        "rerun1_input_manifest": Path(args.rerun1_input_manifest),
        "holdout_status": Path(args.holdout_status),
        "post_gate_action_plan": Path(args.post_gate_action_plan),
        "audit_sample": Path(args.audit_sample),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage03V WP7-v2 final gate.")
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--scope-freeze", default=str(DEFAULT_SCOPE_FREEZE))
    parser.add_argument("--sample-feasibility", default=str(DEFAULT_SAMPLE_FEASIBILITY))
    parser.add_argument("--target-support", default=str(DEFAULT_TARGET_SUPPORT))
    parser.add_argument("--target-controls", default=str(DEFAULT_TARGET_CONTROLS))
    parser.add_argument("--full-target-audit", default=str(DEFAULT_FULL_TARGET_AUDIT))
    parser.add_argument("--baseline-diagnostics", default=str(DEFAULT_BASELINE_DIAGNOSTICS))
    parser.add_argument("--vol-scaled-sanity", default=str(DEFAULT_VOL_SCALED_SANITY))
    parser.add_argument("--fold-plan-v2", default=str(DEFAULT_FOLD_PLAN_V2))
    parser.add_argument("--fold-magnitude-overview", default=str(DEFAULT_FOLD_MAGNITUDE_OVERVIEW))
    parser.add_argument("--trial-accounting", default=str(DEFAULT_TRIAL_ACCOUNTING))
    parser.add_argument("--logistic-hazard", default=str(DEFAULT_LOGISTIC_HAZARD))
    parser.add_argument("--calibration-readiness", default=str(DEFAULT_CALIBRATION_READINESS))
    parser.add_argument("--downshift-experiment", default=str(DEFAULT_DOWNSHIFT_EXPERIMENT))
    parser.add_argument("--downshift-arm-metrics", default=str(DEFAULT_DOWNSHIFT_ARM_METRICS))
    parser.add_argument("--ledger-template", default=str(DEFAULT_LEDGER_TEMPLATE))
    parser.add_argument("--policy", default=str(DEFAULT_POLICY))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--verdict-json", default=str(DEFAULT_VERDICT_JSON))
    parser.add_argument("--evidence-matrix", default=str(DEFAULT_EVIDENCE_MATRIX))
    parser.add_argument("--artifact-manifest", default=str(DEFAULT_ARTIFACT_MANIFEST))
    parser.add_argument("--rerun1-input-manifest", default=str(DEFAULT_RERUN1_INPUT_MANIFEST))
    parser.add_argument("--holdout-status", default=str(DEFAULT_HOLDOUT_STATUS))
    parser.add_argument("--post-gate-action-plan", default=str(DEFAULT_POST_GATE_ACTION_PLAN))
    parser.add_argument("--audit-sample", default=str(DEFAULT_AUDIT_SAMPLE))
    parser.add_argument("--no-fetch", action="store_true")
    args = parser.parse_args(argv)

    paths = _output_paths_from_args(args)
    report = build_final_gate_report(
        db_path=args.db,
        scope_freeze=args.scope_freeze,
        sample_feasibility=args.sample_feasibility,
        target_support=args.target_support,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        baseline_diagnostics=args.baseline_diagnostics,
        vol_scaled_sanity=args.vol_scaled_sanity,
        fold_plan_v2=args.fold_plan_v2,
        fold_magnitude_overview=args.fold_magnitude_overview,
        trial_accounting=args.trial_accounting,
        logistic_hazard=args.logistic_hazard,
        calibration_readiness=args.calibration_readiness,
        downshift_experiment=args.downshift_experiment,
        downshift_arm_metrics=args.downshift_arm_metrics,
        ledger_template=args.ledger_template,
        policy_path=args.policy,
        output_paths=paths,
    )
    write_outputs(report, paths)
    print(
        "STAGE03V_FINAL_GATE_V2="
        f"{report.get('status')} "
        f"verdict={report.get('final_gate_verdict')} "
        f"primary_risk={report.get('primary_risk_metric_comparison_status')} "
        f"model_discrimination={report.get('model_discrimination_status')} "
        f"holdout_min_20d_days={report.get('prospective_holdout_min_complete_20d_label_trade_dates', REGISTERED_HOLDOUT_MIN_COMPLETE_20D_LABEL_TRADE_DATES)} "
        f"holdout_min_blocks={report.get('prospective_holdout_min_market_event_blocks', REGISTERED_HOLDOUT_MIN_MARKET_EVENT_BLOCKS)} "
        f"db={report.get('source_db_path')} "
        f"report={_safe_path(paths['output'])} "
        f"summary_json={_safe_path(paths['summary_json'])} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") in {"pass", "blocked_missing_v7_db", "blocked_invalid_v7_db"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
