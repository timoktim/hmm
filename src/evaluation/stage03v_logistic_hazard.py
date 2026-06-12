"""Stage03V WP4 logistic downside-risk hazard.

This module trains deterministic logistic hazard models on historical
development training folds only. It is read-only with respect to DuckDB and
does not calibrate probabilities, assign readiness, score the prospective
holdout, or replace the fixed-threshold Stage03V1 target mainline.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_baseline_diagnostics import (
    BASELINE_DEFINITIONS,
    build_price_baseline_features,
    build_target_rows_for_trade_dates,
    compute_metric_row,
    read_ohlcv_inputs,
    slice_specs_from_target_support,
    validate_baseline_input_columns,
)
from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)
from src.evaluation.stage03v_vol_scaled_threshold_sanity import (
    detect_asof_violations,
    shifted_price_features,
)


INDEX_ID = "STAGE03V-WP4-v1"
REPORT_VERSION = "stage03v_logistic_hazard_v1"
POLICY_VERSION = "stage03v_logistic_hazard_policy_v1"
STAGE_ID = "stage03v"
MODEL_FAMILY = "logistic_regression"
MODEL_VARIANT = "sklearn_logistic_regression_l2_lbfgs"
DATE_AWARE_WEIGHTING_STATUS = "implemented"
PRIMARY_TARGET_FAMILY = "fixed_threshold_stage03v1_downside_event"
PRIMARY_ASOF_MODE = "close_t_minus_1"
ASOF_MODES = ["close_t_minus_1", "close_t"]
DEFAULT_SAMPLE_ROWS = 500

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_BASELINE_DIAGNOSTICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_BASELINE_FOLD_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_fold_metrics.csv"
DEFAULT_VOL_SCALED_SANITY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_logistic_hazard_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "logistic_hazard_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_FOLD_METRICS = ROOT / "reports" / "stage03v" / "logistic_hazard_fold_metrics.csv"
DEFAULT_SLICE_METRICS = ROOT / "reports" / "stage03v" / "logistic_hazard_slice_metrics.csv"
DEFAULT_COEFFICIENTS = ROOT / "reports" / "stage03v" / "logistic_hazard_coefficients.csv"
DEFAULT_MODEL_MANIFEST = ROOT / "reports" / "stage03v" / "logistic_hazard_model_manifest.json"
DEFAULT_FEATURE_AUDIT = ROOT / "reports" / "stage03v" / "logistic_hazard_feature_audit.csv"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "logistic_hazard_audit_sample.csv"

ALLOWED_FEATURE_FAMILIES = [
    "realized_volatility",
    "range_based_volatility",
    "recent_drawdown",
]

FEATURE_DEFINITIONS = [
    {
        "feature_name": str(item["name"]),
        "feature_family": str(item["family"]),
        "feature_source": "price_history",
        "allowed_in_wp4": "yes",
        "asof_requirement": "close_t <= trade_date; close_t_minus_1 < trade_date",
    }
    for item in BASELINE_DEFINITIONS
    if item.get("kind") == "price" and str(item.get("family")) in set(ALLOWED_FEATURE_FAMILIES)
]
MODEL_FEATURE_COLUMNS = [item["feature_name"] for item in FEATURE_DEFINITIONS]

FOLD_METRIC_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "row_count",
    "train_row_count",
    "validation_row_count",
    "scored_row_count",
    "positive_event_count",
    "event_base_rate",
    "score_available_rate",
    "roc_auc",
    "average_precision",
    "brier_score_uncalibrated",
    "log_loss_uncalibrated",
    "spearman_score_vs_event",
    "spearman_score_vs_future_mae",
    "spearman_score_vs_future_mdd",
    "quantile_lift_top_decile",
    "quantile_lift_top_quintile",
    "coefficient_l1_norm",
    "coefficient_l2_norm",
    "convergence_status",
    "insufficient_data_reason",
    "best_wp3_baseline_auc",
    "best_wp3_baseline_average_precision",
    "logistic_delta_auc_vs_best_baseline",
    "logistic_delta_ap_vs_best_baseline",
    "logistic_beats_best_baseline_flag",
]
SLICE_METRIC_COLUMNS = [column for column in FOLD_METRIC_COLUMNS if column != "fold_id"]
COEFFICIENT_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "feature_name",
    "feature_family",
    "coefficient",
    "abs_coefficient",
]
FEATURE_AUDIT_COLUMNS = [
    "feature_name",
    "feature_family",
    "feature_source",
    "allowed_in_wp4",
    "asof_requirement",
    "target_namespace_violation",
    "future_column_violation",
]
AUDIT_SAMPLE_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "entity_id",
    "trade_date",
    "feature_asof_date",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "score",
    "score_available",
    "event_label",
    "future_mae",
    "future_mdd",
    "future_return",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "full_feature_matrix_committed": "no",
    "full_score_matrix_committed": "no",
    "model_training": "yes",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
    "trading_or_decision_output": "no",
}

LEAKAGE_ZERO_COUNTS = {
    "feature_asof_violation_count": 0,
    "target_namespace_input_violation_count": 0,
    "future_column_input_violation_count": 0,
    "same_row_label_leakage_count": 0,
    "validation_label_leakage_count": 0,
    "prospective_holdout_score_count": 0,
    "prospective_holdout_metric_count": 0,
    "fixed_threshold_mainline_mutation_count": 0,
    "persistent_db_write_count": 0,
    "external_fetch_count": 0,
    "leakage_violation_count_total": 0,
}

TRAINING_BOUNDARY_ZERO_COUNTS = {
    "train_rows_after_validation_start_count": 0,
    "train_target_end_on_or_after_validation_start_count": 0,
    "validation_rows_used_for_fit_count": 0,
    "scaler_fit_on_validation_rows_count": 0,
    "imputer_fit_on_validation_rows_count": 0,
    "training_boundary_violation_count_total": 0,
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


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


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP4 Logistic Downside-Risk Hazard",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- wp1_support_status: {report.get('wp1_support_status')}",
        f"- wp2_controls_status: {report.get('wp2_controls_status')}",
        f"- wp2_1_full_target_audit_status: {report.get('wp2_1_full_target_audit_status')}",
        f"- wp3_baseline_diagnostics_status: {report.get('wp3_baseline_diagnostics_status')}",
        f"- wp3_5_vol_scaled_sanity_status: {report.get('wp3_5_vol_scaled_sanity_status')}",
        f"- model_family: {report.get('model_family')}",
        f"- primary_asof_mode: {report.get('primary_asof_mode')}",
        f"- validation_row_count_evaluated: {report.get('validation_row_count_evaluated')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- fitted_model_count: {report.get('fitted_model_count')}",
        f"- insufficient_data_slice_count: {report.get('insufficient_data_slice_count')}",
        f"- feature_count: {report.get('feature_count')}",
        f"- vol_scaled_candidate_tracking_status: {report.get('vol_scaled_candidate_tracking_status')}",
        f"- fixed_threshold_mainline_status: {report.get('fixed_threshold_mainline_status')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Leakage Counts",
        "",
    ]
    for key, value in report.get("leakage_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Training Boundary Counts", ""])
    for key, value in report.get("training_boundary_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Boundary Flags", ""])
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Remaining Risks", ""])
    risks = report.get("remaining_risks", [])
    if risks:
        for risk in risks:
            lines.append(f"- {risk}")
    else:
        lines.append("- none")
    lines.extend(["", "## Blocking Reasons", ""])
    reasons = report.get("blocking_reasons", [])
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _safe_div(numerator: float | int, denominator: float | int) -> float | None:
    denominator = float(denominator)
    if denominator == 0 or not math.isfinite(denominator):
        return None
    value = float(numerator) / denominator
    return value if math.isfinite(value) else None


def _normalise_date(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.normalize()


def _slice_key_columns() -> list[str]:
    return ["horizon", "threshold_type", "threshold_value", "target_usage"]


def _slice_key_from_row(row: Mapping[str, Any]) -> tuple[int, str, float, str]:
    return (
        int(row.get("horizon")),
        str(row.get("threshold_type", "fixed")),
        float(row.get("threshold_value")),
        str(row.get("target_usage", "eligible")),
    )


def _slice_id(row: Mapping[str, Any]) -> str:
    return (
        f"h{int(row.get('horizon'))}:"
        f"{row.get('threshold_type', 'fixed')}:"
        f"{float(row.get('threshold_value')):.4f}:"
        f"{row.get('target_usage', 'unknown')}"
    )


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "source_target_controls": "reports/stage03v/target_controls_report.json",
        "source_full_target_audit": "reports/stage03v/full_target_streaming_audit_report.json",
        "source_baseline_diagnostics": "reports/stage03v/baseline_diagnostics_report.json",
        "source_vol_scaled_sanity": "reports/stage03v/vol_scaled_threshold_sanity_report.json",
        "fold_plan": "reports/stage03v/purge_embargo_fold_plan.json",
        "primary_target_family": PRIMARY_TARGET_FAMILY,
        "vol_scaled_candidate_policy": "tracked_reference_only",
        "primary_asof_mode": PRIMARY_ASOF_MODE,
        "diagnostic_asof_modes": ASOF_MODES,
        "model_family": MODEL_FAMILY,
        "model_variant": MODEL_VARIANT,
        "solver": "lbfgs",
        "penalty": "l2",
        "max_iter": 1000,
        "random_state": 20260611,
        "class_weight": "balanced",
        "date_aware_sample_weighting": "enabled",
        "date_aware_weighting_status": DATE_AWARE_WEIGHTING_STATUS,
        "min_train_positive_events": 2,
        "min_train_negative_events": 2,
        "calibration_policy": "forbidden_in_wp4",
        "readiness_policy": "forbidden_in_wp4",
        "final_holdout_policy": "withheld_not_scored",
        "feature_families": ALLOWED_FEATURE_FAMILIES,
        "feature_asof_policy": {
            "close_t": "feature_asof_date <= trade_date",
            "close_t_minus_1": "feature_asof_date < trade_date",
        },
        "training_policy": "train_folds_only",
        "validation_policy": "validation_folds_only",
        "purge_embargo_policy": "accepted_wp2_fold_plan",
        "full_feature_matrix_policy": "forbidden_to_commit",
        "persistent_db_table_policy": "forbidden_by_default",
        "external_fetch_policy": "forbidden",
        "audit_sample_cap": DEFAULT_SAMPLE_ROWS,
        "boundary_flags": BOUNDARY_FLAGS,
    }


def validate_policy(policy: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    expected = default_policy()
    for key in ["index_id", "policy_version", "information_cutoff_date", "holdout_start"]:
        if policy.get(key) != expected[key]:
            issues.append(f"{key}_mismatch")
    if policy.get("primary_target_family") != PRIMARY_TARGET_FAMILY:
        issues.append("primary_target_family_mismatch")
    if policy.get("vol_scaled_candidate_policy") != "tracked_reference_only":
        issues.append("vol_scaled_candidate_policy_not_reference_only")
    if policy.get("primary_asof_mode") != PRIMARY_ASOF_MODE:
        issues.append("primary_asof_mode_mismatch")
    if list(policy.get("diagnostic_asof_modes", [])) != ASOF_MODES:
        issues.append("diagnostic_asof_modes_mismatch")
    if policy.get("model_family") != MODEL_FAMILY:
        issues.append("model_family_mismatch")
    for key in ["calibration_policy", "readiness_policy"]:
        if policy.get(key) != "forbidden_in_wp4":
            issues.append(f"{key}_not_forbidden_in_wp4")
    if policy.get("final_holdout_policy") != "withheld_not_scored":
        issues.append("final_holdout_policy_not_withheld")
    if policy.get("date_aware_sample_weighting") != "enabled":
        issues.append("date_aware_sample_weighting_not_enabled")
    if policy.get("date_aware_weighting_status") != DATE_AWARE_WEIGHTING_STATUS:
        issues.append("date_aware_weighting_status_not_implemented")
    if policy.get("training_policy") != "train_folds_only":
        issues.append("training_policy_not_train_folds_only")
    if policy.get("validation_policy") != "validation_folds_only":
        issues.append("validation_policy_not_validation_folds_only")
    if policy.get("external_fetch_policy") != "forbidden":
        issues.append("external_fetch_policy_not_forbidden")
    if policy.get("persistent_db_table_policy") != "forbidden_by_default":
        issues.append("persistent_db_table_policy_not_forbidden")
    if set(policy.get("feature_families", [])) != set(ALLOWED_FEATURE_FAMILIES):
        issues.append("feature_families_mismatch")
    return issues


def validate_feature_columns(columns: Sequence[str]) -> dict[str, Any]:
    return validate_baseline_input_columns(columns)


def _feature_family(feature_name: str) -> str:
    for item in FEATURE_DEFINITIONS:
        if item["feature_name"] == feature_name:
            return str(item["feature_family"])
    if feature_name == "intercept":
        return "intercept"
    return "unknown"


def build_feature_audit_rows(feature_columns: Sequence[str]) -> list[dict[str, Any]]:
    namespace = validate_feature_columns(feature_columns)
    target_violations = set(namespace.get("target_namespace_input_violations", []))
    future_violations = set(namespace.get("future_column_input_violations", []))
    rows: list[dict[str, Any]] = []
    definition_by_name = {item["feature_name"]: item for item in FEATURE_DEFINITIONS}
    for column in feature_columns:
        definition = definition_by_name.get(str(column), {})
        rows.append(
            {
                "feature_name": str(column),
                "feature_family": definition.get("feature_family", _feature_family(str(column))),
                "feature_source": definition.get("feature_source", "unknown"),
                "allowed_in_wp4": definition.get("allowed_in_wp4", "no"),
                "asof_requirement": definition.get(
                    "asof_requirement",
                    "close_t <= trade_date; close_t_minus_1 < trade_date",
                ),
                "target_namespace_violation": "yes" if str(column) in target_violations else "no",
                "future_column_violation": "yes" if str(column) in future_violations else "no",
            }
        )
    return rows


def validate_wp4_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    full_target_audit: Mapping[str, Any],
    baseline_diagnostics: Mapping[str, Any],
    vol_scaled_sanity: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    db_path: Path | str,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    if target_support.get("status") != "pass":
        issues.append("wp1_support_status_not_pass")
    if target_controls.get("status") != "pass":
        issues.append("wp2_controls_status_not_pass")
    if full_target_audit.get("status") != "pass":
        issues.append("wp2_1_full_target_audit_status_not_pass")
    if baseline_diagnostics.get("status") != "pass":
        issues.append("wp3_baseline_diagnostics_status_not_pass")
    if vol_scaled_sanity.get("status") != "pass":
        issues.append("wp3_5_vol_scaled_sanity_status_not_pass")
    if vol_scaled_sanity.get("wp4_entry_recommendation") != "proceed_with_vol_scaled_candidate_tracking":
        issues.append("wp3_5_wp4_entry_recommendation_not_proceed")
    if fold_plan.get("status") != "pass" or _as_int(fold_plan.get("fold_count"), default=0) <= 0:
        issues.append("fold_plan_status_not_pass")
    if _as_int(fold_plan.get("purge_violation_count"), default=-1) != 0:
        issues.append("fold_plan_purge_violation_count_not_zero")
    if _as_int(fold_plan.get("embargo_violation_count"), default=-1) != 0:
        issues.append("fold_plan_embargo_violation_count_not_zero")

    if target_support.get("v7_coverage_available") != "yes":
        issues.append("wp1_v7_coverage_not_verified")
    for label, doc in [
        ("wp1", target_support),
        ("wp2", target_controls),
        ("wp2_1", full_target_audit),
        ("wp3", baseline_diagnostics),
        ("wp3_5", vol_scaled_sanity),
    ]:
        if doc.get("sw2021_l2_universe_coverage") != "pass":
            issues.append(f"{label}_sw2021_l2_universe_not_pass")
        if doc.get("v7_coverage_available") != "yes":
            issues.append(f"{label}_v7_coverage_not_yes")

    leakage_docs = [
        ("wp3", baseline_diagnostics),
        ("wp3_5", vol_scaled_sanity),
    ]
    for label, doc in leakage_docs:
        total = _as_int(doc.get("leakage_violation_counts", {}).get("leakage_violation_count_total"), default=0)
        if total != 0:
            issues.append(f"{label}_leakage_violation_count_not_zero")
        if _as_int(doc.get("prospective_holdout_rows_evaluated"), default=0) != 0:
            issues.append(f"{label}_prospective_holdout_rows_evaluated_not_zero")

    expected_paths = {
        str(value)
        for value in [
            target_support.get("source_db_path"),
            target_controls.get("source_db_path"),
            full_target_audit.get("source_db_path"),
            baseline_diagnostics.get("source_db_path"),
            vol_scaled_sanity.get("source_db_path"),
        ]
        if value
    }
    resolved_safe = _safe_path(db_path)
    if not os.environ.get("STAGE03V_V7_DB") and expected_paths and resolved_safe not in expected_paths:
        issues.append("resolved_db_path_does_not_match_accepted_stage03v_artifacts")

    if not issues:
        return "pass", []
    if any(issue.startswith("wp3_5") for issue in issues):
        return "blocked_wp3_5_not_ready", issues
    if any(issue.startswith("wp3") for issue in issues):
        return "blocked_wp3_not_ready", issues
    return "blocked_inputs_not_ready", issues


def _labeled_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    work = rows.copy()
    return work[work["censoring_status"].astype(str).eq("labeled") & work["event_label"].notna()].copy()


def split_fold_rows(target_rows: pd.DataFrame, fold: Mapping[str, Any]) -> dict[str, Any]:
    validation_start = _normalise_date(fold.get("validation_start_date"))
    validation_end = _normalise_date(fold.get("validation_end_date"))
    train_start = _normalise_date(fold.get("train_start_date"))
    train_end = _normalise_date(fold.get("train_end_date"))
    if validation_start is None or validation_end is None or target_rows.empty:
        empty = target_rows.iloc[0:0].copy()
        return {
            "train_rows": empty,
            "validation_rows": empty,
            "prospective_holdout_rows_withheld": 0,
            "training_boundary_violation_counts": dict(TRAINING_BOUNDARY_ZERO_COUNTS),
        }
    work = target_rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["target_observation_end_date"] = pd.to_datetime(
        work["target_observation_end_date"], errors="coerce"
    ).dt.normalize()
    holdout = pd.Timestamp(HOLDOUT_START).normalize()

    validation = work[work["trade_date"].between(validation_start, validation_end, inclusive="both")].copy()
    holdout_mask = validation["trade_date"].ge(holdout) | validation["split_role"].astype(str).eq("prospective_final_holdout")
    withheld = int(holdout_mask.sum())
    validation = validation[~holdout_mask].copy()
    validation = _labeled_rows(validation)

    train_mask = (
        work["trade_date"].lt(validation_start)
        & work["target_observation_end_date"].lt(validation_start)
        & work["split_role"].astype(str).eq("historical_development")
    )
    if train_start is not None:
        train_mask &= work["trade_date"].ge(train_start)
    if train_end is not None:
        train_mask &= work["trade_date"].le(train_end)
    train = _labeled_rows(work[train_mask].copy())
    counts = detect_training_boundary_violations(train, fold)
    return {
        "train_rows": train,
        "validation_rows": validation,
        "prospective_holdout_rows_withheld": withheld,
        "training_boundary_violation_counts": counts,
    }


def detect_training_boundary_violations(train_rows: pd.DataFrame, fold: Mapping[str, Any]) -> dict[str, int]:
    counts = dict(TRAINING_BOUNDARY_ZERO_COUNTS)
    validation_start = _normalise_date(fold.get("validation_start_date"))
    if validation_start is None or train_rows.empty:
        return counts
    trade_date = pd.to_datetime(train_rows.get("trade_date"), errors="coerce").dt.normalize()
    target_end = pd.to_datetime(train_rows.get("target_observation_end_date"), errors="coerce").dt.normalize()
    counts["train_rows_after_validation_start_count"] = int(trade_date.ge(validation_start).sum())
    counts["train_target_end_on_or_after_validation_start_count"] = int(target_end.ge(validation_start).sum())
    counts["training_boundary_violation_count_total"] = int(sum(value for key, value in counts.items() if key != "training_boundary_violation_count_total"))
    return counts


def _prepare_feature_join(rows: pd.DataFrame, features: pd.DataFrame, feature_columns: Sequence[str]) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    base = rows.copy().reset_index(drop=True)
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce").dt.normalize()
    feature_cols = ["entity_id", "trade_date", "feature_asof_date", *feature_columns]
    available = [column for column in feature_cols if column in features.columns]
    feature_frame = features[available].copy() if available else pd.DataFrame(columns=feature_cols)
    if feature_frame.empty:
        for column in ["feature_asof_date", *feature_columns]:
            if column not in base.columns:
                base[column] = pd.NaT if column == "feature_asof_date" else np.nan
        return base
    feature_frame["entity_id"] = feature_frame["entity_id"].astype(str)
    feature_frame["trade_date"] = pd.to_datetime(feature_frame["trade_date"], errors="coerce").dt.normalize()
    feature_frame = feature_frame.drop_duplicates(["entity_id", "trade_date"], keep="last")
    merged = base.merge(feature_frame, on=["entity_id", "trade_date"], how="left")
    for column in feature_columns:
        if column not in merged.columns:
            merged[column] = np.nan
    if "feature_asof_date" not in merged.columns:
        merged["feature_asof_date"] = pd.NaT
    return merged


def fit_train_only_preprocessor(
    train_frame: pd.DataFrame,
    validation_frame: pd.DataFrame,
    feature_columns: Sequence[str],
    *,
    imputation_strategy: str = "median",
) -> dict[str, Any]:
    try:
        from sklearn.impute import SimpleImputer
        from sklearn.preprocessing import StandardScaler
    except ModuleNotFoundError as exc:
        raise RuntimeError("blocked_missing_sklearn") from exc

    X_train = train_frame[list(feature_columns)].apply(pd.to_numeric, errors="coerce")
    X_validation = validation_frame[list(feature_columns)].apply(pd.to_numeric, errors="coerce")
    try:
        imputer = SimpleImputer(strategy=imputation_strategy, keep_empty_features=True)
    except TypeError:
        imputer = SimpleImputer(strategy=imputation_strategy)
    scaler = StandardScaler()
    X_train_imputed = imputer.fit_transform(X_train)
    X_validation_imputed = imputer.transform(X_validation)
    X_train_scaled = scaler.fit_transform(X_train_imputed)
    X_validation_scaled = scaler.transform(X_validation_imputed)
    return {
        "imputer": imputer,
        "scaler": scaler,
        "X_train": np.asarray(X_train_scaled, dtype=float),
        "X_validation": np.asarray(X_validation_scaled, dtype=float),
        "imputer_statistics": np.asarray(getattr(imputer, "statistics_", []), dtype=float),
        "scaler_mean": np.asarray(getattr(scaler, "mean_", []), dtype=float),
        "scaler_scale": np.asarray(getattr(scaler, "scale_", []), dtype=float),
        "fit_on_validation_rows_count": 0,
    }


def _log_loss_uncalibrated(y: np.ndarray, score: np.ndarray) -> float | None:
    if len(y) == 0:
        return None
    clipped = np.clip(score.astype(float), 1e-15, 1 - 1e-15)
    value = -np.mean(y.astype(float) * np.log(clipped) + (1 - y.astype(float)) * np.log(1 - clipped))
    return float(value) if math.isfinite(value) else None


def _positive_negative_counts(rows: pd.DataFrame) -> tuple[int, int]:
    if rows.empty or "event_label" not in rows.columns:
        return 0, 0
    labels = rows["event_label"].astype(bool).astype(int)
    positives = int(labels.sum())
    negatives = int(len(labels) - positives)
    return positives, negatives


def date_aware_sample_weights(rows: pd.DataFrame) -> np.ndarray:
    """Give each training trade date bounded total influence before class weighting."""

    if rows.empty or "trade_date" not in rows.columns:
        return np.array([], dtype=float)
    dates = pd.to_datetime(rows["trade_date"], errors="coerce").dt.normalize()
    counts = dates.value_counts(dropna=False)
    weights = dates.map(counts).astype(float).replace({0.0: np.nan})
    weights = 1.0 / weights
    weights = weights.fillna(1.0)
    return weights.to_numpy(dtype=float)


def _metric_from_scored(
    scored_rows: pd.DataFrame,
    *,
    fold_id: str | None,
    train_row_count: int,
    coefficient_l1_norm: float | None,
    coefficient_l2_norm: float | None,
    convergence_status: str,
    insufficient_data_reason: str | None,
) -> dict[str, Any]:
    base = compute_metric_row(
        scored_rows,
        baseline_family=MODEL_FAMILY,
        baseline_name=MODEL_VARIANT,
        fold_id=fold_id,
    )
    scored = scored_rows[pd.to_numeric(scored_rows.get("score"), errors="coerce").notna()].copy()
    y = scored["event_label"].astype(bool).astype(int).to_numpy(dtype=int) if not scored.empty else np.array([], dtype=int)
    score = pd.to_numeric(scored.get("score"), errors="coerce").to_numpy(dtype=float) if not scored.empty else np.array([], dtype=float)
    finite = np.isfinite(score)
    y = y[finite]
    score = score[finite]
    row = {
        "row_count": base.get("row_count"),
        "train_row_count": int(train_row_count),
        "validation_row_count": int(len(scored_rows)),
        "scored_row_count": base.get("scored_row_count"),
        "positive_event_count": base.get("positive_event_count"),
        "event_base_rate": base.get("event_base_rate"),
        "score_available_rate": base.get("score_available_rate"),
        "roc_auc": base.get("roc_auc"),
        "average_precision": base.get("average_precision"),
        "brier_score_uncalibrated": base.get("brier_like_score_if_score_in_0_1"),
        "log_loss_uncalibrated": _log_loss_uncalibrated(y, score),
        "spearman_score_vs_event": base.get("spearman_score_vs_event"),
        "spearman_score_vs_future_mae": base.get("spearman_score_vs_future_mae"),
        "spearman_score_vs_future_mdd": base.get("spearman_score_vs_future_mdd"),
        "quantile_lift_top_decile": base.get("quantile_lift_top_decile"),
        "quantile_lift_top_quintile": base.get("quantile_lift_top_quintile"),
        "coefficient_l1_norm": coefficient_l1_norm,
        "coefficient_l2_norm": coefficient_l2_norm,
        "convergence_status": convergence_status,
        "insufficient_data_reason": insufficient_data_reason,
    }
    for column in _slice_key_columns():
        row[column] = base.get(column)
    if fold_id is not None:
        row["fold_id"] = fold_id
    row["model_variant"] = MODEL_VARIANT
    return row


def fit_logistic_model(
    train_frame: pd.DataFrame,
    validation_frame: pd.DataFrame,
    feature_columns: Sequence[str],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    min_pos = int(policy.get("min_train_positive_events", 2))
    min_neg = int(policy.get("min_train_negative_events", 2))
    train_pos, train_neg = _positive_negative_counts(train_frame)
    if train_frame.empty:
        return {"status": "skipped", "insufficient_data_reason": "empty_training_rows"}
    if validation_frame.empty:
        return {"status": "skipped", "insufficient_data_reason": "empty_validation_rows"}
    if train_pos < min_pos:
        return {"status": "skipped", "insufficient_data_reason": "insufficient_positive_training_events"}
    if train_neg < min_neg:
        return {"status": "skipped", "insufficient_data_reason": "insufficient_negative_training_events"}
    try:
        from sklearn.linear_model import LogisticRegression
    except ModuleNotFoundError as exc:
        raise RuntimeError("blocked_missing_sklearn") from exc

    prep = fit_train_only_preprocessor(train_frame, validation_frame, feature_columns)
    y_train = train_frame["event_label"].astype(bool).astype(int).to_numpy(dtype=int)
    max_iter = int(policy.get("max_iter", 1000))
    class_weight = policy.get("class_weight", "balanced")
    if class_weight in ("none", "None", None):
        class_weight = None
    model_kwargs = {
        "solver": str(policy.get("solver", "lbfgs")),
        "max_iter": max_iter,
        "random_state": int(policy.get("random_state", 20260611)),
        "class_weight": class_weight,
    }
    penalty = str(policy.get("penalty", "l2"))
    if penalty != "l2":
        model_kwargs["penalty"] = penalty
    model = LogisticRegression(**model_kwargs)
    sample_weight = None
    if policy.get("date_aware_sample_weighting", "enabled") == "enabled":
        sample_weight = date_aware_sample_weights(train_frame)
    model.fit(prep["X_train"], y_train, sample_weight=sample_weight)
    score = model.predict_proba(prep["X_validation"])[:, 1]
    coefficients = model.coef_[0].astype(float)
    l1_norm = float(np.abs(coefficients).sum())
    l2_norm = float(np.sqrt(np.square(coefficients).sum()))
    n_iter = int(np.max(getattr(model, "n_iter_", [0])))
    convergence = "converged" if n_iter < max_iter else "max_iter_reached"
    return {
        "status": "fitted",
        "model": model,
        "scores": score,
        "coefficients": coefficients,
        "intercept": float(model.intercept_[0]),
        "coefficient_l1_norm": l1_norm,
        "coefficient_l2_norm": l2_norm,
        "convergence_status": convergence,
        "preprocessor": prep,
        "training_positive_event_count": train_pos,
        "training_negative_event_count": train_neg,
        "date_aware_weighting_status": DATE_AWARE_WEIGHTING_STATUS if sample_weight is not None else "disabled",
        "date_weight_min": float(np.min(sample_weight)) if sample_weight is not None and len(sample_weight) else None,
        "date_weight_max": float(np.max(sample_weight)) if sample_weight is not None and len(sample_weight) else None,
        "date_weight_sum": float(np.sum(sample_weight)) if sample_weight is not None and len(sample_weight) else None,
    }


def _normalise_baseline_fold_metrics(path: Path | str) -> dict[tuple[str, int, str, float, str], dict[str, Any]]:
    if not Path(path).exists():
        return {}
    frame = pd.read_csv(path)
    if frame.empty:
        return {}
    out: dict[tuple[str, int, str, float, str], dict[str, Any]] = {}
    for key, group in frame.groupby(["fold_id", "horizon", "threshold_type", "threshold_value", "target_usage"], dropna=False):
        fold_id, horizon, threshold_type, threshold_value, target_usage = key
        auc_values = pd.to_numeric(group.get("roc_auc"), errors="coerce").dropna()
        ap_values = pd.to_numeric(group.get("average_precision"), errors="coerce").dropna()
        out[(str(fold_id), int(horizon), str(threshold_type), float(threshold_value), str(target_usage))] = {
            "best_wp3_baseline_auc": float(auc_values.max()) if not auc_values.empty else None,
            "best_wp3_baseline_average_precision": float(ap_values.max()) if not ap_values.empty else None,
        }
    return out


def _attach_baseline_comparison(
    row: dict[str, Any],
    baseline_lookup: Mapping[tuple[str, int, str, float, str], Mapping[str, Any]],
) -> dict[str, Any]:
    key = (
        str(row.get("fold_id")),
        int(row.get("horizon")) if row.get("horizon") is not None else 0,
        str(row.get("threshold_type")),
        float(row.get("threshold_value")) if row.get("threshold_value") is not None else 0.0,
        str(row.get("target_usage")),
    )
    baseline = baseline_lookup.get(key, {})
    best_auc = _as_float(baseline.get("best_wp3_baseline_auc"))
    best_ap = _as_float(baseline.get("best_wp3_baseline_average_precision"))
    auc = _as_float(row.get("roc_auc"))
    ap = _as_float(row.get("average_precision"))
    row["best_wp3_baseline_auc"] = best_auc
    row["best_wp3_baseline_average_precision"] = best_ap
    row["logistic_delta_auc_vs_best_baseline"] = None if auc is None or best_auc is None else float(auc - best_auc)
    row["logistic_delta_ap_vs_best_baseline"] = None if ap is None or best_ap is None else float(ap - best_ap)
    row["logistic_beats_best_baseline_flag"] = bool(
        row["logistic_delta_auc_vs_best_baseline"] is not None
        and row["logistic_delta_ap_vs_best_baseline"] is not None
        and row["logistic_delta_auc_vs_best_baseline"] > 0
        and row["logistic_delta_ap_vs_best_baseline"] > 0
    )
    return row


def _empty_metric_row(
    *,
    fold_id: str,
    asof_mode: str,
    slice_row: Mapping[str, Any],
    train_row_count: int,
    validation_row_count: int,
    positive_event_count: int,
    insufficient_data_reason: str,
) -> dict[str, Any]:
    event_rate = _safe_div(positive_event_count, validation_row_count)
    row = {
        "fold_id": fold_id,
        "asof_mode": asof_mode,
        "model_variant": MODEL_VARIANT,
        "horizon": int(slice_row.get("horizon")),
        "threshold_type": str(slice_row.get("threshold_type", "fixed")),
        "threshold_value": float(slice_row.get("threshold_value")),
        "target_usage": str(slice_row.get("target_usage", "eligible")),
        "row_count": int(validation_row_count),
        "train_row_count": int(train_row_count),
        "validation_row_count": int(validation_row_count),
        "scored_row_count": 0,
        "positive_event_count": int(positive_event_count),
        "event_base_rate": event_rate,
        "score_available_rate": 0.0 if validation_row_count else None,
        "roc_auc": None,
        "average_precision": None,
        "brier_score_uncalibrated": None,
        "log_loss_uncalibrated": None,
        "spearman_score_vs_event": None,
        "spearman_score_vs_future_mae": None,
        "spearman_score_vs_future_mdd": None,
        "quantile_lift_top_decile": None,
        "quantile_lift_top_quintile": None,
        "coefficient_l1_norm": None,
        "coefficient_l2_norm": None,
        "convergence_status": "skipped",
        "insufficient_data_reason": insufficient_data_reason,
        "best_wp3_baseline_auc": None,
        "best_wp3_baseline_average_precision": None,
        "logistic_delta_auc_vs_best_baseline": None,
        "logistic_delta_ap_vs_best_baseline": None,
        "logistic_beats_best_baseline_flag": False,
    }
    return row


def evaluate_logistic_for_folds(
    *,
    target_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    fold_plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    baseline_fold_metrics: Path | str = DEFAULT_BASELINE_FOLD_METRICS,
    audit_sample_cap: int = DEFAULT_SAMPLE_ROWS,
) -> dict[str, Any]:
    asof_modes = [str(item) for item in policy.get("diagnostic_asof_modes", ASOF_MODES)]
    feature_columns = [column for column in MODEL_FEATURE_COLUMNS if any(column in frame.columns for frame in feature_frames.values())]
    if not feature_columns:
        feature_columns = MODEL_FEATURE_COLUMNS

    namespace = validate_feature_columns(feature_columns)
    leakage_counts = dict(LEAKAGE_ZERO_COUNTS)
    leakage_counts["target_namespace_input_violation_count"] = int(namespace["target_namespace_input_violation_count"])
    leakage_counts["future_column_input_violation_count"] = int(namespace["future_column_input_violation_count"])
    training_counts = dict(TRAINING_BOUNDARY_ZERO_COUNTS)
    baseline_lookup = _normalise_baseline_fold_metrics(baseline_fold_metrics)

    fold_metric_rows: list[dict[str, Any]] = []
    slice_score_frames: list[pd.DataFrame] = []
    coefficients: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    model_manifest_entries: list[dict[str, Any]] = []
    validation_row_total = 0
    train_row_total = 0
    prospective_withheld_total = 0
    fitted_model_count = 0
    insufficient_data_count = 0
    slice_keys_seen: set[tuple[int, str, float, str]] = set()
    folds_with_validation: set[str] = set()

    for fold in fold_plan.get("folds", []):
        fold_id = str(fold.get("fold_id", "fold_unknown"))
        split = split_fold_rows(target_rows, fold)
        train_rows = split["train_rows"]
        validation_rows = split["validation_rows"]
        prospective_withheld_total += int(split["prospective_holdout_rows_withheld"])
        for key, value in split["training_boundary_violation_counts"].items():
            training_counts[key] = int(training_counts.get(key, 0)) + int(value)
        if validation_rows.empty:
            continue
        validation_row_total += int(len(validation_rows))
        folds_with_validation.add(fold_id)
        slice_keys_seen.update(_slice_key_from_row(row) for row in validation_rows.to_dict(orient="records"))
        for asof_mode in asof_modes:
            features = feature_frames.get(asof_mode, pd.DataFrame())
            train_featured = _prepare_feature_join(train_rows, features, feature_columns)
            validation_featured = _prepare_feature_join(validation_rows, features, feature_columns)
            leakage_counts["feature_asof_violation_count"] += detect_asof_violations(validation_featured, asof_mode=asof_mode)
            holdout_scores = validation_featured[
                pd.to_datetime(validation_featured["trade_date"], errors="coerce").dt.normalize().ge(pd.Timestamp(HOLDOUT_START))
            ]
            leakage_counts["prospective_holdout_score_count"] += int(len(holdout_scores))

            for slice_key, val_group in validation_featured.groupby(_slice_key_columns(), sort=False, dropna=False):
                if not isinstance(slice_key, tuple):
                    slice_key = (slice_key,)
                horizon, threshold_type, threshold_value, target_usage = slice_key
                train_group = train_featured[
                    train_featured["horizon"].astype(int).eq(int(horizon))
                    & train_featured["threshold_type"].astype(str).eq(str(threshold_type))
                    & train_featured["threshold_value"].astype(float).eq(float(threshold_value))
                    & train_featured["target_usage"].astype(str).eq(str(target_usage))
                ].copy()
                train_row_total += int(len(train_group))
                try:
                    result = fit_logistic_model(train_group, val_group.copy(), feature_columns, policy)
                except RuntimeError as exc:
                    if str(exc) == "blocked_missing_sklearn":
                        raise
                    raise
                if result["status"] != "fitted":
                    insufficient_data_count += 1
                    positive_events = int(val_group["event_label"].astype(bool).sum()) if "event_label" in val_group else 0
                    row = _empty_metric_row(
                        fold_id=fold_id,
                        asof_mode=asof_mode,
                        slice_row=val_group.iloc[0].to_dict(),
                        train_row_count=len(train_group),
                        validation_row_count=len(val_group),
                        positive_event_count=positive_events,
                        insufficient_data_reason=str(result.get("insufficient_data_reason", "insufficient_data")),
                    )
                    fold_metric_rows.append(_attach_baseline_comparison(row, baseline_lookup))
                    continue

                fitted_model_count += 1
                scored = val_group.copy().reset_index(drop=True)
                scored["score"] = result["scores"]
                scored["score_available"] = True
                scored["asof_mode"] = asof_mode
                scored["fold_id"] = fold_id
                scored["model_variant"] = MODEL_VARIANT
                row = _metric_from_scored(
                    scored,
                    fold_id=fold_id,
                    train_row_count=len(train_group),
                    coefficient_l1_norm=result["coefficient_l1_norm"],
                    coefficient_l2_norm=result["coefficient_l2_norm"],
                    convergence_status=result["convergence_status"],
                    insufficient_data_reason=None,
                )
                row["asof_mode"] = asof_mode
                fold_metric_rows.append(_attach_baseline_comparison(row, baseline_lookup))
                slice_score_frames.append(scored)
                if len(audit_rows) < audit_sample_cap:
                    take = scored.head(audit_sample_cap - len(audit_rows))
                    for audit_row in take[AUDIT_SAMPLE_COLUMNS].to_dict(orient="records"):
                        audit_rows.append(audit_row)
                for feature_name, coefficient in zip(feature_columns, result["coefficients"], strict=False):
                    coefficients.append(
                        {
                            "fold_id": fold_id,
                            "asof_mode": asof_mode,
                            "model_variant": MODEL_VARIANT,
                            "horizon": int(horizon),
                            "threshold_type": str(threshold_type),
                            "threshold_value": float(threshold_value),
                            "target_usage": str(target_usage),
                            "feature_name": feature_name,
                            "feature_family": _feature_family(feature_name),
                            "coefficient": float(coefficient),
                            "abs_coefficient": float(abs(coefficient)),
                        }
                    )
                coefficients.append(
                    {
                        "fold_id": fold_id,
                        "asof_mode": asof_mode,
                        "model_variant": MODEL_VARIANT,
                        "horizon": int(horizon),
                        "threshold_type": str(threshold_type),
                        "threshold_value": float(threshold_value),
                        "target_usage": str(target_usage),
                        "feature_name": "intercept",
                        "feature_family": "intercept",
                        "coefficient": float(result["intercept"]),
                        "abs_coefficient": float(abs(result["intercept"])),
                    }
                )
                model_manifest_entries.append(
                    {
                        "model_id": f"{MODEL_VARIANT}::{fold_id}::{asof_mode}::{_slice_id(val_group.iloc[0].to_dict())}",
                        "fold_id": fold_id,
                        "asof_mode": asof_mode,
                        "model_variant": MODEL_VARIANT,
                        "horizon": int(horizon),
                        "threshold_type": str(threshold_type),
                        "threshold_value": float(threshold_value),
                        "target_usage": str(target_usage),
                        "feature_count": int(len(feature_columns)),
                        "feature_columns": list(feature_columns),
                        "train_row_count": int(len(train_group)),
                        "validation_row_count": int(len(val_group)),
                        "training_positive_event_count": int(result["training_positive_event_count"]),
                        "training_negative_event_count": int(result["training_negative_event_count"]),
                        "date_aware_weighting_status": result.get("date_aware_weighting_status"),
                        "date_weight_min": result.get("date_weight_min"),
                        "date_weight_max": result.get("date_weight_max"),
                        "date_weight_sum": result.get("date_weight_sum"),
                        "coefficient_l1_norm": result["coefficient_l1_norm"],
                        "coefficient_l2_norm": result["coefficient_l2_norm"],
                        "convergence_status": result["convergence_status"],
                        "serialized_model_written": "no",
                        "probability_calibration": "no",
                        "readiness_assigned": "no",
                    }
                )

    slice_metric_rows: list[dict[str, Any]] = []
    if slice_score_frames:
        combined = pd.concat(slice_score_frames, ignore_index=True)
        for _, group in combined.groupby(["asof_mode", *_slice_key_columns()], sort=False, dropna=False):
            row = _metric_from_scored(
                group,
                fold_id=None,
                train_row_count=0,
                coefficient_l1_norm=None,
                coefficient_l2_norm=None,
                convergence_status="aggregate",
                insufficient_data_reason=None,
            )
            row["asof_mode"] = str(group["asof_mode"].iloc[0])
            row["best_wp3_baseline_auc"] = None
            row["best_wp3_baseline_average_precision"] = None
            row["logistic_delta_auc_vs_best_baseline"] = None
            row["logistic_delta_ap_vs_best_baseline"] = None
            row["logistic_beats_best_baseline_flag"] = False
            slice_metric_rows.append(row)

    leakage_counts["prospective_holdout_metric_count"] = 0
    leakage_counts["leakage_violation_count_total"] = int(
        sum(value for key, value in leakage_counts.items() if key != "leakage_violation_count_total")
    )
    training_counts["training_boundary_violation_count_total"] = int(
        sum(value for key, value in training_counts.items() if key != "training_boundary_violation_count_total")
    )
    return {
        "fold_metrics": fold_metric_rows,
        "slice_metrics": slice_metric_rows,
        "coefficients": coefficients,
        "feature_audit": build_feature_audit_rows(feature_columns),
        "audit_rows": audit_rows,
        "model_manifest_entries": model_manifest_entries,
        "leakage_violation_counts": leakage_counts,
        "training_boundary_violation_counts": training_counts,
        "train_row_count_total": int(train_row_total),
        "validation_row_count_evaluated": int(validation_row_total),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_rows_withheld": int(prospective_withheld_total),
        "slice_count_evaluated": int(len(slice_keys_seen)),
        "fold_count_evaluated": int(len(folds_with_validation)),
        "fitted_model_count": int(fitted_model_count),
        "insufficient_data_slice_count": int(insufficient_data_count),
        "feature_columns": list(feature_columns),
        "feature_families": sorted({_feature_family(column) for column in feature_columns}),
        "date_aware_weighting_status": DATE_AWARE_WEIGHTING_STATUS,
    }


def _best_metric(rows: Sequence[Mapping[str, Any]], metric: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if _as_float(row.get(metric)) is not None and row.get("insufficient_data_reason") in (None, "")]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: float(row[metric]))
    return {
        "fold_id": best.get("fold_id"),
        "asof_mode": best.get("asof_mode"),
        "model_variant": best.get("model_variant"),
        "metric": metric,
        "value": _as_float(best.get(metric)),
        "horizon": best.get("horizon"),
        "threshold_type": best.get("threshold_type"),
        "threshold_value": best.get("threshold_value"),
        "target_usage": best.get("target_usage"),
    }


def _metric_summary(fold_rows: Sequence[Mapping[str, Any]], slice_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    def values(metric: str, *, primary_only: bool = False) -> list[float]:
        source = [row for row in slice_rows if not primary_only or row.get("asof_mode") == PRIMARY_ASOF_MODE]
        return [float(row[metric]) for row in source if _as_float(row.get(metric)) is not None]

    aucs = values("roc_auc")
    aps = values("average_precision")
    primary_aucs = values("roc_auc", primary_only=True)
    primary_aps = values("average_precision", primary_only=True)
    return {
        "fold_metric_row_count": int(len(fold_rows)),
        "slice_metric_row_count": int(len(slice_rows)),
        "mean_roc_auc": float(np.mean(aucs)) if aucs else None,
        "max_roc_auc": float(np.max(aucs)) if aucs else None,
        "mean_average_precision": float(np.mean(aps)) if aps else None,
        "max_average_precision": float(np.max(aps)) if aps else None,
        "primary_asof_mean_roc_auc": float(np.mean(primary_aucs)) if primary_aucs else None,
        "primary_asof_max_roc_auc": float(np.max(primary_aucs)) if primary_aucs else None,
        "primary_asof_mean_average_precision": float(np.mean(primary_aps)) if primary_aps else None,
        "primary_asof_max_average_precision": float(np.max(primary_aps)) if primary_aps else None,
        "score_type": "raw_uncalibrated_logistic_score",
    }


def _baseline_comparison_summary(fold_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    comparable_auc = [
        row for row in fold_rows if _as_float(row.get("logistic_delta_auc_vs_best_baseline")) is not None
    ]
    comparable_ap = [
        row for row in fold_rows if _as_float(row.get("logistic_delta_ap_vs_best_baseline")) is not None
    ]
    beating = [row for row in fold_rows if bool(row.get("logistic_beats_best_baseline_flag"))]
    return {
        "comparable_auc_row_count": int(len(comparable_auc)),
        "comparable_average_precision_row_count": int(len(comparable_ap)),
        "best_logistic_delta_auc_vs_best_baseline": max(
            (float(row["logistic_delta_auc_vs_best_baseline"]) for row in comparable_auc),
            default=None,
        ),
        "best_logistic_delta_ap_vs_best_baseline": max(
            (float(row["logistic_delta_ap_vs_best_baseline"]) for row in comparable_ap),
            default=None,
        ),
        "logistic_beats_best_baseline_row_count": int(len(beating)),
        "outperformance_required_for_wp4_pass": "no",
    }


def _blocked_report(
    *,
    status: str,
    db_path: Path | str | None,
    reasons: Sequence[str],
    wp1_status: str | None = None,
    wp2_status: str | None = None,
    wp2_1_status: str | None = None,
    wp3_status: str | None = None,
    wp3_5_status: str | None = None,
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "wp1_support_status": wp1_status,
        "wp2_controls_status": wp2_status,
        "wp2_1_full_target_audit_status": wp2_1_status,
        "wp3_baseline_diagnostics_status": wp3_status,
        "wp3_5_vol_scaled_sanity_status": wp3_5_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "fold_plan_status": "blocked",
        "policy_status": "blocked",
        "model_family": MODEL_FAMILY,
        "model_variant_count": 0,
        "asof_modes_evaluated": [],
        "primary_asof_mode": PRIMARY_ASOF_MODE,
        "slice_count_evaluated": 0,
        "fold_count_evaluated": 0,
        "train_row_count_total": 0,
        "validation_row_count_evaluated": 0,
        "prospective_holdout_rows_evaluated": 0,
        "insufficient_data_slice_count": 0,
        "fitted_model_count": 0,
        "feature_count": len(MODEL_FEATURE_COLUMNS),
        "feature_families": ALLOWED_FEATURE_FAMILIES,
        "feature_audit_path": None,
        "fold_metrics_path": None,
        "slice_metrics_path": None,
        "coefficients_path": None,
        "model_manifest_path": None,
        "audit_sample_path": None,
        "metric_summary": {},
        "best_logistic_model_by_auc": None,
        "best_logistic_model_by_average_precision": None,
        "baseline_comparison_summary": {},
        "vol_scaled_candidate_tracking_status": "blocked",
        "wp3_5_wp4_entry_recommendation": None,
        "vol_scaled_candidate_count": 0,
        "best_vol_scaled_candidate_by_event_support": None,
        "fixed_threshold_mainline_status": "blocked",
        "leakage_violation_counts": dict(LEAKAGE_ZERO_COUNTS),
        "training_boundary_violation_counts": dict(TRAINING_BOUNDARY_ZERO_COUNTS),
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": list(reasons),
        "remaining_risks": [],
    }


def _write_blocked_outputs(
    *,
    report: Mapping[str, Any],
    output: Path,
    summary_json: Path,
    fold_metrics: Path,
    slice_metrics: Path,
    coefficients: Path,
    model_manifest: Path,
    feature_audit: Path,
    audit_sample: Path,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(fold_metrics, [], FOLD_METRIC_COLUMNS)
    _write_csv(slice_metrics, [], SLICE_METRIC_COLUMNS)
    _write_csv(coefficients, [], COEFFICIENT_COLUMNS)
    _write_csv(feature_audit, build_feature_audit_rows(MODEL_FEATURE_COLUMNS), FEATURE_AUDIT_COLUMNS)
    _write_csv(audit_sample, [], AUDIT_SAMPLE_COLUMNS)
    _write_json(
        model_manifest,
        {
            "index_id": INDEX_ID,
            "report_version": REPORT_VERSION,
            "status": report.get("status"),
            "model_family": MODEL_FAMILY,
            "serialized_model_written": "no",
            "models": [],
        },
    )


def build_logistic_hazard_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    baseline_diagnostics: Path | str = DEFAULT_BASELINE_DIAGNOSTICS,
    vol_scaled_sanity: Path | str = DEFAULT_VOL_SCALED_SANITY,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    policy: Path | str = DEFAULT_POLICY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    fold_metrics: Path | str = DEFAULT_FOLD_METRICS,
    slice_metrics: Path | str = DEFAULT_SLICE_METRICS,
    coefficients: Path | str = DEFAULT_COEFFICIENTS,
    model_manifest: Path | str = DEFAULT_MODEL_MANIFEST,
    feature_audit: Path | str = DEFAULT_FEATURE_AUDIT,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    baseline_fold_metrics: Path | str = DEFAULT_BASELINE_FOLD_METRICS,
    asof_modes: Sequence[str] | None = None,
    audit_sample_cap: int = DEFAULT_SAMPLE_ROWS,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP4 logistic hazard is no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    fold_path = Path(fold_metrics)
    slice_path = Path(slice_metrics)
    coefficients_path = Path(coefficients)
    manifest_path = Path(model_manifest)
    feature_audit_path = Path(feature_audit)
    audit_path = Path(audit_sample)

    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
        full_audit = _load_json(full_target_audit)
        baseline_report = _load_json(baseline_diagnostics)
        vol_report = _load_json(vol_scaled_sanity)
        fold_doc = _load_json(fold_plan)
    except FileNotFoundError as exc:
        report = _blocked_report(
            status="blocked_missing_input",
            db_path=resolved_db,
            reasons=[f"missing input: {exc.filename}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["sw2021_l2_universe_coverage"] = v7.coverage.get("sw2021_l2_universe_coverage", "missing")
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    try:
        policy_doc = _load_machine_config(policy)
    except FileNotFoundError:
        report = _blocked_report(
            status="blocked_missing_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=[f"missing policy: {policy}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report
    policy_issues = validate_policy(policy_doc)
    if policy_issues:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=policy_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    selected_asof_modes = list(asof_modes or policy_doc.get("diagnostic_asof_modes", ASOF_MODES))
    if selected_asof_modes != ASOF_MODES:
        policy_doc = dict(policy_doc)
        policy_doc["diagnostic_asof_modes"] = selected_asof_modes

    precondition_status, precondition_issues = validate_wp4_preconditions(
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        baseline_diagnostics=baseline_report,
        vol_scaled_sanity=vol_report,
        fold_plan=fold_doc,
        db_path=resolved_db,
    )
    if precondition_status != "pass":
        report = _blocked_report(
            status=precondition_status,
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=precondition_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    try:
        target_universe_doc = _load_machine_config(target_universe)
    except FileNotFoundError:
        target_universe_doc = {}
    target_universe_status = "pass" if target_universe_doc.get("source", {}).get("v7_coverage_available") == "yes" else "partial"
    specs = slice_specs_from_target_support(support)
    universe_ids = v7.universe_frame["entity_id"].astype(str).tolist()
    ohlcv, range_report = read_ohlcv_inputs(resolved_db, universe_ids)
    if ohlcv.empty:
        close_only = v7.price_frame.rename(columns={"sector_id": "entity_id"}).copy()
        close_only["open"] = np.nan
        close_only["high"] = np.nan
        close_only["low"] = np.nan
        ohlcv = close_only[["entity_id", "trade_date", "open", "high", "low", "close"]]
    price_features, feature_range_report = build_price_baseline_features(ohlcv)
    range_report = {**range_report, **feature_range_report}
    feature_frames = {mode: shifted_price_features(price_features, asof_mode=mode) for mode in selected_asof_modes}

    max_validation_end: pd.Timestamp | None = None
    for fold in fold_doc.get("folds", []):
        end = _normalise_date(fold.get("validation_end_date"))
        if end is not None and (max_validation_end is None or end > max_validation_end):
            max_validation_end = end
    if max_validation_end is None:
        report = _blocked_report(
            status="blocked_invalid_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=["fold plan has no valid validation_end_date"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    available_price_dates = set(pd.to_datetime(v7.price_frame["trade_date"], errors="coerce").dt.normalize().dropna().tolist())
    needed_dates = sorted(date for date in available_price_dates if date <= max_validation_end)
    target_rows = build_target_rows_for_trade_dates(
        v7.price_frame,
        v7.universe_frame,
        specs,
        needed_dates,
        source_db_path=resolved_db,
    )

    try:
        evaluation = evaluate_logistic_for_folds(
            target_rows=target_rows,
            feature_frames=feature_frames,
            fold_plan=fold_doc,
            policy=policy_doc,
            baseline_fold_metrics=baseline_fold_metrics,
            audit_sample_cap=int(policy_doc.get("audit_sample_cap", audit_sample_cap)),
        )
    except RuntimeError as exc:
        if str(exc) != "blocked_missing_sklearn":
            raise
        report = _blocked_report(
            status="blocked_missing_sklearn",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_report.get("status", "unknown")),
            wp3_5_status=str(vol_report.get("status", "unknown")),
            reasons=["scikit-learn is unavailable"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            coefficients=coefficients_path,
            model_manifest=manifest_path,
            feature_audit=feature_audit_path,
            audit_sample=audit_path,
        )
        return report

    _write_csv(fold_path, evaluation["fold_metrics"], FOLD_METRIC_COLUMNS)
    _write_csv(slice_path, evaluation["slice_metrics"], SLICE_METRIC_COLUMNS)
    _write_csv(coefficients_path, evaluation["coefficients"], COEFFICIENT_COLUMNS)
    _write_csv(feature_audit_path, evaluation["feature_audit"], FEATURE_AUDIT_COLUMNS)
    _write_csv(audit_path, evaluation["audit_rows"], AUDIT_SAMPLE_COLUMNS)
    manifest = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "status": "pass" if evaluation["fitted_model_count"] > 0 else "partial",
        "source_db_path": _safe_path(resolved_db),
        "model_family": MODEL_FAMILY,
        "model_variant": MODEL_VARIANT,
        "serialized_model_written": "no",
        "date_aware_weighting_status": evaluation["date_aware_weighting_status"],
        "probability_calibration": "no",
        "readiness_assigned": "no",
        "model_count": int(len(evaluation["model_manifest_entries"])),
        "models": evaluation["model_manifest_entries"],
        "created_at": _now_iso(),
    }
    _write_json(manifest_path, manifest)

    leakage_counts = evaluation["leakage_violation_counts"]
    training_counts = evaluation["training_boundary_violation_counts"]
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "unknown",
        "wp1_support_status": support.get("status"),
        "wp2_controls_status": controls.get("status"),
        "wp2_1_full_target_audit_status": full_audit.get("status"),
        "wp3_baseline_diagnostics_status": baseline_report.get("status"),
        "wp3_5_vol_scaled_sanity_status": vol_report.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": target_universe_status,
        "fold_plan_status": fold_doc.get("status"),
        "policy_status": "pass",
        "model_family": MODEL_FAMILY,
        "model_variant_count": 1,
        "date_aware_weighting_status": evaluation["date_aware_weighting_status"],
        "asof_modes_evaluated": selected_asof_modes,
        "primary_asof_mode": PRIMARY_ASOF_MODE,
        "slice_count_evaluated": evaluation["slice_count_evaluated"],
        "fold_count_evaluated": evaluation["fold_count_evaluated"],
        "train_row_count_total": evaluation["train_row_count_total"],
        "validation_row_count_evaluated": evaluation["validation_row_count_evaluated"],
        "prospective_holdout_rows_evaluated": evaluation["prospective_holdout_rows_evaluated"],
        "prospective_holdout_rows_withheld": evaluation["prospective_holdout_rows_withheld"],
        "insufficient_data_slice_count": evaluation["insufficient_data_slice_count"],
        "fitted_model_count": evaluation["fitted_model_count"],
        "feature_count": int(len(evaluation["feature_columns"])),
        "feature_families": evaluation["feature_families"],
        "range_based_availability_status": range_report.get("range_based_availability_status"),
        "feature_audit_path": _safe_path(feature_audit_path),
        "fold_metrics_path": _safe_path(fold_path),
        "slice_metrics_path": _safe_path(slice_path),
        "coefficients_path": _safe_path(coefficients_path),
        "model_manifest_path": _safe_path(manifest_path),
        "audit_sample_path": _safe_path(audit_path),
        "metric_summary": _metric_summary(evaluation["fold_metrics"], evaluation["slice_metrics"]),
        "best_logistic_model_by_auc": _best_metric(evaluation["fold_metrics"], "roc_auc"),
        "best_logistic_model_by_average_precision": _best_metric(evaluation["fold_metrics"], "average_precision"),
        "baseline_comparison_summary": _baseline_comparison_summary(evaluation["fold_metrics"]),
        "vol_scaled_candidate_tracking_status": "tracked_reference_only",
        "wp3_5_wp4_entry_recommendation": vol_report.get("wp4_entry_recommendation"),
        "vol_scaled_candidate_count": _as_int(vol_report.get("vol_scaled_candidate_count"), default=0),
        "best_vol_scaled_candidate_by_event_support": vol_report.get("best_vol_scaled_candidate_by_event_support"),
        "fixed_threshold_mainline_status": "unchanged_primary_target",
        "leakage_violation_counts": leakage_counts,
        "training_boundary_violation_counts": training_counts,
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": [],
        "remaining_risks": [
            "WP4 scores are raw uncalibrated logistic outputs; probability calibration and readiness remain explicitly deferred.",
            "Outperformance versus WP3 baselines is diagnostic only and is not required for WP4 acceptance.",
            "Volatility-scaled candidates remain tracked reference metadata only and do not replace fixed-threshold labels.",
        ],
    }
    violation_total = int(leakage_counts.get("leakage_violation_count_total", 0))
    training_total = int(training_counts.get("training_boundary_violation_count_total", 0))
    if violation_total == 0 and training_total == 0 and int(evaluation["fitted_model_count"]) > 0:
        report["status"] = "pass"
    elif int(evaluation["fitted_model_count"]) == 0:
        report["status"] = "partial_insufficient_data"
        report["blocking_reasons"] = ["no logistic models fitted with configured class-support thresholds"]
    else:
        report["status"] = "fail"
        report["blocking_reasons"] = ["leakage_or_training_boundary_violation_detected"]
    report["ci_gate_status"] = "pass" if report["status"] == "pass" else report["status"]
    _write_markdown(output_path, report)
    _write_json(summary_path, report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--target-universe", type=Path, default=DEFAULT_TARGET_UNIVERSE)
    parser.add_argument("--target-controls", type=Path, default=DEFAULT_TARGET_CONTROLS)
    parser.add_argument("--full-target-audit", type=Path, default=DEFAULT_FULL_TARGET_AUDIT)
    parser.add_argument("--baseline-diagnostics", type=Path, default=DEFAULT_BASELINE_DIAGNOSTICS)
    parser.add_argument("--vol-scaled-sanity", type=Path, default=DEFAULT_VOL_SCALED_SANITY)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--fold-metrics", type=Path, default=DEFAULT_FOLD_METRICS)
    parser.add_argument("--slice-metrics", type=Path, default=DEFAULT_SLICE_METRICS)
    parser.add_argument("--coefficients", type=Path, default=DEFAULT_COEFFICIENTS)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--feature-audit", type=Path, default=DEFAULT_FEATURE_AUDIT)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--baseline-fold-metrics", type=Path, default=DEFAULT_BASELINE_FOLD_METRICS)
    parser.add_argument("--asof-modes", type=str, default=",".join(ASOF_MODES))
    parser.add_argument("--audit-sample-cap", type=int, default=DEFAULT_SAMPLE_ROWS)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    asof_modes = [item.strip() for item in str(args.asof_modes).split(",") if item.strip()]
    report = build_logistic_hazard_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        baseline_diagnostics=args.baseline_diagnostics,
        vol_scaled_sanity=args.vol_scaled_sanity,
        fold_plan=args.fold_plan,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        fold_metrics=args.fold_metrics,
        slice_metrics=args.slice_metrics,
        coefficients=args.coefficients,
        model_manifest=args.model_manifest,
        feature_audit=args.feature_audit,
        audit_sample=args.audit_sample,
        baseline_fold_metrics=args.baseline_fold_metrics,
        asof_modes=asof_modes,
        audit_sample_cap=args.audit_sample_cap,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_LOGISTIC_HAZARD="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"fitted_models={report.get('fitted_model_count')} "
        f"validation_rows={report.get('validation_row_count_evaluated')} "
        f"primary_asof={report.get('primary_asof_mode')} "
        f"leakage_violations={report.get('leakage_violation_counts', {}).get('leakage_violation_count_total')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
