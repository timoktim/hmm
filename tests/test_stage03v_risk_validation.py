from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.evaluation import stage03v_risk_validation as rv


def _stage_doc(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
    }


def _wp5_doc(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "fixed_threshold_mainline_status": "unchanged_primary_target",
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "calibration_boundary_violation_counts": {"calibration_boundary_violation_count_total": 0},
            "boundary_flags": {
                "probability_calibration": "yes",
                "readiness_assigned": "yes_development_only",
                "trading_or_decision_output": "no",
                "holdout_consumed": "no",
            },
        }
    )
    return doc


def _fold_plan() -> dict:
    return {"status": "pass", "fold_count": 3, "purge_violation_count": 0, "embargo_violation_count": 0}


def _readiness_rows() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "asof_mode": "close_t_minus_1",
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_usage": "eligible",
                "calibration_method": "platt_logistic_calibration",
                "readiness_category": "usable_probability_candidate",
                "development_only": "yes",
                "evaluation_row_count": 900,
                "positive_event_count": 40,
                "negative_event_count": 860,
                "mean_brier_score": 0.03,
                "mean_log_loss": 0.12,
                "mean_expected_calibration_error": 0.02,
                "max_expected_calibration_error": 0.03,
                "mean_auc": 0.72,
                "mean_average_precision": 0.22,
                "clustered_uncertainty_width": 0.10,
                "fold_count": 3,
                "readiness_reason": "development_calibration_gate_pass",
            },
            {
                "asof_mode": "close_t_minus_1",
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.08,
                "target_usage": "eligible",
                "calibration_method": "platt_logistic_calibration",
                "readiness_category": "ordinal_only_candidate",
                "development_only": "yes",
                "evaluation_row_count": 600,
                "positive_event_count": 12,
                "negative_event_count": 588,
                "mean_brier_score": 0.04,
                "mean_log_loss": 0.18,
                "mean_expected_calibration_error": 0.08,
                "max_expected_calibration_error": 0.10,
                "mean_auc": 0.62,
                "mean_average_precision": 0.14,
                "clustered_uncertainty_width": 0.20,
                "fold_count": 3,
                "readiness_reason": "ranking_retained_but_probability_gate_not_met",
            },
            {
                "asof_mode": "close_t_minus_1",
                "horizon": 5,
                "threshold_type": "fixed",
                "threshold_value": 0.10,
                "target_usage": "diagnostic_only",
                "calibration_method": "platt_logistic_calibration",
                "readiness_category": "research_only",
                "development_only": "yes",
                "evaluation_row_count": 500,
                "positive_event_count": 20,
                "negative_event_count": 480,
                "mean_brier_score": 0.05,
                "mean_log_loss": 0.20,
                "mean_expected_calibration_error": 0.04,
                "max_expected_calibration_error": 0.05,
                "mean_auc": 0.80,
                "mean_average_precision": 0.30,
                "clustered_uncertainty_width": 0.10,
                "fold_count": 3,
                "readiness_reason": "diagnostic_only_target_usage",
            },
        ]
    )


def _bin_rows() -> pd.DataFrame:
    rows = []
    for threshold, positives in [(0.05, 8), (0.08, 4), (0.10, 5)]:
        for bin_index, high, row_count, pos in [(0, 0.5, 100, 2), (1, 1.0, 50, positives)]:
            rows.append(
                {
                    "fold_id": "fold_1",
                    "asof_mode": "close_t_minus_1",
                    "model_variant": "sklearn_logistic_regression_l2_lbfgs",
                    "horizon": 5,
                    "threshold_type": "fixed",
                    "threshold_value": threshold,
                    "target_usage": "diagnostic_only" if threshold == 0.10 else "eligible",
                    "calibration_method": "platt_logistic_calibration",
                    "bin_index": bin_index,
                    "bin_low": high - 0.5,
                    "bin_high": high,
                    "row_count": row_count,
                    "positive_event_count": pos,
                    "mean_score": high - 0.25,
                    "observed_event_rate": pos / row_count,
                    "calibration_gap": 0.0,
                }
            )
    return pd.DataFrame(rows)


def _cluster_rows() -> pd.DataFrame:
    rows = []
    for threshold in [0.05, 0.08, 0.10]:
        for cluster_type, count in [("entity_id", 60), ("trade_date", 4)]:
            rows.append(
                {
                    "fold_id": "fold_1",
                    "asof_mode": "close_t_minus_1",
                    "model_variant": "sklearn_logistic_regression_l2_lbfgs",
                    "horizon": 5,
                    "threshold_type": "fixed",
                    "threshold_value": threshold,
                    "target_usage": "diagnostic_only" if threshold == 0.10 else "eligible",
                    "calibration_method": "platt_logistic_calibration",
                    "cluster_type": cluster_type,
                    "metric_name": "brier_loss",
                    "cluster_count": count,
                    "min_cluster_size": 3,
                    "max_cluster_size": 100,
                    "clustered_metric_mean": 0.04,
                    "clustered_metric_std": 0.01,
                    "bootstrap_or_cluster_se_rows": 0.01,
                    "confidence_interval_low": 0.02,
                    "confidence_interval_high": 0.08,
                    "uncertainty_status": "pass",
                }
            )
    return pd.DataFrame(rows)


def test_policy_contract_and_preconditions_pass_for_wp6_inputs() -> None:
    assert rv.validate_policy(rv.default_policy()) == []
    status, issues = rv.validate_wp6_preconditions(
        target_support=_stage_doc(),
        target_controls=_stage_doc(),
        full_target_audit=_stage_doc(),
        baseline_diagnostics=_stage_doc(),
        vol_scaled_sanity=_stage_doc(),
        logistic_hazard=_stage_doc(),
        calibration_readiness=_wp5_doc(),
        fold_plan=_fold_plan(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert status == "pass"
    assert issues == []


def test_validation_metrics_assign_protocol_statuses_without_holdout() -> None:
    evidence = rv.build_validation_metrics(
        readiness_rows=_readiness_rows(),
        fold_rows=pd.DataFrame(),
        bin_rows=_bin_rows(),
        clustered_rows=_cluster_rows(),
        baseline_report={"metric_summary": {"mean_roc_auc": 0.5, "mean_average_precision": 0.1}},
        vol_report={"metric_sanity_summary": {"metric_sanity_fail_count": 0, "known_high_auc_diagnostic_covered": True}},
        policy=rv.default_policy(),
        leakage_total=0,
        boundary_total=0,
    )
    rows = evidence["metrics"]
    by_threshold = {row["threshold_value"]: row for row in rows}

    assert by_threshold[0.05]["validation_status"] == "validation_pass_candidate"
    assert by_threshold[0.08]["validation_status"] == "validation_watchlist"
    assert by_threshold[0.10]["validation_status"] == "research_only_evidence"
    assert all(row["research_only"] == "yes" for row in rows)
    assert all(row["not_trading_output"] == "yes" for row in rows)


def test_build_report_writes_wp7_manifest_from_aggregate_artifacts(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        rv,
        "read_v7_inputs",
        lambda path: SimpleNamespace(
            coverage={
                "status": "pass",
                "db_opened_read_only": True,
                "v7_coverage_available": "yes",
                "sw2021_l2_universe_coverage": "pass",
            }
        ),
    )
    files = {
        "support": tmp_path / "support.json",
        "controls": tmp_path / "controls.json",
        "full": tmp_path / "full.json",
        "baseline": tmp_path / "baseline.json",
        "vol": tmp_path / "vol.json",
        "logistic": tmp_path / "logistic.json",
        "wp5": tmp_path / "wp5.json",
        "fold": tmp_path / "fold.json",
        "policy": tmp_path / "policy.json",
        "universe": tmp_path / "universe.json",
    }
    for key in ["support", "controls", "full", "baseline", "vol", "logistic"]:
        payload = _stage_doc()
        if key == "baseline":
            payload["metric_summary"] = {"mean_roc_auc": 0.5, "mean_average_precision": 0.1}
        if key == "vol":
            payload["metric_sanity_summary"] = {"metric_sanity_fail_count": 0, "known_high_auc_diagnostic_covered": True}
        files[key].write_text(json.dumps(payload), encoding="utf-8")
    files["wp5"].write_text(json.dumps(_wp5_doc()), encoding="utf-8")
    files["fold"].write_text(json.dumps(_fold_plan()), encoding="utf-8")
    files["policy"].write_text(json.dumps(rv.default_policy()), encoding="utf-8")
    files["universe"].write_text(
        json.dumps(
            {
                "source": {
                    "v7_coverage_available": "yes",
                    "taxonomy_source_status": "verified_sw2021_l2_tushare_classify",
                }
            }
        ),
        encoding="utf-8",
    )
    readiness = tmp_path / "readiness.csv"
    bins = tmp_path / "bins.csv"
    cluster = tmp_path / "cluster.csv"
    folds = tmp_path / "folds.csv"
    slices = tmp_path / "slices.csv"
    _readiness_rows().to_csv(readiness, index=False)
    _bin_rows().to_csv(bins, index=False)
    _cluster_rows().to_csv(cluster, index=False)
    pd.DataFrame({"fold_id": ["fold_1"]}).to_csv(folds, index=False)
    pd.DataFrame({"asof_mode": ["close_t_minus_1"]}).to_csv(slices, index=False)

    report = rv.build_risk_validation_report(
        db_path=Path("data/db/a_share_hmm_tushare_v7.duckdb"),
        target_support=files["support"],
        target_universe=files["universe"],
        target_controls=files["controls"],
        full_target_audit=files["full"],
        baseline_diagnostics=files["baseline"],
        vol_scaled_sanity=files["vol"],
        logistic_hazard=files["logistic"],
        calibration_readiness=files["wp5"],
        calibration_fold_metrics=folds,
        calibration_slice_metrics=slices,
        calibration_bins=bins,
        clustered_inference=cluster,
        readiness_matrix=readiness,
        fold_plan=files["fold"],
        policy=files["policy"],
        protocol_output=tmp_path / "protocol.md",
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        metrics=tmp_path / "metrics.csv",
        downshift_report=tmp_path / "downshift.md",
        downshift_json=tmp_path / "downshift.json",
        candidate_matrix=tmp_path / "candidates.csv",
        clustered_summary=tmp_path / "cluster_summary.csv",
        audit_sample=tmp_path / "audit.csv",
        wp7_manifest=tmp_path / "manifest.json",
        no_fetch=True,
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["prospective_holdout_rows_evaluated"] == 0
    assert manifest["status"] == "prepared_for_wp7"
    assert manifest["wp7_final_gate_executed"] == "no"
    assert manifest["prospective_holdout_rows_evaluated"] == 0
