from __future__ import annotations

import json
import subprocess
import sys

import pytest

from src.evaluation.evidence_registry import (
    EvidenceRecord,
    ValidationRunRecord,
    read_existing_run_metadata,
    register_report_as_evidence,
    upsert_evidence_record,
    upsert_validation_run,
)
from src.evaluation.run_manifest import get_git_sha


def test_validation_run_upsert_inserts_and_updates(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")
    evidence_id = upsert_evidence_record(
        db_path,
        EvidenceRecord(
            run_id="run-2",
            model_type="hmm",
            evidence_level="internal_diagnostic",
            readiness_status="research_only",
            feature_scope_id="features-v1",
            report_path="reports/a.md",
        ),
    )

    validation_id = upsert_validation_run(
        db_path,
        ValidationRunRecord(
            validation_type="unit_tests",
            status="pass",
            run_id="run-2",
            evidence_id=evidence_id,
            command="pytest -q tests/test_evidence_registry.py",
            metrics_json={"tests": 6},
        ),
    )
    same_id = upsert_validation_run(
        db_path,
        ValidationRunRecord(
            validation_run_id=validation_id,
            validation_type="unit_tests",
            status="fail",
            run_id="run-2",
            evidence_id=evidence_id,
            command="pytest -q tests/test_evidence_registry.py",
            warnings_json=["rerun failed in test fixture"],
        ),
    )

    assert same_id == validation_id
    import duckdb

    with duckdb.connect(db_path) as con:
        row = con.execute(
            "SELECT status, warnings_json FROM validation_runs WHERE validation_run_id = ?",
            [validation_id],
        ).fetchone()
    assert row[0] == "fail"
    assert json.loads(row[1]) == ["rerun failed in test fixture"]


def test_validation_run_rejects_unknown_status_and_type(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")

    with pytest.raises(ValueError):
        upsert_validation_run(db_path, ValidationRunRecord(validation_type="unit_tests", status="green"))
    with pytest.raises(ValueError):
        upsert_validation_run(db_path, ValidationRunRecord(validation_type="portfolio_optimization", status="pass"))


def test_read_existing_run_metadata_warns_when_source_tables_are_missing(tmp_path):
    metadata, warnings = read_existing_run_metadata(str(tmp_path / "registry.duckdb"), "run-without-source")

    assert metadata == {}
    assert "run metadata not found for run_id=run-without-source" in warnings
    assert any("source table missing: model_runs" == warning for warning in warnings)


def test_register_report_as_evidence_inherits_existing_metadata(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")
    report = tmp_path / "summary.md"
    report.write_text("# summary\n", encoding="utf-8")

    import duckdb

    with duckdb.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE model_runs (
                run_id TEXT,
                universe_id TEXT,
                feature_scope_id TEXT,
                feature_scope_type TEXT
            )
            """
        )
        con.execute("INSERT INTO model_runs VALUES ('run-3', 'a_share', 'scope-1', 'sector')")

    evidence_id, warnings = register_report_as_evidence(
        db_path,
        str(report),
        run_id="run-3",
        model_type="hmm",
        evidence_level="internal_diagnostic",
        readiness_status="research_only",
    )

    assert evidence_id.startswith("evidence_")
    assert warnings
    with duckdb.connect(db_path) as con:
        row = con.execute(
            """
            SELECT universe_id, feature_scope_id, feature_scope_type, artifact_manifest_json
            FROM model_evidence_registry
            WHERE evidence_id = ?
            """,
            [evidence_id],
        ).fetchone()
    assert row[:3] == ("a_share", "scope-1", "sector")
    assert json.loads(row[3])["exists"] is True


def test_cli_reports_clear_failure_for_missing_register_report(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.evidence_registry",
            "--db",
            str(tmp_path / "registry.duckdb"),
            "--register-report",
            str(tmp_path / "missing.md"),
            "--run-id",
            "run-missing",
            "--model-type",
            "hmm",
            "--evidence-level",
            "internal_diagnostic",
            "--readiness-status",
            "research_only",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "report not found" in result.stderr


def test_git_sha_unknown_when_directory_is_not_a_git_checkout(tmp_path):
    assert get_git_sha(tmp_path) == "unknown"
