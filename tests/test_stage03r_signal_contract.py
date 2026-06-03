from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_CONTRACT = ROOT / "configs" / "lifecycle_signal_contract_v1.yaml"
READINESS_POLICY = ROOT / "configs" / "readiness_policy_lifecycle_v1.yaml"

REQUIRED_CATEGORIES = {
    "display_safe",
    "internal_diagnostic",
    "calibration_required",
    "hidden",
    "future_hazard_input",
    "forbidden_decision_input",
}

REQUIRED_FIELDS = {
    "hmm_state_label",
    "hmm_state_confidence",
    "hmm_state_entropy",
    "hmm_posterior_margin",
    "hsmm_state_age",
    "hsmm_state_phase",
    "hsmm_duration_percentile",
    "hsmm_duration_percentile_status",
    "hsmm_duration_tail_status",
    "hsmm_exit_tendency_ordinal",
    "hsmm_raw_p_exit_1d",
    "hsmm_raw_p_exit_3d",
    "hsmm_raw_p_exit_5d",
    "hsmm_raw_p_exit_10d",
    "hsmm_raw_p_exit_20d",
    "hsmm_calibrated_p_exit_1d",
    "hsmm_calibrated_p_exit_3d",
    "hsmm_calibrated_p_exit_5d",
    "hsmm_calibrated_p_exit_10d",
    "hsmm_calibrated_p_exit_20d",
    "hsmm_next_state_tendency",
    "hazard_exit_tendency_ordinal",
    "hazard_calibrated_probability",
    "hazard_readiness_status",
    "hazard_sample_support",
    "hazard_fallback_reason",
}

REQUIRED_READINESS_STATUSES = {
    "display_safe",
    "internal_only",
    "calibration_required",
    "hidden",
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
    "abstain",
}


def _load_machine_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return json.loads(text)
    return yaml.safe_load(text)


def _contracts() -> tuple[dict, dict]:
    return _load_machine_yaml(SIGNAL_CONTRACT), _load_machine_yaml(READINESS_POLICY)


def test_stage03r_yaml_contracts_parse() -> None:
    signal_contract, readiness_policy = _contracts()

    assert isinstance(signal_contract, dict)
    assert isinstance(readiness_policy, dict)
    assert signal_contract["metadata"]["index_id"] == "STAGE03R-WP0"
    assert readiness_policy["metadata"]["index_id"] == "STAGE03R-WP0"


def test_required_top_level_sections_and_fields_exist() -> None:
    signal_contract, readiness_policy = _contracts()

    assert {"metadata", "field_categories", "fields", "rules", "out_of_scope_models"}.issubset(
        signal_contract
    )
    assert {"metadata", "readiness_statuses", "status_rules", "decision_engine_rules"}.issubset(
        readiness_policy
    )
    assert REQUIRED_CATEGORIES.issubset(signal_contract["field_categories"])
    assert REQUIRED_FIELDS.issubset(signal_contract["fields"])
    assert REQUIRED_READINESS_STATUSES.issubset(readiness_policy["readiness_statuses"])


def test_hsmm_numeric_p_exit_is_not_default_decision_input() -> None:
    signal_contract, _ = _contracts()
    fields = signal_contract["fields"]
    allowed_categories = set(signal_contract["rules"]["hsmm_numeric_p_exit_allowed_categories"])

    numeric_p_exit_fields = [
        field
        for field in fields
        if field.startswith("hsmm_raw_p_exit_") or field.startswith("hsmm_calibrated_p_exit_")
    ]
    assert numeric_p_exit_fields
    assert signal_contract["rules"]["hsmm_numeric_p_exit_default_decision_input"] is False
    for field in numeric_p_exit_fields:
        spec = fields[field]
        assert spec["category"] in allowed_categories
        assert spec["decision_input_default"] is False
        assert spec["category"] != "future_hazard_input"


def test_invalid_missing_and_insufficient_sample_do_not_allow_numeric_probability_display() -> None:
    signal_contract, readiness_policy = _contracts()

    for status in ["insufficient_sample", "invalid"]:
        spec = readiness_policy["readiness_statuses"][status]
        assert spec["allow_numeric_probability"] is False
        assert spec.get("pseudo_probability_fill") is False

    for status in ["missing", "invalid", "insufficient_sample"]:
        override = signal_contract["rules"]["readiness_status_overrides"][status]
        assert override["category"] == "hidden"
        assert override["numeric_probability_display"] == "forbidden"
        assert override["pseudo_probability_fill"] == "forbidden"


def test_hazard_fields_are_future_inputs_and_readiness_gated() -> None:
    signal_contract, readiness_policy = _contracts()

    hazard_fields = {
        "hazard_exit_tendency_ordinal",
        "hazard_calibrated_probability",
        "hazard_readiness_status",
        "hazard_sample_support",
        "hazard_fallback_reason",
    }
    for field in hazard_fields:
        spec = signal_contract["fields"][field]
        assert spec["category"] == "future_hazard_input"
        assert spec["readiness_required"] is True
        assert spec["future_decision_input"] == "readiness_approved_only"

    may_consume = set(readiness_policy["decision_engine_rules"]["may_consume"])
    assert "readiness_approved_hazard_calibrated_probability" in may_consume
    assert "hsmm_raw_p_exit" in readiness_policy["decision_engine_rules"]["must_not_consume"]


def test_abstain_is_an_allowed_non_failure_output() -> None:
    _, readiness_policy = _contracts()

    abstain = readiness_policy["readiness_statuses"]["abstain"]
    assert abstain["allowed"] is True
    assert abstain["failure"] is False
    assert abstain["allow_numeric_probability"] is False
    assert readiness_policy["status_rules"]["abstain"]["valid_output"] is True


def test_stage03r_out_of_scope_models_are_listed() -> None:
    signal_contract, _ = _contracts()

    out_of_scope = "\n".join(signal_contract["out_of_scope_models"]).lower()
    for model in [
        "competing-risks",
        "bocpd",
        "robust hmm",
        "sticky hmm",
        "var-hsmm",
        "deep switching state-space",
        "full decision engine",
    ]:
        assert model in out_of_scope
