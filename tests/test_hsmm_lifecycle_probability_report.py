from __future__ import annotations

from datetime import datetime

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_lifecycle_calibration import ui_readiness_matrix
from src.evaluation.hsmm_lifecycle_probability_report import _verdicts, generate_probability_report


def _seed_hsmm_states(storage: DuckDBStorage, run_id: str = "prob_report_run") -> None:
    rows = []
    dates = pd.bdate_range("2024-01-02", periods=18)
    for sector in ["S1", "S2"]:
        labels = ["Stress"] * 4 + ["Neutral"] * 5 + ["Trend"] * 4 + ["Repair"] * 5
        state_ids = [1] * 2 + [2] * 2 + [3] * 5 + [4] * 4 + [5] * 5
        for i, date in enumerate(dates):
            rows.append(
                {
                    "run_id": run_id,
                    "checkpoint_id": "c1",
                    "trade_date": date,
                    "sector_code": sector,
                    "sector_name": sector,
                    "state_id": state_ids[i],
                    "state_label": labels[i],
                    "state_probability": 0.8,
                    "state_phase": "middle",
                    "state_age_days": i + 1,
                    "state_age_days_by_id": i + 1,
                    "state_age_days_by_label": i + 1,
                    "model_state_age_days": i + 1,
                    "label_state_age_days": i + 1,
                    "duration_model_age_days": i + 1,
                    "display_state_age_days": i + 1,
                    "duration_percentile": 0.5,
                    "expected_remaining_days": 4.0,
                    "p_stay_1d": 0.7,
                    "p_stay_3d": 0.5,
                    "p_stay_5d": 0.4,
                    "p_stay_10d": 0.2,
                    "p_exit_1d": 0.3,
                    "p_exit_3d": 0.5,
                    "p_exit_5d": 0.6,
                    "p_exit_10d": 0.8,
                    "p_exit_20d": 0.9,
                    "raw_p_exit_1d": 0.3,
                    "raw_p_exit_3d": 0.5,
                    "raw_p_exit_5d": 0.6,
                    "raw_p_exit_10d": 0.8,
                    "raw_p_exit_20d": 0.9,
                    "calibrated_p_exit_1d": None,
                    "calibrated_p_exit_3d": None,
                    "calibrated_p_exit_5d": None,
                    "calibrated_p_exit_10d": None,
                    "calibrated_p_exit_20d": None,
                    "most_likely_next_state_id": state_ids[min(i + 1, len(state_ids) - 1)],
                    "most_likely_next_state_label": labels[min(i + 1, len(labels) - 1)],
                    "next_state_probability": 0.6,
                    "viterbi_score": -1.0,
                    "confidence": 0.8,
                    "train_start_date": dates[0],
                    "train_end_date": date,
                    "max_observation_date_used": date,
                    "state_source": "causal_hsmm",
                    "feature_scope_id": "all",
                    "decode_mode": "causal_prefix_viterbi",
                    "snapshot_frequency": "daily",
                    "created_at": datetime(2024, 1, 1),
                }
            )
    storage.upsert_df("hsmm_state_daily", pd.DataFrame(rows), ["run_id", "trade_date", "sector_code"])


def test_probability_report_writes_required_outputs(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_hsmm_states(storage)
    output = tmp_path / "probability_report"

    result = generate_probability_report(
        storage,
        "prob_report_run",
        output,
        horizons=(1, 3),
        exit_types=("state_id", "display_label"),
    )

    required = [
        "summary.md",
        "config.json",
        "exit_targets_sample.csv",
        "state_id_exit_calibration_summary.csv",
        "display_label_exit_calibration_summary.csv",
        "state_id_exit_calibration_buckets.csv",
        "display_label_exit_calibration_buckets.csv",
        "selected_exit_probability_status.csv",
        "selected_exit_probability_daily.csv",
        "transition_validation_summary.csv",
        "transition_validation_by_age_bucket.csv",
        "stress_display_label_lifecycle.csv",
        "stress_hidden_state_lifecycle.csv",
        "duration_hidden_vs_display.csv",
        "ui_readiness_matrix.csv",
        "known_limitations.md",
    ]
    for filename in required:
        assert (output / filename).exists(), filename

    summary = (output / "summary.md").read_text(encoding="utf-8")
    assert "Layered Verdict" in summary
    assert "display_readiness_verdict" in summary
    assert "must be hidden from formal UI" in summary
    assert result["verdicts"]["engineering_verdict"] == "EngineeringPass"


def test_all_invalid_probabilities_are_hidden_for_ui():
    selected = pd.DataFrame(
        [
            {
                "state_label": "Stress",
                "horizon_days": 5,
                "exit_type": "display_label",
                "selected_method": "none",
                "status": "invalid",
                "reason": "fails calibration",
            }
        ]
    )

    matrix = ui_readiness_matrix(selected)
    verdicts = _verdicts(selected, pd.DataFrame())

    assert bool(matrix.loc[0, "must_hide"])
    assert not bool(matrix.loc[0, "can_show_numeric_probability"])
    assert verdicts["display_readiness_verdict"] == "DisplayHidden"


def test_partial_usable_probability_only_allows_that_slice():
    selected = pd.DataFrame(
        [
            {
                "state_label": "Neutral",
                "horizon_days": 5,
                "exit_type": "display_label",
                "selected_method": "logistic",
                "status": "usable_probability",
                "reason": "improves raw",
            },
            {
                "state_label": "Stress",
                "horizon_days": 5,
                "exit_type": "display_label",
                "selected_method": "none",
                "status": "invalid",
                "reason": "fails calibration",
            },
        ]
    )

    matrix = ui_readiness_matrix(selected).sort_values("state_label").reset_index(drop=True)
    verdicts = _verdicts(selected, pd.DataFrame())

    assert bool(matrix[matrix["state_label"].eq("Neutral")]["can_show_numeric_probability"].iloc[0])
    assert bool(matrix[matrix["state_label"].eq("Stress")]["must_hide"].iloc[0])
    assert verdicts["calibration_verdict"] == "PartialLifecycleProbability"
    assert verdicts["display_readiness_verdict"] == "DisplayAllowedProbability"
