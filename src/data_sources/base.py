from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import pandas as pd

from src.config import BoardType


@dataclass
class DataResult:
    data: pd.DataFrame
    stale: bool = False
    from_cache: bool = False
    error: str | None = None


class MarketDataClient(Protocol):
    def board_names(self, board_type: BoardType, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ...

    def board_hist(
        self,
        board_type: BoardType,
        sector_name: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        ...

    def board_constituents(self, board_type: BoardType, sector_name: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ...

    def stock_hist(self, stock_code: str, start_date: str, end_date: str, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ...

    def market_benchmark_hist(
        self,
        benchmark_id: str,
        start_date: str,
        end_date: str,
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        ...

    def market_index_hist(
        self,
        index_code: str,
        index_name: str | None = None,
        start_date: str = "20200101",
        end_date: str = "today",
        force_refresh: bool = False,
        ttl_seconds: int | float | None = None,
    ) -> DataResult:
        ...

    def all_a_stock_universe(self, force_refresh: bool = False, ttl_seconds: int | float | None = None) -> DataResult:
        ...
