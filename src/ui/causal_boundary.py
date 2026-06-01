"""Causal versus in-sample UI boundary helpers."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping, Sequence

from src.ui.readiness_policy import (
    CAUSAL_SOURCES,
    IN_SAMPLE_SOURCES,
    UNKNOWN_SOURCE,
    ReadinessDecision,
    evaluate_hmm_strategy_display,
)


def _norm(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip().lower()


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return bool(value)


def _parse_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def classify_state_source(record: Mapping[str, Any] | None = None, **metadata: Any) -> str:
    """Classify the state source from explicit metadata first, then cache hints."""

    data = dict(record or {})
    data.update(metadata)
    source = _norm(data.get("state_source"))
    if source in CAUSAL_SOURCES:
        return "causal_walk_forward"
    if source in IN_SAMPLE_SOURCES:
        return "in_sample_explanation"
    if _truthy(data.get("causal_cache_id")) or _truthy(data.get("walk_forward_cache_id")):
        return "causal_walk_forward"
    context = _norm(data.get("context"))
    if context in {"research", "in_sample_explanation", "research_only"}:
        return "in_sample_explanation"
    return UNKNOWN_SOURCE


def require_causal_for_strategy(record: Mapping[str, Any] | None = None, **metadata: Any) -> ReadinessDecision:
    """Return a strategy display decision requiring causal cache metadata."""

    data = dict(record or {})
    data.update(metadata)
    return evaluate_hmm_strategy_display(
        causal_cache_id=data.get("causal_cache_id"),
        walk_forward_cache_id=data.get("walk_forward_cache_id"),
        cache_metadata=data.get("cache_metadata") if isinstance(data.get("cache_metadata"), Mapping) else None,
        baseline_passed=data.get("baseline_passed"),
        evidence_level=data.get("evidence_level"),
        readiness_status=data.get("readiness_status"),
    )


def attach_evidence_metadata(
    record: Mapping[str, Any],
    *,
    evidence_level: str,
    readiness_status: str,
    state_source: str | None = None,
    readiness_reason: str | None = None,
) -> dict[str, Any]:
    """Return a copy of a UI row with explicit readiness metadata attached."""

    output = dict(record)
    output["evidence_level"] = evidence_level
    output["readiness_status"] = readiness_status
    output["state_source"] = state_source or classify_state_source(output)
    if readiness_reason:
        output["readiness_reason"] = readiness_reason
    return output


def _finding(check: str, status: str, message: str, index: int | None = None) -> dict[str, Any]:
    item: dict[str, Any] = {"check": check, "status": status, "message": message}
    if index is not None:
        item["record_index"] = index
    return item


def _check_required_date_pair(
    record: Mapping[str, Any],
    *,
    index: int,
    left_field: str,
    right_field: str,
    check: str,
    invalid_when: str,
) -> list[dict[str, Any]]:
    left = _parse_date(record.get(left_field))
    right = _parse_date(record.get(right_field))
    if left is None or right is None:
        return [
            _finding(
                check,
                UNKNOWN_SOURCE,
                f"Missing or invalid {left_field}/{right_field}; cannot prove causal boundary.",
                index,
            )
        ]
    if invalid_when == "left_gt_right" and left > right:
        return [_finding(check, "fail", f"{left_field} > {right_field}.", index)]
    if invalid_when == "left_lte_right" and left <= right:
        return [_finding(check, "fail", f"{left_field} <= {right_field}.", index)]
    return []


def audit_no_in_sample_causal_mix(
    ui_records: Iterable[Mapping[str, Any]],
    *,
    strategy_records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Audit UI records for in-sample/causal mixing and look-ahead metadata."""

    records = list(ui_records)
    findings: list[dict[str, Any]] = []
    sources = [classify_state_source(record) for record in records]
    source_set = set(sources)

    if "causal_walk_forward" in source_set and "in_sample_explanation" in source_set:
        findings.append(
            _finding(
                "state_source_mix",
                "fail",
                "UI dataset mixes in-sample and causal walk-forward state sources.",
            )
        )
    if UNKNOWN_SOURCE in source_set:
        findings.append(
            _finding(
                "state_source_metadata",
                UNKNOWN_SOURCE,
                "At least one UI record lacks state_source metadata.",
            )
        )

    for index, record in enumerate(records):
        findings.extend(
            _check_required_date_pair(
                record,
                index=index,
                left_field="train_end",
                right_field="trade_date",
                check="train_end_after_trade_date",
                invalid_when="left_gt_right",
            )
        )
        findings.extend(
            _check_required_date_pair(
                record,
                index=index,
                left_field="max_observation_date_used",
                right_field="trade_date",
                check="observation_after_trade_date",
                invalid_when="left_gt_right",
            )
        )
        findings.extend(
            _check_required_date_pair(
                record,
                index=index,
                left_field="exec_date",
                right_field="signal_date",
                check="exec_date_not_after_signal_date",
                invalid_when="left_lte_right",
            )
        )

    strategy_items: Sequence[Mapping[str, Any]]
    if strategy_records is None:
        strategy_items = [
            record
            for record in records
            if _norm(record.get("record_type")) == "strategy_evaluation" or record.get("is_strategy")
        ]
    else:
        strategy_items = list(strategy_records)

    for index, strategy in enumerate(strategy_items):
        decision = require_causal_for_strategy(strategy)
        if decision.action != "allow":
            findings.append(
                _finding(
                    "strategy_missing_causal_cache",
                    "fail" if decision.action in {"block", "research_only"} else decision.readiness_status,
                    decision.reason,
                    index,
                )
            )

    if any(item["status"] == "fail" for item in findings):
        status = "fail"
    elif any(item["status"] == UNKNOWN_SOURCE for item in findings):
        status = UNKNOWN_SOURCE
    else:
        status = "pass"

    return {
        "status": status,
        "findings": findings,
        "state_sources": sources,
        "causal_in_sample_mix_found": any(item["check"] == "state_source_mix" for item in findings),
        "strategy_missing_causal_cache_found": any(
            item["check"] == "strategy_missing_causal_cache" for item in findings
        ),
    }
