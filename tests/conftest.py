from __future__ import annotations

import os

import pytest

from src.config import settings


for env_name in ["OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS", "LOKY_MAX_CPU_COUNT"]:
    os.environ.setdefault(env_name, "1")
os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
os.environ.setdefault("KMP_BLOCKTIME", "0")


@pytest.fixture(autouse=True)
def isolate_model_artifacts(tmp_path, monkeypatch):
    model_dir = tmp_path / "models"
    model_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(settings, "model_dir", model_dir)


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.option.markexpr:
        return
    skip_slow = pytest.mark.skip(reason="slow test; run with -m slow")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
