from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models import hsmm_walk_forward
from src.models.hsmm_model import DiscreteDurationGaussianHSMM
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward, write_hsmm_performance_profile


FEATURES = ["f1", "f2"]
FORBIDDEN_PUBLIC_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]


def _synthetic_sequence(sector_id: str, seed: int, repeats: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    specs = [
        (4, np.array([-3.0, 0.0])),
        (7, np.array([0.0, 3.0])),
        (9, np.array([3.0, 0.0])),
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


def _synthetic_sequences(count: int = 6) -> list[pd.DataFrame]:
    return [_synthetic_sequence(f"S{idx}", 100 + idx) for idx in range(count)]


def _seed_sector_ohlcv(storage: DuckDBStorage, sectors: int = 4, days: int = 72) -> None:
    dates = pd.date_range("2024-01-01", periods=days, freq="D")
    rows = []
    for sector in range(sectors):
        close = 100.0 + sector
        for idx, date in enumerate(dates):
            drift = 0.001 * ((sector % 2) * 2 - 1) + 0.002 * np.sin(idx / 6 + sector)
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
                    "volume": 1000 + idx,
                    "amount": 10000 + 10 * idx + sector,
                    "pct_chg": drift,
                    "turnover": 1.0,
                    "source": "test",
                    "fetched_at": pd.Timestamp("2024-04-01"),
                }
            )
    storage.upsert_df("sector_ohlcv", pd.DataFrame(rows), ["sector_id", "trade_date"])


def _small_walk_forward_config(tmp_path: Path, **overrides: object) -> HSMMWalkForwardConfig:
    payload: dict[str, object] = {
        "db_path": str(tmp_path / "hsmm_perf.duckdb"),
        "start_date": "2024-02-10",
        "end_date": "2024-02-24",
        "n_states": 4,
        "max_duration": 10,
        "train_window_days": 35,
        "train_frequency": "every_n_trade_days",
        "train_every_n_trade_days": 8,
        "snapshot_frequency": "daily",
        "min_sequence_length": 20,
        "min_train_sequences": 3,
        "n_iter": 1,
        "snapshot_decode_mode": "prefix",
        "hsmm_engine": "python",
        "n_jobs": 1,
        "sector_chunk_size": 2,
        "run_id": "hsmm_parallel_fit_test",
    }
    payload.update(overrides)
    return HSMMWalkForwardConfig(**payload)


class _InlineParallel:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs

    def __call__(self, tasks):
        out = []
        for func, args, kwargs in tasks:
            out.append(func(*args, **kwargs))
        return out


def test_parallel_fit_matches_serial_paths_on_synthetic_data(monkeypatch):
    monkeypatch.setattr(joblib, "Parallel", _InlineParallel)
    sequences = _synthetic_sequences()
    serial = DiscreteDurationGaussianHSMM(n_states=4, max_duration=12, n_iter=3, random_state=9, engine="python", n_jobs=1)
    parallel = DiscreteDurationGaussianHSMM(
        n_states=4,
        max_duration=12,
        n_iter=3,
        random_state=9,
        engine="python",
        n_jobs=2,
        sequence_chunk_size=1,
    )

    serial.fit(sequences, FEATURES)
    parallel.fit(sequences, FEATURES)

    assert 0 < len(serial.monitor_history_) <= serial.n_iter
    assert 0 < len(parallel.monitor_history_) <= parallel.n_iter
    assert parallel.fit_parallel_enabled_ is True
    assert parallel.fit_parallel_fallback_ is False
    for seq in sequences:
        np.testing.assert_array_equal(serial.decode(seq)["state_id"].to_numpy(), parallel.decode(seq)["state_id"].to_numpy())
    np.testing.assert_allclose(serial.startprob_, parallel.startprob_)
    np.testing.assert_allclose(serial.transmat_, parallel.transmat_)
    np.testing.assert_allclose(serial.duration_pmf_, parallel.duration_pmf_)


def test_parallel_fit_fallback_to_serial(monkeypatch):
    def _raise_parallel(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("parallel unavailable")

    monkeypatch.setattr(joblib, "Parallel", _raise_parallel)
    model = DiscreteDurationGaussianHSMM(
        n_states=4,
        max_duration=12,
        n_iter=2,
        random_state=7,
        engine="python",
        n_jobs=2,
        sequence_chunk_size=1,
    )

    model.fit(_synthetic_sequences(4), FEATURES)

    assert model.fit_parallel_fallback_ is True
    assert model.fit_parallel_warning_ is not None
    assert model.fit_iteration_count_ > 0


def test_fit_parallel_diagnostics_populated():
    model = DiscreteDurationGaussianHSMM(
        n_states=4,
        max_duration=12,
        n_iter=2,
        random_state=11,
        engine="python",
        n_jobs=2,
        sequence_chunk_size=1,
    )

    model.fit(_synthetic_sequences(5), FEATURES)

    assert model.fit_iteration_count_ > 0
    assert model.fit_n_jobs_ == 2
    assert model.fit_sequence_count_ == 5
    assert model.fit_decode_seconds_ >= 0
    assert model.fit_update_seconds_ >= 0


def test_hsmm_walk_forward_passes_fit_n_jobs(tmp_path, monkeypatch):
    storage = DuckDBStorage(tmp_path / "hsmm_perf.duckdb")
    storage.init_schema()
    _seed_sector_ohlcv(storage)
    captured: list[dict[str, object]] = []
    original_init = hsmm_walk_forward.DiscreteDurationGaussianHSMM.__init__

    def _capture_init(self, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        captured.append({"n_jobs": kwargs.get("n_jobs"), "sequence_chunk_size": kwargs.get("sequence_chunk_size")})
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(hsmm_walk_forward.DiscreteDurationGaussianHSMM, "__init__", _capture_init)

    result = run_hsmm_walk_forward(
        _small_walk_forward_config(tmp_path, fit_n_jobs=1, fit_sequence_chunk_size=7),
        storage=storage,
    )

    assert captured
    assert any(item["n_jobs"] == 1 and item["sequence_chunk_size"] == 7 for item in captured)
    performance = result["performance"]
    assert not performance.empty
    assert {"fit_n_jobs", "fit_decode_seconds", "decode_n_jobs", "hsmm_engine"}.issubset(performance.columns)


def test_no_schema_migration(tmp_path):
    storage = DuckDBStorage(tmp_path / "hsmm_schema.duckdb")
    storage.init_schema()

    columns = set(storage.read_df("DESCRIBE hsmm_run_performance")["column_name"])

    assert "fit_decode_seconds" not in columns
    assert "fit_n_jobs" not in columns


def test_no_forbidden_stage04_or_decision_terms(tmp_path):
    profile = {
        "run_id": "profile_test",
        "start_date": "2025-01-01",
        "end_date": "2025-01-31",
        "snapshot_count": 10,
        "checkpoint_count": 1,
        "sector_count_raw": 4,
        "sector_count_feature_eligible": 4,
        "legacy_snapshot_decode_calls": 40,
        "legacy_prefix_day_units": 400,
        "optimized_checkpoint_sector_decodes": 4,
        "optimized_prefix_day_units": 100,
        "rough_complexity_ratio_legacy_vs_prefix": 4.0,
        "fit_n_jobs": "auto",
        "fit_sequence_chunk_size": 32,
        "decode_n_jobs": "auto",
        "sector_chunk_size": 32,
        "snapshot_decode_mode": "prefix",
        "hsmm_engine": "auto",
    }
    write_hsmm_performance_profile(profile, tmp_path)
    public_text = "\n".join(
        [
            Path("docs/runtime/HSMM_PERFORMANCE.md").read_text(encoding="utf-8"),
            (tmp_path / "performance_estimate.md").read_text(encoding="utf-8"),
        ]
    )

    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in public_text
