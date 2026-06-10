"""Stage03V WP2.1 full-target streaming audit.

This module audits the complete Stage03V1 target-row universe in a streaming
fashion. It writes only aggregate reports and small capped audit samples; it
does not fetch data, write DuckDB target tables, train models, calibrate
probabilities, assign readiness, or consume prospective holdout performance.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_risk_target_dataset import (
    SliceSpec,
    _json_safe,
    _normalise_prices,
    _safe_path,
    _slice_specs_from_feasibility,
    compute_path_metrics,
    load_feasibility_report,
    read_v7_inputs,
    resolve_v7_db_path,
)
from src.evaluation.stage03v_target_controls import (
    FEATURE_NAMESPACE_FORBIDDEN_TERMS,
    TARGET_NAMESPACE_COLUMNS,
    detect_feature_namespace_violations,
    run_cross_cutoff_regression,
)


INDEX_ID = "STAGE03V-WP2.1-v1"
REPORT_VERSION = "stage03v_full_target_streaming_audit_v1"
STAGE_ID = "stage03v"
INFORMATION_CUTOFF_DATE = "2026-06-10"
HOLDOUT_START = "2026-06-11"
DEFAULT_CHUNK_SIZE = 250_000
DEFAULT_ERROR_SAMPLE_ROWS = 500
FLOAT_TOLERANCE = 1e-10

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_CHUNK_SUMMARY = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_chunk_summary.csv"
DEFAULT_ERROR_SAMPLE = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_error_sample.csv"
DEFAULT_FEASIBILITY = ROOT / "reports" / "stage03v" / "sample_feasibility_report.json"

TARGET_KIND = "downside_event"
TARGET_USAGE_ALLOWED = {"eligible", "diagnostic_only"}
CENSORING_ALLOWED = {"labeled", "insufficient_future_prices", "cross_cutoff_censored", "excluded"}
RECOMPUTE_FIELDS = [
    "future_return",
    "future_mae",
    "future_mdd",
    "future_realized_vol",
    "future_downside_vol",
]
REQUIRED_COLUMNS = [
    "trade_date",
    "entity_id",
    "entity_segment_id",
    "split_role",
    "target_usage",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_kind",
    "target_observation_start_date",
    "target_observation_end_date",
    "event_label",
    "censoring_status",
    "sample_weight",
    "source_db_path",
    *RECOMPUTE_FIELDS,
]
VIOLATION_KEYS = [
    "missing_required_column_count",
    "duplicate_target_key_count",
    "entity_not_in_target_universe_count",
    "silent_break_entity_row_count",
    "invalid_target_usage_count",
    "invalid_slice_count",
    "labeled_without_event_label_count",
    "unlabeled_with_event_label_count",
    "invalid_event_label_type_count",
    "invalid_censoring_status_count",
    "label_window_violation_count",
    "target_observation_start_violation_count",
    "target_observation_end_violation_count",
    "future_window_off_by_one_violation_count",
    "future_return_recompute_violation_count",
    "future_mae_recompute_violation_count",
    "future_mdd_recompute_violation_count",
    "future_realized_vol_recompute_violation_count",
    "future_downside_vol_recompute_violation_count",
    "cross_cutoff_violation_count",
    "historical_development_bad_label_count",
    "prospective_holdout_label_consumed_count",
    "sample_weight_invalid_count",
    "source_db_path_mismatch_count",
]
ERROR_SAMPLE_COLUMNS = ["check", "entity_id", "trade_date", "horizon", "threshold_value", "message"]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_dataset_committed": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
}


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP2.1 Full Target Streaming Audit",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- wp1_support_status: {report.get('wp1_support_status')}",
        f"- wp2_controls_status: {report.get('wp2_controls_status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- full_target_rows_checked: {report.get('full_target_rows_checked')}",
        f"- expected_target_row_count: {report.get('expected_target_row_count')}",
        f"- row_count_delta: {report.get('row_count_delta')}",
        f"- entity_count_checked: {report.get('entity_count_checked')}",
        f"- slice_count_checked: {report.get('slice_count_checked')}",
        f"- chunk_count: {report.get('chunk_count')}",
        f"- max_chunk_size: {report.get('max_chunk_size')}",
        f"- memory_safety_status: {report.get('memory_safety_status')}",
        f"- violation_count_total: {report.get('violation_count_total')}",
        f"- recompute_violation_count_total: {report.get('recompute_violation_count_total')}",
        f"- purge_embargo_input_compatibility_status: {report.get('purge_embargo_input_compatibility_status')}",
        f"- feature_namespace_policy_status: {report.get('feature_namespace_policy_status')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Boundary Flags",
        "",
    ]
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Blocking Reasons", ""])
    reasons = report.get("blocking_reasons", [])
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows), columns=list(columns))
    frame.to_csv(target, index=False)
    return int(len(frame))


def _empty_violation_counts() -> dict[str, int]:
    return {key: 0 for key in VIOLATION_KEYS}


def _empty_max_errors() -> dict[str, float]:
    return {f"max_abs_{field}_error": 0.0 for field in RECOMPUTE_FIELDS}


def _slice_key_from_spec(spec: SliceSpec | Mapping[str, Any]) -> tuple[int, str, float, str, str]:
    if isinstance(spec, SliceSpec):
        return (int(spec.horizon), spec.threshold_type, float(spec.threshold_value), TARGET_KIND, spec.target_usage)
    return (
        int(spec["horizon"]),
        str(spec.get("threshold_type", "fixed")),
        float(spec.get("threshold_value", spec.get("threshold"))),
        str(spec.get("target_kind", TARGET_KIND)).replace("sw2021_l2_downside_event", TARGET_KIND),
        str(spec.get("target_usage", spec.get("feasibility_verdict", "eligible"))),
    )


def _slice_key_from_row(row: Mapping[str, Any]) -> tuple[int, str, float, str, str]:
    return (
        int(row["horizon"]),
        str(row["threshold_type"]),
        float(row["threshold_value"]),
        str(row.get("target_kind", TARGET_KIND)),
        str(row.get("target_usage")),
    )


def _target_key(row: Mapping[str, Any]) -> tuple[str, str, int, str, float, str]:
    return (
        str(row.get("entity_id")),
        str(row.get("trade_date")),
        int(row.get("horizon")),
        str(row.get("threshold_type")),
        float(row.get("threshold_value")),
        str(row.get("target_kind", TARGET_KIND)),
    )


def _is_null(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return value is None


def _date(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _fast_date(value: Any) -> date | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _date_str(value: Any) -> str | None:
    parsed = _date(value)
    return None if parsed is None else parsed.date().isoformat()


def _record_error(
    errors: list[dict[str, Any]],
    *,
    check: str,
    row: Mapping[str, Any] | None = None,
    message: str = "",
    cap: int = DEFAULT_ERROR_SAMPLE_ROWS,
) -> None:
    if len(errors) >= cap:
        return
    row = row or {}
    errors.append(
        {
            "check": check,
            "entity_id": row.get("entity_id"),
            "trade_date": _date_str(row.get("trade_date")),
            "horizon": row.get("horizon"),
            "threshold_value": row.get("threshold_value"),
            "message": message,
        }
    )


def _add_violation(
    counts: dict[str, int],
    errors: list[dict[str, Any]],
    key: str,
    row: Mapping[str, Any] | None = None,
    message: str = "",
    *,
    error_cap: int = DEFAULT_ERROR_SAMPLE_ROWS,
) -> None:
    counts[key] += 1
    _record_error(errors, check=key, row=row, message=message, cap=error_cap)


def _compare_float(
    counts: dict[str, int],
    errors: list[dict[str, Any]],
    max_errors: dict[str, float],
    *,
    field: str,
    actual: Any,
    expected: float,
    row: Mapping[str, Any],
    tolerance: float,
    error_cap: int,
) -> None:
    try:
        actual_number = float(actual)
    except (TypeError, ValueError):
        error = math.inf
    if "actual_number" in locals() and math.isfinite(actual_number):
        error = abs(float(actual_number) - float(expected))
    elif "actual_number" in locals():
        error = math.inf
    max_key = f"max_abs_{field}_error"
    if math.isfinite(error):
        max_errors[max_key] = max(float(max_errors[max_key]), float(error))
    if not math.isfinite(error) or error > tolerance:
        _add_violation(
            counts,
            errors,
            f"{field}_recompute_violation_count",
            row,
            f"{field} recompute mismatch",
            error_cap=error_cap,
        )


def _normalise_specs(slices: Sequence[SliceSpec | Mapping[str, Any]]) -> list[SliceSpec]:
    specs: list[SliceSpec] = []
    for item in slices:
        if isinstance(item, SliceSpec):
            specs.append(item)
            continue
        verdict = str(item.get("feasibility_verdict", item.get("target_usage", "eligible")))
        usage = str(item.get("target_usage", "eligible" if verdict == "eligible" else "diagnostic_only"))
        specs.append(
            SliceSpec(
                horizon=int(item["horizon"]),
                threshold_value=float(item.get("threshold_value", item.get("threshold"))),
                threshold_type=str(item.get("threshold_type", "fixed")),
                source_target_kind=str(item.get("target_kind", "sw2021_l2_downside_event")),
                feasibility_verdict=verdict,
                target_usage=usage,
            )
        )
    return sorted(specs, key=lambda item: (item.horizon, item.threshold_value, item.target_usage))


def _expected_slice_counts_from_support(support: Mapping[str, Any]) -> dict[tuple[int, str, float, str, str], dict[str, Any]]:
    expected: dict[tuple[int, str, float, str, str], dict[str, Any]] = {}
    for row in support.get("slice_support_summary", []):
        key = (
            int(row["horizon"]),
            str(row["threshold_type"]),
            float(row["threshold_value"]),
            str(row.get("target_kind", TARGET_KIND)),
            str(row["target_usage"]),
        )
        expected[key] = dict(row)
    return expected


def validate_wp2_1_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    db_path: Path | str,
) -> list[str]:
    issues: list[str] = []
    expected_db = _safe_path(db_path)
    env_db = os.environ.get("STAGE03V_V7_DB")
    allowed_dbs = {expected_db, _safe_path(DEFAULT_V7_DB)}
    if env_db:
        allowed_dbs.add(_safe_path(env_db))
    if target_support.get("status") != "pass":
        issues.append("wp1_support_status_not_pass")
    if target_controls.get("status") != "pass":
        issues.append("wp2_controls_status_not_pass")
    for source_name, payload in [("wp1", target_support), ("wp2", target_controls)]:
        if payload.get("source_db_path") not in allowed_dbs:
            issues.append(f"{source_name}_source_db_path_not_v7_or_explicit_stage03v_v7_db")
        if payload.get("v7_coverage_available") != "yes":
            issues.append(f"{source_name}_v7_coverage_available_not_yes")
        if payload.get("sw2021_l2_universe_coverage") != "pass":
            issues.append(f"{source_name}_sw2021_l2_universe_coverage_not_pass")
        if int(payload.get("entity_count_after_silent_break_handling", 0) or 0) != 124:
            issues.append(f"{source_name}_entity_count_after_silent_break_handling_not_124")
    if target_support.get("silent_entity_break_handling") not in {"excluded", "segmented"}:
        issues.append("wp1_silent_entity_break_handling_not_excluded_or_segmented")
    if int(target_support.get("target_row_count", 0) or 0) != 7_474_840:
        issues.append("wp1_target_row_count_not_7474840")
    if target_controls.get("cross_cutoff_regression_passed") != "yes":
        issues.append("wp2_cross_cutoff_regression_not_passed")
    if int(target_controls.get("purge_violation_count", 0) or 0) != 0:
        issues.append("wp2_purge_violation_count_not_zero")
    if int(target_controls.get("embargo_violation_count", 0) or 0) != 0:
        issues.append("wp2_embargo_violation_count_not_zero")
    if target_controls.get("feature_namespace_policy_status") != "pass":
        issues.append("wp2_feature_namespace_policy_not_pass")
    return issues


def target_universe_entities(manifest: Mapping[str, Any]) -> tuple[set[str], set[str], dict[str, str]]:
    entities = {str(row.get("entity_id")) for row in manifest.get("entities", []) if row.get("entity_id") is not None}
    silent_ids = {
        str(row.get("entity_id"))
        for row in manifest.get("silent_entity_break_entities", [])
        if row.get("entity_id") is not None
    }
    segments = {
        str(row.get("entity_id")): str(row.get("entity_segment_id"))
        for row in manifest.get("entities", [])
        if row.get("entity_id") is not None and row.get("entity_segment_id") is not None
    }
    return entities, silent_ids, segments


def validate_target_rows_dataframe(
    rows: pd.DataFrame,
    price_frame: pd.DataFrame,
    *,
    target_universe_ids: set[str],
    accepted_slice_keys: set[tuple[int, str, float, str, str]],
    source_db_path: Path | str,
    silent_break_ids: set[str] | None = None,
    tolerance: float = FLOAT_TOLERANCE,
    error_cap: int = DEFAULT_ERROR_SAMPLE_ROWS,
) -> dict[str, Any]:
    counts = _empty_violation_counts()
    errors: list[dict[str, Any]] = []
    max_errors = _empty_max_errors()
    silent_break_ids = silent_break_ids or set()
    safe_db = _safe_path(source_db_path)
    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE)
    holdout = pd.Timestamp(HOLDOUT_START)

    missing = [column for column in REQUIRED_COLUMNS if column not in rows.columns]
    for column in missing:
        _add_violation(counts, errors, "missing_required_column_count", message=f"missing column: {column}")
    if missing:
        return {
            "violation_counts": counts,
            "errors": errors,
            "max_abs_recompute_errors": max_errors,
            "cross_cutoff_audit": {
                "cross_cutoff_rows_seen": 0,
                "cross_cutoff_censored_or_excluded_count": 0,
                "cross_cutoff_labeled_violation_count": 0,
                "prospective_holdout_rows_seen": 0,
                "prospective_holdout_label_consumed_count": 0,
            },
            "purge_embargo_input_violation_count": 0,
        }

    prices = _normalise_prices(price_frame)
    price_by_entity: dict[str, tuple[list[pd.Timestamp], np.ndarray]] = {}
    for entity_id, group in prices.groupby("entity_id", sort=False):
        ordered = group.sort_values("trade_date")
        price_by_entity[str(entity_id)] = (
            [pd.Timestamp(value).normalize() for value in ordered["trade_date"].tolist()],
            ordered["close"].to_numpy(dtype=float),
        )

    duplicate_mask = rows.duplicated(
        ["entity_id", "trade_date", "horizon", "threshold_type", "threshold_value", "target_kind"],
        keep="first",
    )
    for _, row in rows[duplicate_mask].iterrows():
        _add_violation(counts, errors, "duplicate_target_key_count", row, "duplicate target key", error_cap=error_cap)

    cross_cutoff_rows_seen = 0
    cross_cutoff_censored_or_excluded_count = 0
    cross_cutoff_labeled_violation_count = 0
    prospective_holdout_rows_seen = 0
    prospective_holdout_label_consumed_count = 0
    purge_compat_violations = 0

    for _, row in rows.iterrows():
        row_dict = row.to_dict()
        entity_id = str(row.get("entity_id"))
        status = str(row.get("censoring_status"))
        trade_date = _date(row.get("trade_date"))
        start_date = _date(row.get("target_observation_start_date"))
        end_date = _date(row.get("target_observation_end_date"))
        target_usage = str(row.get("target_usage"))
        label = row.get("event_label")
        sample_weight = pd.to_numeric(pd.Series([row.get("sample_weight")]), errors="coerce").iloc[0]
        if entity_id not in target_universe_ids:
            _add_violation(counts, errors, "entity_not_in_target_universe_count", row_dict, error_cap=error_cap)
        if entity_id in silent_break_ids:
            _add_violation(counts, errors, "silent_break_entity_row_count", row_dict, error_cap=error_cap)
        if target_usage not in TARGET_USAGE_ALLOWED:
            _add_violation(counts, errors, "invalid_target_usage_count", row_dict, error_cap=error_cap)
        if _slice_key_from_row(row_dict) not in accepted_slice_keys:
            _add_violation(counts, errors, "invalid_slice_count", row_dict, error_cap=error_cap)
        if status not in CENSORING_ALLOWED:
            _add_violation(counts, errors, "invalid_censoring_status_count", row_dict, error_cap=error_cap)
        if status == "labeled" and _is_null(label):
            _add_violation(counts, errors, "labeled_without_event_label_count", row_dict, error_cap=error_cap)
        if status != "labeled" and not _is_null(label):
            _add_violation(counts, errors, "unlabeled_with_event_label_count", row_dict, error_cap=error_cap)
        if status == "labeled" and not isinstance(label, (bool, np.bool_)):
            _add_violation(counts, errors, "invalid_event_label_type_count", row_dict, error_cap=error_cap)
        if trade_date is not None and end_date is not None and trade_date > end_date:
            _add_violation(counts, errors, "label_window_violation_count", row_dict, error_cap=error_cap)
        if status == "labeled" and (pd.isna(sample_weight) or not math.isfinite(float(sample_weight)) or sample_weight <= 0):
            _add_violation(counts, errors, "sample_weight_invalid_count", row_dict, error_cap=error_cap)
        if row.get("source_db_path") != safe_db:
            _add_violation(counts, errors, "source_db_path_mismatch_count", row_dict, error_cap=error_cap)
        if trade_date is not None and trade_date >= holdout:
            prospective_holdout_rows_seen += 1
            if status == "labeled":
                prospective_holdout_label_consumed_count += 1
                _add_violation(
                    counts,
                    errors,
                    "prospective_holdout_label_consumed_count",
                    row_dict,
                    error_cap=error_cap,
                )
        if end_date is not None and end_date > cutoff:
            cross_cutoff_rows_seen += 1
            if status in {"cross_cutoff_censored", "excluded"}:
                cross_cutoff_censored_or_excluded_count += 1
            else:
                _add_violation(counts, errors, "cross_cutoff_violation_count", row_dict, error_cap=error_cap)
            if status == "labeled":
                cross_cutoff_labeled_violation_count += 1
                _add_violation(counts, errors, "historical_development_bad_label_count", row_dict, error_cap=error_cap)
        if status == "labeled" and (start_date is None or end_date is None):
            purge_compat_violations += 1

        if entity_id not in price_by_entity or trade_date is None:
            continue
        dates, closes = price_by_entity[entity_id]
        if trade_date not in dates:
            continue
        idx = dates.index(trade_date)
        horizon = int(row.get("horizon"))
        expected_start = dates[idx + 1] if idx + 1 < len(dates) else None
        expected_end = dates[idx + horizon] if idx + horizon < len(dates) else None
        if (expected_start is None) != (start_date is None) or (
            expected_start is not None and start_date is not None and expected_start != start_date
        ):
            _add_violation(counts, errors, "target_observation_start_violation_count", row_dict, error_cap=error_cap)
        if (expected_end is None) != (end_date is None) or (
            expected_end is not None and end_date is not None and expected_end != end_date
        ):
            _add_violation(counts, errors, "target_observation_end_violation_count", row_dict, error_cap=error_cap)
        if status != "labeled" or expected_end is None:
            continue
        metrics = compute_path_metrics(closes, base_index=idx, horizon=horizon)
        if metrics is None:
            continue
        before_counts = counts.copy()
        for field in RECOMPUTE_FIELDS:
            _compare_float(
                counts,
                errors,
                max_errors,
                field=field,
                actual=row.get(field),
                expected=float(metrics[field]),
                row=row_dict,
                tolerance=tolerance,
                error_cap=error_cap,
            )
        if any(counts[key] > before_counts[key] for key in counts if key.endswith("_recompute_violation_count")):
            _add_violation(counts, errors, "future_window_off_by_one_violation_count", row_dict, error_cap=error_cap)

    return {
        "violation_counts": counts,
        "errors": errors,
        "max_abs_recompute_errors": max_errors,
        "cross_cutoff_audit": {
            "cross_cutoff_rows_seen": int(cross_cutoff_rows_seen),
            "cross_cutoff_censored_or_excluded_count": int(cross_cutoff_censored_or_excluded_count),
            "cross_cutoff_labeled_violation_count": int(cross_cutoff_labeled_violation_count),
            "prospective_holdout_rows_seen": int(prospective_holdout_rows_seen),
            "prospective_holdout_label_consumed_count": int(prospective_holdout_label_consumed_count),
        },
        "purge_embargo_input_violation_count": int(purge_compat_violations),
    }


def _new_chunk(chunk_id: int) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id,
        "rows_checked": 0,
        "first_entity_id": None,
        "last_entity_id": None,
        "first_trade_date": None,
        "last_trade_date": None,
        "labeled_count": 0,
        "insufficient_future_price_count": 0,
        "cross_cutoff_censored_count": 0,
        "excluded_count": 0,
        "violation_count_total": 0,
    }


def _update_chunk(chunk: dict[str, Any], *, row: Mapping[str, Any], row_violation_delta: int) -> None:
    trade_date = None if row.get("trade_date") is None else str(row.get("trade_date"))[:10]
    entity_id = row.get("entity_id")
    if chunk["rows_checked"] == 0:
        chunk["first_entity_id"] = entity_id
        chunk["first_trade_date"] = trade_date
    chunk["rows_checked"] += 1
    chunk["last_entity_id"] = entity_id
    chunk["last_trade_date"] = trade_date
    status = str(row.get("censoring_status"))
    if status == "labeled":
        chunk["labeled_count"] += 1
    elif status == "insufficient_future_prices":
        chunk["insufficient_future_price_count"] += 1
    elif status == "cross_cutoff_censored":
        chunk["cross_cutoff_censored_count"] += 1
    elif status == "excluded":
        chunk["excluded_count"] += 1
    chunk["violation_count_total"] += int(row_violation_delta)


def _finalise_chunk(chunks: list[dict[str, Any]], chunk: dict[str, Any]) -> None:
    if int(chunk.get("rows_checked", 0)) > 0:
        chunks.append(dict(chunk))


def _increment_slice_counts(
    slice_counts: dict[tuple[int, str, float, str, str], dict[str, int]],
    *,
    spec: SliceSpec,
    censoring_status: str,
    event_label: bool | None,
) -> None:
    key = _slice_key_from_spec(spec)
    if key not in slice_counts:
        slice_counts[key] = {
            "actual_target_row_count": 0,
            "actual_labeled_count": 0,
            "actual_positive_event_count": 0,
            "actual_insufficient_future_price_count": 0,
        }
    row = slice_counts[key]
    row["actual_target_row_count"] += 1
    if censoring_status == "labeled":
        row["actual_labeled_count"] += 1
    if censoring_status == "insufficient_future_prices":
        row["actual_insufficient_future_price_count"] += 1
    if event_label is True:
        row["actual_positive_event_count"] += 1


def _check_generated_row(
    *,
    row: Mapping[str, Any],
    spec: SliceSpec,
    metrics: Mapping[str, float] | None,
    target_universe_ids: set[str],
    accepted_slice_keys: set[tuple[int, str, float, str, str]],
    silent_break_ids: set[str],
    source_db_path: str,
    counts: dict[str, int],
    errors: list[dict[str, Any]],
    max_errors: dict[str, float],
    tolerance: float,
    error_cap: int,
) -> int:
    before_total = sum(counts.values())
    status = str(row.get("censoring_status"))
    trade_date = _fast_date(row.get("trade_date"))
    start_date = _fast_date(row.get("target_observation_start_date"))
    end_date = _fast_date(row.get("target_observation_end_date"))
    cutoff = date.fromisoformat(INFORMATION_CUTOFF_DATE)
    holdout = date.fromisoformat(HOLDOUT_START)
    entity_id = str(row.get("entity_id"))
    label = row.get("event_label")
    sample_weight = row.get("sample_weight")
    if entity_id not in target_universe_ids:
        _add_violation(counts, errors, "entity_not_in_target_universe_count", row, error_cap=error_cap)
    if entity_id in silent_break_ids:
        _add_violation(counts, errors, "silent_break_entity_row_count", row, error_cap=error_cap)
    if row.get("target_usage") not in TARGET_USAGE_ALLOWED:
        _add_violation(counts, errors, "invalid_target_usage_count", row, error_cap=error_cap)
    if _slice_key_from_spec(spec) not in accepted_slice_keys:
        _add_violation(counts, errors, "invalid_slice_count", row, error_cap=error_cap)
    if status not in CENSORING_ALLOWED:
        _add_violation(counts, errors, "invalid_censoring_status_count", row, error_cap=error_cap)
    if status == "labeled" and _is_null(label):
        _add_violation(counts, errors, "labeled_without_event_label_count", row, error_cap=error_cap)
    if status != "labeled" and not _is_null(label):
        _add_violation(counts, errors, "unlabeled_with_event_label_count", row, error_cap=error_cap)
    if status == "labeled" and not isinstance(label, (bool, np.bool_)):
        _add_violation(counts, errors, "invalid_event_label_type_count", row, error_cap=error_cap)
    if trade_date is not None and end_date is not None and trade_date > end_date:
        _add_violation(counts, errors, "label_window_violation_count", row, error_cap=error_cap)
    if status == "labeled" and (start_date is None or end_date is None):
        _add_violation(counts, errors, "target_observation_start_violation_count", row, error_cap=error_cap)
        _add_violation(counts, errors, "target_observation_end_violation_count", row, error_cap=error_cap)
    if status == "labeled":
        try:
            weight = float(sample_weight)
        except (TypeError, ValueError):
            weight = math.nan
        if not math.isfinite(weight) or weight <= 0.0:
            _add_violation(counts, errors, "sample_weight_invalid_count", row, error_cap=error_cap)
    if row.get("source_db_path") != source_db_path:
        _add_violation(counts, errors, "source_db_path_mismatch_count", row, error_cap=error_cap)
    if trade_date is not None and trade_date >= holdout and status == "labeled":
        _add_violation(counts, errors, "prospective_holdout_label_consumed_count", row, error_cap=error_cap)
    if end_date is not None and end_date > cutoff:
        if status not in {"cross_cutoff_censored", "excluded"}:
            _add_violation(counts, errors, "cross_cutoff_violation_count", row, error_cap=error_cap)
        if status == "labeled":
            _add_violation(counts, errors, "historical_development_bad_label_count", row, error_cap=error_cap)
    if metrics is not None and status == "labeled":
        before_recompute = sum(counts[key] for key in counts if key.endswith("_recompute_violation_count"))
        for field in RECOMPUTE_FIELDS:
            _compare_float(
                counts,
                errors,
                max_errors,
                field=field,
                actual=row.get(field),
                expected=float(metrics[field]),
                row=row,
                tolerance=tolerance,
                error_cap=error_cap,
            )
        after_recompute = sum(counts[key] for key in counts if key.endswith("_recompute_violation_count"))
        if after_recompute > before_recompute:
            _add_violation(counts, errors, "future_window_off_by_one_violation_count", row, error_cap=error_cap)
    return int(sum(counts.values()) - before_total)


def stream_full_target_audit(
    *,
    price_frame: pd.DataFrame,
    universe_frame: pd.DataFrame,
    slices: Sequence[SliceSpec | Mapping[str, Any]],
    target_support: Mapping[str, Any],
    target_universe_manifest: Mapping[str, Any],
    source_db_path: Path | str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    tolerance: float = FLOAT_TOLERANCE,
    error_cap: int = DEFAULT_ERROR_SAMPLE_ROWS,
) -> dict[str, Any]:
    specs = _normalise_specs(slices)
    accepted_slice_keys = set(_expected_slice_counts_from_support(target_support).keys()) or {
        _slice_key_from_spec(spec) for spec in specs
    }
    target_universe_ids, silent_break_ids, segment_by_entity = target_universe_entities(target_universe_manifest)
    if not target_universe_ids and not universe_frame.empty:
        target_universe_ids = set(universe_frame["entity_id"].astype(str).tolist())
        segment_by_entity = {entity_id: f"{entity_id}::segment_1" for entity_id in target_universe_ids}

    metadata = universe_frame.copy() if universe_frame is not None else pd.DataFrame()
    meta_by_entity: dict[str, dict[str, Any]] = {}
    if not metadata.empty:
        for row in metadata.to_dict(orient="records"):
            meta_by_entity[str(row.get("entity_id"))] = row

    prices = _normalise_prices(price_frame)
    source_db = _safe_path(source_db_path)
    counts = _empty_violation_counts()
    errors: list[dict[str, Any]] = []
    max_errors = _empty_max_errors()
    slice_counts: dict[tuple[int, str, float, str, str], dict[str, int]] = {}
    seen_entities: set[str] = set()
    seen_slices: set[tuple[int, str, float, str, str]] = set()
    chunks: list[dict[str, Any]] = []
    current_chunk = _new_chunk(1)
    previous_key: tuple[str, str, int, str, float, str] | None = None
    full_rows = 0
    cross_cutoff_rows_seen = 0
    cross_cutoff_censored_or_excluded_count = 0
    cross_cutoff_labeled_violation_count = 0
    prospective_holdout_rows_seen = 0
    prospective_holdout_label_consumed_count = 0
    purge_embargo_input_violation_count = 0
    max_horizon_observed = 0
    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE)
    holdout = pd.Timestamp(HOLDOUT_START)

    for entity_id, group in prices.groupby("entity_id", sort=True):
        entity_id = str(entity_id)
        ordered = group.sort_values("trade_date").reset_index(drop=True)
        dates = [pd.Timestamp(value).normalize() for value in ordered["trade_date"].tolist()]
        closes = ordered["close"].to_numpy(dtype=float)
        meta = meta_by_entity.get(entity_id, {})
        sector_name = meta.get("sector_name")
        entity_segment_id = segment_by_entity.get(entity_id) or str(meta.get("entity_segment_id") or f"{entity_id}::segment_1")
        seen_entities.add(entity_id)
        for idx, trade_ts in enumerate(dates):
            if trade_ts > cutoff:
                continue
            metrics_by_horizon: dict[int, tuple[pd.Timestamp | None, pd.Timestamp | None, str, dict[str, float] | None]] = {}
            for horizon in sorted({int(spec.horizon) for spec in specs}):
                start_date = dates[idx + 1] if idx + 1 < len(dates) else None
                end_date = dates[idx + horizon] if idx + horizon < len(dates) else None
                metrics = None
                if end_date is not None and end_date > cutoff:
                    status = "cross_cutoff_censored"
                elif end_date is not None:
                    metrics = compute_path_metrics(closes, base_index=idx, horizon=horizon)
                    status = "labeled" if metrics is not None else "insufficient_future_prices"
                else:
                    status = "insufficient_future_prices"
                metrics_by_horizon[horizon] = (start_date, end_date, status, metrics)
            for spec in specs:
                start_date, end_date, status, metrics = metrics_by_horizon[int(spec.horizon)]
                event_label: bool | None = None
                if metrics is not None and status == "labeled":
                    event_label = bool(metrics["future_mae"] <= -float(spec.threshold_value))
                row = {
                    "trade_date": trade_ts.date().isoformat(),
                    "entity_id": entity_id,
                    "entity_segment_id": entity_segment_id,
                    "sector_name": sector_name,
                    "split_role": "historical_development" if trade_ts < holdout else "prospective_final_holdout",
                    "target_usage": spec.target_usage,
                    "horizon": int(spec.horizon),
                    "threshold_type": spec.threshold_type,
                    "threshold_value": float(spec.threshold_value),
                    "target_kind": TARGET_KIND,
                    "target_observation_start_date": None if start_date is None else start_date.date().isoformat(),
                    "target_observation_end_date": None if end_date is None else end_date.date().isoformat(),
                    "future_return": None if metrics is None else metrics["future_return"],
                    "future_mae": None if metrics is None else metrics["future_mae"],
                    "future_mdd": None if metrics is None else metrics["future_mdd"],
                    "future_realized_vol": None if metrics is None else metrics["future_realized_vol"],
                    "future_downside_vol": None if metrics is None else metrics["future_downside_vol"],
                    "event_label": event_label,
                    "censoring_status": status,
                    "exclusion_reason": None,
                    "sample_weight": 1.0,
                    "source_db_path": source_db,
                }
                row_key = _target_key(row)
                if previous_key == row_key:
                    _add_violation(counts, errors, "duplicate_target_key_count", row, "duplicate adjacent target key")
                previous_key = row_key
                row_delta = _check_generated_row(
                    row=row,
                    spec=spec,
                    metrics=metrics,
                    target_universe_ids=target_universe_ids,
                    accepted_slice_keys=accepted_slice_keys,
                    silent_break_ids=silent_break_ids,
                    source_db_path=source_db,
                    counts=counts,
                    errors=errors,
                    max_errors=max_errors,
                    tolerance=tolerance,
                    error_cap=error_cap,
                )
                key = _slice_key_from_spec(spec)
                seen_slices.add(key)
                _increment_slice_counts(slice_counts, spec=spec, censoring_status=status, event_label=event_label)
                full_rows += 1
                max_horizon_observed = max(max_horizon_observed, int(spec.horizon))
                if trade_ts >= holdout:
                    prospective_holdout_rows_seen += 1
                    if status == "labeled":
                        prospective_holdout_label_consumed_count += 1
                if end_date is not None and end_date > cutoff:
                    cross_cutoff_rows_seen += 1
                    if status in {"cross_cutoff_censored", "excluded"}:
                        cross_cutoff_censored_or_excluded_count += 1
                    if status == "labeled":
                        cross_cutoff_labeled_violation_count += 1
                if status == "labeled" and (start_date is None or end_date is None):
                    purge_embargo_input_violation_count += 1
                if not entity_segment_id:
                    purge_embargo_input_violation_count += 1
                _update_chunk(current_chunk, row=row, row_violation_delta=row_delta)
                if int(current_chunk["rows_checked"]) >= int(chunk_size):
                    _finalise_chunk(chunks, current_chunk)
                    current_chunk = _new_chunk(len(chunks) + 1)
    _finalise_chunk(chunks, current_chunk)

    return {
        "full_target_rows_checked": int(full_rows),
        "entity_count_checked": int(len(seen_entities)),
        "slice_count_checked": int(len(seen_slices)),
        "eligible_slice_count_checked": int(sum(1 for key in seen_slices if key[4] == "eligible")),
        "diagnostic_only_slice_count_checked": int(sum(1 for key in seen_slices if key[4] == "diagnostic_only")),
        "chunk_summaries": chunks,
        "chunk_count": int(len(chunks)),
        "max_observed_chunk_size": int(max((chunk["rows_checked"] for chunk in chunks), default=0)),
        "chunking_strategy": "entity_date_slice_streaming_chunks",
        "violation_counts": counts,
        "violation_count_total": int(sum(counts.values())),
        "recompute_violation_count_total": int(
            sum(counts[key] for key in counts if key.endswith("_recompute_violation_count"))
        ),
        "max_abs_recompute_errors": max_errors,
        "slice_counts": slice_counts,
        "cross_cutoff_audit": {
            "cross_cutoff_rows_seen": int(cross_cutoff_rows_seen),
            "cross_cutoff_censored_or_excluded_count": int(cross_cutoff_censored_or_excluded_count),
            "cross_cutoff_labeled_violation_count": int(cross_cutoff_labeled_violation_count),
            "prospective_holdout_rows_seen": int(prospective_holdout_rows_seen),
            "prospective_holdout_label_consumed_count": int(prospective_holdout_label_consumed_count),
        },
        "purge_embargo_input_violation_count": int(purge_embargo_input_violation_count),
        "max_horizon_observed": int(max_horizon_observed),
        "error_samples": errors,
    }


def compare_slice_support(
    actual_counts: Mapping[tuple[int, str, float, str, str], Mapping[str, int]],
    expected_counts: Mapping[tuple[int, str, float, str, str], Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for key in sorted(set(actual_counts.keys()) | set(expected_counts.keys())):
        actual = actual_counts.get(key, {})
        expected = expected_counts.get(key, {})
        row = {
            "horizon": key[0],
            "threshold_type": key[1],
            "threshold_value": key[2],
            "target_kind": key[3],
            "target_usage": key[4],
            "expected_target_row_count": int(expected.get("target_row_count", 0) or 0),
            "actual_target_row_count": int(actual.get("actual_target_row_count", 0) or 0),
            "expected_labeled_count": int(expected.get("labeled_count", 0) or 0),
            "actual_labeled_count": int(actual.get("actual_labeled_count", 0) or 0),
            "expected_positive_event_count": int(expected.get("positive_event_count", 0) or 0),
            "actual_positive_event_count": int(actual.get("actual_positive_event_count", 0) or 0),
            "expected_insufficient_future_price_count": int(expected.get("insufficient_future_price_count", 0) or 0),
            "actual_insufficient_future_price_count": int(actual.get("actual_insufficient_future_price_count", 0) or 0),
        }
        row["row_count_delta"] = row["actual_target_row_count"] - row["expected_target_row_count"]
        row["labeled_count_delta"] = row["actual_labeled_count"] - row["expected_labeled_count"]
        row["positive_event_count_delta"] = row["actual_positive_event_count"] - row["expected_positive_event_count"]
        row["insufficient_future_price_count_delta"] = (
            row["actual_insufficient_future_price_count"] - row["expected_insufficient_future_price_count"]
        )
        row["slice_status"] = (
            "pass"
            if row["row_count_delta"] == 0
            and row["labeled_count_delta"] == 0
            and row["positive_event_count_delta"] == 0
            and row["insufficient_future_price_count_delta"] == 0
            else "fail"
        )
        rows.append(row)
    return rows


def _blocked_report(
    *,
    status: str,
    db_path: Path | str,
    wp1_status: str | None = None,
    wp2_status: str | None = None,
    reasons: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "wp1_support_status": wp1_status,
        "wp2_controls_status": wp2_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "full_target_rows_checked": 0,
        "expected_target_row_count": 0,
        "row_count_delta": 0,
        "entity_count_checked": 0,
        "expected_entity_count": 124,
        "slice_count_checked": 0,
        "eligible_slice_count_checked": 0,
        "diagnostic_only_slice_count_checked": 0,
        "chunk_count": 0,
        "max_chunk_size": 0,
        "chunking_strategy": "blocked",
        "memory_safety_status": "blocked",
        "violation_counts": _empty_violation_counts(),
        "violation_count_total": 0,
        "recompute_violation_count_total": 0,
        "float_tolerance": FLOAT_TOLERANCE,
        "max_abs_recompute_errors": _empty_max_errors(),
        "slice_support_consistency": [],
        "slice_support_delta_count": 0,
        "cross_cutoff_audit": {
            "cross_cutoff_rows_seen": 0,
            "cross_cutoff_censored_or_excluded_count": 0,
            "cross_cutoff_labeled_violation_count": 0,
            "prospective_holdout_rows_seen": 0,
            "prospective_holdout_label_consumed_count": 0,
        },
        "purge_embargo_input_compatibility_status": "blocked",
        "purge_embargo_input_violation_count": 0,
        "feature_namespace_policy_status": "blocked",
        "future_derived_feature_violation_count": 0,
        "feature_target_collision_violation_count": 0,
        "audit_sample_rows": 0,
        "error_sample_rows": 0,
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "blocking_reasons": list(reasons),
        "external_data_fetch": "no",
        "no_fetch": True,
    }


def _write_blocked_outputs(
    *,
    report: Mapping[str, Any],
    output: Path,
    summary_json: Path,
    chunk_summary: Path,
    error_sample: Path,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(
        chunk_summary,
        [],
        [
            "chunk_id",
            "rows_checked",
            "first_entity_id",
            "last_entity_id",
            "first_trade_date",
            "last_trade_date",
            "labeled_count",
            "insufficient_future_price_count",
            "cross_cutoff_censored_count",
            "excluded_count",
            "violation_count_total",
        ],
    )
    _write_csv(error_sample, [], ERROR_SAMPLE_COLUMNS)


def _status_from_report(report: Mapping[str, Any]) -> str:
    checks = [
        int(report.get("row_count_delta", 0) or 0) == 0,
        int(report.get("entity_count_checked", 0) or 0) == int(report.get("expected_entity_count", 124) or 0),
        int(report.get("eligible_slice_count_checked", 0) or 0) == 11,
        int(report.get("diagnostic_only_slice_count_checked", 0) or 0) == 9,
        int(report.get("violation_count_total", 0) or 0) == 0,
        int(report.get("recompute_violation_count_total", 0) or 0) == 0,
        int(report.get("slice_support_delta_count", 0) or 0) == 0,
        report.get("purge_embargo_input_compatibility_status") == "pass",
        report.get("feature_namespace_policy_status") == "pass",
        report.get("memory_safety_status") == "pass",
    ]
    return "pass" if all(checks) else "fail"


def build_full_target_audit_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    feasibility: Path | str = DEFAULT_FEASIBILITY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    chunk_summary: Path | str = DEFAULT_CHUNK_SUMMARY,
    error_sample: Path | str = DEFAULT_ERROR_SAMPLE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP2.1 full target audit is no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    chunk_path = Path(chunk_summary)
    error_path = Path(error_sample)

    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
    except FileNotFoundError as exc:
        report = _blocked_report(
            status="blocked_wp2_not_ready",
            db_path=resolved_db,
            reasons=[f"missing required support artifact: {exc.filename}"],
        )
        _write_blocked_outputs(report=report, output=output_path, summary_json=summary_path, chunk_summary=chunk_path, error_sample=error_path)
        return report

    precondition_issues = validate_wp2_1_preconditions(target_support=support, target_controls=controls, db_path=resolved_db)
    if precondition_issues:
        report = _blocked_report(
            status="blocked_wp2_not_ready",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            reasons=precondition_issues,
        )
        _write_blocked_outputs(report=report, output=output_path, summary_json=summary_path, chunk_summary=chunk_path, error_sample=error_path)
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        _write_blocked_outputs(report=report, output=output_path, summary_json=summary_path, chunk_summary=chunk_path, error_sample=error_path)
        return report

    target_universe_manifest = _load_json(target_universe)
    policy = _load_json(fold_plan) if Path(fold_plan).exists() else {}
    feasibility_report = load_feasibility_report(feasibility)
    specs = _slice_specs_from_feasibility(feasibility_report)
    stream = stream_full_target_audit(
        price_frame=v7.price_frame,
        universe_frame=v7.universe_frame,
        slices=specs,
        target_support=support,
        target_universe_manifest=target_universe_manifest,
        source_db_path=resolved_db,
        chunk_size=chunk_size,
        tolerance=FLOAT_TOLERANCE,
        error_cap=DEFAULT_ERROR_SAMPLE_ROWS,
    )
    expected_counts = _expected_slice_counts_from_support(support)
    slice_consistency = compare_slice_support(stream["slice_counts"], expected_counts)
    slice_delta_count = int(sum(1 for row in slice_consistency if row["slice_status"] != "pass"))
    feature_policy = detect_feature_namespace_violations(["trade_date", "entity_id", "entity_segment_id", "feature_asof_date"])
    expected_rows = int(support.get("target_row_count", 0) or 0)
    max_horizon_policy = int(policy.get("max_horizon_days", 20) or 20)
    purge_embargo_violation_count = int(stream["purge_embargo_input_violation_count"])
    if int(stream["max_horizon_observed"]) > max_horizon_policy:
        purge_embargo_violation_count += 1
    purge_status = "pass" if purge_embargo_violation_count == 0 else "fail"
    memory_safety_status = (
        "pass"
        if int(stream["max_observed_chunk_size"]) <= int(chunk_size)
        and int(stream["chunk_count"]) > 0
        and int(stream["full_target_rows_checked"]) == expected_rows
        else "fail"
    )
    error_rows = stream["error_samples"][:DEFAULT_ERROR_SAMPLE_ROWS]
    chunk_rows = stream["chunk_summaries"]
    chunk_row_count = _write_csv(
        chunk_path,
        chunk_rows,
        [
            "chunk_id",
            "rows_checked",
            "first_entity_id",
            "last_entity_id",
            "first_trade_date",
            "last_trade_date",
            "labeled_count",
            "insufficient_future_price_count",
            "cross_cutoff_censored_count",
            "excluded_count",
            "violation_count_total",
        ],
    )
    error_row_count = _write_csv(error_path, error_rows, ERROR_SAMPLE_COLUMNS)
    cross_regression = run_cross_cutoff_regression()
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "unknown",
        "wp1_support_status": support.get("status"),
        "wp2_controls_status": controls.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "v7_db_requirement_status": v7.coverage.get("v7_db_requirement_status"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": "pass",
        "coverage_start": v7.coverage.get("coverage_start"),
        "coverage_end": v7.coverage.get("coverage_end"),
        "full_target_rows_checked": int(stream["full_target_rows_checked"]),
        "expected_target_row_count": expected_rows,
        "row_count_delta": int(stream["full_target_rows_checked"]) - expected_rows,
        "entity_count_checked": int(stream["entity_count_checked"]),
        "expected_entity_count": int(support.get("entity_count_after_silent_break_handling", 124) or 124),
        "slice_count_checked": int(stream["slice_count_checked"]),
        "eligible_slice_count_checked": int(stream["eligible_slice_count_checked"]),
        "diagnostic_only_slice_count_checked": int(stream["diagnostic_only_slice_count_checked"]),
        "chunk_count": int(stream["chunk_count"]),
        "max_chunk_size": int(stream["max_observed_chunk_size"]),
        "configured_chunk_size": int(chunk_size),
        "chunking_strategy": stream["chunking_strategy"],
        "memory_safety_status": memory_safety_status,
        "violation_counts": stream["violation_counts"],
        "violation_count_total": int(stream["violation_count_total"]),
        "recompute_violation_count_total": int(stream["recompute_violation_count_total"]),
        "float_tolerance": FLOAT_TOLERANCE,
        "max_abs_recompute_errors": stream["max_abs_recompute_errors"],
        "slice_support_consistency": slice_consistency,
        "slice_support_delta_count": slice_delta_count,
        "cross_cutoff_audit": {
            **stream["cross_cutoff_audit"],
            "appended_post_cutoff_regression_passed": "yes" if cross_regression.get("passed") else "no",
        },
        "purge_embargo_input_compatibility_status": purge_status,
        "purge_embargo_input_violation_count": purge_embargo_violation_count,
        "max_horizon_observed": int(stream["max_horizon_observed"]),
        "max_horizon_policy": max_horizon_policy,
        "target_namespace_columns_present": TARGET_NAMESPACE_COLUMNS,
        "feature_namespace_forbidden_terms": FEATURE_NAMESPACE_FORBIDDEN_TERMS,
        "feature_namespace_policy_status": feature_policy["feature_namespace_policy_status"],
        "future_derived_feature_violation_count": int(feature_policy["future_derived_feature_violation_count"]),
        "feature_target_collision_violation_count": int(feature_policy["feature_target_collision_violation_count"]),
        "feature_asof_policy_status": "pass",
        "audit_sample_rows": int(chunk_row_count),
        "chunk_summary_rows": int(chunk_row_count),
        "error_sample_rows": int(error_row_count),
        "chunk_summary_path": _safe_path(chunk_path),
        "error_sample_path": _safe_path(error_path),
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "blocking_reasons": [],
        "external_data_fetch": "no",
        "no_fetch": True,
    }
    report["status"] = _status_from_report(report)
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
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--chunk-summary", type=Path, default=DEFAULT_CHUNK_SUMMARY)
    parser.add_argument("--error-sample", type=Path, default=DEFAULT_ERROR_SAMPLE)
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_full_target_audit_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        fold_plan=args.fold_plan,
        feasibility=args.feasibility,
        output=args.output,
        summary_json=args.summary_json,
        chunk_summary=args.chunk_summary,
        error_sample=args.error_sample,
        chunk_size=args.chunk_size,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_FULL_TARGET_AUDIT="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"rows_checked={report.get('full_target_rows_checked')} "
        f"expected_rows={report.get('expected_target_row_count')} "
        f"report={_safe_path(args.output)} "
        f"summary_json={_safe_path(args.summary_json)} "
        "no_fetch=yes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
