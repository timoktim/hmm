"""Stage 00 UI readiness policy.

The rules in this module are intentionally conservative. They only gate how UI
and reports may display model outputs; they do not train, fit, rank, or generate
signals.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence


NUMERIC_P_EXIT_FIELDS = frozenset({"raw_p_exit", "calibrated_p_exit", "p_exit"})
STATE_AGE_FIELDS = frozenset({"state_age", "state_age_days", "age", "age_days"})
STATE_PHASE_FIELDS = frozenset({"state_phase", "phase", "lifecycle_phase"})
CANONICAL_EVIDENCE_LEVELS = frozenset(
    {"exploratory", "internal_diagnostic", "validated_signal", "decision_support"}
)
CANONICAL_READINESS_STATUSES = frozenset(
    {"blocked", "research_only", "internal_only", "partial", "validated", "decision_ready"}
)
INVALID_PROBABILITY_STATUSES = frozenset(
    {"invalid", "missing", "insufficient_sample", "insufficient", "unknown"}
)
VALIDATED_READINESS_STATUSES = frozenset({"validated", "decision_ready"})
CAUSAL_SOURCES = frozenset({"causal_walk_forward", "walk_forward", "causal_backtest", "causal_hsmm"})
IN_SAMPLE_SOURCES = frozenset(
    {"in_sample", "in_sample_display", "in_sample_explanation", "research", "research_only"}
)
UNKNOWN_SOURCE = "unknown_due_to_missing_metadata"

MISLEADING_PROBABILITY_CLAIMS = (
    "HMM上涨概率",
    "上涨概率",
    "下跌概率",
    "买入概率",
    "卖出概率",
    "赚钱概率",
    "HSMM预测下一状态概率",
    "p_exit代表下跌概率",
    "p_exit代表上涨概率",
)
NEGATION_MARKERS = ("不是", "并非", "不得", "不能", "禁止", "不应", "no ", "not ")


@dataclass(frozen=True)
class ReadinessDecision:
    """A display decision returned by the Stage 00 readiness gate."""

    action: str
    display: bool
    evidence_level: str
    readiness_status: str
    state_source: str = UNKNOWN_SOURCE
    semantic_role: str = "unspecified"
    reason: str = ""
    warnings: tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.evidence_level not in CANONICAL_EVIDENCE_LEVELS:
            raise ValueError(f"non-canonical evidence_level: {self.evidence_level}")
        if self.readiness_status not in CANONICAL_READINESS_STATUSES:
            raise ValueError(f"non-canonical readiness_status: {self.readiness_status}")

    @property
    def allowed(self) -> bool:
        return self.action == "allow" and self.display

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["warnings"] = list(self.warnings)
        data["metadata"] = dict(self.metadata)
        data["allowed"] = self.allowed
        return data


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


def _canonical_evidence_override(value: str | None) -> str | None:
    normalized = _norm(value)
    return normalized if normalized in CANONICAL_EVIDENCE_LEVELS else None


def _canonical_readiness_override(value: str | None) -> str | None:
    normalized = _norm(value)
    return normalized if normalized in CANONICAL_READINESS_STATUSES else None


def is_numeric_p_exit_field(field_name: str) -> bool:
    field = _norm(field_name)
    return (
        field in NUMERIC_P_EXIT_FIELDS
        or field.startswith("raw_p_exit_")
        or field.startswith("calibrated_p_exit_")
        or field.startswith("p_exit_")
    )


def _decision(
    action: str,
    display: bool,
    *,
    evidence_level: str,
    readiness_status: str,
    state_source: str = UNKNOWN_SOURCE,
    semantic_role: str = "unspecified",
    reason: str,
    warnings: Sequence[str] = (),
    metadata: Mapping[str, Any] | None = None,
) -> ReadinessDecision:
    return ReadinessDecision(
        action=action,
        display=display,
        evidence_level=evidence_level,
        readiness_status=readiness_status,
        state_source=state_source,
        semantic_role=semantic_role,
        reason=reason,
        warnings=tuple(warnings),
        metadata=dict(metadata or {}),
    )


def _contains_causal_cache(metadata: Mapping[str, Any] | None) -> bool:
    if not metadata:
        return False
    if _truthy(metadata.get("causal_cache_id")) or _truthy(metadata.get("walk_forward_cache_id")):
        return True
    cache_metadata = metadata.get("cache_metadata")
    if isinstance(cache_metadata, Mapping):
        return _truthy(cache_metadata.get("causal_cache_id")) or _truthy(
            cache_metadata.get("walk_forward_cache_id")
        )
    return False


def _is_negated(text: str, index: int) -> bool:
    window = text[max(0, index - 14) : index].lower()
    return any(marker in window for marker in NEGATION_MARKERS)


def find_misleading_probability_claims(texts: Iterable[str]) -> list[dict[str, Any]]:
    """Find non-negated probability claims that are disallowed in controlled UI."""

    findings: list[dict[str, Any]] = []
    for text_index, text in enumerate(texts):
        if not text:
            continue
        for phrase in MISLEADING_PROBABILITY_CLAIMS:
            start = 0
            while True:
                index = text.find(phrase, start)
                if index < 0:
                    break
                if not _is_negated(text, index):
                    findings.append(
                        {
                            "text_index": text_index,
                            "phrase": phrase,
                            "offset": index,
                            "context": text[max(0, index - 20) : index + len(phrase) + 20],
                        }
                    )
                start = index + len(phrase)
    return findings


def _overlay_policy_rows(policy: MutableMapping[str, Any], rows: Sequence[Mapping[str, Any]]) -> None:
    policy_rows = {str(row.get("policy_id")): dict(row) for row in rows if row.get("policy_id")}
    policy["policy_rows"] = policy_rows

    hsmm_numeric = policy_rows.get("hsmm_numeric_p_exit")
    if hsmm_numeric:
        policy["allow_numeric_p_exit_when_validated"] = bool(hsmm_numeric.get("allow_display"))

    hmm_posterior = policy_rows.get("hmm_posterior_probability")
    if hmm_posterior and hmm_posterior.get("display_mode") == "state_confidence_only":
        policy["hmm_posterior_semantic_role"] = "state_confidence"

    strategy = policy_rows.get("hmm_strategy_output")
    if strategy:
        policy["require_causal_cache_for_strategy"] = not bool(strategy.get("allow_display"))


def get_default_stage00_policy(db_path: str | Path | None = None) -> dict[str, Any]:
    """Return the built-in conservative policy, optionally overlaid by WP-A data."""

    policy: dict[str, Any] = {
        "stage": "00",
        "policy_name": "builtin_stage00_conservative",
        "policy_source": "builtin_conservative",
        "allow_numeric_p_exit_when_validated": False,
        "hmm_posterior_semantic_role": "state_confidence",
        "require_causal_cache_for_strategy": True,
        "allow_hsmm_internal_diagnostics": True,
        "allow_next_state_realized_tendency": True,
        "misleading_probability_claims": list(MISLEADING_PROBABILITY_CLAIMS),
    }

    if db_path is None:
        return policy

    path = Path(db_path)
    if not path.exists():
        policy["policy_source"] = "builtin_conservative_db_missing"
        policy["policy_load_warning"] = "ui_readiness_policy table not read because DB is missing"
        return policy

    try:
        import duckdb  # type: ignore

        with duckdb.connect(str(path), read_only=True) as con:
            tables = {
                row[0]
                for row in con.execute("select table_name from information_schema.tables").fetchall()
            }
            if "ui_readiness_policy" not in tables:
                policy["policy_source"] = "builtin_conservative_table_missing"
                policy["policy_load_warning"] = "ui_readiness_policy table does not exist"
                return policy

            rows = con.execute("select * from ui_readiness_policy").fetchall()
            columns = [desc[0] for desc in con.description or ()]
            items = [dict(zip(columns, row)) for row in rows]
            _overlay_policy_rows(policy, items)
            policy["policy_source"] = "db_overlay"
    except Exception as exc:  # pragma: no cover - depends on optional local DB/duckdb.
        policy["policy_source"] = "builtin_conservative_policy_read_failed"
        policy["policy_load_warning"] = f"failed to read ui_readiness_policy: {exc}"

    return policy


def evaluate_hmm_state_display(
    *,
    field_name: str = "state_label",
    state_source: str | None = None,
    context: str | None = None,
    semantic_role: str | None = None,
    display_label: str | None = None,
    evidence_level: str | None = None,
    policy: Mapping[str, Any] | None = None,
) -> ReadinessDecision:
    """Gate HMM state labels and posterior displays."""

    policy = policy or get_default_stage00_policy()
    field = _norm(field_name)
    source = _norm(state_source, UNKNOWN_SOURCE)
    ctx = _norm(context)
    role = _norm(semantic_role)
    label = display_label or ""
    evidence_level = _canonical_evidence_override(evidence_level)

    if "posterior" in field or "prob" in field:
        findings = find_misleading_probability_claims([label])
        if findings or (role and role not in {"state_confidence", "confidence"}):
            return _decision(
                "hide",
                False,
                evidence_level=evidence_level or "internal_diagnostic",
                readiness_status="blocked",
                state_source=source,
                semantic_role=role or "state_confidence",
                reason="blocked_misleading_probability_label",
                warnings=("hmm_posterior_not_return_probability", "blocked_misleading_probability_label"),
                metadata={"findings": findings, "policy_source": policy.get("policy_source")},
            )
        return _decision(
            "allow",
            True,
            evidence_level=evidence_level or "internal_diagnostic",
            readiness_status="internal_only",
            state_source=source,
            semantic_role="state_confidence",
            reason="allowed_state_confidence_only",
            metadata={"policy_source": policy.get("policy_source")},
        )

    if source in CAUSAL_SOURCES:
        return _decision(
            "allow",
            True,
            evidence_level=evidence_level or "internal_diagnostic",
            readiness_status="partial",
            state_source="causal_walk_forward",
            semantic_role="state_label",
            reason="State source is causal walk-forward.",
            metadata={"policy_source": policy.get("policy_source")},
        )

    if source in IN_SAMPLE_SOURCES or ctx in {"research", "in_sample_explanation", "research_only"}:
        return _decision(
            "research_only",
            True,
            evidence_level=evidence_level or "exploratory",
            readiness_status="research_only",
            state_source="in_sample_explanation",
            semantic_role="state_label",
            reason="In-sample states may be shown only as historical explanation.",
            warnings=("not_for_strategy_backtest",),
            metadata={"policy_source": policy.get("policy_source")},
        )

    return _decision(
        "warn",
        True,
        evidence_level=evidence_level or "exploratory",
        readiness_status="blocked",
        state_source=UNKNOWN_SOURCE,
        semantic_role="state_label",
        reason=UNKNOWN_SOURCE,
        warnings=("state_source_missing", UNKNOWN_SOURCE),
        metadata={"policy_source": policy.get("policy_source")},
    )


def evaluate_hmm_strategy_display(
    *,
    causal_cache_id: str | None = None,
    walk_forward_cache_id: str | None = None,
    cache_metadata: Mapping[str, Any] | None = None,
    baseline_passed: bool | None = None,
    evidence_level: str | None = None,
    readiness_status: str | None = None,
    policy: Mapping[str, Any] | None = None,
) -> ReadinessDecision:
    """Gate HMM strategy/backtest display behind causal cache metadata."""

    policy = policy or get_default_stage00_policy()
    metadata = {
        "causal_cache_id": causal_cache_id,
        "walk_forward_cache_id": walk_forward_cache_id,
        "cache_metadata": cache_metadata or {},
    }
    has_cache = _contains_causal_cache(metadata)
    evidence_level = _canonical_evidence_override(evidence_level)
    readiness_status = _canonical_readiness_override(readiness_status)

    if policy.get("require_causal_cache_for_strategy", True) and not has_cache:
        return _decision(
            "research_only",
            False,
            evidence_level=evidence_level or "exploratory",
            readiness_status="research_only",
            state_source=UNKNOWN_SOURCE,
            semantic_role="strategy_evaluation",
            reason="Strategy evaluation lacks causal walk-forward cache metadata.",
            warnings=("missing_causal_cache_id",),
            metadata={"policy_source": policy.get("policy_source")},
        )

    if baseline_passed is False:
        return _decision(
            "research_only",
            True,
            evidence_level=evidence_level or "validated_signal",
            readiness_status="partial",
            state_source="causal_walk_forward",
            semantic_role="strategy_evaluation",
            reason="research_signal",
            warnings=("baseline_not_passed", "research_signal"),
            metadata={"policy_source": policy.get("policy_source")},
        )

    return _decision(
        "allow",
        True,
        evidence_level=evidence_level or "validated_signal",
        readiness_status=readiness_status or "validated",
        state_source="causal_walk_forward",
        semantic_role="strategy_evaluation",
        reason="Strategy evaluation has causal cache metadata.",
        metadata={"policy_source": policy.get("policy_source")},
    )


def evaluate_hsmm_lifecycle_field_display(
    field_name: str,
    *,
    probability_status: str | None = None,
    readiness_status: str | None = None,
    semantic_role: str | None = None,
    value: Any = None,
    policy: Mapping[str, Any] | None = None,
) -> ReadinessDecision:
    """Gate HSMM lifecycle fields before UI display."""

    policy = policy or get_default_stage00_policy()
    field = _norm(field_name)
    prob_status = _norm(probability_status, "missing" if value is None else "unknown")
    readiness = _norm(readiness_status, "research_only")

    if field in STATE_AGE_FIELDS:
        return _decision(
            "allow",
            True,
            evidence_level="internal_diagnostic",
            readiness_status="internal_only",
            semantic_role="state_age",
            reason="HSMM state age is an allowed internal diagnostic.",
            metadata={"policy_source": policy.get("policy_source")},
        )

    if field in STATE_PHASE_FIELDS:
        return _decision(
            "allow",
            True,
            evidence_level="internal_diagnostic",
            readiness_status="internal_only",
            semantic_role="state_phase",
            reason="HSMM state phase is an allowed internal diagnostic.",
            metadata={"policy_source": policy.get("policy_source")},
        )

    if field.startswith("exit_tendency_"):
        return _decision(
            "allow",
            True,
            evidence_level="internal_diagnostic",
            readiness_status="internal_only",
            semantic_role="ordinal_exit_tendency",
            reason="HSMM exit tendency may be shown only as low/medium/high ordinal tendency.",
            metadata={"display_format": "ordinal_tendency", "policy_source": policy.get("policy_source")},
        )

    if field.startswith("next_state_tendency_"):
        return _decision(
            "allow",
            True,
            evidence_level="internal_diagnostic",
            readiness_status="internal_only",
            semantic_role="realized_historical_tendency",
            reason="Next-state tendency may only describe realized historical tendency.",
            metadata={"display_format": "ordinal_tendency", "policy_source": policy.get("policy_source")},
        )

    if is_numeric_p_exit_field(field):
        if prob_status in INVALID_PROBABILITY_STATUSES:
            return _decision(
                "hide",
                False,
                evidence_level="internal_diagnostic",
                readiness_status="blocked",
                semantic_role=semantic_role or "numeric_exit_probability",
                reason=f"hidden_due_to_{prob_status}_probability_status",
                warnings=("do_not_fill_missing_probability_with_zero", "hidden"),
                metadata={"policy_source": policy.get("policy_source"), "probability_status": prob_status},
            )

        allow_numeric = bool(policy.get("allow_numeric_p_exit_when_validated", False))
        if prob_status == "usable_probability" and readiness in VALIDATED_READINESS_STATUSES and allow_numeric:
            return _decision(
                "allow",
                True,
                evidence_level="validated_signal",
                readiness_status=readiness,
                semantic_role="usable_probability",
                reason="Numeric p_exit allowed by policy and validation metadata.",
                metadata={
                    "policy_source": policy.get("policy_source"),
                    "probability_evidence": "validated_probability",
                },
            )

        return _decision(
            "hide",
            False,
            evidence_level="internal_diagnostic",
            readiness_status="blocked",
            semantic_role=semantic_role or "numeric_exit_probability",
            reason="hidden_by_stage00_policy",
            warnings=("numeric_p_exit_requires_usable_probability_and_policy_allow", "hidden"),
            metadata={"policy_source": policy.get("policy_source")},
        )

    return _decision(
        "warn",
        False,
        evidence_level="exploratory",
        readiness_status="blocked",
        semantic_role=semantic_role or "unknown_field",
        reason="unknown_lifecycle_field",
        warnings=("unknown_lifecycle_field",),
        metadata={"policy_source": policy.get("policy_source")},
    )


def evaluate_state_source_boundary(
    state_sources: Iterable[str | None],
    *,
    require_causal: bool = False,
) -> ReadinessDecision:
    """Evaluate whether a UI dataset crosses the in-sample/causal boundary."""

    normalized = {_norm(source, UNKNOWN_SOURCE) for source in state_sources}
    if not normalized or normalized == {UNKNOWN_SOURCE}:
        return _decision(
            "warn",
            False,
            evidence_level="exploratory",
            readiness_status="blocked",
            state_source=UNKNOWN_SOURCE,
            semantic_role="state_source_boundary",
            reason=UNKNOWN_SOURCE,
            warnings=("state_source_missing", UNKNOWN_SOURCE),
        )

    has_causal = bool(normalized & CAUSAL_SOURCES)
    has_in_sample = bool(normalized & IN_SAMPLE_SOURCES)
    if has_causal and has_in_sample:
        return _decision(
            "block",
            False,
            evidence_level="exploratory",
            readiness_status="blocked",
            state_source="mixed",
            semantic_role="state_source_boundary",
            reason="blocked_mixed_state_source",
            warnings=("mixed_in_sample_and_causal_state_source", "blocked_mixed_state_source"),
            metadata={"state_sources": sorted(normalized)},
        )

    if require_causal and not has_causal:
        return _decision(
            "research_only",
            False,
            evidence_level="exploratory",
            readiness_status="research_only",
            state_source=next(iter(sorted(normalized))),
            semantic_role="state_source_boundary",
            reason="Causal state source is required but was not present.",
            warnings=("causal_state_source_required",),
            metadata={"state_sources": sorted(normalized)},
        )

    source = "causal_walk_forward" if has_causal else "in_sample_explanation"
    return _decision(
        "allow" if has_causal else "research_only",
        True,
        evidence_level="internal_diagnostic" if has_causal else "exploratory",
        readiness_status="partial" if has_causal else "research_only",
        state_source=source,
        semantic_role="state_source_boundary",
        reason="State source boundary is internally consistent.",
        metadata={"state_sources": sorted(normalized)},
    )


def build_readiness_audit(db_path: str | Path | None = None) -> dict[str, Any]:
    """Build a read-only Stage 00 UI readiness audit summary."""

    db = Path(db_path) if db_path else None
    policy = get_default_stage00_policy(db)
    used_db = bool(db and db.exists())
    status = "skipped_db_missing" if db and not db.exists() else "policy_only"
    if used_db:
        status = "policy_loaded"

    return {
        "wp": "STAGE00_WP_C_ui_readiness_causal_boundary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "db_path": str(db) if db else None,
        "used_db": used_db,
        "external_data_fetch": False,
        "policy_source": policy.get("policy_source"),
        "numeric_p_exit_displayed": False,
        "causal_in_sample_mix_found": False,
        "notes": [
            "Stage 00 audit is read-only.",
            "Numeric p_exit is hidden unless a future policy explicitly allows validated usable probability.",
            "No external data was fetched.",
        ],
    }


def write_readiness_audit_report(audit: Mapping[str, Any], output: str | Path) -> tuple[Path, Path]:
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    json_path = output_path.with_suffix(".json")

    lines = [
        "# Stage 00 WP-C UI Readiness Audit",
        "",
        f"WP: {audit['wp']}",
        f"Status: {audit['status']}",
        f"DB path: {audit.get('db_path') or 'not provided'}",
        f"Used local DB: {'yes' if audit.get('used_db') else 'no'}",
        "External data fetch: no",
        f"Policy source: {audit.get('policy_source')}",
        f"Numeric p_exit displayed: {'yes' if audit.get('numeric_p_exit_displayed') else 'no'}",
        f"Causal/in-sample mix found: {'yes' if audit.get('causal_in_sample_mix_found') else 'no'}",
        "",
        "## Notes",
    ]
    lines.extend(f"- {note}" for note in audit.get("notes", []))
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    json_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output_path, json_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Stage 00 UI readiness audit.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--audit-lifecycle", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)

    audit = build_readiness_audit(args.db)
    if args.audit_lifecycle:
        audit["audit_lifecycle"] = True
    write_readiness_audit_report(audit, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
