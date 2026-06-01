from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.utils.dates import normalize_yyyymmdd


def build_custom_basket_ohlcv(
    basket_id: str,
    start_date: str,
    end_date: str,
    storage: DuckDBStorage | None = None,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    members = storage.list_basket_members(basket_id)
    if members.empty:
        return pd.DataFrame()
    basket = storage.read_df("SELECT index_method FROM custom_stock_basket WHERE basket_id = ?", [basket_id])
    index_method = str(basket.loc[0, "index_method"]) if not basket.empty else "equal_weight"
    codes = members["stock_code"].astype(str).tolist()
    placeholders = ",".join(["?"] * len(codes))
    stocks = storage.read_df(
        f"""
        SELECT stock_code, trade_date, close, volume, amount
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
          AND trade_date BETWEEN ? AND ?
        ORDER BY stock_code, trade_date
        """,
        [*codes, pd.to_datetime(normalize_yyyymmdd(start_date)).date(), pd.to_datetime(normalize_yyyymmdd(end_date)).date()],
    )
    if stocks.empty:
        return pd.DataFrame()
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"])
    stocks = stocks.sort_values(["stock_code", "trade_date"])
    stocks["daily_ret"] = stocks.groupby("stock_code")["close"].pct_change()
    member_weights = members[["stock_code", "weight"]].copy()
    member_weights["stock_code"] = member_weights["stock_code"].astype(str).str.zfill(6)
    member_weights["weight"] = pd.to_numeric(member_weights["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    stocks = stocks.merge(member_weights, on="stock_code", how="left")
    stocks["weight"] = stocks["weight"].fillna(0.0)

    def daily_ret(g: pd.DataFrame) -> float:
        valid = g.dropna(subset=["daily_ret"])
        if valid.empty:
            return float("nan")
        if index_method == "custom_weight":
            weights = valid["weight"].astype(float)
            total = float(weights.sum())
            if total <= 0:
                return float(valid["daily_ret"].mean())
            return float((valid["daily_ret"].astype(float) * weights / total).sum())
        return float(valid["daily_ret"].mean())

    daily = stocks.groupby("trade_date").agg(
        daily_ret=("daily_ret", lambda s: daily_ret(stocks.loc[s.index])),
        volume=("volume", "sum"),
        amount=("amount", "sum"),
        member_count=("stock_code", "nunique"),
    )
    daily = daily[daily["member_count"] > 0].copy()
    if daily.empty:
        return pd.DataFrame()
    daily["daily_ret"] = daily["daily_ret"].astype(float)
    daily.iloc[0, daily.columns.get_loc("daily_ret")] = 0.0
    daily = daily[daily["daily_ret"].notna()].copy()
    if daily.empty:
        return pd.DataFrame()
    daily["close"] = 1000.0 * (1 + daily["daily_ret"].fillna(0)).cumprod()
    out = daily.reset_index()
    out["basket_id"] = basket_id
    out["created_at"] = pd.Timestamp.now()
    out["trade_date"] = out["trade_date"].dt.date
    out = out[["basket_id", "trade_date", "close", "daily_ret", "volume", "amount", "member_count", "created_at"]]
    storage.upsert_custom_basket_ohlcv(out)
    return out


def custom_basket_quality_frame(basket_id: str, storage: DuckDBStorage | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    members = storage.list_basket_members(basket_id)
    total = len(members)
    if total == 0:
        return pd.DataFrame()
    df = storage.read_df("SELECT *, member_count::DOUBLE / ? AS coverage FROM custom_basket_ohlcv WHERE basket_id = ? ORDER BY trade_date", [total, basket_id])
    if not df.empty:
        df["low_quality"] = df["coverage"] < 0.5
    return df
