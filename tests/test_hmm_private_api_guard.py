from __future__ import annotations

import numpy as np
import pytest

from src.models.hmm_model import filtered_predict_proba
from src.utils.dependency_guard import (
    HMMPrivateAPIError,
    last_monitor_log_prob,
    monitor_converged,
    monitor_history,
    require_hmmlearn_log_likelihood,
)


class _CompatibleModel:
    n_components = 2
    startprob_ = np.array([0.6, 0.4])
    transmat_ = np.array([[0.7, 0.3], [0.2, 0.8]])

    def _compute_log_likelihood(self, x: np.ndarray) -> np.ndarray:
        return np.log(np.array([[0.9, 0.1], [0.2, 0.8]])[: len(x)])


class _MissingPrivateAPIModel:
    n_components = 2
    startprob_ = np.array([0.5, 0.5])
    transmat_ = np.array([[0.8, 0.2], [0.3, 0.7]])


class _MonitorOnlyModel:
    class monitor_:
        history = [-12.5, None, "bad", -10.0]


def test_filtered_predict_proba_uses_private_api_wrapper() -> None:
    x = np.array([[1.0], [2.0]])

    probs = filtered_predict_proba(_CompatibleModel(), x, lengths=[2])

    assert probs.shape == (2, 2)
    np.testing.assert_allclose(probs.sum(axis=1), np.ones(2))


def test_missing_hmmlearn_private_log_likelihood_api_fails_explicitly() -> None:
    x = np.array([[1.0], [2.0]])

    with pytest.raises(HMMPrivateAPIError, match="_compute_log_likelihood"):
        filtered_predict_proba(_MissingPrivateAPIModel(), x, lengths=[2])


def test_private_log_likelihood_shape_mismatch_fails_explicitly() -> None:
    class BadShapeModel(_CompatibleModel):
        def _compute_log_likelihood(self, x: np.ndarray) -> np.ndarray:
            return np.array([0.0, 1.0])

    with pytest.raises(HMMPrivateAPIError, match="expected 2"):
        require_hmmlearn_log_likelihood(BadShapeModel(), np.array([[1.0], [2.0]]))


def test_missing_monitor_attributes_return_fallback_without_crashing() -> None:
    model = object()

    assert monitor_history(model) == ()
    assert last_monitor_log_prob(model) == float("-inf")
    assert monitor_converged(model) is False


def test_monitor_history_and_converged_access_are_guarded() -> None:
    model = _MonitorOnlyModel()

    assert monitor_history(model) == (-12.5, -10.0)
    assert last_monitor_log_prob(model) == -10.0
    assert monitor_converged(model) is False


def test_last_monitor_log_prob_uses_latest_history_value_or_fallback() -> None:
    class LatestInvalidModel:
        class monitor_:
            history = [-12.5, float("nan")]

    assert last_monitor_log_prob(LatestInvalidModel()) == float("-inf")
