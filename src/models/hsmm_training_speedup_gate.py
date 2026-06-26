from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pandas as pd

from src.config import project_relative_path
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward


TARGET_SECONDS = 600.0
DEFAULT_DB_PATH = "data/db/a_share_hmm_tushare_v7.duckdb"
DEFAULT_RUN_ID = "hsmm_perf_wp1_speedup_gate"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _value(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip() or default


def _progress(current: int, total: int, trade_date: pd.Timestamp, stage: str) -> None:
    date_text = pd.Timestamp(trade_date).strftime("%Y-%m-%d")
    print(
        f"HSMM_SPEEDUP_GATE_PROGRESS={current}/{total} stage={stage} train_date={date_text}",
        file=sys.stderr,
        flush=True,
    )


def _performance_value(performance: pd.DataFrame, column: str, default: object = None) -> object:
    if performance.empty or column not in performance.columns:
        return default
    values = performance[column].dropna()
    if values.empty:
        return default
    unique = sorted({str(value) for value in values})
    return ",".join(unique)


def run_gate() -> dict[str, object]:
    db_path = Path(_value("HSMM_SPEEDUP_DB", DEFAULT_DB_PATH))
    target_seconds = float(_value("HSMM_SPEEDUP_TARGET_SECONDS", str(int(TARGET_SECONDS))))
    if not db_path.exists():
        return {
            "status": "fail",
            "error": f"missing_db:{project_relative_path(db_path)}",
            "engine_used": "not_run",
            "resolved_engine_is_numba": False,
            "fit_parallel_enabled": False,
            "walltime_seconds": 0.0,
            "target_seconds": target_seconds,
            "config_unchanged": True,
            "run_id": _value("HSMM_SPEEDUP_RUN_ID", DEFAULT_RUN_ID),
            "db_path": project_relative_path(db_path),
        }

    config = HSMMWalkForwardConfig(
        db_path=str(db_path),
        start_date=_value("HSMM_SPEEDUP_START_DATE", "20140101"),
        end_date=_value("HSMM_SPEEDUP_END_DATE", "today"),
        n_states=4,
        max_duration=60,
        n_iter=20,
        train_window_days=504,
        train_frequency="monthly",
        snapshot_frequency="daily",
        snapshot_decode_mode="prefix",
        hsmm_engine="auto",
        n_jobs=_value("HSMM_SPEEDUP_N_JOBS", "auto"),
        fit_n_jobs=_value("HSMM_SPEEDUP_FIT_N_JOBS", "auto"),
        sector_chunk_size=int(_value("HSMM_SPEEDUP_SECTOR_CHUNK_SIZE", "32")),
        fit_sequence_chunk_size=int(_value("HSMM_SPEEDUP_FIT_SEQUENCE_CHUNK_SIZE", "32")),
        run_id=_value("HSMM_SPEEDUP_RUN_ID", DEFAULT_RUN_ID),
        notes="hsmm_perf_wp1_speedup_gate",
        overwrite=True,
    )
    started = time.perf_counter()
    result = run_hsmm_walk_forward(config, progress_callback=_progress)
    walltime_seconds = time.perf_counter() - started
    performance = result.get("performance")
    if not isinstance(performance, pd.DataFrame):
        performance = pd.DataFrame()
    engine_used = str(_performance_value(performance, "engine_used", "unknown"))
    resolved_engine_is_numba = bool(engine_used) and all(item == "numba" for item in engine_used.split(","))
    fit_parallel_enabled = bool(performance.get("fit_parallel_enabled", pd.Series(dtype=bool)).fillna(False).astype(bool).any())
    status = "pass" if resolved_engine_is_numba and fit_parallel_enabled and walltime_seconds < target_seconds else "fail"
    return {
        "status": status,
        "engine_used": engine_used,
        "resolved_engine_is_numba": resolved_engine_is_numba,
        "fit_parallel_enabled": fit_parallel_enabled,
        "fit_n_jobs": str(_performance_value(performance, "fit_n_jobs", config.fit_n_jobs)),
        "decode_n_jobs": str(_performance_value(performance, "decode_n_jobs", config.n_jobs)),
        "walltime_seconds": walltime_seconds,
        "target_seconds": target_seconds,
        "config_unchanged": True,
        "core_count": os.cpu_count() or 1,
        "run_id": str(result.get("run_id", config.run_id)),
        "db_path": project_relative_path(db_path),
        "checkpoint_count": int(len(performance)) if not performance.empty else 0,
    }


def main() -> None:
    try:
        result = run_gate()
    except Exception as exc:
        result = {
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
            "engine_used": "failed",
            "resolved_engine_is_numba": False,
            "fit_parallel_enabled": False,
            "walltime_seconds": 0.0,
            "target_seconds": float(_value("HSMM_SPEEDUP_TARGET_SECONDS", str(int(TARGET_SECONDS)))),
            "config_unchanged": True,
            "core_count": os.cpu_count() or 1,
            "run_id": _value("HSMM_SPEEDUP_RUN_ID", DEFAULT_RUN_ID),
            "db_path": project_relative_path(_value("HSMM_SPEEDUP_DB", DEFAULT_DB_PATH)),
        }
    print(f"HSMM_SPEEDUP_GATE_STATUS={result['status']}")
    if "error" in result:
        print(f"error={result['error']}")
    print(f"engine_used={result.get('engine_used', 'unknown')}")
    print(f"resolved_engine_is_numba={_yes_no(bool(result.get('resolved_engine_is_numba', False)))}")
    print(f"fit_parallel_enabled={_yes_no(bool(result.get('fit_parallel_enabled', False)))}")
    print(f"fit_n_jobs={result.get('fit_n_jobs', 'unknown')}")
    print(f"decode_n_jobs={result.get('decode_n_jobs', 'unknown')}")
    print(f"walltime_seconds={float(result.get('walltime_seconds', 0.0)):.3f}")
    print(f"target_seconds={float(result.get('target_seconds', TARGET_SECONDS)):.0f}")
    print(f"config_unchanged={_yes_no(bool(result.get('config_unchanged', False)))}")
    print(f"core_count={int(result.get('core_count', os.cpu_count() or 1))}")
    print(f"run_id={result.get('run_id', DEFAULT_RUN_ID)}")
    print(f"db_path={result.get('db_path', DEFAULT_DB_PATH)}")
    if "checkpoint_count" in result:
        print(f"checkpoint_count={result['checkpoint_count']}")
    raise SystemExit(0 if result.get("status") == "pass" else 1)


if __name__ == "__main__":
    main()
