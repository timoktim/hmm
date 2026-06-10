from __future__ import annotations

import pandas as pd

from src.ui.lifecycle_page import _format_metric_date, _load_lifecycle_latest_daily, _load_sector_trajectory


class RecordingStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[object]]] = []

    def read_df(self, sql: str, params: list[object] | None = None) -> pd.DataFrame:
        self.calls.append((sql, params or []))
        if "MAX(profile_cutoff_date)" in sql and "MAX(trade_date)" not in sql:
            return pd.DataFrame({"profile_cutoff_date": [pd.Timestamp("2026-05-28")]})
        if "MAX(trade_date)" in sql:
            return pd.DataFrame(
                {
                    "run_id": ["r", "r"],
                    "profile_mode": ["latest_asof", "latest_asof"],
                    "state_date_policy": ["full_run", "full_run"],
                    "profile_cutoff_date": [pd.Timestamp("2026-05-28"), pd.Timestamp("2026-05-28")],
                    "trade_date": [pd.Timestamp("2026-05-28"), pd.Timestamp("2026-05-28")],
                    "sector_code": ["S1", "S2"],
                    "state_label": ["Trend", "Stress"],
                }
            )
        if "LIMIT ?" in sql:
            return pd.DataFrame(
                {
                    "trade_date": pd.bdate_range("2026-05-01", periods=3),
                    "sector_code": ["S1"] * 3,
                    "state_label": ["Trend"] * 3,
                }
            )
        return pd.DataFrame()


def test_lifecycle_latest_query_reads_only_latest_trade_date():
    storage = RecordingStorage()

    df = _load_lifecycle_latest_daily(storage, "r", "latest_asof", "full_run")

    assert len(df) == 2
    sql = storage.calls[-1][0]
    assert "trade_date = (" in sql
    assert "MAX(trade_date)" in sql
    assert "ORDER BY trade_date" not in sql
    assert "raw_p_exit" not in sql
    assert "calibrated_p_exit" not in sql


def test_sector_trajectory_query_is_sector_scoped_and_limited():
    storage = RecordingStorage()

    _load_sector_trajectory(storage, "r", "S1", "latest_asof", "full_run", "2026-05-28", 60)

    sql, params = storage.calls[-1]
    assert "sector_code = ?" in sql
    assert "LIMIT ?" in sql
    assert params[-2:] == ["S1", 60]


def test_metric_date_formatter_returns_streamlit_safe_strings():
    assert _format_metric_date(pd.Timestamp("2026-06-09")) == "2026-06-09"
    assert _format_metric_date(pd.Timestamp("2026-06-09").date()) == "2026-06-09"
    assert _format_metric_date(pd.NaT) == "无"
