"""Stage03R WP7 hazard vs HSMM comparison report.

This module compares Duration Hazard readiness evidence against HSMM lifecycle
interpretation fields. It does not train models, fetch data, consume HSMM
numeric p_exit as a decision input, create risk validation, or emit decision
surfaces.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


INDEX_ID = "STAGE03R-WP7"
REPORT_VERSION = "hazard_vs_hsmm_report_v1"
EXPECTED_HORIZONS = (1, 3, 5, 10, 20)
READINESS_STATUSES = (
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
)
BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "training_algorithm_modified": "no",
    "HMM_HSMM_retrained": "no",
    "HSMM_p_exit_used_for_decision": "no",
    "decision_ready_output": "no",
    "DuckDB_committed": "no",
}
HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY = "diagnostic_only_not_decision_input"


@dataclass
class HazardVsHsmmResult:
    status: str
    report_version: str
    hazard_readiness_counts: dict[str, int]
    hazard_by_horizon: list[dict[str, Any]]
    hsmm_lifecycle_availability: dict[str, Any]
    hazard_vs_hsmm_by_horizon: list[dict[str, Any]]
    hazard_vs_hsmm_verdict: str
    hazard_vs_age_bucket_baseline_verdict: str
    usable_probability_scope: dict[str, Any]
    baseline_only_scope: dict[str, Any]
    failure_abstain_cases: dict[str, Any]
    input_artifacts: dict[str, Any]
    local_db_validation: dict[str, Any] = field(default_factory=dict)
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


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _status_counts(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = {status: 0 for status in READINESS_STATUSES}
    for row in rows:
        status = str(row.get("readiness_status", "invalid"))
        counts[status] = counts.get(status, 0) + 1
    return {status: int(counts.get(status, 0)) for status in READINESS_STATUSES}


def _counts_by_horizon(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    horizons = sorted({_as_int(row.get("horizon_days")) for row in rows if row.get("horizon_days") is not None})
    for horizon in horizons:
        subset = [row for row in rows if _as_int(row.get("horizon_days")) == horizon]
        counts = _status_counts(subset)
        raw_deltas = [_as_float(row.get("brier_delta_calibrated_vs_raw")) for row in subset]
        baseline_deltas = [_as_float(row.get("brier_delta_calibrated_vs_baseline")) for row in subset]
        raw_numeric = [value for value in raw_deltas if value is not None]
        baseline_numeric = [value for value in baseline_deltas if value is not None]
        out.append(
            {
                "horizon_days": horizon,
                "readiness_status_counts": counts,
                "usable_probability_count": counts.get("usable_probability", 0),
                "baseline_only_count": counts.get("baseline_only", 0),
                "insufficient_sample_count": counts.get("insufficient_sample", 0),
                "calibrated_vs_raw_mean": _mean(raw_numeric),
                "calibrated_vs_raw_non_worse_count": sum(1 for value in raw_numeric if value <= 0.0),
                "calibrated_vs_raw_row_count": len(raw_numeric),
                "calibrated_vs_baseline_mean": _mean(baseline_numeric),
                "calibrated_vs_baseline_non_worse_count": sum(1 for value in baseline_numeric if value <= 0.0),
                "calibrated_vs_baseline_row_count": len(baseline_numeric),
            }
        )
    return out


def _mean(values: Sequence[float]) -> float | None:
    return float(sum(values) / len(values)) if values else None


def _safe_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _empty_hsmm_summary(db_path: str | None = None) -> dict[str, Any]:
    return {
        "available": "no",
        "db_path_used": db_path,
        "db_found": "no",
        "opened_read_only": "no",
        "row_count": 0,
        "run_ids": [],
        "profile_policy_counts": [],
        "p_exit_columns": [],
        "exit_tendency_columns": [],
        "hsmm_lifecycle_probability_status_policy": HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
        "lifecycle_probability_status_columns_diagnostic_only": [],
        "matched_numeric_artifact": "missing",
        "hsmm_numeric_p_exit_policy": "not_available",
        "ordinal_tendency_available": "no",
        "per_horizon": {},
        "matched_slice_count_by_horizon": {},
    }


def load_hsmm_lifecycle_summary(db_path: str | None, hazard_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not db_path:
        return _empty_hsmm_summary()
    path = Path(db_path)
    safe_path = _safe_source_path(path)
    if not path.exists():
        return _empty_hsmm_summary(safe_path)

    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        out = _empty_hsmm_summary(safe_path)
        out["db_found"] = "yes"
        out["open_error"] = str(exc)
        return out

    try:
        columns = [row[0] for row in con.execute("describe hsmm_lifecycle_ui_daily").fetchall()]
        row_count = int(con.execute("select count(*) from hsmm_lifecycle_ui_daily").fetchone()[0])
        run_ids = [
            {
                "run_id": row[0],
                "row_count": int(row[1]),
                "min_trade_date": _json_default(row[2]),
                "max_trade_date": _json_default(row[3]),
            }
            for row in con.execute(
                """
                select run_id, count(*) as n, min(trade_date), max(trade_date)
                from hsmm_lifecycle_ui_daily
                group by run_id
                order by max(trade_date) desc, n desc
                """
            ).fetchall()
        ]
        profile_policy_counts = [
            {
                "profile_mode": row[0],
                "state_date_policy": row[1],
                "row_count": int(row[2]),
                "min_trade_date": _json_default(row[3]),
                "max_trade_date": _json_default(row[4]),
            }
            for row in con.execute(
                """
                select profile_mode, state_date_policy, count(*) as n, min(trade_date), max(trade_date)
                from hsmm_lifecycle_ui_daily
                group by profile_mode, state_date_policy
                order by n desc
                """
            ).fetchall()
        ]
        p_exit_columns = [column for column in columns if "p_exit" in column.lower()]
        exit_tendency_columns = [column for column in columns if column.startswith("exit_tendency_")]
        probability_status_columns = [
            column for column in columns if column.startswith("probability_status_") or column.startswith("raw_score_used_")
        ]
        hazard_keys_by_horizon = {
            horizon: {
                (
                    str(row.get("state_label")),
                    str(row.get("state_phase")),
                    str(row.get("age_bucket")),
                    str(row.get("profile_mode")),
                    str(row.get("state_date_policy")),
                )
                for row in hazard_rows
                if _as_int(row.get("horizon_days")) == horizon
            }
            for horizon in EXPECTED_HORIZONS
        }
        per_horizon: dict[str, Any] = {}
        matched_slice_count_by_horizon: dict[str, int] = {}
        for horizon in EXPECTED_HORIZONS:
            tendency_col = f"exit_tendency_{horizon}d"
            probability_col = f"probability_status_{horizon}d"
            raw_col = f"raw_score_used_{horizon}d"
            if tendency_col not in columns:
                per_horizon[str(horizon)] = {
                    "available": "no",
                    "ordinal_tendency_counts": {},
                    "lifecycle_probability_status_counts_diagnostic_only": {},
                    "raw_score_used_counts_diagnostic_only": {},
                }
                matched_slice_count_by_horizon[str(horizon)] = 0
                continue
            rows = con.execute(
                f"""
                select
                    state_label,
                    state_phase,
                    display_age_bucket,
                    profile_mode,
                    state_date_policy,
                    {tendency_col} as tendency,
                    {probability_col if probability_col in columns else "NULL"} as probability_status,
                    {raw_col if raw_col in columns else "NULL"} as raw_score_used,
                    count(*) as n
                from hsmm_lifecycle_ui_daily
                group by 1,2,3,4,5,6,7,8
                """
            ).fetchall()
            tendency_counts: dict[str, int] = {}
            probability_counts: dict[str, int] = {}
            raw_counts: dict[str, int] = {}
            matched_keys = set()
            target_keys = hazard_keys_by_horizon.get(horizon, set())
            for row in rows:
                key = (str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]))
                if key in target_keys:
                    matched_keys.add(key)
                n = int(row[8])
                tendency_counts[str(row[5])] = tendency_counts.get(str(row[5]), 0) + n
                probability_counts[str(row[6])] = probability_counts.get(str(row[6]), 0) + n
                raw_counts[str(row[7])] = raw_counts.get(str(row[7]), 0) + n
            matched_slice_count_by_horizon[str(horizon)] = len(matched_keys)
            per_horizon[str(horizon)] = {
                "available": "yes",
                "ordinal_tendency_counts": dict(sorted(tendency_counts.items())),
                "lifecycle_probability_status_counts_diagnostic_only": dict(sorted(probability_counts.items())),
                "raw_score_used_counts_diagnostic_only": dict(sorted(raw_counts.items())),
                "matched_hazard_slice_count": len(matched_keys),
                "hazard_slice_count": len(target_keys),
            }
        return {
            "available": "yes",
            "db_path_used": safe_path,
            "db_found": "yes",
            "opened_read_only": "yes",
            "row_count": row_count,
            "run_ids": run_ids,
            "profile_policy_counts": profile_policy_counts,
            "p_exit_columns": p_exit_columns,
            "exit_tendency_columns": exit_tendency_columns,
            "hsmm_lifecycle_probability_status_policy": HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
            "lifecycle_probability_status_columns_diagnostic_only": probability_status_columns,
            "matched_numeric_artifact": "present" if p_exit_columns else "missing",
            "hsmm_numeric_p_exit_policy": "diagnostic_only_not_decision_input" if p_exit_columns else "not_available",
            "ordinal_tendency_available": "yes" if exit_tendency_columns else "no",
            "per_horizon": per_horizon,
            "matched_slice_count_by_horizon": matched_slice_count_by_horizon,
        }
    except Exception as exc:
        out = _empty_hsmm_summary(safe_path)
        out["db_found"] = "yes"
        out["opened_read_only"] = "yes"
        out["read_error"] = str(exc)
        return out
    finally:
        try:
            con.close()
        except Exception:
            pass


def _local_db_validation(hsmm_summary: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "db_path_used": hsmm_summary.get("db_path_used"),
        "db_found": hsmm_summary.get("db_found", "no"),
        "opened_read_only": hsmm_summary.get("opened_read_only", "no"),
        "key_tables_checked": ["hsmm_lifecycle_ui_daily"],
        "row_counts": {"hsmm_lifecycle_ui_daily": hsmm_summary.get("row_count", 0)},
        "external_data_fetch": "no",
        "DuckDB_committed": "no",
    }


def evaluate_hazard_vs_hsmm(
    *,
    hazard_readiness: Mapping[str, Any],
    age_bucket_baseline: Mapping[str, Any],
    hazard_verdict_text: str = "",
    hsmm_lifecycle_summary: Mapping[str, Any] | None = None,
    input_artifacts: Mapping[str, Any] | None = None,
) -> HazardVsHsmmResult:
    hazard_rows = [dict(row) for row in hazard_readiness.get("readiness_rows", [])]
    readiness_counts = _status_counts(hazard_rows)
    by_horizon = _counts_by_horizon(hazard_rows)
    hsmm_summary = dict(hsmm_lifecycle_summary or _empty_hsmm_summary())
    per_horizon: list[dict[str, Any]] = []
    for horizon_row in by_horizon:
        horizon = str(horizon_row["horizon_days"])
        hsmm_horizon = dict(hsmm_summary.get("per_horizon", {}).get(horizon, {}))
        lifecycle_probability_counts = hsmm_horizon.get(
            "lifecycle_probability_status_counts_diagnostic_only",
            hsmm_horizon.get("probability_status_counts", {}),
        )
        usable = horizon_row["usable_probability_count"]
        baseline = horizon_row["baseline_only_count"]
        if hsmm_horizon.get("available") == "yes" and usable > 0:
            verdict = "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked"
        elif hsmm_horizon.get("available") == "yes":
            verdict = "hazard not promoted; HSMM remains interpretation-only context"
        elif usable > 0:
            verdict = "hazard locally usable; matched HSMM lifecycle artifact missing"
        else:
            verdict = "baseline or abstain dominates; matched HSMM lifecycle artifact missing"
        if baseline > usable:
            verdict += "; baseline_only majority preserved"
        per_horizon.append(
            {
                "horizon_days": horizon_row["horizon_days"],
                "hazard_readiness_counts": horizon_row["readiness_status_counts"],
                "usable_probability_count": usable,
                "baseline_only_count": baseline,
                "hsmm_lifecycle_available": hsmm_horizon.get("available", "no"),
                "hsmm_matched_hazard_slice_count": hsmm_horizon.get("matched_hazard_slice_count", 0),
                "hsmm_ordinal_tendency_counts": hsmm_horizon.get("ordinal_tendency_counts", {}),
                "hsmm_lifecycle_probability_status_policy": hsmm_summary.get(
                    "hsmm_lifecycle_probability_status_policy",
                    HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
                ),
                "hsmm_lifecycle_probability_status_counts_diagnostic_only": lifecycle_probability_counts,
                "verdict": verdict,
            }
        )
    total_rows = int(sum(readiness_counts.values()))
    baseline_majority = readiness_counts.get("baseline_only", 0) > readiness_counts.get("usable_probability", 0)
    hazard_vs_hsmm_verdict = (
        "Duration Hazard is locally usable but not broadly promoted. HSMM lifecycle fields remain "
        "interpretation-only context, and HSMM numeric p_exit is not used as a decision input."
    )
    if hsmm_summary.get("available") != "yes":
        hazard_vs_hsmm_verdict += " Matched HSMM lifecycle table is unavailable in this run."
    hazard_vs_age_bucket_verdict = (
        "Age-bucket baseline remains stronger for the majority of slices; usable hazard probability is limited "
        "to readiness-approved local slices."
        if baseline_majority
        else "Usable hazard probability is not a broad baseline replacement; review slice-level evidence."
    )
    usable_rows = [row for row in hazard_rows if row.get("readiness_status") == "usable_probability"]
    baseline_rows = [row for row in hazard_rows if row.get("readiness_status") == "baseline_only"]
    insufficient_rows = [row for row in hazard_rows if row.get("readiness_status") == "insufficient_sample"]
    invalid_rows = [row for row in hazard_rows if row.get("readiness_status") == "invalid"]
    warnings: list[str] = []
    if hsmm_summary.get("matched_numeric_artifact") == "missing":
        warnings.append("matched HSMM numeric p_exit artifact missing; no numeric probability comparison fabricated")
    if baseline_majority:
        warnings.append("baseline_only is the majority readiness status")
    return HazardVsHsmmResult(
        status="pass" if total_rows else "partial",
        report_version=REPORT_VERSION,
        hazard_readiness_counts=readiness_counts,
        hazard_by_horizon=by_horizon,
        hsmm_lifecycle_availability=hsmm_summary,
        hazard_vs_hsmm_by_horizon=per_horizon,
        hazard_vs_hsmm_verdict=hazard_vs_hsmm_verdict,
        hazard_vs_age_bucket_baseline_verdict=hazard_vs_age_bucket_verdict,
        usable_probability_scope={
            "count": len(usable_rows),
            "source": "hazard_readiness_matrix_only",
            "broadly_promoted": "no",
            "by_horizon": {
                str(row["horizon_days"]): row["usable_probability_count"] for row in by_horizon
            },
        },
        baseline_only_scope={
            "count": len(baseline_rows),
            "majority": "yes" if baseline_majority else "no",
            "by_horizon": {
                str(row["horizon_days"]): row["baseline_only_count"] for row in by_horizon
            },
        },
        failure_abstain_cases={
            "insufficient_sample_count": len(insufficient_rows),
            "invalid_count": len(invalid_rows),
            "insufficient_sample_by_horizon": {
                str(row["horizon_days"]): row["insufficient_sample_count"] for row in by_horizon
            },
        },
        input_artifacts=dict(input_artifacts or {}),
        local_db_validation=_local_db_validation(hsmm_summary),
        warnings=warnings,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    hsmm = summary.get("hsmm_lifecycle_availability", {})
    lines = [
        "# Stage03R WP7 Hazard vs HSMM Report",
        "",
        "## Executive Verdict",
        "",
        str(summary.get("hazard_vs_hsmm_verdict")),
        "",
        str(summary.get("hazard_vs_age_bucket_baseline_verdict")),
        "",
        "## Input Artifacts And Versions",
        "",
        "```json",
        json.dumps(summary.get("input_artifacts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Hazard Readiness Summary",
        "",
        "```json",
        json.dumps(summary.get("hazard_readiness_counts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## HSMM Lifecycle Availability Summary",
        "",
        "```json",
        json.dumps(
            {
                "available": hsmm.get("available"),
                "row_count": hsmm.get("row_count"),
                "ordinal_tendency_available": hsmm.get("ordinal_tendency_available"),
                "matched_numeric_artifact": hsmm.get("matched_numeric_artifact"),
                "hsmm_numeric_p_exit_policy": hsmm.get("hsmm_numeric_p_exit_policy"),
                "hsmm_lifecycle_probability_status_policy": hsmm.get(
                    "hsmm_lifecycle_probability_status_policy",
                    HSMM_LIFECYCLE_PROBABILITY_STATUS_POLICY,
                ),
                "p_exit_columns": hsmm.get("p_exit_columns", []),
                "lifecycle_probability_status_columns_diagnostic_only": hsmm.get(
                    "lifecycle_probability_status_columns_diagnostic_only",
                    [],
                ),
                "profile_policy_counts": hsmm.get("profile_policy_counts", []),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        "```",
        "",
        "## Hazard vs HSMM Comparison By Horizon",
        "",
        "```json",
        json.dumps(summary.get("hazard_vs_hsmm_by_horizon", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Hazard vs Age-Bucket Baseline Summary",
        "",
        str(summary.get("hazard_vs_age_bucket_baseline_verdict")),
        "",
        "## Where Usable Probability Is Allowed",
        "",
        "```json",
        json.dumps(summary.get("usable_probability_scope", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Where Baseline Only Should Dominate",
        "",
        "```json",
        json.dumps(summary.get("baseline_only_scope", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Where HSMM Should Remain Interpretation-Only",
        "",
        "- HSMM lifecycle fields provide state age, phase, duration profile, and ordinal exit tendency context.",
        "- HSMM numeric exit probabilities are not used for decision input in this report.",
        "- If HSMM numeric fields are present, their policy is diagnostic-only and not a promotion signal.",
        "",
        "## Failure And Abstain Cases",
        "",
        "```json",
        json.dumps(summary.get("failure_abstain_cases", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        "- external data fetch: no",
        "- training algorithm modified: no",
        "- HMM/HSMM retrained: no",
        "- HSMM numeric exit probability used for decision input: no",
        "- decision-ready output: no",
        "- DuckDB committed: no",
        "",
        "## Warnings",
        "",
        "```json",
        json.dumps(summary.get("warnings", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: HazardVsHsmmResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def run_cli(args: argparse.Namespace) -> int:
    hazard_readiness = _load_json(Path(args.hazard_readiness))
    age_bucket_baseline = _load_json(Path(args.age_bucket_baseline))
    verdict_path = Path(args.hazard_verdict) if args.hazard_verdict else None
    verdict_text = verdict_path.read_text(encoding="utf-8") if verdict_path and verdict_path.exists() else ""
    hsmm_summary = load_hsmm_lifecycle_summary(args.db, hazard_readiness.get("readiness_rows", []))
    result = evaluate_hazard_vs_hsmm(
        hazard_readiness=hazard_readiness,
        age_bucket_baseline=age_bucket_baseline,
        hazard_verdict_text=verdict_text,
        hsmm_lifecycle_summary=hsmm_summary,
        input_artifacts={
            "hazard_readiness": _safe_source_path(Path(args.hazard_readiness)),
            "hazard_verdict": _safe_source_path(verdict_path),
            "age_bucket_baseline": _safe_source_path(Path(args.age_bucket_baseline)),
            "hazard_readiness_version": hazard_readiness.get("readiness_version"),
            "age_bucket_baseline_version": age_bucket_baseline.get("baseline_version"),
            "wp6_1_verdict_present": "yes" if verdict_text else "no",
        },
    )
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R WP7 hazard vs HSMM report")
    parser.add_argument("--hazard-readiness", required=True, help="WP6 hazard readiness JSON")
    parser.add_argument("--hazard-verdict", default=None, help="WP6.1 multi-horizon verdict markdown")
    parser.add_argument("--age-bucket-baseline", required=True, help="WP4 age-bucket baseline JSON")
    parser.add_argument("--db", default=None, help="Optional local DuckDB path for HSMM lifecycle read-only summary")
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
