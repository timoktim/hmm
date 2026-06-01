from __future__ import annotations

from datetime import date, datetime

import pandas as pd


def today_yyyymmdd() -> str:
    return date.today().strftime("%Y%m%d")


def normalize_yyyymmdd(value: str | date | datetime | pd.Timestamp | None) -> str:
    if value is None or value == "today":
        return today_yyyymmdd()
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y%m%d")
    if isinstance(value, datetime):
        return value.strftime("%Y%m%d")
    if isinstance(value, date):
        return value.strftime("%Y%m%d")
    text = str(value).replace("-", "").strip()
    if len(text) != 8 or not text.isdigit():
        raise ValueError(f"日期必须是 YYYYMMDD 或 today，收到: {value}")
    return text


def to_trade_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series).dt.date

