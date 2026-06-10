"""Stage03V WP0.5 sample feasibility preflight.

This module counts downside-event sample evidence before any Stage03V target
dataset or model package is opened. It is deliberately read-only and offline:
no fetchers, updaters, training code, calibration code, or holdout performance
artifacts are used here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


INDEX_ID = "STAGE03V-WP0.5-v1"
REPORT_VERSION = "stage03v_sample_feasibility_v1"
STAGE_ID = "stage03v"
TARGET_KIND = "sw2021_l2_downside_event"
BENCHMARK_TARGET_KIND = "broad_a_share_downside_event"
THRESHOLD_TYPE_FIXED = "fixed"
INFORMATION_CUTOFF_DATE = "2026-06-10"
HOLDOUT_START = "2026-06-11"
CORE_HORIZONS = [5, 10, 20]
DIAGNOSTIC_HORIZONS = [1, 3]
ALL_HORIZONS = [1, 3, 5, 10, 20]
FIXED_THRESHOLDS = [0.03, 0.05, 0.08, 0.10]
RECOMMENDED_FIRST_READINESS = {5: [0.03, 0.05], 10: [0.05, 0.08], 20: [0.08, 0.10]}
EVENT_SHARE_THRESHOLDS = [0.10, 0.20, 0.30]
PRIMARY_EVENT_SHARE_THRESHOLD = 0.20
IDIOSYNCRATIC_DISCOUNTS = [0.10, 0.25, 0.50]
DEFAULT_IDIOSYNCRATIC_DISCOUNT = 0.25
LONG_HORIZON_NOTE = (
    "The gap <= horizon merge rule intentionally makes long-horizon event blocks coarser. "
    "For 20d horizons, a chain of selloff days across a quarter may count as one block. "
    "This is a conservative effective-sample rule, not a data defect."
)

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
SIGNAL_CONTRACT = ROOT / "configs" / "risk_event_signal_contract_v1.yaml"
READINESS_POLICY = ROOT / "configs" / "readiness_policy_risk_event_v1.yaml"
UNIVERSE_MANIFEST = ROOT / "configs" / "stage03v_sw_l2_universe_manifest_v1.yaml"
LEDGER_TEMPLATE = ROOT / "reports" / "stage04" / "prospective_validation_ledger.stage03v.template.jsonl"
EXECUTION_INDEX = ROOT / "docs" / "work_packages" / "stage03v" / "STAGE03V_EXECUTION_INDEX.md"

SLICE_COLUMNS = ["horizon", "threshold", "threshold_type", "target_kind"]
BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_built": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
}


@dataclass(frozen=True)
class DBInputs:
    price_frame: pd.DataFrame
    benchmark_frame: pd.DataFrame
    coverage: dict[str, Any]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if math.isnan(float(value)) or math.isinf(float(value)):
            return None
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if value is pd.NA:
        return None
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _safe_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return candidate.name


def _resolve_v7_db_path(db_path: Path | str | None = None) -> Path:
    if db_path is not None:
        return Path(db_path)
    return Path(os.environ.get("STAGE03V_V7_DB", DEFAULT_V7_DB))


def _load_machine_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore[import-not-found]
        except ModuleNotFoundError as exc:  # pragma: no cover - JSON configs are expected here.
            raise ValueError(f"{_safe_path(path)} is not JSON and PyYAML is unavailable") from exc
        loaded = yaml.safe_load(text)
        return loaded if isinstance(loaded, dict) else {}


def _load_contracts() -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    loaded: dict[str, Any] = {}
    for key, path in {
        "signal_contract": SIGNAL_CONTRACT,
        "readiness_policy": READINESS_POLICY,
        "universe_manifest": UNIVERSE_MANIFEST,
        "ledger_template": LEDGER_TEMPLATE,
        "execution_index": EXECUTION_INDEX,
    }.items():
        if not path.exists():
            issues.append(f"missing_contract:{_safe_path(path)}")
            continue
        try:
            if path.suffix == ".jsonl":
                loaded[key] = json.loads(path.read_text(encoding="utf-8").strip())
            elif path.suffix == ".md":
                loaded[key] = {"text": path.read_text(encoding="utf-8")}
            else:
                loaded[key] = _load_machine_yaml(path)
        except Exception as exc:
            issues.append(f"unparseable_contract:{_safe_path(path)}:{exc}")

    signal = loaded.get("signal_contract", {})
    readiness = loaded.get("readiness_policy", {})
    manifest = loaded.get("universe_manifest", {})
    ledger = loaded.get("ledger_template", {})

    if signal.get("stage_id") != STAGE_ID:
        issues.append("signal_contract_stage_id_mismatch")
    if signal.get("stage03v1_entity_type") != "sw2021_l2_industry":
        issues.append("signal_contract_entity_type_mismatch")
    if signal.get("split_role_policy", {}).get("information_cutoff_date") != INFORMATION_CUTOFF_DATE:
        issues.append("signal_contract_cutoff_mismatch")
    if signal.get("split_role_policy", {}).get("holdout_start") != HOLDOUT_START:
        issues.append("signal_contract_holdout_start_mismatch")
    if signal.get("cross_cutoff_censoring", {}).get("cross_cutoff_censoring_policy") != "permanent":
        issues.append("cross_cutoff_censoring_policy_not_permanent")
    if readiness.get("metadata", {}).get("information_cutoff_date") != INFORMATION_CUTOFF_DATE:
        issues.append("readiness_policy_cutoff_mismatch")
    if ledger.get("information_cutoff_date") != INFORMATION_CUTOFF_DATE:
        issues.append("ledger_cutoff_mismatch")
    if ledger.get("holdout_start") != HOLDOUT_START:
        issues.append("ledger_holdout_start_mismatch")
    universe = manifest.get("universe", {})
    if universe.get("taxonomy_provider") != "SW":
        issues.append("universe_taxonomy_provider_mismatch")
    if universe.get("taxonomy_version") != "SW2021":
        issues.append("universe_taxonomy_version_mismatch")
    if universe.get("taxonomy_level") != "L2":
        issues.append("universe_taxonomy_level_mismatch")
    if universe.get("empirical_promotion_universe") != "sw2021_l2_industry_only":
        issues.append("universe_empirical_scope_mismatch")
    if "usable_probability" not in json.dumps(readiness, ensure_ascii=False):
        issues.append("readiness_policy_missing_statuses")

    return loaded, issues


def _normalise_price_frame(
    frame: pd.DataFrame,
    *,
    entity_col: str = "entity_id",
    date_col: str = "trade_date",
    close_col: str = "close",
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[entity_col, date_col, close_col])
    data = frame.copy()
    if entity_col not in data.columns:
        for candidate in ["sector_id", "benchmark_id", "entity", "industry_id"]:
            if candidate in data.columns:
                data = data.rename(columns={candidate: entity_col})
                break
    required = {entity_col, date_col, close_col}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"price frame missing required columns: {sorted(missing)}")
    data[entity_col] = data[entity_col].astype(str)
    data[date_col] = pd.to_datetime(data[date_col], errors="coerce").dt.normalize()
    data[close_col] = pd.to_numeric(data[close_col], errors="coerce")
    data = data[data[date_col].notna() & data[close_col].gt(0)].copy()
    return data.sort_values([entity_col, date_col]).drop_duplicates([entity_col, date_col], keep="last")


def compute_mae_events(
    frame: pd.DataFrame,
    horizons: Sequence[int],
    thresholds: Sequence[float],
    cutoff_date: str | date | pd.Timestamp,
    *,
    entity_col: str = "entity_id",
    date_col: str = "trade_date",
    close_col: str = "close",
    target_kind: str = TARGET_KIND,
    threshold_type: str = THRESHOLD_TYPE_FIXED,
) -> pd.DataFrame:
    """Compute future-path MAE downside labels with permanent cutoff censoring.

    For each entity and trade date, horizon ``N`` uses only t+1 through t+N.
    Rows whose target observation end is after ``cutoff_date`` are marked as
    ``cross_cutoff_censored`` and receive a null event label.
    """

    data = _normalise_price_frame(frame, entity_col=entity_col, date_col=date_col, close_col=close_col)
    cutoff = pd.Timestamp(cutoff_date).normalize()
    rows: list[dict[str, Any]] = []
    if data.empty:
        return pd.DataFrame(
            columns=[
                entity_col,
                "trade_date",
                "horizon",
                "threshold",
                "threshold_type",
                "target_kind",
                "target_observation_end_date",
                "mae",
                "event_label",
                "censoring_status",
            ]
        )

    for entity_id, group in data.groupby(entity_col, sort=False):
        group = group.sort_values(date_col).reset_index(drop=True)
        base_dates = group[date_col]
        base_closes = group[close_col]
        last_available_date = base_dates.max()
        for horizon in horizons:
            future_dates = [base_dates.shift(-step) for step in range(1, int(horizon) + 1)]
            future_closes = [base_closes.shift(-step) for step in range(1, int(horizon) + 1)]
            target_end = future_dates[-1]
            returns = []
            for shifted_date, shifted_close in zip(future_dates, future_closes):
                future_is_historical = shifted_date.le(cutoff)
                returns.append(((shifted_close / base_closes) - 1.0).where(future_is_historical))
            path_returns = pd.concat(returns, axis=1)
            complete_horizon = target_end.notna() & path_returns.notna().all(axis=1)
            labelable = base_dates.le(cutoff) & complete_horizon & target_end.le(cutoff)
            mae = path_returns.where(labelable, np.nan).min(axis=1, skipna=False)

            for idx in range(len(group)):
                trade_date = base_dates.iloc[idx]
                if pd.isna(trade_date) or trade_date > cutoff:
                    continue
                end_date = target_end.iloc[idx]
                if labelable.iloc[idx]:
                    censoring_status = "labeled"
                elif pd.notna(end_date) and pd.Timestamp(end_date).normalize() > cutoff:
                    censoring_status = "cross_cutoff_censored"
                elif pd.isna(end_date) and last_available_date >= cutoff:
                    censoring_status = "cross_cutoff_censored"
                else:
                    censoring_status = "insufficient_future_prices"

                for threshold in thresholds:
                    event_value: bool | None
                    mae_value: float | None
                    if labelable.iloc[idx]:
                        mae_value = float(mae.iloc[idx])
                        event_value = bool(mae_value <= -float(threshold))
                    else:
                        mae_value = None
                        event_value = None
                    rows.append(
                        {
                            entity_col: str(entity_id),
                            "trade_date": pd.Timestamp(trade_date).date(),
                            "horizon": int(horizon),
                            "threshold": float(threshold),
                            "threshold_type": threshold_type,
                            "target_kind": target_kind,
                            "target_observation_end_date": (
                                pd.Timestamp(end_date).date() if pd.notna(end_date) else None
                            ),
                            "mae": mae_value,
                            "event_label": event_value,
                            "censoring_status": censoring_status,
                        }
                    )
    return pd.DataFrame(rows)


def _slice_columns(frame: pd.DataFrame) -> list[str]:
    return [column for column in SLICE_COLUMNS if column in frame.columns]


def _discount_key(discount: float) -> str:
    return f"{discount:.2f}".replace(".", "_")


def _date_key(value: Any) -> pd.Timestamp:
    return pd.Timestamp(value).normalize()


def _merge_active_dates(
    active_dates: Iterable[Any],
    all_dates: Sequence[Any],
    *,
    horizon: int,
) -> list[dict[str, Any]]:
    active = sorted({_date_key(value) for value in active_dates if pd.notna(value)})
    if not active:
        return []
    ordered_dates = sorted({_date_key(value) for value in all_dates if pd.notna(value)})
    if not ordered_dates:
        ordered_dates = active
    position = {value: idx for idx, value in enumerate(ordered_dates)}

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
                    "block_start_date": start.date(),
                    "block_end_date": end.date(),
                    "active_date_count": active_count,
                }
            )
            start = current
            end = current
            active_count = 1
        previous = current
    blocks.append(
        {
            "block_start_date": start.date(),
            "block_end_date": end.date(),
            "active_date_count": active_count,
        }
    )
    return blocks


def compute_market_event_blocks(
    events: pd.DataFrame,
    event_share_thresholds: Sequence[float],
    horizon: int | None = None,
    *,
    benchmark_events: pd.DataFrame | None = None,
) -> dict[str, pd.DataFrame]:
    """Compute cross-sectional market event blocks and threshold sensitivity."""

    if events.empty:
        empty_counts = pd.DataFrame(columns=SLICE_COLUMNS + ["event_share_threshold", "market_event_block_count"])
        return {
            "event_share_by_date": pd.DataFrame(
                columns=SLICE_COLUMNS + ["trade_date", "event_count", "entity_count", "event_share"]
            ),
            "blocks": pd.DataFrame(
                columns=SLICE_COLUMNS
                + ["event_share_threshold", "block_id", "block_start_date", "block_end_date", "active_date_count"]
            ),
            "block_counts": empty_counts,
        }

    data = events.copy()
    if horizon is not None:
        data = data[data["horizon"].astype(int).eq(int(horizon))]
    data = data[data["event_label"].notna()].copy()
    if data.empty:
        empty_counts = pd.DataFrame(columns=SLICE_COLUMNS + ["event_share_threshold", "market_event_block_count"])
        return {
            "event_share_by_date": pd.DataFrame(
                columns=SLICE_COLUMNS + ["trade_date", "event_count", "entity_count", "event_share"]
            ),
            "blocks": pd.DataFrame(
                columns=SLICE_COLUMNS
                + ["event_share_threshold", "block_id", "block_start_date", "block_end_date", "active_date_count"]
            ),
            "block_counts": empty_counts,
        }

    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    data["event_label_bool"] = data["event_label"].astype(bool)
    group_cols = _slice_columns(data) + ["trade_date"]
    share = (
        data.groupby(group_cols, dropna=False)
        .agg(
            event_count=("event_label_bool", "sum"),
            entity_count=("entity_id", "nunique"),
        )
        .reset_index()
    )
    share["event_share"] = share["event_count"] / share["entity_count"].replace({0: np.nan})

    benchmark_by_slice: dict[tuple[Any, ...], set[pd.Timestamp]] = {}
    if benchmark_events is not None and not benchmark_events.empty:
        bench = benchmark_events.copy()
        if horizon is not None:
            bench = bench[bench["horizon"].astype(int).eq(int(horizon))]
        bench = bench[bench["event_label"].fillna(False).astype(bool)].copy()
        if not bench.empty:
            bench["trade_date"] = pd.to_datetime(bench["trade_date"], errors="coerce").dt.normalize()
            for key, group in bench.groupby(_slice_columns(bench), dropna=False):
                key_tuple = key if isinstance(key, tuple) else (key,)
                benchmark_by_slice[key_tuple] = set(group["trade_date"].dropna())

    block_rows: list[dict[str, Any]] = []
    count_rows: list[dict[str, Any]] = []
    slice_cols = _slice_columns(share)
    for key, group in share.groupby(slice_cols, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        base = dict(zip(slice_cols, key_tuple))
        all_dates = sorted(group["trade_date"].dropna().unique())
        slice_horizon = int(base.get("horizon", horizon if horizon is not None else 1))
        for share_threshold in event_share_thresholds:
            active_dates = set(group.loc[group["event_share"].ge(float(share_threshold)), "trade_date"].dropna())
            active_dates.update(benchmark_by_slice.get(key_tuple, set()))
            blocks = _merge_active_dates(active_dates, all_dates, horizon=slice_horizon)
            count_rows.append(
                {
                    **base,
                    "event_share_threshold": float(share_threshold),
                    "market_event_block_count": len(blocks),
                }
            )
            for block_id, block in enumerate(blocks, start=1):
                block_rows.append(
                    {
                        **base,
                        "event_share_threshold": float(share_threshold),
                        "block_id": block_id,
                        **block,
                    }
                )

    return {
        "event_share_by_date": share,
        "blocks": pd.DataFrame(block_rows),
        "block_counts": pd.DataFrame(count_rows),
    }


def _interval_overlaps(left_start: Any, left_end: Any, right_start: Any, right_end: Any) -> bool:
    return _date_key(left_start) <= _date_key(right_end) and _date_key(left_end) >= _date_key(right_start)


def compute_idiosyncratic_episodes(
    events: pd.DataFrame,
    market_blocks: pd.DataFrame | Mapping[str, pd.DataFrame],
    horizon: int | None = None,
    *,
    primary_event_share_threshold: float = PRIMARY_EVENT_SHARE_THRESHOLD,
) -> pd.DataFrame:
    """Count industry event episodes outside primary market event blocks."""

    if isinstance(market_blocks, Mapping):
        blocks = market_blocks.get("blocks", pd.DataFrame()).copy()
    else:
        blocks = market_blocks.copy()
    if not blocks.empty and "event_share_threshold" in blocks.columns:
        blocks = blocks[blocks["event_share_threshold"].astype(float).eq(float(primary_event_share_threshold))]

    if events.empty:
        return pd.DataFrame(columns=SLICE_COLUMNS + ["idiosyncratic_industry_episode_count"])
    data = events.copy()
    if horizon is not None:
        data = data[data["horizon"].astype(int).eq(int(horizon))]
    data = data[data["event_label"].notna()].copy()
    if data.empty:
        return pd.DataFrame(columns=SLICE_COLUMNS + ["idiosyncratic_industry_episode_count"])
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    data["event_label_bool"] = data["event_label"].astype(bool)

    detail_rows: list[dict[str, Any]] = []
    summary_rows: list[dict[str, Any]] = []
    slice_cols = _slice_columns(data)
    for key, slice_frame in data.groupby(slice_cols, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        base = dict(zip(slice_cols, key_tuple))
        slice_horizon = int(base.get("horizon", horizon if horizon is not None else 1))
        slice_blocks = blocks
        for col, value in base.items():
            if col in slice_blocks.columns:
                slice_blocks = slice_blocks[slice_blocks[col].eq(value)]

        count = 0
        for entity_id, entity_frame in slice_frame.groupby("entity_id", dropna=False):
            entity_dates = sorted(entity_frame["trade_date"].dropna().unique())
            active_dates = entity_frame.loc[entity_frame["event_label_bool"], "trade_date"].dropna().unique()
            episodes = _merge_active_dates(active_dates, entity_dates, horizon=slice_horizon)
            for episode_id, episode in enumerate(episodes, start=1):
                overlaps_market = False
                if not slice_blocks.empty:
                    overlaps_market = any(
                        _interval_overlaps(
                            episode["block_start_date"],
                            episode["block_end_date"],
                            block.block_start_date,
                            block.block_end_date,
                        )
                        for block in slice_blocks.itertuples(index=False)
                    )
                if not overlaps_market:
                    count += 1
                detail_rows.append(
                    {
                        **base,
                        "entity_id": str(entity_id),
                        "episode_id": episode_id,
                        "episode_start_date": episode["block_start_date"],
                        "episode_end_date": episode["block_end_date"],
                        "overlaps_primary_market_block": bool(overlaps_market),
                        "counted_as_idiosyncratic": not overlaps_market,
                    }
                )
        summary_rows.append({**base, "idiosyncratic_industry_episode_count": count})

    summary = pd.DataFrame(summary_rows)
    summary.attrs["episode_details"] = pd.DataFrame(detail_rows)
    return summary


def compute_effective_event_evidence(
    market_blocks: pd.DataFrame | Mapping[str, pd.DataFrame],
    idiosyncratic_episodes: pd.DataFrame,
    discounts: Sequence[float],
    *,
    primary_event_share_threshold: float = PRIMARY_EVENT_SHARE_THRESHOLD,
) -> pd.DataFrame:
    """Combine primary market blocks with discounted idiosyncratic episodes."""

    if isinstance(market_blocks, Mapping):
        block_counts = market_blocks.get("block_counts", pd.DataFrame()).copy()
    else:
        block_counts = market_blocks.copy()
    if block_counts.empty:
        base = idiosyncratic_episodes[_slice_columns(idiosyncratic_episodes)].drop_duplicates().copy()
        base["primary_market_event_block_count"] = 0
    else:
        primary = block_counts[block_counts["event_share_threshold"].astype(float).eq(float(primary_event_share_threshold))]
        base = primary[_slice_columns(primary) + ["market_event_block_count"]].rename(
            columns={"market_event_block_count": "primary_market_event_block_count"}
        )
    if base.empty:
        base = pd.DataFrame(columns=SLICE_COLUMNS + ["primary_market_event_block_count"])

    if idiosyncratic_episodes.empty:
        result = base.copy()
        result["idiosyncratic_industry_episode_count"] = 0
    else:
        result = base.merge(idiosyncratic_episodes, on=_slice_columns(base), how="outer")
        result["primary_market_event_block_count"] = result["primary_market_event_block_count"].fillna(0).astype(int)
        result["idiosyncratic_industry_episode_count"] = (
            result["idiosyncratic_industry_episode_count"].fillna(0).astype(int)
        )

    for discount in discounts:
        key = _discount_key(float(discount))
        discounted_col = f"discounted_idiosyncratic_episode_count_{key}"
        effective_col = f"effective_event_evidence_count_{key}"
        result[discounted_col] = result["idiosyncratic_industry_episode_count"] * float(discount)
        result[effective_col] = result["primary_market_event_block_count"] + result[discounted_col]
    return result


def assign_feasibility_verdict(row: Mapping[str, Any]) -> str:
    """Assign a WP0.5 feasibility verdict without any readiness promotion."""

    data_status = str(row.get("data_status", "pass"))
    labeled_count = int(row.get("historical_development_labeled_count", row.get("labeled_count", 0)) or 0)
    positive_count = int(row.get("positive_event_count", 0) or 0)
    horizon = int(row.get("horizon", 0) or 0)
    threshold_type = str(row.get("threshold_type", THRESHOLD_TYPE_FIXED))
    primary_blocks = float(row.get("primary_market_event_block_count", 0) or 0)
    effective = float(row.get("effective_event_evidence_count_0_25", 0) or 0)

    if data_status in {
        "blocked_missing_v7_db",
        "partial_missing_db",
        "partial_missing_universe",
        "partial_missing_data",
    }:
        return "partial_missing_data"
    if threshold_type != THRESHOLD_TYPE_FIXED:
        return "defer_threshold"
    if labeled_count <= 0:
        return "blocked_short_history"
    if effective < 5:
        return "drop_threshold" if positive_count > 0 else "blocked_short_history"
    if effective < 10:
        return "diagnostic_only"
    if horizon in DIAGNOSTIC_HORIZONS:
        return "diagnostic_only"
    if primary_blocks < 2:
        return "diagnostic_only"
    return "eligible"


def _table_exists(con: Any, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT count(*) AS n
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _table_columns(con: Any, table_name: str) -> set[str]:
    if not _table_exists(con, table_name):
        return set()
    return {
        str(row[0])
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table_name],
        ).fetchall()
    }


def _table_summary(con: Any, table_name: str) -> dict[str, Any]:
    if not _table_exists(con, table_name):
        return {"exists": False, "row_count": 0, "min_trade_date": None, "max_trade_date": None}
    row_count = int(con.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])
    columns = _table_columns(con, table_name)
    if "trade_date" not in columns or row_count == 0:
        return {"exists": True, "row_count": row_count, "min_trade_date": None, "max_trade_date": None}
    row = con.execute(f"SELECT min(trade_date), max(trade_date) FROM {table_name}").fetchone()
    return {
        "exists": True,
        "row_count": row_count,
        "min_trade_date": _json_safe(row[0]) if row else None,
        "max_trade_date": _json_safe(row[1]) if row else None,
    }


def _workspace_metadata(con: Any) -> dict[str, str]:
    if not _table_exists(con, "database_workspace_metadata"):
        return {}
    try:
        rows = con.execute("SELECT key, value FROM database_workspace_metadata").fetchall()
    except Exception:
        return {}
    return {str(key): str(value) for key, value in rows if key is not None}


def _yyyymmdd_to_timestamp(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(str(value), format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _read_db_inputs(db_path: Path | str | None) -> DBInputs:
    safe_db_path = _safe_path(db_path)
    coverage: dict[str, Any] = {
        "db_path": safe_db_path,
        "v7_db_required": True,
        "db_available": False,
        "db_opened_read_only": False,
        "v7_coverage_available": "unknown",
        "v7_db_requirement_status": "unknown",
        "sw2021_l2_universe_coverage": "missing",
        "benchmark_target_status": "unavailable",
        "source_tables": {},
        "workspace_metadata": {},
        "taxonomy_provider": "SW",
        "taxonomy_version": "SW2021",
        "taxonomy_level": "L2",
        "industry_count_total": 0,
        "industry_count_after_quality_filter": 0,
        "min_trade_date": None,
        "max_trade_date": None,
        "coverage_start": None,
        "coverage_end": None,
        "history_continuity_status": "missing",
        "reform_window_continuity_status": "missing",
        "silent_entity_break_count": 0,
        "duplicate_entity_count": 0,
        "short_history_entity_count": 0,
        "quality_filter_exclusion_count": 0,
        "constituent_count_filter_status": "not_applicable_missing_constituents",
        "constituent_snapshot_available": False,
        "universe_source_status": "missing",
        "blocking_reasons": [],
    }
    if db_path is None or not Path(db_path).exists():
        coverage["status"] = "blocked_missing_v7_db"
        coverage["v7_db_requirement_status"] = "blocked_missing_v7_db"
        coverage["blocking_reasons"].append("STAGE03V_V7_DB/--db path is missing")
        return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

    try:
        import duckdb  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        coverage["status"] = "partial_missing_duckdb"
        coverage["db_available"] = True
        return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        coverage["status"] = "partial_db_open_failed"
        coverage["db_open_error"] = str(exc)
        return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

    try:
        coverage["db_available"] = True
        coverage["db_opened_read_only"] = True
        metadata = _workspace_metadata(con)
        coverage["workspace_metadata"] = {
            key: metadata.get(key)
            for key in [
                "label",
                "db_profile",
                "active_source",
                "market_data_source",
                "snapshot_start_date",
                "snapshot_end_date",
                "snapshot_effective_end_date",
                "snapshot_skipped_trade_dates",
                "build_status",
                "validation_status",
            ]
            if key in metadata
        }
        for table in ["sector_meta", "sector_ohlcv", "sector_constituents", "market_benchmark_ohlcv"]:
            coverage["source_tables"][table] = _table_summary(con, table)

        if not _table_exists(con, "sector_meta") or not _table_exists(con, "sector_ohlcv"):
            coverage["status"] = "partial_missing_universe"
            return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

        sector_columns = _table_columns(con, "sector_meta")
        sector_select = ["sector_id", "sector_type", "sector_name", "source"]
        if "sector_level" in sector_columns:
            sector_select.append("sector_level")
        sector_meta = con.execute(
            f"""
            SELECT {", ".join(sector_select)}
            FROM sector_meta
            WHERE sector_type = 'industry'
            """
        ).fetchdf()
        if sector_meta.empty:
            coverage["status"] = "partial_missing_universe"
            return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

        coverage["industry_count_total"] = int(sector_meta["sector_id"].nunique())
        coverage["duplicate_entity_count"] = int(sector_meta.duplicated("sector_id").sum())
        sources = sorted(sector_meta.get("source", pd.Series(dtype="object")).dropna().astype(str).unique().tolist())
        coverage["universe_sources"] = sources
        if "sector_level" in sector_meta.columns:
            sector_meta["sector_level"] = sector_meta["sector_level"].fillna("").astype(str)
        else:
            sector_meta["sector_level"] = ""
        sector_meta["source"] = sector_meta["source"].fillna("").astype(str)
        verified_l2_mask = sector_meta["source"].str.lower().eq("tushare_sw_classify") & sector_meta[
            "sector_level"
        ].str.upper().eq("L2")
        verified_l2_meta = sector_meta[verified_l2_mask].copy()
        coverage["sw2021_l2_verified_entity_count"] = int(verified_l2_meta["sector_id"].nunique())
        coverage["non_verified_or_non_l2_industry_count"] = int(
            coverage["industry_count_total"] - coverage["sw2021_l2_verified_entity_count"]
        )
        verified_sw_source = not verified_l2_meta.empty
        coverage["universe_source_status"] = (
            "verified_sw2021_l2_tushare_classify" if verified_sw_source else "unverified_local_industry"
        )

        candidate_meta = verified_l2_meta if verified_sw_source else sector_meta
        sector_ids = candidate_meta["sector_id"].dropna().astype(str).drop_duplicates().tolist()
        placeholders = ",".join(["?"] * len(sector_ids))
        ohlcv = con.execute(
            f"""
            SELECT sector_id, trade_date, close
            FROM sector_ohlcv
            WHERE sector_id IN ({placeholders})
              AND close IS NOT NULL
            ORDER BY sector_id, trade_date
            """,
            sector_ids,
        ).fetchdf()
        if ohlcv.empty:
            coverage["status"] = "partial_missing_universe"
            return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)

        ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"], errors="coerce").dt.normalize()
        entity_summary = (
            ohlcv.groupby("sector_id")
            .agg(min_trade_date=("trade_date", "min"), max_trade_date=("trade_date", "max"), row_count=("trade_date", "count"))
            .reset_index()
        )
        coverage_start = entity_summary["min_trade_date"].min()
        coverage_end = entity_summary["max_trade_date"].max()
        coverage["min_trade_date"] = _json_safe(coverage_start)
        coverage["max_trade_date"] = _json_safe(coverage_end)
        coverage["coverage_start"] = _json_safe(coverage_start)
        coverage["coverage_end"] = _json_safe(coverage_end)
        coverage["short_history_entity_count"] = int(
            (entity_summary["min_trade_date"] > pd.Timestamp("2021-07-01")).sum()
        )
        cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE)
        snapshot_start = _yyyymmdd_to_timestamp(metadata.get("snapshot_start_date"))
        label = metadata.get("label", "")
        profile = metadata.get("db_profile", "")
        source = metadata.get("market_data_source", metadata.get("active_source", ""))
        long_history_available = bool(pd.notna(coverage_start) and coverage_start <= pd.Timestamp("2014-01-03"))
        metadata_confirms_v7 = bool(
            "v7" in label.lower()
            and profile == "clean_tushare_snapshot"
            and source == "tushare"
            and metadata.get("build_status") == "pass"
            and metadata.get("validation_status") == "pass"
            and snapshot_start is not None
            and snapshot_start <= pd.Timestamp("2014-01-01")
        )
        v7_available = long_history_available and metadata_confirms_v7
        coverage["v7_coverage_available"] = "yes" if v7_available else "no"
        coverage["v7_db_requirement_status"] = "pass" if v7_available else "blocked_missing_v7_db"
        if not v7_available:
            coverage["status"] = "blocked_missing_v7_db"
            coverage["blocking_reasons"].append(
                "DB does not satisfy Stage03V V7 long-history requirement: expected clean Tushare V7 snapshot with 2014 coverage"
            )
            return DBInputs(pd.DataFrame(), pd.DataFrame(), coverage)
        coverage["reform_window_continuity_status"] = (
            "pass"
            if pd.notna(coverage_start) and pd.notna(coverage_end) and coverage_start <= pd.Timestamp("2021-07-01") <= coverage_end
            else "partial"
        )
        snapshot_effective_end = _yyyymmdd_to_timestamp(metadata.get("snapshot_effective_end_date"))
        if pd.notna(coverage_end) and coverage_end >= cutoff:
            coverage["history_continuity_status"] = "pass"
        elif snapshot_effective_end is not None and pd.notna(coverage_end) and coverage_end >= snapshot_effective_end:
            coverage["history_continuity_status"] = "pass_to_snapshot_effective_end"
        else:
            coverage["history_continuity_status"] = "partial_short_to_cutoff"

        gap_counts = []
        for _, group in ohlcv.sort_values(["sector_id", "trade_date"]).groupby("sector_id"):
            gaps = group["trade_date"].diff().dt.days.dropna()
            gap_counts.append(bool((gaps > 45).any()))
        coverage["silent_entity_break_count"] = int(sum(gap_counts))

        quality_exclusions: set[str] = set()
        if _table_exists(con, "sector_constituents"):
            constituents = con.execute(
                f"""
                SELECT sector_id, count(DISTINCT stock_code) AS constituent_count
                FROM sector_constituents
                WHERE sector_id IN ({placeholders})
                GROUP BY sector_id
                """,
                sector_ids,
            ).fetchdf()
            if not constituents.empty:
                coverage["constituent_snapshot_available"] = True
                low_constituents = constituents[constituents["constituent_count"].astype(int) < 5]
                quality_exclusions.update(low_constituents["sector_id"].astype(str).tolist())
                coverage["constituent_count_min_observed"] = int(constituents["constituent_count"].min())
                coverage["constituent_count_filter_status"] = "pass" if low_constituents.empty else "partial_low_constituents"

        short_history_ids = entity_summary.loc[
            entity_summary["min_trade_date"] > pd.Timestamp("2021-07-01"), "sector_id"
        ].astype(str)
        quality_exclusions.update(short_history_ids.tolist())
        non_verified_ids = set(sector_meta["sector_id"].dropna().astype(str)) - set(
            verified_l2_meta["sector_id"].dropna().astype(str)
        )
        if verified_sw_source:
            quality_exclusions.update(non_verified_ids)
        coverage["quality_filter_exclusion_count"] = int(len(quality_exclusions))
        qualified_ids = [sector_id for sector_id in sector_ids if sector_id not in quality_exclusions]
        coverage["industry_count_after_quality_filter"] = int(len(qualified_ids))

        if v7_available and verified_sw_source and qualified_ids:
            coverage["sw2021_l2_universe_coverage"] = "pass"
            coverage["status"] = "pass"
            usable_ids = qualified_ids
        elif qualified_ids:
            coverage["sw2021_l2_universe_coverage"] = "partial"
            coverage["status"] = "partial_missing_universe"
            usable_ids = qualified_ids
        else:
            coverage["sw2021_l2_universe_coverage"] = "missing"
            coverage["status"] = "partial_missing_universe"
            usable_ids = sector_ids

        price_frame = ohlcv[ohlcv["sector_id"].astype(str).isin(usable_ids)].rename(columns={"sector_id": "entity_id"})

        benchmark_frame = pd.DataFrame()
        if _table_exists(con, "market_benchmark_ohlcv"):
            benchmark = con.execute(
                """
                SELECT benchmark_id, trade_date, close
                FROM market_benchmark_ohlcv
                WHERE benchmark_id IN ('csi_all', 'hs300')
                  AND close IS NOT NULL
                ORDER BY benchmark_id, trade_date
                """
            ).fetchdf()
            if not benchmark.empty:
                preferred = "csi_all" if (benchmark["benchmark_id"].astype(str) == "csi_all").any() else "hs300"
                benchmark_frame = benchmark[benchmark["benchmark_id"].astype(str).eq(preferred)].rename(
                    columns={"benchmark_id": "entity_id"}
                )
                coverage["benchmark_target_status"] = "available"
                coverage["benchmark_id"] = preferred
            else:
                coverage["benchmark_target_status"] = "unavailable"
        return DBInputs(price_frame, benchmark_frame, coverage)
    finally:
        con.close()


def _empty_feasibility_matrix(data_status: str, benchmark_target_status: str) -> pd.DataFrame:
    rows = []
    for horizon in ALL_HORIZONS:
        for threshold in FIXED_THRESHOLDS:
            row = {
                "horizon": horizon,
                "threshold": threshold,
                "threshold_type": THRESHOLD_TYPE_FIXED,
                "target_kind": TARGET_KIND,
                "data_status": data_status,
                "cross_cutoff_censored_count": 0,
                "cross_cutoff_excluded_count": 0,
                "historical_development_labeled_count": 0,
                "historical_development_unlabeled_due_to_cutoff_count": 0,
                "positive_event_count": 0,
                "event_base_rate": None,
                "market_event_block_count_10pct": 0,
                "market_event_block_count_20pct": 0,
                "market_event_block_count_30pct": 0,
                "primary_market_event_block_count": 0,
                "benchmark_event_count": 0,
                "benchmark_target_status": benchmark_target_status,
                "idiosyncratic_industry_episode_count": 0,
                "discounted_idiosyncratic_episode_count_0_10": 0.0,
                "discounted_idiosyncratic_episode_count_0_25": 0.0,
                "discounted_idiosyncratic_episode_count_0_50": 0.0,
                "effective_event_evidence_count_0_10": 0.0,
                "effective_event_evidence_count_0_25": 0.0,
                "effective_event_evidence_count_0_50": 0.0,
            }
            row["feasibility_verdict"] = assign_feasibility_verdict(row)
            rows.append(row)
    return pd.DataFrame(rows)


def _event_slice_counts(events: pd.DataFrame) -> pd.DataFrame:
    if events.empty:
        return pd.DataFrame()
    data = events.copy()
    data["event_label_bool"] = data["event_label"].fillna(False).astype(bool)
    data["is_labeled"] = data["event_label"].notna()
    grouped = (
        data.groupby(SLICE_COLUMNS, dropna=False)
        .agg(
            cross_cutoff_censored_count=("censoring_status", lambda s: int((s == "cross_cutoff_censored").sum())),
            historical_development_labeled_count=("is_labeled", "sum"),
            historical_development_unlabeled_due_to_cutoff_count=(
                "censoring_status",
                lambda s: int((s == "cross_cutoff_censored").sum()),
            ),
            insufficient_future_price_count=("censoring_status", lambda s: int((s == "insufficient_future_prices").sum())),
            positive_event_count=("event_label_bool", "sum"),
            entity_count=("entity_id", "nunique"),
            trade_date_count=("trade_date", "nunique"),
        )
        .reset_index()
    )
    grouped["cross_cutoff_excluded_count"] = 0
    grouped["event_base_rate"] = grouped["positive_event_count"] / grouped[
        "historical_development_labeled_count"
    ].replace({0: np.nan})
    return grouped


def _market_counts_wide(block_counts: pd.DataFrame) -> pd.DataFrame:
    if block_counts.empty:
        return pd.DataFrame()
    rows = []
    for key, group in block_counts.groupby(SLICE_COLUMNS, dropna=False):
        key_tuple = key if isinstance(key, tuple) else (key,)
        row = dict(zip(SLICE_COLUMNS, key_tuple))
        for share_threshold in EVENT_SHARE_THRESHOLDS:
            label = int(round(share_threshold * 100))
            matched = group[group["event_share_threshold"].astype(float).eq(float(share_threshold))]
            row[f"market_event_block_count_{label}pct"] = (
                int(matched["market_event_block_count"].iloc[0]) if not matched.empty else 0
            )
        row["primary_market_event_block_count"] = row.get("market_event_block_count_20pct", 0)
        rows.append(row)
    return pd.DataFrame(rows)


def _benchmark_event_counts(benchmark_events: pd.DataFrame) -> pd.DataFrame:
    if benchmark_events.empty:
        return pd.DataFrame(columns=SLICE_COLUMNS + ["benchmark_event_count"])
    data = benchmark_events.copy()
    data["target_kind"] = TARGET_KIND
    data["event_label_bool"] = data["event_label"].fillna(False).astype(bool)
    return (
        data.groupby(SLICE_COLUMNS, dropna=False)
        .agg(benchmark_event_count=("event_label_bool", "sum"))
        .reset_index()
    )


def _build_matrix_from_events(
    events: pd.DataFrame,
    benchmark_events_for_report: pd.DataFrame,
    benchmark_events_for_blocks: pd.DataFrame,
    *,
    data_status: str,
    benchmark_target_status: str,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    if events.empty:
        return _empty_feasibility_matrix(data_status, benchmark_target_status), {
            "events": events,
            "market": pd.DataFrame(),
            "idiosyncratic": pd.DataFrame(),
            "effective": pd.DataFrame(),
        }

    market = compute_market_event_blocks(
        events,
        EVENT_SHARE_THRESHOLDS,
        benchmark_events=benchmark_events_for_blocks,
    )
    idiosyncratic = compute_idiosyncratic_episodes(events, market)
    effective = compute_effective_event_evidence(market, idiosyncratic, IDIOSYNCRATIC_DISCOUNTS)
    slice_counts = _event_slice_counts(events)
    market_wide = _market_counts_wide(market["block_counts"])
    benchmark_counts = _benchmark_event_counts(benchmark_events_for_report)
    effective_columns = [
        column
        for column in effective.columns
        if column in SLICE_COLUMNS
        or column.startswith("discounted_idiosyncratic_episode_count_")
        or column.startswith("effective_event_evidence_count_")
    ]

    matrix = slice_counts
    for extra in [market_wide, idiosyncratic, effective[effective_columns], benchmark_counts]:
        if not extra.empty:
            matrix = matrix.merge(extra, on=SLICE_COLUMNS, how="left")
    fill_zero_columns = [
        "cross_cutoff_censored_count",
        "cross_cutoff_excluded_count",
        "historical_development_labeled_count",
        "historical_development_unlabeled_due_to_cutoff_count",
        "positive_event_count",
        "market_event_block_count_10pct",
        "market_event_block_count_20pct",
        "market_event_block_count_30pct",
        "primary_market_event_block_count",
        "benchmark_event_count",
        "idiosyncratic_industry_episode_count",
        "discounted_idiosyncratic_episode_count_0_10",
        "discounted_idiosyncratic_episode_count_0_25",
        "discounted_idiosyncratic_episode_count_0_50",
        "effective_event_evidence_count_0_10",
        "effective_event_evidence_count_0_25",
        "effective_event_evidence_count_0_50",
    ]
    for column in fill_zero_columns:
        if column not in matrix.columns:
            matrix[column] = 0
        matrix[column] = matrix[column].fillna(0)
    if "event_base_rate" not in matrix.columns:
        matrix["event_base_rate"] = np.nan
    matrix["benchmark_target_status"] = benchmark_target_status
    matrix["data_status"] = data_status
    if data_status == "pass":
        matrix["feasibility_verdict"] = [assign_feasibility_verdict(row) for row in matrix.to_dict(orient="records")]
    else:
        matrix["feasibility_verdict"] = "partial_missing_data"
    matrix = matrix.sort_values(["horizon", "threshold", "threshold_type", "target_kind"]).reset_index(drop=True)
    return matrix, {
        "events": events,
        "market": market["block_counts"],
        "market_blocks": market["blocks"],
        "event_share_by_date": market["event_share_by_date"],
        "idiosyncratic": idiosyncratic,
        "effective": effective,
    }


def _aggregate_censoring_counts(events: pd.DataFrame) -> dict[str, int]:
    if events.empty:
        return {
            "cross_cutoff_censored_count": 0,
            "cross_cutoff_excluded_count": 0,
            "historical_development_labeled_count": 0,
            "historical_development_unlabeled_due_to_cutoff_count": 0,
        }
    unique = events.drop_duplicates(["entity_id", "trade_date", "horizon"])
    return {
        "cross_cutoff_censored_count": int((unique["censoring_status"] == "cross_cutoff_censored").sum()),
        "cross_cutoff_excluded_count": 0,
        "historical_development_labeled_count": int(unique["event_label"].notna().sum()),
        "historical_development_unlabeled_due_to_cutoff_count": int(
            (unique["censoring_status"] == "cross_cutoff_censored").sum()
        ),
    }


def _status_from_coverage(data_status: str, contract_issues: Sequence[str]) -> str:
    if contract_issues:
        return "blocked_contract_missing"
    if data_status == "pass":
        return "pass"
    return data_status


def build_sample_feasibility_report(
    *,
    db_path: Path | str | None = None,
    output: Path | str | None = None,
    summary_json: Path | str | None = None,
    no_fetch: bool = True,
    price_frame: pd.DataFrame | None = None,
    benchmark_frame: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """Build and optionally write the Stage03V WP0.5 feasibility report."""

    contracts, contract_issues = _load_contracts()
    effective_db_path = _resolve_v7_db_path(db_path) if price_frame is None else db_path
    if price_frame is None:
        db_inputs = _read_db_inputs(effective_db_path)
        price_frame = db_inputs.price_frame
        benchmark_frame = db_inputs.benchmark_frame
        coverage = db_inputs.coverage
    else:
        coverage = {
            "db_path": _safe_path(effective_db_path),
            "db_available": False,
            "db_opened_read_only": False,
            "v7_coverage_available": "unknown",
            "sw2021_l2_universe_coverage": "pass",
            "benchmark_target_status": "available" if benchmark_frame is not None and not benchmark_frame.empty else "unavailable",
            "source_tables": {},
            "taxonomy_provider": "SW",
            "taxonomy_version": "SW2021",
            "taxonomy_level": "L2",
            "industry_count_total": int(price_frame.get("entity_id", pd.Series(dtype="object")).nunique()),
            "industry_count_after_quality_filter": int(price_frame.get("entity_id", pd.Series(dtype="object")).nunique()),
            "status": "pass",
            "history_continuity_status": "synthetic",
            "reform_window_continuity_status": "synthetic",
            "silent_entity_break_count": 0,
            "duplicate_entity_count": 0,
            "short_history_entity_count": 0,
            "quality_filter_exclusion_count": 0,
            "constituent_count_filter_status": "not_applicable_synthetic",
        }

    data_status = str(coverage.get("status", "partial_missing_data"))
    if contract_issues:
        matrix = _empty_feasibility_matrix("partial_missing_data", "unavailable")
        artifacts: dict[str, pd.DataFrame] = {}
        events = pd.DataFrame()
    elif price_frame is None or price_frame.empty:
        matrix = _empty_feasibility_matrix(data_status, str(coverage.get("benchmark_target_status", "unavailable")))
        artifacts = {}
        events = pd.DataFrame()
    else:
        events = compute_mae_events(
            price_frame,
            ALL_HORIZONS,
            FIXED_THRESHOLDS,
            INFORMATION_CUTOFF_DATE,
            target_kind=TARGET_KIND,
        )
        benchmark_events_for_report = pd.DataFrame()
        benchmark_events_for_blocks = pd.DataFrame()
        if benchmark_frame is not None and not benchmark_frame.empty:
            benchmark_events_for_report = compute_mae_events(
                benchmark_frame,
                ALL_HORIZONS,
                FIXED_THRESHOLDS,
                INFORMATION_CUTOFF_DATE,
                target_kind=BENCHMARK_TARGET_KIND,
            )
            benchmark_events_for_blocks = benchmark_events_for_report.copy()
            if not benchmark_events_for_blocks.empty:
                benchmark_events_for_blocks["target_kind"] = TARGET_KIND
        matrix, artifacts = _build_matrix_from_events(
            events,
            benchmark_events_for_report,
            benchmark_events_for_blocks,
            data_status=data_status,
            benchmark_target_status=str(coverage.get("benchmark_target_status", "unavailable")),
        )

    censoring_counts = _aggregate_censoring_counts(events)
    verdict_counts = (
        matrix["feasibility_verdict"].value_counts().sort_index().to_dict()
        if not matrix.empty and "feasibility_verdict" in matrix.columns
        else {}
    )
    eligible = matrix[matrix["feasibility_verdict"].eq("eligible")] if not matrix.empty else pd.DataFrame()
    diagnostic = matrix[matrix["feasibility_verdict"].eq("diagnostic_only")] if not matrix.empty else pd.DataFrame()
    deferred_dropped = (
        matrix[matrix["feasibility_verdict"].isin(["defer_threshold", "drop_threshold", "blocked_short_history", "partial_missing_data"])]
        if not matrix.empty
        else pd.DataFrame()
    )

    status = _status_from_coverage(data_status, contract_issues)
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": status,
        "contract_status": "pass" if not contract_issues else "blocked_contract_missing",
        "contract_issues": list(contract_issues),
        "contract_paths_used": {
            "signal_contract": _safe_path(SIGNAL_CONTRACT),
            "readiness_policy": _safe_path(READINESS_POLICY),
            "universe_manifest": _safe_path(UNIVERSE_MANIFEST),
            "ledger_template": _safe_path(LEDGER_TEMPLATE),
            "execution_index": _safe_path(EXECUTION_INDEX),
        },
        "db_path": _safe_path(effective_db_path),
        "db_used": bool(coverage.get("db_available") and not (price_frame is None or price_frame.empty)),
        "db_availability": "available" if coverage.get("db_available") else "missing",
        "db_opened_read_only": "yes" if coverage.get("db_opened_read_only") else "no",
        "no_fetch": bool(no_fetch),
        "external_data_fetch": "no",
        "source_coverage": coverage,
        "sw2021_l2_universe_coverage": coverage.get("sw2021_l2_universe_coverage", "missing"),
        "benchmark_target_status": coverage.get("benchmark_target_status", "unavailable"),
        "candidate_horizon_threshold_grid": {
            "core_horizons": CORE_HORIZONS,
            "diagnostic_horizons": DIAGNOSTIC_HORIZONS,
            "fixed_thresholds": FIXED_THRESHOLDS,
            "recommended_first_readiness": RECOMMENDED_FIRST_READINESS,
        },
        "vol_scaled_feasibility_status": "deferred_to_wp3_5",
        "vol_scaled_defer_reasons": [
            "WP0.5 does not yet have a reviewed causal ex-ante volatility estimator for this target.",
            "Fixed-threshold feasibility must not be blocked on the volatility-scaled supplement.",
        ],
        **censoring_counts,
        "market_event_block_sensitivity_reported": True,
        "idiosyncratic_episodes_reported": True,
        "effective_evidence_counts_reported": True,
        "long_horizon_block_merge_note": LONG_HORIZON_NOTE,
        "feasibility_verdict_counts": {str(k): int(v) for k, v in verdict_counts.items()},
        "eligible_slice_count": int(len(eligible)),
        "diagnostic_only_slice_count": int(len(diagnostic)),
        "deferred_dropped_slice_count": int(len(deferred_dropped)),
        "no_usable_probability_assigned": True,
        "fixed_threshold_feasibility_matrix": matrix.to_dict(orient="records"),
        "recommended_eligible_slices": eligible[SLICE_COLUMNS].to_dict(orient="records") if not eligible.empty else [],
        "recommended_diagnostic_only_slices": diagnostic[SLICE_COLUMNS].to_dict(orient="records")
        if not diagnostic.empty
        else [],
        "recommended_deferred_or_dropped_slices": deferred_dropped[
            SLICE_COLUMNS + ["feasibility_verdict"]
        ].to_dict(orient="records")
        if not deferred_dropped.empty
        else [],
        "boundary_flags": dict(BOUNDARY_FLAGS),
    }

    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(render_markdown_report(report), encoding="utf-8")
    if summary_json is not None:
        summary_path = Path(summary_json)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def _format_number(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        if math.isnan(value):
            return "n/a"
        return f"{value:.4f}"
    return str(value)


def render_markdown_report(report: Mapping[str, Any]) -> str:
    matrix = report.get("fixed_threshold_feasibility_matrix", [])
    matrix_rows = matrix if isinstance(matrix, list) else []
    display_columns = [
        "horizon",
        "threshold",
        "historical_development_labeled_count",
        "positive_event_count",
        "market_event_block_count_10pct",
        "market_event_block_count_20pct",
        "market_event_block_count_30pct",
        "idiosyncratic_industry_episode_count",
        "effective_event_evidence_count_0_25",
        "benchmark_event_count",
        "feasibility_verdict",
    ]

    lines = [
        "# Stage03V WP0.5 Sample Feasibility Preflight",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- DB path: {report.get('db_path')}",
        f"- DB availability: {report.get('db_availability')}",
        f"- DB opened read-only: {report.get('db_opened_read_only')}",
        f"- external data fetch: {report.get('external_data_fetch')}",
        f"- V7 coverage available: {dict(report.get('source_coverage', {})).get('v7_coverage_available')}",
        f"- SW2021 L2 universe coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- universe source status: {dict(report.get('source_coverage', {})).get('universe_source_status')}",
        f"- benchmark target status: {report.get('benchmark_target_status')}",
        f"- vol_scaled_feasibility_status: {report.get('vol_scaled_feasibility_status')}",
        "",
        "## Contract Paths",
        "",
    ]
    for key, value in dict(report.get("contract_paths_used", {})).items():
        lines.append(f"- {key}: {value}")

    coverage = dict(report.get("source_coverage", {}))
    lines.extend(
        [
            "",
            "## Source Coverage",
            "",
            f"- v7_db_required: {coverage.get('v7_db_required')}",
            f"- v7_db_requirement_status: {coverage.get('v7_db_requirement_status')}",
            f"- v7_coverage_available: {coverage.get('v7_coverage_available')}",
            f"- taxonomy_provider: {coverage.get('taxonomy_provider')}",
            f"- taxonomy_version: {coverage.get('taxonomy_version')}",
            f"- taxonomy_level: {coverage.get('taxonomy_level')}",
            f"- universe_source_status: {coverage.get('universe_source_status')}",
            f"- universe_sources: {coverage.get('universe_sources')}",
            f"- sw2021_l2_verified_entity_count: {coverage.get('sw2021_l2_verified_entity_count')}",
            f"- non_verified_or_non_l2_industry_count: {coverage.get('non_verified_or_non_l2_industry_count')}",
            f"- industry_count_total: {coverage.get('industry_count_total')}",
            f"- industry_count_after_quality_filter: {coverage.get('industry_count_after_quality_filter')}",
            f"- min_trade_date: {coverage.get('min_trade_date')}",
            f"- max_trade_date: {coverage.get('max_trade_date')}",
            f"- coverage_start: {coverage.get('coverage_start')}",
            f"- coverage_end: {coverage.get('coverage_end')}",
            f"- history_continuity_status: {coverage.get('history_continuity_status')}",
            f"- reform_window_continuity_status: {coverage.get('reform_window_continuity_status')}",
            f"- silent_entity_break_count: {coverage.get('silent_entity_break_count')}",
            f"- duplicate_entity_count: {coverage.get('duplicate_entity_count')}",
            f"- short_history_entity_count: {coverage.get('short_history_entity_count')}",
            f"- quality_filter_exclusion_count: {coverage.get('quality_filter_exclusion_count')}",
            f"- constituent_count_filter_status: {coverage.get('constituent_count_filter_status')}",
            f"- workspace_metadata: {coverage.get('workspace_metadata')}",
            "",
            "## Cross-Cutoff Censoring",
            "",
            f"- cross_cutoff_censored_count: {report.get('cross_cutoff_censored_count')}",
            f"- cross_cutoff_excluded_count: {report.get('cross_cutoff_excluded_count')}",
            f"- historical_development_labeled_count: {report.get('historical_development_labeled_count')}",
            "- historical_development_unlabeled_due_to_cutoff_count: "
            f"{report.get('historical_development_unlabeled_due_to_cutoff_count')}",
            "",
            "## Feasibility Matrix",
            "",
            "| " + " | ".join(display_columns) + " |",
            "| " + " | ".join(["---"] * len(display_columns)) + " |",
        ]
    )
    for row in matrix_rows:
        lines.append("| " + " | ".join(_format_number(row.get(column)) for column in display_columns) + " |")

    lines.extend(
        [
            "",
            "## Verdict Counts",
            "",
        ]
    )
    for verdict, count in dict(report.get("feasibility_verdict_counts", {})).items():
        lines.append(f"- {verdict}: {count}")

    lines.extend(
        [
            "",
            "## Long-Horizon Interpretation",
            "",
            str(report.get("long_horizon_block_merge_note")),
            "",
            "## Boundary Flags",
            "",
        ]
    )
    for key, value in dict(report.get("boundary_flags", {})).items():
        lines.append(f"- {key}: {value}")
    lines.append("")
    return "\n".join(lines)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default=os.environ.get("STAGE03V_V7_DB", "data/db/a_share_hmm_tushare_v7.duckdb"),
        help="Stage03V V7 DuckDB path. May also be set with STAGE03V_V7_DB. Read-only if present.",
    )
    parser.add_argument("--output", default="reports/stage03v/sample_feasibility_report.md")
    parser.add_argument("--summary-json", default="reports/stage03v/sample_feasibility_report.json")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        default=True,
        help="Offline mode. This is the default and only supported WP0.5 behavior.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    report = build_sample_feasibility_report(
        db_path=args.db,
        output=args.output,
        summary_json=args.summary_json,
        no_fetch=True,
    )
    status = str(report.get("status", "fail"))
    print(
        "STAGE03V_SAMPLE_FEASIBILITY="
        f"{status} db_path={_safe_path(args.db)} report={_safe_path(args.output)} "
        f"summary_json={_safe_path(args.summary_json)} no_fetch=yes"
    )
    return 1 if status == "blocked_contract_missing" else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
