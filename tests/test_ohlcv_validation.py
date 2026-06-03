from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.data_pipeline.validators import OhlcvValidationResult, validate_ohlcv


def _valid_frame() -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=3, freq="D")
    return pd.DataFrame(
        {
            "trade_date": dates.date,
            "open": [10.0, 10.5, 11.0],
            "high": [11.0, 11.2, 11.6],
            "low": [9.8, 10.1, 10.7],
            "close": [10.5, 11.0, 11.4],
            "volume": [1000.0, 1100.0, 1200.0],
            "amount": [10000.0, 11000.0, 12000.0],
        }
    )


def _assert_invalid(df: pd.DataFrame) -> None:
    with pytest.raises(ValueError):
        validate_ohlcv(df, "unit")


def test_normal_ohlcv_passes() -> None:
    result = validate_ohlcv(_valid_frame(), "unit")

    assert isinstance(result, OhlcvValidationResult)
    assert result.rows == 3
    assert result.warnings == []


def test_missing_column_fails() -> None:
    _assert_invalid(_valid_frame().drop(columns=["open"]))


def test_empty_frame_fails() -> None:
    _assert_invalid(_valid_frame().iloc[0:0])


def test_null_trade_date_fails() -> None:
    df = _valid_frame()
    df.loc[0, "trade_date"] = None

    _assert_invalid(df)


def test_duplicate_trade_date_fails() -> None:
    df = _valid_frame()
    df.loc[1, "trade_date"] = df.loc[0, "trade_date"]

    _assert_invalid(df)


def test_high_less_than_low_fails() -> None:
    df = _valid_frame()
    df.loc[0, "high"] = 9.0

    _assert_invalid(df)


def test_high_less_than_close_fails() -> None:
    df = _valid_frame()
    df.loc[0, "high"] = 10.0

    _assert_invalid(df)


def test_low_greater_than_open_fails() -> None:
    df = _valid_frame()
    df.loc[0, "low"] = 10.2

    _assert_invalid(df)


def test_close_non_positive_fails() -> None:
    df = _valid_frame()
    df.loc[0, "close"] = 0.0

    _assert_invalid(df)


def test_open_non_positive_fails() -> None:
    df = _valid_frame()
    df.loc[0, "open"] = 0.0

    _assert_invalid(df)


def test_negative_volume_fails() -> None:
    df = _valid_frame()
    df.loc[0, "volume"] = -1.0

    _assert_invalid(df)


def test_negative_amount_fails() -> None:
    df = _valid_frame()
    df.loc[0, "amount"] = -1.0

    _assert_invalid(df)


def test_inf_numeric_fails() -> None:
    df = _valid_frame()
    df.loc[0, "amount"] = np.inf

    _assert_invalid(df)


def test_large_gap_warns_by_default_and_fails_in_strict_mode() -> None:
    df = _valid_frame()
    df.loc[1, "open"] = 25.0
    df.loc[1, "high"] = 27.0
    df.loc[1, "low"] = 24.0
    df.loc[1, "close"] = 26.0

    result = validate_ohlcv(df, "gap")

    assert any("gap exceeds threshold" in warning for warning in result.warnings)
    with pytest.raises(ValueError):
        validate_ohlcv(df, "gap", strict=True)


def test_custom_basket_reduced_schema_passes() -> None:
    df = pd.DataFrame(
        {
            "trade_date": pd.date_range("2024-01-01", periods=2, freq="D").date,
            "close": [1000.0, 1010.0],
            "volume": [1000.0, 1100.0],
            "amount": [10000.0, 11000.0],
        }
    )

    result = validate_ohlcv(df, "custom", required_columns={"trade_date", "close"})

    assert result.rows == 2
    assert result.warnings == []
