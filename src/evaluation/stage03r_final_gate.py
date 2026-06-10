"""Stage03R WP10 final gate.

This module aggregates accepted Stage03R public artifacts and gate scripts into
the final engineering/control-plane verdict. It does not fetch data, train or
retrain HMM/HSMM models, tune thresholds, create a decision layer, or promote
hazard probabilities beyond readiness-approved local slices.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


INDEX_ID = "STAGE03R-WP10"
FINAL_GATE_VERSION = "stage03r_final_gate_v1"
EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
READINESS_STATUSES = [
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
]
HSMM_DIAGNOSTIC_POLICY = "diagnostic_only_not_decision_input"
HSMM_DIAGNOSTIC_COUNT_FIELD = "hsmm_lifecycle_probability_status_counts_diagnostic_only"
FORBIDDEN_OUTPUT_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]
LOCAL_DB_TABLES = [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_lifecycle_ui_daily",
]
SAFE_BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "training_algorithm_modified": "no",
    "hmm_hsmm_retrained": "no",
    "hsmm_p_exit_decision_input": "no",
    "final_holdout_consumed": "no",
    "surface_or_action_overlay_output": "no",
    "duckdb_committed": "no",
    "private_db_required_in_ci": "no",
}
PREFLIGHT_COVERED_GATES = {
    "data_quality_ci_gate": "scripts/stage03r_data_quality_ci_gate.sh",
    "private_data_hygiene": "scripts/check_no_private_paths.sh",
    "stage01_no_private_db": "scripts/validate_stage01_no_private_db.sh",
}


@dataclass
class FinalGateResult:
    status: str
    final_gate_version: str
    final_verdict: str
    engineering_gate_verdict: str
    empirical_promotion_verdict: str
    package_evidence: dict[str, Any]
    gate_status_summary: dict[str, Any]
    readiness_status_summary: dict[str, Any]
    hazard_scope_summary: dict[str, Any]
    baseline_scope_summary: dict[str, Any]
    hsmm_scope_summary: dict[str, Any]
    risk_protocol_compliance: dict[str, Any]
    data_quality_ci_compliance: dict[str, Any]
    final_holdout_discipline: dict[str, Any]
    blocking_issues: list[str]
    defer_reasons: list[str]
    remediation_items: list[str]
    boundary_flags: dict[str, str] = field(default_factory=lambda: dict(SAFE_BOUNDARY_FLAGS))
    next_stage_recommendations: list[str] = field(default_factory=list)

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
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_no(value: Any) -> bool:
    return value in {None, "no", "false", "0", False}


def _is_yes(value: Any) -> bool:
    return value in {"yes", "true", "1", True}


def _load_json(path: Path, label: str, blocking_issues: list[str]) -> dict[str, Any]:
    if not path.exists():
        blocking_issues.append(f"{label}: missing {_safe_source_path(path)}")
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        blocking_issues.append(f"{label}: unparseable {_safe_source_path(path)} ({exc})")
        return {}
    if not isinstance(data, dict):
        blocking_issues.append(f"{label}: JSON root is not an object")
        return {}
    return data


def _read_text(path: Path, label: str, blocking_issues: list[str]) -> str:
    if not path.exists():
        blocking_issues.append(f"{label}: missing {_safe_source_path(path)}")
        return ""
    return path.read_text(encoding="utf-8")


def _walk_strings(value: Any) -> list[str]:
    out: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            out.append(str(key))
            out.extend(_walk_strings(child))
    elif isinstance(value, list):
        for child in value:
            out.extend(_walk_strings(child))
    elif isinstance(value, str):
        out.append(value)
    return out


def _normalise_gate_status(value: Any) -> str:
    if isinstance(value, dict):
        status = str(value.get("status", value.get("verdict", "missing"))).lower()
    else:
        status = str(value).lower()
    if status in {"pass", "passed", "ok", "success"}:
        return "pass"
    if status in {"defer", "deferred", "local_only"}:
        return "defer"
    if status in {"not_run", "missing"}:
        return status
    return "fail"


def _parse_marker(stdout: str, marker: str) -> str:
    for line in reversed(stdout.splitlines()):
        if marker in line:
            return line.strip()
    return ""


def _status_from_marker(line: str, marker: str) -> str:
    if not line:
        return "fail"
    after = line.split(marker, 1)[1].split()[0].strip().lower()
    if after in {"pass", "defer", "blocked"}:
        return "pass" if after == "pass" else after
    if after in {"fail", "blocked"}:
        return "fail"
    return after or "fail"


def _run_gate(name: str, command: Sequence[str], marker: str, root: Path) -> dict[str, Any]:
    result = subprocess.run(
        list(command),
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    marker_line = _parse_marker(result.stdout, marker)
    marker_status = _status_from_marker(marker_line, marker)
    status = "pass" if result.returncode == 0 and marker_status == "pass" else "fail"
    return {
        "status": status,
        "returncode": int(result.returncode),
        "stable_line": marker_line,
        "command": " ".join(command),
    }


def _run_required_gates(root: Path) -> dict[str, Any]:
    return {
        "exit_target_dataset_gate": _run_gate(
            "exit_target_dataset_gate",
            ["bash", "scripts/stage03r_exit_target_gate.sh"],
            "STAGE03R_EXIT_TARGET_GATE=",
            root,
        ),
        "stage03_preflight_gate": _run_gate(
            "stage03_preflight_gate",
            ["bash", "scripts/stage03_preflight_gate.sh"],
            "STAGE03_PREFLIGHT_GATE=",
            root,
        ),
    }


def _local_db_status(db_path: str | None) -> dict[str, Any]:
    if not db_path:
        return {
            "db_path_used": None,
            "db_found": "no",
            "opened_read_only": "no",
            "key_tables_checked": [],
            "row_counts": {},
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "duckdb_committed": "no",
        }

    path = Path(db_path)
    safe_path = _safe_source_path(path)
    if not path.exists():
        return {
            "db_path_used": safe_path,
            "db_found": "no",
            "opened_read_only": "no",
            "key_tables_checked": LOCAL_DB_TABLES,
            "row_counts": {},
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "duckdb_committed": "no",
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
            "key_tables_checked": LOCAL_DB_TABLES,
            "row_counts": {},
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "duckdb_committed": "no",
        }

    try:
        row_counts: dict[str, int] = {}
        for table in LOCAL_DB_TABLES:
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
            "ci_requires_db": "no",
            "external_data_fetch": "no",
            "duckdb_committed": "no",
        }
    finally:
        try:
            con.close()
        except Exception:
            pass


def _readiness_counts(hazard_readiness: Mapping[str, Any], risk_protocol: Mapping[str, Any]) -> dict[str, int]:
    direct = hazard_readiness.get("readiness_status_counts")
    if isinstance(direct, dict):
        return {status: _as_int(direct.get(status)) for status in READINESS_STATUSES}
    protocol_counts = (
        risk_protocol.get("readiness_status_summary", {})
        if isinstance(risk_protocol.get("readiness_status_summary"), dict)
        else {}
    ).get("counts", {})
    if isinstance(protocol_counts, dict):
        return {status: _as_int(protocol_counts.get(status)) for status in READINESS_STATUSES}
    rows = hazard_readiness.get("readiness_rows", [])
    counts = {status: 0 for status in READINESS_STATUSES}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                status = str(row.get("readiness_status", "invalid"))
                counts[status] = counts.get(status, 0) + 1
    return {status: _as_int(counts.get(status)) for status in READINESS_STATUSES}


def _readiness_by_horizon(hazard_readiness: Mapping[str, Any]) -> dict[str, dict[str, int]]:
    rows = hazard_readiness.get("readiness_rows", [])
    by_horizon: dict[str, dict[str, int]] = {}
    for horizon in EXPECTED_HORIZONS:
        counts = {status: 0 for status in READINESS_STATUSES}
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict) and _as_int(row.get("horizon_days")) == horizon:
                    status = str(row.get("readiness_status", "invalid"))
                    counts[status] = counts.get(status, 0) + 1
        by_horizon[str(horizon)] = {status: _as_int(counts.get(status)) for status in READINESS_STATUSES}
    return by_horizon


def _package_evidence() -> dict[str, Any]:
    return {
        "stage03_preflight": {"pr": "#38", "evidence": "Stage03 preflight PASS"},
        "STAGE03R-WP0": {"pr": "#39", "status": "accepted", "evidence": "scope freeze and signal contract"},
        "STAGE03R-WP1": {"pr": "#40", "status": "accepted", "evidence": "exit_target_dataset_v1"},
        "STAGE03R-WP2": {"pr": "#41", "status": "accepted", "evidence": "target leakage and purge tests"},
        "STAGE03R-WP3": {"pr": "#42", "status": "accepted", "evidence": "logistic hazard baseline"},
        "STAGE03R-WP4": {"pr": "#43", "status": "accepted", "evidence": "age-bucket baseline"},
        "STAGE03R-WP5": {"pr": "#44", "status": "accepted", "evidence": "hazard isotonic calibration"},
        "STAGE03R-WP6": {"pr": "#45", "status": "accepted", "evidence": "hazard_readiness_matrix_v1"},
        "STAGE03R-WP6.1": {
            "pr": "#46",
            "status": "accepted",
            "evidence": "multi-horizon hazard regeneration",
        },
        "STAGE03R-WP7": {"pr": "#47", "status": "accepted", "evidence": "hazard_vs_hsmm_report_v1"},
        "STAGE03R-WP8": {"pr": "#48", "status": "accepted", "evidence": "risk_validation_protocol_v1"},
        "STAGE03R-WP9": {"pr": "#49", "status": "accepted", "evidence": "data_quality_ci_invariants_v1"},
        "STAGE03R-WP10": {"pr": "#50", "status": "accepted", "evidence": FINAL_GATE_VERSION},
        "STAGE03R-WP10.1": {"status": "active", "evidence": "final_holdout_artifact_v1"},
    }


def _artifact_schema_summary(
    *,
    hazard_readiness: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    hazard_verdict_text: str,
    blocking_issues: list[str],
) -> dict[str, Any]:
    schema = {
        "hazard_readiness_matrix": {
            "status": hazard_readiness.get("status"),
            "version": hazard_readiness.get("readiness_version"),
            "required_fields_present": all(
                field in hazard_readiness
                for field in ["status", "readiness_version", "readiness_rows", "readiness_status_counts"]
            ),
        },
        "multi_horizon_hazard_verdict": {
            "present": "yes" if hazard_verdict_text else "no",
            "mentions_expected_horizons": all(f"{h}" in hazard_verdict_text for h in EXPECTED_HORIZONS),
        },
        "hazard_vs_hsmm": {
            "status": hazard_vs_hsmm.get("status"),
            "version": hazard_vs_hsmm.get("report_version"),
            "required_fields_present": all(
                field in hazard_vs_hsmm
                for field in ["status", "report_version", "hazard_readiness_counts", "boundary_flags"]
            ),
        },
        "risk_validation_protocol": {
            "status": risk_protocol.get("status"),
            "version": risk_protocol.get("protocol_version"),
            "required_fields_present": all(
                field in risk_protocol
                for field in [
                    "status",
                    "protocol_version",
                    "readiness_status_summary",
                    "split_and_final_holdout_discipline",
                    "wp10_handoff_contract",
                ]
            ),
        },
        "data_quality_ci": {
            "status": data_quality.get("status"),
            "version": data_quality.get("report_version"),
            "failure_count": _as_int(data_quality.get("failure_count")),
            "required_fields_present": all(
                field in data_quality
                for field in [
                    "status",
                    "report_version",
                    "failure_count",
                    "private_data_hygiene_summary",
                    "risk_protocol_summary",
                ]
            ),
        },
    }
    for name, item in schema.items():
        if item.get("required_fields_present") is False:
            blocking_issues.append(f"{name}: required schema fields missing")
        if name != "multi_horizon_hazard_verdict" and item.get("status") != "pass":
            blocking_issues.append(f"{name}: status is {item.get('status')}")
    if not hazard_verdict_text:
        blocking_issues.append("multi_horizon_hazard_verdict: missing or empty")
    return schema


def _gate_status_summary(
    *,
    gate_statuses: Mapping[str, Any] | None,
    run_gate_scripts: bool,
    root: Path,
    data_quality: Mapping[str, Any],
    blocking_issues: list[str],
) -> dict[str, Any]:
    statuses: dict[str, Any] = {}
    if run_gate_scripts:
        statuses.update(_run_required_gates(root))
    if gate_statuses:
        statuses.update({str(key): value for key, value in gate_statuses.items()})

    if _normalise_gate_status(statuses.get("stage03_preflight_gate")) == "pass":
        for key, covered_command in PREFLIGHT_COVERED_GATES.items():
            statuses.setdefault(
                key,
                {
                    "status": "pass",
                    "source": "covered_by_stage03_preflight_gate",
                    "covered_command": covered_command,
                },
            )

    leakage = data_quality.get("leakage_causal_target_summary", {})
    if isinstance(leakage, dict):
        leakage_ok = (
            leakage.get("target_sample_exists") is True
            and not leakage.get("required_columns_missing")
            and _as_int(leakage.get("feature_leakage_violation_count")) == 0
            and _as_int(leakage.get("right_censored_bad_label_count")) == 0
        )
        statuses.setdefault(
            "target_leakage_purge_tests",
            {
                "status": "pass" if leakage_ok else "fail",
                "source": "data_quality_ci.leakage_causal_target_summary",
            },
        )

    statuses.setdefault(
        "stage03_preflight_gate_includes_data_quality_ci",
        {
            "status": (
                "pass"
                if data_quality.get("gate_integration_summary", {}).get(
                    "stage03_preflight_gate_includes_data_quality_ci"
                )
                == "yes"
                else "fail"
            ),
            "source": "data_quality_ci.gate_integration_summary",
        },
    )

    required = [
        "exit_target_dataset_gate",
        "target_leakage_purge_tests",
        "data_quality_ci_gate",
        "private_data_hygiene",
        "stage01_no_private_db",
        "stage03_preflight_gate",
        "stage03_preflight_gate_includes_data_quality_ci",
    ]
    for key in required:
        if key not in statuses:
            statuses[key] = {"status": "missing", "source": "not evaluated"}
        status = _normalise_gate_status(statuses[key])
        if status != "pass":
            blocking_issues.append(f"{key}: gate status {status}")

    return statuses


def _readiness_status_summary(
    *,
    hazard_readiness: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    blocking_issues: list[str],
) -> dict[str, Any]:
    counts = _readiness_counts(hazard_readiness, risk_protocol)
    by_horizon = _readiness_by_horizon(hazard_readiness)
    row_count = sum(counts.values())
    baseline_majority = counts.get("baseline_only", 0) > counts.get("usable_probability", 0)
    has_local_probability = counts.get("usable_probability", 0) > 0
    expected = hazard_readiness.get("expected_horizons") or EXPECTED_HORIZONS
    horizon_summary = hazard_readiness.get("horizon_coverage_summary", {})
    missing_calibration = []
    missing_baseline = []
    if isinstance(horizon_summary, dict):
        missing_calibration = list(horizon_summary.get("missing_calibration_horizons") or [])
        missing_baseline = list(horizon_summary.get("missing_baseline_horizons") or [])

    usable_scope = hazard_vs_hsmm.get("usable_probability_scope", {})
    usable_source = usable_scope.get("source") if isinstance(usable_scope, dict) else None
    broadly_promoted = usable_scope.get("broadly_promoted") if isinstance(usable_scope, dict) else None

    if not baseline_majority:
        blocking_issues.append("readiness_status_summary: baseline_only majority was not preserved")
    if broadly_promoted not in {None, "no"}:
        blocking_issues.append("hazard_scope_summary: broad hazard promotion claim detected")
    if usable_source not in {None, "hazard_readiness_matrix_only"}:
        blocking_issues.append(f"hazard_scope_summary: unexpected usable probability source {usable_source}")
    if sorted([_as_int(h) for h in expected]) != EXPECTED_HORIZONS:
        blocking_issues.append(f"readiness_status_summary: expected horizons mismatch {expected}")
    if missing_calibration or missing_baseline:
        blocking_issues.append("multi_horizon_evidence: missing calibration or baseline horizons")

    return {
        "readiness_version": hazard_readiness.get("readiness_version"),
        "row_count": row_count,
        "counts": counts,
        "by_horizon": by_horizon,
        "expected_horizons": EXPECTED_HORIZONS,
        "missing_calibration_horizons": missing_calibration,
        "missing_baseline_horizons": missing_baseline,
        "hazard_locally_usable": "yes" if has_local_probability else "no",
        "hazard_broadly_promoted": "no",
        "baseline_only_majority": "yes" if baseline_majority else "no",
    }


def _hazard_scope_summary(hazard_readiness: Mapping[str, Any], hazard_vs_hsmm: Mapping[str, Any]) -> dict[str, Any]:
    brier_raw = hazard_readiness.get("calibrated_vs_raw_brier_summary", {})
    brier_baseline = hazard_readiness.get("calibrated_vs_age_bucket_baseline_summary", {})
    usable_scope = hazard_vs_hsmm.get("usable_probability_scope", {})
    return {
        "usable_probability_scope": {
            "count": _as_int(usable_scope.get("count") if isinstance(usable_scope, dict) else 0),
            "source": (usable_scope.get("source") if isinstance(usable_scope, dict) else None),
            "broadly_promoted": "no",
            "by_horizon": (usable_scope.get("by_horizon") if isinstance(usable_scope, dict) else {}),
        },
        "calibrated_vs_raw_brier": {
            "row_count": _as_int(brier_raw.get("row_count") if isinstance(brier_raw, dict) else 0),
            "non_worse_count": _as_int(brier_raw.get("non_worse_count") if isinstance(brier_raw, dict) else 0),
            "worse_count": _as_int(brier_raw.get("worse_count") if isinstance(brier_raw, dict) else 0),
        },
        "calibrated_vs_age_bucket_baseline": {
            "row_count": _as_int(brier_baseline.get("row_count") if isinstance(brier_baseline, dict) else 0),
            "non_worse_count": _as_int(brier_baseline.get("non_worse_count") if isinstance(brier_baseline, dict) else 0),
            "worse_count": _as_int(brier_baseline.get("worse_count") if isinstance(brier_baseline, dict) else 0),
        },
        "claim": "Hazard probability remains readiness-approved local-slice evidence only.",
    }


def _baseline_scope_summary(hazard_vs_hsmm: Mapping[str, Any], counts: Mapping[str, int]) -> dict[str, Any]:
    baseline_scope = hazard_vs_hsmm.get("baseline_only_scope", {})
    return {
        "baseline_only_count": _as_int(counts.get("baseline_only")),
        "usable_probability_count": _as_int(counts.get("usable_probability")),
        "majority": (
            baseline_scope.get("majority")
            if isinstance(baseline_scope, dict) and baseline_scope.get("majority")
            else ("yes" if _as_int(counts.get("baseline_only")) > _as_int(counts.get("usable_probability")) else "no")
        ),
        "by_horizon": baseline_scope.get("by_horizon") if isinstance(baseline_scope, dict) else {},
        "claim": "Age-bucket baseline remains stronger for most slices.",
    }


def _hsmm_scope_summary(
    *,
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    blocking_issues: list[str],
) -> dict[str, Any]:
    dq_hsmm = data_quality.get("hsmm_diagnostic_namespace_summary", {})
    risk_cleanup = risk_protocol.get("semantic_cleanup_summary", {})
    hazard_boundary = hazard_vs_hsmm.get("boundary_flags", {})
    risk_boundary = risk_protocol.get("boundary_flags", {})
    dq_boundary = data_quality.get("boundary_flags", {})

    hsmm_used_values = [
        hazard_boundary.get("HSMM_p_exit_used_for_decision") if isinstance(hazard_boundary, dict) else None,
        risk_boundary.get("HSMM_p_exit_used_for_decision") if isinstance(risk_boundary, dict) else None,
        dq_boundary.get("HSMM_p_exit_used_for_decision") if isinstance(dq_boundary, dict) else None,
        dq_hsmm.get("hsmm_p_exit_used_for_decision") if isinstance(dq_hsmm, dict) else None,
    ]
    if not all(_is_no(value) for value in hsmm_used_values):
        blocking_issues.append(f"hsmm_scope_summary: HSMM p_exit decision input detected {hsmm_used_values}")

    diagnostic_field = None
    diagnostic_policy = None
    if isinstance(dq_hsmm, dict):
        diagnostic_field = dq_hsmm.get("diagnostic_count_field")
        diagnostic_policy = dq_hsmm.get("diagnostic_policy")
    if not diagnostic_field and isinstance(risk_cleanup, dict):
        diagnostic_field = risk_cleanup.get("diagnostic_count_field")
        diagnostic_policy = risk_cleanup.get("hsmm_lifecycle_probability_status_policy")

    if diagnostic_field != HSMM_DIAGNOSTIC_COUNT_FIELD:
        blocking_issues.append(f"hsmm_scope_summary: diagnostic field mismatch {diagnostic_field}")
    if diagnostic_policy != HSMM_DIAGNOSTIC_POLICY:
        blocking_issues.append(f"hsmm_scope_summary: diagnostic policy mismatch {diagnostic_policy}")

    return {
        "role": "interpretation_only",
        "lifecycle_probability_status_policy": diagnostic_policy,
        "diagnostic_count_field": diagnostic_field,
        "raw_or_calibrated_p_exit_decision_input": "no",
        "numeric_probability_policy": (
            dq_hsmm.get("hsmm_numeric_p_exit_policy")
            if isinstance(dq_hsmm, dict)
            else "not_a_stage03r_decision_input"
        ),
    }


def _risk_protocol_compliance(risk_protocol: Mapping[str, Any], blocking_issues: list[str]) -> dict[str, Any]:
    required_fields = [
        "pre_registered_metrics",
        "split_and_final_holdout_discipline",
        "validation_rules_by_readiness_status",
        "baseline_comparison_rules",
        "hsmm_interpretation_only_rules",
        "failure_abstain_rules",
        "wp10_handoff_contract",
        "boundary_flags",
    ]
    missing = [field for field in required_fields if field not in risk_protocol]
    if missing:
        blocking_issues.append(f"risk_protocol_compliance: missing fields {missing}")

    discipline = risk_protocol.get("split_and_final_holdout_discipline", {})
    boundary = risk_protocol.get("boundary_flags", {})
    final_consumption = discipline.get("final_holdout_consumption") if isinstance(discipline, dict) else None
    repeated_forbidden = discipline.get("repeated_final_tuning_forbidden") if isinstance(discipline, dict) else None
    threshold_tuning = discipline.get("threshold_tuning_in_wp8") if isinstance(discipline, dict) else None

    if final_consumption != "final holdout can be consumed only by an explicit WP10 final-gate run.":
        blocking_issues.append("risk_protocol_compliance: final holdout consumption rule changed")
    if repeated_forbidden != "yes":
        blocking_issues.append("risk_protocol_compliance: repeated final tuning rule not preserved")
    if threshold_tuning != "no":
        blocking_issues.append("risk_protocol_compliance: threshold tuning was allowed")
    if isinstance(boundary, dict):
        if boundary.get("external_data_fetch") != "no":
            blocking_issues.append("risk_protocol_compliance: external fetch not blocked")
        if boundary.get("training_algorithm_modified") != "no":
            blocking_issues.append("risk_protocol_compliance: training modification not blocked")
        if boundary.get("HMM_HSMM_retrained") != "no":
            blocking_issues.append("risk_protocol_compliance: model retraining not blocked")
        if boundary.get("HSMM_p_exit_used_for_decision") != "no":
            blocking_issues.append("risk_protocol_compliance: HSMM p_exit decision input detected")

    forbidden_hits: list[str] = []
    for text in _walk_strings(risk_protocol):
        for term in FORBIDDEN_OUTPUT_TERMS:
            if term in text:
                if term == "decision_surface" and text == "decision_surface_output":
                    continue
                forbidden_hits.append(term)
    if forbidden_hits:
        blocking_issues.append(f"risk_protocol_compliance: forbidden output terms detected {sorted(set(forbidden_hits))}")

    return {
        "status": risk_protocol.get("status"),
        "protocol_version": risk_protocol.get("protocol_version"),
        "missing_required_fields": missing,
        "final_holdout_rule": final_consumption,
        "repeated_final_tuning_forbidden": repeated_forbidden,
        "threshold_tuning_in_wp8": threshold_tuning,
        "pre_registered_metric_count": len(risk_protocol.get("pre_registered_metrics", [])),
        "forbidden_output_terms_detected": sorted(set(forbidden_hits)),
    }


def _data_quality_ci_compliance(data_quality: Mapping[str, Any], blocking_issues: list[str]) -> dict[str, Any]:
    private_summary = data_quality.get("private_data_hygiene_summary", {})
    local_db = data_quality.get("local_db_status", {})
    risk_summary = data_quality.get("risk_protocol_summary", {})
    failures = data_quality.get("failures", [])

    if data_quality.get("status") != "pass":
        blocking_issues.append(f"data_quality_ci_compliance: status is {data_quality.get('status')}")
    if _as_int(data_quality.get("failure_count")) != 0:
        blocking_issues.append(f"data_quality_ci_compliance: failure_count={data_quality.get('failure_count')}")
    if isinstance(private_summary, dict):
        for key in ["duckdb_or_wal_files_committed", "cache_files_committed", "full_prediction_csv_committed"]:
            if private_summary.get(key):
                blocking_issues.append(f"data_quality_ci_compliance: {key} not empty")
        if private_summary.get("private_path_hits"):
            blocking_issues.append("data_quality_ci_compliance: private path hits detected")
    if isinstance(local_db, dict):
        if local_db.get("ci_requires_db") != "no":
            blocking_issues.append("data_quality_ci_compliance: private DB required in CI")
        if local_db.get("external_data_fetch") != "no":
            blocking_issues.append("data_quality_ci_compliance: external fetch detected")
        if local_db.get("DuckDB_committed") not in {None, "no"}:
            blocking_issues.append("data_quality_ci_compliance: DuckDB committed")
    if isinstance(risk_summary, dict):
        if risk_summary.get("forbidden_surface_terms"):
            blocking_issues.append("data_quality_ci_compliance: forbidden protocol terms detected")

    return {
        "status": data_quality.get("status"),
        "report_version": data_quality.get("report_version"),
        "failure_count": _as_int(data_quality.get("failure_count")),
        "warning_count": _as_int(data_quality.get("warning_count")),
        "failures": failures if isinstance(failures, list) else [],
        "private_path_hits": private_summary.get("private_path_hits") if isinstance(private_summary, dict) else [],
        "duckdb_or_wal_files_committed": (
            private_summary.get("duckdb_or_wal_files_committed") if isinstance(private_summary, dict) else []
        ),
        "full_prediction_csv_committed": (
            private_summary.get("full_prediction_csv_committed") if isinstance(private_summary, dict) else []
        ),
        "ci_requires_db": local_db.get("ci_requires_db") if isinstance(local_db, dict) else "no",
        "external_data_fetch": local_db.get("external_data_fetch") if isinstance(local_db, dict) else "no",
    }


def _final_holdout_discipline(
    *,
    final_holdout_artifact: Path | None,
    risk_protocol: Mapping[str, Any],
    blocking_issues: list[str],
    defer_reasons: list[str],
    remediation_items: list[str],
) -> dict[str, Any]:
    protocol_discipline = risk_protocol.get("split_and_final_holdout_discipline", {})
    base = {
        "protocol_rule": (
            protocol_discipline.get("final_holdout_consumption") if isinstance(protocol_discipline, dict) else None
        ),
        "repeated_final_tuning_forbidden": (
            protocol_discipline.get("repeated_final_tuning_forbidden") if isinstance(protocol_discipline, dict) else None
        ),
        "artifact_path": _safe_source_path(final_holdout_artifact),
        "artifact_present": "no",
        "consumed_in_wp10": "no",
        "consumption_count": 0,
        "empirical_broad_promotion_allowed": "no",
    }

    if final_holdout_artifact is None:
        defer_reasons.append(
            "No explicit final holdout artifact was provided; broad empirical promotion remains deferred."
        )
        remediation_items.append(
            "Provide a WP8-compliant final holdout artifact and consume it once in WP10 before broad empirical promotion."
        )
        return base

    if not final_holdout_artifact.exists():
        defer_reasons.append(
            f"Final holdout artifact path was provided but not found: {_safe_source_path(final_holdout_artifact)}."
        )
        remediation_items.append("Generate the explicit final holdout artifact once under the WP8 protocol.")
        return base

    try:
        holdout = json.loads(final_holdout_artifact.read_text(encoding="utf-8"))
    except Exception as exc:
        blocking_issues.append(f"final_holdout_discipline: final holdout artifact is unparseable ({exc})")
        return base | {"artifact_present": "yes"}

    if not isinstance(holdout, dict):
        blocking_issues.append("final_holdout_discipline: final holdout artifact root is not an object")
        return base | {"artifact_present": "yes"}

    count = _as_int(
        holdout.get(
            "consumption_count",
            holdout.get("holdout_consumption_count", holdout.get("final_holdout_consumption_count", 0)),
        )
    )
    tuned = holdout.get("tuned_on_holdout", holdout.get("threshold_tuning_on_holdout", "no"))
    threshold_tuned = holdout.get("threshold_tuning_on_holdout", tuned)
    model_retrained = holdout.get("model_retrained", "no")
    hmm_hsmm_retrained = holdout.get("HMM_HSMM_retrained", "no")
    hsmm_decision = holdout.get("HSMM_p_exit_used_for_decision", "no")
    surface_output = holdout.get("decision_surface_output", "no")
    wp10_only = holdout.get("wp10_only", holdout.get("consumed_for_wp10_only", "yes"))
    consumed = holdout.get("consumed_in_wp10", "yes" if count == 1 else "no")
    external_fetch = holdout.get("external_data_fetch", "no")
    artifact_empirical = str(holdout.get("empirical_promotion_verdict", "")).upper() or None
    non_overlap_status = holdout.get("non_overlap_status")
    artifact_defer_reasons = holdout.get("defer_reasons", [])
    artifact_blocking_issues = holdout.get("blocking_issues", [])

    if count > 1:
        blocking_issues.append("final_holdout_discipline: final holdout consumption count exceeds one")
    if _is_yes(tuned) or _is_yes(threshold_tuned):
        blocking_issues.append("final_holdout_discipline: tuning on final holdout detected")
    if _is_yes(model_retrained) or _is_yes(hmm_hsmm_retrained):
        blocking_issues.append("final_holdout_discipline: model retraining detected")
    if _is_yes(hsmm_decision):
        blocking_issues.append("final_holdout_discipline: HSMM p_exit decision input detected")
    if surface_output not in {None, "no"}:
        blocking_issues.append("final_holdout_discipline: surface/action output detected")
    if wp10_only in {"no", False}:
        blocking_issues.append("final_holdout_discipline: final holdout was not WP10-only")
    if external_fetch != "no":
        blocking_issues.append("final_holdout_discipline: external fetch detected in holdout artifact")
    if artifact_empirical == "BLOCKED" or artifact_blocking_issues:
        blocking_issues.append("final_holdout_discipline: artifact reported blocking issues")

    return base | {
        "artifact_present": "yes",
        "consumed_in_wp10": "yes" if _is_yes(consumed) else "no",
        "consumption_count": count,
        "wp10_only": "yes" if wp10_only in {"yes", True} else "no",
        "tuned_on_holdout": "yes" if _is_yes(tuned) else "no",
        "external_data_fetch": external_fetch,
        "artifact_empirical_promotion_verdict": artifact_empirical,
        "non_overlap_status": non_overlap_status,
        "artifact_defer_reasons": artifact_defer_reasons if isinstance(artifact_defer_reasons, list) else [],
        "artifact_blocking_issue_count": len(artifact_blocking_issues) if isinstance(artifact_blocking_issues, list) else 0,
        "empirical_broad_promotion_allowed": "no",
    }


def _boundary_flags(
    *,
    hazard_readiness: Mapping[str, Any],
    hazard_vs_hsmm: Mapping[str, Any],
    risk_protocol: Mapping[str, Any],
    data_quality: Mapping[str, Any],
    final_holdout: Mapping[str, Any],
    blocking_issues: list[str],
) -> dict[str, str]:
    flags = dict(SAFE_BOUNDARY_FLAGS)
    raw_flag_groups = [
        hazard_vs_hsmm.get("boundary_flags", {}),
        risk_protocol.get("boundary_flags", {}),
        data_quality.get("boundary_flags", {}),
    ]
    external_fetch_values = [hazard_readiness.get("external_data_fetch"), final_holdout.get("external_data_fetch")]
    training_modified_values = [hazard_readiness.get("training_algorithm_modified")]
    retrained_values: list[Any] = []
    hsmm_decision_values = [hazard_readiness.get("hsmm_p_exit_used")]
    duckdb_values = [hazard_readiness.get("DuckDB_committed")]
    for group in raw_flag_groups:
        if not isinstance(group, dict):
            continue
        external_fetch_values.append(group.get("external_data_fetch"))
        training_modified_values.append(group.get("training_algorithm_modified"))
        retrained_values.append(group.get("HMM_HSMM_retrained"))
        hsmm_decision_values.append(group.get("HSMM_p_exit_used_for_decision"))
        duckdb_values.append(group.get("DuckDB_committed"))

    if not all(_is_no(value) for value in external_fetch_values):
        blocking_issues.append(f"boundary_flags: external fetch detected {external_fetch_values}")
    if not all(_is_no(value) for value in training_modified_values):
        blocking_issues.append(f"boundary_flags: training algorithm modification detected {training_modified_values}")
    if not all(_is_no(value) for value in retrained_values):
        blocking_issues.append(f"boundary_flags: HMM/HSMM retraining detected {retrained_values}")
    if not all(_is_no(value) for value in hsmm_decision_values):
        blocking_issues.append(f"boundary_flags: HSMM p_exit decision input detected {hsmm_decision_values}")
    if not all(_is_no(value) for value in duckdb_values):
        blocking_issues.append(f"boundary_flags: DuckDB commit detected {duckdb_values}")

    return flags


def _next_stage_recommendations() -> list[str]:
    return [
        "Keep hazard probability local-slice only until an explicit final holdout artifact is evaluated once.",
        "Retain age-bucket baseline as the majority fallback and report baseline-only slices without pseudo-probability.",
        "Keep HSMM lifecycle outputs as interpretation-only context.",
        "Define any future decision surface in a later stage with separate pre-registration and trial accounting.",
    ]


def evaluate_final_gate(
    *,
    hazard_readiness_path: Path,
    hazard_vs_hsmm_path: Path,
    risk_protocol_path: Path,
    data_quality_path: Path,
    hazard_verdict_path: Path,
    final_holdout_artifact: Path | None = None,
    db_path: str | None = None,
    root: Path | None = None,
    gate_statuses: Mapping[str, Any] | None = None,
    run_gate_scripts: bool = False,
) -> FinalGateResult:
    root = root or Path.cwd()
    blocking_issues: list[str] = []
    defer_reasons: list[str] = []
    remediation_items: list[str] = []

    hazard_readiness = _load_json(hazard_readiness_path, "hazard_readiness_matrix", blocking_issues)
    hazard_vs_hsmm = _load_json(hazard_vs_hsmm_path, "hazard_vs_hsmm", blocking_issues)
    risk_protocol = _load_json(risk_protocol_path, "risk_validation_protocol", blocking_issues)
    data_quality = _load_json(data_quality_path, "data_quality_ci", blocking_issues)
    hazard_verdict_text = _read_text(hazard_verdict_path, "multi_horizon_hazard_verdict", blocking_issues)

    artifact_summary = _artifact_schema_summary(
        hazard_readiness=hazard_readiness,
        hazard_vs_hsmm=hazard_vs_hsmm,
        risk_protocol=risk_protocol,
        data_quality=data_quality,
        hazard_verdict_text=hazard_verdict_text,
        blocking_issues=blocking_issues,
    )
    gate_summary = _gate_status_summary(
        gate_statuses=gate_statuses,
        run_gate_scripts=run_gate_scripts,
        root=root,
        data_quality=data_quality,
        blocking_issues=blocking_issues,
    )
    readiness_summary = _readiness_status_summary(
        hazard_readiness=hazard_readiness,
        risk_protocol=risk_protocol,
        hazard_vs_hsmm=hazard_vs_hsmm,
        blocking_issues=blocking_issues,
    )
    hazard_summary = _hazard_scope_summary(hazard_readiness, hazard_vs_hsmm)
    baseline_summary = _baseline_scope_summary(hazard_vs_hsmm, readiness_summary.get("counts", {}))
    hsmm_summary = _hsmm_scope_summary(
        hazard_vs_hsmm=hazard_vs_hsmm,
        risk_protocol=risk_protocol,
        data_quality=data_quality,
        blocking_issues=blocking_issues,
    )
    risk_summary = _risk_protocol_compliance(risk_protocol, blocking_issues)
    data_quality_summary = _data_quality_ci_compliance(data_quality, blocking_issues)
    local_db = _local_db_status(db_path)
    data_quality_summary["local_db_status"] = local_db
    final_holdout = _final_holdout_discipline(
        final_holdout_artifact=final_holdout_artifact,
        risk_protocol=risk_protocol,
        blocking_issues=blocking_issues,
        defer_reasons=defer_reasons,
        remediation_items=remediation_items,
    )
    boundary_flags = _boundary_flags(
        hazard_readiness=hazard_readiness,
        hazard_vs_hsmm=hazard_vs_hsmm,
        risk_protocol=risk_protocol,
        data_quality=data_quality,
        final_holdout=final_holdout,
        blocking_issues=blocking_issues,
    )

    # Preserve artifact schema evidence without dumping raw source fields that
    # are explicitly forbidden as WP10 outputs.
    package_evidence = _package_evidence()
    package_evidence["artifact_schema_summary"] = artifact_summary

    engineering_gate_verdict = "BLOCKED" if blocking_issues else "PASS"
    if blocking_issues:
        empirical_promotion_verdict = "BLOCKED"
        final_verdict = "BLOCKED"
    elif final_holdout.get("artifact_present") == "no":
        empirical_promotion_verdict = "DEFER"
        final_verdict = "DEFER"
    elif final_holdout.get("artifact_empirical_promotion_verdict") == "DEFER" or final_holdout.get(
        "non_overlap_status"
    ) not in {None, "proven_non_overlap"}:
        empirical_promotion_verdict = "DEFER"
        final_verdict = "DEFER"
        for reason in final_holdout.get("artifact_defer_reasons", []):
            defer_reasons.append(str(reason))
    elif readiness_summary.get("baseline_only_majority") == "yes" or hazard_summary["usable_probability_scope"].get(
        "broadly_promoted"
    ) == "no":
        empirical_promotion_verdict = "LOCAL_ONLY"
        final_verdict = "DEFER"
        defer_reasons.append("Hazard probability remains local-slice only and is not a broad empirical promotion.")
    else:
        empirical_promotion_verdict = "PASS"
        final_verdict = "PASS"

    status = {"PASS": "pass", "BLOCKED": "blocked", "DEFER": "defer"}.get(final_verdict, "defer")
    if final_verdict == "BLOCKED" and not remediation_items:
        remediation_items.append("Resolve blocking gate or artifact invariant failures, then rerun WP10 final gate.")

    return FinalGateResult(
        status=status,
        final_gate_version=FINAL_GATE_VERSION,
        final_verdict=final_verdict,
        engineering_gate_verdict=engineering_gate_verdict,
        empirical_promotion_verdict=empirical_promotion_verdict,
        package_evidence=package_evidence,
        gate_status_summary=gate_summary,
        readiness_status_summary=readiness_summary,
        hazard_scope_summary=hazard_summary,
        baseline_scope_summary=baseline_summary,
        hsmm_scope_summary=hsmm_summary,
        risk_protocol_compliance=risk_summary,
        data_quality_ci_compliance=data_quality_summary,
        final_holdout_discipline=final_holdout,
        blocking_issues=blocking_issues,
        defer_reasons=defer_reasons,
        remediation_items=remediation_items,
        boundary_flags=boundary_flags,
        next_stage_recommendations=_next_stage_recommendations(),
    )


def _json_block(value: Any) -> list[str]:
    return ["```json", json.dumps(value, ensure_ascii=False, indent=2, default=_json_default), "```"]


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP10 Final Gate Report",
        "",
        "## Executive final verdict",
        "",
        (
            f"Final verdict: {summary.get('final_verdict')}. Engineering gate: "
            f"{summary.get('engineering_gate_verdict')}. Empirical promotion: "
            f"{summary.get('empirical_promotion_verdict')}."
        ),
        "",
        "Hazard probability remains readiness-approved local-slice evidence only. "
        "Age-bucket baseline remains the majority fallback, and HSMM remains interpretation-only.",
        "",
        "## Stage03R package evidence summary",
        "",
        *_json_block(summary.get("package_evidence", {})),
        "",
        "## Required gate status summary",
        "",
        *_json_block(summary.get("gate_status_summary", {})),
        "",
        "## Hazard readiness final summary",
        "",
        *_json_block(summary.get("readiness_status_summary", {})),
        "",
        "## Multi-horizon evidence summary",
        "",
        *_json_block(
            {
                "expected_horizons": summary.get("readiness_status_summary", {}).get("expected_horizons"),
                "missing_calibration_horizons": summary.get("readiness_status_summary", {}).get(
                    "missing_calibration_horizons"
                ),
                "missing_baseline_horizons": summary.get("readiness_status_summary", {}).get(
                    "missing_baseline_horizons"
                ),
            }
        ),
        "",
        "## Hazard vs baseline summary",
        "",
        *_json_block(summary.get("baseline_scope_summary", {})),
        "",
        "## Hazard vs HSMM summary",
        "",
        *_json_block(summary.get("hsmm_scope_summary", {})),
        "",
        "## Risk validation protocol compliance",
        "",
        *_json_block(summary.get("risk_protocol_compliance", {})),
        "",
        "## Data-quality CI compliance",
        "",
        *_json_block(summary.get("data_quality_ci_compliance", {})),
        "",
        "## Final holdout discipline",
        "",
        *_json_block(summary.get("final_holdout_discipline", {})),
        "",
        "## PASS/BLOCKED/DEFER rules",
        "",
        "- PASS requires all engineering gates and a compliant empirical promotion artifact.",
        "- BLOCKED is emitted for missing artifacts, failing gates, boundary violations, or repeated final holdout use.",
        "- DEFER is emitted when engineering controls pass but broad empirical promotion is not yet supported.",
        "",
        "## Remaining limitations",
        "",
        "- Hazard usable probability is local-slice only.",
        "- Baseline-only remains the majority readiness status.",
        "- HSMM remains interpretation-only.",
        "- No decision surface exists yet.",
        "",
        "## Boundary confirmation",
        "",
        *_json_block(summary.get("boundary_flags", {})),
        "",
        "## Next-stage recommendations",
        "",
        *_json_block(summary.get("next_stage_recommendations", [])),
        "",
        "## Blocking issues",
        "",
        *_json_block(summary.get("blocking_issues", [])),
        "",
        "## Defer reasons",
        "",
        *_json_block(summary.get("defer_reasons", [])),
        "",
        "## Remediation items",
        "",
        *_json_block(summary.get("remediation_items", [])),
    ]
    return "\n".join(lines) + "\n"


def _assert_no_forbidden_output_terms(summary: Mapping[str, Any], markdown: str) -> None:
    rendered = json.dumps(summary, ensure_ascii=False, default=_json_default) + "\n" + markdown
    hits = [term for term in FORBIDDEN_OUTPUT_TERMS if term in rendered]
    if hits:
        raise ValueError(f"WP10 output contains forbidden terms: {sorted(set(hits))}")


def write_outputs(result: FinalGateResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    markdown = build_report_markdown(summary)
    _assert_no_forbidden_output_terms(summary, markdown)
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def run_cli(args: argparse.Namespace) -> int:
    final_holdout = Path(args.final_holdout_artifact) if args.final_holdout_artifact else None
    result = evaluate_final_gate(
        hazard_readiness_path=Path(args.hazard_readiness),
        hazard_vs_hsmm_path=Path(args.hazard_vs_hsmm),
        risk_protocol_path=Path(args.risk_protocol),
        data_quality_path=Path(args.data_quality),
        hazard_verdict_path=Path(args.hazard_verdict),
        final_holdout_artifact=final_holdout,
        db_path=args.db,
        root=Path(args.root) if args.root else Path.cwd(),
        run_gate_scripts=not args.skip_gate_scripts,
    )
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 1 if result.status == "blocked" else 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage03R WP10 final gate")
    parser.add_argument("--hazard-readiness", required=True)
    parser.add_argument("--hazard-vs-hsmm", required=True)
    parser.add_argument("--risk-protocol", required=True)
    parser.add_argument("--data-quality", required=True)
    parser.add_argument("--hazard-verdict", required=True)
    parser.add_argument("--final-holdout-artifact", default=None)
    parser.add_argument("--db", default=None)
    parser.add_argument("--root", default=None)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    parser.add_argument("--skip-gate-scripts", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
