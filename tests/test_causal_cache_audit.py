from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from src.evaluation.causal_cache_audit import run_causal_cache_audit


REPO_ROOT = Path(__file__).resolve().parents[1]


def _create_base_tables(con: duckdb.DuckDBPyConnection, *, run_id: str = "run-1") -> None:
    con.execute(
        """
        CREATE TABLE model_runs (
          run_id TEXT,
          model_type TEXT,
          created_at TIMESTAMP,
          train_end DATE
        )
        """
    )
    con.execute("INSERT INTO model_runs VALUES (?, 'GaussianHMM', '2026-01-04', '2026-01-04')", [run_id])
    con.execute(
        """
        CREATE TABLE sector_state_daily (
          run_id TEXT,
          sector_id TEXT,
          trade_date DATE,
          state_id INTEGER,
          state_label TEXT,
          state_source TEXT
        )
        """
    )
    con.execute(
        """
        INSERT INTO sector_state_daily VALUES
          (?, 'S1', '2026-01-02', 0, 'A', 'in_sample_display'),
          (?, 'S2', '2026-01-02', 1, 'B', 'in_sample_display')
        """,
        [run_id, run_id],
    )


def _create_cache_tables(con: duckdb.DuckDBPyConnection, *, with_run_link: bool = True) -> None:
    run_link = "run_id TEXT," if with_run_link else ""
    con.execute(
        f"""
        CREATE TABLE walk_forward_cache_runs (
          cache_key TEXT,
          {run_link}
          row_count INTEGER,
          feature_scope_id TEXT,
          created_at TIMESTAMP
        )
        """
    )
    if with_run_link:
        con.execute(
            """
            INSERT INTO walk_forward_cache_runs
            VALUES ('cache-1', 'run-1', 2, 'scope-1', '2026-01-04')
            """
        )
    else:
        con.execute(
            """
            INSERT INTO walk_forward_cache_runs
            VALUES ('cache-1', 2, 'scope-1', '2026-01-04')
            """
        )
    con.execute(
        """
        CREATE TABLE walk_forward_state_cache (
          cache_key TEXT,
          sector_id TEXT,
          trade_date DATE,
          state_id INTEGER,
          state_label TEXT,
          train_end DATE,
          max_observation_date_used DATE,
          state_source TEXT
        )
        """
    )


def _insert_valid_cache_rows(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        INSERT INTO walk_forward_state_cache VALUES
          ('cache-1', 'S1', '2026-01-02', 0, 'A', '2026-01-02', '2026-01-02', 'causal_backtest'),
          ('cache-1', 'S2', '2026-01-02', 1, 'B', '2026-01-02', '2026-01-02', 'causal_backtest')
        """
    )


def test_missing_db_returns_partial_missing_db_without_fake_pass(tmp_path):
    result = run_causal_cache_audit(
        db_path=tmp_path / "missing.duckdb",
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.status == "partial"
    assert result.report_status == "partial_missing_db"
    assert result.causal_cache_available is False
    assert result.local_db_used is False
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["report_status"] == "partial_missing_db"


def test_missing_walk_forward_tables_returns_cache_unavailable(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)

    result = run_causal_cache_audit(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.status == "partial"
    assert result.report_status == "partial_missing_causal_cache"
    assert result.causal_cache_available is False
    assert result.readiness_status == "research_only"
    assert any("walk_forward_cache_runs table missing" in warning for warning in result.warnings)


def test_valid_toy_causal_cache_passes_with_partial_readiness(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)
        _create_cache_tables(con)
        _insert_valid_cache_rows(con)

    result = run_causal_cache_audit(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.status == "pass"
    assert result.causal_cache_available is True
    assert result.causal_cache_id == "cache-1"
    assert result.cache_run_id == "run-1"
    assert result.state_count == 2
    assert result.coverage_ratio == 1.0
    assert result.readiness_status == "partial"
    assert result.readiness_reason == "causal_cache_contract_passed"
    assert result.registry_seed_payload is not None


def test_duplicate_sector_date_keys_are_counted(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)
        _create_cache_tables(con)
        con.execute(
            """
            INSERT INTO walk_forward_state_cache VALUES
              ('cache-1', 'S1', '2026-01-02', 0, 'A', '2026-01-02', '2026-01-02', 'causal_backtest'),
              ('cache-1', 'S1', '2026-01-02', 0, 'A', '2026-01-02', '2026-01-02', 'causal_backtest')
            """
        )

    result = run_causal_cache_audit(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.duplicate_key_count == 1
    assert result.status == "fail"
    assert result.readiness_status == "blocked"


def test_train_end_after_trade_date_is_leakage_violation(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)
        _create_cache_tables(con)
        con.execute(
            """
            INSERT INTO walk_forward_state_cache VALUES
              ('cache-1', 'S1', '2026-01-02', 0, 'A', '2026-01-03', '2026-01-02', 'causal_backtest')
            """
        )

    result = run_causal_cache_audit(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.train_end_violation_count == 1
    assert result.leakage_violation_count == 1
    assert result.status == "fail"
    assert result.readiness_reason == "causal_cache_contract_violation"


def test_missing_metadata_does_not_pass_silently(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)
        _create_cache_tables(con)
        con.execute(
            """
            INSERT INTO walk_forward_state_cache VALUES
              ('cache-1', 'S1', '2026-01-02', 0, 'A', NULL, '2026-01-02', 'causal_backtest')
            """
        )

    result = run_causal_cache_audit(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        no_fetch=True,
    )

    assert result.missing_metadata_count == 1
    assert result.status == "partial"
    assert result.readiness_status == "research_only"
    assert result.readiness_reason == "unknown_due_to_missing_metadata"


def test_cli_writes_valid_markdown_and_json(tmp_path):
    db_path = tmp_path / "audit.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_base_tables(con)
        _create_cache_tables(con)
        _insert_valid_cache_rows(con)

    report = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.causal_cache_audit",
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
    assert "# Stage 02 WP-A Causal Cache Contract Audit" in report.read_text(encoding="utf-8")
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["index_id"] == "STAGE02-WP-A-v1"
    assert payload["status"] == "pass"
    assert payload["causal_cache_available"] is True


def test_no_fetch_false_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not support fetching external data"):
        run_causal_cache_audit(
            db_path=tmp_path / "missing.duckdb",
            run_id="latest",
            output_path=tmp_path / "report.md",
            summary_json_path=tmp_path / "report.json",
            no_fetch=False,
        )
