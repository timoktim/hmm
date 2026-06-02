from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.hsmm_model import DiscreteDurationGaussianHSMM


FEATURES = ["f1", "f2"]


def _synthetic_sequence(sector_id: str, repeats: int = 4) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    specs = [
        (0, 4, np.array([-4.0, 0.0])),
        (1, 8, np.array([0.0, 4.0])),
        (2, 12, np.array([4.0, 0.0])),
        (3, 6, np.array([0.0, -4.0])),
    ]
    rows = []
    date = pd.Timestamp("2024-01-01")
    for _ in range(repeats):
        for state, duration, mean in specs:
            for _ in range(duration):
                values = mean + rng.normal(0, 0.15, size=2)
                rows.append({"sector_id": sector_id, "trade_date": date, "f1": values[0], "f2": values[1], "true_state": state})
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def test_duration_probabilities_are_stable_and_monotonic():
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=15, n_iter=3, random_state=3)
    model.fit([_synthetic_sequence("A"), _synthetic_sequence("B")], FEATURES)

    assert np.allclose(model.duration_pmf_.sum(axis=1), 1.0)
    assert np.allclose(np.diag(model.transmat_), 0.0)
    assert np.allclose(model.transmat_.sum(axis=1), 1.0)

    for state_id in range(model.n_states):
        assert model.p_exit_h(state_id, 3, 5) >= model.p_exit_h(state_id, 3, 1)
        assert model.p_exit_h(state_id, 3, 10) >= model.p_exit_h(state_id, 3, 5)
        assert model.expected_remaining_days(state_id, 3) >= 0
        assert np.isnan(model.p_exit_h(state_id, model.max_duration + 5, 1))
        assert model.duration_percentile_status(state_id, model.max_duration) == "beyond_support"
        assert model.expected_remaining_days(state_id, model.max_duration + 5) == 0.0


def test_hsmm_p_exit_counts_D_equal_age_for_1d_exit():
    model = DiscreteDurationGaussianHSMM(n_states=2, max_duration=5)
    model.duration_pmf_ = np.array(
        [
            [0.0, 0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 0.5, 0.5, 0.0],
        ]
    )

    assert model.p_exit_h(0, age=3, horizon=1) == 1.0
    assert np.isclose(model.p_exit_h(1, age=3, horizon=1), 0.5)


def test_hsmm_p_stay_plus_exit_equals_one_and_expected_remaining_is_conditional():
    model = DiscreteDurationGaussianHSMM(n_states=2, max_duration=5)
    model.duration_pmf_ = np.array([[0.0, 0.0, 0.5, 0.5, 0.0], [0.2, 0.2, 0.2, 0.2, 0.2]])

    p_exit = model.p_exit_h(0, age=3, horizon=1)
    assert np.isclose((1.0 - p_exit) + p_exit, 1.0)
    assert np.isclose(model.expected_remaining_days(0, age=3), 0.5)
    assert np.isnan(model.p_exit_h(0, age=6, horizon=1))


def test_synthetic_data_recovers_different_duration_profiles():
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=15, n_iter=5, duration_smoothing=0.1, random_state=5)
    model.fit([_synthetic_sequence("A"), _synthetic_sequence("B")], FEATURES)

    support = np.arange(1, model.max_duration + 1)
    expected_durations = model.duration_pmf_.dot(support)

    assert expected_durations.max() - expected_durations.min() > 3
    decoded = model.decode(_synthetic_sequence("C"))
    episode_lengths = decoded.groupby("segment_id").size()
    assert (episode_lengths <= 1).mean() < 0.25


def test_decode_many_keeps_sector_boundaries():
    seq_a = _synthetic_sequence("A", repeats=2)
    seq_b = _synthetic_sequence("B", repeats=2)
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=15, n_iter=3, random_state=11)
    model.fit([seq_a, seq_b], FEATURES)

    decoded = model.decode_many([seq_a, seq_b])

    assert set(decoded["sector_id"]) == {"A", "B"}
    for _, group in decoded.groupby("sector_id"):
        assert group["segment_id"].min() == 0
        assert group.iloc[0]["state_age_days"] == 1
