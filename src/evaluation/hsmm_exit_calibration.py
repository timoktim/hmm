from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


AGE_BINS = [0, 1, 3, 5, 10, 20, np.inf]
AGE_LABELS = ["1", "2-3", "4-5", "6-10", "11-20", "21+"]
DURATION_BINS = [-0.001, 0.2, 0.4, 0.6, 0.8, 1.001]
DURATION_LABELS = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
PROB_BINS = [-0.001, 0.2, 0.4, 0.6, 0.8, 1.001]
PROB_LABELS = ["0-20%", "20-40%", "40-60%", "60-80%", "80-100%"]
TARGET_TYPE_BY_LEGACY_NAME = {
    "state_id": "state_id_exit",
    "state_id_exit": "state_id_exit",
    "display_label": "display_label_exit",
    "display_label_exit": "display_label_exit",
}
TARGET_VALUE_COLUMN = {
    "state_id_exit": "state_id",
    "display_label_exit": "state_label",
}


@dataclass
class EmpiricalExitCalibrator:
    specific: pd.DataFrame
    state_phase: pd.DataFrame
    state: pd.DataFrame
    global_rate: pd.DataFrame
    metadata: dict[str, Any]

    def to_json(self) -> str:
        payload = {
            "specific": self.specific.to_dict("records"),
            "state_phase": self.state_phase.to_dict("records"),
            "state": self.state.to_dict("records"),
            "global_rate": self.global_rate.to_dict("records"),
            "metadata": self.metadata,
        }
        return json.dumps(payload, ensure_ascii=False, default=str, indent=2)


def normalize_target_type(target_type: str) -> str:
    normalized = TARGET_TYPE_BY_LEGACY_NAME.get(str(target_type).strip())
    if normalized is None:
        allowed = ", ".join(sorted(set(TARGET_TYPE_BY_LEGACY_NAME.values())))
        raise ValueError(f"Unsupported target_type: {target_type!r}. Allowed: {allowed}")
    return normalized


def infer_target_type(states: pd.DataFrame) -> str:
    return "state_id_exit" if "state_id" in states.columns else "display_label_exit"


def _raw_score_column(columns: set[str], horizon: int, target_type: str) -> tuple[str | None, str | None]:
    target_type = normalize_target_type(target_type)
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
            return column, target_type
    return None, None


def _actual_exit_within_trading_rows(
    group: pd.DataFrame,
    idx: int,
    horizon: int,
    target_type: str,
) -> tuple[bool | None, pd.Timestamp | None, pd.Timestamp | None]:
    value_col = TARGET_VALUE_COLUMN[normalize_target_type(target_type)]
    if value_col not in group.columns:
        return None, None, None
    current = str(group.loc[idx, value_col])
    future = group.iloc[idx + 1 : idx + 1 + horizon]
    horizon_end_date = pd.Timestamp(future["trade_date"].iloc[-1]) if len(future) == horizon else None
    if len(future) < horizon:
        return None, None, horizon_end_date
    changed = future[future[value_col].astype(str).ne(current)]
    if not changed.empty:
        return True, pd.Timestamp(changed.iloc[0]["trade_date"]), horizon_end_date
    return False, None, horizon_end_date


def _add_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    age_source = "duration_model_age_days" if "duration_model_age_days" in out.columns else "state_age_days"
    out["state_age_bucket"] = pd.cut(pd.to_numeric(out[age_source], errors="coerce"), bins=AGE_BINS, labels=AGE_LABELS)
    out["duration_percentile_bucket"] = pd.cut(pd.to_numeric(out["duration_percentile"], errors="coerce"), bins=DURATION_BINS, labels=DURATION_LABELS)
    out["raw_p_exit_bucket"] = pd.cut(pd.to_numeric(out["raw_p_exit"], errors="coerce"), bins=PROB_BINS, labels=PROB_LABELS)
    return out


def build_exit_calibration_dataset(
    states: pd.DataFrame,
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
    target_type: str | None = None,
) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    target_type = normalize_target_type(target_type or infer_target_type(states))
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    rows: list[dict[str, object]] = []
    for _, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        columns = set(group.columns)
        for idx in range(len(group)):
            for horizon in horizons:
                raw_col, raw_basis = _raw_score_column(columns, horizon, target_type)
                if raw_col is None:
                    continue
                actual, realized_exit_date, horizon_end_date = _actual_exit_within_trading_rows(group, idx, horizon, target_type)
                if actual is None and horizon_end_date is None:
                    continue
                row = group.loc[idx]
                raw_p = pd.to_numeric(pd.Series([row.get(raw_col)]), errors="coerce").iloc[0]
                rows.append(
                    {
                        "sector_code": row.get("sector_code"),
                        "trade_date": pd.Timestamp(row.get("trade_date")),
                        "state_label": row.get("state_label"),
                        "state_phase": row.get("state_phase"),
                        "state_age_days": row.get("state_age_days"),
                        "model_state_age_days": row.get("model_state_age_days", row.get("state_age_days_by_id", row.get("state_age_days"))),
                        "label_state_age_days": row.get("label_state_age_days", row.get("state_age_days_by_label", row.get("state_age_days"))),
                        "duration_model_age_days": row.get("duration_model_age_days", row.get("model_state_age_days", row.get("state_age_days_by_id", row.get("state_age_days")))),
                        "display_state_age_days": row.get("display_state_age_days", row.get("label_state_age_days", row.get("state_age_days_by_label", row.get("state_age_days")))),
                        "duration_percentile": row.get("duration_percentile"),
                        "horizon_days": int(horizon),
                        "raw_p_exit": float(raw_p) if pd.notna(raw_p) else np.nan,
                        "actual_exit_within_h_trading_days": bool(actual) if actual is not None else None,
                        "target_type": target_type,
                        "raw_p_exit_target_type": raw_basis,
                        "actual_exit_target_type": target_type,
                        "realized_exit_date": realized_exit_date,
                        "horizon_end_date": horizon_end_date,
                        "target_observation_status": (
                            "observed_positive"
                            if actual is True
                            else "observed_negative"
                            if actual is False
                            else "unknown"
                        ),
                    }
                )
    return _add_buckets(pd.DataFrame(rows)) if rows else pd.DataFrame()


def _empty_rate_table(group_cols: list[str]) -> pd.DataFrame:
    return pd.DataFrame(columns=[*group_cols, "sample_count", "empirical_exit_rate", "mean_raw_p_exit"])


def _rate_table(df: pd.DataFrame, group_cols: list[str], min_bucket_count: int) -> pd.DataFrame:
    if df.empty:
        return _empty_rate_table(group_cols)
    grouped = (
        df.groupby(group_cols, observed=True)
        .agg(
            sample_count=("actual_exit_within_h_trading_days", "size"),
            empirical_exit_rate=("actual_exit_within_h_trading_days", "mean"),
            mean_raw_p_exit=("raw_p_exit", "mean"),
        )
        .reset_index()
    )
    out = grouped[grouped["sample_count"] >= min_bucket_count].copy()
    if not out.empty:
        out["mean_predicted_exit_probability"] = out["mean_raw_p_exit"]
    return out


def fit_empirical_exit_calibrator(
    calibration_df: pd.DataFrame,
    min_bucket_count: int = 50,
    train_end_date: str | pd.Timestamp | None = None,
    allow_in_sample: bool = False,
    target_type: str | None = None,
) -> EmpiricalExitCalibrator:
    train = calibration_df.copy()

    def date_series(frame: pd.DataFrame, column: str) -> pd.Series:
        if column not in frame.columns:
            return pd.Series(pd.NaT, index=frame.index)
        return pd.to_datetime(frame[column], errors="coerce")

    def bool_positive(series: pd.Series) -> pd.Series:
        return series.map(lambda value: isinstance(value, (bool, np.bool_)) and bool(value))

    if target_type is None:
        if "target_type" in train.columns and train["target_type"].dropna().nunique() == 1:
            target_type = str(train["target_type"].dropna().iloc[0])
        else:
            target_type = "state_id_exit"
    target_type = normalize_target_type(target_type)
    if "target_type" not in train.columns:
        train["target_type"] = target_type
    if "raw_p_exit_target_type" not in train.columns:
        train["raw_p_exit_target_type"] = target_type
    if "actual_exit_target_type" not in train.columns:
        train["actual_exit_target_type"] = target_type
    target_aligned = bool(
        not train.empty
        and train["target_type"].astype(str).eq(target_type).all()
        and train["raw_p_exit_target_type"].astype(str).eq(target_type).all()
        and train["actual_exit_target_type"].astype(str).eq(target_type).all()
    )
    if train_end_date is None and not allow_in_sample:
        train = train.iloc[0:0].copy()
        cutoff_policy = "fail_closed_missing_train_end_date"
    else:
        cutoff_policy = "explicit_allow_in_sample" if train_end_date is None else "train_end_date_horizon_cutoff"
        if train_end_date is not None and not train.empty:
            cutoff = pd.to_datetime(train_end_date)
            trade_date = pd.to_datetime(train["trade_date"], errors="coerce")
            if "horizon_end_date" in train.columns:
                horizon_end = pd.to_datetime(train["horizon_end_date"], errors="coerce")
            else:
                horizon_end = trade_date + pd.to_timedelta(pd.to_numeric(train["horizon_days"], errors="coerce"), unit="D")
                train["horizon_end_date"] = horizon_end
            realized_exit = date_series(train, "realized_exit_date")
            actual_positive = bool_positive(train["actual_exit_within_h_trading_days"])
            train["excluded_post_train_horizon"] = horizon_end > cutoff
            train["excluded_post_train_positive"] = actual_positive & realized_exit.notna() & (realized_exit > cutoff)
            train["censored_by_train_end"] = train["excluded_post_train_horizon"] | train["excluded_post_train_positive"]
            train = train[
                (trade_date <= cutoff)
                & (~train["excluded_post_train_horizon"])
                & (~train["excluded_post_train_positive"])
            ].copy()
    if not train.empty:
        observed = train["actual_exit_within_h_trading_days"].map(lambda value: isinstance(value, (bool, np.bool_)))
        train = train[observed].copy()
        train = train[pd.to_numeric(train["raw_p_exit"], errors="coerce").notna()].copy()
        train = train[
            train["target_type"].astype(str).eq(target_type)
            & train["raw_p_exit_target_type"].astype(str).eq(target_type)
            & train["actual_exit_target_type"].astype(str).eq(target_type)
        ].copy()
    train = _add_buckets(train)
    specific_cols = ["target_type", "state_label", "state_phase", "state_age_bucket", "duration_percentile_bucket", "raw_p_exit_bucket", "horizon_days"]
    state_phase_cols = ["target_type", "state_label", "state_phase", "horizon_days"]
    state_cols = ["target_type", "state_label", "horizon_days"]
    global_cols = ["target_type", "horizon_days"]
    excluded_post_train_horizon_count = int(calibration_df.get("excluded_post_train_horizon", pd.Series(False, index=calibration_df.index)).fillna(False).sum()) if not calibration_df.empty else 0
    if train_end_date is not None and not calibration_df.empty:
        cutoff = pd.to_datetime(train_end_date)
        source_trade = pd.to_datetime(calibration_df["trade_date"], errors="coerce")
        if "horizon_end_date" in calibration_df.columns:
            source_horizon_end = pd.to_datetime(calibration_df["horizon_end_date"], errors="coerce")
        else:
            source_horizon_end = source_trade + pd.to_timedelta(pd.to_numeric(calibration_df["horizon_days"], errors="coerce"), unit="D")
        excluded_post_train_horizon_count = int((source_horizon_end > cutoff).sum())
        actual_positive = bool_positive(calibration_df["actual_exit_within_h_trading_days"])
        realized_exit = date_series(calibration_df, "realized_exit_date")
        excluded_post_train_positive_count = int((actual_positive & realized_exit.notna() & (realized_exit > cutoff)).sum())
        censored_row_count = int((source_horizon_end > cutoff).sum() + (actual_positive & realized_exit.notna() & (realized_exit > cutoff)).sum())
    else:
        excluded_post_train_positive_count = 0
        censored_row_count = 0 if allow_in_sample else int(len(calibration_df))
    usable = bool(target_aligned and not train.empty and (train_end_date is not None or allow_in_sample))
    metadata = {
        "train_start": str(pd.to_datetime(train["trade_date"]).min().date()) if not train.empty else None,
        "train_end": str(pd.to_datetime(train["trade_date"]).max().date()) if not train.empty else None,
        "training_rows": int(len(train)),
        "min_bucket_count": int(min_bucket_count),
        "target_type": target_type,
        "raw_p_exit_target_type": target_type if target_aligned else "mismatch_or_missing",
        "actual_exit_target_type": target_type,
        "target_type_aligned": target_aligned,
        "train_label_cutoff_policy": cutoff_policy,
        "censored_row_count": censored_row_count,
        "excluded_post_train_horizon_count": excluded_post_train_horizon_count,
        "excluded_post_train_positive_count": excluded_post_train_positive_count,
        "allow_in_sample": bool(allow_in_sample),
        "calibration_status": "usable" if usable else "failed",
        "usable_probability": usable,
    }
    return EmpiricalExitCalibrator(
        specific=_rate_table(train, specific_cols, min_bucket_count),
        state_phase=_rate_table(train, state_phase_cols, max(5, min_bucket_count // 2)),
        state=_rate_table(train, state_cols, max(5, min_bucket_count // 2)),
        global_rate=_rate_table(train, global_cols, 1),
        metadata=metadata,
    )


def _lookup_rate(row: pd.Series, calibrator: EmpiricalExitCalibrator) -> float:
    target_type = str(row.get("target_type") or calibrator.metadata.get("target_type") or "state_id_exit")
    tables = [
        (
            calibrator.specific,
            ["target_type", "state_label", "state_phase", "state_age_bucket", "duration_percentile_bucket", "raw_p_exit_bucket", "horizon_days"],
        ),
        (calibrator.state_phase, ["target_type", "state_label", "state_phase", "horizon_days"]),
        (calibrator.state, ["target_type", "state_label", "horizon_days"]),
        (calibrator.global_rate, ["target_type", "horizon_days"]),
    ]
    row = row.copy()
    row["target_type"] = target_type
    for table, cols in tables:
        if table.empty:
            continue
        mask = pd.Series(True, index=table.index)
        for col in cols:
            mask &= table[col].astype(str).eq(str(row.get(col)))
        match = table[mask]
        if not match.empty:
            return float(match.iloc[0]["empirical_exit_rate"])
    return float(row.get("raw_p_exit", np.nan))


def apply_exit_calibrator(calibration_df: pd.DataFrame, calibrator: EmpiricalExitCalibrator) -> pd.DataFrame:
    if calibration_df.empty:
        return calibration_df.copy()
    out = _add_buckets(calibration_df)
    out["calibration_status"] = calibrator.metadata.get("calibration_status", "unknown")
    if not bool(calibrator.metadata.get("usable_probability")):
        out["calibrated_p_exit"] = np.nan
        out["probability_status"] = "invalid"
        return out
    out["calibrated_p_exit"] = out.apply(lambda row: _lookup_rate(row, calibrator), axis=1)
    out["calibrated_p_exit"] = pd.to_numeric(out["calibrated_p_exit"], errors="coerce").clip(0.0, 1.0)
    out["probability_status"] = "usable_probability"
    return out


def summarize_exit_calibration(calibration_df: pd.DataFrame, probability_col: str, probability_type: str) -> pd.DataFrame:
    if calibration_df.empty or probability_col not in calibration_df.columns:
        return pd.DataFrame()
    work = calibration_df.copy()
    work["p"] = pd.to_numeric(work[probability_col], errors="coerce").clip(0.0, 1.0)
    work["prob_bucket"] = pd.cut(work["p"], bins=PROB_BINS, labels=PROB_LABELS)
    rows: list[dict[str, object]] = []
    for (label, horizon, bucket), group in work.groupby(["state_label", "horizon_days", "prob_bucket"], observed=False):
        if group.empty:
            continue
        p = pd.to_numeric(group["p"], errors="coerce")
        actual = group["actual_exit_within_h_trading_days"].astype(float)
        predicted = float(p.mean())
        realized = float(actual.mean())
        rows.append(
            {
                "probability_type": probability_type,
                "prob_type": probability_type,
                "target_type": group["target_type"].dropna().iloc[0] if "target_type" in group and group["target_type"].notna().any() else None,
                "state_label": label,
                "horizon_days": int(horizon),
                "prob_bucket": bucket,
                "sample_count": int(len(group)),
                "mean_predicted_exit_prob": predicted,
                "realized_exit_rate": realized,
                "brier_score": float(((actual - p) ** 2).mean()),
                "calibration_error": realized - predicted,
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
