"""Stage03R WP2 leakage, censoring, purge, and split-discipline audit.

This module audits target datasets only. It does not fetch market data, train
hazard models, calibrate probabilities, or implement a decision engine.
"""

from __future__ import annotations

import argparse
import bisect
import heapq
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
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
    _empty_dataset,
    build_exit_target_dataset,
    load_source_states,
    parse_horizons,
)


INDEX_ID = "STAGE03R-WP2"
RIGHT_CENSORED_STATUSES = {RIGHT_CENSORED_BY_RUN_END, RIGHT_CENSORED_BY_CUTOFF}
UNKNOWN_STATUSES = {UNKNOWN_MISSING_CALENDAR, UNKNOWN_MISSING_STATE_SEQUENCE}
OBSERVED_STATUSES = {OBSERVED_POSITIVE, OBSERVED_NEGATIVE}
NON_TRAINABLE_LABEL_STATUSES = RIGHT_CENSORED_STATUSES | UNKNOWN_STATUSES
FEATURE_METADATA_COLUMNS = ("max_feature_date_used", "feature_cutoff_date")
REQUIRED_AUDIT_COLUMNS = (
    "sector_code",
    "trade_date",
    "horizon_days",
    "target_observation_end_date",
    "censoring_status",
    "exit_within_horizon",
    "sample_weight",
    "purge_group_id",
    "embargo_until_date",
)


@dataclass(frozen=True)
class Violation:
    check: str
    row_index: int | None
    severity: str
    message: str
    field: str | None = None
    value: Any = None


@dataclass
class Split:
    split_id: str
    validation_start_date: str
    validation_end_date: str
    train_indices: list[int]
    validation_indices: list[int]


@dataclass
class SplitPlan:
    splits: list[Split]
    final_holdout_start: str | None = None
    final_holdout_locked: bool = False
    final_holdout_reuse_allowed: bool = False
    final_holdout_reuse_count: int = 0
    right_censored_training_exclusion_policy: bool = True


@dataclass
class ExitTargetAuditResult:
    status: str
    row_count: int
    feature_leakage_violation_count: int
    censoring_violation_count: int
    purge_embargo_violation_count: int
    split_plan_violation_count: int
    overlapping_window_pair_count: int
    right_censored_training_exclusion_policy: bool
    final_holdout_policy_present: bool
    metadata_missing_count: int
    strict: bool
    source: str
    violations: list[Violation] = field(default_factory=list)
    overlap_examples: list[dict[str, Any]] = field(default_factory=list)
    split_plan: SplitPlan | None = None
    external_data_fetch: str = "no"
    training_algorithm_modified: str = "no"
    DuckDB_committed: str = "no"

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["wp"] = INDEX_ID
        data["violations"] = [asdict(violation) for violation in self.violations[:200]]
        if self.split_plan is not None:
            split_data = asdict(self.split_plan)
            split_data["splits"] = [
                {
                    "split_id": split["split_id"],
                    "validation_start_date": split["validation_start_date"],
                    "validation_end_date": split["validation_end_date"],
                    "train_row_count": len(split["train_indices"]),
                    "validation_row_count": len(split["validation_indices"]),
                }
                for split in split_data["splits"]
            ]
            data["split_plan"] = split_data
        return data


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
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


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(pd.Timestamp(value).date())


def _to_date_series(dataset: pd.DataFrame, column: str) -> pd.Series:
    if column not in dataset.columns:
        return pd.Series(pd.NaT, index=dataset.index)
    return pd.to_datetime(dataset[column], errors="coerce").dt.normalize()


def _is_null(value: Any) -> bool:
    try:
        return bool(pd.isna(value))
    except TypeError:
        return value is None


def _present_string(value: Any) -> bool:
    if _is_null(value):
        return False
    return bool(str(value).strip())


def _exit_value(value: Any) -> int | None:
    if _is_null(value):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def validate_no_feature_leakage(dataset: pd.DataFrame) -> list[Violation]:
    violations: list[Violation] = []
    trade_dates = _to_date_series(dataset, "trade_date")
    for field_name in FEATURE_METADATA_COLUMNS:
        if field_name not in dataset.columns:
            violations.append(
                Violation(
                    check="feature_metadata_present",
                    row_index=None,
                    severity="metadata_missing",
                    field=field_name,
                    message=f"{field_name} column missing",
                )
            )
            continue
        values = _to_date_series(dataset, field_name)
        missing = values.isna()
        for row_index in dataset.index[missing].tolist():
            violations.append(
                Violation(
                    check="feature_metadata_present",
                    row_index=int(row_index),
                    severity="metadata_missing",
                    field=field_name,
                    message=f"{field_name} missing",
                )
            )
        bad = values.notna() & trade_dates.notna() & (values > trade_dates)
        for row_index in dataset.index[bad].tolist():
            violations.append(
                Violation(
                    check="feature_date_lte_trade_date",
                    row_index=int(row_index),
                    severity="hard",
                    field=field_name,
                    value=_date_str(dataset.loc[row_index, field_name]),
                    message=f"{field_name} is after trade_date",
                )
            )
    return violations


def validate_censoring_semantics(dataset: pd.DataFrame) -> list[Violation]:
    violations: list[Violation] = []
    trade_dates = _to_date_series(dataset, "trade_date")
    target_end_dates = _to_date_series(dataset, "target_observation_end_date")
    realized_exit_dates = _to_date_series(dataset, "realized_exit_date")
    horizon_days = pd.to_numeric(dataset.get("horizon_days", pd.Series(index=dataset.index)), errors="coerce")
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    sample_weight = pd.to_numeric(dataset.get("sample_weight", pd.Series(index=dataset.index)), errors="coerce")

    for row_index, row_status in status.items():
        exit_value = _exit_value(dataset.loc[row_index, "exit_within_horizon"]) if "exit_within_horizon" in dataset.columns else None
        if row_status == OBSERVED_POSITIVE and exit_value != 1:
            violations.append(Violation("observed_positive_label", int(row_index), "hard", "observed_positive requires exit_within_horizon=1", "exit_within_horizon", exit_value))
        if row_status == OBSERVED_NEGATIVE and exit_value != 0:
            violations.append(Violation("observed_negative_label", int(row_index), "hard", "observed_negative requires exit_within_horizon=0", "exit_within_horizon", exit_value))
        if row_status in RIGHT_CENSORED_STATUSES and exit_value is not None:
            violations.append(Violation("right_censored_label_null", int(row_index), "hard", "right-censored rows must not carry exit labels", "exit_within_horizon", exit_value))
        if row_status.startswith("unknown_") and exit_value is not None:
            violations.append(Violation("unknown_label_null", int(row_index), "hard", "unknown target rows must not carry exit labels", "exit_within_horizon", exit_value))
        if row_status in RIGHT_CENSORED_STATUSES and sample_weight.get(row_index, 0) > 0:
            violations.append(Violation("right_censored_sample_weight", int(row_index), "hard", "right-censored rows cannot be supervised training labels", "sample_weight", sample_weight.get(row_index)))

    positive_bad = (
        status.eq(OBSERVED_POSITIVE)
        & realized_exit_dates.notna()
        & target_end_dates.notna()
        & (realized_exit_dates > target_end_dates)
    )
    for row_index in dataset.index[positive_bad].tolist():
        violations.append(
            Violation(
                "observed_positive_exit_date",
                int(row_index),
                "hard",
                "observed_positive realized_exit_date exceeds target_observation_end_date",
                "realized_exit_date",
                _date_str(dataset.loc[row_index, "realized_exit_date"]),
            )
        )

    negative_before_trade = status.eq(OBSERVED_NEGATIVE) & target_end_dates.notna() & trade_dates.notna() & (target_end_dates < trade_dates)
    for row_index in dataset.index[negative_before_trade].tolist():
        violations.append(Violation("observed_negative_target_end", int(row_index), "hard", "observed_negative target_observation_end_date is before trade_date", "target_observation_end_date", _date_str(dataset.loc[row_index, "target_observation_end_date"])))

    expected_min_end = trade_dates + pd.to_timedelta(horizon_days.fillna(0), unit="D")
    not_fully_observable = (
        status.eq(OBSERVED_NEGATIVE)
        & horizon_days.notna()
        & target_end_dates.notna()
        & trade_dates.notna()
        & (target_end_dates < expected_min_end)
    )
    for row_index in dataset.index[not_fully_observable].tolist():
        violations.append(
            Violation(
                "observed_negative_full_horizon",
                int(row_index),
                "hard",
                "observed_negative target horizon is not fully observable",
                "target_observation_end_date",
                _date_str(dataset.loc[row_index, "target_observation_end_date"]),
            )
        )
    return violations


def validate_purge_embargo_metadata(dataset: pd.DataFrame) -> list[Violation]:
    violations: list[Violation] = []
    observed = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str).isin(OBSERVED_STATUSES)
    target_end_dates = _to_date_series(dataset, "target_observation_end_date")
    embargo_until_dates = _to_date_series(dataset, "embargo_until_date")

    if "purge_group_id" not in dataset.columns:
        return [
            Violation(
                check="purge_group_id_present",
                row_index=None,
                severity="hard",
                field="purge_group_id",
                message="purge_group_id column missing",
            )
        ]

    missing_purge = ~dataset["purge_group_id"].apply(_present_string)
    for row_index in dataset.index[missing_purge].tolist():
        violations.append(Violation("purge_group_id_present", int(row_index), "hard", "purge_group_id missing", "purge_group_id"))

    missing_observed_embargo = observed & embargo_until_dates.isna()
    for row_index in dataset.index[missing_observed_embargo].tolist():
        violations.append(Violation("observed_embargo_present", int(row_index), "hard", "observed rows require embargo_until_date", "embargo_until_date"))

    embargo_before_target = embargo_until_dates.notna() & target_end_dates.notna() & (embargo_until_dates < target_end_dates)
    for row_index in dataset.index[embargo_before_target].tolist():
        violations.append(
            Violation(
                "embargo_covers_target_window",
                int(row_index),
                "hard",
                "embargo_until_date is before target_observation_end_date",
                "embargo_until_date",
                _date_str(dataset.loc[row_index, "embargo_until_date"]),
            )
        )
    return violations


def _prepared_windows(dataset: pd.DataFrame) -> pd.DataFrame:
    work = dataset.copy()
    work["_row_index"] = work.index.astype(int)
    work["_start"] = _to_date_series(work, "trade_date")
    work["_end"] = _to_date_series(work, "target_observation_end_date")
    work["_sector"] = work.get("sector_code", pd.Series("", index=work.index)).fillna("").astype(str)
    return work[work["_sector"].ne("") & work["_start"].notna() & work["_end"].notna()].copy()


def detect_overlapping_target_windows(dataset: pd.DataFrame, *, max_examples: int = 50) -> pd.DataFrame:
    windows = _prepared_windows(dataset)
    examples: list[dict[str, Any]] = []
    for sector, group in windows.sort_values(["_sector", "_start", "_end"]).groupby("_sector", sort=False):
        active: list[tuple[pd.Timestamp, int, pd.Timestamp]] = []
        for _, row in group.iterrows():
            start = pd.Timestamp(row["_start"])
            end = pd.Timestamp(row["_end"])
            while active and active[0][0] < start:
                heapq.heappop(active)
            for active_end, active_index, active_start in active[: max(0, max_examples - len(examples))]:
                examples.append(
                    {
                        "sector_code": sector,
                        "left_row_index": int(active_index),
                        "right_row_index": int(row["_row_index"]),
                        "left_start": _date_str(active_start),
                        "left_end": _date_str(active_end),
                        "right_start": _date_str(start),
                        "right_end": _date_str(end),
                    }
                )
                if len(examples) >= max_examples:
                    break
            heapq.heappush(active, (end, int(row["_row_index"]), start))
    return pd.DataFrame(examples)


def count_overlapping_target_windows(dataset: pd.DataFrame) -> int:
    windows = _prepared_windows(dataset)
    count = 0
    for _, group in windows.sort_values(["_sector", "_start", "_end"]).groupby("_sector", sort=False):
        active: list[pd.Timestamp] = []
        for _, row in group.iterrows():
            start = pd.Timestamp(row["_start"])
            end = pd.Timestamp(row["_end"])
            while active and active[0] < start:
                heapq.heappop(active)
            count += len(active)
            heapq.heappush(active, end)
    return int(count)


def _row_windows_overlap(row_a: pd.Series, row_b: pd.Series) -> bool:
    if str(row_a.get("sector_code", "")) != str(row_b.get("sector_code", "")):
        return False
    a_start = pd.to_datetime(row_a.get("trade_date"), errors="coerce")
    a_end = pd.to_datetime(row_a.get("target_observation_end_date"), errors="coerce")
    b_start = pd.to_datetime(row_b.get("trade_date"), errors="coerce")
    b_end = pd.to_datetime(row_b.get("target_observation_end_date"), errors="coerce")
    if pd.isna(a_start) or pd.isna(a_end) or pd.isna(b_start) or pd.isna(b_end):
        return False
    return bool(a_start <= b_end and b_start <= a_end)


def _overlapping_candidate_indices(candidates: pd.DataFrame, validation_rows: pd.DataFrame) -> set[int]:
    if candidates.empty or validation_rows.empty:
        return set()
    out: set[int] = set()
    for sector, candidate_group in candidates.groupby("sector_code", sort=False):
        sector_validation = validation_rows[validation_rows["sector_code"].astype(str).eq(str(sector))].copy()
        sector_validation = sector_validation.dropna(subset=["_trade_date", "_target_end"])
        if sector_validation.empty:
            continue
        sector_validation = sector_validation.sort_values("_trade_date")
        val_starts = [pd.Timestamp(value) for value in sector_validation["_trade_date"].tolist()]
        val_ends = [pd.Timestamp(value) for value in sector_validation["_target_end"].tolist()]
        cumulative_max_end: list[pd.Timestamp] = []
        current_max: pd.Timestamp | None = None
        for end in val_ends:
            current_max = end if current_max is None or end > current_max else current_max
            cumulative_max_end.append(current_max)
        for row_index, candidate in candidate_group.iterrows():
            start = candidate.get("_trade_date")
            end = candidate.get("_target_end")
            if pd.isna(start) or pd.isna(end):
                continue
            pos = bisect.bisect_right(val_starts, pd.Timestamp(end)) - 1
            if pos >= 0 and cumulative_max_end[pos] >= pd.Timestamp(start):
                out.add(int(row_index))
    return out


def _observed_label_mask(dataset: pd.DataFrame) -> pd.Series:
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    return status.isin(OBSERVED_STATUSES)


def build_purged_time_split_plan(
    dataset: pd.DataFrame,
    *,
    n_splits: int = 3,
    final_holdout_start: str | None = None,
) -> SplitPlan:
    if dataset.empty:
        return SplitPlan(splits=[], final_holdout_start=final_holdout_start, final_holdout_locked=bool(final_holdout_start), final_holdout_reuse_allowed=False, final_holdout_reuse_count=1 if final_holdout_start else 0)

    work = dataset.copy()
    work["_trade_date"] = _to_date_series(work, "trade_date")
    work["_target_end"] = _to_date_series(work, "target_observation_end_date")
    work["_embargo"] = _to_date_series(work, "embargo_until_date")
    final_start = pd.to_datetime(final_holdout_start, errors="coerce") if final_holdout_start else pd.NaT
    non_holdout = work if pd.isna(final_start) else work[work["_trade_date"] < final_start]
    unique_dates = sorted(non_holdout["_trade_date"].dropna().unique().tolist())
    if len(unique_dates) < 2:
        return SplitPlan(splits=[], final_holdout_start=_date_str(final_start), final_holdout_locked=bool(final_holdout_start), final_holdout_reuse_allowed=False, final_holdout_reuse_count=1 if final_holdout_start else 0)

    split_count = min(n_splits + 1, len(unique_dates))
    boundary_size = max(1, len(unique_dates) // split_count)
    split_boundaries: list[pd.Series] = []
    start = 0
    for split_idx in range(split_count):
        if split_idx == split_count - 1:
            end = len(unique_dates)
        else:
            end = min(len(unique_dates), start + boundary_size)
        split_boundaries.append(pd.Series(unique_dates[start:end]))
        start = end
    splits: list[Split] = []
    observed_mask = _observed_label_mask(work)
    for split_no, validation_dates in enumerate(split_boundaries[1:], start=1):
        if len(validation_dates) == 0:
            continue
        validation_start = pd.Timestamp(validation_dates.iloc[0])
        validation_end = pd.Timestamp(validation_dates.iloc[-1])
        validation_mask = work["_trade_date"].between(validation_start, validation_end, inclusive="both")
        train_mask = (work["_trade_date"] < validation_start) & observed_mask
        train_mask &= ~(work.get("censoring_status", "").isin(NON_TRAINABLE_LABEL_STATUSES))
        train_mask &= work["_embargo"].isna() | (work["_embargo"] < validation_start)

        validation_rows = work[validation_mask]
        train_candidates = work[train_mask]
        overlapping_train = _overlapping_candidate_indices(train_candidates, validation_rows)
        train_indices = [int(index) for index in train_candidates.index.tolist() if int(index) not in overlapping_train]
        splits.append(
            Split(
                split_id=f"split_{split_no}",
                validation_start_date=_date_str(validation_start) or "",
                validation_end_date=_date_str(validation_end) or "",
                train_indices=train_indices,
                validation_indices=[int(index) for index in validation_rows.index.tolist()],
            )
        )
    return SplitPlan(
        splits=splits,
        final_holdout_start=_date_str(final_start),
        final_holdout_locked=bool(final_holdout_start),
        final_holdout_reuse_allowed=False,
        final_holdout_reuse_count=1 if final_holdout_start else 0,
        right_censored_training_exclusion_policy=True,
    )


def validate_split_plan(dataset: pd.DataFrame, split_plan: SplitPlan) -> list[Violation]:
    violations: list[Violation] = []
    if split_plan.final_holdout_start and not split_plan.final_holdout_locked:
        violations.append(Violation("final_holdout_locked", None, "hard", "final holdout must be locked"))
    if split_plan.final_holdout_reuse_allowed or split_plan.final_holdout_reuse_count > 1:
        violations.append(Violation("final_holdout_not_reused", None, "hard", "final holdout cannot be reused for repeated tuning"))
    if not split_plan.right_censored_training_exclusion_policy:
        violations.append(Violation("right_censored_training_exclusion_policy", None, "hard", "right-censored rows must be excluded from supervised training labels"))

    work = dataset.copy()
    work["_trade_date"] = _to_date_series(work, "trade_date")
    work["_target_end"] = _to_date_series(work, "target_observation_end_date")
    work["_embargo"] = _to_date_series(work, "embargo_until_date")
    status = work.get("censoring_status", pd.Series("", index=work.index)).fillna("").astype(str)
    for split in split_plan.splits:
        train_set = set(split.train_indices)
        validation_set = set(split.validation_indices)
        overlap = train_set & validation_set
        for row_index in sorted(overlap):
            violations.append(Violation("train_validation_disjoint", int(row_index), "hard", "row appears in both train and validation"))

        validation_start = pd.to_datetime(split.validation_start_date, errors="coerce")
        train_rows = work.loc[[index for index in split.train_indices if index in work.index]]
        validation_rows = work.loc[[index for index in split.validation_indices if index in work.index]]
        overlapping_train = _overlapping_candidate_indices(train_rows, validation_rows)
        for row_index in split.train_indices:
            if row_index not in work.index:
                continue
            if status.loc[row_index] in NON_TRAINABLE_LABEL_STATUSES:
                violations.append(Violation("right_censored_not_trainable", int(row_index), "hard", "right-censored or unknown rows cannot enter supervised training"))
            embargo = work.loc[row_index, "_embargo"]
            if pd.notna(embargo) and pd.notna(validation_start) and embargo >= validation_start:
                violations.append(Violation("embargo_train_exclusion", int(row_index), "hard", "train row embargo reaches validation start"))
            if int(row_index) in overlapping_train:
                violations.append(Violation("purge_overlap_train_validation", int(row_index), "hard", "train target window overlaps validation target window"))
    return violations


def audit_exit_target_dataset(
    dataset: pd.DataFrame,
    *,
    strict: bool = True,
    source: str = "synthetic",
    split_plan: SplitPlan | None = None,
) -> ExitTargetAuditResult:
    work = dataset.copy()
    for column in REQUIRED_AUDIT_COLUMNS:
        if column not in work.columns:
            work[column] = pd.NA

    feature_violations = validate_no_feature_leakage(work)
    censoring_violations = validate_censoring_semantics(work)
    purge_violations = validate_purge_embargo_metadata(work)
    overlap_count = count_overlapping_target_windows(work)
    overlap_examples = detect_overlapping_target_windows(work).to_dict("records")
    split_plan = split_plan or build_purged_time_split_plan(work, n_splits=3, final_holdout_start=None)
    split_violations = validate_split_plan(work, split_plan)
    violations = [*feature_violations, *censoring_violations, *purge_violations, *split_violations]
    hard_count = sum(1 for violation in violations if violation.severity == "hard")
    metadata_missing_count = sum(1 for violation in violations if violation.severity == "metadata_missing")
    if work.empty:
        status = "partial"
    elif hard_count:
        status = "fail"
    elif strict and metadata_missing_count:
        status = "partial"
    else:
        status = "pass"
    return ExitTargetAuditResult(
        status=status,
        row_count=int(len(work)),
        feature_leakage_violation_count=sum(1 for violation in feature_violations if violation.severity == "hard"),
        censoring_violation_count=sum(1 for violation in censoring_violations if violation.severity == "hard"),
        purge_embargo_violation_count=sum(1 for violation in purge_violations if violation.severity == "hard"),
        split_plan_violation_count=sum(1 for violation in split_violations if violation.severity == "hard"),
        overlapping_window_pair_count=overlap_count,
        right_censored_training_exclusion_policy=split_plan.right_censored_training_exclusion_policy,
        final_holdout_policy_present=bool(
            not split_plan.final_holdout_reuse_allowed
            and (not split_plan.final_holdout_start or split_plan.final_holdout_locked)
        ),
        metadata_missing_count=metadata_missing_count,
        strict=bool(strict),
        source=source,
        violations=violations,
        overlap_examples=overlap_examples,
        split_plan=split_plan,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP2 Target Leakage / Purge Audit",
        "",
        f"status: {summary.get('status')}",
        f"row_count: {summary.get('row_count')}",
        f"strict: {str(summary.get('strict')).lower()}",
        f"source: {summary.get('source')}",
        "",
        "## Audit Counts",
        "",
        f"- feature_leakage_violation_count: {summary.get('feature_leakage_violation_count')}",
        f"- censoring_violation_count: {summary.get('censoring_violation_count')}",
        f"- purge_embargo_violation_count: {summary.get('purge_embargo_violation_count')}",
        f"- split_plan_violation_count: {summary.get('split_plan_violation_count')}",
        f"- overlapping_window_pair_count: {summary.get('overlapping_window_pair_count')}",
        f"- metadata_missing_count: {summary.get('metadata_missing_count')}",
        f"- right_censored_training_exclusion_policy: {str(summary.get('right_censored_training_exclusion_policy')).lower()}",
        f"- final_holdout_policy_present: {str(summary.get('final_holdout_policy_present')).lower()}",
        "",
        "## Policy",
        "",
        "- Right-censored and unknown rows are excluded from supervised training labels by default.",
        "- Overlapping target windows are allowed in the dataset but must be purged across train/validation splits.",
        "- Training rows are embargoed through `embargo_until_date` and must be excluded when the embargo reaches validation start.",
        "- Final holdout may be defined once and must be locked before model tuning.",
        "",
        "## Violation Sample",
        "",
        "```json",
        json.dumps(summary.get("violations", [])[:50], ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        f"- external_data_fetch: {summary.get('external_data_fetch')}",
        f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
        f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
    ]
    return "\n".join(lines) + "\n"


def write_audit_outputs(result: ExitTargetAuditResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _load_dataset_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=True)


def _audit_from_db(args: argparse.Namespace) -> ExitTargetAuditResult:
    db_path = Path(args.db)
    if not db_path.exists():
        return audit_exit_target_dataset(_empty_dataset(), strict=args.strict, source="local_db_missing")
    with duckdb.connect(str(db_path), read_only=True) as con:
        from src.evaluation.exit_target_dataset import _resolve_latest_run_id

        run_id = _resolve_latest_run_id(con) if args.run_id == "latest" else args.run_id
        if run_id is None:
            return audit_exit_target_dataset(_empty_dataset(), strict=args.strict, source="local_db_missing_source")
        states, _, _ = load_source_states(con, run_id)
        dataset_result = build_exit_target_dataset(states, horizons=parse_horizons(args.horizons), run_id=run_id)
        return audit_exit_target_dataset(dataset_result.dataset, strict=args.strict, source="local_db")


def run_cli(args: argparse.Namespace) -> int:
    if args.dataset:
        dataset = _load_dataset_csv(Path(args.dataset))
        result = audit_exit_target_dataset(dataset, strict=args.strict, source="dataset_csv")
    elif args.db:
        result = _audit_from_db(args)
    else:
        raise SystemExit("--dataset or --db is required")
    write_audit_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit Stage03R exit_target_dataset_v1 leakage and purge contracts")
    parser.add_argument("--dataset", default=None, help="Dataset CSV to audit")
    parser.add_argument("--db", default=None, help="Local DuckDB path for rebuild-and-audit mode")
    parser.add_argument("--run-id", default="latest", help="Run id for local DB rebuild mode")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizons for local DB rebuild mode")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--strict", action="store_true", default=False)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
