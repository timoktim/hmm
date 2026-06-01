from __future__ import annotations

import json
import subprocess
import sys

import duckdb
import pytest

from src.evaluation.hmm_confidence import (
    compute_posterior_metrics,
    detect_posterior_columns,
    run_hmm_confidence_report,
)


def test_confidence_bucket_assignment_covers_default_rules():
    assert compute_posterior_metrics([0.8, 0.15, 0.05]).confidence_bucket == "high"
    assert compute_posterior_metrics([0.65, 0.25, 0.10]).confidence_bucket == "medium"
    assert compute_posterior_metrics([0.54, 0.36, 0.10]).confidence_bucket == "low"

    unclear = compute_posterior_metrics([0.37, 0.35, 0.28])
    assert unclear.confidence_bucket == "unclear"
    assert unclear.confidence_reason == "near_tie"

    missing = compute_posterior_metrics([None, 0.5, 0.5])
    assert missing.confidence_bucket == "missing"
    assert missing.state_confidence_readiness == "blocked"

    invalid_sum = compute_posterior_metrics([0.7, 0.7, 0.1])
    assert invalid_sum.confidence_bucket == "missing"
    assert invalid_sum.confidence_reason == "posterior_sum_not_one"


def test_entropy_normalization_is_finite_and_bounded():
    metrics = compute_posterior_metrics([0.6, 0.3, 0.1])

    assert metrics.posterior_entropy is not None
    assert metrics.posterior_entropy_norm is not None
    assert metrics.posterior_entropy >= 0
    assert 0 <= metrics.posterior_entropy_norm <= 1


def test_detect_posterior_columns_prefers_hmm_state_probabilities():
    columns = [
        "run_id",
        "prob_trend_up",
        "prob_neutral",
        "prob_risk_off",
        "next_state_probability",
        "p_exit_1d",
        "state_source",
    ]

    assert detect_posterior_columns(columns) == ["prob_trend_up", "prob_neutral", "prob_risk_off"]


def test_cli_generates_confidence_tables_and_reports(tmp_path):
    db_path = tmp_path / "confidence.duckdb"
    output_path = tmp_path / "confidence.md"
    summary_json = tmp_path / "confidence.json"

    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE model_runs (
              run_id TEXT,
              model_type TEXT,
              created_at TIMESTAMP,
              universe_id TEXT,
              feature_scope_id TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO model_runs VALUES
              ('older', 'GaussianHMM', TIMESTAMP '2024-01-01 00:00:00', 'a_share', 'scope-old'),
              ('run_conf', 'GaussianHMM', TIMESTAMP '2024-01-02 00:00:00', 'a_share', 'scope-1')
            """
        )
        con.execute(
            """
            CREATE TABLE sector_state_daily (
              run_id TEXT,
              sector_id TEXT,
              sector_name TEXT,
              trade_date DATE,
              state_id INTEGER,
              state_label TEXT,
              prob_trend_up DOUBLE,
              prob_neutral DOUBLE,
              prob_risk_off DOUBLE,
              feature_scope_id TEXT,
              universe_id TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO sector_state_daily VALUES
              ('run_conf', 'S1', 'Alpha', DATE '2024-01-02', 0, 'TrendUp', 0.80, 0.15, 0.05, 'scope-1', 'a_share'),
              ('run_conf', 'S2', 'Beta', DATE '2024-01-02', 1, 'Neutral', 0.65, 0.25, 0.10, 'scope-1', 'a_share'),
              ('run_conf', 'S3', 'Gamma', DATE '2024-01-02', 2, 'RiskOff', 0.37, 0.35, 0.28, 'scope-1', 'a_share')
            """
        )

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.hmm_confidence",
            "--db",
            str(db_path),
            "--run-id",
            "latest",
            "--output",
            str(output_path),
            "--summary-json",
            str(summary_json),
            "--no-fetch",
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "pass"
    assert payload["run_id"] == "run_conf"
    assert payload["posterior_columns_found"] is True
    assert payload["confidence_rows_generated"] == 3
    assert payload["external_data_fetch"] is False
    assert output_path.exists()

    with duckdb.connect(str(db_path)) as con:
        assert con.execute("SELECT COUNT(*) FROM hmm_confidence_daily").fetchone()[0] == 3
        summary = con.execute(
            "SELECT high_count, medium_count, unclear_count FROM hmm_confidence_run_summary WHERE run_id = 'run_conf'"
        ).fetchone()
    assert summary == (1, 1, 1)


def test_missing_db_writes_partial_report_without_creating_database(tmp_path):
    db_path = tmp_path / "missing.duckdb"
    output_path = tmp_path / "missing.md"
    summary_json = tmp_path / "missing.json"

    result = run_hmm_confidence_report(
        db_path=db_path,
        run_id="latest",
        output_path=output_path,
        summary_json_path=summary_json,
        no_fetch=True,
    )

    assert result.status == "partial"
    assert result.report_status == "partial_missing_db"
    assert result.local_db_used is False
    assert not db_path.exists()
    assert "database file not found" in output_path.read_text(encoding="utf-8")


def test_missing_posterior_columns_are_partial_not_crashing(tmp_path):
    db_path = tmp_path / "missing_columns.duckdb"
    output_path = tmp_path / "missing_columns.md"
    summary_json = tmp_path / "missing_columns.json"
    with duckdb.connect(str(db_path)) as con:
        con.execute("CREATE TABLE model_runs(run_id TEXT, model_type TEXT, created_at TIMESTAMP)")
        con.execute("INSERT INTO model_runs VALUES ('run_no_prob', 'GaussianHMM', TIMESTAMP '2024-01-01 00:00:00')")
        con.execute(
            """
            CREATE TABLE sector_state_daily (
              run_id TEXT,
              sector_id TEXT,
              trade_date DATE,
              state_id INTEGER,
              state_label TEXT
            )
            """
        )
        con.execute("INSERT INTO sector_state_daily VALUES ('run_no_prob', 'S1', DATE '2024-01-02', 0, 'TrendUp')")

    result = run_hmm_confidence_report(
        db_path=db_path,
        run_id="latest",
        output_path=output_path,
        summary_json_path=summary_json,
        no_fetch=True,
    )

    assert result.status == "partial"
    assert result.report_status == "partial_missing_posterior_columns"
    assert result.posterior_columns_found is False
    assert json.loads(summary_json.read_text(encoding="utf-8"))["report_status"] == "partial_missing_posterior_columns"


def test_no_fetch_is_enforced(tmp_path):
    with pytest.raises(ValueError, match="does not support fetching"):
        run_hmm_confidence_report(
            db_path=tmp_path / "missing.duckdb",
            run_id="latest",
            output_path=tmp_path / "out.md",
            summary_json_path=tmp_path / "out.json",
            no_fetch=False,
        )
