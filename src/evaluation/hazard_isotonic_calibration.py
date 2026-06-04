"""Stage03R WP5 isotonic calibration diagnostics for Duration Hazard.

This module calibrates raw WP3 hazard predictions on validation rows only. It
does not train HMM/HSMM models, use HSMM numeric p_exit, create readiness
matrices, or emit usable probabilities.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.age_bucket_baseline import (
    EMPIRICAL_BASELINE,
    GROUP_COLUMNS as AGE_BUCKET_GROUP_COLUMNS,
    age_bucket,
    evaluate_age_bucket_baseline,
    write_outputs as write_age_bucket_outputs,
)
from src.models.duration_hazard import (
    RAW_PROBABILITY_ONLY,
    fit_duration_hazard_baseline,
    write_hazard_outputs,
)


INDEX_ID = "STAGE03R-WP5"
CALIBRATION_VERSION = "hazard_isotonic_calibration_v1"
CALIBRATION_CANDIDATE = "calibration_candidate"
ORDINAL_ONLY = "ordinal_only"
INSUFFICIENT_SAMPLE = "insufficient_sample"
INVALID = "invalid"
DEGRADED_BRIER_WORSE = "degraded_brier_worse"
EXCLUDED_FINAL_HOLDOUT = "excluded_final_holdout"
EXCLUDED_NON_VALIDATION = "excluded_non_validation"
OBSERVED_STATUSES = {"observed_positive", "observed_negative"}
FINAL_HOLDOUT_MARKERS = ("final", "holdout")
SLICE_COLUMNS = ("horizon_days", "state_label", "state_phase", "age_bucket")


@dataclass
class IsotonicModel:
    thresholds: list[float]
    values: list[float]

    def predict(self, raw_probability: Sequence[float] | np.ndarray) -> np.ndarray:
        values = np.asarray(raw_probability, dtype=float)
        thresholds = np.asarray(self.thresholds, dtype=float)
        fitted = np.asarray(self.values, dtype=float)
        if len(thresholds) == 0:
            return np.full(len(values), np.nan, dtype=float)
        positions = np.searchsorted(thresholds, values, side="left")
        positions = np.clip(positions, 0, len(fitted) - 1)
        return fitted[positions]


@dataclass
class CalibrationMetric:
    horizon_days: int | None
    sample_count: int
    positive_count: int
    negative_count: int
    raw_brier: float | None
    calibrated_brier: float | None
    raw_ece: float | None
    calibrated_ece: float | None
    calibration_status: str
    fallback_reason: str | None
    fold_count: int
    raw_probability_min: float | None
    raw_probability_max: float | None
    calibrated_probability_min: float | None
    calibrated_probability_max: float | None


@dataclass
class SliceMetric:
    horizon_days: int | None
    state_label: str
    state_phase: str
    age_bucket: str
    sample_count: int
    positive_count: int
    negative_count: int
    raw_brier: float | None
    calibrated_brier: float | None
    age_bucket_baseline_brier: float | None
    calibration_status: str
    fallback_reason: str | None
    age_bucket_baseline_sample_count: int | None
    age_bucket_baseline_event_rate: float | None


@dataclass
class HazardIsotonicCalibrationResult:
    status: str
    calibration_version: str
    source: str
    hazard_prediction_row_count: int
    calibration_sample_count: int
    positive_count: int
    negative_count: int
    horizons: list[int]
    min_sample_count: int
    min_slice_sample_count: int
    validation_only: bool
    final_holdout_tuning: bool
    final_holdout_excluded_count: int
    non_validation_excluded_count: int
    invalid_prediction_count: int
    raw_brier_mean: float | None
    calibrated_brier_mean: float | None
    brier_delta_mean: float | None
    raw_ece_mean: float | None
    calibrated_ece_mean: float | None
    age_bucket_baseline_brier_mean: float | None
    age_bucket_baseline_joined_row_count: int
    age_bucket_baseline_key_columns: list[str]
    horizon_metrics: list[dict[str, Any]]
    slice_metrics: list[dict[str, Any]]
    calibration_status_counts: dict[str, int]
    usable_probability_count: int = 0
    calibrated_probability_count: int = 0
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


def _mean(values: Sequence[float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(np.mean(numeric)) if numeric else None


def _brier(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    return float(np.mean((probabilities - y_true) ** 2))


def _ece(y_true: np.ndarray, probabilities: np.ndarray, *, n_bins: int = 10) -> float:
    if len(y_true) == 0:
        return float("nan")
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for idx in range(n_bins):
        lower = bins[idx]
        upper = bins[idx + 1]
        if idx == n_bins - 1:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        if not mask.any():
            continue
        total += float(mask.mean()) * abs(float(y_true[mask].mean()) - float(probabilities[mask].mean()))
    return float(total)


def fit_isotonic_pava(
    raw_probability: Sequence[float] | np.ndarray,
    labels: Sequence[int] | np.ndarray,
    sample_weight: Sequence[float] | np.ndarray | None = None,
) -> IsotonicModel:
    x = np.asarray(raw_probability, dtype=float)
    y = np.asarray(labels, dtype=float)
    weights = np.ones(len(y), dtype=float) if sample_weight is None else np.asarray(sample_weight, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y) & np.isfinite(weights) & (weights > 0)
    x = x[valid]
    y = y[valid]
    weights = weights[valid]
    if len(x) == 0:
        return IsotonicModel(thresholds=[], values=[])

    order = np.argsort(x, kind="mergesort")
    x = x[order]
    y = y[order]
    weights = weights[order]
    blocks: list[dict[str, float]] = []
    for xi, yi, wi in zip(x, y, weights, strict=True):
        blocks.append({"x_max": float(xi), "weight": float(wi), "weighted_y": float(wi * yi)})
        while len(blocks) >= 2:
            previous = blocks[-2]
            current = blocks[-1]
            prev_value = previous["weighted_y"] / previous["weight"]
            current_value = current["weighted_y"] / current["weight"]
            if prev_value <= current_value:
                break
            previous["x_max"] = current["x_max"]
            previous["weight"] += current["weight"]
            previous["weighted_y"] += current["weighted_y"]
            blocks.pop()

    thresholds = [block["x_max"] for block in blocks]
    values = [min(1.0, max(0.0, block["weighted_y"] / block["weight"])) for block in blocks]
    return IsotonicModel(thresholds=thresholds, values=values)


def calibration_status_for_metrics(
    *,
    sample_count: int,
    positive_count: int,
    negative_count: int,
    raw_brier: float | None,
    calibrated_brier: float | None,
    min_sample_count: int,
    brier_worsening_tolerance: float = 1e-12,
) -> tuple[str, str | None]:
    if sample_count <= 0:
        return INSUFFICIENT_SAMPLE, "no validation rows"
    if sample_count < min_sample_count:
        return ORDINAL_ONLY, f"sample_count {sample_count} below min_sample_count {min_sample_count}"
    if positive_count == 0 or negative_count == 0:
        return ORDINAL_ONLY, "validation labels lack both classes"
    if raw_brier is None or calibrated_brier is None:
        return INVALID, "calibration metric unavailable"
    if calibrated_brier > raw_brier + brier_worsening_tolerance:
        return DEGRADED_BRIER_WORSE, "calibrated Brier worse than raw Brier"
    return CALIBRATION_CANDIDATE, None


def _normalized_split_role(values: pd.Series) -> pd.Series:
    return values.fillna("").astype(str).str.lower()


def _prepare_predictions(predictions: pd.DataFrame) -> pd.DataFrame:
    work = predictions.copy()
    for column in ("state_label", "state_phase", "fold_id", "split_role", "hazard_status", "censoring_status"):
        if column not in work.columns:
            work[column] = ""
        work[column] = work[column].fillna("").astype(str)
    if "horizon_days" not in work.columns:
        work["horizon_days"] = pd.NA
    if "state_age" not in work.columns:
        work["state_age"] = pd.NA
    work["horizon_days"] = pd.to_numeric(work["horizon_days"], errors="coerce").astype("Int64")
    work["age_bucket"] = work["state_age"].map(age_bucket)
    work["exit_within_horizon"] = pd.to_numeric(
        work.get("exit_within_horizon", pd.Series(index=work.index)),
        errors="coerce",
    )
    work["hazard_raw_probability"] = pd.to_numeric(
        work.get("hazard_raw_probability", pd.Series(index=work.index)),
        errors="coerce",
    )
    work["_split_role_normalized"] = _normalized_split_role(work["split_role"])
    work["_is_validation"] = work["_split_role_normalized"].eq("validation")
    work["_is_final_holdout"] = work["_split_role_normalized"].apply(
        lambda value: any(marker in value for marker in FINAL_HOLDOUT_MARKERS)
    )
    work["_raw_status_ok"] = work["hazard_status"].eq(RAW_PROBABILITY_ONLY)
    work["_label_ok"] = work["exit_within_horizon"].isin([0, 1])
    work["_probability_ok"] = work["hazard_raw_probability"].between(0.0, 1.0, inclusive="both")
    work["_observed_status_ok"] = work["censoring_status"].isin(OBSERVED_STATUSES) | work["censoring_status"].eq("")
    work["_calibration_eligible"] = (
        work["_is_validation"]
        & ~work["_is_final_holdout"]
        & work["_raw_status_ok"]
        & work["_label_ok"]
        & work["_probability_ok"]
        & work["_observed_status_ok"]
    )
    return work


def _baseline_frame(age_bucket_baseline: Mapping[str, Any] | None) -> pd.DataFrame:
    if not age_bucket_baseline:
        return pd.DataFrame()
    rows = age_bucket_baseline.get("baseline_rows", [])
    if not rows:
        return pd.DataFrame()
    baseline = pd.DataFrame(rows)
    if baseline.empty:
        return baseline
    baseline["event_rate"] = pd.to_numeric(baseline.get("event_rate"), errors="coerce")
    baseline["sample_count"] = pd.to_numeric(baseline.get("sample_count"), errors="coerce").fillna(0).astype(int)
    if "horizon_days" in baseline.columns:
        baseline["horizon_days"] = pd.to_numeric(baseline["horizon_days"], errors="coerce").astype("Int64")
    return baseline


def _attach_age_bucket_baseline(
    eligible: pd.DataFrame,
    age_bucket_baseline: Mapping[str, Any] | None,
) -> tuple[pd.DataFrame, list[str]]:
    work = eligible.copy()
    work["_age_bucket_event_rate"] = np.nan
    work["_age_bucket_sample_count"] = pd.NA
    baseline = _baseline_frame(age_bucket_baseline)
    if baseline.empty or work.empty:
        return work, []
    baseline = baseline[
        baseline.get("baseline_status", pd.Series("", index=baseline.index)).eq(EMPIRICAL_BASELINE)
        & baseline["event_rate"].notna()
    ].copy()
    if baseline.empty:
        return work, []
    key_columns = [
        column
        for column in AGE_BUCKET_GROUP_COLUMNS
        if column in work.columns and column in baseline.columns and column in {"state_label", "state_phase", "horizon_days", "age_bucket", "state_source", "profile_mode", "state_date_policy"}
    ]
    if not key_columns:
        return work, []
    grouped = (
        baseline.groupby(key_columns, dropna=False)
        .apply(
            lambda rows: pd.Series(
                {
                    "_age_bucket_event_rate": float(
                        np.average(rows["event_rate"].astype(float), weights=rows["sample_count"].clip(lower=1))
                    ),
                    "_age_bucket_sample_count": int(rows["sample_count"].sum()),
                }
            )
        )
        .reset_index()
    )
    work = work.merge(grouped, how="left", on=key_columns, suffixes=("", "_joined"))
    if "_age_bucket_event_rate_joined" in work.columns:
        work["_age_bucket_event_rate"] = work["_age_bucket_event_rate_joined"]
        work["_age_bucket_sample_count"] = work["_age_bucket_sample_count_joined"]
        work = work.drop(columns=["_age_bucket_event_rate_joined", "_age_bucket_sample_count_joined"])
    return work, key_columns


def _horizon_metric(
    horizon: int,
    rows: pd.DataFrame,
    *,
    min_sample_count: int,
    brier_worsening_tolerance: float,
) -> tuple[CalibrationMetric, np.ndarray | None]:
    y_true = rows["exit_within_horizon"].astype(int).to_numpy()
    raw = rows["hazard_raw_probability"].astype(float).to_numpy()
    sample_count = int(len(rows))
    positive_count = int(y_true.sum())
    negative_count = int(sample_count - positive_count)
    fold_count = int(rows["fold_id"].nunique())
    raw_brier = _brier(y_true, raw) if sample_count else None
    raw_ece = _ece(y_true, raw) if sample_count else None
    calibrated: np.ndarray | None = None
    calibrated_brier = None
    calibrated_ece = None
    calibrated_min = None
    calibrated_max = None
    if sample_count >= min_sample_count and positive_count > 0 and negative_count > 0:
        model = fit_isotonic_pava(raw, y_true)
        calibrated = model.predict(raw)
        calibrated_brier = _brier(y_true, calibrated)
        calibrated_ece = _ece(y_true, calibrated)
        calibrated_min = float(np.min(calibrated))
        calibrated_max = float(np.max(calibrated))
    status, reason = calibration_status_for_metrics(
        sample_count=sample_count,
        positive_count=positive_count,
        negative_count=negative_count,
        raw_brier=raw_brier,
        calibrated_brier=calibrated_brier,
        min_sample_count=min_sample_count,
        brier_worsening_tolerance=brier_worsening_tolerance,
    )
    if status != CALIBRATION_CANDIDATE:
        calibrated = None
        calibrated_brier = None if status in {ORDINAL_ONLY, INSUFFICIENT_SAMPLE} else calibrated_brier
        calibrated_ece = None if status in {ORDINAL_ONLY, INSUFFICIENT_SAMPLE} else calibrated_ece
        calibrated_min = None
        calibrated_max = None
    metric = CalibrationMetric(
        horizon_days=int(horizon),
        sample_count=sample_count,
        positive_count=positive_count,
        negative_count=negative_count,
        raw_brier=raw_brier,
        calibrated_brier=calibrated_brier,
        raw_ece=raw_ece,
        calibrated_ece=calibrated_ece,
        calibration_status=status,
        fallback_reason=reason,
        fold_count=fold_count,
        raw_probability_min=float(np.min(raw)) if sample_count else None,
        raw_probability_max=float(np.max(raw)) if sample_count else None,
        calibrated_probability_min=calibrated_min,
        calibrated_probability_max=calibrated_max,
    )
    return metric, calibrated


def _slice_metrics(
    eligible: pd.DataFrame,
    *,
    min_slice_sample_count: int,
) -> list[SliceMetric]:
    if eligible.empty:
        return []
    records: list[SliceMetric] = []
    grouped = eligible.groupby(list(SLICE_COLUMNS), dropna=False)
    for keys, rows in grouped:
        horizon, label, phase, bucket = keys
        y_true = rows["exit_within_horizon"].astype(int).to_numpy()
        raw = rows["hazard_raw_probability"].astype(float).to_numpy()
        calibrated = pd.to_numeric(rows.get("_calibrated_probability"), errors="coerce").to_numpy()
        baseline = pd.to_numeric(rows.get("_age_bucket_event_rate"), errors="coerce").to_numpy()
        sample_count = int(len(rows))
        positive_count = int(y_true.sum())
        negative_count = int(sample_count - positive_count)
        raw_brier = _brier(y_true, raw) if sample_count else None
        calibrated_brier = _brier(y_true, calibrated) if np.isfinite(calibrated).all() and sample_count else None
        baseline_brier = _brier(y_true, baseline) if np.isfinite(baseline).all() and sample_count else None
        status, reason = calibration_status_for_metrics(
            sample_count=sample_count,
            positive_count=positive_count,
            negative_count=negative_count,
            raw_brier=raw_brier,
            calibrated_brier=calibrated_brier,
            min_sample_count=min_slice_sample_count,
        )
        baseline_sample_count = pd.to_numeric(rows.get("_age_bucket_sample_count"), errors="coerce")
        baseline_rate = pd.to_numeric(rows.get("_age_bucket_event_rate"), errors="coerce")
        records.append(
            SliceMetric(
                horizon_days=None if pd.isna(horizon) else int(horizon),
                state_label=str(label),
                state_phase=str(phase),
                age_bucket=str(bucket),
                sample_count=sample_count,
                positive_count=positive_count,
                negative_count=negative_count,
                raw_brier=raw_brier,
                calibrated_brier=calibrated_brier if status == CALIBRATION_CANDIDATE else None,
                age_bucket_baseline_brier=baseline_brier,
                calibration_status=status,
                fallback_reason=reason,
                age_bucket_baseline_sample_count=int(baseline_sample_count.dropna().iloc[0]) if baseline_sample_count.notna().any() else None,
                age_bucket_baseline_event_rate=float(baseline_rate.dropna().iloc[0]) if baseline_rate.notna().any() else None,
            )
        )
    return records


def evaluate_hazard_isotonic_calibration(
    hazard_predictions: pd.DataFrame,
    *,
    age_bucket_baseline: Mapping[str, Any] | None = None,
    source: str = "hazard_predictions_csv",
    min_sample_count: int = 30,
    min_slice_sample_count: int | None = None,
    brier_worsening_tolerance: float = 1e-12,
) -> HazardIsotonicCalibrationResult:
    work = _prepare_predictions(hazard_predictions)
    final_holdout_count = int(work["_is_final_holdout"].sum())
    non_validation_count = int((~work["_is_validation"] & ~work["_is_final_holdout"]).sum())
    eligible = work.loc[work["_calibration_eligible"]].copy()
    invalid_count = int(len(work) - final_holdout_count - non_validation_count - len(eligible))
    min_slice = int(min_slice_sample_count if min_slice_sample_count is not None else min_sample_count)
    eligible, baseline_keys = _attach_age_bucket_baseline(eligible, age_bucket_baseline)
    eligible["_calibrated_probability"] = np.nan

    horizon_metrics: list[CalibrationMetric] = []
    for horizon, rows in eligible.groupby("horizon_days", dropna=False):
        if pd.isna(horizon):
            continue
        metric, calibrated = _horizon_metric(
            int(horizon),
            rows,
            min_sample_count=min_sample_count,
            brier_worsening_tolerance=brier_worsening_tolerance,
        )
        horizon_metrics.append(metric)
        if calibrated is not None:
            eligible.loc[rows.index, "_calibrated_probability"] = calibrated

    slice_metrics = _slice_metrics(eligible, min_slice_sample_count=min_slice)
    if slice_metrics:
        status_counts = (
            pd.Series([metric.calibration_status for metric in slice_metrics]).value_counts().sort_index().to_dict()
        )
    else:
        status_counts = (
            pd.Series([metric.calibration_status for metric in horizon_metrics]).value_counts().sort_index().to_dict()
            if horizon_metrics
            else {}
        )
    calibration_status_counts = {str(key): int(value) for key, value in status_counts.items()}
    candidate_horizons = [metric for metric in horizon_metrics if metric.calibration_status == CALIBRATION_CANDIDATE]
    raw_brier_mean = _mean([metric.raw_brier for metric in horizon_metrics])
    calibrated_brier_mean = _mean([metric.calibrated_brier for metric in candidate_horizons])
    raw_ece_mean = _mean([metric.raw_ece for metric in horizon_metrics])
    calibrated_ece_mean = _mean([metric.calibrated_ece for metric in candidate_horizons])
    if raw_brier_mean is not None and calibrated_brier_mean is not None:
        brier_delta_mean = calibrated_brier_mean - raw_brier_mean
    else:
        brier_delta_mean = None
    baseline_brier_mean = _mean([metric.age_bucket_baseline_brier for metric in slice_metrics])
    labels = eligible["exit_within_horizon"].astype(int) if not eligible.empty else pd.Series(dtype=int)
    calibrated_probability_count = int(eligible["_calibrated_probability"].notna().sum())
    if any(metric.calibration_status == DEGRADED_BRIER_WORSE for metric in horizon_metrics):
        status = "partial"
    elif candidate_horizons:
        status = "pass"
    elif len(work) > 0:
        status = "partial"
    else:
        status = "fail"
    validation_only = bool(len(eligible) == 0 or eligible["_split_role_normalized"].eq("validation").all())
    horizons = sorted(int(value) for value in eligible["horizon_days"].dropna().unique().tolist()) if not eligible.empty else []
    joined_count = int(eligible["_age_bucket_event_rate"].notna().sum()) if "_age_bucket_event_rate" in eligible else 0

    return HazardIsotonicCalibrationResult(
        status=status,
        calibration_version=CALIBRATION_VERSION,
        source=source,
        hazard_prediction_row_count=int(len(work)),
        calibration_sample_count=int(len(eligible)),
        positive_count=int(labels.sum()) if len(labels) else 0,
        negative_count=int(len(labels) - labels.sum()) if len(labels) else 0,
        horizons=horizons,
        min_sample_count=int(min_sample_count),
        min_slice_sample_count=min_slice,
        validation_only=validation_only,
        final_holdout_tuning=False,
        final_holdout_excluded_count=final_holdout_count,
        non_validation_excluded_count=non_validation_count,
        invalid_prediction_count=invalid_count,
        raw_brier_mean=raw_brier_mean,
        calibrated_brier_mean=calibrated_brier_mean,
        brier_delta_mean=brier_delta_mean,
        raw_ece_mean=raw_ece_mean,
        calibrated_ece_mean=calibrated_ece_mean,
        age_bucket_baseline_brier_mean=baseline_brier_mean,
        age_bucket_baseline_joined_row_count=joined_count,
        age_bucket_baseline_key_columns=baseline_keys,
        horizon_metrics=[asdict(metric) for metric in horizon_metrics],
        slice_metrics=[asdict(metric) for metric in slice_metrics],
        calibration_status_counts=calibration_status_counts,
        usable_probability_count=0,
        calibrated_probability_count=calibrated_probability_count,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP5 Hazard Isotonic Calibration",
        "",
        f"status: {summary.get('status')}",
        f"calibration_version: {summary.get('calibration_version')}",
        f"source: {summary.get('source')}",
        f"hazard_prediction_row_count: {summary.get('hazard_prediction_row_count')}",
        f"calibration_sample_count: {summary.get('calibration_sample_count')}",
        f"positive_count: {summary.get('positive_count')}",
        f"negative_count: {summary.get('negative_count')}",
        f"horizons: {summary.get('horizons')}",
        f"validation_only: {str(summary.get('validation_only')).lower()}",
        f"final_holdout_tuning: {str(summary.get('final_holdout_tuning')).lower()}",
        f"final_holdout_excluded_count: {summary.get('final_holdout_excluded_count')}",
        f"non_validation_excluded_count: {summary.get('non_validation_excluded_count')}",
        f"usable_probability_count: {summary.get('usable_probability_count')}",
        "",
        "## Brier and ECE",
        "",
        f"- raw_brier_mean: {summary.get('raw_brier_mean')}",
        f"- calibrated_brier_mean: {summary.get('calibrated_brier_mean')}",
        f"- brier_delta_mean: {summary.get('brier_delta_mean')}",
        f"- raw_ece_mean: {summary.get('raw_ece_mean')}",
        f"- calibrated_ece_mean: {summary.get('calibrated_ece_mean')}",
        f"- age_bucket_baseline_brier_mean: {summary.get('age_bucket_baseline_brier_mean')}",
        f"- age_bucket_baseline_joined_row_count: {summary.get('age_bucket_baseline_joined_row_count')}",
        "",
        "## Calibration Status Counts",
        "",
        "```json",
        json.dumps(summary.get("calibration_status_counts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Horizon Metrics",
        "",
        "```json",
        json.dumps(summary.get("horizon_metrics", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Slice Metrics",
        "",
        "```json",
        json.dumps(summary.get("slice_metrics", [])[:50], ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        "- calibration_status is diagnostic only; no readiness promotion here.",
        "- final holdout rows are excluded from calibration.",
        "- HSMM raw/calibrated p_exit is not consumed.",
        f"- external_data_fetch: {summary.get('external_data_fetch')}",
        f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
        f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
        "- usable_probability: no",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: HazardIsotonicCalibrationResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


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


def _load_or_rebuild_hazard_predictions(args: argparse.Namespace) -> tuple[pd.DataFrame, str, list[str]]:
    warnings: list[str] = []
    prediction_path = Path(args.hazard_predictions)
    if prediction_path.exists():
        return pd.read_csv(prediction_path, keep_default_na=True), f"hazard_predictions:{_safe_source_path(prediction_path)}", warnings
    if not args.db:
        raise FileNotFoundError(f"hazard predictions not found: {prediction_path}")
    db_args = argparse.Namespace(db=args.db, run_id=args.run_id, horizons=args.horizons)
    from src.models.duration_hazard import _dataset_from_db as hazard_dataset_from_db

    dataset, source = hazard_dataset_from_db(db_args)
    if dataset.empty:
        warnings.append(source)
        return pd.DataFrame(), source, warnings
    result = fit_duration_hazard_baseline(dataset, source=source, min_train_samples=args.min_train_samples)
    write_hazard_outputs(
        result,
        output=Path(args.hazard_baseline_output),
        summary_json=Path(args.hazard_baseline_summary_json),
        predictions_csv=prediction_path,
        max_predictions=args.max_predictions,
    )
    warnings.append("hazard predictions rebuilt from local DB because CSV was missing")
    return result.predictions, "local_db_rebuild", warnings


def _load_or_rebuild_age_bucket_baseline(args: argparse.Namespace) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    baseline_path = Path(args.age_bucket_baseline)
    if baseline_path.exists():
        return _load_json(baseline_path), warnings
    if not args.db:
        warnings.append(f"age-bucket baseline not found: {baseline_path}")
        return None, warnings
    from src.evaluation.age_bucket_baseline import _dataset_from_db as age_bucket_dataset_from_db

    db_args = argparse.Namespace(db=args.db, run_id=args.run_id, horizons=args.horizons)
    dataset, source = age_bucket_dataset_from_db(db_args)
    if dataset.empty:
        warnings.append(source)
        return None, warnings
    result = evaluate_age_bucket_baseline(dataset, source=source, min_sample_count=args.age_bucket_min_sample_count)
    write_age_bucket_outputs(result, Path(args.age_bucket_baseline_output), baseline_path)
    warnings.append("age-bucket baseline rebuilt from local DB because JSON was missing")
    return result.to_summary(), warnings


def run_cli(args: argparse.Namespace) -> int:
    hazard_predictions, source, hazard_warnings = _load_or_rebuild_hazard_predictions(args)
    age_baseline, baseline_warnings = _load_or_rebuild_age_bucket_baseline(args)
    result = evaluate_hazard_isotonic_calibration(
        hazard_predictions,
        age_bucket_baseline=age_baseline,
        source=source,
        min_sample_count=args.min_sample_count,
        min_slice_sample_count=args.min_slice_sample_count,
    )
    result.warnings.extend(hazard_warnings)
    result.warnings.extend(baseline_warnings)
    if args.db:
        db_path = Path(args.db)
        if not db_path.exists():
            result.warnings.append("local_db_missing")
        else:
            result.warnings.append(f"local_db_available:{_safe_source_path(db_path)}")
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Stage03R WP5 Duration Hazard isotonic calibration diagnostics")
    parser.add_argument("--hazard-predictions", required=True, help="WP3 hazard prediction CSV")
    parser.add_argument("--age-bucket-baseline", required=True, help="WP4 age-bucket baseline JSON")
    parser.add_argument("--db", default=None, help="Optional local DuckDB path for missing-input rebuild mode")
    parser.add_argument("--run-id", default="latest", help="Run id for local DB rebuild mode")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizons for local DB rebuild mode")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--min-sample-count", type=int, default=30)
    parser.add_argument("--min-slice-sample-count", type=int, default=None)
    parser.add_argument("--age-bucket-min-sample-count", type=int, default=30)
    parser.add_argument("--min-train-samples", type=int, default=4)
    parser.add_argument("--max-predictions", type=int, default=5000)
    parser.add_argument(
        "--hazard-baseline-output",
        default="reports/stage03r/duration_hazard_logistic_baseline_report.md",
    )
    parser.add_argument(
        "--hazard-baseline-summary-json",
        default="reports/stage03r/duration_hazard_logistic_baseline_report.json",
    )
    parser.add_argument(
        "--age-bucket-baseline-output",
        default="reports/stage03r/age_bucket_baseline_report.md",
    )
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
