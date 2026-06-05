from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, Mapping

from src.config import PROJECT_ROOT, project_relative_path
from src.evaluation import stage04_annotation_label_gate as gate


REPORT_VERSION = "stage04_wp4_annotation_capture_v1"
INDEX_ID = "STAGE04-WP4"
SOURCE_WP1_INDEX_ID = "STAGE04-WP1"
SOURCE_WP2_INDEX_ID = "STAGE04-WP2"
SOURCE_WP3_INDEX_ID = "STAGE04-WP3"

DEFAULT_SPLIT_REGISTRY_PATH = Path("reports/stage04/split_registry.json")
DEFAULT_WP1_REPORT_PATH = Path("reports/stage04/stage04_wp1_break_detector_report.json")
DEFAULT_WP2_REPORT_PATH = Path("reports/stage04/stage04_wp2_break_casebook_report.json")
DEFAULT_WP3_REPORT_PATH = Path("reports/stage04/stage04_wp3_annotation_label_gate_report.json")
DEFAULT_ANNOTATION_LEDGER_PATH = Path("reports/stage04/prospective_break_annotation.local.jsonl")
DEFAULT_OUTPUT_PATH = Path("reports/stage04/stage04_wp4_annotation_capture_report.md")
DEFAULT_SUMMARY_JSON_PATH = Path("reports/stage04/stage04_wp4_annotation_capture_report.json")
DEFAULT_SAMPLE_JSONL_PATH = Path("reports/stage04/stage04_wp4_annotation_capture_sample.jsonl")

CaptureMode = Literal["dry-run", "append"]
CaptureSource = Literal["latest_wp1", "casebook_episode", "manual"]

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
RECORD_BOUNDARY_FLAGS = dict(gate.REQUIRED_RECORD_BOUNDARY_FLAGS)
ALLOWED_WARNING_LEVELS = set(gate.ALLOWED_WARNING_LEVELS)
NO_CANDIDATE_LEVELS = {"normal", "insufficient_data", "insufficient_history", ""}
DEFAULT_FORBIDDEN_USE_NOTICE = "Research annotation only; diagnostic review note with no trading output."
SAFE_MARKDOWN_NOTICE = (
    "This report creates or previews local annotation records only. It does not evaluate outcomes, "
    "compute returns, provide trading output, define a decision layer, or consume final holdout."
)


@dataclass(frozen=True)
class AnnotationCaptureConfig:
    split_registry_path: Path = DEFAULT_SPLIT_REGISTRY_PATH
    wp1_report_path: Path = DEFAULT_WP1_REPORT_PATH
    wp2_report_path: Path = DEFAULT_WP2_REPORT_PATH
    wp3_report_path: Path = DEFAULT_WP3_REPORT_PATH
    annotation_ledger_path: Path = DEFAULT_ANNOTATION_LEDGER_PATH
    mode: CaptureMode = "dry-run"
    source: CaptureSource = "latest_wp1"
    episode_id: str | None = None
    diagnostic_trade_date: str | None = None
    break_warning_level: str | None = None
    component_stress_labels: str | None = None
    available_component_count: int | None = None
    analyst_annotation: str = "needs_context"
    observed_market_context: str = ""
    followup_required: str = "yes"
    annotation_date: str | None = None
    no_fetch: bool = True
    git_root: Path = PROJECT_ROOT


def _json_safe(value: Any) -> Any:
    return gate._json_safe(value)


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
        raise ValueError("Stage04-WP4 output contains forbidden exact wording")


def _load_json_object(path: Path) -> dict[str, Any]:
    return gate.load_json_object(path)


def _as_date(value: Any) -> date | None:
    return gate._as_date(value)


def _as_int(value: Any) -> int | None:
    if value in {None, ""}:
        return None
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return None


def _record_value_has_forbidden_terms(value: Any) -> bool:
    return gate._record_value_has_forbidden_terms(value)


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


def _ledger_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return len(path.read_text(encoding="utf-8").splitlines())


def _local_ledger_summary(path: Path, *, git_root: Path) -> dict[str, Any]:
    return {
        "annotation_ledger_path": _public_path(path),
        "annotation_ledger_exists": "yes" if path.exists() else "no",
        "local_annotations_gitignored": _is_gitignored(path, git_root=git_root),
        "line_count": _ledger_line_count(path),
    }


def validate_wp3_report(wp3_report: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    causal = wp3_report.get("causal_boundary_summary", {}) if isinstance(wp3_report, Mapping) else {}
    if not wp3_report:
        issues.append("Stage04-WP3 report not found")
    if wp3_report and wp3_report.get("status") not in {"pass", "defer"}:
        issues.append("Stage04-WP3 report status is not pass or defer")
    if wp3_report and wp3_report.get("index_id") != SOURCE_WP3_INDEX_ID:
        issues.append("Stage04-WP3 report index_id mismatch")
    if wp3_report and wp3_report.get("final_holdout_consumed") != "no":
        issues.append("Stage04-WP3 report consumed final holdout")
    if wp3_report and gate._as_int(wp3_report.get("final_holdout_consumption_count"), default=-1) != 0:
        issues.append("Stage04-WP3 final holdout consumption count is not zero")
    if wp3_report and wp3_report.get("threshold_tuning_after_lock") != "no":
        issues.append("Stage04-WP3 threshold tuning flag is not no")
    if wp3_report and wp3_report.get("model_retraining_after_lock") != "no":
        issues.append("Stage04-WP3 model retraining flag is not no")
    if wp3_report and causal.get("performance_metrics_computed") != "no":
        issues.append("Stage04-WP3 performance metric boundary is not no")
    if wp3_report and causal.get("returns_or_outcomes_computed") != "no":
        issues.append("Stage04-WP3 returns or outcomes boundary is not no")

    summary = {
        "status": wp3_report.get("status") if wp3_report else "missing",
        "index_id": wp3_report.get("index_id") if wp3_report else None,
        "report_version": wp3_report.get("report_version") if wp3_report else None,
        "prospective_validation_status": wp3_report.get("prospective_validation_status") if wp3_report else None,
        "final_holdout_consumed": wp3_report.get("final_holdout_consumed") if wp3_report else None,
        "final_holdout_consumption_count": wp3_report.get("final_holdout_consumption_count") if wp3_report else None,
        "threshold_tuning_after_lock": wp3_report.get("threshold_tuning_after_lock") if wp3_report else None,
        "model_retraining_after_lock": wp3_report.get("model_retraining_after_lock") if wp3_report else None,
        "performance_metrics_computed": causal.get("performance_metrics_computed"),
        "returns_or_outcomes_computed": causal.get("returns_or_outcomes_computed"),
    }
    return summary, issues


def _base_annotation_record(config: AnnotationCaptureConfig, *, source_record: dict[str, Any]) -> dict[str, Any]:
    annotation_date = config.annotation_date or date.today().isoformat()
    return {
        "schema_version": gate.SCHEMA_VERSION,
        "record_type": "annotation",
        "annotation_date": annotation_date,
        "diagnostic_trade_date": str(source_record.get("diagnostic_trade_date") or ""),
        "break_warning_level": str(source_record.get("break_warning_level") or ""),
        "component_stress_labels": str(source_record.get("component_stress_labels") or ""),
        "available_component_count": _as_int(source_record.get("available_component_count")) or 0,
        "analyst_annotation": config.analyst_annotation,
        "observed_market_context": config.observed_market_context,
        "followup_required": config.followup_required,
        "forbidden_use_notice": DEFAULT_FORBIDDEN_USE_NOTICE,
        "boundary_flags": dict(RECORD_BOUNDARY_FLAGS),
    }


def _candidate_from_latest_wp1(
    wp1_report: Mapping[str, Any],
    config: AnnotationCaptureConfig,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    issues: list[str] = []
    if not wp1_report:
        return None, ["Stage04-WP1 report not found"], {"status": "missing"}
    if wp1_report.get("index_id") != SOURCE_WP1_INDEX_ID:
        issues.append("Stage04-WP1 report index_id mismatch")
    if wp1_report.get("status") != "pass":
        issues.append("Stage04-WP1 report status is not pass")
    latest = wp1_report.get("latest_break_warning") or {}
    if not isinstance(latest, Mapping) or not latest:
        issues.append("Stage04-WP1 latest diagnostic snapshot is missing")
        latest = {}
    level = str(latest.get("break_warning_level") or "")
    source_summary = {
        "status": wp1_report.get("status"),
        "index_id": wp1_report.get("index_id"),
        "report_version": wp1_report.get("report_version"),
        "latest_diagnostic_trade_date": latest.get("trade_date"),
        "latest_break_warning_level": level or None,
    }
    if issues:
        return None, issues, source_summary
    if level in NO_CANDIDATE_LEVELS:
        return None, [], source_summary
    if level not in ALLOWED_WARNING_LEVELS:
        return None, [f"Stage04-WP1 latest warning level is unsupported: {level}"], source_summary
    source_record = {
        "diagnostic_trade_date": latest.get("trade_date"),
        "break_warning_level": level,
        "component_stress_labels": latest.get("component_stress_labels") or "",
        "available_component_count": latest.get("available_component_count"),
    }
    return _base_annotation_record(config, source_record=source_record), [], source_summary


def _candidate_from_casebook_episode(
    wp2_report: Mapping[str, Any],
    config: AnnotationCaptureConfig,
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    issues: list[str] = []
    if not config.episode_id:
        issues.append("casebook_episode source requires episode_id")
    if not wp2_report:
        return None, issues + ["Stage04-WP2 report not found"], {"status": "missing"}
    if wp2_report.get("index_id") != SOURCE_WP2_INDEX_ID:
        issues.append("Stage04-WP2 report index_id mismatch")
    if wp2_report.get("status") != "pass":
        issues.append("Stage04-WP2 report status is not pass")
    episodes = wp2_report.get("casebook_sample") or []
    if not isinstance(episodes, list):
        issues.append("Stage04-WP2 casebook_sample is not a list")
        episodes = []
    selected = None
    for episode in episodes:
        if isinstance(episode, Mapping) and str(episode.get("episode_id")) == str(config.episode_id):
            selected = episode
            break
    if config.episode_id and selected is None:
        issues.append("casebook episode was not found")
    source_summary = {
        "status": wp2_report.get("status"),
        "index_id": wp2_report.get("index_id"),
        "report_version": wp2_report.get("report_version"),
        "episode_id": config.episode_id,
        "casebook_sample_count": len(episodes),
    }
    if issues:
        return None, issues, source_summary
    assert selected is not None
    labels = selected.get("peak_component_stress_labels") or selected.get("first_component_stress_labels") or ""
    source_record = {
        "diagnostic_trade_date": selected.get("end_date"),
        "break_warning_level": selected.get("peak_warning_level"),
        "component_stress_labels": labels,
        "available_component_count": selected.get("available_component_count_max"),
    }
    return _base_annotation_record(config, source_record=source_record), [], source_summary


def _candidate_from_manual(config: AnnotationCaptureConfig) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    missing: list[str] = []
    if not config.diagnostic_trade_date:
        missing.append("diagnostic_trade_date")
    if not config.break_warning_level:
        missing.append("break_warning_level")
    if not config.component_stress_labels:
        missing.append("component_stress_labels")
    if config.available_component_count is None:
        missing.append("available_component_count")
    source_summary = {
        "manual_fields_supplied": "no" if missing else "yes",
        "missing_fields": missing,
    }
    if missing:
        return None, [f"manual source missing required fields: {', '.join(missing)}"], source_summary
    source_record = {
        "diagnostic_trade_date": config.diagnostic_trade_date,
        "break_warning_level": config.break_warning_level,
        "component_stress_labels": config.component_stress_labels,
        "available_component_count": config.available_component_count,
    }
    return _base_annotation_record(config, source_record=source_record), [], source_summary


def build_candidate_record(
    config: AnnotationCaptureConfig,
    *,
    wp1_report: Mapping[str, Any],
    wp2_report: Mapping[str, Any],
) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    if config.source == "latest_wp1":
        return _candidate_from_latest_wp1(wp1_report, config)
    if config.source == "casebook_episode":
        return _candidate_from_casebook_episode(wp2_report, config)
    if config.source == "manual":
        return _candidate_from_manual(config)
    return None, [f"unsupported source: {config.source}"], {"source": config.source}


def _validate_candidate(
    candidate: dict[str, Any] | None,
    *,
    evidence_cutoff_date: date | None,
) -> tuple[str, list[str]]:
    if candidate is None:
        return "not_applicable", []
    wrapped = [{"record_index": 1, "line_number": 1, "record": candidate}]
    _, issues = gate.validate_annotation_records(wrapped, evidence_cutoff_date=evidence_cutoff_date)
    return ("blocked" if issues else "valid"), [issue.replace("annotation record line 1: ", "candidate annotation record: ") for issue in issues]


def _candidate_public_preview(candidate: dict[str, Any] | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    context = str(candidate.get("observed_market_context") or "")

    def public_value(value: Any) -> Any:
        if isinstance(value, str) and _record_value_has_forbidden_terms(value):
            return "<redacted_forbidden_wording>"
        return value

    preview = {
        "schema_version": public_value(candidate.get("schema_version")),
        "record_type": public_value(candidate.get("record_type")),
        "annotation_date": public_value(candidate.get("annotation_date")),
        "diagnostic_trade_date": public_value(candidate.get("diagnostic_trade_date")),
        "break_warning_level": public_value(candidate.get("break_warning_level")),
        "component_stress_labels": public_value(candidate.get("component_stress_labels")),
        "available_component_count": candidate.get("available_component_count"),
        "analyst_annotation": public_value(candidate.get("analyst_annotation")),
        "followup_required": public_value(candidate.get("followup_required")),
        "forbidden_use_notice": public_value(candidate.get("forbidden_use_notice")),
        "boundary_flags": candidate.get("boundary_flags"),
        "observed_market_context_present": "yes" if context else "no",
        "observed_market_context_preview_chars": min(len(context), 80),
    }
    _assert_no_forbidden_terms(preview)
    return preview


def _append_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_json_safe(record), ensure_ascii=False, sort_keys=True) + "\n")


def _append_summary(
    config: AnnotationCaptureConfig,
    *,
    candidate: dict[str, Any] | None,
    candidate_validation_status: str,
    blocking_issues: list[str],
) -> tuple[dict[str, Any], list[str]]:
    summary = {
        "requested_mode": config.mode,
        "appended_record_count": 0,
        "ledger_created": "no",
        "append_attempted": "no",
        "append_blocked_reason": "not_applicable",
    }
    issues: list[str] = []
    if config.mode == "dry-run":
        return summary, issues
    if config.mode != "append":
        issues.append("unsupported capture mode")
        summary["append_blocked_reason"] = "unsupported capture mode"
        return summary, issues
    summary["append_attempted"] = "yes"
    if candidate is None:
        summary["append_blocked_reason"] = "no candidate annotation record"
        return summary, issues
    if candidate_validation_status != "valid":
        summary["append_blocked_reason"] = "candidate annotation record is invalid"
        return summary, issues
    if blocking_issues:
        summary["append_blocked_reason"] = "capture summary has blocking issues"
        return summary, issues

    ignored = _is_gitignored(config.annotation_ledger_path, git_root=config.git_root)
    if ignored != "yes":
        issue = "local annotation ledger is not confirmed gitignored"
        summary["append_blocked_reason"] = issue
        issues.append(issue)
        return summary, issues

    existed_before = config.annotation_ledger_path.exists()
    try:
        _append_record(config.annotation_ledger_path, candidate)
    except Exception as exc:
        summary["append_blocked_reason"] = f"append failed: {exc.__class__.__name__}"
        issues.append("append failed before writing a confirmed local annotation record")
        return summary, issues
    summary["appended_record_count"] = 1
    summary["ledger_created"] = "no" if existed_before else "yes"
    return summary, issues


def evaluate_annotation_capture(config: AnnotationCaptureConfig) -> dict[str, Any]:
    registry = _load_json_object(config.split_registry_path)
    wp1_report = _load_json_object(config.wp1_report_path)
    wp2_report = _load_json_object(config.wp2_report_path)
    wp3_report = _load_json_object(config.wp3_report_path)

    split_summary, split_issues = gate.validate_split_registry_lock(registry)
    wp3_summary, wp3_issues = validate_wp3_report(wp3_report)
    candidate, source_issues, source_summary = build_candidate_record(config, wp1_report=wp1_report, wp2_report=wp2_report)
    evidence_cutoff = _as_date(registry.get("evidence_cutoff_date")) if registry else None
    candidate_validation_status, candidate_issues = _validate_candidate(candidate, evidence_cutoff_date=evidence_cutoff)

    pre_append_ledger = _local_ledger_summary(config.annotation_ledger_path, git_root=config.git_root)
    blocking_issues = sorted(set(split_issues + wp3_issues + source_issues + candidate_issues))
    append_result, append_issues = _append_summary(
        config,
        candidate=candidate,
        candidate_validation_status=candidate_validation_status,
        blocking_issues=blocking_issues,
    )
    blocking_issues = sorted(set(blocking_issues + append_issues))
    post_append_ledger = _local_ledger_summary(config.annotation_ledger_path, git_root=config.git_root)

    if blocking_issues:
        capture_status = "blocked"
    elif append_result["appended_record_count"] == 1:
        capture_status = "appended"
    elif candidate is None:
        capture_status = "no_candidate"
    else:
        capture_status = "candidate_created"

    defer_reasons: list[str] = []
    if not blocking_issues and wp3_summary.get("status") == "defer":
        defer_reasons.append("Stage04-WP3 is defer, but capture can still preview or append local annotation records")
    status = "blocked" if blocking_issues else ("defer" if defer_reasons else "pass")

    summary = {
        "status": status,
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "mode": config.mode,
        "source": config.source,
        "capture_status": capture_status,
        "candidate_record_public_preview": _candidate_public_preview(candidate),
        "append_summary": append_result,
        "split_registry_lock_summary": split_summary,
        "wp3_source_summary": wp3_summary,
        "boundary_flags": BOUNDARY_FLAGS,
        "local_ledger_summary": {
            "before": pre_append_ledger,
            "after": post_append_ledger,
        },
        "source_summary": source_summary,
        "validation_summary": {
            "candidate_validation_status": candidate_validation_status,
            "candidate_issue_count": len(candidate_issues),
            "source_issue_count": len(source_issues),
            "split_registry_issue_count": len(split_issues),
            "wp3_issue_count": len(wp3_issues),
            "no_fetch_argument_accepted": "yes" if config.no_fetch else "not_required",
            "external_data_fetch": "no",
            "forbidden_exact_wording_check": "enforced",
            "post_cutoff_required": "yes",
            "performance_metrics_computed": "no",
            "returns_or_outcomes_computed": "no",
        },
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
        },
        "blocking_issues": blocking_issues,
        "defer_reasons": defer_reasons,
        "recommended_next_stage": "Run the Stage04-WP3 annotation label gate after local annotation records are collected.",
    }
    _assert_no_forbidden_terms(summary)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Stage04-WP4 Prospective Annotation Capture",
        "",
        f"- status: {summary.get('status')}",
        f"- report_version: {summary.get('report_version')}",
        f"- index_id: {summary.get('index_id')}",
        f"- mode: {summary.get('mode')}",
        f"- source: {summary.get('source')}",
        f"- capture_status: {summary.get('capture_status')}",
        "",
        SAFE_MARKDOWN_NOTICE,
        "",
        "## Candidate Public Preview",
    ]
    preview = summary.get("candidate_record_public_preview")
    if preview:
        for key, value in preview.items():
            if key == "boundary_flags":
                continue
            lines.append(f"- {key}: {value}")
        lines.append("- boundary_flags:")
        for key, value in preview.get("boundary_flags", {}).items():
            lines.append(f"  - {key}: {value}")
    else:
        lines.append("- none")

    lines.extend(["", "## Local Ledger Summary"])
    local = summary.get("local_ledger_summary", {})
    for label in ["before", "after"]:
        ledger = local.get(label, {})
        lines.append(f"- {label}:")
        for key, value in ledger.items():
            lines.append(f"  - {key}: {value}")

    lines.extend(["", "## Append Summary"])
    for key, value in summary.get("append_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Boundary Flags"])
    for key, value in summary.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Split Registry Lock Summary"])
    for key, value in summary.get("split_registry_lock_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## WP3 Source Summary"])
    for key, value in summary.get("wp3_source_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Validation Summary"])
    for key, value in summary.get("validation_summary", {}).items():
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


def _sample_record(summary: dict[str, Any]) -> dict[str, Any]:
    capture_status = summary.get("capture_status")
    preview = summary.get("candidate_record_public_preview")
    if capture_status in {"candidate_created", "appended"} and preview:
        row = dict(preview)
        row["sample_record_type"] = "candidate_public_preview"
        return row
    if capture_status == "no_candidate":
        return {
            "record_type": "no_candidate",
            "report_version": summary.get("report_version"),
            "index_id": summary.get("index_id"),
            "mode": summary.get("mode"),
            "source": summary.get("source"),
            "capture_status": capture_status,
        }
    return {
        "record_type": "blocked",
        "report_version": summary.get("report_version"),
        "index_id": summary.get("index_id"),
        "mode": summary.get("mode"),
        "source": summary.get("source"),
        "capture_status": capture_status,
        "blocking_issue_count": len(summary.get("blocking_issues", [])),
    }


def write_outputs(
    summary: dict[str, Any],
    *,
    output: Path,
    summary_json: Path,
    sample_jsonl: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    sample_jsonl.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(summary)
    sample_record = _sample_record(summary)
    _assert_no_forbidden_terms(sample_record)
    output.write_text(markdown, encoding="utf-8")
    summary_json.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sample_jsonl.write_text(json.dumps(_json_safe(sample_record), ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def run_from_paths(
    *,
    split_registry: Path = DEFAULT_SPLIT_REGISTRY_PATH,
    wp1_report: Path = DEFAULT_WP1_REPORT_PATH,
    wp2_report: Path = DEFAULT_WP2_REPORT_PATH,
    wp3_report: Path = DEFAULT_WP3_REPORT_PATH,
    annotation_ledger: Path = DEFAULT_ANNOTATION_LEDGER_PATH,
    output: Path = DEFAULT_OUTPUT_PATH,
    summary_json: Path = DEFAULT_SUMMARY_JSON_PATH,
    sample_jsonl: Path = DEFAULT_SAMPLE_JSONL_PATH,
    mode: CaptureMode = "dry-run",
    source: CaptureSource = "latest_wp1",
    episode_id: str | None = None,
    diagnostic_trade_date: str | None = None,
    break_warning_level: str | None = None,
    component_stress_labels: str | None = None,
    available_component_count: int | None = None,
    analyst_annotation: str = "needs_context",
    observed_market_context: str = "",
    followup_required: str = "yes",
    annotation_date: str | None = None,
    no_fetch: bool = True,
    git_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    summary = evaluate_annotation_capture(
        AnnotationCaptureConfig(
            split_registry_path=split_registry,
            wp1_report_path=wp1_report,
            wp2_report_path=wp2_report,
            wp3_report_path=wp3_report,
            annotation_ledger_path=annotation_ledger,
            mode=mode,
            source=source,
            episode_id=episode_id,
            diagnostic_trade_date=diagnostic_trade_date,
            break_warning_level=break_warning_level,
            component_stress_labels=component_stress_labels,
            available_component_count=available_component_count,
            analyst_annotation=analyst_annotation,
            observed_market_context=observed_market_context,
            followup_required=followup_required,
            annotation_date=annotation_date,
            no_fetch=no_fetch,
            git_root=git_root,
        )
    )
    write_outputs(summary, output=output, summary_json=summary_json, sample_jsonl=sample_jsonl)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage04-WP4 prospective annotation capture")
    parser.add_argument("--split-registry", default=str(DEFAULT_SPLIT_REGISTRY_PATH))
    parser.add_argument("--wp1-report", default=str(DEFAULT_WP1_REPORT_PATH))
    parser.add_argument("--wp2-report", default=str(DEFAULT_WP2_REPORT_PATH))
    parser.add_argument("--wp3-report", default=str(DEFAULT_WP3_REPORT_PATH))
    parser.add_argument("--annotation-ledger", default=str(DEFAULT_ANNOTATION_LEDGER_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON_PATH))
    parser.add_argument("--sample-jsonl", default=str(DEFAULT_SAMPLE_JSONL_PATH))
    parser.add_argument("--mode", choices=["dry-run", "append"], default="dry-run")
    parser.add_argument("--source", choices=["latest_wp1", "casebook_episode", "manual"], default="latest_wp1")
    parser.add_argument("--episode-id")
    parser.add_argument("--diagnostic-trade-date")
    parser.add_argument("--break-warning-level")
    parser.add_argument("--component-stress-labels")
    parser.add_argument("--available-component-count", type=int)
    parser.add_argument("--analyst-annotation", default="needs_context")
    parser.add_argument("--observed-market-context", default="")
    parser.add_argument("--followup-required", default="yes")
    parser.add_argument("--annotation-date")
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_from_paths(
        split_registry=Path(args.split_registry),
        wp1_report=Path(args.wp1_report),
        wp2_report=Path(args.wp2_report),
        wp3_report=Path(args.wp3_report),
        annotation_ledger=Path(args.annotation_ledger),
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        sample_jsonl=Path(args.sample_jsonl),
        mode=args.mode,
        source=args.source,
        episode_id=args.episode_id,
        diagnostic_trade_date=args.diagnostic_trade_date,
        break_warning_level=args.break_warning_level,
        component_stress_labels=args.component_stress_labels,
        available_component_count=args.available_component_count,
        analyst_annotation=args.analyst_annotation,
        observed_market_context=args.observed_market_context,
        followup_required=args.followup_required,
        annotation_date=args.annotation_date,
        no_fetch=args.no_fetch,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
