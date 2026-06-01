from __future__ import annotations

import pandas as pd


REQUIRED_OHLCV = {"trade_date", "open", "high", "low", "close"}


def validate_ohlcv(df: pd.DataFrame, name: str) -> None:
    missing = REQUIRED_OHLCV - set(df.columns)
    if missing:
        raise ValueError(f"{name} 缺少必要字段: {sorted(missing)}")
    if df.empty:
        raise ValueError(f"{name} 返回空数据")
    if df["trade_date"].isna().any():
        raise ValueError(f"{name} 存在空交易日期")
    if (df["close"].astype(float) <= 0).any():
        raise ValueError(f"{name} 存在非正收盘价")


def validate_board_type(board_type: str) -> str:
    if board_type not in {"industry", "concept"}:
        raise ValueError("board_type 必须是 industry 或 concept")
    return board_type

