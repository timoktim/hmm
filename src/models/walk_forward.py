from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from src.data_pipeline.storage import json_dumps
from src.features.sector_features import FEATURE_COLUMNS
from src.models.hmm_model import filtered_predict_proba
from src.models.preprocessing import FeaturePreprocessor
from src.models.state_labeler import label_states


ProgressCallback = Callable[[int, int, pd.Timestamp, bool], None]


@dataclass
class WalkForwardConfig:
    n_states: int = 3
    train_window_days: int | None = 504
    retrain_frequency: str = "monthly"
    min_train_rows: int = 120
    min_sequence_length: int = 30
    random_state: int = 42
    n_iter: int = 300


@dataclass
class _TrainedArtifacts:
    model: object
    preprocessor: FeaturePreprocessor
    labels: dict[int, str]
    label_to_idx: dict[str, list[int]]
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    sector_ids: set[str]
    period_key: str


def _select_training_frame(features: pd.DataFrame, signal_date: pd.Timestamp, config: WalkForwardConfig) -> pd.DataFrame:
    history = features[features["trade_date"] <= signal_date].copy()
    if config.train_window_days:
        train_dates = pd.Series(history["trade_date"].drop_duplicates().sort_values())
        train_dates = train_dates.tail(config.train_window_days)
        history = history[history["trade_date"].isin(set(train_dates))]
    lengths = history.groupby("sector_id").size()
    valid_sectors = lengths[lengths >= config.min_sequence_length].index
    return history[history["sector_id"].isin(valid_sectors)].sort_values(["sector_id", "trade_date"])


def _period_key(signal_date: pd.Timestamp, retrain_frequency: str) -> str:
    if retrain_frequency == "signal":
        return signal_date.strftime("%Y-%m-%d")
    if retrain_frequency == "monthly":
        return str(signal_date.to_period("M"))
    if retrain_frequency == "quarterly":
        return str(signal_date.to_period("Q"))
    raise ValueError("retrain_frequency 必须是 signal、monthly 或 quarterly")


def _train_artifacts(df: pd.DataFrame, signal_date: pd.Timestamp, config: WalkForwardConfig) -> _TrainedArtifacts | None:
    from hmmlearn.hmm import GaussianHMM

    train_df = _select_training_frame(df, signal_date, config)
    if len(train_df) < max(config.min_train_rows, config.n_states * 30):
        return None
    lengths = train_df.groupby("sector_id", sort=False).size().astype(int).tolist()
    preprocessor = FeaturePreprocessor()
    x = preprocessor.fit_transform_array(train_df)
    model = GaussianHMM(
        n_components=config.n_states,
        covariance_type="diag",
        n_iter=config.n_iter,
        random_state=config.random_state,
        min_covar=1e-4,
        verbose=False,
    )
    model.fit(x, lengths=lengths)
    probs = filtered_predict_proba(model, x, lengths=lengths)
    labeled = train_df.reset_index(drop=True).copy()
    labeled["state_id"] = probs.argmax(axis=1)
    labels = label_states(labeled)
    label_to_idx = {"TrendUp": [], "Neutral": [], "RiskOff": []}
    for state_id, label in labels.items():
        label_to_idx.setdefault(label, []).append(state_id)
    return _TrainedArtifacts(
        model=model,
        preprocessor=preprocessor,
        labels=labels,
        label_to_idx=label_to_idx,
        train_start=train_df["trade_date"].min(),
        train_end=train_df["trade_date"].max(),
        sector_ids=set(train_df["sector_id"].astype(str)),
        period_key=_period_key(signal_date, config.retrain_frequency),
    )


def _infer_signal_rows(df: pd.DataFrame, signal_date: pd.Timestamp, artifacts: _TrainedArtifacts) -> list[dict[str, object]]:
    infer_df = df[
        (df["trade_date"] >= artifacts.train_start)
        & (df["trade_date"] <= signal_date)
        & (df["sector_id"].astype(str).isin(artifacts.sector_ids))
    ].sort_values(["sector_id", "trade_date"])
    if infer_df.empty:
        return []
    lengths = infer_df.groupby("sector_id", sort=False).size().astype(int).tolist()
    x = artifacts.preprocessor.transform_array(infer_df)
    probs = filtered_predict_proba(artifacts.model, x, lengths=lengths)
    labeled = infer_df.reset_index(drop=True).copy()
    rows: list[dict[str, object]] = []
    signal_mask = labeled["trade_date"].eq(signal_date)
    for i, row in labeled.loc[signal_mask].iterrows():
        state_prob = probs[i]
        state_id = int(state_prob.argmax())
        prob_by_label = {
            label: float(state_prob[idxs].sum()) if idxs else 0.0
            for label, idxs in artifacts.label_to_idx.items()
        }
        next_probs = state_prob.dot(artifacts.model.transmat_)
        next_by_label = {
            label: float(next_probs[idxs].sum()) if idxs else 0.0
            for label, idxs in artifacts.label_to_idx.items()
        }
        rows.append(
            {
                "sector_id": row["sector_id"],
                "trade_date": signal_date,
                "state_id": state_id,
                "state_label": artifacts.labels.get(state_id, "Neutral"),
                "prob_trend_up": prob_by_label.get("TrendUp", 0.0),
                "prob_neutral": prob_by_label.get("Neutral", 0.0),
                "prob_risk_off": prob_by_label.get("RiskOff", 0.0),
                "next_state_probs_json": json_dumps(next_by_label),
                "train_start": artifacts.train_start,
                "train_end": artifacts.train_end,
                "max_observation_date_used": signal_date,
                "probability_type": "filtered",
                "state_source": "causal_backtest",
            }
        )
    return rows


def walk_forward_hmm_state_frame(
    features: pd.DataFrame,
    signal_dates: list[pd.Timestamp] | pd.Series,
    config: WalkForwardConfig | None = None,
    progress_callback: ProgressCallback | None = None,
) -> pd.DataFrame:
    """Generate signal-day HMM states using only observations available through each signal date."""
    config = config or WalkForwardConfig()
    df = features.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.dropna(subset=FEATURE_COLUMNS).sort_values(["sector_id", "trade_date"]).reset_index(drop=True)
    rows: list[dict[str, object]] = []
    artifacts: _TrainedArtifacts | None = None
    dates = pd.Series(pd.to_datetime(signal_dates)).drop_duplicates().sort_values().tolist()

    for idx, signal_date in enumerate(dates, start=1):
        signal_date = pd.Timestamp(signal_date)
        period_key = _period_key(signal_date, config.retrain_frequency)
        retrained = False
        if artifacts is None or artifacts.period_key != period_key:
            new_artifacts = _train_artifacts(df, signal_date, config)
            if new_artifacts is not None:
                artifacts = new_artifacts
                retrained = True
        if artifacts is not None:
            rows.extend(_infer_signal_rows(df, signal_date, artifacts))
        if progress_callback is not None:
            progress_callback(idx, len(dates), signal_date, retrained)
    return pd.DataFrame(rows)
