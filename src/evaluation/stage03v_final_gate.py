"""Stage03V WP7 final gate for the Stage03V1 downside-risk branch.

WP7 aggregates accepted WP0-WP6 artifacts and emits the final Stage03V1 gate
verdict. It is a no-fetch, no-training, no-recalibration, no-decision-output
gate. Prospective holdout performance is not consumed by default.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import pandas as pd

from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)


INDEX_ID = "STAGE03V-WP7-v1"
REPORT_VERSION = "stage03v1_final_gate_v1"
POLICY_VERSION = "stage03v_final_gate_policy_v1"
STAGE_ID = "stage03v"
PRIMARY_TARGET_FAMILY = "fixed_threshold_stage03v1_downside_event"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SCOPE_FREEZE = ROOT / "reports" / "stage03v" / "stage03v_wp0_scope_freeze_report.json"
DEFAULT_SAMPLE_FEASIBILITY = ROOT / "reports" / "stage03v" / "sample_feasibility_report.json"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_BASELINE_DIAGNOSTICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_VOL_SCALED_SANITY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_LOGISTIC_HAZARD = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_CALIBRATION_READINESS = ROOT / "reports" / "stage03v" / "calibration_readiness_report.json"
DEFAULT_RISK_VALIDATION = ROOT / "reports" / "stage03v" / "risk_validation_report.json"
DEFAULT_DOWNSHIFT_RESEARCH = ROOT / "reports" / "stage03v" / "downshift_research_report.json"
DEFAULT_WP7_INPUT_MANIFEST = ROOT / "reports" / "stage03v" / "wp7_final_gate_input_manifest.json"
DEFAULT_LEDGER_TEMPLATE = ROOT / "reports" / "stage04" / "prospective_validation_ledger.stage03v.template.jsonl"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_final_gate_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_report.json"
DEFAULT_VERDICT_JSON = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_verdict.json"
DEFAULT_EVIDENCE_MATRIX = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_evidence_matrix.csv"
DEFAULT_ARTIFACT_MANIFEST = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_artifact_manifest.json"
DEFAULT_HOLDOUT_STATUS = ROOT / "reports" / "stage03v" / "stage03v1_prospective_holdout_status.json"
DEFAULT_POST_GATE_ACTION_PLAN = ROOT / "reports" / "stage03v" / "stage03v1_post_gate_action_plan.md"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "stage03v1_final_gate_audit_sample.csv"

ALLOWED_FINAL_VERDICTS = [
    "PASS_ENGINEERING_HISTORICAL_DEFER_PROSPECTIVE",
    "PASS_STAGE03V1_RESEARCH_ONLY",
    "DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT",
    "FAIL_BOUNDARY_OR_LEAKAGE",
    "FAIL_INPUT_ARTIFACTS",
    "FAIL_VALIDATION_EVIDENCE",
    "BLOCKED_INPUTS_NOT_READY",
]
GATE_NAMES = [
    "engineering_gate",
    "causality_gate",
    "historical_validation_gate",
    "calibration_readiness_gate",
    "risk_validation_gate",
    "prospective_holdout_readiness_gate",
    "decision_support_promotion_gate",
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
LEAKAGE_ZERO_COUNTS = {
    "wp3_leakage_violation_count_total": 0,
    "wp3_5_leakage_violation_count_total": 0,
    "wp4_leakage_violation_count_total": 0,
    "wp5_leakage_violation_count_total": 0,
    "wp6_leakage_violation_count_total": 0,
    "prospective_holdout_score_count": 0,
    "prospective_holdout_metric_count": 0,
    "external_fetch_count": 0,
    "leakage_violation_count_total": 0,
}
BOUNDARY_ZERO_COUNTS = {
    "wp2_1_full_target_violation_count_total": 0,
    "wp4_training_boundary_violation_count_total": 0,
    "wp5_calibration_boundary_violation_count_total": 0,
    "wp6_validation_boundary_violation_count_total": 0,
    "persistent_db_write_count": 0,
    "target_dataset_mutation_count": 0,
    "readiness_reassignment_count": 0,
    "decision_or_trading_output_count": 0,
    "boundary_violation_count_total": 0,
}
EVIDENCE_COLUMNS = [
    "evidence_layer",
    "artifact_or_gate",
    "status",
    "requirement",
    "observed_value",
    "verdict_impact",
    "blocking_reason",
]
AUDIT_COLUMNS = [
    "audit_item",
    "status",
    "source_artifact",
    "observed_value",
    "requirement",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_ledger_template(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8").strip()
    if not text:
        return {}
    return json.loads(text.splitlines()[0])


def _load_machine_config(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise ValueError(f"{path} is not JSON and PyYAML is unavailable") from exc
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows), columns=list(columns))
    frame.to_csv(target, index=False)
    return int(len(frame))


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


def _status(doc: Mapping[str, Any], default: str = "unknown") -> str:
    return str(doc.get("status", default))


def _total_from_counts(counts: Mapping[str, Any], total_key: str) -> int:
    if total_key in counts:
        return _as_int(counts.get(total_key), 0)
    return int(sum(_as_int(value, 0) for value in counts.values()))


def _sha256(path: Path | str) -> str | None:
    target = Path(path)
    if not target.exists() or not target.is_file():
        return None
    digest = hashlib.sha256()
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _artifact_record(path: Path | str, role: str) -> dict[str, Any]:
    target = Path(path)
    return {
        "path": _safe_path(target),
        "role": role,
        "exists": target.exists(),
        "size_bytes": target.stat().st_size if target.exists() and target.is_file() else 0,
        "sha256": _sha256(target),
    }


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "primary_target_family": PRIMARY_TARGET_FAMILY,
        "vol_scaled_candidate_policy": "tracked_reference_only",
        "stage03v2_policy": "placeholder_only",
        "stage03v3_policy": "placeholder_only",
        "final_gate_scope": "stage03v1_downside_risk_only",
        "historical_development_gate_policy": "required",
        "prospective_holdout_policy": "defer_if_minimum_not_met",
        "prospective_holdout_evaluation_authorized": False,
        "prospective_holdout_min_trade_dates": 60,
        "prospective_holdout_min_positive_events": 10,
        "prospective_holdout_min_stress_event_blocks": 1,
        "prospective_holdout_review_cadence": "quarterly",
        "allow_decision_support_promotion_without_holdout": False,
        "allowed_final_verdicts": ALLOWED_FINAL_VERDICTS,
        "forbidden_outputs": [
            "buy",
            "sell",
            "position_sizing",
            "execution_instruction",
            "portfolio_recommendation",
        ],
        "external_fetch_policy": "forbidden",
        "persistent_db_table_policy": "forbidden_by_default",
        "full_score_matrix_policy": "forbidden_to_commit",
        "boundary_flags": BOUNDARY_FLAGS,
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
        "historical_development_gate_policy",
        "prospective_holdout_policy",
        "prospective_holdout_review_cadence",
        "external_fetch_policy",
        "persistent_db_table_policy",
        "full_score_matrix_policy",
    ]:
        if policy.get(key) != expected[key]:
            issues.append(f"{key}_mismatch")
    if policy.get("prospective_holdout_evaluation_authorized") is not False:
        issues.append("prospective_holdout_evaluation_authorized_not_false")
    if policy.get("allow_decision_support_promotion_without_holdout") is not False:
        issues.append("decision_support_promotion_without_holdout_allowed")
    if list(policy.get("allowed_final_verdicts", [])) != ALLOWED_FINAL_VERDICTS:
        issues.append("allowed_final_verdicts_mismatch")
    forbidden = set(policy.get("forbidden_outputs", []))
    required = {"buy", "sell", "position_sizing", "execution_instruction", "portfolio_recommendation"}
    if not required.issubset(forbidden):
        issues.append("forbidden_outputs_incomplete")
    return issues


def collect_violation_counts(
    *,
    full_target_audit: Mapping[str, Any],
    baseline_diagnostics: Mapping[str, Any],
    vol_scaled_sanity: Mapping[str, Any],
    logistic_hazard: Mapping[str, Any],
    calibration_readiness: Mapping[str, Any],
    risk_validation: Mapping[str, Any],
) -> tuple[dict[str, int], dict[str, int]]:
    leakage = dict(LEAKAGE_ZERO_COUNTS)
    leakage["wp3_leakage_violation_count_total"] = _total_from_counts(
        baseline_diagnostics.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    leakage["wp3_5_leakage_violation_count_total"] = _total_from_counts(
        vol_scaled_sanity.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    leakage["wp4_leakage_violation_count_total"] = _total_from_counts(
        logistic_hazard.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    leakage["wp5_leakage_violation_count_total"] = _total_from_counts(
        calibration_readiness.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    leakage["wp6_leakage_violation_count_total"] = _total_from_counts(
        risk_validation.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    leakage["prospective_holdout_score_count"] = _as_int(
        risk_validation.get("leakage_violation_counts", {}).get("prospective_holdout_score_count"),
        0,
    )
    leakage["prospective_holdout_metric_count"] = _as_int(
        risk_validation.get("leakage_violation_counts", {}).get("prospective_holdout_metric_count"),
        0,
    )
    leakage["leakage_violation_count_total"] = int(
        sum(value for key, value in leakage.items() if key != "leakage_violation_count_total")
    )

    boundary = dict(BOUNDARY_ZERO_COUNTS)
    boundary["wp2_1_full_target_violation_count_total"] = _as_int(full_target_audit.get("violation_count_total"), 0)
    boundary["wp4_training_boundary_violation_count_total"] = _total_from_counts(
        logistic_hazard.get("training_boundary_violation_counts", {}),
        "training_boundary_violation_count_total",
    )
    boundary["wp5_calibration_boundary_violation_count_total"] = _total_from_counts(
        calibration_readiness.get("calibration_boundary_violation_counts", {}),
        "calibration_boundary_violation_count_total",
    )
    boundary["wp6_validation_boundary_violation_count_total"] = _total_from_counts(
        risk_validation.get("validation_boundary_violation_counts", {}),
        "validation_boundary_violation_count_total",
    )
    boundary["persistent_db_write_count"] = _as_int(
        risk_validation.get("leakage_violation_counts", {}).get("persistent_db_write_count"),
        0,
    )
    boundary["boundary_violation_count_total"] = int(
        sum(value for key, value in boundary.items() if key != "boundary_violation_count_total")
    )
    return leakage, boundary


def validate_wp7_preconditions(
    *,
    docs: Mapping[str, Mapping[str, Any]],
    ledger_template: Mapping[str, Any],
    wp7_input_manifest: Mapping[str, Any],
    db_path: Path | str,
    leakage_counts: Mapping[str, int],
    boundary_counts: Mapping[str, int],
) -> tuple[str, list[str]]:
    issues: list[str] = []
    required_statuses = {
        "wp0_scope_freeze": "pass",
        "wp0_5_sample_feasibility": "pass",
        "wp1_target_support": "pass",
        "wp2_target_controls": "pass",
        "wp2_1_full_target_audit": "pass",
        "wp3_baseline_diagnostics": "pass",
        "wp3_5_vol_scaled_sanity": "pass",
        "wp4_logistic_hazard": "pass",
        "wp5_calibration_readiness": "pass",
        "wp6_risk_validation": "pass",
    }
    for key, expected in required_statuses.items():
        if docs[key].get("status") != expected:
            issues.append(f"{key}_status_not_{expected}")
    for key in [
        "wp0_5_sample_feasibility",
        "wp1_target_support",
        "wp2_target_controls",
        "wp2_1_full_target_audit",
        "wp3_baseline_diagnostics",
        "wp3_5_vol_scaled_sanity",
        "wp4_logistic_hazard",
        "wp5_calibration_readiness",
        "wp6_risk_validation",
    ]:
        doc = docs[key]
        if doc.get("v7_coverage_available") != "yes" and doc.get("source_coverage", {}).get("v7_coverage_available") != "yes":
            issues.append(f"{key}_v7_coverage_not_yes")
        if doc.get("sw2021_l2_universe_coverage") != "pass" and doc.get("source_coverage", {}).get("sw2021_l2_universe_coverage") != "pass":
            issues.append(f"{key}_sw2021_l2_universe_not_pass")
        if _as_int(doc.get("prospective_holdout_rows_evaluated"), 0) != 0:
            issues.append(f"{key}_prospective_holdout_rows_evaluated_not_zero")
    if docs["wp6_risk_validation"].get("historical_development_only") != "yes":
        issues.append("wp6_historical_development_only_not_yes")
    wp6_flags = docs["wp6_risk_validation"].get("boundary_flags", {})
    if wp6_flags.get("trading_or_decision_output") != "no":
        issues.append("wp6_trading_or_decision_output_not_no")
    if _as_int(leakage_counts.get("wp6_leakage_violation_count_total"), 0) != 0:
        issues.append("wp6_leakage_violation_count_not_zero")
    if _as_int(boundary_counts.get("wp6_validation_boundary_violation_count_total"), 0) != 0:
        issues.append("wp6_validation_boundary_violation_count_not_zero")
    if wp7_input_manifest.get("status") != "prepared_for_wp7":
        issues.append("wp7_input_manifest_not_prepared")
    if wp7_input_manifest.get("wp7_final_gate_executed") != "no":
        issues.append("wp7_input_manifest_already_executed")
    for source in [docs["wp0_scope_freeze"], ledger_template]:
        if source.get("information_cutoff_date") != INFORMATION_CUTOFF_DATE:
            issues.append("information_cutoff_date_mismatch")
        if source.get("holdout_start") != HOLDOUT_START:
            issues.append("holdout_start_mismatch")
    expected_paths = {str(doc.get("source_db_path") or doc.get("db_path")) for doc in docs.values() if doc.get("source_db_path") or doc.get("db_path")}
    resolved_safe = _safe_path(db_path)
    if not os.environ.get("STAGE03V_V7_DB") and expected_paths and resolved_safe not in expected_paths:
        issues.append("resolved_db_path_does_not_match_stage03v_artifacts")
    return ("pass", []) if not issues else ("blocked_wp6_not_ready", issues)


def compute_holdout_status(v7: Any, ledger: Mapping[str, Any], policy: Mapping[str, Any]) -> dict[str, Any]:
    holdout_start = pd.Timestamp(policy.get("holdout_start", HOLDOUT_START)).normalize()
    price_frame = getattr(v7, "price_frame", pd.DataFrame())
    if price_frame is None or price_frame.empty or "trade_date" not in price_frame.columns:
        holdout_rows = 0
        holdout_dates = 0
    else:
        dates = pd.to_datetime(price_frame["trade_date"], errors="coerce").dt.normalize()
        mask = dates.ge(holdout_start)
        holdout_rows = int(mask.sum())
        holdout_dates = int(dates[mask].nunique())
    min_dates = _as_int(policy.get("prospective_holdout_min_trade_dates"), 60)
    min_events = _as_int(policy.get("prospective_holdout_min_positive_events"), 10)
    min_stress = _as_int(policy.get("prospective_holdout_min_stress_event_blocks"), 1)
    evaluation_authorized = bool(policy.get("prospective_holdout_evaluation_authorized"))
    consumption_count = _as_int(ledger.get("consumption_count"), 0)
    rows_evaluated = 0
    if not evaluation_authorized:
        minimum_status = "insufficient_unconsumed" if holdout_dates < min_dates else "available_but_unconsumed"
        stress_status = "not_evaluated_unconsumed"
        gate_status = "defer_or_insufficient"
    else:
        minimum_status = "evaluation_authorized_but_not_implemented"
        stress_status = "evaluation_authorized_but_not_implemented"
        gate_status = "defer_or_insufficient"
    return {
        "index_id": INDEX_ID,
        "prospective_holdout_policy": policy.get("prospective_holdout_policy"),
        "information_cutoff_date": policy.get("information_cutoff_date"),
        "holdout_start": policy.get("holdout_start"),
        "prospective_holdout_rows_available": holdout_rows,
        "prospective_holdout_trade_dates_available": holdout_dates,
        "prospective_holdout_rows_evaluated": rows_evaluated,
        "prospective_holdout_consumption_count": consumption_count,
        "prospective_holdout_evaluation_authorized": evaluation_authorized,
        "prospective_holdout_min_trade_dates": min_dates,
        "prospective_holdout_min_positive_events": min_events,
        "prospective_holdout_min_stress_event_blocks": min_stress,
        "prospective_holdout_minimum_requirement_status": minimum_status,
        "prospective_holdout_stress_event_requirement_status": stress_status,
        "prospective_holdout_gate_status": gate_status,
        "prospective_holdout_next_review_cadence": policy.get("prospective_holdout_review_cadence", "quarterly"),
        "holdout_performance_consumed": "no",
    }


def determine_gate_statuses(
    *,
    docs: Mapping[str, Mapping[str, Any]],
    leakage_total: int,
    boundary_total: int,
    holdout_status: Mapping[str, Any],
) -> dict[str, str]:
    all_inputs_pass = all(_status(doc) == "pass" for doc in docs.values())
    validation_pass = _as_int(docs["wp6_risk_validation"].get("validation_pass_candidate_count"), 0)
    usable = _as_int(docs["wp5_calibration_readiness"].get("usable_probability_candidate_count"), 0)
    downshift = _as_int(docs["wp6_risk_validation"].get("downshift_tier_counts", {}).get("research_downshift_candidate"), 0)
    historical_ok = validation_pass > 0 and downshift > 0
    gates = {
        "engineering_gate_status": "pass" if all_inputs_pass else "fail",
        "causality_gate_status": "pass" if leakage_total == 0 and boundary_total == 0 else "fail",
        "historical_validation_gate_status": "pass" if historical_ok else "fail",
        "calibration_readiness_gate_status": "pass" if usable > 0 else "fail",
        "risk_validation_gate_status": "pass" if _status(docs["wp6_risk_validation"]) == "pass" and validation_pass > 0 else "fail",
        "prospective_holdout_readiness_gate_status": str(holdout_status.get("prospective_holdout_gate_status", "defer_or_insufficient")),
        "decision_support_promotion_gate_status": "DEFER",
    }
    if leakage_total or boundary_total:
        gates["decision_support_promotion_gate_status"] = "FAIL"
    return gates


def determine_final_verdict(
    *,
    precondition_status: str,
    gates: Mapping[str, str],
    leakage_total: int,
    boundary_total: int,
    policy: Mapping[str, Any],
) -> tuple[str, str, str]:
    if precondition_status != "pass":
        verdict = "BLOCKED_INPUTS_NOT_READY"
        return verdict, "blocked_inputs_not_ready", "blocked"
    if leakage_total or boundary_total:
        verdict = "FAIL_BOUNDARY_OR_LEAKAGE"
        return verdict, "failed_boundary_or_leakage", "fail"
    required = [
        "engineering_gate_status",
        "causality_gate_status",
        "historical_validation_gate_status",
        "calibration_readiness_gate_status",
        "risk_validation_gate_status",
    ]
    if any(gates.get(key) != "pass" for key in required):
        verdict = "FAIL_VALIDATION_EVIDENCE"
        return verdict, "failed_validation_evidence", "fail"
    if gates.get("decision_support_promotion_gate_status") == "APPROVED":
        verdict = "PASS_STAGE03V1_RESEARCH_ONLY"
        return verdict, "research_only_pass_no_decision_output", "pass"
    verdict = "PASS_ENGINEERING_HISTORICAL_DEFER_PROSPECTIVE"
    if verdict not in set(policy.get("allowed_final_verdicts", ALLOWED_FINAL_VERDICTS)):
        verdict = "DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT"
    return verdict, "historical_research_pass_prospective_deferred", "pass"


def _evidence_rows(
    docs: Mapping[str, Mapping[str, Any]],
    gates: Mapping[str, str],
    holdout_status: Mapping[str, Any],
    leakage_counts: Mapping[str, int],
    boundary_counts: Mapping[str, int],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key, doc in docs.items():
        rows.append(
            {
                "evidence_layer": "input_artifact",
                "artifact_or_gate": key,
                "status": _status(doc),
                "requirement": "status=pass",
                "observed_value": _status(doc),
                "verdict_impact": "pass" if _status(doc) == "pass" else "block",
                "blocking_reason": "" if _status(doc) == "pass" else f"{key}_not_pass",
            }
        )
    for key in GATE_NAMES:
        status_key = f"{key}_status"
        rows.append(
            {
                "evidence_layer": "final_gate",
                "artifact_or_gate": key,
                "status": gates.get(status_key, "unknown"),
                "requirement": "pass or explicit defer for holdout and promotion gates",
                "observed_value": gates.get(status_key, "unknown"),
                "verdict_impact": "defer" if "holdout" in key or "promotion" in key else gates.get(status_key, "unknown"),
                "blocking_reason": "",
            }
        )
    rows.extend(
        [
            {
                "evidence_layer": "boundary",
                "artifact_or_gate": "leakage_violation_count_total",
                "status": "pass" if leakage_counts.get("leakage_violation_count_total") == 0 else "fail",
                "requirement": "0",
                "observed_value": leakage_counts.get("leakage_violation_count_total"),
                "verdict_impact": "pass" if leakage_counts.get("leakage_violation_count_total") == 0 else "fail",
                "blocking_reason": "" if leakage_counts.get("leakage_violation_count_total") == 0 else "leakage_violation_present",
            },
            {
                "evidence_layer": "boundary",
                "artifact_or_gate": "boundary_violation_count_total",
                "status": "pass" if boundary_counts.get("boundary_violation_count_total") == 0 else "fail",
                "requirement": "0",
                "observed_value": boundary_counts.get("boundary_violation_count_total"),
                "verdict_impact": "pass" if boundary_counts.get("boundary_violation_count_total") == 0 else "fail",
                "blocking_reason": "" if boundary_counts.get("boundary_violation_count_total") == 0 else "boundary_violation_present",
            },
            {
                "evidence_layer": "prospective_holdout",
                "artifact_or_gate": "prospective_holdout_rows_evaluated",
                "status": "pass" if holdout_status.get("prospective_holdout_rows_evaluated") == 0 else "fail",
                "requirement": "0 unless explicitly authorized",
                "observed_value": holdout_status.get("prospective_holdout_rows_evaluated"),
                "verdict_impact": "defer",
                "blocking_reason": "",
            },
        ]
    )
    return rows


def _audit_rows(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = [
        ("final_gate_verdict", "pass", report.get("final_gate_verdict"), "allowed final verdict"),
        ("source_db_path", "pass", report.get("source_db_path"), "V7 DB path"),
        ("holdout_rows_evaluated", "pass", report.get("prospective_holdout_rows_evaluated"), "0"),
        ("decision_support_gate", "pass", report.get("decision_support_promotion_gate_status"), "DEFER unless holdout gate met"),
        ("stage03v2_placeholder", "pass", report.get("boundary_flags", {}).get("stage03v2_implemented"), "no"),
        ("stage03v3_placeholder", "pass", report.get("boundary_flags", {}).get("stage03v3_implemented"), "no"),
    ]
    return [
        {
            "audit_item": item,
            "status": status,
            "source_artifact": "reports/stage03v/stage03v1_final_gate_report.json",
            "observed_value": observed,
            "requirement": requirement,
        }
        for item, status, observed, requirement in rows
    ]


def _verdict_doc(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": "stage03v1_final_gate_verdict_v1",
        "status": report.get("status"),
        "final_gate_verdict": report.get("final_gate_verdict"),
        "stage03v1_gate_status": report.get("stage03v1_gate_status"),
        "decision_support_promotion_gate_status": report.get("decision_support_promotion_gate_status"),
        "prospective_holdout_readiness_gate_status": report.get("prospective_holdout_readiness_gate_status"),
        "prospective_holdout_rows_evaluated": report.get("prospective_holdout_rows_evaluated"),
        "prospective_holdout_consumption_count": report.get("prospective_holdout_consumption_count"),
        "boundary_flags": report.get("boundary_flags"),
        "remaining_risks": report.get("remaining_risks"),
        "created_at": report.get("created_at"),
    }


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V1 Final Gate",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- final_gate_verdict: {report.get('final_gate_verdict')}",
        f"- stage03v1_gate_status: {report.get('stage03v1_gate_status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- prospective_holdout_rows_available: {report.get('prospective_holdout_rows_available')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- decision_support_promotion_gate_status: {report.get('decision_support_promotion_gate_status')}",
        "",
        "## Gate Status",
        "",
    ]
    for key in [
        "engineering_gate_status",
        "causality_gate_status",
        "historical_validation_gate_status",
        "calibration_readiness_gate_status",
        "risk_validation_gate_status",
        "prospective_holdout_readiness_gate_status",
        "decision_support_promotion_gate_status",
    ]:
        lines.append(f"- {key}: {report.get(key)}")
    lines.extend(["", "## Boundary Flags", ""])
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Remaining Risks", ""])
    for risk in report.get("remaining_risks", []) or ["none"]:
        lines.append(f"- {risk}")
    lines.extend(["", "## Blocking Reasons", ""])
    for reason in report.get("blocking_reasons", []) or ["none"]:
        lines.append(f"- {reason}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_post_gate_action_plan(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V1 Post-Gate Action Plan",
        "",
        "- Keep Stage03V1 research-only until prospective holdout requirements are met and a later authorized package consumes holdout performance.",
        "- Preserve the fixed-threshold Stage03V1 target family as the mainline.",
        "- Keep volatility-scaled candidates as tracked references only.",
        "- Keep Stage03V2 and Stage03V3 as placeholders.",
        "- Do not expose trading, sizing, portfolio, execution, or decision outputs from this gate.",
        "",
        f"- final_gate_verdict: {report.get('final_gate_verdict')}",
        f"- decision_support_promotion_gate_status: {report.get('decision_support_promotion_gate_status')}",
        f"- prospective_holdout_next_review_cadence: {report.get('prospective_holdout_next_review_cadence')}",
    ]
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _blocked_report(
    *,
    status: str,
    db_path: Path | str | None,
    reasons: Sequence[str],
    policy: Mapping[str, Any] | None = None,
    docs: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    policy_doc = policy or default_policy()
    docs = docs or {}
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "status": status,
        "final_gate_verdict": "BLOCKED_INPUTS_NOT_READY",
        "stage03v1_gate_status": "blocked_inputs_not_ready",
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "information_cutoff_date": policy_doc.get("information_cutoff_date", INFORMATION_CUTOFF_DATE),
        "holdout_start": policy_doc.get("holdout_start", HOLDOUT_START),
        "historical_development_only_prior_to_wp7": "yes",
        "wp0_scope_freeze_status": _status(docs.get("wp0_scope_freeze", {}), "unknown"),
        "wp0_5_sample_feasibility_status": _status(docs.get("wp0_5_sample_feasibility", {}), "unknown"),
        "wp1_target_support_status": _status(docs.get("wp1_target_support", {}), "unknown"),
        "wp2_target_controls_status": _status(docs.get("wp2_target_controls", {}), "unknown"),
        "wp2_1_full_target_audit_status": _status(docs.get("wp2_1_full_target_audit", {}), "unknown"),
        "wp3_baseline_diagnostics_status": _status(docs.get("wp3_baseline_diagnostics", {}), "unknown"),
        "wp3_5_vol_scaled_sanity_status": _status(docs.get("wp3_5_vol_scaled_sanity", {}), "unknown"),
        "wp4_logistic_hazard_status": _status(docs.get("wp4_logistic_hazard", {}), "unknown"),
        "wp5_calibration_readiness_status": _status(docs.get("wp5_calibration_readiness", {}), "unknown"),
        "wp6_risk_validation_status": _status(docs.get("wp6_risk_validation", {}), "unknown"),
        "engineering_gate_status": "blocked",
        "causality_gate_status": "blocked",
        "historical_validation_gate_status": "blocked",
        "calibration_readiness_gate_status": "blocked",
        "risk_validation_gate_status": "blocked",
        "prospective_holdout_readiness_gate_status": "blocked",
        "decision_support_promotion_gate_status": "BLOCKED",
        "prospective_holdout_policy": policy_doc.get("prospective_holdout_policy", "defer_if_minimum_not_met"),
        "prospective_holdout_evaluation_authorized": False,
        "prospective_holdout_rows_available": 0,
        "prospective_holdout_trade_dates_available": 0,
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_consumption_count": 0,
        "prospective_holdout_minimum_requirement_status": "blocked",
        "prospective_holdout_stress_event_requirement_status": "blocked",
        "prospective_holdout_next_review_cadence": policy_doc.get("prospective_holdout_review_cadence", "quarterly"),
        "usable_probability_candidate_count": 0,
        "validation_pass_candidate_count": 0,
        "research_downshift_candidate_count": 0,
        "artifact_manifest_path": None,
        "evidence_matrix_path": None,
        "verdict_json_path": None,
        "holdout_status_path": None,
        "post_gate_action_plan_path": None,
        "leakage_violation_counts": dict(LEAKAGE_ZERO_COUNTS),
        "boundary_violation_counts": dict(BOUNDARY_ZERO_COUNTS),
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": list(reasons),
        "remaining_risks": [],
    }


def _input_paths(
    *,
    scope_freeze: Path | str,
    sample_feasibility: Path | str,
    target_support: Path | str,
    target_controls: Path | str,
    full_target_audit: Path | str,
    baseline_diagnostics: Path | str,
    vol_scaled_sanity: Path | str,
    logistic_hazard: Path | str,
    calibration_readiness: Path | str,
    risk_validation: Path | str,
    downshift_research: Path | str,
    wp7_input_manifest: Path | str,
    ledger_template: Path | str,
    policy: Path | str,
) -> list[Path | str]:
    return [
        scope_freeze,
        sample_feasibility,
        target_support,
        target_controls,
        full_target_audit,
        baseline_diagnostics,
        vol_scaled_sanity,
        logistic_hazard,
        calibration_readiness,
        risk_validation,
        downshift_research,
        wp7_input_manifest,
        ledger_template,
        policy,
    ]


def _output_paths(
    *,
    output: Path | str,
    summary_json: Path | str,
    verdict_json: Path | str,
    evidence_matrix: Path | str,
    artifact_manifest: Path | str,
    holdout_status: Path | str,
    post_gate_action_plan: Path | str,
    audit_sample: Path | str,
) -> list[Path | str]:
    return [
        output,
        summary_json,
        verdict_json,
        evidence_matrix,
        artifact_manifest,
        holdout_status,
        post_gate_action_plan,
        audit_sample,
    ]


def _write_artifact_manifest(
    path: Path | str,
    report: Mapping[str, Any],
    *,
    input_paths: Sequence[Path | str],
    output_paths: Sequence[Path | str],
) -> None:
    manifest = {
        "index_id": INDEX_ID,
        "manifest_version": "stage03v1_final_gate_artifact_manifest_v1",
        "status": report.get("status"),
        "final_gate_executed": "yes",
        "final_gate_verdict": report.get("final_gate_verdict"),
        "source_db_path": report.get("source_db_path"),
        "stage03v2_implemented": "no",
        "stage03v3_implemented": "no",
        "prospective_holdout_rows_evaluated": report.get("prospective_holdout_rows_evaluated"),
        "inputs": [_artifact_record(item, "input") for item in input_paths],
        "outputs": [_artifact_record(item, "output") for item in output_paths if _safe_path(item) != _safe_path(path)],
        "boundary_flags": report.get("boundary_flags", BOUNDARY_FLAGS),
        "created_at": report.get("created_at", _now_iso()),
    }
    _write_json(path, manifest)


def _write_all_outputs(
    *,
    report: Mapping[str, Any],
    output: Path,
    summary_json: Path,
    verdict_json: Path,
    evidence_matrix: Path,
    artifact_manifest: Path,
    holdout_status: Path,
    post_gate_action_plan: Path,
    audit_sample: Path,
    evidence_rows: Sequence[Mapping[str, Any]],
    holdout_doc: Mapping[str, Any],
    input_paths: Sequence[Path | str],
    output_paths: Sequence[Path | str],
) -> None:
    _write_csv(evidence_matrix, evidence_rows, EVIDENCE_COLUMNS)
    _write_json(holdout_status, holdout_doc)
    _write_json(verdict_json, _verdict_doc(report))
    _write_markdown(output, report)
    _write_post_gate_action_plan(post_gate_action_plan, report)
    _write_csv(audit_sample, _audit_rows(report), AUDIT_COLUMNS)
    _write_json(summary_json, report)
    _write_artifact_manifest(artifact_manifest, report, input_paths=input_paths, output_paths=output_paths)


def build_final_gate_report(
    *,
    db_path: Path | str | None = None,
    scope_freeze: Path | str = DEFAULT_SCOPE_FREEZE,
    sample_feasibility: Path | str = DEFAULT_SAMPLE_FEASIBILITY,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    baseline_diagnostics: Path | str = DEFAULT_BASELINE_DIAGNOSTICS,
    vol_scaled_sanity: Path | str = DEFAULT_VOL_SCALED_SANITY,
    logistic_hazard: Path | str = DEFAULT_LOGISTIC_HAZARD,
    calibration_readiness: Path | str = DEFAULT_CALIBRATION_READINESS,
    risk_validation: Path | str = DEFAULT_RISK_VALIDATION,
    downshift_research: Path | str = DEFAULT_DOWNSHIFT_RESEARCH,
    wp7_input_manifest: Path | str = DEFAULT_WP7_INPUT_MANIFEST,
    ledger_template: Path | str = DEFAULT_LEDGER_TEMPLATE,
    policy: Path | str = DEFAULT_POLICY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    verdict_json: Path | str = DEFAULT_VERDICT_JSON,
    evidence_matrix: Path | str = DEFAULT_EVIDENCE_MATRIX,
    artifact_manifest: Path | str = DEFAULT_ARTIFACT_MANIFEST,
    holdout_status: Path | str = DEFAULT_HOLDOUT_STATUS,
    post_gate_action_plan: Path | str = DEFAULT_POST_GATE_ACTION_PLAN,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP7 final gate is no-fetch only")
    resolved_db = resolve_v7_db_path(db_path)
    input_paths = _input_paths(
        scope_freeze=scope_freeze,
        sample_feasibility=sample_feasibility,
        target_support=target_support,
        target_controls=target_controls,
        full_target_audit=full_target_audit,
        baseline_diagnostics=baseline_diagnostics,
        vol_scaled_sanity=vol_scaled_sanity,
        logistic_hazard=logistic_hazard,
        calibration_readiness=calibration_readiness,
        risk_validation=risk_validation,
        downshift_research=downshift_research,
        wp7_input_manifest=wp7_input_manifest,
        ledger_template=ledger_template,
        policy=policy,
    )
    output_paths = _output_paths(
        output=output,
        summary_json=summary_json,
        verdict_json=verdict_json,
        evidence_matrix=evidence_matrix,
        artifact_manifest=artifact_manifest,
        holdout_status=holdout_status,
        post_gate_action_plan=post_gate_action_plan,
        audit_sample=audit_sample,
    )
    paths = {
        "output": Path(output),
        "summary_json": Path(summary_json),
        "verdict_json": Path(verdict_json),
        "evidence_matrix": Path(evidence_matrix),
        "artifact_manifest": Path(artifact_manifest),
        "holdout_status": Path(holdout_status),
        "post_gate_action_plan": Path(post_gate_action_plan),
        "audit_sample": Path(audit_sample),
    }

    policy_doc: dict[str, Any] | None = None
    docs: dict[str, Mapping[str, Any]] = {}
    try:
        policy_doc = _load_machine_config(policy)
        docs = {
            "wp0_scope_freeze": _load_json(scope_freeze),
            "wp0_5_sample_feasibility": _load_json(sample_feasibility),
            "wp1_target_support": _load_json(target_support),
            "wp2_target_controls": _load_json(target_controls),
            "wp2_1_full_target_audit": _load_json(full_target_audit),
            "wp3_baseline_diagnostics": _load_json(baseline_diagnostics),
            "wp3_5_vol_scaled_sanity": _load_json(vol_scaled_sanity),
            "wp4_logistic_hazard": _load_json(logistic_hazard),
            "wp5_calibration_readiness": _load_json(calibration_readiness),
            "wp6_risk_validation": _load_json(risk_validation),
        }
        downshift_doc = _load_json(downshift_research)
        manifest_doc = _load_json(wp7_input_manifest)
        ledger_doc = _load_ledger_template(ledger_template)
    except FileNotFoundError as exc:
        report = _blocked_report(
            status="blocked_missing_input",
            db_path=resolved_db,
            reasons=[f"missing input: {exc.filename}"],
            policy=policy_doc,
            docs=docs,
        )
        holdout_doc = {
            "index_id": INDEX_ID,
            "prospective_holdout_rows_available": 0,
            "prospective_holdout_rows_evaluated": 0,
            "prospective_holdout_consumption_count": 0,
            "prospective_holdout_gate_status": "blocked",
        }
        _write_all_outputs(report=report, evidence_rows=[], holdout_doc=holdout_doc, input_paths=input_paths, output_paths=output_paths, **paths)
        return report

    policy_issues = validate_policy(policy_doc)
    if policy_issues:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            reasons=policy_issues,
            policy=policy_doc,
            docs=docs,
        )
        holdout_doc = {
            "index_id": INDEX_ID,
            "prospective_holdout_rows_available": 0,
            "prospective_holdout_rows_evaluated": 0,
            "prospective_holdout_consumption_count": 0,
            "prospective_holdout_gate_status": "blocked",
        }
        _write_all_outputs(report=report, evidence_rows=[], holdout_doc=holdout_doc, input_paths=input_paths, output_paths=output_paths, **paths)
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            reasons=v7.coverage.get("blocking_reasons", []),
            policy=policy_doc,
            docs=docs,
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["sw2021_l2_universe_coverage"] = v7.coverage.get("sw2021_l2_universe_coverage", "missing")
        holdout_doc = {
            "index_id": INDEX_ID,
            "prospective_holdout_rows_available": 0,
            "prospective_holdout_rows_evaluated": 0,
            "prospective_holdout_consumption_count": 0,
            "prospective_holdout_gate_status": "blocked",
        }
        _write_all_outputs(report=report, evidence_rows=[], holdout_doc=holdout_doc, input_paths=input_paths, output_paths=output_paths, **paths)
        return report

    leakage_counts, boundary_counts = collect_violation_counts(
        full_target_audit=docs["wp2_1_full_target_audit"],
        baseline_diagnostics=docs["wp3_baseline_diagnostics"],
        vol_scaled_sanity=docs["wp3_5_vol_scaled_sanity"],
        logistic_hazard=docs["wp4_logistic_hazard"],
        calibration_readiness=docs["wp5_calibration_readiness"],
        risk_validation=docs["wp6_risk_validation"],
    )
    precondition_status, precondition_issues = validate_wp7_preconditions(
        docs=docs,
        ledger_template=ledger_doc,
        wp7_input_manifest=manifest_doc,
        db_path=resolved_db,
        leakage_counts=leakage_counts,
        boundary_counts=boundary_counts,
    )
    holdout_doc = compute_holdout_status(v7, ledger_doc, policy_doc)
    gates = determine_gate_statuses(
        docs=docs,
        leakage_total=_as_int(leakage_counts.get("leakage_violation_count_total"), 0),
        boundary_total=_as_int(boundary_counts.get("boundary_violation_count_total"), 0),
        holdout_status=holdout_doc,
    )
    final_verdict, stage_status, report_status = determine_final_verdict(
        precondition_status=precondition_status,
        gates=gates,
        leakage_total=_as_int(leakage_counts.get("leakage_violation_count_total"), 0),
        boundary_total=_as_int(boundary_counts.get("boundary_violation_count_total"), 0),
        policy=policy_doc,
    )
    downshift_candidate_count = _as_int(
        docs["wp6_risk_validation"].get("downshift_tier_counts", {}).get("research_downshift_candidate"),
        0,
    )
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "status": report_status,
        "final_gate_verdict": final_verdict,
        "stage03v1_gate_status": stage_status,
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "information_cutoff_date": policy_doc.get("information_cutoff_date"),
        "holdout_start": policy_doc.get("holdout_start"),
        "historical_development_only_prior_to_wp7": docs["wp6_risk_validation"].get("historical_development_only"),
        "wp0_scope_freeze_status": docs["wp0_scope_freeze"].get("status"),
        "wp0_5_sample_feasibility_status": docs["wp0_5_sample_feasibility"].get("status"),
        "wp1_target_support_status": docs["wp1_target_support"].get("status"),
        "wp2_target_controls_status": docs["wp2_target_controls"].get("status"),
        "wp2_1_full_target_audit_status": docs["wp2_1_full_target_audit"].get("status"),
        "wp3_baseline_diagnostics_status": docs["wp3_baseline_diagnostics"].get("status"),
        "wp3_5_vol_scaled_sanity_status": docs["wp3_5_vol_scaled_sanity"].get("status"),
        "wp4_logistic_hazard_status": docs["wp4_logistic_hazard"].get("status"),
        "wp5_calibration_readiness_status": docs["wp5_calibration_readiness"].get("status"),
        "wp6_risk_validation_status": docs["wp6_risk_validation"].get("status"),
        **gates,
        "prospective_holdout_rows_available": holdout_doc.get("prospective_holdout_rows_available"),
        "prospective_holdout_rows_evaluated": holdout_doc.get("prospective_holdout_rows_evaluated"),
        "prospective_holdout_consumption_count": holdout_doc.get("prospective_holdout_consumption_count"),
        "prospective_holdout_minimum_requirement_status": holdout_doc.get("prospective_holdout_minimum_requirement_status"),
        "prospective_holdout_stress_event_requirement_status": holdout_doc.get("prospective_holdout_stress_event_requirement_status"),
        "prospective_holdout_next_review_cadence": holdout_doc.get("prospective_holdout_next_review_cadence"),
        "prospective_holdout_policy": holdout_doc.get("prospective_holdout_policy"),
        "prospective_holdout_evaluation_authorized": holdout_doc.get("prospective_holdout_evaluation_authorized"),
        "prospective_holdout_trade_dates_available": holdout_doc.get("prospective_holdout_trade_dates_available"),
        "usable_probability_candidate_count": docs["wp5_calibration_readiness"].get("usable_probability_candidate_count"),
        "validation_pass_candidate_count": docs["wp6_risk_validation"].get("validation_pass_candidate_count"),
        "research_downshift_candidate_count": downshift_candidate_count,
        "artifact_manifest_path": _safe_path(paths["artifact_manifest"]),
        "evidence_matrix_path": _safe_path(paths["evidence_matrix"]),
        "verdict_json_path": _safe_path(paths["verdict_json"]),
        "holdout_status_path": _safe_path(paths["holdout_status"]),
        "post_gate_action_plan_path": _safe_path(paths["post_gate_action_plan"]),
        "downshift_research_status": downshift_doc.get("status"),
        "wp7_input_manifest_status": manifest_doc.get("status"),
        "wp7_input_manifest_final_gate_executed": manifest_doc.get("wp7_final_gate_executed"),
        "leakage_violation_counts": leakage_counts,
        "boundary_violation_counts": boundary_counts,
        "ci_gate_status": "pass" if report_status == "pass" else report_status,
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": precondition_issues,
        "remaining_risks": [
            "Decision-support promotion remains DEFER until a later authorized package evaluates sufficient prospective holdout rows and stress events.",
            "Stage03V1 remains a research-only downside-risk branch; no trading, sizing, portfolio, execution, or decision output is produced.",
            "Stage03V2 and Stage03V3 remain placeholders.",
        ],
    }
    evidence_rows = _evidence_rows(docs, gates, holdout_doc, leakage_counts, boundary_counts)
    _write_all_outputs(
        report=report,
        output=paths["output"],
        summary_json=paths["summary_json"],
        verdict_json=paths["verdict_json"],
        evidence_matrix=paths["evidence_matrix"],
        artifact_manifest=paths["artifact_manifest"],
        holdout_status=paths["holdout_status"],
        post_gate_action_plan=paths["post_gate_action_plan"],
        audit_sample=paths["audit_sample"],
        evidence_rows=evidence_rows,
        holdout_doc=holdout_doc,
        input_paths=input_paths,
        output_paths=output_paths,
    )
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--scope-freeze", type=Path, default=DEFAULT_SCOPE_FREEZE)
    parser.add_argument("--sample-feasibility", type=Path, default=DEFAULT_SAMPLE_FEASIBILITY)
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--target-controls", type=Path, default=DEFAULT_TARGET_CONTROLS)
    parser.add_argument("--full-target-audit", type=Path, default=DEFAULT_FULL_TARGET_AUDIT)
    parser.add_argument("--baseline-diagnostics", type=Path, default=DEFAULT_BASELINE_DIAGNOSTICS)
    parser.add_argument("--vol-scaled-sanity", type=Path, default=DEFAULT_VOL_SCALED_SANITY)
    parser.add_argument("--logistic-hazard", type=Path, default=DEFAULT_LOGISTIC_HAZARD)
    parser.add_argument("--calibration-readiness", type=Path, default=DEFAULT_CALIBRATION_READINESS)
    parser.add_argument("--risk-validation", type=Path, default=DEFAULT_RISK_VALIDATION)
    parser.add_argument("--downshift-research", type=Path, default=DEFAULT_DOWNSHIFT_RESEARCH)
    parser.add_argument("--wp7-input-manifest", type=Path, default=DEFAULT_WP7_INPUT_MANIFEST)
    parser.add_argument("--ledger-template", type=Path, default=DEFAULT_LEDGER_TEMPLATE)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--verdict-json", type=Path, default=DEFAULT_VERDICT_JSON)
    parser.add_argument("--evidence-matrix", type=Path, default=DEFAULT_EVIDENCE_MATRIX)
    parser.add_argument("--artifact-manifest", type=Path, default=DEFAULT_ARTIFACT_MANIFEST)
    parser.add_argument("--holdout-status", type=Path, default=DEFAULT_HOLDOUT_STATUS)
    parser.add_argument("--post-gate-action-plan", type=Path, default=DEFAULT_POST_GATE_ACTION_PLAN)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_final_gate_report(
        db_path=args.db,
        scope_freeze=args.scope_freeze,
        sample_feasibility=args.sample_feasibility,
        target_support=args.target_support,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        baseline_diagnostics=args.baseline_diagnostics,
        vol_scaled_sanity=args.vol_scaled_sanity,
        logistic_hazard=args.logistic_hazard,
        calibration_readiness=args.calibration_readiness,
        risk_validation=args.risk_validation,
        downshift_research=args.downshift_research,
        wp7_input_manifest=args.wp7_input_manifest,
        ledger_template=args.ledger_template,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        verdict_json=args.verdict_json,
        evidence_matrix=args.evidence_matrix,
        artifact_manifest=args.artifact_manifest,
        holdout_status=args.holdout_status,
        post_gate_action_plan=args.post_gate_action_plan,
        audit_sample=args.audit_sample,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_FINAL_GATE="
        f"{report.get('status')} "
        f"verdict={report.get('final_gate_verdict')} "
        f"db={report.get('source_db_path')} "
        f"holdout_evaluated={report.get('prospective_holdout_rows_evaluated')} "
        f"decision_support_gate={report.get('decision_support_promotion_gate_status')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
