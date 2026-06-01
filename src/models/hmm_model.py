from __future__ import annotations

import argparse
import uuid
from collections.abc import Callable
from dataclasses import dataclass

from src.utils.runtime import configure_numeric_runtime

configure_numeric_runtime()

import joblib
import numpy as np
import pandas as pd

from src.config import project_relative_path, settings
from src.data_pipeline.storage import DuckDBStorage, json_dumps
from src.data_pipeline.universe import load_sector_like_ohlcv
from src.features.sector_features import FEATURE_COLUMNS, add_sector_features, equal_weight_benchmark_ret20_from_close, feature_scope_for_universe
from src.models.preprocessing import FeaturePreprocessor
from src.models.state_labeler import label_states, summarize_state_history
from src.utils.dates import normalize_yyyymmdd


@dataclass
class HMMTrainResult:
    run_id: str
    n_states: int
    rows: int
    model_path: str
    scaler_path: str
    n_init: int = 1
    best_random_state: int | None = None
    best_log_prob: float | None = None


ProgressCallback = Callable[[int, str, dict[str, object]], None]


@dataclass
class HMMFitResult:
    model: object
    best_random_state: int
    best_log_prob: float
    candidates: list[dict[str, object]]


def _prepare_sequences(features: pd.DataFrame, train_start: str, train_end: str) -> tuple[pd.DataFrame, np.ndarray, list[int]]:
    df = features.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    start = pd.to_datetime(normalize_yyyymmdd(train_start))
    end = pd.to_datetime(normalize_yyyymmdd(train_end))
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
    df = df.dropna(subset=FEATURE_COLUMNS).sort_values(["sector_id", "trade_date"])
    lengths = df.groupby("sector_id").size()
    lengths = lengths[lengths >= 30]
    df = df[df["sector_id"].isin(lengths.index)]
    lengths_list = df.groupby("sector_id", sort=False).size().astype(int).tolist()
    return df, df[FEATURE_COLUMNS].to_numpy(dtype=float), lengths_list


def _build_features_for_training(
    storage: DuckDBStorage,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> pd.DataFrame:
    def progress(percent: int, stage: str, **payload: object) -> None:
        if progress_callback is not None:
            progress_callback(percent, stage, payload)

    progress(10, "读取行情")
    ohlcv = load_sector_like_ohlcv(storage, universe_id=universe_id, include_custom_baskets=include_custom_baskets)
    if ohlcv.empty:
        return pd.DataFrame()
    progress(25, "构建特征", sector_count=int(ohlcv["sector_id"].nunique()), raw_rows=len(ohlcv))
    tmp = ohlcv.copy()
    tmp["trade_date"] = pd.to_datetime(tmp["trade_date"])
    daily_close = tmp.pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmark_ret20 = equal_weight_benchmark_ret20_from_close(daily_close)
    feature_scope_id, feature_scope_type = feature_scope_for_universe(storage, universe_id, include_custom_baskets)
    features = add_sector_features(
        ohlcv,
        benchmark_ret20=benchmark_ret20,
        feature_version=settings.default_feature_version,
        apply_winsorize=False,
        feature_scope_id=feature_scope_id,
        feature_scope_type=feature_scope_type,
    )
    storage.upsert_df("sector_features", features, ["sector_id", "trade_date", "feature_version", "feature_scope_id"])
    progress(35, "清洗样本", feature_rows=len(features), sector_count=int(features["sector_id"].nunique()) if not features.empty else 0)
    return features


def _logsumexp(values: np.ndarray) -> float:
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        return float("-inf")
    max_value = float(finite.max())
    return float(max_value + np.log(np.exp(finite - max_value).sum()))


def filtered_predict_proba(model: object, x: np.ndarray, lengths: list[int] | None = None) -> np.ndarray:
    """Forward-filtered P(state_t | observations <= t), not smoothed probabilities."""
    if x.size == 0:
        return np.empty((0, getattr(model, "n_components", 0)))
    lengths = lengths or [len(x)]
    log_likelihood = model._compute_log_likelihood(x)
    log_start = np.log(np.asarray(model.startprob_, dtype=float).clip(1e-300, None))
    log_trans = np.log(np.asarray(model.transmat_, dtype=float).clip(1e-300, None))
    out = np.zeros_like(log_likelihood, dtype=float)
    offset = 0
    for length in lengths:
        log_alpha = log_start + log_likelihood[offset]
        log_alpha -= _logsumexp(log_alpha)
        out[offset] = np.exp(log_alpha)
        for local_idx in range(1, length):
            i = offset + local_idx
            next_alpha = np.empty_like(log_alpha)
            for state in range(log_likelihood.shape[1]):
                next_alpha[state] = log_likelihood[i, state] + _logsumexp(log_alpha + log_trans[:, state])
            next_alpha -= _logsumexp(next_alpha)
            log_alpha = next_alpha
            out[i] = np.exp(log_alpha)
        offset += length
    return out


def _last_log_prob(model: object) -> float:
    history = list(getattr(getattr(model, "monitor_", None), "history", []) or [])
    if not history:
        return float("-inf")
    value = float(history[-1])
    return value if np.isfinite(value) else float("-inf")


def fit_hmm_with_restarts(
    x: np.ndarray,
    lengths: list[int],
    n_states: int,
    n_iter: int,
    random_state: int = 42,
    n_init: int = 3,
    min_covar: float = 1e-4,
    progress_callback: ProgressCallback | None = None,
) -> HMMFitResult:
    from hmmlearn.hmm import GaussianHMM

    n_init = max(1, int(n_init or 1))
    best_model: object | None = None
    best_seed = int(random_state)
    best_log_prob = float("-inf")
    candidates: list[dict[str, object]] = []
    failures: list[str] = []

    for attempt in range(n_init):
        seed = int(random_state) + attempt
        if progress_callback is not None:
            progress_callback(
                70 + int(10 * attempt / max(n_init, 1)),
                "训练 HMM",
                {"restart": attempt + 1, "n_init": n_init, "random_state": seed},
            )
        model = GaussianHMM(
            n_components=n_states,
            covariance_type="diag",
            n_iter=n_iter,
            random_state=seed,
            min_covar=min_covar,
            verbose=False,
        )
        try:
            model.fit(x, lengths=lengths)
        except Exception as exc:
            failures.append(f"seed={seed}: {exc}")
            candidates.append({"random_state": seed, "log_prob": None, "converged": False, "error": str(exc)[:300]})
            continue
        log_prob = _last_log_prob(model)
        converged = bool(getattr(getattr(model, "monitor_", None), "converged", False))
        candidates.append({"random_state": seed, "log_prob": log_prob, "converged": converged})
        if best_model is None or log_prob > best_log_prob:
            best_model = model
            best_seed = seed
            best_log_prob = log_prob

    if best_model is None:
        detail = "；".join(failures[-3:]) if failures else "没有可用初始化结果"
        raise ValueError(f"HMM 训练失败，所有随机初始化都未收敛或报错：{detail}")

    if progress_callback is not None:
        progress_callback(80, "选择最优初始化", {"best_random_state": best_seed, "best_log_prob": round(best_log_prob, 4)})
    return HMMFitResult(model=best_model, best_random_state=best_seed, best_log_prob=best_log_prob, candidates=candidates)


def train_hmm(
    train_start: str,
    train_end: str,
    n_states: int = 3,
    storage: DuckDBStorage | None = None,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
    n_iter: int = 300,
    random_state: int = 42,
    n_init: int = 3,
    progress_callback: ProgressCallback | None = None,
) -> HMMTrainResult:
    storage = storage or DuckDBStorage()
    storage.init_schema()

    def progress(percent: int, stage: str, **payload: object) -> None:
        if progress_callback is not None:
            progress_callback(percent, stage, payload)

    feature_scope_id, feature_scope_type = feature_scope_for_universe(storage, universe_id, include_custom_baskets)
    features = _build_features_for_training(
        storage,
        universe_id=universe_id,
        include_custom_baskets=include_custom_baskets,
        progress_callback=progress_callback,
    )
    if features.empty:
        raise ValueError("没有可训练的板块特征，请先更新板块行情数据。")
    train_df, _, lengths = _prepare_sequences(features, train_start, train_end)
    if len(train_df) < max(100, n_states * 50):
        raise ValueError("训练样本不足，请扩大时间范围或抓取更多板块。")

    preprocessor = FeaturePreprocessor()
    progress(45, "标准化", sample_rows=len(train_df), sector_count=int(train_df["sector_id"].nunique()))
    x = preprocessor.fit_transform_array(train_df)
    progress(70, "训练 HMM", sample_rows=len(train_df), sector_count=int(train_df["sector_id"].nunique()), n_init=int(n_init))
    fit_result = fit_hmm_with_restarts(
        x,
        lengths=lengths,
        n_states=n_states,
        n_iter=n_iter,
        random_state=random_state,
        n_init=n_init,
        min_covar=1e-4,
        progress_callback=progress_callback,
    )
    model = fit_result.model
    progress(85, "推断状态", sample_rows=len(train_df))
    probs = filtered_predict_proba(model, x, lengths=lengths)
    states = probs.argmax(axis=1)
    labeled = train_df.reset_index(drop=True).copy()
    labeled["state_id"] = states
    labels = label_states(labeled)
    labeled["state_label"] = labeled["state_id"].map(labels)
    state_summary = summarize_state_history(labeled)

    run_id = uuid.uuid4().hex[:12]
    model_path = settings.model_dir / f"hmm_{run_id}.joblib"
    scaler_path = settings.model_dir / f"scaler_{run_id}.joblib"
    model_path_for_db = project_relative_path(model_path)
    scaler_path_for_db = project_relative_path(scaler_path)
    joblib.dump(
        {
            "model": model,
            "labels": labels,
            "feature_columns": FEATURE_COLUMNS,
            "probability_type": "filtered",
            "n_init": int(n_init),
            "best_random_state": fit_result.best_random_state,
            "min_covar": 1e-4,
        },
        model_path,
    )
    joblib.dump(preprocessor, scaler_path)

    rows: list[dict[str, object]] = []
    label_to_idx = {"TrendUp": [], "Neutral": [], "RiskOff": []}
    for state_id, label in labels.items():
        label_to_idx.setdefault(label, []).append(state_id)

    for i, row in labeled.iterrows():
        prob_by_label = {
            label: float(probs[i, idxs].sum()) if idxs else 0.0
            for label, idxs in label_to_idx.items()
        }
        next_probs = probs[i].dot(model.transmat_)
        next_by_label = {
            label: float(next_probs[idxs].sum()) if idxs else 0.0
            for label, idxs in label_to_idx.items()
        }
        rows.append(
            {
                "run_id": run_id,
                "sector_id": row["sector_id"],
                "trade_date": row["trade_date"].date(),
                "state_id": int(row["state_id"]),
                "state_label": labels[int(row["state_id"])],
                "prob_trend_up": prob_by_label.get("TrendUp", 0.0),
                "prob_neutral": prob_by_label.get("Neutral", 0.0),
                "prob_risk_off": prob_by_label.get("RiskOff", 0.0),
                "next_state_probs_json": json_dumps(next_by_label),
                "state_source": "in_sample_display",
            }
        )
    state_df = pd.DataFrame(rows)
    storage.upsert_df("sector_state_daily", state_df, ["run_id", "sector_id", "trade_date"])

    run_df = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "model_type": "GaussianHMM",
                "n_states": n_states,
                "train_start": pd.to_datetime(normalize_yyyymmdd(train_start)).date(),
                "train_end": pd.to_datetime(normalize_yyyymmdd(train_end)).date(),
                "feature_version": settings.default_feature_version,
                "model_path": model_path_for_db,
                "scaler_path": scaler_path_for_db,
                "universe_id": universe_id,
                "scope_type": "universe" if universe_id else "all",
                "include_custom_baskets": bool(include_custom_baskets),
                "feature_scope_id": feature_scope_id,
                "feature_scope_type": feature_scope_type,
                "created_at": pd.Timestamp.now(),
                "metrics_json": json_dumps(
                    {
                        "converged": bool(model.monitor_.converged),
                        "log_prob": float(fit_result.best_log_prob),
                        "n_init": int(n_init),
                        "random_state": int(random_state),
                        "best_random_state": fit_result.best_random_state,
                        "min_covar": 1e-4,
                        "restart_candidates": fit_result.candidates,
                        "state_labels": labels,
                        "state_source": "in_sample_display",
                        "universe_id": universe_id,
                        "include_custom_baskets": include_custom_baskets,
                        "feature_scope_id": feature_scope_id,
                        "feature_scope_type": feature_scope_type,
                        "state_summary": state_summary.to_dict(orient="records"),
                        "transition_matrix": model.transmat_.round(4).tolist(),
                    }
                ),
            }
        ]
    )
    storage.upsert_df("model_runs", run_df, ["run_id"])
    progress(100, "写入数据库", rows=len(state_df), run_id=run_id)
    return HMMTrainResult(
        run_id=run_id,
        n_states=n_states,
        rows=len(state_df),
        model_path=model_path_for_db,
        scaler_path=scaler_path_for_db,
        n_init=int(n_init),
        best_random_state=fit_result.best_random_state,
        best_log_prob=float(fit_result.best_log_prob),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="训练全局板块 Gaussian HMM")
    parser.add_argument("--train-start", required=True)
    parser.add_argument("--train-end", default="today")
    parser.add_argument("--states", type=int, default=3)
    parser.add_argument("--universe-id", default=None)
    parser.add_argument("--exclude-custom-baskets", action="store_true")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--n-init", type=int, default=3)
    args = parser.parse_args()
    result = train_hmm(
        args.train_start,
        args.train_end,
        args.states,
        universe_id=args.universe_id,
        include_custom_baskets=not args.exclude_custom_baskets,
        random_state=args.random_state,
        n_init=args.n_init,
    )
    print(pd.Series(result.__dict__).to_string())


if __name__ == "__main__":
    main()
