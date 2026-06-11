from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from src.evaluation import stage03v_final_gate as fg


def _stage_doc(status: str = "pass") -> dict:
    return {
        "status": status,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "prospective_holdout_rows_evaluated": 0,
    }


def _wp0(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update({"information_cutoff_date": "2026-06-10", "holdout_start": "2026-06-11"})
    return doc


def _wp5(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "usable_probability_candidate_count": 4,
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "calibration_boundary_violation_counts": {"calibration_boundary_violation_count_total": 0},
        }
    )
    return doc


def _wp6(status: str = "pass") -> dict:
    doc = _stage_doc(status)
    doc.update(
        {
            "historical_development_only": "yes",
            "validation_pass_candidate_count": 4,
            "downshift_tier_counts": {"research_downshift_candidate": 4},
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "validation_boundary_violation_counts": {"validation_boundary_violation_count_total": 0},
            "boundary_flags": {"trading_or_decision_output": "no"},
        }
    )
    return doc


def _manifest(status: str = "prepared_for_wp7") -> dict:
    return {"status": status, "wp7_final_gate_executed": "no"}


def _ledger() -> dict:
    return {
        "information_cutoff_date": "2026-06-10",
        "holdout_start": "2026-06-11",
        "consumption_count": 0,
    }


def _fake_v7() -> SimpleNamespace:
    return SimpleNamespace(
        coverage={
            "status": "pass",
            "db_opened_read_only": True,
            "v7_coverage_available": "yes",
            "sw2021_l2_universe_coverage": "pass",
        },
        price_frame=pd.DataFrame(
            {
                "sector_id": ["industry:0", "industry:1"],
                "trade_date": [pd.Timestamp("2026-06-09"), pd.Timestamp("2026-06-09")],
                "close": [1.0, 2.0],
            }
        ),
        universe_frame=pd.DataFrame({"entity_id": ["industry:0", "industry:1"]}),
    )


def _write_inputs(tmp_path: Path) -> dict[str, Path]:
    payloads = {
        "scope.json": _wp0(),
        "sample.json": _stage_doc(),
        "target.json": _stage_doc(),
        "controls.json": _stage_doc(),
        "full.json": {**_stage_doc(), "violation_count_total": 0},
        "baseline.json": {**_stage_doc(), "leakage_violation_counts": {"leakage_violation_count_total": 0}},
        "vol.json": {**_stage_doc(), "leakage_violation_counts": {"leakage_violation_count_total": 0}},
        "logistic.json": {
            **_stage_doc(),
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "training_boundary_violation_counts": {"training_boundary_violation_count_total": 0},
        },
        "wp5.json": _wp5(),
        "wp6.json": _wp6(),
        "downshift.json": {"status": "pass"},
        "manifest.json": _manifest(),
        "policy.json": fg.default_policy(),
    }
    paths: dict[str, Path] = {}
    for name, payload in payloads.items():
        path = tmp_path / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        paths[name] = path
    ledger = tmp_path / "ledger.jsonl"
    ledger.write_text(json.dumps(_ledger()) + "\n", encoding="utf-8")
    paths["ledger.jsonl"] = ledger
    return paths


def test_policy_contract_and_preconditions_pass_for_wp7_inputs() -> None:
    assert fg.validate_policy(fg.default_policy()) == []
    docs = {
        "wp0_scope_freeze": _wp0(),
        "wp0_5_sample_feasibility": _stage_doc(),
        "wp1_target_support": _stage_doc(),
        "wp2_target_controls": _stage_doc(),
        "wp2_1_full_target_audit": _stage_doc(),
        "wp3_baseline_diagnostics": _stage_doc(),
        "wp3_5_vol_scaled_sanity": _stage_doc(),
        "wp4_logistic_hazard": _stage_doc(),
        "wp5_calibration_readiness": _wp5(),
        "wp6_risk_validation": _wp6(),
    }
    leakage, boundary = fg.collect_violation_counts(
        full_target_audit={"violation_count_total": 0},
        baseline_diagnostics={"leakage_violation_counts": {"leakage_violation_count_total": 0}},
        vol_scaled_sanity={"leakage_violation_counts": {"leakage_violation_count_total": 0}},
        logistic_hazard={
            "leakage_violation_counts": {"leakage_violation_count_total": 0},
            "training_boundary_violation_counts": {"training_boundary_violation_count_total": 0},
        },
        calibration_readiness=_wp5(),
        risk_validation=_wp6(),
    )
    status, issues = fg.validate_wp7_preconditions(
        docs=docs,
        ledger_template=_ledger(),
        wp7_input_manifest=_manifest(),
        db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        leakage_counts=leakage,
        boundary_counts=boundary,
    )

    assert status == "pass"
    assert issues == []


def test_final_gate_emits_historical_pass_with_prospective_defer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(fg, "read_v7_inputs", lambda path: _fake_v7())
    paths = _write_inputs(tmp_path)

    report = fg.build_final_gate_report(
        db_path=Path("data/db/a_share_hmm_tushare_v7.duckdb"),
        scope_freeze=paths["scope.json"],
        sample_feasibility=paths["sample.json"],
        target_support=paths["target.json"],
        target_controls=paths["controls.json"],
        full_target_audit=paths["full.json"],
        baseline_diagnostics=paths["baseline.json"],
        vol_scaled_sanity=paths["vol.json"],
        logistic_hazard=paths["logistic.json"],
        calibration_readiness=paths["wp5.json"],
        risk_validation=paths["wp6.json"],
        downshift_research=paths["downshift.json"],
        wp7_input_manifest=paths["manifest.json"],
        ledger_template=paths["ledger.jsonl"],
        policy=paths["policy.json"],
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        verdict_json=tmp_path / "verdict.json",
        evidence_matrix=tmp_path / "evidence.csv",
        artifact_manifest=tmp_path / "artifacts.json",
        holdout_status=tmp_path / "holdout.json",
        post_gate_action_plan=tmp_path / "plan.md",
        audit_sample=tmp_path / "audit.csv",
        no_fetch=True,
    )

    manifest = json.loads((tmp_path / "artifacts.json").read_text(encoding="utf-8"))
    verdict = json.loads((tmp_path / "verdict.json").read_text(encoding="utf-8"))
    holdout = json.loads((tmp_path / "holdout.json").read_text(encoding="utf-8"))
    assert report["status"] == "pass"
    assert report["final_gate_verdict"] == "PASS_ENGINEERING_HISTORICAL_DEFER_PROSPECTIVE"
    assert report["decision_support_promotion_gate_status"] == "DEFER"
    assert report["prospective_holdout_rows_evaluated"] == 0
    assert verdict["final_gate_verdict"] == report["final_gate_verdict"]
    assert holdout["prospective_holdout_gate_status"] == "defer_or_insufficient"
    assert manifest["final_gate_executed"] == "yes"
    assert manifest["stage03v2_implemented"] == "no"
    assert manifest["stage03v3_implemented"] == "no"


def test_determine_final_verdict_fails_on_boundary_or_leakage() -> None:
    gates = {
        "engineering_gate_status": "pass",
        "causality_gate_status": "fail",
        "historical_validation_gate_status": "pass",
        "calibration_readiness_gate_status": "pass",
        "risk_validation_gate_status": "pass",
        "decision_support_promotion_gate_status": "DEFER",
    }

    verdict, gate_status, status = fg.determine_final_verdict(
        precondition_status="pass",
        gates=gates,
        leakage_total=1,
        boundary_total=0,
        policy=fg.default_policy(),
    )

    assert verdict == "FAIL_BOUNDARY_OR_LEAKAGE"
    assert gate_status == "failed_boundary_or_leakage"
    assert status == "fail"
