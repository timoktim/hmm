from __future__ import annotations

import numpy as np
import pandas as pd

from src.models.hsmm_model import DiscreteDurationGaussianHSMM


FEATURES = ["f1", "f2"]
PREFIX_COMPARE_FIELDS = [
    "state_id",
    "state_label",
    "state_age_days",
    "state_age_days_by_id",
    "state_age_days_by_label",
    "model_state_age_days",
    "label_state_age_days",
    "duration_model_age_days",
    "display_state_age_days",
    "duration_percentile",
    "duration_percentile_status",
    "duration_tail_status",
    "state_phase",
    "expected_remaining_days",
    "p_exit_1d",
    "p_exit_3d",
    "p_exit_5d",
    "p_exit_10d",
    "p_exit_20d",
    "raw_p_exit_1d",
    "raw_p_exit_3d",
    "raw_p_exit_5d",
    "raw_p_exit_10d",
    "raw_p_exit_20d",
    "raw_p_exit_1d_status",
    "raw_p_exit_3d_status",
    "raw_p_exit_5d_status",
    "raw_p_exit_10d_status",
    "raw_p_exit_20d_status",
]


def _sequence(sector_id: str, repeats: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    specs = [
        (5, np.array([-3.0, 0.0])),
        (7, np.array([0.0, 3.0])),
        (9, np.array([3.0, 0.0])),
        (6, np.array([0.0, -3.0])),
    ]
    rows = []
    date = pd.Timestamp("2024-01-01")
    for _ in range(repeats):
        for duration, mean in specs:
            for _ in range(duration):
                values = mean + rng.normal(0, 0.08, size=2)
                rows.append({"sector_id": sector_id, "trade_date": date, "f1": values[0], "f2": values[1]})
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def _assert_snapshots_equal(left: dict[str, object], right: dict[str, object]) -> None:
    for field in PREFIX_COMPARE_FIELDS:
        assert field in left
        assert field in right
        if isinstance(left[field], str):
            assert left[field] == right[field], field
        else:
            assert np.isclose(float(left[field]), float(right[field]), atol=1e-10, equal_nan=True), field


def test_prefix_snapshot_ignores_future_suffix_changes():
    seq = _sequence("A")
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=12, n_iter=3, random_state=9, engine="python")
    model.fit([seq, _sequence("B")], FEATURES)
    snapshot_date = pd.Timestamp(seq["trade_date"].iloc[30])

    baseline = model.lifecycle_snapshots_from_sequence(seq, [snapshot_date])[0]
    mutated = seq.copy()
    future_mask = pd.to_datetime(mutated["trade_date"]) > snapshot_date
    mutated.loc[future_mask, "f1"] = mutated.loc[future_mask, "f1"] * -100.0 + 250.0
    mutated.loc[future_mask, "f2"] = mutated.loc[future_mask, "f2"] * 100.0 - 250.0
    changed_future = model.lifecycle_snapshots_from_sequence(mutated, [snapshot_date])[0]

    _assert_snapshots_equal(baseline, changed_future)
