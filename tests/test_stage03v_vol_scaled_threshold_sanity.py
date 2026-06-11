from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation.stage03v_vol_scaled_threshold_sanity import (
    ASOF_MODES,
    BOUNDARY_FLAGS,
    build_vol_scaled_threshold_sanity_report,
    default_policy,
    detect_asof_violations,
    evaluate_vol_scaled_thresholds,
    shifted_price_features,
    threshold_abs_from_daily_vol,
    validate_feature_input_columns,
    validate_policy,
    validate_wp3_5_preconditions,
)


def _validation_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "fold_id": "fold_1",
                "entity_id": "industry:A",
                "trade_date": pd.Timestamp("2026-01-03"),
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "event_label": True,
                "future_mdd": 0.08,
                "future_mae": -0.06,
                "future_return": -0.02,
                "censoring_status": "labeled",
            },
            {
                "fold_id": "fold_1",
                "entity_id": "industry:B",
                "trade_date": pd.Timestamp("2026-01-03"),
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "event_label": False,
                "future_mdd": 0.01,
                "future_mae": -0.01,
                "future_return": 0.02,
                "censoring_status": "labeled",
            },
        ]
    )


def _features() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_id": ["industry:A", "industry:A", "industry:B", "industry:B"],
            "trade_date": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-02", "2026-01-03"]),
            "feature_asof_date": pd.to_datetime(["2026-01-02", "2026-01-03", "2026-01-02", "2026-01-03"]),
            "rolling_close_to_close_vol_20": [0.01, 0.02, 0.01, 0.02],
            "rolling_close_to_close_vol_60": [0.01, 0.02, 0.01, 0.02],
            "ewma_close_to_close_vol": [0.01, 0.02, 0.01, 0.02],
        }
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
        "boundary_flags": {
            "external_data_fetch": "no",
            "model_training": "no",
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
                "validation_start_date": "2026-01-03",
                "validation_end_date": "2026-01-03",
            }
        ],
    }


def test_threshold_formula_uses_daily_vol_and_clamps() -> None:
    values = threshold_abs_from_daily_vol([0.001, 0.02, 0.20], horizon=5, k_value=2.0)

    assert values.iloc[0] == pytest.approx(0.02)
    assert values.iloc[1] == pytest.approx(0.02 * (5**0.5) * 2.0)
    assert values.iloc[2] == pytest.approx(0.15)


def test_annualized_volatility_is_converted_before_horizon_scaling() -> None:
    annualized = 0.20
    daily = annualized / (252**0.5)

    converted = threshold_abs_from_daily_vol(
        [annualized],
        horizon=10,
        k_value=1.5,
        input_is_annualized=True,
    ).iloc[0]

    assert converted == pytest.approx(max(0.02, daily * (10**0.5) * 1.5))


def test_close_t_minus_1_mode_excludes_same_date_price_information() -> None:
    shifted = shifted_price_features(_features(), asof_mode="close_t_minus_1")
    row = shifted[
        shifted["entity_id"].eq("industry:A")
        & shifted["trade_date"].eq(pd.Timestamp("2026-01-03"))
    ].iloc[0]

    assert row["feature_asof_date"] == pd.Timestamp("2026-01-02")
    assert row["rolling_close_to_close_vol_20"] == pytest.approx(0.01)


def test_vol_scaled_threshold_uses_causal_features_and_not_same_row_label() -> None:
    validation = _validation_rows()
    shifted_validation = validation.copy()
    shifted_validation["event_label"] = ~shifted_validation["event_label"].astype(bool)
    frames = {mode: shifted_price_features(_features(), asof_mode=mode) for mode in ASOF_MODES}

    result_a = evaluate_vol_scaled_thresholds(
        validation_rows=validation,
        feature_frames=frames,
        policy=default_policy(),
    )
    result_b = evaluate_vol_scaled_thresholds(
        validation_rows=shifted_validation,
        feature_frames=frames,
        policy=default_policy(),
    )

    first_a = result_a["rows"][0]
    first_b = result_b["rows"][0]
    assert first_a["vol_scaled_event_count"] == first_b["vol_scaled_event_count"]
    assert result_a["leakage_violation_counts"]["feature_asof_violation_count"] == 0


def test_future_and_target_namespace_columns_are_rejected() -> None:
    result = validate_feature_input_columns(["close", "future_mae", "event_label", "target_observation_end_date"])

    assert result["future_column_input_violation_count"] == 1
    assert result["target_namespace_input_violation_count"] == 3


def test_feature_asof_violations_detect_close_t_minus_1_same_date() -> None:
    rows = pd.DataFrame(
        [
            {"trade_date": "2026-01-03", "feature_asof_date": "2026-01-02"},
            {"trade_date": "2026-01-03", "feature_asof_date": "2026-01-03"},
        ]
    )

    assert detect_asof_violations(rows, asof_mode="close_t_minus_1") == 1


def test_missing_or_failed_wp3_report_blocks_wp3_5() -> None:
    status, issues = validate_wp3_5_preconditions(
        target_support=_support(),
        target_controls=_controls(),
        full_target_audit=_full_audit(),
        baseline_report=_baseline_report(status="fail"),
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "blocked_wp3_not_ready"
    assert "wp3_baseline_diagnostics_status_not_pass" in issues


def test_policy_contract_forbids_training_calibration_and_readiness() -> None:
    policy = default_policy()
    assert validate_policy(policy) == []
    policy["model_training_policy"] = "allowed"
    assert "model_training_policy_not_forbidden_in_wp3_5" in validate_policy(policy)


def test_missing_v7_db_returns_blocked_status_and_no_old_db_fallback(tmp_path: Path) -> None:
    support = tmp_path / "support.json"
    controls = tmp_path / "controls.json"
    full_audit = tmp_path / "full_audit.json"
    baseline_report = tmp_path / "baseline_report.json"
    for path, payload in [
        (support, _support()),
        (controls, _controls()),
        (full_audit, _full_audit()),
        (baseline_report, _baseline_report()),
    ]:
        path.write_text(json.dumps(payload), encoding="utf-8")

    report = build_vol_scaled_threshold_sanity_report(
        db_path=tmp_path / "missing_v7.duckdb",
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        baseline_report=baseline_report,
        output=tmp_path / "missing.md",
        summary_json=tmp_path / "missing.json",
        vol_scaled_summary=tmp_path / "vol.csv",
        metric_audit=tmp_path / "metric.csv",
        asof_shift_summary=tmp_path / "asof.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["old_db_fallback"] is False
    assert report["boundary_flags"] == BOUNDARY_FLAGS


def test_no_fetch_false_is_rejected() -> None:
    with pytest.raises(ValueError, match="no-fetch"):
        build_vol_scaled_threshold_sanity_report(no_fetch=False)
