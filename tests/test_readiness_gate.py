from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from src.evaluation.readiness_gate import (
    ReadinessGateDecision,
    generate_readiness_gate_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _create_gate_db(path: Path, *, ambiguous_rows: int = 7, stable_rows: int = 3) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute("CREATE TABLE model_runs (run_id TEXT, model_type TEXT, created_at TIMESTAMP)")
        con.execute("INSERT INTO model_runs VALUES ('run-1', 'hmm', now())")
        con.execute(
            """
            CREATE TABLE hmm_confidence_run_summary (
              run_id TEXT,
              row_count INTEGER,
              sector_count INTEGER,
              high_share DOUBLE,
              medium_share DOUBLE,
              low_share DOUBLE,
              unclear_share DOUBLE,
              missing_share DOUBLE,
              readiness_status TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO hmm_confidence_run_summary
            VALUES ('run-1', 100, 10, 0.80, 0.10, 0.05, 0.05, 0.0, 'internal_only')
            """
        )
        con.execute(
            """
            CREATE TABLE hmm_label_alignment_audit (
              audit_id TEXT,
              base_run_id TEXT,
              compare_run_id TEXT,
              ambiguous_match BOOLEAN,
              label_preserved BOOLEAN,
              label_drift_severity TEXT
            )
            """
        )
        for index in range(ambiguous_rows):
            con.execute(
                "INSERT INTO hmm_label_alignment_audit VALUES (?, 'run-1', 'run-old', true, true, 'medium')",
                [f"ambiguous-{index}"],
            )
        for index in range(stable_rows):
            con.execute(
                "INSERT INTO hmm_label_alignment_audit VALUES (?, 'run-1', 'run-old', false, true, 'none')",
                [f"stable-{index}"],
            )
        con.execute(
            """
            CREATE TABLE hmm_churn_dwell_run_summary (
              run_id TEXT,
              row_count INTEGER,
              transition_rate_1d DOUBLE,
              mean_dwell_days DOUBLE,
              median_dwell_days DOUBLE,
              single_day_episode_share DOUBLE,
              episode_count INTEGER,
              churn_bucket TEXT,
              dwell_readiness_status TEXT,
              display_action TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO hmm_churn_dwell_run_summary
            VALUES ('run-1', 100, 0.07, 14.0, 9.0, 0.10, 20, 'low', 'internal_only', 'normal')
            """
        )


def _causal_json(path: Path, **overrides) -> Path:
    payload = {
        "resolved_run_id": "run-1",
        "status": "partial",
        "report_status": "cache_not_linked_to_resolved_run_id",
        "causal_cache_available": True,
        "causal_cache_id": "cache-1",
        "cache_run_id": None,
        "coverage_ratio": 0.10,
        "expected_state_rows": 100,
        "unique_cache_state_rows": 10,
        "missing_metadata_count": 1,
        "leakage_violation_count": 0,
        "duplicate_key_count": 0,
        "exec_date_violation_count": 0,
        "readiness_status": "research_only",
        "warnings": ["walk_forward_cache_runs lacks run_id linkage metadata"],
    }
    payload.update(overrides)
    return _write_json(path, payload)


def _ci_json(path: Path, **overrides) -> Path:
    payload = {
        "index_id": "STAGE02-WP-B-v1",
        "status": "pass",
        "ci_workflow": ".github/workflows/ci.yml",
        "private_db_required": "no",
        "local_db_usage": "no",
        "duckdb_committed": "no",
    }
    payload.update(overrides)
    return _write_json(path, payload)


def test_gate_aggregates_current_risks_conservatively(tmp_path):
    db_path = tmp_path / "gate.duckdb"
    _create_gate_db(db_path)
    causal = _causal_json(tmp_path / "causal.json")
    ci = _ci_json(tmp_path / "ci.json")

    summary = generate_readiness_gate_report(
        db_path=db_path,
        run_id="latest",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        causal_cache_json=causal,
        ci_validation_json=ci,
        confidence_json=tmp_path / "missing_confidence_report.json",
        alignment_json=tmp_path / "missing_alignment_report.json",
        churn_dwell_json=tmp_path / "missing_churn_report.json",
        no_fetch=True,
    )

    gate = summary["readiness_gate"]
    assert summary["status"] == "pass"
    assert gate["run_id"] == "run-1"
    assert gate["readiness_status"] == "research_only"
    assert gate["display_action"] == "research_only"
    assert "decision_ready" != gate["readiness_status"]
    assert "label_alignment_ambiguity_high" in gate["reasons"]
    assert "causal_cache_not_linked_to_resolved_run_id" in gate["reasons"]
    assert "causal_cache_coverage_partial" in gate["reasons"]
    assert "ci_validation_no_private_db_not_db_backed" in gate["reasons"]
    assert summary["external_data_fetch"] is False
    assert summary["training_algorithm_modified"] is False


def test_missing_inputs_degrade_without_fetching(tmp_path):
    summary = generate_readiness_gate_report(
        db_path=tmp_path / "missing.duckdb",
        run_id="latest",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        confidence_json=tmp_path / "missing_confidence.json",
        alignment_json=tmp_path / "missing_alignment.json",
        churn_dwell_json=tmp_path / "missing_churn.json",
        causal_cache_json=tmp_path / "missing_causal.json",
        ci_validation_json=tmp_path / "missing_ci.json",
        no_fetch=True,
    )

    gate = summary["readiness_gate"]
    assert summary["status"] == "partial"
    assert gate["readiness_status"] == "blocked"
    assert gate["display_action"] == "blocked"
    assert "local_db_missing" in gate["reasons"]
    assert "run_id_unresolved" in gate["reasons"]
    assert summary["external_data_fetch"] is False


def test_unavailable_causal_cache_blocks_stronger_readiness(tmp_path):
    db_path = tmp_path / "gate.duckdb"
    _create_gate_db(db_path, ambiguous_rows=0, stable_rows=10)
    causal = _causal_json(
        tmp_path / "causal.json",
        status="partial",
        report_status="causal_cache_unavailable",
        causal_cache_available=False,
        cache_run_id=None,
        coverage_ratio=None,
    )
    ci = _ci_json(tmp_path / "ci.json")

    summary = generate_readiness_gate_report(
        db_path=db_path,
        run_id="latest",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        causal_cache_json=causal,
        ci_validation_json=ci,
        confidence_json=tmp_path / "missing_confidence_report.json",
        alignment_json=tmp_path / "missing_alignment_report.json",
        churn_dwell_json=tmp_path / "missing_churn_report.json",
        no_fetch=True,
    )

    gate = summary["readiness_gate"]
    assert gate["readiness_status"] == "research_only"
    assert gate["causal_cache_status"] == "unavailable"
    assert "causal_cache_unavailable" in gate["reasons"]


def test_invalid_readiness_values_are_rejected():
    with pytest.raises(ValueError, match="decision_ready"):
        ReadinessGateDecision(
            run_id="run-1",
            status="pass",
            evidence_level="internal_diagnostic",
            readiness_status="decision_ready",
            display_action="normal",
            state_confidence_status="available",
            label_identity_status="available",
            churn_dwell_status="available",
            causal_cache_status="available",
            ci_validation_status="available",
        )

    with pytest.raises(ValueError, match="display_action"):
        ReadinessGateDecision(
            run_id="run-1",
            status="pass",
            evidence_level="internal_diagnostic",
            readiness_status="partial",
            display_action="decision_ready",
            state_confidence_status="available",
            label_identity_status="available",
            churn_dwell_status="available",
            causal_cache_status="available",
            ci_validation_status="available",
        )


def test_cli_writes_markdown_and_json_without_external_fetch(tmp_path):
    db_path = tmp_path / "cli.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE model_runs (run_id TEXT, model_type TEXT, created_at TIMESTAMP)")
        con.execute("INSERT INTO model_runs VALUES ('bea7ff20106a', 'hmm', now())")

    report = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.readiness_gate",
            "--db",
            str(db_path),
            "--run-id",
            "latest",
            "--output",
            str(report),
            "--summary-json",
            str(summary_json),
            "--no-fetch",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    loaded = json.loads(summary_json.read_text(encoding="utf-8"))
    assert report.exists()
    assert loaded["index_id"] == "STAGE02-WP-C-v1"
    assert loaded["run_id"] == "bea7ff20106a"
    assert loaded["external_data_fetch"] is False
    assert loaded["readiness_gate"]["readiness_status"] != "decision_ready"
