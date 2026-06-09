from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from src.models import hsmm_core
from src.models.hsmm_model import DiscreteDurationGaussianHSMM


FEATURES = ["f1", "f2"]
FORBIDDEN_PUBLIC_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]


def _small_core_inputs() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    emission = np.array(
        [
            [0.0, -2.0],
            [-0.2, -1.8],
            [-2.0, -0.1],
            [-2.2, -0.2],
            [-0.1, -1.6],
        ],
        dtype=float,
    )
    log_start = np.log(np.array([0.55, 0.45], dtype=float))
    trans = np.array([[0.0, 1.0], [1.0, 0.0]], dtype=float)
    log_trans = np.full_like(trans, -np.inf, dtype=float)
    log_trans[trans > 0] = np.log(trans[trans > 0])
    duration = np.array([[0.2, 0.6, 0.2], [0.3, 0.4, 0.3]], dtype=float)
    log_duration = np.log(duration)
    return emission, log_start, log_trans, log_duration


def _path_from_dp(dp: np.ndarray, back_state: np.ndarray, back_duration: np.ndarray) -> np.ndarray:
    t_count = len(dp) - 1
    path = np.full(t_count, -1, dtype=int)
    end = t_count
    state = int(np.argmax(dp[end]))
    while end > 0 and state >= 0:
        duration = int(back_duration[end, state])
        start = end - duration
        path[start:end] = state
        state = int(back_state[end, state])
        end = start
    return path


def _synthetic_sequence(sector_id: str, seed: int, repeats: int = 2) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    specs = [
        (4, np.array([-3.0, 0.0])),
        (6, np.array([0.0, 3.0])),
        (5, np.array([3.0, 0.0])),
        (3, np.array([0.0, -3.0])),
    ]
    rows = []
    date = pd.Timestamp("2024-01-01")
    for _ in range(repeats):
        for duration, mean in specs:
            for _ in range(duration):
                values = mean + rng.normal(0, 0.08, size=2)
                rows.append({"sector_id": sector_id, "trade_date": date, "f1": values[0], "f2": values[1]})
                date += pd.Timedelta(days=1)
    return pd.DataFrame(rows)


def _synthetic_sequences(count: int = 4) -> list[pd.DataFrame]:
    return [_synthetic_sequence(f"S{idx}", 200 + idx) for idx in range(count)]


class _InlineParallel:
    def __init__(self, *args, **kwargs):  # noqa: ANN002, ANN003
        self.args = args
        self.kwargs = kwargs

    def __call__(self, tasks):
        out = []
        for func, args, kwargs in tasks:
            out.append(func(*args, **kwargs))
        return out


def _numba_available() -> bool:
    try:
        import numba  # noqa: F401
    except Exception:
        return False
    return True


def test_numba_engine_matches_python_on_small_synthetic_case():
    if not _numba_available():
        pytest.skip("numba is not installed")
    inputs = _small_core_inputs()

    python_out = hsmm_core.hsmm_viterbi_dp(*inputs, engine="python")
    try:
        numba_out = hsmm_core.hsmm_viterbi_dp(*inputs, engine="numba")
    except RuntimeError as exc:
        pytest.skip(f"numba engine unavailable: {exc}")

    np.testing.assert_allclose(python_out[0], numba_out[0])
    np.testing.assert_array_equal(python_out[1], numba_out[1])
    np.testing.assert_array_equal(python_out[2], numba_out[2])
    np.testing.assert_allclose(python_out[3], numba_out[3])
    np.testing.assert_array_equal(_path_from_dp(python_out[0], python_out[1], python_out[2]), _path_from_dp(numba_out[0], numba_out[1], numba_out[2]))


def test_auto_engine_falls_back_when_numba_unavailable(monkeypatch):
    monkeypatch.setattr(hsmm_core, "_NUMBA_KERNEL", None)
    monkeypatch.setattr(hsmm_core, "_NUMBA_COMPILE_WARMED", False)

    def _raise_missing():
        raise RuntimeError("simulated numba missing")

    monkeypatch.setattr(hsmm_core, "_load_numba_kernel", _raise_missing)
    inputs = _small_core_inputs()

    python_out = hsmm_core.hsmm_viterbi_dp(*inputs, engine="python")
    auto_out = hsmm_core.hsmm_viterbi_dp(*inputs, engine="auto")
    diagnostic = hsmm_core.last_hsmm_engine_diagnostic()

    np.testing.assert_allclose(auto_out[0], python_out[0])
    assert diagnostic["resolved_engine"] == "python"
    assert "simulated numba missing" in str(diagnostic["fallback_reason"])


def test_numba_engine_required_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(hsmm_core, "_NUMBA_KERNEL", None)

    def _raise_missing():
        raise RuntimeError("simulated numba missing")

    monkeypatch.setattr(hsmm_core, "_load_numba_kernel", _raise_missing)

    with pytest.raises(RuntimeError, match="hsmm_engine='numba'"):
        hsmm_core.hsmm_viterbi_dp(*_small_core_inputs(), engine="numba")


def test_hsmm_model_decode_python_vs_numba_equivalence():
    if not _numba_available():
        pytest.skip("numba is not installed")
    sequences = _synthetic_sequences()
    python_model = DiscreteDurationGaussianHSMM(n_states=4, max_duration=10, n_iter=2, random_state=8, engine="python")
    python_model.fit(sequences, FEATURES)
    payload = python_model.to_dict()
    payload["engine"] = "numba"
    try:
        numba_model = DiscreteDurationGaussianHSMM.from_dict(payload)
        python_decoded = python_model.decode(sequences[0])
        numba_decoded = numba_model.decode(sequences[0])
    except RuntimeError as exc:
        pytest.skip(f"numba engine unavailable: {exc}")

    np.testing.assert_array_equal(python_decoded["state_id"].to_numpy(), numba_decoded["state_id"].to_numpy())
    np.testing.assert_array_equal(python_decoded["state_age_days_by_id"].to_numpy(), numba_decoded["state_age_days_by_id"].to_numpy())
    assert numba_model.engine_used_ == "numba"


def test_parallel_fit_with_numba_engine_smoke(monkeypatch):
    monkeypatch.setattr(joblib, "Parallel", _InlineParallel)
    model = DiscreteDurationGaussianHSMM(
        n_states=4,
        max_duration=10,
        n_iter=1,
        random_state=9,
        engine="auto",
        n_jobs=2,
        sequence_chunk_size=1,
    )

    model.fit(_synthetic_sequences(), FEATURES)

    assert model.fit_n_jobs_ == 2
    assert model.fit_iteration_count_ > 0
    assert model.fit_parallel_enabled_ is True
    assert model.engine_used_ in {"python", "numba"}
    if not _numba_available():
        assert model.engine_used_ == "python"


def test_no_forbidden_output_terms():
    public_text = "\n".join(
        [
            Path("docs/runtime/HSMM_NUMBA_ENGINE.md").read_text(encoding="utf-8"),
            Path("scripts/hsmm_performance_profile.sh").read_text(encoding="utf-8"),
        ]
    )

    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in public_text
