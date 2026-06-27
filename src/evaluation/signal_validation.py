from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.metrics import annual_return, calmar_ratio, max_drawdown, sharpe_ratio, win_rate
from src.backtest.sector_rotation import (
    SectorRotationBacktestContext,
    prepare_sector_rotation_backtest_context,
    run_sector_rotation_backtest,
    run_sector_rotation_backtest_from_context,
    simulate_portfolio_returns,
    validate_state_neutral_backtest_params,
)
from src.config import settings
from src.data_pipeline.calendar import assert_execution_after_signal, next_trade_date
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv
from src.features.sector_features import FEATURE_COLUMNS, feature_scope_for_universe
from src.scoring.sector_ranker import rank_sectors

_ORIGINAL_RUN_SECTOR_ROTATION_BACKTEST = run_sector_rotation_backtest


@dataclass(frozen=True)
class SignalValidationConfig:
    db_path: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    universe_id: str | None = None
    include_custom_baskets: bool = True

    n_states: int = 3
    train_window_days: int | None = 504
    retrain_frequency: str = "monthly"
    rebalance_days: int = 5
    feature_version: str = settings.default_feature_version

    top_n: int = 5
    threshold: float = 0.55
    execution_price: str = "open"
    transaction_cost: float = 0.001
    horizons: tuple[int, ...] = (1, 5, 10, 20, 40, 60)

    random_trials: int = 200
    bootstrap_rounds: int = 1000
    min_cross_section: int = 20
    random_state: int = 42

    skip_random_baseline: bool = False
    skip_robustness: bool = False
    run_model_grid: bool = False
    cost_grid: tuple[float, ...] = (0.0, 0.0005, 0.001, 0.002, 0.003)
    threshold_grid: tuple[float, ...] = (0.45, 0.50, 0.55, 0.60, 0.65)
    top_n_grid: tuple[int, ...] = (3, 5, 8, 10)
    train_window_grid: tuple[int, ...] = (252, 504, 756)
    n_states_grid: tuple[int, ...] = (2, 3, 4)
    rebalance_grid: tuple[int, ...] = (5, 10, 20)

    report_dir: str = "reports/signal_validation/primary"


@dataclass(frozen=True)
class _ParallelMapInfo:
    enabled: bool
    backend: str
    requested_jobs: int
    warning: str | None = None


def _context_backtest_available() -> bool:
    return run_sector_rotation_backtest is _ORIGINAL_RUN_SECTOR_ROTATION_BACKTEST


def _resolve_parallel_jobs(n_jobs: int | str | None, task_count: int) -> int:
    if task_count <= 1:
        return 1
    value = os.environ.get("BACKTEST_PERF_N_JOBS", n_jobs if n_jobs is not None else "auto")
    if isinstance(value, str) and value.strip().lower() == "auto":
        return min(task_count, max(1, os.cpu_count() or 1))
    try:
        jobs = int(value)
    except (TypeError, ValueError):
        jobs = 1
    if jobs <= 0:
        return min(task_count, max(1, os.cpu_count() or 1))
    return max(1, min(task_count, jobs))


def _parallel_map_ordered(tasks: list[object], worker, n_jobs: int | str | None = "auto") -> tuple[list[object], _ParallelMapInfo]:
    jobs = _resolve_parallel_jobs(n_jobs, len(tasks))
    if jobs <= 1:
        return [worker(task) for task in tasks], _ParallelMapInfo(enabled=False, backend="serial", requested_jobs=1)
    warning: str | None = None
    try:
        from joblib import Parallel, delayed

        delayed_tasks = [delayed(worker)(task) for task in tasks]
        try:
            results = Parallel(n_jobs=jobs, prefer="processes")(delayed_tasks)
            return results, _ParallelMapInfo(enabled=True, backend="processes", requested_jobs=jobs)
        except Exception as process_exc:
            warning = f"process_backend_unavailable_used_threads: {type(process_exc).__name__}: {process_exc}"
            try:
                results = Parallel(n_jobs=jobs, prefer="threads")(delayed_tasks)
                return results, _ParallelMapInfo(enabled=True, backend="threads", requested_jobs=jobs, warning=warning)
            except Exception as thread_exc:
                warning = f"{warning}; thread_backend_failed_serial: {type(thread_exc).__name__}: {thread_exc}"
    except Exception as exc:
        warning = f"parallel_unavailable_serial: {type(exc).__name__}: {exc}"
    return [worker(task) for task in tasks], _ParallelMapInfo(enabled=False, backend="serial", requested_jobs=jobs, warning=warning)


def _attach_parallel_attrs(df: pd.DataFrame, info: _ParallelMapInfo, state_reused: bool) -> pd.DataFrame:
    df.attrs["parallel_enabled"] = bool(info.enabled)
    df.attrs["parallel_backend"] = info.backend
    df.attrs["parallel_requested_jobs"] = int(info.requested_jobs)
    df.attrs["parallel_warning"] = info.warning
    df.attrs["state_context_reused"] = bool(state_reused)
    return df


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, (pd.Timestamp,)):
        return value.isoformat()
    return value


def _write_csv(report_dir: Path, name: str, df: pd.DataFrame) -> None:
    df.to_csv(report_dir / name, index=False)


def _normalize_end_date(config: SignalValidationConfig, ohlcv: pd.DataFrame) -> str | None:
    if config.end_date is None:
        return None
    if str(config.end_date).lower() != "today":
        return config.end_date
    if ohlcv.empty:
        return None
    return pd.to_datetime(ohlcv["trade_date"]).max().strftime("%Y-%m-%d")


def build_data_audit(ohlcv: pd.DataFrame, features: pd.DataFrame) -> pd.DataFrame:
    if ohlcv.empty:
        return pd.DataFrame([{"error": "no sector ohlcv"}])
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    duplicate_key_count = int(work.duplicated(["sector_id", "trade_date"]).sum())
    days_per_sector = work.groupby("sector_id")["trade_date"].nunique()
    feature_valid = features.dropna(subset=[c for c in FEATURE_COLUMNS if c in features.columns]) if not features.empty else pd.DataFrame()
    nan_rates = {
        f"nan_rate_{col}": float(pd.to_numeric(features[col], errors="coerce").isna().mean())
        for col in FEATURE_COLUMNS
        if col in features.columns and not features.empty
    }
    row = {
        "min_trade_date": work["trade_date"].min().date(),
        "max_trade_date": work["trade_date"].max().date(),
        "trade_day_count": int(work["trade_date"].nunique()),
        "sector_count": int(work["sector_id"].nunique()),
        "row_count": int(len(work)),
        "duplicate_key_count": duplicate_key_count,
        "non_positive_open_count": int((pd.to_numeric(work["open"], errors="coerce") <= 0).sum()),
        "non_positive_close_count": int((pd.to_numeric(work["close"], errors="coerce") <= 0).sum()),
        "missing_open_count": int(pd.to_numeric(work["open"], errors="coerce").isna().sum()),
        "missing_close_count": int(pd.to_numeric(work["close"], errors="coerce").isna().sum()),
        "missing_amount_count": int(pd.to_numeric(work["amount"], errors="coerce").isna().sum()) if "amount" in work.columns else int(len(work)),
        "median_days_per_sector": float(days_per_sector.median()),
        "p10_days_per_sector": float(days_per_sector.quantile(0.10)),
        "p90_days_per_sector": float(days_per_sector.quantile(0.90)),
        "feature_valid_row_count": int(len(feature_valid)),
        "feature_valid_sector_count": int(feature_valid["sector_id"].nunique()) if not feature_valid.empty else 0,
        **nan_rates,
    }
    return pd.DataFrame([row])


def compute_tradable_forward_returns(ohlcv: pd.DataFrame, horizons: tuple[int, ...]) -> pd.DataFrame:
    if any(h < 1 for h in horizons):
        raise ValueError("horizon must be >= 1")
    frames: list[pd.DataFrame] = []
    required = ["sector_id", "trade_date", "open", "close"]
    missing = [c for c in required if c not in ohlcv.columns]
    if missing:
        raise ValueError(f"ohlcv missing columns: {missing}")
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    for sector_id, group in work.sort_values(["sector_id", "trade_date"]).groupby("sector_id", sort=False):
        g = group.copy()
        g["exec_date"] = g["trade_date"].shift(-1)
        g["exec_open"] = pd.to_numeric(g["open"], errors="coerce").shift(-1)
        for horizon in horizons:
            exit_close = pd.to_numeric(g["close"], errors="coerce").shift(-horizon)
            g[f"future_exit_date_{horizon}d"] = g["trade_date"].shift(-horizon)
            ret = exit_close / g["exec_open"] - 1
            ret = ret.where(g["exec_open"].notna() & (g["exec_open"] > 0) & exit_close.notna())
            g[f"future_ret_open_{horizon}d"] = ret
        g["sector_id"] = sector_id
        frames.append(g[["sector_id", "trade_date", "exec_date", "exec_open", *sum(([f"future_exit_date_{h}d", f"future_ret_open_{h}d"] for h in horizons), [])]])
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def causality_audit(states: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    checks: list[dict[str, object]] = []

    def add(name: str, passed: bool, details: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "details": details})

    if states.empty:
        add("causal states exist", False, "states is empty")
        return pd.DataFrame(checks)
    state_source_ok = "state_source" in states.columns and states["state_source"].fillna("").astype(str).eq("causal_backtest").all()
    add("state_source == causal_backtest", state_source_ok, "" if state_source_ok else str(states.get("state_source", pd.Series(dtype=str)).dropna().unique().tolist()))
    train_ok = "train_end" in states.columns and (pd.to_datetime(states["train_end"]) <= pd.to_datetime(states["trade_date"])).all()
    add("train_end <= trade_date", train_ok)
    obs_ok = "max_observation_date_used" in states.columns and (pd.to_datetime(states["max_observation_date_used"]) <= pd.to_datetime(states["trade_date"])).all()
    add("max_observation_date_used <= trade_date", obs_ok)
    if trades.empty:
        add("exec_date > signal_date", False, "trades is empty")
    else:
        try:
            assert_execution_after_signal(trades)
            add("exec_date > signal_date", True)
        except AssertionError as exc:
            add("exec_date > signal_date", False, str(exc))
    return pd.DataFrame(checks)


def _bootstrap_date_spread(
    frame: pd.DataFrame,
    left_mask: pd.Series,
    right_mask: pd.Series,
    ret_col: str,
    rounds: int,
    random_state: int,
) -> tuple[float, float, float]:
    work = frame[["trade_date", ret_col]].copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    work[ret_col] = pd.to_numeric(work[ret_col], errors="coerce")
    work["left"] = left_mask.to_numpy()
    work["right"] = right_mask.to_numpy()
    work = work.dropna(subset=[ret_col])
    if work["trade_date"].nunique() < 2 or rounds <= 0:
        return (np.nan, np.nan, np.nan)
    grouped_rows: list[dict[str, float]] = []
    for _, group in work.groupby("trade_date", sort=True):
        left_values = group.loc[group["left"], ret_col]
        right_values = group.loc[group["right"], ret_col]
        grouped_rows.append(
            {
                "left_sum": float(left_values.sum()),
                "left_count": float(left_values.count()),
                "right_sum": float(right_values.sum()),
                "right_count": float(right_values.count()),
            }
        )
    by_date = pd.DataFrame(grouped_rows)
    valid = by_date[(by_date["left_count"] > 0) & (by_date["right_count"] > 0)]
    if len(valid) < 2:
        return (np.nan, np.nan, np.nan)
    values = valid[["left_sum", "left_count", "right_sum", "right_count"]].to_numpy(dtype=float)
    rng = np.random.default_rng(random_state)
    sampled = rng.integers(0, len(values), size=(rounds, len(values)))
    sample_values = values[sampled]
    left_sum = sample_values[:, :, 0].sum(axis=1)
    left_count = sample_values[:, :, 1].sum(axis=1)
    right_sum = sample_values[:, :, 2].sum(axis=1)
    right_count = sample_values[:, :, 3].sum(axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        arr = left_sum / left_count - right_sum / right_count
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return (np.nan, np.nan, np.nan)
    return (float(np.nanquantile(arr, 0.025)), float(np.nanquantile(arr, 0.975)), float((arr <= 0).mean()))


def evaluate_state_forward_returns(signal_frame: pd.DataFrame, horizons: tuple[int, ...], bootstrap_rounds: int = 1000, random_state: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict[str, object]] = []
    spread_rows: list[dict[str, object]] = []
    comparisons = {
        "TrendUp - RiskOff": (lambda df: df["state_label"].eq("TrendUp"), lambda df: df["state_label"].eq("RiskOff")),
        "TrendUp - Neutral": (lambda df: df["state_label"].eq("TrendUp"), lambda df: df["state_label"].eq("Neutral")),
        "TrendUp - NonTrendUp": (lambda df: df["state_label"].eq("TrendUp"), lambda df: ~df["state_label"].eq("TrendUp")),
        "RiskOff - NonRiskOff": (lambda df: df["state_label"].eq("RiskOff"), lambda df: ~df["state_label"].eq("RiskOff")),
    }
    for horizon in horizons:
        ret_col = f"future_ret_open_{horizon}d"
        if ret_col not in signal_frame.columns:
            continue
        for state_label, group in signal_frame.groupby("state_label", dropna=False):
            ret = pd.to_numeric(group[ret_col], errors="coerce").dropna()
            if ret.empty:
                continue
            downside = ret[ret < 0]
            rows.append(
                {
                    "state_label": state_label,
                    "horizon_days": horizon,
                    "mean_return": float(ret.mean()),
                    "median_return": float(ret.median()),
                    "win_rate": float((ret > 0).mean()),
                    "volatility": float(ret.std(ddof=0)),
                    "downside_volatility": float(downside.std(ddof=0)) if len(downside) else 0.0,
                    "p10_return": float(ret.quantile(0.10)),
                    "p25_return": float(ret.quantile(0.25)),
                    "p75_return": float(ret.quantile(0.75)),
                    "p90_return": float(ret.quantile(0.90)),
                    "sample_count": int(len(ret)),
                    "signal_date_count": int(pd.to_datetime(group.loc[ret.index, "trade_date"]).nunique()),
                }
            )
        for name, (left_fn, right_fn) in comparisons.items():
            left_mask = left_fn(signal_frame)
            right_mask = right_fn(signal_frame)
            left = pd.to_numeric(signal_frame.loc[left_mask, ret_col], errors="coerce").dropna()
            right = pd.to_numeric(signal_frame.loc[right_mask, ret_col], errors="coerce").dropna()
            if left.empty or right.empty:
                continue
            ci_low, ci_high, p_value = _bootstrap_date_spread(signal_frame, left_mask, right_mask, ret_col, bootstrap_rounds, random_state + horizon)
            spread_rows.append(
                {
                    "comparison": name,
                    "horizon_days": horizon,
                    "mean_spread": float(left.mean() - right.mean()),
                    "median_spread": float(left.median() - right.median()),
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "bootstrap_p_value": p_value,
                    "sample_count_left": int(len(left)),
                    "sample_count_right": int(len(right)),
                    "signal_date_count": int(pd.to_datetime(signal_frame["trade_date"]).nunique()),
                }
            )
    return pd.DataFrame(rows), pd.DataFrame(spread_rows)


def evaluate_cross_sectional_ic(signal_frame: pd.DataFrame, score_cols: list[str], horizons: tuple[int, ...], min_cross_section: int = 20) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for score_col in score_cols:
        if score_col not in signal_frame.columns:
            continue
        for horizon in horizons:
            ret_col = f"future_ret_open_{horizon}d"
            date_ics: list[float] = []
            for _, group in signal_frame.groupby("trade_date"):
                pair = group[[score_col, ret_col]].apply(pd.to_numeric, errors="coerce").dropna()
                if len(pair) < min_cross_section:
                    continue
                ic = pair[score_col].rank().corr(pair[ret_col].rank())
                if pd.notna(ic):
                    date_ics.append(float(ic))
            if not date_ics:
                continue
            ic_s = pd.Series(date_ics)
            std = float(ic_s.std(ddof=1)) if len(ic_s) > 1 else 0.0
            rows.append(
                {
                    "score_col": score_col,
                    "horizon_days": horizon,
                    "date_count": int(len(ic_s)),
                    "mean_ic": float(ic_s.mean()),
                    "median_ic": float(ic_s.median()),
                    "std_ic": std,
                    "ic_t_stat": float(ic_s.mean() / (std / np.sqrt(len(ic_s)))) if std > 0 else 0.0,
                    "positive_ic_ratio": float((ic_s > 0).mean()),
                    "p10_ic": float(ic_s.quantile(0.10)),
                    "p90_ic": float(ic_s.quantile(0.90)),
                }
            )
    return pd.DataFrame(rows)


def evaluate_score_buckets(signal_frame: pd.DataFrame, score_cols: list[str], horizons: tuple[int, ...], n_buckets: int = 5, min_cross_section: int = 20, bootstrap_rounds: int = 1000, random_state: int = 42) -> tuple[pd.DataFrame, pd.DataFrame]:
    bucket_frames: list[pd.DataFrame] = []
    spread_rows: list[dict[str, object]] = []
    for score_col in score_cols:
        if score_col not in signal_frame.columns:
            continue
        assigned_parts: list[pd.DataFrame] = []
        for _, group in signal_frame.groupby("trade_date"):
            valid = group.dropna(subset=[score_col]).copy()
            if len(valid) < min_cross_section:
                continue
            ranks = valid[score_col].rank(method="first")
            valid["bucket"] = pd.qcut(ranks, q=min(n_buckets, len(valid)), labels=False, duplicates="drop") + 1
            assigned_parts.append(valid)
        if not assigned_parts:
            continue
        assigned = pd.concat(assigned_parts, ignore_index=True)
        for horizon in horizons:
            ret_col = f"future_ret_open_{horizon}d"
            if ret_col not in assigned.columns:
                continue
            for bucket, group in assigned.groupby("bucket"):
                ret = pd.to_numeric(group[ret_col], errors="coerce").dropna()
                if ret.empty:
                    continue
                bucket_frames.append(
                    pd.DataFrame(
                        [
                            {
                                "score_col": score_col,
                                "horizon_days": horizon,
                                "bucket": int(bucket),
                                "mean_return": float(ret.mean()),
                                "median_return": float(ret.median()),
                                "win_rate": float((ret > 0).mean()),
                                "sample_count": int(len(ret)),
                                "signal_date_count": int(group.loc[ret.index, "trade_date"].nunique()),
                            }
                        ]
                    )
                )
            top_bucket = int(assigned["bucket"].max())
            bottom_bucket = int(assigned["bucket"].min())
            left_mask = assigned["bucket"].eq(top_bucket)
            right_mask = assigned["bucket"].eq(bottom_bucket)
            left = pd.to_numeric(assigned.loc[left_mask, ret_col], errors="coerce").dropna()
            right = pd.to_numeric(assigned.loc[right_mask, ret_col], errors="coerce").dropna()
            if left.empty or right.empty:
                continue
            monotonic_flags: list[bool] = []
            for _, date_group in assigned.groupby("trade_date"):
                means = date_group.groupby("bucket")[ret_col].mean().dropna()
                if len(means) >= 3:
                    monotonic_flags.append(float(pd.Series(means.index).corr(pd.Series(means.values), method="spearman")) > 0)
            ci_low, ci_high, p_value = _bootstrap_date_spread(assigned, left_mask, right_mask, ret_col, bootstrap_rounds, random_state + horizon)
            spread_rows.append(
                {
                    "score_col": score_col,
                    "horizon_days": horizon,
                    "top_bucket": top_bucket,
                    "bottom_bucket": bottom_bucket,
                    "mean_spread": float(left.mean() - right.mean()),
                    "bootstrap_ci_low": ci_low,
                    "bootstrap_ci_high": ci_high,
                    "bootstrap_p_value": p_value,
                    "monotonic_date_ratio": float(np.mean(monotonic_flags)) if monotonic_flags else np.nan,
                }
            )
    bucket_df = pd.concat(bucket_frames, ignore_index=True) if bucket_frames else pd.DataFrame()
    return bucket_df, pd.DataFrame(spread_rows)


def _strategy_metrics_from_curve(curve: pd.DataFrame) -> dict[str, float]:
    if curve.empty:
        return {"annual_return_net": 0.0, "max_drawdown_net": 0.0, "sharpe_net": 0.0, "calmar_net": 0.0, "turnover": 0.0}
    nav = (1 + curve["net_return"].fillna(0)).cumprod()
    return {
        "annual_return_net": annual_return(nav),
        "max_drawdown_net": max_drawdown(nav),
        "sharpe_net": sharpe_ratio(curve["net_return"]),
        "calmar_net": calmar_ratio(nav),
        "win_rate_net": win_rate(curve["net_return"]),
        "turnover": float(curve["turnover"].fillna(0).sum()) if "turnover" in curve.columns else 0.0,
    }


def add_strategy_excess_metrics(comparison: pd.DataFrame, curve_long: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if comparison.empty:
        return comparison, pd.DataFrame()
    out = comparison.copy()
    strategy_index = out.set_index("strategy")
    model = strategy_index.loc["model"] if "model" in strategy_index.index else pd.Series(dtype=float)
    rows: list[dict[str, object]] = []
    for baseline in ["baseline_1_rs20_top_n", "baseline_2_equal_weight"]:
        if baseline not in strategy_index.index or model.empty:
            continue
        base = strategy_index.loc[baseline]
        diff_col = f"vs_{baseline}"
        rows.append(
            {
                "comparison": diff_col,
                "excess_annual_return_net": float(model.get("annual_return_net", 0) - base.get("annual_return_net", 0)),
                "excess_sharpe_net": float(model.get("sharpe_net", 0) - base.get("sharpe_net", 0)),
            }
        )
    if not curve_long.empty:
        pivot = curve_long.pivot(index="trade_date", columns="strategy", values="net_return").sort_index()
        if {"model", "baseline_1_rs20_top_n"}.issubset(pivot.columns):
            diff = (pivot["model"] - pivot["baseline_1_rs20_top_n"]).dropna()
            if not diff.empty:
                rows.append(
                    {
                        "comparison": "daily_vs_rs20",
                        "tracking_error_vs_rs20": float(diff.std(ddof=0) * np.sqrt(252)),
                        "information_ratio_vs_rs20": float(diff.mean() / diff.std(ddof=0) * np.sqrt(252)) if diff.std(ddof=0) > 0 else 0.0,
                        "paired_daily_t_stat_vs_rs20": float(diff.mean() / (diff.std(ddof=1) / np.sqrt(len(diff)))) if len(diff) > 1 and diff.std(ddof=1) > 0 else 0.0,
                        "paired_daily_win_rate_vs_rs20": float((diff > 0).mean()),
                    }
                )
    excess_df = pd.DataFrame(rows)
    for baseline in ["baseline_1_rs20_top_n", "baseline_2_equal_weight"]:
        if baseline in strategy_index.index and "model" in strategy_index.index:
            out[f"excess_annual_return_net_vs_{baseline}"] = np.where(out["strategy"].eq("model"), float(strategy_index.loc["model", "annual_return_net"] - strategy_index.loc[baseline, "annual_return_net"]), np.nan)
            out[f"excess_sharpe_net_vs_{baseline}"] = np.where(out["strategy"].eq("model"), float(strategy_index.loc["model", "sharpe_net"] - strategy_index.loc[baseline, "sharpe_net"]), np.nan)
    return out, excess_df


def _prepare_backtest_context_from_config(config: SignalValidationConfig, storage: DuckDBStorage) -> SectorRotationBacktestContext:
    return prepare_sector_rotation_backtest_context(
        rebalance_days=config.rebalance_days,
        start_date=config.start_date,
        end_date=config.end_date,
        train_window_days=config.train_window_days,
        n_states=config.n_states,
        walk_forward=True,
        retrain_frequency=config.retrain_frequency,
        feature_version=config.feature_version,
        allow_in_sample_demo=False,
        universe_id=config.universe_id,
        include_custom_baskets=config.include_custom_baskets,
        storage=storage,
    )


def _run_backtest_direct(
    config: SignalValidationConfig,
    storage: DuckDBStorage,
    *,
    threshold: float,
    top_n: int,
    transaction_cost: float,
) -> dict[str, object]:
    return run_sector_rotation_backtest(
        threshold=float(threshold),
        top_n=int(top_n),
        rebalance_days=config.rebalance_days,
        start_date=config.start_date,
        end_date=config.end_date,
        train_window_days=config.train_window_days,
        n_states=config.n_states,
        execution_price=config.execution_price,
        transaction_cost=float(transaction_cost),
        walk_forward=True,
        retrain_frequency=config.retrain_frequency,
        allow_in_sample_demo=False,
        universe_id=config.universe_id,
        include_custom_baskets=config.include_custom_baskets,
        storage=storage,
    )


def _evaluate_cost_sensitivity_direct(config: SignalValidationConfig, storage: DuckDBStorage, costs: tuple[float, ...]) -> pd.DataFrame:
    rows: list[pd.DataFrame] = []
    for cost in costs:
        result = _run_backtest_direct(
            config,
            storage,
            threshold=config.threshold,
            top_n=config.top_n,
            transaction_cost=float(cost),
        )
        comparison, _ = add_strategy_excess_metrics(result.get("comparison", pd.DataFrame()), result.get("curve_long", pd.DataFrame()))
        if not comparison.empty:
            comparison = comparison.copy()
            comparison["transaction_cost"] = float(cost)
            rows.append(comparison)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def _cost_sensitivity_worker(task: tuple[SectorRotationBacktestContext, float, int, str, float, bool]) -> pd.DataFrame:
    context, threshold, top_n, execution_price, cost, cache_hit_override = task
    result = run_sector_rotation_backtest_from_context(
        context,
        threshold=float(threshold),
        top_n=int(top_n),
        execution_price=execution_price,
        transaction_cost=float(cost),
        cache_hit_override=cache_hit_override,
    )
    comparison, _ = add_strategy_excess_metrics(result.get("comparison", pd.DataFrame()), result.get("curve_long", pd.DataFrame()))
    if comparison.empty:
        return pd.DataFrame()
    comparison = comparison.copy()
    comparison["transaction_cost"] = float(cost)
    return comparison


def evaluate_cost_sensitivity(
    config: SignalValidationConfig,
    storage: DuckDBStorage,
    costs: tuple[float, ...],
    *,
    context: SectorRotationBacktestContext | None = None,
    n_jobs: int | str | None = "auto",
) -> pd.DataFrame:
    validate_state_neutral_backtest_params(["transaction_cost"])
    built_context_here = False
    if context is None and _context_backtest_available():
        context = _prepare_backtest_context_from_config(config, storage)
        built_context_here = True
    if context is None:
        out = _evaluate_cost_sensitivity_direct(config, storage, costs)
        return _attach_parallel_attrs(out, _ParallelMapInfo(False, "serial", 1), state_reused=False)

    tasks: list[tuple[SectorRotationBacktestContext, float, int, str, float, bool]] = []
    for idx, cost in enumerate(costs):
        if context.walk_forward:
            cache_hit_override = bool(context.cache_hit) if built_context_here and idx == 0 else True
        else:
            cache_hit_override = bool(context.cache_hit)
        tasks.append((context, float(config.threshold), int(config.top_n), config.execution_price, float(cost), cache_hit_override))
    results, info = _parallel_map_ordered(tasks, _cost_sensitivity_worker, n_jobs=n_jobs)
    frames = [result for result in results if isinstance(result, pd.DataFrame) and not result.empty]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return _attach_parallel_attrs(out, info, state_reused=True)


def _evaluate_random_baseline_direct(
    ohlcv: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    top_n: int,
    transaction_cost: float,
    random_trials: int,
    random_state: int,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if random_trials <= 0 or not signal_dates:
        return pd.DataFrame(), pd.DataFrame()
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    open_prices = work.pivot(index="trade_date", columns="sector_id", values="open").sort_index()
    close_prices = work.pivot(index="trade_date", columns="sector_id", values="close").sort_index()
    trade_dates = pd.Series(close_prices.index)
    rng = np.random.default_rng(random_state)
    rows: list[dict[str, object]] = []
    for trial in range(random_trials):
        events: list[dict[str, object]] = []
        for signal_date in signal_dates:
            signal_date = pd.Timestamp(signal_date)
            exec_date = next_trade_date(trade_dates, signal_date)
            if exec_date is None or signal_date not in close_prices.index:
                continue
            available = close_prices.loc[signal_date].dropna().index.astype(str).tolist()
            if not available:
                continue
            chosen = rng.choice(available, size=min(top_n, len(available)), replace=False).tolist()
            weight = 1.0 / len(chosen)
            events.append({"signal_date": signal_date, "exec_date": exec_date, "weights": {sid: weight for sid in chosen}})
        if not events:
            continue
        curve, _ = simulate_portfolio_returns(open_prices, close_prices, pd.DataFrame(events), execution_price="open", transaction_cost=transaction_cost)
        metrics = _strategy_metrics_from_curve(curve)
        rows.append({"trial": trial, **metrics})
    baseline = pd.DataFrame(rows)
    if baseline.empty:
        return baseline, pd.DataFrame()
    summary_rows: list[dict[str, object]] = []
    for metric in ["annual_return_net", "max_drawdown_net", "sharpe_net", "calmar_net", "turnover"]:
        values = pd.to_numeric(baseline[metric], errors="coerce").dropna()
        if values.empty:
            continue
        summary_rows.append(
            {
                "metric": metric,
                "random_mean": float(values.mean()),
                "random_median": float(values.median()),
                "random_p75": float(values.quantile(0.75)),
                "random_p90": float(values.quantile(0.90)),
                "random_p95": float(values.quantile(0.95)),
            }
        )
    return baseline, pd.DataFrame(summary_rows)


def evaluate_random_baseline(
    ohlcv: pd.DataFrame,
    signal_dates: list[pd.Timestamp],
    top_n: int,
    transaction_cost: float,
    random_trials: int,
    random_state: int,
    n_jobs: int | str | None = "auto",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if random_trials <= 0 or not signal_dates:
        return pd.DataFrame(), pd.DataFrame()
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    open_prices = work.pivot(index="trade_date", columns="sector_id", values="open").sort_index()
    close_prices = work.pivot(index="trade_date", columns="sector_id", values="close").sort_index()
    trade_dates = pd.Series(close_prices.index)
    rng = np.random.default_rng(random_state)
    tasks: list[tuple[int, pd.DataFrame, pd.DataFrame, pd.DataFrame, float]] = []
    for trial in range(random_trials):
        events: list[dict[str, object]] = []
        for signal_date in signal_dates:
            signal_date = pd.Timestamp(signal_date)
            exec_date = next_trade_date(trade_dates, signal_date)
            if exec_date is None or signal_date not in close_prices.index:
                continue
            available = close_prices.loc[signal_date].dropna().index.astype(str).tolist()
            if not available:
                continue
            chosen = rng.choice(available, size=min(top_n, len(available)), replace=False).tolist()
            weight = 1.0 / len(chosen)
            events.append({"signal_date": signal_date, "exec_date": exec_date, "weights": {sid: weight for sid in chosen}})
        tasks.append((trial, pd.DataFrame(events), open_prices, close_prices, float(transaction_cost)))
    results, info = _parallel_map_ordered(tasks, _random_baseline_worker, n_jobs=n_jobs)
    rows = [result for result in results if isinstance(result, dict)]
    baseline = pd.DataFrame(rows)
    if baseline.empty:
        return _attach_parallel_attrs(baseline, info, state_reused=False), pd.DataFrame()
    summary_rows: list[dict[str, object]] = []
    for metric in ["annual_return_net", "max_drawdown_net", "sharpe_net", "calmar_net", "turnover"]:
        values = pd.to_numeric(baseline[metric], errors="coerce").dropna()
        if values.empty:
            continue
        summary_rows.append(
            {
                "metric": metric,
                "random_mean": float(values.mean()),
                "random_median": float(values.median()),
                "random_p75": float(values.quantile(0.75)),
                "random_p90": float(values.quantile(0.90)),
                "random_p95": float(values.quantile(0.95)),
            }
        )
    baseline = _attach_parallel_attrs(baseline, info, state_reused=False)
    summary = _attach_parallel_attrs(pd.DataFrame(summary_rows), info, state_reused=False)
    return baseline, summary


def _random_baseline_worker(task: tuple[int, pd.DataFrame, pd.DataFrame, pd.DataFrame, float]) -> dict[str, object] | None:
    trial, events, open_prices, close_prices, transaction_cost = task
    if events.empty:
        return None
    curve, _ = simulate_portfolio_returns(open_prices, close_prices, events, execution_price="open", transaction_cost=transaction_cost)
    metrics = _strategy_metrics_from_curve(curve)
    return {"trial": int(trial), **metrics}


def evaluate_period_breakdown(curve_long: pd.DataFrame) -> pd.DataFrame:
    if curve_long.empty:
        return pd.DataFrame()
    work = curve_long.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    years = work["trade_date"].dt.year.nunique()
    if years >= 3:
        work["period"] = work["trade_date"].dt.year.astype(str)
    else:
        unique_dates = pd.Series(work["trade_date"].drop_duplicates().sort_values()).reset_index(drop=True)
        bins = pd.qcut(unique_dates.index, q=min(3, len(unique_dates)), labels=[f"part_{i}" for i in range(1, min(3, len(unique_dates)) + 1)])
        date_to_period = dict(zip(unique_dates, bins.astype(str), strict=False))
        work["period"] = work["trade_date"].map(date_to_period)
    rows: list[dict[str, object]] = []
    for (period, strategy), group in work.groupby(["period", "strategy"]):
        metrics = _strategy_metrics_from_curve(group.sort_values("trade_date"))
        rows.append({"period": period, "strategy": strategy, **metrics})
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    rs = out[out["strategy"].eq("baseline_1_rs20_top_n")][["period", "annual_return_net"]].rename(columns={"annual_return_net": "rs20_return"})
    out = out.merge(rs, on="period", how="left")
    out["excess_return_vs_rs20"] = out["annual_return_net"] - out["rs20_return"]
    return out.drop(columns=["rs20_return"])


def _evaluate_selection_grid_direct(config: SignalValidationConfig, storage: DuckDBStorage) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for threshold in config.threshold_grid:
        for top_n in config.top_n_grid:
            result = _run_backtest_direct(
                config,
                storage,
                threshold=float(threshold),
                top_n=int(top_n),
                transaction_cost=config.transaction_cost,
            )
            comparison, _ = add_strategy_excess_metrics(result.get("comparison", pd.DataFrame()), result.get("curve_long", pd.DataFrame()))
            model = comparison[comparison["strategy"].eq("model")].head(1)
            if model.empty:
                continue
            row = model.iloc[0].to_dict()
            rows.append(
                {
                    "n_states": config.n_states,
                    "train_window_days": config.train_window_days,
                    "rebalance_days": config.rebalance_days,
                    "threshold": float(threshold),
                    "top_n": int(top_n),
                    "transaction_cost": config.transaction_cost,
                    "cache_hit": bool(result.get("cache_hit", False)),
                    "signal_count": int(result.get("states", pd.DataFrame()).get("trade_date", pd.Series(dtype=object)).nunique()),
                    "trade_count": int(len(result.get("trades", pd.DataFrame()))),
                    **{k: row.get(k) for k in ["annual_return_net", "max_drawdown_net", "sharpe_net", "calmar_net", "turnover", "excess_annual_return_net_vs_baseline_1_rs20_top_n", "excess_sharpe_net_vs_baseline_1_rs20_top_n"]},
                }
            )
    return pd.DataFrame(rows)


def _selection_grid_worker(task: tuple[SectorRotationBacktestContext, SignalValidationConfig, float, int, bool]) -> dict[str, object] | None:
    context, config, threshold, top_n, cache_hit_override = task
    result = run_sector_rotation_backtest_from_context(
        context,
        threshold=float(threshold),
        top_n=int(top_n),
        execution_price=config.execution_price,
        transaction_cost=config.transaction_cost,
        cache_hit_override=cache_hit_override,
    )
    comparison, _ = add_strategy_excess_metrics(result.get("comparison", pd.DataFrame()), result.get("curve_long", pd.DataFrame()))
    model = comparison[comparison["strategy"].eq("model")].head(1)
    if model.empty:
        return None
    row = model.iloc[0].to_dict()
    return {
        "n_states": config.n_states,
        "train_window_days": config.train_window_days,
        "rebalance_days": config.rebalance_days,
        "threshold": float(threshold),
        "top_n": int(top_n),
        "transaction_cost": config.transaction_cost,
        "cache_hit": bool(result.get("cache_hit", False)),
        "signal_count": int(result.get("states", pd.DataFrame()).get("trade_date", pd.Series(dtype=object)).nunique()),
        "trade_count": int(len(result.get("trades", pd.DataFrame()))),
        **{
            k: row.get(k)
            for k in [
                "annual_return_net",
                "max_drawdown_net",
                "sharpe_net",
                "calmar_net",
                "turnover",
                "excess_annual_return_net_vs_baseline_1_rs20_top_n",
                "excess_sharpe_net_vs_baseline_1_rs20_top_n",
            ]
        },
    }


def evaluate_selection_grid(
    config: SignalValidationConfig,
    storage: DuckDBStorage,
    *,
    context: SectorRotationBacktestContext | None = None,
    n_jobs: int | str | None = "auto",
) -> pd.DataFrame:
    validate_state_neutral_backtest_params(["threshold", "top_n", "transaction_cost"])
    built_context_here = False
    if context is None and _context_backtest_available():
        context = _prepare_backtest_context_from_config(config, storage)
        built_context_here = True
    if context is None:
        out = _evaluate_selection_grid_direct(config, storage)
        return _attach_parallel_attrs(out, _ParallelMapInfo(False, "serial", 1), state_reused=False)

    tasks: list[tuple[SectorRotationBacktestContext, SignalValidationConfig, float, int, bool]] = []
    idx = 0
    for threshold in config.threshold_grid:
        for top_n in config.top_n_grid:
            if context.walk_forward:
                cache_hit_override = bool(context.cache_hit) if built_context_here and idx == 0 else True
            else:
                cache_hit_override = bool(context.cache_hit)
            tasks.append((context, config, float(threshold), int(top_n), cache_hit_override))
            idx += 1
    results, info = _parallel_map_ordered(tasks, _selection_grid_worker, n_jobs=n_jobs)
    rows = [result for result in results if isinstance(result, dict)]
    out = pd.DataFrame(rows)
    return _attach_parallel_attrs(out, info, state_reused=True)


def _resolve_config_dates(config: SignalValidationConfig, ohlcv: pd.DataFrame) -> SignalValidationConfig:
    end_date = _normalize_end_date(config, ohlcv)
    start_date = config.start_date
    if start_date and str(start_date).lower() == "today":
        start_date = pd.to_datetime(ohlcv["trade_date"]).max().strftime("%Y-%m-%d")
    return SignalValidationConfig(**{**asdict(config), "start_date": start_date, "end_date": end_date})


def _build_signal_frame(
    states: pd.DataFrame,
    ohlcv: pd.DataFrame,
    horizons: tuple[int, ...],
    feature_scope_id: str = "all",
    feature_scope_type: str = "all",
    features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if features is None:
        from src.backtest.sector_rotation import _build_raw_features

        features = _build_raw_features(ohlcv, feature_version=settings.default_feature_version, feature_scope_id=feature_scope_id, feature_scope_type=feature_scope_type)
    else:
        features = features.copy()
    states_work = states.copy()
    states_work["trade_date"] = pd.to_datetime(states_work["trade_date"])
    features["trade_date"] = pd.to_datetime(features["trade_date"])
    ranked_input = states_work.merge(
        features[["sector_id", "trade_date", *[c for c in FEATURE_COLUMNS if c in features.columns]]],
        on=["sector_id", "trade_date"],
        how="left",
    )
    ranked = rank_sectors(ranked_input)
    ranked["score_prob_only"] = pd.to_numeric(ranked["prob_trend_up"], errors="coerce")
    ranked["score_prob_spread"] = pd.to_numeric(ranked["prob_trend_up"], errors="coerce") - pd.to_numeric(ranked["prob_risk_off"], errors="coerce")
    ranked["score_ranker"] = pd.to_numeric(ranked["sector_score"], errors="coerce")
    forward = compute_tradable_forward_returns(ohlcv, horizons)
    out = ranked.merge(forward, on=["sector_id", "trade_date"], how="left")
    return out.sort_values(["trade_date", "sector_id"]).reset_index(drop=True)


def _summary_conclusion(
    causality: pd.DataFrame,
    signal_frame: pd.DataFrame,
    state_spreads: pd.DataFrame,
    score_ic: pd.DataFrame,
    comparison: pd.DataFrame,
    random_summary: pd.DataFrame,
    cost_sensitivity: pd.DataFrame,
    robustness_selection: pd.DataFrame,
) -> tuple[str, str]:
    if causality.empty or not causality["passed"].all():
        return "Invalid", "因果性审计未通过，不能判断信号有效性。"
    if signal_frame["trade_date"].nunique() < 20:
        return "Invalid", "有效信号日过少，无法评估。"
    evidence = 0
    reasons: list[str] = []
    spread_focus = state_spreads[
        state_spreads["comparison"].eq("TrendUp - RiskOff")
        & state_spreads["horizon_days"].isin([20, 40])
    ]
    if not spread_focus.empty and (spread_focus["mean_spread"] > 0).mean() >= 0.5:
        evidence += 1
        reasons.append("TrendUp 相对 RiskOff 的中期 forward return 为正。")
    ic_focus = score_ic[score_ic["score_col"].isin(["score_prob_spread", "score_ranker"]) & score_ic["horizon_days"].isin([5, 20, 40])]
    if not ic_focus.empty and ((ic_focus["mean_ic"] > 0) & (ic_focus["positive_ic_ratio"] > 0.55)).any():
        evidence += 1
        reasons.append("HMM 概率/评分在部分 horizon 有正 IC。")
    if not comparison.empty:
        model = comparison[comparison["strategy"].eq("model")]
        rs = comparison[comparison["strategy"].eq("baseline_1_rs20_top_n")]
        ew = comparison[comparison["strategy"].eq("baseline_2_equal_weight")]
        if not model.empty and not ew.empty and float(model.iloc[0]["annual_return_net"]) > float(ew.iloc[0]["annual_return_net"]):
            evidence += 1
            reasons.append("模型扣费后年化收益优于等权。")
        if not model.empty and not rs.empty and float(model.iloc[0]["annual_return_net"]) > float(rs.iloc[0]["annual_return_net"]):
            evidence += 1
            reasons.append("模型扣费后年化收益优于 RS20。")
    if not random_summary.empty and "model_percentile_vs_random" in random_summary.columns:
        sharpe = random_summary[random_summary["metric"].eq("sharpe_net")]
        if not sharpe.empty and float(sharpe.iloc[0]["model_percentile_vs_random"]) >= 0.75:
            evidence += 1
            reasons.append("模型 Sharpe 位于随机基准 75% 分位以上。")
    if not cost_sensitivity.empty:
        c2 = cost_sensitivity[cost_sensitivity["transaction_cost"].eq(0.002)]
        model = c2[c2["strategy"].eq("model")]
        rs = c2[c2["strategy"].eq("baseline_1_rs20_top_n")]
        if not model.empty and not rs.empty and float(model.iloc[0]["annual_return_net"]) > float(rs.iloc[0]["annual_return_net"]):
            evidence += 1
            reasons.append("成本升至 0.2% 时仍优于 RS20。")
    if not robustness_selection.empty and "excess_annual_return_net_vs_baseline_1_rs20_top_n" in robustness_selection.columns:
        ratio = pd.to_numeric(robustness_selection["excess_annual_return_net_vs_baseline_1_rs20_top_n"], errors="coerce").gt(0).mean()
        if ratio >= 0.5:
            evidence += 1
            reasons.append("多数选择参数配置保持相对 RS20 正超额。")
    if evidence >= 6:
        return "Strong", " ".join(reasons)
    if evidence >= 4:
        return "Moderate", " ".join(reasons)
    if evidence >= 2:
        return "Weak", " ".join(reasons)
    return "No Evidence", "目前缺少足够证据证明 HMM 信号稳定有效。"


def _write_summary(report_dir: Path, config: SignalValidationConfig, outputs: dict[str, Any], conclusion: tuple[str, str]) -> None:
    def table(df: pd.DataFrame, max_rows: int = 12) -> str:
        if df is None or df.empty:
            return "无数据"
        return "```text\n" + df.head(max_rows).to_string(index=False) + "\n```"

    audit = outputs.get("data_audit", pd.DataFrame())
    causality = outputs.get("causality_audit", pd.DataFrame())
    comparison = outputs.get("strategy_comparison", pd.DataFrame())
    state_forward = outputs.get("state_forward_returns", pd.DataFrame())
    score_ic = outputs.get("score_ic", pd.DataFrame())
    bucket_spreads = outputs.get("score_bucket_spreads", pd.DataFrame())
    random_summary = outputs.get("random_baseline_summary", pd.DataFrame())
    robustness_selection = outputs.get("robustness_selection_grid", pd.DataFrame())
    cost_sensitivity = outputs.get("cost_sensitivity", pd.DataFrame())
    signal_frame = outputs.get("signal_frame", pd.DataFrame())

    selected_state = state_forward[state_forward["horizon_days"].isin([5, 20, 40])] if not state_forward.empty else state_forward
    selected_ic = score_ic[score_ic["horizon_days"].isin([5, 20, 40])] if not score_ic.empty else score_ic

    lines = [
        "# HMM 信号有效性验证报告",
        "",
        "## 1. 结论",
        "",
        f"结论等级：{conclusion[0]}",
        "",
        f"一句话结论：{conclusion[1]}",
        "",
        "## 2. 配置",
        "",
        f"- 数据库：{config.db_path or settings.db_path}",
        f"- 日期范围：{config.start_date} 至 {config.end_date}",
        f"- Universe：{config.universe_id or '全市场'}",
        f"- n_states：{config.n_states}",
        f"- train_window_days：{config.train_window_days}",
        f"- rebalance_days：{config.rebalance_days}",
        f"- top_n：{config.top_n}",
        f"- threshold：{config.threshold}",
        f"- transaction_cost：{config.transaction_cost}",
        "",
        "## 3. 数据覆盖",
        "",
        table(audit),
        "",
        f"- 有效信号日：{signal_frame['trade_date'].nunique() if not signal_frame.empty else 0}",
        f"- 状态样本数：{len(signal_frame)}",
        "",
        "## 4. 因果性审计",
        "",
        table(causality),
        "",
        "## 5. 状态后续收益",
        "",
        table(selected_state),
        "",
        "## 6. 排序能力",
        "",
        table(selected_ic),
        "",
        "## 7. 分组收益",
        "",
        table(bucket_spreads[bucket_spreads["horizon_days"].isin([5, 20, 40])] if not bucket_spreads.empty else bucket_spreads),
        "",
        "## 8. 策略对照",
        "",
        table(comparison),
        "",
        "## 9. 成本敏感性",
        "",
        table(cost_sensitivity[cost_sensitivity["strategy"].eq("model")] if not cost_sensitivity.empty else cost_sensitivity),
        "",
        "## 10. 随机基准",
        "",
        "未执行随机基准。" if config.skip_random_baseline else table(random_summary),
        "",
        "## 11. 鲁棒性",
        "",
        "未执行鲁棒性网格。" if config.skip_robustness else table(robustness_selection),
        "",
        "## 12. 风险和限制",
        "",
        "- HMM 后验概率不是上涨概率，必须通过 forward return / IC / 组合回测解释。",
        "- 默认收益按下一交易日开盘买入计算，不使用信号日收盘成交假设。",
        "- 数据源来自本地 DuckDB，结论受板块覆盖、个股覆盖、缓存状态和接口质量影响。",
        "- 参数网格只用于鲁棒性检查，不能把最优参数当成主结论。",
        "",
        "## 13. 后续建议",
        "",
        "- 若结论为 Weak 或 No Evidence，优先检查状态分层、IC 和随机基准，而不是继续增加模型复杂度。",
        "- 后续可扩大样本区间并开启模型结构网格，但要保持 primary config 先验登记。",
    ]
    (report_dir / "summary.md").write_text("\n".join(lines), encoding="utf-8")


def run_signal_validation(config: SignalValidationConfig) -> dict[str, pd.DataFrame | dict]:
    storage = DuckDBStorage(config.db_path) if config.db_path else DuckDBStorage()
    storage.init_schema()
    full_ohlcv = load_sector_like_ohlcv(storage, universe_id=config.universe_id, include_custom_baskets=config.include_custom_baskets)
    if full_ohlcv.empty:
        raise ValueError("缺少板块行情数据，无法验证信号。")
    resolved_config = _resolve_config_dates(config, full_ohlcv)
    ohlcv = full_ohlcv.copy()
    if resolved_config.start_date:
        ohlcv = ohlcv[pd.to_datetime(ohlcv["trade_date"]) >= pd.to_datetime(resolved_config.start_date)].copy()
    if resolved_config.end_date:
        ohlcv = ohlcv[pd.to_datetime(ohlcv["trade_date"]) <= pd.to_datetime(resolved_config.end_date)].copy()
    if ohlcv.empty:
        raise ValueError("指定日期范围内缺少板块行情。")

    feature_scope_id, feature_scope_type = feature_scope_for_universe(storage, resolved_config.universe_id, resolved_config.include_custom_baskets)
    backtest_context: SectorRotationBacktestContext | None = None
    if _context_backtest_available():
        backtest_context = _prepare_backtest_context_from_config(resolved_config, storage)
        features_full = backtest_context.features.copy()
    else:
        from src.backtest.sector_rotation import _build_raw_features

        features_full = _build_raw_features(full_ohlcv, feature_version=resolved_config.feature_version, feature_scope_id=feature_scope_id, feature_scope_type=feature_scope_type)
    audit_features = features_full
    if resolved_config.start_date:
        audit_features = audit_features[pd.to_datetime(audit_features["trade_date"]) >= pd.to_datetime(resolved_config.start_date)].copy()
    if resolved_config.end_date:
        audit_features = audit_features[pd.to_datetime(audit_features["trade_date"]) <= pd.to_datetime(resolved_config.end_date)].copy()
    data_audit = build_data_audit(ohlcv, audit_features)
    if int(data_audit.loc[0, "duplicate_key_count"]) > 0:
        raise ValueError("数据审计失败：存在重复 sector_id + trade_date。")
    if int(data_audit.loc[0, "non_positive_open_count"]) > 0 or int(data_audit.loc[0, "non_positive_close_count"]) > 0:
        raise ValueError("数据审计失败：存在 open/close <= 0。")

    if backtest_context is not None:
        result = run_sector_rotation_backtest_from_context(
            backtest_context,
            threshold=resolved_config.threshold,
            top_n=resolved_config.top_n,
            execution_price=resolved_config.execution_price,
            transaction_cost=resolved_config.transaction_cost,
        )
    else:
        result = _run_backtest_direct(
            resolved_config,
            storage,
            threshold=resolved_config.threshold,
            top_n=resolved_config.top_n,
            transaction_cost=resolved_config.transaction_cost,
        )
    states = result.get("states", pd.DataFrame())
    trades = result.get("trades", pd.DataFrame())
    causality = causality_audit(states, trades)
    if not causality["passed"].all():
        signal_frame = pd.DataFrame()
    else:
        signal_frame = _build_signal_frame(states, full_ohlcv, resolved_config.horizons, feature_scope_id, feature_scope_type, features=features_full)

    score_cols = ["score_prob_only", "score_prob_spread", "score_ranker", "rs_20d", "ret_20d"]
    if signal_frame.empty:
        state_forward = state_spreads = score_ic = bucket_returns = bucket_spreads = pd.DataFrame()
    else:
        state_forward, state_spreads = evaluate_state_forward_returns(signal_frame, resolved_config.horizons, resolved_config.bootstrap_rounds, resolved_config.random_state)
        score_ic = evaluate_cross_sectional_ic(signal_frame, score_cols, resolved_config.horizons, resolved_config.min_cross_section)
        bucket_returns, bucket_spreads = evaluate_score_buckets(signal_frame, score_cols, resolved_config.horizons, min_cross_section=resolved_config.min_cross_section, bootstrap_rounds=resolved_config.bootstrap_rounds, random_state=resolved_config.random_state)

    comparison, excess_metrics = add_strategy_excess_metrics(result.get("comparison", pd.DataFrame()), result.get("curve_long", pd.DataFrame()))
    cost_sensitivity = evaluate_cost_sensitivity(resolved_config, storage, resolved_config.cost_grid, context=backtest_context)
    signal_dates = sorted(pd.to_datetime(states["trade_date"].drop_duplicates()).tolist()) if not states.empty else []
    if resolved_config.skip_random_baseline:
        random_baseline = random_summary = pd.DataFrame()
    else:
        random_baseline, random_summary = evaluate_random_baseline(full_ohlcv, signal_dates, resolved_config.top_n, resolved_config.transaction_cost, resolved_config.random_trials, resolved_config.random_state)
        if not random_summary.empty and not comparison.empty:
            model_row = comparison[comparison["strategy"].eq("model")]
            if not model_row.empty:
                model_values = model_row.iloc[0].to_dict()
                for idx, row in random_summary.iterrows():
                    metric = str(row["metric"])
                    model_value = float(model_values.get(metric, np.nan))
                    random_values = pd.to_numeric(random_baseline[metric], errors="coerce").dropna() if metric in random_baseline.columns else pd.Series(dtype=float)
                    random_summary.loc[idx, "model_value"] = model_value
                    random_summary.loc[idx, "model_percentile_vs_random"] = float((random_values <= model_value).mean()) if not random_values.empty else np.nan
                    random_summary.loc[idx, "empirical_p_value_random_ge_model"] = float((random_values >= model_value).mean()) if not random_values.empty else np.nan

    robustness_selection = pd.DataFrame() if resolved_config.skip_robustness else evaluate_selection_grid(resolved_config, storage, context=backtest_context)
    robustness_model = pd.DataFrame()
    period_breakdown = evaluate_period_breakdown(result.get("curve_long", pd.DataFrame()))
    conclusion = _summary_conclusion(causality, signal_frame, state_spreads, score_ic, comparison, random_summary, cost_sensitivity, robustness_selection)

    report_dir = Path(resolved_config.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    config_payload = {k: _to_jsonable(v) for k, v in asdict(resolved_config).items()}
    (report_dir / "config.json").write_text(json.dumps(config_payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")

    outputs: dict[str, pd.DataFrame | dict] = {
        "data_audit": data_audit,
        "causality_audit": causality,
        "causal_states": states,
        "signal_frame": signal_frame,
        "state_forward_returns": state_forward,
        "state_spread_tests": state_spreads,
        "score_ic": score_ic,
        "score_bucket_returns": bucket_returns,
        "score_bucket_spreads": bucket_spreads,
        "strategy_comparison": comparison,
        "strategy_curve": result.get("curve", pd.DataFrame()),
        "strategy_curve_long": result.get("curve_long", pd.DataFrame()),
        "strategy_trades": trades,
        "strategy_excess_metrics": excess_metrics,
        "cost_sensitivity": cost_sensitivity,
        "random_baseline": random_baseline,
        "random_baseline_summary": random_summary,
        "robustness_selection_grid": robustness_selection,
        "robustness_model_grid": robustness_model,
        "period_breakdown": period_breakdown,
        "summary": {
            "conclusion_level": conclusion[0],
            "conclusion_text": conclusion[1],
            "report_dir": str(report_dir),
            "cache_hit": bool(result.get("cache_hit", False)),
            "run_id": result.get("run_id"),
            "backtest_state_context_reused": backtest_context is not None,
            "cost_parallel_backend": cost_sensitivity.attrs.get("parallel_backend"),
            "cost_parallel_enabled": bool(cost_sensitivity.attrs.get("parallel_enabled", False)),
            "random_parallel_backend": random_baseline.attrs.get("parallel_backend") if isinstance(random_baseline, pd.DataFrame) else None,
            "random_parallel_enabled": bool(random_baseline.attrs.get("parallel_enabled", False)) if isinstance(random_baseline, pd.DataFrame) else False,
            "selection_parallel_backend": robustness_selection.attrs.get("parallel_backend") if isinstance(robustness_selection, pd.DataFrame) else None,
            "selection_parallel_enabled": bool(robustness_selection.attrs.get("parallel_enabled", False)) if isinstance(robustness_selection, pd.DataFrame) else False,
        },
    }
    for name, value in outputs.items():
        if isinstance(value, pd.DataFrame):
            _write_csv(report_dir, f"{name}.csv", value)
    _write_summary(report_dir, resolved_config, outputs, conclusion)
    return outputs


def _parse_tuple_int(text: str) -> tuple[int, ...]:
    return tuple(int(x.strip()) for x in text.split(",") if x.strip())


def _parse_tuple_float(text: str) -> tuple[float, ...]:
    return tuple(float(x.strip()) for x in text.split(",") if x.strip())


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 HMM 板块信号有效性")
    parser.add_argument("--db-path", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default="today")
    parser.add_argument("--universe-id", default=None)
    parser.add_argument("--exclude-custom-baskets", action="store_true")
    parser.add_argument("--n-states", type=int, default=3)
    parser.add_argument("--train-window-days", type=int, default=504)
    parser.add_argument("--retrain-frequency", default="monthly")
    parser.add_argument("--rebalance-days", type=int, default=5)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.55)
    parser.add_argument("--execution-price", default="open")
    parser.add_argument("--transaction-cost", type=float, default=0.001)
    parser.add_argument("--horizons", default="1,5,10,20,40,60")
    parser.add_argument("--random-trials", type=int, default=200)
    parser.add_argument("--bootstrap-rounds", type=int, default=1000)
    parser.add_argument("--min-cross-section", type=int, default=20)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--skip-random-baseline", action="store_true")
    parser.add_argument("--skip-robustness", action="store_true")
    parser.add_argument("--run-model-grid", action="store_true")
    parser.add_argument("--cost-grid", default="0,0.0005,0.001,0.002,0.003")
    parser.add_argument("--threshold-grid", default="0.45,0.50,0.55,0.60,0.65")
    parser.add_argument("--top-n-grid", default="3,5,8,10")
    parser.add_argument("--train-window-grid", default="252,504,756")
    parser.add_argument("--n-states-grid", default="2,3,4")
    parser.add_argument("--rebalance-grid", default="5,10,20")
    parser.add_argument("--report-dir", default="reports/signal_validation/primary")
    args = parser.parse_args()
    config = SignalValidationConfig(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        universe_id=args.universe_id,
        include_custom_baskets=not args.exclude_custom_baskets,
        n_states=args.n_states,
        train_window_days=args.train_window_days,
        retrain_frequency=args.retrain_frequency,
        rebalance_days=args.rebalance_days,
        top_n=args.top_n,
        threshold=args.threshold,
        execution_price=args.execution_price,
        transaction_cost=args.transaction_cost,
        horizons=_parse_tuple_int(args.horizons),
        random_trials=args.random_trials,
        bootstrap_rounds=args.bootstrap_rounds,
        min_cross_section=args.min_cross_section,
        random_state=args.random_state,
        skip_random_baseline=args.skip_random_baseline,
        skip_robustness=args.skip_robustness,
        run_model_grid=args.run_model_grid,
        cost_grid=_parse_tuple_float(args.cost_grid),
        threshold_grid=_parse_tuple_float(args.threshold_grid),
        top_n_grid=_parse_tuple_int(args.top_n_grid),
        train_window_grid=_parse_tuple_int(args.train_window_grid),
        n_states_grid=_parse_tuple_int(args.n_states_grid),
        rebalance_grid=_parse_tuple_int(args.rebalance_grid),
        report_dir=args.report_dir,
    )
    outputs = run_signal_validation(config)
    summary = outputs["summary"]
    print(f"报告目录：{summary['report_dir']}")
    print(f"结论等级：{summary['conclusion_level']}")
    print(f"结论：{summary['conclusion_text']}")


if __name__ == "__main__":
    main()
