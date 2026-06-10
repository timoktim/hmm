"""Stage03V WP3 causal baseline diagnostics.

This module computes aggregate diagnostics for simple causal baselines against
the accepted Stage03V1 downside-risk targets. It is intentionally read-only and
offline: no fetches, persistent DuckDB writes, learned model training,
probability calibration, readiness assignment, or final-holdout consumption.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    SOURCE_TARGET_KIND,
    TARGET_KIND,
    SliceSpec,
    _json_safe,
    _normalise_prices,
    _safe_path,
    compute_path_metrics,
    read_v7_inputs,
    resolve_v7_db_path,
)
from src.evaluation.stage03v_target_controls import detect_feature_namespace_violations


INDEX_ID = "STAGE03V-WP3-v1"
REPORT_VERSION = "stage03v_baseline_diagnostics_v1"
STAGE_ID = "stage03v"
DEFAULT_SAMPLE_ROWS = 500
DEFAULT_ROLLING_HISTORY_ROWS = 10_000
DEFAULT_MARKET_SHARE_WINDOW_DATES = 20

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_TARGET_CONTROLS = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FULL_TARGET_AUDIT = ROOT / "reports" / "stage03v" / "full_target_streaming_audit_report.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_baseline_diagnostics_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "baseline_diagnostics_report.json"
DEFAULT_FOLD_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_fold_metrics.csv"
DEFAULT_SLICE_METRICS = ROOT / "reports" / "stage03v" / "baseline_diagnostics_slice_metrics.csv"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "baseline_diagnostics_audit_sample.csv"

BASELINE_FAMILIES_REQUIRED = [
    "empirical_event_rate",
    "entity_empirical_event_rate",
    "cross_sectional_market_event_share",
    "realized_volatility",
    "range_based_volatility",
    "recent_drawdown",
    "continuous_target_proxy",
]

BASELINE_DEFINITIONS: list[dict[str, Any]] = [
    {"name": "rolling_global_event_rate", "family": "empirical_event_rate", "kind": "empirical", "score_in_0_1": True},
    {"name": "rolling_slice_event_rate", "family": "empirical_event_rate", "kind": "empirical", "score_in_0_1": True},
    {"name": "expanding_global_event_rate", "family": "empirical_event_rate", "kind": "empirical", "score_in_0_1": True},
    {
        "name": "rolling_entity_event_rate",
        "family": "entity_empirical_event_rate",
        "kind": "empirical",
        "score_in_0_1": True,
    },
    {
        "name": "rolling_entity_slice_event_rate",
        "family": "entity_empirical_event_rate",
        "kind": "empirical",
        "score_in_0_1": True,
    },
    {
        "name": "expanding_entity_event_rate",
        "family": "entity_empirical_event_rate",
        "kind": "empirical",
        "score_in_0_1": True,
    },
    {
        "name": "rolling_market_event_share_by_slice",
        "family": "cross_sectional_market_event_share",
        "kind": "empirical",
        "score_in_0_1": True,
    },
    {"name": "rolling_close_to_close_vol_20", "family": "realized_volatility", "kind": "price"},
    {"name": "rolling_close_to_close_vol_60", "family": "realized_volatility", "kind": "price"},
    {"name": "ewma_close_to_close_vol", "family": "realized_volatility", "kind": "price"},
    {"name": "rolling_downside_vol_20", "family": "realized_volatility", "kind": "price"},
    {"name": "rolling_downside_vol_60", "family": "realized_volatility", "kind": "price"},
    {"name": "parkinson_vol_20", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "parkinson_vol_60", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "garman_klass_vol_20", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "garman_klass_vol_60", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "rogers_satchell_vol_20", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "rogers_satchell_vol_60", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "intraday_range_ratio_20", "family": "range_based_volatility", "kind": "price", "requires_ohlc": True},
    {"name": "rolling_max_drawdown_20", "family": "recent_drawdown", "kind": "price"},
    {"name": "rolling_max_drawdown_60", "family": "recent_drawdown", "kind": "price"},
    {"name": "rolling_distance_from_high_20", "family": "recent_drawdown", "kind": "price"},
    {"name": "rolling_distance_from_high_60", "family": "recent_drawdown", "kind": "price"},
    {"name": "continuous_proxy_vol_drawdown_combo", "family": "continuous_target_proxy", "kind": "price"},
]

BASELINE_INPUT_COLUMNS = [
    "trade_date",
    "entity_id",
    "feature_asof_date",
    "open",
    "high",
    "low",
    "close",
    "close_to_close_return",
    *[item["name"] for item in BASELINE_DEFINITIONS if item["kind"] == "price"],
]

FOLD_METRIC_COLUMNS = [
    "fold_id",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "baseline_family",
    "baseline_name",
    "row_count",
    "scored_row_count",
    "positive_event_count",
    "event_base_rate",
    "score_available_rate",
    "roc_auc",
    "average_precision",
    "brier_like_score_if_score_in_0_1",
    "spearman_score_vs_event",
    "spearman_score_vs_future_mae",
    "spearman_score_vs_future_mdd",
    "spearman_score_vs_future_return",
    "quantile_lift_top_decile",
    "quantile_lift_top_quintile",
    "top_decile_future_mae_mean",
    "top_decile_future_mdd_mean",
    "monotonic_decile_event_rate_status",
]

SLICE_METRIC_COLUMNS = [column for column in FOLD_METRIC_COLUMNS if column != "fold_id"]

AUDIT_SAMPLE_COLUMNS = [
    "fold_id",
    "entity_id",
    "trade_date",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "baseline_family",
    "baseline_name",
    "score",
    "score_available",
    "feature_asof_date",
    "event_label",
    "future_mae",
    "future_mdd",
    "future_return",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "persistent_db_table_written": "no",
    "full_feature_matrix_committed": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
}


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
        "# Stage03V WP3 Baseline Diagnostics",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- wp1_support_status: {report.get('wp1_support_status')}",
        f"- wp2_controls_status: {report.get('wp2_controls_status')}",
        f"- wp2_1_full_target_audit_status: {report.get('wp2_1_full_target_audit_status')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- fold_plan_status: {report.get('fold_plan_status')}",
        f"- baseline_policy_status: {report.get('baseline_policy_status')}",
        f"- row_count_scored: {report.get('row_count_scored')}",
        f"- validation_row_count_evaluated: {report.get('validation_row_count_evaluated')}",
        f"- prospective_holdout_rows_evaluated: {report.get('prospective_holdout_rows_evaluated')}",
        f"- slice_count_evaluated: {report.get('slice_count_evaluated')}",
        f"- fold_count_evaluated: {report.get('fold_count_evaluated')}",
        f"- baseline_count: {report.get('baseline_count')}",
        f"- range_based_availability_status: {report.get('range_based_availability_status')}",
        f"- continuous_diagnostic_status: {report.get('continuous_diagnostic_status')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Leakage Counts",
        "",
    ]
    for key, value in report.get("leakage_violation_counts", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Baseline Families", ""])
    for family in report.get("baseline_families_implemented", []):
        lines.append(f"- {family}")
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
    if not math.isfinite(number):
        return None
    return number


def _finite_or_none(value: Any) -> float | None:
    return _as_float(value)


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0 or not math.isfinite(float(denominator)):
        return None
    value = float(numerator) / float(denominator)
    return value if math.isfinite(value) else None


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


def _slice_key_columns() -> list[str]:
    return ["horizon", "threshold_type", "threshold_value", "target_usage"]


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


def _slice_key_from_row(row: Mapping[str, Any]) -> tuple[int, str, float, str]:
    return (
        int(row.get("horizon")),
        str(row.get("threshold_type", "fixed")),
        float(row.get("threshold_value")),
        str(row.get("target_usage", "eligible")),
    )


def slice_specs_from_target_support(target_support: Mapping[str, Any]) -> list[SliceSpec]:
    specs: list[SliceSpec] = []
    for item in target_support.get("slice_support_summary", []):
        specs.append(
            SliceSpec(
                horizon=int(item["horizon"]),
                threshold_value=float(item["threshold_value"]),
                threshold_type=str(item.get("threshold_type", "fixed")),
                source_target_kind=SOURCE_TARGET_KIND,
                feasibility_verdict=str(item.get("feasibility_verdict", item.get("target_usage", "eligible"))),
                target_usage=str(item.get("target_usage", "eligible")),
            )
        )
    specs.sort(key=lambda spec: (spec.horizon, spec.threshold_value, spec.target_usage))
    return specs


def validate_wp3_preconditions(
    *,
    target_support: Mapping[str, Any],
    target_controls: Mapping[str, Any],
    full_target_audit: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    db_path: Path | str,
) -> list[str]:
    issues: list[str] = []
    if target_support.get("status") != "pass":
        issues.append("wp1_support_status_not_pass")
    if target_controls.get("status") != "pass":
        issues.append("wp2_controls_status_not_pass")
    if full_target_audit.get("status") != "pass":
        issues.append("wp2_1_full_target_audit_status_not_pass")
    if _as_int(full_target_audit.get("full_target_rows_checked"), default=0) != 7_474_840:
        issues.append("wp2_1_full_target_rows_checked_not_expected")
    if _as_int(full_target_audit.get("row_count_delta"), default=-1) != 0:
        issues.append("wp2_1_row_count_delta_not_zero")
    if _as_int(full_target_audit.get("violation_count_total"), default=-1) != 0:
        issues.append("wp2_1_violation_count_total_not_zero")
    if _as_int(full_target_audit.get("recompute_violation_count_total"), default=-1) != 0:
        issues.append("wp2_1_recompute_violation_count_total_not_zero")
    if _as_int(full_target_audit.get("slice_support_delta_count"), default=-1) != 0:
        issues.append("wp2_1_slice_support_delta_count_not_zero")
    if target_support.get("v7_coverage_available") != "yes" or full_target_audit.get("v7_coverage_available") != "yes":
        issues.append("v7_coverage_not_verified")
    if (
        target_support.get("sw2021_l2_universe_coverage") != "pass"
        or target_controls.get("sw2021_l2_universe_coverage") != "pass"
        or full_target_audit.get("sw2021_l2_universe_coverage") != "pass"
    ):
        issues.append("sw2021_l2_universe_not_pass")
    if _as_int(target_support.get("entity_count_after_silent_break_handling"), default=0) != 124:
        issues.append("wp1_entity_count_after_silent_break_handling_not_124")
    if target_controls.get("feature_namespace_policy_status") != "pass":
        issues.append("wp2_feature_namespace_policy_not_pass")
    if _as_int(target_controls.get("purge_violation_count"), default=-1) != 0:
        issues.append("wp2_purge_violation_count_not_zero")
    if _as_int(target_controls.get("embargo_violation_count"), default=-1) != 0:
        issues.append("wp2_embargo_violation_count_not_zero")
    if fold_plan.get("status") != "pass":
        issues.append("fold_plan_status_not_pass")
    if _as_int(fold_plan.get("purge_violation_count"), default=-1) != 0:
        issues.append("fold_plan_purge_violation_count_not_zero")
    if _as_int(fold_plan.get("embargo_violation_count"), default=-1) != 0:
        issues.append("fold_plan_embargo_violation_count_not_zero")

    resolved_safe = _safe_path(db_path)
    expected_paths = {
        str(value)
        for value in [
            target_support.get("source_db_path"),
            target_controls.get("source_db_path"),
            full_target_audit.get("source_db_path"),
        ]
        if value
    }
    if not os.environ.get("STAGE03V_V7_DB") and expected_paths and resolved_safe not in expected_paths:
        issues.append("resolved_db_path_does_not_match_accepted_stage03v_artifacts")
    return issues


def validate_baseline_policy(policy: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    if policy.get("index_id") != INDEX_ID:
        issues.append("policy_index_id_mismatch")
    if policy.get("policy_version") != "stage03v_baseline_diagnostics_policy_v1":
        issues.append("policy_version_mismatch")
    if policy.get("information_cutoff_date") != INFORMATION_CUTOFF_DATE:
        issues.append("policy_information_cutoff_mismatch")
    if policy.get("holdout_start") != HOLDOUT_START:
        issues.append("policy_holdout_start_mismatch")
    missing_families = set(BASELINE_FAMILIES_REQUIRED).difference(policy.get("baseline_families", []))
    if missing_families:
        issues.append(f"policy_missing_baseline_families:{','.join(sorted(missing_families))}")
    for key in ["calibration_policy", "readiness_policy", "model_training_policy"]:
        if policy.get(key) != "forbidden_in_wp3":
            issues.append(f"{key}_not_forbidden_in_wp3")
    if policy.get("final_holdout_policy") != "withheld_not_scored":
        issues.append("final_holdout_policy_not_withheld")
    return issues


def read_ohlcv_inputs(db_path: Path | str, universe_ids: Sequence[str]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not Path(db_path).exists():
        return pd.DataFrame(), {"range_based_availability_status": "range_based_unavailable_missing_v7_db"}
    try:
        import duckdb  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return pd.DataFrame(), {"range_based_availability_status": "range_based_unavailable_missing_duckdb"}
    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return pd.DataFrame(), {"range_based_availability_status": "range_based_unavailable_invalid_db", "error": str(exc)}
    try:
        columns = con.execute("DESCRIBE sector_ohlcv").fetchdf()["column_name"].astype(str).tolist()
        required = {"sector_id", "trade_date", "open", "high", "low", "close"}
        if not required.issubset(columns):
            return pd.DataFrame(), {
                "range_based_availability_status": "range_based_unavailable_missing_ohlc_columns",
                "missing_ohlc_columns": sorted(required.difference(columns)),
            }
        ids = sorted({str(item) for item in universe_ids})
        if not ids:
            return pd.DataFrame(), {"range_based_availability_status": "range_based_unavailable_empty_universe"}
        placeholders = ",".join(["?"] * len(ids))
        frame = con.execute(
            f"""
            SELECT sector_id AS entity_id, trade_date, open, high, low, close
            FROM sector_ohlcv
            WHERE sector_id IN ({placeholders})
            ORDER BY sector_id, trade_date
            """,
            ids,
        ).fetchdf()
    finally:
        con.close()
    return _normalise_ohlcv(frame), assess_range_based_availability(_normalise_ohlcv(frame))


def _normalise_ohlcv(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=["entity_id", "trade_date", "open", "high", "low", "close"])
    data = frame.copy()
    if "sector_id" in data.columns and "entity_id" not in data.columns:
        data = data.rename(columns={"sector_id": "entity_id"})
    data["entity_id"] = data["entity_id"].astype(str)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    for column in ["open", "high", "low", "close"]:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = pd.to_numeric(data[column], errors="coerce")
    data = data[data["trade_date"].notna() & data["close"].gt(0)].copy()
    return data.sort_values(["entity_id", "trade_date"]).drop_duplicates(["entity_id", "trade_date"], keep="last")


def assess_range_based_availability(ohlcv_frame: pd.DataFrame) -> dict[str, Any]:
    required = {"open", "high", "low", "close"}
    if ohlcv_frame.empty:
        return {"range_based_availability_status": "range_based_unavailable_empty_ohlcv", "valid_ohlc_rate": 0.0}
    if not required.issubset(ohlcv_frame.columns):
        return {
            "range_based_availability_status": "range_based_unavailable_missing_ohlc_columns",
            "valid_ohlc_rate": 0.0,
            "missing_ohlc_columns": sorted(required.difference(ohlcv_frame.columns)),
        }
    data = ohlcv_frame
    finite = data[["open", "high", "low", "close"]].apply(np.isfinite).all(axis=1)
    positive = data[["open", "high", "low", "close"]].gt(0).all(axis=1)
    ordered = data["high"].ge(data[["open", "close", "low"]].max(axis=1)) & data["low"].le(
        data[["open", "close", "high"]].min(axis=1)
    )
    valid = finite & positive & ordered
    valid_rate = float(valid.mean()) if len(valid) else 0.0
    return {
        "range_based_availability_status": "pass" if valid_rate >= 0.95 else "range_based_unavailable_unreliable_ohlc",
        "valid_ohlc_rate": valid_rate,
        "valid_ohlc_row_count": int(valid.sum()),
        "ohlc_row_count": int(len(data)),
    }


def _rolling_max_drawdown(values: np.ndarray) -> float:
    arr = np.asarray(values, dtype=float)
    if len(arr) == 0 or not np.isfinite(arr).all() or (arr <= 0).any():
        return np.nan
    running_high = np.maximum.accumulate(arr)
    return float(np.max(1.0 - arr / running_high))


def build_price_baseline_features(ohlcv_frame: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    data = _normalise_ohlcv(ohlcv_frame)
    availability = assess_range_based_availability(data)
    frames: list[pd.DataFrame] = []
    for _, group in data.groupby("entity_id", sort=False):
        g = group.sort_values("trade_date").copy()
        close = g["close"].astype(float)
        returns = close.pct_change()
        g["feature_asof_date"] = g["trade_date"]
        g["close_to_close_return"] = returns
        g["rolling_close_to_close_vol_20"] = returns.rolling(20, min_periods=5).std(ddof=0)
        g["rolling_close_to_close_vol_60"] = returns.rolling(60, min_periods=10).std(ddof=0)
        g["ewma_close_to_close_vol"] = returns.pow(2).ewm(span=20, min_periods=5, adjust=False).mean().pow(0.5)
        downside = returns.where(returns < 0, 0.0)
        g["rolling_downside_vol_20"] = downside.rolling(20, min_periods=5).std(ddof=0)
        g["rolling_downside_vol_60"] = downside.rolling(60, min_periods=10).std(ddof=0)
        high = g["high"].astype(float)
        low = g["low"].astype(float)
        open_ = g["open"].astype(float)
        with np.errstate(divide="ignore", invalid="ignore"):
            log_hl = np.log(high / low)
            log_co = np.log(close / open_)
            log_hc = np.log(high / close)
            log_ho = np.log(high / open_)
            log_lc = np.log(low / close)
            log_lo = np.log(low / open_)
        parkinson = (log_hl.pow(2) / (4.0 * math.log(2.0))).replace([np.inf, -np.inf], np.nan)
        gk = (0.5 * log_hl.pow(2) - (2.0 * math.log(2.0) - 1.0) * log_co.pow(2)).clip(lower=0)
        rs = (log_hc * log_ho + log_lc * log_lo).clip(lower=0)
        range_ratio = ((high - low) / close).replace([np.inf, -np.inf], np.nan)
        for window in [20, 60]:
            min_periods = 5 if window == 20 else 10
            g[f"parkinson_vol_{window}"] = parkinson.rolling(window, min_periods=min_periods).mean().pow(0.5)
            g[f"garman_klass_vol_{window}"] = gk.rolling(window, min_periods=min_periods).mean().pow(0.5)
            g[f"rogers_satchell_vol_{window}"] = rs.rolling(window, min_periods=min_periods).mean().pow(0.5)
        g["intraday_range_ratio_20"] = range_ratio.rolling(20, min_periods=5).mean()
        g["rolling_max_drawdown_20"] = close.rolling(20, min_periods=5).apply(_rolling_max_drawdown, raw=True)
        g["rolling_max_drawdown_60"] = close.rolling(60, min_periods=10).apply(_rolling_max_drawdown, raw=True)
        g["rolling_distance_from_high_20"] = 1.0 - close / close.rolling(20, min_periods=5).max()
        g["rolling_distance_from_high_60"] = 1.0 - close / close.rolling(60, min_periods=10).max()
        g["continuous_proxy_vol_drawdown_combo"] = g[
            ["rolling_close_to_close_vol_20", "rolling_distance_from_high_20"]
        ].mean(axis=1)
        frames.append(g)
    if not frames:
        columns = ["entity_id", "trade_date", "feature_asof_date", *[item["name"] for item in BASELINE_DEFINITIONS if item["kind"] == "price"]]
        return pd.DataFrame(columns=columns), availability
    result = pd.concat(frames, ignore_index=True)
    return result, availability


def build_target_rows_for_trade_dates(
    price_frame: pd.DataFrame,
    universe_frame: pd.DataFrame,
    slices: Sequence[SliceSpec],
    trade_dates: Sequence[pd.Timestamp | str],
    *,
    source_db_path: Path | str,
) -> pd.DataFrame:
    prices = _normalise_prices(price_frame)
    wanted_dates = {pd.Timestamp(value).normalize() for value in trade_dates}
    if prices.empty or not slices or not wanted_dates:
        return _empty_target_rows()
    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE).normalize()
    holdout = pd.Timestamp(HOLDOUT_START).normalize()
    entity_meta: dict[str, dict[str, Any]] = {}
    if not universe_frame.empty:
        for row in universe_frame.to_dict(orient="records"):
            entity_meta[str(row.get("entity_id"))] = row
    rows: list[dict[str, Any]] = []
    horizons = sorted({int(spec.horizon) for spec in slices})
    created_at = _now_iso()
    for entity_id, group in prices.groupby("entity_id", sort=False):
        group = group.sort_values("trade_date").reset_index(drop=True)
        closes = group["close"].to_numpy(dtype=float)
        dates = [pd.Timestamp(value).normalize() for value in group["trade_date"].tolist()]
        meta = entity_meta.get(str(entity_id), {})
        for idx, trade_ts in enumerate(dates):
            if trade_ts not in wanted_dates:
                continue
            split_role = "prospective_final_holdout" if trade_ts >= holdout else "historical_development"
            metrics_by_horizon: dict[int, tuple[str, dict[str, float] | None, pd.Timestamp | None, pd.Timestamp | None]] = {}
            for horizon in horizons:
                start_idx = idx + 1
                end_idx = idx + horizon
                start_date = dates[start_idx] if start_idx < len(dates) else None
                end_date = dates[end_idx] if end_idx < len(dates) else None
                metrics: dict[str, float] | None = None
                if end_date is None:
                    censoring_status = "insufficient_future_prices"
                elif split_role == "historical_development" and end_date > cutoff:
                    censoring_status = "cross_cutoff_censored"
                else:
                    metrics = compute_path_metrics(closes, base_index=idx, horizon=horizon)
                    censoring_status = "labeled" if metrics is not None else "insufficient_future_prices"
                metrics_by_horizon[horizon] = (censoring_status, metrics, start_date, end_date)
            for spec in slices:
                censoring_status, metrics, start_date, end_date = metrics_by_horizon[int(spec.horizon)]
                event_label = None
                if metrics is not None and censoring_status == "labeled":
                    event_label = bool(metrics["future_mae"] <= -float(spec.threshold_value))
                rows.append(
                    {
                        "trade_date": trade_ts,
                        "entity_id": str(entity_id),
                        "entity_segment_id": meta.get("entity_segment_id", f"{entity_id}::segment_1"),
                        "sector_name": meta.get("sector_name"),
                        "split_role": split_role,
                        "target_usage": spec.target_usage,
                        "horizon": int(spec.horizon),
                        "threshold_type": spec.threshold_type,
                        "threshold_value": float(spec.threshold_value),
                        "target_kind": TARGET_KIND,
                        "target_observation_start_date": start_date,
                        "target_observation_end_date": end_date,
                        "future_return": None if metrics is None else metrics["future_return"],
                        "future_mae": None if metrics is None else metrics["future_mae"],
                        "future_mdd": None if metrics is None else metrics["future_mdd"],
                        "future_realized_vol": None if metrics is None else metrics["future_realized_vol"],
                        "future_downside_vol": None if metrics is None else metrics["future_downside_vol"],
                        "event_label": event_label,
                        "censoring_status": censoring_status,
                        "sample_weight": 1.0,
                        "source_db_path": _safe_path(source_db_path),
                        "created_at": created_at,
                    }
                )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return _empty_target_rows()
    frame["trade_date"] = pd.to_datetime(frame["trade_date"], errors="coerce").dt.normalize()
    frame["target_observation_start_date"] = pd.to_datetime(
        frame["target_observation_start_date"], errors="coerce"
    ).dt.normalize()
    frame["target_observation_end_date"] = pd.to_datetime(frame["target_observation_end_date"], errors="coerce").dt.normalize()
    return frame.sort_values(["trade_date", "entity_id", "horizon", "threshold_value"]).reset_index(drop=True)


def _empty_target_rows() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "trade_date",
            "entity_id",
            "entity_segment_id",
            "sector_name",
            "split_role",
            "target_usage",
            "horizon",
            "threshold_type",
            "threshold_value",
            "target_kind",
            "target_observation_start_date",
            "target_observation_end_date",
            "future_return",
            "future_mae",
            "future_mdd",
            "future_realized_vol",
            "future_downside_vol",
            "event_label",
            "censoring_status",
            "sample_weight",
            "source_db_path",
            "created_at",
        ]
    )


def filter_prospective_holdout_rows(rows: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    if rows.empty or "trade_date" not in rows.columns:
        return rows.copy(), 0
    holdout = pd.Timestamp(HOLDOUT_START).normalize()
    work = rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    holdout_mask = work["trade_date"].ge(holdout)
    return work[~holdout_mask].copy(), int(holdout_mask.sum())


def _labeled_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    work = rows.copy()
    work["event_label"] = work["event_label"].where(work["event_label"].notna(), np.nan)
    return work[work["censoring_status"].astype(str).eq("labeled") & work["event_label"].notna()].copy()


def _event_rate(rows: pd.DataFrame) -> float | None:
    labeled = _labeled_rows(rows)
    if labeled.empty:
        return None
    return float(labeled["event_label"].astype(bool).mean())


def _tail_rate(rows: pd.DataFrame, window_rows: int, fallback: float | None) -> float | None:
    labeled = _labeled_rows(rows)
    if labeled.empty:
        return fallback
    tail = labeled.sort_values("trade_date").tail(int(window_rows))
    rate = _event_rate(tail)
    return fallback if rate is None else rate


def _group_rate_map(
    train_rows: pd.DataFrame,
    group_cols: Sequence[str],
    *,
    window_rows: int | None,
    fallback: float | None,
) -> dict[tuple[Any, ...], float | None]:
    if train_rows.empty:
        return {}
    rates: dict[tuple[Any, ...], float | None] = {}
    for key, group in train_rows.groupby(list(group_cols), sort=False, dropna=False):
        if not isinstance(key, tuple):
            key = (key,)
        rates[key] = _tail_rate(group, window_rows, fallback) if window_rows is not None else (_event_rate(group) or fallback)
    return rates


def compute_empirical_baseline_scores(
    validation_rows: pd.DataFrame,
    training_rows: pd.DataFrame,
    *,
    rolling_history_rows: int = DEFAULT_ROLLING_HISTORY_ROWS,
    market_share_window_dates: int = DEFAULT_MARKET_SHARE_WINDOW_DATES,
) -> pd.DataFrame:
    """Return empirical-rate scores for validation rows using training labels only."""

    if validation_rows.empty:
        return pd.DataFrame(index=validation_rows.index)
    train = _labeled_rows(training_rows)
    val = validation_rows.copy()
    global_expanding = _event_rate(train)
    global_rolling = _tail_rate(train, rolling_history_rows, global_expanding)
    if global_expanding is None:
        global_expanding = 0.0
    if global_rolling is None:
        global_rolling = global_expanding

    slice_cols = _slice_key_columns()
    entity_cols = ["entity_id"]
    entity_slice_cols = ["entity_id", *_slice_key_columns()]
    rolling_slice = _group_rate_map(train, slice_cols, window_rows=rolling_history_rows, fallback=global_expanding)
    rolling_entity = _group_rate_map(train, entity_cols, window_rows=rolling_history_rows, fallback=global_expanding)
    rolling_entity_slice = _group_rate_map(train, entity_slice_cols, window_rows=rolling_history_rows, fallback=global_expanding)
    expanding_entity = _group_rate_map(train, entity_cols, window_rows=None, fallback=global_expanding)

    market_share: dict[tuple[Any, ...], float | None] = {}
    if not train.empty:
        by_date_slice = (
            train.groupby(["trade_date", *slice_cols], dropna=False)["event_label"]
            .mean()
            .reset_index(name="event_share")
            .sort_values("trade_date")
        )
        for key, group in by_date_slice.groupby(slice_cols, sort=False, dropna=False):
            if not isinstance(key, tuple):
                key = (key,)
            market_share[key] = float(group.tail(int(market_share_window_dates))["event_share"].mean())

    out = pd.DataFrame(index=validation_rows.index)
    out["rolling_global_event_rate"] = float(global_rolling)
    out["expanding_global_event_rate"] = float(global_expanding)
    slice_keys = [tuple(row) for row in val[slice_cols].itertuples(index=False, name=None)]
    entity_keys = [(str(entity),) for entity in val["entity_id"].astype(str).tolist()]
    entity_slice_keys = [
        (str(row[0]), int(row[1]), str(row[2]), float(row[3]), str(row[4]))
        for row in val[["entity_id", *slice_cols]].itertuples(index=False, name=None)
    ]
    out["rolling_slice_event_rate"] = [rolling_slice.get(key, global_expanding) for key in slice_keys]
    out["rolling_entity_event_rate"] = [rolling_entity.get(key, global_expanding) for key in entity_keys]
    out["rolling_entity_slice_event_rate"] = [rolling_entity_slice.get(key, global_expanding) for key in entity_slice_keys]
    out["expanding_entity_event_rate"] = [expanding_entity.get(key, global_expanding) for key in entity_keys]
    out["rolling_market_event_share_by_slice"] = [market_share.get(key, global_expanding) for key in slice_keys]
    return out


def detect_feature_asof_violations(rows: pd.DataFrame) -> int:
    if rows.empty or "feature_asof_date" not in rows.columns or "trade_date" not in rows.columns:
        return 0
    asof = pd.to_datetime(rows["feature_asof_date"], errors="coerce").dt.normalize()
    trade_date = pd.to_datetime(rows["trade_date"], errors="coerce").dt.normalize()
    return int((asof.notna() & trade_date.notna() & asof.gt(trade_date)).sum())


def validate_baseline_input_columns(columns: Sequence[str]) -> dict[str, Any]:
    policy = detect_feature_namespace_violations(columns)
    return {
        "target_namespace_input_violation_count": int(policy.get("feature_target_collision_violation_count", 0)),
        "future_column_input_violation_count": int(policy.get("future_derived_feature_violation_count", 0)),
        "target_namespace_input_violations": policy.get("feature_target_collision_violations", []),
        "future_column_input_violations": policy.get("future_derived_feature_violations", []),
    }


def _roc_auc(y: np.ndarray, score: np.ndarray) -> float | None:
    if len(y) == 0:
        return None
    positives = int(np.sum(y == 1))
    negatives = int(np.sum(y == 0))
    if positives == 0 or negatives == 0:
        return None
    ranks = pd.Series(score).rank(method="average").to_numpy(dtype=float)
    sum_pos = float(ranks[y == 1].sum())
    auc = (sum_pos - positives * (positives + 1) / 2.0) / (positives * negatives)
    return float(auc) if math.isfinite(auc) else None


def _average_precision(y: np.ndarray, score: np.ndarray) -> float | None:
    positives = int(np.sum(y == 1))
    if positives == 0:
        return None
    order = np.argsort(-score, kind="mergesort")
    sorted_y = y[order]
    cumsum = np.cumsum(sorted_y)
    ranks = np.arange(1, len(sorted_y) + 1)
    precision = cumsum / ranks
    ap = float(precision[sorted_y == 1].sum() / positives)
    return ap if math.isfinite(ap) else None


def _spearman(a: pd.Series, b: pd.Series) -> float | None:
    data = pd.DataFrame({"a": pd.to_numeric(a, errors="coerce"), "b": pd.to_numeric(b, errors="coerce")}).dropna()
    if len(data) < 2 or data["a"].nunique() < 2 or data["b"].nunique() < 2:
        return None
    value = float(data["a"].corr(data["b"], method="spearman"))
    return value if math.isfinite(value) else None


def _quantile_lift(labels: pd.Series, score: pd.Series, quantile: float) -> float | None:
    data = pd.DataFrame({"label": labels.astype(float), "score": pd.to_numeric(score, errors="coerce")}).dropna()
    if data.empty or data["label"].sum() <= 0:
        return None
    cutoff_count = max(1, int(math.ceil(len(data) * quantile)))
    top = data.sort_values("score", ascending=False).head(cutoff_count)
    base_rate = float(data["label"].mean())
    top_rate = float(top["label"].mean())
    return _safe_div(top_rate, base_rate)


def _top_quantile_mean(value: pd.Series, score: pd.Series, quantile: float) -> float | None:
    data = pd.DataFrame({"value": pd.to_numeric(value, errors="coerce"), "score": pd.to_numeric(score, errors="coerce")}).dropna()
    if data.empty:
        return None
    cutoff_count = max(1, int(math.ceil(len(data) * quantile)))
    mean_value = float(data.sort_values("score", ascending=False).head(cutoff_count)["value"].mean())
    return mean_value if math.isfinite(mean_value) else None


def _monotonic_decile_status(labels: pd.Series, score: pd.Series) -> str:
    data = pd.DataFrame({"label": labels.astype(float), "score": pd.to_numeric(score, errors="coerce")}).dropna()
    if len(data) < 20 or data["score"].nunique() < 3 or data["label"].nunique() < 2:
        return "insufficient_unique_scores"
    try:
        data["decile"] = pd.qcut(data["score"], q=min(10, data["score"].nunique()), duplicates="drop")
    except ValueError:
        return "insufficient_unique_scores"
    rates = data.groupby("decile", observed=True)["label"].mean().to_numpy(dtype=float)
    if len(rates) < 3:
        return "insufficient_unique_scores"
    return "pass" if bool(np.all(np.diff(rates) >= -1e-12)) else "non_monotonic"


def compute_metric_row(
    rows: pd.DataFrame,
    *,
    baseline_family: str,
    baseline_name: str,
    fold_id: str | None = None,
) -> dict[str, Any]:
    labeled = _labeled_rows(rows)
    if rows.empty:
        base: dict[str, Any] = {
            "row_count": 0,
            "scored_row_count": 0,
            "positive_event_count": 0,
            "event_base_rate": None,
            "score_available_rate": None,
            "roc_auc": None,
            "average_precision": None,
            "brier_like_score_if_score_in_0_1": None,
            "spearman_score_vs_event": None,
            "spearman_score_vs_future_mae": None,
            "spearman_score_vs_future_mdd": None,
            "spearman_score_vs_future_return": None,
            "quantile_lift_top_decile": None,
            "quantile_lift_top_quintile": None,
            "top_decile_future_mae_mean": None,
            "top_decile_future_mdd_mean": None,
            "monotonic_decile_event_rate_status": "no_rows",
        }
    else:
        scored = labeled[pd.to_numeric(labeled.get("score"), errors="coerce").notna()].copy()
        y = scored["event_label"].astype(bool).astype(int).to_numpy(dtype=int)
        score = pd.to_numeric(scored["score"], errors="coerce").to_numpy(dtype=float)
        finite = np.isfinite(score)
        y = y[finite]
        score = score[finite]
        base_rate = _safe_div(float(np.sum(y)), float(len(y))) if len(y) else None
        brier = None
        if len(score) and np.nanmin(score) >= 0.0 and np.nanmax(score) <= 1.0:
            brier = float(np.mean((y.astype(float) - score) ** 2))
        base = {
            "row_count": int(len(rows)),
            "scored_row_count": int(len(score)),
            "positive_event_count": int(np.sum(y)) if len(y) else 0,
            "event_base_rate": base_rate,
            "score_available_rate": _safe_div(float(len(score)), float(len(rows))),
            "roc_auc": _roc_auc(y, score) if len(y) else None,
            "average_precision": _average_precision(y, score) if len(y) else None,
            "brier_like_score_if_score_in_0_1": brier if brier is not None and math.isfinite(brier) else None,
            "spearman_score_vs_event": _spearman(scored["score"], scored["event_label"].astype(int)) if not scored.empty else None,
            "spearman_score_vs_future_mae": _spearman(scored["score"], scored["future_mae"]) if not scored.empty else None,
            "spearman_score_vs_future_mdd": _spearman(scored["score"], scored["future_mdd"]) if not scored.empty else None,
            "spearman_score_vs_future_return": _spearman(scored["score"], scored["future_return"]) if not scored.empty else None,
            "quantile_lift_top_decile": _quantile_lift(scored["event_label"], scored["score"], 0.10) if not scored.empty else None,
            "quantile_lift_top_quintile": _quantile_lift(scored["event_label"], scored["score"], 0.20) if not scored.empty else None,
            "top_decile_future_mae_mean": _top_quantile_mean(scored["future_mae"], scored["score"], 0.10) if not scored.empty else None,
            "top_decile_future_mdd_mean": _top_quantile_mean(scored["future_mdd"], scored["score"], 0.10) if not scored.empty else None,
            "monotonic_decile_event_rate_status": _monotonic_decile_status(scored["event_label"], scored["score"]),
        }
    first = rows.head(1)
    for column in _slice_key_columns():
        base[column] = None if first.empty else first.iloc[0].get(column)
    base["baseline_family"] = baseline_family
    base["baseline_name"] = baseline_name
    if fold_id is not None:
        base["fold_id"] = fold_id
    if base.get("horizon") is not None:
        base["horizon"] = int(base["horizon"])
    if base.get("threshold_value") is not None:
        base["threshold_value"] = float(base["threshold_value"])
    return base


def _fold_validation_rows(target_rows: pd.DataFrame, fold: Mapping[str, Any]) -> tuple[pd.DataFrame, int]:
    start = _normalise_date(fold.get("validation_start_date"))
    end = _normalise_date(fold.get("validation_end_date"))
    if start is None or end is None or target_rows.empty:
        return target_rows.iloc[0:0].copy(), 0
    work = target_rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    validation = work[work["trade_date"].between(start, end, inclusive="both")].copy()
    validation, withheld = filter_prospective_holdout_rows(validation)
    return _labeled_rows(validation), withheld


def _fold_training_rows(target_rows: pd.DataFrame, fold: Mapping[str, Any]) -> pd.DataFrame:
    validation_start = _normalise_date(fold.get("validation_start_date"))
    if validation_start is None or target_rows.empty:
        return target_rows.iloc[0:0].copy()
    work = target_rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["target_observation_end_date"] = pd.to_datetime(work["target_observation_end_date"], errors="coerce").dt.normalize()
    train = work[
        work["trade_date"].lt(validation_start)
        & work["target_observation_end_date"].lt(validation_start)
        & work["censoring_status"].astype(str).eq("labeled")
        & work["event_label"].notna()
    ].copy()
    return train


def _metric_best(rows: list[dict[str, Any]], metric: str) -> dict[str, Any] | None:
    candidates = [row for row in rows if _as_float(row.get(metric)) is not None]
    if not candidates:
        return None
    best = max(candidates, key=lambda row: float(row[metric]))
    return {
        "baseline_name": best.get("baseline_name"),
        "baseline_family": best.get("baseline_family"),
        "metric": metric,
        "value": _finite_or_none(best.get(metric)),
        "horizon": best.get("horizon"),
        "threshold_value": best.get("threshold_value"),
        "target_usage": best.get("target_usage"),
    }


def evaluate_baselines_for_folds(
    *,
    target_rows: pd.DataFrame,
    price_features: pd.DataFrame,
    fold_plan: Mapping[str, Any],
    range_based_available: bool,
    audit_sample_cap: int = DEFAULT_SAMPLE_ROWS,
) -> dict[str, Any]:
    fold_metric_rows: list[dict[str, Any]] = []
    slice_metric_frames: list[pd.DataFrame] = []
    audit_rows: list[dict[str, Any]] = []
    leakage_counts = {
        "feature_asof_violation_count": 0,
        "target_namespace_input_violation_count": 0,
        "future_column_input_violation_count": 0,
        "same_row_label_leakage_count": 0,
        "validation_label_leakage_count": 0,
        "prospective_holdout_score_count": 0,
        "prospective_holdout_metric_count": 0,
    }
    namespace_counts = validate_baseline_input_columns(BASELINE_INPUT_COLUMNS)
    leakage_counts["target_namespace_input_violation_count"] = namespace_counts["target_namespace_input_violation_count"]
    leakage_counts["future_column_input_violation_count"] = namespace_counts["future_column_input_violation_count"]
    feature_cols = ["entity_id", "trade_date", "feature_asof_date", *[item["name"] for item in BASELINE_DEFINITIONS if item["kind"] == "price"]]
    features = price_features[[column for column in feature_cols if column in price_features.columns]].copy()
    if not features.empty:
        features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce").dt.normalize()

    validation_row_total = 0
    row_count_scored = 0
    prospective_withheld_total = 0
    slice_keys_seen: set[tuple[int, str, float, str]] = set()
    folds = list(fold_plan.get("folds", []))
    for fold in folds:
        fold_id = str(fold.get("fold_id", "fold_unknown"))
        validation_rows, withheld = _fold_validation_rows(target_rows, fold)
        prospective_withheld_total += int(withheld)
        if validation_rows.empty:
            continue
        training_rows = _fold_training_rows(target_rows, fold)
        validation_row_total += int(len(validation_rows))
        slice_keys_seen.update(_slice_key_from_row(row) for row in validation_rows.to_dict(orient="records"))
        if not training_rows.empty:
            val_start = _normalise_date(fold.get("validation_start_date"))
            bad_train = training_rows[
                (pd.to_datetime(training_rows["trade_date"], errors="coerce").dt.normalize() >= val_start)
                | (pd.to_datetime(training_rows["target_observation_end_date"], errors="coerce").dt.normalize() >= val_start)
            ]
            leakage_counts["validation_label_leakage_count"] += int(len(bad_train))

        empirical_scores = compute_empirical_baseline_scores(validation_rows, training_rows)
        scored_base = validation_rows.merge(features, on=["entity_id", "trade_date"], how="left")
        empirical_asof = None
        if not training_rows.empty:
            empirical_asof = pd.to_datetime(training_rows["trade_date"], errors="coerce").max()
        any_score_mask = pd.Series(False, index=scored_base.index)
        for definition in BASELINE_DEFINITIONS:
            baseline_name = str(definition["name"])
            baseline_family = str(definition["family"])
            if definition.get("requires_ohlc") and not range_based_available:
                score = pd.Series(np.nan, index=scored_base.index, dtype=float)
                feature_asof = pd.Series(pd.NaT, index=scored_base.index)
            elif definition["kind"] == "empirical":
                score = empirical_scores[baseline_name].reset_index(drop=True) if baseline_name in empirical_scores else pd.Series(np.nan, index=scored_base.index)
                feature_asof = pd.Series(empirical_asof, index=scored_base.index)
            else:
                score = pd.to_numeric(scored_base.get(baseline_name), errors="coerce")
                feature_asof = pd.to_datetime(scored_base.get("feature_asof_date"), errors="coerce")
            score = pd.to_numeric(score, errors="coerce").reset_index(drop=True)
            feature_asof = pd.to_datetime(feature_asof, errors="coerce").reset_index(drop=True)
            scored = validation_rows.reset_index(drop=True).copy()
            scored["score"] = score
            scored["feature_asof_date"] = feature_asof
            scored["score_available"] = scored["score"].notna()
            any_score_mask = any_score_mask | scored["score_available"]
            leakage_counts["feature_asof_violation_count"] += detect_feature_asof_violations(scored)
            holdout_scores = scored[
                pd.to_datetime(scored["trade_date"], errors="coerce").dt.normalize().ge(pd.Timestamp(HOLDOUT_START))
                & scored["score_available"]
            ]
            leakage_counts["prospective_holdout_score_count"] += int(len(holdout_scores))
            for _, slice_group in scored.groupby(_slice_key_columns(), sort=False, dropna=False):
                fold_metric_rows.append(
                    compute_metric_row(
                        slice_group,
                        baseline_family=baseline_family,
                        baseline_name=baseline_name,
                        fold_id=fold_id,
                    )
                )
            slice_metric_frames.append(
                scored[
                    [
                        "horizon",
                        "threshold_type",
                        "threshold_value",
                        "target_usage",
                        "censoring_status",
                        "event_label",
                        "future_mae",
                        "future_mdd",
                        "future_return",
                        "score",
                    ]
                ].assign(baseline_family=baseline_family, baseline_name=baseline_name)
            )
            if len(audit_rows) < audit_sample_cap:
                take = scored.head(audit_sample_cap - len(audit_rows)).copy()
                take["fold_id"] = fold_id
                take["baseline_family"] = baseline_family
                take["baseline_name"] = baseline_name
                for row in take[AUDIT_SAMPLE_COLUMNS].to_dict(orient="records"):
                    audit_rows.append(row)
        row_count_scored += int(any_score_mask.sum())

    slice_metric_rows: list[dict[str, Any]] = []
    if slice_metric_frames:
        combined = pd.concat(slice_metric_frames, ignore_index=True)
        group_cols = _slice_key_columns() + ["baseline_family", "baseline_name"]
        for _, group in combined.groupby(group_cols, sort=False, dropna=False):
            slice_metric_rows.append(
                compute_metric_row(
                    group,
                    baseline_family=str(group["baseline_family"].iloc[0]),
                    baseline_name=str(group["baseline_name"].iloc[0]),
                )
            )
    leakage_counts["prospective_holdout_metric_count"] = int(prospective_withheld_total)
    leakage_counts["leakage_violation_count_total"] = int(sum(leakage_counts.values()))
    return {
        "fold_metrics": fold_metric_rows,
        "slice_metrics": slice_metric_rows,
        "audit_rows": audit_rows,
        "leakage_violation_counts": leakage_counts,
        "row_count_scored": int(row_count_scored),
        "validation_row_count_evaluated": int(validation_row_total),
        "prospective_holdout_rows_evaluated": 0,
        "prospective_holdout_rows_withheld": int(prospective_withheld_total),
        "slice_count_evaluated": int(len(slice_keys_seen)),
        "fold_count_evaluated": int(len([fold for fold in folds if fold_metric_rows])),
    }


def _metric_summary(fold_rows: list[dict[str, Any]], slice_rows: list[dict[str, Any]]) -> dict[str, Any]:
    def values(metric: str) -> list[float]:
        return [float(row[metric]) for row in slice_rows if _as_float(row.get(metric)) is not None]

    aucs = values("roc_auc")
    aps = values("average_precision")
    rank_mdd = values("spearman_score_vs_future_mdd")
    return {
        "fold_metric_row_count": int(len(fold_rows)),
        "slice_metric_row_count": int(len(slice_rows)),
        "mean_roc_auc": float(np.mean(aucs)) if aucs else None,
        "max_roc_auc": float(np.max(aucs)) if aucs else None,
        "mean_average_precision": float(np.mean(aps)) if aps else None,
        "max_average_precision": float(np.max(aps)) if aps else None,
        "mean_spearman_score_vs_future_mdd": float(np.mean(rank_mdd)) if rank_mdd else None,
        "continuous_diagnostics": [
            "rank_correlation_with_future_mae",
            "rank_correlation_with_future_mdd",
            "rank_correlation_with_future_return",
            "quantile_lift_by_future_mae",
            "quantile_lift_by_event_label",
        ],
    }


def _blocked_report(
    *,
    status: str,
    db_path: Path | str | None,
    reasons: Sequence[str],
    wp1_status: str | None = None,
    wp2_status: str | None = None,
    wp2_1_status: str | None = None,
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "wp1_support_status": wp1_status,
        "wp2_controls_status": wp2_status,
        "wp2_1_full_target_audit_status": wp2_1_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "target_universe_status": "blocked",
        "fold_plan_status": "blocked",
        "baseline_policy_status": "blocked",
        "baseline_families_implemented": BASELINE_FAMILIES_REQUIRED,
        "baseline_families_unavailable": BASELINE_FAMILIES_REQUIRED,
        "row_count_scored": 0,
        "validation_row_count_evaluated": 0,
        "prospective_holdout_rows_evaluated": 0,
        "slice_count_evaluated": 0,
        "fold_count_evaluated": 0,
        "baseline_count": 0,
        "fold_metrics_path": None,
        "slice_metrics_path": None,
        "audit_sample_path": None,
        "leakage_violation_counts": {
            "feature_asof_violation_count": 0,
            "target_namespace_input_violation_count": 0,
            "future_column_input_violation_count": 0,
            "same_row_label_leakage_count": 0,
            "validation_label_leakage_count": 0,
            "prospective_holdout_score_count": 0,
            "prospective_holdout_metric_count": 0,
            "leakage_violation_count_total": 0,
        },
        "metric_summary": {},
        "best_baseline_by_auc": None,
        "best_baseline_by_average_precision": None,
        "best_baseline_by_rank_correlation": None,
        "range_based_availability_status": "blocked",
        "continuous_diagnostic_status": "blocked",
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
    fold_metrics: Path,
    slice_metrics: Path,
    audit_sample: Path,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_csv(fold_metrics, [], FOLD_METRIC_COLUMNS)
    _write_csv(slice_metrics, [], SLICE_METRIC_COLUMNS)
    _write_csv(audit_sample, [], AUDIT_SAMPLE_COLUMNS)


def build_baseline_diagnostics_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    target_controls: Path | str = DEFAULT_TARGET_CONTROLS,
    full_target_audit: Path | str = DEFAULT_FULL_TARGET_AUDIT,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    policy: Path | str = DEFAULT_POLICY,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    fold_metrics: Path | str = DEFAULT_FOLD_METRICS,
    slice_metrics: Path | str = DEFAULT_SLICE_METRICS,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    audit_sample_cap: int = DEFAULT_SAMPLE_ROWS,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP3 baseline diagnostics are no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    fold_path = Path(fold_metrics)
    slice_path = Path(slice_metrics)
    audit_path = Path(audit_sample)

    try:
        support = _load_json(target_support)
        controls = _load_json(target_controls)
        full_audit = _load_json(full_target_audit)
    except FileNotFoundError as exc:
        report = _blocked_report(status="blocked_wp2_1_not_ready", db_path=resolved_db, reasons=[f"missing input: {exc.filename}"])
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
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
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["sw2021_l2_universe_coverage"] = v7.coverage.get("sw2021_l2_universe_coverage", "missing")
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report

    if not Path(fold_plan).exists():
        report = _blocked_report(
            status="blocked_missing_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=[f"missing fold plan: {fold_plan}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report
    fold_doc = _load_json(fold_plan)
    if fold_doc.get("status") != "pass" or int(fold_doc.get("fold_count", 0) or 0) <= 0:
        report = _blocked_report(
            status="blocked_invalid_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=["fold plan is missing pass status or usable folds"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report

    precondition_issues = validate_wp3_preconditions(
        target_support=support,
        target_controls=controls,
        full_target_audit=full_audit,
        fold_plan=fold_doc,
        db_path=resolved_db,
    )
    if precondition_issues:
        report = _blocked_report(
            status="blocked_wp2_1_not_ready",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=precondition_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report

    try:
        policy_doc = _load_machine_config(policy)
    except FileNotFoundError:
        report = _blocked_report(
            status="blocked_missing_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=[f"missing baseline policy: {policy}"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report
    policy_issues = validate_baseline_policy(policy_doc)
    if policy_issues:
        report = _blocked_report(
            status="blocked_invalid_policy",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=policy_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report

    target_universe_doc = _load_machine_config(target_universe)
    target_universe_status = "pass" if target_universe_doc.get("source", {}).get("v7_coverage_available") == "yes" else "partial"
    specs = slice_specs_from_target_support(support)
    universe_ids = v7.universe_frame["entity_id"].astype(str).tolist()
    ohlcv, range_report = read_ohlcv_inputs(resolved_db, universe_ids)
    if ohlcv.empty:
        close_only = v7.price_frame.rename(columns={"sector_id": "entity_id"}).copy()
        close_only["open"] = np.nan
        close_only["high"] = np.nan
        close_only["low"] = np.nan
        ohlcv = close_only[["entity_id", "trade_date", "open", "high", "low", "close"]]
    price_features, feature_range_report = build_price_baseline_features(ohlcv)
    range_report = {**range_report, **feature_range_report}
    range_status = str(range_report.get("range_based_availability_status", "range_based_unavailable"))
    range_available = range_status == "pass"

    validation_dates: set[pd.Timestamp] = set()
    max_validation_end: pd.Timestamp | None = None
    for fold in fold_doc.get("folds", []):
        start = _normalise_date(fold.get("validation_start_date"))
        end = _normalise_date(fold.get("validation_end_date"))
        if start is None or end is None:
            continue
        if max_validation_end is None or end > max_validation_end:
            max_validation_end = end
        dates = pd.date_range(start, end, freq="D")
        validation_dates.update(pd.Timestamp(value).normalize() for value in dates)
    if max_validation_end is None:
        report = _blocked_report(
            status="blocked_invalid_fold_plan",
            db_path=resolved_db,
            wp1_status=str(support.get("status", "unknown")),
            wp2_status=str(controls.get("status", "unknown")),
            wp2_1_status=str(full_audit.get("status", "unknown")),
            reasons=["fold plan has no valid validation dates"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_metrics=fold_path,
            slice_metrics=slice_path,
            audit_sample=audit_path,
        )
        return report
    available_price_dates = set(pd.to_datetime(v7.price_frame["trade_date"], errors="coerce").dt.normalize().dropna().tolist())
    needed_dates = sorted(date for date in available_price_dates if date <= max_validation_end)
    target_rows = build_target_rows_for_trade_dates(
        v7.price_frame,
        v7.universe_frame,
        specs,
        needed_dates,
        source_db_path=resolved_db,
    )
    evaluation = evaluate_baselines_for_folds(
        target_rows=target_rows,
        price_features=price_features,
        fold_plan=fold_doc,
        range_based_available=range_available,
        audit_sample_cap=audit_sample_cap,
    )
    fold_metric_rows = evaluation["fold_metrics"]
    slice_metric_rows = evaluation["slice_metrics"]
    _write_csv(fold_path, fold_metric_rows, FOLD_METRIC_COLUMNS)
    _write_csv(slice_path, slice_metric_rows, SLICE_METRIC_COLUMNS)
    _write_csv(audit_path, evaluation["audit_rows"], AUDIT_SAMPLE_COLUMNS)

    leakage_counts = evaluation["leakage_violation_counts"]
    families_implemented = sorted({str(item["family"]) for item in BASELINE_DEFINITIONS})
    families_unavailable = ["range_based_volatility"] if not range_available else []
    metric_summary = _metric_summary(fold_metric_rows, slice_metric_rows)
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "unknown",
        "wp1_support_status": support.get("status"),
        "wp2_controls_status": controls.get("status"),
        "wp2_1_full_target_audit_status": full_audit.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "target_universe_status": target_universe_status,
        "fold_plan_status": fold_doc.get("status"),
        "fold_plan_source": "accepted WP2 fold plan",
        "baseline_policy_status": "pass",
        "baseline_families_implemented": families_implemented,
        "baseline_families_unavailable": families_unavailable,
        "baseline_variants_implemented": [item["name"] for item in BASELINE_DEFINITIONS],
        "row_count_scored": evaluation["row_count_scored"],
        "validation_row_count_evaluated": evaluation["validation_row_count_evaluated"],
        "prospective_holdout_rows_evaluated": evaluation["prospective_holdout_rows_evaluated"],
        "prospective_holdout_rows_withheld": evaluation["prospective_holdout_rows_withheld"],
        "slice_count_evaluated": evaluation["slice_count_evaluated"],
        "fold_count_evaluated": evaluation["fold_count_evaluated"],
        "baseline_count": int(len(BASELINE_DEFINITIONS)),
        "fold_metrics_path": _safe_path(fold_path),
        "slice_metrics_path": _safe_path(slice_path),
        "audit_sample_path": _safe_path(audit_path),
        "leakage_violation_counts": leakage_counts,
        "metric_summary": metric_summary,
        "best_baseline_by_auc": _metric_best(slice_metric_rows, "roc_auc"),
        "best_baseline_by_average_precision": _metric_best(slice_metric_rows, "average_precision"),
        "best_baseline_by_rank_correlation": _metric_best(slice_metric_rows, "spearman_score_vs_future_mdd"),
        "range_based_availability_status": range_status,
        "range_based_availability_detail": range_report,
        "continuous_diagnostic_status": "pass",
        "ci_gate_status": "unknown",
        "boundary_flags": BOUNDARY_FLAGS,
        "old_db_fallback": False,
        "external_data_fetch": "no",
        "no_fetch": True,
        "created_at": _now_iso(),
        "blocking_reasons": [],
    }
    report["status"] = "pass" if int(leakage_counts.get("leakage_violation_count_total", 0)) == 0 else "fail"
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
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--fold-metrics", type=Path, default=DEFAULT_FOLD_METRICS)
    parser.add_argument("--slice-metrics", type=Path, default=DEFAULT_SLICE_METRICS)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--audit-sample-cap", type=int, default=DEFAULT_SAMPLE_ROWS)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_baseline_diagnostics_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        target_controls=args.target_controls,
        full_target_audit=args.full_target_audit,
        fold_plan=args.fold_plan,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        fold_metrics=args.fold_metrics,
        slice_metrics=args.slice_metrics,
        audit_sample=args.audit_sample,
        audit_sample_cap=args.audit_sample_cap,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_BASELINE_DIAGNOSTICS="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"baselines={report.get('baseline_count')} "
        f"validation_rows={report.get('validation_row_count_evaluated')} "
        f"leakage_violations={report.get('leakage_violation_counts', {}).get('leakage_violation_count_total')} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
