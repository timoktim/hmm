from __future__ import annotations

import numpy as np
import pandas as pd

from src.evaluation.hsmm_display_lifecycle import build_lifecycle_ui_frame
from src.models.hsmm_model import DiscreteDurationGaussianHSMM


def _tail_model() -> DiscreteDurationGaussianHSMM:
    model = DiscreteDurationGaussianHSMM(n_states=2, max_duration=5)
    model.duration_pmf_ = np.array(
        [
            [0.0, 0.0, 0.25, 0.50, 0.25],
            [0.20, 0.20, 0.20, 0.20, 0.20],
        ]
    )
    model.transmat_ = np.array([[0.0, 1.0], [1.0, 0.0]])
    model.state_labels_ = {0: "Stress", 1: "Trend"}
    return model


def test_beyond_support_p_exit_is_not_false_certainty():
    model = _tail_model()

    assert np.isnan(model.p_exit_h(0, age=model.max_duration + 1, horizon=1))
    assert model.p_exit_h(0, age=model.max_duration + 1, horizon=1) != 1.0
    assert model.duration_percentile(0, age=model.max_duration) == 1.0
    assert model.duration_percentile_status(0, age=model.max_duration) == "beyond_support"


def test_lifecycle_snapshot_marks_beyond_support_exit_as_unavailable_raw_score():
    model = _tail_model()
    decoded = pd.DataFrame(
        [
            {
                "trade_date": pd.Timestamp("2024-01-10"),
                "state_id": 0,
                "state_label": "Stress",
                "state_age_days": model.max_duration + 1,
                "state_age_days_by_id": model.max_duration + 1,
                "state_age_days_by_label": model.max_duration + 1,
                "viterbi_score": -1.0,
            }
        ]
    )

    snapshot = model.lifecycle_snapshot(decoded, pd.Timestamp("2024-01-10"))

    assert np.isnan(snapshot["p_exit_1d"])
    assert np.isnan(snapshot["raw_p_exit_1d"])
    assert np.isnan(snapshot["p_stay_1d"])
    assert snapshot["duration_percentile"] == 1.0


def test_lifecycle_ui_tail_censored_rows_do_not_show_100_percent_exit():
    states = pd.DataFrame(
        [
            {
                "run_id": "tail_run",
                "trade_date": pd.Timestamp("2024-01-10"),
                "sector_code": "S1",
                "sector_name": "S1",
                "state_id": 0,
                "state_label": "Stress",
                "state_age_days": 6,
                "state_age_days_by_id": 6,
                "state_age_days_by_label": 6,
                "model_state_age_days": 6,
                "label_state_age_days": 6,
                "duration_model_age_days": 6,
                "display_state_age_days": 6,
                "duration_percentile": 1.0,
                "expected_remaining_days": 0.0,
                "raw_p_exit_1d": np.nan,
                "p_exit_1d": np.nan,
                "max_observation_date_used": pd.Timestamp("2024-01-10"),
                "state_source": "causal_hsmm",
            }
        ]
    )
    probability_status = pd.DataFrame(
        [{"state_label": "Stress", "horizon_days": 1, "probability_status": "ordinal_only"}]
    )

    ui, *_ = build_lifecycle_ui_frame(states, pd.DataFrame(), horizons=(1,), probability_status=probability_status)

    assert ui.loc[0, "exit_tendency_1d"] == "unavailable"
    assert ui.loc[0, "probability_status_1d"] == "tail_censored"
    assert not bool(ui.loc[0, "raw_score_used_1d"])
    assert ui.loc[0, "exit_tendency_basis_1d"] == "tail_censored_beyond_duration_support"
