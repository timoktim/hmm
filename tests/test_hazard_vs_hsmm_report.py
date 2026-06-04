from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from src.evaluation.hazard_vs_hsmm_report import (
    build_report_markdown,
    evaluate_hazard_vs_hsmm,
    run_cli,
)


def _readiness_row(
    *,
    horizon_days: int = 1,
    readiness_status: str = "usable_probability",
    baseline_delta: float | None = -0.01,
) -> dict[str, object]:
    return {
        "state_label": "Stress",
        "horizon_days": horizon_days,
        "age_bucket": "1-3",
        "state_phase": "early",
        "profile_mode": "latest_asof",
        "state_date_policy": "full_run",
        "sample_count": 100,
        "positive_count": 30,
        "negative_count": 70,
        "event_rate": 0.3,
        "raw_brier": 0.22,
        "calibrated_brier": 0.2,
        "age_bucket_baseline_brier": 0.21,
        "brier_delta_calibrated_vs_raw": -0.02,
        "brier_delta_calibrated_vs_baseline": baseline_delta,
        "calibrated_ece": 0.01,
        "calibration_status": "calibration_candidate",
        "age_bucket_baseline_sample_count": 200,
        "age_bucket_baseline_event_rate": 0.28,
        "ordinal_separation": 0.02,
        "fallback_reason": None,
        "readiness_status": readiness_status,
        "readiness_version": "hazard_readiness_matrix_v1",
        "source": "calibration_x_age_bucket_baseline",
    }


def _hazard_readiness() -> dict[str, object]:
    rows = [
        _readiness_row(horizon_days=1, readiness_status="usable_probability"),
        _readiness_row(horizon_days=1, readiness_status="baseline_only", baseline_delta=0.01),
        _readiness_row(horizon_days=3, readiness_status="baseline_only", baseline_delta=0.02),
        _readiness_row(horizon_days=20, readiness_status="insufficient_sample", baseline_delta=None),
    ]
    return {
        "status": "pass",
        "readiness_version": "hazard_readiness_matrix_v1",
        "readiness_rows": rows,
        "readiness_status_counts": {
            "usable_probability": 1,
            "ordinal_only": 0,
            "baseline_only": 2,
            "insufficient_sample": 1,
            "invalid": 0,
        },
    }


def _age_bucket_baseline() -> dict[str, object]:
    return {
        "status": "pass",
        "baseline_version": "age_bucket_baseline_v1",
        "baseline_rows": [],
    }


def _hsmm_summary(*, p_exit: bool = False) -> dict[str, object]:
    return {
        "available": "yes",
        "db_path_used": "data/db/a_share_hmm.duckdb",
        "db_found": "yes",
        "opened_read_only": "yes",
        "row_count": 1000,
        "run_ids": [{"run_id": "hsmm_lifecycle_primary_v1", "row_count": 1000}],
        "profile_policy_counts": [{"profile_mode": "latest_asof", "state_date_policy": "full_run", "row_count": 1000}],
        "p_exit_columns": ["raw_p_exit_1d"] if p_exit else [],
        "exit_tendency_columns": ["exit_tendency_1d", "exit_tendency_3d"],
        "probability_status_columns": ["probability_status_1d"],
        "matched_numeric_artifact": "present" if p_exit else "missing",
        "hsmm_numeric_p_exit_policy": "diagnostic_only_not_decision_input" if p_exit else "not_available",
        "ordinal_tendency_available": "yes",
        "per_horizon": {
            "1": {
                "available": "yes",
                "ordinal_tendency_counts": {"low": 700, "medium": 300},
                "probability_status_counts": {"hidden": 1000},
                "matched_hazard_slice_count": 2,
            },
            "3": {
                "available": "yes",
                "ordinal_tendency_counts": {"medium": 1000},
                "probability_status_counts": {"hidden": 1000},
                "matched_hazard_slice_count": 1,
            },
        },
    }


def test_report_markdown_does_not_emit_forbidden_signal_fields() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(),
    )
    markdown = build_report_markdown(result.to_summary())

    assert '"decision_ready":' not in markdown
    assert "risk_downshift" not in markdown
    assert "trade_signal" not in markdown
    assert "buy_signal" not in markdown
    assert "sell_signal" not in markdown


def test_hsmm_p_exit_present_is_marked_diagnostic_not_decision_input() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(p_exit=True),
    ).to_summary()

    hsmm = result["hsmm_lifecycle_availability"]
    assert hsmm["matched_numeric_artifact"] == "present"
    assert hsmm["hsmm_numeric_p_exit_policy"] == "diagnostic_only_not_decision_input"
    assert result["boundary_flags"]["HSMM_p_exit_used_for_decision"] == "no"


def test_usable_probability_count_comes_only_from_hazard_readiness() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(p_exit=True),
    ).to_summary()

    assert result["hazard_readiness_counts"]["usable_probability"] == 1
    assert result["usable_probability_scope"]["count"] == 1
    assert result["usable_probability_scope"]["source"] == "hazard_readiness_matrix_only"


def test_baseline_only_majority_is_preserved() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(),
    ).to_summary()

    assert result["baseline_only_scope"]["count"] == 2
    assert result["baseline_only_scope"]["majority"] == "yes"
    assert "baseline" in result["hazard_vs_age_bucket_baseline_verdict"].lower()


def test_missing_matched_hsmm_numeric_artifact_is_explicit() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(),
    ).to_summary()

    assert result["hsmm_lifecycle_availability"]["matched_numeric_artifact"] == "missing"
    assert any("missing" in warning for warning in result["warnings"])


def test_json_summary_boundary_flags_and_local_usability_verdict() -> None:
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=_hazard_readiness(),
        age_bucket_baseline=_age_bucket_baseline(),
        hsmm_lifecycle_summary=_hsmm_summary(),
    ).to_summary()

    assert result["boundary_flags"] == {
        "external_data_fetch": "no",
        "training_algorithm_modified": "no",
        "HMM_HSMM_retrained": "no",
        "HSMM_p_exit_used_for_decision": "no",
        "decision_ready_output": "no",
        "DuckDB_committed": "no",
    }
    assert "locally usable" in result["hazard_vs_hsmm_verdict"]
    assert "not broadly promoted" in result["hazard_vs_hsmm_verdict"]


def test_cli_writes_report_without_external_fetch(tmp_path: Path) -> None:
    readiness = tmp_path / "readiness.json"
    baseline = tmp_path / "baseline.json"
    verdict = tmp_path / "verdict.md"
    output = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    readiness.write_text(json.dumps(_hazard_readiness()), encoding="utf-8")
    baseline.write_text(json.dumps(_age_bucket_baseline()), encoding="utf-8")
    verdict.write_text("hazard is locally usable, not broadly promoted", encoding="utf-8")

    exit_code = run_cli(
        Namespace(
            hazard_readiness=str(readiness),
            hazard_verdict=str(verdict),
            age_bucket_baseline=str(baseline),
            db=None,
            run_id="latest",
            output=str(output),
            summary_json=str(summary_json),
            no_fetch=True,
        )
    )

    assert exit_code == 0
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert output.exists()
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["hsmm_lifecycle_availability"]["available"] == "no"
