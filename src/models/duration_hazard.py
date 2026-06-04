"""Stage03R WP3 raw logistic Duration Hazard baseline.

This module trains only a lightweight per-horizon logistic baseline on
``exit_target_dataset_v1`` rows. It does not calibrate probabilities, create a
readiness matrix, fetch data, or modify HMM/HSMM training algorithms.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import numpy as np
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
from src.evaluation.exit_target_leakage_audit import (
    SplitPlan,
    audit_exit_target_dataset,
    build_purged_time_split_plan,
    validate_split_plan,
)


INDEX_ID = "STAGE03R-WP3"
MODEL_VERSION = "duration_hazard_logistic_v1"
RAW_PROBABILITY_ONLY = "raw_probability_only"
INSUFFICIENT_SAMPLE = "insufficient_sample"
INVALID = "invalid"
EXCLUDED_CENSORED = "excluded_censored"

OBSERVED_STATUSES = {OBSERVED_POSITIVE, OBSERVED_NEGATIVE}
RIGHT_CENSORED_STATUSES = {RIGHT_CENSORED_BY_RUN_END, RIGHT_CENSORED_BY_CUTOFF}
UNKNOWN_STATUSES = {UNKNOWN_MISSING_CALENDAR, UNKNOWN_MISSING_STATE_SEQUENCE}
NON_TRAINABLE_STATUSES = RIGHT_CENSORED_STATUSES | UNKNOWN_STATUSES

REQUIRED_NUMERIC_FEATURES = ("state_age", "duration_percentile", "horizon_days")
REQUIRED_CATEGORICAL_FEATURES = ("state_label", "state_phase")
OPTIONAL_NUMERIC_FEATURES = (
    "volatility_20d",
    "rs_20d",
    "drawdown_20d",
    "liquidity_feature",
    "breadth_feature",
    "hmm_state_confidence",
    "hmm_state_entropy",
    "hmm_posterior_margin",
)
OPTIONAL_CATEGORICAL_FEATURES = (
    "market_regime_label",
    "state_source",
    "profile_mode",
    "state_date_policy",
)
REQUIRED_PREDICTION_COLUMNS = (
    "target_dataset_id",
    "sector_code",
    "trade_date",
    "state_label",
    "state_age",
    "state_phase",
    "horizon_days",
    "censoring_status",
    "exit_within_horizon",
    "fold_id",
    "split_role",
    "hazard_model_version",
    "hazard_raw_score",
    "hazard_raw_probability",
    "hazard_status",
    "sample_support",
    "fallback_reason",
)


@dataclass
class FeatureSpec:
    numeric_features: list[str]
    categorical_features: list[str]
    feature_columns_used: list[str]
    missing_feature_columns: list[str]


@dataclass
class FoldMetric:
    fold_id: str
    horizon_days: int
    status: str
    train_row_count: int
    validation_row_count: int
    observed_positive_count: int
    observed_negative_count: int
    right_censored_excluded_count: int
    feature_columns_used: list[str]
    missing_feature_columns: list[str]
    brier_raw: float | None
    log_loss_raw: float | None
    auc_raw: float | None
    positive_rate: float | None
    prediction_min: float | None
    prediction_max: float | None
    prediction_mean: float | None
    fallback_reason: str | None = None


@dataclass
class HazardBaselineResult:
    status: str
    model_version: str
    source: str
    row_count: int
    trainable_row_count: int
    right_censored_excluded_count: int
    horizons: list[int]
    feature_columns_used: list[str]
    missing_feature_columns: list[str]
    fold_count: int
    fold_metrics: list[FoldMetric]
    horizon_metrics: list[dict[str, Any]]
    state_label_x_horizon_support: list[dict[str, Any]]
    age_bucket_x_horizon_support: list[dict[str, Any]]
    purge_embargo_used: bool
    feature_leakage_violation_count: int
    hazard_status_counts: dict[str, int]
    usable_probability_count: int
    predictions: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=REQUIRED_PREDICTION_COLUMNS))
    external_data_fetch: str = "no"
    training_algorithm_modified: str = "no"
    DuckDB_committed: str = "no"
    audit_status: str | None = None
    audit_hard_violation_count: int = 0

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("predictions", None)
        data["wp"] = INDEX_ID
        data["fold_metrics"] = [asdict(metric) for metric in self.fold_metrics]
        data["prediction_row_count"] = int(len(self.predictions))
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


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(pd.Timestamp(value).date())


def _sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def _age_bucket(value: Any) -> str:
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


def _is_false_like(values: pd.Series) -> pd.Series:
    if values.empty:
        return pd.Series(dtype=bool)
    if values.dtype == bool:
        return ~values
    normalized = values.fillna(False).astype(str).str.lower()
    return normalized.isin({"false", "0", "0.0", "no", "none", "nan", ""})


def trainable_label_mask(dataset: pd.DataFrame) -> pd.Series:
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    labels = pd.to_numeric(dataset.get("exit_within_horizon", pd.Series(index=dataset.index)), errors="coerce")
    weights = pd.to_numeric(dataset.get("sample_weight", pd.Series(0.0, index=dataset.index)), errors="coerce").fillna(0.0)
    leakage = dataset.get("feature_leakage_violation", pd.Series(False, index=dataset.index))
    return status.isin(OBSERVED_STATUSES) & labels.isin([0, 1]) & (weights > 0) & _is_false_like(leakage)


def _right_censored_mask(dataset: pd.DataFrame) -> pd.Series:
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    return status.isin(RIGHT_CENSORED_STATUSES)


def _non_trainable_mask(dataset: pd.DataFrame) -> pd.Series:
    status = dataset.get("censoring_status", pd.Series("", index=dataset.index)).fillna("").astype(str)
    return status.isin(NON_TRAINABLE_STATUSES)


def infer_feature_spec(dataset: pd.DataFrame) -> FeatureSpec:
    columns = set(dataset.columns)
    numeric = [feature for feature in REQUIRED_NUMERIC_FEATURES if feature in columns]
    numeric.extend(feature for feature in OPTIONAL_NUMERIC_FEATURES if feature in columns)
    categorical = [feature for feature in REQUIRED_CATEGORICAL_FEATURES if feature in columns]
    categorical.extend(feature for feature in OPTIONAL_CATEGORICAL_FEATURES if feature in columns)
    missing_optional = [
        feature
        for feature in [*OPTIONAL_NUMERIC_FEATURES, *OPTIONAL_CATEGORICAL_FEATURES]
        if feature not in columns
    ]
    missing_required = [
        feature
        for feature in [*REQUIRED_NUMERIC_FEATURES, *REQUIRED_CATEGORICAL_FEATURES]
        if feature not in columns
    ]
    return FeatureSpec(
        numeric_features=numeric,
        categorical_features=categorical,
        feature_columns_used=[*numeric, *categorical],
        missing_feature_columns=sorted([*missing_optional, *missing_required]),
    )


def _encode_features(
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    spec: FeatureSpec,
) -> tuple[np.ndarray, np.ndarray]:
    train_parts: list[np.ndarray] = []
    validation_parts: list[np.ndarray] = []
    for feature in spec.numeric_features:
        train_values = pd.to_numeric(train_rows[feature], errors="coerce")
        validation_values = pd.to_numeric(validation_rows[feature], errors="coerce")
        fill_value = float(train_values.median()) if train_values.notna().any() else 0.0
        train_array = train_values.fillna(fill_value).astype(float).to_numpy()
        validation_array = validation_values.fillna(fill_value).astype(float).to_numpy()
        mean = float(train_array.mean()) if len(train_array) else 0.0
        std = float(train_array.std()) if len(train_array) else 1.0
        if not math.isfinite(std) or std <= 1e-12:
            std = 1.0
        train_parts.append(((train_array - mean) / std).reshape(-1, 1))
        validation_parts.append(((validation_array - mean) / std).reshape(-1, 1))

    for feature in spec.categorical_features:
        train_values = train_rows[feature].fillna("missing").astype(str)
        validation_values = validation_rows[feature].fillna("missing").astype(str)
        categories = sorted(train_values.unique().tolist())
        if not categories:
            categories = ["missing"]
        train_encoded = np.zeros((len(train_rows), len(categories)), dtype=float)
        validation_encoded = np.zeros((len(validation_rows), len(categories)), dtype=float)
        category_pos = {category: pos for pos, category in enumerate(categories)}
        for row_pos, value in enumerate(train_values.tolist()):
            train_encoded[row_pos, category_pos[value]] = 1.0
        for row_pos, value in enumerate(validation_values.tolist()):
            pos = category_pos.get(value)
            if pos is not None:
                validation_encoded[row_pos, pos] = 1.0
        train_parts.append(train_encoded)
        validation_parts.append(validation_encoded)

    if not train_parts:
        return np.ones((len(train_rows), 1), dtype=float), np.ones((len(validation_rows), 1), dtype=float)
    return np.hstack(train_parts), np.hstack(validation_parts)


def _fit_predict_numpy(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_validation: np.ndarray,
    sample_weight: np.ndarray,
    *,
    max_iter: int = 220,
    learning_rate: float = 0.25,
    l2: float = 1e-4,
) -> tuple[np.ndarray, np.ndarray]:
    coef = np.zeros(x_train.shape[1], dtype=float)
    intercept = 0.0
    weights = sample_weight.astype(float)
    weights = weights / max(float(weights.mean()), 1e-12)
    denom = max(float(weights.sum()), 1e-12)
    for _ in range(max_iter):
        scores = x_train @ coef + intercept
        probs = _sigmoid(scores)
        residual = (probs - y_train) * weights
        grad_coef = (x_train.T @ residual) / denom + l2 * coef
        grad_intercept = float(residual.sum() / denom)
        coef -= learning_rate * grad_coef
        intercept -= learning_rate * grad_intercept
    validation_scores = x_validation @ coef + intercept
    return validation_scores, _sigmoid(validation_scores)


def _fit_predict_logistic(
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    spec: FeatureSpec,
) -> tuple[np.ndarray, np.ndarray]:
    x_train, x_validation = _encode_features(train_rows, validation_rows, spec)
    y_train = pd.to_numeric(train_rows["exit_within_horizon"], errors="coerce").astype(int).to_numpy()
    weights = pd.to_numeric(train_rows.get("sample_weight", 1.0), errors="coerce").fillna(1.0).to_numpy()
    if len(train_rows) >= 1000:
        try:
            from sklearn.linear_model import LogisticRegression

            model = LogisticRegression(max_iter=250, random_state=0, solver="lbfgs")
            model.fit(x_train, y_train, sample_weight=weights)
            scores = model.decision_function(x_validation)
            probabilities = model.predict_proba(x_validation)[:, 1]
            return np.asarray(scores, dtype=float), np.asarray(probabilities, dtype=float)
        except Exception:
            pass
    return _fit_predict_numpy(x_train, y_train, x_validation, weights)


def _brier(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    return float(np.mean((probabilities - y_true) ** 2))


def _log_loss(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    return float(-np.mean(y_true * np.log(clipped) + (1.0 - y_true) * np.log(1.0 - clipped)))


def _auc(y_true: np.ndarray, probabilities: np.ndarray) -> float | None:
    positives = probabilities[y_true == 1]
    negatives = probabilities[y_true == 0]
    if len(positives) == 0 or len(negatives) == 0:
        return None
    combined = pd.DataFrame({"score": probabilities, "label": y_true})
    ranks = combined["score"].rank(method="average").to_numpy()
    positive_rank_sum = float(ranks[y_true == 1].sum())
    n_pos = float(len(positives))
    n_neg = float(len(negatives))
    return float((positive_rank_sum - n_pos * (n_pos + 1.0) / 2.0) / (n_pos * n_neg))


def _support_records(dataset: pd.DataFrame, group_cols: list[str]) -> list[dict[str, Any]]:
    if dataset.empty:
        return []
    work = dataset.copy()
    if "age_bucket" in group_cols and "age_bucket" not in work.columns:
        work["age_bucket"] = work.get("state_age", pd.Series(index=work.index)).map(_age_bucket)
    grouped = (
        work.groupby(group_cols, dropna=False)
        .agg(
            row_count=("censoring_status", "size"),
            observed_positive_count=("censoring_status", lambda s: int((s == OBSERVED_POSITIVE).sum())),
            observed_negative_count=("censoring_status", lambda s: int((s == OBSERVED_NEGATIVE).sum())),
            right_censored_count=("censoring_status", lambda s: int(s.isin(RIGHT_CENSORED_STATUSES).sum())),
        )
        .reset_index()
        .sort_values(group_cols)
    )
    return [
        {
            key: (None if pd.isna(row[key]) else row[key])
            for key in [*group_cols, "row_count", "observed_positive_count", "observed_negative_count", "right_censored_count"]
        }
        for _, row in grouped.iterrows()
    ]


def _base_prediction_rows(rows: pd.DataFrame, split_id: str, status: str, sample_support: int, reason: str | None) -> pd.DataFrame:
    prediction_rows = rows.copy()
    for column in REQUIRED_PREDICTION_COLUMNS:
        if column not in prediction_rows.columns:
            prediction_rows[column] = pd.NA
    prediction_rows["fold_id"] = split_id
    prediction_rows["split_role"] = "validation"
    prediction_rows["hazard_model_version"] = MODEL_VERSION
    prediction_rows["hazard_raw_score"] = pd.NA
    prediction_rows["hazard_raw_probability"] = pd.NA
    prediction_rows["hazard_status"] = status
    prediction_rows["sample_support"] = int(sample_support)
    prediction_rows["fallback_reason"] = reason
    return prediction_rows.loc[:, REQUIRED_PREDICTION_COLUMNS].copy()


def _metric_from_predictions(
    *,
    fold_id: str,
    horizon: int,
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    probabilities: np.ndarray | None,
    spec: FeatureSpec,
    status: str,
    fallback_reason: str | None,
) -> FoldMetric:
    validation_observed = validation_rows.loc[trainable_label_mask(validation_rows)].copy()
    observed_labels = pd.to_numeric(validation_observed.get("exit_within_horizon", pd.Series(dtype=float)), errors="coerce")
    positive_count = int((observed_labels == 1).sum())
    negative_count = int((observed_labels == 0).sum())
    right_censored_count = int(_right_censored_mask(validation_rows).sum())
    brier_raw = log_loss_raw = auc_raw = positive_rate = None
    prediction_min = prediction_max = prediction_mean = None
    metric_status = status
    if probabilities is not None and not validation_observed.empty and positive_count > 0 and negative_count > 0:
        y_true = observed_labels.astype(int).to_numpy()
        brier_raw = _brier(y_true, probabilities)
        log_loss_raw = _log_loss(y_true, probabilities)
        auc_raw = _auc(y_true, probabilities)
        positive_rate = float(y_true.mean())
        prediction_min = float(np.min(probabilities))
        prediction_max = float(np.max(probabilities))
        prediction_mean = float(np.mean(probabilities))
    elif status == RAW_PROBABILITY_ONLY:
        metric_status = INSUFFICIENT_SAMPLE
        fallback_reason = fallback_reason or "validation labels lack both classes"
    return FoldMetric(
        fold_id=fold_id,
        horizon_days=int(horizon),
        status=metric_status,
        train_row_count=int(len(train_rows)),
        validation_row_count=int(len(validation_rows)),
        observed_positive_count=positive_count,
        observed_negative_count=negative_count,
        right_censored_excluded_count=right_censored_count,
        feature_columns_used=spec.feature_columns_used,
        missing_feature_columns=spec.missing_feature_columns,
        brier_raw=brier_raw,
        log_loss_raw=log_loss_raw,
        auc_raw=auc_raw,
        positive_rate=positive_rate,
        prediction_min=prediction_min,
        prediction_max=prediction_max,
        prediction_mean=prediction_mean,
        fallback_reason=fallback_reason,
    )


def _horizon_metrics(fold_metrics: Sequence[FoldMetric]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    by_horizon: dict[int, list[FoldMetric]] = {}
    for metric in fold_metrics:
        by_horizon.setdefault(metric.horizon_days, []).append(metric)
    for horizon, metrics in sorted(by_horizon.items()):
        usable = [metric for metric in metrics if metric.brier_raw is not None]
        records.append(
            {
                "horizon_days": int(horizon),
                "fold_count": len(metrics),
                "raw_metric_fold_count": len(usable),
                "train_row_count": int(sum(metric.train_row_count for metric in metrics)),
                "validation_row_count": int(sum(metric.validation_row_count for metric in metrics)),
                "observed_positive_count": int(sum(metric.observed_positive_count for metric in metrics)),
                "observed_negative_count": int(sum(metric.observed_negative_count for metric in metrics)),
                "right_censored_excluded_count": int(sum(metric.right_censored_excluded_count for metric in metrics)),
                "brier_raw_mean": float(np.mean([metric.brier_raw for metric in usable])) if usable else None,
                "log_loss_raw_mean": float(np.mean([metric.log_loss_raw for metric in usable])) if usable else None,
                "auc_raw_mean": float(np.mean([metric.auc_raw for metric in usable if metric.auc_raw is not None]))
                if any(metric.auc_raw is not None for metric in usable)
                else None,
                "status": RAW_PROBABILITY_ONLY if usable else INSUFFICIENT_SAMPLE,
            }
        )
    return records


def fit_duration_hazard_baseline(
    dataset: pd.DataFrame,
    *,
    source: str = "synthetic",
    n_splits: int = 3,
    min_train_samples: int = 4,
    split_plan: SplitPlan | None = None,
) -> HazardBaselineResult:
    work = dataset.copy()
    if work.empty:
        spec = infer_feature_spec(work)
        return HazardBaselineResult(
            status="partial",
            model_version=MODEL_VERSION,
            source=source,
            row_count=0,
            trainable_row_count=0,
            right_censored_excluded_count=0,
            horizons=[],
            feature_columns_used=spec.feature_columns_used,
            missing_feature_columns=spec.missing_feature_columns,
            fold_count=0,
            fold_metrics=[],
            horizon_metrics=[],
            state_label_x_horizon_support=[],
            age_bucket_x_horizon_support=[],
            purge_embargo_used=False,
            feature_leakage_violation_count=0,
            hazard_status_counts={},
            usable_probability_count=0,
            audit_status="partial",
            audit_hard_violation_count=0,
        )

    work = work.reset_index(drop=True).copy()
    for column in ["trade_date", "target_observation_end_date", "embargo_until_date"]:
        if column in work.columns:
            work[column] = pd.to_datetime(work[column], errors="coerce").dt.date.astype("string")
    audit = audit_exit_target_dataset(work, strict=True, source=source, split_plan=split_plan)
    audit_hard_count = sum(1 for violation in audit.violations if violation.severity == "hard")
    spec = infer_feature_spec(work)
    trainable_mask = trainable_label_mask(work)
    horizons = sorted(int(value) for value in pd.to_numeric(work.get("horizon_days"), errors="coerce").dropna().unique())
    right_censored_count = int(_right_censored_mask(work).sum())
    feature_leakage_count = int(audit.feature_leakage_violation_count)

    if audit_hard_count:
        invalid_predictions = _base_prediction_rows(work.head(0), "none", INVALID, 0, "exit target audit failed")
        return HazardBaselineResult(
            status="fail",
            model_version=MODEL_VERSION,
            source=source,
            row_count=int(len(work)),
            trainable_row_count=int(trainable_mask.sum()),
            right_censored_excluded_count=right_censored_count,
            horizons=horizons,
            feature_columns_used=spec.feature_columns_used,
            missing_feature_columns=spec.missing_feature_columns,
            fold_count=0,
            fold_metrics=[],
            horizon_metrics=[],
            state_label_x_horizon_support=_support_records(work, ["state_label", "horizon_days"]),
            age_bucket_x_horizon_support=_support_records(work, ["age_bucket", "horizon_days"]),
            purge_embargo_used=False,
            feature_leakage_violation_count=feature_leakage_count,
            hazard_status_counts={},
            usable_probability_count=0,
            predictions=invalid_predictions,
            audit_status=audit.status,
            audit_hard_violation_count=audit_hard_count,
        )

    split_plan = split_plan or build_purged_time_split_plan(work, n_splits=n_splits, final_holdout_start=None)
    split_violations = validate_split_plan(work, split_plan)
    purge_embargo_used = not any(violation.severity == "hard" for violation in split_violations)

    prediction_frames: list[pd.DataFrame] = []
    fold_metrics: list[FoldMetric] = []
    for split in split_plan.splits:
        validation_all = work.loc[[index for index in split.validation_indices if index in work.index]].copy()
        train_all = work.loc[[index for index in split.train_indices if index in work.index]].copy()
        for horizon in horizons:
            train_rows = train_all[train_all["horizon_days"].astype(int).eq(int(horizon))]
            train_rows = train_rows.loc[trainable_label_mask(train_rows)].copy()
            validation_rows = validation_all[validation_all["horizon_days"].astype(int).eq(int(horizon))].copy()
            if validation_rows.empty:
                continue
            validation_observed = validation_rows.loc[trainable_label_mask(validation_rows)].copy()
            train_labels = pd.to_numeric(train_rows.get("exit_within_horizon", pd.Series(dtype=float)), errors="coerce")
            train_positive = int((train_labels == 1).sum())
            train_negative = int((train_labels == 0).sum())
            sample_support = int(len(train_rows))
            if sample_support < min_train_samples or train_positive == 0 or train_negative == 0:
                reason = "train labels lack both classes" if train_positive == 0 or train_negative == 0 else "train sample below minimum"
                prediction_frames.append(_base_prediction_rows(validation_rows, split.split_id, INSUFFICIENT_SAMPLE, sample_support, reason))
                fold_metrics.append(
                    _metric_from_predictions(
                        fold_id=split.split_id,
                        horizon=int(horizon),
                        train_rows=train_rows,
                        validation_rows=validation_rows,
                        probabilities=None,
                        spec=spec,
                        status=INSUFFICIENT_SAMPLE,
                        fallback_reason=reason,
                    )
                )
                continue

            scores_observed: np.ndarray | None = None
            probabilities_observed: np.ndarray | None = None
            scored_parts: list[pd.DataFrame] = []
            if not validation_observed.empty:
                scores_observed, probabilities_observed = _fit_predict_logistic(train_rows, validation_observed, spec)
                observed_predictions = _base_prediction_rows(validation_observed, split.split_id, RAW_PROBABILITY_ONLY, sample_support, None)
                observed_predictions["hazard_raw_score"] = scores_observed
                observed_predictions["hazard_raw_probability"] = probabilities_observed
                scored_parts.append(observed_predictions)
            non_trainable_validation = validation_rows.loc[_non_trainable_mask(validation_rows)].copy()
            if not non_trainable_validation.empty:
                scored_parts.append(
                    _base_prediction_rows(
                        non_trainable_validation,
                        split.split_id,
                        EXCLUDED_CENSORED,
                        sample_support,
                        "right-censored or unknown label excluded from supervised training",
                    )
                )
            other_invalid = validation_rows.drop(index=[*validation_observed.index.tolist(), *non_trainable_validation.index.tolist()]).copy()
            if not other_invalid.empty:
                scored_parts.append(_base_prediction_rows(other_invalid, split.split_id, INVALID, sample_support, "row is not trainable or censored"))
            prediction_frames.append(pd.concat(scored_parts, ignore_index=True))
            fold_metrics.append(
                _metric_from_predictions(
                    fold_id=split.split_id,
                    horizon=int(horizon),
                    train_rows=train_rows,
                    validation_rows=validation_rows,
                    probabilities=probabilities_observed,
                    spec=spec,
                    status=RAW_PROBABILITY_ONLY,
                    fallback_reason=None,
                )
            )

    predictions = (
        pd.concat(prediction_frames, ignore_index=True)
        if prediction_frames
        else pd.DataFrame(columns=REQUIRED_PREDICTION_COLUMNS)
    )
    for column in REQUIRED_PREDICTION_COLUMNS:
        if column not in predictions.columns:
            predictions[column] = pd.NA
    predictions = predictions.loc[:, REQUIRED_PREDICTION_COLUMNS]
    status_counts = {str(key): int(value) for key, value in predictions["hazard_status"].value_counts(dropna=False).sort_index().to_dict().items()} if not predictions.empty else {}
    has_raw_predictions = int(status_counts.get(RAW_PROBABILITY_ONLY, 0)) > 0
    has_metric = any(metric.brier_raw is not None for metric in fold_metrics)
    if audit_hard_count or not purge_embargo_used:
        status = "fail"
    elif has_raw_predictions and has_metric:
        status = "pass"
    elif len(work) > 0:
        status = "partial"
    else:
        status = "fail"

    return HazardBaselineResult(
        status=status,
        model_version=MODEL_VERSION,
        source=source,
        row_count=int(len(work)),
        trainable_row_count=int(trainable_mask.sum()),
        right_censored_excluded_count=right_censored_count,
        horizons=horizons,
        feature_columns_used=spec.feature_columns_used,
        missing_feature_columns=spec.missing_feature_columns,
        fold_count=int(len(split_plan.splits)),
        fold_metrics=fold_metrics,
        horizon_metrics=_horizon_metrics(fold_metrics),
        state_label_x_horizon_support=_support_records(work, ["state_label", "horizon_days"]),
        age_bucket_x_horizon_support=_support_records(work, ["age_bucket", "horizon_days"]),
        purge_embargo_used=purge_embargo_used,
        feature_leakage_violation_count=feature_leakage_count,
        hazard_status_counts=status_counts,
        usable_probability_count=0,
        predictions=predictions,
        audit_status=audit.status,
        audit_hard_violation_count=audit_hard_count,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP3 Duration Hazard Logistic Baseline",
        "",
        f"status: {summary.get('status')}",
        f"model_version: {summary.get('model_version')}",
        f"source: {summary.get('source')}",
        f"row_count: {summary.get('row_count')}",
        f"trainable_row_count: {summary.get('trainable_row_count')}",
        f"right_censored_excluded_count: {summary.get('right_censored_excluded_count')}",
        f"horizons: {summary.get('horizons')}",
        f"fold_count: {summary.get('fold_count')}",
        f"purge_embargo_used: {str(summary.get('purge_embargo_used')).lower()}",
        f"feature_leakage_violation_count: {summary.get('feature_leakage_violation_count')}",
        f"usable_probability_count: {summary.get('usable_probability_count')}",
        "",
        "## Feature Columns",
        "",
        f"- feature_columns_used: {summary.get('feature_columns_used')}",
        f"- missing_feature_columns: {summary.get('missing_feature_columns')}",
        "",
        "## Hazard Status Counts",
        "",
        "```json",
        json.dumps(summary.get("hazard_status_counts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Fold Metrics",
        "",
        "```json",
        json.dumps(summary.get("fold_metrics", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Horizon Metrics",
        "",
        "```json",
        json.dumps(summary.get("horizon_metrics", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        f"- external_data_fetch: {summary.get('external_data_fetch')}",
        f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
        f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
        "- calibrated_probability: no",
        "- usable_probability: no",
    ]
    return "\n".join(lines) + "\n"


def write_hazard_outputs(
    result: HazardBaselineResult,
    *,
    output: Path,
    summary_json: Path,
    predictions_csv: Path,
    max_predictions: int = 5000,
) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    predictions_csv.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    sample_hazard_predictions(result.predictions, max_predictions=max_predictions).to_csv(predictions_csv, index=False)


def sample_hazard_predictions(predictions: pd.DataFrame, *, max_predictions: int = 5000) -> pd.DataFrame:
    if max_predictions <= 0 or len(predictions) <= max_predictions:
        return predictions.copy()
    if "horizon_days" not in predictions.columns or predictions.empty:
        return predictions.head(max_predictions).copy()

    work = predictions.copy()
    horizon_values = pd.to_numeric(work["horizon_days"], errors="coerce")
    horizons = sorted(int(value) for value in horizon_values.dropna().unique())
    if not horizons:
        return work.head(max_predictions).copy()

    group_count = len(horizons)
    base_take = max_predictions // group_count
    remainder = max_predictions % group_count
    selected_indices: list[Any] = []
    grouped_indices: dict[int, list[Any]] = {}
    for horizon in horizons:
        group_index = work.index[horizon_values.eq(horizon)].tolist()
        grouped_indices[horizon] = group_index
        initial_take = base_take + (1 if remainder > 0 else 0)
        remainder = max(0, remainder - 1)
        selected_indices.extend(group_index[:initial_take])

    cursor_by_horizon = {
        horizon: base_take + (1 if pos < max_predictions % group_count else 0)
        for pos, horizon in enumerate(horizons)
    }
    while len(selected_indices) < max_predictions:
        added = False
        for horizon in horizons:
            cursor = cursor_by_horizon[horizon]
            group_index = grouped_indices[horizon]
            if cursor < len(group_index):
                selected_indices.append(group_index[cursor])
                cursor_by_horizon[horizon] = cursor + 1
                added = True
                if len(selected_indices) >= max_predictions:
                    break
        if not added:
            break
    return work.loc[selected_indices].copy()


def _load_dataset_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, keep_default_na=True)


def _result_for_missing_db(source: str = "local_db_missing") -> HazardBaselineResult:
    empty = pd.DataFrame(columns=REQUIRED_PREDICTION_COLUMNS)
    return HazardBaselineResult(
        status="partial",
        model_version=MODEL_VERSION,
        source=source,
        row_count=0,
        trainable_row_count=0,
        right_censored_excluded_count=0,
        horizons=[],
        feature_columns_used=[],
        missing_feature_columns=sorted([*OPTIONAL_NUMERIC_FEATURES, *OPTIONAL_CATEGORICAL_FEATURES, *REQUIRED_NUMERIC_FEATURES, *REQUIRED_CATEGORICAL_FEATURES]),
        fold_count=0,
        fold_metrics=[],
        horizon_metrics=[],
        state_label_x_horizon_support=[],
        age_bucket_x_horizon_support=[],
        purge_embargo_used=False,
        feature_leakage_violation_count=0,
        hazard_status_counts={},
        usable_probability_count=0,
        predictions=empty,
        audit_status="partial",
        audit_hard_violation_count=0,
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
        result = fit_duration_hazard_baseline(dataset, source="dataset_csv", min_train_samples=args.min_train_samples)
    elif args.db:
        dataset, source = _dataset_from_db(args)
        if dataset.empty:
            result = _result_for_missing_db(source)
        else:
            result = fit_duration_hazard_baseline(dataset, source=source, min_train_samples=args.min_train_samples)
    else:
        raise SystemExit("--dataset or --db is required")
    write_hazard_outputs(
        result,
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        predictions_csv=Path(args.predictions_csv),
        max_predictions=args.max_predictions,
    )
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Train Stage03R WP3 raw logistic Duration Hazard baseline")
    parser.add_argument("--dataset", default=None, help="Dataset CSV to train/evaluate")
    parser.add_argument("--db", default=None, help="Local DuckDB path for rebuild-and-train mode")
    parser.add_argument("--run-id", default="latest", help="Run id for local DB rebuild mode")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizons for local DB rebuild mode")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--predictions-csv", required=True, help="Predictions sample CSV path")
    parser.add_argument("--min-train-samples", type=int, default=4)
    parser.add_argument("--max-predictions", type=int, default=5000)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
