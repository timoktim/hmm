from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.evaluation.stage03v_calibration_readiness import (
    BOUNDARY_FLAGS,
    build_calibration_readiness_report,
    build_readiness_matrix,
    default_policy,
    evaluate_calibration_for_folds,
    fit_calibrator,
    validate_policy,
    validate_wp5_preconditions,
)


def _support(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
    }


def _controls(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
    }


def _baseline(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
    }


def _vol(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
    }


def _logistic(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "fixed_threshold_mainline_status": "unchanged_primary_target",
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
        "training_boundary_violation_counts": {"training_boundary_violation_count_total": 0},
        "boundary_flags": {
            "model_training": "yes",
            "probability_calibration": "no",
            "readiness_assigned": "no",
            "holdout_consumed": "no",
        },
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
                "train_start_date": "2026-01-01",
                "train_end_date": "2026-01-06",
                "validation_start_date": "2026-01-07",
                "validation_end_date": "2026-01-10",
            }
        ],
    }


def _target_rows() -> pd.DataFrame:
    rows = []
    for day in range(10):
        trade_date = pd.Timestamp("2026-01-01") + pd.Timedelta(days=day)
        for entity_idx in range(2):
            label = bool((day + entity_idx) % 2)
            rows.append(
                {
                    "entity_id": f"industry:{entity_idx}",
                    "trade_date": trade_date,
                    "feature_asof_date": trade_date - pd.Timedelta(days=1),
                    "split_role": "historical_development",
                    "target_usage": "eligible",
                    "horizon": 1,
                    "threshold_type": "fixed",
                    "threshold_value": 0.05,
                    "event_label": label,
                    "future_mae": -0.06 if label else -0.01,
                    "future_mdd": 0.06 if label else 0.01,
                    "future_return": -0.02 if label else 0.01,
                    "censoring_status": "labeled",
                    "target_observation_end_date": trade_date + pd.Timedelta(days=1),
                    "rolling_close_to_close_vol_20": 0.01 + 0.02 * int(label) + day * 0.001,
                    "rolling_close_to_close_vol_60": 0.02 + 0.01 * int(label) + day * 0.001,
                }
            )
    return pd.DataFrame(rows)


def _feature_rows() -> pd.DataFrame:
    return _target_rows()[
        [
            "entity_id",
            "trade_date",
            "feature_asof_date",
            "rolling_close_to_close_vol_20",
            "rolling_close_to_close_vol_60",
        ]
    ].copy()


def test_policy_contract_allows_calibration_but_keeps_development_boundaries() -> None:
    policy = default_policy()

    assert validate_policy(policy) == []
    assert "platt_logistic_calibration" in policy["calibration_methods"]
    assert "isotonic_calibration" in policy["calibration_methods"]
    assert BOUNDARY_FLAGS["probability_calibration"] == "yes"
    assert BOUNDARY_FLAGS["readiness_assigned"] == "yes_development_only"
    assert BOUNDARY_FLAGS["holdout_consumed"] == "no"
    assert BOUNDARY_FLAGS["trading_or_decision_output"] == "no"


def test_failed_wp4_report_blocks_wp5() -> None:
    status, issues = validate_wp5_preconditions(
        target_support=_support(),
        target_controls=_controls(),
        full_target_audit=_controls(),
        baseline_diagnostics=_baseline(),
        vol_scaled_sanity=_vol(),
        logistic_hazard=_logistic(status="fail"),
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_wp4_not_ready"
    assert "wp4_status_not_pass" in issues


def test_missing_v7_db_returns_blocked_status_and_no_old_db_fallback(tmp_path: Path) -> None:
    payloads = {
        "support.json": _support(),
        "controls.json": _controls(),
        "full.json": _controls(),
        "baseline.json": _baseline(),
        "vol.json": _vol(),
        "logistic.json": _logistic(),
        "fold.json": _fold_plan(),
        "policy.json": default_policy(),
        "universe.json": {"source": {"v7_coverage_available": "yes"}},
    }
    for name, payload in payloads.items():
        (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")

    report = build_calibration_readiness_report(
        db_path=tmp_path / "missing_v7.duckdb",
        target_support=tmp_path / "support.json",
        target_universe=tmp_path / "universe.json",
        target_controls=tmp_path / "controls.json",
        full_target_audit=tmp_path / "full.json",
        baseline_diagnostics=tmp_path / "baseline.json",
        vol_scaled_sanity=tmp_path / "vol.json",
        logistic_hazard=tmp_path / "logistic.json",
        fold_plan=tmp_path / "fold.json",
        policy=tmp_path / "policy.json",
        output=tmp_path / "out.md",
        summary_json=tmp_path / "out.json",
        fold_metrics=tmp_path / "fold_metrics.csv",
        slice_metrics=tmp_path / "slice_metrics.csv",
        calibration_bins=tmp_path / "bins.csv",
        clustered_inference=tmp_path / "cluster.csv",
        readiness_matrix=tmp_path / "readiness.csv",
        model_manifest=tmp_path / "manifest.json",
        audit_sample=tmp_path / "sample.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["external_data_fetch"] == "no"


def test_insufficient_class_support_skips_calibration_with_reason() -> None:
    calibration = pd.DataFrame({"raw_score": [0.1, 0.2, 0.3], "event_label": [False, False, False]})

    result = fit_calibrator(calibration, method="platt_logistic_calibration", policy=default_policy())

    assert result["status"] == "skipped"
    assert result["skip_reason"] == "insufficient_positive_calibration_events"


def test_evaluate_calibration_emits_readiness_and_no_serialized_models() -> None:
    result = evaluate_calibration_for_folds(
        target_rows=_target_rows(),
        feature_frames={"close_t_minus_1": _feature_rows(), "close_t": _feature_rows()},
        fold_plan=_fold_plan(),
        policy=default_policy(),
        audit_sample_cap=20,
    )

    assert result["evaluation_row_count_total"] > 0
    assert result["leakage_violation_counts"]["leakage_violation_count_total"] == 0
    assert result["calibration_boundary_violation_counts"]["calibration_boundary_violation_count_total"] == 0
    assert result["readiness_matrix"]
    assert result["model_manifest_entries"]
    assert all(row["serialized_model_written"] == "no" for row in result["model_manifest_entries"])


def test_diagnostic_only_slices_do_not_promote_above_research() -> None:
    slice_rows = [
        {
            "asof_mode": "close_t_minus_1",
            "horizon": 5,
            "threshold_type": "fixed",
            "threshold_value": 0.05,
            "target_usage": "diagnostic_only",
            "calibration_method": "platt_logistic_calibration",
            "evaluation_row_count": 1000,
            "positive_event_count": 50,
            "negative_event_count": 950,
            "expected_calibration_error": 0.01,
            "brier_score": 0.04,
            "log_loss": 0.2,
            "roc_auc": 0.8,
            "average_precision": 0.2,
            "fold_count": 3,
        }
    ]

    rows = build_readiness_matrix(slice_rows, [], policy=default_policy(), leakage_total=0)

    assert rows[0]["readiness_category"] == "research_only"
    assert rows[0]["readiness_reason"] == "diagnostic_only_target_usage"
