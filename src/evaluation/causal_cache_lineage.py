"""Stage 02 WP-E causal cache lineage repair.

This module makes causal cache lineage explicit and machine-readable. It
inspects local DuckDB metadata only; it does not fetch external data, train
models, or modify HMM/HSMM training algorithms.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb


INDEX_ID = "STAGE02-WP-E-v1"
LINKAGE_TABLE = "causal_cache_run_linkage"
ALLOWED_LINKAGE_STATUSES = frozenset(
    {
        "native_link",
        "strict_inferred_link",
        "weak_inferred_candidate",
        "ambiguous",
        "not_linkable",
        "requires_regeneration",
    }
)
STRONG_LINKAGE_STATUSES = frozenset({"native_link", "strict_inferred_link"})
RUN_LINK_COLUMNS = ("run_id", "model_run_id", "parent_run_id", "hmm_run_id", "source_run_id")
NATIVE_LINK_COLUMNS = RUN_LINK_COLUMNS
NATIVE_CACHE_ID_COLUMNS = ("cache_key", "causal_cache_id", "walk_forward_cache_id")
STRICT_MATCH_FIELDS = ("n_states", "feature_scope_id", "universe_id", "scope_type", "feature_version")
AUDITED_TABLES = (
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "model_runs",
    "sector_state_daily",
    "hmm_confidence_run_summary",
    "hmm_label_alignment_audit",
    "hmm_churn_dwell_run_summary",
    LINKAGE_TABLE,
)


@dataclass(frozen=True)
class CacheCandidate:
    cache_key: str
    causal_cache_id: str
    causal_evidence_id: str
    metadata: dict[str, Any]
    matching_fields: tuple[str, ...]
    missing_or_mismatched_fields: tuple[str, ...]
    coverage_ratio: float | None
    expected_state_rows: int
    unique_cache_state_rows: int
    duplicate_key_count: int
    leakage_violation_count: int
    missing_metadata_count: int
    conceptual_unit: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["matching_fields"] = list(self.matching_fields)
        data["missing_or_mismatched_fields"] = list(self.missing_or_mismatched_fields)
        return data


@dataclass
class CausalCacheLineageResult:
    requested_run_id: str
    resolved_run_id: str | None
    cache_key: str | None
    causal_cache_id: str | None
    causal_evidence_id: str | None
    linkage_status: str
    linkage_confidence: float
    linkage_method: str
    candidate_count: int
    competing_candidate_count: int
    coverage_ratio: float | None
    native_link_available: bool
    strict_inferred_link_available: bool
    readiness_effect: str
    required_next_action: str
    required_next_actions: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    db_path: str = ""
    local_db_used: bool = False
    db_preflight: str = "not_checked"
    tables_checked: dict[str, dict[str, Any]] = field(default_factory=dict)
    candidate_details: list[dict[str, Any]] = field(default_factory=list)
    lineage_table_present: bool = False
    linkage_written: bool = False
    report_path: str | None = None
    summary_json_path: str | None = None
    external_data_fetch: bool = False
    training_algorithm_modified: bool = False
    duckdb_committed: bool = False
    generated_at: str = field(default_factory=lambda: utc_now_iso())

    def __post_init__(self) -> None:
        if self.linkage_status not in ALLOWED_LINKAGE_STATUSES:
            raise ValueError(f"invalid linkage_status: {self.linkage_status}")
        if self.readiness_effect == "decision_ready":
            raise ValueError("Stage 02 WP-E must never emit decision_ready")
        self.linkage_confidence = round(float(self.linkage_confidence), 6)
        if not self.required_next_actions:
            self.required_next_actions = [self.required_next_action]

    @property
    def status(self) -> str:
        if self.linkage_status in STRONG_LINKAGE_STATUSES:
            return "pass"
        return "partial"

    def to_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["index_id"] = INDEX_ID
        payload["status"] = self.status
        payload["allowed_linkage_statuses"] = sorted(ALLOWED_LINKAGE_STATUSES)
        payload["strong_linkage_statuses"] = sorted(STRONG_LINKAGE_STATUSES)
        return payload


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
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


def _first_existing(columns: Sequence[str] | set[str], candidates: Sequence[str]) -> str | None:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def _rows_as_dicts(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[Any] | None = None,
) -> list[dict[str, Any]]:
    cursor = con.execute(sql, list(params or ()))
    columns = [item[0] for item in cursor.description or ()]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def _scalar(
    con: duckdb.DuckDBPyConnection,
    sql: str,
    params: Sequence[Any] | None = None,
    default: Any = None,
) -> Any:
    row = con.execute(sql, list(params or ())).fetchone()
    if row is None:
        return default
    return row[0]


def _norm_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


def _hash_payload(payload: Mapping[str, Any], prefix: str) -> str:
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=_json_default).encode("utf-8")
    return f"{prefix}-{hashlib.sha1(encoded).hexdigest()[:20]}"


def inspect_tables(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    profile: dict[str, dict[str, Any]] = {}
    for table_name in AUDITED_TABLES:
        if not table_exists(con, table_name):
            profile[table_name] = {"present": False, "row_count": None, "columns": []}
            continue
        columns = table_columns(con, table_name)
        row_count = int(_scalar(con, f"SELECT COUNT(*) FROM {quote_identifier(table_name)}", default=0))
        profile[table_name] = {"present": True, "row_count": row_count, "columns": columns}
    return profile


LINKAGE_SCHEMA_COLUMNS: tuple[tuple[str, str], ...] = (
    ("linkage_id", "TEXT"),
    ("cache_key", "TEXT"),
    ("causal_cache_id", "TEXT"),
    ("resolved_run_id", "TEXT"),
    ("model_run_id", "TEXT"),
    ("causal_evidence_id", "TEXT"),
    ("linkage_status", "TEXT"),
    ("linkage_confidence", "DOUBLE"),
    ("linkage_method", "TEXT"),
    ("feature_scope_id", "TEXT"),
    ("universe_id", "TEXT"),
    ("scope_type", "TEXT"),
    ("feature_version", "TEXT"),
    ("n_states", "INTEGER"),
    ("cache_start_date", "DATE"),
    ("cache_end_date", "DATE"),
    ("model_train_start", "DATE"),
    ("model_train_end", "DATE"),
    ("coverage_ratio", "DOUBLE"),
    ("expected_state_rows", "BIGINT"),
    ("unique_cache_state_rows", "BIGINT"),
    ("duplicate_key_count", "BIGINT"),
    ("leakage_violation_count", "BIGINT"),
    ("missing_metadata_count", "BIGINT"),
    ("evidence_json", "TEXT"),
    ("blocking_reasons_json", "TEXT"),
    ("created_at", "TIMESTAMP"),
    ("updated_at", "TIMESTAMP"),
)


def ensure_causal_cache_lineage_schema(con: duckdb.DuckDBPyConnection) -> None:
    """Create the causal cache lineage table idempotently."""

    con.execute(
        """
        CREATE TABLE IF NOT EXISTS causal_cache_run_linkage (
          linkage_id TEXT PRIMARY KEY,
          cache_key TEXT,
          causal_cache_id TEXT,
          resolved_run_id TEXT,
          model_run_id TEXT,
          causal_evidence_id TEXT,
          linkage_status TEXT,
          linkage_confidence DOUBLE,
          linkage_method TEXT,
          feature_scope_id TEXT,
          universe_id TEXT,
          scope_type TEXT,
          feature_version TEXT,
          n_states INTEGER,
          cache_start_date DATE,
          cache_end_date DATE,
          model_train_start DATE,
          model_train_end DATE,
          coverage_ratio DOUBLE,
          expected_state_rows BIGINT,
          unique_cache_state_rows BIGINT,
          duplicate_key_count BIGINT,
          leakage_violation_count BIGINT,
          missing_metadata_count BIGINT,
          evidence_json TEXT,
          blocking_reasons_json TEXT,
          created_at TIMESTAMP,
          updated_at TIMESTAMP
        )
        """
    )
    for column_name, column_type in LINKAGE_SCHEMA_COLUMNS:
        con.execute(
            f"ALTER TABLE {quote_identifier(LINKAGE_TABLE)} "
            f"ADD COLUMN IF NOT EXISTS {quote_identifier(column_name)} {column_type}"
        )


def _latest_model_run(con: duckdb.DuckDBPyConnection) -> tuple[dict[str, Any] | None, list[str]]:
    if not table_exists(con, "model_runs"):
        return None, ["model_runs table missing"]
    columns = set(table_columns(con, "model_runs"))
    if "run_id" not in columns:
        return None, ["model_runs table lacks run_id"]
    where = ""
    if "model_type" in columns:
        where = "WHERE model_type IS NULL OR lower(CAST(model_type AS TEXT)) LIKE '%hmm%'"
    order_terms = [
        f"{quote_identifier(column)} DESC NULLS LAST"
        for column in ("created_at", "train_end")
        if column in columns
    ]
    order_by = ", ".join([*order_terms, "run_id DESC"])
    rows = _rows_as_dicts(
        con,
        f"""
        SELECT *
        FROM model_runs
        {where}
        ORDER BY {order_by}
        LIMIT 1
        """,
    )
    if rows:
        return rows[0], []
    return None, ["model_runs did not contain a latest HMM run"]


def _model_run_by_id(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[dict[str, Any] | None, list[str]]:
    if not table_exists(con, "model_runs"):
        return None, ["model_runs table missing"]
    columns = set(table_columns(con, "model_runs"))
    if "run_id" not in columns:
        return None, ["model_runs table lacks run_id"]
    rows = _rows_as_dicts(con, "SELECT * FROM model_runs WHERE run_id = ? LIMIT 1", [run_id])
    if rows:
        return rows[0], []
    return None, [f"model_runs has no row for run_id={run_id}"]


def resolve_model_run(
    con: duckdb.DuckDBPyConnection,
    requested_run_id: str,
) -> tuple[str | None, dict[str, Any] | None, list[str]]:
    if requested_run_id != "latest":
        model, warnings = _model_run_by_id(con, requested_run_id)
        return requested_run_id, model, warnings
    model, warnings = _latest_model_run(con)
    if model and model.get("run_id") is not None:
        return str(model["run_id"]), model, warnings
    return None, None, warnings


def _cache_order(columns: set[str]) -> str:
    terms = [
        f"{quote_identifier(column)} DESC NULLS LAST"
        for column in ("created_at", "end_date", "start_date")
        if column in columns
    ]
    cache_id = _first_existing(columns, NATIVE_CACHE_ID_COLUMNS) or "cache_key"
    return ", ".join([*terms, f"{quote_identifier(cache_id)} DESC"])


def _cache_rows(con: duckdb.DuckDBPyConnection) -> list[dict[str, Any]]:
    if not table_exists(con, "walk_forward_cache_runs"):
        return []
    columns = set(table_columns(con, "walk_forward_cache_runs"))
    if not _first_existing(columns, NATIVE_CACHE_ID_COLUMNS):
        return []
    return _rows_as_dicts(con, f"SELECT * FROM walk_forward_cache_runs ORDER BY {_cache_order(columns)}")


def _native_link_column(columns: set[str]) -> str | None:
    return _first_existing(columns, NATIVE_LINK_COLUMNS)


def _native_link_rows(
    con: duckdb.DuckDBPyConnection,
    resolved_run_id: str,
) -> tuple[list[dict[str, Any]], str | None]:
    if not table_exists(con, "walk_forward_cache_runs"):
        return [], None
    columns = set(table_columns(con, "walk_forward_cache_runs"))
    link_column = _native_link_column(columns)
    if link_column is None:
        return [], None
    rows = _rows_as_dicts(
        con,
        f"""
        SELECT *
        FROM walk_forward_cache_runs
        WHERE CAST({quote_identifier(link_column)} AS VARCHAR) = ?
        ORDER BY {_cache_order(columns)}
        """,
        [resolved_run_id],
    )
    return rows, link_column


def _expected_state_rows(con: duckdb.DuckDBPyConnection, run_id: str) -> int:
    if not table_exists(con, "sector_state_daily"):
        return 0
    columns = set(table_columns(con, "sector_state_daily"))
    if not {"run_id", "sector_id", "trade_date"}.issubset(columns):
        return 0
    return int(
        _scalar(
            con,
            """
            SELECT COUNT(*) FROM (
              SELECT DISTINCT sector_id, trade_date
              FROM sector_state_daily
              WHERE run_id = ?
            )
            """,
            [run_id],
            default=0,
        )
        or 0
    )


def _state_table_has_required_columns(con: duckdb.DuckDBPyConnection) -> bool:
    if not table_exists(con, "walk_forward_state_cache"):
        return False
    columns = set(table_columns(con, "walk_forward_state_cache"))
    return {"cache_key", "sector_id", "trade_date"}.issubset(columns)


def _unique_cache_state_rows(con: duckdb.DuckDBPyConnection, cache_key: str) -> int:
    if not _state_table_has_required_columns(con):
        return 0
    return int(
        _scalar(
            con,
            """
            SELECT COUNT(*) FROM (
              SELECT DISTINCT sector_id, trade_date
              FROM walk_forward_state_cache
              WHERE CAST(cache_key AS VARCHAR) = ?
            )
            """,
            [cache_key],
            default=0,
        )
        or 0
    )


def _duplicate_key_count(con: duckdb.DuckDBPyConnection, cache_key: str) -> int:
    if not _state_table_has_required_columns(con):
        return 0
    return int(
        _scalar(
            con,
            """
            SELECT COALESCE(SUM(cnt - 1), 0)
            FROM (
              SELECT sector_id, trade_date, COUNT(*) AS cnt
              FROM walk_forward_state_cache
              WHERE CAST(cache_key AS VARCHAR) = ?
              GROUP BY sector_id, trade_date
              HAVING COUNT(*) > 1
            )
            """,
            [cache_key],
            default=0,
        )
        or 0
    )


def _leakage_violation_count(con: duckdb.DuckDBPyConnection, cache_key: str) -> int:
    if not table_exists(con, "walk_forward_state_cache"):
        return 0
    columns = set(table_columns(con, "walk_forward_state_cache"))
    if not {"cache_key", "trade_date"}.issubset(columns):
        return 0
    checks: list[str] = []
    if "train_end" in columns:
        checks.append("train_end > trade_date")
    if "max_observation_date_used" in columns:
        checks.append("max_observation_date_used > trade_date")
    if not checks:
        return 0
    return int(
        _scalar(
            con,
            f"""
            SELECT COUNT(*)
            FROM walk_forward_state_cache
            WHERE CAST(cache_key AS VARCHAR) = ?
              AND ({' OR '.join(checks)})
            """,
            [cache_key],
            default=0,
        )
        or 0
    )


def _missing_metadata_count(con: duckdb.DuckDBPyConnection, cache_key: str) -> int:
    if not table_exists(con, "walk_forward_state_cache"):
        return 0
    columns = set(table_columns(con, "walk_forward_state_cache"))
    if "cache_key" not in columns:
        return 0
    required = ("sector_id", "trade_date", "state_source", "train_end", "max_observation_date_used")
    if any(column not in columns for column in required):
        return _unique_cache_state_rows(con, cache_key)
    parts = [
        f"{quote_identifier(column)} IS NULL"
        for column in required
    ]
    parts.append("TRIM(CAST(state_source AS VARCHAR)) = ''")
    return int(
        _scalar(
            con,
            f"""
            SELECT COUNT(*)
            FROM walk_forward_state_cache
            WHERE CAST(cache_key AS VARCHAR) = ?
              AND ({' OR '.join(parts)})
            """,
            [cache_key],
            default=0,
        )
        or 0
    )


def _metadata_matches(cache_row: Mapping[str, Any], model_row: Mapping[str, Any] | None) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not model_row:
        return (), tuple(STRICT_MATCH_FIELDS)
    matching: list[str] = []
    missing_or_mismatched: list[str] = []
    for field in STRICT_MATCH_FIELDS:
        cache_value = _norm_text(cache_row.get(field))
        model_value = _norm_text(model_row.get(field))
        if cache_value is None or model_value is None:
            missing_or_mismatched.append(field)
        elif cache_value == model_value:
            matching.append(field)
        else:
            missing_or_mismatched.append(field)
    return tuple(matching), tuple(missing_or_mismatched)


def _conceptual_unit(cache_row: Mapping[str, Any]) -> str:
    train_window = _norm_text(cache_row.get("train_window_days"))
    retrain = _norm_text(cache_row.get("retrain_frequency"))
    state_mode = _norm_text(cache_row.get("state_date_mode"))
    if train_window or retrain or state_mode:
        return "walk_forward_evidence_unit"
    return "static_or_legacy_cache_unit"


def _candidate_from_row(
    con: duckdb.DuckDBPyConnection,
    *,
    cache_row: Mapping[str, Any],
    model_row: Mapping[str, Any] | None,
    resolved_run_id: str,
    expected_rows: int,
) -> CacheCandidate:
    cache_key_column = _first_existing(cache_row.keys(), NATIVE_CACHE_ID_COLUMNS) or "cache_key"
    cache_key = str(cache_row.get(cache_key_column))
    unique_rows = _unique_cache_state_rows(con, cache_key)
    coverage_ratio = (unique_rows / expected_rows) if expected_rows else None
    matching, missing = _metadata_matches(cache_row, model_row)
    causal_evidence_id = _hash_payload(
        {
            "cache_key": cache_key,
            "resolved_run_id": resolved_run_id,
            "params_hash": cache_row.get("params_hash"),
            "start_date": cache_row.get("start_date"),
            "end_date": cache_row.get("end_date"),
        },
        "causal-evidence",
    )
    return CacheCandidate(
        cache_key=cache_key,
        causal_cache_id=cache_key,
        causal_evidence_id=causal_evidence_id,
        metadata=dict(cache_row),
        matching_fields=matching,
        missing_or_mismatched_fields=missing,
        coverage_ratio=_round_ratio(coverage_ratio),
        expected_state_rows=expected_rows,
        unique_cache_state_rows=unique_rows,
        duplicate_key_count=_duplicate_key_count(con, cache_key),
        leakage_violation_count=_leakage_violation_count(con, cache_key),
        missing_metadata_count=_missing_metadata_count(con, cache_key),
        conceptual_unit=_conceptual_unit(cache_row),
    )


def _candidate_blocking_reasons(candidate: CacheCandidate) -> list[str]:
    reasons: list[str] = []
    if candidate.missing_or_mismatched_fields:
        reasons.append("strict_metadata_not_fully_matched")
    if candidate.coverage_ratio is None:
        reasons.append("coverage_unknown")
    elif candidate.coverage_ratio < 0.999999:
        reasons.append("coverage_incomplete")
    if candidate.duplicate_key_count:
        reasons.append("duplicate_cache_state_keys")
    if candidate.leakage_violation_count:
        reasons.append("causal_boundary_violation")
    if candidate.missing_metadata_count:
        reasons.append("missing_cache_state_metadata")
    if candidate.conceptual_unit == "walk_forward_evidence_unit":
        reasons.append("walk_forward_cache_needs_explicit_causal_evidence_id")
    return reasons


def _strict_candidate(candidate: CacheCandidate) -> bool:
    return not _candidate_blocking_reasons(candidate)


def _matching_candidates(candidates: Sequence[CacheCandidate]) -> list[CacheCandidate]:
    scored = [candidate for candidate in candidates if candidate.matching_fields or candidate.unique_cache_state_rows > 0]
    return sorted(
        scored or list(candidates),
        key=lambda item: (
            len(item.matching_fields),
            item.unique_cache_state_rows,
            str(item.metadata.get("created_at") or ""),
            item.cache_key,
        ),
        reverse=True,
    )


def _result_from_candidate(
    *,
    requested_run_id: str,
    resolved_run_id: str,
    candidate: CacheCandidate,
    status: str,
    confidence: float,
    method: str,
    candidate_count: int,
    native_available: bool,
    strict_available: bool,
    tables_checked: Mapping[str, Mapping[str, Any]],
    db_path: str,
    blocking_reasons: Sequence[str],
    warnings: Sequence[str] = (),
) -> CausalCacheLineageResult:
    if status in STRONG_LINKAGE_STATUSES:
        readiness_effect = "lineage_link_available_no_decision_ready"
        action = "consume causal_cache_run_linkage while keeping coverage, label, and CI gates conservative"
    elif status == "weak_inferred_candidate":
        readiness_effect = "research_only_no_upgrade"
        action = "regenerate or backfill cache with native parent_run_id and causal_evidence_id before stronger readiness"
    elif status == "ambiguous":
        readiness_effect = "research_only_no_upgrade"
        action = "disambiguate competing caches by writing parent_run_id or causal_evidence_id"
    elif status == "not_linkable":
        readiness_effect = "research_only_no_upgrade"
        action = "treat model_run_id and causal_cache_id as separate evidence identities"
    else:
        readiness_effect = "research_only_no_upgrade"
        action = "regenerate causal cache with the Stage 02 WP-E lineage contract"

    return CausalCacheLineageResult(
        requested_run_id=requested_run_id,
        resolved_run_id=resolved_run_id,
        cache_key=candidate.cache_key,
        causal_cache_id=candidate.causal_cache_id,
        causal_evidence_id=candidate.causal_evidence_id,
        linkage_status=status,
        linkage_confidence=confidence,
        linkage_method=method,
        candidate_count=candidate_count,
        competing_candidate_count=max(0, candidate_count - 1),
        coverage_ratio=candidate.coverage_ratio,
        native_link_available=native_available,
        strict_inferred_link_available=strict_available,
        readiness_effect=readiness_effect,
        required_next_action=action,
        blocking_reasons=list(dict.fromkeys(blocking_reasons)),
        warnings=list(dict.fromkeys(warnings)),
        db_path=db_path,
        local_db_used=True,
        db_preflight="pass",
        tables_checked={key: dict(value) for key, value in tables_checked.items()},
        candidate_details=[candidate.to_dict()],
        lineage_table_present=bool(tables_checked.get(LINKAGE_TABLE, {}).get("present")),
    )


def build_causal_cache_lineage_result(
    con: duckdb.DuckDBPyConnection,
    *,
    db_path: str,
    requested_run_id: str,
    strict_only: bool = False,
) -> CausalCacheLineageResult:
    tables_checked = inspect_tables(con)
    resolved_run_id, model_row, warnings = resolve_model_run(con, requested_run_id)
    if not resolved_run_id:
        return CausalCacheLineageResult(
            requested_run_id=requested_run_id,
            resolved_run_id=None,
            cache_key=None,
            causal_cache_id=None,
            causal_evidence_id=None,
            linkage_status="requires_regeneration",
            linkage_confidence=0.0,
            linkage_method="run_id_unresolved",
            candidate_count=0,
            competing_candidate_count=0,
            coverage_ratio=None,
            native_link_available=False,
            strict_inferred_link_available=False,
            readiness_effect="research_only_no_upgrade",
            required_next_action="provide a resolvable HMM run id before linking causal cache",
            blocking_reasons=["run_id_unresolved"],
            warnings=warnings,
            db_path=db_path,
            local_db_used=True,
            db_preflight="pass",
            tables_checked=tables_checked,
            lineage_table_present=bool(tables_checked.get(LINKAGE_TABLE, {}).get("present")),
        )

    native_rows, native_column = _native_link_rows(con, resolved_run_id)
    expected_rows = _expected_state_rows(con, resolved_run_id)
    if native_rows:
        native_candidate = _candidate_from_row(
            con,
            cache_row=native_rows[0],
            model_row=model_row,
            resolved_run_id=resolved_run_id,
            expected_rows=expected_rows,
        )
        return _result_from_candidate(
            requested_run_id=requested_run_id,
            resolved_run_id=resolved_run_id,
            candidate=native_candidate,
            status="native_link",
            confidence=1.0,
            method=f"native_cache_metadata_column:{native_column}",
            candidate_count=len(native_rows),
            native_available=True,
            strict_available=False,
            tables_checked=tables_checked,
            db_path=db_path,
            blocking_reasons=_candidate_blocking_reasons(native_candidate),
            warnings=warnings,
        )

    cache_rows = _cache_rows(con)
    if not cache_rows:
        return CausalCacheLineageResult(
            requested_run_id=requested_run_id,
            resolved_run_id=resolved_run_id,
            cache_key=None,
            causal_cache_id=None,
            causal_evidence_id=None,
            linkage_status="requires_regeneration",
            linkage_confidence=0.0,
            linkage_method="no_walk_forward_cache_runs",
            candidate_count=0,
            competing_candidate_count=0,
            coverage_ratio=None,
            native_link_available=False,
            strict_inferred_link_available=False,
            readiness_effect="research_only_no_upgrade",
            required_next_action="generate causal cache with lineage metadata",
            blocking_reasons=["walk_forward_cache_runs_missing_or_empty"],
            warnings=[*warnings, "walk_forward_cache_runs missing or empty"],
            db_path=db_path,
            local_db_used=True,
            db_preflight="pass",
            tables_checked=tables_checked,
            lineage_table_present=bool(tables_checked.get(LINKAGE_TABLE, {}).get("present")),
        )

    candidates = [
        _candidate_from_row(
            con,
            cache_row=row,
            model_row=model_row,
            resolved_run_id=resolved_run_id,
            expected_rows=expected_rows,
        )
        for row in cache_rows
    ]
    matched_candidates = _matching_candidates(candidates)
    strict_candidates = [candidate for candidate in matched_candidates if _strict_candidate(candidate)]
    if len(strict_candidates) == 1 and len(matched_candidates) == 1:
        return _result_from_candidate(
            requested_run_id=requested_run_id,
            resolved_run_id=resolved_run_id,
            candidate=strict_candidates[0],
            status="strict_inferred_link",
            confidence=0.95,
            method="strict_metadata_and_full_coverage_single_candidate",
            candidate_count=1,
            native_available=False,
            strict_available=True,
            tables_checked=tables_checked,
            db_path=db_path,
            blocking_reasons=[],
            warnings=warnings,
        )

    if len(matched_candidates) > 1:
        best = matched_candidates[0]
        reasons = [
            "multiple_cache_candidates_match_resolved_run_metadata",
            *_candidate_blocking_reasons(best),
        ]
        return _result_from_candidate(
            requested_run_id=requested_run_id,
            resolved_run_id=resolved_run_id,
            candidate=best,
            status="ambiguous",
            confidence=0.2,
            method="multiple_metadata_candidates_without_native_link",
            candidate_count=len(matched_candidates),
            native_available=False,
            strict_available=False,
            tables_checked=tables_checked,
            db_path=db_path,
            blocking_reasons=reasons,
            warnings=warnings,
        )

    best = matched_candidates[0]
    reasons = _candidate_blocking_reasons(best)
    if strict_only:
        status = "requires_regeneration"
        confidence = 0.0
        method = "strict_only_no_safe_link"
    elif "missing_cache_state_metadata" in reasons:
        status = "requires_regeneration"
        confidence = 0.0
        method = "missing_state_metadata_requires_regeneration"
    elif best.matching_fields or best.unique_cache_state_rows:
        status = "weak_inferred_candidate"
        confidence = min(0.65, 0.2 + (0.08 * len(best.matching_fields)))
        method = "weak_metadata_candidate_without_native_link"
    else:
        status = "not_linkable"
        confidence = 0.0
        method = "no_metadata_candidate_for_resolved_run"
    return _result_from_candidate(
        requested_run_id=requested_run_id,
        resolved_run_id=resolved_run_id,
        candidate=best,
        status=status,
        confidence=confidence,
        method=method,
        candidate_count=1 if status == "weak_inferred_candidate" else 0,
        native_available=False,
        strict_available=False,
        tables_checked=tables_checked,
        db_path=db_path,
        blocking_reasons=reasons or ["native_link_missing"],
        warnings=warnings,
    )


def _missing_db_result(db_path: str, run_id: str) -> CausalCacheLineageResult:
    return CausalCacheLineageResult(
        requested_run_id=run_id,
        resolved_run_id=None,
        cache_key=None,
        causal_cache_id=None,
        causal_evidence_id=None,
        linkage_status="requires_regeneration",
        linkage_confidence=0.0,
        linkage_method="local_db_missing",
        candidate_count=0,
        competing_candidate_count=0,
        coverage_ratio=None,
        native_link_available=False,
        strict_inferred_link_available=False,
        readiness_effect="research_only_no_upgrade",
        required_next_action="provide local V0 DuckDB or regenerate cache with lineage contract",
        blocking_reasons=["local_db_missing"],
        warnings=[f"database file not found: {db_path}"],
        db_path=db_path,
        local_db_used=False,
        db_preflight="local_db_missing",
    )


def _linkage_row_from_result(result: CausalCacheLineageResult) -> dict[str, Any]:
    candidate = result.candidate_details[0] if result.candidate_details else {}
    metadata = candidate.get("metadata") if isinstance(candidate.get("metadata"), Mapping) else {}
    linkage_id = _hash_payload(
        {
            "cache_key": result.cache_key,
            "resolved_run_id": result.resolved_run_id,
            "status": result.linkage_status,
            "method": result.linkage_method,
        },
        "linkage",
    )
    return {
        "linkage_id": linkage_id,
        "cache_key": result.cache_key,
        "causal_cache_id": result.causal_cache_id,
        "resolved_run_id": result.resolved_run_id,
        "model_run_id": result.resolved_run_id if result.linkage_status in STRONG_LINKAGE_STATUSES else None,
        "causal_evidence_id": result.causal_evidence_id,
        "linkage_status": result.linkage_status,
        "linkage_confidence": result.linkage_confidence,
        "linkage_method": result.linkage_method,
        "feature_scope_id": metadata.get("feature_scope_id"),
        "universe_id": metadata.get("universe_id"),
        "scope_type": metadata.get("scope_type"),
        "feature_version": metadata.get("feature_version"),
        "n_states": _as_int(metadata.get("n_states")),
        "cache_start_date": metadata.get("start_date"),
        "cache_end_date": metadata.get("end_date"),
        "model_train_start": metadata.get("train_start"),
        "model_train_end": metadata.get("train_end"),
        "coverage_ratio": result.coverage_ratio,
        "expected_state_rows": candidate.get("expected_state_rows"),
        "unique_cache_state_rows": candidate.get("unique_cache_state_rows"),
        "duplicate_key_count": candidate.get("duplicate_key_count"),
        "leakage_violation_count": candidate.get("leakage_violation_count"),
        "missing_metadata_count": candidate.get("missing_metadata_count"),
        "evidence_json": json.dumps(result.to_payload(), ensure_ascii=False, default=_json_default),
        "blocking_reasons_json": json.dumps(result.blocking_reasons, ensure_ascii=False),
        "created_at": result.generated_at,
        "updated_at": utc_now_iso(),
    }


def upsert_causal_cache_linkage(
    con: duckdb.DuckDBPyConnection,
    result: CausalCacheLineageResult,
) -> bool:
    """Persist a lineage row idempotently.

    Strong links get `model_run_id`; weak or blocking statuses are persisted as
    evidence only and must not upgrade readiness.
    """

    if not result.cache_key or not result.resolved_run_id:
        return False
    ensure_causal_cache_lineage_schema(con)
    row = _linkage_row_from_result(result)
    columns = [name for name, _type in LINKAGE_SCHEMA_COLUMNS]
    con.execute(f"DELETE FROM {quote_identifier(LINKAGE_TABLE)} WHERE linkage_id = ?", [row["linkage_id"]])
    placeholders = ", ".join("?" for _ in columns)
    column_sql = ", ".join(quote_identifier(column) for column in columns)
    con.execute(
        f"INSERT INTO {quote_identifier(LINKAGE_TABLE)} ({column_sql}) VALUES ({placeholders})",
        [row.get(column) for column in columns],
    )
    return True


def load_best_lineage_for_run(
    con: duckdb.DuckDBPyConnection,
    *,
    resolved_run_id: str,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    if not table_exists(con, LINKAGE_TABLE):
        return None
    columns = set(table_columns(con, LINKAGE_TABLE))
    if not {"resolved_run_id", "linkage_status", "linkage_confidence"}.issubset(columns):
        return None
    filters = ["resolved_run_id = ?"]
    params: list[Any] = [resolved_run_id]
    if cache_key and "cache_key" in columns:
        filters.append("cache_key = ?")
        params.append(cache_key)
    rows = _rows_as_dicts(
        con,
        f"""
        SELECT *
        FROM {quote_identifier(LINKAGE_TABLE)}
        WHERE {' AND '.join(filters)}
        ORDER BY
          CASE linkage_status
            WHEN 'native_link' THEN 0
            WHEN 'strict_inferred_link' THEN 1
            WHEN 'weak_inferred_candidate' THEN 2
            WHEN 'ambiguous' THEN 3
            WHEN 'not_linkable' THEN 4
            ELSE 5
          END,
          linkage_confidence DESC NULLS LAST,
          updated_at DESC NULLS LAST
        LIMIT 1
        """,
        params,
    )
    return rows[0] if rows else None


def load_lineage_report(
    path: str | Path,
    *,
    resolved_run_id: str | None,
    cache_key: str | None = None,
) -> dict[str, Any] | None:
    report = Path(path)
    if not report.exists():
        return None
    payload = json.loads(report.read_text(encoding="utf-8"))
    if resolved_run_id and payload.get("resolved_run_id") != resolved_run_id:
        return None
    if cache_key and payload.get("cache_key") not in {None, cache_key}:
        return None
    return payload


def write_lineage_reports(
    result: CausalCacheLineageResult,
    output_path: str | Path,
    summary_json_path: str | Path,
) -> None:
    output = Path(output_path)
    summary = Path(summary_json_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary.parent.mkdir(parents=True, exist_ok=True)
    result.report_path = str(output)
    result.summary_json_path = str(summary)

    payload = result.to_payload()
    summary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")

    lines = [
        "# Stage 02 WP-E Causal Cache Lineage Repair",
        "",
        f"- index_id: {INDEX_ID}",
        f"- status: {result.status}",
        f"- resolved_run_id: {result.resolved_run_id or 'unresolved'}",
        f"- cache_key: {result.cache_key or 'n/a'}",
        f"- causal_cache_id: {result.causal_cache_id or 'n/a'}",
        f"- causal_evidence_id: {result.causal_evidence_id or 'n/a'}",
        f"- linkage_status: {result.linkage_status}",
        f"- linkage_confidence: {result.linkage_confidence}",
        f"- linkage_method: {result.linkage_method}",
        f"- candidate_count: {result.candidate_count}",
        f"- competing_candidate_count: {result.competing_candidate_count}",
        f"- coverage_ratio: {result.coverage_ratio if result.coverage_ratio is not None else 'n/a'}",
        f"- native_link_available: {'yes' if result.native_link_available else 'no'}",
        f"- strict_inferred_link_available: {'yes' if result.strict_inferred_link_available else 'no'}",
        f"- readiness_effect: {result.readiness_effect}",
        f"- required_next_action: {result.required_next_action}",
        f"- external_data_fetch: {'yes' if result.external_data_fetch else 'no'}",
        f"- training_algorithm_modified: {'yes' if result.training_algorithm_modified else 'no'}",
        f"- DuckDB committed: {'yes' if result.duckdb_committed else 'no'}",
        "",
        "## Linkage Decision",
        "",
        "No linkage is promoted unless the cache has native run metadata or a strict single-candidate inferred contract. Weak candidates are evidence only and keep readiness conservative.",
        "",
        "## Blocking Reasons",
        "",
    ]
    lines.extend(f"- {reason}" for reason in (result.blocking_reasons or ["none"]))
    lines.extend(["", "## Required Next Actions", ""])
    lines.extend(f"- {action}" for action in result.required_next_actions)
    lines.extend(["", "## Candidate Details", ""])
    if result.candidate_details:
        for item in result.candidate_details:
            lines.extend(
                [
                    f"- cache_key: {item.get('cache_key')}",
                    f"  causal_evidence_id: {item.get('causal_evidence_id')}",
                    f"  coverage_ratio: {item.get('coverage_ratio')}",
                    f"  matching_fields: {', '.join(item.get('matching_fields') or []) or 'none'}",
                    f"  missing_or_mismatched_fields: {', '.join(item.get('missing_or_mismatched_fields') or []) or 'none'}",
                    f"  conceptual_unit: {item.get('conceptual_unit')}",
                ]
            )
    else:
        lines.append("- none")
    lines.extend(["", "## Warnings", ""])
    lines.extend(f"- {warning}" for warning in (result.warnings or ["none"]))
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def run_causal_cache_lineage(
    *,
    db_path: str | Path,
    run_id: str,
    output_path: str | Path,
    summary_json_path: str | Path,
    no_fetch: bool = True,
    write_linkage_table: bool = False,
    dry_run: bool = False,
    strict_only: bool = False,
) -> CausalCacheLineageResult:
    if not no_fetch:
        raise ValueError("Stage 02 WP-E does not support fetching external data")

    db_path_str = str(db_path)
    path = Path(db_path)
    if not path.exists():
        result = _missing_db_result(db_path_str, run_id)
        write_lineage_reports(result, output_path, summary_json_path)
        return result

    read_only = not (write_linkage_table and not dry_run)
    with duckdb.connect(db_path_str, read_only=read_only) as con:
        con.execute("SET timezone='Asia/Shanghai'")
        if write_linkage_table and not dry_run:
            ensure_causal_cache_lineage_schema(con)
        result = build_causal_cache_lineage_result(
            con,
            db_path=db_path_str,
            requested_run_id=run_id,
            strict_only=strict_only,
        )
        if write_linkage_table and not dry_run:
            result.linkage_written = upsert_causal_cache_linkage(con, result)

    write_lineage_reports(result, output_path, summary_json_path)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage 02 WP-E causal cache lineage repair")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    parser.add_argument("--write-linkage-table", action="store_true", help="Persist machine-readable linkage evidence.")
    parser.add_argument("--dry-run", action="store_true", help="Do not write linkage rows even if requested.")
    parser.add_argument("--strict-only", action="store_true", help="Treat weak inferred candidates as requires_regeneration.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    try:
        result = run_causal_cache_lineage(
            db_path=args.db,
            run_id=args.run_id,
            output_path=args.output,
            summary_json_path=args.summary_json,
            no_fetch=args.no_fetch,
            write_linkage_table=args.write_linkage_table,
            dry_run=args.dry_run,
            strict_only=args.strict_only,
        )
    except Exception as exc:
        print(f"causal cache lineage repair failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "index_id": INDEX_ID,
                "status": result.status,
                "resolved_run_id": result.resolved_run_id,
                "cache_key": result.cache_key,
                "causal_cache_id": result.causal_cache_id,
                "linkage_status": result.linkage_status,
                "linkage_confidence": result.linkage_confidence,
                "linkage_method": result.linkage_method,
                "candidate_count": result.candidate_count,
                "competing_candidate_count": result.competing_candidate_count,
                "readiness_effect": result.readiness_effect,
                "required_next_action": result.required_next_action,
                "external_data_fetch": result.external_data_fetch,
                "training_algorithm_modified": result.training_algorithm_modified,
                "duckdb_committed": result.duckdb_committed,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
