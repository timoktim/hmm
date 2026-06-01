from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.features.stock_features import stock_feature_frame


def _risk_flags(
    row: pd.Series,
    sector_recent_weak: bool = False,
    max_drawdown: float = -0.18,
    has_market_benchmark: bool = True,
) -> list[str]:
    flags: list[str] = []
    if row.get("ret_20d", 0) > 0.35:
        flags.append("近期涨幅偏大")
    if row.get("vol_20d", 0) > 0.18:
        flags.append("波动偏高")
    if row.get("amount_z_20d", 0) < -0.5:
        flags.append("成交额偏低")
    if row.get("close", 0) < row.get("ma20", 0):
        flags.append("跌破 20 日均线")
    if row.get("drawdown_20d", 0) < max_drawdown:
        flags.append("回撤偏大")
    if sector_recent_weak:
        flags.append("板块状态转弱")
    if bool(row.get("is_limit_up", False)):
        flags.append("涨停不可追")
    if bool(row.get("is_limit_down", False)):
        flags.append("跌停流动性风险")
    if bool(row.get("is_suspended_or_missing", False)):
        flags.append("停牌或缺失行情")
    if row.get("consecutive_limit_up_days", 0) >= 2:
        flags.append("连续涨停后拥挤")
    if abs(row.get("gap_1d", 0) or 0) > 0.07:
        flags.append("跳空过大")
    if pd.isna(row.get("rs_vs_sector_20d")) or (has_market_benchmark and pd.isna(row.get("rs_vs_index_20d"))):
        flags.append("数据缺失")
    return flags


def _normalize_positive(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce").fillna(0)
    std = s.std(ddof=0)
    if std == 0 or not np.isfinite(std):
        return pd.Series(0.0, index=s.index)
    return ((s - s.mean()) / std).clip(-3, 3)


def load_market_benchmark_close(storage: DuckDBStorage, benchmark_id: str | None = None) -> pd.Series | None:
    storage.init_schema()
    if benchmark_id:
        df = storage.read_df(
            "SELECT trade_date, close FROM market_benchmark_ohlcv WHERE benchmark_id = ? ORDER BY trade_date",
            [benchmark_id],
        )
    else:
        first = storage.read_df("SELECT benchmark_id FROM market_benchmark_ohlcv ORDER BY benchmark_id LIMIT 1")
        if first.empty:
            return None
        df = storage.read_df(
            "SELECT trade_date, close FROM market_benchmark_ohlcv WHERE benchmark_id = ? ORDER BY trade_date",
            [first.loc[0, "benchmark_id"]],
        )
    if df.empty:
        return None
    return pd.Series(df["close"].to_numpy(), index=pd.to_datetime(df["trade_date"]))


def _constituents_for_sector(storage: DuckDBStorage, sector_id: str) -> pd.DataFrame:
    if str(sector_id).startswith("custom:"):
        return storage.read_df(
            """
            SELECT stock_code, stock_name, weight, note
            FROM custom_stock_basket_members
            WHERE basket_id = ?
            ORDER BY stock_code
            """,
            [sector_id],
        )
    return storage.read_df("SELECT * FROM sector_constituents WHERE sector_id = ?", [sector_id])


def _sector_close_for_sector(storage: DuckDBStorage, sector_id: str) -> pd.DataFrame:
    if str(sector_id).startswith("custom:"):
        return storage.read_df(
            """
            SELECT trade_date, close
            FROM custom_basket_ohlcv
            WHERE basket_id = ?
            ORDER BY trade_date
            """,
            [sector_id],
        )
    return storage.read_df("SELECT trade_date, close FROM sector_ohlcv WHERE sector_id = ? ORDER BY trade_date", [sector_id])


def _empty_filter_result(return_diagnostics: bool) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, object]]:
    empty = pd.DataFrame()
    if return_diagnostics:
        return empty, {"total": 0, "filters": [], "has_market_benchmark": False}
    return empty


def filter_sector_stocks(
    sector_id: str,
    trade_date: str | None = None,
    drawdown_threshold: float = 0.18,
    min_amount_z: float = -0.5,
    benchmark_id: str | None = None,
    require_close_above_ma20: bool = True,
    require_ma20_slope_positive: bool = True,
    require_rs_vs_index_positive: bool = True,
    return_diagnostics: bool = False,
    storage: DuckDBStorage | None = None,
) -> pd.DataFrame | tuple[pd.DataFrame, dict[str, object]]:
    storage = storage or DuckDBStorage()
    storage.init_schema()
    cons = _constituents_for_sector(storage, sector_id)
    if cons.empty:
        return _empty_filter_result(return_diagnostics)
    codes = cons["stock_code"].astype(str).tolist()
    placeholders = ",".join(["?"] * len(codes))
    stocks = storage.read_df(
        f"SELECT * FROM stock_ohlcv WHERE stock_code IN ({placeholders}) ORDER BY stock_code, trade_date",
        codes,
    )
    sector = _sector_close_for_sector(storage, sector_id)
    if stocks.empty or sector.empty:
        return _empty_filter_result(return_diagnostics)
    benchmark_close = load_market_benchmark_close(storage, benchmark_id=benchmark_id)
    has_market_benchmark = benchmark_close is not None
    features = stock_feature_frame(stocks, sector, benchmark_close=benchmark_close)
    features = features.merge(cons[["stock_code", "stock_name"]], on="stock_code", how="left")
    if trade_date:
        target_date = pd.to_datetime(trade_date)
    else:
        target_date = features["trade_date"].max()
    latest = features[features["trade_date"] == target_date].copy()
    if latest.empty:
        return _empty_filter_result(return_diagnostics)
    latest["risk_flags"] = latest.apply(
        lambda r: _risk_flags(r, max_drawdown=-abs(drawdown_threshold), has_market_benchmark=has_market_benchmark),
        axis=1,
    )
    latest["risk_penalty"] = latest["risk_flags"].map(len) * 0.08
    latest["score"] = (
        0.30 * _normalize_positive(latest["rs_vs_sector_20d"])
        + 0.20 * latest["trend_quality"].fillna(0)
        + 0.15 * _normalize_positive(latest["amount_z_20d"])
        - 0.10 * _normalize_positive(latest["vol_20d"])
        - 0.10 * _normalize_positive(latest["drawdown_20d"].abs())
        - latest["risk_penalty"]
    )
    if has_market_benchmark:
        latest["score"] = latest["score"] + 0.25 * _normalize_positive(latest["rs_vs_index_20d"])
    else:
        latest["benchmark_status"] = "缺少市场基准"

    diagnostics: dict[str, object] = {
        "total": int(len(latest)),
        "trade_date": str(target_date.date() if hasattr(target_date, "date") else target_date),
        "has_market_benchmark": bool(has_market_benchmark),
        "filters": [],
        "failed_examples": [],
    }
    mask = pd.Series(True, index=latest.index)
    first_failure = pd.Series("", index=latest.index, dtype=object)

    def apply_filter(label: str, condition: pd.Series, enabled: bool = True, skipped_reason: str | None = None, reason: str | None = None) -> None:
        nonlocal mask
        before = int(mask.sum())
        if enabled:
            cond = condition.fillna(False)
            failed_now = mask & ~cond
            first_failure.loc[failed_now & first_failure.eq("")] = reason or label
            mask = mask & cond
            after = int(mask.sum())
        else:
            after = before
        diagnostics["filters"].append(
            {
                "condition": label,
                "enabled": bool(enabled),
                "before": before,
                "after": after,
                "removed": before - after,
                "skipped_reason": skipped_reason,
            }
        )

    apply_filter("排除 ST / 退市风险名称", ~latest["stock_name"].fillna("").str.contains("ST|退", regex=True), reason="ST / 退市风险")
    apply_filter(f"成交额热度高于 {min_amount_z:.2f}", latest["amount_z_20d"] > min_amount_z, reason="成交额过低")
    apply_filter(f"20日回撤不低于 {-abs(drawdown_threshold):.2f}", latest["drawdown_20d"] >= -abs(drawdown_threshold), reason="回撤过大")
    apply_filter("收盘价高于20日均线", latest["close"] > latest["ma20"], require_close_above_ma20, reason="未站上20日均线")
    apply_filter("20日均线向上", latest["ma20_slope"] > 0, require_ma20_slope_positive, reason="20日均线未向上")
    apply_filter("20日相对板块强弱为正", latest["rs_vs_sector_20d"] > 0, reason="相对板块走弱")
    if has_market_benchmark:
        apply_filter("20日相对大盘强弱为正", latest["rs_vs_index_20d"] > 0, require_rs_vs_index_positive, reason="相对大盘走弱")
    else:
        apply_filter("20日相对大盘强弱为正", pd.Series(True, index=latest.index), False, "缺少市场基准")

    out = latest.loc[mask].copy().sort_values("score", ascending=False)
    out["risk_flags_json"] = out["risk_flags"].map(lambda flags: json.dumps(flags, ensure_ascii=False))
    columns = [
        "stock_code",
        "stock_name",
        "trade_date",
        "close",
        "ma20",
        "ma20_slope",
        "score",
        "rs_vs_sector_20d",
        "rs_vs_index_20d",
        "amount_z_20d",
        "vol_20d",
        "drawdown_20d",
        "gap_1d",
        "intraday_ret",
        "is_limit_up",
        "is_limit_down",
        "is_one_word_limit",
        "is_suspended_or_missing",
        "consecutive_limit_up_days",
        "consecutive_limit_down_days",
        "risk_flags_json",
    ]
    if "benchmark_status" in out.columns:
        columns.append("benchmark_status")
    result = out[columns]
    if return_diagnostics:
        diagnostics["passed"] = int(len(result))
        failed = latest.loc[first_failure.ne(""), ["stock_code", "stock_name"]].copy()
        if not failed.empty:
            failed["failed_reason"] = first_failure.loc[failed.index]
            diagnostics["failed_examples"] = failed.head(30).to_dict(orient="records")
        return result, diagnostics
    return result
