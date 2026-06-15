from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_prefix="ASHARE_HMM_",
        extra="ignore",
    )

    db_path: Path = Field(default=PROJECT_ROOT / "data" / "db" / "a_share_hmm.duckdb")
    cache_dir: Path = Field(default=PROJECT_ROOT / "data" / "cache")
    model_dir: Path = Field(default=PROJECT_ROOT / "data" / "models")
    log_level: str = "INFO"
    request_min_sleep: float = 0.5
    request_max_sleep: float = 1.5
    cache_ttl_seconds: int = 24 * 60 * 60
    duckdb_threads: int = 4
    default_feature_version: str = "v1"
    default_source: str = "tushare"
    market_data_source: str = "tushare"
    tushare_token: str | None = None
    tushare_points: int = 2000
    tushare_rate_limit_per_minute: int = 200
    tushare_request_min_interval_seconds: float = 0.31
    tushare_request_jitter_seconds: float = 0.02
    tushare_max_retries: int = 3
    tushare_timeout_seconds: float = 20.0
    tushare_daily_include_basic: bool = True
    tushare_qfq_adjustment_enabled: bool = True
    tushare_use_official_sw_daily: bool = False
    tushare_sw_level: str = "L2"
    tushare_sw_source: str = "SW2021"
    tushare_concept_source: str = "ts"
    bypass_proxy_for_akshare: bool = True
    tdx_servers: str = (
        "119.147.212.81:7709,"
        "221.194.181.176:7709,"
        "202.108.253.130:7709,"
        "59.173.18.69:7709,"
        "180.153.18.170:7709,"
        "218.75.126.9:7709"
    )
    tdx_per_server_workers: int = 1
    tdx_global_workers: int = 8
    tdx_max_workers: int = 16
    tdx_batch_size: int = 80
    tdx_batch_sleep_seconds: float = 3.0
    tdx_request_timeout_seconds: float = 15.0
    tdx_server_cooldown_seconds: float = 120.0
    tdx_failure_threshold: int = 3
    tdx_bar_count: int = 800
    tdx_fallback_to_akshare: bool = False

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.model_dir.mkdir(parents=True, exist_ok=True)


BoardType = Literal["industry", "concept"]


settings = Settings()
settings.ensure_dirs()


def project_relative_path(path: Path | str) -> str:
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(Path(path).name)
