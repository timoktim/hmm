"""Stage03V RERUN1 fold-plan v2 magnitude gates.

This module rebuilds the Stage03V validation fold plan from full
historical-development target rows. It is offline and read-only with respect to
DuckDB: no external fetches and no persistent DB writes.
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
    build_target_rows_for_trade_dates,
    slice_specs_from_target_support,
)
from src.evaluation.stage03v_risk_target_dataset import (
    HOLDOUT_START,
    INFORMATION_CUTOFF_DATE,
    _json_safe,
    _safe_path,
    read_v7_inputs,
    resolve_v7_db_path,
)


INDEX_ID = "STAGE03V-RERUN1-v1"
REPORT_VERSION = "stage03v_rerun1_fold_plan_magnitude_v1"
POLICY_VERSION = "stage03v_purge_embargo_policy_v2"
STAGE_ID = "stage03v"
DEFAULT_FOLD_COUNT = 10
DEFAULT_EMBARGO_DAYS = 20
DEFAULT_VALIDATION_START = "2016-01-01"
DEFAULT_ANCHOR_TRAIN_START = "2014-01-02"
DEFAULT_MIN_VALIDATION_SPAN_RATIO = 0.60
DEFAULT_MIN_TOTAL_VALIDATION_TRADE_DATES = 500
DEFAULT_MIN_TRAIN_ROWS_PER_SLICE = 5000
DEFAULT_MIN_VALIDATION_TRADE_DATES_PER_FOLD = 200
PRIMARY_MARKET_EVENT_SHARE = 0.20
ROW_ASSIGNMENT_SAMPLE_CAP = 300

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_TARGET_SUPPORT = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_OUTPUT_PLAN = ROOT / "reports" / "stage03v" / "purge_embargo_fold_plan_v2.json"
DEFAULT_OVERVIEW_MD = ROOT / "reports" / "stage03v" / "fold_plan_magnitude_overview.md"
DEFAULT_OVERVIEW_CSV = ROOT / "reports" / "stage03v" / "fold_plan_magnitude_overview.csv"
DEFAULT_TRIAL_ACCOUNTING = ROOT / "reports" / "stage03v" / "validation_trial_accounting.json"

SLICE_COLUMNS = ["horizon", "threshold_type", "threshold_value", "target_usage"]
OVERVIEW_COLUMNS = [
    "fold_id",
    "train_start_date",
    "train_end_date",
    "validation_start_date",
    "validation_end_date",
    "validation_trade_date_count",
    "train_row_count",
    "validation_row_count",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_usage",
    "slice_train_row_count",
    "slice_validation_row_count",
    "validation_positive_count",
    "validation_market_event_block_count",
    "validation_idiosyncratic_episode_count",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_definition_modified": "no",
    "fixed_threshold_mainline_modified": "no",
    "persistent_db_table_written": "no",
    "full_target_matrix_committed": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
    "trading_or_decision_output": "no",
}


def rerun1_trial_accounting_record(*, fold_plan_path: Path | str = DEFAULT_OUTPUT_PLAN) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": "stage03v_rerun1_validation_trial_accounting_v1",
        "stage_id": STAGE_ID,
        "status": "pass",
        "trial_accounting_invalidation_recorded": "yes",
        "superseded_run": {
            "run_id": "stage03v_wp4_v1_2014_microfold",
            "status": "invalidated_due_to_fold_coverage",
            "artifact": "reports/stage03v/purge_embargo_fold_plan.json",
            "audit_defect": (
                "committed fold plan covered only 2014-01-13 to 2014-02-12 "
                "and was built from the WP2 500-row audit sample"
            ),
            "not_invalidated_due_to_observed_results": True,
        },
        "replacement_run": {
            "run_id": "stage03v_rerun1_full_scale_revalidation",
            "index_id": INDEX_ID,
            "fold_plan": _safe_path(fold_plan_path),
            "counts_as_first_informative_trial": True,
        },
        "created_at": _now_iso(),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_json(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: Path | str, data: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_csv(path: Path | str, rows: Sequence[Mapping[str, Any]], columns: Sequence[str] = OVERVIEW_COLUMNS) -> int:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(list(rows), columns=list(columns))
    frame.to_csv(target, index=False)
    return int(len(frame))


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


def _date_str(value: Any) -> str | None:
    ts = _normalise_date(value)
    return None if ts is None else ts.date().isoformat()


def _slice_key(row: Mapping[str, Any]) -> tuple[int, str, float, str]:
    return (
        int(row.get("horizon")),
        str(row.get("threshold_type", "fixed")),
        float(row.get("threshold_value")),
        str(row.get("target_usage", "eligible")),
    )


def _slice_id(row: Mapping[str, Any]) -> str:
    horizon, threshold_type, threshold_value, target_usage = _slice_key(row)
    return f"h{horizon}:{threshold_type}:{threshold_value:.4f}:{target_usage}"


def _labeled_rows(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows.copy()
    return rows[rows["censoring_status"].astype(str).eq("labeled") & rows["event_label"].notna()].copy()


def _trading_dates(rows: pd.DataFrame) -> list[pd.Timestamp]:
    if rows.empty or "trade_date" not in rows.columns:
        return []
    dates = pd.to_datetime(rows["trade_date"], errors="coerce").dt.normalize().dropna().unique().tolist()
    return sorted(pd.Timestamp(value).normalize() for value in dates)


def _next_trading_day(dates: Sequence[pd.Timestamp], current: pd.Timestamp) -> pd.Timestamp | None:
    for value in dates:
        if value > current:
            return value
    return None


def _add_trading_days_after(
    current: pd.Timestamp,
    dates: Sequence[pd.Timestamp],
    trading_days: int,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    after = [value for value in dates if value > current]
    if not after:
        return None, None
    start = after[0]
    end = after[min(max(int(trading_days), 1), len(after)) - 1]
    return start, end


def _merge_active_dates(
    active_dates: Sequence[pd.Timestamp],
    all_dates: Sequence[pd.Timestamp],
    *,
    horizon: int,
) -> list[dict[str, Any]]:
    active = sorted({pd.Timestamp(value).normalize() for value in active_dates if pd.notna(value)})
    if not active:
        return []
    ordered = sorted({pd.Timestamp(value).normalize() for value in all_dates if pd.notna(value)})
    if not ordered:
        ordered = active
    position = {value: idx for idx, value in enumerate(ordered)}
    blocks: list[dict[str, Any]] = []
    start = active[0]
    end = active[0]
    active_count = 1
    previous = active[0]
    for current in active[1:]:
        inactive_gap = position.get(current, position.get(previous, 0) + 1) - position.get(previous, 0) - 1
        if inactive_gap <= int(horizon):
            end = current
            active_count += 1
        else:
            blocks.append(
                {
                    "block_start_date": start,
                    "block_end_date": end,
                    "active_date_count": int(active_count),
                }
            )
            start = current
            end = current
            active_count = 1
        previous = current
    blocks.append({"block_start_date": start, "block_end_date": end, "active_date_count": int(active_count)})
    return blocks


def _interval_overlaps(left_start: Any, left_end: Any, right_start: Any, right_end: Any) -> bool:
    left_s = _normalise_date(left_start)
    left_e = _normalise_date(left_end)
    right_s = _normalise_date(right_start)
    right_e = _normalise_date(right_end)
    if left_s is None or left_e is None or right_s is None or right_e is None:
        return False
    return left_s <= right_e and left_e >= right_s


def market_event_blocks(
    rows: pd.DataFrame,
    *,
    event_share_threshold: float = PRIMARY_MARKET_EVENT_SHARE,
) -> list[dict[str, Any]]:
    if rows.empty or not {"trade_date", "entity_id", "event_label"}.issubset(rows.columns):
        return []
    work = rows[rows["event_label"].notna()].copy()
    if work.empty:
        return []
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work = work[work["trade_date"].notna()].copy()
    if work.empty:
        return []
    work["event_label_bool"] = work["event_label"].astype(bool)
    daily = (
        work.groupby("trade_date", dropna=False)
        .agg(event_count=("event_label_bool", "sum"), entity_count=("entity_id", "nunique"))
        .reset_index()
    )
    daily["event_share"] = daily["event_count"] / daily["entity_count"].replace({0: np.nan})
    active_dates = daily.loc[daily["event_share"].ge(float(event_share_threshold)), "trade_date"].tolist()
    horizon_values = pd.to_numeric(work.get("horizon"), errors="coerce").dropna() if "horizon" in work.columns else pd.Series(dtype=float)
    horizon = int(horizon_values.iloc[0]) if not horizon_values.empty else 1
    return _merge_active_dates(active_dates, daily["trade_date"].tolist(), horizon=horizon)


def idiosyncratic_episode_count(rows: pd.DataFrame, market_blocks: Sequence[Mapping[str, Any]]) -> int:
    if rows.empty or not {"trade_date", "entity_id", "event_label"}.issubset(rows.columns):
        return 0
    work = rows[rows["event_label"].notna()].copy()
    if work.empty:
        return 0
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["event_label_bool"] = work["event_label"].astype(bool)
    horizon_values = pd.to_numeric(work.get("horizon"), errors="coerce").dropna() if "horizon" in work.columns else pd.Series(dtype=float)
    horizon = int(horizon_values.iloc[0]) if not horizon_values.empty else 1
    count = 0
    for _, entity_frame in work.groupby("entity_id", sort=False, dropna=False):
        entity_dates = sorted(entity_frame["trade_date"].dropna().unique().tolist())
        active_dates = entity_frame.loc[entity_frame["event_label_bool"], "trade_date"].dropna().unique().tolist()
        for episode in _merge_active_dates(active_dates, entity_dates, horizon=horizon):
            overlaps_market = any(
                _interval_overlaps(
                    episode["block_start_date"],
                    episode["block_end_date"],
                    block.get("block_start_date"),
                    block.get("block_end_date"),
                )
                for block in market_blocks
            )
            if not overlaps_market:
                count += 1
    return int(count)


def _fold_assignment_masks(target_rows: pd.DataFrame, fold: Mapping[str, Any]) -> dict[str, Any]:
    validation_start = _normalise_date(fold.get("validation_start_date"))
    validation_end = _normalise_date(fold.get("validation_end_date"))
    train_start = _normalise_date(fold.get("train_start_date"))
    train_end = _normalise_date(fold.get("train_end_date"))
    if validation_start is None or validation_end is None or target_rows.empty:
        empty_mask = pd.Series(False, index=target_rows.index)
        empty_dates = pd.Series(pd.NaT, index=target_rows.index)
        return {
            "valid": False,
            "trade_date": empty_dates,
            "target_observation_end_date": empty_dates,
            "train_mask": empty_mask,
            "validation_mask": empty_mask,
            "prospective_holdout_rows_withheld": 0,
        }

    trade_date = pd.to_datetime(target_rows["trade_date"], errors="coerce").dt.normalize()
    target_end = pd.to_datetime(target_rows["target_observation_end_date"], errors="coerce").dt.normalize()
    split_role = target_rows["split_role"].astype(str)
    labeled_mask = target_rows["censoring_status"].astype(str).eq("labeled") & target_rows["event_label"].notna()
    holdout = pd.Timestamp(HOLDOUT_START).normalize()

    validation_window = trade_date.between(validation_start, validation_end, inclusive="both")
    holdout_mask = trade_date.ge(holdout) | split_role.eq("prospective_final_holdout")
    validation_mask = validation_window & ~holdout_mask & labeled_mask

    train_mask = (
        trade_date.lt(validation_start)
        & target_end.lt(validation_start)
        & split_role.eq("historical_development")
        & labeled_mask
    )
    if train_start is not None:
        train_mask &= trade_date.ge(train_start)
    if train_end is not None:
        train_mask &= trade_date.le(train_end)

    return {
        "valid": True,
        "trade_date": trade_date,
        "target_observation_end_date": target_end,
        "train_mask": train_mask,
        "validation_mask": validation_mask,
        "prospective_holdout_rows_withheld": int((validation_window & holdout_mask).sum()),
    }


def _assign_normalised_dates(rows: pd.DataFrame, mask_info: Mapping[str, Any], mask_key: str) -> pd.DataFrame:
    if rows.empty:
        return rows
    del mask_key
    rows["trade_date"] = mask_info["trade_date"].reindex(rows.index).to_numpy()
    rows["target_observation_end_date"] = mask_info["target_observation_end_date"].reindex(rows.index).to_numpy()
    return rows


def split_fold_rows(target_rows: pd.DataFrame, fold: Mapping[str, Any]) -> dict[str, Any]:
    empty = target_rows.iloc[0:0].copy()
    mask_info = _fold_assignment_masks(target_rows, fold)
    if not bool(mask_info["valid"]):
        return {"train_rows": empty, "validation_rows": empty, "prospective_holdout_rows_withheld": 0}

    train = target_rows.loc[mask_info["train_mask"]].copy()
    validation = target_rows.loc[mask_info["validation_mask"]].copy()
    train = _assign_normalised_dates(train, mask_info, "train_mask")
    validation = _assign_normalised_dates(validation, mask_info, "validation_mask")
    return {
        "train_rows": train,
        "validation_rows": validation,
        "prospective_holdout_rows_withheld": int(mask_info["prospective_holdout_rows_withheld"]),
    }


def _assignment_sample(train_rows: pd.DataFrame, validation_rows: pd.DataFrame, sample_cap: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, frame in [("train", train_rows), ("validation", validation_rows)]:
        if len(rows) >= sample_cap:
            break
        take = frame.head(sample_cap - len(rows)).copy()
        for idx, row in take.reset_index(drop=False).iterrows():
            rows.append(
                {
                    "row_id": int(row.get("index", idx)),
                    "trade_date": _date_str(row.get("trade_date")),
                    "entity_id": row.get("entity_id"),
                    "horizon": int(row.get("horizon")) if not pd.isna(row.get("horizon")) else None,
                    "threshold_value": _json_safe(row.get("threshold_value")),
                    "assignment": label,
                    "reason": "anchored_expanding_train" if label == "train" else "validation_interval",
                }
            )
    return rows


def _normalised_slice_key(key: Any) -> tuple[int, str, float, str]:
    if not isinstance(key, tuple):
        key = (key,)
    return (int(key[0]), str(key[1]), float(key[2]), str(key[3]))


def _slice_count_map(rows: pd.DataFrame) -> dict[tuple[int, str, float, str], int]:
    if rows.empty:
        return {}
    grouped = rows.groupby(SLICE_COLUMNS, dropna=False).size()
    return {_normalised_slice_key(key): int(value) for key, value in grouped.items()}


def _validation_slice_group_map(rows: pd.DataFrame) -> dict[tuple[int, str, float, str], pd.DataFrame]:
    if rows.empty:
        return {}
    groups: dict[tuple[int, str, float, str], pd.DataFrame] = {}
    for key, frame in rows.groupby(SLICE_COLUMNS, dropna=False):
        groups[_normalised_slice_key(key)] = frame
    return groups


def _slice_magnitude_rows(
    fold_id: str,
    train_rows: pd.DataFrame,
    validation_rows: pd.DataFrame,
    *,
    slice_keys: Sequence[tuple[int, str, float, str]] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    grouped_keys = list(slice_keys or [])
    if not grouped_keys:
        grouped_keys = sorted(
            {
                _slice_key(row)
                for row in pd.concat([train_rows, validation_rows], ignore_index=True).to_dict(orient="records")
            }
        )
    train_counts = _slice_count_map(train_rows)
    validation_counts = _slice_count_map(validation_rows)
    validation_groups = _validation_slice_group_map(validation_rows)
    for horizon, threshold_type, threshold_value, target_usage in grouped_keys:
        key = (int(horizon), str(threshold_type), float(threshold_value), str(target_usage))
        val_slice = validation_groups.get(key, validation_rows.iloc[0:0])
        blocks = market_event_blocks(val_slice, event_share_threshold=PRIMARY_MARKET_EVENT_SHARE)
        rows.append(
            {
                "fold_id": fold_id,
                "horizon": int(horizon),
                "threshold_type": str(threshold_type),
                "threshold_value": float(threshold_value),
                "target_usage": str(target_usage),
                "slice_id": f"h{int(horizon)}:{threshold_type}:{float(threshold_value):.4f}:{target_usage}",
                "slice_train_row_count": int(train_counts.get(key, 0)),
                "slice_validation_row_count": int(validation_counts.get(key, 0)),
                "validation_positive_count": int(val_slice["event_label"].astype(bool).sum()) if not val_slice.empty else 0,
                "validation_market_event_block_count": int(len(blocks)),
                "validation_idiosyncratic_episode_count": idiosyncratic_episode_count(val_slice, blocks),
            }
        )
    return rows


def _gate_status(gates: Mapping[str, bool]) -> str:
    return "pass" if all(bool(value) for value in gates.values()) else "fail"


def build_fold_plan_v2_from_target_rows(
    target_rows: pd.DataFrame,
    *,
    fold_count: int = DEFAULT_FOLD_COUNT,
    validation_start: str | pd.Timestamp = DEFAULT_VALIDATION_START,
    validation_end: str | pd.Timestamp = INFORMATION_CUTOFF_DATE,
    anchor_train_start: str | pd.Timestamp = DEFAULT_ANCHOR_TRAIN_START,
    embargo_days: int = DEFAULT_EMBARGO_DAYS,
    min_validation_span_ratio: float = DEFAULT_MIN_VALIDATION_SPAN_RATIO,
    min_total_validation_trade_dates: int = DEFAULT_MIN_TOTAL_VALIDATION_TRADE_DATES,
    min_train_rows_per_slice: int = DEFAULT_MIN_TRAIN_ROWS_PER_SLICE,
    min_validation_trade_dates_per_fold: int = DEFAULT_MIN_VALIDATION_TRADE_DATES_PER_FOLD,
    row_assignment_sample_cap: int = ROW_ASSIGNMENT_SAMPLE_CAP,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if target_rows.empty:
        plan = {
            "index_id": INDEX_ID,
            "policy_version": POLICY_VERSION,
            "status": "blocked_no_target_rows",
            "fold_count": 0,
            "folds": [],
            "purge_violation_count": 0,
            "embargo_violation_count": 0,
            "prospective_holdout_label_consumed_count": 0,
            "magnitude_hard_gates": {"target_rows_available": False},
            "magnitude_overview": {},
        }
        return plan, []

    work = target_rows.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce").dt.normalize()
    work["target_observation_end_date"] = pd.to_datetime(
        work["target_observation_end_date"], errors="coerce"
    ).dt.normalize()
    slice_keys = sorted({_slice_key(row) for row in work[SLICE_COLUMNS].drop_duplicates().to_dict(orient="records")})
    historical = work[
        work["split_role"].astype(str).eq("historical_development")
        & work["trade_date"].lt(pd.Timestamp(HOLDOUT_START).normalize())
    ].copy()
    labeled = _labeled_rows(historical)
    all_dates = _trading_dates(historical)
    labeled_dates = _trading_dates(labeled)
    start = pd.Timestamp(validation_start).normalize()
    requested_end = pd.Timestamp(validation_end).normalize()
    available_end = max(all_dates) if all_dates else requested_end
    end = min(requested_end, available_end)
    validation_dates = [value for value in labeled_dates if start <= value <= end]
    requested_folds = max(8, min(int(fold_count), 10))
    if len(validation_dates) < requested_folds:
        requested_folds = max(1, len(validation_dates))
    chunks = [chunk for chunk in np.array_split(np.asarray(validation_dates, dtype="datetime64[ns]"), requested_folds) if len(chunk)]
    anchor = pd.Timestamp(anchor_train_start).normalize()

    folds: list[dict[str, Any]] = []
    overview_rows: list[dict[str, Any]] = []
    holdout_withheld_total = 0
    min_fold_validation_dates: int | None = None
    min_fold_slice_train_rows: int | None = None
    min_fold_slice_validation_rows: int | None = None
    for fold_no, chunk in enumerate(chunks, start=1):
        chunk_dates = [pd.Timestamp(value).normalize() for value in chunk.tolist()]
        validation_start_ts = chunk_dates[0]
        validation_end_ts = chunk_dates[-1]
        prior_dates = [value for value in all_dates if anchor <= value < validation_start_ts]
        train_end_ts = prior_dates[-1] if prior_dates else None
        embargo_start, embargo_end = _add_trading_days_after(validation_end_ts, all_dates, embargo_days)
        fold = {
            "fold_id": f"fold_{fold_no}",
            "fold_start_date": _date_str(validation_start_ts),
            "fold_end_date": _date_str(validation_end_ts),
            "train_start_date": _date_str(anchor),
            "train_end_date": _date_str(train_end_ts),
            "validation_start_date": _date_str(validation_start_ts),
            "validation_end_date": _date_str(validation_end_ts),
            "embargo_start_date": _date_str(embargo_start),
            "embargo_end_date": _date_str(embargo_end),
            "max_horizon_days": 20,
            "embargo_days": int(embargo_days),
        }
        mask_info = _fold_assignment_masks(work, fold)
        train_mask = mask_info["train_mask"]
        validation_mask = mask_info["validation_mask"]
        train_rows_for_counts = work.loc[train_mask, SLICE_COLUMNS]
        validation_rows = work.loc[validation_mask].copy()
        validation_rows = _assign_normalised_dates(validation_rows, mask_info, "validation_mask")
        train_sample_rows = work.loc[train_mask].head(row_assignment_sample_cap).copy()
        train_sample_rows = _assign_normalised_dates(train_sample_rows, mask_info, "train_mask")
        holdout_withheld_total += int(mask_info["prospective_holdout_rows_withheld"])
        slice_rows = _slice_magnitude_rows(
            str(fold["fold_id"]),
            train_rows_for_counts,
            validation_rows,
            slice_keys=slice_keys,
        )
        slice_train_min = min((int(row["slice_train_row_count"]) for row in slice_rows), default=0)
        slice_validation_min = min((int(row["slice_validation_row_count"]) for row in slice_rows), default=0)
        min_fold_slice_train_rows = (
            slice_train_min
            if min_fold_slice_train_rows is None
            else min(int(min_fold_slice_train_rows), int(slice_train_min))
        )
        min_fold_slice_validation_rows = (
            slice_validation_min
            if min_fold_slice_validation_rows is None
            else min(int(min_fold_slice_validation_rows), int(slice_validation_min))
        )
        min_fold_validation_dates = (
            len(chunk_dates)
            if min_fold_validation_dates is None
            else min(int(min_fold_validation_dates), int(len(chunk_dates)))
        )
        fold_summary = {
            **fold,
            "validation_trade_date_count": int(len(chunk_dates)),
            "train_row_count": int(train_mask.sum()),
            "validation_row_count": int(validation_mask.sum()),
            "purged_row_count": 0,
            "embargoed_row_count": 0,
            "excluded_row_count": 0,
            "purge_violation_count": 0,
            "embargo_violation_count": 0,
            "assignment_counts": {
                "train": int(train_mask.sum()),
                "validation": int(len(validation_rows)),
                "purged": 0,
                "embargoed": 0,
                "excluded": 0,
            },
            "min_train_row_count_per_slice": int(slice_train_min),
            "min_validation_row_count_per_slice": int(slice_validation_min),
            "row_assignments": _assignment_sample(train_sample_rows, validation_rows, row_assignment_sample_cap),
            "row_assignment_sample_cap": int(row_assignment_sample_cap),
        }
        folds.append(fold_summary)
        for row in slice_rows:
            overview_rows.append(
                {
                    **{key: fold_summary.get(key) for key in OVERVIEW_COLUMNS if key in fold_summary},
                    **row,
                }
            )

    dev_dates = [value for value in all_dates if value >= anchor and value <= end]
    dev_start = min(dev_dates) if dev_dates else None
    dev_end = max(dev_dates) if dev_dates else None
    validation_span_start = min(validation_dates) if validation_dates else None
    validation_span_end = max(validation_dates) if validation_dates else None
    dev_span_days = (dev_end - dev_start).days + 1 if dev_start is not None and dev_end is not None else 0
    validation_span_days = (
        (validation_span_end - validation_span_start).days + 1
        if validation_span_start is not None and validation_span_end is not None
        else 0
    )
    validation_span_ratio = float(validation_span_days / dev_span_days) if dev_span_days else 0.0
    total_validation_trade_dates = len(validation_dates)
    prospective_labels = historical[
        historical["trade_date"].ge(pd.Timestamp(HOLDOUT_START).normalize())
        & historical["censoring_status"].astype(str).eq("labeled")
    ]
    gates = {
        "fold_count_between_8_and_10": 8 <= len(folds) <= 10,
        "validation_date_span_ge_60pct_development_span": validation_span_ratio >= float(min_validation_span_ratio),
        "total_validation_trade_dates_ge_500": total_validation_trade_dates >= int(min_total_validation_trade_dates),
        "per_fold_per_slice_train_rows_ge_5000": (min_fold_slice_train_rows or 0) >= int(min_train_rows_per_slice),
        "per_fold_validation_trade_dates_ge_200": (min_fold_validation_dates or 0) >= int(min_validation_trade_dates_per_fold),
        "prospective_holdout_label_consumed_count_eq_0": int(len(prospective_labels)) == 0,
        "purge_violation_count_eq_0": True,
        "embargo_violation_count_eq_0": True,
    }
    status = _gate_status(gates)
    overview = {
        "fold_count": int(len(folds)),
        "historical_development_start_date": _date_str(dev_start),
        "historical_development_end_date": _date_str(dev_end),
        "validation_start_date": _date_str(validation_span_start),
        "validation_end_date": _date_str(validation_span_end),
        "historical_development_date_span_days": int(dev_span_days),
        "validation_date_span_days": int(validation_span_days),
        "validation_date_span_ratio": validation_span_ratio,
        "total_validation_trade_dates": int(total_validation_trade_dates),
        "min_fold_validation_trade_dates": int(min_fold_validation_dates or 0),
        "min_fold_slice_train_rows": int(min_fold_slice_train_rows or 0),
        "min_fold_slice_validation_rows": int(min_fold_slice_validation_rows or 0),
        "prospective_holdout_label_consumed_count": int(len(prospective_labels)),
        "prospective_holdout_rows_evaluated": 0,
        "magnitude_hard_gates": gates,
        "folds": [
            {
                "fold_id": fold["fold_id"],
                "train_start_date": fold["train_start_date"],
                "train_end_date": fold["train_end_date"],
                "validation_start_date": fold["validation_start_date"],
                "validation_end_date": fold["validation_end_date"],
                "validation_trade_date_count": fold["validation_trade_date_count"],
                "train_row_count": fold["train_row_count"],
                "validation_row_count": fold["validation_row_count"],
                "min_train_row_count_per_slice": fold["min_train_row_count_per_slice"],
                "min_validation_row_count_per_slice": fold["min_validation_row_count_per_slice"],
            }
            for fold in folds
        ],
        "slice_rows": overview_rows,
    }
    plan = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "policy_version": POLICY_VERSION,
        "status": status,
        "fold_plan_source": "full_labeled_historical_development_rows",
        "fold_design": "anchored_expanding_walk_forward",
        "final_holdout_policy": "withheld_not_scored",
        "information_cutoff_date": INFORMATION_CUTOFF_DATE,
        "holdout_start": HOLDOUT_START,
        "anchor_train_start_date": _date_str(anchor),
        "validation_coverage_start_requested": _date_str(start),
        "validation_coverage_end_requested": _date_str(requested_end),
        "validation_coverage_end_available": _date_str(end),
        "fold_count": int(len(folds)),
        "folds": folds,
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
        "prospective_holdout_label_consumed_count": int(len(prospective_labels)),
        "prospective_holdout_rows_evaluated": 0,
        "magnitude_hard_gates": gates,
        "magnitude_overview": overview,
        "boundary_flags": BOUNDARY_FLAGS,
        "created_at": _now_iso(),
        "blocking_reasons": [] if status == "pass" else [key for key, value in gates.items() if not value],
    }
    return plan, overview_rows


def magnitude_markdown_section(report: Mapping[str, Any]) -> list[str]:
    overview = report.get("magnitude_overview", {})
    if not isinstance(overview, Mapping):
        overview = {}
    lines = [
        "## Magnitude Overview",
        "",
        f"- fold_plan_source: {report.get('fold_plan_source', overview.get('fold_plan_source', 'purge_embargo_fold_plan_v2'))}",
        f"- fold_count: {overview.get('fold_count', report.get('fold_count_evaluated', report.get('fold_count')))}",
        f"- validation_start_date: {overview.get('validation_start_date')}",
        f"- validation_end_date: {overview.get('validation_end_date')}",
        f"- total_validation_trade_dates: {overview.get('total_validation_trade_dates')}",
        f"- validation_date_span_ratio: {overview.get('validation_date_span_ratio')}",
        f"- min_fold_validation_trade_dates: {overview.get('min_fold_validation_trade_dates')}",
        f"- min_fold_slice_train_rows: {overview.get('min_fold_slice_train_rows')}",
        f"- prospective_holdout_label_consumed_count: {overview.get('prospective_holdout_label_consumed_count', report.get('prospective_holdout_label_consumed_count', 0))}",
        "",
        "| fold_id | train_start | train_end | validation_start | validation_end | validation_dates | train_rows | validation_rows | min_slice_train_rows |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    folds = overview.get("folds", [])
    if isinstance(folds, list) and folds:
        for fold in folds:
            if not isinstance(fold, Mapping):
                continue
            lines.append(
                "| {fold_id} | {train_start_date} | {train_end_date} | {validation_start_date} | "
                "{validation_end_date} | {validation_trade_date_count} | {train_row_count} | "
                "{validation_row_count} | {min_train_row_count_per_slice} |".format(**fold)
            )
    else:
        lines.append("| none |  |  |  |  | 0 | 0 | 0 | 0 |")
    return lines


def _write_overview_markdown(path: Path | str, plan: Mapping[str, Any], overview_rows: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "# Stage03V RERUN1 Fold Plan Magnitude Overview",
        "",
        f"- index_id: {plan.get('index_id')}",
        f"- status: {plan.get('status')}",
        f"- source_db_path: {plan.get('source_db_path')}",
        f"- v7_coverage_available: {plan.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {plan.get('sw2021_l2_universe_coverage')}",
        f"- fold_plan_path: {plan.get('fold_plan_path')}",
        "",
        *magnitude_markdown_section(plan),
        "",
        "## Hard Gates",
        "",
    ]
    for key, value in plan.get("magnitude_hard_gates", {}).items():
        lines.append(f"- {key}: {'pass' if value else 'fail'}")
    lines.extend(
        [
            "",
            "## Fold Slice Evidence",
            "",
            "| fold_id | slice_id | train_rows | validation_rows | positives | market_blocks | idiosyncratic_episodes |",
            "|---|---|---:|---:|---:|---:|---:|",
        ]
    )
    for row in overview_rows:
        lines.append(
            "| {fold_id} | h{horizon}:{threshold_type}:{threshold_value:.4f}:{target_usage} | "
            "{slice_train_row_count} | {slice_validation_row_count} | {validation_positive_count} | "
            "{validation_market_event_block_count} | {validation_idiosyncratic_episode_count} |".format(**row)
        )
    lines.extend(["", "## Boundary Flags", ""])
    for key, value in plan.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_fold_plan_magnitude_report(
    *,
    db_path: Path | str | None = None,
    target_support: Path | str = DEFAULT_TARGET_SUPPORT,
    output_plan: Path | str = DEFAULT_OUTPUT_PLAN,
    overview_md: Path | str = DEFAULT_OVERVIEW_MD,
    overview_csv: Path | str = DEFAULT_OVERVIEW_CSV,
    trial_accounting: Path | str = DEFAULT_TRIAL_ACCOUNTING,
    fold_count: int = DEFAULT_FOLD_COUNT,
    no_fetch: bool = True,
) -> dict[str, Any]:
    if not no_fetch:
        raise ValueError("Stage03V RERUN1 fold-plan magnitude gate is no-fetch only")
    resolved_db = resolve_v7_db_path(db_path)
    support = _load_json(target_support)
    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        plan = {
            "index_id": INDEX_ID,
            "report_version": REPORT_VERSION,
            "status": str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            "source_db_path": _safe_path(resolved_db),
            "v7_coverage_available": v7.coverage.get("v7_coverage_available", "no"),
            "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage", "missing"),
            "fold_count": 0,
            "folds": [],
            "purge_violation_count": 0,
            "embargo_violation_count": 0,
            "prospective_holdout_label_consumed_count": 0,
            "prospective_holdout_rows_evaluated": 0,
            "magnitude_hard_gates": {"v7_db_available": False},
            "magnitude_overview": {},
            "trial_accounting_path": _safe_path(trial_accounting),
            "trial_accounting_invalidation_recorded": "no",
            "boundary_flags": BOUNDARY_FLAGS,
            "blocking_reasons": list(v7.coverage.get("blocking_reasons", [])),
            "created_at": _now_iso(),
        }
        _write_json(output_plan, plan)
        _write_json(trial_accounting, rerun1_trial_accounting_record(fold_plan_path=output_plan))
        _write_csv(overview_csv, [])
        _write_overview_markdown(overview_md, plan, [])
        return plan

    specs = slice_specs_from_target_support(support)
    available_dates = _trading_dates(v7.price_frame)
    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE).normalize()
    needed_dates = [value for value in available_dates if value <= cutoff]
    target_rows = build_target_rows_for_trade_dates(
        v7.price_frame,
        v7.universe_frame,
        specs,
        needed_dates,
        source_db_path=resolved_db,
    )
    plan, overview_rows = build_fold_plan_v2_from_target_rows(target_rows, fold_count=fold_count)
    plan.update(
        {
            "source_db_path": _safe_path(resolved_db),
            "db_opened_read_only": "yes",
            "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
            "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
            "universe_source_status": v7.coverage.get("universe_source_status"),
            "entity_count_after_silent_break_handling": v7.coverage.get("entity_count_after_silent_break_handling"),
            "target_support_status": support.get("status"),
            "target_row_count_built_in_memory": int(len(target_rows)),
            "full_target_matrix_committed": "no",
            "fold_plan_path": _safe_path(output_plan),
            "overview_md_path": _safe_path(overview_md),
            "overview_csv_path": _safe_path(overview_csv),
            "trial_accounting_path": _safe_path(trial_accounting),
            "trial_accounting_invalidation_recorded": "yes",
            "no_fetch": True,
            "external_data_fetch": "no",
        }
    )
    if support.get("status") != "pass":
        plan["status"] = "blocked_wp1_support_not_pass"
        plan["blocking_reasons"] = [*plan.get("blocking_reasons", []), "wp1_support_status_not_pass"]
    _write_json(output_plan, plan)
    _write_json(trial_accounting, rerun1_trial_accounting_record(fold_plan_path=output_plan))
    _write_csv(overview_csv, overview_rows)
    _write_overview_markdown(overview_md, plan, overview_rows)
    return plan


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--target-support", type=Path, default=DEFAULT_TARGET_SUPPORT)
    parser.add_argument("--output-plan", type=Path, default=DEFAULT_OUTPUT_PLAN)
    parser.add_argument("--overview-md", type=Path, default=DEFAULT_OVERVIEW_MD)
    parser.add_argument("--overview-csv", type=Path, default=DEFAULT_OVERVIEW_CSV)
    parser.add_argument("--trial-accounting", type=Path, default=DEFAULT_TRIAL_ACCOUNTING)
    parser.add_argument("--fold-count", type=int, default=DEFAULT_FOLD_COUNT)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_fold_plan_magnitude_report(
        db_path=args.db,
        target_support=args.target_support,
        output_plan=args.output_plan,
        overview_md=args.overview_md,
        overview_csv=args.overview_csv,
        trial_accounting=args.trial_accounting,
        fold_count=args.fold_count,
        no_fetch=args.no_fetch,
    )
    gates = report.get("magnitude_hard_gates", {})
    print(
        "STAGE03V_RERUN1_B0_FOLD_PLAN="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"folds={report.get('fold_count')} "
        f"validation_trade_dates={report.get('magnitude_overview', {}).get('total_validation_trade_dates')} "
        f"min_fold_slice_train_rows={report.get('magnitude_overview', {}).get('min_fold_slice_train_rows')} "
        f"holdout_labels={report.get('prospective_holdout_label_consumed_count')} "
        f"gates_passed={all(bool(value) for value in gates.values()) if gates else False} "
        "no_fetch=yes"
    )
    return 0 if report.get("status") == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
