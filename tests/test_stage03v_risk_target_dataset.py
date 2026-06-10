from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import src.evaluation.stage03v_risk_target_dataset as target_mod
from src.evaluation.stage03v_risk_target_dataset import (
    SliceSpec,
    V7Inputs,
    _slice_specs_from_feasibility,
    _write_target_universe_manifest,
    build_risk_target_report,
    compute_path_target_rows,
    validate_wp0_5_feasibility,
)


def _feasibility_report(status: str = "pass") -> dict:
    return {
        "status": status,
        "eligible_slice_count": 1,
        "diagnostic_only_slice_count": 1,
        "no_usable_probability_assigned": True,
        "sw2021_l2_universe_coverage": "pass",
        "source_coverage": {
            "v7_coverage_available": "yes",
            "v7_db_requirement_status": "pass",
            "sw2021_l2_universe_coverage": "pass",
            "universe_source_status": "verified_sw2021_l2_tushare_classify",
        },
        "fixed_threshold_feasibility_matrix": [
            {
                "horizon": 5,
                "threshold": 0.05,
                "threshold_type": "fixed",
                "target_kind": "sw2021_l2_downside_event",
                "feasibility_verdict": "eligible",
            },
            {
                "horizon": 1,
                "threshold": 0.03,
                "threshold_type": "fixed",
                "target_kind": "sw2021_l2_downside_event",
                "feasibility_verdict": "diagnostic_only",
            },
            {
                "horizon": 5,
                "threshold": 0.10,
                "threshold_type": "fixed",
                "target_kind": "sw2021_l2_downside_event",
                "feasibility_verdict": "drop_threshold",
            },
            {
                "horizon": 10,
                "threshold": 0.05,
                "threshold_type": "vol_scaled",
                "target_kind": "sw2021_l2_downside_event",
                "feasibility_verdict": "defer_threshold",
            },
        ],
    }


def test_wp0_5_precondition_requires_v7_verified_sw2021_l2_pass() -> None:
    assert validate_wp0_5_feasibility(_feasibility_report()) == []

    bad = _feasibility_report()
    bad["source_coverage"]["v7_coverage_available"] = "no"
    assert "v7_coverage_available_not_yes" in validate_wp0_5_feasibility(bad)


def test_slice_specs_use_wp0_5_verdicts_without_promoting_dropped_or_deferred() -> None:
    specs = _slice_specs_from_feasibility(_feasibility_report())

    assert [(item.horizon, item.threshold_value, item.target_usage) for item in specs] == [
        (1, 0.03, "diagnostic_only"),
        (5, 0.05, "eligible"),
    ]


def test_diagnostic_only_slice_rows_remain_diagnostic_only_and_no_usable_probability() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 7,
            "trade_date": pd.date_range("2026-01-01", periods=7, freq="D"),
            "close": [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0],
        }
    )
    rows = compute_path_target_rows(prices, _slice_specs_from_feasibility(_feasibility_report()), cutoff_date="2026-01-07")

    assert set(rows["target_usage"]) == {"eligible", "diagnostic_only"}
    assert "usable_probability" not in rows.columns
    assert rows.loc[rows["target_usage"].eq("diagnostic_only"), "horizon"].eq(1).all()


def test_missing_v7_db_blocks_without_falling_back_to_old_db_when_manifest_path_is_explicit(tmp_path: Path) -> None:
    feasibility = tmp_path / "sample_feasibility_report.json"
    feasibility.write_text(json.dumps(_feasibility_report()), encoding="utf-8")
    output = tmp_path / "risk_event_target_support.md"
    summary = tmp_path / "risk_event_target_support.json"
    sample = tmp_path / "risk_event_target_dataset_sample.csv"
    universe = tmp_path / "stage03v_sw_l2_target_universe_v1.yaml"

    report = build_risk_target_report(
        db_path=tmp_path / "missing_stage03v_v7.duckdb",
        feasibility_path=feasibility,
        output=output,
        summary_json=summary,
        sample_csv=sample,
        target_universe=universe,
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["source_db_path"] == "missing_stage03v_v7.duckdb"
    assert report["source_db_path"] != "data/db/a_share_hmm.duckdb"
    assert report["boundary_flags"]["external_data_fetch"] == "no"
    assert json.loads(summary.read_text(encoding="utf-8"))["status"] == "blocked_missing_v7_db"
    assert report["target_universe_manifest_written"] is True
    assert json.loads(universe.read_text(encoding="utf-8"))["source"]["db_path"] == "missing_stage03v_v7.duckdb"
    assert sample.exists()


def test_missing_v7_db_default_does_not_write_formal_target_universe(tmp_path: Path, monkeypatch) -> None:
    feasibility = tmp_path / "sample_feasibility_report.json"
    feasibility.write_text(json.dumps(_feasibility_report()), encoding="utf-8")
    formal_manifest = tmp_path / "formal_stage03v_sw_l2_target_universe_v1.yaml"
    monkeypatch.setattr(target_mod, "DEFAULT_TARGET_UNIVERSE", formal_manifest)

    report = target_mod.build_risk_target_report(
        db_path=tmp_path / "missing_stage03v_v7.duckdb",
        feasibility_path=feasibility,
        output=tmp_path / "risk_event_target_support.md",
        summary_json=tmp_path / "risk_event_target_support.json",
        sample_csv=tmp_path / "risk_event_target_dataset_sample.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["target_universe_manifest_written"] is False
    assert report["target_universe_manifest_path"] is None
    assert not formal_manifest.exists()


def test_wp0_5_not_ready_blocks_before_db_use(tmp_path: Path) -> None:
    feasibility = tmp_path / "sample_feasibility_report.json"
    feasibility.write_text(json.dumps(_feasibility_report(status="partial")), encoding="utf-8")

    report = build_risk_target_report(
        db_path=tmp_path / "missing_stage03v_v7.duckdb",
        feasibility_path=feasibility,
        output=tmp_path / "out.md",
        summary_json=tmp_path / "out.json",
        sample_csv=tmp_path / "sample.csv",
        target_universe=tmp_path / "universe.yaml",
        no_fetch=True,
    )

    assert report["status"] == "blocked_wp0_5_not_ready"
    assert "status_not_pass" in report["blocking_reasons"]


def test_target_universe_manifest_records_v7_quality_silent_break_and_entity_audit(tmp_path: Path) -> None:
    path = tmp_path / "stage03v_sw_l2_target_universe_v1.yaml"
    report = {
        "created_at": "2026-06-10T00:00:00+00:00",
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "feasibility_report_path": "reports/stage03v/sample_feasibility_report.json",
        "universe_source_status": "verified_sw2021_l2_tushare_classify",
        "v7_coverage_available": "yes",
        "v7_db_requirement_status": "pass",
        "coverage_start": "2014-01-02",
        "coverage_end": "2026-06-09",
        "entity_count_total": 162,
        "entity_count_after_quality_filter": 124,
        "entity_count_after_silent_break_handling": 124,
        "quality_filter_exclusion_count": 38,
        "non_verified_or_non_l2_industry_count": 31,
        "constituent_count_min_observed": 2,
        "constituent_count_filter_status": "partial_low_constituents",
        "short_history_entity_count": 0,
        "silent_entity_break_count": 2,
        "silent_entity_break_handling": "excluded",
        "permanent_censoring_policy": "cross_cutoff_censored",
        "silent_entity_break_entities": [
            {
                "entity_id": "industry:医疗美容",
                "sector_name": "医疗美容",
                "handling": "silent_break_already_excluded_by_quality_filter",
                "reason": "unexplained_price_history_gap_gt_45_calendar_days",
            }
        ],
        "boundary_flags": {"external_data_fetch": "no"},
    }
    v7 = V7Inputs(
        price_frame=pd.DataFrame(),
        universe_frame=pd.DataFrame(
            [
                {
                    "entity_id": "industry:IT服务Ⅱ",
                    "sector_name": "IT服务Ⅱ",
                    "entity_segment_id": "industry:IT服务Ⅱ::segment_1",
                }
            ]
        ),
        exclusions=[
            {
                "entity_id": "industry:医疗美容",
                "sector_name": "医疗美容",
                "reason": "silent_break_already_excluded_by_quality_filter",
            }
        ],
        silent_break_entities=report["silent_entity_break_entities"],
        coverage={},
    )

    _write_target_universe_manifest(path, report, v7)
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["source"]["db_path"] == "data/db/a_share_hmm_tushare_v7.duckdb"
    assert manifest["source"]["v7_coverage_available"] == "yes"
    assert manifest["source"]["taxonomy_source_status"] == "verified_sw2021_l2_tushare_classify"
    assert manifest["source"]["universe_source_status"] == "verified_sw2021_l2_tushare_classify"
    assert manifest["universe"]["entity_count_after_quality_filter"] == 124
    assert manifest["universe"]["entity_count_after_silent_break_handling"] == 124
    assert manifest["universe"]["silent_entity_break_count"] == 2
    assert manifest["quality_filter_summary"]["constituent_count_filter_status"] == "partial_low_constituents"
    assert manifest["quality_filter_summary"]["quality_filter_exclusion_count"] == 38
    assert manifest["silent_entity_break_entities"][0]["entity_id"] == "industry:医疗美容"
    assert manifest["exclusions"][0]["reason"] == "silent_break_already_excluded_by_quality_filter"
    assert manifest["entity_audit_summary"]["entity_count"] == 1
    assert manifest["entities"][0]["entity_id"] == "industry:IT服务Ⅱ"


def test_compute_target_rows_has_required_minimum_columns() -> None:
    rows = compute_path_target_rows(
        pd.DataFrame(
            {
                "entity_id": ["industry:A"] * 3,
                "trade_date": pd.date_range("2026-01-01", periods=3, freq="D"),
                "close": [100.0, 99.0, 98.0],
            }
        ),
        [
            SliceSpec(
                horizon=1,
                threshold_value=0.01,
                threshold_type="fixed",
                source_target_kind="sw2021_l2_downside_event",
                feasibility_verdict="eligible",
                target_usage="eligible",
            )
        ],
        cutoff_date="2026-01-03",
    )

    required = {
        "trade_date",
        "entity_type",
        "entity_id",
        "sector_code",
        "sector_name",
        "taxonomy_provider",
        "taxonomy_version",
        "taxonomy_level",
        "feature_scope_id",
        "universe_id",
        "entity_segment_id",
        "split_role",
        "horizon",
        "threshold_type",
        "threshold_value",
        "target_kind",
        "future_return",
        "future_mae",
        "future_mdd",
        "future_realized_vol",
        "future_downside_vol",
        "event_label",
        "target_observation_end_date",
        "censoring_status",
        "exclusion_reason",
        "sample_weight",
        "target_definition_version",
        "source_db_path",
        "created_at",
    }
    assert required.issubset(rows.columns)
