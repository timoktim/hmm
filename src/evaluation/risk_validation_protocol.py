"""Stage03R WP8 risk validation protocol.

This module emits a pre-registered validation protocol for Stage03R outputs.
It does not fetch data, train models, tune thresholds, consume the final
holdout, use HSMM numeric p_exit as a decision input, or create any decision
surface.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


INDEX_ID = "STAGE03R-WP8"
PROTOCOL_VERSION = "risk_validation_protocol_v1"
EXPECTED_HORIZONS = (1, 3, 5, 10, 20)
READINESS_STATUSES = (
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
)
HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY = "diagnostic_only_not_decision_input"
HSMM_DIAGNOSTIC_COUNT_FIELD = "hsmm_lifecycle_probability_status_counts_diagnostic_only"
LEGACY_HSMM_COMPARISON_FIELD = "hsmm_probability_status_counts"
FORBIDDEN_PROTOCOL_TERMS = (
    "decision_ready",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
)
BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "training_algorithm_modified": "no",
    "HMM_HSMM_retrained": "no",
    "HSMM_p_exit_used_for_decision": "no",
    "decision_surface_output": "no",
    "downside_action_overlay_output": "no",
    "DuckDB_committed": "no",
}


@dataclass
class RiskValidationProtocolResult:
    status: str
    protocol_version: str
    executive_protocol_verdict: str
    input_artifacts: dict[str, Any]
    readiness_status_summary: dict[str, Any]
    semantic_cleanup_summary: dict[str, Any]
    pre_registered_metrics: list[dict[str, Any]]
    split_and_final_holdout_discipline: dict[str, Any]
    validation_rules_by_readiness_status: dict[str, Any]
    baseline_comparison_rules: dict[str, Any]
    hsmm_interpretation_only_rules: dict[str, Any]
    failure_abstain_rules: dict[str, Any]
    what_wp8_does_not_do: list[str]
    wp10_handoff_contract: dict[str, Any]
    local_db_validation: dict[str, Any]
    boundary_flags: dict[str, str] = field(default_factory=lambda: dict(BOUNDARY_FLAGS))
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["index_id"] = INDEX_ID
        return data


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _readiness_rows(hazard_readiness: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(row) for row in hazard_readiness.get("readiness_rows", [])]


def _readiness_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in READINESS_STATUSES}
    for row in rows:
        status = str(row.get("readiness_status", "invalid"))
        counts[status] = counts.get(status, 0) + 1
    return {status: int(counts.get(status, 0)) for status in READINESS_STATUSES}


def _readiness_by_horizon(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for horizon in EXPECTED_HORIZONS:
        subset = [row for row in rows if _as_int(row.get("horizon_days")) == horizon]
        out[str(horizon)] = _readiness_counts(subset)
    return out


def _sample_support_by_horizon(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon in EXPECTED_HORIZONS:
        subset = [row for row in rows if _as_int(row.get("horizon_days")) == horizon]
        counts = [_as_int(row.get("sample_count")) for row in subset]
        positives = [_as_int(row.get("positive_count")) for row in subset]
        out[str(horizon)] = {
            "slice_count": len(subset),
            "min_sample_count": min(counts) if counts else 0,
            "total_sample_count": sum(counts),
            "total_positive_count": sum(positives),
        }
    return out


def _normalise_hsmm_diagnostic_counts(hazard_vs_hsmm: Mapping[str, Any]) -> tuple[dict[str, dict[str, int]], bool]:
    by_horizon: dict[str, dict[str, int]] = {}
    legacy_field_present = False
    for row in hazard_vs_hsmm.get("hazard_vs_hsmm_by_horizon", []):
        horizon = str(row.get("horizon_days"))
        diagnostic_counts = row.get(HSMM_DIAGNOSTIC_COUNT_FIELD)
        if diagnostic_counts is None:
            diagnostic_counts = row.get(LEGACY_HSMM_COMPARISON_FIELD, {})
            legacy_field_present = legacy_field_present or LEGACY_HSMM_COMPARISON_FIELD in row
        by_horizon[horizon] = {str(key): _as_int(value) for key, value in dict(diagnostic_counts or {}).items()}

    hsmm = hazard_vs_hsmm.get("hsmm_lifecycle_availability", {})
    for horizon, row in dict(hsmm.get("per_horizon", {})).items():
        diagnostic_counts = row.get("lifecycle_probability_status_counts_diagnostic_only")
        if diagnostic_counts is None:
            diagnostic_counts = row.get("probability_status_counts", {})
            legacy_field_present = legacy_field_present or "probability_status_counts" in row
        by_horizon.setdefault(str(horizon), {str(key): _as_int(value) for key, value in dict(diagnostic_counts or {}).items()})
    return by_horizon, legacy_field_present


def _local_db_validation(db_path: str | None) -> dict[str, Any]:
    if not db_path:
        return {
            "db_path_used": None,
            "db_found": "no",
            "opened_read_only": "no",
            "key_tables_checked": [],
            "row_counts": {},
            "protocol_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }

    path = Path(db_path)
    safe_path = _safe_source_path(path)
    if not path.exists():
        return {
            "db_path_used": safe_path,
            "db_found": "no",
            "opened_read_only": "no",
            "key_tables_checked": ["hsmm_lifecycle_ui_daily"],
            "row_counts": {},
            "protocol_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }

    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        return {
            "db_path_used": safe_path,
            "db_found": "yes",
            "opened_read_only": "no",
            "open_error": str(exc),
            "key_tables_checked": ["hsmm_lifecycle_ui_daily"],
            "row_counts": {},
            "protocol_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }

    try:
        row_counts: dict[str, int] = {}
        for table in ["hsmm_lifecycle_ui_daily"]:
            try:
                row_counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
            except Exception:
                row_counts[table] = 0
        return {
            "db_path_used": safe_path,
            "db_found": "yes",
            "opened_read_only": "yes",
            "key_tables_checked": list(row_counts),
            "row_counts": row_counts,
            "protocol_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    finally:
        try:
            con.close()
        except Exception:
            pass


def _pre_registered_metrics() -> list[dict[str, Any]]:
    return [
        {
            "metric": "brier_score",
            "scope": "per horizon/state/age_bucket readiness slice",
            "rule": "calibrated hazard must not worsen raw hazard Brier; where a valid age-bucket baseline exists, it must not worsen that baseline.",
        },
        {
            "metric": "log_loss",
            "scope": "valid non-degenerate slices only",
            "rule": "compute only when labels and probabilities are inside valid numeric bounds; invalid or degenerate slices abstain from this metric.",
        },
        {
            "metric": "expected_calibration_error",
            "scope": "validation folds and WP10 final-gate holdout",
            "rule": "track calibration error with sample support; do not tune on the final holdout outside WP10.",
        },
        {
            "metric": "directional_separation",
            "scope": "event vs non-event ranking diagnostics",
            "rule": "higher exit tendency should separate realized exits from non-exits without replacing calibration checks.",
        },
        {
            "metric": "false_confidence_overconfidence",
            "scope": "high-probability bins and sparse slices",
            "rule": "flag confident probabilities that are poorly supported, miscalibrated, or worse than baseline.",
        },
        {
            "metric": "drawdown_downside_proxy",
            "scope": "only if already available in causal inputs",
            "rule": "summarize downside exposure descriptively; do not create an action overlay.",
        },
        {
            "metric": "abstain_coverage",
            "scope": "all horizons and readiness statuses",
            "rule": "measure how often the protocol abstains because slices are baseline-only, ordinal-only, insufficient, invalid, or HSMM-only context.",
        },
        {
            "metric": "sample_support",
            "scope": "horizon/state/age_bucket/profile policy",
            "rule": "report sample_count, positive_count, negative_count, event_rate, and censoring limitations before any future promotion.",
        },
    ]


def _validation_rules() -> dict[str, Any]:
    return {
        "usable_probability": {
            "candidate_use": "local calibrated hazard probability only",
            "pass_rule": "pass only if calibrated hazard does not worsen raw Brier and does not worsen valid age-bucket baseline Brier.",
            "block_rule": "block or downgrade if support is sparse, calibration worsens, or baseline remains stronger.",
            "wp8_action": "pre-register validation; no final promotion decision is made here.",
        },
        "baseline_only": {
            "candidate_use": "age-bucket empirical baseline remains the numeric fallback",
            "pass_rule": "remain baseline-only unless future registered evidence supports hazard promotion.",
            "block_rule": "do not convert to hazard probability in WP8.",
        },
        "ordinal_only": {
            "candidate_use": "ordinal tendency or qualitative lifecycle context",
            "pass_rule": "retain non-numeric tendency; no numeric probability is fabricated.",
            "block_rule": "block numeric use until sample and calibration evidence exist.",
        },
        "insufficient_sample": {
            "candidate_use": "abstain",
            "pass_rule": "abstain is the only valid output.",
            "block_rule": "any numeric promotion blocks the protocol.",
        },
        "invalid": {
            "candidate_use": "blocked evidence",
            "pass_rule": "invalid rows cannot be consumed by WP10 except as failure evidence.",
            "block_rule": "schema, leakage, or impossible metric violations block the slice.",
        },
    }


def evaluate_risk_validation_protocol(
    *,
    hazard_readiness: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    hazard_verdict_text: str = "",
    db_path: str | None = None,
    input_artifacts: Mapping[str, Any] | None = None,
) -> RiskValidationProtocolResult:
    rows = _readiness_rows(hazard_readiness)
    counts = _readiness_counts(rows)
    diagnostic_counts_by_horizon, legacy_field_present = _normalise_hsmm_diagnostic_counts(hazard_vs_hsmm)
    baseline_majority = counts.get("baseline_only", 0) > counts.get("usable_probability", 0)
    local_usability = counts.get("usable_probability", 0) > 0

    readiness_summary = {
        "readiness_version": hazard_readiness.get("readiness_version"),
        "row_count": sum(counts.values()),
        "counts": counts,
        "by_horizon": _readiness_by_horizon(rows),
        "sample_support_by_horizon": _sample_support_by_horizon(rows),
        "hazard_locally_usable": "yes" if local_usability else "no",
        "hazard_broadly_promoted": "no",
        "baseline_only_majority": "yes" if baseline_majority else "no",
    }
    semantic_cleanup = {
        "hsmm_lifecycle_probability_status_policy": HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
        "diagnostic_count_field": HSMM_DIAGNOSTIC_COUNT_FIELD,
        "legacy_ambiguous_comparison_field_present_in_input": "yes" if legacy_field_present else "no",
        "unqualified_hsmm_lifecycle_status_in_protocol_summary": "no",
        "hsmm_lifecycle_probability_status_counts_diagnostic_only_by_horizon": diagnostic_counts_by_horizon,
        "interpretation": "HSMM lifecycle status labels are diagnostic UI lifecycle labels, not hazard readiness approvals.",
    }
    hsmm_rules = {
        "responsibility": "state age, lifecycle phase, duration profile, and ordinal exit tendency context",
        "numeric_probability_policy": "HSMM numeric p_exit is not a decision input in Stage03R WP8.",
        "lifecycle_probability_status_policy": HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
        "diagnostic_count_field": HSMM_DIAGNOSTIC_COUNT_FIELD,
        "allowed_wp8_use": "context only; may be cited as lifecycle interpretation evidence for WP10.",
        "forbidden_wp8_use": "do not use HSMM raw or calibrated p_exit to rank, size, gate, or promote hazard slices.",
    }
    final_holdout = {
        "validation_folds": "calibration diagnostics may use validation folds.",
        "final_holdout_consumption": "final holdout can be consumed only by an explicit WP10 final-gate run.",
        "repeated_final_tuning_forbidden": "yes",
        "threshold_tuning_in_wp8": "no",
        "trial_accounting_required": "yes for any future model comparison before WP10.",
    }
    baseline_rules = {
        "valid_baseline_required_fields": [
            "age_bucket_baseline_brier",
            "age_bucket_baseline_sample_count",
            "age_bucket_baseline_event_rate",
        ],
        "comparison_rule": "usable hazard probability can pass only when calibrated hazard is not worse than a valid age-bucket baseline.",
        "baseline_only_policy": "baseline-only remains baseline-only unless future registered evidence supports promotion.",
        "current_majority_status": "baseline_only_majority" if baseline_majority else "review_slice_level_evidence",
    }
    failure_rules = {
        "insufficient_sample": "abstain and report sample ceiling.",
        "invalid": "block and report validation failure.",
        "ordinal_only": "retain ordinal tendency; do not fabricate numeric probability.",
        "hsmm_interpretation_only": "context only; not a numeric approval source.",
        "false_confidence": "block or downgrade confident probabilities that fail calibration, support, or baseline checks.",
    }
    wp10_handoff = {
        "contract_version": "wp10_final_gate_handoff_v1",
        "required_inputs": [
            "hazard_readiness_matrix_report.json",
            "hazard_vs_hsmm_report.json",
            "risk_validation_protocol.json",
            "explicit final holdout artifact generated once for WP10",
        ],
        "required_protocol_fields": [
            "readiness_status_summary",
            "semantic_cleanup_summary",
            "pre_registered_metrics",
            "split_and_final_holdout_discipline",
            "validation_rules_by_readiness_status",
            "baseline_comparison_rules",
            "hsmm_interpretation_only_rules",
            "failure_abstain_rules",
            "boundary_flags",
        ],
        "final_gate_allowed_actions": [
            "evaluate pre-registered metrics on final holdout once",
            "emit pass, block, or defer by readiness status",
            "preserve abstain for unsupported slices",
        ],
        "final_gate_forbidden_actions": [
            "tune on final holdout",
            "expand HSMM numeric p_exit responsibility",
            "claim broad hazard superiority without slice evidence",
        ],
    }
    warnings = [
        "WP8 pre-registers validation only; it does not consume the final holdout.",
        "Hazard probability remains local-slice usable only.",
    ]
    if baseline_majority:
        warnings.append("baseline-only remains the majority readiness status.")
    if hazard_vs_hsmm.get("hsmm_lifecycle_availability", {}).get("matched_numeric_artifact") == "missing":
        warnings.append("matched HSMM numeric p_exit artifact remains missing.")

    return RiskValidationProtocolResult(
        status="pass" if rows else "partial",
        protocol_version=PROTOCOL_VERSION,
        executive_protocol_verdict=(
            "Stage03R WP8 is a pre-registered validation protocol. Hazard is locally usable, "
            "not broadly promoted; baseline-only and abstain rules remain conservative; HSMM "
            "lifecycle outputs remain interpretation-only."
        ),
        input_artifacts=dict(input_artifacts or {}),
        readiness_status_summary=readiness_summary,
        semantic_cleanup_summary=semantic_cleanup,
        pre_registered_metrics=_pre_registered_metrics(),
        split_and_final_holdout_discipline=final_holdout,
        validation_rules_by_readiness_status=_validation_rules(),
        baseline_comparison_rules=baseline_rules,
        hsmm_interpretation_only_rules=hsmm_rules,
        failure_abstain_rules=failure_rules,
        what_wp8_does_not_do=[
            "No external data fetch.",
            "No HMM or HSMM retraining.",
            "No training algorithm modification.",
            "No threshold tuning.",
            "No repeated final holdout evaluation.",
            "No trading command, position sizing, ranking, or decision surface.",
            "No HSMM numeric p_exit expansion.",
        ],
        wp10_handoff_contract=wp10_handoff,
        local_db_validation=_local_db_validation(db_path),
        warnings=warnings,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP8 Risk Validation Protocol",
        "",
        "## Executive protocol verdict",
        "",
        str(summary.get("executive_protocol_verdict")),
        "",
        "## Input artifacts and versions",
        "",
        "```json",
        json.dumps(summary.get("input_artifacts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Readiness status summary",
        "",
        "```json",
        json.dumps(summary.get("readiness_status_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Semantic cleanup / HSMM diagnostic namespace",
        "",
        "```json",
        json.dumps(summary.get("semantic_cleanup_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Pre-registered metrics",
        "",
        "```json",
        json.dumps(summary.get("pre_registered_metrics", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Split and final holdout discipline",
        "",
        "```json",
        json.dumps(summary.get("split_and_final_holdout_discipline", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Validation rules by readiness status",
        "",
        "```json",
        json.dumps(summary.get("validation_rules_by_readiness_status", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Baseline comparison rules",
        "",
        "```json",
        json.dumps(summary.get("baseline_comparison_rules", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## HSMM interpretation-only rules",
        "",
        "```json",
        json.dumps(summary.get("hsmm_interpretation_only_rules", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Failure / abstain rules",
        "",
        "```json",
        json.dumps(summary.get("failure_abstain_rules", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## What WP8 does not do",
        "",
        "```json",
        json.dumps(summary.get("what_wp8_does_not_do", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary confirmation",
        "",
        "```json",
        json.dumps(summary.get("boundary_flags", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## WP10 handoff contract",
        "",
        "```json",
        json.dumps(summary.get("wp10_handoff_contract", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Local DB validation",
        "",
        "```json",
        json.dumps(summary.get("local_db_validation", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Warnings",
        "",
        "```json",
        json.dumps(summary.get("warnings", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: RiskValidationProtocolResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def run_cli(args: argparse.Namespace) -> int:
    hazard_readiness = _load_json(Path(args.hazard_readiness))
    hazard_vs_hsmm = _load_json(Path(args.hazard_vs_hsmm))
    verdict_path = Path(args.hazard_verdict) if args.hazard_verdict else None
    verdict_text = verdict_path.read_text(encoding="utf-8") if verdict_path and verdict_path.exists() else ""
    result = evaluate_risk_validation_protocol(
        hazard_readiness=hazard_readiness,
        hazard_vs_hsmm=hazard_vs_hsmm,
        hazard_verdict_text=verdict_text,
        db_path=args.db,
        input_artifacts={
            "hazard_readiness": _safe_source_path(Path(args.hazard_readiness)),
            "hazard_vs_hsmm": _safe_source_path(Path(args.hazard_vs_hsmm)),
            "hazard_verdict": _safe_source_path(verdict_path),
            "hazard_readiness_version": hazard_readiness.get("readiness_version"),
            "hazard_vs_hsmm_report_version": hazard_vs_hsmm.get("report_version"),
            "hazard_verdict_present": "yes" if verdict_text else "no",
            "no_fetch": "yes" if args.no_fetch else "not_requested_but_no_fetch_performed",
        },
    )
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R WP8 risk validation protocol")
    parser.add_argument("--hazard-readiness", required=True, help="WP6 hazard readiness JSON")
    parser.add_argument("--hazard-vs-hsmm", required=True, help="WP7 hazard vs HSMM JSON")
    parser.add_argument("--hazard-verdict", default=None, help="WP6.1 multi-horizon hazard verdict markdown")
    parser.add_argument("--db", default=None, help="Optional local DuckDB path for read-only protocol evidence")
    parser.add_argument("--run-id", default="latest")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
