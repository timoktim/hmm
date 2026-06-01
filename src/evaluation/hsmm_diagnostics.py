from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv
from src.evaluation.hsmm_exit_calibration import (
    apply_exit_calibrator,
    build_exit_calibration_dataset,
    fit_empirical_exit_calibrator,
    summarize_exit_calibration,
)
from src.features.hsmm_features import HSMM_FEATURE_COLUMNS, build_hsmm_features
from src.models.hsmm_walk_forward import params_hash


def _read_run(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    return storage.read_df("SELECT * FROM hsmm_model_runs WHERE run_id = ?", [run_id])


def _read_states(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    df = storage.read_df("SELECT * FROM hsmm_state_daily WHERE run_id = ? ORDER BY sector_code, trade_date", [run_id])
    if not df.empty:
        for col in ["trade_date", "train_start_date", "train_end_date", "max_observation_date_used"]:
            df[col] = pd.to_datetime(df[col])
    return df


def _read_episodes(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    df = storage.read_df("SELECT * FROM hsmm_state_episodes WHERE run_id = ? ORDER BY sector_code, start_date", [run_id])
    if not df.empty:
        for col in ["start_date", "end_date", "entry_trade_date", "exit_trade_date"]:
            df[col] = pd.to_datetime(df[col])
    return df


def _read_checkpoints(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    df = storage.read_df("SELECT * FROM hsmm_model_checkpoints WHERE run_id = ? ORDER BY train_date", [run_id])
    if not df.empty:
        for col in ["train_date", "train_start_date", "train_end_date"]:
            df[col] = pd.to_datetime(df[col])
    return df


def _read_run_performance(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    df = storage.read_df("SELECT * FROM hsmm_run_performance WHERE run_id = ? ORDER BY train_date", [run_id])
    if not df.empty:
        for col in ["train_date", "train_start_date", "train_end_date", "created_at"]:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col])
    return df


def causality_audit(
    run: pd.DataFrame,
    states: pd.DataFrame,
    episodes: pd.DataFrame,
    checkpoints: pd.DataFrame | None = None,
    expected_trade_dates: pd.Series | list[pd.Timestamp] | None = None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []

    def add(check: str, passed: bool, details: str = "", severity: str = "error") -> None:
        rows.append({"check": check, "passed": bool(passed), "severity": severity, "details": details})

    if run.empty:
        add("run exists", False, "hsmm_model_runs 缺少 run_id")
        return pd.DataFrame(rows)
    if states.empty:
        add("states exist", False, "hsmm_state_daily 为空")
        return pd.DataFrame(rows)
    run_start = pd.to_datetime(run.loc[0].get("start_date"))
    run_end = pd.to_datetime(run.loc[0].get("end_date"))
    state_dates = pd.to_datetime(states["trade_date"])
    add("state_trade_date_within_run_window", bool((state_dates >= run_start).all() and (state_dates <= run_end).all()), f"run_start={run_start.date()}, run_end={run_end.date()}")
    add("state_source == causal_hsmm", states["state_source"].fillna("").eq("causal_hsmm").all())
    add("train_end_date <= trade_date", (states["train_end_date"] <= states["trade_date"]).all())
    add("checkpoint_train_end_date_lte_state_trade_date", (states["train_end_date"] <= states["trade_date"]).all())
    add("max_observation_date_used <= trade_date", (states["max_observation_date_used"] <= states["trade_date"]).all())
    if "checkpoint_id" in states.columns:
        add("checkpoint_id_not_null", states["checkpoint_id"].fillna("").astype(str).ne("").all())
    if checkpoints is not None and not checkpoints.empty and "checkpoint_id" in states.columns:
        valid_checkpoints = set(checkpoints["checkpoint_id"].astype(str))
        add("checkpoint_exists_for_every_state", states["checkpoint_id"].astype(str).isin(valid_checkpoints).all())
        checkpoint_dates = checkpoints[["checkpoint_id", "train_date", "train_end_date"]].copy()
        checkpoint_dates["checkpoint_id"] = checkpoint_dates["checkpoint_id"].astype(str)
        merged = states.merge(checkpoint_dates, on="checkpoint_id", how="left", suffixes=("", "_checkpoint"))
        add("checkpoint_train_date_lte_state_trade_date", (pd.to_datetime(merged["train_date"]) <= pd.to_datetime(merged["trade_date"])).all())
        add("checkpoint_train_end_date_lte_state_trade_date", (pd.to_datetime(merged["train_end_date_checkpoint"]) <= pd.to_datetime(merged["trade_date"])).all())
    else:
        add("checkpoint_exists_for_every_state", False, "缺少 hsmm_model_checkpoints")
    if "decode_mode" in states.columns:
        add("decode_mode == causal_prefix_viterbi", states["decode_mode"].fillna("").eq("causal_prefix_viterbi").all())
    snapshot_frequency = str(run.loc[0].get("snapshot_frequency") or "")
    add("snapshot_frequency == daily", snapshot_frequency == "daily", snapshot_frequency)
    feature_cols = json.loads(run.loc[0, "feature_columns_json"] or "[]")
    bad_cols = [col for col in feature_cols if "forward" in str(col).lower() or "future" in str(col).lower()]
    add("no_forward_return_in_features", not bad_cols, ",".join(bad_cols))
    cross_leak = False
    if not episodes.empty:
        cross_leak = episodes["sector_code"].isna().any() or (episodes["duration_days"] <= 0).any()
    add("no_cross_sector_transition_leakage", not cross_leak)
    if not episodes.empty:
        valid_sector_codes = set(states["sector_code"].astype(str))
        add("episode_sector_keys_valid", episodes["sector_code"].astype(str).isin(valid_sector_codes).all())
        state_ranges = states.groupby("sector_code")["trade_date"].agg(["min", "max"]).reset_index()
        episode_ranges = episodes.merge(state_ranges, on="sector_code", how="left")
        in_range = (
            pd.to_datetime(episode_ranges["start_date"]) >= pd.to_datetime(episode_ranges["min"])
        ) & (
            pd.to_datetime(episode_ranges["end_date"]) <= pd.to_datetime(episode_ranges["max"])
        )
        add("episode_start_end_within_state_range", bool(in_range.all()))
        add("episode_does_not_cross_sector", bool(episodes["sector_code"].fillna("").astype(str).ne("").all()))
    duplicate_keys = states.duplicated(["run_id", "sector_code", "trade_date"]).any()
    add("no_duplicate_state_keys", not duplicate_keys)
    if expected_trade_dates is not None:
        expected = set(pd.to_datetime(pd.Series(expected_trade_dates)).dt.date)
        actual = set(pd.to_datetime(states["trade_date"]).dt.date)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        add("state_snapshot_dates_match_expected_trading_calendar", not missing and not extra, f"missing={len(missing)}, extra={len(extra)}")
    else:
        add("state_snapshot_dates_match_expected_trading_calendar", True, "expected calendar not available", severity="warning")
    add("feature_max_observation_date_lte_state_trade_date_if_available", True, "max_observation_date_used 已检查；原始特征最大观测日未单独持久化", severity="warning")
    add("checkpoint_created_before_or_at_decode_if_timestamp_available", True, "state 解码时间未单独持久化", severity="warning")
    payload = json.loads(run.loc[0].get("config_json") or run.loc[0].get("params_json") or "{}")
    expected_hash = params_hash(payload)
    actual_hash = str(run.loc[0].get("config_hash") or run.loc[0].get("params_hash") or "")
    add("config_hash_matches_run_config", expected_hash == actual_hash, f"expected={expected_hash}, actual={actual_hash}" if expected_hash != actual_hash else "")
    return pd.DataFrame(rows)


def coverage_snapshot(run: pd.DataFrame, states: pd.DataFrame, ohlcv: pd.DataFrame) -> pd.DataFrame:
    if run.empty:
        return pd.DataFrame([{"status": "empty"}])
    if ohlcv.empty:
        return pd.DataFrame([{"run_id": run.loc[0, "run_id"], "status": "no_ohlcv", "coverage_passed": False}])
    run_row = run.iloc[0]
    ohlcv_work = ohlcv.copy()
    ohlcv_work["trade_date"] = pd.to_datetime(ohlcv_work["trade_date"])
    if pd.notna(run_row.get("start_date")):
        ohlcv_work = ohlcv_work[ohlcv_work["trade_date"] >= pd.to_datetime(run_row.get("start_date"))]
    if pd.notna(run_row.get("end_date")):
        ohlcv_work = ohlcv_work[ohlcv_work["trade_date"] <= pd.to_datetime(run_row.get("end_date"))]
    expected_dates = pd.Series(ohlcv_work["trade_date"].drop_duplicates().sort_values())
    expected_sectors = pd.Series(ohlcv_work["sector_id"].astype(str).drop_duplicates().sort_values())
    expected = int(len(expected_dates) * len(expected_sectors))
    state_work = states.copy()
    if not state_work.empty:
        state_work["trade_date"] = pd.to_datetime(state_work["trade_date"])
        state_work["sector_code"] = state_work["sector_code"].astype(str)
    actual_dates = pd.Series(state_work["trade_date"].drop_duplicates().sort_values()) if not state_work.empty else pd.Series(dtype="datetime64[ns]")
    actual_sectors = pd.Series(state_work["sector_code"].drop_duplicates().sort_values()) if not state_work.empty else pd.Series(dtype=str)
    stored = int(len(state_work.drop_duplicates(["sector_code", "trade_date"]))) if not state_work.empty else 0
    per_sector = state_work.groupby("sector_code")["trade_date"].nunique() if not state_work.empty else pd.Series(dtype=float)
    per_sector = per_sector.reindex(expected_sectors.tolist(), fill_value=0)
    missing_dates = sorted(set(pd.to_datetime(expected_dates).dt.date) - set(pd.to_datetime(actual_dates).dt.date))
    extra_dates = sorted(set(pd.to_datetime(actual_dates).dt.date) - set(pd.to_datetime(expected_dates).dt.date))
    missing_sectors = sorted(set(expected_sectors.astype(str)) - set(actual_sectors.astype(str)))
    extra_sectors = sorted(set(actual_sectors.astype(str)) - set(expected_sectors.astype(str)))
    ratio = float(stored / expected) if expected else np.nan
    coverage_passed = bool(expected > 0 and stored == expected and not missing_dates and not extra_dates and not missing_sectors and not extra_sectors)
    return pd.DataFrame(
        [
            {
                "run_id": run.loc[0, "run_id"],
                "snapshot_frequency": run.loc[0].get("snapshot_frequency"),
                "expected_min_trade_date": expected_dates.min().date() if len(expected_dates) else None,
                "expected_max_trade_date": expected_dates.max().date() if len(expected_dates) else None,
                "actual_min_trade_date": actual_dates.min().date() if len(actual_dates) else None,
                "actual_max_trade_date": actual_dates.max().date() if len(actual_dates) else None,
                "expected_trade_day_count": int(len(expected_dates)),
                "actual_trade_day_count": int(len(actual_dates)),
                "expected_sector_count": int(len(expected_sectors)),
                "actual_sector_count": int(len(actual_sectors)),
                "expected_dense_rows": expected,
                "actual_state_rows": stored,
                "stored_rows": stored,
                "dense_coverage_ratio": ratio,
                "coverage_ratio_against_expected": ratio,
                "missing_trade_date_count": int(len(missing_dates)),
                "missing_trade_dates_sample": json.dumps([str(x) for x in missing_dates[:10]], ensure_ascii=False),
                "extra_trade_date_count": int(len(extra_dates)),
                "missing_sector_count": int(len(missing_sectors)),
                "missing_sector_codes_sample": json.dumps(missing_sectors[:10], ensure_ascii=False),
                "extra_sector_count": int(len(extra_sectors)),
                "sectors_with_partial_snapshots": int((per_sector < len(expected_dates)).sum()) if len(expected_dates) else 0,
                "min_rows_per_sector": int(per_sector.min()) if not per_sector.empty else 0,
                "p10_rows_per_sector": float(per_sector.quantile(0.10)) if not per_sector.empty else 0,
                "median_rows_per_sector": float(per_sector.median()) if not per_sector.empty else 0,
                "p90_rows_per_sector": float(per_sector.quantile(0.90)) if not per_sector.empty else 0,
                "max_rows_per_sector": int(per_sector.max()) if not per_sector.empty else 0,
                "coverage_passed": coverage_passed,
                "daily_snapshot_complete": bool(not missing_dates and not extra_dates),
                "universe_complete": bool(not missing_sectors and not extra_sectors),
                "status": "complete" if coverage_passed else "incomplete",
            }
        ]
    )


def _run_config(run: pd.DataFrame) -> dict[str, Any]:
    if run.empty:
        return {}
    raw = run.iloc[0].get("config_json") or run.iloc[0].get("params_json") or "{}"
    try:
        return json.loads(raw)
    except Exception:
        return {}


def _state_pairs(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame(columns=["sector_id", "trade_date"])
    out = states[["sector_code", "trade_date"]].drop_duplicates().copy()
    out.rename(columns={"sector_code": "sector_id"}, inplace=True)
    out["sector_id"] = out["sector_id"].astype(str)
    out["trade_date"] = pd.to_datetime(out["trade_date"])
    return out


def _trained_sectors_at_checkpoint(features: pd.DataFrame, train_date: pd.Timestamp, min_sequence_length: int, train_window_days: int | None) -> set[str]:
    history = features[features["trade_date"] <= pd.Timestamp(train_date)].copy()
    if train_window_days:
        train_dates = pd.Series(history["trade_date"].drop_duplicates().sort_values()).tail(int(train_window_days))
        history = history[history["trade_date"].isin(set(train_dates))]
    trained: set[str] = set()
    for sector_id, group in history.groupby("sector_id", sort=False):
        clean = group.dropna(subset=HSMM_FEATURE_COLUMNS)
        if len(clean) >= min_sequence_length:
            trained.add(str(sector_id))
    return trained


def coverage_v2_reports(
    run: pd.DataFrame,
    states: pd.DataFrame,
    checkpoints: pd.DataFrame,
    ohlcv_all: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    """Build raw, feature-eligible, and model-decodable coverage reports."""
    if run.empty or ohlcv_all.empty:
        empty = pd.DataFrame()
        return {
            "coverage_summary": pd.DataFrame([{"coverage_passed": False, "status": "empty"}]),
            "coverage_raw_ohlcv": empty,
            "coverage_feature_eligible": empty,
            "coverage_model_decodable": empty,
            "coverage_missing_reason": empty,
        }
    run_row = run.iloc[0]
    config = _run_config(run)
    run_id = str(run_row["run_id"])
    start = pd.to_datetime(run_row.get("start_date"))
    end = pd.to_datetime(run_row.get("end_date"))
    min_sequence_length = int(config.get("min_sequence_length") or 30)
    train_window_days = config.get("train_window_days")
    train_window_days = int(train_window_days) if train_window_days else None
    feature_scope_id = str(run_row.get("feature_scope_id") or config.get("feature_scope_id") or "all")
    feature_version = str(run_row.get("feature_version") or config.get("feature_version") or "v1")

    ohlcv = ohlcv_all.copy()
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    ohlcv["sector_id"] = ohlcv["sector_id"].astype(str)
    ohlcv_run = ohlcv[(ohlcv["trade_date"] >= start) & (ohlcv["trade_date"] <= end)].copy()
    raw_dates = pd.Series(ohlcv_run["trade_date"].drop_duplicates().sort_values())
    raw_sectors = pd.Series(ohlcv_run["sector_id"].drop_duplicates().sort_values())
    raw_dense_rows = int(len(raw_dates) * len(raw_sectors))
    raw_per_sector = ohlcv_run.groupby("sector_id")["trade_date"].nunique() if not ohlcv_run.empty else pd.Series(dtype=float)
    raw_df = pd.DataFrame({"sector_id": raw_sectors})
    if not raw_df.empty:
        raw_df["raw_trade_day_count"] = raw_df["sector_id"].map(raw_per_sector).fillna(0).astype(int)
        raw_df["raw_start_date"] = raw_df["sector_id"].map(ohlcv_run.groupby("sector_id")["trade_date"].min()).dt.date
        raw_df["raw_end_date"] = raw_df["sector_id"].map(ohlcv_run.groupby("sector_id")["trade_date"].max()).dt.date
        raw_df["raw_expected_trade_day_count"] = int(len(raw_dates))
        raw_df["raw_row_coverage_ratio"] = raw_df["raw_trade_day_count"] / max(len(raw_dates), 1)

    features = build_hsmm_features(
        ohlcv,
        feature_version=feature_version,
        feature_scope_id=feature_scope_id,
        feature_scope_type=str(config.get("feature_scope_type") or "all"),
    )
    if not features.empty:
        features["trade_date"] = pd.to_datetime(features["trade_date"])
        features["sector_id"] = features["sector_id"].astype(str)
    clean_all = features.dropna(subset=HSMM_FEATURE_COLUMNS).copy() if not features.empty else pd.DataFrame()
    if not clean_all.empty:
        clean_all = clean_all.sort_values(["sector_id", "trade_date"])
        clean_all["clean_obs_count_to_date"] = clean_all.groupby("sector_id").cumcount() + 1
    clean_run = clean_all[(clean_all["trade_date"] >= start) & (clean_all["trade_date"] <= end)].copy() if not clean_all.empty else pd.DataFrame()
    eligible_sectors = set()
    if not clean_all.empty:
        max_clean = clean_all[clean_all["trade_date"] <= end].groupby("sector_id")["clean_obs_count_to_date"].max()
        eligible_sectors = set(max_clean[max_clean >= min_sequence_length].index.astype(str))
    feature_rows: list[dict[str, object]] = []
    for sector_id in raw_sectors.astype(str).tolist():
        raw_count = int(raw_per_sector.get(sector_id, 0))
        clean_count = int(len(clean_run[clean_run["sector_id"].eq(sector_id)])) if not clean_run.empty else 0
        eligible = sector_id in eligible_sectors
        reason = None
        if not eligible:
            reason = "insufficient_history" if raw_count < min_sequence_length or clean_count < min_sequence_length else "feature_nan_or_inf"
        feature_rows.append(
            {
                "sector_id": sector_id,
                "raw_trade_day_count": raw_count,
                "clean_feature_row_count": clean_count,
                "min_sequence_length": min_sequence_length,
                "feature_eligible": bool(eligible),
                "missing_reason": reason,
            }
        )
    feature_df = pd.DataFrame(feature_rows)

    state_pairs = _state_pairs(states)
    expected_pairs: list[dict[str, object]] = []
    missing_rows: list[dict[str, object]] = []
    if not checkpoints.empty and not clean_all.empty:
        ckpts = checkpoints.sort_values("train_date").copy()
        ckpts["train_date"] = pd.to_datetime(ckpts["train_date"])
        snapshot_dates = pd.Series(clean_run["trade_date"].drop_duplicates().sort_values())
        checkpoint_train_sets = {
            pd.Timestamp(row["train_date"]): _trained_sectors_at_checkpoint(clean_all, pd.Timestamp(row["train_date"]), min_sequence_length, train_window_days)
            for _, row in ckpts.iterrows()
        }
        clean_pair_set = set(zip(clean_run["sector_id"].astype(str), pd.to_datetime(clean_run["trade_date"]).dt.date, strict=False))
        state_pair_set = set(zip(state_pairs["sector_id"].astype(str), pd.to_datetime(state_pairs["trade_date"]).dt.date, strict=False))
        ckpt_dates = sorted(checkpoint_train_sets)
        for snapshot_date in snapshot_dates:
            current_ckpts = [date for date in ckpt_dates if date <= pd.Timestamp(snapshot_date)]
            if not current_ckpts:
                continue
            checkpoint_date = current_ckpts[-1]
            trained = checkpoint_train_sets[checkpoint_date]
            for sector_id in trained:
                key = (sector_id, pd.Timestamp(snapshot_date).date())
                if key not in clean_pair_set:
                    continue
                present = key in state_pair_set
                expected_pairs.append(
                    {
                        "run_id": run_id,
                        "sector_id": sector_id,
                        "trade_date": pd.Timestamp(snapshot_date).date(),
                        "checkpoint_train_date": checkpoint_date.date(),
                        "expected_decodable": True,
                        "state_present": present,
                    }
                )
                if not present:
                    missing_rows.append(
                        {
                            "run_id": run_id,
                            "sector_id": sector_id,
                            "trade_date": pd.Timestamp(snapshot_date).date(),
                            "coverage_layer": "model_decodable",
                            "missing_reason": "decode_failed",
                            "details": f"checkpoint_train_date={checkpoint_date.date()}",
                        }
                    )

    for _, row in feature_df.iterrows():
        if not bool(row["feature_eligible"]):
            missing_rows.append(
                {
                    "run_id": run_id,
                    "sector_id": row["sector_id"],
                    "trade_date": None,
                    "coverage_layer": "feature_eligible",
                    "missing_reason": row["missing_reason"],
                    "details": f"raw_days={row['raw_trade_day_count']}, clean_rows={row['clean_feature_row_count']}",
                }
            )

    model_df = pd.DataFrame(expected_pairs)
    missing_df = pd.DataFrame(missing_rows)
    model_expected_rows = int(len(model_df))
    model_actual_rows = int(model_df["state_present"].sum()) if not model_df.empty else 0
    model_ratio = float(model_actual_rows / model_expected_rows) if model_expected_rows else np.nan
    eligible_sector_count = int(feature_df["feature_eligible"].sum()) if not feature_df.empty else 0
    state_sector_count = int(states["sector_code"].nunique()) if not states.empty else 0
    eligible_ratio = float(min(state_sector_count, eligible_sector_count) / eligible_sector_count) if eligible_sector_count else np.nan
    raw_actual_rows = int(len(ohlcv_run.drop_duplicates(["sector_id", "trade_date"])))
    raw_ratio = float(raw_actual_rows / raw_dense_rows) if raw_dense_rows else np.nan
    unresolved_missing = missing_df[~missing_df["missing_reason"].isin(["insufficient_history", "feature_nan_or_inf"])] if not missing_df.empty else pd.DataFrame()
    coverage_passed = bool((pd.isna(model_ratio) or model_ratio >= 0.995) and (pd.isna(eligible_ratio) or eligible_ratio >= 0.995) and (unresolved_missing.empty or model_ratio >= 0.995))
    summary = pd.DataFrame(
        [
            {
                "coverage_layer": "raw_ohlcv_universe",
                "expected_sector_count": int(len(raw_sectors)),
                "actual_sector_count": int(len(raw_sectors)),
                "expected_row_count": raw_dense_rows,
                "actual_row_count": raw_actual_rows,
                "coverage_ratio": raw_ratio,
                "coverage_passed": True,
                "notes": "informational_raw_ohlcv_density",
            },
            {
                "coverage_layer": "feature_eligible_universe",
                "expected_sector_count": int(len(raw_sectors)),
                "actual_sector_count": eligible_sector_count,
                "expected_row_count": int(len(raw_sectors)),
                "actual_row_count": eligible_sector_count,
                "coverage_ratio": float(eligible_sector_count / len(raw_sectors)) if len(raw_sectors) else np.nan,
                "coverage_passed": True,
                "notes": "raw sectors can be excluded with insufficient_history or feature_nan_or_inf",
            },
            {
                "coverage_layer": "model_decodable_universe",
                "expected_sector_count": eligible_sector_count,
                "actual_sector_count": state_sector_count,
                "expected_row_count": model_expected_rows,
                "actual_row_count": model_actual_rows,
                "coverage_ratio": model_ratio,
                "coverage_passed": bool(pd.isna(model_ratio) or model_ratio >= 0.995),
                "notes": "verdict layer",
            },
            {
                "coverage_layer": "verdict_coverage",
                "expected_sector_count": eligible_sector_count,
                "actual_sector_count": state_sector_count,
                "expected_row_count": model_expected_rows,
                "actual_row_count": model_actual_rows,
                "coverage_ratio": model_ratio,
                "coverage_passed": coverage_passed,
                "notes": "uses feature/model coverage; raw new sectors alone do not fail verdict",
            },
        ]
    )
    return {
        "coverage_summary": summary,
        "coverage_raw_ohlcv": raw_df,
        "coverage_feature_eligible": feature_df,
        "coverage_model_decodable": model_df,
        "coverage_missing_reason": missing_df,
    }


def state_current_profile(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    numeric = [
        "model_state_age_days",
        "label_state_age_days",
        "display_state_age_days",
        "duration_percentile",
        "expected_remaining_days",
        "raw_p_exit_1d",
        "raw_p_exit_3d",
        "raw_p_exit_5d",
        "raw_p_exit_10d",
        "raw_p_exit_20d",
        "next_state_probability",
    ]
    rows = []
    for label, group in states.groupby("state_label"):
        row: dict[str, object] = {"state_label": label, "sample_count": int(len(group)), "sector_count": int(group["sector_code"].nunique())}
        for col in numeric:
            if col in group.columns:
                row[f"mean_{col}"] = float(pd.to_numeric(group[col], errors="coerce").mean())
        rows.append(row)
    return pd.DataFrame(rows).sort_values("state_label")


def state_duration_profile(episodes: pd.DataFrame) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    rows = []
    for label, group in episodes.groupby("state_label"):
        left = group["is_left_censored"].fillna(False).astype(bool) if "is_left_censored" in group.columns else pd.Series(False, index=group.index)
        right = group["is_right_censored"].fillna(False).astype(bool) if "is_right_censored" in group.columns else pd.Series(False, index=group.index)
        uncensored = group[~left & ~right]
        duration = pd.to_numeric(uncensored["duration_days"], errors="coerce").dropna()
        rows.append(
            {
                "state_label": label,
                "episode_count_total": int(len(group)),
                "episode_count": int(len(duration)),
                "duration_profile_excludes_censored": True,
                "left_censored_count": int(left.sum()),
                "right_censored_count": int(right.sum()),
                "censored_ratio": float((left | right).mean()) if len(group) else np.nan,
                "mean_duration_days": float(duration.mean()) if not duration.empty else np.nan,
                "median_duration_days": float(duration.median()) if not duration.empty else np.nan,
                "p10_duration_days": float(duration.quantile(0.10)) if not duration.empty else np.nan,
                "p90_duration_days": float(duration.quantile(0.90)) if not duration.empty else np.nan,
            }
        )
    return pd.DataFrame(rows).sort_values("state_label")


def censored_episode_profile(episodes: pd.DataFrame) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for label, group in episodes.groupby("state_label"):
        left = group["is_left_censored"].fillna(False).astype(bool) if "is_left_censored" in group.columns else pd.Series(False, index=group.index)
        right = group["is_right_censored"].fillna(False).astype(bool) if "is_right_censored" in group.columns else pd.Series(False, index=group.index)
        rows.append(
            {
                "state_label": label,
                "episode_count": int(len(group)),
                "left_censored_count": int(left.sum()),
                "right_censored_count": int(right.sum()),
                "both_sides_censored_count": int((left & right).sum()),
                "censored_count": int((left | right).sum()),
                "censored_ratio": float((left | right).mean()) if len(group) else np.nan,
            }
        )
    rows.append(
        {
            "state_label": "__ALL__",
            "episode_count": int(len(episodes)),
            "left_censored_count": int(episodes.get("is_left_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool).sum()),
            "right_censored_count": int(episodes.get("is_right_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool).sum()),
            "both_sides_censored_count": int(
                (
                    episodes.get("is_left_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                    & episodes.get("is_right_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                ).sum()
            ),
            "censored_count": int(
                (
                    episodes.get("is_left_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                    | episodes.get("is_right_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                ).sum()
            ),
            "censored_ratio": float(
                (
                    episodes.get("is_left_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                    | episodes.get("is_right_censored", pd.Series(False, index=episodes.index)).fillna(False).astype(bool)
                ).mean()
            ) if len(episodes) else np.nan,
        }
    )
    return pd.DataFrame(rows)


def _actual_exit_within(group: pd.DataFrame, idx: int, horizon: int) -> bool | None:
    current_label = str(group.loc[idx, "state_label"])
    future = group.iloc[idx + 1 : idx + 1 + horizon]
    if len(future) < horizon:
        return None
    return bool(future["state_label"].astype(str).ne(current_label).any())


def exit_probability_calibration(states: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    work = states.sort_values(["sector_code", "trade_date"]).reset_index(drop=True)
    for horizon in horizons:
        p_col = f"raw_p_exit_{horizon}d" if f"raw_p_exit_{horizon}d" in work.columns else f"p_exit_{horizon}d"
        if p_col not in work.columns:
            continue
        samples: list[dict[str, object]] = []
        for _, group in work.groupby("sector_code", sort=False):
            group = group.reset_index(drop=True)
            for idx in range(len(group)):
                realized = _actual_exit_within(group, idx, horizon)
                if realized is None:
                    continue
                samples.append({"state_label": group.loc[idx, "state_label"], "p": float(group.loc[idx, p_col]), "realized": realized})
        sample_df = pd.DataFrame(samples)
        if sample_df.empty:
            continue
        sample_df["prob_bucket"] = pd.cut(sample_df["p"], bins=[-0.001, 0.2, 0.4, 0.6, 0.8, 1.001], labels=["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"])
        for (label, bucket), group in sample_df.groupby(["state_label", "prob_bucket"], observed=False):
            if group.empty:
                continue
            predicted = float(group["p"].mean())
            realized_rate = float(group["realized"].mean())
            rows.append(
                {
                    "probability_type": "raw",
                    "prob_type": "raw",
                    "state_label": label,
                    "horizon_days": horizon,
                    "prob_bucket": bucket,
                    "sample_count": int(len(group)),
                    "mean_predicted_exit_prob": predicted,
                    "realized_exit_rate": realized_rate,
                    "brier_score": float(((group["realized"].astype(float) - group["p"]) ** 2).mean()),
                    "calibration_error": realized_rate - predicted,
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out["bucket"] = out["prob_bucket"]
        out["mean_predicted_exit_probability"] = out["mean_predicted_exit_prob"]
        out["actual_exit_rate"] = out["realized_exit_rate"]
        out["abs_error"] = out["calibration_error"].abs()
        out["monotonic_rank"] = out.groupby(["probability_type", "state_label", "horizon_days"])["mean_predicted_exit_prob"].rank(method="dense")
    return out


def next_state_prediction(states: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    if states.empty or episodes.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    actual_rows: list[dict[str, object]] = []
    state_index = states.copy()
    state_index["trade_date"] = pd.to_datetime(state_index["trade_date"])
    for _, episode in episodes.iterrows():
        is_open = bool(episode.get("is_open_episode", episode.get("is_right_censored", False)))
        if is_open or pd.isna(episode.get("next_state_label")):
            continue
        match = state_index[
            state_index["sector_code"].astype(str).eq(str(episode["sector_code"]))
            & state_index["trade_date"].eq(pd.Timestamp(episode["start_date"]))
        ]
        if match.empty:
            continue
        pred_row = match.iloc[0]
        actual_rows.append(
            {
                "state_label": str(episode["state_label"]),
                "predicted": str(pred_row["most_likely_next_state_label"]),
                "prob": float(pred_row["next_state_probability"]),
                "actual": str(episode["next_state_label"]),
            }
        )
    actual = pd.DataFrame(actual_rows)
    if actual.empty:
        return pd.DataFrame()
    for label, group in actual.groupby("state_label"):
        base_label = group["actual"].mode().iloc[0]
        correct = (group["predicted"] == group["actual"]).astype(float)
        prob = pd.to_numeric(group["prob"], errors="coerce").fillna(0.0).clip(0.0, 1.0)
        rows.append(
            {
                "state_label": label,
                "sample_count": int(len(group)),
                "accuracy": float(correct.mean()),
                "top1_next_state_accuracy": float(correct.mean()),
                "baseline_accuracy": float((group["actual"] == base_label).mean()),
                "brier_score": float(((correct - prob) ** 2).mean()),
                "log_loss_if_available": np.nan,
            }
        )
    return pd.DataFrame(rows)


def _forward_return_frame(ohlcv: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame()
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    close_wide = work.pivot_table(index="trade_date", columns="sector_id", values="close").sort_index()
    daily_ret = close_wide.pct_change(fill_method=None)
    ew_daily = daily_ret.mean(axis=1, skipna=True)
    frames: list[pd.DataFrame] = []
    for sector_id, group in work.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
        g = group[["sector_id", "trade_date", "close"]].copy()
        close = pd.to_numeric(g["close"], errors="coerce")
        for horizon in horizons:
            ret = close.shift(-horizon) / close - 1
            bench_value = pd.Series(1.0, index=ew_daily.index)
            for step in range(1, horizon + 1):
                bench_value = bench_value * (1 + ew_daily.shift(-step))
            bench = bench_value - 1
            future_closes = [close.shift(-step) / close - 1 for step in range(1, horizon + 1)]
            mae = pd.concat(future_closes, axis=1).min(axis=1)
            g[f"fwd_ret_{horizon}d"] = ret
            g[f"fwd_excess_ret_{horizon}d"] = ret - bench.reindex(g["trade_date"]).to_numpy()
            g[f"fwd_mae_{horizon}d"] = mae
        frames.append(g.drop(columns=["close"]))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def state_phase_profile(states: pd.DataFrame, ohlcv: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    fwd = _forward_return_frame(ohlcv, horizons)
    work = states.merge(fwd, left_on=["sector_code", "trade_date"], right_on=["sector_id", "trade_date"], how="left")
    rows: list[dict[str, object]] = []
    for (label, phase), group in work.groupby(["state_label", "state_phase"]):
        row: dict[str, object] = {
            "state_label": label,
            "state_phase": phase,
            "sample_count": int(len(group)),
            "mean_display_state_age_days": float(pd.to_numeric(group.get("display_state_age_days", group.get("state_age_days")), errors="coerce").mean()),
            "mean_model_state_age_days": float(pd.to_numeric(group.get("model_state_age_days", group.get("state_age_days")), errors="coerce").mean()),
            "mean_duration_percentile": float(pd.to_numeric(group["duration_percentile"], errors="coerce").mean()),
        }
        for horizon in horizons:
            for prefix in ["fwd_ret", "fwd_excess_ret"]:
                col = f"{prefix}_{horizon}d"
                if col in group.columns:
                    row[col] = float(pd.to_numeric(group[col], errors="coerce").mean())
            mae_col = f"fwd_mae_{horizon}d"
            if mae_col in group.columns:
                row[mae_col] = float(pd.to_numeric(group[mae_col], errors="coerce").mean())
            p_col = f"raw_p_exit_{horizon}d" if f"raw_p_exit_{horizon}d" in group.columns else f"p_exit_{horizon}d"
            if p_col in group.columns:
                row[f"mean_raw_p_exit_{horizon}d"] = float(pd.to_numeric(group[p_col], errors="coerce").mean())
        rows.append(row)
    return pd.DataFrame(rows)


def stress_lifecycle_profile(states: pd.DataFrame, ohlcv: pd.DataFrame, horizons: tuple[int, ...], episodes: pd.DataFrame | None = None) -> pd.DataFrame:
    pressure_labels = ("Stress", "WeakVolatile", "RiskOff", "HighVolPullback", "Pullback")
    if states.empty:
        return pd.DataFrame()
    pressure = states[states["state_label"].astype(str).str.contains("|".join(pressure_labels), case=False, na=False)].copy()
    if pressure.empty:
        return pd.DataFrame()
    fwd = _forward_return_frame(ohlcv, horizons)
    work = pressure.merge(fwd, left_on=["sector_code", "trade_date"], right_on=["sector_id", "trade_date"], how="left")
    age_col = "display_state_age_days" if "display_state_age_days" in work.columns else "state_age_days"
    work["age_bucket"] = pd.cut(pd.to_numeric(work[age_col], errors="coerce"), bins=[0, 3, 7, 14, np.inf], labels=["1-3", "4-7", "8-14", "15+"])
    work["realized_next_state_label"] = None
    if episodes is not None and not episodes.empty:
        ep = episodes.copy()
        ep["start_date"] = pd.to_datetime(ep["start_date"])
        ep["end_date"] = pd.to_datetime(ep["end_date"])
        work["trade_date"] = pd.to_datetime(work["trade_date"])
        for sector_code, group in ep.groupby("sector_code", sort=False):
            sector_mask = work["sector_code"].astype(str).eq(str(sector_code))
            if not sector_mask.any():
                continue
            for _, episode in group.iterrows():
                mask = (
                    sector_mask
                    & (work["trade_date"] >= pd.Timestamp(episode["start_date"]))
                    & (work["trade_date"] <= pd.Timestamp(episode["end_date"]))
                )
                if mask.any():
                    work.loc[mask, "realized_next_state_label"] = None if pd.isna(episode.get("next_state_label")) else str(episode.get("next_state_label"))
    exit_marks: dict[tuple[str, pd.Timestamp, int], float] = {}
    ordered = states.sort_values(["sector_code", "trade_date"]).copy()
    for _, group in ordered.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        for idx in range(len(group)):
            for horizon in horizons:
                value = _actual_exit_within(group, idx, horizon)
                if value is not None:
                    exit_marks[(str(group.loc[idx, "sector_code"]), pd.Timestamp(group.loc[idx, "trade_date"]), horizon)] = float(value)
    rows: list[dict[str, object]] = []
    for (label, bucket), group in work.groupby(["state_label", "age_bucket"], observed=True):
        row: dict[str, object] = {"state_label": label, "age_bucket": bucket, "sample_count": int(len(group))}
        for horizon in horizons:
            for col in [f"fwd_excess_ret_{horizon}d", f"fwd_mae_{horizon}d"]:
                if col in group.columns:
                    row[col] = float(pd.to_numeric(group[col], errors="coerce").mean())
        for horizon in horizons:
            values = [
                exit_marks.get((str(r["sector_code"]), pd.Timestamp(r["trade_date"]), horizon))
                for _, r in group.iterrows()
            ]
            values = [v for v in values if v is not None]
            row[f"actual_exit_rate_{horizon}d"] = float(np.mean(values)) if values else np.nan
        predicted_dist = group["most_likely_next_state_label"].dropna().value_counts(normalize=True).to_dict() if "most_likely_next_state_label" in group.columns else {}
        realized_dist = group["realized_next_state_label"].dropna().value_counts(normalize=True).to_dict() if "realized_next_state_label" in group.columns else {}
        row["predicted_next_state_distribution"] = json.dumps(predicted_dist, ensure_ascii=False)
        row["realized_next_state_distribution"] = json.dumps(realized_dist, ensure_ascii=False)
        row["next_state_distribution"] = row["predicted_next_state_distribution"]
        row["insufficient_sample"] = bool(len(group) < 20)
        rows.append(row)
    return pd.DataFrame(rows)


def churn_profile(episodes: pd.DataFrame, model_family: str = "hsmm", run_id: str | None = None) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    if {"is_left_censored", "is_right_censored"}.issubset(episodes.columns):
        left = episodes["is_left_censored"].fillna(False).astype(bool)
        right = episodes["is_right_censored"].fillna(False).astype(bool)
        episodes = episodes[~left & ~right].copy()
        if episodes.empty:
            return pd.DataFrame()
    duration_col = "duration_trading_days" if "duration_trading_days" in episodes.columns else "duration_days"
    rows: list[dict[str, object]] = []
    for label, group in episodes.groupby("state_label"):
        duration = pd.to_numeric(group[duration_col], errors="coerce").dropna()
        if duration.empty:
            continue
        total_duration = float(duration.sum())
        state_change_rate = float(max(len(duration) - 1, 0) / total_duration) if total_duration > 0 else np.nan
        rows.append(
            {
                "model_type": model_family,
                "run_id": run_id,
                "state_label": label,
                "episode_count": int(len(duration)),
                "mean_duration": float(duration.mean()),
                "median_duration": float(duration.median()),
                "mean_duration_trading_days": float(duration.mean()),
                "median_duration_trading_days": float(duration.median()),
                "p10_duration": float(duration.quantile(0.10)),
                "p90_duration": float(duration.quantile(0.90)),
                "state_change_rate": state_change_rate,
                "one_day_episode_ratio": float((duration <= 1).mean()),
                "three_day_or_less_episode_ratio": float((duration <= 3).mean()),
            }
        )
    return pd.DataFrame(rows)


def hmm_vs_hsmm_lifecycle_comparison(storage: DuckDBStorage, hsmm_run_id: str, hsmm_episodes: pd.DataFrame, run: pd.DataFrame, hmm_cache_key: str | None = None) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    hsmm = churn_profile(hsmm_episodes, "hsmm", hsmm_run_id)
    if not hsmm.empty:
        hsmm["comparison_status"] = "hsmm_only"
        rows.append(hsmm)
    if not hmm_cache_key:
        status = pd.DataFrame(
            [
                {
                    "model_type": "hmm",
                    "run_id": None,
                    "state_label": None,
                    "comparison_status": "skipped_no_matched_hmm_cache",
                    "details": "Pass --hmm-cache-key to enable matched HMM comparison.",
                }
            ]
        )
        return pd.concat([*rows, status], ignore_index=True) if rows else status
    run_row = run.iloc[0] if not run.empty else {}
    start_date = run_row.get("start_date") if hasattr(run_row, "get") else None
    end_date = run_row.get("end_date") if hasattr(run_row, "get") else None
    cache_meta = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [hmm_cache_key])
    if cache_meta.empty:
        status = pd.DataFrame(
            [
                {
                    "model_type": "hmm",
                    "run_id": hmm_cache_key,
                    "state_label": None,
                    "comparison_status": "skipped_missing_hmm_cache",
                    "details": "cache_key not found in walk_forward_cache_runs",
                }
            ]
        )
        return pd.concat([*rows, status], ignore_index=True) if rows else status
    mismatches: list[str] = []
    meta = cache_meta.iloc[0]
    for col in ["universe_id", "feature_scope_id"]:
        hsmm_value = run_row.get(col) if hasattr(run_row, "get") else None
        hmm_value = meta.get(col)
        if pd.notna(hsmm_value) and pd.notna(hmm_value) and str(hsmm_value) != str(hmm_value):
            mismatches.append(col)
    for hsmm_col, hmm_col in [("start_date", "start_date"), ("end_date", "end_date"), ("train_window_days", "train_window_days")]:
        hsmm_value = run_row.get(hsmm_col) if hasattr(run_row, "get") else None
        hmm_value = meta.get(hmm_col)
        if pd.notna(hsmm_value) and pd.notna(hmm_value) and str(pd.Timestamp(hsmm_value).date() if "date" in hsmm_col else hsmm_value) != str(pd.Timestamp(hmm_value).date() if "date" in hmm_col else hmm_value):
            mismatches.append(hsmm_col)
    if mismatches:
        status = pd.DataFrame(
            [
                {
                    "model_type": "hmm",
                    "run_id": hmm_cache_key,
                    "state_label": None,
                    "comparison_status": "skipped_mismatched_hmm_cache",
                    "details": ",".join(sorted(set(mismatches))),
                }
            ]
        )
        return pd.concat([*rows, status], ignore_index=True) if rows else status
    hmm_states = storage.read_df(
        """
        SELECT cache_key AS run_id, sector_id AS sector_code, trade_date, state_label
        FROM walk_forward_state_cache
        WHERE cache_key = ? AND trade_date BETWEEN ? AND ?
        ORDER BY sector_id, trade_date
        """,
        [hmm_cache_key, start_date, end_date],
    ) if pd.notna(start_date) and pd.notna(end_date) else pd.DataFrame()
    hsmm_sector_count = hsmm_episodes["sector_code"].nunique() if not hsmm_episodes.empty else 0
    hmm_sector_count = hmm_states["sector_code"].nunique() if not hmm_states.empty else 0
    if hmm_states.empty or (hsmm_sector_count and hmm_sector_count < hsmm_sector_count * 0.995):
        status = pd.DataFrame(
            [
                {
                    "model_type": "hmm",
                    "run_id": hmm_cache_key,
                    "state_label": None,
                    "comparison_status": "skipped_incomplete_hmm_cache",
                    "details": f"hmm_sector_count={hmm_sector_count}, hsmm_sector_count={hsmm_sector_count}",
                }
            ]
        )
        return pd.concat([*rows, status], ignore_index=True) if rows else status
    if not hmm_states.empty:
        episodes: list[dict[str, object]] = []
        hmm_states["trade_date"] = pd.to_datetime(hmm_states["trade_date"])
        for sector_code, group in hmm_states.groupby("sector_code", sort=False):
            group = group.sort_values("trade_date").reset_index(drop=True)
            start_idx = 0
            for idx in range(1, len(group) + 1):
                if idx == len(group) or str(group.loc[idx, "state_label"]) != str(group.loc[idx - 1, "state_label"]):
                    segment = group.iloc[start_idx:idx]
                    episodes.append(
                        {
                            "run_id": segment["run_id"].iloc[0],
                            "sector_code": sector_code,
                            "state_label": segment["state_label"].iloc[0],
                            "duration_trading_days": int(len(segment)),
                            "duration_days": int(len(segment)),
                        }
                    )
                    start_idx = idx
        hmm_churn = churn_profile(pd.DataFrame(episodes), "hmm", None)
        if not hmm_churn.empty:
            hmm_churn["run_id"] = hmm_cache_key
            hmm_churn["comparison_status"] = "matched"
            rows.append(hmm_churn)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def state_age_stability(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty or "checkpoint_id" not in states.columns:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    sector_rows: list[dict[str, object]] = []
    total_same_label_pairs = 0
    total_same_label_age_resets = 0
    total_checkpoint_pairs = 0
    total_checkpoint_age_resets = 0
    reset_sectors: set[str] = set()
    max_age_drop = 0.0
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        checkpoint_change = group["checkpoint_id"].astype(str).ne(group["checkpoint_id"].astype(str).shift(1))
        label_same = group["state_label"].astype(str).eq(group["state_label"].astype(str).shift(1))
        age_col = "label_state_age_days" if "label_state_age_days" in group.columns else "state_age_days"
        age = pd.to_numeric(group[age_col], errors="coerce")
        age_drop = (age.shift(1) - age).clip(lower=0)
        same_label_age_reset = label_same & (age < age.shift(1))
        checkpoint_boundary_reset = checkpoint_change & same_label_age_reset
        same_pairs = int(label_same.iloc[1:].sum()) if len(group) > 1 else 0
        checkpoint_pairs = int((checkpoint_change & label_same).iloc[1:].sum()) if len(group) > 1 else 0
        same_resets = int(same_label_age_reset.iloc[1:].sum()) if len(group) > 1 else 0
        checkpoint_resets = int(checkpoint_boundary_reset.iloc[1:].sum()) if len(group) > 1 else 0
        if same_resets:
            reset_sectors.add(str(sector_code))
        total_same_label_pairs += same_pairs
        total_same_label_age_resets += same_resets
        total_checkpoint_pairs += checkpoint_pairs
        total_checkpoint_age_resets += checkpoint_resets
        max_age_drop = max(max_age_drop, float(age_drop.max()) if age_drop.notna().any() else 0.0)
        sector_rows.append(
            {
                "row_type": "sector",
                "sector_code": sector_code,
                "checkpoint_change_count": int(checkpoint_change.iloc[1:].sum()) if len(group) > 1 else 0,
                "same_label_pair_count": same_pairs,
                "same_label_age_reset_count": same_resets,
                "checkpoint_boundary_age_reset_count": checkpoint_resets,
                "max_state_age_days": float(age.max()) if age.notna().any() else np.nan,
            }
        )
    same_rate = total_same_label_age_resets / total_same_label_pairs if total_same_label_pairs else 0.0
    checkpoint_rate = total_checkpoint_age_resets / total_checkpoint_pairs if total_checkpoint_pairs else 0.0
    aggregate = {
        "row_type": "aggregate",
        "sector_code": "__ALL__",
        "sector_count": int(work["sector_code"].nunique()),
        "same_label_pair_count": total_same_label_pairs,
        "same_label_age_reset_count": total_same_label_age_resets,
        "same_label_age_reset_sector_count": len(reset_sectors),
        "same_label_age_reset_rate": same_rate,
        "checkpoint_boundary_pair_count": total_checkpoint_pairs,
        "checkpoint_boundary_age_reset_count": total_checkpoint_age_resets,
        "checkpoint_boundary_age_reset_rate": checkpoint_rate,
        "max_age_drop_same_label": max_age_drop,
        "passed": bool(same_rate <= 0.05 and checkpoint_rate <= 0.05),
    }
    return pd.DataFrame([aggregate, *sector_rows])


def _summary_conclusion(
    audit: pd.DataFrame,
    coverage: pd.DataFrame,
    calibration: pd.DataFrame,
    prediction: pd.DataFrame,
    churn: pd.DataFrame,
    age_stability: pd.DataFrame,
) -> tuple[str, str]:
    if audit.empty:
        return "InvalidDueToCausalityFailure", "缺少因果审计结果。"
    severity = audit["severity"] if "severity" in audit.columns else pd.Series(["error"] * len(audit))
    failed = set(audit.loc[(~audit["passed"]) & severity.ne("warning"), "check"].astype(str))
    if {"train_end_date <= trade_date", "max_observation_date_used <= trade_date", "state_source == causal_hsmm"} & failed:
        return "InvalidDueToCausalityFailure", "HSMM 因果性审计失败。"
    if "snapshot_frequency == daily" in failed:
        return "InvalidDueToSparseSnapshots", "该 run 不是 daily snapshot，不能按逐交易日生命周期解释。"
    if failed:
        return "InvalidDueToCausalityFailure", "审计失败：" + ", ".join(sorted(failed))
    if coverage.empty:
        return "InvalidDueToCoverageFailure", "缺少 coverage audit。"
    if "coverage_layer" in coverage.columns and coverage["coverage_layer"].astype(str).eq("verdict_coverage").any():
        coverage_row = coverage[coverage["coverage_layer"].astype(str).eq("verdict_coverage")].iloc[0]
    else:
        coverage_row = coverage.iloc[0]
    if not bool(coverage_row.get("coverage_passed", False)):
        return "InvalidDueToCoverageFailure", "状态覆盖与 run 的真实输入范围不一致。"
    stored_rows = int(coverage_row.get("actual_row_count") or coverage_row.get("stored_rows") or 0)
    sector_count = int(coverage_row.get("actual_sector_count") or 0)
    trade_day_count = int(coverage_row.get("actual_trade_day_count") or 20)
    if stored_rows < 100 or sector_count < 3 or trade_day_count < 20:
        return "InvalidDueToInsufficientSample", "样本量不足，生命周期诊断不稳定。"
    if not age_stability.empty:
        aggregate = age_stability[age_stability["row_type"].astype(str).eq("aggregate")] if "row_type" in age_stability.columns else age_stability.head(1)
        if not aggregate.empty and not bool(aggregate.iloc[0].get("passed", True)):
            return "InvalidDueToAgeInstability", "同标签状态年龄在 checkpoint 边界附近出现异常重置。"
    evidence = 0
    if not calibration.empty:
        if "probability_type" in calibration.columns and {"raw", "calibrated"}.issubset(set(calibration["probability_type"].astype(str))):
            brier_by_type = calibration.groupby("probability_type")["brier_score"].mean()
            raw_brier = float(brier_by_type.get("raw", np.nan))
            calibrated_brier = float(brier_by_type.get("calibrated", np.nan))
            if pd.notna(raw_brier) and pd.notna(calibrated_brier):
                if calibrated_brier <= raw_brier * 0.98:
                    evidence += 1
                elif calibrated_brier > raw_brier * 1.02:
                    return "InvalidDueToCalibrationFailure", f"CalibrationNotImproved: calibrated Brier {calibrated_brier:.4f} worse than raw {raw_brier:.4f}."
        monotonic_hits = 0
        checked = 0
        cal_work = calibration.copy()
        if "probability_type" in cal_work.columns and cal_work["probability_type"].astype(str).eq("calibrated").any():
            cal_work = cal_work[cal_work["probability_type"].astype(str).eq("calibrated")]
        for _, group in cal_work.groupby(["state_label", "horizon_days"]):
            if group["sample_count"].sum() < 20:
                continue
            checked += 1
            ordered = group.sort_values("mean_predicted_exit_prob")
            corr = ordered["mean_predicted_exit_prob"].corr(ordered["realized_exit_rate"], method="spearman")
            if pd.notna(corr) and corr > 0:
                monotonic_hits += 1
        if checked and monotonic_hits / checked >= 0.5:
            evidence += 1
        elif checked:
            return "InvalidDueToCalibrationFailure", "退出概率校准缺少基本单调性。"
    if not prediction.empty and (prediction["accuracy"] > prediction["baseline_accuracy"]).any():
        evidence += 1
    if not churn.empty and pd.to_numeric(churn["one_day_episode_ratio"], errors="coerce").mean() < 0.4:
        evidence += 1
    if evidence >= 3:
        return "ValidLifecycleSignal", "HSMM 生命周期输出在退出校准、下一状态预测和跳变控制上具备可解释增量。"
    if evidence >= 1:
        return "PartialLifecycleSignal", "HSMM 因果性通过，但生命周期证据仍需更多真实样本验证。"
    return "InvalidDueToNoLifecycleIncrement", "HSMM 因果性通过，但尚未观察到稳定的生命周期增量。"


def _write_csv(output: Path, name: str, df: pd.DataFrame) -> None:
    df.to_csv(output / name, index=False)


def exit_calibration_buckets(calibration: pd.DataFrame) -> pd.DataFrame:
    if calibration.empty:
        return pd.DataFrame()
    out = calibration.copy()
    out["prob_type"] = out.get("prob_type", out.get("probability_type"))
    if "actual_exit_rate" not in out.columns and "realized_exit_rate" in out.columns:
        out["actual_exit_rate"] = out["realized_exit_rate"]
    if "abs_error" not in out.columns and "calibration_error" in out.columns:
        out["abs_error"] = pd.to_numeric(out["calibration_error"], errors="coerce").abs()
    keep = [
        "horizon_days",
        "state_label",
        "prob_type",
        "bucket",
        "sample_count",
        "mean_predicted_exit_prob",
        "actual_exit_rate",
        "abs_error",
    ]
    return out[[col for col in keep if col in out.columns]]


def exit_calibration_summary(calibration: pd.DataFrame, split: pd.DataFrame) -> pd.DataFrame:
    if calibration.empty:
        return pd.DataFrame()
    work = calibration.copy()
    work["prob_type"] = work.get("prob_type", work.get("probability_type"))
    rows: list[dict[str, object]] = []
    validation_start = split.iloc[0].get("valid_start_date") if not split.empty else None
    validation_end = split.iloc[0].get("valid_end_date") if not split.empty else None
    for (horizon, label, prob_type), group in work.groupby(["horizon_days", "state_label", "prob_type"], dropna=False):
        weights = pd.to_numeric(group["sample_count"], errors="coerce").fillna(0.0)
        total = float(weights.sum())
        brier = pd.to_numeric(group["brier_score"], errors="coerce")
        err = pd.to_numeric(group["calibration_error"], errors="coerce")
        ordered = group.sort_values("mean_predicted_exit_prob")
        corr = ordered["mean_predicted_exit_prob"].corr(ordered["realized_exit_rate"], method="spearman") if len(ordered) > 1 else np.nan
        rows.append(
            {
                "horizon_days": int(horizon),
                "state_label": label,
                "prob_type": prob_type,
                "sample_count": int(total),
                "brier_score": float((brier * weights).sum() / total) if total else np.nan,
                "calibration_error": float((err.abs() * weights).sum() / total) if total else np.nan,
                "monotonic_bucket_ratio": float(corr > 0) if pd.notna(corr) else np.nan,
                "bucket_count": int(len(group)),
                "validation_start_date": validation_start,
                "validation_end_date": validation_end,
                "insufficient_validation_sample": bool(total < 50),
            }
        )
    return pd.DataFrame(rows)


def run_hsmm_diagnostics(
    db_path: str | None,
    run_id: str,
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
    output: str | Path | None = None,
    enable_exit_calibration: bool = False,
    calibration_train_ratio: float = 0.7,
    calibration_train_end: str | None = None,
    hmm_cache_key: str | None = None,
) -> dict[str, pd.DataFrame | dict[str, str]]:
    storage = DuckDBStorage(db_path) if db_path else DuckDBStorage()
    storage.init_schema()
    output_dir = Path(output or f"reports/hsmm_diagnostics/{run_id}")
    output_dir.mkdir(parents=True, exist_ok=True)

    run = _read_run(storage, run_id)
    if run.empty:
        raise ValueError(f"缺少 hsmm_model_runs 记录：{run_id}")
    states = _read_states(storage, run_id)
    episodes = _read_episodes(storage, run_id)
    checkpoints = _read_checkpoints(storage, run_id)
    performance = _read_run_performance(storage, run_id)
    run_row = run.iloc[0]
    universe_id = None if pd.isna(run_row.get("universe_id")) else str(run_row.get("universe_id"))
    include_custom = bool(run_row.get("include_custom_baskets")) if "include_custom_baskets" in run.columns and pd.notna(run_row.get("include_custom_baskets")) else True
    ohlcv_all = load_sector_like_ohlcv(storage, universe_id=universe_id, include_custom_baskets=include_custom)
    ohlcv = ohlcv_all.copy()
    if not ohlcv.empty:
        ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
        if pd.notna(run_row.get("start_date")):
            ohlcv = ohlcv[ohlcv["trade_date"] >= pd.to_datetime(run_row.get("start_date"))]
        if pd.notna(run_row.get("end_date")):
            ohlcv = ohlcv[ohlcv["trade_date"] <= pd.to_datetime(run_row.get("end_date"))]

    expected_trade_dates = pd.Series(ohlcv["trade_date"].drop_duplicates().sort_values()) if not ohlcv.empty else None
    audit = causality_audit(run, states, episodes, checkpoints, expected_trade_dates=expected_trade_dates)
    coverage = coverage_snapshot(run, states, ohlcv)
    coverage_reports = coverage_v2_reports(run, states, checkpoints, ohlcv_all)
    coverage_summary = coverage_reports["coverage_summary"]
    current_profile = state_current_profile(states)
    duration_profile = state_duration_profile(episodes)
    censored_profile = censored_episode_profile(episodes)
    exit_dataset = build_exit_calibration_dataset(states, horizons)
    calibrated_summary = pd.DataFrame()
    calibration_split = pd.DataFrame()
    calibrator_metadata: dict[str, object] = {"enabled": bool(enable_exit_calibration)}
    if enable_exit_calibration and not exit_dataset.empty:
        dates = pd.Series(pd.to_datetime(exit_dataset["trade_date"]).drop_duplicates().sort_values())
        if calibration_train_end:
            train_end = pd.to_datetime(calibration_train_end)
        else:
            split_idx = min(len(dates) - 1, max(0, int(len(dates) * calibration_train_ratio) - 1))
            train_end = pd.Timestamp(dates.iloc[split_idx])
        validation = exit_dataset[pd.to_datetime(exit_dataset["trade_date"]) > train_end].copy()
        if validation.empty:
            validation = exit_dataset.copy()
        calibrator = fit_empirical_exit_calibrator(exit_dataset, min_bucket_count=10, train_end_date=train_end)
        calibrated = apply_exit_calibrator(validation, calibrator)
        raw_summary = summarize_exit_calibration(validation, "raw_p_exit", "raw")
        calibrated_summary = summarize_exit_calibration(calibrated, "calibrated_p_exit", "calibrated")
        calibration = pd.concat([raw_summary, calibrated_summary], ignore_index=True)
        calibration_split = pd.DataFrame(
            [
                {
                    "train_start_date": dates.min().date() if len(dates) else None,
                    "train_end_date": train_end.date(),
                    "valid_start_date": pd.to_datetime(validation["trade_date"]).min().date() if not validation.empty else None,
                    "valid_end_date": pd.to_datetime(validation["trade_date"]).max().date() if not validation.empty else None,
                    "train_row_count": int((pd.to_datetime(exit_dataset["trade_date"]) <= train_end).sum()),
                    "valid_row_count": int(len(validation)),
                    "calibration_train_ratio": float(calibration_train_ratio),
                }
            ]
        )
        calibrator_metadata = {**calibrator.metadata, "enabled": True, "train_end": str(train_end.date())}
        (output_dir / "calibrator_metadata.json").write_text(calibrator.to_json(), encoding="utf-8")
    else:
        calibration = exit_probability_calibration(states, horizons)
        (output_dir / "calibrator_metadata.json").write_text(json.dumps(calibrator_metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    calibration_buckets = exit_calibration_buckets(calibration)
    calibration_summary = exit_calibration_summary(calibration, calibration_split)
    prediction = next_state_prediction(states, episodes)
    phase = state_phase_profile(states, ohlcv, horizons) if not ohlcv.empty else pd.DataFrame()
    stress = stress_lifecycle_profile(states, ohlcv, horizons, episodes) if not ohlcv.empty else pd.DataFrame()
    churn = churn_profile(episodes, "hsmm", run_id)
    lifecycle_comparison = hmm_vs_hsmm_lifecycle_comparison(storage, run_id, episodes, run, hmm_cache_key=hmm_cache_key)
    age_stability = state_age_stability(states)
    conclusion = _summary_conclusion(audit, coverage_summary, calibration, prediction, churn, age_stability)

    outputs = {
        "causal_audit": audit,
        "causality_audit": audit,
        "coverage": coverage,
        "coverage_snapshot": coverage,
        **coverage_reports,
        "state_current_profile": current_profile,
        "state_duration_profile": duration_profile,
        "censored_episode_profile": censored_profile,
        "state_phase_profile": phase,
        "hsmm_run_performance": performance,
        "exit_probability_calibration": calibration,
        "exit_probability_calibrated": calibrated_summary,
        "exit_calibration_summary": calibration_summary,
        "exit_calibration_buckets": calibration_buckets,
        "calibration_train_valid_split": calibration_split,
        "next_state_prediction": prediction,
        "stress_lifecycle_profile": stress,
        "churn_profile": churn,
        "hmm_vs_hsmm_churn": lifecycle_comparison,
        "hmm_vs_hsmm_lifecycle_comparison": lifecycle_comparison,
        "state_age_stability": age_stability,
        "state_forward_profile_abs": phase[[c for c in phase.columns if not c.startswith("fwd_excess")]] if not phase.empty else pd.DataFrame(),
        "state_forward_profile_excess": phase[[c for c in phase.columns if "state_" in c or c.startswith("fwd_excess")]] if not phase.empty else pd.DataFrame(),
    }
    for name, df in outputs.items():
        _write_csv(output_dir, f"{name}.csv", df)
    config = {
        "run_id": run_id,
        "horizons": horizons,
        "output": str(output_dir),
        "universe_id": universe_id,
        "include_custom_baskets": include_custom,
        "enable_exit_calibration": enable_exit_calibration,
        "calibration_train_ratio": calibration_train_ratio,
        "calibration_train_end": calibration_train_end,
        "hmm_cache_key": hmm_cache_key,
    }
    (output_dir / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    _write_summary(output_dir, run_id, run, outputs, conclusion)
    return {**outputs, "summary": {"conclusion": conclusion[0], "text": conclusion[1], "output": str(output_dir)}}


def _write_summary(output: Path, run_id: str, run: pd.DataFrame, outputs: dict[str, pd.DataFrame], conclusion: tuple[str, str]) -> None:
    def table(df: pd.DataFrame, max_rows: int = 12) -> str:
        if df.empty:
            return "无数据"
        return "```text\n" + df.head(max_rows).to_string(index=False) + "\n```"

    run_row = run.iloc[0].to_dict() if not run.empty else {}
    lines = [
        "# HSMM 状态生命周期诊断报告",
        "",
        "## 1. 结论",
        "",
        f"Conclusion: {conclusion[0]}",
        "",
        f"一句话结论：{conclusion[1]}",
        "",
        "说明：HSMM 当前只用于生命周期诊断，不用于交易排序或买卖信号。" if "smoke" not in str(run_id).lower() else "说明：该 run 仅为 fresh smoke 工程验收，不用于模型有效性结论。",
        "",
        "## 2. 配置",
        "",
        f"- run_id: {run_id}",
        f"- 日期范围: {run_row.get('start_date')} 至 {run_row.get('end_date')}",
        f"- universe: {run_row.get('universe_id') or '全市场'}",
        f"- n_states: {run_row.get('n_states')}",
        f"- max_duration: {run_row.get('max_duration')}",
        f"- train_window_days: {run_row.get('train_window_days')}",
        f"- train_frequency: {run_row.get('train_frequency')}",
        f"- train_every_n_trade_days: {run_row.get('train_every_n_trade_days')}",
        f"- snapshot_frequency: {run_row.get('snapshot_frequency')}",
        f"- feature_preset: hsmm_v1",
        "",
        "## 3. Snapshot Frequency Audit",
        "",
        table(outputs.get("coverage_summary", outputs["coverage"])),
        "",
        "### Raw OHLCV Coverage",
        "",
        table(outputs.get("coverage_raw_ohlcv", pd.DataFrame()), 8),
        "",
        "### Feature Eligible Coverage",
        "",
        table(outputs.get("coverage_feature_eligible", pd.DataFrame()), 8),
        "",
        "### Model Decodable Coverage",
        "",
        table(outputs.get("coverage_model_decodable", pd.DataFrame()), 8),
        "",
        "### Missing Reasons",
        "",
        table(outputs.get("coverage_missing_reason", pd.DataFrame()), 12),
        "",
        "## 4. Causal Audit",
        "",
        table(outputs["causal_audit"]),
        "",
        "## 5. Duration Calibration Conclusion",
        "",
        f"- verdict: {conclusion[0]}",
        "",
        "## 6. Exit Probability Calibration",
        "",
        table(outputs["exit_probability_calibration"]),
        "",
        "## 7. Next-State Prediction Conclusion",
        "",
        table(outputs["next_state_prediction"]),
        "",
        "## 8. Stress Lifecycle Conclusion",
        "",
        table(outputs["stress_lifecycle_profile"]),
        "",
        "## 9. 状态画像",
        "",
        table(outputs["state_current_profile"]),
        "",
        "## 10. 持续时间画像",
        "",
        table(outputs["state_duration_profile"]),
        "",
        "## 11. HMM vs HSMM Churn Comparison",
        "",
        table(outputs.get("hmm_vs_hsmm_lifecycle_comparison", outputs["churn_profile"])),
        "",
        "## 12. 收益侧辅助诊断",
        "",
        "收益只用于解释生命周期阶段，不参与 HSMM 训练。",
        "",
        "## 13. Known Limitations",
        "",
        "- HSMM 输出的是状态持续和切换概率，不是上涨概率。",
        "- Viterbi-EM 是 hard assignment，可能低估不确定性。",
        "- 第一版 confidence 为空，后续可用 posterior 或 margin 近似。",
        "- 样本期较短时，duration calibration 可能不稳定。",
        "",
        "## 14. Overall Verdict",
        "",
        f"{conclusion[0]}: {conclusion[1]}",
        "",
        "## 15. 后续建议",
        "",
        "- 先看退出概率校准和下一状态预测是否优于 baseline，再决定是否做 UI 展示。",
    ]
    (output / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def _parse_horizons(text: str) -> tuple[int, ...]:
    return tuple(int(x.strip()) for x in text.split(",") if x.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HSMM lifecycle diagnostics")
    parser.add_argument("--db", dest="db_path", default=None)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--output", default=None)
    parser.add_argument("--enable-exit-calibration", action="store_true")
    parser.add_argument("--calibration-train-ratio", type=float, default=0.7)
    parser.add_argument("--calibration-train-end", default=None)
    parser.add_argument("--hmm-cache-key", default=None)
    args = parser.parse_args()
    result = run_hsmm_diagnostics(
        args.db_path,
        args.run_id,
        _parse_horizons(args.horizons),
        args.output,
        enable_exit_calibration=args.enable_exit_calibration,
        calibration_train_ratio=args.calibration_train_ratio,
        calibration_train_end=args.calibration_train_end,
        hmm_cache_key=args.hmm_cache_key,
    )
    summary = result["summary"]
    print(f"报告目录：{summary['output']}")
    print(f"Conclusion: {summary['conclusion']}")
    print(summary["text"])


if __name__ == "__main__":
    main()
