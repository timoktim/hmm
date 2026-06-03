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
from src.evaluation.exit_target_leakage_audit import (
    SplitPlan,
    audit_exit_target_dataset,
    build_purged_time_split_plan,
    detect_overlapping_target_windows,
    run_cli,
    validate_split_plan,
)


def _row(
    idx: int,
    *,
    sector_code: str = "S1",
    trade_date: str = "2024-01-02",
    target_end: str = "2024-01-03",
    horizon_days: int = 1,
    status: str = OBSERVED_NEGATIVE,
    exit_value: int | None = 0,
    realized_exit_date: str | None = None,
    sample_weight: float = 1.0,
    purge_group_id: str | None = None,
    embargo_until_date: str | None = None,
    max_feature_date_used: str | None = None,
    feature_cutoff_date: str | None = None,
) -> dict[str, object]:
    return {
        "target_dataset_id": "dataset",
        "run_id": "run",
        "source_run_id": "run",
        "sector_code": sector_code,
        "sector_id": sector_code,
        "trade_date": trade_date,
        "state_source": "causal_hsmm",
        "state_label": "A",
        "state_id": 1,
        "state_age": idx + 1,
        "state_phase": "early",
        "duration_percentile": 0.2,
        "duration_percentile_status": "available",
        "duration_tail_status": "within_duration_support",
        "horizon_days": horizon_days,
        "exit_within_horizon": exit_value,
        "next_state_label_realized": None,
        "target_observation_end_date": target_end,
        "realized_exit_date": realized_exit_date,
        "censoring_status": status,
        "sample_weight": sample_weight,
        "target_definition_version": "exit_target_dataset_v1",
        "profile_mode": "latest_asof",
        "profile_cutoff_date": "2024-02-01",
        "state_date_policy": "cutoff_only",
        "feature_cutoff_date": feature_cutoff_date or trade_date,
        "max_feature_date_used": max_feature_date_used or trade_date,
        "feature_leakage_violation": False,
        "purge_group_id": purge_group_id or f"run:{sector_code}:{trade_date}:{horizon_days}",
        "embargo_until_date": embargo_until_date or target_end,
        "created_at": "2024-01-10T00:00:00",
    }


def _valid_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(0, trade_date="2024-01-02", target_end="2024-01-03", horizon_days=1),
            _row(1, trade_date="2024-01-04", target_end="2024-01-05", horizon_days=1),
            _row(2, trade_date="2024-01-08", target_end="2024-01-09", horizon_days=1),
            _row(
                3,
                trade_date="2024-01-10",
                target_end="2024-01-11",
                horizon_days=1,
                status=OBSERVED_POSITIVE,
                exit_value=1,
                realized_exit_date="2024-01-11",
            ),
        ]
    )


def _fails(dataset: pd.DataFrame, expected_check: str) -> None:
    result = audit_exit_target_dataset(dataset, strict=True)
    checks = {violation.check for violation in result.violations}
    assert result.status == "fail"
    assert expected_check in checks


def test_feature_date_after_trade_date_fails() -> None:
    data = _valid_dataset()
    data.loc[0, "max_feature_date_used"] = "2024-01-04"

    _fails(data, "feature_date_lte_trade_date")


def test_observed_positive_after_target_end_fails() -> None:
    data = pd.DataFrame(
        [
            _row(
                0,
                status=OBSERVED_POSITIVE,
                exit_value=1,
                realized_exit_date="2024-01-05",
                target_end="2024-01-03",
            )
        ]
    )

    _fails(data, "observed_positive_exit_date")


def test_observed_negative_with_incomplete_target_horizon_fails() -> None:
    data = pd.DataFrame([_row(0, trade_date="2024-01-02", target_end="2024-01-03", horizon_days=5)])

    _fails(data, "observed_negative_full_horizon")


def test_right_censored_row_with_zero_label_fails() -> None:
    data = pd.DataFrame(
        [
            _row(
                0,
                status=RIGHT_CENSORED_BY_RUN_END,
                exit_value=0,
                sample_weight=0.0,
                target_end="2024-01-04",
            )
        ]
    )

    _fails(data, "right_censored_label_null")


def test_right_censored_row_with_positive_sample_weight_fails() -> None:
    data = pd.DataFrame(
        [
            _row(
                0,
                status=RIGHT_CENSORED_BY_RUN_END,
                exit_value=None,
                sample_weight=1.0,
                target_end="2024-01-04",
            )
        ]
    )

    _fails(data, "right_censored_sample_weight")


def test_missing_purge_group_id_fails() -> None:
    data = _valid_dataset()
    data.loc[0, "purge_group_id"] = None

    _fails(data, "purge_group_id_present")


def test_embargo_before_target_end_fails() -> None:
    data = _valid_dataset()
    data.loc[0, "embargo_until_date"] = "2024-01-02"

    _fails(data, "embargo_covers_target_window")


def test_overlapping_target_windows_are_detected_by_sector() -> None:
    data = pd.DataFrame(
        [
            _row(0, trade_date="2024-01-02", target_end="2024-01-05", horizon_days=3),
            _row(1, trade_date="2024-01-04", target_end="2024-01-08", horizon_days=3),
            _row(2, sector_code="S2", trade_date="2024-01-04", target_end="2024-01-08", horizon_days=3),
        ]
    )

    overlaps = detect_overlapping_target_windows(data)

    assert len(overlaps) == 1
    assert overlaps.loc[0, "sector_code"] == "S1"


def test_purged_split_plan_excludes_overlapping_train_rows() -> None:
    data = pd.DataFrame(
        [
            _row(0, trade_date="2024-01-02", target_end="2024-01-06", horizon_days=4),
            _row(1, trade_date="2024-01-04", target_end="2024-01-05", horizon_days=1),
            _row(2, trade_date="2024-01-08", target_end="2024-01-09", horizon_days=1),
        ]
    )

    plan = build_purged_time_split_plan(data, n_splits=1)

    assert plan.splits
    assert 0 not in plan.splits[0].train_indices
    assert not validate_split_plan(data, plan)


def test_embargo_excludes_train_rows_through_validation_start() -> None:
    data = pd.DataFrame(
        [
            _row(0, trade_date="2024-01-02", target_end="2024-01-03", embargo_until_date="2024-01-04"),
            _row(1, trade_date="2024-01-04", target_end="2024-01-05"),
            _row(2, trade_date="2024-01-08", target_end="2024-01-09"),
        ]
    )

    plan = build_purged_time_split_plan(data, n_splits=1)

    assert plan.splits
    assert 0 not in plan.splits[0].train_indices
    assert not validate_split_plan(data, plan)


def test_final_holdout_policy_locked_and_not_reusable() -> None:
    data = _valid_dataset()
    plan = build_purged_time_split_plan(data, n_splits=1, final_holdout_start="2024-01-10")

    assert plan.final_holdout_locked is True
    assert plan.final_holdout_reuse_allowed is False
    assert plan.final_holdout_reuse_count == 1

    bad_plan = SplitPlan(
        splits=plan.splits,
        final_holdout_start=plan.final_holdout_start,
        final_holdout_locked=True,
        final_holdout_reuse_allowed=False,
        final_holdout_reuse_count=2,
    )
    violations = validate_split_plan(data, bad_plan)
    assert {violation.check for violation in violations} == {"final_holdout_not_reused"}


def test_cli_writes_markdown_and_json_without_external_fetch(tmp_path: Path) -> None:
    dataset = _valid_dataset()
    dataset_path = tmp_path / "dataset.csv"
    output = tmp_path / "audit.md"
    summary_json = tmp_path / "audit.json"
    dataset.to_csv(dataset_path, index=False)

    exit_code = run_cli(
        Namespace(
            dataset=str(dataset_path),
            db=None,
            run_id="latest",
            horizons="1,3,5,10,20",
            output=str(output),
            summary_json=str(summary_json),
            strict=True,
            no_fetch=True,
        )
    )

    assert exit_code == 0
    assert output.exists()
    assert summary_json.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["external_data_fetch"] == "no"
    assert summary["final_holdout_policy_present"] is True
