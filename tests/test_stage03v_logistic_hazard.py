from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation.stage03v_logistic_hazard import (
    BOUNDARY_FLAGS,
    MODEL_FEATURE_COLUMNS,
    build_logistic_hazard_report,
    default_policy,
    evaluate_logistic_for_folds,
    fit_logistic_model,
    validate_feature_columns,
    validate_policy,
    validate_wp4_preconditions,
)


def _support(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "entity_count_after_silent_break_handling": 124,
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
    }


def _baseline_report(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
    }


def _vol_scaled_report(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
        "leakage_violation_counts": {"leakage_violation_count_total": 0},
        "wp4_entry_recommendation": "proceed_with_vol_scaled_candidate_tracking",
        "vol_scaled_candidate_count": 48,
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
                "validation_end_date": "2026-01-08",
            }
        ],
    }


def _model_frame(labels: list[bool]) -> pd.DataFrame:
    rows = []
    for idx, label in enumerate(labels):
        rows.append(
            {
                "entity_id": f"industry:{idx % 3}",
                "trade_date": pd.Timestamp("2026-01-01") + pd.Timedelta(days=idx),
                "feature_asof_date": pd.Timestamp("2025-12-31") + pd.Timedelta(days=idx),
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "event_label": label,
                "future_mae": -0.06 if label else -0.01,
                "future_mdd": 0.06 if label else 0.01,
                "future_return": -0.02 if label else 0.01,
                "censoring_status": "labeled",
                "target_observation_end_date": pd.Timestamp("2026-01-02") + pd.Timedelta(days=idx),
                "split_role": "historical_development",
                "rolling_close_to_close_vol_20": 0.01 + 0.01 * int(label) + idx * 0.001,
                "rolling_close_to_close_vol_60": 0.02 + 0.01 * int(label) + idx * 0.001,
            }
        )
    return pd.DataFrame(rows)


def test_policy_contract_forbids_calibration_readiness_holdout_and_fetch() -> None:
    policy = default_policy()

    assert validate_policy(policy) == []
    assert policy["calibration_policy"] == "forbidden_in_wp4"
    assert policy["readiness_policy"] == "forbidden_in_wp4"
    assert policy["final_holdout_policy"] == "withheld_not_scored"
    assert policy["external_fetch_policy"] == "forbidden"
    assert BOUNDARY_FLAGS["model_training"] == "yes"
    assert BOUNDARY_FLAGS["probability_calibration"] == "no"
    assert BOUNDARY_FLAGS["readiness_assigned"] == "no"


def test_missing_or_failed_wp3_5_report_blocks_wp4() -> None:
    status, issues = validate_wp4_preconditions(
        target_support=_support(),
        target_controls=_controls(),
        full_target_audit=_full_audit(),
        baseline_diagnostics=_baseline_report(),
        vol_scaled_sanity=_vol_scaled_report(status="fail"),
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_wp3_5_not_ready"
    assert "wp3_5_vol_scaled_sanity_status_not_pass" in issues


def test_missing_v7_db_returns_blocked_status_and_no_old_db_fallback(tmp_path: Path) -> None:
    paths = {
        "support": tmp_path / "support.json",
        "controls": tmp_path / "controls.json",
        "full": tmp_path / "full.json",
        "baseline": tmp_path / "baseline.json",
        "vol": tmp_path / "vol.json",
        "fold": tmp_path / "fold.json",
        "policy": tmp_path / "policy.json",
        "universe": tmp_path / "universe.json",
    }
    payloads = {
        "support": _support(),
        "controls": _controls(),
        "full": _full_audit(),
        "baseline": _baseline_report(),
        "vol": _vol_scaled_report(),
        "fold": _fold_plan(),
        "policy": default_policy(),
        "universe": {"source": {"v7_coverage_available": "yes"}},
    }
    for key, payload in payloads.items():
        paths[key].write_text(json.dumps(payload), encoding="utf-8")

    report = build_logistic_hazard_report(
        db_path=tmp_path / "missing_v7.duckdb",
        target_support=paths["support"],
        target_universe=paths["universe"],
        target_controls=paths["controls"],
        full_target_audit=paths["full"],
        baseline_diagnostics=paths["baseline"],
        vol_scaled_sanity=paths["vol"],
        fold_plan=paths["fold"],
        policy=paths["policy"],
        output=tmp_path / "out.md",
        summary_json=tmp_path / "out.json",
        fold_metrics=tmp_path / "fold.csv",
        slice_metrics=tmp_path / "slice.csv",
        coefficients=tmp_path / "coef.csv",
        model_manifest=tmp_path / "manifest.json",
        feature_audit=tmp_path / "feature.csv",
        audit_sample=tmp_path / "sample.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["source_db_path"].endswith("missing_v7.duckdb")


def test_future_and_target_namespace_columns_are_rejected() -> None:
    result = validate_feature_columns(["rolling_close_to_close_vol_20", "future_mae", "event_label", "target_observation_end_date"])

    assert result["future_column_input_violation_count"] == 1
    assert result["target_namespace_input_violation_count"] == 3


def test_insufficient_positive_or_negative_class_slice_is_skipped() -> None:
    train = _model_frame([False, False, False, False])
    validation = _model_frame([True, False])

    result = fit_logistic_model(train, validation, ["rolling_close_to_close_vol_20"], default_policy())

    assert result["status"] == "skipped"
    assert result["insufficient_data_reason"] == "insufficient_positive_training_events"


def test_logistic_fit_emits_uncalibrated_scores_and_coefficients() -> None:
    train = _model_frame([False, True, False, True, False, True])
    validation = _model_frame([False, True, False, True])

    result = fit_logistic_model(
        train,
        validation,
        ["rolling_close_to_close_vol_20", "rolling_close_to_close_vol_60"],
        default_policy(),
    )

    assert result["status"] == "fitted"
    assert len(result["scores"]) == len(validation)
    assert len(result["coefficients"]) == 2
    assert all(0.0 <= float(score) <= 1.0 for score in result["scores"])


def test_evaluate_logistic_for_folds_does_not_emit_calibration_or_readiness() -> None:
    target_rows = _model_frame([False, True, False, True, False, True, False, True])
    feature_rows = target_rows[
        [
            "entity_id",
            "trade_date",
            "feature_asof_date",
            "rolling_close_to_close_vol_20",
            "rolling_close_to_close_vol_60",
        ]
    ].copy()
    fold_plan = _fold_plan()

    result = evaluate_logistic_for_folds(
        target_rows=target_rows,
        feature_frames={"close_t_minus_1": feature_rows, "close_t": feature_rows},
        fold_plan=fold_plan,
        policy=default_policy(),
    )

    assert result["fitted_model_count"] > 0
    assert result["leakage_violation_counts"]["prospective_holdout_score_count"] == 0
    assert all(entry["probability_calibration"] == "no" for entry in result["model_manifest_entries"])
    assert all(entry["readiness_assigned"] == "no" for entry in result["model_manifest_entries"])
    assert set(result["feature_columns"]).issubset(set(MODEL_FEATURE_COLUMNS))
