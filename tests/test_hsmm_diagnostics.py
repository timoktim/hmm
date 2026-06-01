from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_diagnostics import _actual_exit_within, run_hsmm_diagnostics
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


def _seed_sector_ohlcv(storage: DuckDBStorage) -> None:
    dates = pd.date_range("2024-01-01", periods=75, freq="D")
    rows = []
    for sector in range(4):
        close = 100.0 + sector
        for i, date in enumerate(dates):
            drift = 0.001 * np.cos(i / 5 + sector)
            close *= 1 + drift
            rows.append(
                {
                    "sector_id": f"S{sector}",
                    "trade_date": date.date(),
                    "open": close * 0.999,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1000,
                    "amount": 10000 + i * 100 + sector,
                    "pct_chg": drift,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-03-20"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def test_hsmm_diagnostics_report_and_causality(tmp_path):
    db = tmp_path / "hsmm.duckdb"
    storage = DuckDBStorage(db)
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(db),
            start_date="2024-02-10",
            end_date="2024-03-10",
            n_states=4,
            max_duration=10,
            train_window_days=40,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=7,
            snapshot_frequency="daily",
            rebalance_days=7,
            min_sequence_length=20,
            n_iter=2,
            run_id="hsmm_diag_run",
        ),
        storage=storage,
    )

    output = tmp_path / "report"
    result = run_hsmm_diagnostics(str(db), "hsmm_diag_run", horizons=(1, 3, 5), output=output)

    assert (output / "summary.md").exists()
    assert (output / "causal_audit.csv").exists()
    assert (output / "coverage.csv").exists()
    assert (output / "churn_profile.csv").exists()
    audit = result["causality_audit"]
    assert audit["passed"].all()
    assert result["summary"]["conclusion"] in {
        "ValidLifecycleSignal",
        "PartialLifecycleSignal",
        "WeakLifecycleSignal",
        "InvalidDueToCausalLeakage",
        "InvalidDueToSparseSnapshots",
        "InvalidDueToCalibrationFailure",
    }


def test_actual_exit_within_uses_trading_rows_not_calendar_days():
    group = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2024-01-05"), pd.Timestamp("2024-01-08"), pd.Timestamp("2024-01-09")],
            "state_label": ["Stress", "Stress", "Repair"],
        }
    )

    assert _actual_exit_within(group, 0, 1) is False
    assert _actual_exit_within(group, 0, 2) is True
    assert _actual_exit_within(group, 1, 2) is None
