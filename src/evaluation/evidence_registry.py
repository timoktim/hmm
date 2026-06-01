from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


class EvidenceLevel(str, Enum):
    EXPLORATORY = "exploratory"
    INTERNAL_DIAGNOSTIC = "internal_diagnostic"
    VALIDATED_SIGNAL = "validated_signal"
    DECISION_SUPPORT = "decision_support"


class ReadinessStatus(str, Enum):
    BLOCKED = "blocked"
    RESEARCH_ONLY = "research_only"
    INTERNAL_ONLY = "internal_only"
    PARTIAL = "partial"
    VALIDATED = "validated"
    DECISION_READY = "decision_ready"


VALIDATION_STATUSES = {"pass", "fail", "skip", "error", "unknown"}
VALIDATION_TYPES = {
    "schema_migration",
    "unit_tests",
    "lifecycle_report",
    "signal_validation",
    "baseline_freeze",
    "ui_readiness_audit",
    "causal_audit",
}
KNOWN_RUN_TABLES = [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_model_runs",
    "hsmm_model_checkpoints",
    "hsmm_state_daily",
    "hsmm_lifecycle_ui_daily",
    "hsmm_lifecycle_duration_profile",
    "hsmm_next_state_tendency_profile",
]


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


@dataclass
class EvidenceRecord:
    run_id: str
    model_type: str
    evidence_level: EvidenceLevel | str
    readiness_status: ReadinessStatus | str
    evidence_id: str | None = None
    source_run_id: str | None = None
    model_family: str | None = None
    verdict_code: str | None = None
    verdict_label: str | None = None
    universe_id: str | None = None
    universe_version: str | None = None
    feature_scope_id: str | None = None
    feature_scope_type: str | None = None
    feature_version: str | None = None
    causal_cache_id: str | None = None
    benchmark_id: str | None = None
    train_start: date | str | None = None
    train_end: date | str | None = None
    eval_start: date | str | None = None
    eval_end: date | str | None = None
    inference_mode: str | None = None
    state_source: str | None = None
    data_source_policy: str | None = None
    execution_calendar: str | None = None
    cost_bps: float | None = None
    profile_mode: str | None = None
    profile_cutoff_date: date | str | None = None
    state_date_policy: str | None = None
    report_path: str | None = None
    ui_route: str | None = None
    artifact_manifest_json: str | dict[str, Any] | list[Any] | None = None
    metrics_json: str | dict[str, Any] | list[Any] | None = None
    notes: str | None = None
    created_at: datetime = field(default_factory=_utc_now)
    updated_at: datetime = field(default_factory=_utc_now)


@dataclass
class ValidationRunRecord:
    validation_type: str
    status: str
    validation_run_id: str | None = None
    run_id: str | None = None
    evidence_id: str | None = None
    command: str | None = None
    verdict_code: str | None = None
    started_at: datetime | str | None = None
    finished_at: datetime | str | None = None
    duration_seconds: float | None = None
    python_version: str | None = None
    duckdb_version: str | None = None
    platform: str | None = None
    git_sha: str | None = None
    db_path: str | None = None
    report_dir: str | None = None
    metrics_json: str | dict[str, Any] | list[Any] | None = None
    warnings_json: str | dict[str, Any] | list[Any] | None = None
    created_at: datetime = field(default_factory=_utc_now)


MODEL_EVIDENCE_COLUMNS = [
    "evidence_id",
    "run_id",
    "source_run_id",
    "model_type",
    "model_family",
    "evidence_level",
    "readiness_status",
    "verdict_code",
    "verdict_label",
    "universe_id",
    "universe_version",
    "feature_scope_id",
    "feature_scope_type",
    "feature_version",
    "causal_cache_id",
    "benchmark_id",
    "train_start",
    "train_end",
    "eval_start",
    "eval_end",
    "inference_mode",
    "state_source",
    "data_source_policy",
    "execution_calendar",
    "cost_bps",
    "profile_mode",
    "profile_cutoff_date",
    "state_date_policy",
    "report_path",
    "ui_route",
    "artifact_manifest_json",
    "metrics_json",
    "notes",
    "created_at",
    "updated_at",
]
VALIDATION_RUN_COLUMNS = [
    "validation_run_id",
    "run_id",
    "evidence_id",
    "validation_type",
    "command",
    "status",
    "verdict_code",
    "started_at",
    "finished_at",
    "duration_seconds",
    "python_version",
    "duckdb_version",
    "platform",
    "git_sha",
    "db_path",
    "report_dir",
    "metrics_json",
    "warnings_json",
    "created_at",
]
UI_POLICY_COLUMNS = [
    "policy_id",
    "surface",
    "field_name",
    "model_type",
    "required_evidence_level",
    "required_readiness_status",
    "allow_display",
    "display_mode",
    "fallback_text",
    "policy_reason",
    "created_at",
    "updated_at",
]
POLICY_SEEDS = [
    ("hmm_posterior_probability", "hmm_state", "posterior_probability", "hmm", "internal_diagnostic", "internal_only", True, "state_confidence_only", "状态概率不是上涨概率", "HMM posterior can describe state confidence only."),
    ("hmm_strategy_output", "strategy", "strategy_output", "hmm", "validated_signal", "validated", False, "research_only", "缺少 validated_signal 证据时仅限研究展示", "Strategy output must not be promoted without validation."),
    ("hsmm_state_age", "hsmm_lifecycle", "state_age", "hsmm", "internal_diagnostic", "internal_only", True, "display", None, "State age is an internal lifecycle diagnostic."),
    ("hsmm_state_phase", "hsmm_lifecycle", "state_phase", "hsmm", "internal_diagnostic", "internal_only", True, "display", None, "State phase is an internal lifecycle diagnostic."),
    ("hsmm_exit_tendency_low_medium_high", "hsmm_lifecycle", "exit_tendency_low_medium_high", "hsmm", "internal_diagnostic", "internal_only", True, "internal_ordinal", "仅显示低/中/高内部倾向", "Ordinal tendency is allowed; numeric probability is not."),
    ("hsmm_numeric_p_exit", "hsmm_lifecycle", "numeric_p_exit", "hsmm", "internal_diagnostic", "validated", False, "hide_unless_usable_probability", "p_exit 未验证为可用概率时隐藏", "Numeric p_exit must pass probability validation before display."),
    ("hsmm_invalid_probability", "hsmm_lifecycle", "invalid_probability", "hsmm", "internal_diagnostic", "blocked", False, "hide", "概率字段无效或样本不足", "Invalid probability fields must not be shown or filled with zero."),
    ("in_sample_state", "state_source", "in_sample_state", None, "exploratory", "research_only", True, "research_only", "样本内解释，不能用于因果回测", "In-sample state is historical explanation only."),
    ("causal_walk_forward_state", "state_source", "causal_walk_forward_state", None, "internal_diagnostic", "partial", True, "display_if_cache_valid", "需要有效 causal cache", "Causal state display requires valid walk-forward cache metadata."),
]


def _connect(db_path: str) -> duckdb.DuckDBPyConnection:
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(db_path)
    con.execute("SET timezone='Asia/Shanghai'")
    return con


def _json_dumps(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _enum_value(value: Enum | str, enum_type: type[Enum], field_name: str) -> str:
    if isinstance(value, enum_type):
        return value.value
    try:
        return enum_type(str(value)).value
    except ValueError as exc:
        allowed = ", ".join(item.value for item in enum_type)
        raise ValueError(f"Invalid {field_name}: {value!r}. Allowed: {allowed}") from exc


def _validate_value(value: str, allowed: set[str], field_name: str) -> str:
    normalized = str(value)
    if normalized not in allowed:
        raise ValueError(f"Invalid {field_name}: {value!r}. Allowed: {', '.join(sorted(allowed))}")
    return normalized


def _stable_hash(prefix: str, parts: list[str | None]) -> str:
    normalized = "\x1f".join("" if part is None else str(part).strip() for part in parts)
    return f"{prefix}_{hashlib.sha256(normalized.encode('utf-8')).hexdigest()[:24]}"


def make_evidence_id(run_id: str, model_type: str, report_path: str | None) -> str:
    normalized_path = str(report_path or "missing_report").replace("\\", "/").strip()
    return _stable_hash("evidence", [run_id, model_type.lower().strip(), normalized_path])


def _make_validation_run_id(record: ValidationRunRecord) -> str:
    return _stable_hash(
        "validation",
        [
            record.run_id,
            record.evidence_id,
            record.validation_type,
            record.command,
            str(record.started_at or ""),
            str(record.finished_at or ""),
            record.db_path,
        ],
    )


def ensure_evidence_registry_schema_for_connection(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS model_evidence_registry (
          evidence_id TEXT PRIMARY KEY,
          run_id TEXT NOT NULL,
          source_run_id TEXT,
          model_type TEXT NOT NULL,
          model_family TEXT,
          evidence_level TEXT NOT NULL CHECK (evidence_level IN ('exploratory', 'internal_diagnostic', 'validated_signal', 'decision_support')),
          readiness_status TEXT NOT NULL CHECK (readiness_status IN ('blocked', 'research_only', 'internal_only', 'partial', 'validated', 'decision_ready')),
          verdict_code TEXT,
          verdict_label TEXT,
          universe_id TEXT,
          universe_version TEXT,
          feature_scope_id TEXT,
          feature_scope_type TEXT,
          feature_version TEXT,
          causal_cache_id TEXT,
          benchmark_id TEXT,
          train_start DATE,
          train_end DATE,
          eval_start DATE,
          eval_end DATE,
          inference_mode TEXT,
          state_source TEXT,
          data_source_policy TEXT,
          execution_calendar TEXT,
          cost_bps DOUBLE,
          profile_mode TEXT,
          profile_cutoff_date DATE,
          state_date_policy TEXT,
          report_path TEXT,
          ui_route TEXT,
          artifact_manifest_json TEXT,
          metrics_json TEXT,
          notes TEXT,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS validation_runs (
          validation_run_id TEXT PRIMARY KEY,
          run_id TEXT,
          evidence_id TEXT,
          validation_type TEXT NOT NULL CHECK (validation_type IN ('schema_migration', 'unit_tests', 'lifecycle_report', 'signal_validation', 'baseline_freeze', 'ui_readiness_audit', 'causal_audit')),
          command TEXT,
          status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'skip', 'error', 'unknown')),
          verdict_code TEXT,
          started_at TIMESTAMP,
          finished_at TIMESTAMP,
          duration_seconds DOUBLE,
          python_version TEXT,
          duckdb_version TEXT,
          platform TEXT,
          git_sha TEXT,
          db_path TEXT,
          report_dir TEXT,
          metrics_json TEXT,
          warnings_json TEXT,
          created_at TIMESTAMP NOT NULL
        );
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS ui_readiness_policy (
          policy_id TEXT PRIMARY KEY,
          surface TEXT NOT NULL,
          field_name TEXT NOT NULL,
          model_type TEXT,
          required_evidence_level TEXT NOT NULL CHECK (required_evidence_level IN ('exploratory', 'internal_diagnostic', 'validated_signal', 'decision_support')),
          required_readiness_status TEXT NOT NULL CHECK (required_readiness_status IN ('blocked', 'research_only', 'internal_only', 'partial', 'validated', 'decision_ready')),
          allow_display BOOLEAN NOT NULL,
          display_mode TEXT NOT NULL,
          fallback_text TEXT,
          policy_reason TEXT,
          created_at TIMESTAMP NOT NULL,
          updated_at TIMESTAMP NOT NULL
        );
        """
    )


def ensure_evidence_registry_schema(db_path: str) -> None:
    with _connect(db_path) as con:
        ensure_evidence_registry_schema_for_connection(con)


def _normalize_evidence_record(record: EvidenceRecord) -> dict[str, Any]:
    data = asdict(record)
    data["model_type"] = record.model_type.lower().strip()
    data["evidence_level"] = _enum_value(record.evidence_level, EvidenceLevel, "evidence_level")
    data["readiness_status"] = _enum_value(record.readiness_status, ReadinessStatus, "readiness_status")
    data["evidence_id"] = record.evidence_id or make_evidence_id(record.run_id, data["model_type"], record.report_path)
    notes = record.notes or ""
    if not record.feature_scope_id:
        data["feature_scope_id"] = "missing"
        missing_note = "feature_scope_id missing; source metadata did not provide a value."
        notes = f"{notes}\n{missing_note}".strip() if notes else missing_note
    data["notes"] = notes or None
    data["artifact_manifest_json"] = _json_dumps(record.artifact_manifest_json)
    data["metrics_json"] = _json_dumps(record.metrics_json)
    data["created_at"] = record.created_at or _utc_now()
    data["updated_at"] = record.updated_at or _utc_now()
    return data


def _upsert(db_path: str, table: str, key: str, columns: list[str], data: dict[str, Any]) -> None:
    updates = ", ".join(f"{column} = EXCLUDED.{column}" for column in columns if column not in {key, "created_at"})
    with _connect(db_path) as con:
        con.execute(
            f"""
            INSERT INTO {table} ({", ".join(columns)})
            VALUES ({", ".join(["?"] * len(columns))})
            ON CONFLICT ({key}) DO UPDATE SET {updates};
            """,
            [data.get(column) for column in columns],
        )


def upsert_evidence_record(db_path: str, record: EvidenceRecord) -> str:
    ensure_evidence_registry_schema(db_path)
    data = _normalize_evidence_record(record)
    _upsert(db_path, "model_evidence_registry", "evidence_id", MODEL_EVIDENCE_COLUMNS, data)
    return str(data["evidence_id"])


def _normalize_validation_run(record: ValidationRunRecord) -> dict[str, Any]:
    data = asdict(record)
    data["validation_type"] = _validate_value(record.validation_type, VALIDATION_TYPES, "validation_type")
    data["status"] = _validate_value(record.status, VALIDATION_STATUSES, "status")
    data["validation_run_id"] = record.validation_run_id or _make_validation_run_id(record)
    data["python_version"] = record.python_version or sys.version.split()[0]
    data["duckdb_version"] = record.duckdb_version or duckdb.__version__
    data["platform"] = record.platform or platform.platform()
    data["metrics_json"] = _json_dumps(record.metrics_json)
    data["warnings_json"] = _json_dumps(record.warnings_json)
    data["created_at"] = record.created_at or _utc_now()
    return data


def upsert_validation_run(db_path: str, record: ValidationRunRecord) -> str:
    ensure_evidence_registry_schema(db_path)
    data = _normalize_validation_run(record)
    _upsert(db_path, "validation_runs", "validation_run_id", VALIDATION_RUN_COLUMNS, data)
    return str(data["validation_run_id"])


def list_evidence_for_run(db_path: str, run_id: str) -> pd.DataFrame:
    ensure_evidence_registry_schema(db_path)
    with _connect(db_path) as con:
        return con.execute(
            "SELECT * FROM model_evidence_registry WHERE run_id = ? ORDER BY updated_at DESC, evidence_id",
            [run_id],
        ).fetchdf()


def get_latest_evidence(db_path: str, model_type: str, run_id: str | None = None) -> dict[str, Any] | None:
    ensure_evidence_registry_schema(db_path)
    params: list[Any] = [model_type.lower().strip()]
    run_filter = ""
    if run_id is not None:
        run_filter = "AND run_id = ?"
        params.append(run_id)
    with _connect(db_path) as con:
        cursor = con.execute(
            f"""
            SELECT * FROM model_evidence_registry
            WHERE model_type = ? {run_filter}
            ORDER BY updated_at DESC, evidence_id LIMIT 1
            """,
            params,
        )
        row = cursor.fetchone()
        return None if row is None else dict(zip([item[0] for item in cursor.description], row, strict=True))


def seed_ui_readiness_policy(db_path: str) -> int:
    ensure_evidence_registry_schema(db_path)
    now = _utc_now()
    with _connect(db_path) as con:
        for seed in POLICY_SEEDS:
            row = dict(zip(UI_POLICY_COLUMNS[:10], seed, strict=True))
            row["created_at"] = now
            row["updated_at"] = now
            updates = ", ".join(
                f"{column} = EXCLUDED.{column}"
                for column in UI_POLICY_COLUMNS
                if column not in {"policy_id", "created_at"}
            )
            con.execute(
                f"""
                INSERT INTO ui_readiness_policy ({", ".join(UI_POLICY_COLUMNS)})
                VALUES ({", ".join(["?"] * len(UI_POLICY_COLUMNS))})
                ON CONFLICT (policy_id) DO UPDATE SET {updates};
                """,
                [row[column] for column in UI_POLICY_COLUMNS],
            )
        return int(
            con.execute(
                f"SELECT COUNT(*) FROM ui_readiness_policy WHERE policy_id IN ({', '.join(['?'] * len(POLICY_SEEDS))})",
                [seed[0] for seed in POLICY_SEEDS],
            ).fetchone()[0]
        )


def _table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> set[str]:
    exists = con.execute(
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main' AND table_name = ?",
        [table_name],
    ).fetchone()[0]
    if not exists:
        return set()
    return {row[1] for row in con.execute(f"PRAGMA table_info('{table_name}')").fetchall()}


def read_existing_run_metadata(db_path: str, run_id: str) -> tuple[dict[str, Any], list[str]]:
    ensure_evidence_registry_schema(db_path)
    metadata: dict[str, Any] = {}
    warnings: list[str] = []
    with _connect(db_path) as con:
        for table_name in KNOWN_RUN_TABLES:
            columns = _table_columns(con, table_name)
            if not columns:
                warnings.append(f"source table missing: {table_name}")
                continue
            if "run_id" not in columns:
                warnings.append(f"source table lacks run_id: {table_name}")
                continue
            desired = [
                column
                for column in ("universe_id", "feature_scope_id", "feature_scope_type", "universe_version", "feature_version")
                if column in columns
            ]
            if desired:
                row = con.execute(
                    f"SELECT {', '.join(desired)} FROM {table_name} WHERE run_id = ? LIMIT 1",
                    [run_id],
                ).fetchone()
                if row is not None:
                    metadata.update({column: value for column, value in zip(desired, row, strict=True) if value is not None})
        if not metadata:
            warnings.append(f"run metadata not found for run_id={run_id}")
    return metadata, warnings


def register_report_as_evidence(
    db_path: str,
    report_path: str,
    run_id: str,
    model_type: str,
    evidence_level: EvidenceLevel | str,
    readiness_status: ReadinessStatus | str,
) -> tuple[str, list[str]]:
    path = Path(report_path)
    if not path.exists():
        raise FileNotFoundError(f"report not found: {report_path}")
    metadata, warnings = read_existing_run_metadata(db_path, run_id)
    evidence_id = upsert_evidence_record(
        db_path,
        EvidenceRecord(
            run_id=run_id,
            model_type=model_type,
            evidence_level=evidence_level,
            readiness_status=readiness_status,
            universe_id=metadata.get("universe_id"),
            universe_version=metadata.get("universe_version"),
            feature_scope_id=metadata.get("feature_scope_id"),
            feature_scope_type=metadata.get("feature_scope_type"),
            feature_version=metadata.get("feature_version"),
            report_path=report_path,
            artifact_manifest_json={"report_path": report_path, "exists": True, "size_bytes": path.stat().st_size},
            notes=("Warnings: " + "; ".join(warnings)) if warnings else None,
        ),
    )
    return evidence_id, warnings


def build_registry_summary(db_path: str, local_db_used: bool | None = None) -> dict[str, Any]:
    ensure_evidence_registry_schema(db_path)
    with _connect(db_path) as con:
        tables = ("model_evidence_registry", "validation_runs", "ui_readiness_policy")
        counts = {table: int(con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in tables}
        columns = {table: [row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()] for table in tables}
    return {
        "generated_at": _utc_now().isoformat(timespec="seconds") + "Z",
        "db_path": db_path,
        "local_db_used": local_db_used,
        "external_data_fetch": False,
        "model_training_changed": False,
        "ui_display_logic_changed": False,
        "tables": counts,
        "columns": columns,
        "notes": [
            "Stage 00 WP-A registry schema and API only.",
            "No market or constituent data was fetched.",
            "No HMM/HSMM training algorithm or UI display logic was changed.",
        ],
    }


def write_registry_summary(summary: dict[str, Any], md_path: str, json_path: str) -> None:
    Path(md_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).parent.mkdir(parents=True, exist_ok=True)
    Path(json_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    table_lines = ["| table | rows | columns |", "|---|---:|---:|"]
    for table_name, count in summary["tables"].items():
        table_lines.append(f"| {table_name} | {count} | {len(summary['columns'][table_name])} |")
    lines = [
        "# Stage 00 WP-A Evidence Registry Summary",
        "",
        f"- generated_at: {summary['generated_at']}",
        f"- db_path: {summary['db_path']}",
        f"- local_db_used: {summary['local_db_used']}",
        f"- external_data_fetch: {str(summary['external_data_fetch']).lower()}",
        f"- model_training_changed: {str(summary['model_training_changed']).lower()}",
        f"- ui_display_logic_changed: {str(summary['ui_display_logic_changed']).lower()}",
        "",
        "## Registry Tables",
        "",
        *table_lines,
        "",
        "## Stage 00 Boundary",
        "",
        "- 本包没有改变 HMM/HSMM 模型训练算法。",
        "- 本包没有改变 UI 页面展示逻辑。",
        "- 本包没有抓取任何新行情或成分股数据。",
        "",
        "## Notes",
        "",
        *[f"- {note}" for note in summary["notes"]],
        "",
    ]
    Path(md_path).write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 00 evidence registry utilities")
    parser.add_argument("--db", required=True)
    parser.add_argument("--seed-policy", action="store_true")
    parser.add_argument("--print-summary", action="store_true")
    parser.add_argument("--register-report")
    parser.add_argument("--run-id")
    parser.add_argument("--model-type")
    parser.add_argument("--evidence-level", choices=[item.value for item in EvidenceLevel])
    parser.add_argument("--readiness-status", choices=[item.value for item in ReadinessStatus])
    parser.add_argument("--summary-md")
    parser.add_argument("--summary-json")
    parser.add_argument("--local-db-used", choices=["yes", "no"])
    args = parser.parse_args(argv)

    warnings: list[str] = []
    ensure_evidence_registry_schema(args.db)
    if args.seed_policy:
        warnings.append(f"seeded_or_updated_ui_readiness_policy_rows={seed_ui_readiness_policy(args.db)}")
    if args.register_report:
        missing = [
            name
            for name in ("run_id", "model_type", "evidence_level", "readiness_status")
            if getattr(args, name) is None
        ]
        if missing:
            raise SystemExit(f"--register-report requires: {', '.join('--' + item.replace('_', '-') for item in missing)}")
        evidence_id, report_warnings = register_report_as_evidence(
            args.db,
            args.register_report,
            args.run_id,
            args.model_type,
            args.evidence_level,
            args.readiness_status,
        )
        warnings.append(f"registered_evidence_id={evidence_id}")
        warnings.extend(report_warnings)

    local_db_used = None if args.local_db_used is None else args.local_db_used == "yes"
    summary = build_registry_summary(args.db, local_db_used=local_db_used)
    if args.summary_md or args.summary_json:
        if not args.summary_md or not args.summary_json:
            raise SystemExit("--summary-md and --summary-json must be provided together")
        write_registry_summary(summary, args.summary_md, args.summary_json)
    if args.print_summary:
        print("Evidence registry summary")
        print(f"  db_path: {summary['db_path']}")
        print(f"  external_data_fetch: {summary['external_data_fetch']}")
        for table_name, count in summary["tables"].items():
            print(f"  {table_name}: {count}")
        for warning in warnings:
            print(f"WARNING: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
