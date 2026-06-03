from __future__ import annotations

import re

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.validators import validate_ohlcv
from src.utils.dates import normalize_yyyymmdd


CUSTOM_BASKET_SOURCE_REQUIRED_COLUMNS = {"stock_code", "trade_date", "close"}
CUSTOM_BASKET_OUTPUT_REQUIRED_COLUMNS = {"basket_id", "trade_date", "close"}
INDEX_METHOD_EQUAL_WEIGHT = "equal_weight"
INDEX_METHOD_CUSTOM_WEIGHT = "custom_weight"
POLICY_DYNAMIC_AVAILABLE = "dynamic_available_members"
POLICY_FIXED_ZERO_RETURN = "fixed_weight_zero_return"
VALID_MEMBERSHIP_POLICIES = {POLICY_DYNAMIC_AVAILABLE, POLICY_FIXED_ZERO_RETURN}
DEFAULT_MEMBERSHIP_POLICY = POLICY_FIXED_ZERO_RETURN
LOW_COVERAGE_THRESHOLD = 0.5


def normalize_stock_code(value: object) -> str:
    text = str(value).strip().upper()
    match = re.search(r"(\d{1,6})", text)
    if match:
        return match.group(1).zfill(6)
    return text.zfill(6)


def _stock_code_lookup_values(codes: list[str]) -> list[str]:
    variants: set[str] = set()
    for code in codes:
        normalized = normalize_stock_code(code)
        stripped = normalized.lstrip("0") or "0"
        variants.update(
            {
                normalized,
                stripped,
                f"{normalized}.SZ",
                f"{normalized}.SH",
                f"{normalized}.BJ",
                f"{stripped}.SZ",
                f"{stripped}.SH",
                f"{stripped}.BJ",
            }
        )
    return sorted(variants)


def _resolve_membership_policy(value: object | None) -> str:
    policy = str(value or DEFAULT_MEMBERSHIP_POLICY).strip()
    if policy in {"", "nan", "None"}:
        policy = DEFAULT_MEMBERSHIP_POLICY
    if policy not in VALID_MEMBERSHIP_POLICIES:
        raise ValueError(f"unsupported custom basket membership_policy={policy!r}")
    return policy


def _resolve_index_method(value: object | None) -> str:
    method = str(value or INDEX_METHOD_EQUAL_WEIGHT).strip()
    if method not in {INDEX_METHOD_EQUAL_WEIGHT, INDEX_METHOD_CUSTOM_WEIGHT}:
        return INDEX_METHOD_EQUAL_WEIGHT
    return method


def build_custom_basket_ohlcv(
    basket_id: str,
    start_date: str,
    end_date: str,
    storage: DuckDBStorage | None = None,
    *,
    membership_policy: str | None = None,
    strict: bool = False,
    low_coverage_threshold: float = LOW_COVERAGE_THRESHOLD,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    members = storage.list_basket_members(basket_id)
    if members.empty:
        return pd.DataFrame()
    basket = storage.read_df("SELECT index_method, membership_policy FROM custom_stock_basket WHERE basket_id = ?", [basket_id])
    index_method = _resolve_index_method(basket.loc[0, "index_method"] if not basket.empty else INDEX_METHOD_EQUAL_WEIGHT)
    resolved_policy = _resolve_membership_policy(
        membership_policy if membership_policy is not None else (basket.loc[0, "membership_policy"] if not basket.empty and "membership_policy" in basket else DEFAULT_MEMBERSHIP_POLICY)
    )

    member_weights = members[["stock_code", "weight"]].copy()
    member_weights["stock_code"] = member_weights["stock_code"].map(normalize_stock_code)
    member_weights = member_weights.drop_duplicates(subset=["stock_code"], keep="last")
    if member_weights.empty:
        return pd.DataFrame()
    member_weights["weight"] = pd.to_numeric(member_weights["weight"], errors="coerce").fillna(0.0).clip(lower=0.0)
    if index_method == INDEX_METHOD_EQUAL_WEIGHT:
        member_weights["weight"] = 1.0
    total_members = int(len(member_weights))
    total_weight = float(member_weights["weight"].sum())
    if total_weight <= 0:
        member_weights["weight"] = 1.0
        total_weight = float(total_members)

    codes = member_weights["stock_code"].astype(str).tolist()
    lookup_values = _stock_code_lookup_values(codes)
    placeholders = ",".join(["?"] * len(lookup_values))
    stocks = storage.read_df(
        f"""
        SELECT stock_code, trade_date, close, volume, amount
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
          AND trade_date BETWEEN ? AND ?
        ORDER BY stock_code, trade_date
        """,
        [*lookup_values, pd.to_datetime(normalize_yyyymmdd(start_date)).date(), pd.to_datetime(normalize_yyyymmdd(end_date)).date()],
    )
    if stocks.empty:
        return pd.DataFrame()
    validate_ohlcv(
        stocks,
        f"custom basket source {basket_id}",
        entity_key="stock_code",
        required_columns=CUSTOM_BASKET_SOURCE_REQUIRED_COLUMNS,
    )
    stocks["stock_code"] = stocks["stock_code"].map(normalize_stock_code)
    stocks = stocks[stocks["stock_code"].isin(codes)].copy()
    if stocks.empty:
        return pd.DataFrame()
    stocks["trade_date"] = pd.to_datetime(stocks["trade_date"])
    stocks = stocks.sort_values(["stock_code", "trade_date"]).drop_duplicates(["stock_code", "trade_date"], keep="last")
    stocks["daily_ret"] = stocks.groupby("stock_code")["close"].pct_change()

    def daily_ret(g: pd.DataFrame) -> float:
        merged = member_weights.merge(g[["stock_code", "daily_ret"]], on="stock_code", how="left")
        if resolved_policy == POLICY_FIXED_ZERO_RETURN:
            returns = merged["daily_ret"].fillna(0.0).astype(float)
            return float((returns * merged["weight"].astype(float) / total_weight).sum())

        valid = merged.dropna(subset=["daily_ret"])
        if valid.empty:
            return float("nan")
        if index_method == INDEX_METHOD_CUSTOM_WEIGHT:
            weights = valid["weight"].astype(float)
            total = float(weights.sum())
            if total <= 0:
                return float(valid["daily_ret"].mean())
            return float((valid["daily_ret"].astype(float) * weights / total).sum())
        return float(valid["daily_ret"].mean())

    rows: list[dict[str, object]] = []
    for trade_date, group in stocks.groupby("trade_date", sort=True):
        member_count = int(group["stock_code"].nunique())
        coverage_ratio = member_count / total_members if total_members else 0.0
        low_coverage_warning = coverage_ratio < float(low_coverage_threshold)
        rows.append(
            {
                "trade_date": trade_date,
                "daily_ret": daily_ret(group),
                "volume": float(pd.to_numeric(group["volume"], errors="coerce").fillna(0.0).sum()),
                "amount": float(pd.to_numeric(group["amount"], errors="coerce").fillna(0.0).sum()),
                "member_count": member_count,
                "coverage_ratio": coverage_ratio,
                "missing_member_count": max(total_members - member_count, 0),
                "low_coverage_warning": bool(low_coverage_warning),
                "membership_policy": resolved_policy,
                "index_method_effective": f"{index_method}:{resolved_policy}",
            }
        )

    daily = pd.DataFrame(rows)
    daily = daily[daily["member_count"] > 0].copy()
    if daily.empty:
        return pd.DataFrame()
    if strict and bool(daily["low_coverage_warning"].any()):
        low_dates = daily.loc[daily["low_coverage_warning"], "trade_date"].dt.date.astype(str).tolist()
        raise ValueError(
            f"custom basket {basket_id} coverage below threshold {low_coverage_threshold:.0%}; "
            f"blocked by strict=True for dates: {', '.join(low_dates[:5])}"
        )
    daily["daily_ret"] = daily["daily_ret"].astype(float)
    daily.iloc[0, daily.columns.get_loc("daily_ret")] = 0.0
    daily = daily[daily["daily_ret"].notna()].copy()
    if daily.empty:
        return pd.DataFrame()
    daily["close"] = 1000.0 * (1 + daily["daily_ret"].fillna(0)).cumprod()
    out = daily.reset_index(drop=True)
    out["basket_id"] = basket_id
    out["created_at"] = pd.Timestamp.now()
    out["trade_date"] = out["trade_date"].dt.date
    out = out[
        [
            "basket_id",
            "trade_date",
            "close",
            "daily_ret",
            "volume",
            "amount",
            "member_count",
            "coverage_ratio",
            "missing_member_count",
            "low_coverage_warning",
            "membership_policy",
            "index_method_effective",
            "created_at",
        ]
    ]
    validate_ohlcv(
        out,
        f"custom basket {basket_id}",
        entity_key="basket_id",
        required_columns=CUSTOM_BASKET_OUTPUT_REQUIRED_COLUMNS,
    )
    storage.upsert_custom_basket_ohlcv(out)
    return out


def custom_basket_quality_frame(basket_id: str, storage: DuckDBStorage | None = None) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    members = storage.list_basket_members(basket_id)
    total = len(members)
    if total == 0:
        return pd.DataFrame()
    df = storage.read_df(
        """
        SELECT *,
               COALESCE(coverage_ratio, member_count::DOUBLE / ?) AS coverage
        FROM custom_basket_ohlcv
        WHERE basket_id = ?
        ORDER BY trade_date
        """,
        [total, basket_id],
    )
    if not df.empty:
        if "low_coverage_warning" not in df:
            df["low_coverage_warning"] = False
        df["low_quality"] = df["low_coverage_warning"].fillna(False).astype(bool) | (df["coverage"] < LOW_COVERAGE_THRESHOLD)
    return df
