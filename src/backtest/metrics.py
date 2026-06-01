from __future__ import annotations

import numpy as np
import pandas as pd


def max_drawdown(nav: pd.Series) -> float:
    if nav.empty:
        return 0.0
    return float((nav / nav.cummax() - 1).min())


def annual_return(nav: pd.Series, periods_per_year: int = 252) -> float:
    if len(nav) < 2:
        return 0.0
    total = nav.iloc[-1] / nav.iloc[0] - 1
    years = max((len(nav) - 1) / periods_per_year, 1 / periods_per_year)
    return float((1 + total) ** (1 / years) - 1)


def sharpe_ratio(returns: pd.Series, periods_per_year: int = 252) -> float:
    ret = returns.dropna()
    if ret.empty or ret.std(ddof=0) == 0:
        return 0.0
    return float(ret.mean() / ret.std(ddof=0) * np.sqrt(periods_per_year))


def calmar_ratio(nav: pd.Series, periods_per_year: int = 252) -> float:
    dd = abs(max_drawdown(nav))
    if dd == 0:
        return 0.0
    return float(annual_return(nav, periods_per_year=periods_per_year) / dd)


def win_rate(returns: pd.Series) -> float:
    ret = returns.dropna()
    if ret.empty:
        return 0.0
    return float((ret > 0).mean())
