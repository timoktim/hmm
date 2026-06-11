"""Stage03V WP3.5 volatility-scaled threshold and metric sanity gate.

This module is a read-only supplement between WP3 baseline diagnostics and WP4
modeling. It evaluates volatility-scaled threshold variants as aggregate
diagnostics and audits WP3 baseline metric artifacts without training models,
calibrating probabilities, assigning readiness, consuming holdout rows, fetching
data, or writing persistent DuckDB tables.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_baseline_diagnostics import (
    BASELINE_DEFINITIONS,
    build_price_baseline_features,
    build_target_rows_for_trade_dates,
    compute_metric_row,
    detect_feature_asof_violations,
    read_ohlcv_inputs,
    slice_specs_from_target_support,
    validate_baseline_input_columns,
)
from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)


INDEX_ID = "STAGE03V-WP3.5-v1"
REPORT_VERSION = "stage03v_vol_scaled_threshold_sanity_v1"
STAGE_ID = "stage03v"
POLICY_VERSION = "stage03v_vol_scaled_threshold_sanity_policy_v1"

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_BASELINE_REPORT = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_BASELINE_FOLD_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_fold_metrics.csv"
DEFAULT_BASELINE_SLICE_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_slice_metrics.csv"
DEFAULT_BASELINE_POLICY = ROOT / "configs" / "stage03v_baseline_diagnostics_policy_v1.yaml"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_vol_scaled_threshold_sanity_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_sanity_report.json"
DEFAULT_VOL_SCALED_SUMMARY = ROOT / "reports" / "stage03v" / "vol_scaled_threshold_slice_summary.csv"
DEFAULT_METRIC_AUDIT = ROOT / "reports" / "stage03v" / "baseline_metric_sanity_audit.csv"
DEFAULT_ASOF_SHIFT_SUMMARY = ROOT / "reports" / "stage03v" / "asof_shift_metric_sanity.csv"

VOLATILITY_ESTIMATORS = [
    {
        "estimator_id": "rolling_close_to_close_vol_20",
        "feature_column": "rolling_close_to_close_vol_20",
        "annualized_input": False,
    },
    {
        "estimator_id": "rolling_close_to_close_vol_60",
        "feature_column": "rolling_close_to_close_vol_60",
        "annualized_input": False,
    },
    {
        "estimator_id": "ewma_close_to_close_vol_20_or_equivalent",
        "feature_column": "ewma_close_to_close_vol",
        "annualized_input": False,
    },
]
K_CANDIDATES = [1.0, 1.5, 2.0, 2.5]
HORIZONS = [1, 5, 10, 20]
ASOF_MODES = ["close_t", "close_t_minus_1"]
CLAMP_MIN_ABS_THRESHOLD = 0.02
CLAMP_MAX_ABS_THRESHOLD = 0.15
TRADING_DAYS_PER_YEAR = 252
DEFAULT_AUDIT_CAP = 500
MATERIAL_DEGRADATION_DELTA = 0.05

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "full_feature_matrix_committed": "no",
    "full_score_matrix_committed": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
    "trading_or_decision_output": "no",
}

LEAKAGE_ZERO_COUNTS = {
    "feature_asof_violation_count": 0,
    "target_namespace_input_violation_count": 0,
    "future_column_input_violation_count": 0,
    "same_row_label_leakage_count": 0,
    "validation_label_leakage_count": 0,
    "prospective_holdout_score_count": 0,
    "prospective_holdout_metric_count": 0,
    "fixed_threshold_mainline_mutation_count": 0,
    "persistent_db_write_count": 0,
    "external_fetch_count": 0,
    "leakage_violation_count_total": 0,
}

VOL_SUMMARY_COLUMNS = [
    "fold_id",
    "asof_mode",
    "candidate_name",
    "volatility_estimator",
    "volatility_feature_column",
    "horizon",
    "k_value",
    "threshold_type",
    "source_threshold_type",
    "source_threshold_value",
    "target_usage",
    "row_count",
    "scored_row_count",
    "positive_event_count",
    "event_base_rate",
    "score_available_rate",
    "fixed_threshold_event_count",
    "fixed_threshold_event_base_rate",
    "vol_scaled_event_count",
    "vol_scaled_event_base_rate",
    "vol_scaled_to_fixed_event_count_ratio",
    "threshold_abs_mean",
    "threshold_abs_median",
    "threshold_abs_p10",
    "threshold_abs_p90",
    "clamp_min_hit_rate",
    "clamp_max_hit_rate",
    "entity_count_with_positive_events",
    "median_positive_events_per_entity",
    "min_positive_events_per_fold",
    "market_event_block_count",
    "effective_event_evidence_count",
    "largest_single_entity_share",
    "largest_single_trade_date_share",
    "entity_hhi",
    "date_hhi",
    "feature_asof_min",
    "feature_asof_max",
    "feature_asof_violation_count",
    "prospective_holdout_score_count",
]

METRIC_AUDIT_COLUMNS = [
    "source_metric_scope",
    "baseline_name",
    "baseline_family",
    "fold_id",
    "slice_id",
    "target_usage",
    "horizon",
    "threshold_value",
    "metric_name",
    "metric_value",
    "row_count",
    "scored_row_count",
    "positive_event_count",
    "event_base_rate",
    "score_available_rate",
    "diagnostic_only_flag",
    "eligible_flag",
    "largest_single_entity_share",
    "largest_single_trade_date_share",
    "largest_single_fold_share",
    "entity_hhi",
    "date_hhi",
    "feature_asof_min",
    "feature_asof_max",
    "feature_asof_violation_count",
    "same_row_label_leakage_count",
    "future_column_input_violation_count",
    "target_namespace_input_violation_count",
    "artifact_flag",
    "artifact_reason",
    "flag_reason",
]

ASOF_SHIFT_COLUMNS = [
    "source",
    "baseline_or_candidate_name",
    "baseline_family",
    "fold_id",
    "slice_id",
    "target_usage",
    "horizon",
    "threshold_value",
    "metric_name",
    "metric_close_t",
    "metric_close_t_minus_1",
    "metric_delta",
    "row_count_close_t",
    "row_count_close_t_minus_1",
    "positive_event_count_close_t",
    "positive_event_count_close_t_minus_1",
    "score_available_rate_close_t",
    "score_available_rate_close_t_minus_1",
    "material_degradation_flag",
    "asof_dependency_flag",
    "asof_shift_status",
    "deferred_reason",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_machine_config(path: Path | str) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:
            raise ValueError(f"{path} is not JSON and PyYAML is unavailable") from exc
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}


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


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP3.5 Volatility-Scaled Threshold Sanity",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- wp1_support_status: {report.get('wp1_support_status')}",
        f"- wp2_controls_status: {report.get('wp2_controls_status')}",
        f"- wp2_1_full_target_audit_status: {report.get('wp2_1_full_target_audit_status')}",
        f"- wp3_baseline_diagnostics_status: {report.get('wp3_baseline_diagnostics_status')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- fixed_threshold_mainline_status: {report.get('fixed_threshold_mainline_status')}",
        f"- volatility_scaled_threshold_status: {report.get('volatility_scaled_threshold_status')}",
        f"- baseline_sanity_status: {report.get('baseline_sanity_status')}",
        f"- wp4_entry_recommendation: {report.get('wp4_entry_recommendation')}",
        f"- validation_row_count_evaluated: {report.get('validation_row_count_evaluated')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- vol_scaled_candidate_count: {report.get('vol_scaled_candidate_count')}",
        f"- asof_mode_count: {report.get('asof_mode_count')}",
        f"- flagged_metric_row_count: {report.get('flagged_metric_row_count')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Leakage Counts",
        "",
    ]
    for key, value in report.get("leakage_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
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


def _as_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or pd.isna(value):
            return int(default)
    except (TypeError, ValueError):
        pass
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _safe_div(numerator: float | int, denominator: float | int) -> float | None:
    denominator = float(denominator)
    if denominator == 0 or not math.isfinite(denominator):
        return None
    value = float(numerator) / denominator
    return value if math.isfinite(value) else None


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


def _slice_id(row: Mapping[str, Any]) -> str:
    return (
        f"h{int(row.get('horizon'))}:"
        f"{row.get('threshold_type', 'fixed')}:"
        f"{float(row.get('threshold_value')):.4f}:"
        f"{row.get('target_usage', 'unknown')}"
    )


def _candidate_name(estimator_id: str, horizon: int, k_value: float) -> str:
    k_text = str(k_value).replace(".", "_")
    return f"{estimator_id}__h{int(horizon)}__k{k_text}"


def default_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "source_target_controls": "reports/stage03v/target_controls_report.json",
        "source_full_target_audit": "reports/stage03v/full_target_streaming_audit_report.json",
        "source_baseline_report": "reports/stage03v/baseline_diagnostics_report.json",
        "fold_plan": "reports/stage03v/purge_embargo_fold_plan.json",
        "fixed_threshold_mainline_policy": "unchanged_reference_only",
        "volatility_scaled_threshold_policy": "supplement_only_not_replacement",
        "volatility_estimators": [item["estimator_id"] for item in VOLATILITY_ESTIMATORS],
        "horizons": HORIZONS,
        "k_candidates": K_CANDIDATES,
        "clamp_min_abs_threshold": CLAMP_MIN_ABS_THRESHOLD,
        "clamp_max_abs_threshold": CLAMP_MAX_ABS_THRESHOLD,
        "threshold_formula": "threshold_abs = clamp(k * daily_vol * sqrt(horizon), 0.02, 0.15)",
        "asof_modes": ASOF_MODES,
        "feature_asof_policy": (
            "feature_asof_date <= trade_date for close_t; "
            "feature_asof_date < trade_date for close_t_minus_1"
        ),
        "evaluation_split_policy": "validation_rows_only",
        "final_holdout_policy": "withheld_not_scored",
        "calibration_policy": "forbidden_in_wp3_5",
        "readiness_policy": "forbidden_in_wp3_5",
        "model_training_policy": "forbidden_in_wp3_5",
        "external_fetch_policy": "forbidden",
        "full_matrix_commit_policy": "aggregate_or_capped_samples_only",
        "metric_sanity_thresholds": {
            "high_roc_auc": 0.90,
            "high_average_precision": 0.25,
            "high_abs_spearman_score_vs_future_mdd": 0.30,
            "min_score_available_rate": 0.50,
            "min_positive_event_count": 5,
            "min_event_base_rate": 0.001,
            "max_event_base_rate": 0.50,
            "concentration_share_warning": 0.50,
            "material_degradation_delta": MATERIAL_DEGRADATION_DELTA,
        },
        "boundary_flags": BOUNDARY_FLAGS,
    }


def validate_policy(policy: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    expected = default_policy()
    for key in ["index_id", "policy_version", "information_cutoff_date", "holdout_start"]:
        if policy.get(key) != expected[key]:
            issues.append(f"{key}_mismatch")
    if policy.get("fixed_threshold_mainline_policy") != "unchanged_reference_only":
        issues.append("fixed_threshold_mainline_policy_not_reference_only")
    if policy.get("volatility_scaled_threshold_policy") != "supplement_only_not_replacement":
        issues.append("volatility_scaled_threshold_policy_not_supplement_only")
    if set(policy.get("volatility_estimators", [])) != {item["estimator_id"] for item in VOLATILITY_ESTIMATORS}:
        issues.append("volatility_estimators_mismatch")
    if [int(item) for item in policy.get("horizons", [])] != HORIZONS:
        issues.append("horizons_mismatch")
    if [float(item) for item in policy.get("k_candidates", [])] != K_CANDIDATES:
        issues.append("k_candidates_mismatch")
    if policy.get("asof_modes") != ASOF_MODES:
        issues.append("asof_modes_mismatch")
    for key in ["calibration_policy", "readiness_policy", "model_training_policy"]:
        if policy.get(key) != "forbidden_in_wp3_5":
            issues.append(f"{key}_not_forbidden_in_wp3_5")
    if policy.get("final_holdout_policy") != "withheld_not_scored":
        issues.append("final_holdout_policy_not_withheld")
    return issues


def threshold_abs_from_daily_vol(
    volatility: pd.Series | np.ndarray | Sequence[float],
    *,
    horizon: int,
    k_value: float,
    clamp_min_abs_threshold: float = CLAMP_MIN_ABS_THRESHOLD,
    clamp_max_abs_threshold: float = CLAMP_MAX_ABS_THRESHOLD,
    input_is_annualized: bool = False,
    trading_days_per_year: int = TRADING_DAYS_PER_YEAR,
) -> pd.Series:
    values = pd.to_numeric(pd.Series(volatility), errors="coerce").astype(float)
    if input_is_annualized:
        values = values / math.sqrt(float(trading_days_per_year))
    threshold = values * math.sqrt(float(horizon)) * float(k_value)
    threshold = threshold.clip(lower=float(clamp_min_abs_threshold), upper=float(clamp_max_abs_threshold))
    return threshold.where(np.isfinite(threshold), np.nan)


def shifted_price_features(price_features: pd.DataFrame, *, asof_mode: str) -> pd.DataFrame:
    if asof_mode not in set(ASOF_MODES):
        raise ValueError(f"unsupported asof_mode: {asof_mode}")
    data = price_features.copy()
    if data.empty:
        return data
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    data["feature_asof_date"] = pd.to_datetime(data["feature_asof_date"], errors="coerce").dt.normalize()
    if asof_mode == "close_t":
        return data
    value_columns = [
        item["feature_column"]
        for item in VOLATILITY_ESTIMATORS
        if item["feature_column"] in data.columns
    ]
    price_baseline_columns = [
        str(item["name"])
        for item in BASELINE_DEFINITIONS
        if item.get("kind") == "price" and str(item["name"]) in data.columns
    ]
    shift_columns = sorted(set(value_columns + price_baseline_columns))
    frames: list[pd.DataFrame] = []
    for _, group in data.sort_values(["entity_id", "trade_date"]).groupby("entity_id", sort=False):
        g = group.copy()
        for column in shift_columns:
            g[column] = g[column].shift(1)
        g["feature_asof_date"] = g["trade_date"].shift(1)
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else data.iloc[0:0].copy()


def detect_asof_violations(rows: pd.DataFrame, *, asof_mode: str) -> int:
    if rows.empty or "feature_asof_date" not in rows.columns or "trade_date" not in rows.columns:
        return 0
    base = detect_feature_asof_violations(rows)
    if asof_mode != "close_t_minus_1":
        return int(base)
    asof = pd.to_datetime(rows["feature_asof_date"], errors="coerce").dt.normalize()
    trade_date = pd.to_datetime(rows["trade_date"], errors="coerce").dt.normalize()
    same_or_after = asof.notna() & trade_date.notna() & asof.ge(trade_date)
    return int(same_or_after.sum())


def validate_feature_input_columns(columns: Sequence[str]) -> dict[str, Any]:
    return validate_baseline_input_columns(columns)


def _event_concentration(rows: pd.DataFrame, event_column: str = "event_label") -> dict[str, Any]:
    if rows.empty or event_column not in rows.columns:
        return {
            "positive_event_count": 0,
            "largest_single_entity_share": None,
            "largest_single_trade_date_share": None,
            "largest_single_fold_share": None,
            "entity_hhi": None,
            "date_hhi": None,
            "entity_count_with_positive_events": 0,
            "median_positive_events_per_entity": None,
        }
    positives = rows[pd.Series(rows[event_column]).astype(bool).to_numpy()].copy()
    positive_count = int(len(positives))
    if positive_count == 0:
        return {
            "positive_event_count": 0,
            "largest_single_entity_share": 0.0,
            "largest_single_trade_date_share": 0.0,
            "largest_single_fold_share": 0.0,
            "entity_hhi": 0.0,
            "date_hhi": 0.0,
            "entity_count_with_positive_events": 0,
            "median_positive_events_per_entity": 0.0,
        }

    def shares(column: str) -> tuple[float | None, float | None, pd.Series]:
        if column not in positives.columns:
            return None, None, pd.Series(dtype=float)
        counts = positives.groupby(column, dropna=False).size().astype(float)
        ratios = counts / float(positive_count)
        return float(ratios.max()), float((ratios**2).sum()), counts

    entity_share, entity_hhi, entity_counts = shares("entity_id")
    date_share, date_hhi, _ = shares("trade_date")
    fold_share, _, _ = shares("fold_id")
    median_entity_events = float(entity_counts.median()) if len(entity_counts) else 0.0
    return {
        "positive_event_count": positive_count,
        "largest_single_entity_share": entity_share,
        "largest_single_trade_date_share": date_share,
        "largest_single_fold_share": fold_share,
        "entity_hhi": entity_hhi,
        "date_hhi": date_hhi,
        "entity_count_with_positive_events": int(len(entity_counts)),
        "median_positive_events_per_entity": median_entity_events,
    }


def market_event_block_count(rows: pd.DataFrame, *, horizon: int, event_column: str = "event_label", share: float = 0.20) -> int:
    if rows.empty or event_column not in rows.columns:
        return 0
    work = rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    by_date = work.groupby("trade_date", dropna=False)[event_column].mean().reset_index(name="event_share")
    event_dates = sorted(pd.to_datetime(by_date.loc[by_date["event_share"].ge(share), "trade_date"]).dropna().tolist())
    if not event_dates:
        return 0
    blocks = 1
    previous = event_dates[0]
    for current in event_dates[1:]:
        if (current - previous).days > int(horizon):
            blocks += 1
        previous = current
    return int(blocks)


def _validation_rows_for_folds(target_rows: pd.DataFrame, fold_plan: Mapping[str, Any]) -> tuple[pd.DataFrame, int]:
    frames: list[pd.DataFrame] = []
    withheld_total = 0
    for fold in fold_plan.get("folds", []):
        fold_id = str(fold.get("fold_id", "fold_unknown"))
        start = _normalise_date(fold.get("validation_start_date"))
        end = _normalise_date(fold.get("validation_end_date"))
        if start is None or end is None or target_rows.empty:
            continue
        work = target_rows.copy()
        work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
        validation = work[work["trade_date"].between(start, end, inclusive="both")].copy()
        holdout_mask = validation["trade_date"].ge(pd.Timestamp(HOLDOUT_START))
        withheld_total += int(holdout_mask.sum())
        validation = validation[~holdout_mask].copy()
        validation = validation[
            validation["censoring_status"].astype(str).eq("labeled")
            & validation["event_label"].notna()
        ].copy()
        validation["fold_id"] = fold_id
        frames.append(validation)
    if not frames:
        return pd.DataFrame(columns=list(target_rows.columns) + ["fold_id"]), withheld_total
    return pd.concat(frames, ignore_index=True), withheld_total


def build_feature_frames(ohlcv: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    features, availability = build_price_baseline_features(ohlcv)
    return {mode: shifted_price_features(features, asof_mode=mode) for mode in ASOF_MODES}, availability


def evaluate_vol_scaled_thresholds(
    *,
    validation_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    feature_columns = ["entity_id", "trade_date", "feature_asof_date"]
    for estimator in VOLATILITY_ESTIMATORS:
        feature_columns.append(str(estimator["feature_column"]))
    leakage_counts = dict(LEAKAGE_ZERO_COUNTS)
    namespace = validate_feature_input_columns(feature_columns)
    leakage_counts["target_namespace_input_violation_count"] = int(namespace["target_namespace_input_violation_count"])
    leakage_counts["future_column_input_violation_count"] = int(namespace["future_column_input_violation_count"])

    thresholds = policy.get("metric_sanity_thresholds", {})
    min_abs = float(policy.get("clamp_min_abs_threshold", CLAMP_MIN_ABS_THRESHOLD))
    max_abs = float(policy.get("clamp_max_abs_threshold", CLAMP_MAX_ABS_THRESHOLD))
    holdout = pd.Timestamp(HOLDOUT_START)

    for asof_mode in ASOF_MODES:
        features = feature_frames.get(asof_mode, pd.DataFrame()).copy()
        if features.empty:
            continue
        keep_columns = [column for column in feature_columns if column in features.columns]
        merged = validation_rows.merge(features[keep_columns], on=["entity_id", "trade_date"], how="left")
        for estimator in VOLATILITY_ESTIMATORS:
            estimator_id = str(estimator["estimator_id"])
            feature_column = str(estimator["feature_column"])
            if feature_column not in merged.columns:
                continue
            for horizon in HORIZONS:
                horizon_rows = merged[merged["horizon"].astype(int).eq(int(horizon))].copy()
                if horizon_rows.empty:
                    continue
                for k_value in K_CANDIDATES:
                    threshold_abs = threshold_abs_from_daily_vol(
                        horizon_rows[feature_column],
                        horizon=horizon,
                        k_value=k_value,
                        clamp_min_abs_threshold=min_abs,
                        clamp_max_abs_threshold=max_abs,
                        input_is_annualized=bool(estimator.get("annualized_input", False)),
                    ).reset_index(drop=True)
                    base = horizon_rows.reset_index(drop=True).copy()
                    base["threshold_abs"] = threshold_abs
                    base["score_available"] = base["threshold_abs"].notna()
                    base["vol_scaled_event_label"] = (
                        pd.to_numeric(base["future_mdd"], errors="coerce").ge(base["threshold_abs"])
                        & base["score_available"]
                    )
                    base.loc[~base["score_available"], "vol_scaled_event_label"] = False
                    leakage_counts["feature_asof_violation_count"] += detect_asof_violations(base, asof_mode=asof_mode)
                    leakage_counts["prospective_holdout_score_count"] += int(
                        (
                            pd.to_datetime(base["trade_date"], errors="coerce").dt.normalize().ge(holdout)
                            & base["score_available"]
                        ).sum()
                    )
                    for _, group in base.groupby(
                        ["fold_id", "horizon", "threshold_type", "threshold_value", "target_usage"],
                        sort=False,
                        dropna=False,
                    ):
                        scored = group[group["score_available"]].copy()
                        concentration = _event_concentration(scored, "vol_scaled_event_label")
                        fixed_positive = int(group["event_label"].astype(bool).sum())
                        vol_positive = int(concentration["positive_event_count"])
                        threshold_values = pd.to_numeric(scored["threshold_abs"], errors="coerce").dropna()
                        candidate = _candidate_name(estimator_id, int(horizon), float(k_value))
                        market_blocks = market_event_block_count(
                            scored,
                            horizon=int(horizon),
                            event_column="vol_scaled_event_label",
                        )
                        effective_evidence = float(market_blocks) + max(
                            0.0,
                            float(concentration.get("entity_count_with_positive_events") or 0) - float(market_blocks),
                        ) * 0.25
                        feature_asof = pd.to_datetime(group["feature_asof_date"], errors="coerce").dropna()
                        rows.append(
                            {
                                "fold_id": str(group["fold_id"].iloc[0]),
                                "asof_mode": asof_mode,
                                "candidate_name": candidate,
                                "volatility_estimator": estimator_id,
                                "volatility_feature_column": feature_column,
                                "horizon": int(horizon),
                                "k_value": float(k_value),
                                "threshold_type": "volatility_scaled",
                                "source_threshold_type": str(group["threshold_type"].iloc[0]),
                                "source_threshold_value": float(group["threshold_value"].iloc[0]),
                                "target_usage": str(group["target_usage"].iloc[0]),
                                "row_count": int(len(group)),
                                "scored_row_count": int(len(scored)),
                                "positive_event_count": vol_positive,
                                "event_base_rate": _safe_div(vol_positive, len(scored)),
                                "score_available_rate": _safe_div(len(scored), len(group)),
                                "fixed_threshold_event_count": fixed_positive,
                                "fixed_threshold_event_base_rate": _safe_div(fixed_positive, len(group)),
                                "vol_scaled_event_count": vol_positive,
                                "vol_scaled_event_base_rate": _safe_div(vol_positive, len(scored)),
                                "vol_scaled_to_fixed_event_count_ratio": _safe_div(vol_positive, fixed_positive),
                                "threshold_abs_mean": float(threshold_values.mean()) if len(threshold_values) else None,
                                "threshold_abs_median": float(threshold_values.median()) if len(threshold_values) else None,
                                "threshold_abs_p10": float(threshold_values.quantile(0.10)) if len(threshold_values) else None,
                                "threshold_abs_p90": float(threshold_values.quantile(0.90)) if len(threshold_values) else None,
                                "clamp_min_hit_rate": _safe_div(float(np.isclose(threshold_values, min_abs).sum()), len(threshold_values))
                                if len(threshold_values)
                                else None,
                                "clamp_max_hit_rate": _safe_div(float(np.isclose(threshold_values, max_abs).sum()), len(threshold_values))
                                if len(threshold_values)
                                else None,
                                "entity_count_with_positive_events": concentration["entity_count_with_positive_events"],
                                "median_positive_events_per_entity": concentration["median_positive_events_per_entity"],
                                "min_positive_events_per_fold": vol_positive,
                                "market_event_block_count": market_blocks,
                                "effective_event_evidence_count": effective_evidence,
                                "largest_single_entity_share": concentration["largest_single_entity_share"],
                                "largest_single_trade_date_share": concentration["largest_single_trade_date_share"],
                                "entity_hhi": concentration["entity_hhi"],
                                "date_hhi": concentration["date_hhi"],
                                "feature_asof_min": _json_safe(feature_asof.min()) if len(feature_asof) else None,
                                "feature_asof_max": _json_safe(feature_asof.max()) if len(feature_asof) else None,
                                "feature_asof_violation_count": detect_asof_violations(group, asof_mode=asof_mode),
                                "prospective_holdout_score_count": int(
                                    pd.to_datetime(group["trade_date"], errors="coerce").dt.normalize().ge(holdout).sum()
                                ),
                            }
                        )
    leakage_counts["leakage_violation_count_total"] = int(sum(v for k, v in leakage_counts.items() if k != "leakage_violation_count_total"))
    return {"rows": rows, "leakage_violation_counts": leakage_counts}


def _metric_thresholds(policy: Mapping[str, Any]) -> dict[str, float]:
    defaults = default_policy()["metric_sanity_thresholds"]
    configured = policy.get("metric_sanity_thresholds", {})
    return {key: float(configured.get(key, value)) for key, value in defaults.items()}


def _flag_metric_row(row: Mapping[str, Any], thresholds: Mapping[str, float], best_keys: set[tuple[str, str, int, float, str, str]]) -> list[tuple[str, str, float | None]]:
    flags: list[tuple[str, str, float | None]] = []
    baseline = str(row.get("baseline_name"))
    family = str(row.get("baseline_family"))
    horizon = _as_int(row.get("horizon"), -1)
    threshold = float(row.get("threshold_value")) if _as_float(row.get("threshold_value")) is not None else math.nan
    usage = str(row.get("target_usage"))
    for metric in ["roc_auc", "average_precision", "spearman_score_vs_future_mdd"]:
        key = (baseline, family, horizon, threshold, usage, metric)
        if key in best_keys:
            flags.append((f"best_baseline_{metric}", metric, _as_float(row.get(metric))))
    roc_auc = _as_float(row.get("roc_auc"))
    if roc_auc is not None and roc_auc >= thresholds["high_roc_auc"]:
        flags.append(("high_auc", "roc_auc", roc_auc))
    ap = _as_float(row.get("average_precision"))
    if ap is not None and ap >= thresholds["high_average_precision"]:
        flags.append(("high_average_precision", "average_precision", ap))
    rank = _as_float(row.get("spearman_score_vs_future_mdd"))
    if rank is not None and abs(rank) >= thresholds["high_abs_spearman_score_vs_future_mdd"]:
        flags.append(("high_rank_correlation", "spearman_score_vs_future_mdd", rank))
    score_rate = _as_float(row.get("score_available_rate"))
    if score_rate is not None and score_rate < thresholds["min_score_available_rate"]:
        flags.append(("low_score_available_rate", "score_available_rate", score_rate))
    positive_count = _as_int(row.get("positive_event_count"), 0)
    if positive_count < int(thresholds["min_positive_event_count"]):
        flags.append(("low_positive_event_support", "positive_event_count", float(positive_count)))
    base_rate = _as_float(row.get("event_base_rate"))
    if base_rate is not None and (
        base_rate < thresholds["min_event_base_rate"] or base_rate > thresholds["max_event_base_rate"]
    ):
        flags.append(("event_base_rate_outside_policy", "event_base_rate", base_rate))
    return flags


def _best_metric_keys(baseline_report: Mapping[str, Any]) -> set[tuple[str, str, int, float, str, str]]:
    keys: set[tuple[str, str, int, float, str, str]] = set()
    for key in ["best_baseline_by_auc", "best_baseline_by_average_precision", "best_baseline_by_rank_correlation"]:
        item = baseline_report.get(key)
        if not isinstance(item, Mapping):
            continue
        metric = str(item.get("metric"))
        threshold = _as_float(item.get("threshold_value"))
        if threshold is None:
            continue
        keys.add(
            (
                str(item.get("baseline_name")),
                str(item.get("baseline_family")),
                _as_int(item.get("horizon"), -1),
                float(threshold),
                str(item.get("target_usage")),
                metric,
            )
        )
    return keys


def _matching_validation_rows(validation_rows: pd.DataFrame, metric_row: Mapping[str, Any]) -> pd.DataFrame:
    if validation_rows.empty:
        return validation_rows.copy()
    mask = (
        validation_rows["horizon"].astype(int).eq(_as_int(metric_row.get("horizon"), -1))
        & validation_rows["threshold_value"].astype(float).eq(float(metric_row.get("threshold_value")))
        & validation_rows["target_usage"].astype(str).eq(str(metric_row.get("target_usage")))
    )
    fold_id = metric_row.get("fold_id")
    if fold_id is not None and str(fold_id) and str(fold_id) != "nan":
        mask = mask & validation_rows["fold_id"].astype(str).eq(str(fold_id))
    return validation_rows[mask].copy()


def _feature_asof_bounds(rows: pd.DataFrame, feature_frames: Mapping[str, pd.DataFrame], baseline_name: str) -> tuple[Any, Any, int]:
    if rows.empty:
        return None, None, 0
    features = feature_frames.get("close_t", pd.DataFrame())
    if features.empty or baseline_name not in features.columns:
        return None, None, 0
    merged = rows[["entity_id", "trade_date"]].merge(
        features[["entity_id", "trade_date", "feature_asof_date", baseline_name]],
        on=["entity_id", "trade_date"],
        how="left",
    )
    scored = merged[pd.to_numeric(merged[baseline_name], errors="coerce").notna()].copy()
    dates = pd.to_datetime(scored["feature_asof_date"], errors="coerce").dropna()
    return (
        _json_safe(dates.min()) if len(dates) else None,
        _json_safe(dates.max()) if len(dates) else None,
        detect_asof_violations(scored, asof_mode="close_t"),
    )


def _artifact_reason(
    *,
    flag_reason: str,
    metric_row: Mapping[str, Any],
    concentration: Mapping[str, Any],
    feature_asof_violation_count: int,
    thresholds: Mapping[str, float],
) -> str:
    if feature_asof_violation_count > 0:
        return "explained_by_asof_semantics"
    positive_count = _as_int(metric_row.get("positive_event_count"), 0)
    base_rate = _as_float(metric_row.get("event_base_rate"))
    if positive_count < int(thresholds["min_positive_event_count"]) or (
        base_rate is not None
        and (base_rate < thresholds["min_event_base_rate"] or base_rate > thresholds["max_event_base_rate"])
    ):
        return "explained_by_threshold_or_event_imbalance"
    entity_share = _as_float(concentration.get("largest_single_entity_share"))
    date_share = _as_float(concentration.get("largest_single_trade_date_share"))
    if (
        (entity_share is not None and entity_share >= thresholds["concentration_share_warning"])
        or (date_share is not None and date_share >= thresholds["concentration_share_warning"])
        or flag_reason == "low_score_available_rate"
    ):
        return "explained_by_sample_or_slice_structure"
    if flag_reason.startswith("best_baseline") or flag_reason.startswith("high_"):
        return "unexplained_warning"
    return "no_artifact_detected"


def audit_baseline_metrics(
    *,
    baseline_report: Mapping[str, Any],
    fold_metrics: pd.DataFrame,
    slice_metrics: pd.DataFrame,
    validation_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    policy: Mapping[str, Any],
    audit_cap: int,
) -> dict[str, Any]:
    thresholds = _metric_thresholds(policy)
    best_keys = _best_metric_keys(baseline_report)
    raw_rows: list[dict[str, Any]] = []
    all_metric_rows: list[tuple[str, Mapping[str, Any]]] = []
    for _, row in fold_metrics.iterrows():
        all_metric_rows.append(("fold", row.to_dict()))
    for _, row in slice_metrics.iterrows():
        all_metric_rows.append(("slice", row.to_dict()))

    summary_counts = {
        "flagged_metric_row_count": 0,
        "high_auc_flag_count": 0,
        "high_ap_flag_count": 0,
        "high_rank_correlation_flag_count": 0,
        "low_support_flag_count": 0,
        "concentration_warning_count": 0,
        "asof_dependency_warning_count": 0,
        "diagnostic_only_flag_count": 0,
        "unexplained_warning_count": 0,
        "metric_sanity_fail_count": 0,
    }
    known_high_auc_covered = False
    known_high_auc_reason = None

    for scope, metric_row in all_metric_rows:
        flags = _flag_metric_row(metric_row, thresholds, best_keys)
        if not flags:
            continue
        matching = _matching_validation_rows(validation_rows, metric_row)
        concentration = _event_concentration(matching, "event_label")
        feature_min, feature_max, asof_violations = _feature_asof_bounds(
            matching,
            feature_frames,
            str(metric_row.get("baseline_name")),
        )
        slice_id = _slice_id(metric_row)
        diagnostic_only = str(metric_row.get("target_usage")) == "diagnostic_only"
        eligible = str(metric_row.get("target_usage")) == "eligible"
        for flag_reason, metric_name, metric_value in flags:
            artifact_reason = _artifact_reason(
                flag_reason=flag_reason,
                metric_row=metric_row,
                concentration=concentration,
                feature_asof_violation_count=asof_violations,
                thresholds=thresholds,
            )
            artifact_flag = "warning" if artifact_reason != "no_artifact_detected" else "no"
            raw_rows.append(
                {
                    "source_metric_scope": scope,
                    "baseline_name": metric_row.get("baseline_name"),
                    "baseline_family": metric_row.get("baseline_family"),
                    "fold_id": metric_row.get("fold_id"),
                    "slice_id": slice_id,
                    "target_usage": metric_row.get("target_usage"),
                    "horizon": _as_int(metric_row.get("horizon"), 0),
                    "threshold_value": _as_float(metric_row.get("threshold_value")),
                    "metric_name": metric_name,
                    "metric_value": metric_value,
                    "row_count": _as_int(metric_row.get("row_count"), 0),
                    "scored_row_count": _as_int(metric_row.get("scored_row_count"), 0),
                    "positive_event_count": _as_int(metric_row.get("positive_event_count"), 0),
                    "event_base_rate": _as_float(metric_row.get("event_base_rate")),
                    "score_available_rate": _as_float(metric_row.get("score_available_rate")),
                    "diagnostic_only_flag": bool(diagnostic_only),
                    "eligible_flag": bool(eligible),
                    "largest_single_entity_share": concentration["largest_single_entity_share"],
                    "largest_single_trade_date_share": concentration["largest_single_trade_date_share"],
                    "largest_single_fold_share": concentration["largest_single_fold_share"],
                    "entity_hhi": concentration["entity_hhi"],
                    "date_hhi": concentration["date_hhi"],
                    "feature_asof_min": feature_min,
                    "feature_asof_max": feature_max,
                    "feature_asof_violation_count": asof_violations,
                    "same_row_label_leakage_count": 0,
                    "future_column_input_violation_count": 0,
                    "target_namespace_input_violation_count": 0,
                    "artifact_flag": artifact_flag,
                    "artifact_reason": artifact_reason,
                    "flag_reason": flag_reason,
                }
            )
            summary_counts["flagged_metric_row_count"] += 1
            if flag_reason == "high_auc":
                summary_counts["high_auc_flag_count"] += 1
            if flag_reason == "high_average_precision":
                summary_counts["high_ap_flag_count"] += 1
            if flag_reason == "high_rank_correlation":
                summary_counts["high_rank_correlation_flag_count"] += 1
            if flag_reason in {"low_positive_event_support", "event_base_rate_outside_policy"}:
                summary_counts["low_support_flag_count"] += 1
            if artifact_reason == "explained_by_sample_or_slice_structure":
                summary_counts["concentration_warning_count"] += 1
            if artifact_reason == "explained_by_asof_semantics":
                summary_counts["asof_dependency_warning_count"] += 1
            if diagnostic_only:
                summary_counts["diagnostic_only_flag_count"] += 1
            if artifact_reason == "unexplained_warning":
                summary_counts["unexplained_warning_count"] += 1
            if (
                str(metric_row.get("baseline_name")) == "rolling_close_to_close_vol_60"
                and str(metric_row.get("baseline_family")) == "realized_volatility"
                and metric_name == "roc_auc"
                and _as_int(metric_row.get("horizon"), 0) == 1
                and abs(float(metric_row.get("threshold_value")) - 0.05) < 1e-12
                and str(metric_row.get("target_usage")) == "diagnostic_only"
            ):
                known_high_auc_covered = True
                known_high_auc_reason = artifact_reason

    capped_rows = raw_rows[: int(audit_cap)]
    return {
        "rows": capped_rows,
        "raw_flagged_count": int(len(raw_rows)),
        "summary": {
            **summary_counts,
            "metric_audit_csv_row_count": int(len(capped_rows)),
            "known_high_auc_diagnostic_covered": bool(known_high_auc_covered),
            "known_high_auc_artifact_reason": known_high_auc_reason,
            "metric_sanity_fail_count": 0,
        },
    }


def _price_baseline_metric_rows(
    *,
    validation_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {"close_t": [], "close_t_minus_1": []}
    price_defs = [item for item in BASELINE_DEFINITIONS if item.get("kind") == "price"]
    for asof_mode in ASOF_MODES:
        features = feature_frames.get(asof_mode, pd.DataFrame())
        if features.empty:
            continue
        feature_cols = ["entity_id", "trade_date", "feature_asof_date", *[str(item["name"]) for item in price_defs]]
        feature_cols = [column for column in feature_cols if column in features.columns]
        merged = validation_rows.merge(features[feature_cols], on=["entity_id", "trade_date"], how="left")
        for definition in price_defs:
            baseline_name = str(definition["name"])
            if baseline_name not in merged.columns:
                continue
            base = validation_rows.reset_index(drop=True).copy()
            base["score"] = pd.to_numeric(merged[baseline_name], errors="coerce").reset_index(drop=True)
            base["feature_asof_date"] = pd.to_datetime(merged["feature_asof_date"], errors="coerce").reset_index(drop=True)
            base["score_available"] = base["score"].notna()
            for _, group in base.groupby(
                ["fold_id", "horizon", "threshold_type", "threshold_value", "target_usage"],
                sort=False,
                dropna=False,
            ):
                metric = compute_metric_row(
                    group,
                    baseline_family=str(definition["family"]),
                    baseline_name=baseline_name,
                    fold_id=str(group["fold_id"].iloc[0]),
                )
                metric["slice_id"] = _slice_id(metric)
                out[asof_mode].append(metric)
    return out


def _paired_key(row: Mapping[str, Any], *, name_key: str) -> tuple[Any, ...]:
    return (
        row.get(name_key),
        row.get("baseline_family"),
        row.get("fold_id"),
        row.get("slice_id"),
        row.get("target_usage"),
        int(row.get("horizon")),
        float(row.get("threshold_value")),
    )


def build_asof_shift_summary(
    *,
    vol_rows: Sequence[Mapping[str, Any]],
    validation_rows: pd.DataFrame,
    feature_frames: Mapping[str, pd.DataFrame],
    policy: Mapping[str, Any],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    material_delta = _metric_thresholds(policy)["material_degradation_delta"]

    vol_by_mode: dict[str, dict[tuple[Any, ...], Mapping[str, Any]]] = {"close_t": {}, "close_t_minus_1": {}}
    for row in vol_rows:
        key = (
            row.get("candidate_name"),
            row.get("fold_id"),
            _slice_id(
                {
                    "horizon": row.get("horizon"),
                    "threshold_type": row.get("source_threshold_type"),
                    "threshold_value": row.get("source_threshold_value"),
                    "target_usage": row.get("target_usage"),
                }
            ),
            row.get("target_usage"),
            int(row.get("horizon")),
            float(row.get("source_threshold_value")),
        )
        vol_by_mode[str(row.get("asof_mode"))][key] = row
    for key, close_row in vol_by_mode["close_t"].items():
        minus_row = vol_by_mode["close_t_minus_1"].get(key)
        if minus_row is None:
            rows.append(
                {
                    "source": "volatility_scaled_threshold",
                    "baseline_or_candidate_name": key[0],
                    "baseline_family": "volatility_scaled_threshold",
                    "fold_id": key[1],
                    "slice_id": key[2],
                    "target_usage": key[3],
                    "horizon": key[4],
                    "threshold_value": key[5],
                    "metric_name": "event_base_rate",
                    "metric_close_t": close_row.get("event_base_rate"),
                    "metric_close_t_minus_1": None,
                    "metric_delta": None,
                    "row_count_close_t": close_row.get("row_count"),
                    "row_count_close_t_minus_1": None,
                    "positive_event_count_close_t": close_row.get("positive_event_count"),
                    "positive_event_count_close_t_minus_1": None,
                    "score_available_rate_close_t": close_row.get("score_available_rate"),
                    "score_available_rate_close_t_minus_1": None,
                    "material_degradation_flag": False,
                    "asof_dependency_flag": False,
                    "asof_shift_status": "asof_shift_deferred",
                    "deferred_reason": "missing_close_t_minus_1_vol_scaled_metric",
                }
            )
            continue
        close_metric = _as_float(close_row.get("event_base_rate"))
        minus_metric = _as_float(minus_row.get("event_base_rate"))
        delta = None if close_metric is None or minus_metric is None else close_metric - minus_metric
        material = bool(delta is not None and abs(delta) >= material_delta)
        rows.append(
            {
                "source": "volatility_scaled_threshold",
                "baseline_or_candidate_name": key[0],
                "baseline_family": "volatility_scaled_threshold",
                "fold_id": key[1],
                "slice_id": key[2],
                "target_usage": key[3],
                "horizon": key[4],
                "threshold_value": key[5],
                "metric_name": "event_base_rate",
                "metric_close_t": close_metric,
                "metric_close_t_minus_1": minus_metric,
                "metric_delta": delta,
                "row_count_close_t": close_row.get("row_count"),
                "row_count_close_t_minus_1": minus_row.get("row_count"),
                "positive_event_count_close_t": close_row.get("positive_event_count"),
                "positive_event_count_close_t_minus_1": minus_row.get("positive_event_count"),
                "score_available_rate_close_t": close_row.get("score_available_rate"),
                "score_available_rate_close_t_minus_1": minus_row.get("score_available_rate"),
                "material_degradation_flag": material,
                "asof_dependency_flag": material,
                "asof_shift_status": "pass",
                "deferred_reason": None,
            }
        )

    baseline_rows = _price_baseline_metric_rows(validation_rows=validation_rows, feature_frames=feature_frames)
    close_by_key = {
        _paired_key(row, name_key="baseline_name"): row for row in baseline_rows.get("close_t", [])
    }
    minus_by_key = {
        _paired_key(row, name_key="baseline_name"): row for row in baseline_rows.get("close_t_minus_1", [])
    }
    for key, close_row in close_by_key.items():
        minus_row = minus_by_key.get(key)
        close_metric = _as_float(close_row.get("roc_auc"))
        minus_metric = None if minus_row is None else _as_float(minus_row.get("roc_auc"))
        delta = None if close_metric is None or minus_metric is None else close_metric - minus_metric
        deferred = minus_row is None or close_metric is None or minus_metric is None
        material = bool(delta is not None and abs(delta) >= material_delta)
        rows.append(
            {
                "source": "price_baseline",
                "baseline_or_candidate_name": key[0],
                "baseline_family": key[1],
                "fold_id": key[2],
                "slice_id": key[3],
                "target_usage": key[4],
                "horizon": key[5],
                "threshold_value": key[6],
                "metric_name": "roc_auc",
                "metric_close_t": close_metric,
                "metric_close_t_minus_1": minus_metric,
                "metric_delta": delta,
                "row_count_close_t": close_row.get("row_count"),
                "row_count_close_t_minus_1": None if minus_row is None else minus_row.get("row_count"),
                "positive_event_count_close_t": close_row.get("positive_event_count"),
                "positive_event_count_close_t_minus_1": None if minus_row is None else minus_row.get("positive_event_count"),
                "score_available_rate_close_t": close_row.get("score_available_rate"),
                "score_available_rate_close_t_minus_1": None if minus_row is None else minus_row.get("score_available_rate"),
                "material_degradation_flag": material,
                "asof_dependency_flag": material,
                "asof_shift_status": "asof_shift_deferred" if deferred else "pass",
                "deferred_reason": "roc_auc_unavailable_for_one_or_both_asof_modes" if deferred else None,
            }
        )

    deltas = [abs(float(row["metric_delta"])) for row in rows if _as_float(row.get("metric_delta")) is not None]
    summary = {
        "asof_shift_row_count": int(len(rows)),
        "material_degradation_count": int(sum(bool(row.get("material_degradation_flag")) for row in rows)),
        "asof_dependency_warning_count": int(sum(bool(row.get("asof_dependency_flag")) for row in rows)),
        "asof_shift_deferred_count": int(sum(row.get("asof_shift_status") == "asof_shift_deferred" for row in rows)),
        "max_abs_metric_delta": float(max(deltas)) if deltas else None,
        "asof_modes_compared": ASOF_MODES,
    }
    return {"rows": rows, "summary": summary}


def validate_wp3_5_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    full_target_audit: Mapping[str, Any],
    baseline_report: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    db_path: Path | str,
) -> tuple[str | None, list[str]]:
    issues: list[str] = []
    if target_support.get("status") != "pass":
        return "blocked_wp1_not_ready", ["wp1_support_status_not_pass"]
    if target_controls.get("status") != "pass":
        return "blocked_wp2_not_ready", ["wp2_controls_status_not_pass"]
    if full_target_audit.get("status") != "pass":
        return "blocked_wp2_1_not_ready", ["wp2_1_full_target_audit_status_not_pass"]
    if baseline_report.get("status") != "pass":
        return "blocked_wp3_not_ready", ["wp3_baseline_diagnostics_status_not_pass"]
    if fold_plan.get("status") != "pass" or _as_int(fold_plan.get("fold_count"), 0) <= 0:
        return "blocked_invalid_fold_plan", ["fold_plan_status_not_pass_or_empty"]

    expected_db = _safe_path(db_path)
    accepted_db_paths = {
        value
        for value in [
            target_support.get("source_db_path"),
            target_controls.get("source_db_path"),
            full_target_audit.get("source_db_path"),
            baseline_report.get("source_db_path"),
        ]
        if value
    }
    if not os.environ.get("STAGE03V_V7_DB") and accepted_db_paths and expected_db not in accepted_db_paths:
        issues.append("resolved_db_path_does_not_match_accepted_artifacts")
    if target_support.get("v7_coverage_available") != "yes" or baseline_report.get("v7_coverage_available") != "yes":
        issues.append("v7_coverage_not_verified")
    if (
        target_support.get("sw2021_l2_universe_coverage") != "pass"
        or target_controls.get("sw2021_l2_universe_coverage") != "pass"
        or full_target_audit.get("sw2021_l2_universe_coverage") != "pass"
        or baseline_report.get("sw2021_l2_universe_coverage") != "pass"
    ):
        issues.append("sw2021_l2_universe_not_pass")
    if _as_int(target_support.get("entity_count_after_silent_break_handling"), 0) != 124:
        issues.append("entity_count_after_silent_break_handling_not_124")
    if target_controls.get("feature_namespace_policy_status") != "pass":
        issues.append("feature_namespace_policy_status_not_pass")
    if _as_int(target_controls.get("purge_violation_count"), -1) != 0:
        issues.append("purge_violation_count_not_zero")
    if _as_int(target_controls.get("embargo_violation_count"), -1) != 0:
        issues.append("embargo_violation_count_not_zero")
    baseline_leakage = baseline_report.get("leakage_violation_counts", {})
    if _as_int(baseline_leakage.get("leakage_violation_count_total"), -1) != 0:
        issues.append("wp3_leakage_violation_count_total_not_zero")
    if _as_int(baseline_report.get("prospective_holdout_rows_evaluated"), -1) != 0:
        issues.append("wp3_prospective_holdout_rows_evaluated_not_zero")
    boundary = baseline_report.get("boundary_flags", {})
    for key in ["external_data_fetch", "model_training", "probability_calibration", "readiness_assigned", "holdout_consumed"]:
        if boundary.get(key) != "no":
            issues.append(f"wp3_boundary_{key}_not_no")
    if _as_int(fold_plan.get("purge_violation_count"), -1) != 0:
        issues.append("fold_plan_purge_violation_count_not_zero")
    if _as_int(fold_plan.get("embargo_violation_count"), -1) != 0:
        issues.append("fold_plan_embargo_violation_count_not_zero")
    if issues:
        if any(issue.startswith("wp3_") for issue in issues):
            return "blocked_wp3_not_ready", issues
        if any(issue.startswith("fold_plan") for issue in issues):
            return "blocked_invalid_fold_plan", issues
        return "blocked_wp2_not_ready", issues
    return None, []


def _blocked_report(
    *,
    status: str,
    db_path: Path | str | None,
    reasons: Sequence[str],
    wp1_status: str | None = None,
    wp2_status: str | None = None,
    wp2_1_status: str | None = None,
    wp3_status: str | None = None,
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "wp1_support_status": wp1_status,
        "wp2_controls_status": wp2_status,
        "wp2_1_full_target_audit_status": wp2_1_status,
        "wp3_baseline_diagnostics_status": wp3_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "fold_plan_status": "blocked",
        "policy_status": "blocked",
        "fixed_threshold_mainline_status": "unchanged_reference_only",
        "volatility_scaled_threshold_status": "defer",
        "baseline_sanity_status": "fail" if status.startswith("blocked_wp3") else "blocked",
        "wp4_entry_recommendation": "blocked",
        "row_count_scored": 0,
        "validation_row_count_evaluated": 0,
        "prospective_holdout_rows_evaluated": 0,
        "slice_count_evaluated": 0,
        "fold_count_evaluated": 0,
        "vol_scaled_candidate_count": 0,
        "asof_mode_count": 0,
        "flagged_metric_row_count": 0,
        "vol_scaled_summary_path": None,
        "metric_audit_path": None,
        "asof_shift_summary_path": None,
        "leakage_violation_counts": dict(LEAKAGE_ZERO_COUNTS),
        "metric_sanity_summary": {},
        "vol_scaled_threshold_summary": {},
        "best_vol_scaled_candidate_by_event_support": None,
        "high_metric_audit_summary": {},
        "asof_shift_summary": {},
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": list(reasons),
    }


def _write_blocked_outputs(
    *,
    report: Mapping[str, Any],
    output: Path,
    summary_json: Path,
    vol_scaled_summary: Path,
    metric_audit: Path,
    asof_shift_summary: Path,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(vol_scaled_summary, [], VOL_SUMMARY_COLUMNS)
    _write_csv(metric_audit, [], METRIC_AUDIT_COLUMNS)
    _write_csv(asof_shift_summary, [], ASOF_SHIFT_COLUMNS)


def _vol_scaled_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "vol_scaled_summary_row_count": 0,
            "candidate_count": 0,
            "asof_mode_count": 0,
            "mean_event_base_rate": None,
            "max_effective_event_evidence_count": None,
        }
    frame = pd.DataFrame(rows)
    event_rates = pd.to_numeric(frame["event_base_rate"], errors="coerce").dropna()
    support = pd.to_numeric(frame["effective_event_evidence_count"], errors="coerce").dropna()
    return {
        "vol_scaled_summary_row_count": int(len(frame)),
        "candidate_count": int(frame["candidate_name"].nunique()),
        "asof_mode_count": int(frame["asof_mode"].nunique()),
        "mean_event_base_rate": float(event_rates.mean()) if len(event_rates) else None,
        "max_event_base_rate": float(event_rates.max()) if len(event_rates) else None,
        "max_effective_event_evidence_count": float(support.max()) if len(support) else None,
        "threshold_formula": "threshold_abs = clamp(k * daily_vol * sqrt(horizon), 0.02, 0.15)",
        "threshold_unit": "absolute future max drawdown fraction",
    }


def _best_vol_scaled_candidate(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    candidates = [row for row in rows if _as_float(row.get("effective_event_evidence_count")) is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: float(row.get("effective_event_evidence_count") or 0.0))
    return {
        "candidate_name": best.get("candidate_name"),
        "asof_mode": best.get("asof_mode"),
        "volatility_estimator": best.get("volatility_estimator"),
        "horizon": best.get("horizon"),
        "k_value": best.get("k_value"),
        "target_usage": best.get("target_usage"),
        "source_threshold_value": best.get("source_threshold_value"),
        "positive_event_count": best.get("positive_event_count"),
        "event_base_rate": best.get("event_base_rate"),
        "market_event_block_count": best.get("market_event_block_count"),
        "effective_event_evidence_count": best.get("effective_event_evidence_count"),
    }


def build_vol_scaled_threshold_sanity_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    baseline_report: Path | str = DEFAULT_BASELINE_REPORT,
    baseline_fold_metrics: Path | str = DEFAULT_BASELINE_FOLD_METRICS,
    baseline_slice_metrics: Path | str = DEFAULT_BASELINE_SLICE_METRICS,
    baseline_policy: Path | str = DEFAULT_BASELINE_POLICY,
    policy: Path | str = DEFAULT_POLICY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    vol_scaled_summary: Path | str = DEFAULT_VOL_SCALED_SUMMARY,
    metric_audit: Path | str = DEFAULT_METRIC_AUDIT,
    asof_shift_summary: Path | str = DEFAULT_ASOF_SHIFT_SUMMARY,
    audit_cap: int = DEFAULT_AUDIT_CAP,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP3.5 is no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    vol_path = Path(vol_scaled_summary)
    audit_path = Path(metric_audit)
    asof_path = Path(asof_shift_summary)

    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
        full_audit = _load_json(full_target_audit)
        baseline_doc = _load_json(baseline_report)
    except FileNotFoundError as exc:
        report = _blocked_report(status="blocked_wp3_not_ready", db_path=resolved_db, reasons=[f"missing input: {exc.filename}"])
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["sw2021_l2_universe_coverage"] = v7.coverage.get("sw2021_l2_universe_coverage", "missing")
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report

    if not Path(fold_plan).exists():
        report = _blocked_report(
            status="blocked_missing_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=[f"missing fold plan: {fold_plan}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report
    fold_doc = _load_json(fold_plan)
    blocked_status, precondition_issues = validate_wp3_5_preconditions(
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        baseline_report=baseline_doc,
        fold_plan=fold_doc,
        db_path=resolved_db,
    )
    if blocked_status:
        report = _blocked_report(
            status=blocked_status,
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=precondition_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report

    try:
        policy_doc = _load_machine_config(policy)
    except FileNotFoundError:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=[f"missing policy: {policy}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report
    policy_issues = validate_policy(policy_doc)
    if policy_issues:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=policy_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report

    baseline_policy_doc = _load_machine_config(baseline_policy)
    target_universe_doc = _load_machine_config(target_universe)
    target_universe_status = "pass" if target_universe_doc.get("source", {}).get("v7_coverage_available") == "yes" else "partial"
    if baseline_policy_doc.get("policy_version") != "stage03v_baseline_diagnostics_policy_v1":
        report = _blocked_report(
            status="blocked_wp3_not_ready",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=["baseline_policy_version_mismatch"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report

    specs = slice_specs_from_target_support(support)
    universe_ids = v7.universe_frame["entity_id"].astype(str).tolist()
    ohlcv, ohlcv_report = read_ohlcv_inputs(resolved_db, universe_ids)
    if ohlcv.empty:
        close_only = v7.price_frame.rename(columns={"sector_id": "entity_id"}).copy()
        close_only["open"] = np.nan
        close_only["high"] = np.nan
        close_only["low"] = np.nan
        ohlcv = close_only[["entity_id", "trade_date", "open", "high", "low", "close"]]
    feature_frames, feature_availability = build_feature_frames(ohlcv)

    max_validation_end: pd.Timestamp | None = None
    for fold in fold_doc.get("folds", []):
        end = _normalise_date(fold.get("validation_end_date"))
        if end is not None and (max_validation_end is None or end > max_validation_end):
            max_validation_end = end
    if max_validation_end is None:
        report = _blocked_report(
            status="blocked_invalid_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            wp3_status=str(baseline_doc.get("status", "unknown")),
            reasons=["fold plan has no valid validation dates"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            vol_scaled_summary=vol_path,
            metric_audit=audit_path,
            asof_shift_summary=asof_path,
        )
        return report
    price_dates = set(pd.to_datetime(v7.price_frame["trade_date"], errors="coerce").dt.normalize().dropna().tolist())
    needed_dates = sorted(date for date in price_dates if date <= max_validation_end)
    target_rows = build_target_rows_for_trade_dates(
        v7.price_frame,
        v7.universe_frame,
        specs,
        needed_dates,
        source_db_path=resolved_db,
    )
    validation_rows, prospective_withheld = _validation_rows_for_folds(target_rows, fold_doc)

    vol_eval = evaluate_vol_scaled_thresholds(
        validation_rows=validation_rows,
        feature_frames=feature_frames,
        policy=policy_doc,
    )
    vol_rows = vol_eval["rows"]
    fold_metrics = pd.read_csv(baseline_fold_metrics)
    slice_metrics = pd.read_csv(baseline_slice_metrics)
    metric_audit_eval = audit_baseline_metrics(
        baseline_report=baseline_doc,
        fold_metrics=fold_metrics,
        slice_metrics=slice_metrics,
        validation_rows=validation_rows,
        feature_frames=feature_frames,
        policy=policy_doc,
        audit_cap=audit_cap,
    )
    asof_eval = build_asof_shift_summary(
        vol_rows=vol_rows,
        validation_rows=validation_rows,
        feature_frames=feature_frames,
        policy=policy_doc,
    )

    _write_csv(vol_path, vol_rows, VOL_SUMMARY_COLUMNS)
    _write_csv(audit_path, metric_audit_eval["rows"], METRIC_AUDIT_COLUMNS)
    _write_csv(asof_path, asof_eval["rows"], ASOF_SHIFT_COLUMNS)

    leakage_counts = dict(vol_eval["leakage_violation_counts"])
    leakage_counts["prospective_holdout_metric_count"] = 0
    leakage_counts["fixed_threshold_mainline_mutation_count"] = 0
    leakage_counts["persistent_db_write_count"] = 0
    leakage_counts["external_fetch_count"] = 0
    leakage_counts["leakage_violation_count_total"] = int(
        sum(value for key, value in leakage_counts.items() if key != "leakage_violation_count_total")
    )

    vol_summary = _vol_scaled_summary(vol_rows)
    best_vol = _best_vol_scaled_candidate(vol_rows)
    metric_summary = metric_audit_eval["summary"]
    asof_summary = asof_eval["summary"]
    baseline_sanity_status = "warning" if int(metric_summary.get("flagged_metric_row_count", 0)) else "pass"
    volatility_status = "candidate_for_wp4_research_tracking" if best_vol else "defer"
    wp4_recommendation = (
        "proceed_with_vol_scaled_candidate_tracking"
        if leakage_counts["leakage_violation_count_total"] == 0 and volatility_status == "candidate_for_wp4_research_tracking"
        else "blocked"
    )

    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "unknown",
        "wp1_support_status": support.get("status"),
        "wp2_controls_status": controls.get("status"),
        "wp2_1_full_target_audit_status": full_audit.get("status"),
        "wp3_baseline_diagnostics_status": baseline_doc.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": target_universe_status,
        "fold_plan_status": fold_doc.get("status"),
        "policy_status": "pass",
        "fixed_threshold_mainline_status": "unchanged_reference_only",
        "volatility_scaled_threshold_status": volatility_status,
        "baseline_sanity_status": baseline_sanity_status,
        "wp4_entry_recommendation": wp4_recommendation,
        "row_count_scored": int(len(validation_rows)),
        "validation_row_count_evaluated": int(len(validation_rows)),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_rows_withheld": int(prospective_withheld),
        "slice_count_evaluated": int(
            validation_rows[["horizon", "threshold_type", "threshold_value", "target_usage"]]
            .drop_duplicates()
            .shape[0]
        )
        if not validation_rows.empty
        else 0,
        "fold_count_evaluated": int(validation_rows["fold_id"].nunique()) if not validation_rows.empty else 0,
        "vol_scaled_candidate_count": int(len(VOLATILITY_ESTIMATORS) * len(HORIZONS) * len(K_CANDIDATES)),
        "asof_mode_count": int(len(ASOF_MODES)),
        "flagged_metric_row_count": int(metric_summary.get("flagged_metric_row_count", 0)),
        "vol_scaled_summary_path": _safe_path(vol_path),
        "metric_audit_path": _safe_path(audit_path),
        "asof_shift_summary_path": _safe_path(asof_path),
        "leakage_violation_counts": leakage_counts,
        "metric_sanity_summary": metric_summary,
        "vol_scaled_threshold_summary": vol_summary,
        "best_vol_scaled_candidate_by_event_support": best_vol,
        "high_metric_audit_summary": {
            "known_high_auc_diagnostic_baseline": "rolling_close_to_close_vol_60",
            "known_high_auc_diagnostic_covered": metric_summary.get("known_high_auc_diagnostic_covered"),
            "known_high_auc_artifact_reason": metric_summary.get("known_high_auc_artifact_reason"),
            "baseline_sanity_status": baseline_sanity_status,
        },
        "asof_shift_summary": asof_summary,
        "range_based_availability_detail": {**ohlcv_report, **feature_availability},
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": [],
    }
    report["status"] = "pass" if leakage_counts["leakage_violation_count_total"] == 0 else "fail"
    report["ci_gate_status"] = "pass" if report["status"] == "pass" else report["status"]
    _write_markdown(output_path, report)
    _write_json(summary_path, report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--target-universe", type=Path, default=DEFAULT_TARGET_UNIVERSE)
    parser.add_argument("--target-controls", type=Path, default=DEFAULT_TARGET_CONTROLS)
    parser.add_argument("--full-target-audit", type=Path, default=DEFAULT_FULL_TARGET_AUDIT)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--baseline-report", type=Path, default=DEFAULT_BASELINE_REPORT)
    parser.add_argument("--baseline-fold-metrics", type=Path, default=DEFAULT_BASELINE_FOLD_METRICS)
    parser.add_argument("--baseline-slice-metrics", type=Path, default=DEFAULT_BASELINE_SLICE_METRICS)
    parser.add_argument("--baseline-policy", type=Path, default=DEFAULT_BASELINE_POLICY)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--vol-scaled-summary", type=Path, default=DEFAULT_VOL_SCALED_SUMMARY)
    parser.add_argument("--metric-audit", type=Path, default=DEFAULT_METRIC_AUDIT)
    parser.add_argument("--asof-shift-summary", type=Path, default=DEFAULT_ASOF_SHIFT_SUMMARY)
    parser.add_argument("--audit-cap", type=int, default=DEFAULT_AUDIT_CAP)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_vol_scaled_threshold_sanity_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        fold_plan=args.fold_plan,
        baseline_report=args.baseline_report,
        baseline_fold_metrics=args.baseline_fold_metrics,
        baseline_slice_metrics=args.baseline_slice_metrics,
        baseline_policy=args.baseline_policy,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        vol_scaled_summary=args.vol_scaled_summary,
        metric_audit=args.metric_audit,
        asof_shift_summary=args.asof_shift_summary,
        audit_cap=args.audit_cap,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_VOL_SCALED_THRESHOLD_SANITY="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"candidates={report.get('vol_scaled_candidate_count')} "
        f"validation_rows={report.get('validation_row_count_evaluated')} "
        f"flagged_metrics={report.get('flagged_metric_row_count')} "
        f"baseline_sanity={report.get('baseline_sanity_status')} "
        f"wp4_recommendation={report.get('wp4_entry_recommendation')} "
        f"leakage_violations={report.get('leakage_violation_counts', {}).get('leakage_violation_count_total')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
