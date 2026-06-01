from src.ui.readiness_policy import (
    CANONICAL_EVIDENCE_LEVELS,
    CANONICAL_READINESS_STATUSES,
    evaluate_hmm_churn_dwell_display,
    evaluate_hmm_state_display,
    evaluate_hmm_strategy_display,
    evaluate_hsmm_lifecycle_field_display,
    evaluate_state_source_boundary,
    find_misleading_probability_claims,
    get_default_stage00_policy,
)


def assert_canonical(decision):
    assert decision.evidence_level in CANONICAL_EVIDENCE_LEVELS
    assert decision.readiness_status in CANONICAL_READINESS_STATUSES


def test_hsmm_state_age_and_phase_are_allowed_internal_diagnostics():
    age = evaluate_hsmm_lifecycle_field_display("state_age")
    phase = evaluate_hsmm_lifecycle_field_display("state_phase")

    assert age.action == "allow"
    assert age.display is True
    assert age.evidence_level == "internal_diagnostic"
    assert age.readiness_status == "internal_only"
    assert phase.action == "allow"
    assert phase.display is True
    assert phase.readiness_status == "internal_only"
    assert_canonical(age)
    assert_canonical(phase)


def test_numeric_p_exit_is_hidden_by_default_even_when_usable():
    decision = evaluate_hsmm_lifecycle_field_display(
        "raw_p_exit",
        probability_status="usable_probability",
        readiness_status="validated",
        value=0.42,
    )

    assert decision.action == "hide"
    assert decision.display is False
    assert decision.evidence_level == "internal_diagnostic"
    assert decision.readiness_status == "blocked"
    assert decision.semantic_role == "numeric_exit_probability"
    assert decision.reason == "hidden_by_stage00_policy"
    assert_canonical(decision)


def test_invalid_missing_and_insufficient_probability_status_hide_values():
    for status in ["invalid", "missing", "insufficient_sample"]:
        decision = evaluate_hsmm_lifecycle_field_display(
            "calibrated_p_exit",
            probability_status=status,
            readiness_status="decision_ready",
            value=0.12,
        )
        assert decision.action == "hide"
        assert decision.display is False
        assert decision.evidence_level == "internal_diagnostic"
        assert decision.readiness_status == "blocked"
        assert decision.semantic_role == "numeric_exit_probability"
        assert "do_not_fill_missing_probability_with_zero" in decision.warnings
        assert_canonical(decision)


def test_next_state_tendency_is_realized_historical_tendency_only():
    decision = evaluate_hsmm_lifecycle_field_display("next_state_tendency_5d")

    assert decision.action == "allow"
    assert decision.evidence_level == "internal_diagnostic"
    assert decision.readiness_status == "internal_only"
    assert decision.semantic_role == "realized_historical_tendency"
    assert decision.metadata["display_format"] == "ordinal_tendency"
    assert_canonical(decision)


def test_strategy_without_causal_cache_is_research_only_or_hidden():
    decision = evaluate_hmm_strategy_display()

    assert decision.action == "research_only"
    assert decision.display is False
    assert decision.evidence_level == "exploratory"
    assert decision.readiness_status == "research_only"
    assert "missing_causal_cache_id" in decision.warnings
    assert_canonical(decision)


def test_hmm_churn_dwell_excessive_churn_hides_strategy_outputs():
    decision = evaluate_hmm_churn_dwell_display(
        churn_bucket="excessive",
        confidence_integration_status="available_confidence",
        alignment_integration_status="available_alignment",
        causal_cache_available=True,
    )

    assert decision.action == "hide_strategy"
    assert decision.display is False
    assert decision.evidence_level == "exploratory"
    assert decision.readiness_status == "research_only"
    assert decision.metadata["display_action"] == "hide_strategy"
    assert "strategy_not_validated_due_to_excessive_churn" in decision.warnings
    assert_canonical(decision)


def test_hmm_churn_dwell_missing_confidence_downgrades_to_research_only():
    decision = evaluate_hmm_churn_dwell_display(
        churn_bucket="low",
        confidence_integration_status="unavailable",
        alignment_integration_status="unavailable",
        causal_cache_available=True,
    )

    assert decision.action == "research_only"
    assert decision.display is True
    assert decision.readiness_status == "research_only"
    assert decision.metadata["display_action"] == "research_only"
    assert "hmm_confidence_low_or_unavailable" in decision.warnings
    assert_canonical(decision)


def test_hmm_posterior_allows_only_state_confidence_labeling():
    allowed = evaluate_hmm_state_display(
        field_name="posterior_probability",
        semantic_role="state_confidence",
        display_label="state confidence",
    )
    blocked = evaluate_hmm_state_display(
        field_name="posterior_probability",
        semantic_role="return_probability",
        display_label="HMM上涨概率",
    )

    assert allowed.action == "allow"
    assert allowed.evidence_level == "internal_diagnostic"
    assert allowed.readiness_status == "internal_only"
    assert allowed.semantic_role == "state_confidence"
    assert blocked.action == "hide"
    assert blocked.display is False
    assert blocked.evidence_level == "internal_diagnostic"
    assert blocked.readiness_status == "blocked"
    assert blocked.reason == "blocked_misleading_probability_label"
    assert_canonical(allowed)
    assert_canonical(blocked)


def test_hmm_causal_and_in_sample_state_use_canonical_fields():
    causal = evaluate_hmm_state_display(state_source="causal_walk_forward")
    in_sample = evaluate_hmm_state_display(context="research")
    missing = evaluate_hmm_state_display()

    assert causal.evidence_level == "internal_diagnostic"
    assert causal.readiness_status == "partial"
    assert causal.state_source == "causal_walk_forward"
    assert in_sample.evidence_level == "exploratory"
    assert in_sample.readiness_status == "research_only"
    assert in_sample.state_source == "in_sample_explanation"
    assert missing.evidence_level == "exploratory"
    assert missing.readiness_status == "blocked"
    assert missing.state_source == "unknown_due_to_missing_metadata"
    assert_canonical(causal)
    assert_canonical(in_sample)
    assert_canonical(missing)


def test_strategy_and_state_boundary_use_canonical_fields():
    cached = evaluate_hmm_strategy_display(causal_cache_id="cache-1")
    baseline_fail = evaluate_hmm_strategy_display(causal_cache_id="cache-1", baseline_passed=False)
    boundary = evaluate_state_source_boundary(["causal_walk_forward"])

    assert cached.evidence_level == "validated_signal"
    assert cached.readiness_status == "validated"
    assert cached.state_source == "causal_walk_forward"
    assert baseline_fail.evidence_level == "validated_signal"
    assert baseline_fail.readiness_status == "partial"
    assert baseline_fail.reason == "research_signal"
    assert boundary.evidence_level == "internal_diagnostic"
    assert boundary.readiness_status == "partial"
    assert boundary.state_source == "causal_walk_forward"
    assert_canonical(cached)
    assert_canonical(baseline_fail)
    assert_canonical(boundary)


def test_default_policy_falls_back_when_db_missing(tmp_path):
    policy = get_default_stage00_policy(tmp_path / "missing.duckdb")

    assert policy["policy_source"] == "builtin_conservative_db_missing"
    assert policy["allow_numeric_p_exit_when_validated"] is False


def test_default_policy_reads_wp_a_ui_readiness_policy_schema(tmp_path):
    import duckdb

    db_path = tmp_path / "policy.duckdb"
    with duckdb.connect(str(db_path)) as con:
        con.execute(
            """
            CREATE TABLE ui_readiness_policy (
              policy_id TEXT PRIMARY KEY,
              surface TEXT NOT NULL,
              field_name TEXT NOT NULL,
              model_type TEXT,
              required_evidence_level TEXT NOT NULL,
              required_readiness_status TEXT NOT NULL,
              allow_display BOOLEAN NOT NULL,
              display_mode TEXT NOT NULL,
              fallback_text TEXT,
              policy_reason TEXT,
              created_at TIMESTAMP NOT NULL,
              updated_at TIMESTAMP NOT NULL
            )
            """
        )
        con.execute(
            """
            INSERT INTO ui_readiness_policy
            VALUES (
              'hsmm_numeric_p_exit', 'hsmm_lifecycle', 'numeric_p_exit', 'hsmm',
              'internal_diagnostic', 'validated', true, 'hide_unless_usable_probability',
              'p_exit validated', 'test override', now(), now()
            )
            """
        )

    policy = get_default_stage00_policy(db_path)

    assert policy["policy_source"] == "db_overlay"
    assert policy["allow_numeric_p_exit_when_validated"] is True
    assert "hsmm_numeric_p_exit" in policy["policy_rows"]

    decision = evaluate_hsmm_lifecycle_field_display(
        "calibrated_p_exit",
        probability_status="usable_probability",
        readiness_status="validated",
        value=0.23,
        policy=policy,
    )
    assert decision.evidence_level == "validated_signal"
    assert decision.readiness_status == "validated"
    assert decision.semantic_role == "usable_probability"
    assert decision.metadata["probability_evidence"] == "validated_probability"
    assert_canonical(decision)


def test_text_audit_allows_negated_context_but_flags_claim():
    findings = find_misleading_probability_claims(
        ["posterior 不是上涨概率", "bad label: 上涨概率"]
    )

    assert len(findings) == 1
    assert findings[0]["phrase"] == "上涨概率"
