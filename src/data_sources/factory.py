from __future__ import annotations

from pathlib import Path

from src.config import settings
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import AKShareClient
from src.data_sources.base import MarketDataClient
from src.data_sources.mootdx_client import MootdxClient


def create_data_client(
    source: str | None = None,
    storage: DuckDBStorage | None = None,
    cache_dir: Path | None = None,
) -> MarketDataClient:
    selected = (source or settings.market_data_source or settings.default_source).strip().lower()
    if selected in {"mootdx", "tdx", "pytdx"}:
        return MootdxClient(cache_dir=cache_dir, storage=storage)
    if selected in {"akshare", "ak"}:
        return AKShareClient(cache_dir=cache_dir, storage=storage)
    raise ValueError(f"未知数据源: {source}")
