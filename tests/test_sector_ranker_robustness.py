from __future__ import annotations

import pandas as pd

from src.scoring.sector_ranker import rank_sectors


def test_rank_sectors_handles_missing_feature_columns():
    df = pd.DataFrame(
        {
            "sector_id": ["A", "B"],
            "sector_name": ["甲", "乙"],
            "prob_trend_up": [0.7, 0.4],
            "prob_risk_off": [0.1, 0.2],
        }
    )

    out = rank_sectors(df)

    assert len(out) == 2
    assert {"sector_score", "sector_tag"}.issubset(out.columns)
    assert "market_adjusted_sector_score" not in out.columns
    assert out["sector_score"].notna().all()


def test_rank_sectors_handles_missing_probability_columns():
    df = pd.DataFrame({"sector_id": ["A", "B"], "rs_20d": [0.2, -0.1], "ret_20d": [0.1, 0.0]})

    out = rank_sectors(df)

    assert len(out) == 2
    assert out["prob_trend_up"].eq(0).all()
    assert out["prob_neutral"].eq(0).all()
    assert out["prob_risk_off"].eq(0).all()
