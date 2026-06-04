from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pandas as pd

from src.evaluation.hazard_isotonic_calibration import (
    CALIBRATION_CANDIDATE,
    DEGRADED_BRIER_WORSE,
    ORDINAL_ONLY,
    calibration_status_for_metrics,
    evaluate_hazard_isotonic_calibration,
    run_cli,
)


def _prediction_row(
    idx: int,
    *,
    split_role: str = "validation",
    state_label: str = "Stress",
    state_phase: str = "early",
    state_age: int = 2,
    horizon_days: int = 1,
    probability: float | None = None,
    label: int | None = None,
    hazard_status: str = "raw_probability_only",
) -> dict[str, object]:
    exit_value = int(idx % 3 == 0) if label is None else label
    raw_probability = (0.2 + 0.012 * (idx % 30)) if probability is None else probability
    return {
        "target_dataset_id": "dataset",
        "sector_code": f"S{idx % 4}",
        "trade_date": str((pd.Timestamp("2024-01-02") + pd.Timedelta(days=idx)).date()),
        "state_label": state_label,
        "state_age": state_age,
        "state_phase": state_phase,
        "horizon_days": horizon_days,
        "censoring_status": "observed_positive" if exit_value == 1 else "observed_negative",
        "exit_within_horizon": exit_value,
        "fold_id": f"split_{idx % 2 + 1}",
        "split_role": split_role,
        "hazard_model_version": "duration_hazard_logistic_v1",
        "hazard_raw_score": 0.0,
        "hazard_raw_probability": raw_probability,
        "hazard_status": hazard_status,
        "sample_support": 100,
        "fallback_reason": None,
    }


def _predictions(row_count: int = 40, **kwargs: object) -> pd.DataFrame:
    return pd.DataFrame([_prediction_row(idx, **kwargs) for idx in range(row_count)])


def _age_bucket_summary(event_rate: float = 0.35, sample_count: int = 200) -> dict[str, object]:
    return {
        "status": "pass",
        "baseline_version": "age_bucket_baseline_v1",
        "baseline_rows": [
            {
                "state_label": "Stress",
                "state_phase": "early",
                "horizon_days": 1,
                "age_bucket": "1-3",
                "sample_count": sample_count,
                "positive_count": int(sample_count * event_rate),
                "event_rate": event_rate,
                "baseline_status": "empirical_baseline",
            }
        ],
    }


def test_validation_rows_only_and_final_holdout_excluded() -> None:
    data = pd.concat(
        [
            _predictions(40),
            _predictions(5, split_role="train"),
            _predictions(3, split_role="final_holdout"),
        ],
        ignore_index=True,
    )

    result = evaluate_hazard_isotonic_calibration(data, age_bucket_baseline=_age_bucket_summary(), min_sample_count=20)
    summary = result.to_summary()

    assert summary["status"] == "pass"
    assert summary["validation_only"] is True
    assert summary["final_holdout_tuning"] is False
    assert summary["calibration_sample_count"] == 40
    assert summary["non_validation_excluded_count"] == 5
    assert summary["final_holdout_excluded_count"] == 3
    assert summary["usable_probability_count"] == 0


def test_sparse_slice_uses_ordinal_only_without_calibrated_probability() -> None:
    result = evaluate_hazard_isotonic_calibration(_predictions(8), min_sample_count=30, min_slice_sample_count=30)
    summary = result.to_summary()

    assert summary["status"] == "partial"
    assert summary["calibration_status_counts"][ORDINAL_ONLY] == 1
    assert summary["calibrated_probability_count"] == 0
    assert summary["usable_probability_count"] == 0
    assert summary["slice_metrics"][0]["fallback_reason"] == "sample_count 8 below min_sample_count 30"


def test_worsened_brier_prevents_candidate_status() -> None:
    status, reason = calibration_status_for_metrics(
        sample_count=50,
        positive_count=25,
        negative_count=25,
        raw_brier=0.1,
        calibrated_brier=0.2,
        min_sample_count=30,
    )

    assert status == DEGRADED_BRIER_WORSE
    assert reason == "calibrated Brier worse than raw Brier"


def test_age_bucket_baseline_comparison_is_explicit() -> None:
    result = evaluate_hazard_isotonic_calibration(
        _predictions(40),
        age_bucket_baseline=_age_bucket_summary(event_rate=0.4),
        min_sample_count=20,
        min_slice_sample_count=20,
    )
    summary = result.to_summary()

    assert summary["age_bucket_baseline_joined_row_count"] == 40
    assert summary["age_bucket_baseline_key_columns"] == ["state_label", "state_phase", "horizon_days", "age_bucket"]
    assert summary["age_bucket_baseline_brier_mean"] is not None
    assert summary["slice_metrics"][0]["age_bucket_baseline_event_rate"] == 0.4


def test_no_usable_probability_emitted_for_supported_calibration() -> None:
    result = evaluate_hazard_isotonic_calibration(_predictions(60), min_sample_count=20, min_slice_sample_count=20)
    summary = result.to_summary()

    assert summary["status"] == "pass"
    assert CALIBRATION_CANDIDATE in summary["calibration_status_counts"]
    assert summary["calibrated_probability_count"] > 0
    assert summary["usable_probability_count"] == 0
    assert all(metric["calibration_status"] != "usable_probability" for metric in summary["slice_metrics"])


def test_cli_writes_markdown_json_without_external_fetch(tmp_path: Path) -> None:
    predictions_path = tmp_path / "predictions.csv"
    baseline_path = tmp_path / "age_bucket.json"
    output = tmp_path / "calibration.md"
    summary_json = tmp_path / "calibration.json"
    _predictions(40).to_csv(predictions_path, index=False)
    baseline_path.write_text(json.dumps(_age_bucket_summary()), encoding="utf-8")

    exit_code = run_cli(
        Namespace(
            hazard_predictions=str(predictions_path),
            age_bucket_baseline=str(baseline_path),
            db=None,
            run_id="latest",
            horizons="1,3,5,10,20",
            output=str(output),
            summary_json=str(summary_json),
            min_sample_count=20,
            min_slice_sample_count=20,
            min_train_samples=4,
            max_predictions=5000,
            hazard_baseline_output=str(tmp_path / "hazard.md"),
            hazard_baseline_summary_json=str(tmp_path / "hazard.json"),
            age_bucket_baseline_output=str(tmp_path / "age_bucket.md"),
            age_bucket_min_sample_count=30,
            no_fetch=True,
        )
    )

    assert exit_code == 0
    assert output.exists()
    assert summary_json.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["external_data_fetch"] == "no"
    assert summary["training_algorithm_modified"] == "no"
    assert summary["usable_probability_count"] == 0
