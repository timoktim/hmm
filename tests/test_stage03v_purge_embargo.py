from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_target_controls import build_purge_embargo_fold_plan, default_purge_embargo_policy


def _row(
    idx: int,
    *,
    trade_date: str,
    target_start: str | None = None,
    target_end: str | None = None,
    entity_id: str = "industry:A",
    status: str = "labeled",
    split_role: str = "historical_development",
    target_usage: str = "eligible",
) -> dict[str, object]:
    start = target_start or trade_date
    end = target_end or trade_date
    return {
        "trade_date": trade_date,
        "entity_id": entity_id,
        "sector_name": entity_id,
        "split_role": split_role,
        "target_usage": target_usage,
        "horizon": 2,
        "threshold_type": "fixed",
        "threshold_value": 0.05,
        "target_kind": "downside_event",
        "target_observation_start_date": start,
        "target_observation_end_date": end,
        "future_return": -0.01,
        "future_mae": -0.01,
        "future_mdd": 0.01,
        "future_realized_vol": 0.0,
        "future_downside_vol": 0.0,
        "event_label": False if status == "labeled" else None,
        "censoring_status": status,
        "exclusion_reason": None,
        "sample_weight": 1.0 if status == "labeled" else 0.0,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "created_at": "2026-06-10T00:00:00+00:00",
        "row_marker": idx,
    }


def _rows_for_dates(dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            _row(
                idx,
                trade_date=value,
                target_start=value,
                target_end=pd.Timestamp(value).date().isoformat(),
            )
            for idx, value in enumerate(dates)
        ]
    )


def test_purge_removes_training_rows_whose_target_interval_overlaps_validation() -> None:
    rows = pd.DataFrame(
        [
            _row(0, trade_date="2026-01-01", target_start="2026-01-02", target_end="2026-01-02"),
            _row(1, trade_date="2026-01-02", target_start="2026-01-03", target_end="2026-01-06"),
            _row(2, trade_date="2026-01-03", target_start="2026-01-04", target_end="2026-01-04"),
            _row(3, trade_date="2026-01-04", target_start="2026-01-05", target_end="2026-01-05"),
            _row(4, trade_date="2026-01-05", target_start="2026-01-06", target_end="2026-01-06"),
            _row(5, trade_date="2026-01-06", target_start="2026-01-07", target_end="2026-01-07"),
        ]
    )

    plan = build_purge_embargo_fold_plan(rows, policy={**default_purge_embargo_policy(), "embargo_days": 1}, fold_count=1)
    fold = plan["folds"][0]
    purged_ids = {item["row_id"] for item in fold["row_assignments"] if item["assignment"] == "purged"}

    assert 1 in purged_ids
    assert plan["purge_violation_count"] == 0


def test_embargo_removes_training_rows_after_validation_interval() -> None:
    rows = _rows_for_dates(
        [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
            "2026-01-09",
        ]
    )

    plan = build_purge_embargo_fold_plan(rows, policy={**default_purge_embargo_policy(), "embargo_days": 2}, fold_count=2)
    first_fold = plan["folds"][0]
    embargoed_dates = {
        item["trade_date"] for item in first_fold["row_assignments"] if item["assignment"] == "embargoed"
    }

    assert {"2026-01-07", "2026-01-08"}.issubset(embargoed_dates)
    assert plan["embargo_violation_count"] == 0


def test_fold_plan_boundaries_are_deterministic() -> None:
    rows = _rows_for_dates(
        [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ]
    )

    first = build_purge_embargo_fold_plan(rows, policy=default_purge_embargo_policy(), fold_count=2)
    second = build_purge_embargo_fold_plan(rows, policy=default_purge_embargo_policy(), fold_count=2)

    assert first["folds"] == second["folds"]
    assert first["fold_count"] == 2
    assert first["purge_violation_count"] == 0
    assert first["embargo_violation_count"] == 0


def test_validation_rows_are_not_from_prospective_final_holdout() -> None:
    rows = pd.concat(
        [
            _rows_for_dates(["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04"]),
            pd.DataFrame(
                [
                    _row(
                        99,
                        trade_date="2026-06-11",
                        target_start="2026-06-12",
                        target_end="2026-06-15",
                        split_role="prospective_final_holdout",
                        status="excluded",
                    )
                ]
            ),
        ],
        ignore_index=True,
    )

    plan = build_purge_embargo_fold_plan(rows, policy=default_purge_embargo_policy(), fold_count=1)
    validation_assignments = [
        item for item in plan["folds"][0]["row_assignments"] if item["assignment"] == "validation"
    ]

    assert all(item["trade_date"] < "2026-06-11" for item in validation_assignments)
    assert plan["prospective_holdout_label_consumed_count"] == 0


def test_purged_and_embargoed_rows_record_reasons() -> None:
    rows = _rows_for_dates(
        [
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
            "2026-01-06",
            "2026-01-07",
            "2026-01-08",
        ]
    )

    plan = build_purge_embargo_fold_plan(rows, policy={**default_purge_embargo_policy(), "embargo_days": 2}, fold_count=2)
    reasoned = [
        item
        for fold in plan["folds"]
        for item in fold["row_assignments"]
        if item["assignment"] in {"purged", "embargoed"}
    ]

    assert reasoned
    assert all(item["reason"] for item in reasoned)
