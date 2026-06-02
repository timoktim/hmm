from __future__ import annotations

from collections.abc import Callable

import pandas as pd

from src.backtest.metrics import annual_return, calmar_ratio, max_drawdown, sharpe_ratio, win_rate
from src.config import settings
from src.data_pipeline.calendar import assert_execution_after_signal, next_trade_date
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv, universe_sector_ids
from src.features.sector_features import FEATURE_COLUMNS, add_sector_features, equal_weight_benchmark_ret20_from_close, feature_scope_for_universe
from src.models.walk_forward import ProgressCallback, WalkForwardConfig, walk_forward_hmm_state_frame
from src.scoring.sector_ranker import rank_sectors
from src.utils.lineage import build_model_lineage_payload, canonical_json, hash_payload, is_valid_cache_metadata

Weights = dict[str, float]

_HMM_WALK_FORWARD_MODEL_VERSION = "stage03pf-wp2"
_HMM_WALK_FORWARD_CODE_VERSION = "stage03pf-wp2"
_HMM_WALK_FORWARD_TOL = 0.01


class LineageMismatchError(ValueError):
    pass


def _load_sector_ohlcv(
    storage: DuckDBStorage,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
) -> pd.DataFrame:
    return load_sector_like_ohlcv(storage, universe_id=universe_id, include_custom_baskets=include_custom_baskets)


def _build_raw_features(
    ohlcv: pd.DataFrame,
    feature_version: str = settings.default_feature_version,
    feature_scope_id: str = "all",
    feature_scope_type: str = "all",
) -> pd.DataFrame:
    tmp = ohlcv.copy()
    tmp["trade_date"] = pd.to_datetime(tmp["trade_date"])
    daily_close = tmp.pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmark_ret20 = equal_weight_benchmark_ret20_from_close(daily_close)
    features = add_sector_features(
        tmp,
        benchmark_ret20=benchmark_ret20,
        feature_version=feature_version,
        apply_winsorize=False,
        feature_scope_id=feature_scope_id,
        feature_scope_type=feature_scope_type,
    )
    features["trade_date"] = pd.to_datetime(features["trade_date"])
    return features


def estimate_backtest_signal_count(
    storage: DuckDBStorage,
    start_date: str | None = None,
    end_date: str | None = None,
    rebalance_days: int = 5,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
) -> dict[str, int]:
    ohlcv = _load_sector_ohlcv(storage, universe_id=universe_id, include_custom_baskets=include_custom_baskets)
    if ohlcv.empty:
        return {"state_dates": 0, "rebalance_signals": 0}
    trade_dates = pd.to_datetime(ohlcv["trade_date"].drop_duplicates()).sort_values()
    if start_date:
        trade_dates = trade_dates[trade_dates >= pd.to_datetime(start_date)]
    if end_date:
        trade_dates = trade_dates[trade_dates <= pd.to_datetime(end_date)]
    signal_dates = trade_dates[:: max(1, rebalance_days)]
    return {
        "candidate_trade_dates": int(len(trade_dates)),
        "state_dates": int(len(signal_dates)),
        "rebalance_signals": int(len(signal_dates)),
    }


def _digest_frame(df: pd.DataFrame, columns: list[str]) -> str:
    available = [column for column in columns if column in df.columns]
    if not available:
        return hash_payload({"columns": [], "rows": []})
    rows = df[available].copy()
    sort_columns = [column for column in ["sector_id", "trade_date"] if column in rows.columns]
    if sort_columns:
        rows = rows.sort_values(sort_columns).reset_index(drop=True)
    return hash_payload({"columns": available, "rows": rows.to_dict("records")})


def _digest_trade_calendar(dates: pd.Series | list[pd.Timestamp]) -> str:
    normalized = sorted(pd.to_datetime(pd.Series(dates)).dropna().dt.date.astype(str).unique().tolist())
    return hash_payload({"trade_dates": normalized})


def _digest_universe_membership(ohlcv: pd.DataFrame, universe_id: str | None, include_custom_baskets: bool) -> str:
    sector_ids = sorted(ohlcv["sector_id"].dropna().astype(str).unique().tolist()) if "sector_id" in ohlcv.columns else []
    return hash_payload(
        {
            "universe_id": universe_id or "all",
            "include_custom_baskets": bool(include_custom_baskets),
            "sector_ids": sector_ids,
        }
    )


def _digest_custom_basket_membership(ohlcv: pd.DataFrame, include_custom_baskets: bool) -> str | None:
    if not include_custom_baskets or "sector_id" not in ohlcv.columns:
        return None
    custom_ids = sorted(sector_id for sector_id in ohlcv["sector_id"].dropna().astype(str).unique() if sector_id.startswith("custom"))
    return hash_payload({"custom_sector_ids": custom_ids})


def _feature_lineage_hash(features: pd.DataFrame, feature_version: str, feature_scope_id: str, feature_scope_type: str) -> str:
    sector_ids = sorted(features["sector_id"].dropna().astype(str).unique().tolist()) if "sector_id" in features.columns else []
    trade_dates = pd.to_datetime(features["trade_date"]).dropna() if "trade_date" in features.columns else pd.Series(dtype="datetime64[ns]")
    return hash_payload(
        {
            "feature_version": feature_version,
            "feature_scope_id": feature_scope_id,
            "feature_scope_type": feature_scope_type,
            "feature_columns": list(FEATURE_COLUMNS),
            "sector_ids": sector_ids,
            "start_date": trade_dates.min().date() if len(trade_dates) else None,
            "end_date": trade_dates.max().date() if len(trade_dates) else None,
            "row_count": int(len(features)),
        }
    )


def _normalize_cache_universe(value: object) -> str:
    if value is None or pd.isna(value):
        return "all"
    text = str(value)
    return "all" if text in {"", "all", "None", "nan"} else text


def _attach_feature_lineage_hash(features: pd.DataFrame, feature_lineage_hash: str, universe_id: str | None = None) -> pd.DataFrame:
    out = features.copy()
    out["feature_lineage_hash"] = feature_lineage_hash
    out["universe_id"] = _normalize_cache_universe(universe_id)
    return out


def _validate_state_feature_merge(states: pd.DataFrame, features: pd.DataFrame, cache_params: dict[str, object]) -> None:
    expected_feature_lineage_hash = str(cache_params.get("feature_lineage_hash") or "")
    expected_feature_scope_id = str(cache_params.get("feature_scope_id") or "")
    expected_universe_id = _normalize_cache_universe(cache_params.get("universe_id"))
    if not expected_feature_lineage_hash:
        raise LineageMismatchError("missing expected feature_lineage_hash")
    if "feature_lineage_hash" not in states.columns or states["feature_lineage_hash"].isna().any():
        raise LineageMismatchError("cached states missing feature_lineage_hash")
    state_hashes = set(states["feature_lineage_hash"].astype(str).dropna().unique())
    if state_hashes != {expected_feature_lineage_hash}:
        raise LineageMismatchError("cached states feature_lineage_hash mismatch")
    if "feature_lineage_hash" not in features.columns or features["feature_lineage_hash"].isna().any():
        raise LineageMismatchError("current features missing feature_lineage_hash")
    feature_hashes = set(features["feature_lineage_hash"].astype(str).dropna().unique())
    if feature_hashes != {expected_feature_lineage_hash}:
        raise LineageMismatchError("current features feature_lineage_hash mismatch")
    if "feature_scope_id" not in features.columns:
        raise LineageMismatchError("current features missing feature_scope_id")
    feature_scope_ids = set(features["feature_scope_id"].astype(str).dropna().unique())
    if feature_scope_ids != {expected_feature_scope_id}:
        raise LineageMismatchError("current features feature_scope_id mismatch")
    if "universe_id" in features.columns:
        feature_universe_ids = {_normalize_cache_universe(value) for value in features["universe_id"].dropna().unique()}
        if feature_universe_ids != {expected_universe_id}:
            raise LineageMismatchError("current features universe_id mismatch")
    if not {"sector_id", "trade_date"}.issubset(states.columns) or not {"sector_id", "trade_date"}.issubset(features.columns):
        raise LineageMismatchError("state/feature date coverage cannot be checked")
    state_keys = set(
        zip(
            states["sector_id"].astype(str),
            pd.to_datetime(states["trade_date"]).dt.normalize(),
            strict=False,
        )
    )
    feature_keys = set(
        zip(
            features["sector_id"].astype(str),
            pd.to_datetime(features["trade_date"]).dt.normalize(),
            strict=False,
        )
    )
    if not state_keys.issubset(feature_keys):
        raise LineageMismatchError("current features do not cover cached state dates")


def _cache_params_with_lineage(params: dict[str, object]) -> dict[str, object]:
    enriched = dict(params)
    model_params = dict(enriched.get("model_params") or {})
    model_params.setdefault("n_states", int(enriched.get("n_states", 3) or 3))
    model_params.setdefault("random_state", int(enriched.get("random_state", 42) or 42))
    model_params.setdefault("n_iter", int(enriched.get("n_iter", 300) or 300))
    model_params.setdefault("tol", enriched.get("tol", _HMM_WALK_FORWARD_TOL))

    preprocess_params = dict(enriched.get("preprocess_params") or {})
    preprocess_params.setdefault("min_train_rows", int(enriched.get("min_train_rows", 120) or 120))
    preprocess_params.setdefault("min_sequence_length", int(enriched.get("min_sequence_length", 30) or 30))
    preprocess_params.setdefault("apply_winsorize", bool(enriched.get("apply_winsorize", False)))

    train_window_policy = dict(enriched.get("train_window_policy") or {})
    train_window_policy.setdefault("train_window_days", enriched.get("train_window_days"))
    train_window_policy.setdefault("retrain_frequency", enriched.get("retrain_frequency"))

    state_date_policy = dict(enriched.get("state_date_policy") or {})
    state_date_policy.setdefault("mode", enriched.get("state_date_mode"))
    state_date_policy.setdefault("rebalance_days", enriched.get("rebalance_days"))

    enriched["model_params"] = model_params
    enriched["preprocess_params"] = preprocess_params
    enriched["train_window_policy"] = train_window_policy
    enriched["state_date_policy"] = state_date_policy
    enriched.setdefault("feature_columns", list(FEATURE_COLUMNS))
    enriched.setdefault("data_snapshot_hash", hash_payload({"data_snapshot": "unknown"}))
    enriched.setdefault("universe_membership_hash", hash_payload({"universe": enriched.get("universe_id", "all")}))
    enriched.setdefault("calendar_hash", hash_payload({"calendar": "unknown"}))
    enriched.setdefault(
        "feature_lineage_hash",
        hash_payload(
            {
                "feature_version": enriched.get("feature_version"),
                "feature_scope_id": enriched.get("feature_scope_id"),
                "feature_columns": enriched.get("feature_columns"),
            }
        ),
    )

    lineage_payload = build_model_lineage_payload(
        model_family="GaussianHMM",
        model_version=str(enriched.get("model_version") or _HMM_WALK_FORWARD_MODEL_VERSION),
        code_version=str(enriched.get("code_version") or _HMM_WALK_FORWARD_CODE_VERSION),
        feature_version=str(enriched.get("feature_version") or ""),
        feature_scope_id=str(enriched.get("feature_scope_id") or "all"),
        feature_columns=enriched["feature_columns"],
        model_params=model_params,
        preprocess_params=preprocess_params,
        train_window_policy=train_window_policy,
        state_date_policy=state_date_policy,
        universe_id=str(enriched.get("universe_id") or "all"),
        universe_membership_hash=str(enriched.get("universe_membership_hash") or ""),
        custom_basket_membership_hash=enriched.get("custom_basket_membership_hash"),
        data_snapshot_hash=str(enriched.get("data_snapshot_hash") or ""),
        calendar_hash=str(enriched.get("calendar_hash") or ""),
        cache_contract_version="stage03pf-wp2",
    )
    enriched["lineage_json"] = canonical_json(lineage_payload)
    enriched["lineage_hash"] = str(enriched.get("lineage_hash") or hash_payload(lineage_payload))
    return enriched


def _build_walk_forward_cache_params(
    *,
    ohlcv: pd.DataFrame,
    features: pd.DataFrame,
    trade_dates: pd.Series,
    config: WalkForwardConfig,
    feature_version: str,
    start_ts: pd.Timestamp,
    end_ts: pd.Timestamp,
    rebalance_days: int,
    state_date_mode: str,
    universe_id: str | None,
    scope_type: str,
    feature_scope_id: str,
    feature_scope_type: str,
    include_custom_baskets: bool,
) -> dict[str, object]:
    base_params: dict[str, object] = {
        "n_states": int(config.n_states),
        "train_window_days": config.train_window_days,
        "retrain_frequency": config.retrain_frequency,
        "random_state": int(config.random_state),
        "n_iter": int(config.n_iter),
        "tol": _HMM_WALK_FORWARD_TOL,
        "min_train_rows": int(config.min_train_rows),
        "min_sequence_length": int(config.min_sequence_length),
        "feature_columns": list(FEATURE_COLUMNS),
        "feature_version": feature_version,
        "start_date": start_ts.date(),
        "end_date": end_ts.date(),
        "rebalance_days": int(rebalance_days),
        "state_date_mode": state_date_mode,
        "universe_id": universe_id or "all",
        "scope_type": scope_type,
        "feature_scope_id": feature_scope_id,
        "feature_scope_type": feature_scope_type,
        "include_custom_baskets": bool(include_custom_baskets),
        "data_snapshot_hash": _digest_frame(
            ohlcv,
            ["sector_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source"],
        ),
        "universe_membership_hash": _digest_universe_membership(ohlcv, universe_id, include_custom_baskets),
        "custom_basket_membership_hash": _digest_custom_basket_membership(ohlcv, include_custom_baskets),
        "calendar_hash": _digest_trade_calendar(trade_dates),
        "feature_lineage_hash": _feature_lineage_hash(features, feature_version, feature_scope_id, feature_scope_type),
    }
    return _cache_params_with_lineage(base_params)


def _walk_forward_cache_key(params: dict[str, object]) -> str:
    enriched = _cache_params_with_lineage(params)
    return f"hmmwf_{enriched['lineage_hash']}"


def _read_walk_forward_cache(
    storage: DuckDBStorage,
    cache_key: str,
    expected_lineage_hash: str,
    expected_feature_lineage_hash: str | None = None,
    expected_feature_scope_id: str | None = None,
    expected_universe_id: str | None = None,
) -> pd.DataFrame:
    run = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key])
    if run.empty:
        return pd.DataFrame()
    run_row = run.iloc[0].to_dict()
    if not is_valid_cache_metadata(run_row, expected_lineage_hash=expected_lineage_hash):
        return pd.DataFrame()
    if expected_feature_lineage_hash is not None and str(run_row.get("feature_lineage_hash") or "") != expected_feature_lineage_hash:
        return pd.DataFrame()
    if expected_feature_scope_id is not None and str(run_row.get("feature_scope_id") or "") != expected_feature_scope_id:
        return pd.DataFrame()
    if expected_universe_id is not None and _normalize_cache_universe(run_row.get("universe_id")) != _normalize_cache_universe(expected_universe_id):
        return pd.DataFrame()
    states = storage.read_df("SELECT * FROM walk_forward_state_cache WHERE cache_key = ? ORDER BY trade_date, sector_id", [cache_key])
    try:
        reported_row_count = int(run_row.get("row_count") or 0)
    except (TypeError, ValueError):
        return pd.DataFrame()
    if reported_row_count != len(states):
        return pd.DataFrame()
    if states.empty:
        return states
    if expected_feature_lineage_hash is not None:
        if "feature_lineage_hash" not in states.columns or states["feature_lineage_hash"].isna().any():
            return pd.DataFrame()
        if set(states["feature_lineage_hash"].astype(str).dropna().unique()) != {expected_feature_lineage_hash}:
            return pd.DataFrame()
    for col in ["trade_date", "train_start", "train_end", "max_observation_date_used"]:
        if col in states.columns:
            states[col] = pd.to_datetime(states[col])
    if "max_observation_date_used" not in states.columns or "trade_date" not in states.columns:
        return pd.DataFrame()
    if states["max_observation_date_used"].gt(states["trade_date"]).any():
        return pd.DataFrame()
    states = states.drop(columns=["cache_key"], errors="ignore")
    return states


def _write_walk_forward_cache(
    storage: DuckDBStorage,
    cache_key: str,
    states: pd.DataFrame,
    params: dict[str, object],
    signal_count: int,
) -> None:
    params = _cache_params_with_lineage(params)
    expected_cache_key = _walk_forward_cache_key(params)
    if cache_key != expected_cache_key:
        raise ValueError("cache_key must be derived from lineage_hash")
    if states.empty:
        row_count = 0
        state_rows = states
    else:
        state_rows = states.copy()
        state_rows["cache_key"] = cache_key
        state_rows["lineage_hash"] = params["lineage_hash"]
        state_rows["feature_lineage_hash"] = params["feature_lineage_hash"]
        leading_cols = ["cache_key"] + [col for col in state_rows.columns if col != "cache_key"]
        state_rows = state_rows[leading_cols]
        for col in ["trade_date", "train_start", "train_end", "max_observation_date_used"]:
            state_rows[col] = pd.to_datetime(state_rows[col]).dt.date
        row_count = len(state_rows)
        storage.upsert_df("walk_forward_state_cache", state_rows, ["cache_key", "sector_id", "trade_date"])
    params_json = canonical_json(params)
    params_hash = hash_payload(params, length=40)
    cache_universe = params.get("universe_id")
    if cache_universe in {"", "all"}:
        cache_universe = None
    run_df = pd.DataFrame(
        [
            {
                "cache_key": cache_key,
                "n_states": int(params["n_states"]),
                "train_window_days": params["train_window_days"],
                "retrain_frequency": params["retrain_frequency"],
                "feature_version": params["feature_version"],
                "start_date": pd.to_datetime(params["start_date"]).date(),
                "end_date": pd.to_datetime(params["end_date"]).date(),
                "params_json": params_json,
                "params_hash": params_hash,
                "universe_id": cache_universe,
                "scope_type": params.get("scope_type", "all"),
                "include_custom_baskets": bool(params.get("include_custom_baskets", True)),
                "rebalance_days": int(params.get("rebalance_days", 0) or 0),
                "state_date_mode": params.get("state_date_mode"),
                "feature_scope_id": params.get("feature_scope_id"),
                "lineage_json": params["lineage_json"],
                "lineage_hash": params["lineage_hash"],
                "feature_lineage_hash": params["feature_lineage_hash"],
                "universe_membership_hash": params["universe_membership_hash"],
                "data_snapshot_hash": params["data_snapshot_hash"],
                "cache_status": "completed",
                "signal_count": signal_count,
                "row_count": row_count,
                "created_at": pd.Timestamp.now(),
                "completed_at": pd.Timestamp.now(),
            }
        ]
    )
    storage.upsert_df("walk_forward_cache_runs", run_df, ["cache_key"])


def _equal_weights(sector_ids: list[str]) -> Weights:
    sector_ids = [s for s in sector_ids if isinstance(s, str)]
    if not sector_ids:
        return {}
    weight = 1.0 / len(sector_ids)
    return {sector_id: weight for sector_id in sector_ids}


def _turnover(old: Weights, new: Weights) -> float:
    keys = set(old) | set(new)
    return float(sum(abs(new.get(k, 0.0) - old.get(k, 0.0)) for k in keys))


def _weighted_return(returns: pd.Series, weights: Weights) -> float:
    if not weights:
        return 0.0
    total = 0.0
    for sector_id, weight in weights.items():
        value = returns.get(sector_id, 0.0)
        if pd.notna(value):
            total += weight * float(value)
    return float(total)


def simulate_portfolio_returns(
    open_prices: pd.DataFrame,
    close_prices: pd.DataFrame,
    target_events: pd.DataFrame,
    execution_price: str = "open",
    transaction_cost: float = 0.001,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    if execution_price not in {"open", "close"}:
        raise ValueError("execution_price 必须是 open 或 close")
    events = target_events.copy()
    if events.empty:
        return pd.DataFrame(), pd.DataFrame()
    events["exec_date"] = pd.to_datetime(events["exec_date"])
    event_map = {pd.Timestamp(row["exec_date"]): row["weights"] for _, row in events.iterrows()}
    open_prices = open_prices.sort_index()
    close_prices = close_prices.sort_index()
    close_ret = close_prices.pct_change().fillna(0)
    overnight_ret = (open_prices / close_prices.shift(1) - 1).replace([float("inf"), float("-inf")], pd.NA).fillna(0)
    intraday_ret = (close_prices / open_prices - 1).replace([float("inf"), float("-inf")], pd.NA).fillna(0)

    current_weights: Weights = {}
    rows: list[dict[str, object]] = []
    trade_rows: list[dict[str, object]] = []
    started = False
    all_dates = pd.Series(close_prices.index)
    for trade_date in all_dates:
        trade_date = pd.Timestamp(trade_date)
        target = event_map.get(trade_date)
        if not started and target is None:
            continue
        turnover = 0.0
        cost = 0.0
        if execution_price == "open":
            old_weights = current_weights
            overnight = _weighted_return(overnight_ret.loc[trade_date], old_weights)
            weights_for_intraday = old_weights
            if target is not None:
                turnover = _turnover(old_weights, target)
                cost = turnover * transaction_cost
                current_weights = target
                weights_for_intraday = target
                trade_rows.append({"exec_date": trade_date, "turnover": turnover, "cost": cost, "weights": target})
            intraday = _weighted_return(intraday_ret.loc[trade_date], weights_for_intraday)
            gross_return = (1 + overnight) * (1 + intraday) - 1
            net_return = (1 + overnight) * (1 - cost) * (1 + intraday) - 1
        else:
            holding_return = _weighted_return(close_ret.loc[trade_date], current_weights)
            gross_return = holding_return
            if target is not None:
                turnover = _turnover(current_weights, target)
                cost = turnover * transaction_cost
                trade_rows.append({"exec_date": trade_date, "turnover": turnover, "cost": cost, "weights": target})
                current_weights = target
            net_return = (1 + holding_return) * (1 - cost) - 1

        started = True
        rows.append(
            {
                "trade_date": trade_date,
                "gross_return": float(gross_return),
                "net_return": float(net_return),
                "cost": float(cost),
                "turnover": float(turnover),
            }
        )

    curve = pd.DataFrame(rows)
    if curve.empty:
        return curve, pd.DataFrame(trade_rows)
    curve["nav_gross"] = (1 + curve["gross_return"].fillna(0)).cumprod()
    curve["nav_net"] = (1 + curve["net_return"].fillna(0)).cumprod()
    return curve, pd.DataFrame(trade_rows)


def _strategy_metrics(curve: pd.DataFrame) -> dict[str, float]:
    if curve.empty:
        return {
            "annual_return_gross": 0.0,
            "annual_return_net": 0.0,
            "max_drawdown_gross": 0.0,
            "max_drawdown_net": 0.0,
            "sharpe_gross": 0.0,
            "sharpe_net": 0.0,
            "calmar_gross": 0.0,
            "calmar_net": 0.0,
            "win_rate_net": 0.0,
            "turnover": 0.0,
        }
    return {
        "annual_return_gross": annual_return(curve["nav_gross"]),
        "annual_return_net": annual_return(curve["nav_net"]),
        "max_drawdown_gross": max_drawdown(curve["nav_gross"]),
        "max_drawdown_net": max_drawdown(curve["nav_net"]),
        "sharpe_gross": sharpe_ratio(curve["gross_return"]),
        "sharpe_net": sharpe_ratio(curve["net_return"]),
        "calmar_gross": calmar_ratio(curve["nav_gross"]),
        "calmar_net": calmar_ratio(curve["nav_net"]),
        "win_rate_net": win_rate(curve["net_return"]),
        "turnover": float(curve["turnover"].sum()),
    }


def _make_events(
    signal_dates: list[pd.Timestamp],
    trade_dates: pd.Series,
    choose_weights: Callable[[pd.Timestamp], Weights],
    strategy: str,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for signal_date in signal_dates:
        exec_date = next_trade_date(trade_dates, signal_date)
        if exec_date is None:
            continue
        weights = choose_weights(pd.Timestamp(signal_date))
        rows.append(
            {
                "strategy": strategy,
                "signal_date": pd.Timestamp(signal_date),
                "exec_date": exec_date,
                "holdings": ",".join(weights),
                "weights": weights,
            }
        )
    events = pd.DataFrame(rows)
    if not events.empty:
        assert_execution_after_signal(events)
    return events


def run_sector_rotation_backtest(
    run_id: str | None = None,
    threshold: float = 0.55,
    top_n: int = 5,
    rebalance_days: int = 5,
    start_date: str | None = None,
    end_date: str | None = None,
    train_window_days: int | None = 504,
    n_states: int = 3,
    execution_price: str = "open",
    transaction_cost: float = 0.001,
    walk_forward: bool = True,
    retrain_frequency: str = "monthly",
    feature_version: str = settings.default_feature_version,
    allow_in_sample_demo: bool = False,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
    progress_callback: ProgressCallback | None = None,
    storage: DuckDBStorage | None = None,
) -> dict[str, object]:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    ohlcv = _load_sector_ohlcv(storage, universe_id=universe_id, include_custom_baskets=include_custom_baskets)
    if ohlcv.empty:
        raise ValueError("缺少板块行情数据。")
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    feature_scope_id, feature_scope_type = feature_scope_for_universe(storage, universe_id, include_custom_baskets)
    features = _build_raw_features(
        ohlcv,
        feature_version=feature_version,
        feature_scope_id=feature_scope_id,
        feature_scope_type=feature_scope_type,
    )
    storage.upsert_df("sector_features", features, ["sector_id", "trade_date", "feature_version", "feature_scope_id"])
    cache_params: dict[str, object] | None = None
    if start_date:
        start_ts = pd.to_datetime(start_date)
    else:
        start_ts = features["trade_date"].min()
    if end_date:
        end_ts = pd.to_datetime(end_date)
    else:
        end_ts = features["trade_date"].max()

    open_prices = ohlcv.pivot(index="trade_date", columns="sector_id", values="open").sort_index()
    close_prices = ohlcv.pivot(index="trade_date", columns="sector_id", values="close").sort_index()
    trade_dates = pd.Series(close_prices.index)
    base_signal_dates = sorted(features[(features["trade_date"] >= start_ts) & (features["trade_date"] <= end_ts)]["trade_date"].drop_duplicates())
    base_signal_dates = base_signal_dates[:: max(1, rebalance_days)]
    if not base_signal_dates:
        raise ValueError("指定区间内没有可用信号日。")

    if walk_forward:
        state_dates = base_signal_dates
        wf_config = WalkForwardConfig(n_states=n_states, train_window_days=train_window_days, retrain_frequency=retrain_frequency)
        cache_params = _build_walk_forward_cache_params(
            ohlcv=ohlcv,
            features=features,
            trade_dates=trade_dates,
            config=wf_config,
            feature_version=feature_version,
            start_ts=start_ts,
            end_ts=end_ts,
            rebalance_days=rebalance_days,
            state_date_mode="rebalance_signals_v2",
            universe_id=universe_id,
            scope_type="universe" if universe_id else "all",
            feature_scope_id=feature_scope_id,
            feature_scope_type=feature_scope_type,
            include_custom_baskets=include_custom_baskets,
        )
        features = _attach_feature_lineage_hash(features, str(cache_params["feature_lineage_hash"]), universe_id=universe_id)
        cache_key = _walk_forward_cache_key(cache_params)
        states = _read_walk_forward_cache(
            storage,
            cache_key,
            expected_lineage_hash=str(cache_params["lineage_hash"]),
            expected_feature_lineage_hash=str(cache_params["feature_lineage_hash"]),
            expected_feature_scope_id=feature_scope_id,
            expected_universe_id=universe_id or "all",
        )
        cache_hit = not states.empty
        if states.empty:
            states = walk_forward_hmm_state_frame(features, state_dates, wf_config, progress_callback=progress_callback)
            if not states.empty:
                states["lineage_hash"] = cache_params["lineage_hash"]
                states["feature_lineage_hash"] = cache_params["feature_lineage_hash"]
            _write_walk_forward_cache(storage, cache_key, states, cache_params, signal_count=len(state_dates))
        run_label = f"walk_forward:{cache_key}"
    else:
        if not allow_in_sample_demo:
            raise ValueError("训练样本内状态仅用于展示，不能用于策略回测。若要演示，请在 UI 中明确选择非因果演示模式。")
        run_id = run_id or storage.latest_run_for_current_scope(universe_id)
        if not run_id:
            raise ValueError("没有可用模型运行，请先训练 HMM，或启用 walk_forward=True。")
        run = storage.get_model_run(run_id)
        if run.empty:
            raise ValueError("指定模型 run 不存在。")
        run_row = run.iloc[0]
        feature_scope_id = str(run_row.get("feature_scope_id") or ("all" if pd.isna(run_row.get("universe_id")) else run_row.get("universe_id")))
        feature_version_for_run = str(run_row.get("feature_version") or feature_version)
        states = storage.read_df(
            """
            SELECT s.*, f.ret_20d, f.rs_20d, f.amount_z_20d, f.vol_20d, f.drawdown_20d, f.ma20_slope
            FROM sector_state_daily s
            LEFT JOIN sector_features f
              ON s.sector_id = f.sector_id
             AND s.trade_date = f.trade_date
             AND f.feature_version = ?
             AND f.feature_scope_id = ?
            WHERE s.run_id = ?
            ORDER BY s.trade_date, s.sector_id
            """,
            [feature_version_for_run, feature_scope_id, run_id],
        )
        states["trade_date"] = pd.to_datetime(states["trade_date"])
        states = states[(states["trade_date"] >= start_ts) & (states["trade_date"] <= end_ts)]
        if universe_id:
            allowed_ids = set(universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets))
            states = states[states["sector_id"].astype(str).isin(allowed_ids)]
        if "state_source" not in states.columns:
            states["state_source"] = "in_sample_display"
        run_label = f"in_sample_demo:{run_id}"
        cache_hit = False

    if states.empty:
        raise ValueError("walk-forward 训练样本不足或没有可用 HMM 状态。")
    if walk_forward and cache_params is not None:
        _validate_state_feature_merge(states, features, cache_params)
    state_features = states.merge(
        features[["sector_id", "trade_date", "ret_20d", "rs_20d", "amount_z_20d", "vol_20d", "drawdown_20d", "ma20_slope"]],
        on=["sector_id", "trade_date"],
        how="left",
        suffixes=("", "_feature"),
    )
    available_state_dates = set(pd.to_datetime(state_features["trade_date"]).drop_duplicates())
    signal_dates = [pd.Timestamp(d) for d in base_signal_dates if pd.Timestamp(d) in available_state_dates]
    if not signal_dates:
        raise ValueError("可用 HMM 状态没有覆盖任何调仓信号日。")

    def choose_model(signal_date: pd.Timestamp) -> Weights:
        day = state_features[state_features["trade_date"] == signal_date]
        ranked = rank_sectors(day)
        candidates = ranked[ranked["prob_trend_up"] >= threshold].head(top_n)
        return _equal_weights(candidates["sector_id"].astype(str).tolist())

    def choose_rs(signal_date: pd.Timestamp) -> Weights:
        day = features[features["trade_date"] == signal_date].dropna(subset=["rs_20d"])
        candidates = day.sort_values("rs_20d", ascending=False).head(top_n)
        return _equal_weights(candidates["sector_id"].astype(str).tolist())

    def choose_equal(signal_date: pd.Timestamp) -> Weights:
        available = close_prices.loc[signal_date].dropna().index.astype(str).tolist() if signal_date in close_prices.index else []
        return _equal_weights(available)

    strategies = {
        "model": choose_model,
        "baseline_1_rs20_top_n": choose_rs,
        "baseline_2_equal_weight": choose_equal,
    }
    curves: list[pd.DataFrame] = []
    all_events: list[pd.DataFrame] = []
    comparison_rows: list[dict[str, object]] = []
    for strategy, chooser in strategies.items():
        events = _make_events(signal_dates, trade_dates, chooser, strategy)
        curve, trade_info = simulate_portfolio_returns(
            open_prices=open_prices,
            close_prices=close_prices,
            target_events=events,
            execution_price=execution_price,
            transaction_cost=transaction_cost,
        )
        if not curve.empty:
            curve = curve[(curve["trade_date"] >= start_ts) & (curve["trade_date"] <= end_ts)].copy()
            curve["strategy"] = strategy
            curves.append(curve)
        if not events.empty:
            events = events.drop(columns=["weights"]).merge(trade_info.drop(columns=["weights"], errors="ignore"), on="exec_date", how="left")
            all_events.append(events)
        metrics = _strategy_metrics(curve)
        comparison_rows.append({"strategy": strategy, **metrics})

    curve_long = pd.concat(curves, ignore_index=True) if curves else pd.DataFrame()
    if curve_long.empty:
        raise ValueError("行情覆盖不足，无法计算净值。")
    curve = curve_long.pivot(index="trade_date", columns="strategy", values=["nav_gross", "nav_net"]).reset_index()
    curve.columns = ["trade_date"] + [f"{strategy}_{kind}" for kind, strategy in curve.columns[1:]]
    trades_df = pd.concat(all_events, ignore_index=True) if all_events else pd.DataFrame()
    comparison = pd.DataFrame(comparison_rows)
    model_metrics = comparison[comparison["strategy"] == "model"].iloc[0].to_dict()
    return {
        "run_id": run_label,
        "metrics": {
            "annual_return": model_metrics["annual_return_net"],
            "max_drawdown": model_metrics["max_drawdown_net"],
            "sharpe": model_metrics["sharpe_net"],
            "calmar": model_metrics["calmar_net"],
            "win_rate": model_metrics["win_rate_net"],
            "turnover": model_metrics["turnover"],
        },
        "comparison": comparison,
        "curve": curve,
        "curve_long": curve_long,
        "trades": trades_df,
        "states": states,
        "execution_price": execution_price,
        "transaction_cost": transaction_cost,
        "state_source": "causal_backtest" if walk_forward else "in_sample_display",
        "cache_hit": cache_hit,
        "retrain_frequency": retrain_frequency,
    }
