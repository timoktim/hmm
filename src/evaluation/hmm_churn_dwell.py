"""Stage 01 WP-C HMM churn/dwell diagnostics.

This module inspects existing local HMM state sequences only. It does not fetch
market data and does not train or modify HMM/HSMM models.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd

from src.ui.readiness_policy import CAUSAL_SOURCES, evaluate_hmm_churn_dwell_display


INDEX_ID = "STAGE01-WP-C-v1"
WORK_PACKAGE = "STAGE01_WP_C_hmm_churn_dwell_ui_readiness"
VERSION = "v1"
DEFAULT_THRESHOLDS = {
    "low": {"transition_rate_1d_max": 0.10, "single_day_episode_share_max": 0.15},
    "medium": {"transition_rate_1d_max": 0.20, "single_day_episode_share_max": 0.30},
    "high": {"transition_rate_1d_max": 0.35, "single_day_episode_share_max": 0.50},
}
SOURCE_TABLES = ("sector_state_daily", "walk_forward_state_cache")
SEQUENCE_TABLE = "hmm_churn_dwell_sequence"
SUMMARY_TABLE = "hmm_churn_dwell_run_summary"
SEQUENCE_COLUMNS = [
    "run_id",
    "sector_id",
    "state_key",
    "state_label",
    "episode_start_date",
    "episode_end_date",
    "dwell_days",
    "is_single_day_episode",
    "feature_scope_id",
    "universe_id",
    "source_table",
    "state_source",
    "created_at",
]
SUMMARY_COLUMNS = [
    "run_id",
    "row_count",
    "sector_count",
    "min_trade_date",
    "max_trade_date",
    "transition_count",
    "transition_rate_1d",
    "mean_dwell_days",
    "median_dwell_days",
    "p10_dwell_days",
    "p90_dwell_days",
    "single_day_episode_share",
    "episode_count",
    "fragmentation_score",
    "churn_bucket",
    "dwell_readiness_status",
    "display_action",
    "confidence_integration_status",
    "alignment_integration_status",
    "report_path",
    "created_at",
]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


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


def _round_float(value: Any, digits: int = 6) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return round(float(value), digits)


def _first_text(series: pd.Series) -> str | None:
    values = series.dropna()
    if values.empty:
        return None
    text = str(values.iloc[0]).strip()
    return text or None


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not table_exists(con, table_name):
        return []
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info('{table_name}')").fetchall()]


def _first_existing(columns: set[str], candidates: Sequence[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _latest_model_run(con: duckdb.DuckDBPyConnection) -> tuple[str | None, str | None]:
    if not table_exists(con, "model_runs"):
        return None, None
    columns = set(table_columns(con, "model_runs"))
    if "run_id" not in columns:
        return None, None
    where = "WHERE lower(model_type) = 'hmm'" if "model_type" in columns else ""
    order_terms = [
        f"{column} DESC NULLS LAST"
        for column in ("created_at", "train_end")
        if column in columns
    ]
    order_by = ", ".join(order_terms or ["run_id DESC"])
    row = con.execute(
        f"""
        SELECT run_id
        FROM model_runs
        {where}
        ORDER BY {order_by}
        LIMIT 1
        """
    ).fetchone()
    return (str(row[0]), "model_runs") if row else (None, None)


def _latest_state_run(
    con: duckdb.DuckDBPyConnection,
    table_name: str,
    id_column: str,
) -> tuple[str | None, str | None]:
    if not table_exists(con, table_name):
        return None, None
    columns = set(table_columns(con, table_name))
    if id_column not in columns:
        return None, None
    date_column = _first_existing(columns, ("trade_date", "end_date", "created_at"))
    if date_column:
        row = con.execute(
            f"""
            SELECT {id_column}, MAX({date_column}) AS latest_date, COUNT(*) AS row_count
            FROM {table_name}
            GROUP BY {id_column}
            ORDER BY latest_date DESC NULLS LAST, row_count DESC, {id_column} DESC
            LIMIT 1
            """
        ).fetchone()
    else:
        row = con.execute(
            f"""
            SELECT {id_column}, COUNT(*) AS row_count
            FROM {table_name}
            GROUP BY {id_column}
            ORDER BY row_count DESC, {id_column} DESC
            LIMIT 1
            """
        ).fetchone()
    return (str(row[0]), table_name) if row else (None, None)


def resolve_run_id(con: duckdb.DuckDBPyConnection, requested_run_id: str) -> tuple[str, str, list[str]]:
    if requested_run_id != "latest":
        return requested_run_id, "explicit", []

    warnings: list[str] = []
    for resolver in (
        _latest_model_run,
        lambda conn: _latest_state_run(conn, "sector_state_daily", "run_id"),
        lambda conn: _latest_state_run(conn, "walk_forward_cache_runs", "cache_key"),
        lambda conn: _latest_state_run(conn, "walk_forward_state_cache", "cache_key"),
    ):
        run_id, source = resolver(con)
        if run_id:
            return run_id, source or "unknown", warnings

    warnings.append("run_id latest could not be resolved from local HMM tables")
    return requested_run_id, "unresolved", warnings


def _optional_expr(columns: set[str], column: str, alias: str, default_sql: str = "CAST(NULL AS VARCHAR)") -> str:
    if column in columns:
        return f"CAST({column} AS VARCHAR) AS {alias}"
    return f"{default_sql} AS {alias}"


def _read_state_table(
    con: duckdb.DuckDBPyConnection,
    *,
    table_name: str,
    run_id: str,
    id_column: str,
) -> pd.DataFrame:
    columns = set(table_columns(con, table_name))
    if not columns or id_column not in columns or "trade_date" not in columns:
        return pd.DataFrame()

    sector_column = _first_existing(columns, ("sector_id", "sector_code"))
    state_label_column = _first_existing(columns, ("state_label", "display_label"))
    state_id_column = _first_existing(columns, ("state_id", "state"))
    if sector_column is None or (state_label_column is None and state_id_column is None):
        return pd.DataFrame()

    if state_id_column and state_label_column:
        state_key_expr = f"COALESCE(CAST({state_id_column} AS VARCHAR), CAST({state_label_column} AS VARCHAR))"
    elif state_id_column:
        state_key_expr = f"CAST({state_id_column} AS VARCHAR)"
    else:
        state_key_expr = f"CAST({state_label_column} AS VARCHAR)"

    if state_label_column:
        state_label_expr = f"CAST({state_label_column} AS VARCHAR)"
    else:
        state_label_expr = f"CAST({state_id_column} AS VARCHAR)"

    df = con.execute(
        f"""
        SELECT
          CAST({id_column} AS VARCHAR) AS run_id,
          CAST({sector_column} AS VARCHAR) AS sector_id,
          trade_date,
          {state_key_expr} AS state_key,
          {state_label_expr} AS state_label,
          {_optional_expr(columns, "feature_scope_id", "feature_scope_id")},
          {_optional_expr(columns, "universe_id", "universe_id")},
          {_optional_expr(columns, "state_source", "state_source", "'unknown_due_to_missing_metadata'")},
          '{table_name}' AS source_table
        FROM {table_name}
        WHERE {id_column} = ?
        ORDER BY {sector_column}, trade_date
        """,
        [run_id],
    ).fetchdf()
    return df


def read_state_rows(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    frames: list[pd.DataFrame] = []

    if table_exists(con, "sector_state_daily"):
        frames.append(_read_state_table(con, table_name="sector_state_daily", run_id=run_id, id_column="run_id"))
    if table_exists(con, "walk_forward_state_cache"):
        frames.append(
            _read_state_table(
                con,
                table_name="walk_forward_state_cache",
                run_id=run_id,
                id_column="cache_key",
            )
        )

    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        warnings.append(f"state rows not found for run_id={run_id}")
        return pd.DataFrame(), warnings

    preferred = frames[0].copy()
    if len(frames) > 1:
        warnings.append("multiple state sources found; using sector_state_daily before walk_forward_state_cache")
    return preferred, warnings


def classify_churn_bucket(
    transition_rate_1d: float | None,
    single_day_episode_share: float | None,
    *,
    sequence_length: int,
    thresholds: Mapping[str, Mapping[str, float]] = DEFAULT_THRESHOLDS,
) -> str:
    if (
        sequence_length < 2
        or transition_rate_1d is None
        or single_day_episode_share is None
        or pd.isna(transition_rate_1d)
        or pd.isna(single_day_episode_share)
    ):
        return "unknown"

    if (
        transition_rate_1d <= thresholds["low"]["transition_rate_1d_max"]
        and single_day_episode_share <= thresholds["low"]["single_day_episode_share_max"]
    ):
        return "low"
    if (
        transition_rate_1d <= thresholds["medium"]["transition_rate_1d_max"]
        and single_day_episode_share <= thresholds["medium"]["single_day_episode_share_max"]
    ):
        return "medium"
    if (
        transition_rate_1d <= thresholds["high"]["transition_rate_1d_max"]
        and single_day_episode_share <= thresholds["high"]["single_day_episode_share_max"]
    ):
        return "high"
    return "excessive"


def fragmentation_score(transition_rate_1d: float | None, single_day_episode_share: float | None) -> float | None:
    if transition_rate_1d is None or single_day_episode_share is None:
        return None
    high_rate = DEFAULT_THRESHOLDS["high"]["transition_rate_1d_max"]
    high_single = DEFAULT_THRESHOLDS["high"]["single_day_episode_share_max"]
    return _round_float(min(1.0, max(0.0, ((transition_rate_1d / high_rate) + (single_day_episode_share / high_single)) / 2)))


def compute_churn_dwell(
    state_rows: pd.DataFrame,
    *,
    run_id: str,
    created_at: str | None = None,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    created_at = created_at or utc_now_iso()
    if state_rows.empty:
        return pd.DataFrame(columns=SEQUENCE_COLUMNS), _empty_metrics(run_id, created_at)

    work = state_rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work["state_key"] = work["state_key"].where(work["state_key"].notna(), work["state_label"])
    work = work.dropna(subset=["sector_id", "trade_date", "state_key"])
    if work.empty:
        return pd.DataFrame(columns=SEQUENCE_COLUMNS), _empty_metrics(run_id, created_at)

    work["sector_id"] = work["sector_id"].astype(str)
    work["state_key"] = work["state_key"].astype(str)
    work["state_label"] = work["state_label"].where(work["state_label"].notna(), work["state_key"]).astype(str)
    work = work.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)

    transition_count = 0
    adjacent_count = 0
    records: list[dict[str, Any]] = []
    for sector_id, group in work.groupby("sector_id", sort=False):
        group = group.sort_values("trade_date").reset_index(drop=True)
        changed = group["state_key"].ne(group["state_key"].shift())
        if len(group) > 1:
            transition_count += int(changed.iloc[1:].sum())
            adjacent_count += len(group) - 1
        group["episode_number"] = changed.cumsum()

        for _, episode in group.groupby("episode_number", sort=False):
            start = pd.Timestamp(episode["trade_date"].iloc[0]).date().isoformat()
            end = pd.Timestamp(episode["trade_date"].iloc[-1]).date().isoformat()
            dwell_days = int(len(episode))
            records.append(
                {
                    "run_id": run_id,
                    "sector_id": str(sector_id),
                    "state_key": str(episode["state_key"].iloc[0]),
                    "state_label": str(episode["state_label"].iloc[-1]),
                    "episode_start_date": start,
                    "episode_end_date": end,
                    "dwell_days": dwell_days,
                    "is_single_day_episode": dwell_days == 1,
                    "feature_scope_id": _first_text(episode.get("feature_scope_id", pd.Series(dtype=object))),
                    "universe_id": _first_text(episode.get("universe_id", pd.Series(dtype=object))),
                    "source_table": _first_text(episode.get("source_table", pd.Series(dtype=object))),
                    "state_source": _first_text(episode.get("state_source", pd.Series(dtype=object))),
                    "created_at": created_at,
                }
            )

    episodes = pd.DataFrame(records, columns=SEQUENCE_COLUMNS)
    dwell = episodes["dwell_days"].astype(float) if not episodes.empty else pd.Series(dtype=float)
    transition_rate = (transition_count / adjacent_count) if adjacent_count else None
    episode_count = int(len(episodes))
    single_day_share = float(episodes["is_single_day_episode"].mean()) if episode_count else None
    bucket = classify_churn_bucket(transition_rate, single_day_share, sequence_length=int(len(work)))

    metrics = {
        "run_id": run_id,
        "row_count": int(len(work)),
        "sector_count": int(work["sector_id"].nunique()),
        "min_trade_date": pd.Timestamp(work["trade_date"].min()).date().isoformat(),
        "max_trade_date": pd.Timestamp(work["trade_date"].max()).date().isoformat(),
        "transition_count": int(transition_count),
        "transition_rate_1d": _round_float(transition_rate),
        "mean_dwell_days": _round_float(dwell.mean()) if not dwell.empty else None,
        "median_dwell_days": _round_float(dwell.median()) if not dwell.empty else None,
        "p10_dwell_days": _round_float(dwell.quantile(0.10)) if not dwell.empty else None,
        "p90_dwell_days": _round_float(dwell.quantile(0.90)) if not dwell.empty else None,
        "single_day_episode_share": _round_float(single_day_share),
        "episode_count": episode_count,
        "fragmentation_score": fragmentation_score(_round_float(transition_rate), _round_float(single_day_share)),
        "churn_bucket": bucket,
        "created_at": created_at,
    }
    return episodes, metrics


def _empty_metrics(run_id: str, created_at: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "row_count": 0,
        "sector_count": 0,
        "min_trade_date": None,
        "max_trade_date": None,
        "transition_count": 0,
        "transition_rate_1d": None,
        "mean_dwell_days": None,
        "median_dwell_days": None,
        "p10_dwell_days": None,
        "p90_dwell_days": None,
        "single_day_episode_share": None,
        "episode_count": 0,
        "fragmentation_score": None,
        "churn_bucket": "unknown",
        "created_at": created_at,
    }


def _integration_status_from_rows(rows: pd.DataFrame, *, low_tokens: set[str], ok_status: str) -> str:
    if rows.empty:
        return "missing_for_run"
    text = " ".join(
        str(value).lower()
        for value in rows.head(20).to_numpy().ravel()
        if value is not None and not (isinstance(value, float) and pd.isna(value))
    )
    if any(token in text for token in low_tokens):
        return "low_confidence" if ok_status == "available_confidence" else "unstable"
    return ok_status


def inspect_confidence_integration(con: duckdb.DuckDBPyConnection, run_id: str) -> str:
    for table_name in ("hmm_confidence_run_summary", "hmm_confidence_daily"):
        if not table_exists(con, table_name):
            continue
        columns = set(table_columns(con, table_name))
        if "run_id" not in columns:
            return "available_table_without_run_id"
        rows = con.execute(f"SELECT * FROM {table_name} WHERE run_id = ? LIMIT 20", [run_id]).fetchdf()
        return _integration_status_from_rows(
            rows,
            low_tokens={"low_confidence", "low confidence", "insufficient", "blocked", "research_only", "fail"},
            ok_status="available_confidence",
        )
    return "unavailable"


def inspect_alignment_integration(con: duckdb.DuckDBPyConnection, run_id: str) -> str:
    if not table_exists(con, "hmm_label_alignment_audit"):
        return "unavailable"
    columns = set(table_columns(con, "hmm_label_alignment_audit"))
    if "run_id" not in columns:
        return "available_table_without_run_id"
    rows = con.execute("SELECT * FROM hmm_label_alignment_audit WHERE run_id = ? LIMIT 20", [run_id]).fetchdf()
    return _integration_status_from_rows(
        rows,
        low_tokens={"unstable", "misaligned", "low_stability", "fail", "failed", "blocked"},
        ok_status="available_alignment",
    )


def _has_causal_cache(state_rows: pd.DataFrame) -> bool | None:
    if state_rows.empty:
        return None
    if "source_table" in state_rows and state_rows["source_table"].astype(str).eq("walk_forward_state_cache").any():
        return True
    if "state_source" not in state_rows:
        return None
    sources = {str(value).strip().lower() for value in state_rows["state_source"].dropna()}
    if sources & CAUSAL_SOURCES:
        return True
    if sources:
        return False
    return None


def ensure_output_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SEQUENCE_TABLE} (
          run_id TEXT,
          sector_id TEXT,
          state_key TEXT,
          state_label TEXT,
          episode_start_date DATE,
          episode_end_date DATE,
          dwell_days INTEGER,
          is_single_day_episode BOOLEAN,
          feature_scope_id TEXT,
          universe_id TEXT,
          source_table TEXT,
          state_source TEXT,
          created_at TIMESTAMP
        )
        """
    )
    con.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {SUMMARY_TABLE} (
          run_id TEXT,
          row_count INTEGER,
          sector_count INTEGER,
          min_trade_date DATE,
          max_trade_date DATE,
          transition_count INTEGER,
          transition_rate_1d DOUBLE,
          mean_dwell_days DOUBLE,
          median_dwell_days DOUBLE,
          p10_dwell_days DOUBLE,
          p90_dwell_days DOUBLE,
          single_day_episode_share DOUBLE,
          episode_count INTEGER,
          fragmentation_score DOUBLE,
          churn_bucket TEXT,
          dwell_readiness_status TEXT,
          display_action TEXT,
          confidence_integration_status TEXT,
          alignment_integration_status TEXT,
          report_path TEXT,
          created_at TIMESTAMP
        )
        """
    )


def write_output_tables(
    con: duckdb.DuckDBPyConnection,
    *,
    run_id: str,
    episodes: pd.DataFrame,
    summary_row: Mapping[str, Any],
) -> dict[str, Any]:
    ensure_output_tables(con)
    con.execute(f"DELETE FROM {SEQUENCE_TABLE} WHERE run_id = ?", [run_id])
    con.execute(f"DELETE FROM {SUMMARY_TABLE} WHERE run_id = ?", [run_id])

    if not episodes.empty:
        episode_frame = episodes.reindex(columns=SEQUENCE_COLUMNS)
        con.register("_stage01_wp_c_sequence", episode_frame)
        con.execute(
            f"""
            INSERT INTO {SEQUENCE_TABLE} ({", ".join(SEQUENCE_COLUMNS)})
            SELECT {", ".join(SEQUENCE_COLUMNS)}
            FROM _stage01_wp_c_sequence
            """
        )
        con.unregister("_stage01_wp_c_sequence")

    summary_frame = pd.DataFrame([{column: summary_row.get(column) for column in SUMMARY_COLUMNS}])
    con.register("_stage01_wp_c_summary", summary_frame)
    con.execute(
        f"""
        INSERT INTO {SUMMARY_TABLE} ({", ".join(SUMMARY_COLUMNS)})
        SELECT {", ".join(SUMMARY_COLUMNS)}
        FROM _stage01_wp_c_summary
        """
    )
    con.unregister("_stage01_wp_c_summary")
    return {
        "db_tables_written": [SEQUENCE_TABLE, SUMMARY_TABLE],
        "sequence_rows_written": int(len(episodes)),
        "summary_rows_written": 1,
    }


def build_markdown_report(summary: Mapping[str, Any]) -> str:
    warnings = summary.get("warnings") or []
    lines = [
        "# Stage 01 WP-C HMM Churn/Dwell Report",
        "",
        f"index_id: {summary['index_id']}",
        f"status: {summary['status']}",
        f"run_id: {summary['run_id']}",
        f"state rows found: {'yes' if summary['state_rows_found'] else 'no'}",
        f"churn/dwell rows generated: {summary['churn_dwell_rows_generated']}",
        f"row coverage: {summary.get('row_count', 0)} rows, {summary.get('sector_count', 0)} sectors",
        f"date coverage: {summary.get('min_trade_date') or 'n/a'} .. {summary.get('max_trade_date') or 'n/a'}",
        "",
        "## Metrics",
        "",
        f"- transition_count: {summary.get('transition_count')}",
        f"- transition_rate_1d: {summary.get('transition_rate_1d')}",
        f"- mean_dwell_days: {summary.get('mean_dwell_days')}",
        f"- median_dwell_days: {summary.get('median_dwell_days')}",
        f"- p10_dwell_days: {summary.get('p10_dwell_days')}",
        f"- p90_dwell_days: {summary.get('p90_dwell_days')}",
        f"- single_day_episode_share: {summary.get('single_day_episode_share')}",
        f"- episode_count: {summary.get('episode_count')}",
        f"- fragmentation_score: {summary.get('fragmentation_score')}",
        f"- churn_bucket: {summary.get('churn_bucket')}",
        "",
        "## Readiness",
        "",
        f"- dwell_readiness_status: {summary.get('dwell_readiness_status')}",
        f"- display_action: {summary.get('display_action')}",
        f"- confidence_integration_status: {summary.get('confidence_integration_status')}",
        f"- alignment_integration_status: {summary.get('alignment_integration_status')}",
        f"- causal_cache_available: {summary.get('causal_cache_available')}",
        "",
        "## Threshold Defaults",
        "",
        "- low: transition_rate_1d <= 0.10 and single_day_episode_share <= 0.15",
        "- medium: transition_rate_1d <= 0.20 and single_day_episode_share <= 0.30",
        "- high: transition_rate_1d <= 0.35 and single_day_episode_share <= 0.50",
        "- excessive: either metric is above the high threshold",
        "- unknown: missing or insufficient state sequence",
        "",
        "## Boundary Flags",
        "",
        f"- external_data_fetch: {'yes' if summary.get('external_data_fetch') else 'no'}",
        f"- training_algorithm_modified: {'yes' if summary.get('training_algorithm_modified') else 'no'}",
        f"- implemented WP-A confidence: {'yes' if summary.get('implemented_wp_a_confidence') else 'no'}",
        f"- implemented WP-B label alignment: {'yes' if summary.get('implemented_wp_b_label_alignment') else 'no'}",
        "",
        "## Warnings",
    ]
    if warnings:
        lines.extend(f"- {warning}" for warning in warnings)
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


def generate_hmm_churn_dwell_report(
    *,
    db_path: str | Path,
    run_id: str,
    output: str | Path,
    summary_json: str | Path,
    no_fetch: bool = True,
) -> dict[str, Any]:
    output_path = Path(output)
    summary_path = Path(summary_json)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    db = Path(db_path)
    created_at = utc_now_iso()
    warnings: list[str] = []
    db_write_result: dict[str, Any] = {
        "db_tables_written": [],
        "sequence_rows_written": 0,
        "summary_rows_written": 0,
    }

    if not db.exists():
        metrics = _empty_metrics(run_id, created_at)
        decision = evaluate_hmm_churn_dwell_display(
            churn_bucket="unknown",
            confidence_integration_status="unavailable",
            alignment_integration_status="unavailable",
            causal_cache_available=None,
        )
        warnings.append(f"database file not found: {db}")
        summary = _build_summary_payload(
            requested_run_id=run_id,
            resolved_run_id=run_id,
            resolved_run_id_source="db_missing",
            output_path=output_path,
            summary_path=summary_path,
            db_path=db,
            db_found=False,
            state_rows_found=False,
            metrics=metrics,
            decision=decision,
            confidence_status="unavailable",
            alignment_status="unavailable",
            causal_cache_available=None,
            warnings=warnings,
            db_write_result=db_write_result,
            no_fetch=no_fetch,
        )
        _write_report_files(output_path, summary_path, summary)
        return summary

    with duckdb.connect(str(db)) as con:
        resolved_run_id, resolved_source, resolve_warnings = resolve_run_id(con, run_id)
        warnings.extend(resolve_warnings)
        state_rows, state_warnings = read_state_rows(con, resolved_run_id)
        warnings.extend(state_warnings)
        episodes, metrics = compute_churn_dwell(state_rows, run_id=resolved_run_id, created_at=created_at)
        confidence_status = inspect_confidence_integration(con, resolved_run_id)
        alignment_status = inspect_alignment_integration(con, resolved_run_id)
        causal_cache_available = _has_causal_cache(state_rows)
        decision = evaluate_hmm_churn_dwell_display(
            churn_bucket=metrics["churn_bucket"],
            confidence_integration_status=confidence_status,
            alignment_integration_status=alignment_status,
            causal_cache_available=causal_cache_available,
        )
        summary_row = {
            **metrics,
            "dwell_readiness_status": decision.readiness_status,
            "display_action": decision.metadata.get("display_action", decision.action),
            "confidence_integration_status": confidence_status,
            "alignment_integration_status": alignment_status,
            "report_path": str(output_path),
        }
        db_write_result = write_output_tables(
            con,
            run_id=resolved_run_id,
            episodes=episodes,
            summary_row=summary_row,
        )

    summary = _build_summary_payload(
        requested_run_id=run_id,
        resolved_run_id=metrics["run_id"],
        resolved_run_id_source=resolved_source,
        output_path=output_path,
        summary_path=summary_path,
        db_path=db,
        db_found=True,
        state_rows_found=bool(metrics["row_count"]),
        metrics=metrics,
        decision=decision,
        confidence_status=confidence_status,
        alignment_status=alignment_status,
        causal_cache_available=causal_cache_available,
        warnings=warnings,
        db_write_result=db_write_result,
        no_fetch=no_fetch,
    )
    _write_report_files(output_path, summary_path, summary)
    return summary


def _build_summary_payload(
    *,
    requested_run_id: str,
    resolved_run_id: str,
    resolved_run_id_source: str,
    output_path: Path,
    summary_path: Path,
    db_path: Path,
    db_found: bool,
    state_rows_found: bool,
    metrics: Mapping[str, Any],
    decision: Any,
    confidence_status: str,
    alignment_status: str,
    causal_cache_available: bool | None,
    warnings: Sequence[str],
    db_write_result: Mapping[str, Any],
    no_fetch: bool,
) -> dict[str, Any]:
    decision_warnings = list(getattr(decision, "warnings", ()))
    combined_warnings = list(dict.fromkeys([*warnings, *decision_warnings]))
    status = "pass" if state_rows_found and metrics.get("churn_bucket") != "unknown" else "partial"
    payload = {
        "index_id": INDEX_ID,
        "work_package": WORK_PACKAGE,
        "version": VERSION,
        "generated_at": utc_now_iso(),
        "status": status,
        "requested_run_id": requested_run_id,
        "run_id": resolved_run_id,
        "resolved_run_id_source": resolved_run_id_source,
        "report_path": str(output_path),
        "summary_json_path": str(summary_path),
        "db_path": str(db_path),
        "db_found": db_found,
        "db_used": db_found,
        "state_rows_found": state_rows_found,
        "churn_dwell_rows_generated": int(db_write_result.get("sequence_rows_written", 0)),
        "dwell_readiness_status": decision.readiness_status,
        "display_action": decision.metadata.get("display_action", decision.action),
        "confidence_integration_status": confidence_status,
        "alignment_integration_status": alignment_status,
        "causal_cache_available": causal_cache_available,
        "external_data_fetch": False,
        "no_fetch_mode": bool(no_fetch),
        "training_algorithm_modified": False,
        "implemented_wp_a_confidence": False,
        "implemented_wp_b_label_alignment": False,
        "thresholds": DEFAULT_THRESHOLDS,
        "db_write_result": dict(db_write_result),
        "warnings": combined_warnings,
        **dict(metrics),
    }
    return payload


def _write_report_files(output_path: Path, summary_path: Path, summary: Mapping[str, Any]) -> None:
    output_path.write_text(build_markdown_report(summary), encoding="utf-8")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Stage 01 WP-C HMM churn/dwell diagnostics.")
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
    summary = generate_hmm_churn_dwell_report(
        db_path=args.db,
        run_id=args.run_id,
        output=args.output,
        summary_json=args.summary_json,
        no_fetch=args.no_fetch,
    )
    print(f"status: {summary['status']}")
    print(f"run_id: {summary['run_id']}")
    print(f"report: {summary['report_path']}")
    print(f"summary_json: {summary['summary_json_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
