"""Data source adapters."""

from src.data_sources.base import DataResult, MarketDataClient
from src.data_sources.factory import create_data_client

__all__ = ["DataResult", "MarketDataClient", "create_data_client"]
