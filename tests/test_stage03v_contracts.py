from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SIGNAL_CONTRACT = ROOT / "configs" / "risk_event_signal_contract_v1.yaml"
READINESS_POLICY = ROOT / "configs" / "readiness_policy_risk_event_v1.yaml"
UNIVERSE_MANIFEST = ROOT / "configs" / "stage03v_sw_l2_universe_manifest_v1.yaml"
EXECUTION_INDEX = ROOT / "docs" / "work_packages" / "stage03v" / "STAGE03V_EXECUTION_INDEX.md"
LEDGER_TEMPLATE = ROOT / "reports" / "stage04" / "prospective_validation_ledger.stage03v.template.jsonl"
REPORT_MD = ROOT / "reports" / "stage03v" / "stage03v_wp0_scope_freeze_report.md"
REPORT_JSON = ROOT / "reports" / "stage03v" / "stage03v_wp0_scope_freeze_report.json"

REQUIRED_READINESS_STATUSES = {
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
}
REQUIRED_CALIBRATION_STATUSES = {
    "not_calibrated",
    "calibration_candidate",
    "calibrated_pass",
    "calibrated_fail",
    "not_applicable",
}
EXPECTED_COMPARABILITY_BREAK = (
    "Stage03V1 uses SW2021 level-2 industries only. Earlier Stage03R and "
    "signal-validation artifacts based on roughly 465 mixed industry/concept "
    "boards are not directly comparable to Stage03V1 metrics without an "
    "explicit comparability adjustment."
)


def _load_machine_yaml(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return json.loads(text)
    return yaml.safe_load(text)


def _ledger_record() -> dict:
    return json.loads(LEDGER_TEMPLATE.read_text(encoding="utf-8").strip())


def test_required_wp0_files_exist_and_machine_configs_parse() -> None:
    for path in [
        SIGNAL_CONTRACT,
        READINESS_POLICY,
        UNIVERSE_MANIFEST,
        EXECUTION_INDEX,
        LEDGER_TEMPLATE,
        REPORT_MD,
        REPORT_JSON,
    ]:
        assert path.exists(), path

    assert _load_machine_yaml(SIGNAL_CONTRACT)["metadata"]["index_id"] == "STAGE03V-WP0-v1"
    assert _load_machine_yaml(READINESS_POLICY)["metadata"]["index_id"] == "STAGE03V-WP0-v1"
    assert _load_machine_yaml(UNIVERSE_MANIFEST)["metadata"]["index_id"] == "STAGE03V-WP0-v1"
    assert json.loads(REPORT_JSON.read_text(encoding="utf-8"))["index_id"] == "STAGE03V-WP0-v1"


def test_execution_index_marks_wp4_active_and_later_packages_blocked() -> None:
    text = EXECUTION_INDEX.read_text(encoding="utf-8")

    assert "STAGE03V-WP0-v1 | Scope Freeze, Contracts, Ledger | archived" in text
    assert "STAGE03V-WP0.5-v1 | Sample Feasibility Preflight | archived" in text
    assert "STAGE03V-WP1-v1 | Risk Event Target Dataset v1 | archived" in text
    assert "STAGE03V-WP2-v1 | Target Leakage, Purge, Embargo, and CI Gate | archived" in text
    assert "STAGE03V-WP2.1-v1 | Full Target Streaming Audit | archived" in text
    assert "STAGE03V-WP3-v1 | Volatility, Range-Based, Empirical, and Continuous Diagnostic Baselines | archived" in text
    assert "STAGE03V-WP3.5-v1 | Volatility-Scaled Threshold Supplement and Baseline Metric Sanity Gate | archived" in text
    assert "STAGE03V-WP4-v1 | Logistic Downside Risk Hazard v1 | active" in text
    assert "STAGE03V-WP5 | Calibration, Clustered Inference, and Downside Risk Readiness Matrix | blocked_until_wp4_accepted" in text
    assert "Only STAGE03V-WP4-v1 is executable in the current Stage03V branch sequence." in text
    assert "STAGE03V-WP5 and later packages are blocked until WP4 is accepted." in text


def test_stage_boundary_and_placeholders_are_contractual() -> None:
    signal = _load_machine_yaml(SIGNAL_CONTRACT)

    assert signal["stage_id"] == "stage03v"
    assert signal["active_module"] == "Stage03V1 Downside Risk"
    assert signal["stage03v1_entity_type"] == "sw2021_l2_industry"
    assert signal["stage03v2_implemented"] is False
    assert signal["stage03v3_implemented"] is False
    assert signal["stage_boundary"]["stage03v2"]["status"] == "placeholder_only"
    assert signal["stage_boundary"]["stage03v3"]["status"] == "placeholder_only"
    assert signal["stage_boundary"]["hmm_hsmm_training_algorithm_modified"] is False


def test_stage03v_holdout_registration_uses_own_cutoff_and_start() -> None:
    signal = _load_machine_yaml(SIGNAL_CONTRACT)
    readiness = _load_machine_yaml(READINESS_POLICY)
    ledger = _ledger_record()

    for obj in [signal["split_role_policy"], readiness["metadata"], ledger]:
        assert obj["information_cutoff_date"] == "2026-06-10"
        assert obj["holdout_start"] == "2026-06-11"

    assert ledger["stage_id"] == "stage03v"
    assert ledger["historical_development"] == "trade_date <= 2026-06-10"
    assert ledger["prospective_final_holdout"] == "trade_date >= 2026-06-11"
    assert ledger["required_label_horizons"] == [1, 3, 5, 10, 20]
    assert ledger["label_completeness_required"] is True
    assert ledger["consumption_count_enabled"] is True
    assert ledger["scheduled_holdout_review_frequency"] == "quarterly"
    assert ledger["ad_hoc_holdout_peeking"] == "forbidden"
    assert ledger["stage04_holdout_start_inherited"] is False
    assert ledger["holdout_start"] != "2026-05-29"


def test_permanent_cross_cutoff_censoring_policy_forbids_backfill() -> None:
    signal = _load_machine_yaml(SIGNAL_CONTRACT)
    policy = signal["cross_cutoff_censoring"]

    assert policy["cross_cutoff_censoring_policy"] == "permanent"
    assert policy["information_cutoff_date"] == "2026-06-10"
    assert policy["label_cutoff_date"] == "2026-06-10"
    assert set(policy["allowed_cross_cutoff_handling"]) == {
        "cross_cutoff_censored",
        "exclude_with_reason",
    }
    assert set(policy["forbidden_cross_cutoff_handling"]) == {
        "backfill_after_cutoff",
        "fill_from_holdout_prices",
    }
    invariant_text = "\n".join(policy["invariant"])
    assert "target_observation_end_date must be <= information_cutoff_date" in invariant_text
    assert "must not be backfilled" in invariant_text


def test_benchmark_downside_target_uses_mae_and_slice_policies() -> None:
    signal = _load_machine_yaml(SIGNAL_CONTRACT)
    benchmark = signal["target_contract"]["benchmark_downside_target"]

    assert benchmark["benchmark_target_name"] == "broad_a_share_downside_event"
    assert benchmark["preferred_benchmark_name"] == "CSI All Share / 中证全指"
    assert benchmark["source_table"] == "market_benchmark_ohlcv"
    assert benchmark["target_kind"] == "downside_event"
    assert benchmark["path_metric"] == "MAE"
    assert benchmark["horizon_policy"] == "same_as_slice"
    assert benchmark["threshold_policy"] == "same_as_slice"
    assert benchmark["fallback_if_unavailable"] == "benchmark_target_unavailable"
    assert benchmark["benchmark_selection_after_modeling"] == "forbidden"


def test_sw2021_l2_taxonomy_and_quality_filter_are_frozen() -> None:
    manifest = _load_machine_yaml(UNIVERSE_MANIFEST)
    universe = manifest["universe"]
    quality = manifest["quality_filter"]

    assert universe["taxonomy_provider"] == "SW"
    assert universe["taxonomy_version"] == "SW2021"
    assert universe["taxonomy_level"] == "L2"
    assert universe["index_history_policy"] == "official_backfilled_index_history_if_available"
    assert universe["reform_check_date"] == "2021-07-01"
    assert universe["constituent_count_min"] == 5
    assert universe["history_continuity_required"] is True
    assert universe["no_performance_based_filtering"] is True
    assert universe["filter_list_frozen_in_manifest"] is True
    assert universe["empirical_promotion_universe"] == "sw2021_l2_industry_only"
    assert universe["optional_diagnostic_universe"] == "sw2021_l1_aggregation"
    assert quality["minimum_constituents_when_snapshot_available"] == 5
    assert quality["freeze_filter_list_before_modeling"] is True


def test_readiness_statuses_calibration_statuses_and_ordinal_buckets_exist() -> None:
    policy = _load_machine_yaml(READINESS_POLICY)

    assert REQUIRED_READINESS_STATUSES.issubset(policy["readiness_statuses"])
    assert REQUIRED_CALIBRATION_STATUSES.issubset(policy["calibration_statuses"])
    assert policy["readiness_statuses"]["usable_probability"]["allow_numeric_probability"] is True
    for status in ["ordinal_only", "baseline_only", "insufficient_sample", "invalid"]:
        assert policy["readiness_statuses"][status]["allow_numeric_probability"] is False

    buckets = policy["ordinal_policy"]["default_buckets"]
    assert buckets["low"]["rule"] == "score < validation q40"
    assert buckets["medium"]["rule"] == "q40 <= score < q75"
    assert buckets["high"]["rule"] == "q75 <= score < q90"
    assert buckets["extreme"]["rule"] == "score >= q90"
    assert policy["ordinal_policy"]["source_rows"] == "validation_fold_rows_only"
    assert set(policy["ordinal_policy"]["forbidden_bucket_tuning"]) == {
        "final_holdout",
        "post_hoc_visual_appearance",
        "model_performance",
    }


def test_event_evidence_gates_and_validation_fold_only_wp5_counts() -> None:
    policy = _load_machine_yaml(READINESS_POLICY)
    gates = policy["event_evidence_gating"]
    scope = policy["readiness_evidence_scope"]

    assert gates["market_event_share_sensitivity"] == [0.10, 0.20, 0.30]
    assert gates["primary_market_event_share"] == 0.20
    assert gates["idiosyncratic_discount_default"] == 0.25
    assert gates["idiosyncratic_discount_sensitivity"] == [0.10, 0.25, 0.50]
    assert gates["market_event_block_count_lt_2"] == "usable_probability_forbidden"
    assert gates["effective_event_evidence_count_lt_5"] == "blocked_or_drop_threshold"
    assert gates["effective_event_evidence_count_5_to_9"] == "diagnostic_or_ordinal_only"
    assert gates["effective_event_evidence_count_gte_10"] == "modeling_eligible_not_auto_usable"
    assert scope["wp0_5_feasibility_counts_may_use"] == "historical_development"
    assert scope["wp5_usable_probability_evidence_counts_must_use"] == "validation_fold_rows_only"
    assert scope["training_period_evidence_cannot_satisfy_usable_probability"] is True


def test_wp0_report_records_comparability_break_and_no_runtime_actions() -> None:
    report = json.loads(REPORT_JSON.read_text(encoding="utf-8"))
    text = REPORT_MD.read_text(encoding="utf-8")
    flags = report["boundary_flags"]

    assert report["comparability_break_statement"] == EXPECTED_COMPARABILITY_BREAK
    assert EXPECTED_COMPARABILITY_BREAK in text
    assert report["ledger_or_split_manifest_path"] == (
        "reports/stage04/prospective_validation_ledger.stage03v.template.jsonl"
    )
    assert report["split_manifest_fallback_used"] is False
    assert flags["external_data_fetch"] == "no"
    assert flags["target_dataset_built"] == "no"
    assert flags["model_training"] == "no"
    assert flags["holdout_consumed"] == "no"
    assert flags["HMM_HSMM_training_modified"] == "no"
    assert flags["decision_or_trading_output"] == "no"
    assert flags["stage03v_wp0_5_started"] == "no"
