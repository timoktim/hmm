from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any, Mapping, MutableMapping

import duckdb

from src.config import PROJECT_ROOT, settings
from src.data_pipeline.storage import DuckDBStorage


DEFAULT_DB_DIR = PROJECT_ROOT / "data" / "db"
WORKSPACE_CONFIG_PATH = DEFAULT_DB_DIR / "workspace_config.json"
SESSION_ACTIVE_DB_KEY = "active_db_path"
DB_PROFILE_TUSHARE_EMPTY = "tushare_empty"

_DB_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+\.duckdb$")
_LEGACY_SOURCE_MARKERS = ("akshare", "ths", "eastmoney", "mootdx")

CORE_TABLES = (
    "stock_ohlcv",
    "sector_ohlcv",
    "all_a_stock_universe",
    "market_breadth_daily",
    "data_health",
    "qfq_rebuild_runs",
    "qfq_rebuild_affected_stocks",
    "tushare_adj_factor_snapshot",
    "model_runs",
    "hsmm_model_runs",
    "hsmm_lifecycle_ui_daily",
)


@dataclass(frozen=True)
class DatabaseValidationResult:
    path: Path
    display_path: str
    exists: bool
    suffix_ok: bool
    can_connect: bool
    schema_initialized: bool
    missing_tables: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class DatabaseInfo:
    path: Path
    display_path: str
    exists: bool
    size_bytes: int
    modified_at: str | None
    schema_status: str
    label: str | None = None
    active: bool = False


@dataclass(frozen=True)
class DatabaseSummary:
    path_display: str
    exists: bool
    size_bytes: int
    modified_at: str | None
    validation: DatabaseValidationResult
    can_read_write: bool
    active_source: str
    latest_stock_trade_date: str | None = None
    latest_sector_trade_date: str | None = None
    latest_breadth_trade_date: str | None = None
    row_counts: dict[str, int] = field(default_factory=dict)
    source_distribution: dict[str, int] = field(default_factory=dict)
    legacy_sources: list[str] = field(default_factory=list)
    duplicate_stock_trade_date_count: int = 0
    latest_qfq_rebuild: dict[str, Any] = field(default_factory=dict)
    data_health_failure_count: int = 0


def _absolute_lexical(path: Path | str) -> Path:
    return Path(os.path.abspath(Path(path)))


def _display_db_path(path: Path | str) -> str:
    absolute = _absolute_lexical(path)
    project_root = _absolute_lexical(PROJECT_ROOT)
    db_dir = _absolute_lexical(DEFAULT_DB_DIR)
    try:
        return str(absolute.relative_to(project_root))
    except ValueError:
        pass
    try:
        suffix = absolute.relative_to(db_dir)
        return str(Path("data") / "db" / suffix)
    except ValueError:
        return Path(path).name


def _session_state_mapping(session_state: MutableMapping[str, Any] | None = None) -> MutableMapping[str, Any] | None:
    if session_state is not None:
        return session_state
    try:
        import streamlit as st

        return st.session_state
    except Exception:
        return None


def _read_workspace_config() -> dict[str, Any]:
    if not WORKSPACE_CONFIG_PATH.exists():
        return {}
    try:
        payload = json.loads(WORKSPACE_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_workspace_config(path: Path) -> None:
    WORKSPACE_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "active_db_path": _display_db_path(path),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "updated_by": "database_workspace",
    }
    WORKSPACE_CONFIG_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def project_safe_db_path(name_or_path: str | Path) -> Path:
    raw = str(name_or_path).strip()
    if not raw:
        raise ValueError("Database path is empty")
    raw_path = Path(raw)
    if len(raw_path.parts) == 1:
        candidate = DEFAULT_DB_DIR / raw
    elif len(raw_path.parts) >= 3 and raw_path.parts[0] == "data" and raw_path.parts[1] == "db":
        candidate = DEFAULT_DB_DIR.joinpath(*raw_path.parts[2:])
    else:
        candidate = raw_path
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = _absolute_lexical(candidate)
    db_dir = _absolute_lexical(DEFAULT_DB_DIR)
    try:
        candidate.relative_to(db_dir)
    except ValueError as exc:
        raise ValueError("Database path must stay under data/db") from exc
    if candidate.suffix != ".duckdb":
        raise ValueError("Database path must end with .duckdb")
    if candidate.exists() and candidate.is_dir():
        raise ValueError("Database path points to a directory")
    if len(Path(raw).parts) == 1 and not _DB_NAME_RE.fullmatch(raw):
        raise ValueError("Database filename may only contain letters, numbers, underscores, hyphens, and dots")
    return candidate


def resolve_active_db_path(session_state: MutableMapping[str, Any] | None = None) -> Path:
    state = _session_state_mapping(session_state)
    if state is not None:
        raw = state.get(SESSION_ACTIVE_DB_KEY)
        if raw:
            try:
                return project_safe_db_path(raw)
            except ValueError:
                pass

    config = _read_workspace_config()
    raw_config_path = config.get("active_db_path")
    if raw_config_path:
        try:
            return project_safe_db_path(raw_config_path)
        except ValueError:
            pass
    return _absolute_lexical(settings.db_path)


def set_active_db_path(path: Path, session_state: MutableMapping[str, Any] | None = None) -> None:
    safe_path = project_safe_db_path(path)
    if not safe_path.exists():
        raise FileNotFoundError(f"Database does not exist: {_display_db_path(safe_path)}")
    if safe_path.is_dir():
        raise ValueError("Database path points to a directory")
    _write_workspace_config(safe_path)
    state = _session_state_mapping(session_state)
    if state is not None:
        state[SESSION_ACTIVE_DB_KEY] = _display_db_path(safe_path)


def _existing_tables(con: duckdb.DuckDBPyConnection) -> set[str]:
    rows = con.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
        """
    ).fetchall()
    return {str(row[0]) for row in rows}


def validate_database(path: Path, initialize: bool = False) -> DatabaseValidationResult:
    display_path = _display_db_path(path)
    try:
        safe_path = project_safe_db_path(path)
    except ValueError as exc:
        return DatabaseValidationResult(
            path=Path(path),
            display_path=display_path,
            exists=Path(path).exists(),
            suffix_ok=Path(path).suffix == ".duckdb",
            can_connect=False,
            schema_initialized=False,
            missing_tables=list(CORE_TABLES),
            errors=[str(exc)],
        )

    exists = safe_path.exists()
    suffix_ok = safe_path.suffix == ".duckdb"
    errors: list[str] = []
    warnings: list[str] = []
    if not exists:
        return DatabaseValidationResult(
            path=safe_path,
            display_path=display_path,
            exists=False,
            suffix_ok=suffix_ok,
            can_connect=False,
            schema_initialized=False,
            missing_tables=list(CORE_TABLES),
            errors=["Database file does not exist"],
        )
    if safe_path.is_dir():
        return DatabaseValidationResult(
            path=safe_path,
            display_path=display_path,
            exists=True,
            suffix_ok=suffix_ok,
            can_connect=False,
            schema_initialized=False,
            missing_tables=list(CORE_TABLES),
            errors=["Database path points to a directory"],
        )

    if initialize:
        try:
            DuckDBStorage(safe_path).init_schema()
        except Exception as exc:
            errors.append(f"init_schema failed: {exc}")

    can_connect = False
    missing_tables = list(CORE_TABLES)
    try:
        # Streamlit keeps reruns inside one Python process. DuckDB rejects
        # opening the same file with mixed read_only/read_write configs, so UI
        # metadata probes use the same connection profile as DuckDBStorage.
        with DuckDBStorage(safe_path).connect() as con:
            can_connect = True
            tables = _existing_tables(con)
            missing_tables = [table for table in CORE_TABLES if table not in tables]
    except Exception as exc:
        errors.append(f"connect failed: {exc}")

    if can_connect and missing_tables:
        warnings.append("Core schema is incomplete")
    return DatabaseValidationResult(
        path=safe_path,
        display_path=display_path,
        exists=True,
        suffix_ok=suffix_ok,
        can_connect=can_connect,
        schema_initialized=can_connect and not missing_tables,
        missing_tables=missing_tables,
        warnings=warnings,
        errors=errors,
    )


def _metadata_rows(label: str | None, profile: str) -> dict[str, str]:
    now = datetime.now().isoformat(timespec="seconds")
    rows = {
        "db_profile": profile,
        "created_by": "database_workspace",
        "created_at": now,
        "schema_version": "unknown",
        "active_source": settings.market_data_source or settings.default_source or "tushare",
    }
    if label:
        rows["label"] = label
    return rows


def _write_database_metadata(path: Path, label: str | None = None, profile: str = DB_PROFILE_TUSHARE_EMPTY) -> None:
    rows = _metadata_rows(label, profile)
    with DuckDBStorage(path).connect() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS database_workspace_metadata (
              key TEXT PRIMARY KEY,
              value TEXT,
              updated_at TIMESTAMP
            )
            """
        )
        for key, value in rows.items():
            con.execute(
                """
                INSERT INTO database_workspace_metadata(key, value, updated_at)
                VALUES (?, ?, now())
                ON CONFLICT(key) DO UPDATE SET
                  value = excluded.value,
                  updated_at = excluded.updated_at
                """,
                [key, value],
            )


def create_database(path: Path, label: str | None = None, initialize_schema: bool = True) -> DatabaseInfo:
    safe_path = project_safe_db_path(path)
    if safe_path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {_display_db_path(safe_path)}")
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    storage = DuckDBStorage(safe_path)
    if initialize_schema:
        storage.init_schema()
    else:
        with storage.connect():
            pass
    _write_database_metadata(safe_path, label=label, profile=DB_PROFILE_TUSHARE_EMPTY)
    return _database_info(safe_path)


def archive_database(path: Path, archive_dir: Path | None = None) -> DatabaseInfo:
    safe_path = project_safe_db_path(path)
    if not safe_path.exists():
        raise FileNotFoundError(f"Database does not exist: {_display_db_path(safe_path)}")
    if safe_path.is_dir():
        raise ValueError("Database path points to a directory")
    destination_dir = archive_dir or (DEFAULT_DB_DIR / "archive")
    if not destination_dir.is_absolute():
        destination_dir = PROJECT_ROOT / destination_dir
    destination_dir = _absolute_lexical(destination_dir)
    db_dir = _absolute_lexical(DEFAULT_DB_DIR)
    try:
        destination_dir.relative_to(db_dir)
    except ValueError as exc:
        raise ValueError("Archive directory must stay under data/db") from exc
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = destination_dir / f"{safe_path.stem}_backup_{timestamp}.duckdb"
    counter = 1
    while target.exists():
        target = destination_dir / f"{safe_path.stem}_backup_{timestamp}_{counter}.duckdb"
        counter += 1
    shutil.copy2(safe_path, target)
    return _database_info(target)


def _database_info(path: Path, active_path: Path | None = None) -> DatabaseInfo:
    exists = path.exists()
    validation = validate_database(path)
    if not exists:
        schema_status = "missing"
    elif validation.schema_initialized:
        schema_status = "ok"
    elif validation.can_connect:
        schema_status = "incomplete"
    else:
        schema_status = "unreadable"
    stat = path.stat() if exists else None
    return DatabaseInfo(
        path=path,
        display_path=_display_db_path(path),
        exists=exists,
        size_bytes=int(stat.st_size) if stat else 0,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
        schema_status=schema_status,
        active=active_path is not None and _absolute_lexical(path) == _absolute_lexical(active_path),
    )


def list_database_files(exclude_paths: Iterable[Path | str] | None = None) -> list[DatabaseInfo]:
    DEFAULT_DB_DIR.mkdir(parents=True, exist_ok=True)
    active_path = resolve_active_db_path()
    excluded = {_absolute_lexical(path) for path in exclude_paths or []}
    paths = sorted(DEFAULT_DB_DIR.glob("*.duckdb"), key=lambda item: item.stat().st_mtime if item.exists() else 0, reverse=True)
    return [_database_info(path, active_path=active_path) for path in paths if _absolute_lexical(path) not in excluded]


def _scalar(con: duckdb.DuckDBPyConnection, sql: str, params: list[Any] | None = None) -> Any:
    row = con.execute(sql, params or []).fetchone()
    return None if row is None else row[0]


def _date_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        return str(value.date())
    except AttributeError:
        return str(value)


def _row_counts(con: duckdb.DuckDBPyConnection, tables: set[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in CORE_TABLES:
        if table in tables:
            counts[table] = int(_scalar(con, f"SELECT COUNT(*) FROM {table}") or 0)
    return counts


def _source_distribution(con: duckdb.DuckDBPyConnection, tables: set[str]) -> dict[str, int]:
    if "stock_ohlcv" not in tables:
        return {}
    rows = con.execute(
        """
        SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS row_count
        FROM stock_ohlcv
        GROUP BY 1
        ORDER BY row_count DESC, source
        LIMIT 20
        """
    ).fetchall()
    return {str(source): int(row_count) for source, row_count in rows}


def _legacy_sources(distribution: Mapping[str, int]) -> list[str]:
    found: list[str] = []
    for source in distribution:
        lowered = str(source).lower()
        for marker in _LEGACY_SOURCE_MARKERS:
            if marker in lowered and marker not in found:
                found.append(marker)
    return found


def database_summary(path: Path) -> DatabaseSummary:
    validation = validate_database(path)
    safe_path = validation.path if validation.suffix_ok else Path(path)
    stat = safe_path.stat() if safe_path.exists() and safe_path.is_file() else None
    summary = DatabaseSummary(
        path_display=_display_db_path(safe_path),
        exists=bool(stat),
        size_bytes=int(stat.st_size) if stat else 0,
        modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
        validation=validation,
        can_read_write=bool(stat) and os.access(safe_path, os.R_OK | os.W_OK),
        active_source=settings.market_data_source or settings.default_source or "tushare",
    )
    if not validation.can_connect:
        return summary
    try:
        with DuckDBStorage(safe_path).connect() as con:
            tables = _existing_tables(con)
            row_counts = _row_counts(con, tables)
            source_distribution = _source_distribution(con, tables)
            latest_qfq: dict[str, Any] = {}
            if "qfq_rebuild_runs" in tables:
                qfq_row = con.execute(
                    """
                    SELECT rebuild_run_id, trigger_reason, status, created_at, completed_at
                    FROM qfq_rebuild_runs
                    ORDER BY created_at DESC
                    LIMIT 1
                    """
                ).fetchone()
                if qfq_row:
                    latest_qfq = {
                        "rebuild_run_id": qfq_row[0],
                        "trigger_reason": qfq_row[1],
                        "status": qfq_row[2],
                        "created_at": str(qfq_row[3]) if qfq_row[3] is not None else None,
                        "completed_at": str(qfq_row[4]) if qfq_row[4] is not None else None,
                    }
            duplicate_count = 0
            if "stock_ohlcv" in tables:
                duplicate_count = int(
                    _scalar(
                        con,
                        """
                        SELECT COUNT(*)
                        FROM (
                          SELECT stock_code, trade_date, COUNT(*) AS row_count
                          FROM stock_ohlcv
                          GROUP BY stock_code, trade_date
                          HAVING COUNT(*) > 1
                        )
                        """,
                    )
                    or 0
                )
            health_failures = 0
            if "data_health" in tables:
                health_failures = int(
                    _scalar(con, "SELECT COUNT(*) FROM data_health WHERE last_failure IS NOT NULL AND (last_success IS NULL OR last_failure > last_success)")
                    or 0
                )
            return DatabaseSummary(
                path_display=_display_db_path(safe_path),
                exists=bool(stat),
                size_bytes=int(stat.st_size) if stat else 0,
                modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
                validation=validation,
                can_read_write=bool(stat) and os.access(safe_path, os.R_OK | os.W_OK),
                active_source=settings.market_data_source or settings.default_source or "tushare",
                latest_stock_trade_date=_date_text(_scalar(con, "SELECT MAX(trade_date) FROM stock_ohlcv")) if "stock_ohlcv" in tables else None,
                latest_sector_trade_date=_date_text(_scalar(con, "SELECT MAX(trade_date) FROM sector_ohlcv")) if "sector_ohlcv" in tables else None,
                latest_breadth_trade_date=_date_text(_scalar(con, "SELECT MAX(trade_date) FROM market_breadth_daily")) if "market_breadth_daily" in tables else None,
                row_counts=row_counts,
                source_distribution=source_distribution,
                legacy_sources=_legacy_sources(source_distribution),
                duplicate_stock_trade_date_count=duplicate_count,
                latest_qfq_rebuild=latest_qfq,
                data_health_failure_count=health_failures,
            )
    except Exception as exc:
        failed_validation = DatabaseValidationResult(
            path=validation.path,
            display_path=validation.display_path,
            exists=validation.exists,
            suffix_ok=validation.suffix_ok,
            can_connect=False,
            schema_initialized=False,
            missing_tables=validation.missing_tables,
            warnings=validation.warnings,
            errors=[*validation.errors, f"summary failed: {exc}"],
        )
        return DatabaseSummary(
            path_display=_display_db_path(safe_path),
            exists=bool(stat),
            size_bytes=int(stat.st_size) if stat else 0,
            modified_at=datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds") if stat else None,
            validation=failed_validation,
            can_read_write=bool(stat) and os.access(safe_path, os.R_OK | os.W_OK),
            active_source=settings.market_data_source or settings.default_source or "tushare",
        )
