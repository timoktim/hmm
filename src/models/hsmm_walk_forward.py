from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage, json_dumps
from src.data_pipeline.universe import (
    compute_calendar_hash,
    compute_custom_basket_membership_hash,
    compute_sector_ohlcv_snapshot_hash,
    compute_universe_membership_hash,
    load_sector_like_ohlcv,
)
from src.features.hsmm_features import HSMM_FEATURE_COLUMNS, build_hsmm_features
from src.features.sector_features import feature_scope_for_universe
from src.models.hsmm_core import last_hsmm_engine_diagnostic, resolve_hsmm_engine
from src.models.hsmm_model import DiscreteDurationGaussianHSMM


ProgressCallback = Callable[[int, int, pd.Timestamp, str], None]


@dataclass(frozen=True)
class HSMMWalkForwardConfig:
    db_path: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    universe_id: str | None = None
    include_custom_baskets: bool = True
    feature_scope_id: str | None = None
    feature_version: str = settings.default_feature_version
    feature_preset: str = "hsmm_v1"
    n_states: int = 4
    max_duration: int = 60
    train_window_days: int | None = 504
    train_frequency: str = "monthly"
    train_every_n_trade_days: int | None = None
    snapshot_frequency: str = "daily"
    rebalance_days: int = 5
    min_sequence_length: int = 30
    min_train_sequences: int = 3
    n_iter: int = 20
    tol: float = 1e-4
    duration_smoothing: float = 1.0
    transition_smoothing: float = 1.0
    variance_floor: float = 1e-4
    random_state: int = 42
    run_id: str | None = None
    notes: str = ""
    append: bool = False
    profile_only: bool = False
    snapshot_decode_mode: str = "prefix"
    hsmm_engine: str = "auto"
    n_jobs: int | str = 1
    sector_chunk_size: int = 32
    fit_n_jobs: int | str | None = None
    fit_sequence_chunk_size: int = 32
    log_every_n_snapshots: int = 10
    persist_incremental: bool = False
    resume: bool = False
    checkpoint_write_mode: str = "end"
    overwrite: bool = False


HSMM_RUN_PERFORMANCE_STORAGE_COLUMNS = [
    "run_id",
    "checkpoint_id",
    "train_date",
    "train_start_date",
    "train_end_date",
    "training_sequence_count",
    "training_row_count",
    "fit_seconds",
    "decode_snapshot_count",
    "decode_sector_count",
    "decode_rows_generated",
    "decode_seconds",
    "created_at",
]


def params_hash(payload: dict[str, object]) -> str:
    params_json = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(params_json.encode("utf-8")).hexdigest()


def _fit_n_jobs_for_config(config: HSMMWalkForwardConfig) -> int | str:
    return config.n_jobs if config.fit_n_jobs is None else config.fit_n_jobs


def _hsmm_performance_storage_frame(rows: list[dict[str, object]] | pd.DataFrame) -> pd.DataFrame:
    df = rows if isinstance(rows, pd.DataFrame) else pd.DataFrame(rows)
    if df.empty:
        return df
    cols = [column for column in HSMM_RUN_PERFORMANCE_STORAGE_COLUMNS if column in df.columns]
    return df[cols].copy()


def _hsmm_engine_profile_diagnostic(engine: str) -> dict[str, object]:
    try:
        resolved = resolve_hsmm_engine(engine)
        diagnostic = last_hsmm_engine_diagnostic()
        return {
            "engine_used": resolved,
            "engine_fallback_reason": diagnostic.get("fallback_reason"),
            "numba_available": diagnostic.get("numba_available"),
            "numba_compile_warmed": diagnostic.get("compile_warmed"),
        }
    except RuntimeError as exc:
        return {
            "engine_used": "unavailable",
            "engine_fallback_reason": str(exc),
            "numba_available": False,
            "numba_compile_warmed": False,
        }


def _config_hash_payload(
    config: HSMMWalkForwardConfig,
    feature_scope_id: str,
    feature_scope_type: str,
    lineage_digests: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = asdict(config)
    for key in ["run_id", "notes", "db_path", "overwrite"]:
        payload.pop(key, None)
    payload["feature_scope_id"] = feature_scope_id
    payload["feature_scope_type"] = feature_scope_type
    payload["feature_columns"] = HSMM_FEATURE_COLUMNS
    if lineage_digests:
        payload.update(lineage_digests)
    return payload


def _hsmm_lineage_digests(
    storage: DuckDBStorage,
    config: HSMMWalkForwardConfig,
    ohlcv: pd.DataFrame,
    trade_dates: list[pd.Timestamp] | pd.Series,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
) -> dict[str, object]:
    sector_ids = sorted(ohlcv["sector_id"].dropna().astype(str).unique().tolist()) if "sector_id" in ohlcv.columns else []
    custom_ids = [sector_id for sector_id in sector_ids if sector_id.startswith("custom:")]
    return {
        "universe_membership_hash": compute_universe_membership_hash(storage, config.universe_id, as_of_date=end_date),
        "custom_basket_membership_hash": (
            compute_custom_basket_membership_hash(storage, custom_ids, as_of_date=end_date) if config.include_custom_baskets else None
        ),
        "custom_basket_membership_policy": "current_snapshot" if config.include_custom_baskets else None,
        "data_snapshot_hash": compute_sector_ohlcv_snapshot_hash(storage, sector_ids, start_date, end_date),
        "calendar_hash": compute_calendar_hash(trade_dates),
    }


def _resolve_run_id(config: HSMMWalkForwardConfig) -> str:
    if config.run_id:
        return config.run_id
    stamp = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
    scope = config.universe_id or "all"
    return f"hsmm_v1_{scope}_{stamp}"


def clear_hsmm_run(storage: DuckDBStorage, run_id: str) -> dict[str, object]:
    """Remove every persisted artifact for a HSMM run before rerunning it."""
    return storage.clear_hsmm_run_cascade(run_id)


def _hsmm_run_metadata_frame(
    *,
    run_id: str,
    config: HSMMWalkForwardConfig,
    feature_scope_id: str,
    feature_scope_type: str,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    config_payload: dict[str, object],
    config_hash: str,
    run_hash: str,
    lineage_digests: dict[str, object],
    run_status: str,
    started_at: pd.Timestamp,
    expected_snapshot_count: int,
    expected_state_row_count: int,
    actual_snapshot_count: int = 0,
    actual_state_row_count: int = 0,
    completed_at: pd.Timestamp | None = None,
    failed_at: pd.Timestamp | None = None,
    failure_message: str | None = None,
) -> pd.DataFrame:
    lineage_payload = {
        "run_id": run_id,
        "config_hash": config_hash,
        "run_hash": run_hash,
        "feature_scope_id": feature_scope_id,
        "feature_scope_type": feature_scope_type,
        **lineage_digests,
    }
    return pd.DataFrame(
        [
            {
                "run_id": run_id,
                "model_family": "hsmm",
                "model_version": "hsmm_v1",
                "created_at": pd.Timestamp.now(),
                "universe_id": config.universe_id,
                "include_custom_baskets": bool(config.include_custom_baskets),
                "feature_scope_id": feature_scope_id,
                "feature_version": config.feature_version,
                "start_date": start_date.date(),
                "end_date": end_date.date(),
                "train_window_days": config.train_window_days,
                "rebalance_days": config.rebalance_days,
                "train_frequency": config.train_frequency,
                "train_every_n_trade_days": config.train_every_n_trade_days,
                "snapshot_frequency": config.snapshot_frequency,
                "n_states": config.n_states,
                "max_duration": config.max_duration,
                "duration_smoothing": config.duration_smoothing,
                "emission_type": "diag_gaussian",
                "feature_columns_json": json_dumps(HSMM_FEATURE_COLUMNS),
                "config_json": json.dumps(config_payload, ensure_ascii=False, sort_keys=True, default=str),
                "config_hash": config_hash,
                "run_hash": run_hash,
                "universe_membership_hash": lineage_digests.get("universe_membership_hash"),
                "custom_basket_membership_hash": lineage_digests.get("custom_basket_membership_hash"),
                "data_snapshot_hash": lineage_digests.get("data_snapshot_hash"),
                "calendar_hash": lineage_digests.get("calendar_hash"),
                "clean_run": not config.append,
                "lineage_json": json.dumps(lineage_payload, ensure_ascii=False, sort_keys=True, default=str),
                "lineage_hash": run_hash,
                "run_status": run_status,
                "started_at": started_at,
                "completed_at": completed_at,
                "failed_at": failed_at,
                "failure_message": failure_message,
                "expected_snapshot_count": int(expected_snapshot_count),
                "actual_snapshot_count": int(actual_snapshot_count),
                "expected_state_row_count": int(expected_state_row_count),
                "actual_state_row_count": int(actual_state_row_count),
                "params_json": json.dumps(config_payload, ensure_ascii=False, sort_keys=True, default=str),
                "params_hash": config_hash,
                "code_version": "hsmm_mvp_v1",
                "notes": config.notes,
            }
        ]
    )


def _write_hsmm_run_metadata(storage: DuckDBStorage, metadata: pd.DataFrame) -> None:
    storage.upsert_df("hsmm_model_runs", metadata, ["run_id"])


def _resolve_dates(config: HSMMWalkForwardConfig, ohlcv: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp]:
    dates = pd.to_datetime(ohlcv["trade_date"])
    start = pd.to_datetime(config.start_date) if config.start_date else dates.min()
    if config.end_date and str(config.end_date).lower() != "today":
        end = pd.to_datetime(config.end_date)
    else:
        end = dates.max()
    return pd.Timestamp(start), pd.Timestamp(end)


def _training_sequences(features: pd.DataFrame, signal_date: pd.Timestamp, config: HSMMWalkForwardConfig) -> list[pd.DataFrame]:
    history = features[features["trade_date"] <= signal_date].copy()
    if config.train_window_days:
        train_dates = pd.Series(history["trade_date"].drop_duplicates().sort_values()).tail(config.train_window_days)
        history = history[history["trade_date"].isin(set(train_dates))]
    sequences: list[pd.DataFrame] = []
    for _, group in history.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
        if len(group.dropna(subset=HSMM_FEATURE_COLUMNS)) >= config.min_sequence_length:
            sequences.append(group.copy())
    return sequences


def _select_checkpoint_dates(all_trade_dates: pd.Series, snapshot_dates: list[pd.Timestamp], config: HSMMWalkForwardConfig) -> list[pd.Timestamp]:
    if not snapshot_dates:
        return []
    dates = pd.Series(pd.to_datetime(all_trade_dates).drop_duplicates().sort_values()).reset_index(drop=True)
    first_snapshot = pd.Timestamp(snapshot_dates[0])
    end_snapshot = pd.Timestamp(snapshot_dates[-1])
    eligible = dates[dates <= end_snapshot]
    if eligible.empty:
        return []
    checkpoints: list[pd.Timestamp] = []
    if config.train_frequency == "monthly":
        month_ends = eligible.groupby(eligible.dt.to_period("M")).max().sort_values().tolist()
        prior = eligible[eligible <= first_snapshot]
        checkpoints.append(pd.Timestamp(prior.iloc[-1] if not prior.empty else first_snapshot))
        checkpoints.extend(pd.Timestamp(x) for x in month_ends if pd.Timestamp(x) > checkpoints[0])
    elif config.train_frequency == "every_n_trade_days":
        step = int(config.train_every_n_trade_days or config.rebalance_days or 20)
        if step <= 0:
            raise ValueError("train_every_n_trade_days must be positive")
        start_idx = int(eligible.searchsorted(first_snapshot, side="right") - 1)
        start_idx = max(0, start_idx)
        checkpoints = [pd.Timestamp(x) for x in eligible.iloc[start_idx::step].tolist()]
    else:
        raise ValueError("train_frequency must be monthly or every_n_trade_days")
    deduped = pd.Series(pd.to_datetime(checkpoints)).drop_duplicates().sort_values()
    return [pd.Timestamp(x) for x in deduped.tolist()]


def _checkpoint_id(run_id: str, train_date: pd.Timestamp, ordinal: int) -> str:
    return f"{run_id}:ckpt:{ordinal:04d}:{pd.Timestamp(train_date).strftime('%Y%m%d')}"


def _latest_checkpoint_for(snapshot_date: pd.Timestamp, checkpoint_dates: list[pd.Timestamp]) -> pd.Timestamp | None:
    eligible = [date for date in checkpoint_dates if date <= snapshot_date]
    return eligible[-1] if eligible else None


def _snapshot_dates_by_checkpoint(
    snapshot_dates: list[pd.Timestamp],
    checkpoint_dates: list[pd.Timestamp],
) -> dict[pd.Timestamp, list[pd.Timestamp]]:
    grouped: dict[pd.Timestamp, list[pd.Timestamp]] = {}
    sorted_checkpoints = sorted(pd.Timestamp(date) for date in checkpoint_dates)
    for snapshot_date in snapshot_dates:
        checkpoint_date = _latest_checkpoint_for(pd.Timestamp(snapshot_date), sorted_checkpoints)
        if checkpoint_date is not None:
            grouped.setdefault(pd.Timestamp(checkpoint_date), []).append(pd.Timestamp(snapshot_date))
    return grouped


def _inference_sequences(features: pd.DataFrame, sector_ids: set[str], train_start: pd.Timestamp, snapshot_date: pd.Timestamp) -> list[pd.DataFrame]:
    frame = features[
        (features["trade_date"] >= train_start)
        & (features["trade_date"] <= snapshot_date)
        & (features["sector_id"].astype(str).isin(sector_ids))
    ].copy()
    sequences: list[pd.DataFrame] = []
    for _, group in frame.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
        clean = group.dropna(subset=HSMM_FEATURE_COLUMNS)
        if not clean.empty and pd.Timestamp(clean["trade_date"].max()) == pd.Timestamp(snapshot_date):
            sequences.append(group.copy())
    return sequences


def build_hsmm_performance_profile(
    *,
    run_id: str,
    config: HSMMWalkForwardConfig,
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    checkpoint_dates: list[pd.Timestamp],
    snapshot_dates: list[pd.Timestamp],
    feature_scope_id: str,
    feature_scope_type: str,
) -> dict[str, object]:
    clean = features.dropna(subset=HSMM_FEATURE_COLUMNS).copy()
    sector_count_feature_eligible = int(
        clean.groupby("sector_id").size().loc[lambda s: s >= config.min_sequence_length].shape[0]
    ) if not clean.empty else 0
    checkpoint_groups = _snapshot_dates_by_checkpoint(snapshot_dates, checkpoint_dates)
    clean_by_sector: dict[str, np.ndarray] = {}
    if not clean.empty:
        for sector_id, group in clean.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
            clean_by_sector[str(sector_id)] = pd.to_datetime(group["trade_date"]).to_numpy(dtype="datetime64[ns]")

    legacy_snapshot_decode_calls = 0
    legacy_prefix_day_units = 0
    optimized_checkpoint_sector_decodes = 0
    optimized_prefix_day_units = 0
    checkpoint_profiles: list[dict[str, object]] = []
    for train_date in checkpoint_dates:
        train_sequences = _training_sequences(features, pd.Timestamp(train_date), config)
        sector_ids = {str(seq["sector_id"].iloc[0]) for seq in train_sequences}
        if train_sequences:
            train_start = min(pd.to_datetime(seq["trade_date"]).min() for seq in train_sequences)
            train_row_count = int(sum(len(seq.dropna(subset=HSMM_FEATURE_COLUMNS)) for seq in train_sequences))
        else:
            train_start = pd.NaT
            train_row_count = 0
        served_dates = checkpoint_groups.get(pd.Timestamp(train_date), [])
        max_snapshot = max(served_dates) if served_dates else None
        optimized_decodes = 0
        optimized_units = 0
        if max_snapshot is not None and sector_ids:
            train_start64 = np.datetime64(pd.Timestamp(train_start).to_datetime64())
            max_snapshot64 = np.datetime64(pd.Timestamp(max_snapshot).to_datetime64())
            served64 = np.asarray([np.datetime64(pd.Timestamp(date).to_datetime64()) for date in served_dates], dtype="datetime64[ns]")
            for sector_id in sector_ids:
                dates = clean_by_sector.get(str(sector_id))
                if dates is None or len(dates) == 0:
                    continue
                start_idx = int(np.searchsorted(dates, train_start64, side="left"))
                max_idx = int(np.searchsorted(dates, max_snapshot64, side="right"))
                if max_idx <= start_idx:
                    continue
                sector_dates = dates[start_idx:max_idx]
                if bool(np.isin(served64, sector_dates).any()):
                    optimized_decodes += 1
                    optimized_units += len(sector_dates)
                for snapshot64 in served64:
                    end_idx = int(np.searchsorted(dates, snapshot64, side="right"))
                    if end_idx <= start_idx:
                        continue
                    if end_idx > 0 and dates[end_idx - 1] == snapshot64:
                        legacy_snapshot_decode_calls += 1
                        legacy_prefix_day_units += end_idx - start_idx
            optimized_checkpoint_sector_decodes += optimized_decodes
            optimized_prefix_day_units += optimized_units
        checkpoint_profiles.append(
            {
                "train_date": pd.Timestamp(train_date).date().isoformat(),
                "snapshot_count": len(served_dates),
                "training_sequence_count": len(train_sequences),
                "training_row_count": train_row_count,
                "optimized_sector_decodes": optimized_decodes,
                "optimized_prefix_day_units": optimized_units,
            }
        )

    optimized_prefix_day_units = max(optimized_prefix_day_units, 1)
    rough_ratio = float(legacy_prefix_day_units / optimized_prefix_day_units)
    engine_diagnostic = _hsmm_engine_profile_diagnostic(config.hsmm_engine)
    return {
        "run_id": run_id,
        "start_date": start_date.date().isoformat(),
        "end_date": end_date.date().isoformat(),
        "feature_scope_id": feature_scope_id,
        "feature_scope_type": feature_scope_type,
        "trade_day_count": int(pd.Series(features["trade_date"]).nunique()),
        "snapshot_count": len(snapshot_dates),
        "checkpoint_count": len(checkpoint_dates),
        "sector_count_raw": int(ohlcv["sector_id"].astype(str).nunique()),
        "sector_count_feature_eligible": sector_count_feature_eligible,
        "n_states": config.n_states,
        "max_duration": config.max_duration,
        "n_iter": config.n_iter,
        "train_window_days": config.train_window_days,
        "snapshot_decode_mode": config.snapshot_decode_mode,
        "hsmm_engine": config.hsmm_engine,
        **engine_diagnostic,
        "n_jobs": config.n_jobs,
        "fit_n_jobs": _fit_n_jobs_for_config(config),
        "fit_sequence_chunk_size": config.fit_sequence_chunk_size,
        "decode_n_jobs": config.n_jobs,
        "sector_chunk_size": config.sector_chunk_size,
        "legacy_snapshot_decode_calls": legacy_snapshot_decode_calls,
        "legacy_prefix_day_units": legacy_prefix_day_units,
        "optimized_checkpoint_sector_decodes": optimized_checkpoint_sector_decodes,
        "optimized_prefix_day_units": optimized_prefix_day_units,
        "estimated_training_sequence_decodes": int(
            sum(len(_training_sequences(features, pd.Timestamp(date), config)) * max(config.n_iter, 0) for date in checkpoint_dates)
        ),
        "estimated_viterbi_core_units": int(optimized_prefix_day_units * config.n_states * config.n_states * config.max_duration),
        "rough_complexity_ratio_legacy_vs_prefix": rough_ratio,
        "checkpoint_profiles": checkpoint_profiles,
    }


def write_hsmm_performance_profile(profile: dict[str, object], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "performance_estimate.json").write_text(json.dumps(profile, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    lines = [
        "# HSMM Performance Estimate",
        "",
        f"- run_id: {profile.get('run_id')}",
        f"- date range: {profile.get('start_date')} to {profile.get('end_date')}",
        f"- snapshot count: {profile.get('snapshot_count')}",
        f"- checkpoint count: {profile.get('checkpoint_count')}",
        f"- raw sector count: {profile.get('sector_count_raw')}",
        f"- feature eligible sector count: {profile.get('sector_count_feature_eligible')}",
        f"- legacy snapshot decode calls: {profile.get('legacy_snapshot_decode_calls')}",
        f"- legacy prefix day units: {profile.get('legacy_prefix_day_units')}",
        f"- optimized checkpoint-sector decodes: {profile.get('optimized_checkpoint_sector_decodes')}",
        f"- optimized prefix day units: {profile.get('optimized_prefix_day_units')}",
        f"- rough complexity ratio legacy/prefix: {profile.get('rough_complexity_ratio_legacy_vs_prefix'):.2f}",
        f"- fit n_jobs: {profile.get('fit_n_jobs')}",
        f"- fit sequence chunk size: {profile.get('fit_sequence_chunk_size')}",
        f"- decode n_jobs: {profile.get('decode_n_jobs')}",
        f"- sector chunk size: {profile.get('sector_chunk_size')}",
        f"- snapshot decode mode: {profile.get('snapshot_decode_mode')}",
        f"- HSMM engine: {profile.get('hsmm_engine')}",
        f"- engine used: {profile.get('engine_used')}",
        f"- engine fallback reason: {profile.get('engine_fallback_reason')}",
        "",
        "This is a scale estimate only. It does not train or write HSMM model rows.",
    ]
    (output_dir / "performance_estimate.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _sector_name_map(storage: DuckDBStorage) -> dict[str, str]:
    meta = storage.read_df("SELECT sector_id, sector_name FROM sector_meta")
    names = {str(row["sector_id"]): str(row["sector_name"]) for _, row in meta.iterrows()} if not meta.empty else {}
    baskets = storage.read_df("SELECT basket_id, basket_name FROM custom_stock_basket")
    if not baskets.empty:
        names.update({f"custom:{row['basket_id']}": str(row["basket_name"]) for _, row in baskets.iterrows()})
    return names


def _state_row_from_snapshot(
    snapshot: dict[str, object],
    signal_date: pd.Timestamp,
    run_id: str,
    checkpoint_id: str,
    sector_code: str,
    sector_names: dict[str, str],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    feature_scope_id: str,
    snapshot_frequency: str,
) -> dict[str, object]:
    payload = {key: value for key, value in snapshot.items() if key != "trade_date"}
    return {
        "run_id": run_id,
        "checkpoint_id": checkpoint_id,
        "trade_date": pd.Timestamp(signal_date).date(),
        "sector_code": sector_code,
        "sector_name": sector_names.get(sector_code, sector_code),
        **payload,
        "state_probability": None,
        "train_start_date": train_start.date(),
        "train_end_date": train_end.date(),
        "max_observation_date_used": pd.Timestamp(signal_date).date(),
        "state_source": "causal_hsmm",
        "feature_scope_id": feature_scope_id,
        "decode_mode": "causal_prefix_viterbi",
        "snapshot_frequency": snapshot_frequency,
        "created_at": pd.Timestamp.now(),
    }


def _snapshot_rows(
    model: DiscreteDurationGaussianHSMM,
    sequences: list[pd.DataFrame],
    signal_date: pd.Timestamp,
    run_id: str,
    checkpoint_id: str,
    sector_names: dict[str, str],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    feature_scope_id: str,
    snapshot_frequency: str,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for seq in sequences:
        sector_code = str(seq["sector_id"].iloc[0])
        decoded = model.decode(seq)
        snapshot = model.lifecycle_snapshot(decoded, signal_date)
        if not snapshot:
            continue
        rows.append(
            _state_row_from_snapshot(
                snapshot,
                signal_date,
                run_id,
                checkpoint_id,
                sector_code,
                sector_names,
                train_start,
                train_end,
                feature_scope_id,
                snapshot_frequency,
            )
        )
    return rows


def _chunked(items: list[tuple[str, pd.DataFrame]], chunk_size: int) -> list[list[tuple[str, pd.DataFrame]]]:
    chunk_size = max(1, int(chunk_size or 32))
    return [items[i : i + chunk_size] for i in range(0, len(items), chunk_size)]


def _resolve_n_jobs(n_jobs: int | str) -> int:
    if isinstance(n_jobs, str):
        value = n_jobs.strip().lower()
        if value == "auto":
            return max(1, min((os.cpu_count() or 2) - 1, 4))
        return max(1, int(value))
    return max(1, int(n_jobs or 1))


def _prefix_rows_for_sector_items(
    model_payload: dict[str, object],
    sector_items: list[tuple[str, pd.DataFrame]],
    snapshot_dates: list[pd.Timestamp],
    run_id: str,
    checkpoint_id: str,
    sector_names: dict[str, str],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    feature_scope_id: str,
    snapshot_frequency: str,
) -> list[dict[str, object]]:
    model = DiscreteDurationGaussianHSMM.from_dict(model_payload)
    rows: list[dict[str, object]] = []
    for sector_code, seq in sector_items:
        snapshots = model.lifecycle_snapshots_from_sequence(seq, snapshot_dates)
        for snapshot in snapshots:
            rows.append(
                _state_row_from_snapshot(
                    snapshot,
                    pd.Timestamp(snapshot["trade_date"]),
                    run_id,
                    checkpoint_id,
                    sector_code,
                    sector_names,
                    train_start,
                    train_end,
                    feature_scope_id,
                    snapshot_frequency,
                )
            )
    return rows


def _snapshot_rows_for_checkpoint_prefix(
    model: DiscreteDurationGaussianHSMM,
    features: pd.DataFrame,
    sector_ids: set[str],
    snapshot_dates: list[pd.Timestamp],
    run_id: str,
    checkpoint_id: str,
    sector_names: dict[str, str],
    train_start: pd.Timestamp,
    train_end: pd.Timestamp,
    feature_scope_id: str,
    snapshot_frequency: str,
    n_jobs: int | str = 1,
    sector_chunk_size: int = 32,
) -> list[dict[str, object]]:
    if not snapshot_dates:
        return []
    snapshot_dates = [pd.Timestamp(date) for date in sorted(snapshot_dates)]
    max_snapshot = max(snapshot_dates)
    frame = features[
        (features["trade_date"] >= train_start)
        & (features["trade_date"] <= max_snapshot)
        & (features["sector_id"].astype(str).isin(sector_ids))
    ].copy()
    if frame.empty:
        return []
    sector_items: list[tuple[str, pd.DataFrame]] = []
    for sector_code, group in frame.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
        clean = group.dropna(subset=HSMM_FEATURE_COLUMNS)
        if not clean.empty and pd.Timestamp(clean["trade_date"].max()) >= snapshot_dates[0]:
            sector_items.append((str(sector_code), group.copy()))
    if not sector_items:
        return []

    model_payload = model.to_dict()
    jobs = _resolve_n_jobs(n_jobs)
    chunks = _chunked(sector_items, sector_chunk_size)
    if jobs <= 1 or len(chunks) <= 1:
        rows: list[dict[str, object]] = []
        for chunk in chunks:
            rows.extend(
                _prefix_rows_for_sector_items(
                    model_payload,
                    chunk,
                    snapshot_dates,
                    run_id,
                    checkpoint_id,
                    sector_names,
                    train_start,
                    train_end,
                    feature_scope_id,
                    snapshot_frequency,
                )
            )
        return rows

    try:
        from joblib import Parallel, delayed

        parts = Parallel(n_jobs=jobs, prefer="processes")(
            delayed(_prefix_rows_for_sector_items)(
                model_payload,
                chunk,
                snapshot_dates,
                run_id,
                checkpoint_id,
                sector_names,
                train_start,
                train_end,
                feature_scope_id,
                snapshot_frequency,
            )
            for chunk in chunks
        )
        rows = []
        for part in parts:
            rows.extend(part)
        return rows
    except Exception:
        rows = []
        for chunk in chunks:
            rows.extend(
                _prefix_rows_for_sector_items(
                    model_payload,
                    chunk,
                    snapshot_dates,
                    run_id,
                    checkpoint_id,
                    sector_names,
                    train_start,
                    train_end,
                    feature_scope_id,
                    snapshot_frequency,
                )
            )
        return rows


def _episodes_from_daily(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    rows: list[dict[str, object]] = []
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        first_snapshot_date = pd.Timestamp(group["trade_date"].iloc[0])
        start_idx = 0
        for i in range(1, len(group) + 1):
            boundary = i == len(group) or group.loc[i, "state_id"] != group.loc[i - 1, "state_id"]
            if not boundary:
                continue
            segment = group.iloc[start_idx:i]
            next_row = group.iloc[i] if i < len(group) else None
            start_date = pd.Timestamp(segment["trade_date"].iloc[0])
            end_date = pd.Timestamp(segment["trade_date"].iloc[-1])
            is_open = next_row is None
            is_left_censored = bool(start_date == first_snapshot_date)
            episode_id = f"{sector_code}:{start_date.strftime('%Y%m%d')}:{int(segment['state_id'].iloc[0])}"
            rows.append(
                {
                    "run_id": segment["run_id"].iloc[0],
                    "sector_code": sector_code,
                    "sector_name": segment["sector_name"].iloc[0],
                    "state_id": int(segment["state_id"].iloc[0]),
                    "state_label": segment["state_label"].iloc[0],
                    "episode_id": episode_id,
                    "start_date": start_date.date(),
                    "end_date": end_date.date(),
                    "duration_days": int(len(segment)),
                    "duration_trading_days": int(len(segment)),
                    "duration_calendar_days": int((end_date - start_date).days + 1),
                    "entry_trade_date": start_date.date(),
                    "exit_trade_date": None if next_row is None else pd.Timestamp(next_row["trade_date"]).date(),
                    "next_state_id": None if next_row is None else int(next_row["state_id"]),
                    "next_state_label": None if next_row is None else str(next_row["state_label"]),
                    "is_left_censored": bool(is_left_censored),
                    "left_censor_reason": "starts_at_run_boundary" if is_left_censored else None,
                    "is_right_censored": bool(is_open),
                    "right_censor_reason": "open_at_run_end" if is_open else None,
                    "checkpoint_id_start": str(segment["checkpoint_id"].iloc[0]) if "checkpoint_id" in segment.columns else None,
                    "checkpoint_id_end": str(segment["checkpoint_id"].iloc[-1]) if "checkpoint_id" in segment.columns else None,
                    "is_open_episode": is_open,
                    "created_at": pd.Timestamp.now(),
                }
            )
            start_idx = i
    return pd.DataFrame(rows)


def _write_episodes(storage: DuckDBStorage, run_id: str, episodes: pd.DataFrame) -> None:
    with storage.connect() as con:
        con.execute("DELETE FROM hsmm_state_episodes WHERE run_id = ?", [run_id])
        if not episodes.empty:
            con.register("incoming_hsmm_episodes", episodes)
            cols = list(episodes.columns)
            con.execute(f"INSERT INTO hsmm_state_episodes ({', '.join(cols)}) SELECT {', '.join(cols)} FROM incoming_hsmm_episodes")
            con.execute("UPDATE hsmm_state_episodes SET is_left_censored = TRUE WHERE run_id = ? AND left_censor_reason IS NOT NULL", [run_id])
            con.execute("UPDATE hsmm_state_episodes SET is_right_censored = TRUE WHERE run_id = ? AND right_censor_reason IS NOT NULL", [run_id])
    if not episodes.empty:
        with storage.connect() as con:
            con.execute("UPDATE hsmm_state_episodes SET is_left_censored = TRUE WHERE run_id = ? AND left_censor_reason IS NOT NULL", [run_id])
            con.execute("UPDATE hsmm_state_episodes SET is_right_censored = TRUE WHERE run_id = ? AND right_censor_reason IS NOT NULL", [run_id])


def _stitch_state_age_by_label(states: pd.DataFrame) -> pd.DataFrame:
    """Keep same-label lifecycle age continuous across checkpoint boundaries."""
    if states.empty or "state_label" not in states.columns:
        return states
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    label_ages: list[int] = []
    for _, group in work.groupby("sector_code", sort=False):
        previous_label: str | None = None
        age = 0
        for label in group["state_label"].astype(str):
            age = age + 1 if label == previous_label else 1
            label_ages.append(age)
            previous_label = label
    work["state_age_days_by_label"] = label_ages
    work["label_state_age_days"] = label_ages
    work["display_state_age_days"] = label_ages
    if "model_state_age_days" not in work.columns:
        work["model_state_age_days"] = work.get("state_age_days_by_id", work.get("state_age_days"))
    if "duration_model_age_days" not in work.columns:
        work["duration_model_age_days"] = work["model_state_age_days"]
    work["state_age_days"] = work["model_state_age_days"]
    return work.sort_index()


def run_hsmm_walk_forward(
    config: HSMMWalkForwardConfig,
    storage: DuckDBStorage | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, object]:
    if config.snapshot_decode_mode not in {"legacy", "prefix"}:
        raise ValueError("snapshot_decode_mode must be legacy or prefix")
    if config.checkpoint_write_mode not in {"end", "incremental"}:
        raise ValueError("checkpoint_write_mode must be end or incremental")
    storage = storage or (DuckDBStorage(config.db_path) if config.db_path else DuckDBStorage())
    storage.init_schema()
    run_id = _resolve_run_id(config)
    ohlcv = load_sector_like_ohlcv(storage, universe_id=config.universe_id, include_custom_baskets=config.include_custom_baskets)
    if ohlcv.empty:
        raise ValueError("缺少板块行情，无法训练 HSMM。")
    start_date, end_date = _resolve_dates(config, ohlcv)
    feature_scope_id, feature_scope_type = feature_scope_for_universe(storage, config.universe_id, config.include_custom_baskets)
    if config.feature_scope_id:
        feature_scope_id = config.feature_scope_id
    features = build_hsmm_features(
        ohlcv,
        feature_version=config.feature_version,
        feature_scope_id=feature_scope_id,
        feature_scope_type=feature_scope_type,
    )
    features["trade_date"] = pd.to_datetime(features["trade_date"])
    features = features[features["trade_date"] <= end_date].copy()
    all_trade_dates = pd.Series(features["trade_date"].drop_duplicates().sort_values())
    snapshot_dates = pd.Series(all_trade_dates[(all_trade_dates >= start_date) & (all_trade_dates <= end_date)]).tolist()
    if config.snapshot_frequency != "daily":
        raise ValueError("HSMM MVP only supports snapshot_frequency='daily'")
    checkpoint_dates = _select_checkpoint_dates(all_trade_dates, snapshot_dates, config)
    sector_names = _sector_name_map(storage)
    lineage_digests = _hsmm_lineage_digests(storage, config, ohlcv, snapshot_dates, start_date, end_date)
    config_payload = _config_hash_payload(config, feature_scope_id, feature_scope_type, lineage_digests)
    hash_value = params_hash(config_payload)
    run_hash = params_hash({**config_payload, "run_id": run_id})

    if config.profile_only:
        profile = build_hsmm_performance_profile(
            run_id=run_id,
            config=config,
            ohlcv=ohlcv,
            features=features,
            start_date=start_date,
            end_date=end_date,
            checkpoint_dates=checkpoint_dates,
            snapshot_dates=snapshot_dates,
            feature_scope_id=feature_scope_id,
            feature_scope_type=feature_scope_type,
        )
        if progress_callback:
            progress_callback(1, 1, end_date, "profile_ready")
        return {
            "run_id": run_id,
            "profile": profile,
            "states": pd.DataFrame(),
            "episodes": pd.DataFrame(),
            "checkpoints": pd.DataFrame(),
            "performance": pd.DataFrame(),
            "config_hash": hash_value,
            "run_hash": run_hash,
        }

    existing_run = storage.read_df("SELECT run_status FROM hsmm_model_runs WHERE run_id = ? LIMIT 1", [run_id])
    existing_status = None if existing_run.empty else str(existing_run.loc[0, "run_status"] or "completed")
    if existing_status == "completed" and not config.overwrite:
        raise ValueError(f"HSMM run_id already completed: {run_id}. Use overwrite=True to rerun and cascade-clean stale rows.")
    cleanup_summary: dict[str, object] | None = None
    if config.overwrite or (not config.append and not config.resume):
        cleanup_summary = clear_hsmm_run(storage, run_id)

    rows: list[dict[str, object]] = []
    checkpoint_rows: list[dict[str, object]] = []
    performance_rows: list[dict[str, object]] = []
    checkpoint_artifacts: dict[pd.Timestamp, dict[str, object]] = {}
    last_model: DiscreteDurationGaussianHSMM | None = None
    fit_n_jobs = _fit_n_jobs_for_config(config)

    sector_count = int(features["sector_id"].astype(str).nunique()) if "sector_id" in features.columns else 0
    expected_snapshot_count = int(len(snapshot_dates))
    expected_state_row_count = int(expected_snapshot_count * sector_count)
    run_started_at = pd.Timestamp.now(tz=None)
    _write_hsmm_run_metadata(
        storage,
        _hsmm_run_metadata_frame(
            run_id=run_id,
            config=config,
            feature_scope_id=feature_scope_id,
            feature_scope_type=feature_scope_type,
            start_date=start_date,
            end_date=end_date,
            config_payload=config_payload,
            config_hash=hash_value,
            run_hash=run_hash,
            lineage_digests=lineage_digests,
            run_status="running",
            started_at=run_started_at,
            expected_snapshot_count=expected_snapshot_count,
            expected_state_row_count=expected_state_row_count,
        ),
    )

    try:
        for ordinal, train_date in enumerate(checkpoint_dates, start=1):
            train_date = pd.Timestamp(train_date)
            checkpoint_id = _checkpoint_id(run_id, train_date, ordinal)
            train_sequences = _training_sequences(features, train_date, config)
            if len(train_sequences) < config.min_train_sequences:
                if progress_callback:
                    progress_callback(ordinal, len(checkpoint_dates), train_date, "insufficient_training_data")
                continue
            model = DiscreteDurationGaussianHSMM(
                n_states=config.n_states,
                max_duration=config.max_duration,
                n_iter=config.n_iter,
                tol=config.tol,
                duration_smoothing=config.duration_smoothing,
                transition_smoothing=config.transition_smoothing,
                variance_floor=config.variance_floor,
                random_state=config.random_state,
                engine=config.hsmm_engine,
                n_jobs=fit_n_jobs,
                sequence_chunk_size=config.fit_sequence_chunk_size,
            )
            fit_started = time.perf_counter()
            if progress_callback:
                progress_callback(ordinal, len(checkpoint_dates), train_date, "checkpoint_fit_started")
            model.fit(train_sequences, HSMM_FEATURE_COLUMNS)
            fit_seconds = time.perf_counter() - fit_started
            train_start = min(pd.to_datetime(seq["trade_date"]).min() for seq in train_sequences)
            train_end = max(pd.to_datetime(seq["trade_date"]).max() for seq in train_sequences)
            n_observations = int(sum(len(seq.dropna(subset=HSMM_FEATURE_COLUMNS)) for seq in train_sequences))
            model_params_json = model.to_json()
            model_params_hash = params_hash(json.loads(model_params_json))
            checkpoint_artifacts[train_date] = {
                "checkpoint_id": checkpoint_id,
                "model": model,
                "train_start": pd.Timestamp(train_start),
                "train_end": pd.Timestamp(train_end),
                "sector_ids": {str(seq["sector_id"].iloc[0]) for seq in train_sequences},
            }
            checkpoint_rows.append(
                {
                    "run_id": run_id,
                    "checkpoint_id": checkpoint_id,
                    "train_date": train_date.date(),
                    "train_start_date": pd.Timestamp(train_start).date(),
                    "train_end_date": pd.Timestamp(train_end).date(),
                    "train_trade_day_count": int(pd.Series(pd.concat(train_sequences)["trade_date"]).nunique()),
                    "n_sequences": len(train_sequences),
                    "n_observations": n_observations,
                    "model_version": "hsmm_v1",
                    "feature_columns_json": json_dumps(HSMM_FEATURE_COLUMNS),
                    "state_label_profile_json": json_dumps(model.state_labels_),
                    "params_json": model_params_json,
                    "params_hash": model_params_hash,
                    "config_hash": hash_value,
                    "created_at": pd.Timestamp.now(),
                }
            )
            performance_rows.append(
                {
                    "run_id": run_id,
                    "checkpoint_id": checkpoint_id,
                    "train_date": train_date.date(),
                    "train_start_date": pd.Timestamp(train_start).date(),
                    "train_end_date": pd.Timestamp(train_end).date(),
                    "training_sequence_count": len(train_sequences),
                    "training_row_count": n_observations,
                    "fit_seconds": fit_seconds,
                    "decode_snapshot_count": 0,
                    "decode_sector_count": 0,
                    "decode_rows_generated": 0,
                    "decode_seconds": 0.0,
                    "fit_n_jobs": model.fit_n_jobs_,
                    "fit_parallel_enabled": model.fit_parallel_enabled_,
                    "fit_parallel_fallback": model.fit_parallel_fallback_,
                    "fit_parallel_warning": model.fit_parallel_warning_,
                    "fit_iteration_count": model.fit_iteration_count_,
                    "fit_decode_seconds": model.fit_decode_seconds_,
                    "fit_update_seconds": model.fit_update_seconds_,
                    "decode_n_jobs": config.n_jobs,
                    "sector_chunk_size": config.sector_chunk_size,
                    "snapshot_decode_mode": config.snapshot_decode_mode,
                    "hsmm_engine": config.hsmm_engine,
                    "engine_used": model.engine_used_,
                    "engine_fallback_reason": model.engine_fallback_reason_,
                    "created_at": pd.Timestamp.now(),
                }
            )
            if config.persist_incremental or config.checkpoint_write_mode == "incremental":
                storage.upsert_df("hsmm_model_checkpoints", pd.DataFrame([checkpoint_rows[-1]]), ["run_id", "checkpoint_id"])
                storage.upsert_df("hsmm_run_performance", _hsmm_performance_storage_frame([performance_rows[-1]]), ["run_id", "checkpoint_id"])
            last_model = model
            if progress_callback:
                progress_callback(ordinal, len(checkpoint_dates), train_date, "checkpoint_trained")

        performance_by_checkpoint = {row["checkpoint_id"]: row for row in performance_rows}
        if config.snapshot_decode_mode == "legacy":
            for idx, snapshot_date in enumerate(snapshot_dates, start=1):
                snapshot_date = pd.Timestamp(snapshot_date)
                checkpoint_date = _latest_checkpoint_for(snapshot_date, sorted(checkpoint_artifacts))
                if checkpoint_date is None:
                    continue
                artifact = checkpoint_artifacts[checkpoint_date]
                infer_sequences = _inference_sequences(
                    features,
                    artifact["sector_ids"],
                    artifact["train_start"],
                    snapshot_date,
                )
                decode_started = time.perf_counter()
                snapshot_rows = _snapshot_rows(
                    artifact["model"],
                    infer_sequences,
                    snapshot_date,
                    run_id,
                    artifact["checkpoint_id"],
                    sector_names,
                    artifact["train_start"],
                    artifact["train_end"],
                    feature_scope_id,
                    config.snapshot_frequency,
                )
                decode_seconds = time.perf_counter() - decode_started
                rows.extend(snapshot_rows)
                perf = performance_by_checkpoint.get(artifact["checkpoint_id"])
                if perf is not None:
                    perf["decode_snapshot_count"] += 1
                    perf["decode_sector_count"] = max(perf["decode_sector_count"], len(infer_sequences))
                    perf["decode_rows_generated"] += len(snapshot_rows)
                    perf["decode_seconds"] += decode_seconds
                    if config.persist_incremental or config.checkpoint_write_mode == "incremental":
                        storage.upsert_df("hsmm_run_performance", _hsmm_performance_storage_frame([perf]), ["run_id", "checkpoint_id"])
                if snapshot_rows and (config.persist_incremental or config.checkpoint_write_mode == "incremental"):
                    storage.upsert_df("hsmm_state_daily", pd.DataFrame(snapshot_rows), ["run_id", "trade_date", "sector_code"])
                if progress_callback and (idx == 1 or idx == len(snapshot_dates) or idx % max(1, config.log_every_n_snapshots) == 0):
                    progress_callback(idx, len(snapshot_dates), snapshot_date, "snapshot_decoded")
        else:
            checkpoint_snapshot_dates = _snapshot_dates_by_checkpoint(snapshot_dates, sorted(checkpoint_artifacts))
            for idx, (checkpoint_date, served_dates) in enumerate(checkpoint_snapshot_dates.items(), start=1):
                artifact = checkpoint_artifacts[checkpoint_date]
                if progress_callback:
                    progress_callback(idx, len(checkpoint_snapshot_dates), pd.Timestamp(served_dates[-1]), "checkpoint_decode_started")
                decode_started = time.perf_counter()
                snapshot_rows = _snapshot_rows_for_checkpoint_prefix(
                    artifact["model"],
                    features,
                    artifact["sector_ids"],
                    served_dates,
                    run_id,
                    artifact["checkpoint_id"],
                    sector_names,
                    artifact["train_start"],
                    artifact["train_end"],
                    feature_scope_id,
                    config.snapshot_frequency,
                    n_jobs=config.n_jobs,
                    sector_chunk_size=config.sector_chunk_size,
                )
                decode_seconds = time.perf_counter() - decode_started
                rows.extend(snapshot_rows)
                perf = performance_by_checkpoint.get(artifact["checkpoint_id"])
                if perf is not None:
                    perf["decode_snapshot_count"] += len(served_dates)
                    perf["decode_sector_count"] = max(perf["decode_sector_count"], len(artifact["sector_ids"]))
                    perf["decode_rows_generated"] += len(snapshot_rows)
                    perf["decode_seconds"] += decode_seconds
                    if config.persist_incremental or config.checkpoint_write_mode == "incremental":
                        storage.upsert_df("hsmm_run_performance", _hsmm_performance_storage_frame([perf]), ["run_id", "checkpoint_id"])
                if snapshot_rows and (config.persist_incremental or config.checkpoint_write_mode == "incremental"):
                    storage.upsert_df("hsmm_state_daily", pd.DataFrame(snapshot_rows), ["run_id", "trade_date", "sector_code"])
                if progress_callback:
                    progress_callback(idx, len(checkpoint_snapshot_dates), pd.Timestamp(served_dates[-1]), "checkpoint_decode_finished")

        states = _stitch_state_age_by_label(pd.DataFrame(rows))
        if not states.empty:
            storage.upsert_df("hsmm_state_daily", states, ["run_id", "trade_date", "sector_code"])
        if checkpoint_rows:
            storage.upsert_df("hsmm_model_checkpoints", pd.DataFrame(checkpoint_rows), ["run_id", "checkpoint_id"])
        performance_df = pd.DataFrame(performance_rows)
        if not performance_df.empty:
            storage.upsert_df("hsmm_run_performance", _hsmm_performance_storage_frame(performance_df), ["run_id", "checkpoint_id"])
        episodes = _episodes_from_daily(states)
        _write_episodes(storage, run_id, episodes)

        if last_model is not None:
            payload = last_model.to_dict()
            params_df = pd.DataFrame(
                [
                    {
                        "run_id": run_id,
                        "state_labels_json": json_dumps(payload["state_labels"]),
                        "startprob_json": json_dumps(payload["startprob"]),
                        "transition_matrix_json": json_dumps(payload["transmat"]),
                        "duration_pmf_json": json_dumps(payload["duration_pmf"]),
                        "emission_mean_json": json_dumps(payload["means"]),
                        "emission_var_json": json_dumps(payload["vars"]),
                        "scaler_json": json_dumps(payload["scaler"]),
                        "created_at": pd.Timestamp.now(),
                    }
                ]
            )
            storage.upsert_df("hsmm_parameters", params_df, ["run_id"])

        actual_snapshot_count = int(states["trade_date"].nunique()) if "trade_date" in states.columns and not states.empty else 0
        actual_state_row_count = int(len(states))
        _write_hsmm_run_metadata(
            storage,
            _hsmm_run_metadata_frame(
                run_id=run_id,
                config=config,
                feature_scope_id=feature_scope_id,
                feature_scope_type=feature_scope_type,
                start_date=start_date,
                end_date=end_date,
                config_payload=config_payload,
                config_hash=hash_value,
                run_hash=run_hash,
                lineage_digests=lineage_digests,
                run_status="completed",
                started_at=run_started_at,
                completed_at=pd.Timestamp.now(tz=None),
                expected_snapshot_count=expected_snapshot_count,
                expected_state_row_count=expected_state_row_count,
                actual_snapshot_count=actual_snapshot_count,
                actual_state_row_count=actual_state_row_count,
            ),
        )
        return {
            "run_id": run_id,
            "states": states,
            "episodes": episodes,
            "checkpoints": pd.DataFrame(checkpoint_rows),
            "performance": performance_df,
            "config_hash": hash_value,
            "run_hash": run_hash,
            "cleanup_summary": cleanup_summary,
        }
    except Exception as exc:
        failure_states = pd.DataFrame(rows)
        actual_snapshot_count = int(failure_states["trade_date"].nunique()) if "trade_date" in failure_states.columns and not failure_states.empty else 0
        _write_hsmm_run_metadata(
            storage,
            _hsmm_run_metadata_frame(
                run_id=run_id,
                config=config,
                feature_scope_id=feature_scope_id,
                feature_scope_type=feature_scope_type,
                start_date=start_date,
                end_date=end_date,
                config_payload=config_payload,
                config_hash=hash_value,
                run_hash=run_hash,
                lineage_digests=lineage_digests,
                run_status="failed",
                started_at=run_started_at,
                failed_at=pd.Timestamp.now(tz=None),
                failure_message=str(exc)[:1000],
                expected_snapshot_count=expected_snapshot_count,
                expected_state_row_count=expected_state_row_count,
                actual_snapshot_count=actual_snapshot_count,
                actual_state_row_count=int(len(failure_states)),
            ),
        )
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Run causal walk-forward HSMM lifecycle model")
    parser.add_argument("--db", dest="db_path", default=None)
    parser.add_argument("--start-date", required=True)
    parser.add_argument("--end-date", default="today")
    parser.add_argument("--universe-id", default=None)
    parser.add_argument("--exclude-custom-baskets", action="store_true")
    parser.add_argument("--feature-scope-id", default=None)
    parser.add_argument("--feature-preset", default="hsmm_v1")
    parser.add_argument("--n-states", type=int, default=4)
    parser.add_argument("--max-duration", type=int, default=60)
    parser.add_argument("--train-window-days", type=int, default=504)
    parser.add_argument("--train-frequency", default="monthly", choices=["monthly", "every_n_trade_days"])
    parser.add_argument("--train-every-n-trade-days", type=int, default=None)
    parser.add_argument("--snapshot-frequency", default="daily", choices=["daily"])
    parser.add_argument("--rebalance-days", type=int, default=5)
    parser.add_argument("--min-sequence-length", type=int, default=30)
    parser.add_argument("--n-iter", type=int, default=20)
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--append", action="store_true")
    parser.add_argument("--profile-only", action="store_true")
    parser.add_argument("--snapshot-decode-mode", default="prefix", choices=["legacy", "prefix"])
    parser.add_argument("--hsmm-engine", default="auto", choices=["python", "auto", "numba"])
    parser.add_argument("--n-jobs", default="1")
    parser.add_argument("--sector-chunk-size", type=int, default=32)
    parser.add_argument("--fit-n-jobs", default=None)
    parser.add_argument("--fit-sequence-chunk-size", type=int, default=32)
    parser.add_argument("--log-every-n-snapshots", type=int, default=10)
    parser.add_argument("--persist-incremental", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--checkpoint-write-mode", default="end", choices=["end", "incremental"])
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    def _print_progress(current: int, total: int, trade_date: pd.Timestamp, stage: str) -> None:
        timestamp = pd.Timestamp.now().strftime("%H:%M:%S")
        date_text = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
        print(f"[{timestamp}] {stage}: {current}/{total} @ {date_text}", flush=True)

    result = run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=args.db_path,
            start_date=args.start_date,
            end_date=args.end_date,
            universe_id=args.universe_id,
            include_custom_baskets=not args.exclude_custom_baskets,
            feature_scope_id=args.feature_scope_id,
            feature_preset=args.feature_preset,
            n_states=args.n_states,
            max_duration=args.max_duration,
            train_window_days=args.train_window_days,
            train_frequency=args.train_frequency,
            train_every_n_trade_days=args.train_every_n_trade_days,
            snapshot_frequency=args.snapshot_frequency,
            rebalance_days=args.rebalance_days,
            min_sequence_length=args.min_sequence_length,
            n_iter=args.n_iter,
            run_id=args.run_id,
            append=args.append,
            profile_only=args.profile_only,
            snapshot_decode_mode=args.snapshot_decode_mode,
            hsmm_engine=args.hsmm_engine,
            n_jobs=args.n_jobs,
            sector_chunk_size=args.sector_chunk_size,
            fit_n_jobs=args.fit_n_jobs,
            fit_sequence_chunk_size=args.fit_sequence_chunk_size,
            log_every_n_snapshots=args.log_every_n_snapshots,
            persist_incremental=args.persist_incremental,
            resume=args.resume,
            checkpoint_write_mode=args.checkpoint_write_mode,
            overwrite=args.overwrite,
        ),
        progress_callback=_print_progress,
    )
    if args.profile_only:
        output_dir = Path("reports/hsmm_diagnostics") / str(result["run_id"])
        write_hsmm_performance_profile(result["profile"], output_dir)
        print(f"profile_json: {output_dir / 'performance_estimate.json'}")
        print(f"profile_md: {output_dir / 'performance_estimate.md'}")
        return
    print(f"run_id: {result['run_id']}")
    print(f"checkpoint_rows: {len(result['checkpoints'])}")
    print(f"state_rows: {len(result['states'])}")
    print(f"episode_rows: {len(result['episodes'])}")
    performance = result.get("performance")
    if isinstance(performance, pd.DataFrame) and not performance.empty:
        output_dir = Path("reports/hsmm_diagnostics") / str(result["run_id"])
        output_dir.mkdir(parents=True, exist_ok=True)
        performance.to_csv(output_dir / "hsmm_run_performance.csv", index=False)
        print(f"performance_csv: {output_dir / 'hsmm_run_performance.csv'}")


if __name__ == "__main__":
    main()
