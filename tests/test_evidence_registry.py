from __future__ import annotations

import json

import pytest

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.evidence_registry import (
    EvidenceLevel,
    EvidenceRecord,
    ReadinessStatus,
    get_latest_evidence,
    list_evidence_for_run,
    make_evidence_id,
    seed_ui_readiness_policy,
    upsert_evidence_record,
)


def test_storage_init_schema_is_idempotent_and_creates_registry_tables(tmp_path):
    db_path = tmp_path / "registry.duckdb"
    storage = DuckDBStorage(db_path)

    storage.init_schema()
    storage.init_schema()

    with storage.connect() as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema = 'main'"
            ).fetchall()
        }
        assert {"model_evidence_registry", "validation_runs", "ui_readiness_policy"}.issubset(tables)
        columns = {row[1] for row in con.execute("PRAGMA table_info('model_evidence_registry')").fetchall()}
        assert {
            "evidence_id",
            "run_id",
            "model_type",
            "evidence_level",
            "readiness_status",
            "feature_scope_id",
            "artifact_manifest_json",
            "metrics_json",
        }.issubset(columns)


def test_seed_ui_readiness_policy_is_repeatable_without_duplicates(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")

    assert seed_ui_readiness_policy(db_path) == 9
    assert seed_ui_readiness_policy(db_path) == 9

    with DuckDBStorage(db_path).connect() as con:
        assert con.execute("SELECT COUNT(*) FROM ui_readiness_policy").fetchone()[0] == 9


def test_make_evidence_id_is_stable_and_discriminates_inputs():
    first = make_evidence_id("run-1", "hmm", "reports/a.md")

    assert first == make_evidence_id("run-1", "HMM", "reports/a.md")
    assert first != make_evidence_id("run-1", "hmm", "reports/b.md")
    assert first != make_evidence_id("run-1", "hsmm", "reports/a.md")


def test_upsert_evidence_record_inserts_and_updates_same_evidence(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")
    evidence_id = upsert_evidence_record(
        db_path,
        EvidenceRecord(
            run_id="run-1",
            model_type="hmm",
            evidence_level=EvidenceLevel.INTERNAL_DIAGNOSTIC,
            readiness_status=ReadinessStatus.RESEARCH_ONLY,
            feature_scope_id="sector_features_v1",
            report_path="reports/a.md",
            metrics_json={"score": 1},
        ),
    )

    same_id = upsert_evidence_record(
        db_path,
        EvidenceRecord(
            run_id="run-1",
            model_type="hmm",
            evidence_level="internal_diagnostic",
            readiness_status="internal_only",
            feature_scope_id="sector_features_v1",
            report_path="reports/a.md",
            metrics_json={"score": 2},
        ),
    )

    assert same_id == evidence_id
    frame = list_evidence_for_run(db_path, "run-1")
    assert len(frame) == 1
    assert frame.iloc[0]["readiness_status"] == "internal_only"
    assert json.loads(frame.iloc[0]["metrics_json"]) == {"score": 2}

    latest = get_latest_evidence(db_path, "hmm", run_id="run-1")
    assert latest is not None
    assert latest["evidence_id"] == evidence_id


def test_missing_feature_scope_is_recorded_as_missing_with_note(tmp_path):
    db_path = str(tmp_path / "registry.duckdb")

    evidence_id = upsert_evidence_record(
        db_path,
        EvidenceRecord(
            run_id="run-missing-feature",
            model_type="hsmm",
            evidence_level="exploratory",
            readiness_status="research_only",
            report_path="reports/missing_feature.md",
        ),
    )

    latest = get_latest_evidence(db_path, "hsmm", run_id="run-missing-feature")
    assert latest is not None
    assert latest["evidence_id"] == evidence_id
    assert latest["feature_scope_id"] == "missing"
    assert "feature_scope_id missing" in latest["notes"]


@pytest.mark.parametrize(
    ("evidence_level", "readiness_status"),
    [
        ("production_signal", "research_only"),
        ("internal_diagnostic", "ready_for_trading"),
    ],
)
def test_invalid_evidence_enums_are_rejected(tmp_path, evidence_level, readiness_status):
    with pytest.raises(ValueError):
        upsert_evidence_record(
            str(tmp_path / "registry.duckdb"),
            EvidenceRecord(
                run_id="bad-run",
                model_type="hmm",
                evidence_level=evidence_level,
                readiness_status=readiness_status,
                report_path="reports/bad.md",
            ),
        )
