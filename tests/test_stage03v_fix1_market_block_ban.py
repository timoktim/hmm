from __future__ import annotations

import pandas as pd

from src.evaluation.stage03v_calibration_readiness import (
    build_readiness_matrix,
    default_policy,
    validation_market_event_block_count,
)


def test_validation_market_event_block_count_lt_two_forbids_usable_probability() -> None:
    rows = []
    for day, positive_entities in enumerate([3, 0, 0]):
        trade_date = pd.Timestamp("2026-01-07") + pd.Timedelta(days=day)
        for entity_idx in range(10):
            rows.append(
                {
                    "entity_id": f"industry:{entity_idx}",
                    "trade_date": trade_date,
                    "horizon": 1,
                    "event_label": entity_idx < positive_entities,
                }
            )
    assert validation_market_event_block_count(pd.DataFrame(rows), event_share_threshold=0.20) == 1

    slice_row = {
        "asof_mode": "close_t_minus_1",
        "horizon": 1,
        "threshold_type": "fixed",
        "threshold_value": 0.05,
        "target_usage": "eligible",
        "calibration_method": "platt_logistic_calibration",
        "evaluation_row_count": 600,
        "positive_event_count": 30,
        "negative_event_count": 570,
        "expected_calibration_error": 0.01,
        "brier_score": 0.04,
        "brier_retention": 0.01,
        "roc_auc": 0.72,
        "average_precision": 0.22,
        "validation_market_event_block_count": 1,
        "fold_count": 1,
    }

    readiness = build_readiness_matrix([slice_row], [], policy=default_policy(), leakage_total=0)

    assert readiness[0]["readiness_category"] != "usable_probability_candidate"
    assert readiness[0]["readiness_reason"] == "market_event_block_evidence_below_minimum"
