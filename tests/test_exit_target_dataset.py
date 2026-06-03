from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import duckdb
import pandas as pd

from src.evaluation.exit_target_dataset import (
    OBSERVED_NEGATIVE,
    OBSERVED_POSITIVE,
    RIGHT_CENSORED_BY_CUTOFF,
    RIGHT_CENSORED_BY_RUN_END,
    TARGET_DEFINITION_VERSION,
    build_exit_target_dataset,
    run_cli,
)


def _states(labels: list[str], *, cutoff: str | None = "2024-01-31", extra: dict | None = None) -> pd.DataFrame:
    dates = pd.bdate_range("2024-01-02", periods=len(labels))
    rows: list[dict[str, object]] = []
    for idx, (date, label) in enumerate(zip(dates, labels, strict=True), start=1):
        row: dict[str, object] = {
            "run_id": "target_run",
            "source_run_id": "target_run",
            "sector_code": "S1",
            "sector_id": "S1",
            "trade_date": date,
            "state_source": "causal_hsmm",
            "state_label": label,
            "state_id": 1 if label == "A" else 2,
            "state_age_days": idx,
            "state_phase": "early" if idx <= 2 else "mature",
            "duration_percentile": 0.1 * idx,
            "duration_percentile_status": "available",
            "duration_tail_status": "within_duration_support",
            "profile_mode": "latest_asof",
            "profile_cutoff_date": cutoff,
            "state_date_policy": "cutoff_only",
            "feature_cutoff_date": date,
            "max_feature_date_used": date,
        }
        if extra:
            row.update(extra)
        rows.append(row)
    return pd.DataFrame(rows)


def test_exit_inside_horizon_is_observed_positive() -> None:
    result = build_exit_target_dataset(_states(["A", "B", "B"]), horizons=(1,))

    first = result.dataset.iloc[0]
    assert first["censoring_status"] == OBSERVED_POSITIVE
    assert first["exit_within_horizon"] == 1
    assert first["realized_exit_date"] == "2024-01-03"
    assert first["next_state_label_realized"] == "B"


def test_full_horizon_without_exit_is_observed_negative() -> None:
    result = build_exit_target_dataset(_states(["A", "A", "A", "B"]), horizons=(2,))

    first = result.dataset.iloc[0]
    assert first["censoring_status"] == OBSERVED_NEGATIVE
    assert first["exit_within_horizon"] == 0


def test_horizon_beyond_run_end_is_right_censored_not_negative() -> None:
    result = build_exit_target_dataset(_states(["A", "A"]), horizons=(5,))

    first = result.dataset.iloc[0]
    assert first["censoring_status"] == RIGHT_CENSORED_BY_RUN_END
    assert pd.isna(first["exit_within_horizon"])
    assert result.summary["observed_negative_count"] == 0
    assert result.summary["right_censored_count"] == 2


def test_profile_cutoff_before_horizon_end_is_right_censored_by_cutoff() -> None:
    result = build_exit_target_dataset(_states(["A", "A", "A"], cutoff="2024-01-03"), horizons=(2,))

    first = result.dataset.iloc[0]
    assert first["censoring_status"] == RIGHT_CENSORED_BY_CUTOFF
    assert pd.isna(first["exit_within_horizon"])
    assert first["target_observation_end_date"] == "2024-01-03"


def test_feature_date_after_trade_date_marks_leakage_violation() -> None:
    states = _states(["A", "A", "A"])
    states.loc[0, "max_feature_date_used"] = pd.Timestamp("2024-01-03")

    result = build_exit_target_dataset(states, horizons=(1,))

    assert bool(result.dataset.iloc[0]["feature_leakage_violation"]) is True
    assert result.summary["feature_leakage_violation_count"] == 1


def test_optional_features_missing_are_reported_but_do_not_fail() -> None:
    result = build_exit_target_dataset(_states(["A", "A", "A"]), horizons=(1,))

    assert result.status == "pass"
    assert "volatility_20d" in result.summary["missing_feature_columns"]
    assert "hmm_state_entropy" in result.summary["missing_feature_columns"]


def test_purge_and_embargo_metadata_are_present() -> None:
    result = build_exit_target_dataset(_states(["A", "A", "A"]), horizons=(1, 2))

    assert result.summary["purge_embargo_policy_present"] is True
    assert result.dataset["purge_group_id"].notna().all()
    assert (
        pd.to_datetime(result.dataset["embargo_until_date"])
        >= pd.to_datetime(result.dataset["target_observation_end_date"])
    ).all()
    assert result.dataset["target_definition_version"].eq(TARGET_DEFINITION_VERSION).all()


def test_cli_writes_markdown_json_and_csv_without_external_fetch(tmp_path: Path) -> None:
    db_path = tmp_path / "target.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE hsmm_state_daily (
              run_id TEXT,
              trade_date DATE,
              sector_code TEXT,
              sector_name TEXT,
              state_id INTEGER,
              state_label TEXT,
              state_phase TEXT,
              state_age_days INTEGER,
              duration_percentile DOUBLE,
              duration_percentile_status TEXT,
              duration_tail_status TEXT,
              max_observation_date_used DATE,
              state_source TEXT,
              created_at TIMESTAMP
            )
            """
        )
        con.execute(
            """
            INSERT INTO hsmm_state_daily VALUES
            ('target_run', '2024-01-02', 'S1', 'Sector', 1, 'A', 'early', 1, 0.1, 'available', 'within_duration_support', '2024-01-02', 'causal_hsmm', '2024-01-02 00:00:00'),
            ('target_run', '2024-01-03', 'S1', 'Sector', 2, 'B', 'early', 2, 0.2, 'available', 'within_duration_support', '2024-01-03', 'causal_hsmm', '2024-01-03 00:00:00'),
            ('target_run', '2024-01-04', 'S1', 'Sector', 2, 'B', 'mature', 3, 0.3, 'available', 'within_duration_support', '2024-01-04', 'causal_hsmm', '2024-01-04 00:00:00')
            """
        )

    output = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    csv_path = tmp_path / "sample.csv"
    exit_code = run_cli(
        Namespace(
            db=str(db_path),
            run_id="latest",
            output=str(output),
            summary_json=str(summary_json),
            dataset_csv=str(csv_path),
            horizons="1,3",
            no_fetch=True,
        )
    )

    assert exit_code == 0
    assert output.exists()
    assert summary_json.exists()
    assert csv_path.exists()
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "pass"
    assert summary["external_data_fetch"] == "no"
    assert summary["row_count"] > 0
    assert summary["purge_embargo_policy_present"] is True
