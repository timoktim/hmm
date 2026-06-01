from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import custom_basket_sector_meta, universe_sector_ids
from src.scoring.sector_ranker import rank_sectors


STATE_ORDER = ["TrendUp", "Neutral", "RiskOff"]


def _run_feature_scope(storage: DuckDBStorage, run_id: str | None) -> tuple[str, str]:
    if not run_id:
        return "", "all"
    run = storage.get_model_run(run_id)
    if run.empty:
        return "", "all"
    row = run.iloc[0]
    feature_version = str(row.get("feature_version") or "")
    feature_scope_id = str(row.get("feature_scope_id") or ("all" if pd.isna(row.get("universe_id")) else row.get("universe_id")))
    return feature_version, feature_scope_id


def _attach_meta(df: pd.DataFrame, storage: DuckDBStorage) -> pd.DataFrame:
    if df.empty or "sector_id" not in df.columns:
        return df
    meta = storage.read_df("SELECT sector_id, sector_type, sector_name FROM sector_meta")
    custom_ids = df.loc[df["sector_id"].astype(str).str.startswith("custom:"), "sector_id"].astype(str).drop_duplicates().tolist()
    custom_meta = custom_basket_sector_meta(storage, custom_ids)
    if not custom_meta.empty:
        meta = pd.concat([meta, custom_meta], ignore_index=True)
    if meta.empty:
        return df
    return df.merge(meta.drop_duplicates("sector_id"), on="sector_id", how="left", suffixes=("", "_meta"))


def _attach_latest_features(df: pd.DataFrame, storage: DuckDBStorage, run_id: str | None) -> pd.DataFrame:
    if df.empty:
        return df
    feature_version, feature_scope_id = _run_feature_scope(storage, run_id)
    if not feature_version:
        return df
    features = storage.read_df(
        """
        WITH latest AS (
          SELECT sector_id, max(trade_date) AS trade_date
          FROM sector_features
          WHERE feature_version = ? AND feature_scope_id = ?
          GROUP BY sector_id
        )
        SELECT f.sector_id, f.ret_20d, f.rs_20d, f.drawdown_20d, f.amount_z_20d,
               f.vol_20d, f.ma20_slope, f.feature_scope_id, f.feature_scope_type
        FROM sector_features f
        JOIN latest l USING(sector_id, trade_date)
        WHERE f.feature_version = ? AND f.feature_scope_id = ?
        """,
        [feature_version, feature_scope_id, feature_version, feature_scope_id],
    )
    if features.empty:
        return df
    return df.merge(features, on="sector_id", how="left")


def load_sector_states_for_analysis(
    storage: DuckDBStorage,
    run_id: str,
    universe_id: str | None = None,
    source: str = "in_sample_display",
    cache_key: str | None = None,
) -> pd.DataFrame:
    if source == "walk_forward":
        if cache_key is None:
            return pd.DataFrame()
        states = storage.read_df(
            """
            SELECT ? AS run_id, sector_id, trade_date, state_label,
                   prob_trend_up, prob_neutral, prob_risk_off, next_state_probs_json,
                   COALESCE(state_source, 'causal_backtest') AS state_source
            FROM walk_forward_state_cache
            WHERE cache_key = ?
            ORDER BY sector_id, trade_date
            """,
            [run_id, cache_key],
        )
    else:
        states = storage.read_df(
            """
            SELECT run_id, sector_id, trade_date, state_label,
                   prob_trend_up, prob_neutral, prob_risk_off, next_state_probs_json,
                   COALESCE(state_source, 'in_sample_display') AS state_source
            FROM sector_state_daily
            WHERE run_id = ?
            ORDER BY sector_id, trade_date
            """,
            [run_id],
        )
    if states.empty:
        return states
    if universe_id:
        allowed = set(universe_sector_ids(storage, universe_id, include_custom_baskets=True))
        states = states[states["sector_id"].astype(str).isin(allowed)]
    return _attach_meta(states, storage)


def build_state_segments(states: pd.DataFrame, ohlcv: pd.DataFrame | None = None) -> pd.DataFrame:
    if states is None or states.empty:
        return pd.DataFrame()
    work = states.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    work = work.sort_values(["sector_id", "trade_date"]).reset_index(drop=True)
    work["segment_id"] = work.groupby("sector_id")["state_label"].transform(lambda s: (s.astype(str) != s.astype(str).shift()).cumsum())
    agg = {
        "trade_date": ["min", "max", "count"],
        "prob_trend_up": "mean",
        "prob_neutral": "mean",
        "prob_risk_off": "mean",
    }
    if "run_id" in work.columns:
        agg["run_id"] = "first"
    if "sector_type" in work.columns:
        agg["sector_type"] = "first"
    if "sector_name" in work.columns:
        agg["sector_name"] = "first"
    segments = work.groupby(["sector_id", "segment_id", "state_label"], as_index=False).agg(agg)
    segments.columns = [
        "_".join(col).strip("_") if isinstance(col, tuple) else str(col)
        for col in segments.columns
    ]
    segments = segments.rename(
        columns={
            "trade_date_min": "start_date",
            "trade_date_max": "end_date",
            "trade_date_count": "trading_days",
            "prob_trend_up_mean": "avg_prob_trend_up",
            "prob_neutral_mean": "avg_prob_neutral",
            "prob_risk_off_mean": "avg_prob_risk_off",
            "run_id_first": "run_id",
            "sector_type_first": "sector_type",
            "sector_name_first": "sector_name",
        }
    )
    segments["calendar_days"] = (segments["end_date"] - segments["start_date"]).dt.days + 1
    segments = segments.sort_values(["sector_id", "segment_id"]).reset_index(drop=True)
    segments["prev_state_label"] = segments.groupby("sector_id")["state_label"].shift(1)
    segments["next_state_label"] = segments.groupby("sector_id")["state_label"].shift(-1)
    segments["previous_state_days"] = segments.groupby("sector_id")["trading_days"].shift(1)
    segments["segment_return"] = pd.NA
    segments["max_drawdown"] = pd.NA
    if ohlcv is not None and not ohlcv.empty:
        prices = ohlcv.copy()
        prices["trade_date"] = pd.to_datetime(prices["trade_date"])
        prices["close"] = pd.to_numeric(prices["close"], errors="coerce")
        for idx, row in segments.iterrows():
            g = prices[
                prices["sector_id"].astype(str).eq(str(row["sector_id"]))
                & (prices["trade_date"] >= row["start_date"])
                & (prices["trade_date"] <= row["end_date"])
            ].sort_values("trade_date")
            close = g["close"].dropna()
            if close.empty:
                continue
            segments.loc[idx, "segment_return"] = float(close.iloc[-1] / close.iloc[0] - 1)
            segments.loc[idx, "max_drawdown"] = float((close / close.cummax() - 1).min())
    return segments


def _latest_rows(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return states
    work = states.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    return work.sort_values(["sector_id", "trade_date"]).groupby("sector_id", as_index=False).tail(1)


def screen_state_transitions(segments: pd.DataFrame, latest_states: pd.DataFrame, filters: dict[str, object]) -> pd.DataFrame:
    if segments is None or segments.empty:
        return pd.DataFrame()
    out = segments.copy()
    only_current = bool(filters.get("only_current_state", True))
    if only_current:
        latest_segment = out.groupby("sector_id")["segment_id"].transform("max")
        out = out[out["segment_id"].eq(latest_segment)]
    from_state = filters.get("from_state")
    to_state = filters.get("to_state")
    if from_state and from_state != "任意":
        out = out[out["prev_state_label"].astype(str).eq(str(from_state))]
    if to_state and to_state != "任意":
        out = out[out["state_label"].astype(str).eq(str(to_state))]
    max_days = filters.get("current_segment_max_days")
    if max_days is not None:
        out = out[pd.to_numeric(out["trading_days"], errors="coerce") <= int(max_days)]
    min_prev_days = filters.get("min_previous_segment_days")
    if min_prev_days is not None:
        out = out[pd.to_numeric(out["previous_state_days"], errors="coerce").fillna(0) >= int(min_prev_days)]
    storage = filters.get("storage")
    run_id = str(filters.get("run_id") or "") or None
    latest = _latest_rows(latest_states)
    if storage is not None and isinstance(storage, DuckDBStorage):
        latest = _attach_latest_features(_attach_meta(latest, storage), storage, run_id)
    enrich_cols = [
        "sector_id",
        "sector_type",
        "sector_name",
        "prob_trend_up",
        "prob_neutral",
        "prob_risk_off",
        "ret_20d",
        "rs_20d",
        "drawdown_20d",
        "amount_z_20d",
        "vol_20d",
        "ma20_slope",
        "state_source",
    ]
    latest = latest[[c for c in enrich_cols if c in latest.columns]].drop_duplicates("sector_id")
    out = out.merge(latest, on="sector_id", how="left", suffixes=("", "_latest"))
    for col in ["prob_trend_up", "prob_neutral", "prob_risk_off"]:
        avg_col = "avg_" + col
        if col not in out.columns and avg_col in out.columns:
            out[col] = out[avg_col]
        elif col in out.columns and avg_col in out.columns:
            out[col] = out[col].fillna(out[avg_col])
    prob_min = filters.get("prob_trend_up_min")
    if prob_min is not None:
        out = out[pd.to_numeric(out["prob_trend_up"], errors="coerce").fillna(0) >= float(prob_min)]
    risk_max = filters.get("prob_risk_off_max")
    if risk_max is not None:
        out = out[pd.to_numeric(out["prob_risk_off"], errors="coerce").fillna(1) <= float(risk_max)]
    sector_type = filters.get("sector_type")
    if sector_type and sector_type != "all":
        if sector_type == "custom":
            out = out[out["sector_id"].astype(str).str.startswith("custom:")]
        elif "sector_type" in out.columns:
            out = out[out["sector_type"].astype(str).eq(str(sector_type))]
    if filters.get("universe_id") and storage is not None and isinstance(storage, DuckDBStorage):
        allowed = set(universe_sector_ids(storage, str(filters["universe_id"]), include_custom_baskets=True))
        out = out[out["sector_id"].astype(str).isin(allowed)]
    if not out.empty:
        try:
            out = rank_sectors(out)
        except Exception:
            out["sector_score"] = pd.NA
    out = out.rename(
        columns={
            "start_date": "switch_date",
            "prev_state_label": "from_state",
            "state_label": "to_state",
            "trading_days": "current_state_days",
        }
    )
    if "previous_state_days" in out.columns:
        out["previous_state_days"] = pd.to_numeric(out["previous_state_days"], errors="coerce").fillna(0).astype(int)
    columns = [
        "sector_id",
        "sector_type",
        "sector_name",
        "switch_date",
        "from_state",
        "to_state",
        "current_state_days",
        "previous_state_days",
        "prob_trend_up",
        "prob_neutral",
        "prob_risk_off",
        "ret_20d",
        "rs_20d",
        "drawdown_20d",
        "amount_z_20d",
        "sector_score",
        "state_source",
    ]
    return out[[c for c in columns if c in out.columns]].sort_values(["switch_date", "prob_trend_up"], ascending=[False, False])


def build_stock_overlay_normalized_series(
    sector_ohlcv: pd.DataFrame,
    stock_ohlcv: pd.DataFrame,
    stock_names: dict[str, str] | None = None,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    stock_names = stock_names or {}

    def append_series(df: pd.DataFrame, label: str, series_type: str, stock_code: str | None = None) -> None:
        if df.empty:
            return
        g = df.copy()
        g["trade_date"] = pd.to_datetime(g["trade_date"])
        if start_date is not None:
            g = g[g["trade_date"] >= pd.to_datetime(start_date)]
        if end_date is not None:
            g = g[g["trade_date"] <= pd.to_datetime(end_date)]
        g = g.sort_values("trade_date")
        close = pd.to_numeric(g["close"], errors="coerce").dropna()
        if close.empty:
            return
        g = g.loc[close.index].copy()
        g["normalized_close"] = close / close.iloc[0] * 100
        g["label"] = label
        g["series_type"] = series_type
        g["stock_code"] = stock_code or ""
        frames.append(g[["trade_date", "label", "series_type", "stock_code", "normalized_close"]])

    append_series(sector_ohlcv, "板块指数", "sector")
    if stock_ohlcv is not None and not stock_ohlcv.empty:
        for code, group in stock_ohlcv.groupby("stock_code"):
            code_str = str(code).zfill(6)
            name = stock_names.get(code_str, "")
            label = f"{code_str} {name}".strip()
            append_series(group, label, "stock", code_str)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
