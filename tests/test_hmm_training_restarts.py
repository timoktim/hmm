from __future__ import annotations

import numpy as np

from src.models.hmm_model import fit_hmm_with_restarts


def test_fit_hmm_with_restarts_uses_min_covar_and_best_log_prob(monkeypatch):
    import hmmlearn.hmm as hmm_mod

    calls: list[dict[str, object]] = []

    class FakeMonitor:
        def __init__(self, log_prob: float):
            self.history = [log_prob]
            self.converged = True

    class FakeGaussianHMM:
        def __init__(self, n_components, covariance_type, n_iter, random_state, min_covar, verbose):
            self.n_components = n_components
            self.covariance_type = covariance_type
            self.n_iter = n_iter
            self.random_state = random_state
            self.min_covar = min_covar
            self.verbose = verbose
            calls.append(
                {
                    "n_components": n_components,
                    "covariance_type": covariance_type,
                    "n_iter": n_iter,
                    "random_state": random_state,
                    "min_covar": min_covar,
                }
            )

        def fit(self, x, lengths):
            scores = {42: -100.0, 43: -80.0, 44: -90.0}
            self.monitor_ = FakeMonitor(scores[self.random_state])
            return self

    monkeypatch.setattr(hmm_mod, "GaussianHMM", FakeGaussianHMM)

    result = fit_hmm_with_restarts(
        np.zeros((12, 2)),
        lengths=[12],
        n_states=3,
        n_iter=20,
        random_state=42,
        n_init=3,
        min_covar=1e-4,
    )

    assert [call["random_state"] for call in calls] == [42, 43, 44]
    assert all(call["min_covar"] == 1e-4 for call in calls)
    assert result.best_random_state == 43
    assert result.best_log_prob == -80.0
    assert result.model.random_state == 43
