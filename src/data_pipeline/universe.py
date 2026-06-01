from __future__ import annotations

import re

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage


def default_universe_id(storage: DuckDBStorage) -> str | None:
    df = storage.read_df("SELECT universe_id FROM user_universe WHERE is_default = TRUE ORDER BY updated_at DESC LIMIT 1")
    return None if df.empty else str(df.loc[0, "universe_id"])


def universe_sector_ids(storage: DuckDBStorage, universe_id: str | None, include_custom_baskets: bool = True) -> list[str]:
    if not universe_id:
        return []
    items = storage.list_universe_items(universe_id)
    if items.empty:
        return []
    allowed = ["industry", "concept"]
    if include_custom_baskets:
        allowed.append("custom_stock_basket")
    out: list[str] = []
    for row in items[items["item_type"].isin(allowed)].itertuples(index=False):
        out.append(str(row.item_id))
    return out


def universe_items_for_update(storage: DuckDBStorage, universe_id: str) -> pd.DataFrame:
    return storage.list_universe_items(universe_id)


def custom_basket_sector_meta(storage: DuckDBStorage, basket_ids: list[str] | None = None) -> pd.DataFrame:
    if basket_ids:
        placeholders = ",".join(["?"] * len(basket_ids))
        df = storage.read_df(f"SELECT basket_id, basket_name FROM custom_stock_basket WHERE basket_id IN ({placeholders})", basket_ids)
    else:
        df = storage.read_df("SELECT basket_id, basket_name FROM custom_stock_basket")
    if df.empty:
        return pd.DataFrame(columns=["sector_id", "sector_type", "sector_name"])
    return pd.DataFrame({"sector_id": df["basket_id"], "sector_type": "custom", "sector_name": df["basket_name"]})


def load_sector_like_ohlcv(
    storage: DuckDBStorage,
    universe_id: str | None = None,
    include_custom_baskets: bool = True,
) -> pd.DataFrame:
    sector_ids = universe_sector_ids(storage, universe_id, include_custom_baskets=include_custom_baskets) if universe_id else []
    custom_ids = [sid for sid in sector_ids if sid.startswith("custom:")]
    board_ids = [sid for sid in sector_ids if not sid.startswith("custom:")]
    if universe_id and not sector_ids:
        return pd.DataFrame()

    frames: list[pd.DataFrame] = []
    if board_ids:
        placeholders = ",".join(["?"] * len(board_ids))
        frames.append(
            storage.read_df(
                f"""
                SELECT sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover, source, fetched_at
                FROM sector_ohlcv
                WHERE sector_id IN ({placeholders})
                ORDER BY sector_id, trade_date
                """,
                board_ids,
            )
        )
    elif not universe_id:
        frames.append(
            storage.read_df(
                """
                SELECT sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover, source, fetched_at
                FROM sector_ohlcv
                ORDER BY sector_id, trade_date
                """
            )
        )
    if include_custom_baskets and (custom_ids or not universe_id):
        if custom_ids:
            placeholders = ",".join(["?"] * len(custom_ids))
            custom = storage.read_df(
                f"""
                SELECT basket_id AS sector_id, trade_date, close, daily_ret, volume, amount, created_at AS fetched_at
                FROM custom_basket_ohlcv
                WHERE basket_id IN ({placeholders})
                ORDER BY basket_id, trade_date
                """,
                custom_ids,
            )
        else:
            custom = storage.read_df(
                """
                SELECT basket_id AS sector_id, trade_date, close, daily_ret, volume, amount, created_at AS fetched_at
                FROM custom_basket_ohlcv
                ORDER BY basket_id, trade_date
                """
        )
        if not custom.empty:
            custom["open"] = custom.groupby("sector_id")["close"].shift(1)
            first_idx = custom.groupby("sector_id").head(1).index
            custom.loc[first_idx, "open"] = custom.loc[first_idx, "close"]
            custom["high"] = custom[["open", "close"]].max(axis=1)
            custom["low"] = custom[["open", "close"]].min(axis=1)
            custom["pct_chg"] = custom["daily_ret"] * 100
            custom["turnover"] = pd.NA
            custom["source"] = "custom_basket"
            frames.append(custom[["sector_id", "trade_date", "open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover", "source", "fetched_at"]])
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def parse_stock_lines(text: str) -> list[dict[str, object]]:
    members: list[dict[str, object]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^(\d{6})(?:\.(?:SZ|SH|BJ))?\s*(.*)$", line, flags=re.IGNORECASE)
        if not match:
            continue
        code = match.group(1)
        if code in seen:
            continue
        seen.add(code)
        rest = match.group(2).strip()
        weight = 1.0
        name = rest
        parts = rest.split(maxsplit=1)
        if parts:
            try:
                weight = float(parts[0])
                name = parts[1] if len(parts) > 1 else ""
            except ValueError:
                name = rest
        members.append({"stock_code": code, "stock_name": name, "weight": weight, "note": ""})
    return members
