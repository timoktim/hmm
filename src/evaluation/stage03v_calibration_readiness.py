"""Stage03V WP5 calibration, clustered inference, and readiness matrix.

WP5 fits development-only calibration candidates on historical-development
calibration partitions and evaluates them on separate evaluation partitions.
It does not consume the prospective holdout, write DuckDB tables, serialize
calibration models, or emit trading/decision outputs.
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
    build_price_baseline_features,
    build_target_rows_for_trade_dates,
    read_ohlcv_inputs,
    slice_specs_from_target_support,
)
from src.evaluation.stage03v_fold_plan_magnitude import magnitude_markdown_section
from src.evaluation.stage03v_logistic_hazard import (
    ASOF_MODES,
    MODEL_FEATURE_COLUMNS,
    MODEL_VARIANT,
    PRIMARY_ASOF_MODE,
    PRIMARY_TARGET_FAMILY,
    _prepare_feature_join,
    fit_logistic_model,
    split_fold_rows,
)
from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)
from src.evaluation.stage03v_vol_scaled_threshold_sanity import shifted_price_features


INDEX_ID = "STAGE03V-WP5-v1"
REPORT_VERSION = "stage03v_calibration_readiness_v1"
POLICY_VERSION = "stage03v_calibration_readiness_policy_v1"
STAGE_ID = "stage03v"
DEFAULT_SAMPLE_ROWS = 500
PRIMARY_MARKET_EVENT_SHARE = 0.20
MIN_MARKET_EVENT_BLOCKS_FOR_USABLE_PROBABILITY = 2
CALIBRATION_METHODS = [
    "identity_uncalibrated_reference",
    "platt_logistic_calibration",
    "isotonic_calibration",
]
PRIMARY_CALIBRATION_METHOD = "platt_logistic_calibration"
SUPERSEDES_MICROFOLD_RUN = "stage03v_wp4_v1_2014_microfold"
SUPERSESSION_REASON = "invalidated_due_to_fold_coverage"
READINESS_CATEGORIES = [
    "usable_probability_candidate",
    "ordinal_only_candidate",
    "baseline_only_candidate",
    "research_only",
    "insufficient_data",
    "blocked_by_leakage",
]

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_BASELINE_DIAGNOSTICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_VOL_SCALED_SANITY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_LOGISTIC_HAZARD = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_LOGISTIC_FOLD_METRICS = ROOT / "reports" / "stage03v" / "logistic_hazard_fold_metrics.csv"
DEFAULT_LOGISTIC_SLICE_METRICS = ROOT / "reports" / "stage03v" / "logistic_hazard_slice_metrics.csv"
DEFAULT_LOGISTIC_MODEL_MANIFEST = ROOT / "reports" / "stage03v" / "logistic_hazard_model_manifest.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_calibration_readiness_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "calibration_readiness_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "calibration_readiness_report.json"
DEFAULT_FOLD_METRICS = ROOT / "reports" / "stage03v" / "calibration_fold_metrics.csv"
DEFAULT_SLICE_METRICS = ROOT / "reports" / "stage03v" / "calibration_slice_metrics.csv"
DEFAULT_CALIBRATION_BINS = ROOT / "reports" / "stage03v" / "calibration_curve_bins.csv"
DEFAULT_CLUSTERED_INFERENCE = ROOT / "reports" / "stage03v" / "clustered_inference_summary.csv"
DEFAULT_READINESS_MATRIX = ROOT / "reports" / "stage03v" / "downside_readiness_matrix.csv"
DEFAULT_MODEL_MANIFEST = ROOT / "reports" / "stage03v" / "calibration_model_manifest.json"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "calibration_audit_sample.csv"

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "full_feature_matrix_committed": "no",
    "full_score_matrix_committed": "no",
    "calibration_model_serialized": "no",
    "model_training": "no_new_non_logistic_model",
    "probability_calibration": "yes",
    "readiness_assigned": "yes_development_only",
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
    "evaluation_label_leakage_count": 0,
    "prospective_holdout_score_count": 0,
    "prospective_holdout_metric_count": 0,
    "fixed_threshold_mainline_mutation_count": 0,
    "persistent_db_write_count": 0,
    "external_fetch_count": 0,
    "leakage_violation_count_total": 0,
}

CALIBRATION_BOUNDARY_ZERO_COUNTS = {
    "calibration_rows_on_or_after_evaluation_start_count": 0,
    "evaluation_rows_used_for_calibrator_fit_count": 0,
    "holdout_rows_used_for_calibration_count": 0,
    "holdout_rows_used_for_evaluation_count": 0,
    "serialized_calibration_model_count": 0,
    "new_non_logistic_model_family_count": 0,
    "trading_or_decision_output_count": 0,
    "calibration_boundary_violation_count_total": 0,
}

FOLD_METRIC_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "calibration_protocol",
    "calibration_row_count",
    "evaluation_row_count",
    "scored_row_count",
    "positive_event_count",
    "negative_event_count",
    "event_base_rate",
    "brier_score",
    "brier_identity_uncalibrated",
    "brier_calibrated",
    "brier_retention",
    "log_loss",
    "expected_calibration_error",
    "max_calibration_error",
    "reliability_slope",
    "reliability_intercept",
    "roc_auc",
    "average_precision",
    "auc_retention_vs_identity",
    "ap_retention_vs_identity",
    "validation_market_event_block_count",
    "monotonic_bin_status",
    "calibration_fit_status",
    "skip_reason",
]
SLICE_METRIC_COLUMNS = [
    column for column in FOLD_METRIC_COLUMNS if column not in {"fold_id", "calibration_protocol"}
] + ["fold_count"]
CALIBRATION_BIN_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "bin_index",
    "bin_low",
    "bin_high",
    "row_count",
    "positive_event_count",
    "mean_score",
    "observed_event_rate",
    "calibration_gap",
]
CLUSTERED_INFERENCE_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "cluster_type",
    "metric_name",
    "cluster_count",
    "min_cluster_size",
    "max_cluster_size",
    "clustered_metric_mean",
    "clustered_metric_std",
    "bootstrap_or_cluster_se_rows",
    "confidence_interval_low",
    "confidence_interval_high",
    "uncertainty_status",
]
READINESS_COLUMNS = [
    "asof_mode",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "readiness_category",
    "development_only",
    "evaluation_row_count",
    "positive_event_count",
    "negative_event_count",
    "mean_brier_score",
    "mean_brier_retention",
    "validation_market_event_block_count",
    "mean_log_loss",
    "mean_expected_calibration_error",
    "max_expected_calibration_error",
    "mean_auc",
    "mean_average_precision",
    "clustered_uncertainty_width",
    "fold_count",
    "readiness_reason",
]
AUDIT_SAMPLE_COLUMNS = [
    "fold_id",
    "asof_mode",
    "model_variant",
    "entity_id",
    "trade_date",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "calibration_protocol",
    "row_role",
    "raw_score",
    "calibrated_score",
    "event_label",
    "future_mae",
    "future_mdd",
    "future_return",
]


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
        *magnitude_markdown_section(report),
        "",
        "# Stage03V WP5 Calibration Readiness",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- wp4_logistic_hazard_status: {report.get('wp4_logistic_hazard_status')}",
        f"- calibration_methods_evaluated: {', '.join(report.get('calibration_methods_evaluated', []))}",
        f"- primary_calibration_method: {report.get('primary_calibration_method')}",
        f"- evaluation_row_count_total: {report.get('evaluation_row_count_total')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- calibration_model_count: {report.get('calibration_model_count')}",
        f"- skipped_calibration_count: {report.get('skipped_calibration_count')}",
        f"- usable_probability_candidate_count: {report.get('usable_probability_candidate_count')}",
        f"- ordinal_only_candidate_count: {report.get('ordinal_only_candidate_count')}",
        f"- baseline_only_candidate_count: {report.get('baseline_only_candidate_count')}",
        f"- research_only_count: {report.get('research_only_count')}",
        f"- insufficient_data_count: {report.get('insufficient_data_count')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Leakage Counts",
        "",
    ]
    for key, value in report.get("leakage_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Calibration Boundary Counts", ""])
    for key, value in report.get("calibration_boundary_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Readiness Category Counts", ""])
    for key, value in report.get("readiness_category_counts", {}).items():
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


def _slice_id(row: Mapping[str, Any]) -> str:
    return (
        f"h{int(row.get('horizon'))}:"
        f"{row.get('threshold_type', 'fixed')}:"
        f"{float(row.get('threshold_value')):.4f}:"
        f"{row.get('target_usage', 'unknown')}"
    )


def _logistic_policy() -> dict[str, Any]:
    return {
        "min_train_positive_events": 2,
        "min_train_negative_events": 2,
        "solver": "lbfgs",
        "penalty": "l2",
        "max_iter": 1000,
        "random_state": 20260611,
        "class_weight": "balanced",
    }


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "source_logistic_hazard": "reports/stage03v/logistic_hazard_report.json",
        "source_vol_scaled_sanity": "reports/stage03v/vol_scaled_threshold_sanity_report.json",
        "fold_plan": "reports/stage03v/purge_embargo_fold_plan.json",
        "primary_target_family": PRIMARY_TARGET_FAMILY,
        "vol_scaled_candidate_policy": "tracked_reference_only",
        "primary_asof_mode": PRIMARY_ASOF_MODE,
        "asof_modes": ASOF_MODES,
        "calibration_methods": CALIBRATION_METHODS,
        "primary_calibration_method": PRIMARY_CALIBRATION_METHOD,
        "calibration_protocol": "deterministic_time_ordered_calibration_then_evaluation",
        "validation_calibration_fraction": 0.5,
        "min_calibration_positive_events": 2,
        "min_calibration_negative_events": 2,
        "min_evaluation_rows_for_candidate": 100,
        "min_evaluation_positive_events_for_candidate": 3,
        "usable_probability_min_evaluation_rows": 500,
        "usable_probability_min_positive_events": 10,
        "usable_probability_max_ece": 0.05,
        "usable_probability_max_cluster_width": 0.25,
        "primary_market_event_share": PRIMARY_MARKET_EVENT_SHARE,
        "usable_probability_min_market_event_blocks": MIN_MARKET_EVENT_BLOCKS_FOR_USABLE_PROBABILITY,
        "brier_retention_policy": "forbid_usable_probability_when_negative_vs_identity",
        "ordinal_min_evaluation_rows": 100,
        "ordinal_min_positive_events": 3,
        "ordinal_min_auc": 0.55,
        "final_holdout_policy": "withheld_not_scored",
        "readiness_scope": "development_only_not_trading",
        "readiness_categories": READINESS_CATEGORIES,
        "external_fetch_policy": "forbidden",
        "persistent_db_table_policy": "forbidden_by_default",
        "full_score_matrix_policy": "forbidden_to_commit",
        "calibration_model_serialization_policy": "forbidden",
        "cluster_random_seed": 20260611,
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
    if list(policy.get("calibration_methods", [])) != CALIBRATION_METHODS:
        issues.append("calibration_methods_mismatch")
    if policy.get("final_holdout_policy") != "withheld_not_scored":
        issues.append("final_holdout_policy_not_withheld")
    if policy.get("readiness_scope") != "development_only_not_trading":
        issues.append("readiness_scope_not_development_only")
    if float(policy.get("primary_market_event_share", -1.0)) != PRIMARY_MARKET_EVENT_SHARE:
        issues.append("primary_market_event_share_mismatch")
    if int(policy.get("usable_probability_min_market_event_blocks", 0)) != MIN_MARKET_EVENT_BLOCKS_FOR_USABLE_PROBABILITY:
        issues.append("usable_probability_min_market_event_blocks_mismatch")
    if policy.get("brier_retention_policy") != "forbid_usable_probability_when_negative_vs_identity":
        issues.append("brier_retention_policy_mismatch")
    if set(policy.get("readiness_categories", [])) != set(READINESS_CATEGORIES):
        issues.append("readiness_categories_mismatch")
    if policy.get("external_fetch_policy") != "forbidden":
        issues.append("external_fetch_policy_not_forbidden")
    if policy.get("persistent_db_table_policy") != "forbidden_by_default":
        issues.append("persistent_db_table_policy_not_forbidden")
    if policy.get("full_score_matrix_policy") != "forbidden_to_commit":
        issues.append("full_score_matrix_policy_not_forbidden")
    if policy.get("calibration_model_serialization_policy") != "forbidden":
        issues.append("calibration_model_serialization_policy_not_forbidden")
    return issues


def validate_wp5_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    full_target_audit: Mapping[str, Any],
    baseline_diagnostics: Mapping[str, Any],
    vol_scaled_sanity: Mapping[str, Any],
    logistic_hazard: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    db_path: Path | str,
) -> tuple[str, list[str]]:
    issues: list[str] = []
    docs = [
        ("wp1", target_support),
        ("wp2", target_controls),
        ("wp2_1", full_target_audit),
        ("wp3", baseline_diagnostics),
        ("wp3_5", vol_scaled_sanity),
        ("wp4", logistic_hazard),
    ]
    holdout_issues: list[str] = []
    for label, doc in docs:
        if doc.get("status") != "pass":
            issues.append(f"{label}_status_not_pass")
        if doc.get("v7_coverage_available") != "yes":
            issues.append(f"{label}_v7_coverage_not_yes")
        if doc.get("sw2021_l2_universe_coverage") != "pass":
            issues.append(f"{label}_sw2021_l2_universe_not_pass")
        holdout_issues.extend(holdout_consumption_issues(label, doc))
    if fold_plan.get("status") != "pass":
        issues.append("fold_plan_status_not_pass")
    if _as_int(fold_plan.get("fold_count"), default=0) <= 0:
        issues.append("fold_plan_has_no_folds")
    if _as_int(fold_plan.get("purge_violation_count"), default=-1) != 0:
        issues.append("fold_plan_purge_violation_count_not_zero")
    if _as_int(fold_plan.get("embargo_violation_count"), default=-1) != 0:
        issues.append("fold_plan_embargo_violation_count_not_zero")

    wp4_flags = logistic_hazard.get("boundary_flags", {})
    if wp4_flags.get("model_training") != "yes":
        issues.append("wp4_model_training_not_yes")
    if wp4_flags.get("probability_calibration") != "no":
        issues.append("wp4_probability_calibration_not_no")
    if wp4_flags.get("readiness_assigned") != "no":
        issues.append("wp4_readiness_assigned_not_no")
    if wp4_flags.get("holdout_consumed") != "no":
        issues.append("wp4_holdout_consumed_not_no")
    if _as_int(logistic_hazard.get("leakage_violation_counts", {}).get("leakage_violation_count_total"), -1) != 0:
        issues.append("wp4_leakage_violation_count_not_zero")
    if (
        _as_int(
            logistic_hazard.get("training_boundary_violation_counts", {}).get(
                "training_boundary_violation_count_total"
            ),
            -1,
        )
        != 0
    ):
        issues.append("wp4_training_boundary_violation_count_not_zero")
    if _as_int(logistic_hazard.get("prospective_holdout_rows_evaluated"), -1) != 0:
        issues.append("wp4_prospective_holdout_rows_evaluated_not_zero")
    if logistic_hazard.get("fixed_threshold_mainline_status") != "unchanged_primary_target":
        issues.append("wp4_fixed_threshold_mainline_not_unchanged")

    expected_paths = {str(doc.get("source_db_path")) for _, doc in docs if doc.get("source_db_path")}
    resolved_safe = _safe_path(db_path)
    if not os.environ.get("STAGE03V_V7_DB") and expected_paths and resolved_safe not in expected_paths:
        issues.append("resolved_db_path_does_not_match_accepted_stage03v_artifacts")
    if holdout_issues:
        issues.extend(issue for issue in holdout_issues if issue not in issues)
        return "blocked_holdout_consumed", issues
    return ("pass", []) if not issues else ("blocked_wp4_not_ready", issues)


def split_calibration_evaluation_rows(
    rows: pd.DataFrame,
    *,
    calibration_fraction: float = 0.5,
) -> dict[str, Any]:
    if rows.empty:
        return {
            "calibration_rows": rows.copy(),
            "evaluation_rows": rows.copy(),
            "protocol": "empty_rows",
            "evaluation_start_date": None,
        }
    work = rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    dates = sorted(pd.to_datetime(work["trade_date"], errors="coerce").dropna().unique())
    if len(dates) < 2:
        return {
            "calibration_rows": work.iloc[0:0].copy(),
            "evaluation_rows": work.copy(),
            "protocol": "insufficient_validation_dates_for_time_split",
            "evaluation_start_date": pd.Timestamp(dates[0]).normalize() if dates else None,
        }
    cut = max(1, min(len(dates) - 1, int(math.floor(len(dates) * float(calibration_fraction)))))
    calibration_dates = set(pd.Timestamp(value).normalize() for value in dates[:cut])
    evaluation_dates = set(pd.Timestamp(value).normalize() for value in dates[cut:])
    calibration = work[work["trade_date"].isin(calibration_dates)].copy()
    evaluation = work[work["trade_date"].isin(evaluation_dates)].copy()
    evaluation_start = min(evaluation_dates) if evaluation_dates else None
    return {
        "calibration_rows": calibration,
        "evaluation_rows": evaluation,
        "protocol": "validation_time_ordered_calibration_then_evaluation",
        "evaluation_start_date": evaluation_start,
    }


def detect_calibration_boundary_violations(calibration_rows: pd.DataFrame, evaluation_rows: pd.DataFrame) -> dict[str, int]:
    counts = dict(CALIBRATION_BOUNDARY_ZERO_COUNTS)
    if not calibration_rows.empty and not evaluation_rows.empty:
        eval_start = pd.to_datetime(evaluation_rows["trade_date"], errors="coerce").dt.normalize().min()
        calib_dates = pd.to_datetime(calibration_rows["trade_date"], errors="coerce").dt.normalize()
        counts["calibration_rows_on_or_after_evaluation_start_count"] = int(calib_dates.ge(eval_start).sum())
    holdout = pd.Timestamp(HOLDOUT_START).normalize()
    if not calibration_rows.empty:
        calib_dates = pd.to_datetime(calibration_rows["trade_date"], errors="coerce").dt.normalize()
        counts["holdout_rows_used_for_calibration_count"] = int(calib_dates.ge(holdout).sum())
    if not evaluation_rows.empty:
        eval_dates = pd.to_datetime(evaluation_rows["trade_date"], errors="coerce").dt.normalize()
        counts["holdout_rows_used_for_evaluation_count"] = int(eval_dates.ge(holdout).sum())
    counts["calibration_boundary_violation_count_total"] = int(
        sum(value for key, value in counts.items() if key != "calibration_boundary_violation_count_total")
    )
    return counts


def _merge_market_event_dates(active_dates: Sequence[pd.Timestamp], all_dates: Sequence[pd.Timestamp], *, horizon: int) -> int:
    active = sorted({pd.Timestamp(value).normalize() for value in active_dates if pd.notna(value)})
    if not active:
        return 0
    ordered = sorted({pd.Timestamp(value).normalize() for value in all_dates if pd.notna(value)})
    if not ordered:
        return 0
    position = {value: idx for idx, value in enumerate(ordered)}
    blocks = 1
    previous = active[0]
    for current in active[1:]:
        inactive_gap = position.get(current, position.get(previous, 0) + 1) - position.get(previous, 0) - 1
        if inactive_gap > int(horizon):
            blocks += 1
        previous = current
    return blocks


def validation_market_event_block_count(rows: pd.DataFrame, *, event_share_threshold: float = PRIMARY_MARKET_EVENT_SHARE) -> int:
    if rows.empty or not {"trade_date", "entity_id", "event_label"}.issubset(rows.columns):
        return 0
    work = rows[rows["event_label"].notna()].copy()
    if work.empty:
        return 0
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work = work[work["trade_date"].notna()].copy()
    if work.empty:
        return 0
    work["event_label_bool"] = work["event_label"].astype(bool)
    daily = (
        work.groupby("trade_date", dropna=False)
        .agg(event_count=("event_label_bool", "sum"), entity_count=("entity_id", "nunique"))
        .reset_index()
    )
    daily["event_share"] = daily["event_count"] / daily["entity_count"].replace({0: np.nan})
    active_dates = daily.loc[daily["event_share"].ge(float(event_share_threshold)), "trade_date"].tolist()
    horizon_values = pd.to_numeric(work.get("horizon"), errors="coerce").dropna() if "horizon" in work.columns else pd.Series(dtype=float)
    horizon = int(horizon_values.iloc[0]) if not horizon_values.empty else 1
    return _merge_market_event_dates(active_dates, daily["trade_date"].tolist(), horizon=horizon)


HOLDOUT_CONSUMPTION_COUNTER_KEYS = {
    "prospective_holdout_rows_evaluated",
    "prospective_holdout_score_count",
    "prospective_holdout_metric_count",
    "holdout_rows_used_for_calibration_count",
    "holdout_rows_used_for_evaluation_count",
    "holdout_rows_validated_count",
}


def holdout_consumption_issues(label: str, doc: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []

    def visit(prefix: str, value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                nested_prefix = f"{prefix}_{key}" if prefix else str(key)
                if str(key) in HOLDOUT_CONSUMPTION_COUNTER_KEYS and _as_int(nested, 0) > 0:
                    issues.append(f"{label}_{nested_prefix}_not_zero")
                visit(nested_prefix, nested)
        elif isinstance(value, list):
            for idx, nested in enumerate(value):
                visit(f"{prefix}_{idx}", nested)

    visit("", doc)
    return issues


def _positive_negative_counts(rows: pd.DataFrame) -> tuple[int, int]:
    if rows.empty:
        return 0, 0
    labels = rows["event_label"].astype(bool).astype(int)
    positives = int(labels.sum())
    return positives, int(len(labels) - positives)


def fit_calibrator(
    calibration_rows: pd.DataFrame,
    *,
    method: str,
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    if method == "identity_uncalibrated_reference":
        return {"status": "identity", "calibrator": None, "skip_reason": None}
    positives, negatives = _positive_negative_counts(calibration_rows)
    if positives < int(policy.get("min_calibration_positive_events", 2)):
        return {"status": "skipped", "calibrator": None, "skip_reason": "insufficient_positive_calibration_events"}
    if negatives < int(policy.get("min_calibration_negative_events", 2)):
        return {"status": "skipped", "calibrator": None, "skip_reason": "insufficient_negative_calibration_events"}
    raw = pd.to_numeric(calibration_rows.get("raw_score"), errors="coerce").to_numpy(dtype=float)
    labels = calibration_rows["event_label"].astype(bool).astype(int).to_numpy(dtype=int)
    finite = np.isfinite(raw)
    raw = raw[finite]
    labels = labels[finite]
    if len(np.unique(raw)) < 2:
        return {"status": "skipped", "calibrator": None, "skip_reason": "insufficient_unique_calibration_scores"}
    try:
        if method == "platt_logistic_calibration":
            from sklearn.linear_model import LogisticRegression

            calibrator = LogisticRegression(solver="lbfgs", max_iter=1000, random_state=20260611)
            calibrator.fit(raw.reshape(-1, 1), labels)
            return {"status": "fitted", "calibrator": calibrator, "skip_reason": None}
        if method == "isotonic_calibration":
            from sklearn.isotonic import IsotonicRegression

            calibrator = IsotonicRegression(out_of_bounds="clip")
            calibrator.fit(raw, labels)
            return {"status": "fitted", "calibrator": calibrator, "skip_reason": None}
    except ModuleNotFoundError as exc:
        raise RuntimeError("blocked_missing_sklearn") from exc
    raise ValueError(f"unsupported calibration method: {method}")


def apply_calibrator(rows: pd.DataFrame, *, method: str, calibrator: Any) -> np.ndarray:
    raw = pd.to_numeric(rows.get("raw_score"), errors="coerce").to_numpy(dtype=float)
    if method == "identity_uncalibrated_reference":
        return np.clip(raw, 0.0, 1.0)
    if method == "platt_logistic_calibration":
        return np.clip(calibrator.predict_proba(raw.reshape(-1, 1))[:, 1], 0.0, 1.0)
    if method == "isotonic_calibration":
        return np.clip(calibrator.predict(raw), 0.0, 1.0)
    raise ValueError(f"unsupported calibration method: {method}")


def _roc_auc(labels: np.ndarray, score: np.ndarray) -> float | None:
    if len(labels) == 0:
        return None
    positives = int(np.sum(labels == 1))
    negatives = int(np.sum(labels == 0))
    if positives == 0 or negatives == 0:
        return None
    ranks = pd.Series(score).rank(method="average").to_numpy(dtype=float)
    sum_pos = float(ranks[labels == 1].sum())
    auc = (sum_pos - positives * (positives + 1) / 2.0) / (positives * negatives)
    return float(auc) if math.isfinite(auc) else None


def _average_precision(labels: np.ndarray, score: np.ndarray) -> float | None:
    positives = int(np.sum(labels == 1))
    if positives == 0:
        return None
    order = np.argsort(-score, kind="mergesort")
    sorted_labels = labels[order]
    cumsum = np.cumsum(sorted_labels)
    ranks = np.arange(1, len(sorted_labels) + 1)
    precision = cumsum / ranks
    ap = float(precision[sorted_labels == 1].sum() / positives)
    return ap if math.isfinite(ap) else None


def calibration_curve_bins(
    rows: pd.DataFrame,
    *,
    score_column: str = "calibrated_score",
    bins: int = 10,
) -> list[dict[str, Any]]:
    if rows.empty:
        return []
    work = rows.copy()
    score = pd.to_numeric(work.get(score_column), errors="coerce")
    labels = work["event_label"].astype(bool).astype(int)
    valid = work[score.notna()].copy()
    if valid.empty:
        return []
    score = pd.to_numeric(valid[score_column], errors="coerce").clip(0.0, 1.0)
    labels = valid["event_label"].astype(bool).astype(int)
    out: list[dict[str, Any]] = []
    for idx in range(int(bins)):
        low = idx / float(bins)
        high = (idx + 1) / float(bins)
        if idx == bins - 1:
            mask = score.ge(low) & score.le(high)
        else:
            mask = score.ge(low) & score.lt(high)
        subset_score = score[mask]
        subset_labels = labels[mask]
        if subset_score.empty:
            row_count = 0
            positive = 0
            mean_score = None
            observed = None
            gap = None
        else:
            row_count = int(len(subset_score))
            positive = int(subset_labels.sum())
            mean_score = float(subset_score.mean())
            observed = float(subset_labels.mean())
            gap = float(observed - mean_score)
        out.append(
            {
                "bin_index": idx,
                "bin_low": low,
                "bin_high": high,
                "row_count": row_count,
                "positive_event_count": positive,
                "mean_score": mean_score,
                "observed_event_rate": observed,
                "calibration_gap": gap,
            }
        )
    return out


def expected_calibration_error(rows: pd.DataFrame) -> tuple[float | None, float | None, str]:
    bins = calibration_curve_bins(rows)
    non_empty = [row for row in bins if int(row["row_count"]) > 0]
    total = sum(int(row["row_count"]) for row in non_empty)
    if total == 0:
        return None, None, "no_scored_rows"
    abs_gaps = [abs(float(row["calibration_gap"])) for row in non_empty if row["calibration_gap"] is not None]
    ece = sum(abs(float(row["calibration_gap"])) * int(row["row_count"]) for row in non_empty) / float(total)
    mce = max(abs_gaps) if abs_gaps else None
    rates = [row["observed_event_rate"] for row in non_empty if row["observed_event_rate"] is not None]
    if len(rates) < 2:
        monotonic = "insufficient_non_empty_bins"
    else:
        monotonic = "pass" if all(b >= a - 1e-12 for a, b in zip(rates, rates[1:], strict=False)) else "non_monotonic"
    return float(ece), (float(mce) if mce is not None else None), monotonic


def compute_calibration_metrics(
    rows: pd.DataFrame,
    *,
    calibration_row_count: int,
    method: str,
    protocol: str,
    fit_status: str,
    skip_reason: str | None,
) -> dict[str, Any]:
    first = rows.head(1)
    raw_labels = rows["event_label"].astype(bool).astype(int).to_numpy(dtype=int) if not rows.empty else np.array([], dtype=int)
    calibrated_source = rows["calibrated_score"] if "calibrated_score" in rows else pd.Series([np.nan] * len(rows))
    raw_source = rows["raw_score"] if "raw_score" in rows else pd.Series([np.nan] * len(rows))
    calibrated_score = (
        pd.to_numeric(calibrated_source, errors="coerce").to_numpy(dtype=float) if not rows.empty else np.array([], dtype=float)
    )
    raw_score = pd.to_numeric(raw_source, errors="coerce").to_numpy(dtype=float) if not rows.empty else np.array([], dtype=float)
    finite = np.isfinite(calibrated_score)
    labels = raw_labels[finite]
    score = calibrated_score[finite]
    positives = int(labels.sum()) if len(labels) else 0
    negatives = int(len(labels) - positives)
    brier = float(np.mean((labels.astype(float) - score) ** 2)) if len(score) else None
    finite_identity = np.isfinite(raw_score) & np.isfinite(calibrated_score)
    identity_labels = raw_labels[finite_identity]
    identity_score = np.clip(raw_score[finite_identity], 0.0, 1.0)
    calibrated_for_identity = calibrated_score[finite_identity]
    brier_identity = (
        float(np.mean((identity_labels.astype(float) - identity_score) ** 2)) if len(identity_score) else None
    )
    brier_calibrated = (
        float(np.mean((identity_labels.astype(float) - calibrated_for_identity) ** 2))
        if len(calibrated_for_identity) == len(identity_labels) and len(identity_labels)
        else brier
    )
    brier_retention = (
        float(brier_identity - brier_calibrated)
        if brier_identity is not None and brier_calibrated is not None
        else None
    )
    log_loss = None
    if len(score):
        clipped = np.clip(score, 1e-15, 1 - 1e-15)
        log_loss_value = -np.mean(labels.astype(float) * np.log(clipped) + (1 - labels.astype(float)) * np.log(1 - clipped))
        log_loss = float(log_loss_value) if math.isfinite(log_loss_value) else None
    ece, mce, monotonic = expected_calibration_error(rows)
    slope = None
    intercept = None
    if len(score) >= 2 and len(np.unique(score)) >= 2:
        try:
            slope_value, intercept_value = np.polyfit(score, labels.astype(float), 1)
            slope = float(slope_value) if math.isfinite(float(slope_value)) else None
            intercept = float(intercept_value) if math.isfinite(float(intercept_value)) else None
        except (np.linalg.LinAlgError, ValueError):
            slope = None
            intercept = None
    row: dict[str, Any] = {
        "calibration_method": method,
        "calibration_protocol": protocol,
        "calibration_row_count": int(calibration_row_count),
        "evaluation_row_count": int(len(rows)),
        "scored_row_count": int(len(score)),
        "positive_event_count": positives,
        "negative_event_count": negatives,
        "event_base_rate": _safe_div(positives, len(score)),
        "brier_score": brier,
        "brier_identity_uncalibrated": brier_identity,
        "brier_calibrated": brier_calibrated,
        "brier_retention": brier_retention,
        "log_loss": log_loss,
        "expected_calibration_error": ece,
        "max_calibration_error": mce,
        "reliability_slope": slope,
        "reliability_intercept": intercept,
        "roc_auc": _roc_auc(labels, score),
        "average_precision": _average_precision(labels, score),
        "auc_retention_vs_identity": None,
        "ap_retention_vs_identity": None,
        "validation_market_event_block_count": 0,
        "monotonic_bin_status": monotonic,
        "calibration_fit_status": fit_status,
        "skip_reason": skip_reason,
        "model_variant": MODEL_VARIANT,
    }
    for column in _slice_key_columns():
        row[column] = None if first.empty else first.iloc[0].get(column)
    if row.get("horizon") is not None:
        row["horizon"] = int(row["horizon"])
    if row.get("threshold_value") is not None:
        row["threshold_value"] = float(row["threshold_value"])
    return row


def _attach_identity_retention(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    identity_by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        key = (
            row.get("fold_id"),
            row.get("asof_mode"),
            row.get("horizon"),
            row.get("threshold_type"),
            row.get("threshold_value"),
            row.get("target_usage"),
        )
        if row.get("calibration_method") == "identity_uncalibrated_reference":
            identity_by_key[key] = row
    for row in rows:
        key = (
            row.get("fold_id"),
            row.get("asof_mode"),
            row.get("horizon"),
            row.get("threshold_type"),
            row.get("threshold_value"),
            row.get("target_usage"),
        )
        identity = identity_by_key.get(key, {})
        auc = _as_float(row.get("roc_auc"))
        ap = _as_float(row.get("average_precision"))
        identity_auc = _as_float(identity.get("roc_auc"))
        identity_ap = _as_float(identity.get("average_precision"))
        row["auc_retention_vs_identity"] = None if auc is None or identity_auc in (None, 0.0) else float(auc / identity_auc)
        row["ap_retention_vs_identity"] = None if ap is None or identity_ap in (None, 0.0) else float(ap / identity_ap)
    return rows


def _cluster_summary_for_rows(
    rows: pd.DataFrame,
    *,
    cluster_type: str,
    metric_name: str = "brier_loss",
) -> dict[str, Any]:
    if rows.empty or cluster_type not in rows.columns:
        return {
            "cluster_type": cluster_type,
            "metric_name": metric_name,
            "cluster_count": 0,
            "min_cluster_size": 0,
            "max_cluster_size": 0,
            "clustered_metric_mean": None,
            "clustered_metric_std": None,
            "bootstrap_or_cluster_se_rows": None,
            "confidence_interval_low": None,
            "confidence_interval_high": None,
            "uncertainty_status": "insufficient_clusters",
        }
    work = rows.copy()
    labels = work["event_label"].astype(bool).astype(int)
    score = pd.to_numeric(work["calibrated_score"], errors="coerce")
    work["_brier_loss"] = (labels.astype(float) - score.astype(float)) ** 2
    grouped = work.groupby(cluster_type, dropna=False)["_brier_loss"].agg(["mean", "size"]).reset_index()
    values = grouped["mean"].dropna().to_numpy(dtype=float)
    sizes = grouped["size"].to_numpy(dtype=int)
    if len(values) < 2:
        return {
            "cluster_type": cluster_type,
            "metric_name": metric_name,
            "cluster_count": int(len(values)),
            "min_cluster_size": int(sizes.min()) if len(sizes) else 0,
            "max_cluster_size": int(sizes.max()) if len(sizes) else 0,
            "clustered_metric_mean": float(values.mean()) if len(values) else None,
            "clustered_metric_std": None,
            "bootstrap_or_cluster_se_rows": None,
            "confidence_interval_low": None,
            "confidence_interval_high": None,
            "uncertainty_status": "insufficient_clusters",
        }
    mean = float(values.mean())
    std = float(values.std(ddof=1))
    se = float(std / math.sqrt(float(len(values))))
    return {
        "cluster_type": cluster_type,
        "metric_name": metric_name,
        "cluster_count": int(len(values)),
        "min_cluster_size": int(sizes.min()) if len(sizes) else 0,
        "max_cluster_size": int(sizes.max()) if len(sizes) else 0,
        "clustered_metric_mean": mean,
        "clustered_metric_std": std,
        "bootstrap_or_cluster_se_rows": se,
        "confidence_interval_low": mean - 1.96 * se,
        "confidence_interval_high": mean + 1.96 * se,
        "uncertainty_status": "pass",
    }


def clustered_inference_rows(scored_rows: pd.DataFrame) -> list[dict[str, Any]]:
    if scored_rows.empty:
        return []
    work = scored_rows.copy()
    work["slice_key"] = [
        _slice_id(row)
        for row in work[["horizon", "threshold_type", "threshold_value", "target_usage"]].to_dict(orient="records")
    ]
    prefix = {
        "fold_id": work["fold_id"].iloc[0],
        "asof_mode": work["asof_mode"].iloc[0],
        "model_variant": MODEL_VARIANT,
        "horizon": int(work["horizon"].iloc[0]),
        "threshold_type": str(work["threshold_type"].iloc[0]),
        "threshold_value": float(work["threshold_value"].iloc[0]),
        "target_usage": str(work["target_usage"].iloc[0]),
        "calibration_method": str(work["calibration_method"].iloc[0]),
    }
    rows: list[dict[str, Any]] = []
    for cluster_type in ["entity_id", "trade_date", "fold_id", "slice_key"]:
        row = {**prefix, **_cluster_summary_for_rows(work, cluster_type=cluster_type)}
        rows.append(row)
    return rows


def _aggregate_slice_metrics(fold_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if not fold_rows:
        return []
    frame = pd.DataFrame(list(fold_rows))
    group_cols = ["asof_mode", "horizon", "threshold_type", "threshold_value", "target_usage", "calibration_method"]
    rows: list[dict[str, Any]] = []
    for _, group in frame.groupby(group_cols, sort=False, dropna=False):
        out = {column: group.iloc[0].get(column) for column in group_cols}
        out["model_variant"] = MODEL_VARIANT
        out["calibration_row_count"] = int(pd.to_numeric(group["calibration_row_count"], errors="coerce").fillna(0).sum())
        out["evaluation_row_count"] = int(pd.to_numeric(group["evaluation_row_count"], errors="coerce").fillna(0).sum())
        out["scored_row_count"] = int(pd.to_numeric(group["scored_row_count"], errors="coerce").fillna(0).sum())
        out["positive_event_count"] = int(pd.to_numeric(group["positive_event_count"], errors="coerce").fillna(0).sum())
        out["negative_event_count"] = int(pd.to_numeric(group["negative_event_count"], errors="coerce").fillna(0).sum())
        out["event_base_rate"] = _safe_div(out["positive_event_count"], out["scored_row_count"])
        for metric in [
            "brier_score",
            "brier_identity_uncalibrated",
            "brier_calibrated",
            "brier_retention",
            "log_loss",
            "expected_calibration_error",
            "max_calibration_error",
            "reliability_slope",
            "reliability_intercept",
            "roc_auc",
            "average_precision",
            "auc_retention_vs_identity",
            "ap_retention_vs_identity",
        ]:
            values = pd.to_numeric(group[metric], errors="coerce").dropna()
            out[metric] = float(values.mean()) if not values.empty else None
        block_values = pd.to_numeric(group.get("validation_market_event_block_count"), errors="coerce").dropna()
        out["validation_market_event_block_count"] = int(block_values.min()) if not block_values.empty else 0
        out["monotonic_bin_status"] = "pass" if all(group["monotonic_bin_status"].astype(str).eq("pass")) else "mixed_or_non_monotonic"
        out["calibration_fit_status"] = "aggregate"
        out["skip_reason"] = None
        out["fold_count"] = int(group["fold_id"].nunique())
        rows.append(out)
    return rows


def _readiness_category(row: Mapping[str, Any], *, policy: Mapping[str, Any], uncertainty_width: float | None) -> tuple[str, str]:
    if str(row.get("target_usage")) != "eligible":
        return "research_only", "diagnostic_only_target_usage"
    eval_rows = _as_int(row.get("evaluation_row_count"), 0)
    positives = _as_int(row.get("positive_event_count"), 0)
    negatives = _as_int(row.get("negative_event_count"), 0)
    if eval_rows < int(policy.get("min_evaluation_rows_for_candidate", 100)) or positives < int(
        policy.get("min_evaluation_positive_events_for_candidate", 3)
    ) or negatives <= 0:
        return "insufficient_data", "insufficient_evaluation_support"
    method = str(row.get("calibration_method"))
    if method == "identity_uncalibrated_reference":
        return "baseline_only_candidate", "uncalibrated_reference_not_probability"
    ece = _as_float(row.get("expected_calibration_error"))
    auc = _as_float(row.get("roc_auc"))
    brier = _as_float(row.get("brier_score"))
    brier_retention = _as_float(row.get("brier_retention"))
    market_blocks = _as_int(row.get("validation_market_event_block_count"), 0)
    usable_gate_passes = (
        eval_rows >= int(policy.get("usable_probability_min_evaluation_rows", 500))
        and positives >= int(policy.get("usable_probability_min_positive_events", 10))
        and ece is not None
        and ece <= float(policy.get("usable_probability_max_ece", 0.05))
        and (uncertainty_width is None or uncertainty_width <= float(policy.get("usable_probability_max_cluster_width", 0.25)))
        and brier is not None
    )
    if usable_gate_passes:
        if market_blocks < int(policy.get("usable_probability_min_market_event_blocks", 2)):
            return "ordinal_only_candidate", "market_event_block_evidence_below_minimum"
        if brier_retention is not None and brier_retention < 0:
            return "ordinal_only_candidate", "calibration_worsened_brier_score"
        return "usable_probability_candidate", "development_calibration_gate_pass"
    if (
        eval_rows >= int(policy.get("ordinal_min_evaluation_rows", 100))
        and positives >= int(policy.get("ordinal_min_positive_events", 3))
        and auc is not None
        and auc >= float(policy.get("ordinal_min_auc", 0.55))
    ):
        return "ordinal_only_candidate", "ranking_retained_but_probability_gate_not_met"
    return "research_only", "calibration_diagnostics_not_ready"


def build_readiness_matrix(
    slice_rows: Sequence[Mapping[str, Any]],
    clustered_rows: Sequence[Mapping[str, Any]],
    *,
    policy: Mapping[str, Any],
    leakage_total: int,
) -> list[dict[str, Any]]:
    width_by_key: dict[tuple[Any, ...], float | None] = {}
    for row in clustered_rows:
        if row.get("cluster_type") != "trade_date":
            continue
        key = (
            row.get("asof_mode"),
            row.get("horizon"),
            row.get("threshold_type"),
            row.get("threshold_value"),
            row.get("target_usage"),
            row.get("calibration_method"),
        )
        low = _as_float(row.get("confidence_interval_low"))
        high = _as_float(row.get("confidence_interval_high"))
        width_by_key[key] = None if low is None or high is None else float(high - low)
    out: list[dict[str, Any]] = []
    for row in slice_rows:
        key = (
            row.get("asof_mode"),
            row.get("horizon"),
            row.get("threshold_type"),
            row.get("threshold_value"),
            row.get("target_usage"),
            row.get("calibration_method"),
        )
        width = width_by_key.get(key)
        if leakage_total:
            category, reason = "blocked_by_leakage", "leakage_violation_present"
        else:
            category, reason = _readiness_category(row, policy=policy, uncertainty_width=width)
        out.append(
            {
                "asof_mode": row.get("asof_mode"),
                "horizon": int(row.get("horizon")),
                "threshold_type": row.get("threshold_type"),
                "threshold_value": float(row.get("threshold_value")),
                "target_usage": row.get("target_usage"),
                "calibration_method": row.get("calibration_method"),
                "readiness_category": category,
                "development_only": "yes",
                "evaluation_row_count": _as_int(row.get("evaluation_row_count"), 0),
                "positive_event_count": _as_int(row.get("positive_event_count"), 0),
                "negative_event_count": _as_int(row.get("negative_event_count"), 0),
                "mean_brier_score": _as_float(row.get("brier_score")),
                "mean_brier_retention": _as_float(row.get("brier_retention")),
                "validation_market_event_block_count": _as_int(row.get("validation_market_event_block_count"), 0),
                "mean_log_loss": _as_float(row.get("log_loss")),
                "mean_expected_calibration_error": _as_float(row.get("expected_calibration_error")),
                "max_expected_calibration_error": _as_float(row.get("max_calibration_error")),
                "mean_auc": _as_float(row.get("roc_auc")),
                "mean_average_precision": _as_float(row.get("average_precision")),
                "clustered_uncertainty_width": width,
                "fold_count": _as_int(row.get("fold_count"), 0),
                "readiness_reason": reason,
            }
        )
    return out


def evaluate_calibration_for_folds(
    *,
    target_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    fold_plan: Mapping[str, Any],
    policy: Mapping[str, Any],
    audit_sample_cap: int = DEFAULT_SAMPLE_ROWS,
) -> dict[str, Any]:
    methods = [str(item) for item in policy.get("calibration_methods", CALIBRATION_METHODS)]
    asof_modes = [str(item) for item in policy.get("asof_modes", ASOF_MODES)]
    fold_metric_rows: list[dict[str, Any]] = []
    bin_rows: list[dict[str, Any]] = []
    clustered_rows: list[dict[str, Any]] = []
    audit_rows: list[dict[str, Any]] = []
    manifest_rows: list[dict[str, Any]] = []
    leakage_counts = dict(LEAKAGE_ZERO_COUNTS)
    boundary_counts = dict(CALIBRATION_BOUNDARY_ZERO_COUNTS)
    calibration_row_total = 0
    evaluation_row_total = 0
    holdout_withheld_total = 0
    calibration_model_count = 0
    skipped_calibration_count = 0
    slice_keys_seen: set[tuple[Any, ...]] = set()
    folds_seen: set[str] = set()

    for fold in fold_plan.get("folds", []):
        fold_id = str(fold.get("fold_id", "fold_unknown"))
        split = split_fold_rows(target_rows, fold)
        train_rows = split["train_rows"]
        validation_rows = split["validation_rows"]
        holdout_withheld_total += int(split["prospective_holdout_rows_withheld"])
        if validation_rows.empty:
            continue
        folds_seen.add(fold_id)
        for asof_mode in asof_modes:
            features = feature_frames.get(asof_mode, pd.DataFrame())
            train_featured = _prepare_feature_join(train_rows, features, MODEL_FEATURE_COLUMNS)
            validation_featured = _prepare_feature_join(validation_rows, features, MODEL_FEATURE_COLUMNS)
            for slice_key, val_group in validation_featured.groupby(_slice_key_columns(), sort=False, dropna=False):
                if not isinstance(slice_key, tuple):
                    slice_key = (slice_key,)
                horizon, threshold_type, threshold_value, target_usage = slice_key
                market_event_blocks = validation_market_event_block_count(
                    val_group,
                    event_share_threshold=float(policy.get("primary_market_event_share", PRIMARY_MARKET_EVENT_SHARE)),
                )
                train_group = train_featured[
                    train_featured["horizon"].astype(int).eq(int(horizon))
                    & train_featured["threshold_type"].astype(str).eq(str(threshold_type))
                    & train_featured["threshold_value"].astype(float).eq(float(threshold_value))
                    & train_featured["target_usage"].astype(str).eq(str(target_usage))
                ].copy()
                result = fit_logistic_model(train_group, val_group.copy(), MODEL_FEATURE_COLUMNS, _logistic_policy())
                if result["status"] != "fitted":
                    skipped_calibration_count += len(methods)
                    continue
                scored_validation = val_group.copy().reset_index(drop=True)
                scored_validation["raw_score"] = result["scores"]
                scored_validation["fold_id"] = fold_id
                scored_validation["asof_mode"] = asof_mode
                scored_validation["model_variant"] = MODEL_VARIANT
                split_eval = split_calibration_evaluation_rows(
                    scored_validation,
                    calibration_fraction=float(policy.get("validation_calibration_fraction", 0.5)),
                )
                calibration_rows = split_eval["calibration_rows"]
                evaluation_rows = split_eval["evaluation_rows"]
                protocol = str(split_eval["protocol"])
                for key, value in detect_calibration_boundary_violations(calibration_rows, evaluation_rows).items():
                    boundary_counts[key] = int(boundary_counts.get(key, 0)) + int(value)
                calibration_row_total += int(len(calibration_rows))
                evaluation_row_total += int(len(evaluation_rows))
                if not evaluation_rows.empty:
                    slice_keys_seen.add((asof_mode, int(horizon), str(threshold_type), float(threshold_value), str(target_usage)))
                for method in methods:
                    fit = fit_calibrator(calibration_rows, method=method, policy=policy)
                    if fit["status"] == "skipped":
                        skipped_calibration_count += 1
                        empty_metrics = compute_calibration_metrics(
                            evaluation_rows.iloc[0:0].copy(),
                            calibration_row_count=len(calibration_rows),
                            method=method,
                            protocol=protocol,
                            fit_status="skipped",
                            skip_reason=str(fit["skip_reason"]),
                        )
                        empty_metrics.update(
                            {
                                "fold_id": fold_id,
                                "asof_mode": asof_mode,
                                "horizon": int(horizon),
                                "threshold_type": str(threshold_type),
                                "threshold_value": float(threshold_value),
                                "target_usage": str(target_usage),
                                "validation_market_event_block_count": int(market_event_blocks),
                            }
                        )
                        fold_metric_rows.append(empty_metrics)
                        continue
                    if fit["status"] == "fitted":
                        calibration_model_count += 1
                    scored_eval = evaluation_rows.copy().reset_index(drop=True)
                    if scored_eval.empty:
                        skipped_calibration_count += 1
                        continue
                    scored_eval["calibrated_score"] = apply_calibrator(
                        scored_eval,
                        method=method,
                        calibrator=fit.get("calibrator"),
                    )
                    scored_eval["calibration_method"] = method
                    scored_eval["calibration_protocol"] = protocol
                    metrics = compute_calibration_metrics(
                        scored_eval,
                        calibration_row_count=len(calibration_rows),
                        method=method,
                        protocol=protocol,
                        fit_status=str(fit["status"]),
                        skip_reason=None,
                    )
                    metrics.update(
                        {
                            "fold_id": fold_id,
                            "asof_mode": asof_mode,
                            "horizon": int(horizon),
                            "threshold_type": str(threshold_type),
                            "threshold_value": float(threshold_value),
                            "target_usage": str(target_usage),
                            "validation_market_event_block_count": int(market_event_blocks),
                        }
                    )
                    fold_metric_rows.append(metrics)
                    prefix = {
                        "fold_id": fold_id,
                        "asof_mode": asof_mode,
                        "model_variant": MODEL_VARIANT,
                        "horizon": int(horizon),
                        "threshold_type": str(threshold_type),
                        "threshold_value": float(threshold_value),
                        "target_usage": str(target_usage),
                        "calibration_method": method,
                    }
                    for bin_row in calibration_curve_bins(scored_eval):
                        bin_rows.append({**prefix, **bin_row})
                    clustered_rows.extend(clustered_inference_rows(scored_eval))
                    if fit["status"] in {"identity", "fitted"}:
                        manifest_rows.append(
                            {
                                "calibration_id": f"{method}::{fold_id}::{asof_mode}::{_slice_id(scored_eval.iloc[0].to_dict())}",
                                "fold_id": fold_id,
                                "asof_mode": asof_mode,
                                "model_variant": MODEL_VARIANT,
                                "horizon": int(horizon),
                                "threshold_type": str(threshold_type),
                                "threshold_value": float(threshold_value),
                                "target_usage": str(target_usage),
                                "calibration_method": method,
                                "calibration_protocol": protocol,
                                "calibration_row_count": int(len(calibration_rows)),
                                "evaluation_row_count": int(len(scored_eval)),
                                "fit_status": str(fit["status"]),
                                "serialized_model_written": "no",
                                "development_only": "yes",
                            }
                        )
                    if len(audit_rows) < audit_sample_cap:
                        take = scored_eval.head(audit_sample_cap - len(audit_rows)).copy()
                        take["row_role"] = "evaluation"
                        for audit_row in take[AUDIT_SAMPLE_COLUMNS].to_dict(orient="records"):
                            audit_rows.append(audit_row)

    fold_metric_rows = _attach_identity_retention(fold_metric_rows)
    slice_metric_rows = _aggregate_slice_metrics(fold_metric_rows)
    leakage_counts["prospective_holdout_score_count"] = int(
        sum(
            1
            for row in audit_rows
            if pd.Timestamp(row.get("trade_date")).normalize() >= pd.Timestamp(HOLDOUT_START).normalize()
        )
    )
    leakage_counts["leakage_violation_count_total"] = int(
        sum(value for key, value in leakage_counts.items() if key != "leakage_violation_count_total")
    )
    boundary_counts["calibration_boundary_violation_count_total"] = int(
        sum(value for key, value in boundary_counts.items() if key != "calibration_boundary_violation_count_total")
    )
    readiness_rows = build_readiness_matrix(
        slice_metric_rows,
        clustered_rows,
        policy=policy,
        leakage_total=int(leakage_counts["leakage_violation_count_total"]) + int(boundary_counts["calibration_boundary_violation_count_total"]),
    )
    return {
        "fold_metrics": fold_metric_rows,
        "slice_metrics": slice_metric_rows,
        "calibration_bins": bin_rows,
        "clustered_inference": clustered_rows,
        "readiness_matrix": readiness_rows,
        "audit_rows": audit_rows,
        "model_manifest_entries": manifest_rows,
        "leakage_violation_counts": leakage_counts,
        "calibration_boundary_violation_counts": boundary_counts,
        "calibration_row_count_total": int(calibration_row_total),
        "evaluation_row_count_total": int(evaluation_row_total),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_rows_withheld": int(holdout_withheld_total),
        "calibration_model_count": int(calibration_model_count),
        "skipped_calibration_count": int(skipped_calibration_count),
        "slice_count_evaluated": int(len(slice_keys_seen)),
        "fold_count_evaluated": int(len(folds_seen)),
    }


def _metric_summary(slice_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    frame = pd.DataFrame(list(slice_rows))
    if frame.empty:
        return {}
    out: dict[str, Any] = {
        "slice_metric_row_count": int(len(frame)),
        "methods": sorted(frame["calibration_method"].astype(str).unique().tolist()),
    }
    for metric in ["brier_score", "log_loss", "expected_calibration_error", "roc_auc", "average_precision"]:
        values = pd.to_numeric(frame.get(metric), errors="coerce").dropna()
        out[f"mean_{metric}"] = float(values.mean()) if not values.empty else None
        out[f"best_{metric}"] = float(values.min()) if metric in {"brier_score", "log_loss", "expected_calibration_error"} and not values.empty else (
            float(values.max()) if not values.empty else None
        )
    return out


def _best_by_metric(rows: Sequence[Mapping[str, Any]], metric: str, *, lower_is_better: bool) -> dict[str, Any] | None:
    candidates = [row for row in rows if _as_float(row.get(metric)) is not None]
    if not candidates:
        return None
    best = min(candidates, key=lambda row: float(row[metric])) if lower_is_better else max(candidates, key=lambda row: float(row[metric]))
    return {
        "asof_mode": best.get("asof_mode"),
        "calibration_method": best.get("calibration_method"),
        "metric": metric,
        "value": _as_float(best.get(metric)),
        "horizon": best.get("horizon"),
        "threshold_type": best.get("threshold_type"),
        "threshold_value": best.get("threshold_value"),
        "target_usage": best.get("target_usage"),
    }


def _readiness_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {category: 0 for category in READINESS_CATEGORIES}
    for row in rows:
        category = str(row.get("readiness_category", "insufficient_data"))
        counts[category] = counts.get(category, 0) + 1
    return counts


def _clustered_report_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"row_count": 0}
    frame = pd.DataFrame(list(rows))
    return {
        "row_count": int(len(frame)),
        "cluster_types": sorted(frame["cluster_type"].astype(str).unique().tolist()),
        "pass_uncertainty_row_count": int(frame["uncertainty_status"].astype(str).eq("pass").sum()),
        "max_cluster_count": int(pd.to_numeric(frame["cluster_count"], errors="coerce").max()),
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
    wp4_status: str | None = None,
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
        "wp4_logistic_hazard_status": wp4_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "fold_plan_status": "blocked",
        "fold_plan_source": None,
        "fold_plan_path": None,
        "magnitude_overview": {},
        "supersedes": None,
        "supersession_reason": None,
        "trial_accounting_invalidation_recorded": "no",
        "policy_status": "blocked",
        "calibration_methods_evaluated": CALIBRATION_METHODS,
        "primary_calibration_method": PRIMARY_CALIBRATION_METHOD,
        "asof_modes_evaluated": ASOF_MODES,
        "primary_asof_mode": PRIMARY_ASOF_MODE,
        "slice_count_evaluated": 0,
        "fold_count_evaluated": 0,
        "calibration_row_count_total": 0,
        "evaluation_row_count_total": 0,
        "prospective_holdout_rows_evaluated": 0,
        "calibration_model_count": 0,
        "skipped_calibration_count": 0,
        "readiness_category_counts": _readiness_counts([]),
        "usable_probability_candidate_count": 0,
        "ordinal_only_candidate_count": 0,
        "baseline_only_candidate_count": 0,
        "research_only_count": 0,
        "insufficient_data_count": 0,
        "blocked_by_leakage_count": 0,
        "fold_metrics_path": None,
        "slice_metrics_path": None,
        "calibration_bins_path": None,
        "clustered_inference_path": None,
        "readiness_matrix_path": None,
        "model_manifest_path": None,
        "audit_sample_path": None,
        "metric_summary": {},
        "best_calibrated_candidate_by_brier": None,
        "best_calibrated_candidate_by_log_loss": None,
        "best_calibrated_candidate_by_ece": None,
        "clustered_inference_summary": {},
        "leakage_violation_counts": dict(LEAKAGE_ZERO_COUNTS),
        "calibration_boundary_violation_counts": dict(CALIBRATION_BOUNDARY_ZERO_COUNTS),
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
    calibration_bins: Path,
    clustered_inference: Path,
    readiness_matrix: Path,
    model_manifest: Path,
    audit_sample: Path,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(fold_metrics, [], FOLD_METRIC_COLUMNS)
    _write_csv(slice_metrics, [], SLICE_METRIC_COLUMNS)
    _write_csv(calibration_bins, [], CALIBRATION_BIN_COLUMNS)
    _write_csv(clustered_inference, [], CLUSTERED_INFERENCE_COLUMNS)
    _write_csv(readiness_matrix, [], READINESS_COLUMNS)
    _write_csv(audit_sample, [], AUDIT_SAMPLE_COLUMNS)
    _write_json(
        model_manifest,
        {
            "index_id": INDEX_ID,
            "report_version": REPORT_VERSION,
            "status": report.get("status"),
            "calibration_model_serialized": "no",
            "models": [],
        },
    )


def build_calibration_readiness_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    baseline_diagnostics: Path | str = DEFAULT_BASELINE_DIAGNOSTICS,
    vol_scaled_sanity: Path | str = DEFAULT_VOL_SCALED_SANITY,
    logistic_hazard: Path | str = DEFAULT_LOGISTIC_HAZARD,
    logistic_fold_metrics: Path | str = DEFAULT_LOGISTIC_FOLD_METRICS,
    logistic_slice_metrics: Path | str = DEFAULT_LOGISTIC_SLICE_METRICS,
    logistic_model_manifest: Path | str = DEFAULT_LOGISTIC_MODEL_MANIFEST,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    policy: Path | str = DEFAULT_POLICY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    fold_metrics: Path | str = DEFAULT_FOLD_METRICS,
    slice_metrics: Path | str = DEFAULT_SLICE_METRICS,
    calibration_bins: Path | str = DEFAULT_CALIBRATION_BINS,
    clustered_inference: Path | str = DEFAULT_CLUSTERED_INFERENCE,
    readiness_matrix: Path | str = DEFAULT_READINESS_MATRIX,
    model_manifest: Path | str = DEFAULT_MODEL_MANIFEST,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP5 calibration readiness is no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    fold_path = Path(fold_metrics)
    slice_path = Path(slice_metrics)
    bins_path = Path(calibration_bins)
    clustered_path = Path(clustered_inference)
    readiness_path = Path(readiness_matrix)
    manifest_path = Path(model_manifest)
    audit_path = Path(audit_sample)

    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
        full_audit = _load_json(full_target_audit)
        baseline_report = _load_json(baseline_diagnostics)
        vol_report = _load_json(vol_scaled_sanity)
        logistic_report = _load_json(logistic_hazard)
        fold_doc = _load_json(fold_plan)
    except FileNotFoundError as exc:
        report = _blocked_report(status="blocked_missing_input", db_path=resolved_db, reasons=[f"missing input: {exc.filename}"])
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
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
            wp4_status=str(logistic_report.get("status", "unknown")),
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
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
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
            wp4_status=str(logistic_report.get("status", "unknown")),
            reasons=[f"missing policy: {policy}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
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
            wp4_status=str(logistic_report.get("status", "unknown")),
            reasons=policy_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
            audit_sample=audit_path,
        )
        return report

    precondition_status, precondition_issues = validate_wp5_preconditions(
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        baseline_diagnostics=baseline_report,
        vol_scaled_sanity=vol_report,
        logistic_hazard=logistic_report,
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
            wp4_status=str(logistic_report.get("status", "unknown")),
            reasons=precondition_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
            audit_sample=audit_path,
        )
        return report

    target_universe_status = "partial"
    try:
        target_universe_doc = _load_machine_config(target_universe)
        if target_universe_doc.get("source", {}).get("v7_coverage_available") == "yes":
            target_universe_status = "pass"
    except FileNotFoundError:
        target_universe_status = "missing"

    # These inputs are required by the package contract; reading them here also
    # verifies that the accepted WP4 artifact set is present before recomputing
    # raw scores in memory.
    _ = pd.read_csv(logistic_fold_metrics)
    _ = pd.read_csv(logistic_slice_metrics)
    _ = _load_json(logistic_model_manifest)

    specs = slice_specs_from_target_support(support)
    universe_ids = v7.universe_frame["entity_id"].astype(str).tolist()
    ohlcv, _range_report = read_ohlcv_inputs(resolved_db, universe_ids)
    if ohlcv.empty:
        close_only = v7.price_frame.rename(columns={"sector_id": "entity_id"}).copy()
        close_only["open"] = np.nan
        close_only["high"] = np.nan
        close_only["low"] = np.nan
        ohlcv = close_only[["entity_id", "trade_date", "open", "high", "low", "close"]]
    price_features, _ = build_price_baseline_features(ohlcv)
    feature_frames = {mode: shifted_price_features(price_features, asof_mode=mode) for mode in policy_doc.get("asof_modes", ASOF_MODES)}

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
            wp4_status=str(logistic_report.get("status", "unknown")),
            reasons=["fold plan has no valid validation_end_date"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
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
        evaluation = evaluate_calibration_for_folds(
            target_rows=target_rows,
            feature_frames=feature_frames,
            fold_plan=fold_doc,
            policy=policy_doc,
            audit_sample_cap=int(policy_doc.get("audit_sample_cap", DEFAULT_SAMPLE_ROWS)),
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
            wp4_status=str(logistic_report.get("status", "unknown")),
            reasons=["scikit-learn is unavailable"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            calibration_bins=bins_path,
            clustered_inference=clustered_path,
            readiness_matrix=readiness_path,
            model_manifest=manifest_path,
            audit_sample=audit_path,
        )
        return report

    _write_csv(fold_path, evaluation["fold_metrics"], FOLD_METRIC_COLUMNS)
    _write_csv(slice_path, evaluation["slice_metrics"], SLICE_METRIC_COLUMNS)
    _write_csv(bins_path, evaluation["calibration_bins"], CALIBRATION_BIN_COLUMNS)
    _write_csv(clustered_path, evaluation["clustered_inference"], CLUSTERED_INFERENCE_COLUMNS)
    _write_csv(readiness_path, evaluation["readiness_matrix"], READINESS_COLUMNS)
    _write_csv(audit_path, evaluation["audit_rows"], AUDIT_SAMPLE_COLUMNS)
    manifest = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "status": "pass",
        "source_db_path": _safe_path(resolved_db),
        "calibration_model_serialized": "no",
        "development_only": "yes",
        "model_count": int(len(evaluation["model_manifest_entries"])),
        "models": evaluation["model_manifest_entries"],
        "created_at": _now_iso(),
    }
    _write_json(manifest_path, manifest)

    readiness_counts = _readiness_counts(evaluation["readiness_matrix"])
    leakage_counts = evaluation["leakage_violation_counts"]
    boundary_counts = evaluation["calibration_boundary_violation_counts"]
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
        "wp4_logistic_hazard_status": logistic_report.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": target_universe_status,
        "fold_plan_status": fold_doc.get("status"),
        "fold_plan_source": fold_doc.get("fold_plan_source"),
        "fold_plan_path": _safe_path(fold_plan),
        "magnitude_overview": fold_doc.get("magnitude_overview", {}),
        "supersedes": SUPERSEDES_MICROFOLD_RUN,
        "supersession_reason": SUPERSESSION_REASON,
        "trial_accounting_invalidation_recorded": "yes"
        if fold_doc.get("index_id") == "STAGE03V-RERUN1-v1"
        else "no",
        "trial_accounting_path": "reports/stage03v/validation_trial_accounting.json"
        if fold_doc.get("index_id") == "STAGE03V-RERUN1-v1"
        else None,
        "policy_status": "pass",
        "calibration_methods_evaluated": policy_doc.get("calibration_methods", CALIBRATION_METHODS),
        "primary_calibration_method": policy_doc.get("primary_calibration_method", PRIMARY_CALIBRATION_METHOD),
        "asof_modes_evaluated": policy_doc.get("asof_modes", ASOF_MODES),
        "primary_asof_mode": policy_doc.get("primary_asof_mode", PRIMARY_ASOF_MODE),
        "slice_count_evaluated": evaluation["slice_count_evaluated"],
        "fold_count_evaluated": evaluation["fold_count_evaluated"],
        "calibration_row_count_total": evaluation["calibration_row_count_total"],
        "evaluation_row_count_total": evaluation["evaluation_row_count_total"],
        "prospective_holdout_rows_evaluated": evaluation["prospective_holdout_rows_evaluated"],
        "prospective_holdout_rows_withheld": evaluation["prospective_holdout_rows_withheld"],
        "calibration_model_count": evaluation["calibration_model_count"],
        "skipped_calibration_count": evaluation["skipped_calibration_count"],
        "readiness_category_counts": readiness_counts,
        "usable_probability_candidate_count": readiness_counts.get("usable_probability_candidate", 0),
        "ordinal_only_candidate_count": readiness_counts.get("ordinal_only_candidate", 0),
        "baseline_only_candidate_count": readiness_counts.get("baseline_only_candidate", 0),
        "research_only_count": readiness_counts.get("research_only", 0),
        "insufficient_data_count": readiness_counts.get("insufficient_data", 0),
        "blocked_by_leakage_count": readiness_counts.get("blocked_by_leakage", 0),
        "fold_metrics_path": _safe_path(fold_path),
        "slice_metrics_path": _safe_path(slice_path),
        "calibration_bins_path": _safe_path(bins_path),
        "clustered_inference_path": _safe_path(clustered_path),
        "readiness_matrix_path": _safe_path(readiness_path),
        "model_manifest_path": _safe_path(manifest_path),
        "audit_sample_path": _safe_path(audit_path),
        "metric_summary": _metric_summary(evaluation["slice_metrics"]),
        "best_calibrated_candidate_by_brier": _best_by_metric(evaluation["slice_metrics"], "brier_score", lower_is_better=True),
        "best_calibrated_candidate_by_log_loss": _best_by_metric(evaluation["slice_metrics"], "log_loss", lower_is_better=True),
        "best_calibrated_candidate_by_ece": _best_by_metric(
            evaluation["slice_metrics"],
            "expected_calibration_error",
            lower_is_better=True,
        ),
        "clustered_inference_summary": _clustered_report_summary(evaluation["clustered_inference"]),
        "vol_scaled_candidate_tracking_status": "tracked_reference_only",
        "fixed_threshold_mainline_status": "unchanged_primary_target",
        "leakage_violation_counts": leakage_counts,
        "calibration_boundary_violation_counts": boundary_counts,
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": [],
        "remaining_risks": [
            "Readiness labels are development-only candidates and are not final decision-support approval.",
            "Prospective final holdout remains unconsumed; WP6/WP7 must handle later validation protocol work.",
            "Volatility-scaled candidates remain reference-only and do not replace fixed-threshold Stage03V1 labels.",
        ],
    }
    violation_total = int(leakage_counts.get("leakage_violation_count_total", 0)) + int(
        boundary_counts.get("calibration_boundary_violation_count_total", 0)
    )
    if violation_total == 0 and evaluation["evaluation_row_count_total"] > 0:
        report["status"] = "pass"
    elif evaluation["evaluation_row_count_total"] == 0:
        report["status"] = "partial_insufficient_data"
        report["blocking_reasons"] = ["no evaluation rows available for calibration readiness"]
    else:
        report["status"] = "fail"
        report["blocking_reasons"] = ["calibration leakage_or_boundary_violation_detected"]
    holdout_issues = holdout_consumption_issues("wp5_report", report)
    if holdout_issues:
        report["status"] = "blocked_holdout_consumed"
        report["blocking_reasons"] = holdout_issues
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
    parser.add_argument("--logistic-hazard", type=Path, default=DEFAULT_LOGISTIC_HAZARD)
    parser.add_argument("--logistic-fold-metrics", type=Path, default=DEFAULT_LOGISTIC_FOLD_METRICS)
    parser.add_argument("--logistic-slice-metrics", type=Path, default=DEFAULT_LOGISTIC_SLICE_METRICS)
    parser.add_argument("--logistic-model-manifest", type=Path, default=DEFAULT_LOGISTIC_MODEL_MANIFEST)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--fold-metrics", type=Path, default=DEFAULT_FOLD_METRICS)
    parser.add_argument("--slice-metrics", type=Path, default=DEFAULT_SLICE_METRICS)
    parser.add_argument("--calibration-bins", type=Path, default=DEFAULT_CALIBRATION_BINS)
    parser.add_argument("--clustered-inference", type=Path, default=DEFAULT_CLUSTERED_INFERENCE)
    parser.add_argument("--readiness-matrix", type=Path, default=DEFAULT_READINESS_MATRIX)
    parser.add_argument("--model-manifest", type=Path, default=DEFAULT_MODEL_MANIFEST)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_calibration_readiness_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        baseline_diagnostics=args.baseline_diagnostics,
        vol_scaled_sanity=args.vol_scaled_sanity,
        logistic_hazard=args.logistic_hazard,
        logistic_fold_metrics=args.logistic_fold_metrics,
        logistic_slice_metrics=args.logistic_slice_metrics,
        logistic_model_manifest=args.logistic_model_manifest,
        fold_plan=args.fold_plan,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        fold_metrics=args.fold_metrics,
        slice_metrics=args.slice_metrics,
        calibration_bins=args.calibration_bins,
        clustered_inference=args.clustered_inference,
        readiness_matrix=args.readiness_matrix,
        model_manifest=args.model_manifest,
        audit_sample=args.audit_sample,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_CALIBRATION_READINESS="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"calibration_models={report.get('calibration_model_count')} "
        f"readiness_rows={sum(report.get('readiness_category_counts', {}).values()) if report.get('readiness_category_counts') else 0} "
        f"usable_probability_candidates={report.get('usable_probability_candidate_count')} "
        f"leakage_violations={report.get('leakage_violation_counts', {}).get('leakage_violation_count_total')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
