from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

import src.evaluation.stage03v_target_controls as controls
from src.evaluation.stage03v_risk_target_dataset import SliceSpec
from src.evaluation.stage03v_target_controls import (
    build_target_control_rows,
    build_target_controls_report,
    detect_feature_namespace_violations,
    run_cross_cutoff_regression,
    validate_target_row_invariants,
)


SLICE = SliceSpec(
    horizon=2,
    threshold_value=0.05,
    threshold_type="fixed",
    source_target_kind="sw2021_l2_downside_event",
    feasibility_verdict="eligible",
    target_usage="eligible",
)


def _wp1_support() -> dict:
    return {
        "status": "pass",
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "entity_count_after_silent_break_handling": 124,
        "silent_entity_break_handling": "excluded",
        "permanent_censoring_policy": "cross_cutoff_censored",
        "silent_entity_break_entities": [
            {"entity_id": "industry:break", "handling": "excluded", "reason": "unexplained_gap"}
        ],
        "boundary_flags": {
            "persistent_db_table_written": "no",
            "target_dataset_built": "yes",
            "model_training": "no",
            "probability_calibration": "no",
            "readiness_assigned": "no",
            "holdout_consumed": "no",
            "stage03v2_implemented": "no",
            "stage03v3_implemented": "no",
        },
    }


def _target_universe() -> dict:
    return {
        "source": {
            "db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
            "taxonomy_source_status": "verified_sw2021_l2_tushare_classify",
            "universe_source_status": "verified_sw2021_l2_tushare_classify",
            "v7_coverage_available": "yes",
        },
        "universe": {
            "entity_count_after_silent_break_handling": 124,
            "silent_entity_break_count": 2,
            "silent_entity_break_handling": "excluded",
        },
    }


def _feasibility() -> dict:
    return {
        "fixed_threshold_feasibility_matrix": [
            {
                "horizon": 2,
                "threshold": 0.05,
                "threshold_type": "fixed",
                "target_kind": "sw2021_l2_downside_event",
                "feasibility_verdict": "eligible",
            }
        ]
    }


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def test_target_windows_use_t_plus_1_through_t_plus_n_for_mae() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "close": [100.0, 101.0, 90.0],
        }
    )
    rows = build_target_control_rows(prices, [{**SLICE.__dict__, "horizon": 1}], cutoff_date="2026-01-03")
    jan1 = rows[rows["trade_date"].astype(str).eq("2026-01-01")].iloc[0]

    assert jan1["target_observation_start_date"].isoformat() == "2026-01-02"
    assert jan1["target_observation_end_date"].isoformat() == "2026-01-02"
    assert round(float(jan1["future_mae"]), 6) == 0.01
    assert jan1["event_label"] is False


def test_same_day_price_move_is_not_in_future_mae() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"]),
            "close": [100.0, 50.0, 49.5],
        }
    )
    rows = build_target_control_rows(prices, [{**SLICE.__dict__, "horizon": 1}], cutoff_date="2026-01-03")
    jan2 = rows[rows["trade_date"].astype(str).eq("2026-01-02")].iloc[0]

    assert round(float(jan2["future_mae"]), 6) == round(49.5 / 50.0 - 1.0, 6)
    assert jan2["event_label"] is False


def test_mdd_window_semantics_are_deterministic() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 4,
            "trade_date": pd.date_range("2026-01-01", periods=4, freq="D"),
            "close": [100.0, 110.0, 90.0, 95.0],
        }
    )
    rows = build_target_control_rows(prices, [{**SLICE.__dict__, "horizon": 3}], cutoff_date="2026-01-04")
    first = rows.iloc[0]

    assert round(float(first["future_mdd"]), 6) == round(1.0 - 90.0 / 110.0, 6)
    assert validate_target_row_invariants(rows.head(1), prices)["mdd_window_violation_count"] == 0


def test_labeled_historical_development_rows_do_not_end_after_cutoff() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 5,
            "trade_date": pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"]),
            "close": [100.0, 99.0, 98.0, 70.0, 60.0],
        }
    )
    rows = build_target_control_rows(
        prices,
        [SLICE],
        cutoff_date="2026-06-10",
        trading_calendar=prices["trade_date"],
    )
    counts = validate_target_row_invariants(rows, prices, trading_calendar=prices["trade_date"])

    assert counts["historical_development_bad_label_count"] == 0
    assert rows[rows["trade_date"].astype(str).eq("2026-06-09")].iloc[0]["censoring_status"] == "cross_cutoff_censored"


def test_cross_cutoff_censored_rows_remain_censored_after_append() -> None:
    result = run_cross_cutoff_regression()

    assert result["passed"] is True
    assert result["violation_count"] == 0
    assert result["cross_cutoff_censored_or_excluded_count"] > 0


def test_prospective_final_holdout_rows_are_withheld_and_not_scored() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 4,
            "trade_date": pd.to_datetime(["2026-06-10", "2026-06-11", "2026-06-12", "2026-06-15"]),
            "close": [100.0, 90.0, 80.0, 70.0],
        }
    )
    rows = build_target_control_rows(
        prices,
        [{**SLICE.__dict__, "horizon": 1}],
        cutoff_date="2026-06-10",
        holdout_start="2026-06-11",
        trading_calendar=prices["trade_date"],
        include_prospective=True,
    )
    holdout_rows = rows[rows["split_role"].eq("prospective_final_holdout")]

    assert not holdout_rows.empty
    assert holdout_rows["censoring_status"].eq("excluded").all()
    assert holdout_rows["event_label"].isna().all()
    assert validate_target_row_invariants(rows, prices, trading_calendar=prices["trade_date"])[
        "prospective_holdout_label_consumed_count"
    ] == 0


def test_missing_v7_db_returns_blocked_and_no_fallback_or_formal_policy_write(tmp_path: Path, monkeypatch) -> None:
    support = tmp_path / "support.json"
    universe = tmp_path / "universe.json"
    feasibility = tmp_path / "feasibility.json"
    formal_policy = tmp_path / "formal_policy.yaml"
    monkeypatch.setattr(controls, "DEFAULT_POLICY", formal_policy)
    _write_json(support, _wp1_support())
    _write_json(universe, _target_universe())
    _write_json(feasibility, _feasibility())

    report = build_target_controls_report(
        db_path=tmp_path / "missing_stage03v_v7.duckdb",
        target_support=support,
        target_universe=universe,
        feasibility=feasibility,
        output=tmp_path / "blocked.md",
        summary_json=tmp_path / "blocked.json",
        fold_plan=tmp_path / "blocked_fold.json",
        audit_sample=tmp_path / "blocked_sample.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["source_db_path"] == "missing_stage03v_v7.duckdb"
    assert report["source_db_path"] != "data/db/a_share_hmm.duckdb"
    assert report["boundary_flags"]["external_data_fetch"] == "no"
    assert not formal_policy.exists()


def test_silent_break_entities_remain_excluded_from_control_rows() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:break"] * 3 + ["industry:ok"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"] * 2),
            "close": [100.0, 99.0, 98.0, 100.0, 99.0, 98.0],
        }
    )
    rows = build_target_control_rows(prices, [SLICE], cutoff_date="2026-01-03", excluded_entity_ids={"industry:break"})

    assert set(rows["entity_id"]) == {"industry:ok"}


def test_feature_namespace_policy_detects_future_and_target_collisions() -> None:
    result = detect_feature_namespace_violations(
        ["trade_date", "feature_asof_date", "future_mae", "target_observation_end_date", "target_custom_flag"]
    )

    assert result["feature_namespace_policy_status"] == "fail"
    assert result["future_derived_feature_violation_count"] == 1
    assert result["feature_target_collision_violation_count"] == 3


def test_no_external_fetch_flag_is_hard_boundary(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-fetch only"):
        build_target_controls_report(
            db_path=tmp_path / "missing.duckdb",
            output=tmp_path / "out.md",
            summary_json=tmp_path / "out.json",
            fold_plan=tmp_path / "fold.json",
            audit_sample=tmp_path / "sample.csv",
            no_fetch=False,
        )
