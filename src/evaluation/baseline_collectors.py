"""Collectors for the Stage 00 baseline-freeze snapshot.

The collectors are intentionally read-only. They never fetch market data, update
universes, or call data updaters; they only inspect local files and an optional
DuckDB database opened in read-only mode.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


KEY_TABLES = [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_model_runs",
    "hsmm_model_checkpoints",
    "hsmm_state_daily",
    "hsmm_state_episodes",
    "hsmm_display_label_episodes",
    "hsmm_lifecycle_ui_daily",
    "hsmm_lifecycle_duration_profile",
    "hsmm_next_state_tendency_profile",
    "market_breadth_daily",
    "sector_features",
]

REQUIRED_HMM_REPORTS = [
    "reports/signal_validation/primary_20260529_main/summary.md",
    "OVERALL_EVALUATION_20260530.md",
    "EVALUATION_README.md",
]

REQUIRED_HSMM_ARTIFACTS = [
    "HSMM_LIFECYCLE_UI_V0_HARDENING_TEST_RESULTS_20260601.md",
    "HSMM_DISPLAY_LIFECYCLE_EVALUATION_20260601.md",
    "HSMM_PROBABILITY_VALIDITY_EVALUATION_20260531.md",
    "reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_full_run",
    "reports/hsmm_display_lifecycle/hsmm_lifecycle_primary_v1_latest_asof_20251031_cutoff_only",
]

DATE_COLUMNS = [
    "trade_date",
    "state_date",
    "date",
    "as_of_date",
    "profile_cutoff_date",
]
RUN_COLUMNS = ["run_id", "model_run_id", "cache_run_id", "hsmm_run_id"]
SECTOR_COLUMNS = ["sector_id", "sector_code", "sector_name", "industry_code"]
SAMPLE_COLUMNS = ["feature_scope_id", "universe_id"]


@dataclass
class TableProfile:
    table_name: str
    exists: bool
    row_count: int | None = None
    min_trade_date: str | None = None
    max_trade_date: str | None = None
    distinct_run_count: int | None = None
    distinct_sector_count: int | None = None
    feature_scope_id_sample: list[str] = field(default_factory=list)
    universe_id_sample: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class ArtifactStatus:
    path: str
    exists: bool
    kind: str
    size_bytes: int | None = None


@dataclass
class DatabaseSnapshot:
    db_path: str
    db_available: bool
    db_found: bool
    db_file_size: int | None
    duckdb_opened_read_only: bool
    duckdb_version: str | None
    db_open_error: str | None
    table_profiles: list[TableProfile]
    run_inventory: list[dict[str, Any]]
    v0_fact_checks: dict[str, Any]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    return str(value)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=json_default) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, records: Iterable[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=json_default) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})


def _csv_value(value: Any) -> Any:
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    if value is None:
        return ""
    return value


def collect_environment(working_dir: Path) -> dict[str, Any]:
    duckdb_version = get_duckdb_version()
    requirement_files = collect_requirement_files(working_dir)
    package_list = sorted(
        f"{dist.metadata.get('Name', dist.metadata['Name'])}=={dist.version}"
        for dist in importlib.metadata.distributions()
        if dist.metadata.get("Name")
    )

    return {
        "python_version": sys.version.split()[0],
        "duckdb_version": duckdb_version,
        "platform": platform.platform(),
        "working_directory": str(working_dir),
        "is_git_repo": is_git_repo(working_dir),
        "git_sha": git_sha(working_dir),
        "requirements": requirement_files,
        "package_list": package_list,
        "created_at": utc_now_iso(),
    }


def get_duckdb_version() -> str | None:
    try:
        import duckdb  # type: ignore
    except Exception:
        return None
    return getattr(duckdb, "__version__", "unknown")


def is_git_repo(working_dir: Path) -> bool:
    result = subprocess.run(
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def git_sha(working_dir: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=working_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def collect_requirement_files(working_dir: Path) -> list[dict[str, Any]]:
    candidates = ["requirements.txt", "pyproject.toml", "setup.cfg", "setup.py"]
    records: list[dict[str, Any]] = []
    for relative_path in candidates:
        path = working_dir / relative_path
        if not path.exists():
            continue
        data = path.read_bytes()
        records.append(
            {
                "path": relative_path,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size_bytes": len(data),
            }
        )
    return records


def collect_artifact_inventory(working_dir: Path) -> list[ArtifactStatus]:
    artifacts: list[ArtifactStatus] = []
    for relative_path in REQUIRED_HMM_REPORTS:
        artifacts.append(_artifact_status(working_dir, relative_path, "hmm_signal_validation"))
    for relative_path in REQUIRED_HSMM_ARTIFACTS:
        artifacts.append(_artifact_status(working_dir, relative_path, "hsmm_lifecycle"))
    return artifacts


def _artifact_status(working_dir: Path, relative_path: str, kind: str) -> ArtifactStatus:
    path = working_dir / relative_path
    return ArtifactStatus(
        path=relative_path,
        exists=path.exists(),
        kind=kind,
        size_bytes=path.stat().st_size if path.exists() and path.is_file() else None,
    )


def collect_database_snapshot(db_path: Path) -> DatabaseSnapshot:
    db_found = db_path.exists()
    db_size = db_path.stat().st_size if db_found else None
    duckdb_version = get_duckdb_version()
    if not db_found:
        return DatabaseSnapshot(
            db_path=str(db_path),
            db_available=False,
            db_found=False,
            db_file_size=db_size,
            duckdb_opened_read_only=False,
            duckdb_version=duckdb_version,
            db_open_error="database file not found",
            table_profiles=[TableProfile(table_name=name, exists=False) for name in KEY_TABLES],
            run_inventory=[],
            v0_fact_checks={"status": "skipped_db_missing"},
        )

    try:
        import duckdb  # type: ignore
    except Exception as exc:
        return DatabaseSnapshot(
            db_path=str(db_path),
            db_available=False,
            db_found=True,
            db_file_size=db_size,
            duckdb_opened_read_only=False,
            duckdb_version=None,
            db_open_error=f"duckdb import failed: {exc}",
            table_profiles=[TableProfile(table_name=name, exists=False) for name in KEY_TABLES],
            run_inventory=[],
            v0_fact_checks={"status": "skipped_duckdb_unavailable"},
        )

    connection = None
    try:
        connection = duckdb.connect(str(db_path), read_only=True)
        table_profiles = [profile_table(connection, table_name) for table_name in KEY_TABLES]
        run_inventory = collect_run_inventory(connection, table_profiles)
        return DatabaseSnapshot(
            db_path=str(db_path),
            db_available=True,
            db_found=True,
            db_file_size=db_size,
            duckdb_opened_read_only=True,
            duckdb_version=getattr(duckdb, "__version__", "unknown"),
            db_open_error=None,
            table_profiles=table_profiles,
            run_inventory=run_inventory,
            v0_fact_checks=collect_v0_fact_checks(connection),
        )
    except Exception as exc:
        return DatabaseSnapshot(
            db_path=str(db_path),
            db_available=False,
            db_found=True,
            db_file_size=db_size,
            duckdb_opened_read_only=False,
            duckdb_version=getattr(duckdb, "__version__", "unknown"),
            db_open_error=str(exc),
            table_profiles=[TableProfile(table_name=name, exists=False) for name in KEY_TABLES],
            run_inventory=[],
            v0_fact_checks={"status": "skipped_db_open_error", "error": str(exc)},
        )
    finally:
        if connection is not None:
            connection.close()


def profile_table(connection: Any, table_name: str) -> TableProfile:
    if not table_exists(connection, table_name):
        return TableProfile(table_name=table_name, exists=False, notes=["table_missing"])

    columns = table_columns(connection, table_name)
    notes: list[str] = []
    date_column = first_present(columns, DATE_COLUMNS)
    run_column = first_present(columns, RUN_COLUMNS)
    sector_column = first_present(columns, SECTOR_COLUMNS)

    if date_column is None:
        notes.append("no date column found for min_trade_date/max_trade_date")
    if run_column is None:
        notes.append("no run id column found for distinct_run_count")
    if sector_column is None:
        notes.append("no sector column found for distinct_sector_count")

    feature_scope_sample = sample_column(connection, table_name, "feature_scope_id", columns)
    universe_sample = sample_column(connection, table_name, "universe_id", columns)

    return TableProfile(
        table_name=table_name,
        exists=True,
        row_count=scalar_int(connection, f"select count(*) from {quote_identifier(table_name)}"),
        min_trade_date=scalar_text(
            connection,
            f"select min(cast({quote_identifier(date_column)} as varchar)) "
            f"from {quote_identifier(table_name)}",
        )
        if date_column
        else None,
        max_trade_date=scalar_text(
            connection,
            f"select max(cast({quote_identifier(date_column)} as varchar)) "
            f"from {quote_identifier(table_name)}",
        )
        if date_column
        else None,
        distinct_run_count=scalar_int(
            connection,
            f"select count(distinct {quote_identifier(run_column)}) from {quote_identifier(table_name)}",
        )
        if run_column
        else None,
        distinct_sector_count=scalar_int(
            connection,
            f"select count(distinct {quote_identifier(sector_column)}) from {quote_identifier(table_name)}",
        )
        if sector_column
        else None,
        feature_scope_id_sample=feature_scope_sample,
        universe_id_sample=universe_sample,
        notes=notes,
    )


def collect_run_inventory(connection: Any, profiles: list[TableProfile]) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for profile in profiles:
        if not profile.exists:
            continue
        columns = table_columns(connection, profile.table_name)
        run_column = first_present(columns, RUN_COLUMNS)
        if run_column is None:
            continue
        date_column = first_present(columns, DATE_COLUMNS)
        select_parts = [
            f"cast({quote_identifier(run_column)} as varchar) as run_id",
            "count(*) as row_count",
        ]
        if date_column:
            select_parts.extend(
                [
                    f"min(cast({quote_identifier(date_column)} as varchar)) as min_trade_date",
                    f"max(cast({quote_identifier(date_column)} as varchar)) as max_trade_date",
                ]
            )
        else:
            select_parts.extend(["null as min_trade_date", "null as max_trade_date"])
        for sample_column_name in SAMPLE_COLUMNS:
            if sample_column_name in columns:
                select_parts.append(
                    f"min(cast({quote_identifier(sample_column_name)} as varchar)) "
                    f"as {sample_column_name}_sample"
                )
            else:
                select_parts.append(f"null as {sample_column_name}_sample")

        query = (
            f"select {', '.join(select_parts)} from {quote_identifier(profile.table_name)} "
            f"where {quote_identifier(run_column)} is not null "
            f"group by {quote_identifier(run_column)} "
            f"order by row_count desc limit 200"
        )
        try:
            for row in connection.execute(query).fetchall():
                inventory.append(
                    {
                        "source_table": profile.table_name,
                        "run_id": row[0],
                        "row_count": row[1],
                        "min_trade_date": row[2],
                        "max_trade_date": row[3],
                        "feature_scope_id_sample": row[4],
                        "universe_id_sample": row[5],
                    }
                )
        except Exception as exc:
            inventory.append(
                {
                    "source_table": profile.table_name,
                    "run_id": None,
                    "row_count": None,
                    "min_trade_date": None,
                    "max_trade_date": None,
                    "feature_scope_id_sample": None,
                    "universe_id_sample": None,
                    "error": str(exc),
                }
            )
    return inventory


def collect_v0_fact_checks(connection: Any) -> dict[str, Any]:
    checks: dict[str, Any] = {
        "reference_notes": {
            "hsmm_run_id": "hsmm_lifecycle_primary_v1",
            "full_run_lifecycle_rows_reference": 155118,
            "date_range_reference": ["2025-01-02", "2026-05-28"],
            "sector_count_reference": 464,
            "trade_day_count_reference": 337,
            "duplicate_sector_date_reference": 0,
            "future_episode_leakage_reference": 0,
            "raw_score_used_violation_reference": 0,
        }
    }
    if table_exists(connection, "hsmm_lifecycle_ui_daily"):
        checks["hsmm_lifecycle_ui_daily"] = {
            "run_id": "hsmm_lifecycle_primary_v1",
            "row_count_for_run": safe_scalar(
                connection,
                "select count(*) from hsmm_lifecycle_ui_daily where run_id = 'hsmm_lifecycle_primary_v1'",
            ),
            "min_trade_date_for_run": safe_scalar(
                connection,
                "select min(cast(trade_date as varchar)) from hsmm_lifecycle_ui_daily "
                "where run_id = 'hsmm_lifecycle_primary_v1'",
            ),
            "max_trade_date_for_run": safe_scalar(
                connection,
                "select max(cast(trade_date as varchar)) from hsmm_lifecycle_ui_daily "
                "where run_id = 'hsmm_lifecycle_primary_v1'",
            ),
            "sector_count_for_run": safe_scalar(
                connection,
                "select count(distinct sector_id) from hsmm_lifecycle_ui_daily "
                "where run_id = 'hsmm_lifecycle_primary_v1'",
            ),
            "trade_day_count_for_run": safe_scalar(
                connection,
                "select count(distinct trade_date) from hsmm_lifecycle_ui_daily "
                "where run_id = 'hsmm_lifecycle_primary_v1'",
            ),
            "duplicate_sector_date_keys": safe_scalar(
                connection,
                "select count(*) from ("
                "select sector_id, trade_date, count(*) as n from hsmm_lifecycle_ui_daily "
                "where run_id = 'hsmm_lifecycle_primary_v1' group by sector_id, trade_date having count(*) > 1"
                ")",
            ),
        }
    else:
        checks["hsmm_lifecycle_ui_daily"] = {"status": "missing_evidence"}
    return checks


def table_exists(connection: Any, table_name: str) -> bool:
    query = (
        "select count(*) from information_schema.tables "
        "where lower(table_name) = lower(?) and table_schema not in ('information_schema', 'pg_catalog')"
    )
    return bool(connection.execute(query, [table_name]).fetchone()[0])


def table_columns(connection: Any, table_name: str) -> set[str]:
    rows = connection.execute(
        "select column_name from information_schema.columns where lower(table_name) = lower(?)",
        [table_name],
    ).fetchall()
    return {row[0] for row in rows}


def first_present(columns: set[str], candidates: list[str]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def sample_column(connection: Any, table_name: str, column: str, columns: set[str]) -> list[str]:
    if column not in columns:
        return []
    query = (
        f"select distinct cast({quote_identifier(column)} as varchar) "
        f"from {quote_identifier(table_name)} where {quote_identifier(column)} is not null "
        f"order by cast({quote_identifier(column)} as varchar) limit 5"
    )
    return [row[0] for row in connection.execute(query).fetchall()]


def quote_identifier(identifier: str | None) -> str:
    if identifier is None:
        raise ValueError("identifier cannot be None")
    return '"' + identifier.replace('"', '""') + '"'


def scalar_int(connection: Any, query: str) -> int | None:
    value = connection.execute(query).fetchone()[0]
    return int(value) if value is not None else None


def scalar_text(connection: Any, query: str) -> str | None:
    value = connection.execute(query).fetchone()[0]
    return str(value) if value is not None else None


def safe_scalar(connection: Any, query: str) -> Any:
    try:
        return connection.execute(query).fetchone()[0]
    except Exception as exc:
        return {"error": str(exc)}


def dataclass_list(records: Iterable[Any]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]
