from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from typing import Any

from src.evaluation.risk_validation_protocol import (
    FORBIDDEN_PROTOCOL_TERMS,
    HSMM_DIAGNOSTIC_COUNT_FIELD,
    HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
    LEGACY_HSMM_COMPARISON_FIELD,
    build_report_markdown,
    evaluate_risk_validation_protocol,
    run_cli,
)


ROOT = Path(__file__).resolve().parents[1]


def _actual_hazard_readiness() -> dict[str, Any]:
    return json.loads((ROOT / "reports/stage03r/hazard_readiness_matrix_report.json").read_text(encoding="utf-8"))


def _actual_hazard_vs_hsmm() -> dict[str, Any]:
    return json.loads((ROOT / "reports/stage03r/hazard_vs_hsmm_report.json").read_text(encoding="utf-8"))


def _actual_verdict_text() -> str:
    return (ROOT / "reports/stage03r/multi_horizon_hazard_verdict.md").read_text(encoding="utf-8")


def _summary() -> dict[str, Any]:
    return evaluate_risk_validation_protocol(
        hazard_readiness=_actual_hazard_readiness(),
        hazard_vs_hsmm=_actual_hazard_vs_hsmm(),
        hazard_verdict_text=_actual_verdict_text(),
        db_path=None,
    ).to_summary()


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def test_hsmm_lifecycle_probability_status_is_diagnostic_only_namespace() -> None:
    hazard_vs_hsmm = _actual_hazard_vs_hsmm()
    hazard_vs_hsmm["hazard_vs_hsmm_by_horizon"] = [
        {
            "horizon_days": 1,
            LEGACY_HSMM_COMPARISON_FIELD: {
                "usable_probability": 10,
                "raw_only": 5,
                "ordinal_only": 20,
            },
        }
    ]
    summary = evaluate_risk_validation_protocol(
        hazard_readiness=_actual_hazard_readiness(),
        hazard_vs_hsmm=hazard_vs_hsmm,
        hazard_verdict_text=_actual_verdict_text(),
    ).to_summary()
    cleanup = summary["semantic_cleanup_summary"]

    assert cleanup["hsmm_lifecycle_probability_status_policy"] == HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY
    assert cleanup["diagnostic_count_field"] == HSMM_DIAGNOSTIC_COUNT_FIELD
    assert cleanup["legacy_ambiguous_comparison_field_present_in_input"] == "yes"
    assert cleanup["hsmm_lifecycle_probability_status_counts_diagnostic_only_by_horizon"]["1"] == {
        "usable_probability": 10,
        "raw_only": 5,
        "ordinal_only": 20,
    }


def test_no_unqualified_hsmm_probability_status_counts_key_remains() -> None:
    summary = _summary()

    assert LEGACY_HSMM_COMPARISON_FIELD not in _walk_keys(summary)


def test_actual_hsmm_status_labels_are_under_diagnostic_only_field() -> None:
    summary = _summary()
    cleanup = summary["semantic_cleanup_summary"]

    assert cleanup["hsmm_lifecycle_probability_status_counts_diagnostic_only_by_horizon"]
    assert cleanup["diagnostic_count_field"].endswith("_diagnostic_only")
    assert cleanup["unqualified_hsmm_lifecycle_status_in_protocol_summary"] == "no"


def test_protocol_json_includes_required_policy_and_boundary_flags() -> None:
    summary = _summary()

    assert summary["semantic_cleanup_summary"]["hsmm_lifecycle_probability_status_policy"] == (
        "diagnostic_only_not_decision_input"
    )
    assert summary["boundary_flags"]["HSMM_p_exit_used_for_decision"] == "no"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"


def test_protocol_preserves_hazard_readiness_counts() -> None:
    counts = _summary()["readiness_status_summary"]["counts"]

    assert counts["usable_probability"] == 21
    assert counts["baseline_only"] == 93
    assert counts["insufficient_sample"] == 1


def test_protocol_keeps_hazard_local_not_broadly_promoted() -> None:
    summary = _summary()
    readiness = summary["readiness_status_summary"]

    assert readiness["hazard_locally_usable"] == "yes"
    assert readiness["hazard_broadly_promoted"] == "no"
    assert "locally usable" in summary["executive_protocol_verdict"]
    assert "not broadly promoted" in summary["executive_protocol_verdict"]


def test_final_holdout_discipline_forbids_repeated_tuning() -> None:
    discipline = _summary()["split_and_final_holdout_discipline"]

    assert discipline["final_holdout_consumption"] == "final holdout can be consumed only by an explicit WP10 final-gate run."
    assert discipline["repeated_final_tuning_forbidden"] == "yes"
    assert discipline["threshold_tuning_in_wp8"] == "no"


def test_protocol_outputs_no_forbidden_surface_terms() -> None:
    summary = _summary()
    rendered = json.dumps(summary, ensure_ascii=False) + "\n" + build_report_markdown(summary)

    for term in FORBIDDEN_PROTOCOL_TERMS:
        assert term not in rendered


def test_protocol_emits_no_external_fetch() -> None:
    summary = _summary()

    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["local_db_validation"]["external_data_fetch"] == "no"


def test_wp10_handoff_contract_is_present() -> None:
    contract = _summary()["wp10_handoff_contract"]

    assert contract["contract_version"] == "wp10_final_gate_handoff_v1"
    assert "risk_validation_protocol.json" in contract["required_inputs"]
    assert "evaluate pre-registered metrics on final holdout once" in contract["final_gate_allowed_actions"]


def test_cli_writes_protocol_reports_without_external_fetch(tmp_path: Path) -> None:
    output = tmp_path / "risk_validation_protocol.md"
    summary_json = tmp_path / "risk_validation_protocol.json"

    exit_code = run_cli(
        Namespace(
            hazard_readiness=str(ROOT / "reports/stage03r/hazard_readiness_matrix_report.json"),
            hazard_vs_hsmm=str(ROOT / "reports/stage03r/hazard_vs_hsmm_report.json"),
            hazard_verdict=str(ROOT / "reports/stage03r/multi_horizon_hazard_verdict.md"),
            db=None,
            run_id="latest",
            output=str(output),
            summary_json=str(summary_json),
            no_fetch=True,
        )
    )
    summary = json.loads(summary_json.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert output.exists()
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["wp10_handoff_contract"]["contract_version"] == "wp10_final_gate_handoff_v1"
