from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, project_relative_path
from src.evaluation import stage04_annotation_capture as capture
from src.evaluation import stage04_annotation_label_gate as gate


REPORT_VERSION = "stage04_wp5_annotation_operations_v1"
INDEX_ID = "STAGE04-WP5"
SOURCE_WP3_INDEX_ID = "STAGE04-WP3"
SOURCE_WP4_INDEX_ID = "STAGE04-WP4"
MAX_REVIEW_QUEUE_ROWS = 100

DEFAULT_SPLIT_REGISTRY_PATH = Path("reports/stage04/split_registry.json")
DEFAULT_WP3_REPORT_PATH = Path("reports/stage04/stage04_wp3_annotation_label_gate_report.json")
DEFAULT_WP4_REPORT_PATH = Path("reports/stage04/stage04_wp4_annotation_capture_report.json")
DEFAULT_ANNOTATION_LEDGER_PATH = Path("reports/stage04/prospective_break_annotation.local.jsonl")
DEFAULT_OUTPUT_PATH = Path("reports/stage04/stage04_wp5_annotation_operations_report.md")
DEFAULT_SUMMARY_JSON_PATH = Path("reports/stage04/stage04_wp5_annotation_operations_report.json")
DEFAULT_SAMPLE_CSV_PATH = Path("reports/stage04/stage04_wp5_annotation_operations_sample.csv")

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "model_retrained": "no",
    "hmm_hsmm_training_changed": "no",
    "hazard_model_changed": "no",
    "threshold_tuning": "no",
    "final_holdout_consumed": "no",
    "decision_engine_output": "no",
    "trading_output": "no",
    "duckdb_schema_changed": "no",
    "duckdb_committed": "no",
}
ALLOWED_CAPTURE_STATUS = {"candidate_created", "no_candidate", "appended", "blocked"}
ALLOWED_CAPTURE_MODES = {"dry-run", "append"}
SAFE_MARKDOWN_NOTICE = (
    "This report summarizes annotation operations only. It does not evaluate outcomes, compute returns, "
    "provide trading output, define a decision layer, or consume final holdout."
)


@dataclass(frozen=True)
class AnnotationOperationsConfig:
    split_registry_path: Path = DEFAULT_SPLIT_REGISTRY_PATH
    wp3_report_path: Path = DEFAULT_WP3_REPORT_PATH
    wp4_report_path: Path = DEFAULT_WP4_REPORT_PATH
    annotation_ledger_path: Path = DEFAULT_ANNOTATION_LEDGER_PATH
    git_root: Path = PROJECT_ROOT
    no_fetch: bool = True


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value) if not isinstance(value, (list, tuple, dict, pd.Series, pd.DataFrame)) else False:
        return None
    return value


def _public_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    raw = Path(path)
    if not raw.is_absolute():
        return raw.as_posix()
    return project_relative_path(raw)


def _forbidden_terms() -> tuple[str, ...]:
    return gate._forbidden_output_terms()


def _assert_no_forbidden_terms(payload: Any, markdown: str = "") -> None:
    serialized = json.dumps(_json_safe(payload), ensure_ascii=False) + "\n" + markdown
    if any(term in serialized for term in _forbidden_terms()):
        raise ValueError("Stage04-WP5 output contains forbidden exact wording")


def _load_json_object(path: Path) -> dict[str, Any]:
    return gate.load_json_object(path)


def _as_date(value: Any) -> date | None:
    return gate._as_date(value)


def _is_gitignored(path: Path, *, git_root: Path = PROJECT_ROOT) -> str:
    try:
        target = path if not path.is_absolute() else path.relative_to(git_root)
    except ValueError:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--", target.as_posix()],
            cwd=git_root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return "unknown"
    return "yes" if result.returncode == 0 else "no"


def validate_wp3_report(wp3_report: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    return capture.validate_wp3_report(wp3_report)


def validate_wp4_report(wp4_report: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    causal = wp4_report.get("causal_boundary_summary", {}) if isinstance(wp4_report, Mapping) else {}
    append_summary = wp4_report.get("append_summary", {}) if isinstance(wp4_report, Mapping) else {}

    if not wp4_report:
        issues.append("Stage04-WP4 report not found")
    if wp4_report and wp4_report.get("index_id") != SOURCE_WP4_INDEX_ID:
        issues.append("Stage04-WP4 report index_id mismatch")
    if wp4_report and wp4_report.get("status") not in {"pass", "defer"}:
        issues.append("Stage04-WP4 report status is not pass or defer")
    if wp4_report and wp4_report.get("final_holdout_consumed") != "no":
        issues.append("Stage04-WP4 report consumed final holdout")
    if wp4_report and gate._as_int(wp4_report.get("final_holdout_consumption_count"), default=-1) != 0:
        issues.append("Stage04-WP4 final holdout consumption count is not zero")
    if wp4_report and wp4_report.get("threshold_tuning_after_lock") != "no":
        issues.append("Stage04-WP4 threshold tuning flag is not no")
    if wp4_report and wp4_report.get("model_retraining_after_lock") != "no":
        issues.append("Stage04-WP4 model retraining flag is not no")
    if wp4_report and causal.get("performance_metrics_computed") != "no":
        issues.append("Stage04-WP4 performance metric boundary is not no")
    if wp4_report and causal.get("returns_or_outcomes_computed") != "no":
        issues.append("Stage04-WP4 returns or outcomes boundary is not no")

    appended_count = gate._as_int(append_summary.get("appended_record_count"), default=-1)
    if wp4_report and appended_count not in {0, 1}:
        issues.append("Stage04-WP4 appended record count is outside allowed bounds")
    if wp4_report and wp4_report.get("mode") not in ALLOWED_CAPTURE_MODES:
        issues.append("Stage04-WP4 capture mode is unsupported")
    if wp4_report and wp4_report.get("capture_status") not in ALLOWED_CAPTURE_STATUS:
        issues.append("Stage04-WP4 capture status is unsupported")

    summary = {
        "status": wp4_report.get("status") if wp4_report else "missing",
        "index_id": wp4_report.get("index_id") if wp4_report else None,
        "report_version": wp4_report.get("report_version") if wp4_report else None,
        "mode": wp4_report.get("mode") if wp4_report else None,
        "capture_status": wp4_report.get("capture_status") if wp4_report else None,
        "final_holdout_consumed": wp4_report.get("final_holdout_consumed") if wp4_report else None,
        "final_holdout_consumption_count": wp4_report.get("final_holdout_consumption_count") if wp4_report else None,
        "threshold_tuning_after_lock": wp4_report.get("threshold_tuning_after_lock") if wp4_report else None,
        "model_retraining_after_lock": wp4_report.get("model_retraining_after_lock") if wp4_report else None,
        "performance_metrics_computed": causal.get("performance_metrics_computed"),
        "returns_or_outcomes_computed": causal.get("returns_or_outcomes_computed"),
        "appended_record_count": appended_count if append_summary else None,
    }
    return summary, issues


def _parse_annotation_ledger(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[str]]:
    records: list[dict[str, Any]] = []
    invalid_entries: list[dict[str, Any]] = []
    issues: list[str] = []
    line_count = 0
    blank_line_count = 0
    template_record_count = 0

    if path.exists():
        for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            line_count += 1
            if not raw_line.strip():
                blank_line_count += 1
                continue
            try:
                payload = json.loads(raw_line)
            except json.JSONDecodeError:
                issue = f"annotation ledger line {line_number} is not valid JSON"
                issues.append(issue)
                invalid_entries.append({"line_number": line_number, "issue": issue, "record_type": None})
                continue
            if not isinstance(payload, dict):
                issue = f"annotation ledger line {line_number} is not a JSON object"
                issues.append(issue)
                invalid_entries.append({"line_number": line_number, "issue": issue, "record_type": None})
                continue
            record_type = payload.get("record_type")
            if record_type == "template":
                template_record_count += 1
                continue
            if record_type not in gate.ALLOWED_RECORD_TYPES:
                issue = f"annotation ledger line {line_number} has unsupported record_type"
                issues.append(issue)
                invalid_entries.append({"line_number": line_number, "issue": issue, "record_type": record_type})
                continue
            records.append({"record_index": len(records) + 1, "line_number": line_number, "record": payload})

    summary = {
        "annotation_ledger_path": _public_path(path),
        "ledger_exists": "yes" if path.exists() else "no",
        "total_line_count": line_count,
        "blank_line_count": blank_line_count,
        "template_record_count": template_record_count,
        "annotation_record_count": len(records),
        "invalid_line_count": len(issues),
        "allowed_record_types": sorted(gate.ALLOWED_RECORD_TYPES),
    }
    return records, invalid_entries, summary, issues


def _count_values(records: list[dict[str, Any]], field: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = record.get(field)
        if value in {None, ""}:
            continue
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _date_min_max(records: list[dict[str, Any]], field: str) -> tuple[str | None, str | None]:
    values = sorted(str(record[field]) for record in records if record.get(field))
    return (values[0], values[-1]) if values else (None, None)


def _validated_records(
    raw_records: list[dict[str, Any]],
    *,
    evidence_cutoff_date: date | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    validated, issues = gate.validate_annotation_records(raw_records, evidence_cutoff_date=evidence_cutoff_date)
    sanitized: list[dict[str, Any]] = []
    for record in validated:
        raw = record.get("raw_record", {})
        sanitized.append(
            {
                "record_index": record.get("record_index"),
                "line_number": record.get("line_number"),
                "record_type": record.get("record_type"),
                "annotation_date": record.get("annotation_date"),
                "diagnostic_trade_date": record.get("diagnostic_trade_date"),
                "break_warning_level": record.get("break_warning_level"),
                "boundary_status": record.get("boundary_status"),
                "boundary_issues": list(record.get("boundary_issues", [])),
                "available_component_count": raw.get("available_component_count") if isinstance(raw, Mapping) else None,
            }
        )
    return sanitized, issues


def _operations_rollup(
    validated_records: list[dict[str, Any]],
    *,
    ledger_summary: dict[str, Any],
    evidence_cutoff_date: date | None,
) -> dict[str, Any]:
    annotation_dates = _date_min_max(validated_records, "annotation_date")
    diagnostic_dates = _date_min_max(validated_records, "diagnostic_trade_date")
    records_after_cutoff = 0
    records_on_or_before_cutoff = 0
    for record in validated_records:
        diagnostic_date = _as_date(record.get("diagnostic_trade_date"))
        if diagnostic_date and evidence_cutoff_date and diagnostic_date > evidence_cutoff_date:
            records_after_cutoff += 1
        elif diagnostic_date and evidence_cutoff_date and diagnostic_date <= evidence_cutoff_date:
            records_on_or_before_cutoff += 1

    boundary_valid = sum(1 for record in validated_records if record.get("boundary_status") == "valid")
    boundary_blocked = sum(1 for record in validated_records if record.get("boundary_status") != "valid")
    return {
        "ledger_exists": ledger_summary.get("ledger_exists"),
        "ledger_gitignored": ledger_summary.get("ledger_gitignored"),
        "total_line_count": ledger_summary.get("total_line_count", 0),
        "annotation_record_count": ledger_summary.get("annotation_record_count", 0),
        "template_record_count": ledger_summary.get("template_record_count", 0),
        "invalid_line_count": ledger_summary.get("invalid_line_count", 0),
        "boundary_valid_record_count": boundary_valid,
        "boundary_blocked_record_count": boundary_blocked,
        "records_after_cutoff_count": records_after_cutoff,
        "records_on_or_before_cutoff_count": records_on_or_before_cutoff,
        "warning_level_counts": _count_values(validated_records, "break_warning_level"),
        "record_type_counts": _count_values(validated_records, "record_type"),
        "annotation_date_min": annotation_dates[0],
        "annotation_date_max": annotation_dates[1],
        "diagnostic_trade_date_min": diagnostic_dates[0],
        "diagnostic_trade_date_max": diagnostic_dates[1],
    }


def _label_completeness_rollup(wp3_report: Mapping[str, Any]) -> dict[str, Any]:
    label_summary = wp3_report.get("label_completeness_summary", {}) if wp3_report else {}
    status_counts = label_summary.get("label_completeness_status_counts", {}) if isinstance(label_summary, Mapping) else {}
    return {
        "prospective_validation_status": wp3_report.get("prospective_validation_status") if wp3_report else None,
        "label_complete_count": label_summary.get("complete_record_count", 0),
        "label_pending_count": label_summary.get("pending_record_count", 0),
        "label_unknown_db_missing_count": label_summary.get("unknown_db_missing_record_count", 0),
        "pre_lock_violation_count": label_summary.get("pre_lock_violation_record_count", 0),
        "invalid_date_count": label_summary.get("invalid_date_record_count", 0),
        "required_horizons": label_summary.get("required_horizons", gate.EXPECTED_HORIZONS),
        "label_completeness_status_counts": status_counts if isinstance(status_counts, Mapping) else {},
    }


def _label_lookup(wp3_report: Mapping[str, Any]) -> dict[int, str]:
    sample = wp3_report.get("annotation_record_sample", []) if wp3_report else []
    lookup: dict[int, str] = {}
    if isinstance(sample, list):
        for row in sample:
            if not isinstance(row, Mapping):
                continue
            index = gate._as_int(row.get("record_index"), default=0)
            if index:
                lookup[index] = str(row.get("label_completeness_status") or "")
    return lookup


def _review_status(record: Mapping[str, Any], label_status: str | None) -> tuple[str, str]:
    if record.get("boundary_status") != "valid":
        return "boundary_fix_required", "boundary validation issue requires operator review"
    if label_status == "complete":
        return "ready_for_operator_review", "required label horizons are complete"
    if label_status in {"pending", "unknown_db_missing"}:
        return "waiting_for_label_horizon", "label completeness is not yet confirmed"
    return "awaiting_annotation", "annotation record is awaiting label completeness status"


def _review_queue(
    validated_records: list[dict[str, Any]],
    invalid_entries: list[dict[str, Any]],
    *,
    wp3_report: Mapping[str, Any],
) -> list[dict[str, Any]]:
    label_by_index = _label_lookup(wp3_report)
    rows: list[dict[str, Any]] = []
    for invalid in invalid_entries:
        rows.append(
            {
                "record_index": None,
                "line_number": invalid.get("line_number"),
                "record_type": invalid.get("record_type"),
                "annotation_date": None,
                "diagnostic_trade_date": None,
                "break_warning_level": None,
                "boundary_status": "blocked",
                "label_completeness_status": None,
                "review_queue_status": "boundary_fix_required",
                "note": "ledger line cannot be used for operations rollup",
            }
        )
    for record in validated_records:
        label_status = label_by_index.get(int(record.get("record_index") or 0)) or None
        review_status, note = _review_status(record, label_status)
        rows.append(
            {
                "record_index": record.get("record_index"),
                "line_number": record.get("line_number"),
                "record_type": record.get("record_type"),
                "annotation_date": record.get("annotation_date"),
                "diagnostic_trade_date": record.get("diagnostic_trade_date"),
                "break_warning_level": record.get("break_warning_level"),
                "boundary_status": record.get("boundary_status"),
                "label_completeness_status": label_status,
                "review_queue_status": review_status,
                "note": note,
            }
        )

    def sort_key(row: Mapping[str, Any]) -> tuple[int, int, str]:
        status = str(row.get("review_queue_status") or "")
        rank = {
            "boundary_fix_required": 0,
            "ready_for_operator_review": 1,
            "waiting_for_label_horizon": 2,
            "awaiting_annotation": 3,
        }.get(status, 4)
        annotation_date = str(row.get("annotation_date") or "")
        return rank, -int(annotation_date.replace("-", "") or 0), str(row.get("record_index") or row.get("line_number") or "")

    return sorted(rows, key=sort_key)[:MAX_REVIEW_QUEUE_ROWS]


def _status_from_inputs(
    *,
    blocking_issues: list[str],
    wp3_report: Mapping[str, Any],
    operations_rollup: Mapping[str, Any],
) -> tuple[str, str, list[str]]:
    if blocking_issues:
        return "blocked", "blocked", []
    if int(operations_rollup.get("annotation_record_count") or 0) == 0:
        return "pass", "no_annotations_yet", []
    defer_reasons: list[str] = []
    if wp3_report.get("status") == "defer":
        defer_reasons.append("Stage04-WP3 label completeness gate is defer")
    label_summary = wp3_report.get("label_completeness_summary", {}) if wp3_report else {}
    if int(label_summary.get("unknown_db_missing_record_count") or 0) > 0:
        defer_reasons.append("Stage04-WP3 reports unknown label completeness because local DB was missing")
    if defer_reasons:
        return "defer", "annotation_collection_defer", defer_reasons
    return "pass", "annotation_collection_active", []


def evaluate_annotation_operations(config: AnnotationOperationsConfig) -> dict[str, Any]:
    registry = _load_json_object(config.split_registry_path)
    wp3_report = _load_json_object(config.wp3_report_path)
    wp4_report = _load_json_object(config.wp4_report_path)
    split_summary, split_issues = gate.validate_split_registry_lock(registry)
    wp3_summary, wp3_issues = validate_wp3_report(wp3_report)
    wp4_summary, wp4_issues = validate_wp4_report(wp4_report)
    evidence_cutoff = _as_date(registry.get("evidence_cutoff_date")) if registry else None

    raw_records, invalid_entries, ledger_summary, ledger_issues = _parse_annotation_ledger(config.annotation_ledger_path)
    ledger_summary["ledger_gitignored"] = _is_gitignored(config.annotation_ledger_path, git_root=config.git_root)
    record_rows, record_issues = _validated_records(raw_records, evidence_cutoff_date=evidence_cutoff)
    operations = _operations_rollup(record_rows, ledger_summary=ledger_summary, evidence_cutoff_date=evidence_cutoff)
    label_rollup = _label_completeness_rollup(wp3_report)
    review_rows = _review_queue(record_rows, invalid_entries, wp3_report=wp3_report)

    blocking_issues = list(split_issues) + list(wp3_issues) + list(wp4_issues) + list(ledger_issues) + list(record_issues)
    if ledger_summary["ledger_gitignored"] != "yes":
        blocking_issues.append("local annotation ledger is not confirmed gitignored")
    if operations["boundary_blocked_record_count"]:
        blocking_issues.append("local annotation ledger contains boundary-blocked records")
    if int(label_rollup.get("pre_lock_violation_count") or 0) > 0:
        blocking_issues.append("Stage04-WP3 reports pre-lock annotation records")
    if int(label_rollup.get("invalid_date_count") or 0) > 0:
        blocking_issues.append("Stage04-WP3 reports invalid annotation dates")
    blocking_issues = sorted(set(blocking_issues))
    status, operations_status, defer_reasons = _status_from_inputs(
        blocking_issues=blocking_issues,
        wp3_report=wp3_report,
        operations_rollup=operations,
    )

    summary = {
        "status": status,
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "split_registry_lock_summary": split_summary,
        "wp3_source_summary": wp3_summary,
        "wp4_source_summary": wp4_summary,
        "boundary_flags": BOUNDARY_FLAGS,
        "local_ledger_summary": ledger_summary,
        "operations_rollup": operations,
        "label_completeness_rollup": label_rollup,
        "review_queue_sample": review_rows,
        "operations_status": operations_status,
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
        "causal_boundary_summary": {
            "external_data_fetch": "no",
            "performance_metrics_computed": "no",
            "returns_or_outcomes_computed": "no",
            "threshold_tuning_after_lock": "no",
            "model_retraining_after_lock": "no",
            "hmm_hsmm_training_changed": "no",
            "hazard_model_changed": "no",
            "final_holdout_consumed": "no",
            "local_db_required": "no",
            "label_completeness_source": "Stage04-WP3 report only",
        },
        "blocking_issues": blocking_issues,
        "defer_reasons": defer_reasons,
        "recommended_next_stage": "Continue annotation-only collection and rerun Stage04-WP3 before any later reviewed work package changes the Stage04 operating rule.",
    }
    _assert_no_forbidden_terms(summary)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Stage04-WP5 Annotation Operations Rollup",
        "",
        f"- status: {summary.get('status')}",
        f"- report_version: {summary.get('report_version')}",
        f"- index_id: {summary.get('index_id')}",
        f"- operations_status: {summary.get('operations_status')}",
        "",
        SAFE_MARKDOWN_NOTICE,
        "",
        "## Local Ledger Summary",
    ]
    for key, value in summary.get("local_ledger_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Operations Rollup"])
    for key, value in summary.get("operations_rollup", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Label Completeness Rollup"])
    for key, value in summary.get("label_completeness_rollup", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Review Queue Sample"])
    rows = summary.get("review_queue_sample", [])
    if rows:
        lines.append("| record_index | record_type | annotation_date | diagnostic_trade_date | break_warning_level | boundary_status | label_completeness_status | review_queue_status | note |")
        lines.append("|---:|---|---:|---:|---|---|---|---|---|")
        for row in rows:
            lines.append(
                f"| {row.get('record_index')} | {row.get('record_type')} | {row.get('annotation_date')} | "
                f"{row.get('diagnostic_trade_date')} | {row.get('break_warning_level')} | {row.get('boundary_status')} | "
                f"{row.get('label_completeness_status')} | {row.get('review_queue_status')} | {row.get('note')} |"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Boundary Flags"])
    for key, value in summary.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")

    if summary.get("blocking_issues"):
        lines.extend(["", "## Blocking Issues"])
        for issue in summary.get("blocking_issues", []):
            lines.append(f"- {issue}")
    if summary.get("defer_reasons"):
        lines.extend(["", "## Defer Reasons"])
        for reason in summary.get("defer_reasons", []):
            lines.append(f"- {reason}")

    lines.extend(["", "## Recommended Next Stage", str(summary.get("recommended_next_stage", "")), ""])
    markdown = "\n".join(lines)
    _assert_no_forbidden_terms(summary, markdown)
    return markdown


def _sample_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    columns = [
        "record_index",
        "record_type",
        "annotation_date",
        "diagnostic_trade_date",
        "break_warning_level",
        "boundary_status",
        "label_completeness_status",
        "review_queue_status",
        "note",
    ]
    return pd.DataFrame([{key: row.get(key) for key in columns} for row in rows[:MAX_REVIEW_QUEUE_ROWS]], columns=columns)


def write_outputs(
    summary: dict[str, Any],
    *,
    output: Path,
    summary_json: Path,
    sample_csv: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    sample_csv.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(summary)
    sample = _sample_frame(summary.get("review_queue_sample", []))
    output.write_text(markdown, encoding="utf-8")
    summary_json.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sample.to_csv(sample_csv, index=False)


def run_from_paths(
    *,
    split_registry: Path = DEFAULT_SPLIT_REGISTRY_PATH,
    wp3_report: Path = DEFAULT_WP3_REPORT_PATH,
    wp4_report: Path = DEFAULT_WP4_REPORT_PATH,
    annotation_ledger: Path = DEFAULT_ANNOTATION_LEDGER_PATH,
    output: Path = DEFAULT_OUTPUT_PATH,
    summary_json: Path = DEFAULT_SUMMARY_JSON_PATH,
    sample_csv: Path = DEFAULT_SAMPLE_CSV_PATH,
    no_fetch: bool = True,
    git_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    summary = evaluate_annotation_operations(
        AnnotationOperationsConfig(
            split_registry_path=split_registry,
            wp3_report_path=wp3_report,
            wp4_report_path=wp4_report,
            annotation_ledger_path=annotation_ledger,
            git_root=git_root,
            no_fetch=no_fetch,
        )
    )
    write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage04-WP5 annotation operations rollup")
    parser.add_argument("--split-registry", default=str(DEFAULT_SPLIT_REGISTRY_PATH))
    parser.add_argument("--wp3-report", default=str(DEFAULT_WP3_REPORT_PATH))
    parser.add_argument("--wp4-report", default=str(DEFAULT_WP4_REPORT_PATH))
    parser.add_argument("--annotation-ledger", default=str(DEFAULT_ANNOTATION_LEDGER_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON_PATH))
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV_PATH))
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_from_paths(
        split_registry=Path(args.split_registry),
        wp3_report=Path(args.wp3_report),
        wp4_report=Path(args.wp4_report),
        annotation_ledger=Path(args.annotation_ledger),
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        sample_csv=Path(args.sample_csv),
        no_fetch=args.no_fetch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
