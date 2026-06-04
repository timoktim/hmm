from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from src.evaluation.stage03r_final_gate import (
    FORBIDDEN_OUTPUT_TERMS,
    build_report_markdown,
    evaluate_final_gate,
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
        "data_quality": report_dir / "data_quality_ci_report.json",
        "hazard_verdict": report_dir / "multi_horizon_hazard_verdict.md",
    }
    for key, path in paths.items():
        source = ROOT / "reports/stage03r" / path.name
        path.write_bytes(source.read_bytes())
    return paths


def _passing_gate_statuses() -> dict[str, dict[str, str]]:
    return {
        "exit_target_dataset_gate": {"status": "pass"},
        "target_leakage_purge_tests": {"status": "pass"},
        "data_quality_ci_gate": {"status": "pass"},
        "private_data_hygiene": {"status": "pass"},
        "stage01_no_private_db": {"status": "pass"},
        "stage03_preflight_gate": {"status": "pass"},
    }


def _evaluate(paths: dict[str, Path], **kwargs: Any) -> dict[str, Any]:
    return evaluate_final_gate(
        hazard_readiness_path=paths["hazard_readiness"],
        hazard_vs_hsmm_path=paths["hazard_vs_hsmm"],
        risk_protocol_path=paths["risk_protocol"],
        data_quality_path=paths["data_quality"],
        hazard_verdict_path=paths["hazard_verdict"],
        root=kwargs.pop("root", paths["hazard_readiness"].parents[2]),
        gate_statuses=kwargs.pop("gate_statuses", _passing_gate_statuses()),
        run_gate_scripts=False,
        **kwargs,
    ).to_summary()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def test_final_gate_passes_engineering_control_plane_criteria(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths)

    assert summary["index_id"] == "STAGE03R-WP10"
    assert summary["engineering_gate_verdict"] == "PASS"
    assert summary["final_verdict"] == "DEFER"
    assert summary["empirical_promotion_verdict"] == "DEFER"
    assert summary["blocking_issues"] == []


def test_final_gate_does_not_claim_broad_hazard_promotion_with_baseline_majority(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths)

    assert summary["readiness_status_summary"]["counts"]["baseline_only"] == 93
    assert summary["readiness_status_summary"]["baseline_only_majority"] == "yes"
    assert summary["hazard_scope_summary"]["usable_probability_scope"]["broadly_promoted"] == "no"
    assert summary["baseline_scope_summary"]["majority"] == "yes"


def test_missing_data_quality_report_causes_blocked(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    paths["data_quality"].unlink()
    summary = _evaluate(paths)

    assert summary["status"] == "blocked"
    assert summary["final_verdict"] == "BLOCKED"
    assert any("data_quality_ci" in issue for issue in summary["blocking_issues"])


def test_failed_data_quality_report_causes_blocked(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    data_quality = _read_json(paths["data_quality"])
    data_quality["status"] = "fail"
    data_quality["failure_count"] = 1
    data_quality["failures"] = ["probe failure"]
    _write_json(paths["data_quality"], data_quality)
    summary = _evaluate(paths)

    assert summary["final_verdict"] == "BLOCKED"
    assert any("data_quality_ci_compliance" in issue for issue in summary["blocking_issues"])


def test_missing_risk_protocol_causes_blocked(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    paths["risk_protocol"].unlink()
    summary = _evaluate(paths)

    assert summary["final_verdict"] == "BLOCKED"
    assert any("risk_validation_protocol" in issue for issue in summary["blocking_issues"])


def test_hsmm_diagnostic_only_namespace_is_preserved(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths)
    hsmm = summary["hsmm_scope_summary"]

    assert hsmm["role"] == "interpretation_only"
    assert hsmm["lifecycle_probability_status_policy"] == "diagnostic_only_not_decision_input"
    assert hsmm["diagnostic_count_field"] == "hsmm_lifecycle_probability_status_counts_diagnostic_only"


def test_hsmm_p_exit_used_for_decision_causes_blocked(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    hazard_vs_hsmm = _read_json(paths["hazard_vs_hsmm"])
    hazard_vs_hsmm["boundary_flags"]["HSMM_p_exit_used_for_decision"] = "yes"
    _write_json(paths["hazard_vs_hsmm"], hazard_vs_hsmm)
    summary = _evaluate(paths)

    assert summary["final_verdict"] == "BLOCKED"
    assert any("HSMM p_exit" in issue for issue in summary["blocking_issues"])


def test_final_holdout_absent_defers_empirical_promotion(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths)

    assert summary["engineering_gate_verdict"] == "PASS"
    assert summary["final_holdout_discipline"]["artifact_present"] == "no"
    assert summary["empirical_promotion_verdict"] in {"DEFER", "LOCAL_ONLY"}
    assert summary["defer_reasons"]


def test_final_holdout_cannot_be_consumed_repeatedly(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    final_holdout = tmp_path / "reports/stage03r/final_holdout_probe.json"
    final_holdout.write_text(
        json.dumps(
            {
                "consumption_count": 2,
                "wp10_only": "yes",
                "tuned_on_holdout": "no",
                "external_data_fetch": "no",
            }
        ),
        encoding="utf-8",
    )
    summary = _evaluate(paths, final_holdout_artifact=final_holdout)

    assert summary["final_verdict"] == "BLOCKED"
    assert any("consumption count exceeds one" in issue for issue in summary["blocking_issues"])


def test_final_gate_preserves_artifact_defer_when_non_overlap_not_proven(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    final_holdout = tmp_path / "reports/stage03r/final_holdout_artifact.json"
    final_holdout.write_text(
        json.dumps(
            {
                "consumption_count": 1,
                "consumed_in_wp10": "yes",
                "tuned_on_holdout": "no",
                "threshold_tuning_on_holdout": "no",
                "model_retrained": "no",
                "HMM_HSMM_retrained": "no",
                "HSMM_p_exit_used_for_decision": "no",
                "decision_surface_output": "no",
                "external_data_fetch": "no",
                "non_overlap_status": "not_proven",
                "empirical_promotion_verdict": "DEFER",
                "defer_reasons": ["non-overlap with prior calibration evidence is not proven"],
                "blocking_issues": [],
            }
        ),
        encoding="utf-8",
    )

    summary = _evaluate(paths, final_holdout_artifact=final_holdout)

    assert summary["final_verdict"] == "DEFER"
    assert summary["empirical_promotion_verdict"] == "DEFER"
    assert any("non-overlap" in reason for reason in summary["defer_reasons"])


def test_forbidden_output_terms_do_not_appear_in_final_outputs(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths)
    rendered = json.dumps(summary, ensure_ascii=False) + "\n" + build_report_markdown(summary)

    for term in FORBIDDEN_OUTPUT_TERMS:
        assert term not in rendered


def test_no_private_db_required_in_ci(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    summary = _evaluate(paths, db_path=None)

    assert summary["data_quality_ci_compliance"]["ci_requires_db"] == "no"
    assert summary["data_quality_ci_compliance"]["local_db_status"]["db_found"] == "no"
    assert summary["data_quality_ci_compliance"]["local_db_status"]["ci_requires_db"] == "no"


def test_cli_blocks_when_required_gate_scripts_are_skipped(tmp_path: Path) -> None:
    paths = _copy_public_artifacts(tmp_path)
    output = tmp_path / "reports/stage03r/stage03r_final_gate_report.md"
    summary_json = tmp_path / "reports/stage03r/stage03r_final_gate_report.json"

    exit_code = run_cli(
        Namespace(
            hazard_readiness=str(paths["hazard_readiness"]),
            hazard_vs_hsmm=str(paths["hazard_vs_hsmm"]),
            risk_protocol=str(paths["risk_protocol"]),
            data_quality=str(paths["data_quality"]),
            hazard_verdict=str(paths["hazard_verdict"]),
            final_holdout_artifact=None,
            db=None,
            root=str(tmp_path),
            output=str(output),
            summary_json=str(summary_json),
            no_fetch=True,
            skip_gate_scripts=True,
        )
    )
    summary = _read_json(summary_json)

    assert exit_code == 1
    assert output.exists()
    assert summary["final_verdict"] == "BLOCKED"
    assert any("gate status missing" in issue for issue in summary["blocking_issues"])


def test_gate_script_prints_stable_final_line() -> None:
    result = subprocess.run(
        ["bash", "scripts/stage03r_final_gate.sh"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "STAGE03R_FINAL_GATE=defer" in result.stdout
