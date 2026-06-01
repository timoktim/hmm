from __future__ import annotations

import pandas as pd

from src.evaluation.hsmm_transition_validation import build_display_label_episodes, validate_transitions


def _transition_states() -> pd.DataFrame:
    rows = []
    date = pd.Timestamp("2024-01-01")
    for sector in range(8):
        labels = ["Stress", "Stress", "Neutral", "Neutral", "Stress", "Stress", "Neutral", "Neutral"]
        predictions = ["Trend"] * len(labels)
        for i, label in enumerate(labels):
            rows.append(
                {
                    "run_id": "r",
                    "sector_code": f"S{sector}",
                    "trade_date": date + pd.Timedelta(days=i + sector * 20),
                    "state_id": i % 3,
                    "state_label": label,
                    "display_state_age_days": 1,
                    "most_likely_next_state_label": predictions[i],
                }
            )
    return pd.DataFrame(rows)


def test_realized_next_label_comes_from_actual_episode_not_prediction():
    episodes = build_display_label_episodes(_transition_states())
    first_complete = episodes[episodes["is_right_censored"] == False].iloc[0]  # noqa: E712

    assert first_complete["state_label"] == "Stress"
    assert first_complete["next_state_label"] == "Neutral"
    assert first_complete["predicted_next_state_label"] == "Trend"


def test_model_prediction_weak_than_baseline_falls_back():
    result = validate_transitions(_transition_states(), min_sample=2, advantage=0.02)
    summary = result["summary"]
    stress = summary[summary["state_label"].eq("Stress")].iloc[0]

    assert stress["status"] in {"empirical_baseline_only", "hidden"}
    assert stress["best_baseline_accuracy"] >= stress["model_top1_accuracy"]

