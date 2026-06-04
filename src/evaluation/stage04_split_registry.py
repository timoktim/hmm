"""Stage04 WP0 split registry and prospective validation lock.

This module freezes the accepted Stage03R evidence boundary and defines the
prospective holdout policy for later Stage04 validation. It reads committed
Stage03R reports only; it does not fetch data, retrain models, tune thresholds,
or consume a final holdout.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence


INDEX_ID = "STAGE04-WP0"
REGISTRY_VERSION = "stage04_split_registry_v1"
LEDGER_SCHEMA_VERSION = "stage04_prospective_validation_ledger_v1"
EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
FORBIDDEN_OUTPUT_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]
DENIAL_FLAG_ALLOWLIST = {
    "decision_surface_output",
    "trading_output",
}


@dataclass(frozen=True)
class Stage04Paths:
    final_holdout_artifact: Path
    final_gate_report: Path
    risk_protocol: Path
    hazard_readiness: Path
    data_quality: Path
    hazard_vs_hsmm: Path
    age_bucket_baseline: Path
    hazard_calibration: Path
    hazard_baseline: Path
    exit_target_dataset: Path
    target_leakage_audit: Path


def default_stage04_paths(root: Path) -> Stage04Paths:
    stage03r = root / "reports/stage03r"
    return Stage04Paths(
        final_holdout_artifact=stage03r / "final_holdout_artifact.json",
        final_gate_report=stage03r / "stage03r_final_gate_report.json",
        risk_protocol=stage03r / "risk_validation_protocol.json",
        hazard_readiness=stage03r / "hazard_readiness_matrix_report.json",
        data_quality=stage03r / "data_quality_ci_report.json",
        hazard_vs_hsmm=stage03r / "hazard_vs_hsmm_report.json",
        age_bucket_baseline=stage03r / "age_bucket_baseline_report.json",
        hazard_calibration=stage03r / "hazard_isotonic_calibration_report.json",
        hazard_baseline=stage03r / "duration_hazard_logistic_baseline_report.json",
        exit_target_dataset=stage03r / "exit_target_dataset_v1_report.json",
        target_leakage_audit=stage03r / "target_leakage_purge_audit.json",
    )


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _safe_source_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _git_head(root: Path) -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except Exception:
        return "unknown"


def _as_date(value: Any) -> date | None:
    if value in {None, ""}:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_yes(value: Any) -> bool:
    return value in {"yes", "true", "1", True, 1}


def _artifact_version(data: Mapping[str, Any]) -> str | None:
    for key in [
        "artifact_version",
        "final_gate_version",
        "protocol_version",
        "readiness_version",
        "report_version",
        "baseline_version",
        "calibration_version",
        "model_version",
        "target_definition_version",
    ]:
        value = data.get(key)
        if value:
            return str(value)
    return None


def _forbidden_output_hits(value: Any) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in DENIAL_FLAG_ALLOWLIST and child == "no":
                continue
            for term in FORBIDDEN_OUTPUT_TERMS:
                if term in key_text:
                    hits.append(f"key:{term}:{key_text}")
            hits.extend(_forbidden_output_hits(child))
    elif isinstance(value, list):
        for child in value:
            hits.extend(_forbidden_output_hits(child))
    elif isinstance(value, str):
        for term in FORBIDDEN_OUTPUT_TERMS:
            if term in value:
                hits.append(f"value:{term}:{value[:80]}")
    return hits


def _label_completeness(candidate: Mapping[str, Any]) -> tuple[bool, list[int]]:
    raw = candidate.get("label_completeness_by_horizon", {})
    complete: dict[int, bool] = {}
    if isinstance(raw, Mapping):
        for horizon, value in raw.items():
            complete[_as_int(horizon)] = bool(value)
    missing = [horizon for horizon in EXPECTED_HORIZONS if not complete.get(horizon, False)]
    return not missing, missing


def evaluate_prospective_holdout_candidate(
    registry: Mapping[str, Any],
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate whether a future holdout candidate satisfies the Stage04 lock."""

    blocking_issues: list[str] = []
    defer_reasons: list[str] = []
    cutoff = _as_date(registry.get("evidence_cutoff_date"))
    start = _as_date(candidate.get("holdout_start_date"))

    if start is None:
        defer_reasons.append("candidate holdout_start_date is missing or invalid")
    elif cutoff is not None and start <= cutoff:
        blocking_issues.append("holdout_start_date must be strictly after evidence_cutoff_date")

    if _as_int(candidate.get("consumption_count")) > 1:
        blocking_issues.append("final holdout consumption count exceeds one")
    if _as_yes(candidate.get("threshold_tuning_after_lock")):
        blocking_issues.append("threshold tuning after split lock detected")
    if _as_yes(candidate.get("model_retrained_in_locked_evaluation_path")):
        blocking_issues.append("model retraining inside locked evaluation path detected")
    if _as_yes(candidate.get("final_holdout_consumed")):
        blocking_issues.append("WP0 cannot consume final holdout")

    complete, missing_horizons = _label_completeness(candidate)
    if not complete:
        defer_reasons.append(f"labels are incomplete for horizons {missing_horizons}")

    forbidden_hits = _forbidden_output_hits(candidate)
    if forbidden_hits:
        blocking_issues.append(f"forbidden decision/trading output terms detected: {forbidden_hits[:5]}")

    status = "eligible"
    if blocking_issues:
        status = "blocked"
    elif defer_reasons:
        status = "defer"

    return {
        "status": status,
        "blocking_issues": sorted(set(blocking_issues)),
        "defer_reasons": sorted(set(defer_reasons)),
        "evidence_cutoff_date": registry.get("evidence_cutoff_date"),
        "holdout_start_date": candidate.get("holdout_start_date"),
        "label_completeness_required_horizons": EXPECTED_HORIZONS,
        "final_holdout_consumed": "no",
        "decision_surface_output": "no",
        "trading_output": "no",
    }


def build_split_registry(
    *,
    root: Path,
    frozen_stage03r_commit: str | None = None,
    ledger_template_path: str = "reports/stage04/prospective_validation_ledger.jsonl",
) -> dict[str, Any]:
    paths = default_stage04_paths(root)
    artifacts = {
        "final_holdout_artifact": _load_json(paths.final_holdout_artifact),
        "final_gate": _load_json(paths.final_gate_report),
        "risk_protocol": _load_json(paths.risk_protocol),
        "hazard_readiness_matrix": _load_json(paths.hazard_readiness),
        "data_quality_ci": _load_json(paths.data_quality),
        "hazard_vs_hsmm": _load_json(paths.hazard_vs_hsmm),
        "age_bucket_baseline": _load_json(paths.age_bucket_baseline),
        "hazard_isotonic_calibration": _load_json(paths.hazard_calibration),
        "duration_hazard_logistic": _load_json(paths.hazard_baseline),
        "exit_target_dataset": _load_json(paths.exit_target_dataset),
        "target_leakage_purge_audit": _load_json(paths.target_leakage_audit),
    }
    final_holdout = artifacts["final_holdout_artifact"]
    final_gate = artifacts["final_gate"]
    non_overlap = final_holdout.get("non_overlap_evidence", {})
    max_validation_end = non_overlap.get("max_reconstructed_validation_end_date")
    evidence_cutoff = str(max_validation_end or final_holdout.get("holdout_end_date"))
    cutoff_date = _as_date(evidence_cutoff)
    min_start = (cutoff_date + timedelta(days=1)).isoformat() if cutoff_date else None

    accepted_versions = {
        name: {
            "version": _artifact_version(data),
            "status": data.get("status"),
            "index_id": data.get("index_id"),
        }
        for name, data in artifacts.items()
    }

    registry = {
        "registry_version": REGISTRY_VERSION,
        "index_id": INDEX_ID,
        "status": "locked",
        "frozen_stage03r_commit": frozen_stage03r_commit or _git_head(root),
        "frozen_stage03r_merge_pr": "#51",
        "evidence_cutoff_date": evidence_cutoff,
        "evidence_cutoff_source": "max_reconstructed_validation_end_date from Stage03R WP10.1 non-overlap evidence",
        "max_reconstructed_validation_end_date": max_validation_end,
        "accepted_artifact_versions": accepted_versions,
        "stage03r_final_gate": {
            "engineering_gate_verdict": final_gate.get("engineering_gate_verdict"),
            "empirical_promotion_verdict": final_gate.get("empirical_promotion_verdict"),
            "final_verdict": final_gate.get("final_verdict"),
            "defer_reasons": final_gate.get("defer_reasons", []),
        },
        "stage03r_final_holdout_candidate": {
            "holdout_status": final_holdout.get("holdout_status"),
            "holdout_start_date": final_holdout.get("holdout_start_date"),
            "holdout_end_date": final_holdout.get("holdout_end_date"),
            "non_overlap_status": final_holdout.get("non_overlap_status"),
            "candidate_overlaps_reconstructed_prior_validation": non_overlap.get(
                "candidate_overlaps_reconstructed_prior_validation"
            ),
            "consumption_count": final_holdout.get("consumption_count"),
            "empirical_promotion_verdict": final_holdout.get("empirical_promotion_verdict"),
        },
        "future_holdout_policy": {
            "holdout_start_rule": "strictly_after_evidence_cutoff_date",
            "minimum_candidate_holdout_start_date": min_start,
            "required_label_horizons": EXPECTED_HORIZONS,
            "labels_must_be_complete": "yes",
            "no_threshold_tuning_after_lock": "yes",
            "no_model_retraining_inside_locked_evaluation_path": "yes",
            "final_holdout_consumption_count_starts_at": 0,
            "final_holdout_consumed_in_wp0": "no",
            "external_data_fetch": "no",
            "locked_evaluation_path": "prospective_only",
        },
        "prospective_validation_ledger": {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "template_path": ledger_template_path,
            "local_daily_records_path": "reports/stage04/prospective_validation_ledger.local.jsonl",
            "committed_template_allowed": "yes",
            "daily_local_records_gitignored": "yes",
            "append_only": "yes",
            "record_types": ["template", "candidate_check", "label_completeness_check", "consumption_event"],
        },
        "boundary_flags": {
            "external_data_fetch": "no",
            "training_algorithm_modified": "no",
            "model_retrained": "no",
            "HMM_HSMM_retrained": "no",
            "threshold_tuning": "no",
            "final_holdout_consumed": "no",
            "final_holdout_consumption_count": 0,
            "HSMM_p_exit_used_for_decision": "no",
            "decision_surface_output": "no",
            "trading_output": "no",
            "DuckDB_committed": "no",
        },
        "eligibility_rule_summary": (
            "A future holdout is eligible only when its start date is strictly after "
            f"{evidence_cutoff}, labels are complete for horizons {EXPECTED_HORIZONS}, "
            "and no threshold tuning, retraining, final-holdout consumption, or decision output occurs after lock."
        ),
        "blocking_issues": [],
        "defer_reasons": [],
    }

    forbidden_hits = _forbidden_output_hits(registry)
    if forbidden_hits:
        registry["blocking_issues"] = [f"registry contains forbidden output terms: {forbidden_hits[:5]}"]
        registry["status"] = "blocked"
    return registry


def build_ledger_template(registry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "record_type": "template",
        "schema_version": LEDGER_SCHEMA_VERSION,
        "registry_version": registry.get("registry_version"),
        "index_id": registry.get("index_id"),
        "frozen_stage03r_commit": registry.get("frozen_stage03r_commit"),
        "evidence_cutoff_date": registry.get("evidence_cutoff_date"),
        "required_label_horizons": EXPECTED_HORIZONS,
        "final_holdout_consumed": "no",
        "consumption_count": 0,
        "external_data_fetch": "no",
        "daily_records_policy": (
            "Keep local daily records in reports/stage04/prospective_validation_ledger.local.jsonl; "
            "the committed file is a schema template."
        ),
    }


def build_report_markdown(registry: Mapping[str, Any]) -> str:
    sections = [
        "# Stage04 WP0 Split Registry",
        "",
        f"status: {registry.get('status')}",
        f"registry_version: {registry.get('registry_version')}",
        f"frozen_stage03r_commit: {registry.get('frozen_stage03r_commit')}",
        f"evidence_cutoff_date: {registry.get('evidence_cutoff_date')}",
        f"max_reconstructed_validation_end_date: {registry.get('max_reconstructed_validation_end_date')}",
        "final_holdout_consumed: no",
        "",
        "## Future Holdout Policy",
        "",
        "```json",
        json.dumps(registry.get("future_holdout_policy", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Stage03R Evidence Boundary",
        "",
        "```json",
        json.dumps(
            {
                "stage03r_final_gate": registry.get("stage03r_final_gate", {}),
                "stage03r_final_holdout_candidate": registry.get("stage03r_final_holdout_candidate", {}),
                "accepted_artifact_versions": registry.get("accepted_artifact_versions", {}),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        "```",
        "",
        "## Prospective Validation Ledger",
        "",
        "```json",
        json.dumps(registry.get("prospective_validation_ledger", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Boundary Flags",
        "",
        "```json",
        json.dumps(registry.get("boundary_flags", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## Eligibility Rule",
        "",
        str(registry.get("eligibility_rule_summary")),
    ]
    return "\n".join(sections) + "\n"


def write_outputs(registry: Mapping[str, Any], output: Path, summary_json: Path, ledger_template: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    ledger_template.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(registry), encoding="utf-8")
    summary_json.write_text(json.dumps(registry, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    ledger_template.write_text(
        json.dumps(build_ledger_template(registry), ensure_ascii=False, default=_json_default) + "\n",
        encoding="utf-8",
    )


def run_cli(args: argparse.Namespace) -> int:
    root = Path(args.root)
    registry = build_split_registry(
        root=root,
        frozen_stage03r_commit=args.frozen_stage03r_commit,
        ledger_template_path=args.ledger_template,
    )
    write_outputs(
        registry,
        Path(args.output),
        Path(args.summary_json),
        Path(args.ledger_template),
    )
    return 1 if registry.get("status") == "blocked" else 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage04 WP0 split registry")
    parser.add_argument("--root", default=".")
    parser.add_argument("--frozen-stage03r-commit", default=None)
    parser.add_argument("--output", default="reports/stage04/split_registry.md")
    parser.add_argument("--summary-json", default="reports/stage04/split_registry.json")
    parser.add_argument("--ledger-template", default="reports/stage04/prospective_validation_ledger.jsonl")
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    return run_cli(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
