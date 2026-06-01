from __future__ import annotations

import pandas as pd

from src.backtest.sector_rotation import run_sector_rotation_backtest
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv, universe_sector_ids


def _empty_forward_result(reason: str) -> pd.DataFrame:
    df = pd.DataFrame()
    df.attrs["warning"] = reason
    return df


def _normalize_cache_universe(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text in {"", "all", "None", "nan", "<NA>"} else text


def _cache_match_warning(
    cache_row: pd.Series,
    run_row: pd.Series,
    universe_id: str | None,
    scope: str,
    expected_cache_params: dict[str, object] | None = None,
) -> str:
    if pd.isna(cache_row.get("params_hash")) and pd.isna(cache_row.get("params_json")):
        return "该 walk-forward 缓存缺少参数记录，无法确认是否匹配当前评估范围。请重新运行因果回测生成新缓存。"

    expected_universe = universe_id if scope == "universe" else None
    cache_universe = _normalize_cache_universe(cache_row.get("universe_id"))
    if cache_universe != expected_universe:
        return f"walk-forward 缓存的板块池不匹配：缓存={cache_universe or '全市场'}，当前={expected_universe or '全市场'}。"

    run_feature_version = str(run_row.get("feature_version") or "")
    cache_feature_version = str(cache_row.get("feature_version") or "")
    if run_feature_version and cache_feature_version and cache_feature_version != run_feature_version:
        return f"walk-forward 缓存的特征版本不匹配：缓存={cache_feature_version}，当前 run={run_feature_version}。"

    run_scope_id = str(run_row.get("feature_scope_id") or ("all" if pd.isna(run_row.get("universe_id")) else run_row.get("universe_id")))
    cache_scope_id = cache_row.get("feature_scope_id")
    if pd.isna(cache_scope_id):
        return "该 walk-forward 缓存缺少 feature_scope_id，无法确认特征作用域。请重新运行因果回测生成新缓存。"
    if str(cache_scope_id) != run_scope_id:
        return f"walk-forward 缓存的特征作用域不匹配：缓存={cache_scope_id}，当前 run={run_scope_id}。"

    run_include_custom = bool(run_row.get("include_custom_baskets", True))
    cache_include_custom = cache_row.get("include_custom_baskets")
    if pd.isna(cache_include_custom):
        return "该 walk-forward 缓存缺少 include_custom_baskets 参数，无法确认是否匹配当前评估范围。"
    if bool(cache_include_custom) != run_include_custom:
        return "walk-forward 缓存的自定义股票池包含方式与当前 run 不一致。"

    for key, expected_value in (expected_cache_params or {}).items():
        if key not in cache_row.index:
            continue
        cache_value = cache_row.get(key)
        if pd.isna(cache_value):
            return f"walk-forward 缓存缺少参数 {key}，无法确认匹配。"
        if str(cache_value) != str(expected_value):
            return f"walk-forward 缓存参数 {key} 不匹配：缓存={cache_value}，当前={expected_value}。"
    return ""


def _scope_filter(df: pd.DataFrame, storage: DuckDBStorage, universe_id: str | None, scope: str) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if universe_id and scope == "universe":
        allowed = set(universe_sector_ids(storage, universe_id, include_custom_baskets=True))
        out = out[out["sector_id"].astype(str).isin(allowed)]
    if scope == "industry" and "sector_type" in out.columns:
        out = out[out["sector_type"].astype(str).eq("industry")]
    elif scope == "concept" and "sector_type" in out.columns:
        out = out[out["sector_type"].astype(str).eq("concept")]
    elif scope == "custom" and "sector_id" in out.columns:
        out = out[out["sector_id"].astype(str).str.startswith("custom:")]
    return out


def evaluate_forward_returns(
    storage: DuckDBStorage,
    run_id: str,
    horizons: tuple[int, ...] = (5, 20),
    universe_id: str | None = None,
    scope: str = "all",
    state_source: str = "in_sample_display",
    cache_key: str | None = None,
    expected_cache_params: dict[str, object] | None = None,
) -> pd.DataFrame:
    run = storage.get_model_run(run_id)
    if run.empty:
        return pd.DataFrame()
    run_row = run.iloc[0]
    ohlcv = load_sector_like_ohlcv(storage, universe_id=universe_id if scope == "universe" else None, include_custom_baskets=True)
    if ohlcv.empty:
        return pd.DataFrame()
    meta = storage.read_df("SELECT sector_id, sector_type, sector_name FROM sector_meta")
    if state_source == "walk_forward":
        if cache_key is None:
            return _empty_forward_result("选择因果 walk-forward 状态评估时必须指定 cache_key；不会自动使用最新缓存。")
        cache_run = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key])
        if cache_run.empty:
            return _empty_forward_result(f"找不到 walk-forward 缓存：{cache_key}")
        mismatch = _cache_match_warning(cache_run.iloc[0], run_row, universe_id, scope, expected_cache_params)
        if mismatch:
            return _empty_forward_result(mismatch)
        states = storage.read_df(
            """
            SELECT sector_id, trade_date, state_label,
                   COALESCE(state_source, 'causal_backtest') AS state_source
            FROM walk_forward_state_cache
            WHERE cache_key = ?
            """,
            [cache_key],
        )
    else:
        states = storage.read_df(
            """
            SELECT sector_id, trade_date, state_label, state_source
            FROM sector_state_daily
            WHERE run_id = ?
            """,
            [run_id],
        )
    if states.empty:
        return pd.DataFrame()
    states = states.merge(meta, on="sector_id", how="left")
    states = _scope_filter(states, storage, universe_id, scope)
    prices = ohlcv.copy()
    prices["trade_date"] = pd.to_datetime(prices["trade_date"])
    prices = prices.sort_values(["sector_id", "trade_date"])
    for horizon in horizons:
        prices[f"future_ret_{horizon}d"] = prices.groupby("sector_id")["close"].shift(-horizon) / prices["close"] - 1
    merged = states.copy()
    merged["trade_date"] = pd.to_datetime(merged["trade_date"])
    merged = merged.merge(prices[["sector_id", "trade_date", *[f"future_ret_{h}d" for h in horizons]]], on=["sector_id", "trade_date"], how="left")
    rows: list[dict[str, object]] = []
    for state_label, group in merged.groupby("state_label", dropna=False):
        for horizon in horizons:
            col = f"future_ret_{horizon}d"
            ret = pd.to_numeric(group[col], errors="coerce").dropna()
            if ret.empty:
                continue
            rows.append(
                {
                    "state_label": state_label,
                    "horizon_days": horizon,
                    "mean_return": float(ret.mean()),
                    "median_return": float(ret.median()),
                    "win_rate": float((ret > 0).mean()),
                    "volatility": float(ret.std(ddof=0)),
                    "sample_count": int(len(ret)),
                    "state_source": state_source,
                    "cache_key": cache_key,
                }
            )
    return pd.DataFrame(rows).sort_values(["state_label", "horizon_days"]) if rows else pd.DataFrame()


def evaluate_state_stability(storage: DuckDBStorage, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    states = storage.read_df(
        """
        SELECT sector_id, trade_date, state_label
        FROM sector_state_daily
        WHERE run_id = ?
        ORDER BY sector_id, trade_date
        """,
        [run_id],
    )
    if states.empty:
        return pd.DataFrame(), pd.DataFrame()
    states["trade_date"] = pd.to_datetime(states["trade_date"])
    states["segment"] = states.groupby("sector_id")["state_label"].transform(lambda s: (s != s.shift()).cumsum())
    segments = states.groupby(["sector_id", "segment", "state_label"], as_index=False).agg(start=("trade_date", "min"), end=("trade_date", "max"), days=("trade_date", "count"))
    summary = states.groupby("state_label").size().rename("sample_count").reset_index()
    avg_duration = segments.groupby("state_label")["days"].mean().rename("avg_duration_days").reset_index()
    summary = summary.merge(avg_duration, on="state_label", how="left")
    summary["state_share"] = summary["sample_count"] / summary["sample_count"].sum()

    ordered = states.copy()
    ordered["next_label"] = ordered.groupby("sector_id")["state_label"].shift(-1)
    transitions = pd.crosstab(ordered["state_label"], ordered["next_label"], normalize="index").fillna(0).reset_index()
    return summary.sort_values("state_label"), transitions


def evaluate_strategy_comparison(
    storage: DuckDBStorage,
    run_id: str,
    universe_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    top_n: int = 5,
    threshold: float = 0.55,
    transaction_cost: float = 0.001,
) -> pd.DataFrame:
    result = run_sector_rotation_backtest(
        run_id=run_id,
        threshold=threshold,
        top_n=top_n,
        start_date=start_date,
        end_date=end_date,
        transaction_cost=transaction_cost,
        walk_forward=True,
        allow_in_sample_demo=False,
        universe_id=universe_id,
        storage=storage,
    )
    comparison = result.get("comparison", pd.DataFrame())
    if not comparison.empty:
        comparison = comparison.copy()
        comparison["same_universe"] = "是" if universe_id else "全市场"
        comparison["uses_transaction_cost"] = transaction_cost > 0
        comparison["causal_walk_forward"] = True
    return comparison
