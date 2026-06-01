from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_exit_targets import (
    build_exit_targets,
    parse_exit_types,
    parse_horizons,
    read_hsmm_episodes,
    read_hsmm_states,
)


AGE_BUCKETS = [(1, 3), (4, 7), (8, 14), (15, None)]
PROB_BINS = np.linspace(0.0, 1.0, 6)
PROB_LABELS = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]


@dataclass(frozen=True)
class CalibrationConfig:
    min_delta_brier: float = 0.005
    max_ece_for_probability: float = 0.05
    max_mce_for_probability: float = 0.15
    min_sample_per_state_horizon: int = 1000
    min_positive_events: int = 100
    min_bucket_count: int = 200
    shrinkage_alpha: float = 100.0
    time_split: tuple[float, float, float] = (0.6, 0.2, 0.2)


def age_bucket(value: object, buckets: list[tuple[int, int | None]] = AGE_BUCKETS) -> str:
    try:
        age = int(value)
    except Exception:
        return "unknown"
    for low, high in buckets:
        if high is None and age >= low:
            return f"{low}+"
        if high is not None and low <= age <= high:
            return f"{low}-{high}"
    return "unknown"


def add_calibration_features(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    out["raw_exit_score"] = pd.to_numeric(out["raw_exit_score"], errors="coerce").clip(0.0, 1.0)
    out["actual_exit"] = out["actual_exit_within_h"].map({True: 1.0, False: 0.0})
    out["age_bucket"] = out["display_state_age_days"].apply(age_bucket)
    out["model_age_bucket"] = out["model_state_age_days"].apply(age_bucket)
    out["raw_score_bucket"] = pd.cut(out["raw_exit_score"], bins=[-0.001, *PROB_BINS[1:]], labels=PROB_LABELS)
    return out


def time_split_targets(targets: pd.DataFrame, split: tuple[float, float, float] = (0.6, 0.2, 0.2)) -> pd.DataFrame:
    if targets.empty:
        return targets.copy()
    out = add_calibration_features(targets)
    eligible = out[(out["is_right_censored_for_horizon"] == False) & out["actual_exit"].notna() & out["raw_exit_score"].notna()].copy()  # noqa: E712
    if eligible.empty:
        return eligible
    dates = pd.Series(pd.to_datetime(eligible["trade_date"]).drop_duplicates().sort_values()).reset_index(drop=True)
    n = len(dates)
    train_end_idx = max(0, min(n - 1, int(np.floor(n * split[0])) - 1))
    valid_end_idx = max(train_end_idx + 1, min(n - 1, int(np.floor(n * (split[0] + split[1]))) - 1))
    train_end = dates.iloc[train_end_idx]
    valid_end = dates.iloc[valid_end_idx]
    conditions = [
        eligible["trade_date"] <= train_end,
        (eligible["trade_date"] > train_end) & (eligible["trade_date"] <= valid_end),
        eligible["trade_date"] > valid_end,
    ]
    eligible["split"] = np.select(conditions, ["train", "validation", "test"], default="test")
    return eligible


def _brier(y: pd.Series, p: pd.Series) -> float:
    return float(((y.astype(float) - p.astype(float)) ** 2).mean()) if len(y) else np.nan


def _bucket_stats(y: pd.Series, p: pd.Series, n_bins: int = 5, strategy: str = "equal_width") -> pd.DataFrame:
    work = pd.DataFrame({"y": y.astype(float), "p": p.astype(float)}).dropna()
    if work.empty:
        return pd.DataFrame()
    if strategy == "equal_frequency":
        try:
            work["bucket"] = pd.qcut(work["p"], q=min(n_bins, work["p"].nunique()), duplicates="drop")
        except ValueError:
            work["bucket"] = "all"
    else:
        work["bucket"] = pd.cut(work["p"], bins=np.linspace(0, 1, n_bins + 1), include_lowest=True)
    grouped = (
        work.groupby("bucket", observed=True)
        .agg(sample_count=("y", "size"), mean_predicted=("p", "mean"), realized_rate=("y", "mean"))
        .reset_index()
    )
    grouped["abs_error"] = (grouped["realized_rate"] - grouped["mean_predicted"]).abs()
    return grouped


def _ece(y: pd.Series, p: pd.Series, strategy: str) -> tuple[float, float]:
    buckets = _bucket_stats(y, p, strategy=strategy)
    if buckets.empty:
        return np.nan, np.nan
    total = float(buckets["sample_count"].sum())
    ece = float((buckets["sample_count"] * buckets["abs_error"]).sum() / total) if total else np.nan
    mce = float(buckets["abs_error"].max())
    return ece, mce


def _monotonic_passed(y: pd.Series, p: pd.Series) -> tuple[bool, float]:
    buckets = _bucket_stats(y, p, strategy="equal_frequency")
    if len(buckets) < 2:
        return False, np.nan
    rates = buckets.sort_values("mean_predicted")["realized_rate"].to_numpy(dtype=float)
    monotonic = bool(np.all(np.diff(rates) >= -0.03))
    spearman = float(pd.Series(buckets["mean_predicted"]).corr(pd.Series(buckets["realized_rate"]), method="spearman"))
    return monotonic, spearman


def _calibration_slope_intercept(y: pd.Series, p: pd.Series) -> tuple[float, float]:
    work = pd.DataFrame({"y": y.astype(float), "p": p.astype(float)}).dropna()
    if len(work) < 3 or work["p"].nunique() < 2:
        return np.nan, np.nan
    try:
        slope, intercept = np.polyfit(work["p"], work["y"], deg=1)
        return float(slope), float(intercept)
    except Exception:
        return np.nan, np.nan


def _metrics(df: pd.DataFrame, probability_col: str, method: str, baseline_rate: float) -> dict[str, object]:
    if df.empty or probability_col not in df.columns:
        return {
            "method": method,
            "sample_count": 0,
            "positive_events": 0,
            "positive_rate": np.nan,
            "brier_score": np.nan,
            "baseline_brier": np.nan,
            "ece_equal_width": np.nan,
            "ece_equal_frequency": np.nan,
            "mce": np.nan,
            "mean_abs_calibration_error": np.nan,
            "bucket_monotonicity_passed": False,
            "spearman_pred_vs_realized_bucket_rate": np.nan,
            "calibration_slope": np.nan,
            "calibration_intercept": np.nan,
        }
    y = df["actual_exit"].astype(float)
    p = pd.to_numeric(df[probability_col], errors="coerce").clip(0, 1)
    ece_width, mce_width = _ece(y, p, "equal_width")
    ece_freq, mce_freq = _ece(y, p, "equal_frequency")
    monotonic, spearman = _monotonic_passed(y, p)
    slope, intercept = _calibration_slope_intercept(y, p)
    baseline = pd.Series(float(baseline_rate), index=df.index)
    return {
        "method": method,
        "sample_count": int(len(df)),
        "positive_events": int(y.sum()),
        "positive_rate": float(y.mean()) if len(y) else np.nan,
        "brier_score": _brier(y, p),
        "baseline_brier": _brier(y, baseline),
        "ece_equal_width": ece_width,
        "ece_equal_frequency": ece_freq,
        "mce": max(mce_width, mce_freq) if pd.notna(mce_width) and pd.notna(mce_freq) else np.nan,
        "mean_abs_calibration_error": float(abs(y.mean() - p.mean())) if len(y) else np.nan,
        "bucket_monotonicity_passed": monotonic,
        "spearman_pred_vs_realized_bucket_rate": spearman,
        "calibration_slope": slope,
        "calibration_intercept": intercept,
    }


class EmpiricalShrinkageCalibrator:
    def __init__(self, table: pd.DataFrame, state_table: pd.DataFrame, horizon_table: pd.DataFrame, alpha: float):
        self.table = table
        self.state_table = state_table
        self.horizon_table = horizon_table
        self.alpha = float(alpha)
        self.horizon_lookup = self._build_lookup(horizon_table, ["exit_type", "horizon_days"])
        self.state_lookup = self._build_lookup(state_table, ["exit_type", "horizon_days", "state_label"])
        self.bucket_lookup = self._build_lookup(table, ["exit_type", "horizon_days", "state_label", "age_bucket", "raw_score_bucket"])

    @staticmethod
    def _normalize_key_value(value: object) -> object:
        if pd.isna(value):
            return "nan"
        if isinstance(value, (int, np.integer)):
            return int(value)
        if isinstance(value, (float, np.floating)) and float(value).is_integer():
            return int(value)
        return str(value)

    @classmethod
    def _key(cls, values: list[object]) -> tuple[object, ...]:
        return tuple(cls._normalize_key_value(value) for value in values)

    @classmethod
    def _build_lookup(cls, table: pd.DataFrame, cols: list[str]) -> dict[tuple[object, ...], tuple[float, int]]:
        if table.empty:
            return {}
        lookup: dict[tuple[object, ...], tuple[float, int]] = {}
        for row in table.to_dict("records"):
            key = cls._key([row.get(col) for col in cols])
            lookup[key] = (float(row.get("empirical_rate", np.nan)), int(row.get("sample_count", 0)))
        return lookup

    @classmethod
    def fit(cls, train: pd.DataFrame, alpha: float, min_bucket_count: int) -> "EmpiricalShrinkageCalibrator":
        def rate(group_cols: list[str]) -> pd.DataFrame:
            if train.empty:
                return pd.DataFrame()
            return (
                train.groupby(group_cols, observed=True)
                .agg(sample_count=("actual_exit", "size"), empirical_rate=("actual_exit", "mean"), mean_raw=("raw_exit_score", "mean"))
                .reset_index()
            )

        base_cols = ["exit_type", "horizon_days"]
        horizon_table = rate(base_cols)
        state_table = rate(["exit_type", "horizon_days", "state_label"])
        bucket_table = rate(["exit_type", "horizon_days", "state_label", "age_bucket", "raw_score_bucket"])
        if not bucket_table.empty:
            bucket_table = bucket_table[bucket_table["sample_count"] >= max(1, min_bucket_count)].copy()
        return cls(bucket_table, state_table, horizon_table, alpha)

    def _lookup_global(self, exit_type: object, horizon_days: object, raw_score: object) -> float:
        key = self._key([exit_type, horizon_days])
        value = self.horizon_lookup.get(key)
        if value is None:
            return float(raw_score) if pd.notna(raw_score) else np.nan
        return value[0]

    def _lookup_state(self, exit_type: object, horizon_days: object, state_label: object, raw_score: object) -> tuple[float, int]:
        key = self._key([exit_type, horizon_days, state_label])
        value = self.state_lookup.get(key)
        if value is None:
            return self._lookup_global(exit_type, horizon_days, raw_score), 0
        return value

    def predict(self, df: pd.DataFrame) -> pd.Series:
        preds: list[float] = []
        cols = ["exit_type", "horizon_days", "state_label", "age_bucket", "raw_score_bucket", "raw_exit_score"]
        for row in df[cols].itertuples(index=False):
            exit_type = row.exit_type
            horizon_days = row.horizon_days
            state_label = row.state_label
            age = row.age_bucket
            score_bucket = row.raw_score_bucket
            raw_score = row.raw_exit_score
            p_global = self._lookup_global(exit_type, horizon_days, raw_score)
            p_state, _ = self._lookup_state(exit_type, horizon_days, state_label, raw_score)
            p_bucket = np.nan
            n_bucket = 0
            bucket_value = self.bucket_lookup.get(self._key([exit_type, horizon_days, state_label, age, score_bucket]))
            if bucket_value is not None:
                p_bucket, n_bucket = bucket_value
            if pd.notna(p_bucket) and n_bucket > 0:
                pred = (n_bucket * p_bucket + self.alpha * p_state) / (n_bucket + self.alpha)
            else:
                pred = p_state if pd.notna(p_state) else p_global
            preds.append(float(np.clip(pred, 0.0, 1.0)))
        return pd.Series(preds, index=df.index)


class LogisticLifecycleCalibrator:
    def __init__(self, models: dict[tuple[str, int], tuple[LogisticRegression, list[str]]]):
        self.models = models

    @staticmethod
    def _design(df: pd.DataFrame) -> pd.DataFrame:
        base = pd.DataFrame(
            {
                "raw_exit_score": pd.to_numeric(df["raw_exit_score"], errors="coerce"),
                "model_state_age_days": pd.to_numeric(df["model_state_age_days"], errors="coerce"),
                "label_state_age_days": pd.to_numeric(df["label_state_age_days"], errors="coerce"),
                "duration_percentile": pd.to_numeric(df.get("duration_percentile", 0.0), errors="coerce"),
                "expected_remaining_days": pd.to_numeric(df.get("expected_remaining_days", 0.0), errors="coerce"),
            },
            index=df.index,
        ).fillna(0.0)
        cats = pd.get_dummies(df[["state_label", "age_bucket"]].astype(str), prefix=["state", "age"])
        return pd.concat([base, cats], axis=1)

    @classmethod
    def fit(cls, train: pd.DataFrame, min_sample: int = 1000) -> "LogisticLifecycleCalibrator":
        models: dict[tuple[str, int], tuple[LogisticRegression, list[str]]] = {}
        for (exit_type, horizon), group in train.groupby(["exit_type", "horizon_days"], observed=True):
            y = group["actual_exit"].astype(int)
            if len(group) < min_sample or y.nunique() < 2:
                continue
            x = cls._design(group)
            model = LogisticRegression(max_iter=300, C=1.0)
            model.fit(x, y)
            models[(str(exit_type), int(horizon))] = (model, list(x.columns))
        return cls(models)

    def predict(self, df: pd.DataFrame) -> pd.Series:
        out = pd.Series(np.nan, index=df.index, dtype=float)
        for (exit_type, horizon), group in df.groupby(["exit_type", "horizon_days"], observed=True):
            key = (str(exit_type), int(horizon))
            if key not in self.models:
                continue
            model, cols = self.models[key]
            x = self._design(group)
            x = x.reindex(columns=cols, fill_value=0.0)
            out.loc[group.index] = model.predict_proba(x)[:, 1]
        return out.clip(0.0, 1.0)


class IsotonicLifecycleCalibrator:
    def __init__(self, models: dict[tuple[str, int, str], IsotonicRegression]):
        self.models = models

    @classmethod
    def fit(cls, train: pd.DataFrame, min_sample: int = 1000) -> "IsotonicLifecycleCalibrator":
        models: dict[tuple[str, int, str], IsotonicRegression] = {}
        for (exit_type, horizon, label), group in train.groupby(["exit_type", "horizon_days", "state_label"], observed=True):
            y = group["actual_exit"].astype(int)
            if len(group) < min_sample or y.nunique() < 2 or group["raw_exit_score"].nunique() < 3:
                continue
            model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            model.fit(group["raw_exit_score"].astype(float), y)
            models[(str(exit_type), int(horizon), str(label))] = model
        return cls(models)

    def predict(self, df: pd.DataFrame) -> pd.Series:
        out = pd.Series(np.nan, index=df.index, dtype=float)
        for (exit_type, horizon, label), group in df.groupby(["exit_type", "horizon_days", "state_label"], observed=True):
            key = (str(exit_type), int(horizon), str(label))
            if key not in self.models:
                continue
            out.loc[group.index] = self.models[key].predict(group["raw_exit_score"].astype(float))
        return out.clip(0.0, 1.0)


def _fit_method_calibrators(train: pd.DataFrame, methods: tuple[str, ...], config: CalibrationConfig) -> dict[str, object]:
    fitted: dict[str, object] = {}
    if "empirical_shrinkage" in methods:
        fitted["empirical_shrinkage"] = EmpiricalShrinkageCalibrator.fit(train, config.shrinkage_alpha, config.min_bucket_count)
    if "logistic" in methods:
        fitted["logistic"] = LogisticLifecycleCalibrator.fit(train, config.min_sample_per_state_horizon)
    if "isotonic" in methods:
        fitted["isotonic"] = IsotonicLifecycleCalibrator.fit(train, config.min_sample_per_state_horizon)
    return fitted


def _method_predictions(
    eval_df: pd.DataFrame,
    methods: tuple[str, ...],
    fitted: dict[str, object],
) -> pd.DataFrame:
    out = eval_df.copy()
    out["raw"] = out["raw_exit_score"].astype(float)
    if "empirical_shrinkage" in methods:
        empirical = fitted.get("empirical_shrinkage")
        if isinstance(empirical, EmpiricalShrinkageCalibrator):
            out["empirical_shrinkage"] = empirical.predict(out)
    if "logistic" in methods:
        logistic = fitted.get("logistic")
        if isinstance(logistic, LogisticLifecycleCalibrator):
            out["logistic"] = logistic.predict(out)
    if "isotonic" in methods:
        isotonic = fitted.get("isotonic")
        if isinstance(isotonic, IsotonicLifecycleCalibrator):
            out["isotonic"] = isotonic.predict(out)
    return out


def evaluate_calibration(
    split_df: pd.DataFrame,
    methods: tuple[str, ...] = ("empirical_shrinkage", "logistic", "isotonic"),
    config: CalibrationConfig = CalibrationConfig(),
) -> dict[str, pd.DataFrame]:
    if split_df.empty:
        empty = pd.DataFrame()
        return {"summary": empty, "buckets": empty, "selected_status": empty, "scored": empty, "splits": empty}
    train = split_df[split_df["split"].eq("train")].copy()
    fitted = _fit_method_calibrators(train, methods, config)
    scored_parts: list[pd.DataFrame] = []
    for split_name in ["train", "validation", "test"]:
        part = split_df[split_df["split"].eq(split_name)].copy()
        if part.empty:
            continue
        scored = _method_predictions(part, methods, fitted)
        scored_parts.append(scored)
    scored_all = pd.concat(scored_parts, ignore_index=True) if scored_parts else pd.DataFrame()

    metric_rows: list[dict[str, object]] = []
    bucket_rows: list[dict[str, object]] = []
    candidate_methods = ["raw", *[m for m in methods if m in scored_all.columns]]
    train_rates = (
        train.groupby(["exit_type", "horizon_days"], observed=True)["actual_exit"].mean().reset_index().rename(columns={"actual_exit": "baseline_rate"})
    )
    for (split_name, exit_type, horizon, label), group in scored_all.groupby(["split", "exit_type", "horizon_days", "state_label"], observed=True):
        base_match = train_rates[(train_rates["exit_type"].astype(str).eq(str(exit_type))) & (train_rates["horizon_days"].astype(int).eq(int(horizon)))]
        baseline_rate = float(base_match.iloc[0]["baseline_rate"]) if not base_match.empty else float(train["actual_exit"].mean())
        for method in candidate_methods:
            if method not in group.columns or group[method].isna().all():
                continue
            metrics = _metrics(group, method, method, baseline_rate)
            metrics.update({"split": split_name, "exit_type": exit_type, "horizon_days": int(horizon), "state_label": label})
            metric_rows.append(metrics)
            buckets = _bucket_stats(group["actual_exit"], group[method], strategy="equal_frequency")
            if not buckets.empty:
                buckets["split"] = split_name
                buckets["exit_type"] = exit_type
                buckets["horizon_days"] = int(horizon)
                buckets["state_label"] = label
                buckets["method"] = method
                bucket_rows.extend(buckets.to_dict("records"))
    summary = pd.DataFrame(metric_rows)
    buckets = pd.DataFrame(bucket_rows)
    selected = select_probability_status(summary, config)
    scored = scored_all.merge(
        selected[["state_label", "horizon_days", "exit_type", "selected_method", "status"]],
        on=["state_label", "horizon_days", "exit_type"],
        how="left",
    )
    scored["selected_exit_value"] = np.nan
    for method in scored["selected_method"].dropna().unique():
        if method in scored.columns:
            mask = scored["selected_method"].eq(method)
            scored.loc[mask, "selected_exit_value"] = scored.loc[mask, method]
    return {"summary": summary, "buckets": buckets, "selected_status": selected, "scored": scored, "splits": split_df}


def select_probability_status(summary: pd.DataFrame, config: CalibrationConfig = CalibrationConfig()) -> pd.DataFrame:
    if summary.empty:
        return pd.DataFrame()
    validation = summary[summary["split"].eq("validation")].copy()
    rows: list[dict[str, object]] = []
    for (label, horizon, exit_type), group in validation.groupby(["state_label", "horizon_days", "exit_type"], observed=True):
        raw = group[group["method"].eq("raw")]
        if raw.empty:
            continue
        raw_row = raw.iloc[0]
        sample = int(raw_row["sample_count"])
        positives = int(raw_row["positive_events"])
        raw_brier = float(raw_row["brier_score"])
        raw_ece = float(raw_row["ece_equal_frequency"])
        raw_mce = float(raw_row["mce"])
        raw_monotonic = bool(raw_row["bucket_monotonicity_passed"])
        raw_spearman = float(raw_row["spearman_pred_vs_realized_bucket_rate"]) if pd.notna(raw_row["spearman_pred_vs_realized_bucket_rate"]) else np.nan
        if sample < config.min_sample_per_state_horizon or positives < config.min_positive_events:
            status = "insufficient_sample"
            selected_method = "none"
            reason = f"sample={sample}, positive_events={positives}"
            selected = raw_row
        else:
            calibrated = group[~group["method"].eq("raw")].dropna(subset=["brier_score"])
            selected = calibrated.sort_values(["brier_score", "ece_equal_frequency"]).iloc[0] if not calibrated.empty else raw_row
            selected_method = str(selected["method"])
            selected_brier = float(selected["brier_score"])
            selected_ece = float(selected["ece_equal_frequency"])
            selected_mce = float(selected["mce"])
            selected_monotonic = bool(selected["bucket_monotonicity_passed"])
            if (
                selected_method != "raw"
                and selected_brier <= raw_brier - config.min_delta_brier
                and selected_ece <= max(raw_ece, config.max_ece_for_probability)
                and selected_mce <= config.max_mce_for_probability
                and selected_monotonic
            ):
                status = "usable_probability"
                reason = f"{selected_method} improves raw brier by {raw_brier - selected_brier:.4f}"
            elif raw_monotonic and raw_ece <= config.max_ece_for_probability and raw_mce <= config.max_mce_for_probability:
                status = "raw_only"
                selected_method = "raw"
                selected = raw_row
                reason = "raw score is calibrated enough; calibrated method not better"
            elif raw_monotonic or (pd.notna(raw_spearman) and raw_spearman >= 0.3):
                status = "ordinal_only"
                selected_method = "raw"
                selected = raw_row
                reason = "raw score has ordering value but not probability quality"
            else:
                status = "invalid"
                selected_method = "none"
                reason = "raw and calibrated probabilities fail calibration gates"
        rows.append(
            {
                "state_label": label,
                "horizon_days": int(horizon),
                "exit_type": exit_type,
                "selected_method": selected_method,
                "status": status,
                "sample_count": sample,
                "positive_events": positives,
                "raw_brier": raw_brier,
                "selected_brier": float(selected["brier_score"]) if selected_method != "none" else np.nan,
                "raw_ece": raw_ece,
                "selected_ece": float(selected["ece_equal_frequency"]) if selected_method != "none" else np.nan,
                "raw_mce": raw_mce,
                "selected_mce": float(selected["mce"]) if selected_method != "none" else np.nan,
                "bucket_monotonicity_passed": bool(selected["bucket_monotonicity_passed"]) if selected_method != "none" else False,
                "reason": reason,
            }
        )
    return pd.DataFrame(rows)


def ui_readiness_matrix(selected_status: pd.DataFrame) -> pd.DataFrame:
    if selected_status.empty:
        return pd.DataFrame()
    out = selected_status.copy()
    out["probability_status"] = out["status"]
    out["can_show_numeric_probability"] = out["status"].eq("usable_probability") | out["status"].eq("raw_only")
    out["can_show_ordinal_score"] = out["status"].isin(["usable_probability", "raw_only", "ordinal_only"])
    out["must_hide"] = out["status"].isin(["invalid", "insufficient_sample"])
    out.loc[out["status"].eq("raw_only"), "can_show_numeric_probability"] = False
    return out[
        [
            "state_label",
            "horizon_days",
            "exit_type",
            "probability_status",
            "selected_method",
            "can_show_numeric_probability",
            "can_show_ordinal_score",
            "must_hide",
            "reason",
        ]
    ]


def write_calibration_outputs(results: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = results["summary"]
    buckets = results["buckets"]
    selected = results["selected_status"]
    scored = results["scored"]
    summary[summary["exit_type"].eq("state_id")].to_csv(output_dir / "state_id_exit_calibration_summary.csv", index=False)
    summary[summary["exit_type"].eq("display_label")].to_csv(output_dir / "display_label_exit_calibration_summary.csv", index=False)
    buckets[buckets["exit_type"].eq("state_id")].to_csv(output_dir / "state_id_exit_calibration_buckets.csv", index=False)
    buckets[buckets["exit_type"].eq("display_label")].to_csv(output_dir / "display_label_exit_calibration_buckets.csv", index=False)
    selected.to_csv(output_dir / "selected_exit_probability_status.csv", index=False)
    ui_readiness_matrix(selected).to_csv(output_dir / "ui_readiness_matrix.csv", index=False)
    daily_cols = [
        "run_id",
        "trade_date",
        "sector_code",
        "state_label",
        "horizon_days",
        "exit_type",
        "raw_exit_score",
        "selected_method",
        "status",
        "selected_exit_value",
        "actual_exit_within_h",
        "is_right_censored_for_horizon",
        "split",
    ]
    scored[[c for c in daily_cols if c in scored.columns]].to_csv(output_dir / "selected_exit_probability_daily.csv", index=False)
    results["splits"].to_csv(output_dir / "calibration_splits.csv", index=False)
    (output_dir / "config.json").write_text(json.dumps(asdict(CalibrationConfig()), ensure_ascii=False, indent=2), encoding="utf-8")


def validate_lifecycle_calibration(
    targets: pd.DataFrame,
    methods: tuple[str, ...] = ("empirical_shrinkage", "logistic", "isotonic"),
    config: CalibrationConfig = CalibrationConfig(),
) -> dict[str, pd.DataFrame]:
    split_df = time_split_targets(targets, config.time_split)
    return evaluate_calibration(split_df, methods, config)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate HSMM lifecycle exit probability")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--exit-types", default="state_id,display_label")
    parser.add_argument("--methods", default="empirical_shrinkage,logistic,isotonic")
    parser.add_argument("--time-split", default="0.6,0.2,0.2")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    split = tuple(float(x) for x in args.time_split.split(","))
    config = CalibrationConfig(time_split=split)  # type: ignore[arg-type]
    storage = DuckDBStorage(args.db)
    states = read_hsmm_states(storage, args.run_id)
    episodes = read_hsmm_episodes(storage, args.run_id)
    targets = build_exit_targets(states, episodes, parse_horizons(args.horizons), parse_exit_types(args.exit_types))
    results = validate_lifecycle_calibration(targets, tuple(x.strip() for x in args.methods.split(",") if x.strip()), config)
    write_calibration_outputs(results, Path(args.output))
    print(f"calibration_rows: {len(results['summary'])}")
    print(f"output_dir: {args.output}")


if __name__ == "__main__":
    main()
