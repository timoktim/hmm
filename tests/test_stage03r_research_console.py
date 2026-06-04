from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.ui import stage03r_ui_data
from src.ui.stage03r_ui_data import (
    ANNOTATION_PATH,
    append_annotation,
    build_annotation_record,
    build_research_console_snapshot,
    forbidden_output_terms,
    load_local_db_sector_snapshot_readonly,
    load_split_registry_optional,
    load_stage03r_reports,
    validate_annotation_schema,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _seed_reports(root: Path) -> None:
    report_dir = root / "reports/stage03r"
    readiness_summary = {
        "counts": {
            "usable_probability": 21,
            "baseline_only": 93,
            "ordinal_only": 0,
            "insufficient_sample": 1,
            "invalid": 0,
        },
        "by_horizon": {
            "1": {"usable_probability": 7, "baseline_only": 16, "ordinal_only": 0, "insufficient_sample": 0, "invalid": 0},
            "3": {"usable_probability": 6, "baseline_only": 17, "ordinal_only": 0, "insufficient_sample": 0, "invalid": 0},
            "5": {"usable_probability": 3, "baseline_only": 20, "ordinal_only": 0, "insufficient_sample": 0, "invalid": 0},
            "10": {"usable_probability": 2, "baseline_only": 21, "ordinal_only": 0, "insufficient_sample": 0, "invalid": 0},
            "20": {"usable_probability": 3, "baseline_only": 19, "ordinal_only": 0, "insufficient_sample": 1, "invalid": 0},
        },
        "expected_horizons": [1, 3, 5, 10, 20],
        "hazard_locally_usable": "yes",
        "hazard_broadly_promoted": "no",
        "baseline_only_majority": "yes",
    }
    _write_json(
        report_dir / "stage03r_final_gate_report.json",
        {
            "status": "pass",
            "engineering_gate_verdict": "PASS",
            "empirical_promotion_verdict": "DEFER",
            "final_verdict": "DEFER",
            "defer_reasons": ["non-overlap with WP3-WP6.1 calibration/readiness evidence is not proven."],
            "readiness_status_summary": readiness_summary,
            "final_holdout_discipline": {
                "artifact_present": "yes",
                "artifact_empirical_promotion_verdict": "DEFER",
                "non_overlap_status": "not_proven",
                "consumption_count": 1,
            },
        },
    )
    _write_json(
        report_dir / "hazard_readiness_matrix_report.json",
        {"readiness_status_counts": readiness_summary["counts"], "expected_horizons": [1, 3, 5, 10, 20]},
    )
    _write_json(
        report_dir / "hazard_vs_hsmm_report.json",
        {
            "hsmm_lifecycle_availability": {
                "available": "yes",
                "row_count": 557104,
                "hsmm_numeric_p_exit_policy": "not_available",
            },
            "boundary_flags": {
                "decision_surface_output": "no",
            },
        },
    )
    _write_json(
        report_dir / "risk_validation_protocol.json",
        {
            "readiness_status_summary": readiness_summary,
            "semantic_cleanup_summary": {
                "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
            },
            "boundary_flags": {
                "decision_surface_output": "no",
            },
        },
    )
    _write_json(report_dir / "data_quality_ci_report.json", {"status": "pass", "local_db_status": {"db_found": "no"}})
    _write_json(
        report_dir / "final_holdout_artifact.json",
        {
            "holdout_status": "holdout_candidate",
            "empirical_promotion_verdict": "DEFER",
            "non_overlap_status": "not_proven",
            "consumption_count": 1,
        },
    )


def test_reports_load_without_private_db(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    reports = load_stage03r_reports(tmp_path / "reports/stage03r")
    snapshot = build_research_console_snapshot(root=tmp_path)

    assert reports["_missing"] == []
    assert snapshot["local_db"]["available"] == "no"
    assert snapshot["final_gate"]["engineering_gate"] == "PASS"
    assert snapshot["final_gate"]["empirical_promotion"] == "DEFER"
    assert snapshot["readiness_counts"]["baseline_only"] == 93
    assert snapshot["readiness_by_horizon"][0]["usable_probability"] == 7


def test_missing_split_registry_does_not_crash_ui_data_layer(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    registry = load_split_registry_optional(tmp_path / "reports/stage04/split_registry.json")
    snapshot = build_research_console_snapshot(root=tmp_path)

    assert registry["available"] == "no"
    assert snapshot["split_registry"]["status"] == "missing"


def test_annotation_schema_validates_and_appends(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    snapshot = build_research_console_snapshot(root=tmp_path)
    record = build_annotation_record(
        sector_code="industry:example",
        trade_date="2026-05-28",
        horizon_days=5,
        human_label="watch",
        confidence="medium",
        note="research note",
        model_context_snapshot={"final_gate": snapshot["final_gate"]},
        created_at="2026-06-04T00:00:00+00:00",
    )

    validated = validate_annotation_schema(record)
    out_path = append_annotation(validated, tmp_path / ANNOTATION_PATH)

    rows = [json.loads(line) for line in out_path.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["human_label"] == "watch"
    assert rows[0]["confidence"] == "medium"
    assert rows[0]["model_context_snapshot"]["final_gate"]["final_verdict"] == "DEFER"


def test_annotation_path_is_ignored() -> None:
    ignore_text = Path(".gitignore").read_text(encoding="utf-8")

    assert "data/local_annotations/" in ignore_text


def test_forbidden_terms_are_not_emitted_as_outputs(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    snapshot = build_research_console_snapshot(root=tmp_path)

    assert forbidden_output_terms(snapshot) == []


def test_no_external_fetch_dependency_in_data_layer(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    source = Path(stage03r_ui_data.__file__).read_text(encoding="utf-8")
    snapshot = build_research_console_snapshot(root=tmp_path)

    assert "requests" not in source
    assert "akshare" not in source
    assert "urllib" not in source
    assert snapshot["boundary"]["external_data_fetch"] == "no"


def test_local_db_optional_readonly_aggregate(tmp_path: Path) -> None:
    missing = load_local_db_sector_snapshot_readonly(tmp_path / "missing.duckdb")
    assert missing["available"] == "no"

    duckdb = pytest.importorskip("duckdb")
    db_path = tmp_path / "local.duckdb"
    con = duckdb.connect(str(db_path))
    try:
        con.execute("CREATE TABLE hsmm_lifecycle_ui_daily AS SELECT 1 AS id")
    finally:
        con.close()

    found = load_local_db_sector_snapshot_readonly(db_path)

    assert found["available"] == "yes"
    assert found["opened_read_only"] == "yes"
    assert found["row_counts"]["hsmm_lifecycle_ui_daily"] == 1
