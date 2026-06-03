from __future__ import annotations

import re
from collections.abc import Iterable

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.utils.lineage import hash_payload


DIGEST_DATE_COLUMNS = ("valid_from", "valid_to", "created_at", "updated_at", "trade_date", "fetched_at")


def _normalize_asof_date(as_of_date: object | None) -> pd.Timestamp | None:
    if as_of_date is None:
        return None
    parsed = pd.to_datetime(as_of_date, errors="coerce")
    return None if pd.isna(parsed) else parsed


def _frame_digest(frame: pd.DataFrame, columns: list[str], sort_columns: list[str], extra: dict[str, object]) -> str:
    available = [column for column in columns if column in frame.columns]
    rows = frame[available].copy() if available else pd.DataFrame()
    for column in DIGEST_DATE_COLUMNS:
        if column in rows.columns:
            rows[column] = pd.to_datetime(rows[column], errors="coerce").dt.strftime("%Y-%m-%d")
    for column in rows.columns:
        if column not in DIGEST_DATE_COLUMNS:
            rows[column] = rows[column].where(rows[column].notna(), None)
    sort_available = [column for column in sort_columns if column in rows.columns]
    if sort_available:
        rows = rows.sort_values(sort_available).reset_index(drop=True)
    payload = dict(extra)
    payload["columns"] = available
    payload["rows"] = rows.to_dict("records")
    payload["row_count"] = int(len(rows))
    return hash_payload(payload)


def _apply_asof_filter(frame: pd.DataFrame, as_of_date: object | None) -> pd.DataFrame:
    if frame.empty:
        return frame
    asof = _normalize_asof_date(as_of_date)
    if asof is None:
        return frame
    out = frame.copy()
    if "valid_from" in out.columns:
        valid_from = pd.to_datetime(out["valid_from"], errors="coerce")
        out = out[valid_from.isna() | valid_from.le(asof)]
    if "valid_to" in out.columns:
        valid_to = pd.to_datetime(out["valid_to"], errors="coerce")
        out = out[valid_to.isna() | valid_to.gt(asof)]
    return out


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


def compute_universe_membership_hash(
    storage: DuckDBStorage,
    universe_id: str | None,
    as_of_date: object | None = None,
) -> str:
    if not universe_id:
        return hash_payload(
            {
                "digest_type": "universe_membership",
                "universe_id": "all",
                "membership_policy": "all_current_snapshot",
                "as_of_date": _normalize_asof_date(as_of_date),
            }
        )
    items = _apply_asof_filter(storage.list_universe_items(universe_id), as_of_date)
    return _frame_digest(
        items,
        [
            "universe_id",
            "item_type",
            "item_id",
            "item_name",
            "weight",
            "note",
            "valid_from",
            "valid_to",
        ],
        ["item_type", "item_id"],
        {
            "digest_type": "universe_membership",
            "universe_id": universe_id,
            "membership_policy": "current_snapshot",
            "as_of_date": _normalize_asof_date(as_of_date),
            "reserved_scd_fields": ["valid_from", "valid_to"],
        },
    )


def compute_custom_basket_membership_hash(
    storage: DuckDBStorage,
    include_ids: Iterable[str] | None = None,
    as_of_date: object | None = None,
) -> str:
    basket_ids = None if include_ids is None else sorted(str(value) for value in include_ids)
    params: list[object] = []
    where = ""
    if basket_ids is not None:
        if not basket_ids:
            return hash_payload(
                {
                    "digest_type": "custom_basket_membership",
                    "basket_ids": [],
                    "membership_policy": "current_snapshot",
                    "as_of_date": _normalize_asof_date(as_of_date),
                    "reserved_scd_fields": ["valid_from", "valid_to"],
                    "row_count": 0,
                }
            )
        where = "WHERE b.basket_id IN (" + ",".join(["?"] * len(basket_ids)) + ")"
        params.extend(basket_ids)
    baskets = storage.read_df(
        f"""
        SELECT b.basket_id, b.basket_name, b.index_method,
               m.stock_code, m.stock_name, m.weight, m.note,
               m.valid_from, m.valid_to
        FROM custom_stock_basket b
        LEFT JOIN custom_stock_basket_members m USING(basket_id)
        {where}
        ORDER BY b.basket_id, m.stock_code
        """,
        params,
    )
    baskets = _apply_asof_filter(baskets, as_of_date)
    return _frame_digest(
        baskets,
        [
            "basket_id",
            "basket_name",
            "index_method",
            "stock_code",
            "stock_name",
            "weight",
            "note",
            "valid_from",
            "valid_to",
        ],
        ["basket_id", "stock_code"],
        {
            "digest_type": "custom_basket_membership",
            "basket_ids": basket_ids if basket_ids is not None else "all",
            "membership_policy": "current_snapshot",
            "as_of_date": _normalize_asof_date(as_of_date),
            "reserved_scd_fields": ["valid_from", "valid_to"],
        },
    )


def compute_sector_ohlcv_snapshot_hash(
    storage: DuckDBStorage,
    sector_ids: Iterable[str],
    start_date: object,
    end_date: object,
) -> str:
    ids = sorted(str(value) for value in sector_ids)
    start = pd.to_datetime(start_date).date()
    end = pd.to_datetime(end_date).date()
    frames: list[pd.DataFrame] = []
    board_ids = [sector_id for sector_id in ids if not sector_id.startswith("custom:")]
    custom_ids = [sector_id for sector_id in ids if sector_id.startswith("custom:")]
    if board_ids:
        placeholders = ",".join(["?"] * len(board_ids))
        frames.append(
            storage.read_df(
                f"""
                SELECT sector_id, trade_date, open, high, low, close, volume, amount,
                       pct_chg, turnover, source, fetched_at
                FROM sector_ohlcv
                WHERE sector_id IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                """,
                [*board_ids, start, end],
            )
        )
    if custom_ids:
        placeholders = ",".join(["?"] * len(custom_ids))
        frames.append(
            storage.read_df(
                f"""
                SELECT basket_id AS sector_id, trade_date, close, daily_ret, volume, amount,
                       member_count, created_at AS fetched_at
                FROM custom_basket_ohlcv
                WHERE basket_id IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                """,
                [*custom_ids, start, end],
            )
        )
    ohlcv = pd.concat([frame for frame in frames if not frame.empty], ignore_index=True) if frames else pd.DataFrame()
    return _frame_digest(
        ohlcv,
        [
            "sector_id",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "daily_ret",
            "volume",
            "amount",
            "pct_chg",
            "turnover",
            "member_count",
            "source",
            "fetched_at",
        ],
        ["sector_id", "trade_date"],
        {
            "digest_type": "sector_ohlcv_snapshot",
            "sector_ids": ids,
            "start_date": start,
            "end_date": end,
        },
    )


def compute_calendar_hash(trade_dates: Iterable[object]) -> str:
    dates = sorted(pd.to_datetime(pd.Series(list(trade_dates)), errors="coerce").dropna().dt.date.astype(str).unique().tolist())
    return hash_payload({"digest_type": "trade_calendar", "trade_dates": dates, "row_count": len(dates)})


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
