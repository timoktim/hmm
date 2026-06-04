from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from src.evaluation.hazard_readiness_matrix import (
    BASELINE_ONLY,
    INSUFFICIENT_SAMPLE,
    ORDINAL_ONLY,
    USABLE_PROBABILITY,
    assign_readiness_status,
    evaluate_hazard_readiness_matrix,
    run_cli,
)


def _calibration_slice(
    *,
    horizon_days: int = 1,
    state_label: str = "Stress",
    state_phase: str = "early",
    age_bucket: str = "1-3",
    sample_count: int = 100,
    positive_count: int = 30,
    raw_brier: float | None = 0.25,
    calibrated_brier: float | None = 0.2,
    baseline_brier: float | None = 0.22,
    calibration_status: str = "calibration_candidate",
) -> dict[str, object]:
    return {
        "horizon_days": horizon_days,
        "state_label": state_label,
        "state_phase": state_phase,
        "age_bucket": age_bucket,
        "sample_count": sample_count,
        "positive_count": positive_count,
        "negative_count": sample_count - positive_count,
        "raw_brier": raw_brier,
        "calibrated_brier": calibrated_brier,
        "age_bucket_baseline_brier": baseline_brier,
        "calibration_status": calibration_status,
        "fallback_reason": None,
        "age_bucket_baseline_sample_count": 200,
        "age_bucket_baseline_event_rate": 0.31,
    }


def _baseline_row(
    *,
    horizon_days: int = 1,
    state_label: str = "Stress",
    state_phase: str = "early",
    age_bucket: str = "1-3",
    sample_count: int = 200,
    positive_count: int = 60,
    event_rate: float = 0.3,
    baseline_status: str = "empirical_baseline",
) -> dict[str, object]:
    return {
        "state_source": "causal_hsmm",
        "state_label": state_label,
        "state_phase": state_phase,
        "horizon_days": horizon_days,
        "age_bucket": age_bucket,
        "profile_mode": "latest_asof",
        "state_date_policy": "cutoff_only",
        "sample_count": sample_count,
        "positive_count": positive_count,
        "negative_count": sample_count - positive_count,
        "event_rate": event_rate,
        "baseline_status": baseline_status,
    }


def _calibration_report(*slices: dict[str, object]) -> dict[str, object]:
    return {
        "status": "pass",
        "calibration_version": "hazard_isotonic_calibration_v1",
        "horizons": sorted({int(row["horizon_days"]) for row in slices}),
        "horizon_metrics": [
            {
                "horizon_days": 1,
                "calibrated_ece": 0.05,
            }
        ],
        "slice_metrics": list(slices),
    }


def _baseline_report(*rows: dict[str, object]) -> dict[str, object]:
    return {
        "status": "pass",
        "baseline_version": "age_bucket_baseline_v1",
        "horizons": sorted({int(row["horizon_days"]) for row in rows}),
        "baseline_rows": list(rows),
    }


def _evaluate(
    calibration: dict[str, object] | None = None,
    baseline: dict[str, object] | None = None,
) -> dict[str, object]:
    result = evaluate_hazard_readiness_matrix(
        hazard_calibration=calibration or _calibration_report(_calibration_slice()),
        age_bucket_baseline=baseline or _baseline_report(_baseline_row()),
        expected_horizons=[1, 3],
        min_sample_count=30,
        min_baseline_sample_count=30,
    )
    return result.to_summary()


def test_usable_probability_requires_calibrated_brier_not_worse_than_raw() -> None:
    status, _ = assign_readiness_status(
        sample_count=100,
        positive_count=30,
        negative_count=70,
        raw_brier=0.2,
        calibrated_brier=0.25,
        age_bucket_baseline_brier=0.3,
        calibration_status="calibration_candidate",
        baseline_valid=False,
        missing_calibration=False,
        min_sample_count=30,
    )

    assert status == ORDINAL_ONLY


def test_usable_probability_not_allowed_when_worse_than_age_bucket_baseline() -> None:
    summary = _evaluate(
        calibration=_calibration_report(
            _calibration_slice(raw_brier=0.25, calibrated_brier=0.21, baseline_brier=0.18)
        ),
        baseline=_baseline_report(_baseline_row()),
    )

    row = summary["readiness_rows"][0]
    assert row["readiness_status"] == BASELINE_ONLY
    assert summary["usable_probability_count"] == 0


def test_degraded_brier_worse_becomes_baseline_or_ordinal_not_usable() -> None:
    summary = _evaluate(
        calibration=_calibration_report(
            _calibration_slice(
                raw_brier=0.2,
                calibrated_brier=None,
                baseline_brier=0.19,
                calibration_status="degraded_brier_worse",
            )
        ),
        baseline=_baseline_report(_baseline_row(event_rate=0.3)),
    )

    assert summary["readiness_rows"][0]["readiness_status"] == BASELINE_ONLY
    assert summary["usable_probability_count"] == 0


def test_sparse_slice_becomes_insufficient_sample() -> None:
    summary = _evaluate(
        calibration=_calibration_report(_calibration_slice(sample_count=5, positive_count=2)),
        baseline=_baseline_report(_baseline_row()),
    )

    assert summary["readiness_rows"][0]["readiness_status"] == INSUFFICIENT_SAMPLE


def test_missing_horizon_evidence_is_explicitly_represented() -> None:
    summary = _evaluate(
        calibration=_calibration_report(_calibration_slice(horizon_days=1)),
        baseline=_baseline_report(_baseline_row(horizon_days=1), _baseline_row(horizon_days=3, age_bucket="4-7")),
    )

    assert 3 in summary["horizon_coverage_summary"]["missing_calibration_horizons"]
    missing_rows = [
        row for row in summary["readiness_rows"] if row["fallback_reason"] == "missing_horizon_evidence"
    ]
    assert missing_rows
    assert missing_rows[0]["horizon_days"] == 3
    assert missing_rows[0]["readiness_status"] == BASELINE_ONLY


def test_no_decision_ready_risk_downshift_trade_signal_or_hsmm_p_exit_emitted() -> None:
    calibration = _calibration_report(_calibration_slice())
    calibration["hsmm_raw_p_exit"] = 0.9
    calibration["hsmm_calibrated_p_exit"] = 0.8

    summary = _evaluate(calibration=calibration, baseline=_baseline_report(_baseline_row()))
    serialized = json.dumps(summary, ensure_ascii=False)

    assert "decision_ready" not in serialized
    assert "risk_downshift" not in serialized
    assert "trade_signal" not in serialized
    assert "hsmm_raw_p_exit" not in serialized
    assert "hsmm_calibrated_p_exit" not in serialized
    assert summary["hsmm_p_exit_used"] == "no"


def test_supported_candidate_gets_usable_probability_readiness_status() -> None:
    summary = _evaluate()

    assert summary["readiness_rows"][0]["readiness_status"] == USABLE_PROBABILITY
    assert summary["usable_probability_count"] == 1


def test_no_external_fetch_cli_and_deterministic_status_counts(tmp_path: Path) -> None:
    calibration_path = tmp_path / "calibration.json"
    baseline_path = tmp_path / "baseline.json"
    output = tmp_path / "readiness.md"
    summary_json = tmp_path / "readiness.json"
    calibration_path.write_text(json.dumps(_calibration_report(_calibration_slice())), encoding="utf-8")
    baseline_path.write_text(json.dumps(_baseline_report(_baseline_row())), encoding="utf-8")

    args = Namespace(
        hazard_calibration=str(calibration_path),
        age_bucket_baseline=str(baseline_path),
        hazard_predictions=None,
        db=None,
        run_id="latest",
        horizons="1,3",
        output=str(output),
        summary_json=str(summary_json),
        min_sample_count=30,
        min_baseline_sample_count=30,
        no_fetch=True,
    )

    assert run_cli(args) == 0
    first = json.loads(summary_json.read_text(encoding="utf-8"))
    assert run_cli(args) == 0
    second = json.loads(summary_json.read_text(encoding="utf-8"))
    assert first["readiness_status_counts"] == second["readiness_status_counts"]
    assert first["external_data_fetch"] == "no"
    assert first["DuckDB_committed"] == "no"
