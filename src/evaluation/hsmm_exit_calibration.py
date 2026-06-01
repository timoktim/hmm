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


def _actual_exit_within_trading_rows(group: pd.DataFrame, idx: int, horizon: int) -> bool | None:
    label = str(group.loc[idx, "state_label"])
    future = group.iloc[idx + 1 : idx + 1 + horizon]
    if len(future) < horizon:
        return None
    return bool(future["state_label"].astype(str).ne(label).any())


def _add_buckets(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    age_source = "duration_model_age_days" if "duration_model_age_days" in out.columns else "state_age_days"
    out["state_age_bucket"] = pd.cut(pd.to_numeric(out[age_source], errors="coerce"), bins=AGE_BINS, labels=AGE_LABELS)
    out["duration_percentile_bucket"] = pd.cut(pd.to_numeric(out["duration_percentile"], errors="coerce"), bins=DURATION_BINS, labels=DURATION_LABELS)
    out["raw_p_exit_bucket"] = pd.cut(pd.to_numeric(out["raw_p_exit"], errors="coerce"), bins=PROB_BINS, labels=PROB_LABELS)
    return out


def build_exit_calibration_dataset(states: pd.DataFrame, horizons: tuple[int, ...] = (1, 3, 5, 10, 20)) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    rows: list[dict[str, object]] = []
    for _, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        for idx in range(len(group)):
            for horizon in horizons:
                raw_col = f"raw_p_exit_{horizon}d" if f"raw_p_exit_{horizon}d" in group.columns else f"p_exit_{horizon}d"
                if raw_col not in group.columns:
                    continue
                actual = _actual_exit_within_trading_rows(group, idx, horizon)
                if actual is None:
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
                        "actual_exit_within_h_trading_days": bool(actual),
                    }
                )
    return _add_buckets(pd.DataFrame(rows)) if rows else pd.DataFrame()


def _rate_table(df: pd.DataFrame, group_cols: list[str], min_bucket_count: int) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=[*group_cols, "sample_count", "empirical_exit_rate", "mean_raw_p_exit"])
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
) -> EmpiricalExitCalibrator:
    train = calibration_df.copy()
    if train_end_date is not None and not train.empty:
        train = train[pd.to_datetime(train["trade_date"]) <= pd.to_datetime(train_end_date)].copy()
    train = _add_buckets(train)
    specific_cols = ["state_label", "state_phase", "state_age_bucket", "duration_percentile_bucket", "raw_p_exit_bucket", "horizon_days"]
    state_phase_cols = ["state_label", "state_phase", "horizon_days"]
    state_cols = ["state_label", "horizon_days"]
    global_cols = ["horizon_days"]
    metadata = {
        "train_start": str(pd.to_datetime(train["trade_date"]).min().date()) if not train.empty else None,
        "train_end": str(pd.to_datetime(train["trade_date"]).max().date()) if not train.empty else None,
        "training_rows": int(len(train)),
        "min_bucket_count": int(min_bucket_count),
    }
    return EmpiricalExitCalibrator(
        specific=_rate_table(train, specific_cols, min_bucket_count),
        state_phase=_rate_table(train, state_phase_cols, max(5, min_bucket_count // 2)),
        state=_rate_table(train, state_cols, max(5, min_bucket_count // 2)),
        global_rate=_rate_table(train, global_cols, 1),
        metadata=metadata,
    )


def _lookup_rate(row: pd.Series, calibrator: EmpiricalExitCalibrator) -> float:
    tables = [
        (
            calibrator.specific,
            ["state_label", "state_phase", "state_age_bucket", "duration_percentile_bucket", "raw_p_exit_bucket", "horizon_days"],
        ),
        (calibrator.state_phase, ["state_label", "state_phase", "horizon_days"]),
        (calibrator.state, ["state_label", "horizon_days"]),
        (calibrator.global_rate, ["horizon_days"]),
    ]
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
    out["calibrated_p_exit"] = out.apply(lambda row: _lookup_rate(row, calibrator), axis=1)
    out["calibrated_p_exit"] = pd.to_numeric(out["calibrated_p_exit"], errors="coerce").clip(0.0, 1.0)
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
