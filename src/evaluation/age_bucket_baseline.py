"""Stage03R WP4 age-bucket empirical baseline.

This module builds an empirical comparison baseline from exit_target_dataset_v1.
It does not fetch data, calibrate probabilities, create readiness matrices, or
modify HMM/HSMM training algorithms.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd

from src.evaluation.exit_target_dataset import (
    OBSERVED_NEGATIVE,
    OBSERVED_POSITIVE,
    RIGHT_CENSORED_BY_CUTOFF,
    RIGHT_CENSORED_BY_RUN_END,
    UNKNOWN_MISSING_CALENDAR,
    UNKNOWN_MISSING_STATE_SEQUENCE,
    build_exit_target_dataset,
    load_source_states,
    parse_horizons,
)
from src.evaluation.exit_target_leakage_audit import audit_exit_target_dataset


INDEX_ID = "STAGE03R-WP4"
BASELINE_VERSION = "age_bucket_baseline_v1"
EMPIRICAL_BASELINE = "empirical_baseline"
ORDINAL_FALLBACK = "ordinal_fallback"
INSUFFICIENT_SAMPLE = "insufficient_sample"
INVALID = "invalid"
OBSERVED_STATUSES = {OBSERVED_POSITIVE, OBSERVED_NEGATIVE}
RIGHT_CENSORED_STATUSES = {RIGHT_CENSORED_BY_RUN_END, RIGHT_CENSORED_BY_CUTOFF}
UNKNOWN_STATUSES = {UNKNOWN_MISSING_CALENDAR, UNKNOWN_MISSING_STATE_SEQUENCE}
GROUP_COLUMNS = (
    "state_source",
    "state_label",
    "state_phase",
    "horizon_days",
    "age_bucket",
    "profile_mode",
    "state_date_policy",
)


@dataclass
class AgeBucketBaselineResult:
    status: str
    baseline_version: str
    source: str
    row_count: int
    observed_row_count: int
    positive_count: int
    negative_count: int
    right_censored_excluded_count: int
    unknown_excluded_count: int
    horizons: list[int]
    group_columns: list[str]
    min_sample_count: int
    baseline_rows: list[dict[str, Any]]
    baseline_status_counts: dict[str, int]
    slice_count: int
    numeric_slice_count: int
    sparse_slice_count: int
    insufficient_sample_count: int
    ordinal_fallback_count: int
    event_rate_min: float | None
    event_rate_max: float | None
    event_rate_mean: float | None
    feature_leakage_violation_count: int
    audit_status: str | None
    audit_hard_violation_count: int
    usable_probability_count: int = 0
    external_data_fetch: str = "no"
    training_algorithm_modified: str = "no"
    DuckDB_committed: str = "no"
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["wp"] = INDEX_ID
        return data


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(value)


def _is_false_like(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=bool)
    if values.dtype == bool:
        return ~values
    normalized = values.fillna(False).astype(str).str.lower()
    return normalized.isin({"false", "0", "0.0", "no", "none", "nan", ""})


def age_bucket(value: Any) -> str:
    try:
        age = int(value)
    except Exception:
        return "unknown"
    if 1 <= age <= 3:
        return "1-3"
    if 4 <= age <= 7:
        return "4-7"
    if 8 <= age <= 14:
        return "8-14"
    if age >= 15:
        return "15+"
    return "unknown"


def ordinal_tendency_from_rate(rate: float | None) -> str:
    if rate is None:
        return "abstain"
    if rate < 1.0 / 3.0:
        return "low"
    if rate < 2.0 / 3.0:
        return "medium"
    return "high"


def valid_observed_mask(dataset: pd.DataFrame) -> pd.Series:
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    labels = pd.to_numeric(dataset.get("exit_within_horizon", pd.Series(index=dataset.index)), errors="coerce")
    weights = pd.to_numeric(dataset.get("sample_weight", pd.Series(0.0, index=dataset.index)), errors="coerce").fillna(0.0)
    leakage = dataset.get("feature_leakage_violation", pd.Series(False, index=dataset.index))
    return status.isin(OBSERVED_STATUSES) & labels.isin([0, 1]) & (weights > 0) & _is_false_like(leakage)


def _prepare_dataset(dataset: pd.DataFrame) -> pd.DataFrame:
    work = dataset.copy()
    for column in ("state_source", "state_label", "state_phase", "profile_mode", "state_date_policy"):
        if column not in work.columns:
            work[column] = "unknown"
        work[column] = work[column].fillna("unknown").astype(str)
    if "horizon_days" not in work.columns:
        work["horizon_days"] = pd.NA
    work["horizon_days"] = pd.to_numeric(work["horizon_days"], errors="coerce").astype("Int64")
    if "state_age" not in work.columns:
        work["state_age"] = pd.NA
    work["age_bucket"] = work["state_age"].map(age_bucket)
    status = work.get("censoring_status", pd.Series("", index=work.index)).fillna("").astype(str)
    labels = pd.to_numeric(work.get("exit_within_horizon", pd.Series(index=work.index)), errors="coerce")
    work["_valid_observed"] = valid_observed_mask(work)
    work["_observed_positive"] = work["_valid_observed"] & labels.eq(1)
    work["_observed_negative"] = work["_valid_observed"] & labels.eq(0)
    work["_right_censored"] = status.isin(RIGHT_CENSORED_STATUSES)
    work["_unknown_target"] = status.isin(UNKNOWN_STATUSES) | status.str.startswith("unknown_")
    return work


def _baseline_rows(work: pd.DataFrame, *, min_sample_count: int) -> list[dict[str, Any]]:
    if work.empty:
        return []
    grouped = (
        work.groupby(list(GROUP_COLUMNS), dropna=False)
        .agg(
            row_count=("_valid_observed", "size"),
            sample_count=("_valid_observed", "sum"),
            positive_count=("_observed_positive", "sum"),
            negative_count=("_observed_negative", "sum"),
            right_censored_excluded_count=("_right_censored", "sum"),
            unknown_excluded_count=("_unknown_target", "sum"),
        )
        .reset_index()
        .sort_values(list(GROUP_COLUMNS))
    )
    rows: list[dict[str, Any]] = []
    for _, row in grouped.iterrows():
        sample_count = int(row["sample_count"])
        positive_count = int(row["positive_count"])
        raw_rate = positive_count / sample_count if sample_count > 0 else None
        if sample_count >= min_sample_count:
            event_rate = raw_rate
            baseline_status = EMPIRICAL_BASELINE
            insufficient = False
            fallback_reason = None
        elif sample_count > 0:
            event_rate = None
            baseline_status = ORDINAL_FALLBACK
            insufficient = True
            fallback_reason = f"sample_count {sample_count} below min_sample_count {min_sample_count}"
        else:
            event_rate = None
            baseline_status = INSUFFICIENT_SAMPLE
            insufficient = True
            fallback_reason = "no valid observed target rows"
        out = {column: (None if pd.isna(row[column]) else row[column]) for column in GROUP_COLUMNS}
        out.update(
            {
                "row_count": int(row["row_count"]),
                "sample_count": sample_count,
                "positive_count": positive_count,
                "negative_count": int(row["negative_count"]),
                "event_rate": event_rate,
                "right_censored_excluded_count": int(row["right_censored_excluded_count"]),
                "unknown_excluded_count": int(row["unknown_excluded_count"]),
                "insufficient_sample": insufficient,
                "baseline_status": baseline_status,
                "exit_tendency_ordinal": ordinal_tendency_from_rate(raw_rate),
                "fallback_reason": fallback_reason,
                "probability_kind": "empirical_baseline" if event_rate is not None else "ordinal_only",
                "baseline_version": BASELINE_VERSION,
            }
        )
        rows.append(out)
    return rows


def evaluate_age_bucket_baseline(
    dataset: pd.DataFrame,
    *,
    source: str = "synthetic",
    min_sample_count: int = 30,
) -> AgeBucketBaselineResult:
    work = _prepare_dataset(dataset)
    audit = audit_exit_target_dataset(work.drop(columns=[c for c in work.columns if c.startswith("_")]), strict=True, source=source)
    hard_count = sum(1 for violation in audit.violations if violation.severity == "hard")
    baseline_rows = [] if hard_count else _baseline_rows(work, min_sample_count=min_sample_count)
    status_counts = (
        pd.Series([row["baseline_status"] for row in baseline_rows]).value_counts().sort_index().to_dict()
        if baseline_rows
        else {}
    )
    observed = work["_valid_observed"] if "_valid_observed" in work.columns else pd.Series(dtype=bool)
    positive_count = int(work["_observed_positive"].sum()) if "_observed_positive" in work.columns else 0
    negative_count = int(work["_observed_negative"].sum()) if "_observed_negative" in work.columns else 0
    right_censored_count = int(work["_right_censored"].sum()) if "_right_censored" in work.columns else 0
    unknown_count = int(work["_unknown_target"].sum()) if "_unknown_target" in work.columns else 0
    event_rates = [float(row["event_rate"]) for row in baseline_rows if row.get("event_rate") is not None]
    numeric_slice_count = int(status_counts.get(EMPIRICAL_BASELINE, 0))
    ordinal_count = int(status_counts.get(ORDINAL_FALLBACK, 0))
    insufficient_count = int(status_counts.get(INSUFFICIENT_SAMPLE, 0))
    if hard_count:
        status = "fail"
    elif numeric_slice_count > 0:
        status = "pass"
    elif len(work) > 0:
        status = "partial"
    else:
        status = "partial"
    horizons = sorted(int(value) for value in work["horizon_days"].dropna().unique().tolist()) if "horizon_days" in work else []
    return AgeBucketBaselineResult(
        status=status,
        baseline_version=BASELINE_VERSION,
        source=source,
        row_count=int(len(work)),
        observed_row_count=int(observed.sum()) if len(work) else 0,
        positive_count=positive_count,
        negative_count=negative_count,
        right_censored_excluded_count=right_censored_count,
        unknown_excluded_count=unknown_count,
        horizons=horizons,
        group_columns=list(GROUP_COLUMNS),
        min_sample_count=int(min_sample_count),
        baseline_rows=baseline_rows,
        baseline_status_counts={str(key): int(value) for key, value in status_counts.items()},
        slice_count=int(len(baseline_rows)),
        numeric_slice_count=numeric_slice_count,
        sparse_slice_count=ordinal_count + insufficient_count,
        insufficient_sample_count=insufficient_count,
        ordinal_fallback_count=ordinal_count,
        event_rate_min=float(min(event_rates)) if event_rates else None,
        event_rate_max=float(max(event_rates)) if event_rates else None,
        event_rate_mean=float(sum(event_rates) / len(event_rates)) if event_rates else None,
        feature_leakage_violation_count=int(audit.feature_leakage_violation_count),
        audit_status=audit.status,
        audit_hard_violation_count=int(hard_count),
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP4 Age-Bucket Empirical Baseline",
        "",
        f"status: {summary.get('status')}",
        f"baseline_version: {summary.get('baseline_version')}",
        f"source: {summary.get('source')}",
        f"row_count: {summary.get('row_count')}",
        f"observed_row_count: {summary.get('observed_row_count')}",
        f"positive_count: {summary.get('positive_count')}",
        f"negative_count: {summary.get('negative_count')}",
        f"right_censored_excluded_count: {summary.get('right_censored_excluded_count')}",
        f"horizons: {summary.get('horizons')}",
        f"min_sample_count: {summary.get('min_sample_count')}",
        f"numeric_slice_count: {summary.get('numeric_slice_count')}",
        f"sparse_slice_count: {summary.get('sparse_slice_count')}",
        f"usable_probability_count: {summary.get('usable_probability_count')}",
        "",
        "## Status Counts",
        "",
        "```json",
        json.dumps(summary.get("baseline_status_counts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Event Rate Summary",
        "",
        f"- event_rate_min: {summary.get('event_rate_min')}",
        f"- event_rate_max: {summary.get('event_rate_max')}",
        f"- event_rate_mean: {summary.get('event_rate_mean')}",
        "",
        "## Sparse Fallback",
        "",
        f"- ordinal_fallback_count: {summary.get('ordinal_fallback_count')}",
        f"- insufficient_sample_count: {summary.get('insufficient_sample_count')}",
        "- sparse slices keep `event_rate` null and expose ordinal-only fallback.",
        "",
        "## Baseline Row Sample",
        "",
        "```json",
        json.dumps(summary.get("baseline_rows", [])[:50], ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        f"- external_data_fetch: {summary.get('external_data_fetch')}",
        f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
        f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
        "- usable_probability: no",
        "- calibrated_probability: no",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: AgeBucketBaselineResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _load_dataset_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=True)


def _missing_db_result(source: str, min_sample_count: int) -> AgeBucketBaselineResult:
    return AgeBucketBaselineResult(
        status="partial",
        baseline_version=BASELINE_VERSION,
        source=source,
        row_count=0,
        observed_row_count=0,
        positive_count=0,
        negative_count=0,
        right_censored_excluded_count=0,
        unknown_excluded_count=0,
        horizons=[],
        group_columns=list(GROUP_COLUMNS),
        min_sample_count=int(min_sample_count),
        baseline_rows=[],
        baseline_status_counts={},
        slice_count=0,
        numeric_slice_count=0,
        sparse_slice_count=0,
        insufficient_sample_count=0,
        ordinal_fallback_count=0,
        event_rate_min=None,
        event_rate_max=None,
        event_rate_mean=None,
        feature_leakage_violation_count=0,
        audit_status="partial",
        audit_hard_violation_count=0,
        warnings=[source],
    )


def _dataset_from_db(args: argparse.Namespace) -> tuple[pd.DataFrame, str]:
    db_path = Path(args.db)
    if not db_path.exists():
        return pd.DataFrame(), "local_db_missing"
    with duckdb.connect(str(db_path), read_only=True) as con:
        from src.evaluation.exit_target_dataset import _resolve_latest_run_id

        run_id = _resolve_latest_run_id(con) if args.run_id == "latest" else args.run_id
        if run_id is None:
            return pd.DataFrame(), "local_db_missing_source"
        states, _, _ = load_source_states(con, run_id)
        dataset_result = build_exit_target_dataset(states, horizons=parse_horizons(args.horizons), run_id=run_id)
        return dataset_result.dataset, "local_db"


def run_cli(args: argparse.Namespace) -> int:
    if args.dataset:
        dataset = _load_dataset_csv(Path(args.dataset))
        result = evaluate_age_bucket_baseline(dataset, source="dataset_csv", min_sample_count=args.min_sample_count)
    elif args.db:
        dataset, source = _dataset_from_db(args)
        if dataset.empty:
            result = _missing_db_result(source, args.min_sample_count)
        else:
            result = evaluate_age_bucket_baseline(dataset, source=source, min_sample_count=args.min_sample_count)
    else:
        raise SystemExit("--dataset or --db is required")
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R WP4 age-bucket empirical baseline")
    parser.add_argument("--dataset", default=None, help="Dataset CSV to evaluate")
    parser.add_argument("--db", default=None, help="Local DuckDB path for rebuild-and-evaluate mode")
    parser.add_argument("--run-id", default="latest", help="Run id for local DB rebuild mode")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizons for local DB rebuild mode")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--min-sample-count", type=int, default=30)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
