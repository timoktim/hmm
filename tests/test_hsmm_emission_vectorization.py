from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.hsmm_model import DiscreteDurationGaussianHSMM


FEATURES = ["f1", "f2", "f3"]


def _sequence(sector_id: str, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    date = pd.Timestamp("2024-01-01")
    means = [
        np.array([-2.0, 0.0, 1.0], dtype=float),
        np.array([0.0, 2.0, -1.0], dtype=float),
        np.array([2.0, -1.0, 0.0], dtype=float),
    ]
    for repeat in range(5):
        for mean in means:
            for _ in range(5 + repeat % 2):
                values = mean + rng.normal(0.0, 0.08, size=len(FEATURES))
                rows.append(
                    {
                        "sector_id": sector_id,
                        "trade_date": date,
                        "f1": float(values[0]),
                        "f2": float(values[1]),
                        "f3": float(values[2]),
                    }
                )
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def _loop_emission(model: DiscreteDurationGaussianHSMM, x: np.ndarray) -> np.ndarray:
    out = np.empty((len(x), model.n_states), dtype=float)
    for state in range(model.n_states):
        var = np.maximum(model.vars_[state], model.variance_floor)
        diff = x - model.means_[state]
        out[:, state] = -0.5 * (np.log(2 * np.pi * var).sum() + ((diff * diff) / var).sum(axis=1))
    return out


def test_hsmm_emission_logprob_vectorized_matches_loop_formula():
    sequences = [_sequence("A", 1), _sequence("B", 2), _sequence("C", 3)]
    model = DiscreteDurationGaussianHSMM(n_states=3, max_duration=8, n_iter=2, random_state=13, engine="python")
    model.fit(sequences, FEATURES)
    x = model.scaler_.transform(sequences[0][FEATURES].to_numpy(dtype=float))

    vectorized = model._emission_logprob(x)
    loop = _loop_emission(model, x)

    np.testing.assert_allclose(vectorized, loop, atol=1e-10, rtol=0.0)
