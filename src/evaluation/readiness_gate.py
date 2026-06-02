"""Stage 02 WP-C conservative readiness gate integration.

This module aggregates existing diagnostic outputs only. It does not fetch
market data, train models, or modify HMM/HSMM algorithms.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd

from src.evaluation.causal_cache_lineage import STRONG_LINKAGE_STATUSES, load_lineage_report
from src.ui.readiness_policy import CANONICAL_EVIDENCE_LEVELS, CANONICAL_READINESS_STATUSES


INDEX_ID = "STAGE02-WP-C-v1"
VERSION = "v1"
CANONICAL_GATE_STATUSES = frozenset({"pass", "partial", "fail"})
CANONICAL_DISPLAY_ACTIONS = frozenset({"normal", "warn", "research_only", "hide_strategy", "blocked"})
DEFAULT_CONFIDENCE_JSON = Path("reports/hmm_confidence/stage01_wp_a_confidence_report.json")
DEFAULT_ALIGNMENT_JSON = Path("reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json")
DEFAULT_CHURN_DWELL_JSON = Path("reports/hmm_churn_dwell/stage01_wp_c_churn_dwell_report.json")
DEFAULT_STAGE01_INTEGRATION_JSON = Path("reports/stage01_integration/stage01_integration_summary.json")
DEFAULT_CAUSAL_CACHE_JSON = Path("reports/causal_cache/stage02_wp_a_causal_cache_audit.json")
DEFAULT_CAUSAL_CACHE_LINEAGE_JSON = Path("reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.json")
DEFAULT_CI_VALIDATION_JSON = Path("reports/ci_validation/stage02_wp_b_ci_validation_summary.json")
HIGH_LABEL_AMBIGUITY_THRESHOLD = 0.50
MIN_CAUSAL_CACHE_COVERAGE = 0.80


@dataclass(frozen=True)
class ReadinessGateDecision:
    run_id: str | None
    status: str
    evidence_level: str
    readiness_status: str
    display_action: str
    state_confidence_status: str
    label_identity_status: str
    churn_dwell_status: str
    causal_cache_status: str
    ci_validation_status: str
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    required_next_evidence: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in CANONICAL_GATE_STATUSES:
            raise ValueError(f"non-canonical gate status: {self.status}")
        if self.evidence_level not in CANONICAL_EVIDENCE_LEVELS:
            raise ValueError(f"non-canonical evidence_level: {self.evidence_level}")
        if self.readiness_status not in CANONICAL_READINESS_STATUSES:
            raise ValueError(f"non-canonical readiness_status: {self.readiness_status}")
        if self.readiness_status == "decision_ready":
            raise ValueError("Stage 02 WP-C must never emit decision_ready")
        if self.display_action not in CANONICAL_DISPLAY_ACTIONS:
            raise ValueError(f"non-canonical display_action: {self.display_action}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        data["warnings"] = list(self.warnings)
        data["required_next_evidence"] = list(self.required_next_evidence)
        return data


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(value)


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not table_exists(con, table_name):
        return []
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()]


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _dedupe(items: Sequence[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item for item in items if item))


def _norm_text(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _status_from_bool(value: bool) -> str:
    return "available" if value else "missing"


def _latest_model_run(con: duckdb.DuckDBPyConnection) -> tuple[str | None, list[str], str]:
    if not table_exists(con, "model_runs"):
        return None, ["model_runs table missing"], "missing"
    columns = set(table_columns(con, "model_runs"))
    if "run_id" not in columns:
        return None, ["model_runs schema lacks run_id"], "schema_missing_run_id"
    where = ""
    if "model_type" in columns:
        where = "WHERE model_type IS NULL OR lower(CAST(model_type AS TEXT)) LIKE '%hmm%'"
    order_terms = [
        f"{quote_identifier(column)} DESC NULLS LAST"
        for column in ("created_at", "train_end")
        if column in columns
    ]
    order_by = ", ".join([*order_terms, "run_id DESC"])
    row = con.execute(
        f"""
        SELECT run_id
        FROM model_runs
        {where}
        ORDER BY {order_by}
        LIMIT 1
        """
    ).fetchone()
    if row and row[0] is not None:
        return str(row[0]), [], "model_runs"
    return None, ["model_runs contains no HMM run rows"], "data_empty"


def _latest_state_run(con: duckdb.DuckDBPyConnection) -> tuple[str | None, list[str], str]:
    if not table_exists(con, "sector_state_daily"):
        return None, ["sector_state_daily table missing"], "missing"
    columns = set(table_columns(con, "sector_state_daily"))
    if "run_id" not in columns:
        return None, ["sector_state_daily schema lacks run_id"], "schema_missing_run_id"
    if "trade_date" in columns:
        row = con.execute(
            """
            SELECT run_id
            FROM sector_state_daily
            WHERE run_id IS NOT NULL
            GROUP BY run_id
            ORDER BY max(trade_date) DESC NULLS LAST, count(*) DESC, run_id DESC
            LIMIT 1
            """
        ).fetchone()
    else:
        row = con.execute("SELECT run_id FROM sector_state_daily WHERE run_id IS NOT NULL LIMIT 1").fetchone()
    if row and row[0] is not None:
        return str(row[0]), ["latest run_id resolved from sector_state_daily fallback"], "sector_state_daily"
    return None, ["sector_state_daily contains no run rows"], "data_empty"


def resolve_run_id(con: duckdb.DuckDBPyConnection, requested_run_id: str) -> tuple[str | None, str, list[str]]:
    if requested_run_id != "latest":
        return requested_run_id, "explicit", []

    run_id, warnings, source = _latest_model_run(con)
    if run_id:
        return run_id, source, warnings
    fallback_run_id, fallback_warnings, fallback_source = _latest_state_run(con)
    return fallback_run_id, fallback_source, [*warnings, *fallback_warnings]


def _table_profile(con: duckdb.DuckDBPyConnection, tables: Sequence[str]) -> dict[str, dict[str, Any]]:
    profile: dict[str, dict[str, Any]] = {}
    for table in tables:
        if not table_exists(con, table):
            profile[table] = {"present": False, "row_count": None, "columns": []}
            continue
        columns = table_columns(con, table)
        row_count = int(con.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])
        profile[table] = {"present": True, "row_count": row_count, "columns": columns}
    return profile


def _input_result(
    *,
    name: str,
    availability: str,
    source: str,
    status: str = "unknown",
    readiness_status: str | None = None,
    display_action: str | None = None,
    reasons: Sequence[str] = (),
    warnings: Sequence[str] = (),
    metrics: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "availability": availability,
        "source": source,
        "status": status,
        "readiness_status": readiness_status,
        "display_action": display_action,
        "reasons": list(_dedupe(tuple(reasons))),
        "warnings": list(_dedupe(tuple(warnings))),
        "metrics": dict(metrics or {}),
    }


def _confidence_from_db(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    if not table_exists(con, "hmm_confidence_run_summary"):
        return None
    columns = set(table_columns(con, "hmm_confidence_run_summary"))
    if "run_id" not in columns:
        return _input_result(
            name="confidence",
            availability="missing",
            source="db:hmm_confidence_run_summary",
            status="schema_missing_run_id",
            reasons=("hmm_confidence_run_summary schema lacks run_id",),
        )
    rows = con.execute("SELECT * FROM hmm_confidence_run_summary WHERE run_id = ?", [run_id]).fetchdf()
    if rows.empty:
        total = int(con.execute("SELECT COUNT(*) FROM hmm_confidence_run_summary").fetchone()[0])
        return _input_result(
            name="confidence",
            availability="missing",
            source="db:hmm_confidence_run_summary",
            status="run_id_mismatch" if total else "data_empty",
            reasons=(f"hmm_confidence_run_summary has no rows for run_id={run_id}",),
            metrics={"table_row_count": total},
        )
    row = rows.iloc[0].to_dict()
    return _input_result(
        name="confidence",
        availability="available",
        source="db:hmm_confidence_run_summary",
        status="pass",
        readiness_status=_norm_text(row.get("readiness_status"), "unknown"),
        metrics={
            "row_count": int(row.get("row_count") or 0),
            "sector_count": int(row.get("sector_count") or 0),
            "high_share": row.get("high_share"),
            "medium_share": row.get("medium_share"),
            "low_share": row.get("low_share"),
            "unclear_share": row.get("unclear_share"),
            "missing_share": row.get("missing_share"),
        },
    )


def _confidence_from_report(path: Path, run_id: str) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    report_run_id = payload.get("run_id")
    if report_run_id != run_id:
        return _input_result(
            name="confidence",
            availability="missing",
            source=str(path),
            status="run_id_mismatch",
            reasons=(f"confidence report run_id={report_run_id} does not match resolved run_id={run_id}",),
        )
    summary = payload.get("summary") if isinstance(payload.get("summary"), Mapping) else {}
    return _input_result(
        name="confidence",
        availability="available",
        source=str(path),
        status=_norm_text(payload.get("status"), "unknown"),
        readiness_status=_norm_text(summary.get("readiness_status"), "unknown"),
        warnings=tuple(str(item) for item in payload.get("warnings") or ()),
        metrics={
            "row_count": payload.get("confidence_rows_generated") or summary.get("row_count"),
            "posterior_columns_found": payload.get("posterior_columns_found"),
            "posterior_columns": payload.get("posterior_columns"),
            "high_share": summary.get("high_share"),
            "medium_share": summary.get("medium_share"),
            "low_share": summary.get("low_share"),
            "unclear_share": summary.get("unclear_share"),
            "missing_share": summary.get("missing_share"),
        },
    )


def load_confidence_input(con: duckdb.DuckDBPyConnection | None, run_id: str, report_path: Path) -> dict[str, Any]:
    if con is not None:
        db_result = _confidence_from_db(con, run_id)
        if db_result is not None and db_result["availability"] == "available":
            return db_result
        report_result = _confidence_from_report(report_path, run_id)
        if report_result is not None and report_result["availability"] == "available":
            report_result["warnings"].extend(db_result.get("reasons", []) if db_result else ["hmm_confidence_run_summary table does not exist"])
            return report_result
        if db_result is not None:
            return db_result
    report_result = _confidence_from_report(report_path, run_id)
    if report_result is not None:
        return report_result
    return _input_result(
        name="confidence",
        availability="missing",
        source="db/report",
        status="table_or_report_missing",
        reasons=("hmm_confidence_run_summary table missing and confidence report JSON missing",),
    )


def _alignment_from_db(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    if not table_exists(con, "hmm_label_alignment_audit"):
        return None
    columns = set(table_columns(con, "hmm_label_alignment_audit"))
    if "run_id" in columns:
        rows = con.execute("SELECT * FROM hmm_label_alignment_audit WHERE run_id = ?", [run_id]).fetchdf()
    elif "base_run_id" in columns:
        rows = con.execute("SELECT * FROM hmm_label_alignment_audit WHERE base_run_id = ?", [run_id]).fetchdf()
    else:
        return _input_result(
            name="label_alignment",
            availability="missing",
            source="db:hmm_label_alignment_audit",
            status="schema_missing_run_id",
            reasons=("hmm_label_alignment_audit schema lacks run_id/base_run_id",),
        )
    total = int(con.execute("SELECT COUNT(*) FROM hmm_label_alignment_audit").fetchone()[0])
    if rows.empty:
        return _input_result(
            name="label_alignment",
            availability="missing",
            source="db:hmm_label_alignment_audit",
            status="run_id_mismatch" if total else "data_empty",
            reasons=(f"hmm_label_alignment_audit has no rows for run_id={run_id}",),
            metrics={"table_row_count": total},
        )
    ambiguous_share = None
    label_preserved_share = None
    high_drift_share = None
    if "ambiguous_match" in rows:
        ambiguous_share = float(rows["ambiguous_match"].fillna(False).astype(bool).mean())
    if "label_preserved" in rows:
        label_preserved_share = float(rows["label_preserved"].fillna(False).astype(bool).mean())
    if "label_drift_severity" in rows:
        high_drift_share = float(rows["label_drift_severity"].astype(str).str.lower().eq("high").mean())
    reasons: list[str] = []
    if ambiguous_share is not None and ambiguous_share > HIGH_LABEL_AMBIGUITY_THRESHOLD:
        reasons.append("label_alignment_ambiguity_high")
    return _input_result(
        name="label_alignment",
        availability="available",
        source="db:hmm_label_alignment_audit",
        status="pass",
        readiness_status="research_only" if reasons else "internal_only",
        reasons=reasons,
        metrics={
            "rows": int(len(rows)),
            "ambiguous_share": ambiguous_share,
            "label_preserved_share": label_preserved_share,
            "high_drift_share": high_drift_share,
        },
    )


def _alignment_from_report(path: Path, run_id: str) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    report_run_id = payload.get("resolved_run_id") or payload.get("run_id")
    if report_run_id != run_id:
        return _input_result(
            name="label_alignment",
            availability="missing",
            source=str(path),
            status="run_id_mismatch",
            reasons=(f"label alignment report run_id={report_run_id} does not match resolved run_id={run_id}",),
        )
    ambiguous_share = payload.get("ambiguous_share")
    reasons: list[str] = []
    if ambiguous_share is not None and float(ambiguous_share) > HIGH_LABEL_AMBIGUITY_THRESHOLD:
        reasons.append("label_alignment_ambiguity_high")
    return _input_result(
        name="label_alignment",
        availability="available",
        source=str(path),
        status=_norm_text(payload.get("status"), "unknown"),
        readiness_status=_norm_text(payload.get("state_identity_readiness_status"), "unknown"),
        reasons=reasons,
        warnings=tuple(str(item) for item in payload.get("warnings") or ()),
        metrics={
            "run_pairs_compared": payload.get("run_pairs_compared"),
            "alignment_method": payload.get("alignment_method"),
            "ambiguous_share": ambiguous_share,
            "label_preserved_share": payload.get("label_preserved_share"),
            "high_drift_share": payload.get("high_drift_share"),
        },
    )


def load_alignment_input(con: duckdb.DuckDBPyConnection | None, run_id: str, report_path: Path) -> dict[str, Any]:
    if con is not None:
        db_result = _alignment_from_db(con, run_id)
        if db_result is not None and db_result["availability"] == "available":
            return db_result
        report_result = _alignment_from_report(report_path, run_id)
        if report_result is not None and report_result["availability"] == "available":
            report_result["warnings"].extend(db_result.get("reasons", []) if db_result else ["hmm_label_alignment_audit table does not exist"])
            return report_result
        if db_result is not None:
            return db_result
    report_result = _alignment_from_report(report_path, run_id)
    if report_result is not None:
        return report_result
    return _input_result(
        name="label_alignment",
        availability="missing",
        source="db/report",
        status="table_or_report_missing",
        reasons=("hmm_label_alignment_audit table missing and label alignment report JSON missing",),
    )


def _churn_from_db(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, Any] | None:
    if not table_exists(con, "hmm_churn_dwell_run_summary"):
        return None
    columns = set(table_columns(con, "hmm_churn_dwell_run_summary"))
    if "run_id" not in columns:
        return _input_result(
            name="churn_dwell",
            availability="missing",
            source="db:hmm_churn_dwell_run_summary",
            status="schema_missing_run_id",
            reasons=("hmm_churn_dwell_run_summary schema lacks run_id",),
        )
    rows = con.execute("SELECT * FROM hmm_churn_dwell_run_summary WHERE run_id = ?", [run_id]).fetchdf()
    total = int(con.execute("SELECT COUNT(*) FROM hmm_churn_dwell_run_summary").fetchone()[0])
    if rows.empty:
        return _input_result(
            name="churn_dwell",
            availability="missing",
            source="db:hmm_churn_dwell_run_summary",
            status="run_id_mismatch" if total else "data_empty",
            reasons=(f"hmm_churn_dwell_run_summary has no rows for run_id={run_id}",),
            metrics={"table_row_count": total},
        )
    row = rows.iloc[0].to_dict()
    return _input_result(
        name="churn_dwell",
        availability="available",
        source="db:hmm_churn_dwell_run_summary",
        status="pass",
        readiness_status=_norm_text(row.get("dwell_readiness_status"), "unknown"),
        display_action=_norm_text(row.get("display_action"), "unknown"),
        warnings=tuple(str(item) for item in row.get("warnings", []) or ()),
        metrics={
            "row_count": row.get("row_count"),
            "transition_rate_1d": row.get("transition_rate_1d"),
            "mean_dwell_days": row.get("mean_dwell_days"),
            "median_dwell_days": row.get("median_dwell_days"),
            "single_day_episode_share": row.get("single_day_episode_share"),
            "episode_count": row.get("episode_count"),
            "churn_bucket": row.get("churn_bucket"),
        },
    )


def _churn_from_report(path: Path, run_id: str) -> dict[str, Any] | None:
    payload = _load_json(path)
    if payload is None:
        return None
    report_run_id = payload.get("run_id")
    if report_run_id != run_id:
        return _input_result(
            name="churn_dwell",
            availability="missing",
            source=str(path),
            status="run_id_mismatch",
            reasons=(f"churn/dwell report run_id={report_run_id} does not match resolved run_id={run_id}",),
        )
    reasons: list[str] = []
    if payload.get("churn_bucket") == "excessive":
        reasons.append("excessive_hmm_state_churn")
    if payload.get("causal_cache_available") is False:
        reasons.append("churn_dwell_missing_causal_cache_linkage")
    return _input_result(
        name="churn_dwell",
        availability="available",
        source=str(path),
        status=_norm_text(payload.get("status"), "unknown"),
        readiness_status=_norm_text(payload.get("dwell_readiness_status"), "unknown"),
        display_action=_norm_text(payload.get("display_action"), "unknown"),
        reasons=reasons,
        warnings=tuple(str(item) for item in payload.get("warnings") or ()),
        metrics={
            "row_count": payload.get("row_count"),
            "transition_rate_1d": payload.get("transition_rate_1d"),
            "mean_dwell_days": payload.get("mean_dwell_days"),
            "median_dwell_days": payload.get("median_dwell_days"),
            "single_day_episode_share": payload.get("single_day_episode_share"),
            "episode_count": payload.get("episode_count"),
            "churn_bucket": payload.get("churn_bucket"),
            "churn_dwell_rows_generated": payload.get("churn_dwell_rows_generated"),
        },
    )


def load_churn_dwell_input(con: duckdb.DuckDBPyConnection | None, run_id: str, report_path: Path) -> dict[str, Any]:
    if con is not None:
        db_result = _churn_from_db(con, run_id)
        if db_result is not None and db_result["availability"] == "available":
            return db_result
        report_result = _churn_from_report(report_path, run_id)
        if report_result is not None and report_result["availability"] == "available":
            report_result["warnings"].extend(db_result.get("reasons", []) if db_result else ["hmm_churn_dwell_run_summary table does not exist"])
            return report_result
        if db_result is not None:
            return db_result
    report_result = _churn_from_report(report_path, run_id)
    if report_result is not None:
        return report_result
    return _input_result(
        name="churn_dwell",
        availability="missing",
        source="db/report",
        status="table_or_report_missing",
        reasons=("hmm_churn_dwell_run_summary table missing and churn/dwell report JSON missing",),
    )


def load_causal_cache_input(
    path: Path,
    run_id: str | None,
    lineage_path: Path = DEFAULT_CAUSAL_CACHE_LINEAGE_JSON,
) -> dict[str, Any]:
    payload = _load_json(path)
    if payload is None:
        return _input_result(
            name="causal_cache",
            availability="missing",
            source=str(path),
            status="report_missing",
            reasons=("causal cache audit report JSON missing",),
        )
    report_run_id = payload.get("resolved_run_id") or payload.get("run_id")
    reasons: list[str] = []
    warnings = [str(item) for item in payload.get("warnings") or ()]
    if run_id and report_run_id != run_id:
        reasons.append(f"causal_cache_run_id_mismatch:{report_run_id}!={run_id}")
    if not payload.get("causal_cache_available"):
        reasons.append("causal_cache_unavailable")
        availability = "unavailable"
    else:
        availability = "available"
    lineage = load_lineage_report(
        lineage_path,
        resolved_run_id=run_id,
        cache_key=payload.get("causal_cache_id") or payload.get("cache_key"),
    )
    lineage_status = lineage.get("linkage_status") if lineage else payload.get("lineage_status")
    strong_lineage = lineage_status in STRONG_LINKAGE_STATUSES
    if payload.get("status") != "pass" or payload.get("report_status") not in {None, "pass"}:
        reasons.append(_norm_text(payload.get("report_status"), "causal_cache_audit_not_pass"))
    if payload.get("cache_run_id") in {None, ""} and not strong_lineage:
        reasons.append("causal_cache_not_linked_to_resolved_run_id")
    if lineage_status and not strong_lineage:
        reasons.append(f"causal_cache_lineage_{lineage_status}")
    coverage = payload.get("coverage_ratio")
    if coverage is not None and float(coverage) < MIN_CAUSAL_CACHE_COVERAGE:
        reasons.append("causal_cache_coverage_partial")
    if int(payload.get("missing_metadata_count") or 0) > 0:
        reasons.append("causal_cache_missing_metadata")
    if int(payload.get("leakage_violation_count") or 0) > 0:
        reasons.append("causal_cache_leakage_violation")
    if int(payload.get("exec_date_violation_count") or 0) > 0:
        reasons.append("causal_cache_exec_date_violation")
    return _input_result(
        name="causal_cache",
        availability=availability,
        source=str(path),
        status=_norm_text(payload.get("status"), "unknown"),
        readiness_status=_norm_text(payload.get("readiness_status"), "unknown"),
        reasons=reasons,
        warnings=warnings,
        metrics={
            "report_status": payload.get("report_status"),
            "causal_cache_available": payload.get("causal_cache_available"),
            "causal_cache_id": payload.get("causal_cache_id"),
            "cache_run_id": payload.get("cache_run_id"),
            "lineage_status": lineage_status,
            "lineage_confidence": lineage.get("linkage_confidence") if lineage else payload.get("lineage_confidence"),
            "lineage_method": lineage.get("linkage_method") if lineage else payload.get("lineage_method"),
            "lineage_readiness_effect": lineage.get("readiness_effect") if lineage else payload.get("lineage_readiness_effect"),
            "coverage_ratio": payload.get("coverage_ratio"),
            "expected_state_rows": payload.get("expected_state_rows"),
            "unique_cache_state_rows": payload.get("unique_cache_state_rows"),
            "missing_metadata_count": payload.get("missing_metadata_count"),
            "leakage_violation_count": payload.get("leakage_violation_count"),
            "duplicate_key_count": payload.get("duplicate_key_count"),
            "exec_date_violation_count": payload.get("exec_date_violation_count"),
        },
    )


def load_ci_validation_input(path: Path) -> dict[str, Any]:
    payload = _load_json(path)
    if payload is None:
        return _input_result(
            name="ci_validation",
            availability="missing",
            source=str(path),
            status="report_missing",
            reasons=("CI validation summary JSON missing",),
        )
    reasons: list[str] = []
    if payload.get("status") != "pass":
        reasons.append("ci_validation_not_pass")
    if payload.get("private_db_required") == "no":
        reasons.append("ci_validation_no_private_db_not_db_backed")
    return _input_result(
        name="ci_validation",
        availability="available",
        source=str(path),
        status=_norm_text(payload.get("status"), "unknown"),
        reasons=reasons,
        metrics={
            "ci_workflow": payload.get("ci_workflow"),
            "private_db_required": payload.get("private_db_required"),
            "local_db_usage": payload.get("local_db_usage"),
            "duckdb_committed": payload.get("duckdb_committed"),
            "private_path_hygiene": payload.get("private_path_hygiene"),
        },
    )


def decide_readiness(
    *,
    run_id: str | None,
    db_found: bool,
    run_id_resolved: bool,
    inputs: Mapping[str, Mapping[str, Any]],
) -> ReadinessGateDecision:
    reasons: list[str] = []
    warnings: list[str] = []
    required_next_evidence: list[str] = []

    if not db_found:
        reasons.append("local_db_missing")
        required_next_evidence.append("provide local V0 DuckDB for data-backed readiness aggregation")
    if not run_id_resolved:
        reasons.append("run_id_unresolved")

    for key, result in inputs.items():
        reasons.extend(str(item) for item in result.get("reasons") or ())
        warnings.extend(str(item) for item in result.get("warnings") or ())
        if result.get("availability") in {"missing", "unavailable"}:
            required_next_evidence.append(f"make {key} input available for resolved HMM run_id")

    confidence = inputs.get("confidence", {})
    alignment = inputs.get("label_alignment", {})
    churn = inputs.get("churn_dwell", {})
    causal = inputs.get("causal_cache", {})
    ci_validation = inputs.get("ci_validation", {})

    confidence_status = _norm_text(confidence.get("availability"), "missing")
    label_status = _norm_text(alignment.get("availability"), "missing")
    churn_status = _norm_text(churn.get("availability"), "missing")
    causal_status = _norm_text(causal.get("availability"), "missing")
    ci_status = _norm_text(ci_validation.get("availability"), "missing")

    if confidence.get("readiness_status") in {"blocked", "research_only", "partial"}:
        reasons.append("confidence_not_strong_enough_for_validated_readiness")
    if alignment.get("readiness_status") in {"blocked", "research_only", "partial"}:
        reasons.append("label_identity_not_strong_enough_for_validated_readiness")
    if churn.get("readiness_status") in {"blocked", "research_only"}:
        reasons.append("churn_dwell_gate_keeps_display_research_only")

    hard_fail_tokens = {
        "causal_cache_leakage_violation",
        "causal_cache_exec_date_violation",
        "evidence_boundary_violation",
    }
    status = "pass"
    readiness_status = "partial"
    evidence_level = "internal_diagnostic"
    display_action = "warn"

    if any(reason in hard_fail_tokens for reason in reasons):
        status = "fail"
        readiness_status = "blocked"
        evidence_level = "exploratory"
        display_action = "blocked"
    elif not db_found or not run_id_resolved:
        status = "partial"
        readiness_status = "blocked"
        evidence_level = "exploratory"
        display_action = "blocked"
    elif any(result.get("availability") in {"missing", "unavailable"} for result in inputs.values()):
        status = "partial"
        readiness_status = "research_only"
        evidence_level = "exploratory"
        display_action = "research_only"
    elif (
        causal.get("status") != "pass"
        or "causal_cache_not_linked_to_resolved_run_id" in reasons
        or "causal_cache_coverage_partial" in reasons
        or "label_alignment_ambiguity_high" in reasons
        or "ci_validation_no_private_db_not_db_backed" in reasons
    ):
        readiness_status = "research_only"
        evidence_level = "exploratory"
        display_action = "research_only"
    else:
        readiness_status = "partial"
        evidence_level = "internal_diagnostic"
        display_action = "warn"

    if churn.get("metrics", {}).get("churn_bucket") == "excessive":
        display_action = "hide_strategy"
        readiness_status = "research_only"
        evidence_level = "exploratory"

    required_next_evidence.extend(
        [
            "link causal cache rows to resolved HMM run_id in metadata or registry",
            "raise causal cache coverage before stronger readiness",
            "reduce or explain high label alignment ambiguity",
            "produce CI evidence beyond no-private-DB smoke validation before stronger claims",
        ]
    )

    return ReadinessGateDecision(
        run_id=run_id,
        status=status,
        evidence_level=evidence_level,
        readiness_status=readiness_status,
        display_action=display_action,
        state_confidence_status=confidence_status,
        label_identity_status=label_status,
        churn_dwell_status=churn_status,
        causal_cache_status=causal_status,
        ci_validation_status=ci_status,
        reasons=_dedupe(tuple(reasons)),
        warnings=_dedupe(tuple(warnings)),
        required_next_evidence=_dedupe(tuple(required_next_evidence)),
    )


def _build_summary(
    *,
    requested_run_id: str,
    resolved_run_id: str | None,
    resolved_run_id_source: str,
    db_path: Path,
    db_found: bool,
    db_opened_read_only: bool,
    db_preflight: str,
    table_profile: Mapping[str, Any],
    inputs: Mapping[str, Mapping[str, Any]],
    decision: ReadinessGateDecision,
    output_path: Path,
    summary_path: Path,
    no_fetch: bool,
    run_id_warnings: Sequence[str],
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "version": VERSION,
        "generated_at": utc_now_iso(),
        "status": decision.status,
        "requested_run_id": requested_run_id,
        "run_id": resolved_run_id,
        "resolved_run_id_source": resolved_run_id_source,
        "db_path": str(db_path),
        "local_db_available": db_found,
        "db_found": db_found,
        "db_opened_read_only": db_opened_read_only,
        "db_preflight": db_preflight,
        "tables_checked": dict(table_profile),
        "readiness_gate": decision.to_dict(),
        "inputs": {key: dict(value) for key, value in inputs.items()},
        "report_path": str(output_path),
        "summary_json_path": str(summary_path),
        "external_data_fetch": False,
        "no_fetch_mode": bool(no_fetch),
        "training_algorithm_modified": False,
        "duckdb_committed": False,
        "posterior_semantic_statement": (
            "HMM posterior probabilities are state confidence diagnostics only; "
            "they are not return, rising, falling, profit, buy, or sell probabilities."
        ),
        "warnings": list(_dedupe((*run_id_warnings, *decision.warnings))),
    }


def build_markdown_report(summary: Mapping[str, Any]) -> str:
    gate = summary["readiness_gate"]
    inputs = summary["inputs"]
    reasons = gate.get("reasons") or []
    warnings = summary.get("warnings") or []
    required = gate.get("required_next_evidence") or []
    lines = [
        "# Stage 02 WP-C Readiness Gate Report",
        "",
        f"index_id: {summary['index_id']}",
        f"status: {summary['status']}",
        f"run_id: {summary.get('run_id') or 'unresolved'}",
        f"local DB available: {'yes' if summary.get('local_db_available') else 'no'}",
        f"db preflight: {summary.get('db_preflight')}",
        "",
        "## Readiness Gate",
        "",
        f"- evidence_level: {gate.get('evidence_level')}",
        f"- readiness_status: {gate.get('readiness_status')}",
        f"- display_action: {gate.get('display_action')}",
        f"- state_confidence_status: {gate.get('state_confidence_status')}",
        f"- label_identity_status: {gate.get('label_identity_status')}",
        f"- churn_dwell_status: {gate.get('churn_dwell_status')}",
        f"- causal_cache_status: {gate.get('causal_cache_status')}",
        f"- ci_validation_status: {gate.get('ci_validation_status')}",
        "",
        "## Inputs",
        "",
    ]
    for key in ("confidence", "label_alignment", "churn_dwell", "causal_cache", "ci_validation"):
        item = inputs.get(key, {})
        readiness_status = item.get("readiness_status") or "n/a"
        display_action = item.get("display_action") or "n/a"
        lines.extend(
            [
                f"### {key}",
                "",
                f"- availability: {item.get('availability')}",
                f"- source: {item.get('source')}",
                f"- status: {item.get('status')}",
                f"- readiness_status: {readiness_status}",
                f"- display_action: {display_action}",
                f"- reasons: {', '.join(item.get('reasons') or ['none'])}",
                f"- warnings: {', '.join(item.get('warnings') or ['none'])}",
                "",
            ]
        )

    lines.extend(["## Blocking / Downgrade Reasons", ""])
    if reasons:
        lines.extend(f"- {reason}" for reason in reasons)
    else:
        lines.append("- none")
    lines.extend(["", "## Required Next Evidence", ""])
    if required:
        lines.extend(f"- {item}" for item in required)
    else:
        lines.append("- none")
    lines.extend(["", "## Boundary Flags", ""])
    lines.extend(
        [
            "- external_data_fetch: no",
            "- training_algorithm_modified: no",
            "- duckdb_committed: no",
            "- decision_ready_emitted: no",
            "- HMM posterior semantic role: state confidence diagnostics only",
            "",
            "## Warnings",
        ]
    )
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def write_report_files(output_path: Path, summary_path: Path, summary: Mapping[str, Any]) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(build_markdown_report(summary), encoding="utf-8")
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n",
        encoding="utf-8",
    )


def generate_readiness_gate_report(
    *,
    db_path: str | Path,
    run_id: str,
    output: str | Path,
    summary_json: str | Path,
    no_fetch: bool = True,
    confidence_json: str | Path = DEFAULT_CONFIDENCE_JSON,
    alignment_json: str | Path = DEFAULT_ALIGNMENT_JSON,
    churn_dwell_json: str | Path = DEFAULT_CHURN_DWELL_JSON,
    causal_cache_json: str | Path = DEFAULT_CAUSAL_CACHE_JSON,
    causal_cache_lineage_json: str | Path = DEFAULT_CAUSAL_CACHE_LINEAGE_JSON,
    ci_validation_json: str | Path = DEFAULT_CI_VALIDATION_JSON,
) -> dict[str, Any]:
    db = Path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    db_found = db.exists()
    db_opened_read_only = False
    db_preflight = "pass" if db_found else "local_db_missing"
    table_profile: dict[str, Any] = {}
    run_id_warnings: list[str] = []
    resolved_run_id: str | None = run_id if run_id != "latest" else None
    resolved_run_id_source = "explicit" if run_id != "latest" else "unresolved"
    con: duckdb.DuckDBPyConnection | None = None

    try:
        if db_found:
            con = duckdb.connect(str(db), read_only=True)
            db_opened_read_only = True
            resolved_run_id, resolved_run_id_source, run_id_warnings = resolve_run_id(con, run_id)
            table_profile = _table_profile(
                con,
                (
                    "model_runs",
                    "sector_state_daily",
                    "hmm_confidence_run_summary",
                    "hmm_label_alignment_audit",
                    "hmm_churn_dwell_run_summary",
                    "walk_forward_cache_runs",
                    "walk_forward_state_cache",
                    "causal_cache_run_linkage",
                    "model_evidence_registry",
                    "validation_runs",
                ),
            )

        effective_run_id = resolved_run_id or run_id
        inputs = {
            "confidence": load_confidence_input(con, effective_run_id, Path(confidence_json)),
            "label_alignment": load_alignment_input(con, effective_run_id, Path(alignment_json)),
            "churn_dwell": load_churn_dwell_input(con, effective_run_id, Path(churn_dwell_json)),
            "causal_cache": load_causal_cache_input(
                Path(causal_cache_json),
                resolved_run_id,
                Path(causal_cache_lineage_json),
            ),
            "ci_validation": load_ci_validation_input(Path(ci_validation_json)),
        }
        decision = decide_readiness(
            run_id=resolved_run_id,
            db_found=db_found,
            run_id_resolved=resolved_run_id is not None,
            inputs=inputs,
        )
        summary = _build_summary(
            requested_run_id=run_id,
            resolved_run_id=resolved_run_id,
            resolved_run_id_source=resolved_run_id_source,
            db_path=db,
            db_found=db_found,
            db_opened_read_only=db_opened_read_only,
            db_preflight=db_preflight,
            table_profile=table_profile,
            inputs=inputs,
            decision=decision,
            output_path=output_path,
            summary_path=summary_path,
            no_fetch=no_fetch,
            run_id_warnings=run_id_warnings,
        )
    finally:
        if con is not None:
            con.close()

    write_report_files(output_path, summary_path, summary)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Stage 02 WP-C readiness gate integration report.")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb", help="Local DuckDB path.")
    parser.add_argument("--run-id", default="latest", help="HMM run_id or latest.")
    parser.add_argument("--output", required=True, help="Markdown report path.")
    parser.add_argument("--summary-json", required=True, help="JSON summary path.")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        default=True,
        help="Default and only supported mode; no external data fetch is attempted.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    summary = generate_readiness_gate_report(
        db_path=args.db,
        run_id=args.run_id,
        output=args.output,
        summary_json=args.summary_json,
        no_fetch=args.no_fetch,
    )
    gate = summary["readiness_gate"]
    print(f"status: {summary['status']}")
    print(f"run_id: {summary.get('run_id') or 'unresolved'}")
    print(f"readiness_status: {gate['readiness_status']}")
    print(f"display_action: {gate['display_action']}")
    print(f"report: {summary['report_path']}")
    print(f"summary_json: {summary['summary_json_path']}")
    return 0 if summary["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
