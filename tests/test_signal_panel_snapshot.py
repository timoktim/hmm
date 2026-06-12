from __future__ import annotations

import numpy as np
import pandas as pd

from src.signals.signal_panel_snapshot import (
    CURRENT_STAGE03V_SCORE_SOURCE,
    INVALIDATED_SIGNAL_SOURCE_FORBIDDEN,
    NO_CURRENT_STAGE03V_SCORE_SOURCE,
    REQUIRED_SNAPSHOT_COLUMNS,
    Stage03VReadinessSummary,
    build_signal_panel_snapshot_from_frames,
    forbidden_output_columns,
    signal_source_paths,
    validate_snapshot_schema,
)


def _ohlcv(close_values: list[float], sector_id: str = "801010", sector_name: str = "农林牧渔") -> pd.DataFrame:
    dates = pd.date_range("2026-01-01", periods=len(close_values), freq="B")
    return pd.DataFrame(
        {
            "sector_id": sector_id,
            "sector_name": sector_name,
            "sector_type": "industry",
            "trade_date": dates,
            "open": close_values,
            "high": close_values,
            "low": close_values,
            "close": close_values,
            "volume": 1.0,
            "amount": 1.0,
        }
    )


def test_snapshot_builder_returns_required_schema_and_no_action_columns() -> None:
    snapshot = build_signal_panel_snapshot_from_frames(_ohlcv([100 + i for i in range(30)]))

    assert set(REQUIRED_SNAPSHOT_COLUMNS).issubset(snapshot.columns)
    assert validate_snapshot_schema(snapshot) == []
    assert snapshot["not_trading_output"].eq("yes").all()
    assert forbidden_output_columns(snapshot.columns) == []


def test_volatility_bands_use_only_rows_on_or_before_signal_date() -> None:
    base = _ohlcv([100 + i for i in range(30)])
    future = pd.DataFrame([base.iloc[-1].to_dict()])
    future["trade_date"] = pd.Timestamp("2026-03-31")
    future["close"] = 1000.0
    full = pd.concat([base, future], ignore_index=True)

    cutoff = base["trade_date"].max()
    with_future = build_signal_panel_snapshot_from_frames(full, signal_date=cutoff)
    without_future = build_signal_panel_snapshot_from_frames(base, signal_date=cutoff)

    assert with_future.loc[0, "signal_date"] == cutoff.date()
    assert np.isclose(with_future.loc[0, "vol_20d"], without_future.loc[0, "vol_20d"], equal_nan=True)


def test_downside_volatility_handles_zero_and_all_positive_windows() -> None:
    constant = _ohlcv([100.0] * 30, sector_id="801020", sector_name="采掘")
    positive = _ohlcv([100.0 + i for i in range(30)], sector_id="801030", sector_name="化工")
    snapshot = build_signal_panel_snapshot_from_frames(pd.concat([constant, positive], ignore_index=True))

    zero_row = snapshot[snapshot["sector_id"] == "801020"].iloc[0]
    positive_row = snapshot[snapshot["sector_id"] == "801030"].iloc[0]

    assert pd.isna(zero_row["downside_vol_share_20d"])
    assert positive_row["downside_vol_share_20d"] == 0.0
    assert positive_row["negative_return_day_share_20d"] == 0.0


def test_missing_hmm_and_hsmm_context_do_not_block_baseline_snapshot() -> None:
    snapshot = build_signal_panel_snapshot_from_frames(_ohlcv([100 + i for i in range(30)]))

    assert len(snapshot) == 1
    assert snapshot.loc[0, "volatility_signal_status"] == "available"
    assert snapshot.loc[0, "hmm_state_label"] == "unavailable"
    assert snapshot.loc[0, "hmm_state_source"] == "unavailable_causal_cache"
    assert snapshot.loc[0, "hsmm_state_phase"] == "unavailable"
    assert snapshot.loc[0, "hsmm_probability_display_policy"] == "unavailable_lifecycle_source"


def test_stage03v_probability_is_unavailable_without_current_per_entity_scores() -> None:
    snapshot = build_signal_panel_snapshot_from_frames(
        _ohlcv([100 + i for i in range(30)]),
        stage03v_readiness=Stage03VReadinessSummary(
            usable_probability_slice_count=5,
            ordinal_only_slice_count=27,
            baseline_only_slice_count=22,
            research_only_slice_count=66,
        ),
    )

    assert snapshot.loc[0, "stage03v_probability_source_status"] == NO_CURRENT_STAGE03V_SCORE_SOURCE
    assert snapshot.loc[0, "stage03v_probability_display_status"] == "hidden_no_current_per_entity_score_source"
    assert snapshot.loc[0, "stage03v_calibrated_probability_available"] == "no"
    assert pd.isna(snapshot.loc[0, "stage03v_calibrated_probability"])


def test_usable_probability_candidate_requires_current_score_source() -> None:
    scores = pd.DataFrame(
        [
            {
                "sector_id": "801010",
                "readiness_category": "usable_probability_candidate",
                "risk_ordinal": "high",
                "calibrated_probability": 0.72,
            }
        ]
    )
    snapshot = build_signal_panel_snapshot_from_frames(
        _ohlcv([100 + i for i in range(30)]),
        stage03v_readiness=Stage03VReadinessSummary(
            usable_probability_slice_count=5,
            probability_source_status=CURRENT_STAGE03V_SCORE_SOURCE,
        ),
        current_stage03v_scores=scores,
    )

    assert snapshot.loc[0, "stage03v_probability_source_status"] == CURRENT_STAGE03V_SCORE_SOURCE
    assert snapshot.loc[0, "stage03v_probability_display_status"] == "readiness_gated_numeric_probability_available"
    assert snapshot.loc[0, "stage03v_calibrated_probability_available"] == "yes"
    assert snapshot.loc[0, "stage03v_calibrated_probability"] == 0.72


def test_ordinal_only_candidate_never_exposes_numeric_probability() -> None:
    scores = pd.DataFrame(
        [
            {
                "sector_id": "801010",
                "readiness_category": "ordinal_only_candidate",
                "risk_ordinal": "extreme",
                "calibrated_probability": 0.91,
            }
        ]
    )
    snapshot = build_signal_panel_snapshot_from_frames(
        _ohlcv([100 + i for i in range(30)]),
        stage03v_readiness=Stage03VReadinessSummary(
            ordinal_only_slice_count=27,
            probability_source_status=CURRENT_STAGE03V_SCORE_SOURCE,
        ),
        current_stage03v_scores=scores,
    )

    assert snapshot.loc[0, "stage03v_probability_display_status"] == "ordinal_only_no_numeric_probability"
    assert snapshot.loc[0, "stage03v_risk_ordinal"] == "extreme"
    assert snapshot.loc[0, "stage03v_calibrated_probability_available"] == "no"
    assert pd.isna(snapshot.loc[0, "stage03v_calibrated_probability"])


def test_invalidated_artifacts_are_not_signal_sources() -> None:
    accepted_sources = "\n".join(signal_source_paths().values())

    for forbidden in INVALIDATED_SIGNAL_SOURCE_FORBIDDEN:
        assert forbidden not in accepted_sources
