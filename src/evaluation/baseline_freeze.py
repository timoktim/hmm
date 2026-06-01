"""Stage 00 baseline freeze CLI.

This module freezes the current local baseline by collecting environment,
artifact, and optional read-only DuckDB inventory. It never fetches market data
and it never modifies HMM/HSMM training code or database contents.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from .baseline_collectors import (
        ArtifactStatus,
        collect_artifact_inventory,
        collect_database_snapshot,
        collect_environment,
        dataclass_list,
        utc_now_iso,
        write_csv,
        write_json,
        write_jsonl,
    )
except ImportError:  # pragma: no cover - supports direct script execution.
    from baseline_collectors import (  # type: ignore
        ArtifactStatus,
        collect_artifact_inventory,
        collect_database_snapshot,
        collect_environment,
        dataclass_list,
        utc_now_iso,
        write_csv,
        write_json,
        write_jsonl,
    )


HMM_BOUNDARY = {
    "positioning": "causal nowcast / state context / weak auxiliary signal",
    "not_accepted_as": "standalone trading decision engine",
    "default_evidence_level": "internal_diagnostic or research_only",
    "validated_signal": False,
}

HSMM_BOUNDARY = {
    "state_age": "displayable as internal diagnostic",
    "state_phase": "displayable as internal diagnostic",
    "exit_tendency": "low/medium/high ordinal tendency only; internal diagnostic",
    "numeric_p_exit": "hidden unless usable_probability/readiness passes",
    "next_state_tendency": "realized-profile tendency, not predicted probability",
    "ranking_or_trading_recommendation": False,
}

UI_READINESS_BOUNDARY = {
    "sample_in_states": "historical explanation only",
    "causal_walk_forward_required_for_strategy": True,
    "probability_display": "restricted by readiness and evidence level",
}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Stage 00 V0 baseline freeze snapshot.")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb", help="Local DuckDB path.")
    parser.add_argument(
        "--output",
        default="reports/baseline_freeze/stage00_v0_baseline_20260601",
        help="Output directory for baseline artifacts.",
    )
    parser.add_argument(
        "--run-tests",
        choices=["no", "unit", "not-slow", "all"],
        default="no",
        help="Optionally run validation tests after collecting inventory.",
    )
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        default=True,
        help="Default and only supported mode; no external data fetch is attempted.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Return non-zero when critical artifacts are missing or validation commands fail.",
    )
    parser.add_argument(
        "--register-evidence",
        action="store_true",
        help="Write evidence seed records when no WP-A registry is available.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    working_dir = Path.cwd()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    snapshot = generate_baseline_snapshot(
        db_path=Path(args.db),
        output_dir=output_dir,
        working_dir=working_dir,
        run_tests=args.run_tests,
        register_evidence=args.register_evidence,
    )

    critical_missing = bool(snapshot["missing_artifacts"])
    failed_commands = any(command["returncode"] not in (0, None) for command in snapshot["validation_commands"])
    if args.strict and (critical_missing or failed_commands):
        return 1
    return 0


def generate_baseline_snapshot(
    db_path: Path,
    output_dir: Path,
    working_dir: Path,
    run_tests: str = "no",
    register_evidence: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    environment = collect_environment(working_dir)
    database = collect_database_snapshot(db_path)
    artifacts = collect_artifact_inventory(working_dir)
    missing_artifacts = [artifact for artifact in artifacts if not artifact.exists]
    validation_commands = run_validation_commands(run_tests, working_dir)
    status = "pass" if database.db_available and not missing_artifacts else "partial"
    if database.db_open_error and database.db_found:
        status = "partial"

    snapshot: dict[str, Any] = {
        "index_id": "STAGE00-WP-B-v1",
        "work_package": "STAGE00_WP_B_baseline_freeze",
        "version": "v1",
        "created_at": utc_now_iso(),
        "external_fetch_attempted": False,
        "no_fetch_mode": True,
        "status": status,
        "summary_verdict": summary_verdict(database.db_available, bool(missing_artifacts)),
        "environment": environment,
        "database": asdict(database),
        "artifact_inventory": dataclass_list(artifacts),
        "missing_artifacts": [artifact.path for artifact in missing_artifacts],
        "boundaries": {
            "hmm": HMM_BOUNDARY,
            "hsmm_lifecycle": HSMM_BOUNDARY,
            "ui_readiness": UI_READINESS_BOUNDARY,
            "sample_in_vs_causal": {
                "sample_in": "descriptive historical explanation only",
                "causal_walk_forward": "required before strategy/backtest claims",
            },
        },
        "validation_commands": validation_commands,
        "local_db_usage": {
            "db_found": database.db_found,
            "db_path": str(db_path),
            "db_file_size": database.db_file_size,
            "duckdb_opened_read_only": database.duckdb_opened_read_only,
            "external_fetch_attempted": False,
        },
    }

    snapshot["evidence_registration"] = register_baseline_evidence(db_path, output_dir, snapshot) if register_evidence else {
        "registered": False,
        "reason": "--register-evidence not requested",
    }
    write_outputs(output_dir, snapshot, database.table_profiles, database.run_inventory, validation_commands)
    write_evidence_seed(output_dir, snapshot)
    return snapshot


def summary_verdict(db_available: bool, has_missing_artifacts: bool = False) -> str:
    if db_available and has_missing_artifacts:
        return "BaselineFreezePartialDueToMissingArtifacts"
    if db_available:
        return "BaselineFreezePassWithLocalDbInventory"
    return "BaselineFreezePartialDueToDbUnavailable"


def run_validation_commands(run_tests: str, working_dir: Path) -> list[dict[str, Any]]:
    commands: list[list[str]] = []
    if run_tests == "unit":
        if shutil.which("pytest"):
            commands.append([sys.executable, "-m", "pytest", "-q", "tests/test_baseline_freeze.py"])
        else:
            commands.append(
                [
                    sys.executable,
                    "-m",
                    "unittest",
                    "discover",
                    "-s",
                    "tests",
                    "-p",
                    "test_baseline_freeze.py",
                ]
            )
    elif run_tests == "not-slow":
        commands.append([sys.executable, "-m", "pytest", "-q", "-m", "not slow"])
    elif run_tests == "all":
        commands.append([sys.executable, "-m", "pytest", "-q"])

    results: list[dict[str, Any]] = []
    if not commands:
        return [{"command": None, "returncode": None, "result": "not_run", "reason": "--run-tests no"}]

    for command in commands:
        if command[2] == "pytest" and shutil.which("pytest") is None:
            results.append(
                {
                    "command": " ".join(command),
                    "returncode": None,
                    "result": "not_run",
                    "reason": "pytest is not installed in this environment",
                }
            )
            continue
        completed = subprocess.run(
            command,
            cwd=working_dir,
            capture_output=True,
            text=True,
            check=False,
        )
        results.append(
            {
                "command": " ".join(command),
                "returncode": completed.returncode,
                "result": "pass" if completed.returncode == 0 else "fail",
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            }
        )
    return results


def write_outputs(
    output_dir: Path,
    snapshot: dict[str, Any],
    table_profiles: list[Any],
    run_inventory: list[dict[str, Any]],
    validation_commands: list[dict[str, Any]],
) -> None:
    write_summary(output_dir / "summary.md", snapshot)
    write_json(output_dir / "baseline_snapshot.json", snapshot)
    write_csv(
        output_dir / "db_table_profile.csv",
        [asdict(profile) for profile in table_profiles],
        [
            "table_name",
            "exists",
            "row_count",
            "min_trade_date",
            "max_trade_date",
            "distinct_run_count",
            "distinct_sector_count",
            "feature_scope_id_sample",
            "universe_id_sample",
            "notes",
        ],
    )
    write_csv(
        output_dir / "run_inventory.csv",
        run_inventory,
        [
            "source_table",
            "run_id",
            "row_count",
            "min_trade_date",
            "max_trade_date",
            "feature_scope_id_sample",
            "universe_id_sample",
            "error",
        ],
    )
    write_json(output_dir / "validation_commands.json", {"commands": validation_commands})
    write_missing_artifacts(output_dir / "missing_artifacts.md", snapshot["artifact_inventory"])


def write_summary(path: Path, snapshot: dict[str, Any]) -> None:
    db = snapshot["database"]
    local_db = snapshot["local_db_usage"]
    missing = snapshot["missing_artifacts"]
    lines = [
        "# Stage 00 V0 Baseline Freeze Summary",
        "",
        f"- index_id: {snapshot['index_id']}",
        f"- work_package: {snapshot['work_package']}",
        f"- status: {snapshot['status']}",
        f"- verdict: {snapshot['summary_verdict']}",
        f"- created_at: {snapshot['created_at']}",
        "- external_fetch_attempted: no",
        "",
        "## Environment",
        "",
        f"- python_version: {snapshot['environment']['python_version']}",
        f"- duckdb_version: {snapshot['environment']['duckdb_version']}",
        f"- platform: {snapshot['environment']['platform']}",
        f"- working_directory: {snapshot['environment']['working_directory']}",
        f"- is_git_repo: {snapshot['environment']['is_git_repo']}",
        f"- git_sha: {snapshot['environment']['git_sha']}",
        "",
        "## Local DB Usage",
        "",
        f"- DB found: {'yes' if local_db['db_found'] else 'no'}",
        f"- DB path: {local_db['db_path']}",
        f"- DB file size: {local_db['db_file_size']}",
        f"- DuckDB opened read-only: {'yes' if local_db['duckdb_opened_read_only'] else 'no'}",
        "- External fetch attempted=no",
        f"- db_available: {db['db_available']}",
        f"- db_open_error: {db['db_open_error']}",
        f"- evidence_registration: {snapshot.get('evidence_registration')}",
        "",
        "## HMM / Signal Validation Boundary",
        "",
        "- Current positioning: causal nowcast / state context / weak auxiliary signal.",
        "- Not accepted as a standalone trading decision engine.",
        "- Default evidence_level: internal_diagnostic or research_only.",
        "- Current HMM outputs are not promoted to validated_signal or decision_support.",
        "- Sample-in states remain historical explanation only; causal walk-forward evidence is required for strategy claims.",
        "",
        "## HSMM Lifecycle Boundary",
        "",
        "- State age is displayable as an internal diagnostic.",
        "- State phase is displayable as an internal diagnostic.",
        "- Low/medium/high exit tendency is internal diagnostic ordinal tendency.",
        "- Numeric p_exit is hidden unless usable_probability/readiness passes.",
        "- Next-state tendency is a realized-profile tendency, not a predicted probability.",
        "- HSMM lifecycle is not used for ranking or trading recommendations.",
        "",
        "## UI Readiness Snapshot",
        "",
        "- Probability displays remain restricted by evidence/readiness level.",
        "- Causal and sample-in outputs must not be mixed for strategy evaluation.",
        "- No UI readiness logic was modified by this work package.",
        "",
        "## DB Table Inventory",
        "",
    ]
    if db["db_available"]:
        for profile in db["table_profiles"]:
            lines.append(
                "- {table_name}: rows={row_count}, date_range={min_trade_date}..{max_trade_date}, "
                "runs={distinct_run_count}, sectors={distinct_sector_count}".format(**profile)
            )
    else:
        lines.append("- DB inventory skipped because the local DB was unavailable.")

    lines.extend(
        [
            "",
            "## V0 Fact Checks",
            "",
            "Reference points are recorded in baseline_snapshot.json and are not hard-coded pass criteria.",
            f"- fact_check_status: {json.dumps(db['v0_fact_checks'], ensure_ascii=False)}",
            "",
            "## Missing Artifacts",
            "",
        ]
    )
    if missing:
        lines.extend(f"- {item}" for item in missing)
    else:
        lines.append("- none")

    lines.extend(
        [
            "",
            "## Validation Commands",
            "",
        ]
    )
    for command in snapshot["validation_commands"]:
        lines.append(f"- command: {command.get('command')}")
        lines.append(f"  result: {command.get('result')}")
        if command.get("reason"):
            lines.append(f"  reason: {command.get('reason')}")

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_missing_artifacts(path: Path, artifact_inventory: list[dict[str, Any] | ArtifactStatus]) -> None:
    lines = [
        "# Missing Baseline Artifacts",
        "",
        "The following required Stage 00 WP-B artifacts were checked without fetching new data.",
        "",
    ]
    missing_count = 0
    for artifact in artifact_inventory:
        record = asdict(artifact) if isinstance(artifact, ArtifactStatus) else artifact
        if record["exists"]:
            continue
        missing_count += 1
        lines.append(f"- {record['path']} ({record['kind']})")
    if missing_count == 0:
        lines.append("- none")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_evidence_seed(output_dir: Path, snapshot: dict[str, Any]) -> None:
    record = {
        "record_type": "baseline_freeze",
        "index_id": snapshot["index_id"],
        "work_package": snapshot["work_package"],
        "created_at": snapshot["created_at"],
        "status": snapshot["status"],
        "verdict": snapshot["summary_verdict"],
        "output_dir": str(output_dir),
        "baseline_snapshot": str(output_dir / "baseline_snapshot.json"),
        "summary": str(output_dir / "summary.md"),
        "external_fetch_attempted": False,
        "db_available": snapshot["database"]["db_available"],
        "evidence_level": "internal_diagnostic",
    }
    write_jsonl(output_dir / "evidence_seed.jsonl", [record])


def register_baseline_evidence(db_path: Path, output_dir: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    if not snapshot["database"]["db_found"]:
        return {"registered": False, "reason": "db_missing"}
    try:
        import duckdb  # type: ignore
    except Exception as exc:
        return {"registered": False, "reason": f"duckdb_unavailable: {exc}"}

    evidence_id = "evidence_stage00_wp_b_baseline_freeze"
    validation_run_id = "validation_stage00_wp_b_baseline_freeze"
    now = snapshot["created_at"]
    status = "pass" if snapshot["status"] == "pass" else "unknown"
    warnings = {
        "missing_artifacts": snapshot["missing_artifacts"],
        "summary_verdict": snapshot["summary_verdict"],
    }
    metrics = {
        "db_available": snapshot["database"]["db_available"],
        "table_count": len(snapshot["database"]["table_profiles"]),
        "external_fetch_attempted": False,
    }

    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            if not registry_tables_exist(conn):
                return {"registered": False, "reason": "wp_a_registry_tables_missing"}
    except Exception as exc:
        return {"registered": False, "reason": f"registry_check_failed: {exc}"}

    try:
        with duckdb.connect(str(db_path)) as conn:
            conn.execute(
                """
                INSERT INTO model_evidence_registry (
                  evidence_id, run_id, model_type, model_family, evidence_level,
                  readiness_status, verdict_code, verdict_label, feature_scope_id,
                  report_path, artifact_manifest_json, metrics_json, notes,
                  created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (evidence_id) DO UPDATE SET
                  verdict_code = EXCLUDED.verdict_code,
                  verdict_label = EXCLUDED.verdict_label,
                  report_path = EXCLUDED.report_path,
                  artifact_manifest_json = EXCLUDED.artifact_manifest_json,
                  metrics_json = EXCLUDED.metrics_json,
                  notes = EXCLUDED.notes,
                  updated_at = EXCLUDED.updated_at
                """,
                [
                    evidence_id,
                    "stage00_v0_baseline_20260601",
                    "baseline",
                    "hmm_hsmm",
                    "internal_diagnostic",
                    "partial" if snapshot["status"] == "partial" else "validated",
                    snapshot["summary_verdict"],
                    "Stage 00 V0 baseline freeze",
                    "baseline_freeze",
                    str(output_dir / "summary.md"),
                    json.dumps(snapshot["artifact_inventory"], ensure_ascii=False, sort_keys=True),
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    "Stage 00 WP-B baseline freeze; no external data fetch; no training algorithm changes.",
                    now,
                    now,
                ],
            )
            conn.execute(
                """
                INSERT INTO validation_runs (
                  validation_run_id, run_id, evidence_id, validation_type, command,
                  status, verdict_code, started_at, finished_at, python_version,
                  duckdb_version, platform, git_sha, db_path, report_dir,
                  metrics_json, warnings_json, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (validation_run_id) DO UPDATE SET
                  status = EXCLUDED.status,
                  verdict_code = EXCLUDED.verdict_code,
                  finished_at = EXCLUDED.finished_at,
                  python_version = EXCLUDED.python_version,
                  duckdb_version = EXCLUDED.duckdb_version,
                  platform = EXCLUDED.platform,
                  git_sha = EXCLUDED.git_sha,
                  db_path = EXCLUDED.db_path,
                  report_dir = EXCLUDED.report_dir,
                  metrics_json = EXCLUDED.metrics_json,
                  warnings_json = EXCLUDED.warnings_json
                """,
                [
                    validation_run_id,
                    "stage00_v0_baseline_20260601",
                    evidence_id,
                    "baseline_freeze",
                    "python -m src.evaluation.baseline_freeze --db data/db/a_share_hmm.duckdb --output reports/baseline_freeze/stage00_v0_baseline_20260601 --run-tests no --no-fetch --register-evidence",
                    status,
                    snapshot["summary_verdict"],
                    now,
                    now,
                    snapshot["environment"]["python_version"],
                    snapshot["environment"]["duckdb_version"],
                    snapshot["environment"]["platform"],
                    snapshot["environment"]["git_sha"],
                    str(db_path),
                    str(output_dir),
                    json.dumps(metrics, ensure_ascii=False, sort_keys=True),
                    json.dumps(warnings, ensure_ascii=False, sort_keys=True),
                    now,
                ],
            )
    except Exception as exc:
        return {"registered": False, "reason": f"registry_write_failed: {exc}"}

    return {
        "registered": True,
        "evidence_id": evidence_id,
        "validation_run_id": validation_run_id,
    }


def registry_tables_exist(conn: Any) -> bool:
    required = {"model_evidence_registry", "validation_runs"}
    rows = conn.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name IN ('model_evidence_registry', 'validation_runs')
        """
    ).fetchall()
    return {row[0] for row in rows} == required


if __name__ == "__main__":
    raise SystemExit(main())
