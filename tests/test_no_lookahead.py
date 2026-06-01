from __future__ import annotations

import pandas as pd
import pytest

from src.data_pipeline.calendar import assert_execution_after_signal


def test_execution_date_must_be_after_signal_date():
    df = pd.DataFrame({"signal_date": ["2024-01-02"], "exec_date": ["2024-01-03"]})
    assert_execution_after_signal(df)


def test_execution_date_equal_signal_date_fails():
    df = pd.DataFrame({"signal_date": ["2024-01-02"], "exec_date": ["2024-01-02"]})
    with pytest.raises(AssertionError):
        assert_execution_after_signal(df)

