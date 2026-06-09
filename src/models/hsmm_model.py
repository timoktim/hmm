from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler

from src.models.hsmm_core import hsmm_viterbi_dp, resolve_hsmm_engine
from src.models.hsmm_labeler import label_hsmm_states


EPS = 1e-12


@dataclass
class _DecodeResult:
    path: np.ndarray
    score: float
    segment_ids: np.ndarray
    segment_starts: np.ndarray
    segment_ends: np.ndarray
    state_age_days: np.ndarray


@dataclass
class _ViterbiDPResult:
    dp: np.ndarray
    back_state: np.ndarray
    back_duration: np.ndarray
    score_by_t: np.ndarray
    emission: np.ndarray | None = None
    engine: str = "python"


def _normalize(values: np.ndarray, axis: int | None = None) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if axis is None:
        total = arr.sum()
        return arr / total if total > 0 else np.full_like(arr, 1.0 / arr.size)
    total = arr.sum(axis=axis, keepdims=True)
    return np.divide(arr, total, out=np.full_like(arr, 1.0 / arr.shape[axis]), where=total > 0)


def _segments_from_path(path: np.ndarray) -> list[tuple[int, int, int]]:
    if len(path) == 0:
        return []
    segments: list[tuple[int, int, int]] = []
    start = 0
    current = int(path[0])
    for i in range(1, len(path)):
        state = int(path[i])
        if state != current:
            segments.append((current, start, i - 1))
            start = i
            current = state
    segments.append((current, start, len(path) - 1))
    return segments


def _resolve_n_jobs(n_jobs: int | str | None) -> int:
    if isinstance(n_jobs, str):
        value = n_jobs.strip().lower()
        if value == "auto":
            return max(1, os.cpu_count() or 1)
        return max(1, int(value or "1"))
    return max(1, int(n_jobs or 1))


def _chunked_arrays(arrays: list[np.ndarray], chunk_size: int) -> list[list[np.ndarray]]:
    size = max(1, int(chunk_size or 1))
    return [arrays[idx : idx + size] for idx in range(0, len(arrays), size)]


def _decode_array_chunk_worker(model_payload: dict[str, Any], array_chunk: list[np.ndarray]) -> list[_DecodeResult]:
    model = DiscreteDurationGaussianHSMM.from_dict(model_payload)
    return [model._viterbi_array(np.asarray(arr, dtype=float)) for arr in array_chunk]


class DiscreteDurationGaussianHSMM:
    def __init__(
        self,
        n_states: int = 4,
        max_duration: int = 60,
        n_iter: int = 20,
        tol: float = 1e-4,
        duration_smoothing: float = 1.0,
        transition_smoothing: float = 1.0,
        variance_floor: float = 1e-4,
        random_state: int | None = 42,
        engine: str = "python",
        n_jobs: int | str = 1,
        sequence_chunk_size: int = 32,
    ):
        if n_states < 2:
            raise ValueError("n_states must be >= 2")
        if max_duration < 2:
            raise ValueError("max_duration must be >= 2")
        self.n_states = int(n_states)
        self.max_duration = int(max_duration)
        self.n_iter = int(n_iter)
        self.tol = float(tol)
        self.duration_smoothing = float(duration_smoothing)
        self.transition_smoothing = float(transition_smoothing)
        self.variance_floor = float(variance_floor)
        self.random_state = random_state
        self.engine = str(engine or "python")
        resolve_hsmm_engine(self.engine)
        self.n_jobs = n_jobs
        self.sequence_chunk_size = max(1, int(sequence_chunk_size or 1))

        self.startprob_: np.ndarray | None = None
        self.transmat_: np.ndarray | None = None
        self.duration_pmf_: np.ndarray | None = None
        self.means_: np.ndarray | None = None
        self.vars_: np.ndarray | None = None
        self.feature_cols_: list[str] = []
        self.scaler_: StandardScaler | None = None
        self.state_labels_: dict[int, str] = {}
        self.monitor_history_: list[float] = []
        self.fit_parallel_enabled_: bool = False
        self.fit_parallel_fallback_: bool = False
        self.fit_parallel_warning_: str | None = None
        self.fit_decode_seconds_: float = 0.0
        self.fit_update_seconds_: float = 0.0
        self.fit_iteration_count_: int = 0
        self.fit_n_jobs_: int = _resolve_n_jobs(n_jobs)
        self.fit_sequence_count_: int = 0

    def fit(self, sequences: list[pd.DataFrame], feature_cols: list[str]) -> "DiscreteDurationGaussianHSMM":
        clean_sequences = self._prepare_input_frames(sequences, feature_cols)
        if not clean_sequences:
            raise ValueError("HSMM fit requires at least one non-empty sequence")
        self.feature_cols_ = list(feature_cols)
        train_df = pd.concat(clean_sequences, ignore_index=True)
        self.scaler_ = StandardScaler()
        self.scaler_.fit(train_df[self.feature_cols_].to_numpy(dtype=float))
        arrays = [self.scaler_.transform(seq[self.feature_cols_].to_numpy(dtype=float)) for seq in clean_sequences]
        paths = self._initial_paths(arrays, train_df)
        self.fit_parallel_enabled_ = False
        self.fit_parallel_fallback_ = False
        self.fit_parallel_warning_ = None
        self.fit_decode_seconds_ = 0.0
        self.fit_update_seconds_ = 0.0
        self.fit_iteration_count_ = 0
        self.fit_n_jobs_ = _resolve_n_jobs(self.n_jobs)
        self.fit_sequence_count_ = len(arrays)
        update_started = time.perf_counter()
        self._update_parameters(arrays, paths)
        self.fit_update_seconds_ += time.perf_counter() - update_started

        previous_score: float | None = None
        self.monitor_history_ = []
        for _ in range(self.n_iter):
            decode_started = time.perf_counter()
            decoded = self._decode_arrays(arrays)
            self.fit_decode_seconds_ += time.perf_counter() - decode_started
            paths = [item.path for item in decoded]
            score = float(sum(item.score for item in decoded))
            self.monitor_history_.append(score)
            update_started = time.perf_counter()
            self._update_parameters(arrays, paths)
            self.fit_update_seconds_ += time.perf_counter() - update_started
            self.fit_iteration_count_ += 1
            if previous_score is not None:
                denom = max(abs(previous_score), 1.0)
                if abs(score - previous_score) / denom < self.tol:
                    break
            previous_score = score

        labeled_parts: list[pd.DataFrame] = []
        for seq, path in zip(clean_sequences, paths, strict=False):
            part = seq.reset_index(drop=True).copy()
            part["state_id"] = path
            labeled_parts.append(part)
        self.state_labels_ = label_hsmm_states(pd.concat(labeled_parts, ignore_index=True))
        return self

    def decode(self, sequence: pd.DataFrame) -> pd.DataFrame:
        self._check_fitted()
        seq = self._prepare_input_frames([sequence], self.feature_cols_)[0]
        x = self.scaler_.transform(seq[self.feature_cols_].to_numpy(dtype=float))
        result = self._viterbi_array(x)
        out = seq.reset_index(drop=True).copy()
        out["state_id"] = result.path
        out["state_label"] = [self.state_labels_.get(int(s), f"State{s}") for s in result.path]
        out["segment_id"] = result.segment_ids
        out["segment_start_index"] = result.segment_starts
        out["segment_end_index"] = result.segment_ends
        out["state_age_days_by_id"] = result.state_age_days
        label_ages: list[int] = []
        previous_label: str | None = None
        current_age = 0
        for label in out["state_label"].astype(str):
            current_age = current_age + 1 if label == previous_label else 1
            label_ages.append(current_age)
            previous_label = label
        out["state_age_days_by_label"] = label_ages
        out["state_age_days"] = out["state_age_days_by_label"]
        out["duration_percentile"] = [self.duration_percentile(int(s), int(a)) for s, a in zip(result.path, out["state_age_days_by_id"], strict=False)]
        out["duration_percentile_status"] = [
            self.duration_percentile_status(int(s), int(a))
            for s, a in zip(result.path, out["state_age_days_by_id"], strict=False)
        ]
        out["duration_tail_status"] = [
            self.duration_tail_status(int(s), int(a))
            for s, a in zip(result.path, out["state_age_days_by_id"], strict=False)
        ]
        out["state_phase"] = [self.state_phase(float(p)) for p in out["duration_percentile"]]
        out["viterbi_score"] = result.score
        return out

    def decode_many(self, sequences: list[pd.DataFrame]) -> pd.DataFrame:
        frames = [self.decode(seq) for seq in sequences if not seq.empty]
        return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    def lifecycle_snapshot(self, decoded_sequence: pd.DataFrame, as_of_date: pd.Timestamp) -> dict[str, Any]:
        if decoded_sequence.empty:
            return {}
        work = decoded_sequence.copy()
        work["trade_date"] = pd.to_datetime(work["trade_date"])
        row = work[work["trade_date"] <= pd.Timestamp(as_of_date)].tail(1)
        if row.empty:
            return {}
        record = row.iloc[0]
        state_id = int(record["state_id"])
        age = int(record.get("state_age_days_by_id", record["state_age_days"]))
        label_age = int(record.get("state_age_days_by_label", record["state_age_days"]))
        p_exit = {h: self.p_exit_h(state_id, age, h) for h in (1, 3, 5, 10, 20)}
        p_stay = {h: 1.0 - p_exit[h] for h in p_exit}
        p_exit_status = {h: self.p_exit_status(state_id, age, h) for h in p_exit}
        next_state_id = int(np.argmax(self.transmat_[state_id]))
        next_prob = float(self.transmat_[state_id, next_state_id])
        duration_percentile = self.duration_percentile(state_id, age)
        duration_percentile_status = self.duration_percentile_status(state_id, age)
        duration_tail_status = self.duration_tail_status(state_id, age)
        return {
            "state_id": state_id,
            "state_label": self.state_labels_.get(state_id, f"State{state_id}"),
            "state_phase": self.state_phase(duration_percentile),
            "state_age_days": age,
            "state_age_days_by_id": age,
            "state_age_days_by_label": label_age,
            "model_state_age_days": age,
            "label_state_age_days": label_age,
            "duration_model_age_days": age,
            "display_state_age_days": label_age,
            "duration_percentile": duration_percentile,
            "duration_percentile_status": duration_percentile_status,
            "duration_tail_status": duration_tail_status,
            "expected_remaining_days": self.expected_remaining_days(state_id, age),
            "p_stay_1d": p_stay[1],
            "p_stay_3d": p_stay[3],
            "p_stay_5d": p_stay[5],
            "p_stay_10d": p_stay[10],
            "p_exit_1d": p_exit[1],
            "p_exit_3d": p_exit[3],
            "p_exit_5d": p_exit[5],
            "p_exit_10d": p_exit[10],
            "p_exit_20d": p_exit[20],
            "raw_p_exit_1d": p_exit[1],
            "raw_p_exit_3d": p_exit[3],
            "raw_p_exit_5d": p_exit[5],
            "raw_p_exit_10d": p_exit[10],
            "raw_p_exit_20d": p_exit[20],
            "p_exit_1d_status": p_exit_status[1],
            "p_exit_3d_status": p_exit_status[3],
            "p_exit_5d_status": p_exit_status[5],
            "p_exit_10d_status": p_exit_status[10],
            "p_exit_20d_status": p_exit_status[20],
            "raw_p_exit_1d_status": p_exit_status[1],
            "raw_p_exit_3d_status": p_exit_status[3],
            "raw_p_exit_5d_status": p_exit_status[5],
            "raw_p_exit_10d_status": p_exit_status[10],
            "raw_p_exit_20d_status": p_exit_status[20],
            "calibrated_p_exit_1d": np.nan,
            "calibrated_p_exit_3d": np.nan,
            "calibrated_p_exit_5d": np.nan,
            "calibrated_p_exit_10d": np.nan,
            "calibrated_p_exit_20d": np.nan,
            "most_likely_next_state_id": next_state_id,
            "most_likely_next_state_label": self.state_labels_.get(next_state_id, f"State{next_state_id}"),
            "next_state_probability": next_prob,
            "viterbi_score": float(record.get("viterbi_score", np.nan)),
            "confidence": np.nan,
        }

    def endpoint_snapshot_from_dp(self, dp_result: _ViterbiDPResult, end_index: int) -> dict[str, Any]:
        """Return the causal endpoint state for a prefix ending at 1-based end_index."""
        self._check_fitted()
        end_index = int(end_index)
        if end_index <= 0 or end_index >= len(dp_result.dp):
            raise ValueError("end_index must be in [1, sequence_length]")
        state_id = int(np.argmax(dp_result.dp[end_index]))
        age = int(dp_result.back_duration[end_index, state_id])
        if age <= 0:
            age = 1
        p_exit = {h: self.p_exit_h(state_id, age, h) for h in (1, 3, 5, 10, 20)}
        p_stay = {h: 1.0 - p_exit[h] for h in p_exit}
        p_exit_status = {h: self.p_exit_status(state_id, age, h) for h in p_exit}
        next_state_id = int(np.argmax(self.transmat_[state_id]))
        next_prob = float(self.transmat_[state_id, next_state_id])
        duration_percentile = self.duration_percentile(state_id, age)
        duration_percentile_status = self.duration_percentile_status(state_id, age)
        duration_tail_status = self.duration_tail_status(state_id, age)
        return {
            "state_id": state_id,
            "state_label": self.state_labels_.get(state_id, f"State{state_id}"),
            "state_phase": self.state_phase(duration_percentile),
            "state_age_days": age,
            "state_age_days_by_id": age,
            "state_age_days_by_label": age,
            "model_state_age_days": age,
            "label_state_age_days": age,
            "duration_model_age_days": age,
            "display_state_age_days": age,
            "duration_percentile": duration_percentile,
            "duration_percentile_status": duration_percentile_status,
            "duration_tail_status": duration_tail_status,
            "expected_remaining_days": self.expected_remaining_days(state_id, age),
            "p_stay_1d": p_stay[1],
            "p_stay_3d": p_stay[3],
            "p_stay_5d": p_stay[5],
            "p_stay_10d": p_stay[10],
            "p_exit_1d": p_exit[1],
            "p_exit_3d": p_exit[3],
            "p_exit_5d": p_exit[5],
            "p_exit_10d": p_exit[10],
            "p_exit_20d": p_exit[20],
            "raw_p_exit_1d": p_exit[1],
            "raw_p_exit_3d": p_exit[3],
            "raw_p_exit_5d": p_exit[5],
            "raw_p_exit_10d": p_exit[10],
            "raw_p_exit_20d": p_exit[20],
            "p_exit_1d_status": p_exit_status[1],
            "p_exit_3d_status": p_exit_status[3],
            "p_exit_5d_status": p_exit_status[5],
            "p_exit_10d_status": p_exit_status[10],
            "p_exit_20d_status": p_exit_status[20],
            "raw_p_exit_1d_status": p_exit_status[1],
            "raw_p_exit_3d_status": p_exit_status[3],
            "raw_p_exit_5d_status": p_exit_status[5],
            "raw_p_exit_10d_status": p_exit_status[10],
            "raw_p_exit_20d_status": p_exit_status[20],
            "calibrated_p_exit_1d": np.nan,
            "calibrated_p_exit_3d": np.nan,
            "calibrated_p_exit_5d": np.nan,
            "calibrated_p_exit_10d": np.nan,
            "calibrated_p_exit_20d": np.nan,
            "most_likely_next_state_id": next_state_id,
            "most_likely_next_state_label": self.state_labels_.get(next_state_id, f"State{next_state_id}"),
            "next_state_probability": next_prob,
            "viterbi_score": float(dp_result.dp[end_index, state_id]),
            "confidence": np.nan,
        }

    def lifecycle_snapshots_from_sequence(
        self,
        sequence: pd.DataFrame,
        snapshot_dates: list[pd.Timestamp],
    ) -> list[dict[str, Any]]:
        """Compute many causal endpoint snapshots from a single DP pass."""
        self._check_fitted()
        if not snapshot_dates:
            return []
        seq = self._prepare_input_frames([sequence], self.feature_cols_)
        if not seq:
            return []
        work = seq[0].reset_index(drop=True)
        work["trade_date"] = pd.to_datetime(work["trade_date"])
        date_to_index = {pd.Timestamp(date): idx + 1 for idx, date in enumerate(work["trade_date"])}
        wanted = [pd.Timestamp(date) for date in snapshot_dates]
        valid_dates = [date for date in wanted if date in date_to_index]
        if not valid_dates:
            return []
        x = self.scaler_.transform(work[self.feature_cols_].to_numpy(dtype=float))
        dp_result = self._viterbi_dp_array(x)
        rows: list[dict[str, Any]] = []
        for date in valid_dates:
            snapshot = self.endpoint_snapshot_from_dp(dp_result, date_to_index[date])
            snapshot["trade_date"] = date
            rows.append(snapshot)
        return rows

    def duration_percentile(self, state_id: int, age: int) -> float:
        pmf = self.duration_pmf_[state_id]
        if age <= 0:
            return 0.0
        if age >= self.max_duration:
            return 1.0
        return float(pmf[:age].sum())

    def duration_percentile_status(self, state_id: int, age: int) -> str:
        if age >= self.max_duration:
            return "beyond_support"
        if age <= 0:
            return "unknown"
        return "within_support"

    def duration_tail_status(self, state_id: int, age: int) -> str:
        if age <= 0:
            return "unavailable"
        if age >= self.max_duration:
            return "beyond_duration_support"
        return "within_duration_support"

    def p_exit_h(self, state_id: int, age: int, horizon: int) -> float:
        pmf = self.duration_pmf_[state_id]
        support = np.arange(1, self.max_duration + 1)
        if age <= 0 or age >= self.max_duration:
            return np.nan
        survival = pmf[support >= max(age, 1)].sum()
        if survival <= EPS:
            return np.nan
        exit_mass = pmf[(support >= age) & (support < age + horizon)].sum()
        return float(np.clip(exit_mass / survival, 0.0, 1.0))

    def p_exit_status(self, state_id: int, age: int, horizon: int) -> str:
        if age <= 0:
            return "unavailable"
        if age >= self.max_duration:
            return "beyond_duration_support"
        value = self.p_exit_h(state_id, age, horizon)
        if not np.isfinite(value):
            return "unavailable"
        return "available"

    def expected_remaining_days(self, state_id: int, age: int) -> float:
        pmf = self.duration_pmf_[state_id]
        support = np.arange(1, self.max_duration + 1)
        if age >= self.max_duration:
            return 0.0
        mask = support >= max(age, 1)
        survival = pmf[mask].sum()
        if survival <= EPS:
            return 0.0
        remaining = np.maximum(support[mask] - age, 0)
        return float(np.dot(remaining, pmf[mask]) / survival)

    @staticmethod
    def state_phase(duration_percentile: float) -> str:
        if pd.isna(duration_percentile):
            return "unknown"
        if duration_percentile < 0.33:
            return "early"
        if duration_percentile < 0.67:
            return "mature"
        return "late"

    def to_dict(self) -> dict[str, Any]:
        self._check_fitted()
        scaler_payload = {
            "mean": self.scaler_.mean_.tolist(),
            "scale": self.scaler_.scale_.tolist(),
            "var": self.scaler_.var_.tolist(),
            "n_features_in": int(self.scaler_.n_features_in_),
        }
        return {
            "n_states": self.n_states,
            "max_duration": self.max_duration,
            "n_iter": self.n_iter,
            "tol": self.tol,
            "duration_smoothing": self.duration_smoothing,
            "transition_smoothing": self.transition_smoothing,
            "variance_floor": self.variance_floor,
            "random_state": self.random_state,
            "engine": self.engine,
            "feature_cols": self.feature_cols_,
            "startprob": self.startprob_.tolist(),
            "transmat": self.transmat_.tolist(),
            "duration_pmf": self.duration_pmf_.tolist(),
            "means": self.means_.tolist(),
            "vars": self.vars_.tolist(),
            "state_labels": {str(k): v for k, v in self.state_labels_.items()},
            "monitor_history": self.monitor_history_,
            "scaler": scaler_payload,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "DiscreteDurationGaussianHSMM":
        model = cls(
            n_states=int(payload["n_states"]),
            max_duration=int(payload["max_duration"]),
            n_iter=int(payload.get("n_iter", 20)),
            tol=float(payload.get("tol", 1e-4)),
            duration_smoothing=float(payload.get("duration_smoothing", 1.0)),
            transition_smoothing=float(payload.get("transition_smoothing", 1.0)),
            variance_floor=float(payload.get("variance_floor", 1e-4)),
            random_state=payload.get("random_state", 42),
            engine=payload.get("engine", "python"),
        )
        model.feature_cols_ = list(payload["feature_cols"])
        model.startprob_ = np.asarray(payload["startprob"], dtype=float)
        model.transmat_ = np.asarray(payload["transmat"], dtype=float)
        model.duration_pmf_ = np.asarray(payload["duration_pmf"], dtype=float)
        model.means_ = np.asarray(payload["means"], dtype=float)
        model.vars_ = np.asarray(payload["vars"], dtype=float)
        model.state_labels_ = {int(k): str(v) for k, v in dict(payload.get("state_labels", {})).items()}
        model.monitor_history_ = [float(x) for x in payload.get("monitor_history", [])]
        scaler_data = payload["scaler"]
        scaler = StandardScaler()
        scaler.mean_ = np.asarray(scaler_data["mean"], dtype=float)
        scaler.scale_ = np.asarray(scaler_data["scale"], dtype=float)
        scaler.var_ = np.asarray(scaler_data["var"], dtype=float)
        scaler.n_features_in_ = int(scaler_data.get("n_features_in", len(model.feature_cols_)))
        model.scaler_ = scaler
        return model

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)

    def _prepare_input_frames(self, sequences: list[pd.DataFrame], feature_cols: list[str]) -> list[pd.DataFrame]:
        out: list[pd.DataFrame] = []
        for seq in sequences:
            if seq.empty:
                continue
            missing = [col for col in feature_cols if col not in seq.columns]
            if missing:
                raise ValueError(f"HSMM sequence missing feature columns: {missing}")
            work = seq.copy()
            if "trade_date" in work.columns:
                work["trade_date"] = pd.to_datetime(work["trade_date"])
                work = work.sort_values("trade_date")
            work[feature_cols] = work[feature_cols].apply(pd.to_numeric, errors="coerce")
            work.replace([np.inf, -np.inf], np.nan, inplace=True)
            work = work.dropna(subset=feature_cols).reset_index(drop=True)
            if not work.empty:
                out.append(work)
        return out

    def _initial_paths(self, arrays: list[np.ndarray], train_df: pd.DataFrame) -> list[np.ndarray]:
        x = np.vstack(arrays)
        rng = np.random.default_rng(self.random_state)
        try:
            labels = KMeans(n_clusters=self.n_states, n_init=10, random_state=self.random_state).fit_predict(x)
        except Exception:
            score = x[:, 0] if x.shape[1] else rng.normal(size=len(x))
            edges = np.nanquantile(score, np.linspace(0, 1, self.n_states + 1)[1:-1])
            labels = np.digitize(score, edges)
        if len(np.unique(labels)) < self.n_states:
            labels = np.arange(len(labels)) % self.n_states
        paths: list[np.ndarray] = []
        offset = 0
        for arr in arrays:
            paths.append(np.asarray(labels[offset : offset + len(arr)], dtype=int))
            offset += len(arr)
        return paths

    def _update_parameters(self, arrays: list[np.ndarray], paths: list[np.ndarray]) -> None:
        n_features = arrays[0].shape[1]
        start_counts = np.full(self.n_states, self.transition_smoothing, dtype=float)
        trans_counts = np.full((self.n_states, self.n_states), self.transition_smoothing, dtype=float)
        np.fill_diagonal(trans_counts, 0.0)
        duration_counts = np.full((self.n_states, self.max_duration), self.duration_smoothing, dtype=float)
        obs_by_state = [[] for _ in range(self.n_states)]

        for x, path in zip(arrays, paths, strict=False):
            if len(path) == 0:
                continue
            segments = _segments_from_path(path)
            start_counts[segments[0][0]] += 1
            for idx, (state, start, end) in enumerate(segments):
                is_right_censored = idx == len(segments) - 1
                if not is_right_censored:
                    duration = min(end - start + 1, self.max_duration)
                    duration_counts[state, duration - 1] += 1
                obs_by_state[state].append(x[start : end + 1])
                if idx > 0:
                    prev = segments[idx - 1][0]
                    if prev != state:
                        trans_counts[prev, state] += 1

        all_x = np.vstack(arrays)
        global_mean = all_x.mean(axis=0)
        global_var = np.maximum(all_x.var(axis=0), self.variance_floor)
        means = np.zeros((self.n_states, n_features), dtype=float)
        vars_ = np.zeros((self.n_states, n_features), dtype=float)
        for state in range(self.n_states):
            if obs_by_state[state]:
                values = np.vstack(obs_by_state[state])
                means[state] = values.mean(axis=0)
                vars_[state] = np.maximum(values.var(axis=0), self.variance_floor)
            elif self.means_ is not None and self.vars_ is not None:
                means[state] = self.means_[state]
                vars_[state] = self.vars_[state]
            else:
                means[state] = global_mean
                vars_[state] = global_var

        self.startprob_ = _normalize(start_counts)
        self.transmat_ = _normalize(trans_counts, axis=1)
        np.fill_diagonal(self.transmat_, 0.0)
        self.transmat_ = _normalize(self.transmat_, axis=1)
        self.duration_pmf_ = _normalize(duration_counts, axis=1)
        self.means_ = means
        self.vars_ = vars_

    def _decode_arrays(self, arrays: list[np.ndarray]) -> list[_DecodeResult]:
        n_jobs = _resolve_n_jobs(self.n_jobs)
        self.fit_n_jobs_ = n_jobs
        if n_jobs <= 1 or len(arrays) <= 1:
            return self._decode_arrays_serial(arrays)
        return self._decode_arrays_parallel(arrays, n_jobs, self.sequence_chunk_size)

    def _decode_arrays_serial(self, arrays: list[np.ndarray]) -> list[_DecodeResult]:
        return [self._viterbi_array(arr) for arr in arrays]

    def _decode_arrays_parallel(self, arrays: list[np.ndarray], n_jobs: int, sequence_chunk_size: int) -> list[_DecodeResult]:
        try:
            from joblib import Parallel, delayed

            model_payload = self.to_dict()
            chunks = _chunked_arrays(arrays, sequence_chunk_size)
            parts = Parallel(n_jobs=n_jobs, prefer="processes")(
                delayed(_decode_array_chunk_worker)(model_payload, chunk) for chunk in chunks
            )
            decoded = [item for part in parts for item in part]
            if len(decoded) != len(arrays):
                raise RuntimeError("parallel HSMM fit decode returned an unexpected sequence count")
            self.fit_parallel_enabled_ = True
            return decoded
        except Exception as exc:
            self.fit_parallel_fallback_ = True
            self.fit_parallel_warning_ = f"{type(exc).__name__}: {exc}"
            return self._decode_arrays_serial(arrays)

    def _emission_logprob(self, x: np.ndarray) -> np.ndarray:
        self._check_fitted()
        x = np.asarray(x, dtype=float)
        out = np.empty((len(x), self.n_states), dtype=float)
        for state in range(self.n_states):
            var = np.maximum(self.vars_[state], self.variance_floor)
            diff = x - self.means_[state]
            out[:, state] = -0.5 * (np.log(2 * np.pi * var).sum() + ((diff * diff) / var).sum(axis=1))
        return out

    def _viterbi_dp_array(self, x: np.ndarray) -> _ViterbiDPResult:
        self._check_fitted()
        x = np.asarray(x, dtype=float)
        if len(x) == 0:
            return _ViterbiDPResult(
                np.full((1, self.n_states), -np.inf, dtype=float),
                np.full((1, self.n_states), -1, dtype=int),
                np.full((1, self.n_states), 0, dtype=int),
                np.array([], dtype=float),
                np.empty((0, self.n_states), dtype=float),
                resolve_hsmm_engine(self.engine),
            )
        emission = self._emission_logprob(x)
        log_start = np.log(np.clip(self.startprob_, EPS, None))
        trans = self.transmat_.copy()
        np.fill_diagonal(trans, 0.0)
        log_trans = np.full_like(trans, -np.inf, dtype=float)
        positive = trans > 0
        log_trans[positive] = np.log(trans[positive])
        log_duration = np.log(np.clip(self.duration_pmf_, EPS, None))
        dp, back_state, back_duration, score_by_t = hsmm_viterbi_dp(
            emission,
            log_start,
            log_trans,
            log_duration,
            engine=self.engine,
        )
        return _ViterbiDPResult(
            dp=dp,
            back_state=back_state,
            back_duration=back_duration,
            score_by_t=score_by_t,
            emission=emission,
            engine=resolve_hsmm_engine(self.engine),
        )

    def _viterbi_array(self, x: np.ndarray) -> _DecodeResult:
        self._check_fitted()
        t_count = len(x)
        if t_count == 0:
            return _DecodeResult(np.array([], dtype=int), 0.0, np.array([], dtype=int), np.array([], dtype=int), np.array([], dtype=int), np.array([], dtype=int))
        dp_result = self._viterbi_dp_array(x)
        dp = dp_result.dp
        back_state = dp_result.back_state
        back_duration = dp_result.back_duration
        path = np.full(t_count, -1, dtype=int)
        end = t_count
        state = int(np.argmax(dp[end]))
        best_total = float(dp[end, state])
        while end > 0 and state >= 0:
            duration = int(back_duration[end, state])
            start = end - duration
            path[start:end] = state
            state = int(back_state[end, state])
            end = start
        if (path < 0).any():
            path[path < 0] = int(np.argmax(self.startprob_))

        segment_ids = np.zeros(t_count, dtype=int)
        segment_starts = np.zeros(t_count, dtype=int)
        segment_ends = np.zeros(t_count, dtype=int)
        ages = np.ones(t_count, dtype=int)
        for seg_id, (_, start, end_idx) in enumerate(_segments_from_path(path)):
            segment_ids[start : end_idx + 1] = seg_id
            segment_starts[start : end_idx + 1] = start
            segment_ends[start : end_idx + 1] = end_idx
            ages[start : end_idx + 1] = np.arange(1, end_idx - start + 2)
        return _DecodeResult(path=path, score=best_total, segment_ids=segment_ids, segment_starts=segment_starts, segment_ends=segment_ends, state_age_days=ages)

    def _check_fitted(self) -> None:
        if self.startprob_ is None or self.transmat_ is None or self.duration_pmf_ is None or self.means_ is None or self.vars_ is None or self.scaler_ is None:
            raise ValueError("HSMM model is not fitted")
