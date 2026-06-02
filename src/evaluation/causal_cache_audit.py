"""Stage 02 WP-A causal walk-forward cache contract audit.

This module inspects existing local DuckDB tables only. It does not fetch
market data, train models, or modify HMM/HSMM training algorithms.
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

from src.evaluation.evidence_registry import EvidenceRecord, ValidationRunRecord, upsert_evidence_record, upsert_validation_run
from src.ui.readiness_policy import CANONICAL_READINESS_STATUSES, CAUSAL_SOURCES


INDEX_ID = "STAGE02-WP-A-v1"
CANONICAL_STATUSES = {"pass", "partial", "fail"}
UNKNOWN_METADATA = "unknown_due_to_missing_metadata"
AUDITED_TABLES = (
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "sector_state_daily",
    "model_runs",
    "model_evidence_registry",
    "validation_runs",
)
RUN_LINK_COLUMNS = ("run_id", "model_run_id", "hmm_run_id", "source_run_id")
CACHE_ID_COLUMNS = ("cache_key", "causal_cache_id", "walk_forward_cache_id")
SECTOR_ID_COLUMNS = ("sector_id", "sector_code")
DATE_COLUMNS = ("trade_date", "signal_date", "state_date")


@dataclass
class CausalCacheAuditResult:
    run_id: str
    resolved_run_id: str | None
    status: str
    report_status: str
    causal_cache_available: bool
    causal_cache_id: str | None = None
    cache_run_id: str | None = None
    state_source: str = UNKNOWN_METADATA
    state_count: int = 0
    sector_count: int = 0
    min_trade_date: str | None = None
    max_trade_date: str | None = None
    coverage_ratio: float | None = None
    train_end_max: str | None = None
    max_observation_date_used_max: str | None = None
    leakage_violation_count: int = 0
    missing_metadata_count: int = 0
    duplicate_key_count: int = 0
    exec_date_violation_count: int = 0
    readiness_status: str = "blocked"
    readiness_reason: str = ""
    warnings: list[str] = field(default_factory=list)
    db_path: str = ""
    local_db_used: bool = False
    tables_checked: dict[str, dict[str, Any]] = field(default_factory=dict)
    cache_linkage_status: str = "not_checked"
    expected_state_rows: int = 0
    unique_cache_state_rows: int = 0
    cache_run_reported_row_count: int | None = None
    train_end_violation_count: int = 0
    max_observation_date_used_violation_count: int = 0
    state_source_mix_found: bool = False
    registry_written: bool = False
    evidence_id: str | None = None
    validation_run_id: str | None = None
    registry_seed_payload: dict[str, Any] | None = None
    report_path: str | None = None
    summary_json_path: str | None = None
    external_data_fetch: bool = False
    training_algorithm_modified: bool = False
    generated_at: str = field(default_factory=lambda: datetime.now(UTC).replace(microsecond=0).isoformat())

    def __post_init__(self) -> None:
        if self.status not in CANONICAL_STATUSES:
            raise ValueError(f"non-canonical audit status: {self.status}")
        if self.readiness_status not in CANONICAL_READINESS_STATUSES:
            raise ValueError(f"non-canonical readiness_status: {self.readiness_status}")
        if self.readiness_status == "decision_ready":
            raise ValueError("Stage 02 WP-A must never set decision_ready")


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


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(pd.Timestamp(value).date())


def _round_ratio(value: float | None) -> float | None:
    if value is None:
        return None
    return round(float(value), 6)


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


def inspect_tables(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    profile: dict[str, dict[str, Any]] = {}
    for table in AUDITED_TABLES:
        if not table_exists(con, table):
            profile[table] = {"present": False, "row_count": None, "columns": []}
            continue
        columns = table_columns(con, table)
        row_count = int(con.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])
        profile[table] = {"present": True, "row_count": row_count, "columns": columns}
    return profile


def _latest_model_run(con: duckdb.DuckDBPyConnection) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
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
        return str(row[0]), warnings
    warnings.append("model_runs did not contain a latest HMM run_id")
    return None, warnings


def _latest_state_run(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    id_candidates: Sequence[str],
) -> tuple[str | None, str | None]:
    if not table_exists(con, table_name):
        return None, None
    columns = set(table_columns(con, table_name))
    id_column = _first_existing(columns, id_candidates)
    if id_column is None:
        return None, None
    date_column = _first_existing(columns, ("trade_date", "end_date", "created_at"))
    if date_column:
        row = con.execute(
            f"""
            SELECT {quote_identifier(id_column)}, MAX({quote_identifier(date_column)}) AS latest_date, COUNT(*) AS row_count
            FROM {quote_identifier(table_name)}
            GROUP BY {quote_identifier(id_column)}
            ORDER BY latest_date DESC NULLS LAST, row_count DESC, {quote_identifier(id_column)} DESC
            LIMIT 1
            """
        ).fetchone()
    else:
        row = con.execute(
            f"""
            SELECT {quote_identifier(id_column)}, COUNT(*) AS row_count
            FROM {quote_identifier(table_name)}
            GROUP BY {quote_identifier(id_column)}
            ORDER BY row_count DESC, {quote_identifier(id_column)} DESC
            LIMIT 1
            """
        ).fetchone()
    return (str(row[0]), table_name) if row and row[0] is not None else (None, None)


def resolve_run_id(con: duckdb.DuckDBPyConnection, requested_run_id: str) -> tuple[str | None, list[str]]:
    if requested_run_id != "latest":
        return requested_run_id, []

    resolved, warnings = _latest_model_run(con)
    if resolved:
        return resolved, warnings

    fallback_warnings = list(warnings)
    for table_name, candidates in (
        ("sector_state_daily", ("run_id",)),
        ("walk_forward_cache_runs", (*RUN_LINK_COLUMNS, *CACHE_ID_COLUMNS)),
        ("walk_forward_state_cache", (*RUN_LINK_COLUMNS, *CACHE_ID_COLUMNS)),
    ):
        resolved, source = _latest_state_run(con, table_name, candidates)
        if resolved:
            fallback_warnings.append(f"latest run_id resolved from {source} fallback")
            return resolved, fallback_warnings

    fallback_warnings.append("run_id latest could not be resolved from local HMM tables")
    return None, fallback_warnings


def _cache_order(columns: set[str]) -> str:
    terms = [
        f"{quote_identifier(column)} DESC NULLS LAST"
        for column in ("created_at", "end_date", "start_date")
        if column in columns
    ]
    return ", ".join([*terms, quote_identifier(_first_existing(columns, CACHE_ID_COLUMNS) or "cache_key") + " DESC"])


def _cache_row_to_dict(cursor: duckdb.DuckDBPyConnection) -> dict[str, Any] | None:
    row = cursor.fetchone()
    if row is None:
        return None
    return dict(zip([item[0] for item in cursor.description or ()], row, strict=True))


def select_cache_run(
    con: duckdb.DuckDBPyConnection,
    resolved_run_id: str,
) -> tuple[dict[str, Any] | None, str | None, str | None, str, list[str]]:
    warnings: list[str] = []
    if not table_exists(con, "walk_forward_cache_runs"):
        return None, None, None, "missing_cache_run_table", ["walk_forward_cache_runs table missing"]

    columns = set(table_columns(con, "walk_forward_cache_runs"))
    cache_id_column = _first_existing(columns, CACHE_ID_COLUMNS)
    if cache_id_column is None:
        return None, None, None, "missing_cache_id_column", ["walk_forward_cache_runs lacks cache id column"]

    order_by = _cache_order(columns)
    run_link_column = _first_existing(columns, RUN_LINK_COLUMNS)
    if run_link_column:
        cursor = con.execute(
            f"""
            SELECT *
            FROM walk_forward_cache_runs
            WHERE CAST({quote_identifier(run_link_column)} AS VARCHAR) = ?
            ORDER BY {order_by}
            LIMIT 1
            """,
            [resolved_run_id],
        )
        row = _cache_row_to_dict(cursor)
        if row:
            return row, str(row.get(cache_id_column)), str(row.get(run_link_column)), "direct_run_link", warnings
        warnings.append(f"no walk_forward_cache_runs row linked to run_id={resolved_run_id}")

    cursor = con.execute(
        f"""
        SELECT *
        FROM walk_forward_cache_runs
        WHERE CAST({quote_identifier(cache_id_column)} AS VARCHAR) = ?
        ORDER BY {order_by}
        LIMIT 1
        """,
        [resolved_run_id],
    )
    row = _cache_row_to_dict(cursor)
    if row:
        return row, str(row.get(cache_id_column)), str(row.get(cache_id_column)), "cache_id_equals_run_id", warnings

    if run_link_column is None:
        warnings.append("walk_forward_cache_runs lacks run_id linkage metadata")

    cursor = con.execute(
        f"""
        SELECT *
        FROM walk_forward_cache_runs
        ORDER BY {order_by}
        LIMIT 1
        """
    )
    row = _cache_row_to_dict(cursor)
    if row:
        warnings.append(
            "audited latest walk-forward cache because no cache row can be proven to belong to the resolved HMM run"
        )
        return row, str(row.get(cache_id_column)), None, "latest_unlinked_cache", warnings

    return None, None, None, "no_cache_runs", ["walk_forward_cache_runs contains no rows"]


def _select_expr(columns: set[str], candidates: Sequence[str], alias: str, default_sql: str = "NULL") -> str:
    column = _first_existing(columns, candidates)
    if column:
        return f"{quote_identifier(column)} AS {quote_identifier(alias)}"
    return f"{default_sql} AS {quote_identifier(alias)}"


def read_cache_state_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    cache_id: str | None,
    resolved_run_id: str,
) -> tuple[pd.DataFrame, str | None, list[str]]:
    warnings: list[str] = []
    if not table_exists(con, "walk_forward_state_cache"):
        return pd.DataFrame(), None, ["walk_forward_state_cache table missing"]

    columns = set(table_columns(con, "walk_forward_state_cache"))
    id_column = _first_existing(columns, (*CACHE_ID_COLUMNS, *RUN_LINK_COLUMNS))
    sector_column = _first_existing(columns, SECTOR_ID_COLUMNS)
    date_column = _first_existing(columns, DATE_COLUMNS)
    if id_column is None or sector_column is None or date_column is None:
        missing = [
            name
            for name, value in (("cache/run id", id_column), ("sector id", sector_column), ("trade date", date_column))
            if value is None
        ]
        return pd.DataFrame(), id_column, [f"walk_forward_state_cache missing required columns: {', '.join(missing)}"]

    selected_id = cache_id or resolved_run_id
    df = con.execute(
        f"""
        SELECT
          CAST({quote_identifier(id_column)} AS VARCHAR) AS cache_key,
          CAST({quote_identifier(sector_column)} AS VARCHAR) AS sector_id,
          {quote_identifier(date_column)} AS trade_date,
          {_select_expr(columns, ("state_source",), "state_source", "'unknown_due_to_missing_metadata'")},
          {_select_expr(columns, ("train_end", "train_end_date"), "train_end")},
          {_select_expr(columns, ("max_observation_date_used",), "max_observation_date_used")},
          {_select_expr(columns, ("exec_date",), "exec_date")},
          {_select_expr(columns, ("signal_date",), "signal_date")}
        FROM walk_forward_state_cache
        WHERE CAST({quote_identifier(id_column)} AS VARCHAR) = ?
        """,
        [selected_id],
    ).fetchdf()
    if df.empty and cache_id and cache_id != resolved_run_id:
        warnings.append(f"no walk_forward_state_cache rows found for cache_id={cache_id}")
    return df, id_column, warnings


def expected_state_coverage(
    con: duckdb.DuckDBPyConnection,
    resolved_run_id: str,
) -> tuple[int, list[str]]:
    if not table_exists(con, "sector_state_daily"):
        return 0, ["sector_state_daily table missing; coverage ratio cannot be computed"]
    columns = set(table_columns(con, "sector_state_daily"))
    if "run_id" not in columns:
        return 0, ["sector_state_daily lacks run_id; coverage ratio cannot be computed"]
    sector_column = _first_existing(columns, SECTOR_ID_COLUMNS)
    date_column = _first_existing(columns, DATE_COLUMNS)
    if sector_column is None or date_column is None:
        return 0, ["sector_state_daily lacks sector/date columns; coverage ratio cannot be computed"]
    row = con.execute(
        f"""
        SELECT COUNT(*) FROM (
          SELECT DISTINCT CAST({quote_identifier(sector_column)} AS VARCHAR), {quote_identifier(date_column)}
          FROM sector_state_daily
          WHERE run_id = ?
        )
        """,
        [resolved_run_id],
    ).fetchone()
    return int(row[0]) if row else 0, []


def _count_duplicate_keys(rows: pd.DataFrame) -> tuple[int, int]:
    if rows.empty:
        return 0, 0
    key_columns = ["cache_key", "sector_id", "trade_date"]
    unique_count = int(rows[key_columns].drop_duplicates().shape[0])
    grouped = rows.groupby(key_columns, dropna=False).size()
    duplicate_count = int((grouped[grouped > 1] - 1).sum())
    return duplicate_count, unique_count


def _count_missing_metadata(rows: pd.DataFrame) -> int:
    if rows.empty:
        return 0
    required = ("cache_key", "sector_id", "trade_date", "state_source", "train_end", "max_observation_date_used")
    missing = pd.Series(False, index=rows.index)
    for column in required:
        if column not in rows:
            missing = pd.Series(True, index=rows.index)
            continue
        missing = missing | rows[column].isna() | rows[column].astype(str).str.strip().eq("")
    return int(missing.sum())


def _source_summary(rows: pd.DataFrame) -> tuple[str, bool]:
    if rows.empty or "state_source" not in rows:
        return UNKNOWN_METADATA, False
    sources = sorted({str(value).strip().lower() for value in rows["state_source"].dropna() if str(value).strip()})
    if not sources:
        return UNKNOWN_METADATA, False
    if len(sources) == 1:
        return sources[0], False
    return "mixed", True


def _violation_counts(rows: pd.DataFrame) -> tuple[int, int, int]:
    if rows.empty:
        return 0, 0, 0
    trade_dates = pd.to_datetime(rows["trade_date"], errors="coerce")
    train_end = pd.to_datetime(rows["train_end"], errors="coerce") if "train_end" in rows else pd.Series(pd.NaT, index=rows.index)
    obs = (
        pd.to_datetime(rows["max_observation_date_used"], errors="coerce")
        if "max_observation_date_used" in rows
        else pd.Series(pd.NaT, index=rows.index)
    )
    train_violations = int((train_end.notna() & trade_dates.notna() & (train_end > trade_dates)).sum())
    obs_violations = int((obs.notna() & trade_dates.notna() & (obs > trade_dates)).sum())

    exec_violations = 0
    if {"exec_date", "signal_date"}.issubset(rows.columns):
        exec_date = pd.to_datetime(rows["exec_date"], errors="coerce")
        signal_date = pd.to_datetime(rows["signal_date"], errors="coerce")
        available = exec_date.notna() & signal_date.notna()
        if available.any():
            exec_violations = int((available & (exec_date <= signal_date)).sum())
    return train_violations, obs_violations, exec_violations


def _readiness_and_status(
    *,
    cache_available: bool,
    cache_linkage_status: str,
    duplicate_key_count: int,
    leakage_violation_count: int,
    exec_date_violation_count: int,
    missing_metadata_count: int,
    state_source: str,
    state_source_mix_found: bool,
    coverage_ratio: float | None,
) -> tuple[str, str, str]:
    if not cache_available:
        return "partial", "research_only", "causal_cache_unavailable"
    if duplicate_key_count or leakage_violation_count or exec_date_violation_count or state_source_mix_found:
        return "fail", "blocked", "causal_cache_contract_violation"
    if state_source not in CAUSAL_SOURCES:
        return "partial", "research_only", "state_source_not_proven_causal"
    if cache_linkage_status not in {"direct_run_link", "cache_id_equals_run_id"}:
        return "partial", "research_only", "cache_not_linked_to_resolved_run_id"
    if missing_metadata_count:
        return "partial", "research_only", "unknown_due_to_missing_metadata"
    if coverage_ratio is None:
        return "partial", "research_only", "coverage_unknown"
    if coverage_ratio < 0.999999:
        return "partial", "research_only", "incomplete_cache_coverage"
    return "pass", "partial", "causal_cache_contract_passed"


def build_causal_cache_audit_result(
    con: duckdb.DuckDBPyConnection,
    *,
    db_path: str,
    requested_run_id: str,
) -> CausalCacheAuditResult:
    tables_checked = inspect_tables(con)
    resolved_run_id, warnings = resolve_run_id(con, requested_run_id)
    if not resolved_run_id:
        return CausalCacheAuditResult(
            run_id=requested_run_id,
            resolved_run_id=None,
            status="partial",
            report_status="partial_missing_run_id",
            causal_cache_available=False,
            readiness_status="blocked",
            readiness_reason="run_id_unresolved",
            warnings=warnings,
            db_path=db_path,
            local_db_used=True,
            tables_checked=tables_checked,
        )

    cache_run, cache_id, cache_run_id, linkage_status, cache_warnings = select_cache_run(con, resolved_run_id)
    warnings.extend(cache_warnings)
    state_rows, state_id_column, state_warnings = read_cache_state_rows(
        con,
        cache_id=cache_id,
        resolved_run_id=resolved_run_id,
    )
    warnings.extend(state_warnings)
    if state_id_column is None and tables_checked.get("walk_forward_state_cache", {}).get("present"):
        warnings.append("walk_forward_state_cache id metadata unavailable")

    duplicate_key_count, unique_cache_state_rows = _count_duplicate_keys(state_rows)
    expected_rows, coverage_warnings = expected_state_coverage(con, resolved_run_id)
    warnings.extend(coverage_warnings)
    coverage_ratio = None
    if expected_rows > 0:
        coverage_ratio = unique_cache_state_rows / expected_rows

    missing_metadata_count = _count_missing_metadata(state_rows)
    if linkage_status == "latest_unlinked_cache":
        missing_metadata_count += 1
    state_source, source_mix = _source_summary(state_rows)
    train_violations, obs_violations, exec_violations = _violation_counts(state_rows)
    leakage_count = train_violations + obs_violations

    if cache_run and cache_run.get("row_count") is not None:
        try:
            reported_row_count = int(cache_run["row_count"])
        except (TypeError, ValueError):
            reported_row_count = None
            warnings.append("walk_forward_cache_runs.row_count is non-numeric")
    else:
        reported_row_count = None

    if reported_row_count is not None and reported_row_count != len(state_rows):
        warnings.append(
            f"walk_forward_cache_runs.row_count={reported_row_count} differs from selected state_count={len(state_rows)}"
        )
    if {"exec_date", "signal_date"}.isdisjoint(set(state_rows.columns)) or (
        not state_rows.empty and state_rows[["exec_date", "signal_date"]].isna().all().all()
    ):
        warnings.append("execution metadata absent; exec_date > signal_date was not audited")
    if state_source == UNKNOWN_METADATA:
        warnings.append("state_source missing or unknown in selected cache rows")
    if source_mix:
        warnings.append("walk_forward_state_cache mixes state_source values")

    status, readiness_status, readiness_reason = _readiness_and_status(
        cache_available=not state_rows.empty,
        cache_linkage_status=linkage_status,
        duplicate_key_count=duplicate_key_count,
        leakage_violation_count=leakage_count,
        exec_date_violation_count=exec_violations,
        missing_metadata_count=missing_metadata_count,
        state_source=state_source,
        state_source_mix_found=source_mix,
        coverage_ratio=coverage_ratio,
    )
    report_status = status if status == "pass" else readiness_reason
    if not state_rows.empty:
        min_trade_date = _date_str(pd.to_datetime(state_rows["trade_date"], errors="coerce").min())
        max_trade_date = _date_str(pd.to_datetime(state_rows["trade_date"], errors="coerce").max())
        train_end_max = _date_str(pd.to_datetime(state_rows["train_end"], errors="coerce").max())
        obs_max = _date_str(pd.to_datetime(state_rows["max_observation_date_used"], errors="coerce").max())
        sector_count = int(state_rows["sector_id"].nunique())
    else:
        min_trade_date = max_trade_date = train_end_max = obs_max = None
        sector_count = 0
        if report_status == "causal_cache_unavailable":
            report_status = "partial_missing_causal_cache"

    return CausalCacheAuditResult(
        run_id=requested_run_id,
        resolved_run_id=resolved_run_id,
        status=status,
        report_status=report_status,
        causal_cache_available=not state_rows.empty,
        causal_cache_id=cache_id,
        cache_run_id=cache_run_id,
        state_source=state_source,
        state_count=int(len(state_rows)),
        sector_count=sector_count,
        min_trade_date=min_trade_date,
        max_trade_date=max_trade_date,
        coverage_ratio=_round_ratio(coverage_ratio),
        train_end_max=train_end_max,
        max_observation_date_used_max=obs_max,
        leakage_violation_count=leakage_count,
        missing_metadata_count=missing_metadata_count,
        duplicate_key_count=duplicate_key_count,
        exec_date_violation_count=exec_violations,
        readiness_status=readiness_status,
        readiness_reason=readiness_reason,
        warnings=warnings,
        db_path=db_path,
        local_db_used=True,
        tables_checked=tables_checked,
        cache_linkage_status=linkage_status,
        expected_state_rows=expected_rows,
        unique_cache_state_rows=unique_cache_state_rows,
        cache_run_reported_row_count=reported_row_count,
        train_end_violation_count=train_violations,
        max_observation_date_used_violation_count=obs_violations,
        state_source_mix_found=source_mix,
    )


def _missing_db_result(db_path: str, requested_run_id: str) -> CausalCacheAuditResult:
    return CausalCacheAuditResult(
        run_id=requested_run_id,
        resolved_run_id=None,
        status="partial",
        report_status="partial_missing_db",
        causal_cache_available=False,
        readiness_status="blocked",
        readiness_reason="local_db_missing",
        warnings=[f"database file not found: {db_path}"],
        db_path=db_path,
        local_db_used=False,
    )


def _registry_payload(result: CausalCacheAuditResult, command: str | None = None) -> dict[str, Any]:
    metrics = {
        "index_id": INDEX_ID,
        "status": result.status,
        "report_status": result.report_status,
        "causal_cache_available": result.causal_cache_available,
        "causal_cache_id": result.causal_cache_id,
        "state_count": result.state_count,
        "coverage_ratio": result.coverage_ratio,
        "duplicate_key_count": result.duplicate_key_count,
        "leakage_violation_count": result.leakage_violation_count,
        "missing_metadata_count": result.missing_metadata_count,
        "exec_date_violation_count": result.exec_date_violation_count,
        "readiness_status": result.readiness_status,
        "readiness_reason": result.readiness_reason,
    }
    return {
        "model_evidence_registry": {
            "run_id": result.resolved_run_id,
            "model_type": "hmm",
            "evidence_level": "internal_diagnostic",
            "readiness_status": result.readiness_status,
            "causal_cache_id": result.causal_cache_id,
            "state_source": result.state_source,
            "report_path": result.report_path,
            "metrics_json": metrics,
            "notes": "Seed payload only; Stage 00 registry tables were not present in the local DB.",
        },
        "validation_runs": {
            "run_id": result.resolved_run_id,
            "validation_type": "causal_audit",
            "status": "pass" if result.status == "pass" else "unknown",
            "command": command,
            "verdict_code": result.report_status,
            "db_path": result.db_path,
            "report_dir": str(Path(result.report_path or ".").parent),
            "metrics_json": metrics,
            "warnings_json": result.warnings,
        },
    }


def maybe_register_evidence(
    result: CausalCacheAuditResult,
    *,
    command: str | None,
) -> CausalCacheAuditResult:
    if not result.local_db_used or not result.resolved_run_id:
        return result
    table_profile = result.tables_checked
    registry_present = all(table_profile.get(table, {}).get("present") for table in ("model_evidence_registry", "validation_runs"))
    if not registry_present:
        result.registry_seed_payload = _registry_payload(result, command)
        result.warnings.append("Stage 00 registry tables missing; wrote registry seed payload to summary JSON")
        return result

    evidence = EvidenceRecord(
        run_id=result.resolved_run_id,
        model_type="hmm",
        evidence_level="internal_diagnostic",
        readiness_status=result.readiness_status,
        causal_cache_id=result.causal_cache_id,
        state_source=result.state_source,
        report_path=result.report_path,
        metrics_json=_registry_payload(result, command)["model_evidence_registry"]["metrics_json"],
        notes="Stage 02 WP-A causal cache contract audit.",
    )
    evidence_id = upsert_evidence_record(result.db_path, evidence)
    validation_status = "pass" if result.status == "pass" else ("fail" if result.status == "fail" else "unknown")
    validation_id = upsert_validation_run(
        result.db_path,
        ValidationRunRecord(
            run_id=result.resolved_run_id,
            evidence_id=evidence_id,
            validation_type="causal_audit",
            status=validation_status,
            command=command,
            verdict_code=result.report_status,
            db_path=result.db_path,
            report_dir=str(Path(result.report_path or ".").parent),
            metrics_json=_registry_payload(result, command)["validation_runs"]["metrics_json"],
            warnings_json=result.warnings,
        ),
    )
    result.registry_written = True
    result.evidence_id = evidence_id
    result.validation_run_id = validation_id
    return result


def write_reports(result: CausalCacheAuditResult, output_path: str | Path, summary_json_path: str | Path) -> None:
    output = Path(output_path)
    summary_json = Path(summary_json_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    result.report_path = str(output)
    result.summary_json_path = str(summary_json)

    payload = asdict(result)
    payload["index_id"] = INDEX_ID
    payload["readiness_policy_note"] = (
        "Stage 02 WP-A never promotes HMM outputs to decision_ready; causal cache evidence is a conservative gate only."
    )
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")

    table_lines = ["| table | present | rows |", "|---|---:|---:|"]
    for table_name in AUDITED_TABLES:
        info = result.tables_checked.get(table_name, {"present": False, "row_count": None})
        table_lines.append(f"| {table_name} | {str(bool(info.get('present'))).lower()} | {info.get('row_count') if info.get('row_count') is not None else 'n/a'} |")

    lines = [
        "# Stage 02 WP-A Causal Cache Contract Audit",
        "",
        f"- index_id: {INDEX_ID}",
        f"- status: {result.status}",
        f"- report_status: {result.report_status}",
        f"- db_path: {result.db_path}",
        f"- local_db_used: {str(result.local_db_used).lower()}",
        f"- run_id_requested: {result.run_id}",
        f"- resolved_run_id: {result.resolved_run_id or 'unresolved'}",
        f"- causal_cache_available: {str(result.causal_cache_available).lower()}",
        f"- causal_cache_id: {result.causal_cache_id or 'n/a'}",
        f"- cache_run_id: {result.cache_run_id or 'n/a'}",
        f"- cache_linkage_status: {result.cache_linkage_status}",
        f"- state_source: {result.state_source}",
        f"- state_count: {result.state_count}",
        f"- sector_count: {result.sector_count}",
        f"- date_range: {result.min_trade_date or 'n/a'} to {result.max_trade_date or 'n/a'}",
        f"- coverage_ratio: {result.coverage_ratio if result.coverage_ratio is not None else 'n/a'}",
        f"- readiness_status: {result.readiness_status}",
        f"- readiness_reason: {result.readiness_reason}",
        f"- external_data_fetch: {str(result.external_data_fetch).lower()}",
        f"- training_algorithm_modified: {str(result.training_algorithm_modified).lower()}",
        "",
        "## Contract Checks",
        "",
        f"- expected_state_rows: {result.expected_state_rows}",
        f"- unique_cache_state_rows: {result.unique_cache_state_rows}",
        f"- duplicate_key_count: {result.duplicate_key_count}",
        f"- leakage_violation_count: {result.leakage_violation_count}",
        f"- train_end_violation_count: {result.train_end_violation_count}",
        f"- max_observation_date_used_violation_count: {result.max_observation_date_used_violation_count}",
        f"- exec_date_violation_count: {result.exec_date_violation_count}",
        f"- missing_metadata_count: {result.missing_metadata_count}",
        f"- train_end_max: {result.train_end_max or 'n/a'}",
        f"- max_observation_date_used_max: {result.max_observation_date_used_max or 'n/a'}",
        f"- state_source_mix_found: {str(result.state_source_mix_found).lower()}",
        "",
        "## Tables Checked",
        "",
        *table_lines,
        "",
        "## Registry",
        "",
        f"- registry_written: {str(result.registry_written).lower()}",
        f"- evidence_id: {result.evidence_id or 'n/a'}",
        f"- validation_run_id: {result.validation_run_id or 'n/a'}",
        f"- registry_seed_payload_written: {str(result.registry_seed_payload is not None).lower()}",
        "",
        "## Readiness Boundary",
        "",
        "This audit is evidence for causal cache availability only. It does not train a model, fetch data, or make HMM outputs decision-ready.",
        "",
        "## Warnings",
        "",
    ]
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- none")
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def run_causal_cache_audit(
    *,
    db_path: str | Path,
    run_id: str,
    output_path: str | Path,
    summary_json_path: str | Path,
    no_fetch: bool = True,
    command: str | None = None,
) -> CausalCacheAuditResult:
    if not no_fetch:
        raise ValueError("Stage 02 WP-A does not support fetching external data")

    db_path_str = str(db_path)
    path = Path(db_path)
    if not path.exists():
        result = _missing_db_result(db_path_str, run_id)
        write_reports(result, output_path, summary_json_path)
        return result

    with duckdb.connect(db_path_str) as con:
        con.execute("SET timezone='Asia/Shanghai'")
        result = build_causal_cache_audit_result(con, db_path=db_path_str, requested_run_id=run_id)

    write_reports(result, output_path, summary_json_path)
    result = maybe_register_evidence(result, command=command)
    write_reports(result, output_path, summary_json_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 02 WP-A causal cache contract audit")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    args = parser.parse_args(argv)

    command = "python -m src.evaluation.causal_cache_audit " + " ".join(sys.argv[1:])
    try:
        result = run_causal_cache_audit(
            db_path=args.db,
            run_id=args.run_id,
            output_path=args.output,
            summary_json_path=args.summary_json,
            no_fetch=args.no_fetch,
            command=command,
        )
    except Exception as exc:
        print(f"causal cache audit failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "index_id": INDEX_ID,
                "status": result.status,
                "report_status": result.report_status,
                "resolved_run_id": result.resolved_run_id,
                "causal_cache_available": result.causal_cache_available,
                "causal_cache_id": result.causal_cache_id,
                "state_count": result.state_count,
                "duplicate_key_count": result.duplicate_key_count,
                "leakage_violation_count": result.leakage_violation_count,
                "missing_metadata_count": result.missing_metadata_count,
                "readiness_status": result.readiness_status,
                "readiness_reason": result.readiness_reason,
                "report_path": result.report_path,
                "summary_json_path": result.summary_json_path,
                "external_data_fetch": result.external_data_fetch,
                "training_algorithm_modified": result.training_algorithm_modified,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
