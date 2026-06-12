"""Stage03V WP6 risk validation protocol and downshift research report.

WP6 consumes accepted Stage03V WP1-WP5 artifacts and emits a
historical-development validation evidence pack. It does not fetch external
data, consume prospective holdout rows, recalibrate probabilities, train
models, or produce trading/decision outputs.
"""

from __future__ import annotations

import argparse
import json
import math
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


INDEX_ID = "STAGE03V-WP6-v1"
REPORT_VERSION = "stage03v_risk_validation_v1"
POLICY_VERSION = "stage03v_risk_validation_protocol_policy_v1"
STAGE_ID = "stage03v"
PRIMARY_TARGET_FAMILY = "fixed_threshold_stage03v1_downside_event"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_BASELINE_DIAGNOSTICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_VOL_SCALED_SANITY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_LOGISTIC_HAZARD = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_CALIBRATION_READINESS = ROOT / "reports" / "stage03v" / "calibration_readiness_report.json"
DEFAULT_CALIBRATION_FOLD_METRICS = ROOT / "reports" / "stage03v" / "calibration_fold_metrics.csv"
DEFAULT_CALIBRATION_SLICE_METRICS = ROOT / "reports" / "stage03v" / "calibration_slice_metrics.csv"
DEFAULT_CALIBRATION_BINS = ROOT / "reports" / "stage03v" / "calibration_curve_bins.csv"
DEFAULT_CLUSTERED_INFERENCE = ROOT / "reports" / "stage03v" / "clustered_inference_summary.csv"
DEFAULT_READINESS_MATRIX = ROOT / "reports" / "stage03v" / "downside_readiness_matrix.csv"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_risk_validation_protocol_policy_v1.yaml"
DEFAULT_PROTOCOL_OUTPUT = ROOT / "reports" / "stage03v" / "risk_validation_protocol.md"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "risk_validation_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "risk_validation_report.json"
DEFAULT_METRICS = ROOT / "reports" / "stage03v" / "risk_validation_metrics.csv"
DEFAULT_DOWNSHIFT_REPORT = ROOT / "reports" / "stage03v" / "downshift_research_report.md"
DEFAULT_DOWNSHIFT_JSON = ROOT / "reports" / "stage03v" / "downshift_research_report.json"
DEFAULT_CANDIDATE_MATRIX = ROOT / "reports" / "stage03v" / "downshift_candidate_matrix.csv"
DEFAULT_CLUSTERED_SUMMARY = ROOT / "reports" / "stage03v" / "risk_validation_clustered_summary.csv"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "risk_validation_audit_sample.csv"
DEFAULT_WP7_MANIFEST = ROOT / "reports" / "stage03v" / "wp7_final_gate_input_manifest.json"

VALIDATION_STATUSES = [
    "validation_pass_candidate",
    "validation_watchlist",
    "research_only_evidence",
    "insufficient_validation_support",
    "blocked_by_boundary_or_leakage",
]
DOWNSHIFT_TIERS = [
    "research_downshift_watch",
    "research_downshift_candidate",
    "research_downshift_insufficient",
    "research_downshift_blocked",
]
READINESS_CATEGORIES = [
    "usable_probability_candidate",
    "ordinal_only_candidate",
    "baseline_only_candidate",
    "research_only",
    "insufficient_data",
    "blocked_by_leakage",
]
KEY_COLUMNS = [
    "asof_mode",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
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
    "validation_protocol_created": "yes",
    "research_report_created": "yes",
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
VALIDATION_BOUNDARY_ZERO_COUNTS = {
    "wp5_calibration_boundary_violation_count_total": 0,
    "holdout_rows_validated_count": 0,
    "recalibration_attempt_count": 0,
    "new_model_training_count": 0,
    "readiness_reassignment_count": 0,
    "trading_or_decision_output_count": 0,
    "validation_boundary_violation_count_total": 0,
}

METRIC_COLUMNS = KEY_COLUMNS + [
    "readiness_category",
    "validation_status",
    "downshift_research_tier",
    "research_only",
    "not_trading_output",
    "no_position_sizing",
    "no_buy_sell_recommendation",
    "no_execution_instruction",
    "evaluation_row_count",
    "positive_event_count",
    "negative_event_count",
    "event_base_rate",
    "fold_count",
    "mean_brier_score",
    "mean_log_loss",
    "mean_expected_calibration_error",
    "max_expected_calibration_error",
    "mean_auc",
    "mean_average_precision",
    "clustered_uncertainty_width",
    "event_lift_top_bin",
    "top_bin_row_count",
    "top_bin_observed_event_rate",
    "coverage_support_status",
    "calibration_stability_status",
    "fold_stability_status",
    "clustered_uncertainty_status",
    "lead_time_status",
    "event_capture_status",
    "false_alarm_concentration_status",
    "quantile_lift_status",
    "threshold_sensitivity_status",
    "entity_concentration_status",
    "calendar_date_concentration_status",
    "baseline_comparison_status",
    "known_anomaly_handling_status",
    "validation_dimension_pass_count",
    "validation_dimension_watch_count",
    "validation_dimension_insufficient_count",
    "validation_reason",
]
CLUSTERED_SUMMARY_COLUMNS = KEY_COLUMNS + [
    "entity_cluster_count",
    "entity_min_cluster_size",
    "entity_max_cluster_size",
    "entity_uncertainty_status",
    "date_cluster_count",
    "date_min_cluster_size",
    "date_max_cluster_size",
    "date_uncertainty_status",
    "date_uncertainty_width",
]
AUDIT_COLUMNS = KEY_COLUMNS + [
    "readiness_category",
    "validation_status",
    "downshift_research_tier",
    "research_only",
    "not_trading_output",
    "evaluation_row_count",
    "positive_event_count",
    "fold_count",
    "validation_reason",
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


def _normalise_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("asof_mode")),
        int(row.get("horizon")),
        str(row.get("threshold_type")),
        float(row.get("threshold_value")),
        str(row.get("target_usage")),
        str(row.get("calibration_method")),
    )


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "source_calibration_readiness": "reports/stage03v/calibration_readiness_report.json",
        "source_readiness_matrix": "reports/stage03v/downside_readiness_matrix.csv",
        "fold_plan": "reports/stage03v/purge_embargo_fold_plan.json",
        "primary_target_family": PRIMARY_TARGET_FAMILY,
        "vol_scaled_candidate_policy": "tracked_reference_only",
        "historical_development_only": True,
        "final_holdout_policy": "withheld_not_scored",
        "validation_scope": "development_research_protocol_only",
        "validation_statuses": VALIDATION_STATUSES,
        "downshift_research_tiers": DOWNSHIFT_TIERS,
        "min_evaluation_rows_for_pass_candidate": 500,
        "min_positive_events_for_pass_candidate": 10,
        "min_evaluation_rows_for_watchlist": 100,
        "min_positive_events_for_watchlist": 3,
        "max_ece_for_pass_candidate": 0.05,
        "max_ece_for_watchlist": 0.10,
        "max_cluster_width_for_pass_candidate": 0.25,
        "max_cluster_width_for_watchlist": 0.50,
        "min_top_bin_row_count": 10,
        "min_event_lift_for_pass_candidate": 1.20,
        "min_event_lift_for_watchlist": 1.00,
        "audit_sample_cap": 500,
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
        "final_holdout_policy",
        "validation_scope",
        "external_fetch_policy",
        "persistent_db_table_policy",
        "full_score_matrix_policy",
    ]:
        if policy.get(key) != expected[key]:
            issues.append(f"{key}_mismatch")
    if policy.get("historical_development_only") is not True:
        issues.append("historical_development_only_not_true")
    if list(policy.get("validation_statuses", [])) != VALIDATION_STATUSES:
        issues.append("validation_statuses_mismatch")
    if list(policy.get("downshift_research_tiers", [])) != DOWNSHIFT_TIERS:
        issues.append("downshift_research_tiers_mismatch")
    forbidden = set(policy.get("forbidden_outputs", []))
    if not {"buy", "sell", "position_sizing", "execution_instruction", "portfolio_recommendation"}.issubset(forbidden):
        issues.append("forbidden_outputs_incomplete")
    return issues


def _status(doc: Mapping[str, Any], default: str = "unknown") -> str:
    return str(doc.get("status", default))


def _total_from_counts(counts: Mapping[str, Any], total_key: str) -> int:
    if total_key in counts:
        return _as_int(counts.get(total_key), 0)
    return int(sum(_as_int(value, 0) for value in counts.values()))


def validate_wp6_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    full_target_audit: Mapping[str, Any],
    baseline_diagnostics: Mapping[str, Any],
    vol_scaled_sanity: Mapping[str, Any],
    logistic_hazard: Mapping[str, Any],
    calibration_readiness: Mapping[str, Any],
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
        ("wp5", calibration_readiness),
    ]
    holdout_issues: list[str] = []
    for label, doc in docs:
        if doc.get("status") != "pass":
            issues.append(f"{label}_status_not_pass")
        if doc.get("v7_coverage_available") != "yes":
            issues.append(f"{label}_v7_coverage_not_yes")
        if doc.get("sw2021_l2_universe_coverage") != "pass":
            issues.append(f"{label}_sw2021_l2_universe_not_pass")
        if _as_int(doc.get("prospective_holdout_rows_evaluated"), 0) != 0:
            issues.append(f"{label}_prospective_holdout_rows_evaluated_not_zero")
        holdout_issues.extend(holdout_consumption_issues(label, doc))
    if fold_plan.get("status") != "pass":
        issues.append("fold_plan_status_not_pass")
    if _as_int(fold_plan.get("purge_violation_count"), -1) != 0:
        issues.append("fold_plan_purge_violation_count_not_zero")
    if _as_int(fold_plan.get("embargo_violation_count"), -1) != 0:
        issues.append("fold_plan_embargo_violation_count_not_zero")

    wp5_leakage_total = _total_from_counts(
        calibration_readiness.get("leakage_violation_counts", {}),
        "leakage_violation_count_total",
    )
    wp5_boundary_total = _total_from_counts(
        calibration_readiness.get("calibration_boundary_violation_counts", {}),
        "calibration_boundary_violation_count_total",
    )
    if wp5_leakage_total != 0:
        issues.append("wp5_leakage_violation_count_not_zero")
    if wp5_boundary_total != 0:
        issues.append("wp5_calibration_boundary_violation_count_not_zero")
    flags = calibration_readiness.get("boundary_flags", {})
    if flags.get("probability_calibration") != "yes":
        issues.append("wp5_probability_calibration_not_yes")
    if flags.get("readiness_assigned") != "yes_development_only":
        issues.append("wp5_readiness_assigned_not_development_only")
    if flags.get("trading_or_decision_output") != "no":
        issues.append("wp5_trading_or_decision_output_not_no")
    if flags.get("holdout_consumed") != "no":
        issues.append("wp5_holdout_consumed_not_no")
    if calibration_readiness.get("fixed_threshold_mainline_status") != "unchanged_primary_target":
        issues.append("wp5_fixed_threshold_mainline_not_unchanged")

    expected_paths = {str(doc.get("source_db_path")) for _, doc in docs if doc.get("source_db_path")}
    resolved_safe = _safe_path(db_path)
    if not os.environ.get("STAGE03V_V7_DB") and expected_paths and resolved_safe not in expected_paths:
        issues.append("resolved_db_path_does_not_match_accepted_stage03v_artifacts")
    if holdout_issues:
        issues.extend(issue for issue in holdout_issues if issue not in issues)
        return "blocked_holdout_consumed", issues
    return ("pass", []) if not issues else ("blocked_wp5_not_ready", issues)


def _coverage_support(row: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    rows = _as_int(row.get("evaluation_row_count"), 0)
    positives = _as_int(row.get("positive_event_count"), 0)
    if rows >= _as_int(policy.get("min_evaluation_rows_for_pass_candidate"), 500) and positives >= _as_int(
        policy.get("min_positive_events_for_pass_candidate"),
        10,
    ):
        return "pass"
    if rows >= _as_int(policy.get("min_evaluation_rows_for_watchlist"), 100) and positives >= _as_int(
        policy.get("min_positive_events_for_watchlist"),
        3,
    ):
        return "watch"
    return "insufficient"


def _calibration_stability(row: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    ece = _as_float(row.get("mean_expected_calibration_error"))
    if ece is None:
        return "insufficient"
    if ece <= float(policy.get("max_ece_for_pass_candidate", 0.05)):
        return "pass"
    if ece <= float(policy.get("max_ece_for_watchlist", 0.10)):
        return "watch"
    return "watch"


def _fold_stability(row: Mapping[str, Any]) -> str:
    folds = _as_int(row.get("fold_count"), 0)
    if folds >= 3:
        return "pass"
    if folds >= 2:
        return "watch"
    return "insufficient"


def _clustered_uncertainty(row: Mapping[str, Any], policy: Mapping[str, Any]) -> str:
    width = _as_float(row.get("clustered_uncertainty_width"))
    if width is None:
        return "insufficient"
    if width <= float(policy.get("max_cluster_width_for_pass_candidate", 0.25)):
        return "pass"
    if width <= float(policy.get("max_cluster_width_for_watchlist", 0.50)):
        return "watch"
    return "watch"


def _lead_time(row: Mapping[str, Any]) -> str:
    horizon = _as_int(row.get("horizon"), 0)
    positives = _as_int(row.get("positive_event_count"), 0)
    if horizon >= 5 and positives >= 10:
        return "pass"
    if horizon >= 3 and positives >= 3:
        return "watch"
    return "insufficient"


def _event_capture(row: Mapping[str, Any]) -> str:
    positives = _as_int(row.get("positive_event_count"), 0)
    eval_rows = _as_int(row.get("evaluation_row_count"), 0)
    base_rate = _safe_div(positives, eval_rows)
    if base_rate is None or positives <= 0:
        return "insufficient"
    if positives >= 10 and base_rate >= 0.02:
        return "pass"
    if positives >= 3:
        return "watch"
    return "insufficient"


def _false_alarm_status(row: Mapping[str, Any]) -> str:
    positives = _as_int(row.get("positive_event_count"), 0)
    negatives = _as_int(row.get("negative_event_count"), 0)
    if positives <= 0:
        return "insufficient"
    ratio = _safe_div(negatives, positives)
    if ratio is None:
        return "insufficient"
    if ratio <= 40:
        return "pass"
    if ratio <= 120:
        return "watch"
    return "watch"


def _baseline_comparison(row: Mapping[str, Any], baseline_report: Mapping[str, Any]) -> str:
    baseline = baseline_report.get("metric_summary", {})
    auc = _as_float(row.get("mean_auc"))
    ap = _as_float(row.get("mean_average_precision"))
    mean_auc = _as_float(baseline.get("mean_roc_auc"))
    mean_ap = _as_float(baseline.get("mean_average_precision"))
    if auc is None and ap is None:
        return "insufficient"
    if (auc is not None and mean_auc is not None and auc >= mean_auc) or (
        ap is not None and mean_ap is not None and ap >= mean_ap
    ):
        return "pass"
    return "watch"


def _known_anomaly_handling(vol_report: Mapping[str, Any]) -> str:
    sanity = str(vol_report.get("baseline_sanity_status", "unknown"))
    metric_summary = vol_report.get("metric_sanity_summary", {})
    fail_count = _as_int(metric_summary.get("metric_sanity_fail_count"), 0)
    covered = bool(metric_summary.get("known_high_auc_diagnostic_covered"))
    if fail_count == 0 and covered:
        return "pass"
    if sanity in {"warning", "pass"}:
        return "watch"
    return "insufficient"


def summarize_calibration_bins(bin_rows: pd.DataFrame) -> dict[tuple[Any, ...], dict[str, Any]]:
    summaries: dict[tuple[Any, ...], dict[str, Any]] = {}
    if bin_rows.empty:
        return summaries
    work = bin_rows.copy()
    for column in ["row_count", "positive_event_count", "observed_event_rate", "bin_high"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    for _, group in work.groupby(KEY_COLUMNS, sort=False, dropna=False):
        key = _normalise_key(group.iloc[0].to_dict())
        non_empty = group[group["row_count"].fillna(0).gt(0)].copy()
        if non_empty.empty:
            summaries[key] = {
                "event_lift_top_bin": None,
                "top_bin_row_count": 0,
                "top_bin_observed_event_rate": None,
                "quantile_lift_status": "insufficient",
            }
            continue
        top = non_empty.sort_values(["bin_high", "bin_index"], ascending=[False, False]).iloc[0]
        total_rows = float(non_empty["row_count"].sum())
        total_pos = float(non_empty["positive_event_count"].sum())
        base_rate = _safe_div(total_pos, total_rows)
        top_rate = _as_float(top.get("observed_event_rate"))
        lift = None if base_rate in {None, 0.0} or top_rate is None else float(top_rate / base_rate)
        summaries[key] = {
            "event_lift_top_bin": lift,
            "top_bin_row_count": _as_int(top.get("row_count"), 0),
            "top_bin_observed_event_rate": top_rate,
            "quantile_lift_status": "insufficient",
        }
    return summaries


def summarize_clustered_inference(cluster_rows: pd.DataFrame) -> list[dict[str, Any]]:
    if cluster_rows.empty:
        return []
    work = cluster_rows.copy()
    for column in ["cluster_count", "min_cluster_size", "max_cluster_size", "confidence_interval_low", "confidence_interval_high"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    rows: list[dict[str, Any]] = []
    for _, group in work.groupby(KEY_COLUMNS, sort=False, dropna=False):
        base = {column: group.iloc[0].get(column) for column in KEY_COLUMNS}
        by_type = {str(row.get("cluster_type")): row for row in group.to_dict(orient="records")}
        entity = by_type.get("entity_id", {})
        date = by_type.get("trade_date", {})
        low = _as_float(date.get("confidence_interval_low"))
        high = _as_float(date.get("confidence_interval_high"))
        rows.append(
            {
                **base,
                "entity_cluster_count": _as_int(entity.get("cluster_count"), 0),
                "entity_min_cluster_size": _as_int(entity.get("min_cluster_size"), 0),
                "entity_max_cluster_size": _as_int(entity.get("max_cluster_size"), 0),
                "entity_uncertainty_status": entity.get("uncertainty_status", "missing"),
                "date_cluster_count": _as_int(date.get("cluster_count"), 0),
                "date_min_cluster_size": _as_int(date.get("min_cluster_size"), 0),
                "date_max_cluster_size": _as_int(date.get("max_cluster_size"), 0),
                "date_uncertainty_status": date.get("uncertainty_status", "missing"),
                "date_uncertainty_width": None if low is None or high is None else float(high - low),
            }
        )
    return rows


def _cluster_statuses(row: Mapping[str, Any]) -> tuple[str, str]:
    entity_count = _as_int(row.get("entity_cluster_count"), 0)
    date_count = _as_int(row.get("date_cluster_count"), 0)
    entity_status = "pass" if entity_count >= 30 else ("watch" if entity_count >= 5 else "insufficient")
    date_status = "pass" if date_count >= 3 else ("watch" if date_count >= 2 else "insufficient")
    if str(row.get("entity_uncertainty_status")) not in {"pass", "missing"}:
        entity_status = "watch"
    if str(row.get("date_uncertainty_status")) not in {"pass", "missing"}:
        date_status = "watch"
    return entity_status, date_status


def _threshold_sensitivity(
    row: Mapping[str, Any],
    readiness_rows: pd.DataFrame,
) -> str:
    if readiness_rows.empty:
        return "insufficient"
    subset = readiness_rows[
        readiness_rows["asof_mode"].astype(str).eq(str(row.get("asof_mode")))
        & readiness_rows["horizon"].astype(int).eq(int(row.get("horizon")))
        & readiness_rows["target_usage"].astype(str).eq(str(row.get("target_usage")))
        & readiness_rows["calibration_method"].astype(str).eq(str(row.get("calibration_method")))
    ]
    if subset["threshold_value"].nunique() >= 3:
        return "pass"
    if subset["threshold_value"].nunique() >= 2:
        return "watch"
    return "insufficient"


def _validation_status(
    *,
    row: Mapping[str, Any],
    dimension_counts: Mapping[str, int],
    leakage_total: int,
    boundary_total: int,
) -> tuple[str, str]:
    readiness = str(row.get("readiness_category"))
    if leakage_total or boundary_total or readiness == "blocked_by_leakage":
        return "blocked_by_boundary_or_leakage", "boundary_or_leakage_block"
    if str(row.get("target_usage")) != "eligible" or readiness == "research_only":
        return "research_only_evidence", "diagnostic_or_research_only_input"
    if readiness == "insufficient_data":
        return "insufficient_validation_support", "insufficient_wp5_support"
    if readiness == "baseline_only_candidate":
        return "research_only_evidence", "uncalibrated_baseline_reference_only"
    passes = _as_int(dimension_counts.get("pass"), 0)
    insufficient = _as_int(dimension_counts.get("insufficient"), 0)
    if readiness == "usable_probability_candidate" and passes >= 8 and insufficient == 0:
        return "validation_pass_candidate", "development_validation_dimensions_pass"
    if readiness in {"usable_probability_candidate", "ordinal_only_candidate"} and passes >= 5:
        return "validation_watchlist", "development_validation_watchlist"
    return "insufficient_validation_support", "validation_dimensions_insufficient"


def _downshift_tier(validation_status: str) -> str:
    if validation_status == "validation_pass_candidate":
        return "research_downshift_candidate"
    if validation_status == "validation_watchlist":
        return "research_downshift_watch"
    if validation_status == "blocked_by_boundary_or_leakage":
        return "research_downshift_blocked"
    return "research_downshift_insufficient"


def build_validation_metrics(
    *,
    readiness_rows: pd.DataFrame,
    fold_rows: pd.DataFrame,
    bin_rows: pd.DataFrame,
    clustered_rows: pd.DataFrame,
    baseline_report: Mapping[str, Any],
    vol_report: Mapping[str, Any],
    policy: Mapping[str, Any],
    leakage_total: int,
    boundary_total: int,
) -> dict[str, Any]:
    if readiness_rows.empty:
        return {"metrics": [], "clustered_summary": [], "audit_sample": []}
    work = readiness_rows.copy()
    for column in ["horizon", "threshold_value", "evaluation_row_count", "positive_event_count", "negative_event_count", "fold_count"]:
        work[column] = pd.to_numeric(work[column], errors="coerce")
    bin_summary = summarize_calibration_bins(bin_rows)
    clustered_summary = summarize_clustered_inference(clustered_rows)
    clustered_by_key = {_normalise_key(row): row for row in clustered_summary}
    rows: list[dict[str, Any]] = []
    for source_row in work.to_dict(orient="records"):
        key = _normalise_key(source_row)
        bin_info = bin_summary.get(key, {})
        cluster_info = clustered_by_key.get(key, {})
        entity_status, date_status = _cluster_statuses(cluster_info)
        event_lift = _as_float(bin_info.get("event_lift_top_bin"))
        top_bin_rows = _as_int(bin_info.get("top_bin_row_count"), 0)
        if event_lift is None or top_bin_rows < _as_int(policy.get("min_top_bin_row_count"), 10):
            quantile_status = "insufficient"
        elif event_lift >= float(policy.get("min_event_lift_for_pass_candidate", 1.20)):
            quantile_status = "pass"
        elif event_lift >= float(policy.get("min_event_lift_for_watchlist", 1.00)):
            quantile_status = "watch"
        else:
            quantile_status = "watch"
        statuses = {
            "coverage_support_status": _coverage_support(source_row, policy),
            "calibration_stability_status": _calibration_stability(source_row, policy),
            "fold_stability_status": _fold_stability(source_row),
            "clustered_uncertainty_status": _clustered_uncertainty(source_row, policy),
            "lead_time_status": _lead_time(source_row),
            "event_capture_status": _event_capture(source_row),
            "false_alarm_concentration_status": _false_alarm_status(source_row),
            "quantile_lift_status": quantile_status,
            "threshold_sensitivity_status": _threshold_sensitivity(source_row, work),
            "entity_concentration_status": entity_status,
            "calendar_date_concentration_status": date_status,
            "baseline_comparison_status": _baseline_comparison(source_row, baseline_report),
            "known_anomaly_handling_status": _known_anomaly_handling(vol_report),
        }
        dimension_counts = Counter(statuses.values())
        validation_status, reason = _validation_status(
            row=source_row,
            dimension_counts=dimension_counts,
            leakage_total=leakage_total,
            boundary_total=boundary_total,
        )
        rows.append(
            {
                **{column: source_row.get(column) for column in KEY_COLUMNS},
                "horizon": _as_int(source_row.get("horizon"), 0),
                "threshold_value": _as_float(source_row.get("threshold_value")),
                "readiness_category": source_row.get("readiness_category"),
                "validation_status": validation_status,
                "downshift_research_tier": _downshift_tier(validation_status),
                "research_only": "yes",
                "not_trading_output": "yes",
                "no_position_sizing": "yes",
                "no_buy_sell_recommendation": "yes",
                "no_execution_instruction": "yes",
                "evaluation_row_count": _as_int(source_row.get("evaluation_row_count"), 0),
                "positive_event_count": _as_int(source_row.get("positive_event_count"), 0),
                "negative_event_count": _as_int(source_row.get("negative_event_count"), 0),
                "event_base_rate": _safe_div(
                    _as_int(source_row.get("positive_event_count"), 0),
                    _as_int(source_row.get("evaluation_row_count"), 0),
                ),
                "fold_count": _as_int(source_row.get("fold_count"), 0),
                "mean_brier_score": _as_float(source_row.get("mean_brier_score")),
                "mean_log_loss": _as_float(source_row.get("mean_log_loss")),
                "mean_expected_calibration_error": _as_float(source_row.get("mean_expected_calibration_error")),
                "max_expected_calibration_error": _as_float(source_row.get("max_expected_calibration_error")),
                "mean_auc": _as_float(source_row.get("mean_auc")),
                "mean_average_precision": _as_float(source_row.get("mean_average_precision")),
                "clustered_uncertainty_width": _as_float(source_row.get("clustered_uncertainty_width")),
                "event_lift_top_bin": event_lift,
                "top_bin_row_count": top_bin_rows,
                "top_bin_observed_event_rate": _as_float(bin_info.get("top_bin_observed_event_rate")),
                **statuses,
                "validation_dimension_pass_count": int(dimension_counts.get("pass", 0)),
                "validation_dimension_watch_count": int(dimension_counts.get("watch", 0)),
                "validation_dimension_insufficient_count": int(dimension_counts.get("insufficient", 0)),
                "validation_reason": reason,
            }
        )
    rows.sort(key=lambda item: (str(item["validation_status"]), str(item["asof_mode"]), int(item["horizon"]), float(item["threshold_value"] or 0.0), str(item["calibration_method"])))
    cap = _as_int(policy.get("audit_sample_cap"), 500)
    audit_rows = [{column: row.get(column) for column in AUDIT_COLUMNS} for row in rows[:cap]]
    _ = fold_rows  # fold rows are read for contract presence and future protocol extension only.
    return {"metrics": rows, "clustered_summary": clustered_summary, "audit_sample": audit_rows}


def _counts(rows: Sequence[Mapping[str, Any]], column: str, allowed: Sequence[str]) -> dict[str, int]:
    counter = Counter(str(row.get(column)) for row in rows)
    return {key: int(counter.get(key, 0)) for key in allowed}


def _numeric_summary(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> dict[str, Any]:
    frame = pd.DataFrame(list(rows))
    if frame.empty:
        return {"row_count": 0}
    out: dict[str, Any] = {"row_count": int(len(frame))}
    for column in columns:
        values = pd.to_numeric(frame.get(column), errors="coerce").dropna()
        out[f"mean_{column}"] = float(values.mean()) if not values.empty else None
        out[f"min_{column}"] = float(values.min()) if not values.empty else None
        out[f"max_{column}"] = float(values.max()) if not values.empty else None
    return out


def _status_summary(rows: Sequence[Mapping[str, Any]], column: str) -> dict[str, int]:
    return dict(Counter(str(row.get(column)) for row in rows))


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
    wp5_status: str | None = None,
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
        "wp5_calibration_readiness_status": wp5_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "fold_plan_status": "blocked",
        "policy_status": "blocked",
        "validation_protocol_status": "blocked",
        "historical_development_only": "yes",
        "prospective_holdout_rows_evaluated": 0,
        "readiness_rows_evaluated": 0,
        "candidate_rows_evaluated": 0,
        "validation_status_counts": _counts([], "validation_status", VALIDATION_STATUSES),
        "downshift_tier_counts": _counts([], "downshift_research_tier", DOWNSHIFT_TIERS),
        "usable_probability_candidate_count": 0,
        "ordinal_only_candidate_count": 0,
        "baseline_only_candidate_count": 0,
        "research_only_count": 0,
        "validation_pass_candidate_count": 0,
        "validation_watchlist_count": 0,
        "research_only_evidence_count": 0,
        "insufficient_validation_support_count": 0,
        "blocked_by_boundary_or_leakage_count": 0,
        "risk_validation_metrics_path": None,
        "downshift_candidate_matrix_path": None,
        "clustered_summary_path": None,
        "audit_sample_path": None,
        "wp7_manifest_path": None,
        "metric_summary": {},
        "lead_time_summary": {},
        "event_capture_summary": {},
        "false_alarm_summary": {},
        "clustered_concentration_summary": {},
        "baseline_comparison_summary": {},
        "leakage_violation_counts": dict(LEAKAGE_ZERO_COUNTS),
        "validation_boundary_violation_counts": dict(VALIDATION_BOUNDARY_ZERO_COUNTS),
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": list(reasons),
        "remaining_risks": [],
    }


def _write_protocol(path: Path | str, policy: Mapping[str, Any], report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP6 Risk Validation Protocol",
        "",
        f"- index_id: {INDEX_ID}",
        f"- status: {report.get('validation_protocol_status')}",
        f"- information_cutoff_date: {policy.get('information_cutoff_date')}",
        f"- holdout_start: {policy.get('holdout_start')}",
        f"- historical_development_only: {policy.get('historical_development_only')}",
        f"- final_holdout_policy: {policy.get('final_holdout_policy')}",
        f"- primary_target_family: {policy.get('primary_target_family')}",
        f"- vol_scaled_candidate_policy: {policy.get('vol_scaled_candidate_policy')}",
        "",
        "## Validation Dimensions",
        "",
    ]
    for item in [
        "coverage and support",
        "calibration stability",
        "fold stability",
        "clustered uncertainty",
        "lead-time and event capture",
        "false alarm concentration",
        "drawdown/event lift by score bin",
        "threshold sensitivity",
        "entity concentration",
        "calendar-date concentration",
        "baseline comparison",
        "known WP3/WP3.5 anomaly handling",
    ]:
        lines.append(f"- {item}")
    lines.extend(["", "## Validation Statuses", ""])
    for item in policy.get("validation_statuses", []):
        lines.append(f"- {item}")
    lines.extend(["", "## Downshift Research Tiers", ""])
    for item in policy.get("downshift_research_tiers", []):
        lines.append(f"- {item}: research_only=yes; not_trading_output=yes")
    lines.extend(["", "## Boundary Flags", ""])
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP6 Risk Validation Report",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- historical_development_only: {report.get('historical_development_only')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- readiness_rows_evaluated: {report.get('readiness_rows_evaluated')}",
        f"- candidate_rows_evaluated: {report.get('candidate_rows_evaluated')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Validation Status Counts",
        "",
    ]
    for key, value in report.get("validation_status_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Downshift Tier Counts", ""])
    for key, value in report.get("downshift_tier_counts", {}).items():
        lines.append(f"- {key}: {value}")
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


def _write_downshift_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP6 Downshift Research Report",
        "",
        f"- index_id: {INDEX_ID}",
        f"- status: {report.get('status')}",
        f"- research_only: {report.get('research_only')}",
        f"- not_trading_output: {report.get('not_trading_output')}",
        f"- no_position_sizing: {report.get('no_position_sizing')}",
        f"- no_buy_sell_recommendation: {report.get('no_buy_sell_recommendation')}",
        f"- no_execution_instruction: {report.get('no_execution_instruction')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        "",
        "## Tier Counts",
        "",
    ]
    for key, value in report.get("downshift_tier_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Interpretation Boundary", ""])
    lines.append("- These tiers summarize historical-development evidence quality only.")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_blocked_outputs(
    *,
    report: Mapping[str, Any],
    protocol_output: Path,
    output: Path,
    summary_json: Path,
    metrics: Path,
    downshift_report: Path,
    downshift_json: Path,
    candidate_matrix: Path,
    clustered_summary: Path,
    audit_sample: Path,
    wp7_manifest: Path,
    policy_doc: Mapping[str, Any] | None = None,
) -> None:
    policy = policy_doc or default_policy()
    _write_protocol(protocol_output, policy, report)
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(metrics, [], METRIC_COLUMNS)
    _write_csv(candidate_matrix, [], METRIC_COLUMNS)
    _write_csv(clustered_summary, [], CLUSTERED_SUMMARY_COLUMNS)
    _write_csv(audit_sample, [], AUDIT_COLUMNS)
    downshift = _downshift_report(report, [])
    _write_downshift_markdown(downshift_report, downshift)
    _write_json(downshift_json, downshift)
    _write_wp7_manifest(wp7_manifest, report, accepted_artifacts=[], wp6_outputs=[], status="blocked")


def _downshift_report(report: Mapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": "stage03v_downshift_research_v1",
        "status": report.get("status"),
        "source_db_path": report.get("source_db_path"),
        "historical_development_only": "yes",
        "prospective_holdout_rows_evaluated": report.get("prospective_holdout_rows_evaluated", 0),
        "research_only": "yes",
        "not_trading_output": "yes",
        "no_position_sizing": "yes",
        "no_buy_sell_recommendation": "yes",
        "no_execution_instruction": "yes",
        "downshift_tier_counts": report.get("downshift_tier_counts", _counts(rows, "downshift_research_tier", DOWNSHIFT_TIERS)),
        "candidate_matrix_path": report.get("downshift_candidate_matrix_path"),
        "validation_status_counts": report.get("validation_status_counts"),
        "boundary_flags": report.get("boundary_flags", BOUNDARY_FLAGS),
        "remaining_risks": report.get("remaining_risks", []),
        "created_at": report.get("created_at", _now_iso()),
    }


def _write_wp7_manifest(
    path: Path | str,
    report: Mapping[str, Any],
    *,
    accepted_artifacts: Sequence[str],
    wp6_outputs: Sequence[str],
    status: str = "prepared_for_wp7",
) -> None:
    manifest = {
        "index_id": INDEX_ID,
        "manifest_version": "stage03v_wp7_final_gate_input_manifest_v1",
        "status": status,
        "wp7_final_gate_executed": "no",
        "final_gate_verdict": "not_run",
        "source_db_path": report.get("source_db_path"),
        "v7_coverage_available": report.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": report.get("sw2021_l2_universe_coverage"),
        "prospective_holdout_rows_evaluated": report.get("prospective_holdout_rows_evaluated", 0),
        "historical_development_only": "yes",
        "accepted_input_artifacts": list(accepted_artifacts),
        "wp6_output_artifacts": list(wp6_outputs),
        "validation_status_counts": report.get("validation_status_counts"),
        "downshift_tier_counts": report.get("downshift_tier_counts"),
        "boundary_flags": report.get("boundary_flags", BOUNDARY_FLAGS),
        "created_at": report.get("created_at", _now_iso()),
    }
    _write_json(path, manifest)


def build_risk_validation_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    baseline_diagnostics: Path | str = DEFAULT_BASELINE_DIAGNOSTICS,
    vol_scaled_sanity: Path | str = DEFAULT_VOL_SCALED_SANITY,
    logistic_hazard: Path | str = DEFAULT_LOGISTIC_HAZARD,
    calibration_readiness: Path | str = DEFAULT_CALIBRATION_READINESS,
    calibration_fold_metrics: Path | str = DEFAULT_CALIBRATION_FOLD_METRICS,
    calibration_slice_metrics: Path | str = DEFAULT_CALIBRATION_SLICE_METRICS,
    calibration_bins: Path | str = DEFAULT_CALIBRATION_BINS,
    clustered_inference: Path | str = DEFAULT_CLUSTERED_INFERENCE,
    readiness_matrix: Path | str = DEFAULT_READINESS_MATRIX,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    policy: Path | str = DEFAULT_POLICY,
    protocol_output: Path | str = DEFAULT_PROTOCOL_OUTPUT,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    metrics: Path | str = DEFAULT_METRICS,
    downshift_report: Path | str = DEFAULT_DOWNSHIFT_REPORT,
    downshift_json: Path | str = DEFAULT_DOWNSHIFT_JSON,
    candidate_matrix: Path | str = DEFAULT_CANDIDATE_MATRIX,
    clustered_summary: Path | str = DEFAULT_CLUSTERED_SUMMARY,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    wp7_manifest: Path | str = DEFAULT_WP7_MANIFEST,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP6 risk validation is no-fetch only")
    resolved_db = resolve_v7_db_path(db_path)
    paths = {
        "protocol_output": Path(protocol_output),
        "output": Path(output),
        "summary_json": Path(summary_json),
        "metrics": Path(metrics),
        "downshift_report": Path(downshift_report),
        "downshift_json": Path(downshift_json),
        "candidate_matrix": Path(candidate_matrix),
        "clustered_summary": Path(clustered_summary),
        "audit_sample": Path(audit_sample),
        "wp7_manifest": Path(wp7_manifest),
    }

    policy_doc: dict[str, Any] | None = None
    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
        full_audit = _load_json(full_target_audit)
        baseline_report = _load_json(baseline_diagnostics)
        vol_report = _load_json(vol_scaled_sanity)
        logistic_report = _load_json(logistic_hazard)
        calibration_report = _load_json(calibration_readiness)
        fold_doc = _load_json(fold_plan)
        policy_doc = _load_machine_config(policy)
    except FileNotFoundError as exc:
        report = _blocked_report(status="blocked_missing_input", db_path=resolved_db, reasons=[f"missing input: {exc.filename}"])
        _write_blocked_outputs(report=report, policy_doc=policy_doc, **paths)
        return report

    policy_issues = validate_policy(policy_doc)
    if policy_issues:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            reasons=policy_issues,
            wp1_status=_status(support),
            wp2_status=_status(controls),
            wp2_1_status=_status(full_audit),
            wp3_status=_status(baseline_report),
            wp3_5_status=_status(vol_report),
            wp4_status=_status(logistic_report),
            wp5_status=_status(calibration_report),
        )
        _write_blocked_outputs(report=report, policy_doc=policy_doc, **paths)
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            wp1_status=_status(support),
            wp2_status=_status(controls),
            wp2_1_status=_status(full_audit),
            wp3_status=_status(baseline_report),
            wp3_5_status=_status(vol_report),
            wp4_status=_status(logistic_report),
            wp5_status=_status(calibration_report),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["sw2021_l2_universe_coverage"] = v7.coverage.get("sw2021_l2_universe_coverage", "missing")
        _write_blocked_outputs(report=report, policy_doc=policy_doc, **paths)
        return report

    precondition_status, precondition_issues = validate_wp6_preconditions(
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        baseline_diagnostics=baseline_report,
        vol_scaled_sanity=vol_report,
        logistic_hazard=logistic_report,
        calibration_readiness=calibration_report,
        fold_plan=fold_doc,
        db_path=resolved_db,
    )
    if precondition_status != "pass":
        report = _blocked_report(
            status=precondition_status,
            db_path=resolved_db,
            reasons=precondition_issues,
            wp1_status=_status(support),
            wp2_status=_status(controls),
            wp2_1_status=_status(full_audit),
            wp3_status=_status(baseline_report),
            wp3_5_status=_status(vol_report),
            wp4_status=_status(logistic_report),
            wp5_status=_status(calibration_report),
        )
        _write_blocked_outputs(report=report, policy_doc=policy_doc, **paths)
        return report

    target_universe_status = "missing"
    try:
        target_universe_doc = _load_machine_config(target_universe)
        source = target_universe_doc.get("source", {})
        target_universe_status = (
            "pass"
            if source.get("v7_coverage_available") == "yes"
            and source.get("taxonomy_source_status") == "verified_sw2021_l2_tushare_classify"
            else "partial"
        )
    except FileNotFoundError:
        target_universe_status = "missing"

    readiness_rows = pd.read_csv(readiness_matrix)
    fold_rows = pd.read_csv(calibration_fold_metrics)
    _ = pd.read_csv(calibration_slice_metrics)
    bin_rows = pd.read_csv(calibration_bins)
    cluster_rows = pd.read_csv(clustered_inference)
    leakage_counts = dict(LEAKAGE_ZERO_COUNTS)
    leakage_counts.update({key: _as_int(value, 0) for key, value in calibration_report.get("leakage_violation_counts", {}).items()})
    leakage_counts["leakage_violation_count_total"] = _total_from_counts(leakage_counts, "leakage_violation_count_total")
    validation_boundary_counts = dict(VALIDATION_BOUNDARY_ZERO_COUNTS)
    validation_boundary_counts["wp5_calibration_boundary_violation_count_total"] = _total_from_counts(
        calibration_report.get("calibration_boundary_violation_counts", {}),
        "calibration_boundary_violation_count_total",
    )
    validation_boundary_counts["validation_boundary_violation_count_total"] = int(
        sum(value for key, value in validation_boundary_counts.items() if key != "validation_boundary_violation_count_total")
    )
    leakage_total = _as_int(leakage_counts.get("leakage_violation_count_total"), 0)
    boundary_total = _as_int(validation_boundary_counts.get("validation_boundary_violation_count_total"), 0)

    evidence = build_validation_metrics(
        readiness_rows=readiness_rows,
        fold_rows=fold_rows,
        bin_rows=bin_rows,
        clustered_rows=cluster_rows,
        baseline_report=baseline_report,
        vol_report=vol_report,
        policy=policy_doc,
        leakage_total=leakage_total,
        boundary_total=boundary_total,
    )
    metrics_rows = evidence["metrics"]
    clustered_rows_out = evidence["clustered_summary"]
    audit_rows = evidence["audit_sample"]
    _write_csv(paths["metrics"], metrics_rows, METRIC_COLUMNS)
    _write_csv(paths["candidate_matrix"], metrics_rows, METRIC_COLUMNS)
    _write_csv(paths["clustered_summary"], clustered_rows_out, CLUSTERED_SUMMARY_COLUMNS)
    _write_csv(paths["audit_sample"], audit_rows, AUDIT_COLUMNS)

    validation_counts = _counts(metrics_rows, "validation_status", VALIDATION_STATUSES)
    downshift_counts = _counts(metrics_rows, "downshift_research_tier", DOWNSHIFT_TIERS)
    readiness_counts = _counts(readiness_rows.to_dict(orient="records"), "readiness_category", READINESS_CATEGORIES)
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
        "wp5_calibration_readiness_status": calibration_report.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": target_universe_status,
        "fold_plan_status": fold_doc.get("status"),
        "policy_status": "pass",
        "validation_protocol_status": "pass",
        "historical_development_only": "yes",
        "prospective_holdout_rows_evaluated": 0,
        "readiness_rows_evaluated": int(len(readiness_rows)),
        "candidate_rows_evaluated": int(len(metrics_rows)),
        "validation_status_counts": validation_counts,
        "downshift_tier_counts": downshift_counts,
        "usable_probability_candidate_count": readiness_counts.get("usable_probability_candidate", 0),
        "ordinal_only_candidate_count": readiness_counts.get("ordinal_only_candidate", 0),
        "baseline_only_candidate_count": readiness_counts.get("baseline_only_candidate", 0),
        "research_only_count": readiness_counts.get("research_only", 0),
        "validation_pass_candidate_count": validation_counts.get("validation_pass_candidate", 0),
        "validation_watchlist_count": validation_counts.get("validation_watchlist", 0),
        "research_only_evidence_count": validation_counts.get("research_only_evidence", 0),
        "insufficient_validation_support_count": validation_counts.get("insufficient_validation_support", 0),
        "blocked_by_boundary_or_leakage_count": validation_counts.get("blocked_by_boundary_or_leakage", 0),
        "risk_validation_metrics_path": _safe_path(paths["metrics"]),
        "downshift_candidate_matrix_path": _safe_path(paths["candidate_matrix"]),
        "clustered_summary_path": _safe_path(paths["clustered_summary"]),
        "audit_sample_path": _safe_path(paths["audit_sample"]),
        "wp7_manifest_path": _safe_path(paths["wp7_manifest"]),
        "metric_summary": _numeric_summary(
            metrics_rows,
            [
                "mean_brier_score",
                "mean_log_loss",
                "mean_expected_calibration_error",
                "mean_auc",
                "mean_average_precision",
                "event_lift_top_bin",
            ],
        ),
        "lead_time_summary": _status_summary(metrics_rows, "lead_time_status"),
        "event_capture_summary": _status_summary(metrics_rows, "event_capture_status"),
        "false_alarm_summary": _status_summary(metrics_rows, "false_alarm_concentration_status"),
        "clustered_concentration_summary": {
            "entity": _status_summary(metrics_rows, "entity_concentration_status"),
            "calendar_date": _status_summary(metrics_rows, "calendar_date_concentration_status"),
        },
        "baseline_comparison_summary": _status_summary(metrics_rows, "baseline_comparison_status"),
        "leakage_violation_counts": leakage_counts,
        "validation_boundary_violation_counts": validation_boundary_counts,
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": [],
        "remaining_risks": [
            "WP6 validates historical-development evidence only; WP7 must run the final gate before any Stage03V1 acceptance claim.",
            "Downshift tiers are research-only evidence labels and are not trading, sizing, portfolio, or execution outputs.",
            "Volatility-scaled candidates remain tracked references and do not replace the fixed-threshold Stage03V1 target family.",
        ],
    }
    if leakage_total or boundary_total:
        report["status"] = "fail"
        report["blocking_reasons"] = ["validation_boundary_or_leakage_violation_detected"]
    elif not metrics_rows:
        report["status"] = "partial_insufficient_data"
        report["blocking_reasons"] = ["no readiness rows available for validation"]
    else:
        report["status"] = "pass"
    holdout_issues = holdout_consumption_issues("wp6_report", report)
    if holdout_issues:
        report["status"] = "blocked_holdout_consumed"
        report["blocking_reasons"] = holdout_issues
    report["ci_gate_status"] = "pass" if report["status"] == "pass" else report["status"]
    _write_protocol(paths["protocol_output"], policy_doc, report)
    _write_markdown(paths["output"], report)
    _write_json(paths["summary_json"], report)
    downshift = _downshift_report(report, metrics_rows)
    _write_downshift_markdown(paths["downshift_report"], downshift)
    _write_json(paths["downshift_json"], downshift)
    accepted_artifacts = [
        _safe_path(target_support),
        _safe_path(target_universe),
        _safe_path(target_controls),
        _safe_path(full_target_audit),
        _safe_path(baseline_diagnostics),
        _safe_path(vol_scaled_sanity),
        _safe_path(logistic_hazard),
        _safe_path(calibration_readiness),
        _safe_path(calibration_fold_metrics),
        _safe_path(calibration_slice_metrics),
        _safe_path(calibration_bins),
        _safe_path(clustered_inference),
        _safe_path(readiness_matrix),
        _safe_path(fold_plan),
    ]
    wp6_outputs = [
        _safe_path(paths["protocol_output"]),
        _safe_path(paths["output"]),
        _safe_path(paths["summary_json"]),
        _safe_path(paths["metrics"]),
        _safe_path(paths["downshift_report"]),
        _safe_path(paths["downshift_json"]),
        _safe_path(paths["candidate_matrix"]),
        _safe_path(paths["clustered_summary"]),
        _safe_path(paths["audit_sample"]),
        _safe_path(paths["wp7_manifest"]),
    ]
    _write_wp7_manifest(
        paths["wp7_manifest"],
        report,
        accepted_artifacts=[str(item) for item in accepted_artifacts if item],
        wp6_outputs=[str(item) for item in wp6_outputs if item],
    )
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
    parser.add_argument("--calibration-readiness", type=Path, default=DEFAULT_CALIBRATION_READINESS)
    parser.add_argument("--calibration-fold-metrics", type=Path, default=DEFAULT_CALIBRATION_FOLD_METRICS)
    parser.add_argument("--calibration-slice-metrics", type=Path, default=DEFAULT_CALIBRATION_SLICE_METRICS)
    parser.add_argument("--calibration-bins", type=Path, default=DEFAULT_CALIBRATION_BINS)
    parser.add_argument("--clustered-inference", type=Path, default=DEFAULT_CLUSTERED_INFERENCE)
    parser.add_argument("--readiness-matrix", type=Path, default=DEFAULT_READINESS_MATRIX)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--protocol-output", type=Path, default=DEFAULT_PROTOCOL_OUTPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--metrics", type=Path, default=DEFAULT_METRICS)
    parser.add_argument("--downshift-report", type=Path, default=DEFAULT_DOWNSHIFT_REPORT)
    parser.add_argument("--downshift-json", type=Path, default=DEFAULT_DOWNSHIFT_JSON)
    parser.add_argument("--candidate-matrix", type=Path, default=DEFAULT_CANDIDATE_MATRIX)
    parser.add_argument("--clustered-summary", type=Path, default=DEFAULT_CLUSTERED_SUMMARY)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--wp7-manifest", type=Path, default=DEFAULT_WP7_MANIFEST)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_risk_validation_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        baseline_diagnostics=args.baseline_diagnostics,
        vol_scaled_sanity=args.vol_scaled_sanity,
        logistic_hazard=args.logistic_hazard,
        calibration_readiness=args.calibration_readiness,
        calibration_fold_metrics=args.calibration_fold_metrics,
        calibration_slice_metrics=args.calibration_slice_metrics,
        calibration_bins=args.calibration_bins,
        clustered_inference=args.clustered_inference,
        readiness_matrix=args.readiness_matrix,
        fold_plan=args.fold_plan,
        policy=args.policy,
        protocol_output=args.protocol_output,
        output=args.output,
        summary_json=args.summary_json,
        metrics=args.metrics,
        downshift_report=args.downshift_report,
        downshift_json=args.downshift_json,
        candidate_matrix=args.candidate_matrix,
        clustered_summary=args.clustered_summary,
        audit_sample=args.audit_sample,
        wp7_manifest=args.wp7_manifest,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_RISK_VALIDATION="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"candidates={report.get('candidate_rows_evaluated')} "
        f"validation_pass_candidates={report.get('validation_pass_candidate_count')} "
        f"holdout_evaluated={report.get('prospective_holdout_rows_evaluated')} "
        f"leakage_violations={report.get('leakage_violation_counts', {}).get('leakage_violation_count_total')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
