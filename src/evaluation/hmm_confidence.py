from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import duckdb
import pandas as pd


INDEX_ID = "STAGE01-WP-A-v1"
CANONICAL_READINESS_STATUSES = {
    "blocked",
    "research_only",
    "internal_only",
    "partial",
    "validated",
    "decision_ready",
}
POSTERIOR_EXCLUDED_TOKENS = (
    "next",
    "transition",
    "calibrated",
    "raw_",
    "p_exit",
    "probability_type",
)


@dataclass(frozen=True)
class ConfidenceThresholds:
    high_max: float = 0.70
    high_margin: float = 0.25
    high_entropy_norm: float = 0.65
    medium_max: float = 0.55
    medium_margin: float = 0.12
    medium_entropy_norm: float = 0.85
    unclear_margin: float = 0.08
    unclear_entropy_norm: float = 0.90


@dataclass(frozen=True)
class PosteriorMetrics:
    posterior_max: float | None
    posterior_second: float | None
    posterior_margin: float | None
    posterior_entropy: float | None
    posterior_entropy_norm: float | None
    confidence_bucket: str
    confidence_reason: str
    state_confidence_readiness: str


@dataclass
class ConfidenceRunResult:
    index_id: str = INDEX_ID
    status: str = "partial"
    report_status: str = "partial_not_started"
    run_id: str | None = None
    db_path: str = ""
    local_db_used: bool = False
    posterior_columns: list[str] = field(default_factory=list)
    posterior_columns_found: bool = False
    confidence_rows_generated: int = 0
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    report_path: str | None = None
    summary_json_path: str | None = None
    external_data_fetch: bool = False
    training_algorithm_modified: bool = False


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def json_default(value: Any) -> Any:
    if isinstance(value, (datetime, pd.Timestamp)):
        return value.isoformat()
    if pd.isna(value):
        return None
    return str(value)


def quote_identifier(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    return bool(
        con.execute(
            """
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
    )


def table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not table_exists(con, table_name):
        return []
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()]


def detect_posterior_columns(columns: Sequence[str]) -> list[str]:
    candidates: list[str] = []
    for column in columns:
        lowered = column.lower()
        if any(token in lowered for token in POSTERIOR_EXCLUDED_TOKENS):
            continue
        if lowered.startswith(("prob_", "state_prob_", "posterior_", "state_posterior_")):
            candidates.append(column)
            continue
        if lowered.endswith("_posterior") or lowered.endswith("_prob"):
            candidates.append(column)
    return candidates if len(candidates) >= 2 else []


def _finite_probabilities(values: Iterable[Any]) -> tuple[list[float] | None, str | None]:
    probabilities: list[float] = []
    for value in values:
        if value is None or pd.isna(value):
            return None, "missing_posterior_value"
        try:
            probability = float(value)
        except (TypeError, ValueError):
            return None, "non_numeric_posterior_value"
        if not math.isfinite(probability):
            return None, "non_finite_posterior_value"
        if probability < -1e-9 or probability > 1.0 + 1e-9:
            return None, "posterior_value_out_of_bounds"
        probabilities.append(max(0.0, probability))

    total = sum(probabilities)
    if total <= 0:
        return None, "posterior_sum_not_positive"
    if not math.isclose(total, 1.0, rel_tol=1e-6, abs_tol=1e-6):
        return None, "posterior_sum_not_one"
    return probabilities, None


def compute_posterior_metrics(
    values: Sequence[Any],
    thresholds: ConfidenceThresholds | None = None,
) -> PosteriorMetrics:
    thresholds = thresholds or ConfidenceThresholds()
    probabilities, invalid_reason = _finite_probabilities(values)
    if probabilities is None or len(probabilities) < 2:
        return PosteriorMetrics(
            posterior_max=None,
            posterior_second=None,
            posterior_margin=None,
            posterior_entropy=None,
            posterior_entropy_norm=None,
            confidence_bucket="missing",
            confidence_reason=invalid_reason or "posterior_vector_missing",
            state_confidence_readiness="blocked",
        )

    ordered = sorted(probabilities, reverse=True)
    posterior_max = ordered[0]
    posterior_second = ordered[1]
    posterior_margin = posterior_max - posterior_second
    entropy = -sum(value * math.log(value) for value in probabilities if value > 0)
    entropy_norm = entropy / math.log(len(probabilities))

    if (
        posterior_max >= thresholds.high_max
        and posterior_margin >= thresholds.high_margin
        and entropy_norm <= thresholds.high_entropy_norm
    ):
        bucket = "high"
        reason = "high_max_margin_low_entropy"
        readiness = "internal_only"
    elif (
        posterior_max >= thresholds.medium_max
        and posterior_margin >= thresholds.medium_margin
        and entropy_norm <= thresholds.medium_entropy_norm
    ):
        bucket = "medium"
        reason = "medium_max_margin_entropy"
        readiness = "internal_only"
    elif posterior_margin < thresholds.unclear_margin:
        bucket = "unclear"
        reason = "near_tie"
        readiness = "research_only"
    elif entropy_norm >= thresholds.unclear_entropy_norm:
        bucket = "unclear"
        reason = "high_entropy"
        readiness = "research_only"
    else:
        bucket = "low"
        reason = "below_medium_threshold"
        readiness = "research_only"

    return PosteriorMetrics(
        posterior_max=posterior_max,
        posterior_second=posterior_second,
        posterior_margin=posterior_margin,
        posterior_entropy=entropy,
        posterior_entropy_norm=entropy_norm,
        confidence_bucket=bucket,
        confidence_reason=reason,
        state_confidence_readiness=readiness,
    )


def ensure_hmm_confidence_schema(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(path)) as con:
        con.execute("SET timezone='Asia/Shanghai'")
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS hmm_confidence_daily (
              run_id TEXT NOT NULL,
              trade_date DATE NOT NULL,
              sector_id TEXT NOT NULL,
              sector_code TEXT,
              sector_name TEXT,
              state_id INTEGER,
              state_label TEXT,
              posterior_max DOUBLE,
              posterior_second DOUBLE,
              posterior_margin DOUBLE,
              posterior_entropy DOUBLE,
              posterior_entropy_norm DOUBLE,
              confidence_bucket TEXT NOT NULL,
              confidence_reason TEXT NOT NULL,
              state_confidence_readiness TEXT NOT NULL CHECK (state_confidence_readiness IN ('blocked', 'research_only', 'internal_only', 'partial', 'validated', 'decision_ready')),
              posterior_columns_json TEXT NOT NULL,
              feature_scope_id TEXT,
              universe_id TEXT,
              created_at TIMESTAMP NOT NULL,
              PRIMARY KEY (run_id, trade_date, sector_id)
            );
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS hmm_confidence_run_summary (
              run_id TEXT PRIMARY KEY,
              row_count BIGINT NOT NULL,
              sector_count BIGINT NOT NULL,
              min_trade_date DATE,
              max_trade_date DATE,
              high_count BIGINT NOT NULL,
              medium_count BIGINT NOT NULL,
              low_count BIGINT NOT NULL,
              unclear_count BIGINT NOT NULL,
              missing_count BIGINT NOT NULL,
              high_share DOUBLE NOT NULL,
              medium_share DOUBLE NOT NULL,
              low_share DOUBLE NOT NULL,
              unclear_share DOUBLE NOT NULL,
              missing_share DOUBLE NOT NULL,
              median_posterior_max DOUBLE,
              median_posterior_margin DOUBLE,
              median_entropy_norm DOUBLE,
              readiness_status TEXT NOT NULL CHECK (readiness_status IN ('blocked', 'research_only', 'internal_only', 'partial', 'validated', 'decision_ready')),
              report_path TEXT,
              created_at TIMESTAMP NOT NULL
            );
            """
        )


def resolve_run_id(con: duckdb.DuckDBPyConnection, requested_run_id: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    if requested_run_id != "latest":
        return requested_run_id, warnings

    if table_exists(con, "model_runs") and "run_id" in table_columns(con, "model_runs"):
        columns = table_columns(con, "model_runs")
        where = ""
        if "model_type" in columns:
            where = "WHERE model_type IS NULL OR lower(CAST(model_type AS TEXT)) LIKE '%hmm%'"
        order = "run_id"
        if "created_at" in columns:
            order = "created_at DESC NULLS LAST, run_id DESC"
        row = con.execute(f"SELECT run_id FROM model_runs {where} ORDER BY {order} LIMIT 1").fetchone()
        if row and row[0] is not None:
            return str(row[0]), warnings
        warnings.append("model_runs did not contain a latest HMM run_id")
    else:
        warnings.append("model_runs table missing or lacks run_id")

    if table_exists(con, "sector_state_daily") and "run_id" in table_columns(con, "sector_state_daily"):
        columns = table_columns(con, "sector_state_daily")
        if "trade_date" in columns:
            row = con.execute(
                """
                SELECT run_id
                FROM sector_state_daily
                GROUP BY run_id
                ORDER BY max(trade_date) DESC NULLS LAST, run_id DESC
                LIMIT 1
                """
            ).fetchone()
        else:
            row = con.execute("SELECT run_id FROM sector_state_daily WHERE run_id IS NOT NULL LIMIT 1").fetchone()
        if row and row[0] is not None:
            warnings.append("latest run_id resolved from sector_state_daily fallback")
            return str(row[0]), warnings

    warnings.append("run_id could not be resolved")
    return None, warnings


def _select_source_rows(
    con: duckdb.DuckDBPyConnection,
    run_id: str,
    posterior_columns: Sequence[str],
) -> pd.DataFrame:
    columns = table_columns(con, "sector_state_daily")
    desired = [
        "run_id",
        "trade_date",
        "sector_id",
        "sector_code",
        "sector_name",
        "state_id",
        "state_label",
        "feature_scope_id",
        "universe_id",
        *posterior_columns,
    ]
    selected = [column for column in desired if column in columns]
    if "run_id" not in selected:
        return pd.DataFrame()
    sql = f"""
        SELECT {", ".join(quote_identifier(column) for column in selected)}
        FROM sector_state_daily
        WHERE run_id = ?
    """
    if "trade_date" in selected:
        sql += " ORDER BY trade_date, " + quote_identifier(
            "sector_id" if "sector_id" in selected else selected[0]
        )
    return con.execute(sql, [run_id]).fetchdf()


def build_daily_confidence_rows(
    source_rows: pd.DataFrame,
    posterior_columns: Sequence[str],
    thresholds: ConfidenceThresholds | None = None,
) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    created_at = utc_now()
    posterior_columns_json = json.dumps(list(posterior_columns), ensure_ascii=False)
    for row_index, row in source_rows.reset_index(drop=True).iterrows():
        metrics = compute_posterior_metrics([row.get(column) for column in posterior_columns], thresholds)
        sector_id = row.get("sector_id")
        sector_code = row.get("sector_code")
        if _is_missing(sector_id):
            sector_id = sector_code
        if _is_missing(sector_id):
            sector_id = f"row_{row_index}"
        records.append(
            {
                "run_id": row.get("run_id"),
                "trade_date": row.get("trade_date"),
                "sector_id": str(sector_id),
                "sector_code": _optional_text(sector_code),
                "sector_name": _optional_value(row.get("sector_name")),
                "state_id": _optional_value(row.get("state_id")),
                "state_label": _optional_value(row.get("state_label")),
                "posterior_max": metrics.posterior_max,
                "posterior_second": metrics.posterior_second,
                "posterior_margin": metrics.posterior_margin,
                "posterior_entropy": metrics.posterior_entropy,
                "posterior_entropy_norm": metrics.posterior_entropy_norm,
                "confidence_bucket": metrics.confidence_bucket,
                "confidence_reason": metrics.confidence_reason,
                "state_confidence_readiness": metrics.state_confidence_readiness,
                "posterior_columns_json": posterior_columns_json,
                "feature_scope_id": _optional_value(row.get("feature_scope_id")),
                "universe_id": _optional_value(row.get("universe_id")),
                "created_at": created_at,
            }
        )
    return pd.DataFrame(records)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _optional_text(value: Any) -> str | None:
    if _is_missing(value):
        return None
    return str(value)


def _optional_value(value: Any) -> Any:
    if _is_missing(value):
        return None
    return value


def summarize_confidence_rows(
    daily_rows: pd.DataFrame,
    run_id: str,
    report_path: str | None = None,
) -> dict[str, Any]:
    row_count = int(len(daily_rows))
    bucket_counts = {
        bucket: int((daily_rows["confidence_bucket"] == bucket).sum()) if row_count else 0
        for bucket in ("high", "medium", "low", "unclear", "missing")
    }

    if row_count:
        high_medium_share = (bucket_counts["high"] + bucket_counts["medium"]) / row_count
        missing_share = bucket_counts["missing"] / row_count
        ambiguous_share = (bucket_counts["low"] + bucket_counts["unclear"]) / row_count
        if missing_share > 0:
            readiness_status = "partial"
        elif high_medium_share >= 0.75 and ambiguous_share <= 0.25:
            readiness_status = "internal_only"
        else:
            readiness_status = "research_only"
    else:
        readiness_status = "blocked"

    summary: dict[str, Any] = {
        "run_id": run_id,
        "row_count": row_count,
        "sector_count": int(daily_rows["sector_id"].nunique()) if row_count else 0,
        "min_trade_date": daily_rows["trade_date"].min() if row_count else None,
        "max_trade_date": daily_rows["trade_date"].max() if row_count else None,
        **{f"{bucket}_count": count for bucket, count in bucket_counts.items()},
        **{f"{bucket}_share": (count / row_count if row_count else 0.0) for bucket, count in bucket_counts.items()},
        "median_posterior_max": _median_or_none(daily_rows, "posterior_max"),
        "median_posterior_margin": _median_or_none(daily_rows, "posterior_margin"),
        "median_entropy_norm": _median_or_none(daily_rows, "posterior_entropy_norm"),
        "readiness_status": readiness_status,
        "report_path": report_path,
        "created_at": utc_now(),
    }
    return summary


def _median_or_none(df: pd.DataFrame, column: str) -> float | None:
    if df.empty or column not in df.columns:
        return None
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.median())


def upsert_confidence_outputs(
    con: duckdb.DuckDBPyConnection,
    daily_rows: pd.DataFrame,
    summary: Mapping[str, Any],
) -> None:
    daily_columns = [
        "run_id",
        "trade_date",
        "sector_id",
        "sector_code",
        "sector_name",
        "state_id",
        "state_label",
        "posterior_max",
        "posterior_second",
        "posterior_margin",
        "posterior_entropy",
        "posterior_entropy_norm",
        "confidence_bucket",
        "confidence_reason",
        "state_confidence_readiness",
        "posterior_columns_json",
        "feature_scope_id",
        "universe_id",
        "created_at",
    ]
    if not daily_rows.empty:
        con.register("incoming_hmm_confidence_daily", daily_rows[daily_columns])
        con.execute(
            f"""
            INSERT INTO hmm_confidence_daily ({", ".join(daily_columns)})
            SELECT {", ".join(daily_columns)} FROM incoming_hmm_confidence_daily
            ON CONFLICT (run_id, trade_date, sector_id) DO UPDATE SET
              sector_code = EXCLUDED.sector_code,
              sector_name = EXCLUDED.sector_name,
              state_id = EXCLUDED.state_id,
              state_label = EXCLUDED.state_label,
              posterior_max = EXCLUDED.posterior_max,
              posterior_second = EXCLUDED.posterior_second,
              posterior_margin = EXCLUDED.posterior_margin,
              posterior_entropy = EXCLUDED.posterior_entropy,
              posterior_entropy_norm = EXCLUDED.posterior_entropy_norm,
              confidence_bucket = EXCLUDED.confidence_bucket,
              confidence_reason = EXCLUDED.confidence_reason,
              state_confidence_readiness = EXCLUDED.state_confidence_readiness,
              posterior_columns_json = EXCLUDED.posterior_columns_json,
              feature_scope_id = EXCLUDED.feature_scope_id,
              universe_id = EXCLUDED.universe_id,
              created_at = EXCLUDED.created_at
            """
        )

    summary_columns = [
        "run_id",
        "row_count",
        "sector_count",
        "min_trade_date",
        "max_trade_date",
        "high_count",
        "medium_count",
        "low_count",
        "unclear_count",
        "missing_count",
        "high_share",
        "medium_share",
        "low_share",
        "unclear_share",
        "missing_share",
        "median_posterior_max",
        "median_posterior_margin",
        "median_entropy_norm",
        "readiness_status",
        "report_path",
        "created_at",
    ]
    summary_df = pd.DataFrame([{column: summary.get(column) for column in summary_columns}])
    con.register("incoming_hmm_confidence_summary", summary_df)
    con.execute(
        f"""
        INSERT INTO hmm_confidence_run_summary ({", ".join(summary_columns)})
        SELECT {", ".join(summary_columns)} FROM incoming_hmm_confidence_summary
        ON CONFLICT (run_id) DO UPDATE SET
          row_count = EXCLUDED.row_count,
          sector_count = EXCLUDED.sector_count,
          min_trade_date = EXCLUDED.min_trade_date,
          max_trade_date = EXCLUDED.max_trade_date,
          high_count = EXCLUDED.high_count,
          medium_count = EXCLUDED.medium_count,
          low_count = EXCLUDED.low_count,
          unclear_count = EXCLUDED.unclear_count,
          missing_count = EXCLUDED.missing_count,
          high_share = EXCLUDED.high_share,
          medium_share = EXCLUDED.medium_share,
          low_share = EXCLUDED.low_share,
          unclear_share = EXCLUDED.unclear_share,
          missing_share = EXCLUDED.missing_share,
          median_posterior_max = EXCLUDED.median_posterior_max,
          median_posterior_margin = EXCLUDED.median_posterior_margin,
          median_entropy_norm = EXCLUDED.median_entropy_norm,
          readiness_status = EXCLUDED.readiness_status,
          report_path = EXCLUDED.report_path,
          created_at = EXCLUDED.created_at
        """
    )


def write_reports(result: ConfidenceRunResult, output_path: str | Path, summary_json_path: str | Path) -> None:
    output = Path(output_path)
    summary_json = Path(summary_json_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    result.report_path = str(output)
    result.summary_json_path = str(summary_json)

    payload = asdict(result)
    payload["posterior_semantic_statement"] = (
        "HMM posterior probabilities are state confidence diagnostics only; "
        "they are not return, rising, falling, profit, buy, or sell probabilities."
    )
    summary_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default) + "\n", encoding="utf-8")

    summary = result.summary
    lines = [
        "# Stage 01 WP-A HMM Confidence Report",
        "",
        f"- index_id: {result.index_id}",
        f"- status: {result.status}",
        f"- report_status: {result.report_status}",
        f"- db_path: {result.db_path}",
        f"- local_db_used: {str(result.local_db_used).lower()}",
        f"- run_id: {result.run_id or 'unresolved'}",
        f"- posterior_columns_found: {str(result.posterior_columns_found).lower()}",
        f"- posterior_columns_used: {', '.join(result.posterior_columns) if result.posterior_columns else 'none'}",
        f"- confidence_rows_generated: {result.confidence_rows_generated}",
        f"- external_data_fetch: {str(result.external_data_fetch).lower()}",
        f"- training_algorithm_modified: {str(result.training_algorithm_modified).lower()}",
        "",
        "## Semantics",
        "",
        "HMM posterior probabilities are state confidence diagnostics only. They are not return probability, rising probability, falling probability, profit probability, buy probability, or sell probability.",
        "",
        "## Threshold Defaults",
        "",
        "| bucket | rule | readiness |",
        "|---|---|---|",
        "| high | posterior_max >= 0.70, posterior_margin >= 0.25, entropy_norm <= 0.65 | internal_only |",
        "| medium | posterior_max >= 0.55, posterior_margin >= 0.12, entropy_norm <= 0.85 | internal_only |",
        "| unclear | posterior_margin < 0.08 or entropy_norm >= 0.90 | research_only |",
        "| low | valid posterior vector below medium threshold | research_only |",
        "| missing | missing or invalid posterior vector | blocked |",
        "",
        "## Run Summary",
        "",
        f"- row_count: {summary.get('row_count', 0)}",
        f"- sector_count: {summary.get('sector_count', 0)}",
        f"- data_range: {summary.get('min_trade_date') or 'n/a'} to {summary.get('max_trade_date') or 'n/a'}",
        f"- readiness_status: {summary.get('readiness_status', 'n/a')}",
        f"- median_posterior_max: {_format_float(summary.get('median_posterior_max'))}",
        f"- median_posterior_margin: {_format_float(summary.get('median_posterior_margin'))}",
        f"- median_entropy_norm: {_format_float(summary.get('median_entropy_norm'))}",
        "",
        "## Confidence Bucket Distribution",
        "",
        "| bucket | count | share |",
        "|---|---:|---:|",
    ]
    for bucket in ("high", "medium", "low", "unclear", "missing"):
        lines.append(
            f"| {bucket} | {summary.get(f'{bucket}_count', 0)} | {_format_float(summary.get(f'{bucket}_share', 0.0))} |"
        )
    lines.extend(["", "## Warnings", ""])
    if result.warnings:
        lines.extend(f"- {warning}" for warning in result.warnings)
    else:
        lines.append("- none")
    lines.append("")
    output.write_text("\n".join(lines), encoding="utf-8")


def _format_float(value: Any) -> str:
    if value is None or pd.isna(value):
        return "n/a"
    return f"{float(value):.6f}"


def _partial_result(
    *,
    db_path: str,
    report_status: str,
    warnings: Sequence[str],
    run_id: str | None = None,
    local_db_used: bool = False,
    posterior_columns: Sequence[str] = (),
    report_path: str | None = None,
) -> ConfidenceRunResult:
    summary = {
        "run_id": run_id,
        "row_count": 0,
        "sector_count": 0,
        "min_trade_date": None,
        "max_trade_date": None,
        "high_count": 0,
        "medium_count": 0,
        "low_count": 0,
        "unclear_count": 0,
        "missing_count": 0,
        "high_share": 0.0,
        "medium_share": 0.0,
        "low_share": 0.0,
        "unclear_share": 0.0,
        "missing_share": 0.0,
        "median_posterior_max": None,
        "median_posterior_margin": None,
        "median_entropy_norm": None,
        "readiness_status": "blocked" if report_status != "partial_missing_posterior_columns" else "partial",
        "report_path": report_path,
        "created_at": utc_now(),
    }
    return ConfidenceRunResult(
        status="partial",
        report_status=report_status,
        run_id=run_id,
        db_path=db_path,
        local_db_used=local_db_used,
        posterior_columns=list(posterior_columns),
        posterior_columns_found=bool(posterior_columns),
        confidence_rows_generated=0,
        summary=summary,
        warnings=list(warnings),
    )


def run_hmm_confidence_report(
    *,
    db_path: str | Path,
    run_id: str,
    output_path: str | Path,
    summary_json_path: str | Path,
    no_fetch: bool = True,
) -> ConfidenceRunResult:
    if not no_fetch:
        raise ValueError("Stage 01 WP-A does not support fetching external data")

    db_path_str = str(db_path)
    output_str = str(output_path)
    db_file = Path(db_path)
    if not db_file.exists():
        result = _partial_result(
            db_path=db_path_str,
            report_status="partial_missing_db",
            warnings=[f"database file not found: {db_path_str}"],
            report_path=output_str,
        )
        write_reports(result, output_path, summary_json_path)
        return result

    ensure_hmm_confidence_schema(db_file)
    with duckdb.connect(str(db_file)) as con:
        con.execute("SET timezone='Asia/Shanghai'")
        if not table_exists(con, "sector_state_daily"):
            result = _partial_result(
                db_path=db_path_str,
                report_status="partial_missing_source_table",
                warnings=["sector_state_daily table is missing"],
                local_db_used=True,
                report_path=output_str,
            )
            write_reports(result, output_path, summary_json_path)
            return result

        resolved_run_id, run_warnings = resolve_run_id(con, run_id)
        if not resolved_run_id:
            result = _partial_result(
                db_path=db_path_str,
                report_status="partial_missing_run_id",
                warnings=run_warnings,
                local_db_used=True,
                report_path=output_str,
            )
            write_reports(result, output_path, summary_json_path)
            return result

        columns = table_columns(con, "sector_state_daily")
        posterior_columns = detect_posterior_columns(columns)
        if not posterior_columns:
            result = _partial_result(
                db_path=db_path_str,
                report_status="partial_missing_posterior_columns",
                warnings=[*run_warnings, "no HMM posterior probability columns found in sector_state_daily"],
                run_id=resolved_run_id,
                local_db_used=True,
                report_path=output_str,
            )
            write_reports(result, output_path, summary_json_path)
            return result

        source_rows = _select_source_rows(con, resolved_run_id, posterior_columns)
        if source_rows.empty:
            result = _partial_result(
                db_path=db_path_str,
                report_status="partial_no_rows_for_run",
                warnings=[*run_warnings, f"no sector_state_daily rows found for run_id={resolved_run_id}"],
                run_id=resolved_run_id,
                local_db_used=True,
                posterior_columns=posterior_columns,
                report_path=output_str,
            )
            write_reports(result, output_path, summary_json_path)
            return result

        daily_rows = build_daily_confidence_rows(source_rows, posterior_columns)
        summary = summarize_confidence_rows(daily_rows, resolved_run_id, output_str)
        upsert_confidence_outputs(con, daily_rows, summary)

    result = ConfidenceRunResult(
        status="pass",
        report_status="pass",
        run_id=resolved_run_id,
        db_path=db_path_str,
        local_db_used=True,
        posterior_columns=list(posterior_columns),
        posterior_columns_found=True,
        confidence_rows_generated=int(len(daily_rows)),
        summary=dict(summary),
        warnings=run_warnings,
    )
    write_reports(result, output_path, summary_json_path)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 01 WP-A HMM confidence metrics")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    args = parser.parse_args(argv)

    try:
        result = run_hmm_confidence_report(
            db_path=args.db,
            run_id=args.run_id,
            output_path=args.output,
            summary_json_path=args.summary_json,
            no_fetch=args.no_fetch,
        )
    except Exception as exc:
        print(f"hmm confidence report failed: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "index_id": result.index_id,
                "status": result.status,
                "report_status": result.report_status,
                "run_id": result.run_id,
                "posterior_columns_found": result.posterior_columns_found,
                "confidence_rows_generated": result.confidence_rows_generated,
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
