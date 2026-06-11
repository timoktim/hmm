from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_vol_scaled_threshold_sanity import (
    ASOF_MODES,
    audit_baseline_metrics,
    build_asof_shift_summary,
    default_policy,
    shifted_price_features,
)


def _validation_rows(*, concentrated: bool = False) -> pd.DataFrame:
    rows = []
    for idx in range(20):
        positive = idx < 6
        rows.append(
            {
                "fold_id": "fold_1",
                "entity_id": "industry:A" if concentrated and positive else f"industry:{idx % 5}",
                "trade_date": pd.Timestamp("2026-01-03" if concentrated and positive else f"2026-01-{idx + 1:02d}"),
                "horizon": 1,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "diagnostic_only",
                "event_label": positive,
                "future_mdd": 0.06 if positive else 0.01,
                "future_mae": -0.06 if positive else -0.01,
                "future_return": -0.02 if positive else 0.02,
                "censoring_status": "labeled",
            }
        )
    return pd.DataFrame(rows)


def _feature_frames() -> dict[str, pd.DataFrame]:
    base = pd.DataFrame(
        {
            "entity_id": [f"industry:{idx % 5}" for idx in range(40)],
            "trade_date": pd.date_range("2026-01-01", periods=40, freq="D"),
            "feature_asof_date": pd.date_range("2026-01-01", periods=40, freq="D"),
            "rolling_close_to_close_vol_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rolling_close_to_close_vol_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "ewma_close_to_close_vol": [0.015 + idx * 0.0001 for idx in range(40)],
            "rolling_downside_vol_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rolling_downside_vol_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "parkinson_vol_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "parkinson_vol_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "garman_klass_vol_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "garman_klass_vol_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "rogers_satchell_vol_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rogers_satchell_vol_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "intraday_range_ratio_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rolling_max_drawdown_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rolling_max_drawdown_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "rolling_distance_from_high_20": [0.01 + idx * 0.0001 for idx in range(40)],
            "rolling_distance_from_high_60": [0.02 + idx * 0.0001 for idx in range(40)],
            "continuous_proxy_vol_drawdown_combo": [0.02 + idx * 0.0001 for idx in range(40)],
        }
    )
    return {mode: shifted_price_features(base, asof_mode=mode) for mode in ASOF_MODES}


def _metric_row(**updates: object) -> dict[str, object]:
    row: dict[str, object] = {
        "fold_id": "fold_1",
        "horizon": 1,
        "threshold_type": "fixed",
        "threshold_value": 0.05,
        "target_usage": "diagnostic_only",
        "baseline_family": "realized_volatility",
        "baseline_name": "rolling_close_to_close_vol_60",
        "row_count": 20,
        "scored_row_count": 20,
        "positive_event_count": 1,
        "event_base_rate": 0.0005,
        "score_available_rate": 1.0,
        "roc_auc": 0.9939857845817387,
        "average_precision": 0.08,
        "spearman_score_vs_future_mdd": 0.04,
    }
    row.update(updates)
    return row


def _baseline_report() -> dict:
    return {
        "best_baseline_by_auc": {
            "baseline_name": "rolling_close_to_close_vol_60",
            "baseline_family": "realized_volatility",
            "metric": "roc_auc",
            "value": 0.9939857845817387,
            "horizon": 1,
            "threshold_value": 0.05,
            "target_usage": "diagnostic_only",
        }
    }


def test_known_high_auc_diagnostic_metric_is_covered_and_explained_by_imbalance() -> None:
    fold_metrics = pd.DataFrame([_metric_row()])
    slice_metrics = pd.DataFrame([_metric_row(fold_id=None)])

    result = audit_baseline_metrics(
        baseline_report=_baseline_report(),
        fold_metrics=fold_metrics,
        slice_metrics=slice_metrics,
        validation_rows=_validation_rows(),
        feature_frames=_feature_frames(),
        policy=default_policy(),
        audit_cap=20,
    )

    assert result["summary"]["known_high_auc_diagnostic_covered"] is True
    assert result["summary"]["known_high_auc_artifact_reason"] == "explained_by_threshold_or_event_imbalance"
    assert any(row["baseline_name"] == "rolling_close_to_close_vol_60" for row in result["rows"])


def test_low_positive_event_support_triggers_artifact_warning() -> None:
    result = audit_baseline_metrics(
        baseline_report={},
        fold_metrics=pd.DataFrame([_metric_row(roc_auc=0.91, positive_event_count=2, event_base_rate=0.01)]),
        slice_metrics=pd.DataFrame([]),
        validation_rows=_validation_rows(),
        feature_frames=_feature_frames(),
        policy=default_policy(),
        audit_cap=20,
    )

    assert result["summary"]["low_support_flag_count"] >= 1
    assert result["rows"][0]["artifact_reason"] == "explained_by_threshold_or_event_imbalance"


def test_single_date_or_entity_concentration_triggers_sample_structure_warning() -> None:
    result = audit_baseline_metrics(
        baseline_report={},
        fold_metrics=pd.DataFrame([_metric_row(positive_event_count=6, event_base_rate=0.30, roc_auc=0.95)]),
        slice_metrics=pd.DataFrame([]),
        validation_rows=_validation_rows(concentrated=True),
        feature_frames=_feature_frames(),
        policy=default_policy(),
        audit_cap=20,
    )

    assert result["summary"]["concentration_warning_count"] >= 1
    assert result["rows"][0]["artifact_reason"] == "explained_by_sample_or_slice_structure"


def test_asof_shift_summary_reports_metric_delta_or_deferred_reason() -> None:
    vol_rows = [
        {
            "asof_mode": "close_t",
            "candidate_name": "rolling_close_to_close_vol_20__h1__k1_0",
            "fold_id": "fold_1",
            "horizon": 1,
            "source_threshold_type": "fixed",
            "source_threshold_value": 0.05,
            "target_usage": "diagnostic_only",
            "event_base_rate": 0.20,
            "row_count": 20,
            "positive_event_count": 4,
            "score_available_rate": 1.0,
        },
        {
            "asof_mode": "close_t_minus_1",
            "candidate_name": "rolling_close_to_close_vol_20__h1__k1_0",
            "fold_id": "fold_1",
            "horizon": 1,
            "source_threshold_type": "fixed",
            "source_threshold_value": 0.05,
            "target_usage": "diagnostic_only",
            "event_base_rate": 0.10,
            "row_count": 20,
            "positive_event_count": 2,
            "score_available_rate": 1.0,
        },
    ]

    result = build_asof_shift_summary(
        vol_rows=vol_rows,
        validation_rows=_validation_rows(),
        feature_frames=_feature_frames(),
        policy=default_policy(),
    )

    vol_delta_rows = [row for row in result["rows"] if row["source"] == "volatility_scaled_threshold"]
    assert vol_delta_rows[0]["metric_delta"] == 0.10
    assert vol_delta_rows[0]["material_degradation_flag"] is True
    assert result["summary"]["asof_shift_row_count"] >= 1
