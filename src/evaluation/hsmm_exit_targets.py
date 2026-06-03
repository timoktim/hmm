from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage


DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
DEFAULT_EXIT_TYPES = ("state_id", "display_label")
TARGET_TYPE_BY_EXIT_TYPE = {
    "state_id": "state_id_exit",
    "state_id_exit": "state_id_exit",
    "display_label": "display_label_exit",
    "display_label_exit": "display_label_exit",
}


def parse_horizons(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return DEFAULT_HORIZONS
    return tuple(int(x.strip()) for x in str(raw).split(",") if x.strip())


def parse_exit_types(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return DEFAULT_EXIT_TYPES
    exit_types = tuple(x.strip() for x in str(raw).split(",") if x.strip())
    invalid = [x for x in exit_types if x not in TARGET_TYPE_BY_EXIT_TYPE]
    if invalid:
        raise ValueError(f"Unsupported exit types: {invalid}")
    return tuple("state_id" if TARGET_TYPE_BY_EXIT_TYPE[x] == "state_id_exit" else "display_label" for x in exit_types)


def read_hsmm_states(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    states = storage.read_df("SELECT * FROM hsmm_state_daily WHERE run_id = ? ORDER BY sector_code, trade_date", [run_id])
    if not states.empty:
        states["trade_date"] = pd.to_datetime(states["trade_date"])
    return states


def read_hsmm_episodes(storage: DuckDBStorage, run_id: str) -> pd.DataFrame:
    episodes = storage.read_df("SELECT * FROM hsmm_state_episodes WHERE run_id = ? ORDER BY sector_code, start_date", [run_id])
    if not episodes.empty:
        for col in ["start_date", "end_date", "exit_trade_date"]:
            if col in episodes.columns:
                episodes[col] = pd.to_datetime(episodes[col])
    return episodes


def _left_censored_context_for_group(group: pd.DataFrame, episodes: pd.DataFrame) -> pd.Series:
    out = pd.Series(False, index=group.index)
    if episodes.empty:
        return out
    sector = str(group["sector_code"].iloc[0])
    ep = episodes[(episodes["sector_code"].astype(str) == sector) & (episodes.get("is_left_censored", False) == True)]  # noqa: E712
    if ep.empty:
        return out
    dates = pd.to_datetime(group["trade_date"])
    for _, row in ep.iterrows():
        start = pd.to_datetime(row.get("start_date"))
        end = pd.to_datetime(row.get("end_date"))
        out |= (dates >= start) & (dates <= end)
    return out


def _target_type(exit_type: str) -> str:
    return TARGET_TYPE_BY_EXIT_TYPE[str(exit_type)]


def _raw_score_series(group: pd.DataFrame, horizon: int, target_type: str) -> tuple[pd.Series, str | None]:
    columns = set(group.columns)
    if target_type == "state_id_exit":
        candidates = [
            f"raw_p_exit_state_id_exit_{horizon}d",
            f"raw_p_exit_state_id_{horizon}d",
            f"p_exit_state_id_exit_{horizon}d",
            f"p_exit_state_id_{horizon}d",
            f"raw_p_exit_{horizon}d",
            f"p_exit_{horizon}d",
        ]
    else:
        candidates = [
            f"raw_p_exit_display_label_exit_{horizon}d",
            f"raw_p_exit_display_label_{horizon}d",
            f"p_exit_display_label_exit_{horizon}d",
            f"p_exit_display_label_{horizon}d",
        ]
    for column in candidates:
        if column in columns:
            return pd.to_numeric(group[column], errors="coerce"), target_type
    return pd.Series(np.nan, index=group.index), None


def _first_exit(
    group: pd.DataFrame,
    idx: int,
    horizon: int,
    exit_type: str,
) -> tuple[bool | None, object | None, str | None, pd.Timestamp | None, int | None, bool]:
    value_col = "state_id" if exit_type == "state_id" else "state_label"
    current = group.loc[idx, value_col]
    future = group.iloc[idx + 1 : idx + 1 + horizon]
    is_censored = len(future) < horizon
    if future.empty:
        return None, None, None, None, None, True
    changed = future[future[value_col].astype(str).ne(str(current))]
    if not changed.empty:
        first = changed.iloc[0]
        lag = int(group.index.get_loc(first.name) - idx)
        return (
            True,
            first.get("state_id"),
            str(first.get("state_label")),
            pd.Timestamp(first.get("trade_date")),
            lag,
            is_censored,
        )
    if is_censored:
        return None, None, None, None, None, True
    return False, None, None, None, None, False


def _first_exit_arrays(group: pd.DataFrame, horizon: int, exit_type: str) -> dict[str, object]:
    value_col = "state_id" if exit_type == "state_id" else "state_label"
    n = len(group)
    positions = np.arange(n)
    values = group[value_col].astype(str).to_numpy()
    first_lag = np.full(n, np.nan)
    first_pos = np.full(n, -1, dtype=int)
    for lag in range(1, horizon + 1):
        if lag >= n:
            break
        base_idx = positions[:-lag]
        unmatched = np.isnan(first_lag[:-lag])
        changed = values[lag:] != values[:-lag]
        hit = unmatched & changed
        if hit.any():
            idx = base_idx[hit]
            first_lag[idx] = lag
            first_pos[idx] = idx + lag

    censored = positions + horizon >= n
    actual = np.empty(n, dtype=object)
    actual[:] = False
    actual[censored] = None
    actual[~np.isnan(first_lag)] = True

    state_ids = group["state_id"].to_numpy()
    labels = group["state_label"].astype(object).to_numpy()
    dates = pd.to_datetime(group["trade_date"]).to_numpy()
    horizon_end_dates = np.empty(n, dtype=object)
    horizon_end_dates[:] = None
    horizon_positions = positions + horizon
    has_horizon_end = horizon_positions < n
    horizon_end_dates[has_horizon_end] = pd.to_datetime(dates[horizon_positions[has_horizon_end]])
    next_state_id = np.empty(n, dtype=object)
    next_state_id[:] = None
    next_state_label = np.empty(n, dtype=object)
    next_state_label[:] = None
    exit_dates = np.empty(n, dtype=object)
    exit_dates[:] = None
    has_exit = first_pos >= 0
    if has_exit.any():
        next_state_id[has_exit] = state_ids[first_pos[has_exit]]
        next_state_label[has_exit] = labels[first_pos[has_exit]]
        exit_dates[has_exit] = pd.to_datetime(dates[first_pos[has_exit]])

    lag_values = np.empty(n, dtype=object)
    lag_values[:] = None
    lag_values[has_exit] = first_lag[has_exit].astype(int)
    return {
        "actual": actual,
        "next_state_id": next_state_id,
        "next_state_label": next_state_label,
        "exit_dates": exit_dates,
        "lags": lag_values,
        "censored": censored.astype(bool),
        "horizon_end_dates": horizon_end_dates,
    }


def _is_true(value: object) -> bool:
    return isinstance(value, (bool, np.bool_)) and bool(value)


def _is_false(value: object) -> bool:
    return isinstance(value, (bool, np.bool_)) and not bool(value)


def _target_observation_status(
    actual_exit: object,
    horizon_end_date: object,
    realized_exit_date: object,
    asof_cutoff_date: date | pd.Timestamp | str | None,
) -> str:
    horizon_end = pd.to_datetime(horizon_end_date) if pd.notna(horizon_end_date) else pd.NaT
    realized_exit = pd.to_datetime(realized_exit_date) if pd.notna(realized_exit_date) else pd.NaT
    cutoff = pd.to_datetime(asof_cutoff_date) if asof_cutoff_date is not None and pd.notna(asof_cutoff_date) else None
    if _is_true(actual_exit):
        if cutoff is None or (pd.notna(realized_exit) and realized_exit <= cutoff):
            return "observed_positive"
        return "right_censored_by_cutoff"
    if pd.isna(horizon_end):
        return "unknown"
    if cutoff is not None and horizon_end > cutoff:
        return "right_censored_by_cutoff"
    if _is_false(actual_exit):
        return "observed_negative"
    return "unknown"


def build_exit_targets(
    states: pd.DataFrame,
    episodes: pd.DataFrame | None = None,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    exit_types: tuple[str, ...] = DEFAULT_EXIT_TYPES,
    asof_cutoff_date: date | pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Build audited HSMM exit targets by trading-row horizons.

    `state_id` exit asks whether the hidden state id changes.
    `display_label` exit asks whether the displayed state label changes.
    The future realized labels are evaluation targets only; they are never used
    as features or predictions.
    """
    if states.empty:
        return pd.DataFrame()
    episodes = episodes if episodes is not None else pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    frames: list[pd.DataFrame] = []
    base_cols = [
        "run_id",
        "trade_date",
        "sector_code",
        "state_id",
        "state_label",
        "model_state_age_days",
        "label_state_age_days",
        "display_state_age_days",
        "duration_percentile",
        "expected_remaining_days",
    ]
    for _, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        left_context = _left_censored_context_for_group(group, episodes)
        base = group.reindex(columns=base_cols).copy()
        if "model_state_age_days" not in group.columns:
            base["model_state_age_days"] = group.get("state_age_days_by_id", group.get("state_age_days"))
        if "label_state_age_days" not in group.columns:
            base["label_state_age_days"] = group.get("state_age_days_by_label", group.get("state_age_days"))
        if "display_state_age_days" not in group.columns:
            base["display_state_age_days"] = base.get("label_state_age_days", group.get("state_age_days"))
        base["is_left_censored_context"] = left_context.to_numpy(dtype=bool)
        for horizon in horizons:
            for exit_type in exit_types:
                target_type = _target_type(exit_type)
                score, raw_score_target_type = _raw_score_series(group, horizon, target_type)
                exits = _first_exit_arrays(group, horizon, exit_type)
                frame = base.copy()
                frame["horizon_days"] = int(horizon)
                frame["exit_type"] = exit_type
                frame["target_type"] = target_type
                frame["actual_exit_within_h"] = exits["actual"]
                frame["actual_exit_target_type"] = target_type
                frame["actual_next_state_id"] = exits["next_state_id"]
                frame["actual_next_state_label"] = exits["next_state_label"]
                frame["realized_exit_date"] = exits["exit_dates"]
                frame["realized_exit_lag_days"] = exits["lags"]
                frame["horizon_end_date"] = exits["horizon_end_dates"]
                frame["is_right_censored_for_horizon"] = exits["censored"]
                frame["target_observation_status"] = [
                    _target_observation_status(actual, horizon_end, realized_exit, asof_cutoff_date)
                    for actual, horizon_end, realized_exit in zip(
                        frame["actual_exit_within_h"],
                        frame["horizon_end_date"],
                        frame["realized_exit_date"],
                        strict=False,
                    )
                ]
                frame["raw_exit_score"] = score.to_numpy(dtype=float)
                frame["raw_exit_score_target_type"] = raw_score_target_type
                state_score, state_basis = _raw_score_series(group, horizon, "state_id_exit")
                label_score, label_basis = _raw_score_series(group, horizon, "display_label_exit")
                frame["raw_state_exit_score"] = state_score.to_numpy(dtype=float)
                frame["raw_state_exit_score_target_type"] = state_basis
                frame["raw_label_exit_score"] = label_score.to_numpy(dtype=float)
                frame["raw_label_exit_score_target_type"] = label_basis
                frames.append(frame)
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not out.empty:
        out["actual_exit_within_h"] = out["actual_exit_within_h"].astype("object")
    return out


def write_exit_targets(targets: pd.DataFrame, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    targets.to_csv(output_dir / "exit_targets.csv", index=False)
    targets.head(5000).to_csv(output_dir / "exit_targets_sample.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HSMM lifecycle exit targets")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--exit-types", default="state_id,display_label")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    storage = DuckDBStorage(args.db)
    states = read_hsmm_states(storage, args.run_id)
    episodes = read_hsmm_episodes(storage, args.run_id)
    targets = build_exit_targets(states, episodes, parse_horizons(args.horizons), parse_exit_types(args.exit_types))
    write_exit_targets(targets, Path(args.output))
    print(f"exit_targets_rows: {len(targets)}")
    print(f"output_dir: {args.output}")


if __name__ == "__main__":
    main()
