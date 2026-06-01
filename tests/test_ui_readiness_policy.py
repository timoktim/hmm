from src.ui.readiness_policy import (
    evaluate_hmm_state_display,
    evaluate_hmm_strategy_display,
    evaluate_hsmm_lifecycle_field_display,
    find_misleading_probability_claims,
    get_default_stage00_policy,
)


def test_hsmm_state_age_and_phase_are_allowed_internal_diagnostics():
    age = evaluate_hsmm_lifecycle_field_display("state_age")
    phase = evaluate_hsmm_lifecycle_field_display("state_phase")

    assert age.action == "allow"
    assert age.display is True
    assert age.evidence_level == "internal_diagnostic"
    assert phase.action == "allow"
    assert phase.display is True


def test_numeric_p_exit_is_hidden_by_default_even_when_usable():
    decision = evaluate_hsmm_lifecycle_field_display(
        "raw_p_exit",
        probability_status="usable_probability",
        readiness_status="validated",
        value=0.42,
    )

    assert decision.action == "hide"
    assert decision.display is False


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
        assert "do_not_fill_missing_probability_with_zero" in decision.warnings


def test_next_state_tendency_is_realized_historical_tendency_only():
    decision = evaluate_hsmm_lifecycle_field_display("next_state_tendency_5d")

    assert decision.action == "allow"
    assert decision.semantic_role == "realized_historical_tendency"
    assert decision.metadata["display_format"] == "ordinal_tendency"


def test_strategy_without_causal_cache_is_research_only_or_hidden():
    decision = evaluate_hmm_strategy_display()

    assert decision.action == "research_only"
    assert decision.display is False
    assert decision.readiness_status == "research_only"
    assert "missing_causal_cache_id" in decision.warnings


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
    assert blocked.action == "hide"
    assert blocked.display is False


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


def test_text_audit_allows_negated_context_but_flags_claim():
    findings = find_misleading_probability_claims(
        ["posterior 不是上涨概率", "bad label: 上涨概率"]
    )

    assert len(findings) == 1
    assert findings[0]["phrase"] == "上涨概率"
