from __future__ import annotations

import numpy as np
import pandas as pd

from src.backtest.sector_rotation import simulate_portfolio_returns


def test_open_execution_excludes_entry_day_intraday_return_by_default():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    open_prices = pd.DataFrame({"industry:test": [100.0, 100.0, 120.0, 120.0]}, index=dates)
    close_prices = pd.DataFrame({"industry:test": [100.0, 120.0, 120.0, 120.0]}, index=dates)
    events = pd.DataFrame(
        [
            {
                "signal_date": dates[0],
                "exec_date": dates[1],
                "weights": {"industry:test": 1.0},
            }
        ]
    )

    curve, trades = simulate_portfolio_returns(
        open_prices,
        close_prices,
        events,
        execution_price="open",
        transaction_cost=0.0,
    )

    exec_row = curve[curve["trade_date"] == dates[1]].iloc[0]
    assert exec_row["gross_return"] == 0.0
    assert curve.attrs["execution_price_policy"] == "signal_date_close_to_next_trade_date_open"
    assert curve.attrs["execution_timing"] == "next_trade_date_open"
    assert curve.attrs["entry_day_return_policy"] == "exclude_entry_day_intraday"
    assert curve.attrs["cost_policy"] == "single_side_turnover_cost"
    assert trades.loc[0, "entry_day_return_policy"] == "exclude_entry_day_intraday"


def test_open_to_close_entry_day_return_requires_explicit_policy():
    dates = pd.date_range("2024-01-01", periods=4, freq="D")
    open_prices = pd.DataFrame({"industry:test": [100.0, 100.0, 120.0, 120.0]}, index=dates)
    close_prices = pd.DataFrame({"industry:test": [100.0, 120.0, 120.0, 120.0]}, index=dates)
    events = pd.DataFrame(
        [
            {
                "signal_date": dates[0],
                "exec_date": dates[1],
                "weights": {"industry:test": 1.0},
            }
        ]
    )

    curve, trades = simulate_portfolio_returns(
        open_prices,
        close_prices,
        events,
        execution_price="open",
        transaction_cost=0.0,
        entry_day_return_policy="include_open_to_close",
    )

    exec_row = curve[curve["trade_date"] == dates[1]].iloc[0]
    assert np.isclose(exec_row["gross_return"], 0.20)
    assert curve.attrs["entry_day_return_policy"] == "include_open_to_close"
    assert trades.loc[0, "entry_day_return_policy"] == "include_open_to_close"
