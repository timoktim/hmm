from src.ui.causal_boundary import (
    attach_evidence_metadata,
    audit_no_in_sample_causal_mix,
    classify_state_source,
    require_causal_for_strategy,
)


def test_classify_state_source_uses_explicit_metadata_and_cache_hints():
    assert classify_state_source({"state_source": "causal_walk_forward"}) == "causal_walk_forward"
    assert classify_state_source({"state_source": "in_sample"}) == "in_sample_explanation"
    assert classify_state_source({"causal_cache_id": "cache-1"}) == "causal_walk_forward"


def test_audit_detects_mixed_state_sources():
    audit = audit_no_in_sample_causal_mix(
        [
            {
                "state_source": "causal_walk_forward",
                "train_end": "2025-01-01",
                "trade_date": "2025-01-02",
                "max_observation_date_used": "2025-01-01",
                "exec_date": "2025-01-03",
                "signal_date": "2025-01-02",
            },
            {
                "state_source": "in_sample",
                "train_end": "2025-01-01",
                "trade_date": "2025-01-02",
                "max_observation_date_used": "2025-01-01",
                "exec_date": "2025-01-03",
                "signal_date": "2025-01-02",
            },
        ]
    )

    assert audit["status"] == "fail"
    assert audit["causal_in_sample_mix_found"] is True


def test_audit_flags_missing_causal_cache_for_strategy():
    audit = audit_no_in_sample_causal_mix(
        [
            {
                "state_source": "causal_walk_forward",
                "record_type": "strategy_evaluation",
                "train_end": "2025-01-01",
                "trade_date": "2025-01-02",
                "max_observation_date_used": "2025-01-01",
                "exec_date": "2025-01-03",
                "signal_date": "2025-01-02",
            }
        ]
    )

    assert audit["status"] == "fail"
    assert audit["strategy_missing_causal_cache_found"] is True


def test_audit_flags_lookahead_date_violations():
    audit = audit_no_in_sample_causal_mix(
        [
            {
                "state_source": "causal_walk_forward",
                "train_end": "2025-01-03",
                "trade_date": "2025-01-02",
                "max_observation_date_used": "2025-01-04",
                "exec_date": "2025-01-02",
                "signal_date": "2025-01-02",
            }
        ]
    )

    checks = {finding["check"] for finding in audit["findings"]}
    assert "train_end_after_trade_date" in checks
    assert "observation_after_trade_date" in checks
    assert "exec_date_not_after_signal_date" in checks


def test_missing_metadata_returns_unknown_not_pass():
    audit = audit_no_in_sample_causal_mix([{"state_source": "causal_walk_forward"}])

    assert audit["status"] == "unknown_due_to_missing_metadata"


def test_attach_evidence_metadata_adds_required_fields():
    row = attach_evidence_metadata(
        {"symbol": "AAA"},
        evidence_level="internal_diagnostic",
        readiness_status="research_only",
        state_source="in_sample_explanation",
        readiness_reason="historical explanation only",
    )

    assert row["evidence_level"] == "internal_diagnostic"
    assert row["readiness_status"] == "research_only"
    assert row["state_source"] == "in_sample_explanation"
    assert row["readiness_reason"] == "historical explanation only"


def test_require_causal_for_strategy_allows_cached_record():
    decision = require_causal_for_strategy({"causal_cache_id": "cache-1"})

    assert decision.action == "allow"
    assert decision.state_source == "causal_walk_forward"
