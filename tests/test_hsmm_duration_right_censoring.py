from __future__ import annotations

import numpy as np

from src.models.hsmm_model import DiscreteDurationGaussianHSMM


def test_right_censored_terminal_segments_do_not_inflate_duration_pmf() -> None:
    model = DiscreteDurationGaussianHSMM(n_states=2, max_duration=5, duration_smoothing=0.0)
    arrays = [np.zeros((9, 1))]
    paths = [np.array([0, 0, 1, 1, 0, 0, 0, 1, 1])]

    model._update_parameters(arrays, paths)

    assert np.isclose(model.duration_pmf_[0, 1], 0.5)
    assert np.isclose(model.duration_pmf_[0, 2], 0.5)
    assert np.isclose(model.duration_pmf_[1, 1], 1.0)
    assert np.isclose(model.duration_pmf_[1, 4], 0.0)


def test_all_right_censored_state_uses_smoothing_not_observed_tail_certainty() -> None:
    model = DiscreteDurationGaussianHSMM(n_states=2, max_duration=4, duration_smoothing=0.1)
    arrays = [np.zeros((7, 1))]
    paths = [np.zeros(7, dtype=int)]

    model._update_parameters(arrays, paths)

    assert np.allclose(model.duration_pmf_[0], np.full(4, 0.25))
    assert np.isnan(model.p_exit_h(0, age=model.max_duration, horizon=1))
    assert model.p_exit_status(0, age=model.max_duration, horizon=1) == "beyond_duration_support"
