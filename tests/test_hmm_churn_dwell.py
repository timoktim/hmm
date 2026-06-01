from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pandas as pd

from src.evaluation.hmm_churn_dwell import (
    classify_churn_bucket,
    compute_churn_dwell,
    generate_hmm_churn_dwell_report,
    inspect_alignment_integration,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _states(labels: list[str], *, sector_id: str = "S1", run_id: str = "run-1") -> pd.DataFrame:
    return pd.DataFrame(
        {
            "run_id": [run_id] * len(labels),
            "sector_id": [sector_id] * len(labels),
            "trade_date": pd.date_range("2026-01-01", periods=len(labels), freq="D"),
            "state_key": labels,
            "state_label": labels,
            "feature_scope_id": ["scope-1"] * len(labels),
            "universe_id": ["universe-1"] * len(labels),
            "source_table": ["sector_state_daily"] * len(labels),
            "state_source": ["in_sample_display"] * len(labels),
        }
    )


def test_episode_dwell_computation_from_synthetic_state_sequence():
    episodes, summary = compute_churn_dwell(_states(["A", "A", "B", "B", "B", "A"]), run_id="run-1")

    assert episodes["dwell_days"].tolist() == [2, 3, 1]
    assert episodes["is_single_day_episode"].tolist() == [False, False, True]
    assert summary["transition_count"] == 2
    assert summary["transition_rate_1d"] == 0.4
    assert summary["mean_dwell_days"] == 2.0
    assert summary["median_dwell_days"] == 2.0
    assert summary["single_day_episode_share"] == 0.333333
    assert summary["churn_bucket"] == "excessive"


def test_transition_rate_and_single_day_episode_share_across_sectors():
    rows = pd.concat(
        [
            _states(["A", "B", "A"], sector_id="S1"),
            _states(["A", "A", "A"], sector_id="S2"),
        ],
        ignore_index=True,
    )

    episodes, summary = compute_churn_dwell(rows, run_id="run-1")

    assert len(episodes) == 4
    assert summary["transition_count"] == 2
    assert summary["transition_rate_1d"] == 0.5
    assert summary["single_day_episode_share"] == 0.75
    assert summary["churn_bucket"] == "excessive"


def test_churn_bucket_thresholds_are_conservative():
    assert classify_churn_bucket(0.05, 0.10, sequence_length=20) == "low"
    assert classify_churn_bucket(0.15, 0.20, sequence_length=20) == "medium"
    assert classify_churn_bucket(0.30, 0.40, sequence_length=20) == "high"
    assert classify_churn_bucket(0.36, 0.10, sequence_length=20) == "excessive"
    assert classify_churn_bucket(0.10, 0.51, sequence_length=20) == "excessive"
    assert classify_churn_bucket(None, None, sequence_length=1) == "unknown"


def test_missing_state_rows_generate_partial_report_without_fetching(tmp_path):
    db_path = tmp_path / "empty.duckdb"
    with duckdb.connect(str(db_path)):
        pass

    summary = generate_hmm_churn_dwell_report(
        db_path=db_path,
        run_id="latest",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        no_fetch=True,
    )

    assert summary["status"] == "partial"
    assert summary["state_rows_found"] is False
    assert summary["churn_bucket"] == "unknown"
    assert summary["external_data_fetch"] is False
    assert summary["training_algorithm_modified"] is False
    assert (tmp_path / "report.md").exists()
    assert json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))["status"] == "partial"


def test_cli_works_on_minimal_temporary_duckdb(tmp_path):
    db_path = tmp_path / "minimal.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE model_runs (
              run_id TEXT,
              model_type TEXT,
              created_at TIMESTAMP
            )
            """
        )
        con.execute("INSERT INTO model_runs VALUES ('run-1', 'hmm', now())")
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
              ('run-1', 'S1', '2026-01-01', 0, 'A', 'causal_walk_forward'),
              ('run-1', 'S1', '2026-01-02', 0, 'A', 'causal_walk_forward'),
              ('run-1', 'S1', '2026-01-03', 1, 'B', 'causal_walk_forward'),
              ('run-1', 'S1', '2026-01-04', 1, 'B', 'causal_walk_forward')
            """
        )

    report = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.hmm_churn_dwell",
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
    assert loaded["run_id"] == "run-1"
    assert loaded["state_rows_found"] is True
    assert loaded["churn_dwell_rows_generated"] == 2
    assert loaded["confidence_integration_status"] == "unavailable"
    assert loaded["implemented_wp_a_confidence"] is False
    assert loaded["implemented_wp_b_label_alignment"] is False
    with duckdb.connect(str(db_path)) as con:
        sequence_count = con.execute("SELECT COUNT(*) FROM hmm_churn_dwell_sequence").fetchone()[0]
        summary_count = con.execute("SELECT COUNT(*) FROM hmm_churn_dwell_run_summary").fetchone()[0]
    assert sequence_count == 2
    assert summary_count == 1


def test_alignment_integration_reads_wp_b_base_run_id_schema(tmp_path):
    db_path = tmp_path / "alignment.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE hmm_label_alignment_audit (
              audit_id TEXT PRIMARY KEY,
              base_run_id TEXT NOT NULL,
              compare_run_id TEXT NOT NULL,
              base_state_key TEXT NOT NULL,
              matched_state_key TEXT,
              match_score DOUBLE,
              state_signature_distance DOUBLE,
              label_preserved BOOLEAN,
              ambiguous_match BOOLEAN,
              label_drift_severity TEXT,
              alignment_method TEXT,
              coverage_status TEXT,
              created_at TIMESTAMP NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO hmm_label_alignment_audit VALUES (
              'audit-1', 'run-1', 'run-0', 'state_id:0', 'state_id:0',
              1.0, 0.0, true, false, 'none', 'hungarian', 'ok', now()
            )
            """
        )

        assert inspect_alignment_integration(con, "run-1") == "available_alignment"
        assert inspect_alignment_integration(con, "missing-run") == "missing_for_run"
