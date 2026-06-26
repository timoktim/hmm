from __future__ import annotations

import os
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

from src.config import project_relative_path
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.universe import load_sector_like_ohlcv
from src.evaluation import signal_validation
from src.evaluation.signal_validation import SignalValidationConfig


DEFAULT_DB_PATH = "data/db/a_share_hmm_tushare_v7.duckdb"
EQUIVALENCE_ATOL = 1e-9


def _value(name: str, default: str) -> str:
    return str(os.environ.get(name, default)).strip() or default


def _optional_value(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "auto"}:
        return None
    return text


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _parse_tuple_int(text: str) -> tuple[int, ...]:
    return tuple(int(value.strip()) for value in text.split(",") if value.strip())


def _parse_tuple_float(text: str) -> tuple[float, ...]:
    return tuple(float(value.strip()) for value in text.split(",") if value.strip())


def _assert_frame_identical(left: pd.DataFrame, right: pd.DataFrame, name: str) -> None:
    left = left.reset_index(drop=True).copy()
    right = right.reset_index(drop=True).copy()
    left.attrs.clear()
    right.attrs.clear()
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, atol=EQUIVALENCE_ATOL, rtol=0, obj=name)


def _make_config(db_path: Path) -> SignalValidationConfig:
    return SignalValidationConfig(
        db_path=str(db_path),
        start_date=_optional_value("BACKTEST_SPEEDUP_START_DATE"),
        end_date=_value("BACKTEST_SPEEDUP_END_DATE", "today"),
        universe_id=os.environ.get("BACKTEST_SPEEDUP_UNIVERSE_ID"),
        include_custom_baskets=_value("BACKTEST_SPEEDUP_INCLUDE_CUSTOM_BASKETS", "yes").lower() not in {"0", "false", "no"},
        n_states=int(_value("BACKTEST_SPEEDUP_N_STATES", "3")),
        train_window_days=int(_value("BACKTEST_SPEEDUP_TRAIN_WINDOW_DAYS", "504")),
        retrain_frequency=_value("BACKTEST_SPEEDUP_RETRAIN_FREQUENCY", "monthly"),
        rebalance_days=int(_value("BACKTEST_SPEEDUP_REBALANCE_DAYS", "5")),
        top_n=int(_value("BACKTEST_SPEEDUP_TOP_N", "5")),
        threshold=float(_value("BACKTEST_SPEEDUP_THRESHOLD", "0.55")),
        execution_price=_value("BACKTEST_SPEEDUP_EXECUTION_PRICE", "open"),
        transaction_cost=float(_value("BACKTEST_SPEEDUP_TRANSACTION_COST", "0.001")),
        random_trials=int(_value("BACKTEST_SPEEDUP_RANDOM_TRIALS", "200")),
        random_state=int(_value("BACKTEST_SPEEDUP_RANDOM_STATE", "42")),
        cost_grid=_parse_tuple_float(_value("BACKTEST_SPEEDUP_COST_GRID", "0,0.0005,0.001,0.002,0.003")),
        threshold_grid=_parse_tuple_float(_value("BACKTEST_SPEEDUP_THRESHOLD_GRID", "0.45,0.50,0.55,0.60,0.65")),
        top_n_grid=_parse_tuple_int(_value("BACKTEST_SPEEDUP_TOP_N_GRID", "3,5,8,10")),
        report_dir=_value("BACKTEST_SPEEDUP_REPORT_DIR", "reports/signal_validation/backtest_speedup_gate"),
    )


def run_gate() -> dict[str, object]:
    warnings.filterwarnings(
        "ignore",
        message="The default fill_method='pad' in DataFrame.pct_change is deprecated.*",
        category=FutureWarning,
    )
    db_path = Path(_value("BACKTEST_SPEEDUP_DB", DEFAULT_DB_PATH))
    if not db_path.exists():
        return {
            "status": "fail",
            "error": f"missing_db:{project_relative_path(db_path)}",
            "states_computed_count": 0,
            "parallel_enabled": False,
            "walltime_seconds": 0.0,
            "equivalence_atol": EQUIVALENCE_ATOL,
            "results_identical": False,
        }

    storage = DuckDBStorage(str(db_path))
    storage.init_schema()
    config = _make_config(db_path)
    full_ohlcv = load_sector_like_ohlcv(storage, universe_id=config.universe_id, include_custom_baskets=config.include_custom_baskets)
    if full_ohlcv.empty:
        return {
            "status": "fail",
            "error": "missing_sector_ohlcv",
            "states_computed_count": 0,
            "parallel_enabled": False,
            "walltime_seconds": 0.0,
            "equivalence_atol": EQUIVALENCE_ATOL,
            "results_identical": False,
        }
    resolved_config = signal_validation._resolve_config_dates(config, full_ohlcv)
    n_jobs = _value("BACKTEST_PERF_N_JOBS", "auto")

    optimized_started = time.perf_counter()
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=prepare_context", file=sys.stderr, flush=True)
    context = signal_validation._prepare_backtest_context_from_config(resolved_config, storage)
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=optimized_selection_grid", file=sys.stderr, flush=True)
    optimized_selection = signal_validation.evaluate_selection_grid(resolved_config, storage, context=context, n_jobs=n_jobs)
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=optimized_cost_sensitivity", file=sys.stderr, flush=True)
    optimized_cost = signal_validation.evaluate_cost_sensitivity(resolved_config, storage, resolved_config.cost_grid, context=context, n_jobs=n_jobs)
    signal_dates = sorted(pd.to_datetime(context.states["trade_date"].drop_duplicates()).tolist()) if not context.states.empty else []
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=optimized_random_baseline", file=sys.stderr, flush=True)
    optimized_random, optimized_random_summary = signal_validation.evaluate_random_baseline(
        context.ohlcv,
        signal_dates,
        resolved_config.top_n,
        resolved_config.transaction_cost,
        resolved_config.random_trials,
        resolved_config.random_state,
        n_jobs=n_jobs,
    )
    optimized_walltime = time.perf_counter() - optimized_started

    direct_started = time.perf_counter()
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=legacy_selection_grid", file=sys.stderr, flush=True)
    legacy_selection = signal_validation._evaluate_selection_grid_direct(resolved_config, storage)
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=legacy_cost_sensitivity", file=sys.stderr, flush=True)
    legacy_cost = signal_validation._evaluate_cost_sensitivity_direct(resolved_config, storage, resolved_config.cost_grid)
    print("BACKTEST_SPEEDUP_GATE_PROGRESS=legacy_random_baseline", file=sys.stderr, flush=True)
    legacy_random, legacy_random_summary = signal_validation._evaluate_random_baseline_direct(
        context.ohlcv,
        signal_dates,
        resolved_config.top_n,
        resolved_config.transaction_cost,
        resolved_config.random_trials,
        resolved_config.random_state,
    )
    direct_walltime = time.perf_counter() - direct_started

    error = ""
    results_identical = True
    try:
        _assert_frame_identical(legacy_selection, optimized_selection, "selection_grid")
        _assert_frame_identical(legacy_cost, optimized_cost, "cost_sensitivity")
        _assert_frame_identical(legacy_random, optimized_random, "random_baseline")
        _assert_frame_identical(legacy_random_summary, optimized_random_summary, "random_baseline_summary")
    except AssertionError as exc:
        results_identical = False
        error = str(exc).splitlines()[0]

    parallel_enabled = any(
        bool(frame.attrs.get("parallel_enabled", False))
        for frame in [optimized_selection, optimized_cost, optimized_random]
        if isinstance(frame, pd.DataFrame)
    )
    improvement_factor = direct_walltime / optimized_walltime if optimized_walltime > 0 else 0.0
    status = "pass" if results_identical and parallel_enabled else "fail"
    return {
        "status": status,
        "error": error,
        "states_computed_count": 1,
        "parallel_enabled": parallel_enabled,
        "walltime_seconds": optimized_walltime,
        "direct_walltime_seconds": direct_walltime,
        "optimized_walltime_seconds": optimized_walltime,
        "walltime_improvement_factor": improvement_factor,
        "equivalence_atol": EQUIVALENCE_ATOL,
        "results_identical": results_identical,
        "selection_parallel_backend": optimized_selection.attrs.get("parallel_backend"),
        "cost_parallel_backend": optimized_cost.attrs.get("parallel_backend"),
        "random_parallel_backend": optimized_random.attrs.get("parallel_backend"),
        "db_path": project_relative_path(db_path),
        "start_date": resolved_config.start_date,
        "end_date": resolved_config.end_date,
        "random_trials": resolved_config.random_trials,
        "threshold_grid_size": len(resolved_config.threshold_grid),
        "top_n_grid_size": len(resolved_config.top_n_grid),
        "cost_grid_size": len(resolved_config.cost_grid),
    }


def main() -> None:
    try:
        result = run_gate()
    except Exception as exc:
        result = {
            "status": "fail",
            "error": f"{type(exc).__name__}: {exc}",
            "states_computed_count": 0,
            "parallel_enabled": False,
            "walltime_seconds": 0.0,
            "direct_walltime_seconds": 0.0,
            "optimized_walltime_seconds": 0.0,
            "walltime_improvement_factor": 0.0,
            "equivalence_atol": EQUIVALENCE_ATOL,
            "results_identical": False,
        }
    print(f"BACKTEST_SPEEDUP_GATE_STATUS={result['status']}")
    if result.get("error"):
        print(f"error={result['error']}")
    print(f"states_computed_count={int(result.get('states_computed_count', 0))}")
    print(f"parallel_enabled={_yes_no(bool(result.get('parallel_enabled', False)))}")
    print(f"walltime_seconds={float(result.get('walltime_seconds', 0.0)):.3f}")
    print(f"direct_walltime_seconds={float(result.get('direct_walltime_seconds', 0.0)):.3f}")
    print(f"optimized_walltime_seconds={float(result.get('optimized_walltime_seconds', 0.0)):.3f}")
    print(f"walltime_improvement_factor={float(result.get('walltime_improvement_factor', 0.0)):.3f}")
    print(f"equivalence_atol={float(result.get('equivalence_atol', EQUIVALENCE_ATOL)):.0e}")
    print(f"results_identical={_yes_no(bool(result.get('results_identical', False)))}")
    print(f"selection_parallel_backend={result.get('selection_parallel_backend', 'unknown')}")
    print(f"cost_parallel_backend={result.get('cost_parallel_backend', 'unknown')}")
    print(f"random_parallel_backend={result.get('random_parallel_backend', 'unknown')}")
    print(f"db_path={result.get('db_path', project_relative_path(DEFAULT_DB_PATH))}")
    print(f"start_date={result.get('start_date', 'unknown')}")
    print(f"end_date={result.get('end_date', 'unknown')}")
    print(f"random_trials={result.get('random_trials', 'unknown')}")
    print(f"threshold_grid_size={result.get('threshold_grid_size', 'unknown')}")
    print(f"top_n_grid_size={result.get('top_n_grid_size', 'unknown')}")
    print(f"cost_grid_size={result.get('cost_grid_size', 'unknown')}")
    raise SystemExit(0 if result.get("status") == "pass" else 1)


if __name__ == "__main__":
    main()
