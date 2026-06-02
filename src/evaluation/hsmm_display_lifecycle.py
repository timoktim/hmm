from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.ui.readiness_policy import MISLEADING_PROBABILITY_CLAIMS, find_misleading_probability_claims
from src.evaluation.hsmm_exit_targets import build_exit_targets, parse_horizons


DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
AGE_BUCKETS = ((1, 3), (4, 7), (8, 14), (15, None))
PHASES = ("early", "mature", "late", "unknown")
EXIT_TENDENCIES = ("low", "medium", "high", "unavailable")
RAW_SCORE_ALLOWED_STATUSES = {"usable_probability", "raw_only"}
PROBABILITY_READINESS_REQUIRED_FIELDS = (
    "run_id",
    "config_hash",
    "lineage_hash",
    "profile_mode",
    "profile_cutoff_date",
    "state_date_policy",
    "feature_scope_id",
    "exit_type",
    "horizon_days",
    "probability_status",
    "created_at",
)
PROBABILITY_READINESS_METADATA_FIELDS = (
    "run_id",
    "config_hash",
    "lineage_hash",
    "profile_mode",
    "profile_cutoff_date",
    "state_date_policy",
    "feature_scope_id",
)
PROBABILITY_READINESS_VALID_STATUSES = {
    "usable_probability",
    "raw_only",
    "ordinal_only",
    "invalid",
    "insufficient_sample",
    "missing",
    "tail_censored",
}
NEXT_STATE_TENDENCIES = ("Trend", "Neutral", "Stress", "Repair", "Mixed", "Unavailable")
FORBIDDEN_UI_TERMS = ("上涨概率", "下跌概率", "买入", "卖出", "交易信号", "推荐买入", "推荐板块", "目标收益", "胜率", "RiskOff")
STATE_DATE_POLICIES = ("full_run", "cutoff_only")
WP8_DAILY_ALIAS_SUFFIXES = ("readiness_status", "raw_score_used", "raw_basis")


@dataclass(frozen=True)
class LifecycleDisplayConfig:
    horizons: tuple[int, ...] = DEFAULT_HORIZONS
    age_buckets: tuple[tuple[int, int | None], ...] = AGE_BUCKETS
    min_duration_profile_samples: int = 3
    min_empirical_bucket_sample: int = 100
    min_empirical_label_sample: int = 300
    min_next_state_sample: int = 100
    next_state_top_threshold: float = 0.45
    next_state_mixed_threshold: float = 0.35
    age_weight_with_raw: float = 0.45
    empirical_weight_with_raw: float = 0.40
    raw_rank_weight: float = 0.15
    age_weight_without_raw: float = 0.55
    empirical_weight_without_raw: float = 0.45
    low_quantile: float = 0.30
    high_quantile: float = 0.70
    low_discrimination_min_categories: int = 2
    saturation_high_medium_share: float = 0.95


def read_hsmm_states(storage: DuckDBStorage, run_id: str, require_completed: bool = True) -> pd.DataFrame:
    if require_completed:
        run_status = storage.read_df("SELECT run_status FROM hsmm_model_runs WHERE run_id = ? LIMIT 1", [run_id])
        if not run_status.empty and str(run_status.loc[0, "run_status"]) != "completed":
            return pd.DataFrame()
    states = storage.read_df("SELECT * FROM hsmm_state_daily WHERE run_id = ? ORDER BY sector_code, trade_date", [run_id])
    if states.empty:
        return states
    for col in ["trade_date", "train_start_date", "train_end_date", "max_observation_date_used", "created_at"]:
        if col in states.columns:
            states[col] = pd.to_datetime(states[col])
    return states


def age_bucket(value: object, buckets: Iterable[tuple[int, int | None]] = AGE_BUCKETS) -> str:
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


def normalize_profile_mode(profile_mode: str) -> str:
    mode = str(profile_mode or "retrospective").strip()
    if mode not in {"retrospective", "latest_asof"}:
        raise ValueError("profile_mode must be retrospective or latest_asof")
    return mode


def normalize_state_date_policy(state_date_policy: str) -> str:
    policy = str(state_date_policy or "full_run").strip()
    if policy not in STATE_DATE_POLICIES:
        raise ValueError("state_date_policy must be full_run or cutoff_only")
    return policy


def build_display_label_episodes(states: pd.DataFrame) -> pd.DataFrame:
    """Build user-visible display-label episodes from causal HSMM daily states."""
    if states.empty:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    run_id = str(work["run_id"].iloc[0]) if "run_id" in work.columns else ""
    created_at = pd.Timestamp.now(tz=None)
    rows: list[dict[str, object]] = []
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        start_idx = 0
        episode_no = 0
        for idx in range(1, len(group) + 1):
            boundary = idx == len(group) or str(group.loc[idx, "state_label"]) != str(group.loc[idx - 1, "state_label"])
            if not boundary:
                continue
            segment = group.iloc[start_idx:idx]
            prev_label = None if start_idx == 0 else str(group.loc[start_idx - 1, "state_label"])
            next_label = None if idx == len(group) else str(group.loc[idx, "state_label"])
            is_left = start_idx == 0
            is_right = idx == len(group)
            episode_no += 1
            start_date = pd.Timestamp(segment["trade_date"].iloc[0]).date()
            end_date = pd.Timestamp(segment["trade_date"].iloc[-1]).date()
            duration = int(len(segment))
            rows.append(
                {
                    "run_id": run_id,
                    "sector_code": str(sector_code),
                    "sector_name": segment["sector_name"].iloc[0] if "sector_name" in segment.columns else str(sector_code),
                    "state_label": str(segment["state_label"].iloc[0]),
                    "episode_id": f"{run_id}:{sector_code}:display:{episode_no:06d}",
                    "start_date": start_date,
                    "end_date": end_date,
                    "episode_start_date": start_date,
                    "episode_end_date": end_date,
                    "start_trade_idx": int(start_idx + 1),
                    "end_trade_idx": int(idx),
                    "duration_days": duration,
                    "duration_trading_days": duration,
                    "is_open_episode": bool(is_right),
                    "is_left_censored": bool(is_left),
                    "left_censor_reason": "run_start" if is_left else None,
                    "is_right_censored": bool(is_right),
                    "right_censor_reason": "run_end" if is_right else None,
                    "prev_state_label": prev_label,
                    "previous_state_label": prev_label,
                    "next_state_label": next_label,
                    "created_at": created_at,
                }
            )
            start_idx = idx
    return pd.DataFrame(rows)


def attach_display_episode_context(states: pd.DataFrame, episodes: pd.DataFrame) -> pd.DataFrame:
    if states.empty or episodes.empty:
        return states.copy()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    pieces: list[pd.DataFrame] = []
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=False).rename(columns={"index": "_original_index"})
        sector_eps = episodes[episodes["sector_code"].astype(str).eq(str(sector_code))].sort_values("start_trade_idx")
        for _, ep in sector_eps.iterrows():
            start_pos = int(ep["start_trade_idx"]) - 1
            end_pos = int(ep["end_trade_idx"])
            segment = group.iloc[start_pos:end_pos].copy()
            segment["display_episode_id"] = ep["episode_id"]
            segment["display_episode_start_date"] = pd.to_datetime(ep["episode_start_date"])
            segment["display_episode_end_date"] = pd.to_datetime(ep["episode_end_date"])
            segment["display_state_age_days"] = np.arange(1, len(segment) + 1)
            segment["display_age_bucket"] = segment["display_state_age_days"].map(age_bucket)
            segment["prev_state_label"] = ep.get("prev_state_label")
            segment["next_state_label_realized"] = ep.get("next_state_label")
            pieces.append(segment)
    if not pieces:
        return work
    out = pd.concat(pieces, ignore_index=True).sort_values("_original_index")
    return out.drop(columns=["_original_index"])


def filter_profile_episodes(
    episodes: pd.DataFrame,
    profile_mode: str = "retrospective",
    profile_cutoff_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    if episodes.empty:
        return episodes.copy()
    mode = normalize_profile_mode(profile_mode)
    work = episodes.copy()
    work["episode_end_date"] = pd.to_datetime(work.get("episode_end_date", work.get("end_date")))
    complete = work[
        (work["is_left_censored"] == False)  # noqa: E712
        & (work["is_right_censored"] == False)  # noqa: E712
        & (work["is_open_episode"] == False)  # noqa: E712
    ].copy()
    if mode == "latest_asof":
        if profile_cutoff_date is None:
            profile_cutoff_date = work["episode_end_date"].max()
        cutoff = pd.to_datetime(profile_cutoff_date)
        complete = complete[complete["episode_end_date"] < cutoff].copy()
    return complete


def _duration_percentile(durations: pd.Series, age: object) -> float:
    clean = pd.to_numeric(durations, errors="coerce").dropna()
    try:
        age_value = float(age)
    except Exception:
        return np.nan
    if clean.empty:
        return np.nan
    return float((clean <= age_value).mean())


def compute_display_duration_profile(episodes: pd.DataFrame, min_samples: int = 3) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    labels = sorted(episodes["state_label"].dropna().astype(str).unique())
    rows: list[dict[str, object]] = []
    for label in labels:
        group = episodes[episodes["state_label"].astype(str).eq(label)]
        durations = pd.to_numeric(group["duration_trading_days"] if "duration_trading_days" in group.columns else group["duration_days"], errors="coerce").dropna()
        enough = len(durations) >= min_samples
        rows.append(
            {
                "state_label": label,
                "completed_episode_count": int(len(group)),
                "median_duration_days": float(durations.median()) if enough else np.nan,
                "p10_duration_days": float(durations.quantile(0.10)) if enough else np.nan,
                "p25_duration_days": float(durations.quantile(0.25)) if enough else np.nan,
                "p33_duration_days": float(durations.quantile(0.33)) if enough else np.nan,
                "p66_duration_days": float(durations.quantile(0.66)) if enough else np.nan,
                "p75_duration_days": float(durations.quantile(0.75)) if enough else np.nan,
                "p90_duration_days": float(durations.quantile(0.90)) if enough else np.nan,
                "mean_duration_days": float(durations.mean()) if enough else np.nan,
                "duration_profile_status": "usable" if enough else "insufficient_sample",
            }
        )
    return pd.DataFrame(rows)


def build_profile_specific_duration_profile(
    duration_profile: pd.DataFrame,
    all_episodes: pd.DataFrame,
    profile_episodes: pd.DataFrame,
    metadata: dict[str, object],
) -> pd.DataFrame:
    if duration_profile.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "profile_mode",
                "profile_cutoff_date",
                "state_label",
                "completed_episode_count",
                "mean_duration_days",
                "median_duration_days",
                "p10_duration_days",
                "p25_duration_days",
                "p75_duration_days",
                "p90_duration_days",
                "left_censored_count",
                "right_censored_count",
                "profile_sample_window_start",
                "profile_sample_window_end",
                "created_at",
            ]
        )
    out = duration_profile.copy()
    if "p25_duration_days" not in out.columns:
        out["p25_duration_days"] = np.nan
    if "p75_duration_days" not in out.columns:
        out["p75_duration_days"] = np.nan
    censor_counts = pd.DataFrame(columns=["state_label", "left_censored_count", "right_censored_count"])
    if not all_episodes.empty:
        censor_counts = (
            all_episodes.groupby("state_label", observed=True)
            .agg(
                left_censored_count=("is_left_censored", "sum"),
                right_censored_count=("is_right_censored", "sum"),
            )
            .reset_index()
        )
    out = out.merge(censor_counts, on="state_label", how="left")
    out["left_censored_count"] = pd.to_numeric(out["left_censored_count"], errors="coerce").fillna(0).astype(int)
    out["right_censored_count"] = pd.to_numeric(out["right_censored_count"], errors="coerce").fillna(0).astype(int)
    out["run_id"] = metadata.get("run_id")
    out["profile_mode"] = metadata.get("profile_mode")
    out["profile_cutoff_date"] = metadata.get("profile_cutoff_date")
    out["profile_sample_window_start"] = metadata.get("profile_window_start")
    out["profile_sample_window_end"] = metadata.get("profile_window_end")
    out["created_at"] = pd.Timestamp.now(tz=None)
    cols = [
        "run_id",
        "profile_mode",
        "profile_cutoff_date",
        "state_label",
        "completed_episode_count",
        "mean_duration_days",
        "median_duration_days",
        "p10_duration_days",
        "p25_duration_days",
        "p75_duration_days",
        "p90_duration_days",
        "left_censored_count",
        "right_censored_count",
        "profile_sample_window_start",
        "profile_sample_window_end",
        "created_at",
    ]
    return out[[c for c in cols if c in out.columns]].copy()


def _completed_duration_map(profile_episodes: pd.DataFrame) -> dict[str, pd.Series]:
    if profile_episodes.empty:
        return {}
    duration_col = "duration_trading_days" if "duration_trading_days" in profile_episodes.columns else "duration_days"
    return {
        str(label): pd.to_numeric(group[duration_col], errors="coerce").dropna()
        for label, group in profile_episodes.groupby("state_label", observed=True)
    }


def assign_state_phase(states: pd.DataFrame, duration_profile: pd.DataFrame, min_samples: int = 3) -> pd.DataFrame:
    if states.empty:
        return states.copy()
    out = states.copy()
    profile = duration_profile.set_index("state_label").to_dict("index") if not duration_profile.empty else {}
    phases: list[str] = []
    for _, row in out.iterrows():
        label = str(row.get("state_label"))
        info = profile.get(label)
        age = pd.to_numeric(pd.Series([row.get("display_state_age_days")]), errors="coerce").iloc[0]
        if not info or pd.isna(age) or int(info.get("completed_episode_count", 0) or 0) < min_samples:
            phases.append("unknown")
            continue
        p33 = info.get("p33_duration_days")
        p66 = info.get("p66_duration_days")
        if pd.isna(p33) or pd.isna(p66):
            phases.append("unknown")
        elif age <= float(p33):
            phases.append("early")
        elif age <= float(p66):
            phases.append("mature")
        else:
            phases.append("late")
    out["state_phase"] = phases
    return out


def _single_contract_value(frame: pd.DataFrame, column: str) -> object | None:
    if column not in frame.columns or frame.empty:
        return None
    values = frame[column].dropna().astype(str).unique().tolist()
    return values[0] if len(values) == 1 else None


def _normalize_contract_value(field: str, value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    if field.endswith("_date"):
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.notna(parsed):
            return str(parsed.date())
    return str(value).strip()


def _expected_probability_metadata(
    states: pd.DataFrame,
    *,
    profile_mode: str,
    profile_cutoff_date: object,
    state_date_policy: str,
    extra: dict[str, object] | None = None,
) -> dict[str, object]:
    expected: dict[str, object] = {
        "run_id": _single_contract_value(states, "run_id"),
        "config_hash": _single_contract_value(states, "config_hash"),
        "lineage_hash": _single_contract_value(states, "lineage_hash"),
        "profile_mode": profile_mode,
        "profile_cutoff_date": profile_cutoff_date,
        "state_date_policy": state_date_policy,
        "feature_scope_id": _single_contract_value(states, "feature_scope_id"),
    }
    if extra:
        expected.update({key: value for key, value in extra.items() if value is not None})
    return expected


def _read_hsmm_run_contract_metadata(storage: DuckDBStorage, run_id: str) -> dict[str, object]:
    try:
        run = storage.read_df(
            """
            SELECT run_id, config_hash, lineage_hash, feature_scope_id
            FROM hsmm_model_runs
            WHERE run_id = ?
            LIMIT 1
            """,
            [run_id],
        )
    except Exception:
        return {}
    if run.empty:
        return {}
    row = run.iloc[0]
    return {field: row.get(field) for field in ["run_id", "config_hash", "lineage_hash", "feature_scope_id"]}


def validate_probability_status_matrix(
    matrix: pd.DataFrame,
    expected_metadata: dict[str, object] | None = None,
) -> pd.DataFrame:
    if matrix.empty:
        return pd.DataFrame()
    out = matrix.copy()
    if "probability_status" not in out.columns and "status" in out.columns:
        out["probability_status"] = out["status"]
    if "probability_status" not in out.columns:
        out["probability_status"] = "missing"
    if "exit_type" in out.columns:
        out = out[out["exit_type"].astype(str).eq("display_label")].copy()
    if out.empty:
        return out
    if "state_label" not in out.columns or "horizon_days" not in out.columns:
        return pd.DataFrame()

    out["probability_status"] = (
        out["probability_status"]
        .fillna("missing")
        .astype(str)
        .replace({"": "missing", "nan": "missing", "None": "missing"})
    )
    invalid_mask = ~out["probability_status"].isin(PROBABILITY_READINESS_VALID_STATUSES)
    mismatch_reasons = pd.Series("", index=out.index, dtype=object)

    missing_fields = [field for field in PROBABILITY_READINESS_REQUIRED_FIELDS if field not in out.columns]
    if missing_fields:
        invalid_mask = pd.Series(True, index=out.index)
        mismatch_reasons = pd.Series("missing_required_fields:" + ",".join(missing_fields), index=out.index, dtype=object)

    expected = expected_metadata or {}
    for field in PROBABILITY_READINESS_METADATA_FIELDS:
        expected_value = _normalize_contract_value(field, expected.get(field))
        if expected_value == "":
            continue
        if field not in out.columns:
            invalid_mask = pd.Series(True, index=out.index)
            reason = f"missing_expected_field:{field}"
            mismatch_reasons = mismatch_reasons.mask(mismatch_reasons.eq(""), reason)
            mismatch_reasons = mismatch_reasons.mask(
                ~mismatch_reasons.str.contains(reason, regex=False),
                mismatch_reasons + ";" + reason,
            )
            continue
        actual_values = out[field].map(lambda value: _normalize_contract_value(field, value))
        field_mismatch = actual_values.ne(expected_value)
        reason = f"{field}_mismatch"
        mismatch_reasons = mismatch_reasons.mask(field_mismatch & mismatch_reasons.eq(""), reason)
        mismatch_reasons = mismatch_reasons.mask(
            field_mismatch & ~mismatch_reasons.str.contains(reason, regex=False),
            mismatch_reasons + ";" + reason,
        )
        invalid_mask |= field_mismatch

    out["readiness_contract_status"] = np.where(invalid_mask, "invalid", "valid")
    out["readiness_mismatch_reason"] = mismatch_reasons.where(invalid_mask, "")
    out.loc[invalid_mask, "probability_status"] = "invalid"
    if "can_show_numeric_probability" in out.columns:
        out.loc[invalid_mask, "can_show_numeric_probability"] = False
    if "can_show_ordinal_score" in out.columns:
        out.loc[invalid_mask, "can_show_ordinal_score"] = False
    if "must_hide" in out.columns:
        out.loc[invalid_mask, "must_hide"] = True
    return out


def _read_probability_status(
    run_id: str,
    base_dir: Path | None = None,
    expected_metadata: dict[str, object] | None = None,
) -> pd.DataFrame:
    root = base_dir or Path("reports") / "hsmm_lifecycle_probability" / run_id
    matrix_path = root / "ui_readiness_matrix.csv"
    if not matrix_path.exists():
        return pd.DataFrame()
    matrix = pd.read_csv(matrix_path)
    return validate_probability_status_matrix(matrix, expected_metadata)


def _probability_status_map(probability_status: pd.DataFrame, horizons: tuple[int, ...], labels: Iterable[str]) -> pd.DataFrame:
    labels_df = pd.DataFrame({"state_label": sorted(set(str(x) for x in labels))})
    pieces: list[pd.DataFrame] = []
    for horizon in horizons:
        frame = labels_df.copy()
        frame["horizon_days"] = int(horizon)
        if not probability_status.empty:
            status = probability_status[probability_status["horizon_days"].astype(int).eq(int(horizon))]
            mapping = status.set_index("state_label")["probability_status"].astype(str).to_dict()
            frame["probability_status"] = frame["state_label"].map(mapping).fillna("missing")
        else:
            frame["probability_status"] = "missing"
        frame["raw_score_allowed"] = frame["probability_status"].isin(RAW_SCORE_ALLOWED_STATUSES)
        pieces.append(frame)
    return pd.concat(pieces, ignore_index=True) if pieces else pd.DataFrame()


def _raw_basis(status: object) -> str:
    value = str(status)
    if value == "usable_probability":
        return "raw_rank_used_allowed"
    if value == "raw_only":
        return "raw_rank_used_as_internal_diagnostic"
    if value == "ordinal_only":
        return "raw_rank_excluded_ordinal_only"
    if value == "tail_censored":
        return "tail_censored_beyond_duration_support"
    if value == "invalid":
        return "raw_rank_excluded_invalid"
    if value == "insufficient_sample":
        return "raw_rank_excluded_insufficient_sample"
    return "raw_rank_excluded_missing_policy"


def _score_to_relative_tendency(group: pd.DataFrame, config: LifecycleDisplayConfig) -> pd.Series:
    scores = pd.to_numeric(group["exit_tendency_score"], errors="coerce")
    out = pd.Series("unavailable", index=group.index, dtype=object)
    valid = scores.notna()
    if valid.sum() < 3 or scores[valid].nunique() < config.low_discrimination_min_categories:
        out.loc[valid] = "medium"
        return out
    low_cut = float(scores[valid].quantile(config.low_quantile))
    high_cut = float(scores[valid].quantile(config.high_quantile))
    if np.isclose(low_cut, high_cut):
        out.loc[valid] = "medium"
        return out
    out.loc[valid & (scores <= low_cut)] = "low"
    out.loc[valid & (scores >= high_cut)] = "high"
    out.loc[valid & (scores > low_cut) & (scores < high_cut)] = "medium"
    return out


def _exit_tendency_long(
    states: pd.DataFrame,
    episodes: pd.DataFrame,
    profile_episodes: pd.DataFrame,
    duration_profile: pd.DataFrame,
    horizons: tuple[int, ...],
    probability_status: pd.DataFrame,
    config: LifecycleDisplayConfig,
    profile_cutoff_date: str | pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    if states.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    targets = build_exit_targets(
        states,
        episodes,
        horizons=horizons,
        exit_types=("display_label",),
        asof_cutoff_date=profile_cutoff_date,
    )
    if targets.empty:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    targets["age_bucket"] = targets["display_state_age_days"].apply(lambda x: age_bucket(x, config.age_buckets))
    targets["actual_exit"] = targets["actual_exit_within_h"].map({True: 1.0, False: 0.0})
    profile_target_source = targets.merge(
        profile_episodes[["run_id", "sector_code", "episode_id"]] if "episode_id" in profile_episodes.columns else pd.DataFrame(),
        left_on=["run_id", "sector_code"],
        right_on=["run_id", "sector_code"],
        how="inner",
    ) if False else targets
    eligible = targets[targets["target_observation_status"].isin(["observed_positive", "observed_negative"])].copy()

    bucket = (
        eligible.groupby(["state_label", "age_bucket", "horizon_days"], observed=True)
        .agg(sample_count=("actual_exit", "size"), empirical_exit_rate=("actual_exit", "mean"))
        .reset_index()
        if not eligible.empty
        else pd.DataFrame()
    )
    label_level = (
        eligible.groupby(["state_label", "horizon_days"], observed=True)
        .agg(label_sample_count=("actual_exit", "size"), label_exit_rate=("actual_exit", "mean"))
        .reset_index()
        if not eligible.empty
        else pd.DataFrame()
    )
    if not bucket.empty:
        bucket = bucket.merge(label_level, on=["state_label", "horizon_days"], how="left")
        bucket["bucket_usable"] = bucket["sample_count"] >= config.min_empirical_bucket_sample
        bucket["label_fallback_usable"] = bucket["label_sample_count"] >= config.min_empirical_label_sample
        bucket["profile_exit_rate_used"] = np.where(
            bucket["bucket_usable"],
            bucket["empirical_exit_rate"],
            np.where(bucket["label_fallback_usable"], bucket["label_exit_rate"], np.nan),
        )
    else:
        bucket = pd.DataFrame(
            columns=[
                "state_label",
                "age_bucket",
                "horizon_days",
                "sample_count",
                "empirical_exit_rate",
                "label_sample_count",
                "label_exit_rate",
                "bucket_usable",
                "label_fallback_usable",
                "profile_exit_rate_used",
            ]
        )

    duration_map = _completed_duration_map(profile_episodes)
    target_base = targets.copy()
    target_base["duration_percentile_display"] = [
        _duration_percentile(duration_map.get(str(label), pd.Series(dtype=float)), age)
        for label, age in zip(target_base["state_label"], target_base["display_state_age_days"], strict=False)
    ]
    status_map = _probability_status_map(probability_status, horizons, target_base["state_label"].dropna().astype(str).unique())
    long_rows: list[pd.DataFrame] = []
    for horizon in horizons:
        h = target_base[target_base["horizon_days"].eq(int(horizon))].copy()
        h = h.merge(status_map[status_map["horizon_days"].eq(int(horizon))], on=["state_label", "horizon_days"], how="left")
        h["probability_status"] = h["probability_status"].fillna("missing")
        h["raw_score_allowed"] = h["raw_score_allowed"].fillna(False).astype(bool)
        raw_col = f"raw_p_exit_{horizon}d"
        if raw_col in states.columns:
            raw_rank = states[["sector_code", "trade_date", "state_label", raw_col]].copy()
            raw_rank["trade_date"] = pd.to_datetime(raw_rank["trade_date"])
            raw_rank["raw_exit_score_value"] = pd.to_numeric(raw_rank[raw_col], errors="coerce")
            raw_rank["raw_exit_rank_score_unmasked"] = raw_rank.groupby("state_label")[raw_col].rank(pct=True)
            h = h.merge(raw_rank[["sector_code", "trade_date", "raw_exit_score_value", "raw_exit_rank_score_unmasked"]], on=["sector_code", "trade_date"], how="left")
        else:
            h["raw_exit_score_value"] = np.nan
            h["raw_exit_rank_score_unmasked"] = np.nan
        if "duration_percentile" in h.columns:
            model_duration_percentile = pd.to_numeric(h["duration_percentile"], errors="coerce")
        else:
            model_duration_percentile = pd.Series(np.nan, index=h.index)
        h["tail_censored"] = model_duration_percentile.ge(1.0) & h["raw_exit_score_value"].isna()
        h.loc[h["tail_censored"], "probability_status"] = "tail_censored"
        h.loc[h["tail_censored"], "raw_score_allowed"] = False
        h["raw_score_used"] = h["raw_score_allowed"] & h["raw_exit_rank_score_unmasked"].notna()
        h["raw_exit_rank_score"] = np.where(h["raw_score_used"], h["raw_exit_rank_score_unmasked"], np.nan)
        h = h.merge(
            bucket[
                [
                    "state_label",
                    "age_bucket",
                    "horizon_days",
                    "sample_count",
                    "label_sample_count",
                    "profile_exit_rate_used",
                    "bucket_usable",
                    "label_fallback_usable",
                ]
            ],
            on=["state_label", "age_bucket", "horizon_days"],
            how="left",
        )
        age_score = pd.to_numeric(h["duration_percentile_display"], errors="coerce")
        empirical_score = pd.to_numeric(h["profile_exit_rate_used"], errors="coerce")
        raw_score = pd.to_numeric(h["raw_exit_rank_score"], errors="coerce")
        score_with_raw = (
            config.age_weight_with_raw * age_score
            + config.empirical_weight_with_raw * empirical_score
            + config.raw_rank_weight * raw_score
        ) / (config.age_weight_with_raw + config.empirical_weight_with_raw + config.raw_rank_weight)
        score_without_raw = (
            config.age_weight_without_raw * age_score
            + config.empirical_weight_without_raw * empirical_score
        ) / (config.age_weight_without_raw + config.empirical_weight_without_raw)
        h["exit_tendency_score"] = np.where(h["raw_score_used"], score_with_raw, score_without_raw)
        h.loc[age_score.isna() | empirical_score.isna(), "exit_tendency_score"] = np.nan
        h["raw_basis"] = h["probability_status"].map(_raw_basis)
        h["exit_tendency_basis"] = "age_percentile+empirical_exit_rate+" + h["raw_basis"].astype(str)
        h.loc[h["tail_censored"], "exit_tendency_score"] = np.nan
        h.loc[h["tail_censored"], "exit_tendency_basis"] = "tail_censored_beyond_duration_support"
        tendency_parts = [
            _score_to_relative_tendency(group, config)
            for _, group in h.groupby(["state_label", "horizon_days"], observed=True)
        ]
        if tendency_parts:
            h["exit_tendency"] = pd.concat(tendency_parts).reindex(h.index).fillna("unavailable")
        else:
            h["exit_tendency"] = "unavailable"
        h.loc[h["tail_censored"], "exit_tendency"] = "unavailable"
        long_rows.append(
            h[
                [
                    "run_id",
                    "trade_date",
                    "sector_code",
                    "state_label",
                    "horizon_days",
                    "exit_tendency",
                    "exit_tendency_score",
                    "exit_tendency_basis",
                    "duration_percentile_display",
                    "profile_exit_rate_used",
                    "raw_exit_rank_score",
                    "raw_score_used",
                    "probability_status",
                    "raw_basis",
                    "sample_count",
                    "label_sample_count",
                ]
            ]
        )
    long = pd.concat(long_rows, ignore_index=True) if long_rows else pd.DataFrame()
    distribution = build_exit_tendency_distribution(long, config)
    return long, bucket, distribution


def build_exit_tendency_distribution(exit_long: pd.DataFrame, config: LifecycleDisplayConfig = LifecycleDisplayConfig()) -> pd.DataFrame:
    if exit_long.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    total_by_group = exit_long.groupby(["horizon_days", "state_label"], observed=True).size().rename("total").reset_index()
    counts = (
        exit_long.groupby(["horizon_days", "state_label", "exit_tendency"], observed=True)
        .size()
        .rename("row_count")
        .reset_index()
        .merge(total_by_group, on=["horizon_days", "state_label"], how="left")
    )
    counts["share"] = counts["row_count"] / counts["total"].replace(0, np.nan)
    for (horizon, label), group in counts.groupby(["horizon_days", "state_label"], observed=True):
        categories = set(group.loc[group["row_count"] > 0, "exit_tendency"].astype(str))
        high_medium_share = float(group[group["exit_tendency"].isin(["high", "medium"])]["share"].sum())
        low_discrimination = len(categories - {"unavailable"}) < config.low_discrimination_min_categories
        if int(horizon) == 20 and high_medium_share >= config.saturation_high_medium_share:
            low_discrimination = True
        for _, row in group.iterrows():
            rows.append(
                {
                    "horizon_days": int(horizon),
                    "state_label": label,
                    "exit_tendency": row["exit_tendency"],
                    "row_count": int(row["row_count"]),
                    "share": float(row["share"]),
                    "low_discrimination": bool(low_discrimination),
                    "high_medium_share": high_medium_share,
                }
            )
    return pd.DataFrame(rows)


def build_exit_tendency_policy_audit(exit_long: pd.DataFrame) -> pd.DataFrame:
    if exit_long.empty:
        return pd.DataFrame()
    audit = (
        exit_long.groupby(["horizon_days", "state_label", "probability_status", "raw_score_used"], observed=True)
        .size()
        .rename("row_count")
        .reset_index()
    )
    audit["policy_violation"] = audit["probability_status"].isin(["invalid", "insufficient_sample", "missing", "unknown", "unverified"]) & audit["raw_score_used"].astype(bool)
    return audit


def compute_empirical_exit_tendency(states: pd.DataFrame, episodes: pd.DataFrame, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    config = LifecycleDisplayConfig(horizons=tuple(horizons))
    profile_episodes = filter_profile_episodes(episodes, "retrospective")
    duration_profile = compute_display_duration_profile(profile_episodes, config.min_duration_profile_samples)
    _, profile, _ = _exit_tendency_long(states, episodes, profile_episodes, duration_profile, tuple(horizons), pd.DataFrame(), config)
    return profile


def _episode_phase(row: pd.Series, duration_profile: pd.DataFrame, config: LifecycleDisplayConfig) -> str:
    if duration_profile.empty:
        return "unknown"
    profile = duration_profile.set_index("state_label").to_dict("index")
    info = profile.get(str(row.get("state_label")))
    if not info:
        return "unknown"
    duration = row.get("duration_trading_days", row.get("duration_days"))
    if pd.isna(duration) or pd.isna(info.get("p33_duration_days")) or pd.isna(info.get("p66_duration_days")):
        return "unknown"
    if float(duration) <= float(info["p33_duration_days"]):
        return "early"
    if float(duration) <= float(info["p66_duration_days"]):
        return "mature"
    return "late"


def _next_state_profile(
    episodes: pd.DataFrame,
    group_cols: list[str],
    config: LifecycleDisplayConfig,
) -> pd.DataFrame:
    if episodes.empty:
        return pd.DataFrame()
    complete = episodes[
        (episodes["is_right_censored"] == False)  # noqa: E712
        & episodes["next_state_label"].notna()
    ].copy()
    if complete.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for keys, group in complete.groupby(group_cols, observed=True, dropna=False):
        if not isinstance(keys, tuple):
            keys = (keys,)
        sample = int(len(group))
        dist = group["next_state_label"].dropna().astype(str).value_counts(normalize=True)
        top_label = str(dist.index[0]) if not dist.empty else None
        top_share = float(dist.iloc[0]) if not dist.empty else np.nan
        if sample < config.min_next_state_sample:
            tendency = "Unavailable"
            status = "insufficient_sample"
        elif pd.notna(top_share) and top_share >= config.next_state_top_threshold and top_label in NEXT_STATE_TENDENCIES:
            tendency = top_label
            status = "usable"
        elif pd.notna(top_share) and top_share >= config.next_state_mixed_threshold:
            tendency = "Mixed"
            status = "mixed"
        else:
            tendency = "Unavailable"
            status = "unavailable"
        row = {col: key for col, key in zip(group_cols, keys, strict=False)}
        row.update(
            {
                "sample_count": sample,
                "top_next_state_label": top_label,
                "top_next_state_share": top_share,
                "next_state_tendency": tendency,
                "confidence": top_share if status == "usable" else np.nan,
                "status": status,
                "next_state_distribution_json": json.dumps(dist.to_dict(), ensure_ascii=False),
                "created_at": pd.Timestamp.now(tz=None),
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def compute_next_state_tendency_profiles(
    profile_episodes: pd.DataFrame,
    duration_profile: pd.DataFrame,
    config: LifecycleDisplayConfig = LifecycleDisplayConfig(),
) -> dict[str, pd.DataFrame]:
    if profile_episodes.empty:
        empty = pd.DataFrame()
        return {"by_label": empty, "by_phase": empty, "by_age_bucket": empty}
    work = profile_episodes.copy()
    work["state_phase"] = work.apply(lambda row: _episode_phase(row, duration_profile, config), axis=1)
    duration_col = "duration_trading_days" if "duration_trading_days" in work.columns else "duration_days"
    work["age_bucket"] = work[duration_col].apply(lambda x: age_bucket(x, config.age_buckets))
    return {
        "by_label": _next_state_profile(work, ["state_label"], config),
        "by_phase": _next_state_profile(work, ["state_label", "state_phase"], config),
        "by_age_bucket": _next_state_profile(work, ["state_label", "age_bucket"], config),
    }


def compute_next_state_tendency(episodes: pd.DataFrame, config: LifecycleDisplayConfig = LifecycleDisplayConfig()) -> pd.DataFrame:
    profile = compute_next_state_tendency_profiles(episodes, pd.DataFrame(), config)["by_label"]
    if profile.empty:
        return profile
    return profile.rename(
        columns={
            "top_next_state_label": "next_state_top_label",
            "top_next_state_share": "next_state_top_label_rate",
            "sample_count": "next_state_sample_count",
        }
    )


def build_lifecycle_ui_frame(
    states: pd.DataFrame,
    episodes: pd.DataFrame,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    probability_status: pd.DataFrame | None = None,
    config: LifecycleDisplayConfig = LifecycleDisplayConfig(),
    profile_mode: str = "retrospective",
    profile_cutoff_date: str | pd.Timestamp | None = None,
    state_date_policy: str = "full_run",
    source_probability_report_path: str | None = None,
    expected_probability_metadata: dict[str, object] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, object]]:
    if states.empty:
        empty = pd.DataFrame()
        return empty, empty, empty, empty, empty, {}
    mode = normalize_profile_mode(profile_mode)
    date_policy = normalize_state_date_policy(state_date_policy)
    states_all = states.sort_values(["sector_code", "trade_date"]).copy()
    states_all["trade_date"] = pd.to_datetime(states_all["trade_date"])
    if profile_cutoff_date is None:
        profile_cutoff_date = pd.to_datetime(states_all["trade_date"]).max()
    cutoff = pd.to_datetime(profile_cutoff_date)
    if date_policy == "cutoff_only":
        states_for_ui = states_all[states_all["trade_date"].le(cutoff)].copy()
    else:
        states_for_ui = states_all.copy()
    ui_episodes = build_display_label_episodes(states_for_ui)
    profile_episodes = filter_profile_episodes(episodes, mode, cutoff)
    duration_profile = compute_display_duration_profile(profile_episodes, config.min_duration_profile_samples)
    context = attach_display_episode_context(states_for_ui, ui_episodes)
    context = assign_state_phase(context, duration_profile, config.min_duration_profile_samples)
    duration_map = _completed_duration_map(profile_episodes)
    context["duration_percentile_display"] = [
        _duration_percentile(duration_map.get(str(label), pd.Series(dtype=float)), age)
        for label, age in zip(context["state_label"], context["display_state_age_days"], strict=False)
    ]
    probability_status = probability_status if probability_status is not None else pd.DataFrame()
    probability_status = validate_probability_status_matrix(
        probability_status,
        _expected_probability_metadata(
            states_all,
            profile_mode=mode,
            profile_cutoff_date=cutoff,
            state_date_policy=date_policy,
            extra=expected_probability_metadata,
        ),
    )
    exit_long, exit_profile, exit_distribution = _exit_tendency_long(
        context,
        ui_episodes,
        profile_episodes,
        duration_profile,
        horizons,
        probability_status,
        config,
        profile_cutoff_date=cutoff,
    )
    next_profiles = compute_next_state_tendency_profiles(profile_episodes, duration_profile, config)
    next_label = next_profiles["by_label"]
    next_phase = next_profiles["by_phase"]
    next_age = next_profiles["by_age_bucket"]

    base_cols = [
        "run_id",
        "trade_date",
        "sector_code",
        "sector_name",
        "state_label",
        "display_episode_id",
        "display_state_age_days",
        "display_age_bucket",
        "display_episode_start_date",
        "state_phase",
        "duration_percentile_display",
        "checkpoint_id",
        "state_source",
    ]
    ui = context[[c for c in base_cols if c in context.columns]].copy()
    ui.rename(columns={"checkpoint_id": "source_checkpoint_id"}, inplace=True)
    ui["trade_date"] = pd.to_datetime(ui["trade_date"]).dt.date
    ui["display_episode_start_date"] = pd.to_datetime(ui["display_episode_start_date"]).dt.date

    profile_cols = {
        "median_duration_days": "historical_median_duration_days",
        "p10_duration_days": "historical_p10_duration_days",
        "p25_duration_days": "historical_p25_duration_days",
        "p33_duration_days": "historical_p33_duration_days",
        "p66_duration_days": "historical_p66_duration_days",
        "p75_duration_days": "historical_p75_duration_days",
        "p90_duration_days": "historical_p90_duration_days",
    }
    ui = ui.merge(duration_profile[["state_label", *profile_cols.keys()]] if not duration_profile.empty else pd.DataFrame(columns=["state_label", *profile_cols]), on="state_label", how="left")
    ui.rename(columns=profile_cols, inplace=True)

    if not exit_long.empty:
        exit_long = exit_long.copy()
        exit_long["trade_date"] = pd.to_datetime(exit_long["trade_date"]).dt.date
        for value_col, prefix in [
            ("exit_tendency", "exit_tendency"),
            ("exit_tendency_score", "exit_tendency_score"),
            ("exit_tendency_basis", "exit_tendency_basis"),
            ("probability_status", "probability_status"),
            ("raw_score_used", "raw_score_used"),
            ("raw_basis", "raw_basis"),
        ]:
            pivot = exit_long.pivot_table(
                index=["run_id", "trade_date", "sector_code"],
                columns="horizon_days",
                values=value_col,
                aggfunc="first",
            )
            pivot.columns = [f"{prefix}_{int(col)}d" for col in pivot.columns]
            ui = ui.merge(pivot.reset_index(), on=["run_id", "trade_date", "sector_code"], how="left")
    for horizon in horizons:
        defaults = {
            f"exit_tendency_{horizon}d": "unavailable",
            f"exit_tendency_score_{horizon}d": np.nan,
            f"exit_tendency_basis_{horizon}d": "unavailable",
            f"probability_status_{horizon}d": "missing",
            f"raw_score_used_{horizon}d": False,
            f"raw_basis_{horizon}d": "raw_rank_excluded_missing_policy",
        }
        for col, default in defaults.items():
            if col not in ui.columns:
                ui[col] = default
            ui[col] = ui[col].fillna(default)
        ui[f"exit_tendency_{horizon}d_readiness_status"] = ui[f"probability_status_{horizon}d"]
        ui[f"exit_tendency_{horizon}d_raw_score_used"] = ui[f"raw_score_used_{horizon}d"].fillna(False).astype(bool)
        ui[f"exit_tendency_{horizon}d_raw_basis"] = ui[f"raw_basis_{horizon}d"]
    ui["probability_display_policy"] = "ordinal_tendency_only_no_percent"

    if not next_label.empty:
        label_map = next_label.rename(
            columns={
                "next_state_tendency": "next_state_tendency_label",
                "status": "next_state_tendency_label_status",
                "sample_count": "next_state_tendency_label_sample_count",
                "top_next_state_share": "next_state_tendency_label_top_share",
            }
        )[
            [
                "state_label",
                "next_state_tendency_label",
                "next_state_tendency_label_status",
                "next_state_tendency_label_sample_count",
                "next_state_tendency_label_top_share",
            ]
        ]
        ui = ui.merge(label_map, on="state_label", how="left")
    else:
        ui["next_state_tendency_label"] = "Unavailable"
        ui["next_state_tendency_label_status"] = "unavailable"
        ui["next_state_tendency_label_sample_count"] = 0
        ui["next_state_tendency_label_top_share"] = np.nan
    if not next_phase.empty:
        phase_map = next_phase.rename(
            columns={
                "next_state_tendency": "next_state_tendency_phase_aware",
                "status": "next_state_tendency_phase_status",
                "sample_count": "next_state_tendency_phase_sample_count",
                "top_next_state_share": "next_state_tendency_phase_top_share",
            }
        )[
            [
                "state_label",
                "state_phase",
                "next_state_tendency_phase_aware",
                "next_state_tendency_phase_status",
                "next_state_tendency_phase_sample_count",
                "next_state_tendency_phase_top_share",
            ]
        ]
        ui = ui.merge(phase_map, on=["state_label", "state_phase"], how="left")
    else:
        ui["next_state_tendency_phase_aware"] = "Unavailable"
        ui["next_state_tendency_phase_status"] = "unavailable"
        ui["next_state_tendency_phase_sample_count"] = 0
        ui["next_state_tendency_phase_top_share"] = np.nan
    if not next_age.empty:
        age_map = next_age.rename(
            columns={
                "age_bucket": "display_age_bucket",
                "next_state_tendency": "next_state_tendency_age_bucket",
                "status": "next_state_tendency_age_status",
                "sample_count": "next_state_tendency_age_sample_count",
                "top_next_state_share": "next_state_tendency_age_top_share",
            }
        )[
            [
                "state_label",
                "display_age_bucket",
                "next_state_tendency_age_bucket",
                "next_state_tendency_age_status",
                "next_state_tendency_age_sample_count",
                "next_state_tendency_age_top_share",
            ]
        ]
        ui = ui.merge(age_map, on=["state_label", "display_age_bucket"], how="left")
    else:
        ui["next_state_tendency_age_bucket"] = "Unavailable"
        ui["next_state_tendency_age_status"] = "unavailable"
        ui["next_state_tendency_age_sample_count"] = 0
        ui["next_state_tendency_age_top_share"] = np.nan
    ui["next_state_tendency"] = ui["next_state_tendency_label"]
    for col in ["next_state_tendency", "next_state_tendency_label", "next_state_tendency_phase_aware", "next_state_tendency_age_bucket"]:
        ui[col] = ui[col].fillna("Unavailable")
    for col in ["next_state_tendency_label_status", "next_state_tendency_phase_status", "next_state_tendency_age_status"]:
        ui[col] = ui[col].fillna("unavailable")
    for col in ["next_state_tendency_label_sample_count", "next_state_tendency_phase_sample_count", "next_state_tendency_age_sample_count"]:
        ui[col] = pd.to_numeric(ui[col], errors="coerce").fillna(0).astype(int)
    for col in ["next_state_tendency_label_top_share", "next_state_tendency_phase_top_share", "next_state_tendency_age_top_share"]:
        ui[col] = pd.to_numeric(ui[col], errors="coerce")
    ui["next_state_tendency_confidence"] = ui["next_state_tendency_label_top_share"]
    ui.loc[ui["next_state_tendency_label_status"].ne("usable"), "next_state_tendency_confidence"] = np.nan
    ui["next_state_tendency_sample_count"] = ui["next_state_tendency_label_sample_count"]

    ui["profile_mode"] = mode
    ui["profile_cutoff_date"] = cutoff.date()
    ui["state_date_policy"] = date_policy
    if not profile_episodes.empty:
        ui["profile_sample_window_start"] = pd.to_datetime(profile_episodes["episode_end_date"]).min().date()
        ui["profile_sample_window_end"] = pd.to_datetime(profile_episodes["episode_end_date"]).max().date()
    else:
        ui["profile_sample_window_start"] = pd.NaT
        ui["profile_sample_window_end"] = pd.NaT
    ui["source_run_id"] = ui["run_id"]
    ui["source_probability_run_id"] = Path(source_probability_report_path).name if source_probability_report_path else None
    ui["created_at"] = pd.Timestamp.now(tz=None)

    metadata = {
        "run_id": str(states_all["run_id"].iloc[0]),
        "profile_run_id": f"{states_all['run_id'].iloc[0]}:{mode}:{cutoff.date()}:{date_policy}",
        "profile_mode": mode,
        "profile_cutoff_date": str(cutoff.date()),
        "state_date_policy": date_policy,
        "source_probability_report_path": source_probability_report_path or "",
        "source_probability_run_id": Path(source_probability_report_path).name if source_probability_report_path else "",
        "horizons": list(horizons),
        "state_labels": sorted(states_all["state_label"].dropna().astype(str).unique().tolist()),
        "completed_episode_count": int(len(profile_episodes)),
        "profile_window_start": None if profile_episodes.empty else str(pd.to_datetime(profile_episodes["episode_end_date"]).min().date()),
        "profile_window_end": None if profile_episodes.empty else str(pd.to_datetime(profile_episodes["episode_end_date"]).max().date()),
        "state_row_count": int(len(states_for_ui)),
        "state_window_start": None if states_for_ui.empty else str(pd.to_datetime(states_for_ui["trade_date"]).min().date()),
        "state_window_end": None if states_for_ui.empty else str(pd.to_datetime(states_for_ui["trade_date"]).max().date()),
        "created_at": str(pd.Timestamp.now(tz=None)),
        "notes": "state lifecycle research only; not a price prediction, trading signal, or sector recommendation",
    }
    return ui, duration_profile, exit_profile, exit_distribution, exit_long, {"metadata": metadata, "next_profiles": next_profiles}


def build_lifecycle_ui_daily(storage: DuckDBStorage, run_id: str, horizons: tuple[int, ...] = DEFAULT_HORIZONS) -> pd.DataFrame:
    states = read_hsmm_states(storage, run_id)
    episodes = build_display_label_episodes(states)
    run_metadata = _read_hsmm_run_contract_metadata(storage, run_id)
    probability_status = _read_probability_status(run_id, expected_metadata=run_metadata)
    config = LifecycleDisplayConfig(horizons=tuple(horizons))
    ui, *_ = build_lifecycle_ui_frame(
        states,
        episodes,
        tuple(horizons),
        probability_status,
        config,
        expected_probability_metadata=run_metadata,
    )
    return ui


def _wp8_daily_alias_columns(horizons: tuple[int, ...]) -> list[str]:
    return [
        f"exit_tendency_{horizon}d_{suffix}"
        for horizon in horizons
        for suffix in WP8_DAILY_ALIAS_SUFFIXES
    ] + [f"raw_basis_{horizon}d" for horizon in horizons]


def _clear_lifecycle_profile_outputs(
    storage: DuckDBStorage,
    *,
    run_id: str,
    profile_mode: str,
    profile_cutoff_date: object,
    state_date_policy: str,
) -> dict[str, int]:
    cutoff = pd.to_datetime(profile_cutoff_date, errors="coerce")
    if pd.isna(cutoff):
        return {}
    cutoff_date = cutoff.date()
    statements = [
        (
            "hsmm_display_label_episodes",
            "run_id = ?",
            [run_id],
        ),
        (
            "hsmm_lifecycle_ui_daily",
            "run_id = ? AND profile_mode = ? AND profile_cutoff_date = ? AND state_date_policy = ?",
            [run_id, profile_mode, cutoff_date, state_date_policy],
        ),
        (
            "hsmm_lifecycle_profile_metadata",
            "run_id = ? AND profile_mode = ? AND profile_cutoff_date = ? AND state_date_policy = ?",
            [run_id, profile_mode, cutoff_date, state_date_policy],
        ),
        (
            "hsmm_lifecycle_duration_profile",
            "run_id = ? AND profile_mode = ? AND profile_cutoff_date = ?",
            [run_id, profile_mode, cutoff_date],
        ),
        (
            "hsmm_next_state_tendency_profile",
            "run_id = ? AND profile_mode = ? AND profile_cutoff_date = ?",
            [run_id, profile_mode, cutoff_date],
        ),
    ]
    deleted: dict[str, int] = {}
    with storage.connect() as con:
        for table, where_sql, params in statements:
            before = int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}", params).fetchone()[0])
            con.execute(f"DELETE FROM {table} WHERE {where_sql}", params)
            after = int(con.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}", params).fetchone()[0])
            deleted[table] = before - after
    return deleted


def build_ui_field_policy() -> pd.DataFrame:
    rows = [
        ("state_label", True, "show", "状态标签不是交易信号"),
        ("display_state_age_days", True, "show", "使用交易日口径"),
        ("state_phase", True, "show", "基于历史 display-label 持续时间分布"),
        ("duration_percentile_display", True, "show", "年龄分位用于生命周期解释"),
        ("exit_tendency_5d", True, "show", "退出倾向不是概率"),
        ("exit_tendency_10d", True, "show", "退出倾向不是概率"),
        ("exit_tendency_20d", True, "detail_or_hide", "20日口径容易饱和，不作为主字段"),
        ("next_state_tendency_phase_aware", True, "show_if_status_usable_else_mixed", "下一个状态倾向来自历史 display-label 统计"),
        ("raw_p_exit_*", False, "hide", "未经验证不能展示百分比"),
        ("calibrated_p_exit_*", False, "hide", "全局校准未通过"),
        ("next_state_probability", False, "hide", "下一个状态概率未全局验证"),
    ]
    return pd.DataFrame(rows, columns=["field_name", "display_allowed", "display_type", "required_disclaimer"])


def build_ui_text_policy_audit(ui_root: str | Path = "src/ui") -> pd.DataFrame:
    root = Path(ui_root)
    rows: list[dict[str, object]] = []
    for path in sorted(root.rglob("*.py")):
        if path.name in {"readiness_policy.py", "causal_boundary.py", "evidence_badges.py"}:
            continue
        text = path.read_text(encoding="utf-8")
        for line_no, line in enumerate(text.splitlines(), start=1):
            for finding in find_misleading_probability_claims([line]):
                rows.append(
                    {
                        "file": str(path),
                        "line_number": line_no,
                        "matched_text": finding["phrase"],
                        "severity": "error",
                        "allowed_exception": False,
                        "reason": "misleading probability claim in controlled UI text",
                    }
                )
            for term in FORBIDDEN_UI_TERMS:
                if term in MISLEADING_PROBABILITY_CLAIMS:
                    continue
                if term not in line:
                    continue
                is_lifecycle_page = path.name == "lifecycle_page.py"
                allowed_exception = not is_lifecycle_page
                rows.append(
                    {
                        "file": str(path),
                        "line_number": line_no,
                        "matched_text": term,
                        "severity": "error" if is_lifecycle_page else "warning",
                        "allowed_exception": bool(allowed_exception),
                        "reason": "legacy page outside lifecycle UI" if allowed_exception else "forbidden visible lifecycle UI text",
                    }
                )
    return pd.DataFrame(rows, columns=["file", "line_number", "matched_text", "severity", "allowed_exception", "reason"])


def summarize_text_policy_audit(text_audit: pd.DataFrame) -> dict[str, int]:
    if text_audit.empty:
        return {
            "text_audit_error_count": 0,
            "text_audit_warning_count": 0,
            "lifecycle_page_error_count": 0,
            "legacy_warning_count": 0,
        }
    allowed = text_audit["allowed_exception"].astype(bool) if "allowed_exception" in text_audit.columns else pd.Series(False, index=text_audit.index)
    severity = text_audit["severity"].astype(str) if "severity" in text_audit.columns else pd.Series("", index=text_audit.index)
    file_col = text_audit["file"].astype(str) if "file" in text_audit.columns else pd.Series("", index=text_audit.index)
    errors = severity.eq("error") & ~allowed
    warnings = severity.eq("warning")
    lifecycle_errors = errors & file_col.str.endswith("lifecycle_page.py")
    legacy_warnings = warnings & allowed
    return {
        "text_audit_error_count": int(errors.sum()),
        "text_audit_warning_count": int(warnings.sum()),
        "lifecycle_page_error_count": int(lifecycle_errors.sum()),
        "legacy_warning_count": int(legacy_warnings.sum()),
    }


def _summary_markdown(
    run_id: str,
    states: pd.DataFrame,
    episodes: pd.DataFrame,
    duration_profile: pd.DataFrame,
    exit_distribution: pd.DataFrame,
    policy_audit: pd.DataFrame,
    next_profiles: dict[str, pd.DataFrame],
    ui: pd.DataFrame,
    config: LifecycleDisplayConfig,
    metadata: dict[str, object],
    text_audit: pd.DataFrame,
) -> str:
    key_cols = ["run_id", "profile_mode", "profile_cutoff_date", "state_date_policy", "trade_date", "sector_code"]
    duplicate_count = int(ui.duplicated([c for c in key_cols if c in ui.columns]).sum()) if not ui.empty else 0
    valid_tendency = True
    for horizon in config.horizons:
        col = f"exit_tendency_{horizon}d"
        if col in ui.columns:
            valid_tendency = valid_tendency and ui[col].isin(EXIT_TENDENCIES).all()
    policy_violations = int(policy_audit["policy_violation"].sum()) if "policy_violation" in policy_audit.columns and not policy_audit.empty else 0
    text_counts = summarize_text_policy_audit(text_audit)
    text_audit_errors = text_counts["text_audit_error_count"]
    ready = bool(not states.empty and not episodes.empty and not ui.empty and duplicate_count == 0 and valid_tendency and policy_violations == 0 and text_audit_errors == 0)
    conclusion = "LifecycleUIV0ReadyForInternalUse" if ready else "InvalidDueToLifecycleUIPolicyFailure"
    state_dist = ui["state_label"].value_counts(dropna=False).to_string() if "state_label" in ui.columns and not ui.empty else "_none_"
    phase_dist = ui["state_phase"].value_counts(dropna=False).to_string() if "state_phase" in ui.columns and not ui.empty else "_none_"
    tendency_lines = []
    for horizon in config.horizons:
        col = f"exit_tendency_{horizon}d"
        if col in ui.columns:
            tendency_lines.append(f"{col}\n{ui[col].value_counts(dropna=False).to_string()}")
    raw_counts = []
    for horizon in config.horizons:
        status_col = f"probability_status_{horizon}d"
        raw_col = f"raw_score_used_{horizon}d"
        if status_col in ui.columns and raw_col in ui.columns:
            raw_counts.append(ui.groupby([status_col, raw_col], observed=True).size().rename("row_count").reset_index().assign(horizon_days=horizon).to_string(index=False))
    saturation = exit_distribution[
        exit_distribution["horizon_days"].eq(20) & exit_distribution["low_discrimination"].astype(bool)
    ] if not exit_distribution.empty else pd.DataFrame()
    explicit_note = "This report is for state lifecycle research only. It is not a price prediction, trading signal, or sector recommendation."
    content = f"""# HSMM Lifecycle UI v0 Report

## Conclusion

`{conclusion}`

{explicit_note}

## Run

- run_id: `{run_id}`
- profile_mode: `{metadata.get('profile_mode')}`
- profile_cutoff_date: `{metadata.get('profile_cutoff_date')}`
- state_date_policy: `{metadata.get('state_date_policy')}`
- row_count: {len(ui)}
- duplicate_sector_date_key_count: {duplicate_count}
- state_window: `{metadata.get('state_window_start')}` to `{metadata.get('state_window_end')}`
- profile_sample_window: `{metadata.get('profile_window_start')}` to `{metadata.get('profile_window_end')}`
- profile_completed_episode_count: {metadata.get('completed_episode_count')}

## Config

```json
{json.dumps(asdict(config), ensure_ascii=False, indent=2)}
```

## State Label Distribution

```text
{state_dist}
```

## State Phase Distribution

```text
{phase_dist}
```

## Duration Profile

{duration_profile.to_string(index=False) if not duration_profile.empty else '_none_'}

## Exit Tendency Distribution By Horizon

```text
{chr(10).join(tendency_lines) if tendency_lines else '_none_'}
```

## Raw Score Used Counts By Horizon And Probability Status

```text
{chr(10).join(raw_counts) if raw_counts else '_none_'}
```

## 20d Saturation Warning

{saturation.to_string(index=False) if not saturation.empty else 'No 20d low-discrimination warning.'}

## Next State Tendency Summary

### By Label
{next_profiles.get('by_label', pd.DataFrame()).to_string(index=False) if not next_profiles.get('by_label', pd.DataFrame()).empty else '_none_'}

### By Phase
{next_profiles.get('by_phase', pd.DataFrame()).head(20).to_string(index=False) if not next_profiles.get('by_phase', pd.DataFrame()).empty else '_none_'}

### By Age Bucket
{next_profiles.get('by_age_bucket', pd.DataFrame()).head(20).to_string(index=False) if not next_profiles.get('by_age_bucket', pd.DataFrame()).empty else '_none_'}

## UI Readiness Verdict

- valid_tendency_values: {valid_tendency}
- policy_violation_count: {policy_violations}
- text_audit_error_count: {text_counts['text_audit_error_count']}
- text_audit_warning_count: {text_counts['text_audit_warning_count']}
- lifecycle_page_error_count: {text_counts['lifecycle_page_error_count']}
- legacy_warning_count: {text_counts['legacy_warning_count']}
- ui_field_policy: raw and calibrated exit probabilities are hidden.
"""
    return content


def write_lifecycle_ui_outputs(
    storage: DuckDBStorage,
    run_id: str,
    output_dir: str | Path,
    horizons: tuple[int, ...] = DEFAULT_HORIZONS,
    profile_mode: str = "retrospective",
    profile_cutoff_date: str | None = None,
    state_date_policy: str = "full_run",
    probability_report: str | Path | None = None,
    ui_text_audit_root: str | Path = "src/ui",
) -> dict[str, pd.DataFrame | dict[str, object]]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    config = LifecycleDisplayConfig(horizons=tuple(horizons))
    states = read_hsmm_states(storage, run_id)
    episodes = build_display_label_episodes(states)
    run_metadata = _read_hsmm_run_contract_metadata(storage, run_id)
    probability_report_path = Path(probability_report) if probability_report else None
    probability_status = _read_probability_status(run_id, probability_report_path, expected_metadata=run_metadata)
    ui, duration_profile, exit_profile, exit_distribution, exit_long, extras = build_lifecycle_ui_frame(
        states,
        episodes,
        tuple(horizons),
        probability_status,
        config,
        profile_mode=profile_mode,
        profile_cutoff_date=profile_cutoff_date,
        state_date_policy=state_date_policy,
        source_probability_report_path=str(probability_report_path) if probability_report_path else "",
        expected_probability_metadata=run_metadata,
    )
    metadata = extras["metadata"]
    next_profiles: dict[str, pd.DataFrame] = extras["next_profiles"]
    profile_duration = build_profile_specific_duration_profile(duration_profile, episodes, filter_profile_episodes(episodes, profile_mode, metadata["profile_cutoff_date"]), metadata)
    policy = build_ui_field_policy()
    policy_audit = build_exit_tendency_policy_audit(exit_long)
    text_audit = build_ui_text_policy_audit(ui_text_audit_root)

    episodes.to_csv(output / "display_label_episodes.csv", index=False)
    profile_duration.to_csv(output / "duration_profile_by_display_label.csv", index=False)
    profile_duration.to_csv(output / "profile_specific_duration_profile.csv", index=False)
    exit_profile.to_csv(output / "exit_tendency_profile.csv", index=False)
    exit_distribution.to_csv(output / "exit_tendency_distribution.csv", index=False)
    policy_audit.to_csv(output / "exit_tendency_policy_audit.csv", index=False)
    next_profiles["by_label"].to_csv(output / "next_state_tendency_profile.csv", index=False)
    next_profiles["by_phase"].to_csv(output / "next_state_tendency_by_phase.csv", index=False)
    next_profiles["by_age_bucket"].to_csv(output / "next_state_tendency_by_age_bucket.csv", index=False)
    ui.to_csv(output / "lifecycle_ui_daily.csv", index=False)
    ui.head(100).to_csv(output / "lifecycle_ui_daily_head100.csv", index=False)
    policy.to_csv(output / "ui_field_policy.csv", index=False)
    text_audit.to_csv(output / "ui_text_policy_audit.csv", index=False)
    (output / "config.json").write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "profile_metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (output / "summary.md").write_text(
        _summary_markdown(run_id, states, episodes, profile_duration, exit_distribution, policy_audit, next_profiles, ui, config, metadata, text_audit),
        encoding="utf-8",
    )

    metadata_for_db = metadata.copy()
    metadata_for_db["horizons"] = json.dumps(metadata.get("horizons", []), ensure_ascii=False)
    metadata_for_db["state_labels"] = json.dumps(metadata.get("state_labels", []), ensure_ascii=False)
    metadata_df = pd.DataFrame([metadata_for_db])
    lifecycle_cleanup_summary = _clear_lifecycle_profile_outputs(
        storage,
        run_id=run_id,
        profile_mode=str(metadata["profile_mode"]),
        profile_cutoff_date=metadata["profile_cutoff_date"],
        state_date_policy=str(metadata["state_date_policy"]),
    )
    if not episodes.empty:
        storage.upsert_df("hsmm_display_label_episodes", episodes, ["run_id", "sector_code", "episode_id"])
    if not ui.empty:
        ui_for_db = ui.drop(columns=_wp8_daily_alias_columns(tuple(horizons)), errors="ignore")
        storage.upsert_df(
            "hsmm_lifecycle_ui_daily",
            ui_for_db,
            ["run_id", "profile_mode", "profile_cutoff_date", "state_date_policy", "trade_date", "sector_code"],
        )
    if not metadata_df.empty:
        storage.upsert_df("hsmm_lifecycle_profile_metadata", metadata_df, ["run_id", "profile_run_id"])
    if not profile_duration.empty:
        storage.upsert_df(
            "hsmm_lifecycle_duration_profile",
            profile_duration,
            ["run_id", "profile_mode", "profile_cutoff_date", "state_label"],
        )
    profile_rows: list[pd.DataFrame] = []
    for name, frame in next_profiles.items():
        if frame.empty:
            continue
        out = frame.copy()
        out["run_id"] = run_id
        out["profile_mode"] = metadata["profile_mode"]
        out["profile_cutoff_date"] = metadata["profile_cutoff_date"]
        if "state_phase" not in out.columns:
            out["state_phase"] = "__ALL__"
        if "age_bucket" not in out.columns:
            out["age_bucket"] = "__ALL__"
        profile_rows.append(out)
    if profile_rows:
        storage.upsert_df(
            "hsmm_next_state_tendency_profile",
            pd.concat(profile_rows, ignore_index=True),
            ["run_id", "profile_mode", "profile_cutoff_date", "state_label", "state_phase", "age_bucket"],
        )
    return {
        "states": states,
        "display_label_episodes": episodes,
        "display_duration_profile": profile_duration,
        "exit_tendency_profile": exit_profile,
        "exit_tendency_distribution": exit_distribution,
        "exit_tendency_policy_audit": policy_audit,
        "next_state_tendency_profile": next_profiles["by_label"],
        "next_state_tendency_by_phase": next_profiles["by_phase"],
        "next_state_tendency_by_age_bucket": next_profiles["by_age_bucket"],
        "lifecycle_ui_daily": ui,
        "ui_field_policy": policy,
        "ui_text_policy_audit": text_audit,
        "metadata": metadata,
        "lifecycle_cleanup_summary": lifecycle_cleanup_summary,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HSMM display-label lifecycle UI data")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--profile-mode", default="retrospective", choices=["retrospective", "latest_asof"])
    parser.add_argument("--profile-cutoff-date", default=None)
    parser.add_argument("--state-date-policy", default="full_run", choices=list(STATE_DATE_POLICIES))
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--probability-report", default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    storage = DuckDBStorage(args.db)
    storage.init_schema()
    result = write_lifecycle_ui_outputs(
        storage,
        args.run_id,
        Path(args.output),
        parse_horizons(args.horizons),
        profile_mode=args.profile_mode,
        profile_cutoff_date=args.profile_cutoff_date,
        state_date_policy=args.state_date_policy,
        probability_report=args.probability_report,
    )
    print(f"output_dir: {args.output}")
    print(f"profile_mode: {args.profile_mode}")
    print(f"state_date_policy: {args.state_date_policy}")
    print(f"display_label_episodes: {len(result['display_label_episodes'])}")
    print(f"lifecycle_ui_daily: {len(result['lifecycle_ui_daily'])}")


if __name__ == "__main__":
    main()
