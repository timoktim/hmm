from __future__ import annotations

import pandas as pd

from src.models.state_labeler import label_states


def test_state_labeler_identifies_three_regimes():
    df = pd.DataFrame(
        {
            "state_id": [0, 0, 1, 1, 2, 2],
            "ret_20d": [0.12, 0.10, 0.00, 0.01, -0.10, -0.08],
            "rs_20d": [0.05, 0.04, 0.00, -0.01, -0.06, -0.05],
            "ma20_slope": [0.03, 0.04, 0.00, 0.00, -0.02, -0.03],
            "vol_20d": [0.08, 0.07, 0.05, 0.06, 0.18, 0.20],
            "drawdown_20d": [-0.03, -0.02, -0.04, -0.05, -0.20, -0.18],
        }
    )
    labels = label_states(df)
    assert labels[0] == "TrendUp"
    assert labels[1] == "Neutral"
    assert labels[2] == "RiskOff"

