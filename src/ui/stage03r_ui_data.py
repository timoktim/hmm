from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
ANNOTATION_PATH = Path("data/local_annotations/stage04_research_notes.jsonl")
DEFAULT_REPORT_DIR = Path("reports/stage03r")
DEFAULT_SPLIT_REGISTRY_PATH = Path("reports/stage04/split_registry.json")
DEFAULT_LOCAL_DB_PATH = Path("data/db/a_share_hmm.duckdb")

REPORT_FILES = {
    "final_gate": "stage03r_final_gate_report.json",
    "readiness_matrix": "hazard_readiness_matrix_report.json",
    "hazard_vs_hsmm": "hazard_vs_hsmm_report.json",
    "risk_protocol": "risk_validation_protocol.json",
    "data_quality_ci": "data_quality_ci_report.json",
    "final_holdout": "final_holdout_artifact.json",
}

ANNOTATION_LABELS = {"watch", "ignore", "investigate", "paper_trade"}
CONFIDENCE_LEVELS = {"low", "medium", "high"}

FORBIDDEN_OUTPUT_TERMS = (
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
)


def load_json_report(path: str | Path) -> dict[str, Any]:
    report_path = Path(path)
    if not report_path.exists():
        return {}
    data = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object report: {report_path.as_posix()}")
    return data


def load_stage03r_reports(report_dir: str | Path = DEFAULT_REPORT_DIR) -> dict[str, Any]:
    base = Path(report_dir)
    reports: dict[str, Any] = {"_report_dir": base.as_posix(), "_missing": []}
    for key, filename in REPORT_FILES.items():
        path = base / filename
        reports[key] = load_json_report(path)
        if not reports[key]:
            reports["_missing"].append(path.as_posix())
    return reports


def load_split_registry_optional(path: str | Path = DEFAULT_SPLIT_REGISTRY_PATH) -> dict[str, Any]:
    registry_path = Path(path)
    if not registry_path.exists():
        return {
            "available": "no",
            "status": "missing",
            "path": registry_path.as_posix(),
            "message": "当前分支尚未包含 Stage04 切分登记文件。",
        }
    content = load_json_report(registry_path)
    return {
        "available": "yes",
        "status": "loaded",
        "path": registry_path.as_posix(),
        "schema_version": content.get("schema_version", content.get("registry_version", "unknown")),
        "split_status": content.get("status", content.get("split_status", "unknown")),
        "entry_count": len(content.get("splits", content.get("entries", []))) if isinstance(content, dict) else 0,
    }


def _readiness_summary(reports: dict[str, Any]) -> dict[str, Any]:
    final_gate = reports.get("final_gate", {})
    matrix = reports.get("readiness_matrix", {})
    risk_protocol = reports.get("risk_protocol", {})
    return (
        final_gate.get("readiness_status_summary")
        or risk_protocol.get("readiness_status_summary")
        or {
            "counts": matrix.get("readiness_status_counts", {}),
            "by_horizon": {},
            "expected_horizons": matrix.get("expected_horizons", EXPECTED_HORIZONS),
            "hazard_locally_usable": "unknown",
            "hazard_broadly_promoted": "unknown",
        }
    )


def summarize_readiness_by_horizon(reports: dict[str, Any]) -> list[dict[str, Any]]:
    summary = _readiness_summary(reports)
    by_horizon = summary.get("by_horizon", {})
    rows: list[dict[str, Any]] = []
    for horizon in summary.get("expected_horizons") or EXPECTED_HORIZONS:
        values = by_horizon.get(str(horizon), {})
        rows.append(
            {
                "horizon_days": int(horizon),
                "usable_probability": int(values.get("usable_probability", 0) or 0),
                "baseline_only": int(values.get("baseline_only", 0) or 0),
                "ordinal_only": int(values.get("ordinal_only", 0) or 0),
                "insufficient_sample": int(values.get("insufficient_sample", 0) or 0),
                "invalid": int(values.get("invalid", 0) or 0),
            }
        )
    return rows


def summarize_readiness_counts(reports: dict[str, Any]) -> dict[str, int]:
    counts = _readiness_summary(reports).get("counts") or reports.get("readiness_matrix", {}).get("readiness_status_counts", {})
    return {
        "usable_probability": int(counts.get("usable_probability", 0) or 0),
        "baseline_only": int(counts.get("baseline_only", 0) or 0),
        "ordinal_only": int(counts.get("ordinal_only", 0) or 0),
        "insufficient_sample": int(counts.get("insufficient_sample", 0) or 0),
        "invalid": int(counts.get("invalid", 0) or 0),
    }


def local_db_available(db_path: str | Path = DEFAULT_LOCAL_DB_PATH) -> bool:
    return Path(db_path).exists()


def load_local_db_sector_snapshot_readonly(db_path: str | Path = DEFAULT_LOCAL_DB_PATH) -> dict[str, Any]:
    path = Path(db_path)
    if not path.exists():
        return {"available": "no", "opened_read_only": "no", "path": path.as_posix(), "row_counts": {}}
    try:
        import duckdb
    except Exception as exc:  # pragma: no cover - depends on optional runtime
        return {
            "available": "yes",
            "opened_read_only": "no",
            "path": path.as_posix(),
            "error": f"duckdb unavailable: {exc.__class__.__name__}",
            "row_counts": {},
        }

    tables = ["hsmm_lifecycle_ui_daily", "sector_state_daily", "walk_forward_state_cache"]
    row_counts: dict[str, int] = {}
    try:
        con = duckdb.connect(str(path), read_only=True)
        try:
            existing = {
                str(row[0])
                for row in con.execute(
                    "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
                ).fetchall()
            }
            for table in tables:
                if table in existing:
                    row_counts[table] = int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        finally:
            con.close()
    except Exception as exc:
        return {
            "available": "yes",
            "opened_read_only": "no",
            "path": path.as_posix(),
            "error": f"read-only open failed: {exc.__class__.__name__}",
            "row_counts": {},
        }
    return {"available": "yes", "opened_read_only": "yes", "path": path.as_posix(), "row_counts": row_counts}


def _final_gate_summary(reports: dict[str, Any]) -> dict[str, Any]:
    final_gate = reports.get("final_gate", {})
    return {
        "status": str(final_gate.get("status", "unknown")),
        "engineering_gate": str(final_gate.get("engineering_gate_verdict", "unknown")),
        "empirical_promotion": str(final_gate.get("empirical_promotion_verdict", "unknown")),
        "final_verdict": str(final_gate.get("final_verdict", "unknown")),
        "defer_reasons": list(final_gate.get("defer_reasons", [])),
    }


def _hazard_summary(reports: dict[str, Any]) -> dict[str, Any]:
    readiness = _readiness_summary(reports)
    return {
        "locally_usable": str(readiness.get("hazard_locally_usable", "unknown")),
        "broadly_promoted": str(readiness.get("hazard_broadly_promoted", "unknown")),
        "baseline_only_majority": str(readiness.get("baseline_only_majority", "unknown")),
        "scope": "local_slice_only",
    }


def _hsmm_summary(reports: dict[str, Any]) -> dict[str, Any]:
    availability = reports.get("hazard_vs_hsmm", {}).get("hsmm_lifecycle_availability", {})
    protocol = reports.get("risk_protocol", {}).get("semantic_cleanup_summary", {})
    return {
        "available": str(availability.get("available", "unknown")),
        "row_count": availability.get("row_count", 0),
        "role": "interpretation_only",
        "numeric_policy": str(
            availability.get("hsmm_numeric_p_exit_policy")
            or protocol.get("hsmm_lifecycle_probability_status_policy")
            or "not_available"
        ),
        "diagnostic_policy": str(
            protocol.get("hsmm_lifecycle_probability_status_policy", "diagnostic_only_not_decision_input")
        ),
    }


def _holdout_summary(reports: dict[str, Any]) -> dict[str, Any]:
    final_holdout = reports.get("final_holdout", {})
    gate_holdout = reports.get("final_gate", {}).get("final_holdout_discipline", {})
    return {
        "status": str(final_holdout.get("holdout_status", gate_holdout.get("artifact_present", "unknown"))),
        "empirical_promotion": str(final_holdout.get("empirical_promotion_verdict", gate_holdout.get("artifact_empirical_promotion_verdict", "unknown"))),
        "non_overlap_status": str(final_holdout.get("non_overlap_status", gate_holdout.get("non_overlap_status", "unknown"))),
        "consumption_count": int(final_holdout.get("consumption_count", gate_holdout.get("consumption_count", 0)) or 0),
        "pending_review_horizons": list(EXPECTED_HORIZONS),
        "future_review": "pending",
        "future_computation": "not_requested",
    }


def build_model_context_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "final_gate": snapshot["final_gate"],
        "readiness_counts": snapshot["readiness_counts"],
        "hazard_status": snapshot["hazard_status"],
        "hsmm_summary": snapshot["hsmm_summary"],
        "holdout_status": snapshot["holdout_status"],
        "split_registry_status": snapshot["split_registry"]["status"],
    }


def build_research_console_snapshot(
    root: str | Path = ".",
    report_dir: str | Path | None = None,
    split_registry_path: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, Any]:
    root_path = Path(root)
    report_path = Path(report_dir) if report_dir is not None else DEFAULT_REPORT_DIR
    split_path = Path(split_registry_path) if split_registry_path is not None else DEFAULT_SPLIT_REGISTRY_PATH
    db_file_path = Path(db_path) if db_path is not None else DEFAULT_LOCAL_DB_PATH
    resolved_report_dir = root_path / report_path
    resolved_split_registry = root_path / split_path
    resolved_db = root_path / db_file_path
    reports = load_stage03r_reports(resolved_report_dir)
    split_registry = load_split_registry_optional(resolved_split_registry)
    split_registry["path"] = split_path.as_posix()
    db_status = load_local_db_sector_snapshot_readonly(resolved_db)
    db_status["path"] = db_file_path.as_posix()
    snapshot = {
        "mode": "research_only",
        "reports_missing": [str(Path(path).relative_to(root_path)) if Path(path).is_absolute() else path for path in reports["_missing"]],
        "final_gate": _final_gate_summary(reports),
        "readiness_counts": summarize_readiness_counts(reports),
        "readiness_by_horizon": summarize_readiness_by_horizon(reports),
        "hazard_status": _hazard_summary(reports),
        "hsmm_summary": _hsmm_summary(reports),
        "holdout_status": _holdout_summary(reports),
        "split_registry": split_registry,
        "local_db": db_status,
        "annotation_path": ANNOTATION_PATH.as_posix(),
        "boundary": {
            "external_data_fetch": "no",
            "model_retrained": "no",
            "threshold_tuning": "no",
            "trading_output": "no",
            "decision_output": "no",
            "annotation_files_committed": "no",
            "duckdb_committed": "no",
        },
    }
    return snapshot


def validate_annotation_schema(record: dict[str, Any]) -> dict[str, Any]:
    required = {
        "created_at",
        "sector_code",
        "trade_date",
        "horizon_days",
        "human_label",
        "confidence",
        "note",
        "model_context_snapshot",
    }
    missing = sorted(required - set(record))
    if missing:
        raise ValueError(f"annotation missing required fields: {', '.join(missing)}")
    if str(record["human_label"]) not in ANNOTATION_LABELS:
        raise ValueError("human_label must be watch, ignore, investigate, or paper_trade")
    if str(record["confidence"]) not in CONFIDENCE_LEVELS:
        raise ValueError("confidence must be low, medium, or high")
    horizon = int(record["horizon_days"])
    if horizon not in EXPECTED_HORIZONS:
        raise ValueError("horizon_days must be one of 1, 3, 5, 10, 20")
    if not isinstance(record["model_context_snapshot"], dict):
        raise ValueError("model_context_snapshot must be an object")
    return {
        "created_at": str(record["created_at"]),
        "sector_code": str(record["sector_code"]).strip(),
        "trade_date": str(record["trade_date"]).strip(),
        "horizon_days": horizon,
        "human_label": str(record["human_label"]),
        "confidence": str(record["confidence"]),
        "note": str(record["note"]).strip(),
        "model_context_snapshot": record["model_context_snapshot"],
    }


def build_annotation_record(
    *,
    sector_code: str,
    trade_date: str,
    horizon_days: int,
    human_label: str,
    confidence: str,
    note: str,
    model_context_snapshot: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    return validate_annotation_schema(
        {
            "created_at": created_at or datetime.now(timezone.utc).isoformat(),
            "sector_code": sector_code,
            "trade_date": trade_date,
            "horizon_days": horizon_days,
            "human_label": human_label,
            "confidence": confidence,
            "note": note,
            "model_context_snapshot": model_context_snapshot,
        }
    )


def append_annotation(record: dict[str, Any], path: str | Path = ANNOTATION_PATH) -> Path:
    annotation = validate_annotation_schema(record)
    out_path = Path(path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(annotation, ensure_ascii=False, sort_keys=True) + "\n")
    return out_path


def public_output_text(snapshot: dict[str, Any]) -> str:
    return json.dumps(snapshot, ensure_ascii=False, sort_keys=True)


def forbidden_output_terms(snapshot: dict[str, Any]) -> list[str]:
    text = public_output_text(snapshot)
    return [term for term in FORBIDDEN_OUTPUT_TERMS if term in text]
