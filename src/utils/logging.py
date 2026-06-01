from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from src.config import PROJECT_ROOT, settings


def setup_logging() -> None:
    log_dir = PROJECT_ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(log_dir / "app.log", level="INFO", rotation="10 MB", retention="14 days")


setup_logging()

