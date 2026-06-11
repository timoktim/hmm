from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation.stage03v_baseline_diagnostics import (
    BASELINE_FAMILIES_REQUIRED,
    HOLDOUT_START,
    build_baseline_diagnostics_report,
    build_price_baseline_features,
    compute_empirical_baseline_scores,
    filter_prospective_holdout_rows,
    slice_specs_from_target_support,
    validate_baseline_policy,
    validate_wp3_preconditions,
)


def _target_row(
    trade_date: str,
    event_label: bool,
    *,
    entity_id: str = "industry:A",
    horizon: int = 5,
    threshold_value: float = 0.05,
    target_end: str | None = None,
) -> dict[str, object]:
    target_end = target_end or trade_date
    return {
        "trade_date": pd.Timestamp(trade_date),
        "entity_id": entity_id,
        "target_usage": "eligible",
        "horizon": horizon,
        "threshold_type": "fixed",
        "threshold_value": threshold_value,
        "target_kind": "downside_event",
        "target_observation_end_date": pd.Timestamp(target_end),
        "future_return": -0.01 if event_label else 0.01,
        "future_mae": -0.06 if event_label else -0.01,
        "future_mdd": 0.06 if event_label else 0.01,
        "event_label": event_label,
        "censoring_status": "labeled",
    }


def _support(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "entity_count_after_silent_break_handling": 124,
        "slice_support_summary": [
            {
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "feasibility_verdict": "eligible",
            }
        ],
    }


def _controls(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "feature_namespace_policy_status": "pass",
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
    }


def _full_audit(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "full_target_rows_checked": 7474840,
        "row_count_delta": 0,
        "violation_count_total": 0,
        "recompute_violation_count_total": 0,
        "slice_support_delta_count": 0,
    }


def _fold_plan(status: str = "pass") -> dict:
    return {
        "status": status,
        "fold_count": 1,
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
        "folds": [
            {
                "fold_id": "fold_1",
                "validation_start_date": "2026-01-04",
                "validation_end_date": "2026-01-05",
            }
        ],
    }


def _policy() -> dict:
    return {
        "index_id": "STAGE03V-WP3-v1",
        "policy_version": "stage03v_baseline_diagnostics_policy_v1",
        "information_cutoff_date": "2026-06-10",
        "holdout_start": "2026-06-11",
        "baseline_families": BASELINE_FAMILIES_REQUIRED,
        "final_holdout_policy": "withheld_not_scored",
        "calibration_policy": "forbidden_in_wp3",
        "readiness_policy": "forbidden_in_wp3",
        "model_training_policy": "forbidden_in_wp3",
    }


def test_empirical_scores_use_training_history_only() -> None:
    train = pd.DataFrame(
        [
            _target_row("2026-01-01", False),
            _target_row("2026-01-02", True),
            _target_row("2026-01-03", True),
        ]
    )
    validation = pd.DataFrame([_target_row("2026-01-04", False), _target_row("2026-01-05", False)])

    scores = compute_empirical_baseline_scores(validation, train, rolling_history_rows=10)

    assert scores["rolling_global_event_rate"].tolist() == pytest.approx([2 / 3, 2 / 3])
    assert scores["expanding_global_event_rate"].tolist() == pytest.approx([2 / 3, 2 / 3])


def test_same_row_label_does_not_change_empirical_score() -> None:
    train = pd.DataFrame([_target_row("2026-01-01", False), _target_row("2026-01-02", True)])
    validation = pd.DataFrame([_target_row("2026-01-03", False)])
    mutated = validation.copy()
    mutated.loc[0, "event_label"] = True

    score_a = compute_empirical_baseline_scores(validation, train)
    score_b = compute_empirical_baseline_scores(mutated, train)

    assert score_a["rolling_global_event_rate"].iloc[0] == score_b["rolling_global_event_rate"].iloc[0]


def test_validation_labels_do_not_influence_training_derived_rates() -> None:
    train = pd.DataFrame([_target_row("2026-01-01", False), _target_row("2026-01-02", False)])
    validation = pd.DataFrame([_target_row("2026-01-03", True), _target_row("2026-01-04", True)])
    mutated = validation.copy()
    mutated["event_label"] = False

    score_a = compute_empirical_baseline_scores(validation, train)
    score_b = compute_empirical_baseline_scores(mutated, train)

    assert score_a["rolling_global_event_rate"].tolist() == score_b["rolling_global_event_rate"].tolist()
    assert score_a["rolling_global_event_rate"].tolist() == [0.0, 0.0]


def test_price_baseline_features_emit_required_families() -> None:
    ohlcv = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 8,
            "trade_date": pd.date_range("2026-01-01", periods=8, freq="D"),
            "open": [100, 101, 102, 103, 104, 105, 106, 107],
            "high": [102, 103, 104, 105, 106, 107, 108, 109],
            "low": [99, 100, 101, 102, 103, 104, 105, 106],
            "close": [101, 102, 103, 104, 105, 106, 107, 108],
        }
    )

    features, availability = build_price_baseline_features(ohlcv)

    assert availability["range_based_availability_status"] == "pass"
    assert "rolling_close_to_close_vol_20" in features.columns
    assert "parkinson_vol_20" in features.columns
    assert "rolling_distance_from_high_20" in features.columns
    assert "continuous_proxy_vol_drawdown_combo" in features.columns


def test_missing_or_failed_wp2_1_report_blocks_wp3() -> None:
    issues = validate_wp3_preconditions(
        target_support=_support(),
        target_controls=_controls(),
        full_target_audit=_full_audit(status="fail"),
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert "wp2_1_full_target_audit_status_not_pass" in issues


def test_policy_contract_validates_required_forbidden_boundaries() -> None:
    assert validate_baseline_policy(_policy()) == []
    bad = _policy()
    bad["readiness_policy"] = "allowed"
    assert "readiness_policy_not_forbidden_in_wp3" in validate_baseline_policy(bad)


def test_prospective_holdout_rows_are_withheld() -> None:
    rows = pd.DataFrame(
        [
            _target_row("2026-06-10", False),
            _target_row(HOLDOUT_START, True),
        ]
    )

    filtered, withheld = filter_prospective_holdout_rows(rows)

    assert withheld == 1
    assert filtered["trade_date"].max() < pd.Timestamp(HOLDOUT_START)


def test_slice_specs_from_target_support() -> None:
    specs = slice_specs_from_target_support(_support())

    assert len(specs) == 1
    assert specs[0].horizon == 5
    assert specs[0].target_usage == "eligible"


def test_missing_v7_db_returns_blocked_without_old_db_fallback(tmp_path: Path) -> None:
    report = build_baseline_diagnostics_report(
        db_path=tmp_path / "missing_v7.duckdb",
        output=tmp_path / "missing.md",
        summary_json=tmp_path / "missing.json",
        fold_metrics=tmp_path / "fold.csv",
        slice_metrics=tmp_path / "slice.csv",
        audit_sample=tmp_path / "audit.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["external_data_fetch"] == "no"
    assert json.loads((tmp_path / "missing.json").read_text(encoding="utf-8"))["status"] == "blocked_missing_v7_db"


def test_no_external_fetch_mode_is_enforced(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-fetch"):
        build_baseline_diagnostics_report(
            db_path=tmp_path / "missing_v7.duckdb",
            output=tmp_path / "unused.md",
            summary_json=tmp_path / "unused.json",
            fold_metrics=tmp_path / "fold.csv",
            slice_metrics=tmp_path / "slice.csv",
            audit_sample=tmp_path / "audit.csv",
            no_fetch=False,
        )
