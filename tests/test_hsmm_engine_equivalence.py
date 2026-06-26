from __future__ import annotations

import importlib.util

import numpy as np
import pandas as pd
import pytest

from src.models.hsmm_model import DiscreteDurationGaussianHSMM


FEATURES = ["f1", "f2"]


def _numba_available() -> bool:
    return importlib.util.find_spec("numba") is not None


def _sequence(sector_id: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    date = pd.Timestamp("2024-01-01")
    specs = [
        (5, np.array([-3.0, 0.0])),
        (8, np.array([0.0, 3.0])),
        (9, np.array([3.0, 0.0])),
        (6, np.array([0.0, -3.0])),
    ]
    for repeat in range(3):
        for duration, mean in specs:
            for _ in range(duration + repeat % 2):
                values = mean + rng.normal(0.0, 0.06, size=2)
                rows.append(
                    {
                        "sector_id": sector_id,
                        "trade_date": date,
                        "f1": float(values[0]),
                        "f2": float(values[1]),
                    }
                )
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def _fit(engine: str) -> DiscreteDurationGaussianHSMM:
    model = DiscreteDurationGaussianHSMM(
        n_states=4,
        max_duration=12,
        n_iter=3,
        random_state=23,
        engine=engine,
        n_jobs=1,
    )
    model.fit([_sequence("A", 101), _sequence("B", 102), _sequence("C", 103)], FEATURES)
    return model


def test_hsmm_python_and_numba_training_outputs_are_equivalent():
    if not _numba_available():
        pytest.skip("numba is not installed")

    python_model = _fit("python")
    try:
        numba_model = _fit("numba")
    except RuntimeError as exc:
        pytest.skip(f"numba engine unavailable: {exc}")

    assert numba_model.engine_used_ == "numba"
    np.testing.assert_allclose(numba_model.means_, python_model.means_, atol=1e-8, rtol=0.0)
    np.testing.assert_allclose(numba_model.vars_, python_model.vars_, atol=1e-8, rtol=0.0)
    np.testing.assert_allclose(numba_model.transmat_, python_model.transmat_, atol=1e-8, rtol=0.0)
    np.testing.assert_allclose(numba_model.duration_pmf_, python_model.duration_pmf_, atol=1e-8, rtol=0.0)
    np.testing.assert_allclose(numba_model.startprob_, python_model.startprob_, atol=1e-8, rtol=0.0)
    np.testing.assert_allclose(numba_model.monitor_history_, python_model.monitor_history_, atol=1e-8, rtol=0.0)

    for sequence in [_sequence("D", 104), _sequence("E", 105)]:
        np.testing.assert_array_equal(
            numba_model.decode(sequence)["state_id"].to_numpy(),
            python_model.decode(sequence)["state_id"].to_numpy(),
        )
