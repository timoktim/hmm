from __future__ import annotations

import pandas as pd


def next_trade_date(trade_dates: list[pd.Timestamp] | pd.Series, signal_date: pd.Timestamp) -> pd.Timestamp | None:
    dates = pd.Series(pd.to_datetime(trade_dates)).drop_duplicates().sort_values()
    later = dates[dates > pd.Timestamp(signal_date)]
    if later.empty:
        return None
    return pd.Timestamp(later.iloc[0])


def assert_execution_after_signal(signals: pd.DataFrame) -> None:
    if not (pd.to_datetime(signals["exec_date"]) > pd.to_datetime(signals["signal_date"])).all():
        raise AssertionError("发现未来函数风险：执行日必须严格晚于信号日")

