from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

from src.evaluation.stage04_split_registry import (
    EXPECTED_HORIZONS,
    _forbidden_output_hits,
    build_split_registry,
    evaluate_prospective_holdout_candidate,
    run_cli,
)


ROOT = Path(__file__).resolve().parents[1]
FROZEN_COMMIT = "b90acf351826bc200130b0c94a8f156ea51cff5a"


def _registry() -> dict:
    return build_split_registry(
        root=ROOT,
        frozen_stage03r_commit=FROZEN_COMMIT,
        stage03r_final_gate_path=ROOT / "reports/stage03r/stage03r_final_gate_report.json",
        data_quality_path=ROOT / "reports/stage03r/data_quality_ci_report.json",
    )


def _complete_candidate(**updates: object) -> dict:
    candidate = {
        "holdout_start_date": "2026-05-29",
        "label_completeness_by_horizon": {str(horizon): True for horizon in EXPECTED_HORIZONS},
        "consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retrained_in_locked_evaluation_path": "no",
        "HSMM_p_exit_used_for_decision": "no",
        "final_holdout_consumed": "no",
    }
    candidate.update(updates)
    return candidate


def test_registry_freezes_stage03r_boundary_from_accepted_artifacts() -> None:
    registry = _registry()

    assert registry["index_id"] == "STAGE04-WP0"
    assert registry["frozen_stage03r_commit"] == FROZEN_COMMIT
    assert registry["evidence_cutoff_date"] == "2026-05-28"
    assert registry["max_reconstructed_validation_end_date"] == "2026-05-28"
    assert registry["stage03r_final_gate"]["engineering_gate_verdict"] == "PASS"
    assert registry["stage03r_final_gate"]["empirical_promotion_verdict"] == "DEFER"
    assert registry["stage03r_final_gate_verdict"] == "DEFER"
    assert registry["engineering_gate_verdict"] == "PASS"
    assert registry["empirical_promotion_verdict"] == "DEFER"
    assert registry["future_holdout_start_rule"] == "strictly_after_evidence_cutoff_date"
    assert registry["expected_horizons"] == EXPECTED_HORIZONS
    assert registry["max_label_horizon"] == 20
    assert registry["final_holdout_consumption_count"] == 0
    assert registry["threshold_tuning_after_lock"] == "forbidden"
    assert registry["model_retraining_after_lock"] == "forbidden"
    assert registry["HMM_HSMM_retraining_after_lock"] == "forbidden"
    assert registry["HSMM_p_exit_used_for_decision"] == "no"
    assert registry["private_db_required_in_ci"] == "no"
    assert registry["future_holdout_policy"]["final_holdout_consumed_in_wp0"] == "no"
    assert registry["boundary_flags"]["final_holdout_consumed"] == "no"
    assert registry["boundary_flags"]["final_holdout_consumption_count"] == 0


def test_holdout_cannot_overlap_stage03r_evidence_window() -> None:
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(holdout_start_date="2026-05-28"),
    )

    assert result["status"] == "blocked"
    assert any("strictly after evidence_cutoff_date" in issue for issue in result["blocking_issues"])


def test_consumption_count_greater_than_one_blocks() -> None:
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(consumption_count=2),
    )

    assert result["status"] == "blocked"
    assert any("consumption count exceeds one" in issue for issue in result["blocking_issues"])


def test_threshold_tuning_after_lock_blocks() -> None:
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(threshold_tuning_after_lock="yes"),
    )

    assert result["status"] == "blocked"
    assert any("threshold tuning after split lock" in issue for issue in result["blocking_issues"])


def test_hsmm_p_exit_decision_usage_blocks() -> None:
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(HSMM_p_exit_used_for_decision="yes"),
    )

    assert result["status"] == "blocked"
    assert any("HSMM p_exit" in issue for issue in result["blocking_issues"])


def test_missing_label_completeness_defers() -> None:
    labels = {str(horizon): True for horizon in EXPECTED_HORIZONS}
    labels["20"] = False
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(label_completeness_by_horizon=labels),
    )

    assert result["status"] == "defer"
    assert any("labels are incomplete" in reason for reason in result["defer_reasons"])


def test_no_decision_or_trading_outputs_are_produced() -> None:
    registry = _registry()
    result = evaluate_prospective_holdout_candidate(registry, _complete_candidate())

    assert _forbidden_output_hits(registry) == []
    assert result["status"] == "eligible"
    assert result["decision_surface_output"] == "no"
    assert result["trading_output"] == "no"


def test_forbidden_candidate_output_terms_block() -> None:
    result = evaluate_prospective_holdout_candidate(
        _registry(),
        _complete_candidate(sell_signal="never emit this"),
    )

    assert result["status"] == "blocked"
    assert any("forbidden" in issue for issue in result["blocking_issues"])


def test_cli_writes_registry_reports_and_committed_ledger_template(tmp_path: Path) -> None:
    output = tmp_path / "split_registry.md"
    summary_json = tmp_path / "split_registry.json"
    ledger_template = tmp_path / "prospective_validation_ledger.template.jsonl"

    exit_code = run_cli(
        Namespace(
            root=str(ROOT),
            frozen_stage03r_commit=FROZEN_COMMIT,
            stage03r_final_gate=str(ROOT / "reports/stage03r/stage03r_final_gate_report.json"),
            data_quality=str(ROOT / "reports/stage03r/data_quality_ci_report.json"),
            output=str(output),
            summary_json=str(summary_json),
            ledger_template=str(ledger_template),
            no_fetch=True,
        )
    )
    registry = json.loads(summary_json.read_text(encoding="utf-8"))
    ledger_record = json.loads(ledger_template.read_text(encoding="utf-8").strip())

    assert exit_code == 0
    assert output.exists()
    assert registry["evidence_cutoff_date"] == "2026-05-28"
    assert ledger_record["record_type"] == "template"
    assert ledger_record["final_holdout_consumed"] == "no"
    assert ledger_record["consumption_count"] == 0


def test_no_duckdb_wal_or_private_paths_are_committed() -> None:
    tracked = (ROOT / ".git").exists()
    assert tracked

    import subprocess

    result = subprocess.run(
        ["git", "ls-files"],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=True,
    )
    files = result.stdout.splitlines()

    assert not [path for path in files if path.endswith((".duckdb", ".duckdb.wal", ".wal"))]
    assert not [path for path in files if path.startswith("/Users/") or path.startswith("/private/tmp/")]
