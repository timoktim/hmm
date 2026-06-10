"""Stage03V WP2 target-control, purge, embargo, and leakage gate.

This module is a control-plane audit for Stage03V1 target rows. It is
intentionally offline and read-only: no data fetch, model training,
probability calibration, readiness assignment, or holdout scoring happens here.
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
    SliceSpec,
    _json_safe,
    _normalise_prices,
    _safe_path,
    _slice_specs_from_feasibility,
    compute_path_metrics,
    load_feasibility_report,
    read_v7_inputs,
    resolve_v7_db_path,
)


INDEX_ID = "STAGE03V-WP2-v1"
REPORT_VERSION = "stage03v_target_controls_v1"
POLICY_VERSION = "stage03v_purge_embargo_policy_v1"
STAGE_ID = "stage03v"
INFORMATION_CUTOFF_DATE = "2026-06-10"
HOLDOUT_START = "2026-06-11"
MAX_HORIZON_DAYS = 20
DEFAULT_EMBARGO_DAYS = 20
DEFAULT_AUDIT_SAMPLE_ROWS = 500

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"
DEFAULT_FEASIBILITY = ROOT / "reports" / "stage03v" / "sample_feasibility_report.json"
DEFAULT_POLICY = ROOT / "configs" / "stage03v_purge_embargo_policy_v1.yaml"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "target_controls_report.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "target_controls_report.json"
DEFAULT_FOLD_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan.json"
DEFAULT_AUDIT_SAMPLE = ROOT / "reports" / "stage03v" / "target_controls_audit_sample.csv"

ALLOWED_CENSORING_STATUSES = {"labeled", "insufficient_future_prices", "cross_cutoff_censored", "excluded"}
TARGET_NAMESPACE_COLUMNS = [
    "event_label",
    "future_return",
    "future_mae",
    "future_mdd",
    "future_realized_vol",
    "future_downside_vol",
    "target_observation_start_date",
    "target_observation_end_date",
    "censoring_status",
    "exclusion_reason",
    "holdout_label_status",
]
FEATURE_NAMESPACE_FORBIDDEN_TERMS = [
    *TARGET_NAMESPACE_COLUMNS,
    "future_*",
    "target_*",
    "post_trade_date_price_derived_fields",
]
AUDIT_COLUMNS = [
    "trade_date",
    "entity_id",
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
    "exclusion_reason",
    "sample_weight",
    "source_db_path",
    "created_at",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_modified": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
}


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path | str, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP2 Target Controls",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- contract_status: {report.get('contract_status')}",
        f"- wp1_support_status: {report.get('wp1_support_status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- db_opened_read_only: {report.get('db_opened_read_only')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- entity_count_after_silent_break_handling: {report.get('entity_count_after_silent_break_handling')}",
        f"- target_row_count_checked: {report.get('target_row_count_checked')}",
        f"- label_window_violation_count: {report.get('label_window_violation_count')}",
        f"- cross_cutoff_regression_passed: {report.get('cross_cutoff_regression_passed')}",
        f"- cross_cutoff_violation_count: {report.get('cross_cutoff_violation_count')}",
        f"- prospective_holdout_label_consumed_count: {report.get('prospective_holdout_label_consumed_count')}",
        f"- fold_count: {report.get('fold_count')}",
        f"- purge_violation_count: {report.get('purge_violation_count')}",
        f"- embargo_violation_count: {report.get('embargo_violation_count')}",
        f"- feature_namespace_policy_status: {report.get('feature_namespace_policy_status')}",
        f"- ci_gate_status: {report.get('ci_gate_status')}",
        "",
        "## Boundary Flags",
        "",
    ]
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Blocking Reasons", ""])
    blocking_reasons = report.get("blocking_reasons", [])
    if blocking_reasons:
        for reason in blocking_reasons:
            lines.append(f"- {reason}")
    else:
        lines.append("- none")
    lines.extend(["", "## Feature Namespace Policy", ""])
    for term in report.get("feature_namespace_forbidden_terms", []):
        lines.append(f"- {term}")
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_audit_sample(path: Path | str, rows: pd.DataFrame, sample_cap: int) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if rows.empty:
        pd.DataFrame(columns=AUDIT_COLUMNS).to_csv(target, index=False)
        return 0
    out = rows.copy()
    for column in AUDIT_COLUMNS:
        if column not in out.columns:
            out[column] = pd.NA
    out = out[AUDIT_COLUMNS].sort_values(["entity_id", "trade_date", "horizon", "threshold_value"]).head(sample_cap)
    out.to_csv(target, index=False)
    return int(len(out))


def default_purge_embargo_policy() -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "max_horizon_days": MAX_HORIZON_DAYS,
        "purge_rule": "remove any training row whose target observation interval overlaps a validation/test interval",
        "embargo_rule": "remove training rows whose trade_date falls within embargo_days after a validation/test interval",
        "embargo_days": DEFAULT_EMBARGO_DAYS,
        "fold_plan_source": "historical_development_only",
        "final_holdout_policy": "withheld_not_scored",
        "fold_order": "deterministic_time_ordered",
        "target_usage_included": ["eligible", "diagnostic_only"],
        "model_training": "no",
        "probability_calibration": "no",
        "readiness_assigned": "no",
        "boundary_flags": BOUNDARY_FLAGS,
    }


def validate_wp1_support(support: Mapping[str, Any], *, db_path: Path | str) -> list[str]:
    issues: list[str] = []
    boundary = support.get("boundary_flags", {})
    expected_db = _safe_path(db_path)
    source_db = support.get("source_db_path")
    env_db = os.environ.get("STAGE03V_V7_DB")
    env_db_safe = _safe_path(env_db) if env_db else None
    if support.get("status") != "pass":
        issues.append("wp1_status_not_pass")
    if source_db not in {expected_db, env_db_safe, _safe_path(DEFAULT_V7_DB)}:
        issues.append("wp1_source_db_path_not_v7_or_explicit_stage03v_v7_db")
    if support.get("v7_coverage_available") != "yes":
        issues.append("wp1_v7_coverage_available_not_yes")
    if support.get("sw2021_l2_universe_coverage") != "pass":
        issues.append("wp1_sw2021_l2_universe_coverage_not_pass")
    if int(support.get("entity_count_after_silent_break_handling", 0) or 0) != 124:
        issues.append("wp1_entity_count_after_silent_break_handling_not_124")
    if support.get("silent_entity_break_handling") not in {"excluded", "segmented"}:
        issues.append("wp1_silent_entity_break_handling_not_excluded_or_segmented")
    if support.get("permanent_censoring_policy") != "cross_cutoff_censored":
        issues.append("wp1_cross_cutoff_censoring_policy_not_enforced")
    if boundary.get("persistent_db_table_written") != "no":
        issues.append("wp1_persistent_db_table_written_not_no")
    if boundary.get("target_dataset_built") != "yes":
        issues.append("wp1_target_dataset_built_not_yes")
    for field in [
        "model_training",
        "probability_calibration",
        "readiness_assigned",
        "holdout_consumed",
        "stage03v2_implemented",
        "stage03v3_implemented",
    ]:
        if boundary.get(field) != "no":
            issues.append(f"wp1_boundary_{field}_not_no")
    return issues


def validate_target_universe_manifest(manifest: Mapping[str, Any], *, db_path: Path | str) -> list[str]:
    issues: list[str] = []
    source = manifest.get("source", {})
    universe = manifest.get("universe", {})
    expected_db = _safe_path(db_path)
    if source.get("db_path") not in {expected_db, _safe_path(DEFAULT_V7_DB)}:
        issues.append("target_universe_db_path_not_v7")
    if source.get("v7_coverage_available") != "yes":
        issues.append("target_universe_v7_coverage_available_not_yes")
    taxonomy_status = str(source.get("taxonomy_source_status", ""))
    universe_status = str(source.get("universe_source_status", ""))
    for name, value in [
        ("taxonomy_source_status", taxonomy_status),
        ("universe_source_status", universe_status),
    ]:
        if not (value == "verified_sw2021_l2_tushare_classify" or value.startswith("verified")):
            issues.append(f"target_universe_{name}_not_verified")
    if int(universe.get("entity_count_after_silent_break_handling", 0) or 0) != 124:
        issues.append("target_universe_entity_count_after_silent_break_handling_not_124")
    if int(universe.get("silent_entity_break_count", 0) or 0) != 2:
        issues.append("target_universe_silent_entity_break_count_not_2")
    if universe.get("silent_entity_break_handling") not in {"excluded", "segmented"}:
        issues.append("target_universe_silent_break_handling_not_excluded_or_segmented")
    return issues


def _normalise_slice_specs(slices: Sequence[SliceSpec | Mapping[str, Any]]) -> list[SliceSpec]:
    normalised: list[SliceSpec] = []
    for item in slices:
        if isinstance(item, SliceSpec):
            normalised.append(item)
            continue
        verdict = str(item.get("feasibility_verdict", item.get("target_usage", "eligible")))
        normalised.append(
            SliceSpec(
                horizon=int(item["horizon"]),
                threshold_value=float(item.get("threshold_value", item.get("threshold"))),
                threshold_type=str(item.get("threshold_type", "fixed")),
                source_target_kind=str(item.get("target_kind", "sw2021_l2_downside_event")),
                feasibility_verdict=verdict,
                target_usage="eligible" if verdict == "eligible" else "diagnostic_only",
            )
        )
    return sorted(normalised, key=lambda value: (value.horizon, value.threshold_value, value.target_usage))


def _calendar_from_values(values: Sequence[Any]) -> list[pd.Timestamp]:
    series = pd.to_datetime(pd.Series(list(values)), errors="coerce").dt.normalize().dropna()
    return sorted(pd.Timestamp(value).normalize() for value in series.unique().tolist())


def _empty_audit_rows() -> pd.DataFrame:
    return pd.DataFrame(columns=AUDIT_COLUMNS)


def build_target_control_rows(
    price_frame: pd.DataFrame,
    slices: Sequence[SliceSpec | Mapping[str, Any]],
    *,
    cutoff_date: str | date | pd.Timestamp = INFORMATION_CUTOFF_DATE,
    holdout_start: str | date | pd.Timestamp = HOLDOUT_START,
    metadata_frame: pd.DataFrame | None = None,
    excluded_entity_ids: set[str] | None = None,
    trading_calendar: Sequence[Any] | None = None,
    include_prospective: bool = False,
    source_db_path: Path | str | None = None,
    created_at: str | None = None,
) -> pd.DataFrame:
    data = _normalise_prices(price_frame)
    specs = _normalise_slice_specs(slices)
    if data.empty or not specs:
        return _empty_audit_rows()

    cutoff = pd.Timestamp(cutoff_date).normalize()
    holdout = pd.Timestamp(holdout_start).normalize()
    excluded = excluded_entity_ids or set()
    created = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    safe_db = _safe_path(source_db_path)
    global_calendar = _calendar_from_values(trading_calendar) if trading_calendar is not None else None
    meta_by_entity: dict[str, dict[str, Any]] = {}
    if metadata_frame is not None and not metadata_frame.empty:
        meta = metadata_frame.copy()
        if "sector_id" in meta.columns and "entity_id" not in meta.columns:
            meta = meta.rename(columns={"sector_id": "entity_id"})
        for row in meta.to_dict(orient="records"):
            meta_by_entity[str(row.get("entity_id"))] = row

    rows: list[dict[str, Any]] = []
    for entity_id, group in data.groupby("entity_id", sort=False):
        entity_id = str(entity_id)
        if entity_id in excluded:
            continue
        group = group.sort_values("trade_date").reset_index(drop=True)
        price_map = {pd.Timestamp(row.trade_date).normalize(): float(row.close) for row in group.itertuples()}
        calendar = global_calendar or _calendar_from_values(group["trade_date"].tolist())
        position_by_date = {value: idx for idx, value in enumerate(calendar)}
        info = meta_by_entity.get(entity_id, {})
        sector_name = info.get("sector_name")

        for trade_ts in group["trade_date"].tolist():
            trade_ts = pd.Timestamp(trade_ts).normalize()
            if trade_ts > cutoff and not include_prospective:
                continue
            if trade_ts not in position_by_date:
                continue
            base_position = position_by_date[trade_ts]
            for spec in specs:
                start_position = base_position + 1
                end_position = base_position + int(spec.horizon)
                start_date = calendar[start_position] if start_position < len(calendar) else None
                end_date = calendar[end_position] if end_position < len(calendar) else None
                split_role = "historical_development" if trade_ts < holdout else "prospective_final_holdout"
                metrics: dict[str, float] | None = None
                censoring_status = "insufficient_future_prices"
                exclusion_reason = None
                if split_role == "prospective_final_holdout":
                    censoring_status = "excluded"
                    exclusion_reason = "prospective_final_holdout_withheld"
                elif end_date is not None and end_date > cutoff:
                    censoring_status = "cross_cutoff_censored"
                elif end_date is not None:
                    window_dates = calendar[base_position : end_position + 1]
                    if len(window_dates) == int(spec.horizon) + 1 and all(value in price_map for value in window_dates):
                        closes = [price_map[value] for value in window_dates]
                        metrics = compute_path_metrics(closes, base_index=0, horizon=int(spec.horizon))
                    censoring_status = "labeled" if metrics is not None else "insufficient_future_prices"
                event_label: bool | None = None
                if metrics is not None and censoring_status == "labeled":
                    event_label = bool(metrics["future_mae"] <= -float(spec.threshold_value))
                rows.append(
                    {
                        "trade_date": trade_ts.date(),
                        "entity_id": entity_id,
                        "sector_name": sector_name,
                        "split_role": split_role,
                        "target_usage": spec.target_usage,
                        "horizon": int(spec.horizon),
                        "threshold_type": spec.threshold_type,
                        "threshold_value": float(spec.threshold_value),
                        "target_kind": "downside_event",
                        "target_observation_start_date": None if start_date is None else start_date.date(),
                        "target_observation_end_date": None if end_date is None else end_date.date(),
                        "future_return": None if metrics is None else metrics["future_return"],
                        "future_mae": None if metrics is None else metrics["future_mae"],
                        "future_mdd": None if metrics is None else metrics["future_mdd"],
                        "future_realized_vol": None if metrics is None else metrics["future_realized_vol"],
                        "future_downside_vol": None if metrics is None else metrics["future_downside_vol"],
                        "event_label": event_label,
                        "censoring_status": censoring_status,
                        "exclusion_reason": exclusion_reason,
                        "sample_weight": 1.0 if censoring_status == "labeled" else 0.0,
                        "source_db_path": safe_db,
                        "created_at": created,
                    }
                )
    if not rows:
        return _empty_audit_rows()
    return pd.DataFrame(rows)[AUDIT_COLUMNS]


def _select_audit_price_panel(price_frame: pd.DataFrame, *, entity_limit: int = 5, date_limit: int = 90) -> pd.DataFrame:
    data = _normalise_prices(price_frame)
    if data.empty:
        return data
    selected_entities = sorted(data["entity_id"].astype(str).unique().tolist())[:entity_limit]
    parts: list[pd.DataFrame] = []
    for entity_id in selected_entities:
        group = data[data["entity_id"].astype(str).eq(entity_id)].sort_values("trade_date")
        parts.append(group.head(date_limit))
    if not parts:
        return data.head(0)
    return pd.concat(parts, ignore_index=True)


def validate_target_row_invariants(
    rows: pd.DataFrame,
    price_frame: pd.DataFrame,
    *,
    cutoff_date: str | date | pd.Timestamp = INFORMATION_CUTOFF_DATE,
    holdout_start: str | date | pd.Timestamp = HOLDOUT_START,
    trading_calendar: Sequence[Any] | None = None,
) -> dict[str, int]:
    counts = {
        "label_window_violation_count": 0,
        "future_window_off_by_one_violation_count": 0,
        "mdd_window_violation_count": 0,
        "cross_cutoff_violation_count": 0,
        "historical_development_bad_label_count": 0,
        "prospective_holdout_label_consumed_count": 0,
    }
    if rows.empty:
        return counts

    prices = _normalise_prices(price_frame)
    global_calendar = _calendar_from_values(trading_calendar) if trading_calendar is not None else None
    price_by_entity: dict[str, tuple[list[pd.Timestamp], dict[pd.Timestamp, float]]] = {}
    for entity_id, group in prices.groupby("entity_id", sort=False):
        calendar = global_calendar or _calendar_from_values(group["trade_date"].tolist())
        price_map = {pd.Timestamp(row.trade_date).normalize(): float(row.close) for row in group.itertuples()}
        price_by_entity[str(entity_id)] = (calendar, price_map)

    cutoff = pd.Timestamp(cutoff_date).normalize()
    holdout = pd.Timestamp(holdout_start).normalize()
    for _, row in rows.iterrows():
        status = str(row.get("censoring_status", ""))
        trade_ts = pd.to_datetime(row.get("trade_date"), errors="coerce")
        start_ts = pd.to_datetime(row.get("target_observation_start_date"), errors="coerce")
        end_ts = pd.to_datetime(row.get("target_observation_end_date"), errors="coerce")
        label = row.get("event_label")
        weight = pd.to_numeric(pd.Series([row.get("sample_weight")]), errors="coerce").iloc[0]

        if status not in ALLOWED_CENSORING_STATUSES:
            counts["label_window_violation_count"] += 1
        if pd.notna(trade_ts) and pd.notna(end_ts) and trade_ts > end_ts:
            counts["label_window_violation_count"] += 1
        if status == "excluded" and not str(row.get("exclusion_reason") or "").strip():
            counts["label_window_violation_count"] += 1
        if status != "labeled" and not pd.isna(label):
            counts["label_window_violation_count"] += 1
        if status == "labeled" and not isinstance(label, (bool, np.bool_)):
            counts["label_window_violation_count"] += 1
        if status == "labeled" and (not math.isfinite(float(weight)) or float(weight) <= 0.0):
            counts["label_window_violation_count"] += 1

        if pd.notna(trade_ts) and pd.Timestamp(trade_ts).normalize() >= holdout and status == "labeled":
            counts["prospective_holdout_label_consumed_count"] += 1
        if (
            str(row.get("split_role")) == "historical_development"
            and pd.notna(end_ts)
            and pd.Timestamp(end_ts).normalize() > cutoff
            and status not in {"cross_cutoff_censored", "excluded"}
        ):
            counts["cross_cutoff_violation_count"] += 1
        if (
            str(row.get("split_role")) == "historical_development"
            and status == "labeled"
            and pd.notna(end_ts)
            and pd.Timestamp(end_ts).normalize() > cutoff
        ):
            counts["historical_development_bad_label_count"] += 1

        if status != "labeled" or pd.isna(trade_ts):
            continue
        entity_key = str(row.get("entity_id"))
        if entity_key not in price_by_entity:
            continue
        calendar, price_map = price_by_entity[entity_key]
        trade_norm = pd.Timestamp(trade_ts).normalize()
        if trade_norm not in calendar:
            continue
        base_position = calendar.index(trade_norm)
        horizon = int(row.get("horizon"))
        start_position = base_position + 1
        end_position = base_position + horizon
        expected_start = calendar[start_position] if start_position < len(calendar) else None
        expected_end = calendar[end_position] if end_position < len(calendar) else None
        if expected_start is not None and (pd.isna(start_ts) or pd.Timestamp(start_ts).normalize() != expected_start):
            counts["label_window_violation_count"] += 1
        if expected_end is not None and (pd.isna(end_ts) or pd.Timestamp(end_ts).normalize() != expected_end):
            counts["label_window_violation_count"] += 1
        if expected_end is None:
            continue
        window_dates = calendar[base_position : end_position + 1]
        if not all(value in price_map for value in window_dates):
            continue
        metrics = compute_path_metrics([price_map[value] for value in window_dates], base_index=0, horizon=horizon)
        if metrics is None:
            continue
        for field in ["future_return", "future_mae"]:
            actual = pd.to_numeric(pd.Series([row.get(field)]), errors="coerce").iloc[0]
            if not math.isclose(float(actual), float(metrics[field]), rel_tol=1e-10, abs_tol=1e-12):
                counts["future_window_off_by_one_violation_count"] += 1
                break
        actual_mdd = pd.to_numeric(pd.Series([row.get("future_mdd")]), errors="coerce").iloc[0]
        if not math.isclose(float(actual_mdd), float(metrics["future_mdd"]), rel_tol=1e-10, abs_tol=1e-12):
            counts["mdd_window_violation_count"] += 1
    return counts


def run_cross_cutoff_regression() -> dict[str, Any]:
    spec = SliceSpec(
        horizon=2,
        threshold_value=0.05,
        threshold_type="fixed",
        source_target_kind="sw2021_l2_downside_event",
        feasibility_verdict="eligible",
        target_usage="eligible",
    )
    calendar = pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"])
    base_prices = pd.DataFrame(
        {
            "entity_id": ["industry:synthetic"] * 3,
            "trade_date": pd.to_datetime(["2026-06-08", "2026-06-09", "2026-06-10"]),
            "close": [100.0, 99.0, 98.0],
        }
    )
    appended_prices = pd.concat(
        [
            base_prices,
            pd.DataFrame(
                {
                    "entity_id": ["industry:synthetic"] * 2,
                    "trade_date": pd.to_datetime(["2026-06-11", "2026-06-12"]),
                    "close": [70.0, 60.0],
                }
            ),
        ],
        ignore_index=True,
    )
    before = build_target_control_rows(base_prices, [spec], trading_calendar=calendar, cutoff_date=INFORMATION_CUTOFF_DATE)
    after = build_target_control_rows(appended_prices, [spec], trading_calendar=calendar, cutoff_date=INFORMATION_CUTOFF_DATE)
    before_cross = before[before["censoring_status"].isin(["cross_cutoff_censored", "excluded"])].copy()
    after_by_key = {
        (str(row.entity_id), str(row.trade_date), int(row.horizon), float(row.threshold_value)): row
        for row in after.itertuples()
    }
    violations = 0
    for row in before_cross.itertuples():
        key = (str(row.entity_id), str(row.trade_date), int(row.horizon), float(row.threshold_value))
        after_row = after_by_key.get(key)
        if after_row is None or after_row.censoring_status not in {"cross_cutoff_censored", "excluded"}:
            violations += 1
        elif not pd.isna(after_row.event_label):
            violations += 1
    return {
        "passed": violations == 0 and int(len(before_cross)) > 0,
        "violation_count": int(violations),
        "cross_cutoff_censored_or_excluded_count": int(len(before_cross)),
        "base_rows_checked": int(len(before)),
        "appended_rows_checked": int(len(after)),
    }


def _date_or_none(value: Any) -> pd.Timestamp | None:
    parsed = pd.to_datetime(value, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _intervals_overlap(start_a: Any, end_a: Any, start_b: Any, end_b: Any) -> bool:
    a_start = _date_or_none(start_a)
    a_end = _date_or_none(end_a)
    b_start = _date_or_none(start_b)
    b_end = _date_or_none(end_b)
    if a_start is None or a_end is None or b_start is None or b_end is None:
        return False
    return bool(a_start <= b_end and b_start <= a_end)


def _add_trading_days_after(value: pd.Timestamp, trading_dates: Sequence[pd.Timestamp], days: int) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    dates = sorted(pd.Timestamp(item).normalize() for item in trading_dates)
    after = [item for item in dates if item > value]
    if not after:
        return None, None
    start = after[0]
    end = after[min(max(int(days) - 1, 0), len(after) - 1)]
    return start, end


def _row_target_window(row: pd.Series) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    return _date_or_none(row.get("target_observation_start_date")), _date_or_none(row.get("target_observation_end_date"))


def build_purge_embargo_fold_plan(
    target_rows: pd.DataFrame,
    *,
    policy: Mapping[str, Any] | None = None,
    fold_count: int = 3,
    assignment_sample_cap: int = 300,
) -> dict[str, Any]:
    policy = dict(policy or default_purge_embargo_policy())
    embargo_days = int(policy.get("embargo_days", DEFAULT_EMBARGO_DAYS))
    if target_rows.empty:
        return {
            "index_id": INDEX_ID,
            "policy_version": POLICY_VERSION,
            "status": "partial_no_rows",
            "fold_plan_source": policy.get("fold_plan_source"),
            "final_holdout_policy": policy.get("final_holdout_policy"),
            "fold_count": 0,
            "folds": [],
            "purge_violation_count": 0,
            "embargo_violation_count": 0,
            "prospective_holdout_label_consumed_count": 0,
        }

    work = target_rows.copy().reset_index(drop=True)
    work["_row_id"] = work.index.astype(int)
    work["_trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["_target_start"] = pd.to_datetime(work["target_observation_start_date"], errors="coerce").dt.normalize()
    work["_target_end"] = pd.to_datetime(work["target_observation_end_date"], errors="coerce").dt.normalize()
    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE)
    holdout = pd.Timestamp(HOLDOUT_START)
    historical = work["_trade_date"].notna() & (work["_trade_date"] <= cutoff) & (work["_trade_date"] < holdout)
    usable = (
        historical
        & work["censoring_status"].astype(str).eq("labeled")
        & work["target_usage"].astype(str).isin({"eligible", "diagnostic_only"})
    )
    unique_dates = sorted(work.loc[historical, "_trade_date"].dropna().unique().tolist())
    labeled_dates = sorted(work.loc[usable, "_trade_date"].dropna().unique().tolist())
    if len(labeled_dates) < 4:
        return {
            "index_id": INDEX_ID,
            "policy_version": POLICY_VERSION,
            "status": "partial_too_few_labeled_dates",
            "fold_plan_source": policy.get("fold_plan_source"),
            "final_holdout_policy": policy.get("final_holdout_policy"),
            "fold_count": 0,
            "folds": [],
            "purge_violation_count": 0,
            "embargo_violation_count": 0,
            "prospective_holdout_label_consumed_count": int(
                len(work[(work["_trade_date"] >= holdout) & work["censoring_status"].astype(str).eq("labeled")])
            ),
        }

    requested_folds = max(1, min(int(fold_count), len(labeled_dates) - 1))
    split_count = requested_folds + 1
    chunks = [chunk for chunk in np.array_split(np.asarray(labeled_dates, dtype="datetime64[ns]"), split_count) if len(chunk)]
    validation_chunks = chunks[1:]
    folds: list[dict[str, Any]] = []
    aggregate_purge_violations = 0
    aggregate_embargo_violations = 0

    for fold_no, chunk in enumerate(validation_chunks, start=1):
        validation_dates = [pd.Timestamp(value).normalize() for value in chunk.tolist()]
        validation_start = validation_dates[0]
        validation_end = validation_dates[-1]
        embargo_start, embargo_end = _add_trading_days_after(validation_end, unique_dates, embargo_days)
        validation_mask = usable & work["_trade_date"].between(validation_start, validation_end, inclusive="both")
        validation_rows = work[validation_mask]
        train_candidate_mask = usable & ~validation_mask

        def overlaps_validation(row: pd.Series) -> bool:
            row_start, row_end = _row_target_window(row)
            if row_start is None or row_end is None:
                return False
            for _, val in validation_rows.iterrows():
                if _intervals_overlap(row_start, row_end, val.get("target_observation_start_date"), val.get("target_observation_end_date")):
                    return True
            return False

        purge_mask = pd.Series(False, index=work.index)
        if not validation_rows.empty:
            candidate_rows = work[train_candidate_mask]
            purge_indices = [int(idx) for idx, row in candidate_rows.iterrows() if overlaps_validation(row)]
            purge_mask.loc[purge_indices] = True

        embargo_mask = pd.Series(False, index=work.index)
        if embargo_start is not None and embargo_end is not None:
            embargo_mask = train_candidate_mask & ~purge_mask & work["_trade_date"].between(
                embargo_start,
                embargo_end,
                inclusive="both",
            )
        train_mask = train_candidate_mask & ~purge_mask & ~embargo_mask
        excluded_mask = ~(train_mask | validation_mask | purge_mask | embargo_mask)

        train_rows = work[train_mask]
        purge_violations = 0
        embargo_violations = 0
        for _, train_row in train_rows.iterrows():
            if overlaps_validation(train_row):
                purge_violations += 1
            train_date = train_row.get("_trade_date")
            if (
                embargo_start is not None
                and embargo_end is not None
                and pd.notna(train_date)
                and embargo_start <= pd.Timestamp(train_date).normalize() <= embargo_end
            ):
                embargo_violations += 1
        aggregate_purge_violations += int(purge_violations)
        aggregate_embargo_violations += int(embargo_violations)

        assignments: list[dict[str, Any]] = []
        for row_index, row in work.iterrows():
            assignment = "excluded"
            reason = "not_historical_development_labeled_row"
            if bool(validation_mask.loc[row_index]):
                assignment = "validation"
                reason = "validation_interval"
            elif bool(purge_mask.loc[row_index]):
                assignment = "purged"
                reason = "target_window_overlaps_validation_interval"
            elif bool(embargo_mask.loc[row_index]):
                assignment = "embargoed"
                reason = "trade_date_inside_post_validation_embargo"
            elif bool(train_mask.loc[row_index]):
                assignment = "train"
                reason = "eligible_after_purge_embargo"
            assignments.append(
                {
                    "row_id": int(row["_row_id"]),
                    "trade_date": _json_safe(row.get("trade_date")),
                    "entity_id": row.get("entity_id"),
                    "horizon": int(row.get("horizon")) if not pd.isna(row.get("horizon")) else None,
                    "threshold_value": _json_safe(row.get("threshold_value")),
                    "assignment": assignment,
                    "reason": reason,
                }
            )
        assignment_counts = {
            "train": int(train_mask.sum()),
            "validation": int(validation_mask.sum()),
            "purged": int(purge_mask.sum()),
            "embargoed": int(embargo_mask.sum()),
            "excluded": int(excluded_mask.sum()),
        }
        folds.append(
            {
                "fold_id": f"fold_{fold_no}",
                "fold_start_date": _json_safe(validation_start),
                "fold_end_date": _json_safe(validation_end),
                "train_start_date": _json_safe(train_rows["_trade_date"].min()) if not train_rows.empty else None,
                "train_end_date": _json_safe(train_rows["_trade_date"].max()) if not train_rows.empty else None,
                "validation_start_date": _json_safe(validation_start),
                "validation_end_date": _json_safe(validation_end),
                "embargo_start_date": _json_safe(embargo_start),
                "embargo_end_date": _json_safe(embargo_end),
                "train_row_count": int(train_mask.sum()),
                "validation_row_count": int(validation_mask.sum()),
                "purged_row_count": int(purge_mask.sum()),
                "embargoed_row_count": int(embargo_mask.sum()),
                "excluded_row_count": int(excluded_mask.sum()),
                "max_horizon_days": int(policy.get("max_horizon_days", MAX_HORIZON_DAYS)),
                "embargo_days": embargo_days,
                "purge_violation_count": int(purge_violations),
                "embargo_violation_count": int(embargo_violations),
                "assignment_counts": assignment_counts,
                "row_assignments": assignments[:assignment_sample_cap],
                "row_assignment_sample_cap": assignment_sample_cap,
            }
        )

    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "status": "pass" if aggregate_purge_violations == 0 and aggregate_embargo_violations == 0 and folds else "fail",
        "fold_plan_source": policy.get("fold_plan_source"),
        "final_holdout_policy": policy.get("final_holdout_policy"),
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "fold_count": int(len(folds)),
        "folds": folds,
        "purge_violation_count": int(aggregate_purge_violations),
        "embargo_violation_count": int(aggregate_embargo_violations),
        "prospective_holdout_label_consumed_count": int(
            len(work[(work["_trade_date"] >= holdout) & work["censoring_status"].astype(str).eq("labeled")])
        ),
    }


def detect_feature_namespace_violations(feature_columns: Sequence[str]) -> dict[str, Any]:
    columns = [str(column) for column in feature_columns]
    target_collisions = []
    future_collisions = []
    for column in columns:
        if column in TARGET_NAMESPACE_COLUMNS or column.startswith("target_"):
            target_collisions.append(column)
        if column.startswith("future_") or column in {
            "future_return",
            "future_mae",
            "future_mdd",
            "future_realized_vol",
            "future_downside_vol",
        }:
            future_collisions.append(column)
    return {
        "feature_namespace_forbidden_terms": FEATURE_NAMESPACE_FORBIDDEN_TERMS,
        "target_namespace_columns": TARGET_NAMESPACE_COLUMNS,
        "feature_asof_required": "yes",
        "feature_asof_max_date_policy": "feature_asof_date <= trade_date",
        "future_derived_feature_violation_count": int(len(set(future_collisions))),
        "feature_target_collision_violation_count": int(len(set(target_collisions))),
        "future_derived_feature_violations": sorted(set(future_collisions)),
        "feature_target_collision_violations": sorted(set(target_collisions)),
        "feature_namespace_policy_status": "pass"
        if not future_collisions and not target_collisions
        else "fail",
    }


def _blocked_report(
    *,
    status: str,
    db_path: Path | str,
    wp1_support_status: str | None,
    reasons: Sequence[str],
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "contract_status": "blocked",
        "wp1_support_status": wp1_support_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "entity_count_after_silent_break_handling": 0,
        "target_row_count_checked": 0,
        "sample_row_count_checked": 0,
        "label_window_violation_count": 0,
        "future_window_off_by_one_violation_count": 0,
        "mdd_window_violation_count": 0,
        "cross_cutoff_violation_count": 0,
        "cross_cutoff_regression_passed": "no",
        "cross_cutoff_censored_or_excluded_count": 0,
        "historical_development_bad_label_count": 0,
        "prospective_holdout_label_consumed_count": 0,
        "purge_policy_status": "blocked",
        "embargo_policy_status": "blocked",
        "fold_count": 0,
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
        "feature_namespace_policy_status": "blocked",
        "future_derived_feature_violation_count": 0,
        "feature_target_collision_violation_count": 0,
        "ci_gate_status": status,
        "boundary_flags": BOUNDARY_FLAGS,
        "blocking_reasons": list(reasons),
        "external_data_fetch": "no",
        "no_fetch": True,
    }


def _blocked_fold_plan(status: str, reasons: Sequence[str]) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "policy_version": POLICY_VERSION,
        "status": status,
        "blocking_reasons": list(reasons),
        "fold_count": 0,
        "folds": [],
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
        "prospective_holdout_label_consumed_count": 0,
    }


def _write_blocked_outputs(
    *,
    report: Mapping[str, Any],
    output: Path,
    summary_json: Path,
    fold_plan: Path,
    audit_sample: Path,
    sample_cap: int,
    policy: Path | None,
    policy_explicit: bool,
) -> None:
    _write_markdown(output, report)
    _write_json(summary_json, report)
    _write_json(fold_plan, _blocked_fold_plan(str(report.get("status")), report.get("blocking_reasons", [])))
    _write_audit_sample(audit_sample, _empty_audit_rows(), sample_cap)
    if policy is not None and policy_explicit:
        _write_json(policy, default_purge_embargo_policy())


def _status_from_counts(
    *,
    invariant_counts: Mapping[str, int],
    cross_cutoff: Mapping[str, Any],
    fold_plan: Mapping[str, Any],
    feature_policy: Mapping[str, Any],
) -> str:
    hard_counts = [
        int(invariant_counts.get("label_window_violation_count", 0)),
        int(invariant_counts.get("future_window_off_by_one_violation_count", 0)),
        int(invariant_counts.get("mdd_window_violation_count", 0)),
        int(invariant_counts.get("cross_cutoff_violation_count", 0)),
        int(invariant_counts.get("historical_development_bad_label_count", 0)),
        int(invariant_counts.get("prospective_holdout_label_consumed_count", 0)),
        int(cross_cutoff.get("violation_count", 0)),
        int(fold_plan.get("purge_violation_count", 0)),
        int(fold_plan.get("embargo_violation_count", 0)),
        int(feature_policy.get("future_derived_feature_violation_count", 0)),
        int(feature_policy.get("feature_target_collision_violation_count", 0)),
    ]
    if not cross_cutoff.get("passed"):
        return "fail"
    if any(value > 0 for value in hard_counts):
        return "fail"
    if int(fold_plan.get("fold_count", 0)) <= 0:
        return "partial"
    if feature_policy.get("feature_namespace_policy_status") != "pass":
        return "fail"
    return "pass"


def build_target_controls_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    target_universe: Path | str = DEFAULT_TARGET_UNIVERSE,
    feasibility: Path | str = DEFAULT_FEASIBILITY,
    policy: Path | str | None = None,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    fold_plan: Path | str = DEFAULT_FOLD_PLAN,
    audit_sample: Path | str = DEFAULT_AUDIT_SAMPLE,
    audit_sample_cap: int = DEFAULT_AUDIT_SAMPLE_ROWS,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V WP2 target controls are no-fetch only")

    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    fold_path = Path(fold_plan)
    sample_path = Path(audit_sample)
    policy_explicit = policy is not None
    policy_path = Path(policy) if policy is not None else DEFAULT_POLICY
    policy_doc = default_purge_embargo_policy()

    try:
        support = _load_json(target_support)
    except FileNotFoundError:
        report = _blocked_report(
            status="blocked_wp1_not_ready",
            db_path=resolved_db,
            wp1_support_status="missing",
            reasons=["wp1_target_support_missing"],
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_plan=fold_path,
            audit_sample=sample_path,
            sample_cap=audit_sample_cap,
            policy=policy_path,
            policy_explicit=policy_explicit,
        )
        return report

    wp1_issues = validate_wp1_support(support, db_path=resolved_db)
    if wp1_issues:
        report = _blocked_report(
            status="blocked_wp1_not_ready",
            db_path=resolved_db,
            wp1_support_status=str(support.get("status", "unknown")),
            reasons=wp1_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_plan=fold_path,
            audit_sample=sample_path,
            sample_cap=audit_sample_cap,
            policy=policy_path,
            policy_explicit=policy_explicit,
        )
        return report

    try:
        universe_manifest = _load_json(target_universe)
    except FileNotFoundError:
        universe_manifest = {}
    universe_issues = validate_target_universe_manifest(universe_manifest, db_path=resolved_db)
    if universe_issues:
        report = _blocked_report(
            status="blocked_wp1_not_ready",
            db_path=resolved_db,
            wp1_support_status=str(support.get("status", "unknown")),
            reasons=universe_issues,
        )
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_plan=fold_path,
            audit_sample=sample_path,
            sample_cap=audit_sample_cap,
            policy=policy_path,
            policy_explicit=policy_explicit,
        )
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            wp1_support_status=str(support.get("status", "unknown")),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        _write_blocked_outputs(
            report=report,
            output=output_path,
            summary_json=summary_path,
            fold_plan=fold_path,
            audit_sample=sample_path,
            sample_cap=audit_sample_cap,
            policy=policy_path,
            policy_explicit=policy_explicit,
        )
        return report

    feasibility_report = load_feasibility_report(feasibility)
    slices = _slice_specs_from_feasibility(feasibility_report)
    audit_prices = _select_audit_price_panel(v7.price_frame)
    audit_calendar = _calendar_from_values(audit_prices["trade_date"].tolist())
    audit_rows_full = build_target_control_rows(
        audit_prices,
        slices,
        cutoff_date=INFORMATION_CUTOFF_DATE,
        holdout_start=HOLDOUT_START,
        metadata_frame=v7.universe_frame,
        source_db_path=resolved_db,
        trading_calendar=audit_calendar,
    )
    audit_rows = (
        audit_rows_full.sort_values(["entity_id", "trade_date", "horizon", "threshold_value"]).head(audit_sample_cap)
        if not audit_rows_full.empty
        else audit_rows_full
    )
    sample_count = _write_audit_sample(sample_path, audit_rows, audit_sample_cap)
    invariant_counts = validate_target_row_invariants(
        audit_rows,
        audit_prices,
        cutoff_date=INFORMATION_CUTOFF_DATE,
        holdout_start=HOLDOUT_START,
        trading_calendar=audit_calendar,
    )
    cross_cutoff = run_cross_cutoff_regression()
    fold_doc = build_purge_embargo_fold_plan(audit_rows, policy=policy_doc)
    feature_policy = detect_feature_namespace_violations(["trade_date", "entity_id", "hmm_state_label", "feature_asof_date"])
    status = _status_from_counts(
        invariant_counts=invariant_counts,
        cross_cutoff=cross_cutoff,
        fold_plan=fold_doc,
        feature_policy=feature_policy,
    )
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "contract_status": "pass" if status == "pass" else status,
        "wp1_support_status": support.get("status"),
        "target_support_path": _safe_path(target_support),
        "target_universe_path": _safe_path(target_universe),
        "feasibility_path": _safe_path(feasibility),
        "policy_path": _safe_path(policy_path),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "v7_db_requirement_status": v7.coverage.get("v7_db_requirement_status"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "universe_source_status": v7.coverage.get("universe_source_status"),
        "taxonomy_source_status": universe_manifest.get("source", {}).get("taxonomy_source_status"),
        "coverage_start": v7.coverage.get("coverage_start"),
        "coverage_end": v7.coverage.get("coverage_end"),
        "entity_count_after_silent_break_handling": v7.coverage.get("entity_count_after_silent_break_handling"),
        "silent_entity_break_count": v7.coverage.get("silent_entity_break_count"),
        "silent_entity_break_handling": v7.coverage.get("silent_entity_break_handling"),
        "silent_entity_break_entities": support.get("silent_entity_break_entities", []),
        "target_row_count_checked": int(len(audit_rows)),
        "sample_row_count_checked": int(sample_count),
        "audit_sample_rows": int(sample_count),
        "audit_sample_path": _safe_path(sample_path),
        **invariant_counts,
        "cross_cutoff_regression_passed": "yes" if cross_cutoff.get("passed") else "no",
        "cross_cutoff_censored_or_excluded_count": int(cross_cutoff.get("cross_cutoff_censored_or_excluded_count", 0))
        + int(
            len(
                audit_rows[
                    audit_rows["censoring_status"].isin(["cross_cutoff_censored", "excluded"])
                    & pd.to_datetime(audit_rows["target_observation_end_date"], errors="coerce").gt(
                        pd.Timestamp(INFORMATION_CUTOFF_DATE)
                    )
                ]
            )
        ),
        "cross_cutoff_regression": cross_cutoff,
        "purge_policy_status": "pass" if fold_doc.get("purge_violation_count") == 0 else "fail",
        "embargo_policy_status": "pass" if fold_doc.get("embargo_violation_count") == 0 else "fail",
        "fold_count": int(fold_doc.get("fold_count", 0)),
        "purge_violation_count": int(fold_doc.get("purge_violation_count", 0)),
        "embargo_violation_count": int(fold_doc.get("embargo_violation_count", 0)),
        **feature_policy,
        "ci_gate_status": "pass" if status == "pass" else status,
        "boundary_flags": BOUNDARY_FLAGS,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "no_fetch": True,
        "external_data_fetch": "no",
        "target_dataset_modified": "no",
        "model_training": "no",
        "probability_calibration": "no",
        "readiness_assigned": "no",
        "holdout_consumed": "no",
        "HMM_HSMM_training_modified": "no",
        "stage03v2_implemented": "no",
        "stage03v3_implemented": "no",
        "blocking_reasons": [],
    }
    _write_json(policy_path, policy_doc)
    _write_json(fold_path, fold_doc)
    _write_markdown(output_path, report)
    _write_json(summary_path, report)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--target-universe", type=Path, default=DEFAULT_TARGET_UNIVERSE)
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY)
    parser.add_argument("--policy", type=Path, default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--fold-plan", type=Path, default=DEFAULT_FOLD_PLAN)
    parser.add_argument("--audit-sample", type=Path, default=DEFAULT_AUDIT_SAMPLE)
    parser.add_argument("--audit-sample-cap", type=int, default=DEFAULT_AUDIT_SAMPLE_ROWS)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_target_controls_report(
        db_path=args.db,
        target_support=args.target_support,
        target_universe=args.target_universe,
        feasibility=args.feasibility,
        policy=args.policy,
        output=args.output,
        summary_json=args.summary_json,
        fold_plan=args.fold_plan,
        audit_sample=args.audit_sample,
        audit_sample_cap=args.audit_sample_cap,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_TARGET_CONTROLS="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"report={_safe_path(args.output)} "
        f"summary_json={_safe_path(args.summary_json)} "
        f"fold_plan={_safe_path(args.fold_plan)} "
        "no_fetch=yes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
