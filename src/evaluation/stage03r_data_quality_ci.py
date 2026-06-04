"""Stage03R WP9 data-quality CI invariants.

This module checks committed Stage03R public artifacts for CI-safe invariants.
It does not fetch data, train models, tune thresholds, consume final holdout,
or require a private DuckDB. When a local DuckDB path is provided and exists,
only aggregate read-only table counts are recorded.
"""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


INDEX_ID = "STAGE03R-WP9"
REPORT_VERSION = "data_quality_ci_invariants_v1"
EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
READINESS_STATUSES = {
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
}
HSMM_DIAGNOSTIC_COUNT_FIELD = "hsmm_lifecycle_probability_status_counts_diagnostic_only"
HSMM_DIAGNOSTIC_POLICY = "diagnostic_only_not_decision_input"
LEGACY_HSMM_STATUS_FIELD = "hsmm_probability_status_counts"
REQUIRED_RISK_PROTOCOL_FIELDS = [
    "pre_registered_metrics",
    "split_and_final_holdout_discipline",
    "validation_rules_by_readiness_status",
    "baseline_comparison_rules",
    "hsmm_interpretation_only_rules",
    "failure_abstain_rules",
    "wp10_handoff_contract",
    "boundary_flags",
]
FORBIDDEN_PROTOCOL_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]
PRIVATE_PATH_MARKERS = [
    "/Users/",
    "/Volumes/",
    "/home/",
    ".codex_worktrees",
    "HMM高阶分析器",
    "/var/folders/",
    "C:\\Users\\",
]
LOCAL_DB_TABLES = [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_lifecycle_ui_daily",
]
BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "training_algorithm_modified": "no",
    "HMM_HSMM_retrained": "no",
    "HSMM_p_exit_used_for_decision": "no",
    "final_holdout_consumed": "no",
    "decision_surface_output": "no",
    "DuckDB_committed": "no",
}


@dataclass
class InvariantCheck:
    category: str
    check: str
    status: str
    detail: str


@dataclass
class DataQualityCIResult:
    status: str
    report_version: str
    invariant_checks: list[dict[str, str]]
    failure_count: int
    warning_count: int
    failures: list[str]
    warnings: list[str]
    artifact_schema_summary: dict[str, Any]
    readiness_invariant_summary: dict[str, Any]
    horizon_coverage_summary: dict[str, Any]
    leakage_causal_target_summary: dict[str, Any]
    hsmm_diagnostic_namespace_summary: dict[str, Any]
    risk_protocol_summary: dict[str, Any]
    private_data_hygiene_summary: dict[str, Any]
    local_db_status: dict[str, Any]
    gate_integration_summary: dict[str, Any]
    boundary_flags: dict[str, str] = field(default_factory=lambda: dict(BOUNDARY_FLAGS))

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["index_id"] = INDEX_ID
        return data


class CheckRecorder:
    def __init__(self) -> None:
        self.checks: list[InvariantCheck] = []
        self.failures: list[str] = []
        self.warnings: list[str] = []

    def pass_(self, category: str, check: str, detail: str) -> None:
        self.checks.append(InvariantCheck(category, check, "pass", detail))

    def fail(self, category: str, check: str, detail: str) -> None:
        self.checks.append(InvariantCheck(category, check, "fail", detail))
        self.failures.append(f"{category}.{check}: {detail}")

    def warn(self, category: str, check: str, detail: str) -> None:
        self.checks.append(InvariantCheck(category, check, "warn", detail))
        self.warnings.append(f"{category}.{check}: {detail}")


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _safe_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _load_json(path: Path, recorder: CheckRecorder, label: str) -> dict[str, Any]:
    if not path.exists():
        recorder.fail("artifact_schema", f"{label}_exists", f"missing {path.as_posix()}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        recorder.fail("artifact_schema", f"{label}_parseable", str(exc))
        return {}
    recorder.pass_("artifact_schema", f"{label}_parseable", path.as_posix())
    return data if isinstance(data, dict) else {}


def _read_text(path: Path, recorder: CheckRecorder, label: str) -> str:
    if not path.exists():
        recorder.fail("artifact_schema", f"{label}_exists", f"missing {path.as_posix()}")
        return ""
    text = path.read_text(encoding="utf-8")
    recorder.pass_("artifact_schema", f"{label}_exists", path.as_posix())
    return text


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _walk_strings(value: Any) -> Iterable[tuple[str, str]]:
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            yield ("key", key_text)
            yield from _walk_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_strings(child)
    elif isinstance(value, str):
        yield ("value", value)


def _tracked_or_all_files(root: Path) -> list[Path]:
    try:
        output = subprocess.check_output(["git", "ls-files"], cwd=root, text=True, stderr=subprocess.DEVNULL)
    except Exception:
        output = ""
    files = [root / line.strip() for line in output.splitlines() if line.strip()]
    if files:
        return files

    excluded = {".git", ".venv", ".pytest_cache", "__pycache__"}
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in excluded for part in path.parts):
            continue
        out.append(path)
    return out


def _read_csv_rows(path: Path, recorder: CheckRecorder, label: str) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        recorder.warn("artifact_schema", f"{label}_exists", f"optional CSV missing: {path.as_posix()}")
        return [], []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
    recorder.pass_("artifact_schema", f"{label}_parseable", f"{_safe_source_path(path)} rows={len(rows)}")
    return list(reader.fieldnames or []), rows


def _artifact_schema_summary(
    *,
    recorder: CheckRecorder,
    hazard_readiness_path: Path,
    hazard_vs_hsmm_path: Path,
    risk_protocol_path: Path,
    hazard_verdict_path: Path,
    hazard_readiness: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
    hazard_verdict_text: str,
) -> dict[str, Any]:
    required_fields = {
        "hazard_readiness": ["status", "readiness_version", "readiness_rows", "readiness_status_counts"],
        "hazard_vs_hsmm": ["status", "report_version", "hazard_readiness_counts", "boundary_flags"],
        "risk_protocol": ["status", "protocol_version", "readiness_status_summary", "semantic_cleanup_summary"],
    }
    artifacts = {
        "hazard_readiness": (hazard_readiness_path, hazard_readiness),
        "hazard_vs_hsmm": (hazard_vs_hsmm_path, hazard_vs_hsmm),
        "risk_protocol": (risk_protocol_path, risk_protocol),
    }
    missing_fields: dict[str, list[str]] = {}
    for name, (_, data) in artifacts.items():
        missing = [field for field in required_fields[name] if field not in data]
        missing_fields[name] = missing
        if missing:
            recorder.fail("artifact_schema", f"{name}_required_fields", ",".join(missing))
        else:
            recorder.pass_("artifact_schema", f"{name}_required_fields", "all present")

    text = "\n".join(
        [
            json.dumps(hazard_readiness, ensure_ascii=False),
            json.dumps(hazard_vs_hsmm, ensure_ascii=False),
            json.dumps(risk_protocol, ensure_ascii=False),
            hazard_verdict_text,
        ]
    ).lower()
    broad_claim_patterns = [
        "hazard broadly beats baseline",
        "broad hazard promotion",
        '"hazard_broadly_promoted": "yes"',
        '"broadly_promoted": "yes"',
    ]
    broad_claims = [pattern for pattern in broad_claim_patterns if pattern in text]
    if broad_claims:
        recorder.fail("artifact_schema", "no_broad_hazard_promotion_claim", ",".join(broad_claims))
    else:
        recorder.pass_("artifact_schema", "no_broad_hazard_promotion_claim", "no broad promotion claim found")

    return {
        "artifacts": {
            name: {
                "path": _safe_source_path(path),
                "exists": path.exists(),
                "required_fields_missing": missing_fields[name],
            }
            for name, (path, _) in artifacts.items()
        },
        "hazard_verdict": {
            "path": _safe_source_path(hazard_verdict_path),
            "exists": hazard_verdict_path.exists(),
            "contains_missing_calibration_horizons": "missing_calibration_horizons" in hazard_verdict_text,
        },
        "broad_hazard_promotion_claims": broad_claims,
    }


def _readiness_summary(
    recorder: CheckRecorder,
    hazard_readiness: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    rows = [dict(row) for row in hazard_readiness.get("readiness_rows", [])]
    statuses = [str(row.get("readiness_status", "invalid")) for row in rows]
    invalid_statuses = sorted({status for status in statuses if status not in READINESS_STATUSES})
    if invalid_statuses:
        recorder.fail("readiness", "allowed_statuses", ",".join(invalid_statuses))
    else:
        recorder.pass_("readiness", "allowed_statuses", "restricted readiness status set")

    counts = {status: statuses.count(status) for status in sorted(READINESS_STATUSES)}
    reported_counts = {str(key): _as_int(value) for key, value in dict(hazard_readiness.get("readiness_status_counts", {})).items()}
    if reported_counts and any(reported_counts.get(status, 0) != counts.get(status, 0) for status in READINESS_STATUSES):
        recorder.fail("readiness", "reported_counts_match_rows", f"reported={reported_counts} rows={counts}")
    else:
        recorder.pass_("readiness", "reported_counts_match_rows", f"counts={counts}")

    usable = counts.get("usable_probability", 0)
    baseline = counts.get("baseline_only", 0)
    if baseline > usable:
        recorder.pass_("readiness", "baseline_only_majority", f"baseline_only={baseline} usable_probability={usable}")
    else:
        recorder.fail("readiness", "baseline_only_majority", f"baseline_only={baseline} usable_probability={usable}")

    hvh_counts = {str(key): _as_int(value) for key, value in dict(hazard_vs_hsmm.get("hazard_readiness_counts", {})).items()}
    risk_counts = {
        str(key): _as_int(value)
        for key, value in dict(risk_protocol.get("readiness_status_summary", {}).get("counts", {})).items()
    }
    usable_source = hazard_vs_hsmm.get("usable_probability_scope", {}).get("source")
    if (
        hvh_counts.get("usable_probability", -1) == usable
        and risk_counts.get("usable_probability", -1) == usable
        and usable_source == "hazard_readiness_matrix_only"
    ):
        recorder.pass_("readiness", "usable_probability_matrix_only", "usable probability count matches hazard readiness")
    else:
        recorder.fail(
            "readiness",
            "usable_probability_matrix_only",
            f"readiness={usable} hazard_vs_hsmm={hvh_counts.get('usable_probability')} risk={risk_counts.get('usable_probability')} source={usable_source}",
        )

    insufficient_rows = [row for row in rows if row.get("readiness_status") == "insufficient_sample"]
    promoted_insufficient = [row for row in insufficient_rows if row.get("calibration_status") == "calibration_candidate"]
    if promoted_insufficient:
        recorder.fail("readiness", "insufficient_sample_abstains", f"rows={len(promoted_insufficient)}")
    else:
        recorder.pass_("readiness", "insufficient_sample_abstains", f"insufficient_sample={len(insufficient_rows)}")

    invalid_rows = [row for row in rows if row.get("readiness_status") == "invalid"]
    consumed_invalid = [row for row in invalid_rows if row.get("source") == "calibration_x_age_bucket_baseline"]
    if consumed_invalid:
        recorder.fail("readiness", "invalid_not_valid_evidence", f"rows={len(consumed_invalid)}")
    else:
        recorder.pass_("readiness", "invalid_not_valid_evidence", f"invalid={len(invalid_rows)}")

    return {
        "allowed_statuses": sorted(READINESS_STATUSES),
        "row_count": len(rows),
        "counts_from_rows": counts,
        "reported_counts": reported_counts,
        "hazard_vs_hsmm_counts": hvh_counts,
        "risk_protocol_counts": risk_counts,
        "usable_probability_source": usable_source,
        "baseline_only_majority": baseline > usable,
        "insufficient_sample_count": len(insufficient_rows),
        "invalid_count": len(invalid_rows),
    }


def _horizon_summary(
    *,
    recorder: CheckRecorder,
    root: Path,
    hazard_readiness: Mapping[str, Any],
    hazard_prediction_sample_path: Path,
    hazard_verdict_text: str,
) -> dict[str, Any]:
    expected = list(hazard_readiness.get("expected_horizons", []))
    if expected == EXPECTED_HORIZONS:
        recorder.pass_("horizon", "expected_horizons", str(expected))
    else:
        recorder.fail("horizon", "expected_horizons", f"expected={expected} required={EXPECTED_HORIZONS}")

    coverage = dict(hazard_readiness.get("horizon_coverage_summary", {}))
    missing_calibration = list(coverage.get("missing_calibration_horizons", []))
    missing_summary = dict(hazard_readiness.get("missing_horizon_evidence_summary", {}))
    missing_summary_calibration = list(missing_summary.get("missing_calibration_horizons", []))
    if not missing_calibration and not missing_summary_calibration:
        recorder.pass_("horizon", "missing_calibration_horizons", "none")
    elif "justified" in hazard_verdict_text.lower():
        recorder.warn("horizon", "missing_calibration_horizons", "missing horizons justified in verdict")
    else:
        recorder.fail("horizon", "missing_calibration_horizons", f"{missing_calibration or missing_summary_calibration}")

    columns, rows = _read_csv_rows(hazard_prediction_sample_path, recorder, "hazard_prediction_sample")
    sample_horizons = sorted({_as_int(row.get("horizon_days")) for row in rows if row.get("horizon_days")})
    horizon_counts = {horizon: 0 for horizon in EXPECTED_HORIZONS}
    for row in rows:
        horizon = _as_int(row.get("horizon_days"))
        if horizon in horizon_counts:
            horizon_counts[horizon] += 1
    if rows and sample_horizons == EXPECTED_HORIZONS:
        recorder.pass_("horizon", "prediction_sample_all_horizons", str(sample_horizons))
    elif rows:
        recorder.fail("horizon", "prediction_sample_all_horizons", f"sample_horizons={sample_horizons}")

    if rows and all(count > 0 for count in horizon_counts.values()):
        recorder.pass_("horizon", "prediction_sample_stratified", str(horizon_counts))
    elif rows:
        recorder.fail("horizon", "prediction_sample_stratified", str(horizon_counts))

    full_prediction_csvs = []
    for path in _tracked_or_all_files(root):
        name = path.name
        if name.endswith(".csv") and "prediction" in name and not name.endswith("_sample.csv"):
            full_prediction_csvs.append(path.relative_to(root).as_posix())
    if full_prediction_csvs:
        recorder.fail("horizon", "full_prediction_csv_not_committed", ",".join(full_prediction_csvs))
    else:
        recorder.pass_("horizon", "full_prediction_csv_not_committed", "none")

    return {
        "expected_horizons": expected,
        "required_horizons": EXPECTED_HORIZONS,
        "hazard_prediction_sample_path": _safe_source_path(hazard_prediction_sample_path),
        "hazard_prediction_sample_exists": hazard_prediction_sample_path.exists(),
        "hazard_prediction_sample_columns": columns,
        "hazard_prediction_sample_row_count": len(rows),
        "hazard_prediction_sample_horizons": sample_horizons,
        "hazard_prediction_sample_horizon_counts": {str(k): v for k, v in horizon_counts.items()},
        "missing_calibration_horizons": missing_calibration,
        "missing_calibration_horizons_summary": missing_summary_calibration,
        "full_prediction_csv_committed": full_prediction_csvs,
    }


def _leakage_summary(recorder: CheckRecorder, root: Path) -> dict[str, Any]:
    target_sample_path = root / "reports/stage03r/exit_target_dataset_v1_sample.csv"
    columns, rows = _read_csv_rows(target_sample_path, recorder, "exit_target_dataset_sample")
    required_columns = ["feature_leakage_violation", "purge_group_id", "embargo_until_date", "censoring_status"]
    missing_columns = [column for column in required_columns if column not in columns]
    if missing_columns:
        recorder.fail("leakage", "target_fixture_required_columns", ",".join(missing_columns))
    else:
        recorder.pass_("leakage", "target_fixture_required_columns", "present")

    leakage_count = sum(1 for row in rows if _as_bool(row.get("feature_leakage_violation")))
    if leakage_count:
        recorder.fail("leakage", "feature_leakage_violation_false", f"rows={leakage_count}")
    else:
        recorder.pass_("leakage", "feature_leakage_violation_false", "no true values")

    purge_missing = sum(1 for row in rows if not row.get("purge_group_id"))
    embargo_missing = sum(1 for row in rows if not row.get("embargo_until_date"))
    if purge_missing or embargo_missing:
        recorder.fail("leakage", "purge_embargo_present", f"purge_missing={purge_missing} embargo_missing={embargo_missing}")
    else:
        recorder.pass_("leakage", "purge_embargo_present", "present")

    right_censored = [row for row in rows if str(row.get("censoring_status", "")).startswith("right_censored")]
    right_censored_bad_label = [
        row
        for row in right_censored
        if str(row.get("exit_within_horizon", "")).strip() not in {"", "nan", "None", "null"}
        or str(row.get("sample_weight", "")).strip() not in {"0", "0.0", ""}
    ]
    if right_censored_bad_label:
        recorder.fail("leakage", "right_censored_not_observed_event_rate", f"rows={len(right_censored_bad_label)}")
    else:
        recorder.pass_("leakage", "right_censored_not_observed_event_rate", f"right_censored={len(right_censored)}")

    return {
        "target_sample_path": _safe_source_path(target_sample_path),
        "target_sample_exists": target_sample_path.exists(),
        "target_sample_row_count": len(rows),
        "required_columns_missing": missing_columns,
        "feature_leakage_violation_count": leakage_count,
        "purge_group_id_missing_count": purge_missing,
        "embargo_until_date_missing_count": embargo_missing,
        "right_censored_count": len(right_censored),
        "right_censored_bad_label_count": len(right_censored_bad_label),
        "stage03r_exit_target_gate_required": "yes",
    }


def _hsmm_namespace_summary(
    recorder: CheckRecorder,
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
) -> dict[str, Any]:
    risk_keys = list(_walk_keys(risk_protocol))
    legacy_in_protocol = LEGACY_HSMM_STATUS_FIELD in risk_keys
    if legacy_in_protocol:
        recorder.fail("hsmm_namespace", "no_legacy_hsmm_probability_status_counts", LEGACY_HSMM_STATUS_FIELD)
    else:
        recorder.pass_("hsmm_namespace", "no_legacy_hsmm_probability_status_counts", "absent in protocol")

    cleanup = dict(risk_protocol.get("semantic_cleanup_summary", {}))
    diagnostic_field = cleanup.get("diagnostic_count_field")
    policy = cleanup.get("hsmm_lifecycle_probability_status_policy")
    diagnostic_counts = cleanup.get("hsmm_lifecycle_probability_status_counts_diagnostic_only_by_horizon", {})
    if diagnostic_field == HSMM_DIAGNOSTIC_COUNT_FIELD and diagnostic_counts:
        recorder.pass_("hsmm_namespace", "diagnostic_namespace", diagnostic_field)
    else:
        recorder.fail("hsmm_namespace", "diagnostic_namespace", f"field={diagnostic_field} counts_present={bool(diagnostic_counts)}")

    if policy == HSMM_DIAGNOSTIC_POLICY:
        recorder.pass_("hsmm_namespace", "diagnostic_policy", str(policy))
    else:
        recorder.fail("hsmm_namespace", "diagnostic_policy", str(policy))

    boundary = dict(risk_protocol.get("boundary_flags", {}))
    if boundary.get("HSMM_p_exit_used_for_decision") == "no":
        recorder.pass_("hsmm_namespace", "hsmm_p_exit_not_decision", "no")
    else:
        recorder.fail("hsmm_namespace", "hsmm_p_exit_not_decision", str(boundary.get("HSMM_p_exit_used_for_decision")))

    numeric_policy = hazard_vs_hsmm.get("hsmm_lifecycle_availability", {}).get("hsmm_numeric_p_exit_policy")
    if numeric_policy in {"not_available", HSMM_DIAGNOSTIC_POLICY}:
        recorder.pass_("hsmm_namespace", "numeric_p_exit_responsibility_not_expanded", str(numeric_policy))
    else:
        recorder.fail("hsmm_namespace", "numeric_p_exit_responsibility_not_expanded", str(numeric_policy))

    return {
        "legacy_hsmm_probability_status_counts_in_protocol": legacy_in_protocol,
        "diagnostic_count_field": diagnostic_field,
        "diagnostic_policy": policy,
        "diagnostic_counts_by_horizon": diagnostic_counts,
        "hsmm_p_exit_used_for_decision": boundary.get("HSMM_p_exit_used_for_decision"),
        "hsmm_numeric_p_exit_policy": numeric_policy,
    }


def _risk_protocol_summary(recorder: CheckRecorder, risk_protocol: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in REQUIRED_RISK_PROTOCOL_FIELDS if field not in risk_protocol]
    if missing:
        recorder.fail("risk_protocol", "required_fields", ",".join(missing))
    else:
        recorder.pass_("risk_protocol", "required_fields", "all present")

    discipline = dict(risk_protocol.get("split_and_final_holdout_discipline", {}))
    final_holdout_text = str(discipline.get("final_holdout_consumption", "")).lower()
    if "wp10" in final_holdout_text and "only" in final_holdout_text:
        recorder.pass_("risk_protocol", "final_holdout_wp10_only", discipline.get("final_holdout_consumption", ""))
    else:
        recorder.fail("risk_protocol", "final_holdout_wp10_only", discipline.get("final_holdout_consumption", "missing"))

    if discipline.get("repeated_final_tuning_forbidden") == "yes":
        recorder.pass_("risk_protocol", "repeated_final_tuning_forbidden", "yes")
    else:
        recorder.fail("risk_protocol", "repeated_final_tuning_forbidden", str(discipline.get("repeated_final_tuning_forbidden")))

    if discipline.get("threshold_tuning_in_wp8") == "no":
        recorder.pass_("risk_protocol", "threshold_tuning_in_wp8_no", "no")
    else:
        recorder.fail("risk_protocol", "threshold_tuning_in_wp8_no", str(discipline.get("threshold_tuning_in_wp8")))

    forbidden_hits: list[str] = []
    for kind, text in _walk_strings(risk_protocol):
        lower = text.lower()
        for term in FORBIDDEN_PROTOCOL_TERMS:
            if term not in lower:
                continue
            if kind == "key" and term == "decision_surface" and text == "decision_surface_output":
                continue
            forbidden_hits.append(f"{kind}:{term}:{text[:80]}")
    boundary = dict(risk_protocol.get("boundary_flags", {}))
    if boundary.get("decision_surface_output") not in {None, "no"}:
        forbidden_hits.append(f"key:decision_surface:decision_surface_output={boundary.get('decision_surface_output')}")
    if forbidden_hits:
        recorder.fail("risk_protocol", "forbidden_surface_terms", ";".join(forbidden_hits[:10]))
    else:
        recorder.pass_("risk_protocol", "forbidden_surface_terms", "none")

    return {
        "required_fields_missing": missing,
        "final_holdout_consumption": discipline.get("final_holdout_consumption"),
        "repeated_final_tuning_forbidden": discipline.get("repeated_final_tuning_forbidden"),
        "threshold_tuning_in_wp8": discipline.get("threshold_tuning_in_wp8"),
        "forbidden_surface_terms": forbidden_hits,
        "boundary_flags": boundary,
    }


def _private_data_summary(recorder: CheckRecorder, root: Path) -> dict[str, Any]:
    files = _tracked_or_all_files(root)
    rel_files = [path.relative_to(root).as_posix() for path in files if path.exists()]
    committed_duckdb = [path for path in rel_files if path.endswith(".duckdb") or path.endswith(".duckdb.wal") or path.endswith(".wal")]
    committed_cache = [path for path in rel_files if path.startswith("data/cache/") or "/cache/" in path]
    full_prediction_csv = [
        path for path in rel_files if path.endswith(".csv") and "prediction" in Path(path).name and not path.endswith("_sample.csv")
    ]
    private_path_hits: list[str] = []
    text_suffixes = {".py", ".sh", ".md", ".json", ".csv", ".txt", ".yaml", ".yml"}
    for path in files:
        rel = path.relative_to(root).as_posix()
        if path.suffix not in text_suffixes or not path.exists():
            continue
        if not (rel.startswith("docs/") or rel.startswith("reports/")):
            continue
        if rel.startswith("docs/work_packages/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for marker in PRIVATE_PATH_MARKERS:
            if marker in text:
                private_path_hits.append(f"{rel}:{marker}")

    if committed_duckdb:
        recorder.fail("private_data", "duckdb_wal_not_committed", ",".join(committed_duckdb))
    else:
        recorder.pass_("private_data", "duckdb_wal_not_committed", "none")
    if committed_cache:
        recorder.fail("private_data", "cache_not_committed", ",".join(committed_cache))
    else:
        recorder.pass_("private_data", "cache_not_committed", "none")
    if full_prediction_csv:
        recorder.fail("private_data", "full_prediction_csv_not_committed", ",".join(full_prediction_csv))
    else:
        recorder.pass_("private_data", "full_prediction_csv_not_committed", "none")
    if private_path_hits:
        recorder.fail("private_data", "private_paths_absent", ";".join(private_path_hits[:10]))
    else:
        recorder.pass_("private_data", "private_paths_absent", "none")

    return {
        "scanned_file_count": len(rel_files),
        "duckdb_or_wal_files_committed": committed_duckdb,
        "cache_files_committed": committed_cache,
        "full_prediction_csv_committed": full_prediction_csv,
        "private_path_hits": private_path_hits,
        "check_no_private_paths_required": "yes",
        "validate_stage01_no_private_db_required": "yes",
    }


def _local_db_status(db_path: str | None, root: Path) -> dict[str, Any]:
    candidates: list[Path] = []
    if db_path:
        candidates.append(Path(db_path))
    else:
        default_db = root / "data/db/a_share_hmm.duckdb"
        if default_db.exists():
            candidates.append(default_db)
    if not candidates:
        return {
            "db_path_used": None,
            "db_found": "no",
            "opened_read_only": "no",
            "row_counts": {},
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    path = candidates[0]
    safe_path = _safe_source_path(path)
    if not path.exists():
        return {
            "db_path_used": safe_path,
            "db_found": "no",
            "opened_read_only": "no",
            "row_counts": {},
            "ci_requires_db": "no",
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
            "row_counts": {},
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    try:
        row_counts: dict[str, Any] = {}
        for table in LOCAL_DB_TABLES:
            try:
                row_counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
            except Exception as exc:
                row_counts[table] = f"missing_or_unreadable: {exc}"
        return {
            "db_path_used": safe_path,
            "db_found": "yes",
            "opened_read_only": "yes",
            "key_tables_checked": LOCAL_DB_TABLES,
            "row_counts": row_counts,
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    finally:
        try:
            con.close()
        except Exception:
            pass


def evaluate_data_quality_ci(
    *,
    hazard_readiness_path: Path,
    hazard_vs_hsmm_path: Path,
    risk_protocol_path: Path,
    hazard_verdict_path: Path,
    hazard_prediction_sample_path: Path,
    db_path: str | None = None,
    root: Path | None = None,
) -> DataQualityCIResult:
    root = root or Path.cwd()
    recorder = CheckRecorder()
    hazard_readiness = _load_json(hazard_readiness_path, recorder, "hazard_readiness")
    hazard_vs_hsmm = _load_json(hazard_vs_hsmm_path, recorder, "hazard_vs_hsmm")
    risk_protocol = _load_json(risk_protocol_path, recorder, "risk_protocol")
    hazard_verdict_text = _read_text(hazard_verdict_path, recorder, "hazard_verdict")

    artifact_summary = _artifact_schema_summary(
        recorder=recorder,
        hazard_readiness_path=hazard_readiness_path,
        hazard_vs_hsmm_path=hazard_vs_hsmm_path,
        risk_protocol_path=risk_protocol_path,
        hazard_verdict_path=hazard_verdict_path,
        hazard_readiness=hazard_readiness,
        hazard_vs_hsmm=hazard_vs_hsmm,
        risk_protocol=risk_protocol,
        hazard_verdict_text=hazard_verdict_text,
    )
    readiness_summary = _readiness_summary(recorder, hazard_readiness, hazard_vs_hsmm, risk_protocol)
    horizon_summary = _horizon_summary(
        recorder=recorder,
        root=root,
        hazard_readiness=hazard_readiness,
        hazard_prediction_sample_path=hazard_prediction_sample_path,
        hazard_verdict_text=hazard_verdict_text,
    )
    leakage_summary = _leakage_summary(recorder, root)
    hsmm_summary = _hsmm_namespace_summary(recorder, hazard_vs_hsmm, risk_protocol)
    risk_summary = _risk_protocol_summary(recorder, risk_protocol)
    private_summary = _private_data_summary(recorder, root)
    local_db = _local_db_status(db_path, root)

    if local_db.get("db_found") == "yes" and local_db.get("opened_read_only") == "yes":
        recorder.pass_("local_db", "optional_read_only_counts", json.dumps(local_db.get("row_counts", {}), sort_keys=True))
    elif local_db.get("db_found") == "yes":
        recorder.warn("local_db", "optional_read_only_counts", str(local_db.get("open_error", "not opened")))
    else:
        recorder.pass_("local_db", "optional_absent_ci_safe", "private DuckDB not required")

    boundary = dict(BOUNDARY_FLAGS)
    external_fetch_values = [
        hazard_readiness.get("external_data_fetch"),
        hazard_vs_hsmm.get("boundary_flags", {}).get("external_data_fetch"),
        risk_protocol.get("boundary_flags", {}).get("external_data_fetch"),
        local_db.get("external_data_fetch"),
    ]
    if all(value in {None, "no"} for value in external_fetch_values):
        recorder.pass_("boundary", "external_data_fetch_no", str(external_fetch_values))
    else:
        recorder.fail("boundary", "external_data_fetch_no", str(external_fetch_values))

    gate_summary = {
        "stage03r_data_quality_ci_gate": "required",
        "stage03r_exit_target_gate": "required",
        "check_no_private_paths": "required",
        "validate_stage01_no_private_db": "required",
        "stage03_preflight_gate_includes_data_quality_ci": "yes",
    }
    status = "pass" if not recorder.failures else "fail"
    return DataQualityCIResult(
        status=status,
        report_version=REPORT_VERSION,
        invariant_checks=[asdict(check) for check in recorder.checks],
        failure_count=len(recorder.failures),
        warning_count=len(recorder.warnings),
        failures=recorder.failures,
        warnings=recorder.warnings,
        artifact_schema_summary=artifact_summary,
        readiness_invariant_summary=readiness_summary,
        horizon_coverage_summary=horizon_summary,
        leakage_causal_target_summary=leakage_summary,
        hsmm_diagnostic_namespace_summary=hsmm_summary,
        risk_protocol_summary=risk_summary,
        private_data_hygiene_summary=private_summary,
        local_db_status=local_db,
        gate_integration_summary=gate_summary,
        boundary_flags=boundary,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP9 Data Quality CI Report",
        "",
        "## Executive verdict",
        "",
        f"Stage03R data-quality CI status: {summary.get('status')}.",
        "",
        "## Artifact schema summary",
        "",
        "```json",
        json.dumps(summary.get("artifact_schema_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Readiness invariant summary",
        "",
        "```json",
        json.dumps(summary.get("readiness_invariant_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Horizon coverage summary",
        "",
        "```json",
        json.dumps(summary.get("horizon_coverage_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Leakage and causal target summary",
        "",
        "```json",
        json.dumps(summary.get("leakage_causal_target_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## HSMM diagnostic namespace summary",
        "",
        "```json",
        json.dumps(summary.get("hsmm_diagnostic_namespace_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Risk protocol summary",
        "",
        "```json",
        json.dumps(summary.get("risk_protocol_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Private-data hygiene summary",
        "",
        "```json",
        json.dumps(summary.get("private_data_hygiene_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Local DB status",
        "",
        "```json",
        json.dumps(summary.get("local_db_status", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Gate integration summary",
        "",
        "```json",
        json.dumps(summary.get("gate_integration_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary confirmation",
        "",
        "```json",
        json.dumps(summary.get("boundary_flags", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Failures",
        "",
        "```json",
        json.dumps(summary.get("failures", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Warnings",
        "",
        "```json",
        json.dumps(summary.get("warnings", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: DataQualityCIResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def run_cli(args: argparse.Namespace) -> int:
    result = evaluate_data_quality_ci(
        hazard_readiness_path=Path(args.hazard_readiness),
        hazard_vs_hsmm_path=Path(args.hazard_vs_hsmm),
        risk_protocol_path=Path(args.risk_protocol),
        hazard_verdict_path=Path(args.hazard_verdict),
        hazard_prediction_sample_path=Path(args.hazard_prediction_sample),
        db_path=args.db,
        root=Path(args.root) if args.root else Path.cwd(),
    )
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status == "pass" else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage03R WP9 data-quality CI invariants")
    parser.add_argument("--hazard-readiness", required=True)
    parser.add_argument("--hazard-vs-hsmm", required=True)
    parser.add_argument("--risk-protocol", required=True)
    parser.add_argument("--hazard-verdict", required=True)
    parser.add_argument("--hazard-prediction-sample", required=True)
    parser.add_argument("--db", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
