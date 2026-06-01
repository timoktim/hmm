from __future__ import annotations

import json

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import custom_basket_sector_meta, universe_sector_ids
from src.features.sector_features import feature_scope_for_universe


def _attach_custom_meta(df: pd.DataFrame, storage: DuckDBStorage) -> pd.DataFrame:
    if df.empty or "sector_id" not in df.columns:
        return df
    out = df.copy()
    custom_ids = out.loc[out["sector_id"].astype(str).str.startswith("custom:"), "sector_id"].astype(str).unique().tolist()
    if not custom_ids:
        return out
    meta = custom_basket_sector_meta(storage, custom_ids)
    if meta.empty:
        return out
    meta_map = meta.set_index("sector_id")
    for sector_id, row in meta_map.iterrows():
        mask = out["sector_id"].astype(str) == str(sector_id)
        out.loc[mask, "sector_type"] = "custom"
        out.loc[mask, "sector_name"] = row["sector_name"]
    return out


def _normalize_cache_universe(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    return None if text in {"", "all", "None", "nan", "<NA>"} else text


def latest_sector_states(
    storage: DuckDBStorage | None = None,
    run_id: str | None = None,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
) -> pd.DataFrame:
    """Return latest in-sample HMM states for display only.

    These states come from ``sector_state_daily`` and may be fitted on the
    whole training interval. They are useful for model explanation, but should
    not be used as the default current signal or backtest input.
    """
    storage = storage or DuckDBStorage()
    run_id = run_id or storage.latest_run_for_current_scope(universe_id)
    if not run_id:
        return pd.DataFrame()
    run = storage.get_model_run(run_id)
    if run.empty:
        return pd.DataFrame()
    run_row = run.iloc[0]
    feature_scope_id = str(run_row.get("feature_scope_id") or ("all" if pd.isna(run_row.get("universe_id")) else run_row.get("universe_id")))
    feature_version = str(run_row.get("feature_version") or "")
    df = storage.read_df(
        """
        WITH latest AS (
          SELECT sector_id, max(trade_date) AS trade_date
          FROM sector_state_daily
          WHERE run_id = ?
          GROUP BY sector_id
        )
        SELECT s.*, m.sector_type, m.sector_name,
               f.ret_20d, f.rs_20d, f.amount_z_20d, f.vol_20d, f.drawdown_20d, f.ma20_slope,
               f.feature_scope_id, f.feature_scope_type
        FROM sector_state_daily s
        JOIN latest l USING (sector_id, trade_date)
        LEFT JOIN sector_meta m USING (sector_id)
        LEFT JOIN sector_features f
          ON s.sector_id = f.sector_id
         AND s.trade_date = f.trade_date
         AND f.feature_version = ?
         AND f.feature_scope_id = ?
        WHERE s.run_id = ?
        ORDER BY s.prob_trend_up DESC
        """,
        [run_id, feature_version, feature_scope_id, run_id],
    )
    if universe_id:
        allowed_ids = set(universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets))
        df = df[df["sector_id"].astype(str).isin(allowed_ids)]
    return _attach_custom_meta(df, storage)


latest_in_sample_sector_states = latest_sector_states


def latest_causal_sector_states(
    storage: DuckDBStorage | None = None,
    cache_key: str | None = None,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
    require_cache_match: bool = True,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    if not cache_key:
        return pd.DataFrame()
    cache_run = storage.read_df("SELECT * FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key])
    if cache_run.empty:
        return pd.DataFrame()
    cache_row = cache_run.iloc[0]
    if require_cache_match:
        cache_universe = _normalize_cache_universe(cache_row.get("universe_id"))
        if cache_universe != universe_id:
            return pd.DataFrame()
    feature_version = str(cache_row.get("feature_version") or "")
    feature_scope_id = cache_row.get("feature_scope_id")
    if pd.isna(feature_scope_id) or str(feature_scope_id).strip() == "":
        cache_include_custom = cache_row.get("include_custom_baskets")
        include_custom = include_custom_baskets if pd.isna(cache_include_custom) else bool(cache_include_custom)
        feature_scope_id, _ = feature_scope_for_universe(storage, universe_id, include_custom)
    df = storage.read_df(
        """
        WITH latest AS (
          SELECT sector_id, max(trade_date) AS trade_date
          FROM walk_forward_state_cache
          WHERE cache_key = ?
          GROUP BY sector_id
        )
        SELECT s.*, m.sector_type, m.sector_name,
               f.ret_20d, f.rs_20d, f.amount_z_20d, f.vol_20d, f.drawdown_20d, f.ma20_slope,
               f.feature_scope_id, f.feature_scope_type
        FROM walk_forward_state_cache s
        JOIN latest l USING (sector_id, trade_date)
        LEFT JOIN sector_meta m USING (sector_id)
        LEFT JOIN sector_features f
          ON s.sector_id = f.sector_id
         AND s.trade_date = f.trade_date
         AND f.feature_version = ?
         AND f.feature_scope_id = ?
        WHERE s.cache_key = ?
          AND (s.max_observation_date_used IS NULL OR s.max_observation_date_used <= s.trade_date)
        ORDER BY s.prob_trend_up DESC
        """,
        [cache_key, feature_version, str(feature_scope_id), cache_key],
    )
    if universe_id:
        allowed_ids = set(universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets))
        df = df[df["sector_id"].astype(str).isin(allowed_ids)]
    return _attach_custom_meta(df, storage)


def recent_causal_switches(
    storage: DuckDBStorage | None = None,
    cache_key: str | None = None,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
    limit: int = 30,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    if not cache_key:
        return pd.DataFrame()
    cache_run = storage.read_df("SELECT universe_id FROM walk_forward_cache_runs WHERE cache_key = ?", [cache_key])
    if cache_run.empty:
        return pd.DataFrame()
    cache_universe = _normalize_cache_universe(cache_run.iloc[0].get("universe_id"))
    if cache_universe != universe_id:
        return pd.DataFrame()
    df = storage.read_df(
        """
        WITH ordered AS (
          SELECT s.*,
                 lag(state_label) OVER (PARTITION BY sector_id ORDER BY trade_date) AS prev_label,
                 m.sector_name,
                 m.sector_type
          FROM walk_forward_state_cache s
          LEFT JOIN sector_meta m USING(sector_id)
          WHERE cache_key = ?
            AND (max_observation_date_used IS NULL OR max_observation_date_used <= trade_date)
        )
        SELECT sector_id, sector_type, sector_name, trade_date, prev_label, state_label,
               COALESCE(state_source, 'causal_backtest') AS state_source
        FROM ordered
        WHERE prev_label IS NOT NULL AND prev_label <> state_label
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        [cache_key, int(limit)],
    )
    if universe_id and not df.empty:
        allowed_ids = set(universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets))
        df = df[df["sector_id"].astype(str).isin(allowed_ids)]
    return _attach_custom_meta(df, storage)


def sector_state_history(sector_id: str, storage: DuckDBStorage | None = None, run_id: str | None = None, days: int | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    run_id = run_id or storage.latest_run_id()
    if not run_id:
        return pd.DataFrame()
    run = storage.get_model_run(run_id)
    if run.empty:
        return pd.DataFrame()
    run_row = run.iloc[0]
    feature_scope_id = str(run_row.get("feature_scope_id") or ("all" if pd.isna(run_row.get("universe_id")) else run_row.get("universe_id")))
    feature_version = str(run_row.get("feature_version") or "")
    limit_sql = f"LIMIT {int(days)}" if days else ""
    df = storage.read_df(
        f"""
        SELECT s.*, f.ret_20d, f.rs_20d, f.vol_20d, f.drawdown_20d, f.ma20_slope, f.feature_scope_id, f.feature_scope_type
        FROM sector_state_daily s
        LEFT JOIN sector_features f
          ON s.sector_id = f.sector_id
         AND s.trade_date = f.trade_date
         AND f.feature_version = ?
         AND f.feature_scope_id = ?
        WHERE s.run_id = ? AND s.sector_id = ?
        ORDER BY s.trade_date DESC
        {limit_sql}
        """,
        [feature_version, feature_scope_id, run_id, sector_id],
    )
    return df.sort_values("trade_date")


def transition_matrix(storage: DuckDBStorage | None = None, run_id: str | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    run_id = run_id or storage.latest_run_id()
    if not run_id:
        return pd.DataFrame()
    df = storage.read_df("SELECT metrics_json FROM model_runs WHERE run_id = ?", [run_id])
    if df.empty:
        return pd.DataFrame()
    metrics = json.loads(df.loc[0, "metrics_json"])
    matrix = metrics.get("transition_matrix", [])
    return pd.DataFrame(matrix)
