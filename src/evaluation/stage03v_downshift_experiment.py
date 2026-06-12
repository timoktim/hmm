"""Stage03V RERUN1 three-arm downshift experiment.

The experiment is a historical-development research simulation only. It
recomputes validation-fold scores in memory and writes only aggregate metrics
plus a capped exposure sample. It does not fetch data, write DuckDB tables,
consume prospective holdout rows, or emit trading recommendations.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_baseline_diagnostics import (
    BASELINE_DEFINITIONS,
    build_price_baseline_features,
    build_target_rows_for_trade_dates,
    compute_empirical_baseline_scores,
    read_ohlcv_inputs,
    slice_specs_from_target_support,
)
from src.evaluation.stage03v_calibration_readiness import (
    apply_calibrator,
    default_policy as calibration_default_policy,
    fit_calibrator,
    split_calibration_evaluation_rows,
)
from src.evaluation.stage03v_logistic_hazard import (
    MODEL_FEATURE_COLUMNS,
    MODEL_VARIANT,
    _prepare_feature_join,
    default_policy as logistic_default_policy,
    fit_logistic_model,
    split_fold_rows,
)
from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)
from src.evaluation.stage03v_vol_scaled_threshold_sanity import shifted_price_features


INDEX_ID = "STAGE03V-RERUN1-v1"
REPORT_VERSION = "stage03v_rerun1_downshift_experiment_v1"
STAGE_ID = "stage03v"
PRIMARY_PAIR = "model_minus_baseline"
PRIMARY_METRICS = ["max_drawdown", "cvar_95", "realized_volatility"]
DEFAULT_BOOTSTRAP_ITERATIONS = 300
DEFAULT_RANDOM_SEED = 20260612
DEFAULT_EXPOSURE_SAMPLE_ROWS = 5000

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_LOGISTIC_HAZARD = ROOT / "reports" / "stage03v" / "logistic_hazard_report.json"
DEFAULT_CALIBRATION_READINESS = ROOT / "reports" / "stage03v" / "calibration_readiness_report.json"
DEFAULT_READINESS_MATRIX = ROOT / "reports" / "stage03v" / "downside_readiness_matrix.csv"
DEFAULT_BASELINE_SLICE_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_slice_metrics.csv"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan_v2.json"
DEFAULT_TRIAL_ACCOUNTING = ROOT / "reports" / "stage03v" / "validation_trial_accounting.json"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "downshift_experiment_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "downshift_experiment_report.json"
DEFAULT_ARM_METRICS = ROOT / "reports" / "stage03v" / "downshift_experiment_arm_metrics.csv"
DEFAULT_DAILY_EXPOSURE_SAMPLE = ROOT / "reports" / "stage03v" / "downshift_experiment_daily_exposure_sample.csv"

ARM_METRIC_COLUMNS = [
    "slice_id",
    "asof_mode",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "baseline_name",
    "arm",
    "daily_return_count",
    "entity_day_count",
    "mean_exposure",
    "max_drawdown",
    "cvar_95",
    "realized_volatility",
    "total_return",
    "missed_upside_cost",
    "turnover",
]
PAIR_METRIC_COLUMNS = [
    "slice_id",
    "asof_mode",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "calibration_method",
    "baseline_name",
    "arm_pair",
    "metric",
    "delta",
    "confidence_interval_low",
    "confidence_interval_high",
    "bootstrap_iterations",
    "ci_status",
]
EXPOSURE_SAMPLE_COLUMNS = [
    "slice_id",
    "entity_id",
    "decision_trade_date",
    "apply_trade_date",
    "realized_open_to_open_return",
    "baseline_score",
    "model_score",
    "baseline_bucket",
    "model_bucket",
    "arm_no_downshift_exposure",
    "arm_baseline_driven_exposure",
    "arm_model_driven_exposure",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_definition_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "full_score_matrix_committed": "no",
    "model_family_changed": "no",
    "readiness_threshold_tuned": "no",
    "ordinal_bucket_tuned_after_first_run": "no",
    "exposure_rule_tuned_after_first_run": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
    "trading_or_decision_output": "no",
    "research_only_simulation": "yes",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows), columns=list(columns))
    frame.to_csv(target, index=False)
    return int(len(frame))


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _normalise_date(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.normalize()


def _slice_key(row: Mapping[str, Any]) -> tuple[str, int, str, float, str, str]:
    return (
        str(row.get("asof_mode", "close_t_minus_1")),
        int(row.get("horizon")),
        str(row.get("threshold_type", "fixed")),
        float(row.get("threshold_value")),
        str(row.get("target_usage", "eligible")),
        str(row.get("calibration_method", "platt_logistic_calibration")),
    )


def _slice_id_from_parts(
    *,
    asof_mode: str,
    horizon: int,
    threshold_type: str,
    threshold_value: float,
    target_usage: str,
    calibration_method: str,
) -> str:
    return f"{asof_mode}:h{horizon}:{threshold_type}:{threshold_value:.4f}:{target_usage}:{calibration_method}"


def _slice_id(row: Mapping[str, Any]) -> str:
    asof_mode, horizon, threshold_type, threshold_value, target_usage, calibration_method = _slice_key(row)
    return _slice_id_from_parts(
        asof_mode=asof_mode,
        horizon=horizon,
        threshold_type=threshold_type,
        threshold_value=threshold_value,
        target_usage=target_usage,
        calibration_method=calibration_method,
    )


def _readiness_candidates(readiness_matrix: Path | str) -> list[dict[str, Any]]:
    frame = pd.read_csv(readiness_matrix)
    if frame.empty:
        return []
    allowed = {"usable_probability_candidate", "ordinal_only_candidate"}
    work = frame[frame["readiness_category"].astype(str).isin(allowed)].copy()
    work = work[~work["calibration_method"].astype(str).eq("identity_uncalibrated_reference")].copy()
    rows = work.to_dict(orient="records")
    rows.sort(
        key=lambda row: (
            str(row.get("readiness_category")),
            str(row.get("asof_mode")),
            int(row.get("horizon")),
            float(row.get("threshold_value")),
            str(row.get("calibration_method")),
        )
    )
    return rows


def _baseline_definition(name: str) -> Mapping[str, Any] | None:
    for definition in BASELINE_DEFINITIONS:
        if str(definition.get("name")) == str(name):
            return definition
    return None


def select_strongest_baseline(
    baseline_slice_metrics: Path | str,
    *,
    horizon: int,
    threshold_type: str,
    threshold_value: float,
    target_usage: str,
) -> dict[str, Any]:
    try:
        frame = pd.read_csv(baseline_slice_metrics)
    except FileNotFoundError:
        frame = pd.DataFrame()
    if not frame.empty:
        work = frame[
            frame["horizon"].astype(int).eq(int(horizon))
            & frame["threshold_type"].astype(str).eq(str(threshold_type))
            & frame["threshold_value"].astype(float).eq(float(threshold_value))
            & frame["target_usage"].astype(str).eq(str(target_usage))
        ].copy()
        if not work.empty:
            work["_rank_metric"] = pd.to_numeric(work.get("roc_auc"), errors="coerce")
            if work["_rank_metric"].dropna().empty:
                work["_rank_metric"] = pd.to_numeric(work.get("average_precision"), errors="coerce")
            work = work[pd.to_numeric(work["_rank_metric"], errors="coerce").notna()].copy()
            if not work.empty:
                best = work.sort_values("_rank_metric", ascending=False).iloc[0].to_dict()
                return {
                    "baseline_name": str(best.get("baseline_name")),
                    "baseline_family": str(best.get("baseline_family")),
                    "selection_metric": "roc_auc_or_average_precision",
                    "selection_metric_value": _as_float(best.get("_rank_metric")),
                    "selection_source": _safe_path(baseline_slice_metrics),
                }
    return {
        "baseline_name": "rolling_close_to_close_vol_20",
        "baseline_family": "realized_volatility",
        "selection_metric": "fallback",
        "selection_metric_value": None,
        "selection_source": _safe_path(baseline_slice_metrics),
    }


def _next_open_returns(ohlcv: pd.DataFrame) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame(columns=["entity_id", "trade_date", "apply_trade_date", "realized_open_to_open_return"])
    data = ohlcv.copy()
    data["entity_id"] = data["entity_id"].astype(str)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    if "open" not in data.columns or pd.to_numeric(data["open"], errors="coerce").notna().sum() == 0:
        data["open"] = data["close"]
    data["open"] = pd.to_numeric(data["open"], errors="coerce")
    rows: list[pd.DataFrame] = []
    for _, group in data.sort_values(["entity_id", "trade_date"]).groupby("entity_id", sort=False):
        g = group.copy()
        g["apply_trade_date"] = g["trade_date"].shift(-1)
        entry_open = g["open"].shift(-1)
        exit_open = g["open"].shift(-2)
        g["realized_open_to_open_return"] = exit_open / entry_open - 1.0
        rows.append(g[["entity_id", "trade_date", "apply_trade_date", "realized_open_to_open_return"]])
    result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    result["apply_trade_date"] = pd.to_datetime(result["apply_trade_date"], errors="coerce").dt.normalize()
    result = result[pd.to_numeric(result["realized_open_to_open_return"], errors="coerce").notna()].copy()
    return result


def _baseline_scores_for_rows(
    validation_rows: pd.DataFrame,
    train_rows: pd.DataFrame,
    baseline_feature_frame: pd.DataFrame,
    *,
    baseline_name: str,
) -> pd.Series:
    definition = _baseline_definition(baseline_name)
    if definition is None:
        return pd.Series(np.nan, index=validation_rows.index, dtype=float)
    if definition.get("kind") == "empirical":
        scores = compute_empirical_baseline_scores(validation_rows, train_rows)
        return pd.to_numeric(scores.get(baseline_name), errors="coerce")
    features = baseline_feature_frame.copy()
    if features.empty or baseline_name not in features.columns:
        return pd.Series(np.nan, index=validation_rows.index, dtype=float)
    features["entity_id"] = features["entity_id"].astype(str)
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce").dt.normalize()
    base = validation_rows.reset_index(drop=True).copy()
    base["entity_id"] = base["entity_id"].astype(str)
    base["trade_date"] = pd.to_datetime(base["trade_date"], errors="coerce").dt.normalize()
    baseline_source_column = f"{baseline_name}__baseline_source"
    merged = base.merge(
        features[["entity_id", "trade_date", baseline_name]],
        on=["entity_id", "trade_date"],
        how="left",
        suffixes=("", "__baseline_source"),
    )
    score_column = baseline_source_column if baseline_source_column in merged.columns else baseline_name
    return pd.to_numeric(merged[score_column], errors="coerce")


def _candidate_score_rows(
    *,
    candidates: Sequence[Mapping[str, Any]],
    target_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    baseline_feature_frames: Mapping[str, pd.DataFrame],
    fold_plan: Mapping[str, Any],
    baseline_slice_metrics: Path | str,
    returns: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    if not candidates:
        return pd.DataFrame(), []
    candidate_by_key = {_slice_key(row): dict(row) for row in candidates}
    logistic_policy = logistic_default_policy()
    calibration_policy = calibration_default_policy()
    score_frames: list[pd.DataFrame] = []
    baseline_selection_rows: list[dict[str, Any]] = []
    baseline_selection_by_slice: dict[tuple[int, str, float, str], dict[str, Any]] = {}
    for fold in fold_plan.get("folds", []):
        fold_id = str(fold.get("fold_id", "fold_unknown"))
        split = split_fold_rows(target_rows, fold)
        train_rows = split["train_rows"]
        validation_rows = split["validation_rows"]
        if validation_rows.empty:
            continue
        for asof_mode in sorted({key[0] for key in candidate_by_key}):
            model_features = feature_frames.get(asof_mode, pd.DataFrame())
            baseline_features = baseline_feature_frames.get(asof_mode, pd.DataFrame())
            train_featured = _prepare_feature_join(train_rows, model_features, MODEL_FEATURE_COLUMNS)
            validation_featured = _prepare_feature_join(validation_rows, model_features, MODEL_FEATURE_COLUMNS)
            for slice_key, val_group in validation_featured.groupby(
                ["horizon", "threshold_type", "threshold_value", "target_usage"],
                sort=False,
                dropna=False,
            ):
                if not isinstance(slice_key, tuple):
                    slice_key = (slice_key,)
                horizon, threshold_type, threshold_value, target_usage = (
                    int(slice_key[0]),
                    str(slice_key[1]),
                    float(slice_key[2]),
                    str(slice_key[3]),
                )
                candidate_methods = [
                    key[5]
                    for key in candidate_by_key
                    if key[:5] == (asof_mode, horizon, threshold_type, threshold_value, target_usage)
                ]
                if not candidate_methods:
                    continue
                train_group = train_featured[
                    train_featured["horizon"].astype(int).eq(horizon)
                    & train_featured["threshold_type"].astype(str).eq(threshold_type)
                    & train_featured["threshold_value"].astype(float).eq(threshold_value)
                    & train_featured["target_usage"].astype(str).eq(target_usage)
                ].copy()
                result = fit_logistic_model(train_group, val_group.copy(), MODEL_FEATURE_COLUMNS, logistic_policy)
                if result["status"] != "fitted":
                    continue
                scored_validation = val_group.copy().reset_index(drop=True)
                scored_validation["raw_score"] = result["scores"]
                split_eval = split_calibration_evaluation_rows(
                    scored_validation,
                    calibration_fraction=float(calibration_policy.get("validation_calibration_fraction", 0.5)),
                )
                calibration_rows = split_eval["calibration_rows"]
                evaluation_rows = split_eval["evaluation_rows"]
                if evaluation_rows.empty:
                    continue
                baseline_key = (horizon, threshold_type, threshold_value, target_usage)
                if baseline_key not in baseline_selection_by_slice:
                    baseline_selection_by_slice[baseline_key] = select_strongest_baseline(
                        baseline_slice_metrics,
                        horizon=horizon,
                        threshold_type=threshold_type,
                        threshold_value=threshold_value,
                        target_usage=target_usage,
                    )
                    baseline_selection_rows.append(
                        {
                            **baseline_selection_by_slice[baseline_key],
                            "horizon": horizon,
                            "threshold_type": threshold_type,
                            "threshold_value": threshold_value,
                            "target_usage": target_usage,
                        }
                    )
                baseline_name = str(baseline_selection_by_slice[baseline_key]["baseline_name"])
                baseline_scores = _baseline_scores_for_rows(
                    evaluation_rows,
                    train_rows,
                    baseline_features,
                    baseline_name=baseline_name,
                )
                for method in candidate_methods:
                    fit = fit_calibrator(calibration_rows, method=method, policy=calibration_policy)
                    if fit["status"] == "skipped":
                        continue
                    scored = evaluation_rows.copy().reset_index(drop=True)
                    scored["model_score"] = apply_calibrator(scored, method=method, calibrator=fit.get("calibrator"))
                    scored["baseline_score"] = baseline_scores.reset_index(drop=True)
                    scored["fold_id"] = fold_id
                    scored["asof_mode"] = asof_mode
                    scored["calibration_method"] = method
                    scored["baseline_name"] = baseline_name
                    scored["slice_id"] = _slice_id_from_parts(
                        asof_mode=asof_mode,
                        horizon=horizon,
                        threshold_type=threshold_type,
                        threshold_value=threshold_value,
                        target_usage=target_usage,
                        calibration_method=method,
                    )
                    score_frames.append(scored)
    if not score_frames:
        return pd.DataFrame(), baseline_selection_rows
    scores = pd.concat(score_frames, ignore_index=True)
    scores["trade_date"] = pd.to_datetime(scores["trade_date"], errors="coerce").dt.normalize()
    returns_work = returns.copy()
    returns_work["trade_date"] = pd.to_datetime(returns_work["trade_date"], errors="coerce").dt.normalize()
    scores = scores.merge(returns_work, on=["entity_id", "trade_date"], how="left")
    scores = scores[pd.to_numeric(scores["realized_open_to_open_return"], errors="coerce").notna()].copy()
    holdout = pd.Timestamp(HOLDOUT_START).normalize()
    scores = scores[
        pd.to_datetime(scores["trade_date"], errors="coerce").dt.normalize().lt(holdout)
        & pd.to_datetime(scores["apply_trade_date"], errors="coerce").dt.normalize().lt(holdout)
    ].copy()
    return scores, baseline_selection_rows


def _bucket_scores(score: pd.Series) -> tuple[pd.Series, dict[str, Any]]:
    numeric = pd.to_numeric(score, errors="coerce")
    valid = numeric.dropna()
    if valid.empty:
        buckets = pd.Series("low", index=score.index, dtype=object)
        return buckets, {"high_threshold": None, "extreme_threshold": None, "status": "no_scores"}
    high = float(valid.quantile(0.75))
    extreme = float(valid.quantile(0.90))
    buckets = pd.Series("low", index=score.index, dtype=object)
    buckets.loc[numeric.ge(high)] = "high"
    buckets.loc[numeric.ge(extreme)] = "extreme"
    return buckets, {"high_threshold": high, "extreme_threshold": extreme, "status": "pass"}


def exposure_from_bucket(bucket: Any) -> float:
    value = str(bucket)
    if value == "extreme":
        return 0.5
    if value == "high":
        return 0.75
    return 1.0


def _arm_daily_returns(rows: pd.DataFrame, exposure_column: str) -> pd.DataFrame:
    work = rows.copy()
    work["apply_trade_date"] = pd.to_datetime(work["apply_trade_date"], errors="coerce").dt.normalize()
    work["_arm_return"] = pd.to_numeric(work[exposure_column], errors="coerce") * pd.to_numeric(
        work["realized_open_to_open_return"], errors="coerce"
    )
    return (
        work.groupby("apply_trade_date", dropna=False)
        .agg(daily_return=("_arm_return", "mean"), mean_exposure=(exposure_column, "mean"), entity_count=("entity_id", "nunique"))
        .reset_index()
        .sort_values("apply_trade_date")
    )


def _max_drawdown(daily_returns: Sequence[float]) -> float | None:
    returns = np.asarray(daily_returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    if len(returns) == 0:
        return None
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    dd = 1.0 - equity / peak
    return float(np.max(dd)) if len(dd) else None


def _cvar_95(daily_returns: Sequence[float]) -> float | None:
    returns = np.asarray(daily_returns, dtype=float)
    returns = returns[np.isfinite(returns)]
    if len(returns) == 0:
        return None
    cutoff = np.quantile(returns, 0.05)
    tail = returns[returns <= cutoff]
    return float(-np.mean(tail)) if len(tail) else None


def _daily_metrics(daily: pd.DataFrame, *, no_downshift_daily: pd.DataFrame | None = None) -> dict[str, Any]:
    returns = pd.to_numeric(daily.get("daily_return"), errors="coerce").dropna().to_numpy(dtype=float)
    if len(returns) == 0:
        return {
            "daily_return_count": 0,
            "mean_exposure": None,
            "max_drawdown": None,
            "cvar_95": None,
            "realized_volatility": None,
            "total_return": None,
            "missed_upside_cost": None,
            "turnover": None,
        }
    missed = None
    if no_downshift_daily is not None and not no_downshift_daily.empty:
        merged = daily[["apply_trade_date", "daily_return"]].merge(
            no_downshift_daily[["apply_trade_date", "daily_return"]].rename(columns={"daily_return": "no_downshift_return"}),
            on="apply_trade_date",
            how="inner",
        )
        if not merged.empty:
            missed = float(np.maximum(merged["no_downshift_return"] - merged["daily_return"], 0.0).sum())
    exposures = pd.to_numeric(daily.get("mean_exposure"), errors="coerce").dropna()
    turnover = float(exposures.diff().abs().dropna().mean()) if len(exposures) > 1 else 0.0
    return {
        "daily_return_count": int(len(returns)),
        "mean_exposure": float(exposures.mean()) if len(exposures) else None,
        "max_drawdown": _max_drawdown(returns),
        "cvar_95": _cvar_95(returns),
        "realized_volatility": float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0,
        "total_return": float(np.prod(1.0 + returns) - 1.0),
        "missed_upside_cost": missed,
        "turnover": turnover,
    }


def _pair_delta(
    daily_left: pd.DataFrame,
    daily_right: pd.DataFrame,
    metric: str,
    *,
    bootstrap_iterations: int,
    rng: np.random.Generator,
) -> tuple[float | None, float | None, float | None, str]:
    merged = daily_left[["apply_trade_date", "daily_return"]].merge(
        daily_right[["apply_trade_date", "daily_return"]],
        on="apply_trade_date",
        how="inner",
        suffixes=("_left", "_right"),
    )
    if merged.empty:
        return None, None, None, "no_overlap"

    def metric_value(frame: pd.DataFrame, column: str) -> float | None:
        returns = pd.to_numeric(frame[column], errors="coerce").dropna().to_numpy(dtype=float)
        if metric == "max_drawdown":
            return _max_drawdown(returns)
        if metric == "cvar_95":
            return _cvar_95(returns)
        if metric == "realized_volatility":
            return float(np.std(returns, ddof=1)) if len(returns) > 1 else 0.0
        if metric == "total_return":
            return float(np.prod(1.0 + returns) - 1.0) if len(returns) else None
        if metric == "missed_upside_cost":
            return float(np.maximum(frame["daily_return_right"] - frame["daily_return_left"], 0.0).sum())
        if metric == "turnover":
            return None
        raise ValueError(f"unsupported metric: {metric}")

    left_value = metric_value(merged, "daily_return_left")
    right_value = metric_value(merged, "daily_return_right")
    delta = None if left_value is None or right_value is None else float(left_value - right_value)
    if len(merged) < 20 or bootstrap_iterations <= 0 or metric == "turnover":
        return delta, None, None, "insufficient_dates_for_ci"
    boot: list[float] = []
    n = len(merged)
    for _ in range(int(bootstrap_iterations)):
        sample = merged.iloc[rng.integers(0, n, size=n)].copy()
        left = metric_value(sample, "daily_return_left")
        right = metric_value(sample, "daily_return_right")
        if left is not None and right is not None and math.isfinite(float(left - right)):
            boot.append(float(left - right))
    if len(boot) < 20:
        return delta, None, None, "insufficient_bootstrap_samples"
    return delta, float(np.quantile(boot, 0.025)), float(np.quantile(boot, 0.975)), "pass"


def simulate_downshift_scores(
    scores: pd.DataFrame,
    *,
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    random_seed: int = DEFAULT_RANDOM_SEED,
    exposure_sample_rows: int = DEFAULT_EXPOSURE_SAMPLE_ROWS,
) -> dict[str, Any]:
    if scores.empty:
        return {"arm_metrics": [], "pair_metrics": [], "daily_exposure_sample": [], "bucket_thresholds": []}
    rng = np.random.default_rng(int(random_seed))
    arm_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    exposure_samples: list[dict[str, Any]] = []
    bucket_rows: list[dict[str, Any]] = []
    for slice_id, group in scores.groupby("slice_id", sort=False, dropna=False):
        work = group.copy().reset_index(drop=True)
        baseline_bucket, baseline_thresholds = _bucket_scores(work["baseline_score"])
        model_bucket, model_thresholds = _bucket_scores(work["model_score"])
        work["baseline_bucket"] = baseline_bucket
        work["model_bucket"] = model_bucket
        work["arm_no_downshift_exposure"] = 1.0
        work["arm_baseline_driven_exposure"] = work["baseline_bucket"].map(exposure_from_bucket).astype(float)
        work["arm_model_driven_exposure"] = work["model_bucket"].map(exposure_from_bucket).astype(float)
        first = work.iloc[0].to_dict()
        prefix = {
            "slice_id": str(slice_id),
            "asof_mode": first.get("asof_mode"),
            "horizon": int(first.get("horizon")),
            "threshold_type": first.get("threshold_type"),
            "threshold_value": float(first.get("threshold_value")),
            "target_usage": first.get("target_usage"),
            "calibration_method": first.get("calibration_method"),
            "baseline_name": first.get("baseline_name"),
        }
        bucket_rows.append(
            {
                **prefix,
                "baseline_high_threshold": baseline_thresholds.get("high_threshold"),
                "baseline_extreme_threshold": baseline_thresholds.get("extreme_threshold"),
                "model_high_threshold": model_thresholds.get("high_threshold"),
                "model_extreme_threshold": model_thresholds.get("extreme_threshold"),
                "bucket_source": "pre_evaluation_score_quantiles_q75_q90",
                "exposure_rule": "extreme=0.5, high=0.75, otherwise=1.0",
            }
        )
        daily_by_arm = {
            "arm_no_downshift": _arm_daily_returns(work, "arm_no_downshift_exposure"),
            "arm_baseline_driven": _arm_daily_returns(work, "arm_baseline_driven_exposure"),
            "arm_model_driven": _arm_daily_returns(work, "arm_model_driven_exposure"),
        }
        no_daily = daily_by_arm["arm_no_downshift"]
        for arm, daily in daily_by_arm.items():
            metrics = _daily_metrics(daily, no_downshift_daily=None if arm == "arm_no_downshift" else no_daily)
            arm_rows.append({**prefix, "arm": arm, "entity_day_count": int(len(work)), **metrics})
        pair_specs = [
            ("model_minus_baseline", "arm_model_driven", "arm_baseline_driven"),
            ("model_minus_no_downshift", "arm_model_driven", "arm_no_downshift"),
            ("baseline_minus_no_downshift", "arm_baseline_driven", "arm_no_downshift"),
        ]
        for pair_name, left_arm, right_arm in pair_specs:
            for metric in ["max_drawdown", "cvar_95", "realized_volatility", "total_return", "missed_upside_cost"]:
                delta, low, high, ci_status = _pair_delta(
                    daily_by_arm[left_arm],
                    daily_by_arm[right_arm],
                    metric,
                    bootstrap_iterations=bootstrap_iterations,
                    rng=rng,
                )
                pair_rows.append(
                    {
                        **prefix,
                        "arm_pair": pair_name,
                        "metric": metric,
                        "delta": delta,
                        "confidence_interval_low": low,
                        "confidence_interval_high": high,
                        "bootstrap_iterations": int(bootstrap_iterations),
                        "ci_status": ci_status,
                    }
                )
        if len(exposure_samples) < int(exposure_sample_rows):
            take = work.head(int(exposure_sample_rows) - len(exposure_samples)).copy()
            take = take.rename(
                columns={
                    "trade_date": "decision_trade_date",
                    "realized_open_to_open_return": "realized_open_to_open_return",
                }
            )
            for row in take[EXPOSURE_SAMPLE_COLUMNS].to_dict(orient="records"):
                exposure_samples.append(row)
    return {
        "arm_metrics": arm_rows,
        "pair_metrics": pair_rows,
        "daily_exposure_sample": exposure_samples,
        "bucket_thresholds": bucket_rows,
    }


def _holdout_consumption_count(*docs: Mapping[str, Any]) -> int:
    keys = [
        "prospective_holdout_rows_evaluated",
        "prospective_holdout_score_count",
        "prospective_holdout_metric_count",
        "holdout_rows_used_for_calibration_count",
        "holdout_rows_used_for_evaluation_count",
        "holdout_rows_validated_count",
    ]
    total = 0
    for doc in docs:
        for key in keys:
            value = doc.get(key)
            if value is not None:
                total += int(value or 0)
        for nested_key in ["leakage_violation_counts", "calibration_boundary_violation_counts"]:
            nested = doc.get(nested_key, {})
            if isinstance(nested, Mapping):
                for key in keys:
                    if key in nested:
                        total += int(nested.get(key) or 0)
    return int(total)


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V RERUN1 Downshift Experiment",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- fold_plan_path: {report.get('fold_plan_path')}",
        f"- validation_entity_day_count: {report.get('validation_entity_day_count')}",
        f"- candidate_slice_count: {report.get('candidate_slice_count')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- trial_accounting_invalidation_recorded: {report.get('trial_accounting_invalidation_recorded')}",
        "",
        "## Primary Model Minus Baseline Deltas",
        "",
        "| slice_id | metric | delta | ci_low | ci_high | ci_status |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in report.get("headline_model_minus_baseline_deltas", []):
        lines.append(
            "| {slice_id} | {metric} | {delta} | {confidence_interval_low} | {confidence_interval_high} | {ci_status} |".format(
                **row
            )
        )
    lines.extend(["", "## Boundary Flags", ""])
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Blocking Reasons", ""])
    reasons = report.get("blocking_reasons", [])
    if reasons:
        for reason in reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_downshift_experiment_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    logistic_hazard: Path | str = DEFAULT_LOGISTIC_HAZARD,
    calibration_readiness: Path | str = DEFAULT_CALIBRATION_READINESS,
    readiness_matrix: Path | str = DEFAULT_READINESS_MATRIX,
    baseline_slice_metrics: Path | str = DEFAULT_BASELINE_SLICE_METRICS,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    trial_accounting: Path | str = DEFAULT_TRIAL_ACCOUNTING,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    arm_metrics: Path | str = DEFAULT_ARM_METRICS,
    daily_exposure_sample: Path | str = DEFAULT_DAILY_EXPOSURE_SAMPLE,
    bootstrap_iterations: int = DEFAULT_BOOTSTRAP_ITERATIONS,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V RERUN1 downshift experiment is no-fetch only")
    resolved_db = resolve_v7_db_path(db_path)
    support = _load_json(target_support)
    logistic_report = _load_json(logistic_hazard)
    calibration_report = _load_json(calibration_readiness)
    fold_doc = _load_json(fold_plan)
    trial_doc = _load_json(trial_accounting)
    v7 = read_v7_inputs(resolved_db)
    candidates = _readiness_candidates(readiness_matrix)

    blocking: list[str] = []
    if v7.coverage.get("status") != "pass":
        blocking.extend(v7.coverage.get("blocking_reasons", ["v7_db_not_pass"]))
    for label, doc in [("wp4", logistic_report), ("wp5", calibration_report), ("fold_plan_v2", fold_doc)]:
        if doc.get("status") != "pass":
            blocking.append(f"{label}_status_not_pass")
    if fold_doc.get("index_id") != INDEX_ID:
        blocking.append("fold_plan_v2_index_id_mismatch")
    if trial_doc.get("trial_accounting_invalidation_recorded") != "yes":
        blocking.append("trial_accounting_invalidation_not_recorded")
    if _holdout_consumption_count(logistic_report, calibration_report, fold_doc) != 0:
        blocking.append("upstream_holdout_consumed")
    if not candidates:
        blocking.append("no_usable_or_ordinal_candidates")

    if blocking:
        report = {
            "index_id": INDEX_ID,
            "report_version": REPORT_VERSION,
            "stage_id": STAGE_ID,
            "status": "blocked_no_candidates" if blocking == ["no_usable_or_ordinal_candidates"] else "blocked_inputs_not_ready",
            "source_db_path": _safe_path(resolved_db),
            "fold_plan_path": _safe_path(fold_plan),
            "candidate_slice_count": int(len(candidates)),
            "validation_entity_day_count": 0,
            "prospective_holdout_rows_evaluated": 0,
            "prospective_holdout_score_count": 0,
            "prospective_holdout_metric_count": 0,
            "trial_accounting_invalidation_recorded": trial_doc.get("trial_accounting_invalidation_recorded"),
            "headline_model_minus_baseline_deltas": [],
            "boundary_flags": BOUNDARY_FLAGS,
            "blocking_reasons": blocking,
            "created_at": _now_iso(),
        }
        _write_csv(arm_metrics, [], ARM_METRIC_COLUMNS + PAIR_METRIC_COLUMNS)
        _write_csv(daily_exposure_sample, [], EXPOSURE_SAMPLE_COLUMNS)
        _write_markdown(output, report)
        _write_json(summary_json, report)
        return report

    specs = slice_specs_from_target_support(support)
    universe_ids = v7.universe_frame["entity_id"].astype(str).tolist()
    ohlcv, _range_report = read_ohlcv_inputs(resolved_db, universe_ids)
    if ohlcv.empty:
        close_only = v7.price_frame.rename(columns={"sector_id": "entity_id"}).copy()
        close_only["open"] = np.nan
        close_only["high"] = np.nan
        close_only["low"] = np.nan
        ohlcv = close_only[["entity_id", "trade_date", "open", "high", "low", "close"]]
    price_features, _ = build_price_baseline_features(ohlcv)
    asof_modes = sorted({str(row.get("asof_mode", "close_t_minus_1")) for row in candidates})
    model_feature_frames = {mode: shifted_price_features(price_features, asof_mode=mode) for mode in asof_modes}
    baseline_feature_frames = {mode: shifted_price_features(price_features, asof_mode=mode) for mode in asof_modes}
    validation_end_dates = [
        value
        for value in (_normalise_date(fold.get("validation_end_date")) for fold in fold_doc.get("folds", []))
        if value is not None
    ]
    max_validation_end = max(validation_end_dates, default=None)
    if max_validation_end is None:
        raise ValueError("fold plan has no validation_end_date")
    available_price_dates = set(pd.to_datetime(v7.price_frame["trade_date"], errors="coerce").dt.normalize().dropna().tolist())
    needed_dates = sorted(date for date in available_price_dates if date <= max_validation_end)
    target_rows = build_target_rows_for_trade_dates(
        v7.price_frame,
        v7.universe_frame,
        specs,
        needed_dates,
        source_db_path=resolved_db,
    )
    returns = _next_open_returns(ohlcv)
    scores, baseline_selections = _candidate_score_rows(
        candidates=candidates,
        target_rows=target_rows,
        feature_frames=model_feature_frames,
        baseline_feature_frames=baseline_feature_frames,
        fold_plan=fold_doc,
        baseline_slice_metrics=baseline_slice_metrics,
        returns=returns,
    )
    simulation = simulate_downshift_scores(
        scores,
        bootstrap_iterations=bootstrap_iterations,
        random_seed=DEFAULT_RANDOM_SEED,
        exposure_sample_rows=DEFAULT_EXPOSURE_SAMPLE_ROWS,
    )
    pair_metrics = simulation["pair_metrics"]
    arm_rows = simulation["arm_metrics"]
    headline = [
        row
        for row in pair_metrics
        if row.get("arm_pair") == PRIMARY_PAIR and row.get("metric") in set(PRIMARY_METRICS)
    ]
    holdout = pd.Timestamp(HOLDOUT_START).normalize()
    holdout_scores = 0
    if not scores.empty:
        holdout_scores = int(
            pd.to_datetime(scores["trade_date"], errors="coerce").dt.normalize().ge(holdout).sum()
            + pd.to_datetime(scores["apply_trade_date"], errors="coerce").dt.normalize().ge(holdout).sum()
        )
    status = "pass" if not scores.empty and holdout_scores == 0 else "blocked_holdout_consumed"
    if scores.empty:
        status = "partial_no_scored_candidates"
    report = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "fold_plan_path": _safe_path(fold_plan),
        "fold_plan_status": fold_doc.get("status"),
        "trial_accounting_path": _safe_path(trial_accounting),
        "trial_accounting_invalidation_recorded": trial_doc.get("trial_accounting_invalidation_recorded"),
        "candidate_slice_count": int(len(candidates)),
        "scored_candidate_slice_count": int(scores["slice_id"].nunique()) if not scores.empty else 0,
        "validation_entity_day_count": int(len(scores)),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_score_count": int(holdout_scores),
        "prospective_holdout_metric_count": 0,
        "arm_metrics_path": _safe_path(arm_metrics),
        "daily_exposure_sample_path": _safe_path(daily_exposure_sample),
        "baseline_selections": baseline_selections,
        "bucket_thresholds": simulation["bucket_thresholds"],
        "headline_model_minus_baseline_deltas": headline,
        "primary_claim": "model_minus_baseline on max_drawdown, cvar_95, realized_volatility",
        "bootstrap_iterations": int(bootstrap_iterations),
        "exposure_rule": {
            "extreme_bucket": 0.5,
            "high_bucket": 0.75,
            "otherwise": 1.0,
            "application": "next_day_open_to_next_open",
            "tuned_after_first_run": "no",
        },
        "boundary_flags": BOUNDARY_FLAGS,
        "blocking_reasons": [] if status == "pass" else [status],
        "created_at": _now_iso(),
        "no_fetch": True,
        "external_data_fetch": "no",
    }
    combined_metric_rows = []
    for row in arm_rows:
        combined_metric_rows.append(row)
    for row in pair_metrics:
        combined_metric_rows.append(row)
    _write_csv(arm_metrics, combined_metric_rows, sorted(set(ARM_METRIC_COLUMNS + PAIR_METRIC_COLUMNS), key=(ARM_METRIC_COLUMNS + PAIR_METRIC_COLUMNS).index))
    _write_csv(daily_exposure_sample, simulation["daily_exposure_sample"], EXPOSURE_SAMPLE_COLUMNS)
    _write_markdown(output, report)
    _write_json(summary_json, report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--logistic-hazard", type=Path, default=DEFAULT_LOGISTIC_HAZARD)
    parser.add_argument("--calibration-readiness", type=Path, default=DEFAULT_CALIBRATION_READINESS)
    parser.add_argument("--readiness-matrix", type=Path, default=DEFAULT_READINESS_MATRIX)
    parser.add_argument("--baseline-slice-metrics", type=Path, default=DEFAULT_BASELINE_SLICE_METRICS)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--trial-accounting", type=Path, default=DEFAULT_TRIAL_ACCOUNTING)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--arm-metrics", type=Path, default=DEFAULT_ARM_METRICS)
    parser.add_argument("--daily-exposure-sample", type=Path, default=DEFAULT_DAILY_EXPOSURE_SAMPLE)
    parser.add_argument("--bootstrap-iterations", type=int, default=DEFAULT_BOOTSTRAP_ITERATIONS)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_downshift_experiment_report(
        db_path=args.db,
        target_support=args.target_support,
        logistic_hazard=args.logistic_hazard,
        calibration_readiness=args.calibration_readiness,
        readiness_matrix=args.readiness_matrix,
        baseline_slice_metrics=args.baseline_slice_metrics,
        fold_plan=args.fold_plan,
        trial_accounting=args.trial_accounting,
        output=args.output,
        summary_json=args.summary_json,
        arm_metrics=args.arm_metrics,
        daily_exposure_sample=args.daily_exposure_sample,
        bootstrap_iterations=args.bootstrap_iterations,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_RERUN1_B2_DOWNSHIFT="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"candidate_slices={report.get('candidate_slice_count')} "
        f"scored_slices={report.get('scored_candidate_slice_count')} "
        f"entity_days={report.get('validation_entity_day_count')} "
        f"holdout_scores={report.get('prospective_holdout_score_count')} "
        "no_fetch=yes research_only=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
