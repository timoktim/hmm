from __future__ import annotations

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
from src.features.market_features import BREADTH_FEATURE_COLUMNS, MARKET_FEATURE_VERSION, available_market_feature_columns, build_market_features
from src.models.hmm_model import filtered_predict_proba
from src.models.preprocessing import FeaturePreprocessor
from src.utils.dates import normalize_yyyymmdd


@dataclass
class MarketHMMTrainResult:
    run_id: str
    n_states: int
    rows: int
    model_path: str
    scaler_path: str
    used_breadth: bool
    index_coverage_warning: str = ""
    breadth_coverage_warning: str = ""


MAJOR_INDEX_CODES = {
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
}
ProgressCallback = Callable[[int, str, dict[str, object]], None]


def _major_index_coverage(
    storage: DuckDBStorage,
    start: pd.Timestamp,
    end: pd.Timestamp,
    min_rows: int = 60,
) -> tuple[dict[str, int], list[str], str]:
    rows = storage.read_df(
        """
        SELECT index_code, count(*) AS rows
        FROM market_index_ohlcv
        WHERE index_code IN ('000300', '000905', '000852')
          AND trade_date BETWEEN ? AND ?
        GROUP BY index_code
        """,
        [start.date(), end.date()],
    )
    counts = {code: 0 for code in MAJOR_INDEX_CODES}
    if not rows.empty:
        counts.update({str(row.index_code).zfill(6): int(row.rows) for row in rows.itertuples(index=False)})
    sufficient = [code for code, count in counts.items() if count >= min_rows]
    warning = ""
    if len(sufficient) < 2:
        detail = "，".join(f"{MAJOR_INDEX_CODES[code]} {counts[code]} 行" for code in MAJOR_INDEX_CODES)
        warning = f"主要指数覆盖不足：至少需要沪深300、中证500、中证1000中的两个指数各不少于 {min_rows} 行；当前 {detail}。"
    return counts, sufficient, warning


def _recent_breadth_warning(storage: DuckDBStorage, end: pd.Timestamp) -> str:
    breadth = storage.read_df(
        """
        SELECT trade_date, coverage_level, total_count, effective_count, expected_count,
               coverage_ratio, breadth_mode, coverage_warning
        FROM market_breadth_daily
        WHERE trade_date <= ?
          AND breadth_mode = 'full_market'
        ORDER BY trade_date DESC
        LIMIT 60
        """,
        [end.date()],
    )
    if breadth.empty:
        return "缺少全 A 市场宽度数据，本次模型已自动改用纯指数特征。"
    if len(breadth) < 60:
        return f"全 A 市场宽度最近样本不足 60 日（当前 {len(breadth)} 日），本次模型已自动改用纯指数特征。"
    coverage = breadth["coverage_level"].fillna("insufficient").astype(str)
    mode = breadth["breadth_mode"].fillna("local_sample").astype(str) if "breadth_mode" in breadth.columns else pd.Series("local_sample", index=breadth.index)
    ratio = pd.to_numeric(breadth.get("coverage_ratio", pd.Series(0.0, index=breadth.index)), errors="coerce").fillna(0.0)
    if coverage.eq("full_market").all() and mode.eq("full_market").all() and (ratio >= 0.8).all():
        return ""
    latest = breadth.iloc[0]

    def as_int(value: object) -> int:
        return 0 if pd.isna(value) else int(value)

    def as_float(value: object) -> float:
        return 0.0 if pd.isna(value) else float(value)

    effective_value = latest.get("effective_count")
    effective = as_int(effective_value if pd.notna(effective_value) else latest.get("total_count"))
    mode_value = latest.get("breadth_mode")
    latest_mode = "local_sample" if pd.isna(mode_value) else str(mode_value)
    if latest_mode != "full_market":
        return f"当前宽度仅覆盖本地样本 {effective} 只股票，未达到全市场宽度标准。本次大盘 HMM 已使用纯指数特征。"
    expected = as_int(latest.get("expected_count"))
    latest_ratio = as_float(latest.get("coverage_ratio"))
    return f"当前全 A 宽度覆盖不足：应覆盖 {expected} 只，有效 {effective} 只，覆盖率 {latest_ratio:.1%}。本次大盘 HMM 已使用纯指数特征。"


def label_market_states(feature_df: pd.DataFrame, state_col: str = "state_id", use_breadth: bool = True) -> dict[int, str]:
    work = feature_df.copy()
    original_columns = set(work.columns)
    dynamic = work.groupby(state_col).mean(numeric_only=True)
    zero = pd.Series(0.0, index=dynamic.index)

    def mean_existing(candidates: list[str]) -> pd.Series:
        cols = [c for c in candidates if c in original_columns and c in dynamic.columns]
        if not cols:
            return zero.copy()
        return dynamic[cols].mean(axis=1).fillna(0.0)

    ret_score = mean_existing(["hs300_ret_20d", "zz500_ret_20d", "zz1000_ret_20d"])
    vol_score = mean_existing(["hs300_vol_20d", "zz500_vol_20d", "zz1000_vol_20d"])
    drawdown_risk = -mean_existing(["hs300_drawdown_20d", "zz500_drawdown_20d", "zz1000_drawdown_20d"])
    breadth_cols = [c for c in ["up_ratio", "above_ma20_ratio"] if c in original_columns and c in dynamic.columns]
    breadth_score = dynamic[breadth_cols].mean(axis=1).fillna(0.0) if use_breadth and breadth_cols else zero.copy()
    risk_on_score = ret_score + breadth_score - 0.5 * vol_score - drawdown_risk
    risk_off_score = -ret_score + drawdown_risk + 0.5 * vol_score - breadth_score

    labels: dict[int, str] = {int(state): "Neutral" for state in dynamic.index}
    risk_on_state = int(risk_on_score.idxmax())
    labels[risk_on_state] = "RiskOn"
    remaining = risk_off_score.drop(index=risk_on_state, errors="ignore")
    risk_off_state = int(remaining.idxmax()) if not remaining.empty else risk_on_state
    labels[risk_off_state] = "RiskOff"
    return labels


def latest_market_regime(storage: DuckDBStorage | None = None, run_id: str | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    if run_id is None:
        runs = storage.read_df("SELECT run_id FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")
        if runs.empty:
            return pd.DataFrame()
        run_id = str(runs.loc[0, "run_id"])
    return storage.read_df(
        """
        SELECT d.*, r.train_start, r.train_end, r.metrics_json
        FROM market_regime_daily d
        JOIN market_regime_runs r USING(run_id)
        WHERE d.run_id = ?
        ORDER BY d.trade_date DESC
        LIMIT 1
        """,
        [run_id],
    )


def market_regime_history(storage: DuckDBStorage | None = None, run_id: str | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    if run_id is None:
        runs = storage.read_df("SELECT run_id FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")
        if runs.empty:
            return pd.DataFrame()
        run_id = str(runs.loc[0, "run_id"])
    return storage.read_df("SELECT * FROM market_regime_daily WHERE run_id = ? ORDER BY trade_date", [run_id])


def train_market_hmm(
    start_date: str,
    end_date: str,
    n_states: int = 3,
    use_breadth: bool = True,
    random_state: int = 42,
    n_iter: int = 300,
    allow_insufficient_index_coverage: bool = False,
    storage: DuckDBStorage | None = None,
    progress_callback: ProgressCallback | None = None,
) -> MarketHMMTrainResult:
    from hmmlearn.hmm import GaussianHMM

    storage = storage or DuckDBStorage()
    storage.init_schema()

    def progress(percent: int, stage: str, **payload: object) -> None:
        if progress_callback is not None:
            progress_callback(percent, stage, payload)

    progress(10, "读取指数")
    features = build_market_features(storage, start_date, end_date, breadth_mode="full_market")
    if features.empty:
        raise ValueError("缺少大盘指数数据，无法训练大盘 HMM。")
    features["trade_date"] = pd.to_datetime(features["trade_date"])
    start = pd.to_datetime(normalize_yyyymmdd(start_date))
    end = pd.to_datetime(normalize_yyyymmdd(end_date))
    progress(20, "检查指数覆盖", sample_rows=len(features))
    major_counts, sufficient_major_indices, index_coverage_warning = _major_index_coverage(storage, start, end)
    if index_coverage_warning and len(sufficient_major_indices) < 2 and not allow_insufficient_index_coverage:
        raise ValueError(index_coverage_warning + " 如仍要训练，请勾选“允许指数覆盖不足时训练”。")
    progress(30, "检查市场宽度", major_indices=len(sufficient_major_indices))
    breadth_coverage_warning = _recent_breadth_warning(storage, end) if use_breadth else ""
    effective_use_breadth = bool(use_breadth and not breadth_coverage_warning)
    df = features[(features["trade_date"] >= start) & (features["trade_date"] <= end)].copy()
    progress(45, "构建特征", sample_rows=len(df))
    feature_columns = available_market_feature_columns(df, use_breadth=effective_use_breadth)
    used_breadth = effective_use_breadth and any(c in feature_columns for c in BREADTH_FEATURE_COLUMNS)
    if not feature_columns:
        raise ValueError("大盘特征不足，无法训练。请先更新指数数据。")
    df = df.dropna(subset=feature_columns).sort_values("trade_date").reset_index(drop=True)
    if len(df) < max(60, n_states * 20):
        raise ValueError("大盘 HMM 训练样本不足，请扩大日期范围。")

    preprocessor = FeaturePreprocessor(columns=feature_columns)
    x = preprocessor.fit_transform_array(df)
    progress(70, "训练 HMM", sample_rows=len(df), feature_count=len(feature_columns))
    model = GaussianHMM(
        n_components=n_states,
        covariance_type="diag",
        n_iter=n_iter,
        random_state=random_state,
        min_covar=1e-4,
        verbose=False,
    )
    model.fit(x)
    progress(85, "推断状态", sample_rows=len(df))
    probs = filtered_predict_proba(model, x, lengths=[len(x)])
    labeled = df.copy()
    labeled["state_id"] = probs.argmax(axis=1)
    labels = label_market_states(labeled, use_breadth=used_breadth)
    labeled["state_label"] = labeled["state_id"].map(labels)
    label_to_idx = {"RiskOn": [], "Neutral": [], "RiskOff": []}
    for state_id, label in labels.items():
        label_to_idx.setdefault(label, []).append(state_id)

    run_id = uuid.uuid4().hex[:12]
    model_path = settings.model_dir / f"market_hmm_{run_id}.joblib"
    scaler_path = settings.model_dir / f"market_scaler_{run_id}.joblib"
    model_path_for_db = project_relative_path(model_path)
    scaler_path_for_db = project_relative_path(scaler_path)
    joblib.dump({"model": model, "labels": labels, "feature_columns": feature_columns, "probability_type": "filtered"}, model_path)
    joblib.dump(preprocessor, scaler_path)

    rows: list[dict[str, object]] = []
    for i, row in labeled.iterrows():
        state_prob = probs[i]
        prob_by_label = {
            label: float(state_prob[idxs].sum()) if idxs else 0.0
            for label, idxs in label_to_idx.items()
        }
        next_probs = state_prob.dot(model.transmat_)
        next_by_label = {
            label: float(next_probs[idxs].sum()) if idxs else 0.0
            for label, idxs in label_to_idx.items()
        }
        rows.append(
            {
                "run_id": run_id,
                "trade_date": row["trade_date"].date(),
                "state_id": int(row["state_id"]),
                "state_label": labels[int(row["state_id"])],
                "prob_risk_on": prob_by_label.get("RiskOn", 0.0),
                "prob_neutral": prob_by_label.get("Neutral", 0.0),
                "prob_risk_off": prob_by_label.get("RiskOff", 0.0),
                "next_state_probs_json": json_dumps(next_by_label),
                "feature_version": MARKET_FEATURE_VERSION,
                "created_at": pd.Timestamp.now(),
            }
        )
    state_df = pd.DataFrame(rows)
    storage.upsert_df("market_regime_daily", state_df, ["run_id", "trade_date"])
    run_df = pd.DataFrame(
        [
            {
                "run_id": run_id,
                "n_states": n_states,
                "train_start": df["trade_date"].min().date(),
                "train_end": df["trade_date"].max().date(),
                "feature_version": MARKET_FEATURE_VERSION,
                "model_path": model_path_for_db,
                "scaler_path": scaler_path_for_db,
                "created_at": pd.Timestamp.now(),
                "metrics_json": json_dumps(
                    {
                        "converged": bool(model.monitor_.converged),
                        "log_prob": float(model.monitor_.history[-1]),
                        "state_labels": labels,
                        "feature_columns": feature_columns,
                        "used_breadth": used_breadth,
                        "requested_breadth": bool(use_breadth),
                        "breadth_coverage_warning": breadth_coverage_warning,
                        "index_coverage_warning": index_coverage_warning,
                        "major_index_counts": major_counts,
                        "sufficient_major_indices": sufficient_major_indices,
                        "transition_matrix": np.asarray(model.transmat_).round(4).tolist(),
                    }
                ),
            }
        ]
    )
    storage.upsert_df("market_regime_runs", run_df, ["run_id"])
    progress(100, "写入数据库", rows=len(state_df), run_id=run_id)
    return MarketHMMTrainResult(
        run_id=run_id,
        n_states=n_states,
        rows=len(state_df),
        model_path=model_path_for_db,
        scaler_path=scaler_path_for_db,
        used_breadth=used_breadth,
        index_coverage_warning=index_coverage_warning,
        breadth_coverage_warning=breadth_coverage_warning,
    )
