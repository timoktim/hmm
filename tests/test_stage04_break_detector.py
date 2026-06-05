from __future__ import annotations

import json
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

from src.evaluation import stage04_break_detector as detector


FORBIDDEN_TERMS = {
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
}


def _market_rows(days: int = 90, shock: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    close = [100.0]
    for i in range(1, days):
        ret = 0.001 + 0.0005 * np.sin(i / 3)
        if shock and i == days - 1:
            ret = -0.25
        close.append(close[-1] * (1.0 + ret))
    return pd.DataFrame(
        {
            "index_code": "000300",
            "trade_date": dates.date,
            "close": close,
        }
    )


def _breadth_rows(days: int = 90, shock: bool = False) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    up_ratio = [0.55 + 0.03 * np.sin(i / 4) for i in range(days)]
    above = [0.52 + 0.02 * np.cos(i / 5) for i in range(days)]
    amount = [0.1 * np.sin(i / 6) for i in range(days)]
    if shock:
        up_ratio[-1] = 0.08
        above[-1] = 0.10
        amount[-1] = 3.0
    return pd.DataFrame(
        {
            "trade_date": dates.date,
            "breadth_mode": "full_market",
            "up_ratio": up_ratio,
            "above_ma20_ratio": above,
            "amount_z_20d": amount,
            "coverage_ratio": 0.95,
            "effective_count": 4000,
            "expected_count": 4200,
        }
    )


def _write_table(db_path: Path, table_name: str, frame: pd.DataFrame) -> None:
    with duckdb.connect(str(db_path)) as con:
        con.register("incoming", frame)
        con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM incoming")


def test_causal_rolling_excludes_current_row() -> None:
    values = pd.Series([float(i) for i in range(20)] + [1000.0])

    z = detector.causal_rolling_zscore(values, rolling_window=20, min_periods=20)

    prior = np.array([float(i) for i in range(20)])
    expected = (1000.0 - prior.mean()) / prior.std(ddof=0)
    assert z.iloc[-1] == expected
    assert z.iloc[-1] > 100


def test_break_warning_high_when_volatility_and_breadth_stress(tmp_path: Path) -> None:
    db = tmp_path / "break.duckdb"
    _write_table(db, "market_index_ohlcv", _market_rows(shock=True))
    _write_table(db, "market_breadth_daily", _breadth_rows(shock=True))

    summary, result = detector.evaluate_break_detector(
        detector.BreakDetectorConfig(db_path=db, rolling_window=30, min_periods=10)
    )

    latest = result.iloc[-1]
    assert summary["status"] == "pass"
    assert latest["break_warning_level"] in {"elevated", "high"}
    assert latest["market_volatility_status"] == "high"
    assert latest["breadth_status"] == "high"


def test_insufficient_history_degrades_without_fake_score(tmp_path: Path) -> None:
    db = tmp_path / "short.duckdb"
    _write_table(db, "market_index_ohlcv", _market_rows(days=5))

    summary, result = detector.evaluate_break_detector(
        detector.BreakDetectorConfig(db_path=db, rolling_window=60, min_periods=20)
    )

    assert summary["status"] == "blocked"
    assert set(result["break_warning_level"]) == {"insufficient_data"}
    assert result["market_volatility_z"].isna().all()
    assert summary["latest_break_warning"]["market_volatility_z"] is None


def test_sector_dispersion_component_from_sector_features(tmp_path: Path) -> None:
    dates = pd.date_range("2024-01-01", periods=80, freq="D")
    sectors = [f"industry:{i}" for i in range(6)]
    rows = []
    for day_index, date in enumerate(dates):
        for sector_index, sector_id in enumerate(sectors):
            ret = 0.001 * np.sin(day_index / 4 + sector_index)
            if day_index == len(dates) - 1:
                ret = (sector_index - 2.5) * 0.04
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": date.date(),
                    "ret_1d": ret,
                    "ret_5d": ret * 2,
                    "rs_20d": ret * 3,
                    "drawdown_20d": -abs(ret),
                }
            )
    db = tmp_path / "sector.duckdb"
    _write_table(db, "market_index_ohlcv", _market_rows(days=80))
    _write_table(db, "sector_features", pd.DataFrame(rows))

    summary, result = detector.evaluate_break_detector(
        detector.BreakDetectorConfig(db_path=db, rolling_window=30, min_periods=10)
    )

    latest = result.iloc[-1]
    assert pd.notna(latest["sector_dispersion_z"])
    assert latest["sector_dispersion_status"] == "high"
    assert latest["break_warning_level"] in {"elevated", "high"}
    assert summary["component_availability_summary"]["sector_dispersion"]["available"] is True


def test_hmm_confidence_component_respects_causality() -> None:
    frame = pd.DataFrame(
        [
            {
                "sector_id": "industry:a",
                "trade_date": pd.Timestamp("2024-01-10").date(),
                "prob_trend_up": 0.40,
                "prob_neutral": 0.35,
                "prob_risk_off": 0.25,
                "max_observation_date_used": pd.Timestamp("2024-01-10").date(),
            },
            {
                "sector_id": "industry:b",
                "trade_date": pd.Timestamp("2024-01-10").date(),
                "prob_trend_up": 0.99,
                "prob_neutral": 0.005,
                "prob_risk_off": 0.005,
                "max_observation_date_used": pd.Timestamp("2024-01-11").date(),
            },
        ]
    )

    component, sanity = detector.build_hmm_confidence_component(frame, rolling_window=2, min_periods=1)

    assert sanity["future_leaking_rows_excluded"] == 1
    assert len(component) == 1
    assert component.loc[0, "hmm_sector_count"] == 1
    assert component.loc[0, "hmm_max_prob_mean"] == 0.40


def test_no_decision_or_trade_terms_in_report(tmp_path: Path) -> None:
    db = tmp_path / "report.duckdb"
    _write_table(db, "market_index_ohlcv", _market_rows(shock=True))
    _write_table(db, "market_breadth_daily", _breadth_rows(shock=True))
    summary, result = detector.evaluate_break_detector(
        detector.BreakDetectorConfig(db_path=db, rolling_window=30, min_periods=10)
    )
    markdown = detector.render_markdown(summary, result)
    payload = json.dumps(summary, ensure_ascii=False) + markdown

    assert not (FORBIDDEN_TERMS & set(term for term in FORBIDDEN_TERMS if term in payload))


def test_cli_no_fetch_without_db_blocks_cleanly(tmp_path: Path) -> None:
    output = tmp_path / "blocked.md"
    summary_json = tmp_path / "blocked.json"
    sample_csv = tmp_path / "blocked.csv"

    status = detector.main(
        [
            "--db",
            str(tmp_path / "missing.duckdb"),
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--sample-csv",
            str(sample_csv),
            "--no-fetch",
        ]
    )

    assert status == 0
    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert summary["status"] == "blocked"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert output.exists()
    assert sample_csv.exists()


def test_script_or_module_public_path_hygiene(tmp_path: Path) -> None:
    output = tmp_path / "path_hygiene.md"
    summary_json = tmp_path / "path_hygiene.json"
    sample_csv = tmp_path / "path_hygiene.csv"

    detector.main(
        [
            "--db",
            str(tmp_path / "missing.duckdb"),
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--sample-csv",
            str(sample_csv),
            "--no-fetch",
        ]
    )
    combined = output.read_text(encoding="utf-8") + summary_json.read_text(encoding="utf-8")

    assert "/Users/" not in combined
    assert "/private/" not in combined
