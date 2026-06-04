from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pandas as pd

from src.evaluation.age_bucket_baseline import (
    EMPIRICAL_BASELINE,
    ORDINAL_FALLBACK,
    age_bucket,
    evaluate_age_bucket_baseline,
    run_cli,
)
from src.evaluation.exit_target_dataset import (
    OBSERVED_NEGATIVE,
    OBSERVED_POSITIVE,
    RIGHT_CENSORED_BY_RUN_END,
)


def _row(
    idx: int,
    *,
    state_age: int | None = 2,
    state_label: str = "Stress",
    state_phase: str = "early",
    horizon_days: int = 1,
    status: str = OBSERVED_NEGATIVE,
    exit_value: int | None = 0,
    sample_weight: float = 1.0,
    sector_code: str = "S1",
) -> dict[str, object]:
    trade_date = pd.Timestamp("2024-01-02") + pd.Timedelta(days=idx * 3)
    target_end = trade_date + pd.Timedelta(days=horizon_days)
    return {
        "target_dataset_id": "dataset",
        "run_id": "run",
        "source_run_id": "run",
        "sector_code": sector_code,
        "sector_id": sector_code,
        "trade_date": str(trade_date.date()),
        "state_source": "causal_hsmm",
        "state_label": state_label,
        "state_id": 1,
        "state_age": state_age,
        "state_phase": state_phase,
        "duration_percentile": 0.2,
        "duration_percentile_status": "available",
        "duration_tail_status": "within_duration_support",
        "horizon_days": horizon_days,
        "exit_within_horizon": exit_value,
        "next_state_label_realized": None,
        "target_observation_end_date": str(target_end.date()),
        "realized_exit_date": str(target_end.date()) if status == OBSERVED_POSITIVE else None,
        "censoring_status": status,
        "sample_weight": sample_weight,
        "target_definition_version": "exit_target_dataset_v1",
        "profile_mode": "latest_asof",
        "profile_cutoff_date": "2024-03-01",
        "state_date_policy": "cutoff_only",
        "feature_cutoff_date": str(trade_date.date()),
        "max_feature_date_used": str(trade_date.date()),
        "feature_leakage_violation": False,
        "purge_group_id": f"run:{sector_code}:{trade_date.date()}:{horizon_days}",
        "embargo_until_date": str(target_end.date()),
        "created_at": "2024-01-10T00:00:00",
    }


def test_sample_support_outputs_empirical_event_rate() -> None:
    data = pd.DataFrame(
        [
            _row(0, status=OBSERVED_POSITIVE, exit_value=1),
            _row(1, status=OBSERVED_NEGATIVE, exit_value=0),
            _row(2, status=OBSERVED_POSITIVE, exit_value=1),
        ]
    )

    result = evaluate_age_bucket_baseline(data, min_sample_count=3)
    row = result.baseline_rows[0]

    assert result.status == "pass"
    assert row["baseline_status"] == EMPIRICAL_BASELINE
    assert row["sample_count"] == 3
    assert row["positive_count"] == 2
    assert row["event_rate"] == 2 / 3
    assert row["probability_kind"] == "empirical_baseline"


def test_right_censored_rows_are_excluded_from_event_rate() -> None:
    data = pd.DataFrame(
        [
            _row(0, status=OBSERVED_POSITIVE, exit_value=1),
            _row(1, status=OBSERVED_NEGATIVE, exit_value=0),
            _row(2, status=RIGHT_CENSORED_BY_RUN_END, exit_value=None, sample_weight=0.0),
        ]
    )

    result = evaluate_age_bucket_baseline(data, min_sample_count=2)
    row = result.baseline_rows[0]

    assert row["sample_count"] == 2
    assert row["positive_count"] == 1
    assert row["right_censored_excluded_count"] == 1
    assert row["event_rate"] == 0.5


def test_age_bucket_boundaries_are_deterministic() -> None:
    assert age_bucket(1) == "1-3"
    assert age_bucket(3) == "1-3"
    assert age_bucket(4) == "4-7"
    assert age_bucket(7) == "4-7"
    assert age_bucket(8) == "8-14"
    assert age_bucket(14) == "8-14"
    assert age_bucket(15) == "15+"
    assert age_bucket(0) == "unknown"
    assert age_bucket(None) == "unknown"


def test_sparse_slice_uses_ordinal_fallback_without_numeric_probability() -> None:
    data = pd.DataFrame(
        [
            _row(0, status=OBSERVED_POSITIVE, exit_value=1),
            _row(1, status=OBSERVED_NEGATIVE, exit_value=0),
        ]
    )

    result = evaluate_age_bucket_baseline(data, min_sample_count=3)
    row = result.baseline_rows[0]

    assert result.status == "partial"
    assert row["baseline_status"] == ORDINAL_FALLBACK
    assert row["event_rate"] is None
    assert row["exit_tendency_ordinal"] == "medium"
    assert row["fallback_reason"] == "sample_count 2 below min_sample_count 3"
    assert "usable_probability" not in row


def test_grouping_includes_phase_horizon_profile_policy_and_age_bucket() -> None:
    data = pd.DataFrame(
        [
            _row(0, state_age=2, state_phase="early", horizon_days=1, status=OBSERVED_POSITIVE, exit_value=1),
            _row(1, state_age=6, state_phase="mature", horizon_days=3, status=OBSERVED_NEGATIVE, exit_value=0),
        ]
    )

    result = evaluate_age_bucket_baseline(data, min_sample_count=1)
    keys = {
        (
            row["state_source"],
            row["state_label"],
            row["state_phase"],
            row["horizon_days"],
            row["age_bucket"],
            row["profile_mode"],
            row["state_date_policy"],
        )
        for row in result.baseline_rows
    }

    assert ("causal_hsmm", "Stress", "early", 1, "1-3", "latest_asof", "cutoff_only") in keys
    assert ("causal_hsmm", "Stress", "mature", 3, "4-7", "latest_asof", "cutoff_only") in keys


def test_cli_writes_markdown_and_json_without_external_fetch(tmp_path: Path) -> None:
    dataset_path = tmp_path / "dataset.csv"
    output = tmp_path / "baseline.md"
    summary_json = tmp_path / "baseline.json"
    pd.DataFrame(
        [
            _row(0, status=OBSERVED_POSITIVE, exit_value=1),
            _row(1, status=OBSERVED_NEGATIVE, exit_value=0),
            _row(2, status=OBSERVED_POSITIVE, exit_value=1),
        ]
    ).to_csv(dataset_path, index=False)

    exit_code = run_cli(
        Namespace(
            dataset=str(dataset_path),
            db=None,
            run_id="latest",
            horizons="1,3,5,10,20",
            output=str(output),
            summary_json=str(summary_json),
            min_sample_count=2,
            no_fetch=True,
        )
    )

    assert exit_code == 0
    assert output.exists()
    assert summary_json.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["external_data_fetch"] == "no"
    assert summary["usable_probability_count"] == 0


def test_feature_leakage_hard_fails_before_baseline() -> None:
    data = pd.DataFrame([_row(0, status=OBSERVED_POSITIVE, exit_value=1)])
    data.loc[0, "max_feature_date_used"] = "2024-01-10"

    result = evaluate_age_bucket_baseline(data, min_sample_count=1)

    assert result.status == "fail"
    assert result.audit_hard_violation_count > 0
    assert result.baseline_rows == []
