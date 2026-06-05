from __future__ import annotations

import argparse
import json
import math
import subprocess
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

import duckdb
import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, project_relative_path


REPORT_VERSION = "stage04_wp3_annotation_label_gate_v1"
INDEX_ID = "STAGE04-WP3"
SOURCE_INDEX_ID = "STAGE04-WP2"
SCHEMA_VERSION = "stage04_break_annotation_v1"
EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
MAX_SAMPLE_ROWS = 200

DEFAULT_DB_PATH = Path("data/db/a_share_hmm.duckdb")
DEFAULT_SPLIT_REGISTRY_PATH = Path("reports/stage04/split_registry.json")
DEFAULT_WP2_REPORT_PATH = Path("reports/stage04/stage04_wp2_break_casebook_report.json")
DEFAULT_ANNOTATION_LEDGER_PATH = Path("reports/stage04/prospective_break_annotation.local.jsonl")
DEFAULT_OUTPUT_PATH = Path("reports/stage04/stage04_wp3_annotation_label_gate_report.md")
DEFAULT_SUMMARY_JSON_PATH = Path("reports/stage04/stage04_wp3_annotation_label_gate_report.json")
DEFAULT_SAMPLE_CSV_PATH = Path("reports/stage04/stage04_wp3_annotation_label_gate_sample.csv")

SURFACE_OUTPUT_KEY = "decision" + "_surface_output"
HSMM_EXIT_USE_KEY = "HSMM_p_exit_used_for_" + "decision"

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
REQUIRED_ANNOTATION_FIELDS = [
    "schema_version",
    "record_type",
    "annotation_date",
    "diagnostic_trade_date",
    "break_warning_level",
    "component_stress_labels",
    "available_component_count",
    "analyst_annotation",
    "observed_market_context",
    "followup_required",
    "forbidden_use_notice",
    "boundary_flags",
]
ALLOWED_RECORD_TYPES = {"annotation", "review", "candidate_check"}
ALLOWED_WARNING_LEVELS = {"watch", "elevated", "high"}
REQUIRED_RECORD_BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "model_retrained": "no",
    "hmm_hsmm_training_changed": "no",
    "hazard_model_changed": "no",
    "threshold_tuning": "no",
    "final_holdout_consumed": "no",
    "decision_engine_output": "no",
    "trading_output": "no",
}


@dataclass(frozen=True)
class AnnotationLabelGateConfig:
    db_path: Path = DEFAULT_DB_PATH
    split_registry_path: Path = DEFAULT_SPLIT_REGISTRY_PATH
    wp2_report_path: Path = DEFAULT_WP2_REPORT_PATH
    annotation_ledger_path: Path = DEFAULT_ANNOTATION_LEDGER_PATH


@dataclass(frozen=True)
class MarketCalendar:
    status: str
    selected_index_code: str | None
    trade_dates: tuple[date, ...]
    summary: dict[str, Any]


def _forbidden_output_terms() -> tuple[str, ...]:
    return (
        "decision" + "_ready",
        "decision" + "_surface",
        "risk" + "_downshift",
        "trade" + "_signal",
        "buy" + "_signal",
        "sell" + "_signal",
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (date,)):
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


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {_public_path(path)}")
    return payload


def _as_date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _normalize_index_code(value: Any) -> str:
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw.zfill(6)


def validate_split_registry_lock(registry: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    checks = {
        "status": registry.get("status") if registry else None,
        "evidence_cutoff_date": registry.get("evidence_cutoff_date") if registry else None,
        "future_holdout_start_rule": registry.get("future_holdout_start_rule") if registry else None,
        "expected_horizons": registry.get("expected_horizons") if registry else None,
        "final_holdout_consumption_count": registry.get("final_holdout_consumption_count") if registry else None,
        "threshold_tuning_after_lock": registry.get("threshold_tuning_after_lock") if registry else None,
        "model_retraining_after_lock": registry.get("model_retraining_after_lock") if registry else None,
        "hmm_hsmm_retraining_after_lock": registry.get("HMM_HSMM_retraining_after_lock") if registry else None,
        "hsmm_exit_use": registry.get(HSMM_EXIT_USE_KEY) if registry else None,
        "analysis_layer_output": registry.get(SURFACE_OUTPUT_KEY) if registry else None,
        "external_data_fetch": registry.get("external_data_fetch") if registry else None,
        "private_db_required_in_ci": registry.get("private_db_required_in_ci") if registry else None,
    }

    if not registry:
        issues.append("Stage04-WP0 split registry not found")
    if registry and checks["status"] != "locked":
        issues.append("split registry status is not locked")
    if registry and not checks["evidence_cutoff_date"]:
        issues.append("split registry evidence cutoff date is missing")
    if registry and checks["future_holdout_start_rule"] != "strictly_after_evidence_cutoff_date":
        issues.append("future holdout start rule is not strictly after the evidence cutoff date")
    if registry and list(checks["expected_horizons"] or []) != EXPECTED_HORIZONS:
        issues.append("split registry expected horizons do not match Stage04 lock")
    if registry and _as_int(checks["final_holdout_consumption_count"], default=-1) != 0:
        issues.append("final holdout consumption count is not zero")
    if registry and checks["threshold_tuning_after_lock"] != "forbidden":
        issues.append("threshold tuning after lock is not forbidden")
    if registry and checks["model_retraining_after_lock"] != "forbidden":
        issues.append("model retraining after lock is not forbidden")
    if registry and checks["hmm_hsmm_retraining_after_lock"] != "forbidden":
        issues.append("HMM/HSMM retraining after lock is not forbidden")
    if registry and checks["hsmm_exit_use"] != "no":
        issues.append("HSMM exit probability use is not disabled for this gate")
    if registry and checks["analysis_layer_output"] != "no":
        issues.append("locked registry analysis-layer output flag is not disabled")
    if registry and checks["external_data_fetch"] != "no":
        issues.append("locked registry does not forbid external data fetch")
    if registry and checks["private_db_required_in_ci"] not in {None, "no"}:
        issues.append("locked registry requires a private DB in CI")

    summary = {
        "status": checks["status"] or "missing",
        "evidence_cutoff_date": checks["evidence_cutoff_date"],
        "future_holdout_start_rule": checks["future_holdout_start_rule"],
        "expected_horizons": list(checks["expected_horizons"] or []),
        "final_holdout_consumption_count": _as_int(checks["final_holdout_consumption_count"])
        if checks["final_holdout_consumption_count"] is not None
        else None,
        "threshold_tuning_after_lock": "no" if checks["threshold_tuning_after_lock"] == "forbidden" else checks["threshold_tuning_after_lock"],
        "model_retraining_after_lock": "no" if checks["model_retraining_after_lock"] == "forbidden" else checks["model_retraining_after_lock"],
        "hmm_hsmm_retraining_after_lock": "no"
        if checks["hmm_hsmm_retraining_after_lock"] == "forbidden"
        else checks["hmm_hsmm_retraining_after_lock"],
        "hsmm_exit_probability_review_use": checks["hsmm_exit_use"],
        "analysis_layer_output": checks["analysis_layer_output"],
        "external_data_fetch": checks["external_data_fetch"],
        "private_db_required_in_ci": checks["private_db_required_in_ci"],
    }
    return summary, issues


def validate_wp2_report(wp2_report: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    if not wp2_report:
        issues.append("Stage04-WP2 report not found")
    if wp2_report and wp2_report.get("status") != "pass":
        issues.append("Stage04-WP2 report status is not pass")
    if wp2_report and wp2_report.get("index_id") != SOURCE_INDEX_ID:
        issues.append("Stage04-WP2 report index_id mismatch")
    if wp2_report and wp2_report.get("prospective_validation_status") != "annotation_only":
        issues.append("Stage04-WP2 report is not annotation-only")
    if wp2_report and wp2_report.get("final_holdout_consumed") != "no":
        issues.append("Stage04-WP2 report consumed final holdout")
    if wp2_report and _as_int(wp2_report.get("final_holdout_consumption_count"), default=-1) != 0:
        issues.append("Stage04-WP2 final holdout consumption count is not zero")
    if wp2_report and wp2_report.get("threshold_tuning_after_lock") != "no":
        issues.append("Stage04-WP2 threshold tuning flag is not no")
    if wp2_report and wp2_report.get("model_retraining_after_lock") != "no":
        issues.append("Stage04-WP2 model retraining flag is not no")

    summary = {
        "status": wp2_report.get("status") if wp2_report else "missing",
        "index_id": wp2_report.get("index_id") if wp2_report else None,
        "report_version": wp2_report.get("report_version") if wp2_report else None,
        "prospective_validation_status": wp2_report.get("prospective_validation_status") if wp2_report else None,
        "final_holdout_consumed": wp2_report.get("final_holdout_consumed") if wp2_report else None,
        "final_holdout_consumption_count": wp2_report.get("final_holdout_consumption_count") if wp2_report else None,
        "threshold_tuning_after_lock": wp2_report.get("threshold_tuning_after_lock") if wp2_report else None,
        "model_retraining_after_lock": wp2_report.get("model_retraining_after_lock") if wp2_report else None,
    }
    return summary, issues


def _is_gitignored(path: Path) -> str:
    try:
        target = path if not path.is_absolute() else path.relative_to(PROJECT_ROOT)
    except ValueError:
        return "unknown"
    try:
        result = subprocess.run(
            ["git", "check-ignore", "-q", target.as_posix()],
            cwd=PROJECT_ROOT,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return "unknown"
    return "yes" if result.returncode == 0 else "no"


def _record_value_has_forbidden_terms(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_record_value_has_forbidden_terms(child) for child in value.values())
    if isinstance(value, list):
        return any(_record_value_has_forbidden_terms(child) for child in value)
    if isinstance(value, str):
        return any(term in value for term in _forbidden_output_terms())
    return False


def load_annotation_ledger(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    records: list[dict[str, Any]] = []
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
                issues.append(f"annotation ledger line {line_number} is not valid JSON")
                continue
            if not isinstance(payload, dict):
                issues.append(f"annotation ledger line {line_number} is not a JSON object")
                continue
            record_type = payload.get("record_type")
            if record_type == "template":
                template_record_count += 1
                continue
            if record_type not in ALLOWED_RECORD_TYPES:
                issues.append(f"annotation ledger line {line_number} has unsupported record_type")
                continue
            records.append(
                {
                    "record_index": len(records) + 1,
                    "line_number": line_number,
                    "record": payload,
                }
            )

    summary = {
        "annotation_ledger_path": _public_path(path),
        "annotation_ledger_exists": "yes" if path.exists() else "no",
        "local_annotations_gitignored": _is_gitignored(path),
        "line_count": line_count,
        "blank_line_count": blank_line_count,
        "template_record_count": template_record_count,
        "annotation_record_count": len(records),
        "invalid_line_count": len(issues),
        "allowed_record_types": sorted(ALLOWED_RECORD_TYPES),
        "required_fields": REQUIRED_ANNOTATION_FIELDS,
    }
    return records, summary, issues


def validate_annotation_records(
    raw_records: list[dict[str, Any]],
    *,
    evidence_cutoff_date: date | None,
) -> tuple[list[dict[str, Any]], list[str]]:
    issues: list[str] = []
    validated: list[dict[str, Any]] = []

    for wrapped in raw_records:
        record = wrapped["record"]
        line_number = wrapped["line_number"]
        record_issues: list[str] = []
        missing_fields = [field for field in REQUIRED_ANNOTATION_FIELDS if field not in record]
        if missing_fields:
            record_issues.append(f"missing required fields: {', '.join(missing_fields)}")
        if record.get("schema_version") != SCHEMA_VERSION:
            record_issues.append("schema_version mismatch")
        diagnostic_date = _as_date(record.get("diagnostic_trade_date"))
        if diagnostic_date is None:
            record_issues.append("diagnostic_trade_date is invalid")
        elif evidence_cutoff_date is not None and diagnostic_date <= evidence_cutoff_date:
            record_issues.append("diagnostic_trade_date is not after the evidence cutoff date")
        if record.get("break_warning_level") not in ALLOWED_WARNING_LEVELS:
            record_issues.append("break_warning_level is outside allowed review levels")

        flags = record.get("boundary_flags")
        if not isinstance(flags, Mapping):
            record_issues.append("boundary_flags is missing or not an object")
        else:
            for key, expected in REQUIRED_RECORD_BOUNDARY_FLAGS.items():
                if flags.get(key) != expected:
                    record_issues.append(f"boundary flag {key} is not {expected}")

        notice = str(record.get("forbidden_use_notice", "")).lower()
        if "annotation" not in notice or "only" not in notice:
            record_issues.append("forbidden_use_notice does not state annotation-only use")
        if _record_value_has_forbidden_terms(record):
            record_issues.append("record contains forbidden exact output wording")

        for issue in record_issues:
            issues.append(f"annotation record line {line_number}: {issue}")
        validated.append(
            {
                "record_index": wrapped["record_index"],
                "line_number": line_number,
                "record_type": record.get("record_type"),
                "annotation_date": record.get("annotation_date"),
                "diagnostic_trade_date": record.get("diagnostic_trade_date"),
                "break_warning_level": record.get("break_warning_level"),
                "boundary_status": "blocked" if record_issues else "valid",
                "boundary_issues": record_issues,
                "raw_record": record,
            }
        )
    return validated, issues


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT count(*) AS n
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _load_market_calendar(db_path: Path) -> MarketCalendar:
    if not db_path.exists():
        return MarketCalendar(
            status="db_missing",
            selected_index_code=None,
            trade_dates=(),
            summary={
                "db_available": "no",
                "db_path": _public_path(db_path),
                "calendar_status": "db_missing",
                "selected_market_index_code": None,
                "calendar_trade_date_count": 0,
                "calendar_min_trade_date": None,
                "calendar_max_trade_date": None,
            },
        )

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return MarketCalendar(
            status="db_unreadable",
            selected_index_code=None,
            trade_dates=(),
            summary={
                "db_available": "yes",
                "db_path": _public_path(db_path),
                "calendar_status": "db_unreadable",
                "selected_market_index_code": None,
                "calendar_trade_date_count": 0,
                "calendar_min_trade_date": None,
                "calendar_max_trade_date": None,
                "calendar_error": exc.__class__.__name__,
            },
        )

    try:
        if not _table_exists(con, "market_index_ohlcv"):
            return MarketCalendar(
                status="table_missing",
                selected_index_code=None,
                trade_dates=(),
                summary={
                    "db_available": "yes",
                    "db_path": _public_path(db_path),
                    "calendar_status": "table_missing",
                    "selected_market_index_code": None,
                    "calendar_trade_date_count": 0,
                    "calendar_min_trade_date": None,
                    "calendar_max_trade_date": None,
                },
            )
        columns = {
            str(row[0])
            for row in con.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'main' AND table_name = 'market_index_ohlcv'
                """
            ).fetchall()
        }
        if {"index_code", "trade_date"} - columns:
            return MarketCalendar(
                status="columns_missing",
                selected_index_code=None,
                trade_dates=(),
                summary={
                    "db_available": "yes",
                    "db_path": _public_path(db_path),
                    "calendar_status": "columns_missing",
                    "selected_market_index_code": None,
                    "calendar_trade_date_count": 0,
                    "calendar_min_trade_date": None,
                    "calendar_max_trade_date": None,
                },
            )
        frame = con.execute(
            """
            SELECT index_code, trade_date
            FROM market_index_ohlcv
            WHERE trade_date IS NOT NULL
            """
        ).fetchdf()
    finally:
        con.close()

    if frame.empty:
        return MarketCalendar(
            status="empty",
            selected_index_code=None,
            trade_dates=(),
            summary={
                "db_available": "yes",
                "db_path": _public_path(db_path),
                "calendar_status": "empty",
                "selected_market_index_code": None,
                "calendar_trade_date_count": 0,
                "calendar_min_trade_date": None,
                "calendar_max_trade_date": None,
            },
        )

    data = frame.copy()
    data["index_code"] = data["index_code"].map(_normalize_index_code)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.date
    data = data[data["trade_date"].notna()]
    if data.empty:
        return MarketCalendar(
            status="empty",
            selected_index_code=None,
            trade_dates=(),
            summary={
                "db_available": "yes",
                "db_path": _public_path(db_path),
                "calendar_status": "empty",
                "selected_market_index_code": None,
                "calendar_trade_date_count": 0,
                "calendar_min_trade_date": None,
                "calendar_max_trade_date": None,
            },
        )

    codes = set(data["index_code"])
    if "000300" in codes:
        selected = "000300"
    elif "000001" in codes:
        selected = "000001"
    else:
        counts = data.groupby("index_code").size().sort_values(ascending=False)
        max_count = int(counts.iloc[0])
        selected = sorted([str(code) for code, count in counts.items() if int(count) == max_count])[0]
    dates = tuple(sorted(set(data.loc[data["index_code"] == selected, "trade_date"].tolist())))
    return MarketCalendar(
        status="available" if dates else "empty",
        selected_index_code=selected if dates else None,
        trade_dates=dates,
        summary={
            "db_available": "yes",
            "db_path": _public_path(db_path),
            "calendar_status": "available" if dates else "empty",
            "selected_market_index_code": selected if dates else None,
            "calendar_trade_date_count": len(dates),
            "calendar_min_trade_date": dates[0].isoformat() if dates else None,
            "calendar_max_trade_date": dates[-1].isoformat() if dates else None,
        },
    )


def _label_completeness_for_record(
    record: dict[str, Any],
    *,
    evidence_cutoff_date: date | None,
    calendar: MarketCalendar,
) -> dict[str, Any]:
    diagnostic_date = _as_date(record.get("diagnostic_trade_date"))
    if diagnostic_date is None:
        status = "invalid_date"
        future_count: int | None = None
    elif evidence_cutoff_date is not None and diagnostic_date <= evidence_cutoff_date:
        status = "pre_lock_violation"
        future_count = None
    elif calendar.status == "db_missing":
        status = "unknown_db_missing"
        future_count = None
    elif calendar.status != "available" or not calendar.trade_dates:
        status = "pending"
        future_count = 0
    elif not [trade_date for trade_date in calendar.trade_dates if trade_date <= diagnostic_date]:
        status = "invalid_date"
        future_count = None
    else:
        future_count = sum(1 for trade_date in calendar.trade_dates if trade_date > diagnostic_date)
        status = "complete" if future_count >= max(EXPECTED_HORIZONS) else "pending"

    missing_horizons = [] if future_count is None else [horizon for horizon in EXPECTED_HORIZONS if future_count < horizon]
    max_available = None if future_count is None else min(future_count, max(EXPECTED_HORIZONS))
    return {
        "diagnostic_trade_date": record.get("diagnostic_trade_date"),
        "max_available_future_horizon": max_available,
        "required_horizons": EXPECTED_HORIZONS,
        "missing_horizons": missing_horizons,
        "label_completeness_status": status,
    }


def apply_label_completeness(
    records: list[dict[str, Any]],
    *,
    evidence_cutoff_date: date | None,
    calendar: MarketCalendar,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for record in records:
        label = _label_completeness_for_record(
            record,
            evidence_cutoff_date=evidence_cutoff_date,
            calendar=calendar,
        )
        merged = dict(record)
        merged.update(label)
        out.append(merged)
    return out


def _label_summary(records: list[dict[str, Any]], calendar: MarketCalendar) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("label_completeness_status"))
        counts[status] = counts.get(status, 0) + 1
    return {
        "required_horizons": EXPECTED_HORIZONS,
        "annotation_record_count": len(records),
        "label_completeness_status_counts": dict(sorted(counts.items())),
        "complete_record_count": counts.get("complete", 0),
        "pending_record_count": counts.get("pending", 0),
        "unknown_db_missing_record_count": counts.get("unknown_db_missing", 0),
        "pre_lock_violation_record_count": counts.get("pre_lock_violation", 0),
        "invalid_date_record_count": counts.get("invalid_date", 0),
        "calendar": calendar.summary,
    }


def _annotation_sample(records: list[dict[str, Any]], *, max_rows: int = MAX_SAMPLE_ROWS) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in records[:max_rows]:
        rows.append(
            {
                "record_index": record.get("record_index"),
                "record_type": record.get("record_type"),
                "annotation_date": record.get("annotation_date"),
                "diagnostic_trade_date": record.get("diagnostic_trade_date"),
                "break_warning_level": record.get("break_warning_level"),
                "label_completeness_status": record.get("label_completeness_status"),
                "max_available_future_horizon": record.get("max_available_future_horizon"),
                "missing_horizons": record.get("missing_horizons", []),
                "boundary_status": record.get("boundary_status"),
            }
        )
    return rows


def _prospective_status(records: list[dict[str, Any]], blocking_issues: list[str]) -> str:
    if blocking_issues:
        return "blocked"
    if not records:
        return "not_started"
    if all(record.get("label_completeness_status") == "complete" for record in records):
        return "labels_complete_pending_review"
    return "collecting_annotations"


def _summary_status(records: list[dict[str, Any]], blocking_issues: list[str]) -> str:
    if blocking_issues:
        return "blocked"
    if records and any(record.get("label_completeness_status") == "unknown_db_missing" for record in records):
        return "defer"
    return "pass"


def _defer_reasons(records: list[dict[str, Any]], calendar: MarketCalendar, blocking_issues: list[str]) -> list[str]:
    if blocking_issues:
        return []
    reasons: list[str] = []
    if records and any(record.get("label_completeness_status") == "unknown_db_missing" for record in records):
        reasons.append("local DB is missing, so label completeness cannot be checked yet")
    if records and any(record.get("label_completeness_status") == "pending" for record in records):
        reasons.append("one or more annotation records are still waiting for future trading observations")
    if records and calendar.status not in {"available", "db_missing"}:
        reasons.append("local calendar is not available enough for a complete label check")
    return reasons


def evaluate_annotation_label_gate(config: AnnotationLabelGateConfig) -> dict[str, Any]:
    registry = load_json_object(config.split_registry_path)
    wp2_report = load_json_object(config.wp2_report_path)
    split_summary, split_issues = validate_split_registry_lock(registry)
    wp2_summary, wp2_issues = validate_wp2_report(wp2_report)
    evidence_cutoff = _as_date(registry.get("evidence_cutoff_date")) if registry else None

    raw_records, ledger_summary, ledger_issues = load_annotation_ledger(config.annotation_ledger_path)
    validated_records, record_issues = validate_annotation_records(raw_records, evidence_cutoff_date=evidence_cutoff)
    calendar = _load_market_calendar(config.db_path)
    labeled_records = apply_label_completeness(validated_records, evidence_cutoff_date=evidence_cutoff, calendar=calendar)

    boundary_issue_count = sum(1 for record in labeled_records if record.get("boundary_status") != "valid")
    blocking_issues = list(split_issues) + list(wp2_issues) + list(ledger_issues) + list(record_issues)
    if any(record.get("label_completeness_status") in {"pre_lock_violation", "invalid_date"} for record in labeled_records):
        if "annotation records include invalid or pre-lock diagnostic dates" not in blocking_issues:
            blocking_issues.append("annotation records include invalid or pre-lock diagnostic dates")
    if boundary_issue_count:
        ledger_summary["boundary_violation_count"] = boundary_issue_count
    else:
        ledger_summary["boundary_violation_count"] = 0

    status = _summary_status(labeled_records, blocking_issues)
    prospective_validation_status = _prospective_status(labeled_records, blocking_issues)
    label_summary = _label_summary(labeled_records, calendar)
    annotation_sample = _annotation_sample(labeled_records)
    summary = {
        "status": status,
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "source_wp2_report_version": wp2_report.get("report_version"),
        "split_registry_lock_summary": split_summary,
        "wp2_source_summary": wp2_summary,
        "boundary_flags": BOUNDARY_FLAGS,
        "annotation_ledger_summary": ledger_summary,
        "label_completeness_summary": label_summary,
        "annotation_record_sample": annotation_sample,
        "prospective_validation_status": prospective_validation_status,
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
        "causal_boundary_summary": {
            "external_data_fetch": "no",
            "local_db_calendar_only": "yes",
            "performance_metrics_computed": "no",
            "returns_or_outcomes_computed": "no",
            "threshold_tuning_after_lock": "no",
            "model_retraining_after_lock": "no",
            "hmm_hsmm_training_changed": "no",
            "hazard_model_changed": "no",
            "final_holdout_consumed": "no",
            "label_check_scope": "future trading day availability only",
        },
        "blocking_issues": sorted(set(blocking_issues)),
        "defer_reasons": _defer_reasons(labeled_records, calendar, blocking_issues),
        "recommended_next_stage": "Continue local annotation collection and rerun this annotation gate when required future horizons are available.",
    }
    _assert_no_forbidden_terms(summary)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Stage04-WP3 Annotation Label Completeness Gate",
        "",
        f"- status: {summary.get('status')}",
        f"- report_version: {summary.get('report_version')}",
        f"- index_id: {summary.get('index_id')}",
        f"- source_wp2_report_version: {summary.get('source_wp2_report_version')}",
        "",
        "This report validates annotation records and label completeness only. It does not evaluate predictive performance, provide trading output, define a decision layer, or consume final holdout.",
        "",
        "## Boundary Flags",
    ]
    for key, value in summary.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Split Registry Lock Summary"])
    for key, value in summary.get("split_registry_lock_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## WP2 Source Summary"])
    for key, value in summary.get("wp2_source_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Annotation Ledger Summary"])
    for key, value in summary.get("annotation_ledger_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Label Completeness Summary"])
    label_summary = summary.get("label_completeness_summary", {})
    for key, value in label_summary.items():
        if key == "calendar":
            continue
        lines.append(f"- {key}: {value}")
    lines.append("- calendar:")
    for key, value in label_summary.get("calendar", {}).items():
        lines.append(f"  - {key}: {value}")

    lines.extend(["", "## Bounded Annotation Record Sample"])
    rows = summary.get("annotation_record_sample", [])
    if rows:
        lines.append("| record_index | record_type | annotation_date | diagnostic_trade_date | break_warning_level | label_completeness_status | max_available_future_horizon | missing_horizons | boundary_status |")
        lines.append("|---:|---|---:|---:|---|---|---:|---|---|")
        for row in rows:
            missing = ";".join(str(horizon) for horizon in row.get("missing_horizons", []))
            lines.append(
                f"| {row.get('record_index')} | {row.get('record_type')} | {row.get('annotation_date')} | "
                f"{row.get('diagnostic_trade_date')} | {row.get('break_warning_level')} | "
                f"{row.get('label_completeness_status')} | {row.get('max_available_future_horizon')} | "
                f"{missing} | {row.get('boundary_status')} |"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Prospective Validation Status", str(summary.get("prospective_validation_status")), ""])
    lines.extend(["## Causal Boundary"])
    for key, value in summary.get("causal_boundary_summary", {}).items():
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


def _assert_no_forbidden_terms(summary: dict[str, Any], markdown: str = "") -> None:
    payload = json.dumps(_json_safe(summary), ensure_ascii=False) + "\n" + markdown
    if any(term in payload for term in _forbidden_output_terms()):
        raise ValueError("Stage04-WP3 report contains forbidden exact output wording")


def _sample_frame(records: list[dict[str, Any]]) -> pd.DataFrame:
    columns = [
        "record_index",
        "record_type",
        "annotation_date",
        "diagnostic_trade_date",
        "break_warning_level",
        "label_completeness_status",
        "max_available_future_horizon",
        "missing_horizons",
        "boundary_status",
    ]
    rows: list[dict[str, Any]] = []
    for row in records[:MAX_SAMPLE_ROWS]:
        flat = {key: row.get(key) for key in columns}
        flat["missing_horizons"] = ";".join(str(horizon) for horizon in row.get("missing_horizons", []))
        rows.append(flat)
    return pd.DataFrame(rows, columns=columns)


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
    output.write_text(render_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _sample_frame(summary.get("annotation_record_sample", [])).to_csv(sample_csv, index=False)


def run_from_paths(
    *,
    db: Path = DEFAULT_DB_PATH,
    split_registry: Path = DEFAULT_SPLIT_REGISTRY_PATH,
    wp2_report: Path = DEFAULT_WP2_REPORT_PATH,
    annotation_ledger: Path = DEFAULT_ANNOTATION_LEDGER_PATH,
    output: Path = DEFAULT_OUTPUT_PATH,
    summary_json: Path = DEFAULT_SUMMARY_JSON_PATH,
    sample_csv: Path = DEFAULT_SAMPLE_CSV_PATH,
) -> dict[str, Any]:
    summary = evaluate_annotation_label_gate(
        AnnotationLabelGateConfig(
            db_path=db,
            split_registry_path=split_registry,
            wp2_report_path=wp2_report,
            annotation_ledger_path=annotation_ledger,
        )
    )
    write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage04-WP3 annotation label completeness gate")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--split-registry", default=str(DEFAULT_SPLIT_REGISTRY_PATH))
    parser.add_argument("--wp2-report", default=str(DEFAULT_WP2_REPORT_PATH))
    parser.add_argument("--annotation-ledger", default=str(DEFAULT_ANNOTATION_LEDGER_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON_PATH))
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV_PATH))
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_from_paths(
        db=Path(args.db),
        split_registry=Path(args.split_registry),
        wp2_report=Path(args.wp2_report),
        annotation_ledger=Path(args.annotation_ledger),
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        sample_csv=Path(args.sample_csv),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
