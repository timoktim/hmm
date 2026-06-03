from __future__ import annotations

import json

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_diagnostics import (
    _summary_conclusion,
    causality_audit,
    coverage_snapshot,
    coverage_v2_reports,
    hmm_vs_hsmm_lifecycle_comparison,
    stress_lifecycle_profile,
    state_age_stability,
)
from src.evaluation.hsmm_exit_calibration import (
    apply_exit_calibrator,
    build_exit_calibration_dataset,
    fit_empirical_exit_calibrator,
    summarize_exit_calibration,
)
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


def _seed_sector_ohlcv(storage: DuckDBStorage, sectors: int = 4, days: int = 65) -> None:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows = []
    for sector in range(sectors):
        close = 100.0 + sector
        for i, date in enumerate(dates):
            drift = 0.001 * ((sector % 2) * 2 - 1) + 0.002 * np.sin(i / 6 + sector)
            close *= 1 + drift
            rows.append(
                {
                    "sector_id": f"S{sector}",
                    "trade_date": date.date(),
                    "open": close * 0.999,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "volume": 1000 + i,
                    "amount": 10000 + i * 10 + sector,
                    "pct_chg": drift,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-03-20"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def _run_df(run_id: str = "r") -> pd.DataFrame:
    payload = {"run_id": run_id}
    return pd.DataFrame(
        [
            {
                "run_id": run_id,
                "snapshot_frequency": "daily",
                "start_date": pd.Timestamp("2024-01-01"),
                "end_date": pd.Timestamp("2024-01-03"),
                "feature_columns_json": json.dumps(["ret_1d"]),
                "config_json": json.dumps(payload, sort_keys=True),
                "config_hash": "bad-for-unit-test",
            }
        ]
    )


def test_same_run_id_rerun_clears_stale_hsmm_rows(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)

    base = {
        "db_path": str(tmp_path / "hsmm.duckdb"),
        "start_date": "2024-02-05",
        "n_states": 4,
        "max_duration": 10,
        "train_window_days": 35,
        "train_frequency": "every_n_trade_days",
        "train_every_n_trade_days": 7,
        "snapshot_frequency": "daily",
        "min_sequence_length": 20,
        "n_iter": 1,
        "run_id": "same_run",
    }
    run_hsmm_walk_forward(HSMMWalkForwardConfig(**base, end_date="2024-02-25"), storage=storage)
    run_hsmm_walk_forward(HSMMWalkForwardConfig(**base, end_date="2024-02-18", overwrite=True), storage=storage)

    latest = storage.read_df("SELECT max(trade_date) AS max_date FROM hsmm_state_daily WHERE run_id = 'same_run'")
    assert pd.Timestamp(latest.loc[0, "max_date"]) == pd.Timestamp("2024-02-18")
    run = storage.read_df("SELECT clean_run FROM hsmm_model_runs WHERE run_id = 'same_run'")
    assert bool(run.loc[0, "clean_run"])


def test_hsmm_coverage_audit_uses_ohlcv_expected_scope():
    run = _run_df()
    ohlcv = pd.DataFrame(
        {
            "sector_id": ["A", "A", "B", "B"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-01", "2024-01-02"]),
            "close": [1, 2, 3, 4],
        }
    )
    states = pd.DataFrame(
        {
            "run_id": ["r", "r"],
            "sector_code": ["A", "A"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        }
    )

    coverage = coverage_snapshot(run, states, ohlcv)

    assert not bool(coverage.loc[0, "coverage_passed"])
    assert int(coverage.loc[0, "expected_sector_count"]) == 2
    assert int(coverage.loc[0, "missing_sector_count"]) == 1


def test_hsmm_coverage_audit_detects_missing_full_trade_date():
    run = _run_df()
    ohlcv = pd.DataFrame(
        {
            "sector_id": ["A", "A", "A"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "close": [1, 2, 3],
        }
    )
    states = pd.DataFrame(
        {
            "run_id": ["r", "r"],
            "sector_code": ["A", "A"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-03"]),
        }
    )

    coverage = coverage_snapshot(run, states, ohlcv)

    assert not bool(coverage.loc[0, "daily_snapshot_complete"])
    assert int(coverage.loc[0, "missing_trade_date_count"]) == 1
    assert "2024-01-02" in coverage.loc[0, "missing_trade_dates_sample"]


def test_hsmm_causality_audit_flags_future_checkpoint():
    run = _run_df()
    states = pd.DataFrame(
        {
            "run_id": ["r"],
            "checkpoint_id": ["ckpt"],
            "trade_date": pd.to_datetime(["2024-01-02"]),
            "sector_code": ["A"],
            "state_source": ["causal_hsmm"],
            "train_start_date": pd.to_datetime(["2024-01-01"]),
            "train_end_date": pd.to_datetime(["2024-01-02"]),
            "max_observation_date_used": pd.to_datetime(["2024-01-02"]),
            "decode_mode": ["causal_prefix_viterbi"],
        }
    )
    checkpoints = pd.DataFrame(
        {
            "checkpoint_id": ["ckpt"],
            "train_date": pd.to_datetime(["2024-01-03"]),
            "train_end_date": pd.to_datetime(["2024-01-03"]),
        }
    )

    audit = causality_audit(run, states, pd.DataFrame(), checkpoints, expected_trade_dates=pd.to_datetime(["2024-01-02"]))

    failed = set(audit.loc[~audit["passed"], "check"])
    assert "checkpoint_train_date_lte_state_trade_date" in failed
    assert "checkpoint_train_end_date_lte_state_trade_date" in failed


def test_hsmm_causality_audit_flags_missing_checkpoint_and_duplicate_state_keys():
    run = _run_df()
    states = pd.DataFrame(
        {
            "run_id": ["r", "r"],
            "checkpoint_id": ["missing", "missing"],
            "trade_date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "sector_code": ["A", "A"],
            "state_source": ["causal_hsmm", "causal_hsmm"],
            "train_start_date": pd.to_datetime(["2024-01-01", "2024-01-01"]),
            "train_end_date": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "max_observation_date_used": pd.to_datetime(["2024-01-02", "2024-01-02"]),
            "decode_mode": ["causal_prefix_viterbi", "causal_prefix_viterbi"],
        }
    )

    audit = causality_audit(run, states, pd.DataFrame(), pd.DataFrame(), expected_trade_dates=pd.to_datetime(["2024-01-02"]))
    failed = set(audit.loc[~audit["passed"], "check"])

    assert "checkpoint_exists_for_every_state" in failed
    assert "no_duplicate_state_keys" in failed


def test_state_age_stability_flags_same_label_reset():
    states = pd.DataFrame(
        {
            "sector_code": ["A", "A", "A"],
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
            "checkpoint_id": ["c1", "c1", "c2"],
            "state_label": ["Trend", "Trend", "Trend"],
            "state_age_days": [1, 2, 1],
        }
    )

    stability = state_age_stability(states)
    aggregate = stability[stability["row_type"].eq("aggregate")].iloc[0]

    assert int(aggregate["same_label_age_reset_count"]) == 1
    assert not bool(aggregate["passed"])


def test_hsmm_same_label_age_reset_downgrades_verdict():
    audit = pd.DataFrame({"check": ["ok"], "passed": [True], "severity": ["error"]})
    coverage = pd.DataFrame(
        {
            "coverage_passed": [True],
            "stored_rows": [200],
            "actual_sector_count": [4],
            "actual_trade_day_count": [50],
        }
    )
    stability = pd.DataFrame({"row_type": ["aggregate"], "passed": [False], "same_label_age_reset_rate": [0.2]})

    verdict, text = _summary_conclusion(audit, coverage, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), stability)

    assert verdict == "InvalidDueToAgeInstability"
    assert "年龄" in text


def test_hsmm_label_age_continues_across_checkpoint_when_label_unchanged(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)

    result = run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / "hsmm.duckdb"),
            start_date="2024-02-05",
            end_date="2024-02-20",
            n_states=4,
            max_duration=10,
            train_window_days=35,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=5,
            snapshot_frequency="daily",
            min_sequence_length=20,
            n_iter=1,
            run_id="age_stitch",
        ),
        storage=storage,
    )
    states = result["states"].sort_values(["sector_code", "trade_date"])
    for _, group in states.groupby("sector_code"):
        same_label = group["state_label"].astype(str).eq(group["state_label"].astype(str).shift(1))
        age = pd.to_numeric(group["state_age_days_by_label"], errors="coerce")
        assert not ((same_label) & (age < age.shift(1))).any()
        display_age = pd.to_numeric(group["display_state_age_days"], errors="coerce")
        model_age = pd.to_numeric(group["model_state_age_days"], errors="coerce")
        assert display_age.notna().all()
        assert model_age.notna().all()
    assert result["states"]["duration_model_age_days"].notna().all()
    assert result["states"]["raw_p_exit_20d"].notna().any()
    assert result["states"]["calibrated_p_exit_20d"].isna().all()


def test_hsmm_episodes_mark_left_and_right_censoring(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / "hsmm.duckdb"),
            start_date="2024-02-05",
            end_date="2024-02-15",
            n_states=4,
            max_duration=10,
            train_window_days=35,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=5,
            snapshot_frequency="daily",
            min_sequence_length=20,
            n_iter=1,
            run_id="censor_test",
        ),
        storage=storage,
    )
    episodes = storage.read_df("SELECT * FROM hsmm_state_episodes WHERE run_id = 'censor_test'")
    assert episodes["is_left_censored"].fillna(False).any()
    assert episodes["is_right_censored"].fillna(False).any()
    assert "starts_at_run_boundary" in set(episodes["left_censor_reason"].dropna())
    assert "open_at_run_end" in set(episodes["right_censor_reason"].dropna())


def test_coverage_v2_does_not_fail_raw_insufficient_history():
    run = _run_df()
    run["config_json"] = json.dumps({"min_sequence_length": 20, "train_window_days": 60, "feature_version": "v1"})
    dates = pd.date_range("2023-12-01", periods=40, freq="D")
    rows = []
    for sector_id, sector_dates in {"A": dates, "B": dates[-5:]}.items():
        close = 100.0
        for date in sector_dates:
            close *= 1.001
            rows.append(
                {
                    "sector_id": sector_id,
                    "trade_date": date,
                    "open": close * 0.999,
                    "high": close * 1.01,
                    "low": close * 0.99,
                    "close": close,
                    "amount": 1000,
                }
            )
    ohlcv = pd.DataFrame(rows)
    states = pd.DataFrame(
        {
            "run_id": ["r"] * 3,
            "sector_code": ["A"] * 3,
            "trade_date": pd.to_datetime(["2024-01-01", "2024-01-02", "2024-01-03"]),
        }
    )
    checkpoints = pd.DataFrame({"train_date": [pd.Timestamp("2024-01-01")], "checkpoint_id": ["c1"]})

    reports = coverage_v2_reports(run, states, checkpoints, ohlcv)
    missing = reports["coverage_missing_reason"]
    summary = reports["coverage_summary"]

    assert "insufficient_history" in set(missing["missing_reason"])
    verdict_row = summary[summary["coverage_layer"].eq("verdict_coverage")].iloc[0]
    assert "coverage_passed" in verdict_row


def test_stress_lifecycle_has_predicted_and_realized_distributions():
    dates = pd.date_range("2024-01-01", periods=6, freq="D")
    states = pd.DataFrame(
        {
            "sector_code": ["A"] * 6,
            "trade_date": dates,
            "state_label": ["Stress", "Stress", "Stress", "Neutral", "Neutral", "Trend"],
            "most_likely_next_state_label": ["Neutral"] * 6,
            "display_state_age_days": [1, 2, 3, 1, 2, 1],
        }
    )
    ohlcv = pd.DataFrame(
        {
            "sector_id": ["A"] * 6,
            "trade_date": dates,
            "close": [100, 99, 98, 99, 100, 102],
        }
    )
    episodes = pd.DataFrame(
        {
            "sector_code": ["A", "A", "A"],
            "state_label": ["Stress", "Neutral", "Trend"],
            "start_date": pd.to_datetime(["2024-01-01", "2024-01-04", "2024-01-06"]),
            "end_date": pd.to_datetime(["2024-01-03", "2024-01-05", "2024-01-06"]),
            "next_state_label": ["Neutral", "Trend", None],
        }
    )

    out = stress_lifecycle_profile(states, ohlcv, horizons=(1, 3, 5), episodes=episodes)

    assert "predicted_next_state_distribution" in out.columns
    assert "realized_next_state_distribution" in out.columns
    assert "Neutral" in out.iloc[0]["realized_next_state_distribution"]


def test_hmm_comparison_skips_without_cache_key(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm.duckdb")
    storage.init_schema()
    run = _run_df("r")
    episodes = pd.DataFrame(
        {
            "run_id": ["r"],
            "sector_code": ["A"],
            "state_label": ["Trend"],
            "duration_trading_days": [3],
            "duration_days": [3],
            "is_left_censored": [False],
            "is_right_censored": [False],
        }
    )

    out = hmm_vs_hsmm_lifecycle_comparison(storage, "r", episodes, run, hmm_cache_key=None)

    assert "skipped_no_matched_hmm_cache" in set(out["comparison_status"].dropna())


def test_exit_calibrator_outputs_raw_and_calibrated_probabilities():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    states = pd.DataFrame(
        {
            "sector_code": ["A"] * len(dates),
            "trade_date": dates,
            "state_id": [1] * 10 + [2] * 10 + [1] * 10,
            "state_label": ["Trend"] * 10 + ["Stress"] * 10 + ["Trend"] * 10,
            "state_phase": ["early"] * len(dates),
            "state_age_days": list(range(1, 11)) * 3,
            "duration_percentile": np.linspace(0.05, 0.95, len(dates)),
            "p_exit_1d": [0.1] * 9 + [0.9] + [0.1] * 9 + [0.9] + [0.1] * 9 + [0.9],
        }
    )

    dataset = build_exit_calibration_dataset(states, horizons=(1,))
    calibrator = fit_empirical_exit_calibrator(dataset, min_bucket_count=1, train_end_date="2024-01-20")
    calibrated = apply_exit_calibrator(dataset, calibrator)
    raw_summary = summarize_exit_calibration(dataset, "raw_p_exit", "raw")
    calibrated_summary = summarize_exit_calibration(calibrated, "calibrated_p_exit", "calibrated")

    assert calibrator.metadata["usable_probability"] is True
    assert "calibrated_p_exit" in calibrated.columns
    assert calibrated["calibrated_p_exit"].between(0, 1).all()
    assert set(raw_summary["probability_type"]) == {"raw"}
    assert set(calibrated_summary["probability_type"]) == {"calibrated"}


def _small_exit_calibration_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "sector_code": ["A"] * 8,
            "trade_date": pd.date_range("2024-01-01", periods=8, freq="D"),
            "state_label": ["Trend"] * 8,
            "state_phase": ["early"] * 8,
            "state_age_days": [1, 2, 3, 4, 5, 6, 7, 8],
            "duration_percentile": [0.1] * 8,
            "horizon_days": [1] * 8,
            "raw_p_exit": [0.2] * 8,
            "actual_exit_within_h_trading_days": [False, False, True, False, True, True, True, True],
        }
    )


def test_exit_calibrator_excludes_horizon_crossing_train_end_date():
    df = _small_exit_calibration_frame()

    calibrator = fit_empirical_exit_calibrator(df, min_bucket_count=20, train_end_date="2024-01-04")
    out = apply_exit_calibrator(df[df["trade_date"] > pd.Timestamp("2024-01-04")], calibrator)

    assert calibrator.metadata["training_rows"] == 3
    assert calibrator.metadata["train_end"] == "2024-01-03"
    assert calibrator.metadata["excluded_post_train_horizon_count"] == 5
    assert calibrator.metadata["calibration_status"] == "usable"
    assert out["calibrated_p_exit"].notna().all()
    assert out["calibrated_p_exit"].between(0, 1).all()
    assert out["probability_status"].eq("usable_probability").all()


def test_exit_calibrator_backs_off_small_buckets_when_horizon_inside_cutoff():
    df = _small_exit_calibration_frame()

    calibrator = fit_empirical_exit_calibrator(df, min_bucket_count=20, train_end_date="2024-01-05")
    out = apply_exit_calibrator(df[df["trade_date"] > pd.Timestamp("2024-01-05")], calibrator)

    assert calibrator.metadata["training_rows"] == 4
    assert calibrator.metadata["train_end"] == "2024-01-04"
    assert calibrator.metadata["calibration_status"] == "usable"
    assert calibrator.specific.empty
    assert not calibrator.global_rate.empty
    assert out["calibrated_p_exit"].notna().all()
    assert out["calibrated_p_exit"].between(0, 1).all()
    assert out["probability_status"].eq("usable_probability").all()


def test_exit_calibrator_allow_in_sample_is_explicit_research_only():
    df = _small_exit_calibration_frame()

    calibrator = fit_empirical_exit_calibrator(df, min_bucket_count=20, allow_in_sample=True)
    out = apply_exit_calibrator(df, calibrator)

    assert calibrator.metadata["allow_in_sample"] is True
    assert calibrator.metadata["training_rows"] == 8
    assert calibrator.metadata["calibration_status"] == "exploratory"
    assert calibrator.metadata["readiness_status"] == "research_only"
    assert calibrator.metadata["usable_probability"] is False
    assert out["calibrated_p_exit"].isna().all()
    assert out["probability_status"].eq("raw_only").all()
    assert out["readiness_status"].eq("research_only").all()
