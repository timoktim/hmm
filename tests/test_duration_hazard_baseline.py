from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pandas as pd

from src.evaluation.exit_target_dataset import (
    OBSERVED_NEGATIVE,
    OBSERVED_POSITIVE,
    RIGHT_CENSORED_BY_RUN_END,
)
from src.evaluation.exit_target_leakage_audit import build_purged_time_split_plan, validate_split_plan
from src.models.duration_hazard import (
    INSUFFICIENT_SAMPLE,
    MODEL_VERSION,
    RAW_PROBABILITY_ONLY,
    REQUIRED_PREDICTION_COLUMNS,
    fit_duration_hazard_baseline,
    run_cli,
    write_hazard_outputs,
)


def _row(
    idx: int,
    *,
    sector_code: str = "S1",
    label: str = "A",
    trade_date: str | None = None,
    horizon_days: int = 1,
    status: str = OBSERVED_NEGATIVE,
    exit_value: int | None = 0,
    sample_weight: float = 1.0,
    target_end: str | None = None,
    leakage: bool = False,
) -> dict[str, object]:
    date = pd.Timestamp(trade_date or "2024-01-02") + pd.Timedelta(days=idx)
    target = pd.Timestamp(target_end) if target_end else date + pd.Timedelta(days=horizon_days)
    return {
        "target_dataset_id": "dataset",
        "run_id": "run",
        "source_run_id": "run",
        "sector_code": sector_code,
        "sector_id": sector_code,
        "trade_date": str(date.date()),
        "state_source": "causal_hsmm",
        "state_label": label,
        "state_id": 1 if label == "A" else 2,
        "state_age": idx + 1,
        "state_phase": "early" if idx % 2 == 0 else "mature",
        "duration_percentile": min(0.95, 0.05 * (idx + 1)),
        "duration_percentile_status": "available",
        "duration_tail_status": "within_duration_support",
        "horizon_days": horizon_days,
        "exit_within_horizon": exit_value,
        "next_state_label_realized": None,
        "target_observation_end_date": str(target.date()),
        "realized_exit_date": str(target.date()) if status == OBSERVED_POSITIVE else None,
        "censoring_status": status,
        "sample_weight": sample_weight,
        "target_definition_version": "exit_target_dataset_v1",
        "profile_mode": "latest_asof",
        "profile_cutoff_date": "2024-03-01",
        "state_date_policy": "cutoff_only",
        "feature_cutoff_date": str((date + pd.Timedelta(days=1)).date() if leakage else date.date()),
        "max_feature_date_used": str((date + pd.Timedelta(days=1)).date() if leakage else date.date()),
        "feature_leakage_violation": leakage,
        "purge_group_id": f"run:{sector_code}:{date.date()}:{horizon_days}",
        "embargo_until_date": str(target.date()),
        "created_at": "2024-01-10T00:00:00",
    }


def _two_class_dataset(row_count: int = 24) -> pd.DataFrame:
    rows = []
    for idx in range(row_count):
        is_positive = idx % 4 in {1, 2}
        rows.append(
            _row(
                idx,
                label="B" if is_positive else "A",
                status=OBSERVED_POSITIVE if is_positive else OBSERVED_NEGATIVE,
                exit_value=1 if is_positive else 0,
            )
        )
    return pd.DataFrame(rows)


def _multi_horizon_dataset(rows_per_horizon: int = 36) -> pd.DataFrame:
    rows = []
    for horizon in [1, 3, 5, 10, 20]:
        for idx in range(rows_per_horizon):
            is_positive = idx % 5 in {1, 2}
            rows.append(
                _row(
                    idx,
                    trade_date=str((pd.Timestamp("2024-01-02") + pd.Timedelta(days=idx)).date()),
                    horizon_days=horizon,
                    label="B" if is_positive else "A",
                    status=OBSERVED_POSITIVE if is_positive else OBSERVED_NEGATIVE,
                    exit_value=1 if is_positive else 0,
                )
            )
    return pd.DataFrame(rows)


def test_right_censored_rows_are_excluded_from_training() -> None:
    data = _two_class_dataset()
    data = pd.concat(
        [
            data,
            pd.DataFrame(
                [
                    _row(40, status=RIGHT_CENSORED_BY_RUN_END, exit_value=None, sample_weight=0.0),
                    _row(41, status=RIGHT_CENSORED_BY_RUN_END, exit_value=None, sample_weight=0.0),
                ]
            ),
        ],
        ignore_index=True,
    )

    result = fit_duration_hazard_baseline(data)

    assert result.status == "pass"
    assert result.right_censored_excluded_count == 2
    assert result.trainable_row_count == len(data) - 2
    assert "excluded_censored" in result.hazard_status_counts


def test_feature_leakage_rows_fail_before_training() -> None:
    data = _two_class_dataset()
    data.loc[0, "feature_leakage_violation"] = True
    data.loc[0, "max_feature_date_used"] = "2024-01-04"

    result = fit_duration_hazard_baseline(data)

    assert result.status == "fail"
    assert result.feature_leakage_violation_count > 0
    assert result.audit_hard_violation_count > 0


def test_purged_split_plan_prevents_train_validation_overlap() -> None:
    data = pd.DataFrame(
        [
                _row(0, target_end="2024-01-10"),
            _row(2, target_end="2024-01-04"),
            _row(7, target_end="2024-01-10", status=OBSERVED_POSITIVE, exit_value=1),
            _row(10, target_end="2024-01-12"),
        ]
    )

    plan = build_purged_time_split_plan(data, n_splits=1)

    assert plan.splits
    assert not validate_split_plan(data, plan)
    assert 0 not in plan.splits[0].train_indices


def test_logistic_baseline_fits_synthetic_two_class_dataset() -> None:
    result = fit_duration_hazard_baseline(_two_class_dataset(), min_train_samples=4)

    assert result.status == "pass"
    assert result.model_version == MODEL_VERSION
    assert result.hazard_status_counts[RAW_PROBABILITY_ONLY] > 0
    assert any(metric.brier_raw is not None for metric in result.fold_metrics)


def test_single_class_fold_returns_insufficient_sample_not_fake_metric() -> None:
    data = pd.DataFrame([_row(idx, status=OBSERVED_NEGATIVE, exit_value=0) for idx in range(12)])

    result = fit_duration_hazard_baseline(data)

    assert result.status == "partial"
    assert result.hazard_status_counts[INSUFFICIENT_SAMPLE] > 0
    assert all(metric.brier_raw is None for metric in result.fold_metrics)


def test_missing_optional_features_do_not_fail_and_are_reported() -> None:
    result = fit_duration_hazard_baseline(_two_class_dataset())

    assert result.status == "pass"
    assert "volatility_20d" in result.missing_feature_columns
    assert "market_regime_label" in result.missing_feature_columns


def test_prediction_output_includes_required_hazard_fields() -> None:
    result = fit_duration_hazard_baseline(_two_class_dataset())

    assert set(REQUIRED_PREDICTION_COLUMNS).issubset(result.predictions.columns)
    assert result.predictions["hazard_model_version"].eq(MODEL_VERSION).all()
    assert result.predictions["hazard_status"].isin(
        {"raw_probability_only", "insufficient_sample", "invalid", "excluded_censored"}
    ).all()


def test_wp3_never_emits_usable_probability() -> None:
    result = fit_duration_hazard_baseline(_two_class_dataset())
    summary = result.to_summary()

    assert "usable_probability" not in result.predictions.columns
    assert summary["usable_probability_count"] == 0


def test_cli_writes_markdown_json_and_predictions_without_external_fetch(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    output = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    predictions = tmp_path / "predictions.csv"
    _two_class_dataset().to_csv(dataset_path, index=False)

    exit_code = run_cli(
        Namespace(
            dataset=str(dataset_path),
            db=None,
            run_id="latest",
            horizons="1,3,5,10,20",
            output=str(output),
            summary_json=str(summary_json),
            predictions_csv=str(predictions),
            min_train_samples=4,
            max_predictions=5000,
            no_fetch=True,
        )
    )

    assert exit_code == 0
    assert output.exists()
    assert summary_json.exists()
    assert predictions.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    prediction_rows = pd.read_csv(predictions)
    assert summary["status"] == "pass"
    assert summary["external_data_fetch"] == "no"
    assert summary["usable_probability_count"] == 0
    assert not prediction_rows.empty


def test_multi_horizon_prediction_outputs_and_sample_preserve_all_horizons(tmp_path: Path) -> None:
    expected_horizons = {1, 3, 5, 10, 20}
    result = fit_duration_hazard_baseline(_multi_horizon_dataset(), min_train_samples=4)

    assert set(result.horizons) == expected_horizons
    assert set(result.predictions["horizon_days"].astype(int).unique()) == expected_horizons

    full_predictions = tmp_path / "predictions_full.csv"
    sampled_predictions = tmp_path / "predictions_sample.csv"
    write_hazard_outputs(
        result,
        output=tmp_path / "full.md",
        summary_json=tmp_path / "full.json",
        predictions_csv=full_predictions,
        max_predictions=0,
    )
    write_hazard_outputs(
        result,
        output=tmp_path / "sample.md",
        summary_json=tmp_path / "sample.json",
        predictions_csv=sampled_predictions,
        max_predictions=10,
    )

    full = pd.read_csv(full_predictions)
    sample = pd.read_csv(sampled_predictions)
    assert len(full) == len(result.predictions)
    assert set(full["horizon_days"].astype(int).unique()) == expected_horizons
    assert len(sample) <= 10
    assert set(sample["horizon_days"].astype(int).unique()) == expected_horizons


def test_no_external_fetch_argument_is_accepted(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    _two_class_dataset().to_csv(dataset_path, index=False)

    exit_code = run_cli(
        Namespace(
            dataset=str(dataset_path),
            db=None,
            run_id="latest",
            horizons="1",
            output=str(tmp_path / "report.md"),
            summary_json=str(tmp_path / "report.json"),
            predictions_csv=str(tmp_path / "predictions.csv"),
            min_train_samples=4,
            max_predictions=10,
            no_fetch=True,
        )
    )

    assert exit_code == 0
