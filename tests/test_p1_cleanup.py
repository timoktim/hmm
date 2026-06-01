from __future__ import annotations

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.features.sector_features import add_sector_features
from src.scoring.sector_ranker import rank_sectors


def test_sector_ranker_uses_market_regime_only_as_external_risk_hint():
    df = pd.DataFrame(
        {
            "sector_id": ["A", "B"],
            "prob_trend_up": [0.8, 0.4],
            "prob_neutral": [0.1, 0.4],
            "prob_risk_off": [0.1, 0.2],
            "rs_20d": [0.2, -0.1],
            "ret_20d": [0.1, 0.0],
            "amount_z_20d": [1.0, 0.0],
            "vol_20d": [0.1, 0.1],
        }
    )

    ranked = rank_sectors(df, market_state_label="RiskOff")

    assert "market_multiplier" not in ranked.columns
    assert "market_adjusted_sector_score" not in ranked.columns
    assert ranked.iloc[0]["sector_id"] == "A"


def test_sector_features_do_not_emit_unfilled_structure_placeholders():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    df = pd.DataFrame(
        {
            "sector_id": "S",
            "trade_date": dates,
            "open": range(100, 130),
            "high": range(101, 131),
            "low": range(99, 129),
            "close": range(100, 130),
            "volume": 1000,
            "amount": range(1000, 1030),
            "pct_chg": 0,
            "turnover": 0,
        }
    )

    out = add_sector_features(df, apply_winsorize=False)

    assert {"gap_1d", "intraday_ret", "amount_shock_z"}.issubset(out.columns)
    assert "limit_up_ratio" not in out.columns
    assert "limit_down_ratio" not in out.columns
    assert "suspended_or_missing_ratio" not in out.columns
    assert "effective_member_count" not in out.columns


def test_stock_scores_not_created_for_new_schema(tmp_path):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()

    tables = storage.read_df("SHOW TABLES")

    assert "stock_scores" not in set(tables["name"])
