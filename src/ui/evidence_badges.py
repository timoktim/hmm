"""Small formatting helpers for UI evidence/readiness badges."""

from __future__ import annotations

from typing import Any, Mapping

from src.ui.readiness_policy import ReadinessDecision


BADGE_LABELS = {
    "decision_ready": "Decision ready",
    "validated": "Validated",
    "research_only": "Research only",
    "internal_diagnostic": "Internal diagnostic",
    "unknown_due_to_missing_metadata": "Unknown metadata",
    "hidden": "Hidden",
}


def readiness_badge(decision_or_status: ReadinessDecision | str) -> dict[str, str]:
    status = (
        decision_or_status.readiness_status
        if isinstance(decision_or_status, ReadinessDecision)
        else str(decision_or_status)
    )
    label = BADGE_LABELS.get(status, status.replace("_", " ").title())
    tone = "success" if status in {"decision_ready", "validated"} else "warning"
    if status in {"hidden", "blocked_mixed_state_source", "blocked_misleading_probability_label"}:
        tone = "danger"
    return {"label": label, "status": status, "tone": tone}


def attach_badge(record: Mapping[str, Any], decision: ReadinessDecision) -> dict[str, Any]:
    output = dict(record)
    output["readiness_badge"] = readiness_badge(decision)
    output["evidence_level"] = decision.evidence_level
    output["readiness_status"] = decision.readiness_status
    output["state_source"] = decision.state_source
    return output
