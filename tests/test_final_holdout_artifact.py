from __future__ import annotations

import json
import subprocess
from argparse import Namespace
from pathlib import Path
from typing import Any

from src.evaluation.final_holdout_artifact import (
    _forbidden_output_hits,
    apply_final_holdout_verdict,
    evaluate_final_holdout_artifact,
    run_cli,
)


ROOT = Path(__file__).resolve().parents[1]


def _base_summary(**updates: Any) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "status": "defer",
        "artifact_version": "final_holdout_artifact_v1",
        "index_id": "STAGE03R-WP10.1",
        "source_db": "data/db/a_share_hmm.duckdb",
        "db_opened_read_only": "yes",
        "external_data_fetch": "no",
        "holdout_policy": {"policy": "latest_complete_observed_horizon_window"},
        "holdout_start_date": "2026-04-27",
        "holdout_end_date": "2026-05-27",
        "holdout_status": "holdout_candidate",
        "holdout_selection_reason": "latest deterministic complete observed horizon window",
        "non_overlap_status": "not_proven",
        "non_overlap_evidence": {"proof_status": "not_proven"},
        "consumption_count": 1,
        "consumed_in_wp10": "yes",
        "tuned_on_holdout": "no",
        "threshold_tuning_on_holdout": "no",
        "model_retrained": "no",
        "HMM_HSMM_retrained": "no",
        "HSMM_p_exit_used_for_decision": "no",
        "decision_surface_output": "no",
        "readiness_status_counts": {"usable_probability": 3, "baseline_only": 7},
        "metrics_by_readiness_status": {},
        "readiness_status_verdicts": {},
        "metrics_by_horizon": {},
        "usable_probability_metrics": {"sample_count": 3},
        "baseline_only_metrics": {"sample_count": 7},
        "insufficient_sample_metrics": {"sample_count": 0},
        "abstain_coverage": {"observed_holdout_row_count": 10, "probability_metric_row_count": 10},
        "false_confidence_flags": [],
        "blocking_issues": [],
        "defer_reasons": [],
        "empirical_promotion_verdict": "DEFER",
        "final_recommendation": "",
        "observed_metric_row_count": 10,
    }
    summary.update(updates)
    return summary


def test_final_holdout_artifact_includes_consumption_count_one() -> None:
    summary = apply_final_holdout_verdict(_base_summary())

    assert summary["consumption_count"] == 1
    assert summary["consumed_in_wp10"] == "yes"


def test_final_holdout_artifact_includes_no_tuning_or_retraining_flags() -> None:
    summary = apply_final_holdout_verdict(_base_summary())

    assert summary["tuned_on_holdout"] == "no"
    assert summary["threshold_tuning_on_holdout"] == "no"
    assert summary["model_retrained"] == "no"
    assert summary["HMM_HSMM_retrained"] == "no"


def test_missing_non_overlap_evidence_produces_defer_not_pass() -> None:
    summary = apply_final_holdout_verdict(_base_summary(non_overlap_status="not_proven"))

    assert summary["status"] == "defer"
    assert summary["empirical_promotion_verdict"] == "DEFER"
    assert any("non-overlap" in reason for reason in summary["defer_reasons"])


def test_candidate_artifact_carries_readiness_status_verdicts_without_private_db(tmp_path: Path) -> None:
    result = evaluate_final_holdout_artifact(
        db_path=str(tmp_path / "data/db/a_share_hmm.duckdb"),
        hazard_readiness_path=ROOT / "reports/stage03r/hazard_readiness_matrix_report.json",
        risk_protocol_path=ROOT / "reports/stage03r/risk_validation_protocol.json",
        data_quality_path=ROOT / "reports/stage03r/data_quality_ci_report.json",
    ).to_summary()

    assert result["holdout_status"] == "holdout_candidate"
    assert set(result["readiness_status_verdicts"]) == {
        "usable_probability",
        "ordinal_only",
        "baseline_only",
        "insufficient_sample",
        "invalid",
    }
    assert {item["verdict"] for item in result["readiness_status_verdicts"].values()} == {"DEFER"}


def test_repeated_consumption_count_blocks() -> None:
    summary = apply_final_holdout_verdict(_base_summary(consumption_count=2))

    assert summary["status"] == "blocked"
    assert summary["empirical_promotion_verdict"] == "BLOCKED"
    assert any("consumption count exceeds one" in issue for issue in summary["blocking_issues"])


def test_threshold_tuning_on_holdout_blocks() -> None:
    summary = apply_final_holdout_verdict(_base_summary(threshold_tuning_on_holdout="yes"))

    assert summary["status"] == "blocked"
    assert any("threshold tuning" in issue for issue in summary["blocking_issues"])


def test_hsmm_p_exit_decision_usage_blocks() -> None:
    summary = apply_final_holdout_verdict(_base_summary(HSMM_p_exit_used_for_decision="yes"))

    assert summary["status"] == "blocked"
    assert any("HSMM p_exit" in issue for issue in summary["blocking_issues"])


def test_forbidden_output_terms_are_absent_except_required_denial_flag() -> None:
    summary = apply_final_holdout_verdict(_base_summary())

    assert _forbidden_output_hits(summary) == []


def test_no_private_db_required_for_ci_defer_path(tmp_path: Path) -> None:
    result = evaluate_final_holdout_artifact(
        db_path=str(tmp_path / "data/db/a_share_hmm.duckdb"),
        hazard_readiness_path=ROOT / "reports/stage03r/hazard_readiness_matrix_report.json",
        risk_protocol_path=ROOT / "reports/stage03r/risk_validation_protocol.json",
        data_quality_path=ROOT / "reports/stage03r/data_quality_ci_report.json",
    ).to_summary()

    assert result["status"] == "defer"
    assert result["db_opened_read_only"] == "no"
    assert result["empirical_promotion_verdict"] == "DEFER"


def test_cli_writes_defer_artifact_without_private_db(tmp_path: Path) -> None:
    output = tmp_path / "final_holdout_artifact.md"
    summary_json = tmp_path / "final_holdout_artifact.json"
    exit_code = run_cli(
        Namespace(
            db=None,
            hazard_readiness=str(ROOT / "reports/stage03r/hazard_readiness_matrix_report.json"),
            risk_protocol=str(ROOT / "reports/stage03r/risk_validation_protocol.json"),
            data_quality=str(ROOT / "reports/stage03r/data_quality_ci_report.json"),
            output=str(output),
            summary_json=str(summary_json),
            holdout_trading_days=20,
            no_fetch=True,
        )
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output.exists()
    assert summary["status"] == "defer"
    assert summary["external_data_fetch"] == "no"


def test_no_duckdb_wal_or_full_prediction_csv_committed() -> None:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    tracked = result.stdout.splitlines()

    assert not [path for path in tracked if path.endswith((".duckdb", ".duckdb.wal", ".wal"))]
    assert not [path for path in tracked if path.endswith(".csv") and "prediction" in Path(path).name and not path.endswith("_sample.csv")]


def test_script_prints_stable_final_line() -> None:
    result = subprocess.run(
        ["bash", "scripts/stage03r_final_holdout_artifact.sh"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 0, result.stdout
    assert "STAGE03R_FINAL_HOLDOUT_ARTIFACT=defer" in result.stdout
