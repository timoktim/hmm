from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation import signal_validation
from src.evaluation.signal_validation import (
    SignalValidationConfig,
    causality_audit,
    compute_tradable_forward_returns,
    evaluate_cross_sectional_ic,
    evaluate_state_forward_returns,
    run_signal_validation,
)


def test_tradable_forward_return_uses_next_open():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    ohlcv = pd.DataFrame(
        {
            "sector_id": "S",
            "trade_date": dates,
            "open": [100, 110, 120, 130, 140, 150],
            "close": [105, 121, 132, 143, 154, 165],
        }
    )

    out = compute_tradable_forward_returns(ohlcv, (1, 5))
    first = out.iloc[0]

    assert first["exec_date"] == dates[1]
    assert np.isclose(first["future_ret_open_1d"], 121 / 110 - 1)
    assert np.isclose(first["future_ret_open_5d"], 165 / 110 - 1)


def test_causality_audit_rejects_future_observation_and_in_sample():
    states = pd.DataFrame(
        [
            {
                "sector_id": "S",
                "trade_date": pd.Timestamp("2024-01-02"),
                "train_end": pd.Timestamp("2024-01-03"),
                "max_observation_date_used": pd.Timestamp("2024-01-02"),
                "state_source": "in_sample_display",
            }
        ]
    )
    trades = pd.DataFrame({"signal_date": [pd.Timestamp("2024-01-02")], "exec_date": [pd.Timestamp("2024-01-02")]})

    audit = causality_audit(states, trades)

    assert not audit["passed"].all()
    assert set(audit.loc[~audit["passed"], "check"]) >= {"state_source == causal_backtest", "train_end <= trade_date", "exec_date > signal_date"}


def test_cross_sectional_ic_is_calculated_by_date():
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2024-01-01")] * 3 + [pd.Timestamp("2024-01-02")] * 3,
            "score": [1, 2, 3, 1, 2, 3],
            "future_ret_open_1d": [0.01, 0.02, 0.03, 0.03, 0.02, 0.01],
        }
    )

    out = evaluate_cross_sectional_ic(frame, ["score"], (1,), min_cross_section=3)

    assert out.loc[0, "date_count"] == 2
    assert np.isclose(out.loc[0, "mean_ic"], 0.0)
    assert np.isclose(out.loc[0, "positive_ic_ratio"], 0.5)


def test_state_forward_bootstrap_uses_dates():
    frame = pd.DataFrame(
        {
            "trade_date": [pd.Timestamp("2024-01-01")] * 2 + [pd.Timestamp("2024-01-02")] * 2,
            "state_label": ["TrendUp", "RiskOff", "TrendUp", "RiskOff"],
            "future_ret_open_1d": [0.02, -0.01, 0.03, -0.02],
        }
    )

    summary, spreads = evaluate_state_forward_returns(frame, (1,), bootstrap_rounds=20, random_state=7)

    assert set(summary["state_label"]) == {"TrendUp", "RiskOff"}
    spread = spreads[spreads["comparison"].eq("TrendUp - RiskOff")].iloc[0]
    assert spread["mean_spread"] > 0
    assert pd.notna(spread["bootstrap_ci_low"])


def _seed_validation_ohlcv(storage: DuckDBStorage) -> pd.DatetimeIndex:
    dates = pd.date_range("2024-01-01", periods=45, freq="D")
    rows = []
    for sector_i in range(4):
        close = 100 + sector_i
        for i, date in enumerate(dates):
            close *= 1 + 0.001 * (sector_i + 1)
            rows.append(
                {
                    "sector_id": f"S{sector_i}",
                    "trade_date": date.date(),
                    "open": close * 0.99,
                    "high": close * 1.01,
                    "low": close * 0.98,
                    "close": close,
                    "volume": 1000,
                    "amount": 10000 + i,
                    "pct_chg": 0.0,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-02-15"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])
    return dates


def test_run_signal_validation_smoke(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "test.duckdb")
    storage.init_schema()
    dates = _seed_validation_ohlcv(storage)
    signal_dates = dates[25:35:5]

    states = pd.DataFrame(
        [
            {
                "sector_id": f"S{sector_i}",
                "trade_date": date,
                "state_id": 0,
                "state_label": "TrendUp" if sector_i >= 2 else "RiskOff",
                "prob_trend_up": 0.8 if sector_i >= 2 else 0.2,
                "prob_neutral": 0.1,
                "prob_risk_off": 0.1 if sector_i >= 2 else 0.7,
                "next_state_probs_json": "{}",
                "train_start": dates[0],
                "train_end": date,
                "max_observation_date_used": date,
                "probability_type": "filtered",
                "state_source": "causal_backtest",
            }
            for date in signal_dates
            for sector_i in range(4)
        ]
    )
    trades = pd.DataFrame({"signal_date": signal_dates, "exec_date": signal_dates + pd.Timedelta(days=1), "strategy": "model", "holdings": "S3"})
    curve_long = pd.DataFrame(
        {
            "trade_date": list(dates[26:36]) * 3,
            "strategy": ["model"] * 10 + ["baseline_1_rs20_top_n"] * 10 + ["baseline_2_equal_weight"] * 10,
            "net_return": [0.003] * 10 + [0.002] * 10 + [0.001] * 10,
            "gross_return": [0.003] * 10 + [0.002] * 10 + [0.001] * 10,
            "turnover": [0.1] * 30,
        }
    )
    comparison = pd.DataFrame(
        {
            "strategy": ["model", "baseline_1_rs20_top_n", "baseline_2_equal_weight"],
            "annual_return_net": [0.2, 0.1, 0.05],
            "max_drawdown_net": [-0.03, -0.04, -0.05],
            "sharpe_net": [1.2, 0.8, 0.5],
            "calmar_net": [4.0, 2.5, 1.0],
            "turnover": [1.0, 1.0, 0.2],
        }
    )

    def fake_backtest(**kwargs):
        return {
            "states": states,
            "trades": trades,
            "comparison": comparison,
            "curve": pd.DataFrame(),
            "curve_long": curve_long,
            "cache_hit": True,
            "run_id": "walk_forward:test",
        }

    monkeypatch.setattr(signal_validation, "run_sector_rotation_backtest", fake_backtest)
    report_dir = tmp_path / "report"
    out = run_signal_validation(
        SignalValidationConfig(
            db_path=str(tmp_path / "test.duckdb"),
            start_date="2024-01-20",
            end_date="2024-02-10",
            horizons=(1, 5),
            random_trials=3,
            bootstrap_rounds=20,
            min_cross_section=2,
            skip_robustness=True,
            report_dir=str(report_dir),
        )
    )

    assert (report_dir / "summary.md").exists()
    assert (report_dir / "signal_frame.csv").exists()
    assert not out["causality_audit"].empty
    assert out["summary"]["conclusion_level"] in {"Strong", "Moderate", "Weak", "No Evidence", "Invalid"}
