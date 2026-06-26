from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Callable

import numpy as np


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HSMMEngineDiagnostic:
    requested_engine: str
    resolved_engine: str
    fallback_reason: str | None = None
    numba_available: bool = False
    compile_warmed: bool = False


_NUMBA_KERNEL: Callable | None = None
_NUMBA_LOAD_ATTEMPTED = False
_NUMBA_LOAD_ERROR: str | None = None
_NUMBA_COMPILE_WARMED = False
_LAST_ENGINE_DIAGNOSTIC = HSMMEngineDiagnostic(
    requested_engine="python",
    resolved_engine="python",
    fallback_reason=None,
    numba_available=False,
    compile_warmed=False,
)


def hsmm_viterbi_dp_python(
    emission: np.ndarray,
    log_start: np.ndarray,
    log_trans: np.ndarray,
    log_duration: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Reference HSMM Viterbi DP implementation.

    The inner previous-state max is written as a small explicit loop because
    the state count is tiny. This avoids allocating many short NumPy arrays in
    the duration loop and keeps tie-breaking deterministic.
    """
    emission = np.asarray(emission, dtype=float)
    log_start = np.asarray(log_start, dtype=float)
    log_trans = np.asarray(log_trans, dtype=float)
    log_duration = np.asarray(log_duration, dtype=float)
    t_count, n_states = emission.shape
    max_duration = log_duration.shape[1]

    cumulative = np.vstack([np.zeros((1, n_states)), np.cumsum(emission, axis=0)])
    dp = np.full((t_count + 1, n_states), -np.inf, dtype=float)
    back_state = np.full((t_count + 1, n_states), -1, dtype=int)
    back_duration = np.full((t_count + 1, n_states), 0, dtype=int)

    for end in range(1, t_count + 1):
        max_d = min(max_duration, end)
        for state in range(n_states):
            best_score = -np.inf
            best_prev = -1
            best_duration = 1
            for duration in range(1, max_d + 1):
                start = end - duration
                segment_score = cumulative[end, state] - cumulative[start, state] + log_duration[state, duration - 1]
                if start == 0:
                    score = log_start[state] + segment_score
                    prev_state = -1
                else:
                    best_prev_score = -np.inf
                    prev_state = -1
                    for candidate_prev in range(n_states):
                        candidate = dp[start, candidate_prev] + log_trans[candidate_prev, state]
                        if candidate > best_prev_score:
                            best_prev_score = candidate
                            prev_state = candidate_prev
                    score = best_prev_score + segment_score
                if score > best_score:
                    best_score = score
                    best_prev = prev_state
                    best_duration = duration
            dp[end, state] = best_score
            back_state[end, state] = best_prev
            back_duration[end, state] = best_duration

    score_by_t = np.max(dp[1:], axis=1) if t_count else np.array([], dtype=float)
    return dp, back_state, back_duration, score_by_t


def _build_numba_kernel(njit: Callable) -> Callable:
    @njit
    def _hsmm_viterbi_dp_numba(
        emission: np.ndarray,
        log_start: np.ndarray,
        log_trans: np.ndarray,
        log_duration: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        t_count = emission.shape[0]
        n_states = emission.shape[1]
        max_duration = log_duration.shape[1]

        cumulative = np.zeros((t_count + 1, n_states), dtype=np.float64)
        for t in range(t_count):
            for state in range(n_states):
                cumulative[t + 1, state] = cumulative[t, state] + emission[t, state]

        dp = np.empty((t_count + 1, n_states), dtype=np.float64)
        back_state = np.empty((t_count + 1, n_states), dtype=np.int64)
        back_duration = np.empty((t_count + 1, n_states), dtype=np.int64)
        for t in range(t_count + 1):
            for state in range(n_states):
                dp[t, state] = -np.inf
                back_state[t, state] = -1
                back_duration[t, state] = 0

        for end in range(1, t_count + 1):
            max_d = max_duration if max_duration < end else end
            for state in range(n_states):
                best_score = -np.inf
                best_prev = -1
                best_duration = 1
                for duration in range(1, max_d + 1):
                    start = end - duration
                    segment_score = cumulative[end, state] - cumulative[start, state] + log_duration[state, duration - 1]
                    if start == 0:
                        score = log_start[state] + segment_score
                        prev_state = -1
                    else:
                        best_prev_score = -np.inf
                        prev_state = -1
                        for candidate_prev in range(n_states):
                            candidate = dp[start, candidate_prev] + log_trans[candidate_prev, state]
                            if candidate > best_prev_score:
                                best_prev_score = candidate
                                prev_state = candidate_prev
                        score = best_prev_score + segment_score
                    if score > best_score:
                        best_score = score
                        best_prev = prev_state
                        best_duration = duration
                dp[end, state] = best_score
                back_state[end, state] = best_prev
                back_duration[end, state] = best_duration

        score_by_t = np.empty(t_count, dtype=np.float64)
        for t in range(t_count):
            best = -np.inf
            for state in range(n_states):
                if dp[t + 1, state] > best:
                    best = dp[t + 1, state]
            score_by_t[t] = best
        return dp, back_state, back_duration, score_by_t

    return _hsmm_viterbi_dp_numba


def _set_engine_diagnostic(
    requested_engine: str,
    resolved_engine: str,
    fallback_reason: str | None = None,
) -> None:
    global _LAST_ENGINE_DIAGNOSTIC
    _LAST_ENGINE_DIAGNOSTIC = HSMMEngineDiagnostic(
        requested_engine=requested_engine,
        resolved_engine=resolved_engine,
        fallback_reason=fallback_reason,
        numba_available=_NUMBA_KERNEL is not None,
        compile_warmed=_NUMBA_COMPILE_WARMED,
    )


def last_hsmm_engine_diagnostic() -> dict[str, object]:
    return asdict(_LAST_ENGINE_DIAGNOSTIC)


def _load_numba_kernel() -> Callable:
    global _NUMBA_KERNEL, _NUMBA_LOAD_ATTEMPTED, _NUMBA_LOAD_ERROR
    if _NUMBA_KERNEL is not None:
        return _NUMBA_KERNEL
    if _NUMBA_LOAD_ATTEMPTED:
        raise RuntimeError(_NUMBA_LOAD_ERROR or "numba HSMM kernel is unavailable")
    _NUMBA_LOAD_ATTEMPTED = True
    try:
        from numba import njit

        _NUMBA_KERNEL = _build_numba_kernel(njit)
        _NUMBA_LOAD_ERROR = None
        return _NUMBA_KERNEL
    except Exception as exc:  # pragma: no cover - normal path when numba is absent.
        _NUMBA_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
        _NUMBA_KERNEL = None
        raise RuntimeError(f"numba HSMM kernel is unavailable: {_NUMBA_LOAD_ERROR}") from exc


def _mark_numba_runtime_failure(exc: Exception) -> str:
    global _NUMBA_KERNEL, _NUMBA_LOAD_ERROR
    _NUMBA_KERNEL = None
    _NUMBA_LOAD_ERROR = f"{type(exc).__name__}: {exc}"
    return f"numba HSMM kernel failed: {_NUMBA_LOAD_ERROR}"


def _warn_auto_fallback(fallback_reason: object) -> None:
    logger.warning(
        "HSMM auto engine fell back to python; fallback_reason=%s",
        fallback_reason or "unknown",
    )


def resolve_hsmm_engine(engine: str) -> str:
    engine = str(engine or "python").lower()
    if engine == "python":
        _set_engine_diagnostic(engine, "python")
        return "python"
    if engine not in {"auto", "numba"}:
        raise ValueError("hsmm_engine must be one of: python, auto, numba")
    try:
        _load_numba_kernel()
    except RuntimeError as exc:
        if engine == "numba":
            _set_engine_diagnostic(engine, "unavailable", str(exc))
            raise RuntimeError(f"hsmm_engine='numba' was requested, but {exc}") from exc
        _set_engine_diagnostic(engine, "python", str(exc))
        _warn_auto_fallback(str(exc))
        return "python"
    _set_engine_diagnostic(engine, "numba")
    return "numba"


def hsmm_viterbi_dp(
    emission: np.ndarray,
    log_start: np.ndarray,
    log_trans: np.ndarray,
    log_duration: np.ndarray,
    engine: str = "python",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    global _NUMBA_COMPILE_WARMED
    requested = str(engine or "python").lower()
    resolved = resolve_hsmm_engine(engine)
    if resolved == "numba":
        try:
            kernel = _load_numba_kernel()
            out = kernel(
                np.asarray(emission, dtype=np.float64),
                np.asarray(log_start, dtype=np.float64),
                np.asarray(log_trans, dtype=np.float64),
                np.asarray(log_duration, dtype=np.float64),
            )
            _NUMBA_COMPILE_WARMED = True
            _set_engine_diagnostic(requested, "numba")
            return out
        except Exception as exc:
            fallback_reason = _mark_numba_runtime_failure(exc)
            if requested == "numba":
                _set_engine_diagnostic(requested, "failed", fallback_reason)
                raise RuntimeError(f"hsmm_engine='numba' was requested, but {fallback_reason}") from exc
            _set_engine_diagnostic(requested, "python", fallback_reason)
            _warn_auto_fallback(fallback_reason)
    return hsmm_viterbi_dp_python(emission, log_start, log_trans, log_duration)


def warm_hsmm_numba_engine(n_states: int = 2, max_duration: int = 3, length: int = 5) -> dict[str, object]:
    n_states = max(2, int(n_states))
    max_duration = max(2, int(max_duration))
    length = max(1, int(length))
    emission = np.zeros((length, n_states), dtype=float)
    log_start = np.log(np.full(n_states, 1.0 / n_states, dtype=float))
    trans = np.full((n_states, n_states), 1.0 / max(n_states - 1, 1), dtype=float)
    np.fill_diagonal(trans, 0.0)
    log_trans = np.full_like(trans, -np.inf, dtype=float)
    positive = trans > 0
    log_trans[positive] = np.log(trans[positive])
    log_duration = np.log(np.full((n_states, max_duration), 1.0 / max_duration, dtype=float))
    hsmm_viterbi_dp(emission, log_start, log_trans, log_duration, engine="numba")
    return last_hsmm_engine_diagnostic()
