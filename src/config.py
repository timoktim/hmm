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
    default_feature_version: str = "v1"
    default_source: str = "akshare"
    bypass_proxy_for_akshare: bool = True

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
