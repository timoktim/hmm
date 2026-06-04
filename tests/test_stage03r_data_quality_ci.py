from __future__ import annotations

import csv
import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from src.evaluation.stage03r_data_quality_ci import (
    EXPECTED_HORIZONS,
    HSMM_DIAGNOSTIC_COUNT_FIELD,
    evaluate_data_quality_ci,
    run_cli,
)


ROOT = Path(__file__).resolve().parents[1]


def _copy_public_artifacts(tmp_path: Path) -> dict[str, Path]:
    report_dir = tmp_path / "reports/stage03r"
    report_dir.mkdir(parents=True)
    paths = {
        "hazard_readiness": report_dir / "hazard_readiness_matrix_report.json",
        "hazard_vs_hsmm": report_dir / "hazard_vs_hsmm_report.json",
        "risk_protocol": report_dir / "risk_validation_protocol.json",
        "hazard_verdict": report_dir / "multi_horizon_hazard_verdict.md",
        "hazard_prediction_sample": report_dir / "duration_hazard_logistic_predictions_sample.csv",
        "exit_target_sample": report_dir / "exit_target_dataset_v1_sample.csv",
    }
    source_names = {
        "hazard_readiness": "hazard_readiness_matrix_report.json",
        "hazard_vs_hsmm": "hazard_vs_hsmm_report.json",
        "risk_protocol": "risk_validation_protocol.json",
        "hazard_verdict": "multi_horizon_hazard_verdict.md",
        "hazard_prediction_sample": "duration_hazard_logistic_predictions_sample.csv",
        "exit_target_sample": "exit_target_dataset_v1_sample.csv",
    }
    for key, name in source_names.items():
        paths[key].write_bytes((ROOT / "reports/stage03r" / name).read_bytes())
    return paths


def _evaluate(paths: dict[str, Path], *, root: Path, db_path: str | None = None) -> dict[str, Any]:
    return evaluate_data_quality_ci(
        hazard_readiness_path=paths["hazard_readiness"],
        hazard_vs_hsmm_path=paths["hazard_vs_hsmm"],
        risk_protocol_path=paths["risk_protocol"],
        hazard_verdict_path=paths["hazard_verdict"],
        hazard_prediction_sample_path=paths["hazard_prediction_sample"],
        db_path=db_path,
        root=root,
    ).to_summary()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_data_quality_gate_passes_public_artifacts_without_local_db(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "pass"
    assert summary["local_db_status"]["db_found"] == "no"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"


def test_data_quality_gate_records_local_db_status_when_db_exists(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    missing_db = tmp_path / "data/db/a_share_hmm.duckdb"
    summary = _evaluate(paths, root=tmp_path, db_path=str(missing_db))

    assert summary["status"] == "pass"
    assert summary["local_db_status"]["db_path_used"].endswith("a_share_hmm.duckdb")
    assert summary["local_db_status"]["db_found"] == "no"
    assert summary["local_db_status"]["ci_requires_db"] == "no"


def test_missing_required_artifact_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    paths["risk_protocol"].unlink()
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert any("risk_protocol_exists" in failure for failure in summary["failures"])


def test_invalid_readiness_status_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    readiness = _read_json(paths["hazard_readiness"])
    readiness["readiness_rows"][0]["readiness_status"] = "numeric_probability"
    _write_json(paths["hazard_readiness"], readiness)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert any("allowed_statuses" in failure for failure in summary["failures"])


def test_missing_horizon_in_prediction_sample_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    rows = []
    with paths["hazard_prediction_sample"].open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        for row in reader:
            if int(float(row["horizon_days"])) != 20:
                rows.append(row)
    with paths["hazard_prediction_sample"].open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert summary["horizon_coverage_summary"]["hazard_prediction_sample_horizons"] == [1, 3, 5, 10]


def test_full_prediction_csv_committed_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    full_csv = tmp_path / "reports/stage03r/duration_hazard_logistic_predictions.csv"
    full_csv.write_text("horizon_days\n1\n", encoding="utf-8")
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert "reports/stage03r/duration_hazard_logistic_predictions.csv" in (
        summary["private_data_hygiene_summary"]["full_prediction_csv_committed"]
    )


def test_unqualified_hsmm_probability_status_counts_in_protocol_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    protocol = _read_json(paths["risk_protocol"])
    protocol["semantic_cleanup_summary"]["hsmm_probability_status_counts"] = {"usable_probability": 1}
    _write_json(paths["risk_protocol"], protocol)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert any("no_legacy_hsmm_probability_status_counts" in failure for failure in summary["failures"])


def test_hsmm_diagnostic_namespace_passes(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "pass"
    assert summary["hsmm_diagnostic_namespace_summary"]["diagnostic_count_field"] == HSMM_DIAGNOSTIC_COUNT_FIELD
    assert summary["hsmm_diagnostic_namespace_summary"]["diagnostic_policy"] == "diagnostic_only_not_decision_input"


def test_final_holdout_consumption_outside_wp10_causes_fail(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    protocol = _read_json(paths["risk_protocol"])
    protocol["split_and_final_holdout_discipline"]["final_holdout_consumption"] = "final holdout consumed during WP9"
    _write_json(paths["risk_protocol"], protocol)
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert any("final_holdout_wp10_only" in failure for failure in summary["failures"])


def test_forbidden_protocol_terms_cause_fail(tmp_path: Path) -> None:
    for term in ["decision_ready", "decision_surface", "risk_downshift", "trade_signal", "buy_signal", "sell_signal"]:
        paths = _copy_public_artifacts(tmp_path / term)
        protocol = _read_json(paths["risk_protocol"])
        protocol["forbidden_probe"] = term
        _write_json(paths["risk_protocol"], protocol)
        summary = _evaluate(paths, root=tmp_path / term)

        assert summary["status"] == "fail", term
        assert any("forbidden_surface_terms" in failure for failure in summary["failures"])


def test_private_path_duckdb_wal_cache_hygiene_is_covered(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    private_file = tmp_path / "reports/stage03r/private_path_probe.md"
    private_file.write_text("/Users/example/private\n", encoding="utf-8")
    wal = tmp_path / "reports/stage03r/a_share_hmm.duckdb.wal"
    wal.write_text("wal", encoding="utf-8")
    cache = tmp_path / "data/cache/probe.txt"
    cache.parent.mkdir(parents=True)
    cache.write_text("cache", encoding="utf-8")
    summary = _evaluate(paths, root=tmp_path)

    assert summary["status"] == "fail"
    assert summary["private_data_hygiene_summary"]["private_path_hits"]
    assert summary["private_data_hygiene_summary"]["duckdb_or_wal_files_committed"]
    assert summary["private_data_hygiene_summary"]["cache_files_committed"]


def test_cli_writes_reports_and_preserves_expected_horizons(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    output = tmp_path / "reports/stage03r/data_quality_ci_report.md"
    summary_json = tmp_path / "reports/stage03r/data_quality_ci_report.json"

    exit_code = run_cli(
        Namespace(
            hazard_readiness=str(paths["hazard_readiness"]),
            hazard_vs_hsmm=str(paths["hazard_vs_hsmm"]),
            risk_protocol=str(paths["risk_protocol"]),
            hazard_verdict=str(paths["hazard_verdict"]),
            hazard_prediction_sample=str(paths["hazard_prediction_sample"]),
            db=None,
            root=str(tmp_path),
            output=str(output),
            summary_json=str(summary_json),
            no_fetch=True,
        )
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output.exists()
    assert summary["horizon_coverage_summary"]["hazard_prediction_sample_horizons"] == EXPECTED_HORIZONS


def test_gate_script_prints_pass_on_success() -> None:
    result = subprocess.run(
        ["bash", "scripts/stage03r_data_quality_ci_gate.sh"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "STAGE03R_DATA_QUALITY_CI_GATE=pass" in result.stdout
