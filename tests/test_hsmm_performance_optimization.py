from __future__ import annotations

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models.hsmm_model import DiscreteDurationGaussianHSMM
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


FEATURES = ["f1", "f2"]
SNAPSHOT_COMPARE_FIELDS = [
    "state_id",
    "state_label",
    "model_state_age_days",
    "duration_model_age_days",
    "duration_percentile",
    "state_phase",
    "expected_remaining_days",
    "raw_p_exit_1d",
    "raw_p_exit_3d",
    "raw_p_exit_5d",
    "raw_p_exit_10d",
    "raw_p_exit_20d",
    "most_likely_next_state_id",
    "most_likely_next_state_label",
    "next_state_probability",
    "viterbi_score",
]


def _synthetic_sequence(sector_id: str, repeats: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(123)
    specs = [
        (4, np.array([-3.0, 0.0])),
        (7, np.array([0.0, 3.0])),
        (10, np.array([3.0, 0.0])),
        (5, np.array([0.0, -3.0])),
    ]
    rows = []
    date = pd.Timestamp("2024-01-01")
    for _ in range(repeats):
        for duration, mean in specs:
            for _ in range(duration):
                values = mean + rng.normal(0, 0.1, size=2)
                rows.append({"sector_id": sector_id, "trade_date": date, "f1": values[0], "f2": values[1]})
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def _seed_sector_ohlcv(storage: DuckDBStorage, sectors: int = 4, days: int = 72) -> None:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows = []
    for sector in range(sectors):
        close = 100.0 + sector
        for i, date in enumerate(dates):
            drift = 0.001 * ((sector % 2) * 2 - 1) + 0.002 * np.sin(i / 6 + sector)
            open_price = close * (1 + drift / 2)
            close = max(1.0, close * (1 + drift))
            rows.append(
                {
                    "sector_id": f"S{sector}",
                    "trade_date": date.date(),
                    "open": open_price,
                    "high": max(open_price, close) * 1.01,
                    "low": min(open_price, close) * 0.99,
                    "close": close,
                    "volume": 1000 + i,
                    "amount": 10000 + 10 * i + sector,
                    "pct_chg": drift,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-04-01"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def _assert_snapshot_equal(left: dict[str, object], right: dict[str, object]) -> None:
    for field in SNAPSHOT_COMPARE_FIELDS:
        assert field in left
        assert field in right
        if isinstance(left[field], str):
            assert left[field] == right[field]
        else:
            assert np.isclose(float(left[field]), float(right[field]), atol=1e-10, equal_nan=True), field


def test_prefix_endpoint_matches_legacy_lifecycle_snapshot():
    seq = _synthetic_sequence("A")
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=12, n_iter=3, random_state=4, engine="python")
    model.fit([seq, _synthetic_sequence("B")], FEATURES)
    snapshot_date = pd.Timestamp(seq["trade_date"].iloc[31])

    prefix = seq[pd.to_datetime(seq["trade_date"]) <= snapshot_date]
    legacy = model.lifecycle_snapshot(model.decode(prefix), snapshot_date)
    optimized = model.lifecycle_snapshots_from_sequence(seq, [snapshot_date])[0]

    _assert_snapshot_equal(legacy, optimized)


def test_prefix_endpoint_has_no_lookahead():
    seq = _synthetic_sequence("A")
    model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=12, n_iter=3, random_state=5, engine="python")
    model.fit([seq, _synthetic_sequence("B")], FEATURES)
    snapshot_date = pd.Timestamp(seq["trade_date"].iloc[25])

    baseline = model.lifecycle_snapshots_from_sequence(seq, [snapshot_date])[0]
    mutated = seq.copy()
    future_mask = pd.to_datetime(mutated["trade_date"]) > snapshot_date
    mutated.loc[future_mask, "f1"] = mutated.loc[future_mask, "f1"] * -50 + 100
    mutated.loc[future_mask, "f2"] = mutated.loc[future_mask, "f2"] * 50 - 100
    changed_future = model.lifecycle_snapshots_from_sequence(mutated, [snapshot_date])[0]

    _assert_snapshot_equal(baseline, changed_future)


def _run_small_walk_forward(tmp_path, run_id: str, mode: str, n_jobs: int | str = 1) -> pd.DataFrame:
    storage = DuckDBStorage(tmp_path / f"{run_id}.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    result = run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / f"{run_id}.duckdb"),
            start_date="2024-02-10",
            end_date="2024-03-05",
            n_states=4,
            max_duration=10,
            train_window_days=35,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=8,
            snapshot_frequency="daily",
            min_sequence_length=20,
            n_iter=1,
            snapshot_decode_mode=mode,
            hsmm_engine="python",
            n_jobs=n_jobs,
            sector_chunk_size=2,
            run_id=run_id,
        ),
        storage=storage,
    )
    return result["states"].sort_values(["sector_code", "trade_date"]).reset_index(drop=True)


def test_prefix_mode_matches_legacy_walk_forward(tmp_path):
    legacy = _run_small_walk_forward(tmp_path, "legacy_run", "legacy")
    prefix = _run_small_walk_forward(tmp_path, "prefix_run", "prefix")
    compare_cols = [
        "trade_date",
        "sector_code",
        "state_id",
        "state_label",
        "model_state_age_days",
        "duration_model_age_days",
        "display_state_age_days",
        "raw_p_exit_1d",
        "raw_p_exit_3d",
        "raw_p_exit_5d",
        "raw_p_exit_10d",
        "raw_p_exit_20d",
        "most_likely_next_state_id",
        "max_observation_date_used",
    ]

    pd.testing.assert_frame_equal(legacy[compare_cols], prefix[compare_cols], check_dtype=False)


def test_prefix_parallel_matches_single_job(tmp_path):
    single = _run_small_walk_forward(tmp_path, "prefix_single", "prefix", n_jobs=1)
    parallel = _run_small_walk_forward(tmp_path, "prefix_parallel", "prefix", n_jobs=2)
    compare_cols = [
        "trade_date",
        "sector_code",
        "state_id",
        "state_label",
        "model_state_age_days",
        "duration_model_age_days",
        "raw_p_exit_1d",
        "raw_p_exit_3d",
        "raw_p_exit_5d",
        "raw_p_exit_10d",
        "raw_p_exit_20d",
        "most_likely_next_state_id",
    ]

    pd.testing.assert_frame_equal(single[compare_cols], parallel[compare_cols], check_dtype=False)


def test_profile_only_does_not_write_hsmm_run_rows(tmp_path):
    storage = DuckDBStorage(tmp_path / "profile.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)

    result = run_hsmm_walk_forward(
        HSMMWalkForwardConfig(
            db_path=str(tmp_path / "profile.duckdb"),
            start_date="2024-02-10",
            end_date="2024-03-05",
            n_states=4,
            max_duration=10,
            train_window_days=35,
            train_frequency="every_n_trade_days",
            train_every_n_trade_days=8,
            snapshot_frequency="daily",
            min_sequence_length=20,
            n_iter=1,
            run_id="profile_only_run",
            profile_only=True,
        ),
        storage=storage,
    )

    assert result["profile"]["legacy_snapshot_decode_calls"] > result["profile"]["optimized_checkpoint_sector_decodes"]
    for table in ["hsmm_model_runs", "hsmm_model_checkpoints", "hsmm_state_daily", "hsmm_run_performance"]:
        count = storage.read_df(f"SELECT COUNT(*) AS n FROM {table} WHERE run_id = 'profile_only_run'")
        assert int(count.loc[0, "n"]) == 0

