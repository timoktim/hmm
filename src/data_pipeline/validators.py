from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


REQUIRED_OHLCV = {"trade_date", "open", "high", "low", "close"}


@dataclass(frozen=True)
class OhlcvValidationResult:
    name: str
    rows: int
    warnings: list[str]
    entity_key: str | None = None
    required_columns: tuple[str, ...] = ()


def _failures_message(name: str, failures: list[str]) -> str:
    return f"{name} OHLCV validation failed: " + "; ".join(failures)


def validate_ohlcv(
    df: pd.DataFrame,
    name: str,
    *,
    entity_key: str | None = None,
    required_columns: set[str] | None = None,
    strict: bool = False,
    gap_threshold: float = 0.35,
) -> OhlcvValidationResult:
    required = set(required_columns or REQUIRED_OHLCV)
    failures: list[str] = []
    warnings: list[str] = []

    missing = required - set(df.columns)
    if entity_key and entity_key not in df.columns:
        missing.add(entity_key)
    if missing:
        failures.append(f"缺少必要字段: {sorted(missing)}")
    if df.empty:
        failures.append("返回空数据")
    if failures:
        raise ValueError(_failures_message(name, failures))

    working = df.copy()
    if working["trade_date"].isna().any():
        failures.append("存在空交易日期")
    trade_dates = pd.to_datetime(working["trade_date"], errors="coerce")
    if trade_dates.isna().any():
        failures.append("存在不可解析交易日期")
    working["_trade_date_for_validation"] = trade_dates

    duplicate_keys = [entity_key, "_trade_date_for_validation"] if entity_key else ["_trade_date_for_validation"]
    if working.duplicated(subset=duplicate_keys).any():
        label = f"{entity_key}+trade_date" if entity_key else "trade_date"
        failures.append(f"存在重复 {label}")

    numeric_columns = [column for column in ["open", "high", "low", "close", "volume", "amount"] if column in working.columns]
    numeric_values: dict[str, pd.Series] = {}
    for column in numeric_columns:
        values = pd.to_numeric(working[column], errors="coerce")
        numeric_values[column] = values
        if values.isna().any():
            failures.append(f"{column} 存在不可转数值")
        if np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).any():
            failures.append(f"{column} 存在 inf 数值")

    for column in ["open", "high", "low", "close"]:
        values = numeric_values.get(column)
        if values is not None and (values <= 0).any():
            failures.append(f"{column} 存在非正数值")

    for column in ["volume", "amount"]:
        values = numeric_values.get(column)
        if values is not None and (values < 0).any():
            failures.append(f"{column} 存在负数值")

    if {"high", "low"}.issubset(numeric_values) and (numeric_values["high"] < numeric_values["low"]).any():
        failures.append("high 小于 low")
    if {"high", "open"}.issubset(numeric_values) and (numeric_values["high"] < numeric_values["open"]).any():
        failures.append("high 小于 open")
    if {"high", "close"}.issubset(numeric_values) and (numeric_values["high"] < numeric_values["close"]).any():
        failures.append("high 小于 close")
    if {"low", "open"}.issubset(numeric_values) and (numeric_values["low"] > numeric_values["open"]).any():
        failures.append("low 大于 open")
    if {"low", "close"}.issubset(numeric_values) and (numeric_values["low"] > numeric_values["close"]).any():
        failures.append("low 大于 close")

    if failures:
        raise ValueError(_failures_message(name, failures))

    sort_columns = [entity_key, "_trade_date_for_validation"] if entity_key else ["_trade_date_for_validation"]
    working = working.assign(_close_for_validation=numeric_values.get("close")).sort_values(sort_columns)
    group_keys = [entity_key] if entity_key else None
    if "close" in numeric_values:
        if group_keys:
            close_change = working.groupby(group_keys, sort=False)["_close_for_validation"].pct_change().abs()
        else:
            close_change = working["_close_for_validation"].pct_change().abs()
        if (close_change > gap_threshold).any():
            warnings.append(f"close pct_change gap exceeds threshold: count={int((close_change > gap_threshold).sum())}")

    if {"open", "close"}.issubset(numeric_values):
        working = working.assign(_open_for_validation=numeric_values["open"])
        if group_keys:
            previous_close = working.groupby(group_keys, sort=False)["_close_for_validation"].shift(1)
        else:
            previous_close = working["_close_for_validation"].shift(1)
        open_gap = (working["_open_for_validation"] / previous_close - 1.0).abs()
        if (open_gap > gap_threshold).any():
            warnings.append(f"open/previous close gap exceeds threshold: count={int((open_gap > gap_threshold).sum())}")

    if strict and warnings:
        raise ValueError(_failures_message(name, warnings))

    return OhlcvValidationResult(
        name=name,
        rows=len(df),
        warnings=warnings,
        entity_key=entity_key,
        required_columns=tuple(sorted(required)),
    )


def validate_board_type(board_type: str) -> str:
    if board_type not in {"industry", "concept"}:
        raise ValueError("board_type 必须是 industry 或 concept")
    return board_type
