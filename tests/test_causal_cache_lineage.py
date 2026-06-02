from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from src.evaluation.causal_cache_lineage import (
    ensure_causal_cache_lineage_schema,
    run_causal_cache_lineage,
    upsert_causal_cache_linkage,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _create_model_and_states(con: duckdb.DuckDBPyConnection, *, run_id: str = "run-1", expected_rows: int = 2) -> None:
    con.execute(
        """
        CREATE TABLE model_runs (
          run_id TEXT,
          model_type TEXT,
          n_states INTEGER,
          feature_scope_id TEXT,
          universe_id TEXT,
          scope_type TEXT,
          feature_version TEXT,
          train_start DATE,
          train_end DATE,
          created_at TIMESTAMP
        )
        """
    )
    con.execute(
        """
        INSERT INTO model_runs
        VALUES (?, 'hmm', 3, 'scope-1', 'u-1', 'sector', 'fv1', '2025-01-01', '2026-01-01', '2026-01-02')
        """,
        [run_id],
    )
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
    rows = [
        (run_id, f"S{index}", "2026-01-02", index % 3, "State", "in_sample_display")
        for index in range(1, expected_rows + 1)
    ]
    con.executemany("INSERT INTO sector_state_daily VALUES (?, ?, ?, ?, ?, ?)", rows)


def _create_cache_tables(con: duckdb.DuckDBPyConnection, *, native: bool = False, walk_forward: bool = False) -> None:
    native_column = "run_id TEXT," if native else ""
    walk_forward_columns = "train_window_days INTEGER, retrain_frequency TEXT, state_date_mode TEXT," if walk_forward else ""
    con.execute(
        f"""
        CREATE TABLE walk_forward_cache_runs (
          cache_key TEXT,
          {native_column}
          n_states INTEGER,
          feature_scope_id TEXT,
          universe_id TEXT,
          scope_type TEXT,
          feature_version TEXT,
          start_date DATE,
          end_date DATE,
          params_hash TEXT,
          {walk_forward_columns}
          created_at TIMESTAMP
        )
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


def _insert_cache_run(
    con: duckdb.DuckDBPyConnection,
    *,
    cache_key: str = "cache-1",
    native: bool = False,
    run_id: str = "run-1",
    walk_forward: bool = False,
) -> None:
    if native:
        con.execute(
            """
            INSERT INTO walk_forward_cache_runs
            VALUES (?, ?, 3, 'scope-1', 'u-1', 'sector', 'fv1', '2026-01-01', '2026-01-02', 'hash-1', '2026-01-02')
            """,
            [cache_key, run_id],
        )
    elif walk_forward:
        con.execute(
            """
            INSERT INTO walk_forward_cache_runs
            VALUES (?, 3, 'scope-1', 'u-1', 'sector', 'fv1', '2026-01-01', '2026-01-02', 'hash-1', 120, 'monthly', 'rebalance_signals_v2', '2026-01-02')
            """,
            [cache_key],
        )
    else:
        con.execute(
            """
            INSERT INTO walk_forward_cache_runs
            VALUES (?, 3, 'scope-1', 'u-1', 'sector', 'fv1', '2026-01-01', '2026-01-02', 'hash-1', '2026-01-02')
            """,
            [cache_key],
        )


def _insert_cache_state_rows(
    con: duckdb.DuckDBPyConnection,
    *,
    cache_key: str = "cache-1",
    row_count: int = 2,
    missing_metadata: bool = False,
) -> None:
    rows = []
    for index in range(1, row_count + 1):
        train_end = None if missing_metadata and index == 1 else "2026-01-02"
        rows.append((cache_key, f"S{index}", "2026-01-02", index % 3, "State", train_end, "2026-01-02", "causal_backtest"))
    con.executemany("INSERT INTO walk_forward_state_cache VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)


def test_schema_creation_is_idempotent(tmp_path):
    db_path = tmp_path / "lineage.duckdb"
    with duckdb.connect(str(db_path)) as con:
        ensure_causal_cache_lineage_schema(con)
        ensure_causal_cache_lineage_schema(con)
        columns = [row[1] for row in con.execute("PRAGMA table_info(causal_cache_run_linkage)").fetchall()]

    assert "linkage_id" in columns
    assert "causal_evidence_id" in columns
    assert "linkage_status" in columns


def test_native_link_detection(tmp_path):
    db_path = tmp_path / "native.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con, native=True)
        _insert_cache_run(con, native=True)
        _insert_cache_state_rows(con)

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
    )

    assert result.linkage_status == "native_link"
    assert result.native_link_available is True
    assert result.readiness_effect != "decision_ready"


def test_strict_inferred_link_success_with_one_candidate(tmp_path):
    db_path = tmp_path / "strict.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con)
        _insert_cache_run(con)
        _insert_cache_state_rows(con)

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
        write_linkage_table=True,
    )

    assert result.linkage_status == "strict_inferred_link"
    assert result.strict_inferred_link_available is True
    assert result.candidate_count == 1
    assert result.linkage_written is True
    with duckdb.connect(str(db_path), read_only=True) as con:
        count = con.execute("SELECT COUNT(*) FROM causal_cache_run_linkage").fetchone()[0]
    assert count == 1


def test_ambiguous_candidates_do_not_upgrade(tmp_path):
    db_path = tmp_path / "ambiguous.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con)
        _insert_cache_run(con, cache_key="cache-1")
        _insert_cache_run(con, cache_key="cache-2")
        _insert_cache_state_rows(con, cache_key="cache-1")
        _insert_cache_state_rows(con, cache_key="cache-2")

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
    )

    assert result.linkage_status == "ambiguous"
    assert result.competing_candidate_count == 1
    assert result.readiness_effect == "research_only_no_upgrade"


def test_missing_metadata_requires_regeneration(tmp_path):
    db_path = tmp_path / "missing.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con)
        _insert_cache_run(con)
        _insert_cache_state_rows(con, missing_metadata=True)

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
    )

    assert result.linkage_status == "requires_regeneration"
    assert "missing_cache_state_metadata" in result.blocking_reasons


def test_weak_inferred_candidate_does_not_upgrade_readiness(tmp_path):
    db_path = tmp_path / "weak.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con, expected_rows=2)
        _create_cache_tables(con, walk_forward=True)
        _insert_cache_run(con, walk_forward=True)
        _insert_cache_state_rows(con, row_count=1)

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
    )

    assert result.linkage_status == "weak_inferred_candidate"
    assert result.readiness_effect == "research_only_no_upgrade"
    assert result.strict_inferred_link_available is False


def test_cli_writes_valid_markdown_and_json(tmp_path):
    db_path = tmp_path / "cli.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con)
        _insert_cache_run(con)
        _insert_cache_state_rows(con)

    report = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.causal_cache_lineage",
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
    assert "# Stage 02 WP-E Causal Cache Lineage Repair" in report.read_text(encoding="utf-8")
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["index_id"] == "STAGE02-WP-E-v1"
    assert payload["linkage_status"] == "strict_inferred_link"
    assert payload["external_data_fetch"] is False
    assert payload["readiness_effect"] != "decision_ready"


def test_no_fetch_false_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="does not support fetching external data"):
        run_causal_cache_lineage(
            db_path=tmp_path / "missing.duckdb",
            run_id="latest",
            output_path=tmp_path / "report.md",
            summary_json_path=tmp_path / "report.json",
            no_fetch=False,
        )


def test_upsert_helper_is_idempotent(tmp_path):
    db_path = tmp_path / "upsert.duckdb"
    with duckdb.connect(str(db_path)) as con:
        _create_model_and_states(con)
        _create_cache_tables(con)
        _insert_cache_run(con)
        _insert_cache_state_rows(con)

    result = run_causal_cache_lineage(
        db_path=db_path,
        run_id="latest",
        output_path=tmp_path / "report.md",
        summary_json_path=tmp_path / "report.json",
    )

    with duckdb.connect(str(db_path)) as con:
        assert upsert_causal_cache_linkage(con, result) is True
        assert upsert_causal_cache_linkage(con, result) is True
        count = con.execute("SELECT COUNT(*) FROM causal_cache_run_linkage").fetchone()[0]

    assert count == 1
