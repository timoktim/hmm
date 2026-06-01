from __future__ import annotations

import numpy as np


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


try:  # pragma: no cover - exercised only when optional numba is installed.
    from numba import njit

    @njit(cache=True)
    def hsmm_viterbi_dp_numba(
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

except Exception:  # pragma: no cover - normal path when numba is absent.
    hsmm_viterbi_dp_numba = None


def resolve_hsmm_engine(engine: str) -> str:
    engine = str(engine or "python").lower()
    if engine == "auto":
        return "numba" if hsmm_viterbi_dp_numba is not None else "python"
    if engine == "numba" and hsmm_viterbi_dp_numba is None:
        raise RuntimeError("hsmm_engine='numba' was requested, but numba is not installed.")
    if engine not in {"python", "numba"}:
        raise ValueError("hsmm_engine must be one of: python, auto, numba")
    return engine


def hsmm_viterbi_dp(
    emission: np.ndarray,
    log_start: np.ndarray,
    log_trans: np.ndarray,
    log_duration: np.ndarray,
    engine: str = "python",
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    resolved = resolve_hsmm_engine(engine)
    if resolved == "numba":
        return hsmm_viterbi_dp_numba(emission, log_start, log_trans, log_duration)
    return hsmm_viterbi_dp_python(emission, log_start, log_trans, log_duration)

