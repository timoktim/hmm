from __future__ import annotations

import argparse
import importlib
import json
import time
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd

from src.models import hsmm_core
from src.models.hsmm_model import DiscreteDurationGaussianHSMM


BENCHMARK_VERSION = "hsmm_perf_wp2_1_v1"
FEATURE_COLUMNS = ["f1", "f2"]
SAMPLE_BENCHMARK_DIR = Path("reports/hsmm_diagnostics/benchmark_sample")


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _numba_importable() -> bool:
    try:
        importlib.import_module("numba")
    except Exception:
        return False
    return True


def _normalize_reason(value: object) -> str:
    if value is None or value == "":
        return "none"
    return str(value).replace("\n", " ").strip() or "none"


def check_hsmm_numba_engine(required: bool = False) -> dict[str, object]:
    """Return a DB-free operational check for the optional numba engine."""
    requested_engine = "numba"
    numba_importable = _numba_importable()
    status = "failed"
    engine_used = "failed"
    resolved_engine = "failed"
    fallback_reason: str | None = None
    compile_warmed = False

    try:
        diagnostic = hsmm_core.warm_hsmm_numba_engine()
        resolved_engine = str(diagnostic.get("resolved_engine") or "numba")
        engine_used = resolved_engine
        fallback_reason = diagnostic.get("fallback_reason")
        compile_warmed = bool(diagnostic.get("compile_warmed"))
        status = "pass" if engine_used == "numba" and compile_warmed else "fallback"
    except Exception as exc:
        fallback_reason = "numba unavailable" if not numba_importable else str(exc)
        try:
            resolved_engine = hsmm_core.resolve_hsmm_engine("auto")
            engine_used = resolved_engine
            diagnostic = hsmm_core.last_hsmm_engine_diagnostic()
            fallback_reason = fallback_reason or str(diagnostic.get("fallback_reason") or "")
            compile_warmed = bool(diagnostic.get("compile_warmed"))
            status = "fallback" if engine_used == "python" else "failed"
        except Exception as fallback_exc:
            engine_used = "failed"
            resolved_engine = "failed"
            fallback_reason = str(fallback_exc)
            compile_warmed = False
            status = "failed"

    if required and (status != "pass" or engine_used != "numba"):
        status = "failed"

    return {
        "status": status,
        "requested_engine": requested_engine,
        "resolved_engine": resolved_engine,
        "numba_importable": numba_importable,
        "numba_available": status == "pass" and engine_used == "numba",
        "engine_used": engine_used,
        "fallback_reason": _normalize_reason(fallback_reason),
        "compile_warmed": compile_warmed,
        "required": required,
    }


def format_numba_check_lines(result: dict[str, object]) -> list[str]:
    return [
        f"HSMM_NUMBA_CHECK_STATUS={result['status']}",
        f"requested_engine={result.get('requested_engine', 'numba')}",
        f"resolved_engine={result.get('resolved_engine', result.get('engine_used', 'unknown'))}",
        f"numba_importable={_yes_no(bool(result['numba_importable']))}",
        f"numba_available={_yes_no(bool(result.get('numba_available', False)))}",
        f"engine_used={result['engine_used']}",
        f"fallback_reason={_normalize_reason(result.get('fallback_reason'))}",
        f"compile_warmed={_yes_no(bool(result['compile_warmed']))}",
    ]


def synthetic_hsmm_sequences(n_sequences: int = 4, sequence_length: int = 48) -> list[pd.DataFrame]:
    """Build deterministic synthetic HSMM-like sequences without DB access."""
    n_sequences = max(1, int(n_sequences))
    sequence_length = max(8, int(sequence_length))
    means = [
        np.array([-2.5, 0.0], dtype=float),
        np.array([0.0, 2.5], dtype=float),
        np.array([2.5, 0.0], dtype=float),
        np.array([0.0, -2.5], dtype=float),
    ]
    out: list[pd.DataFrame] = []
    for seq_idx in range(n_sequences):
        rng = np.random.default_rng(10_000 + seq_idx)
        rows = []
        date = pd.Timestamp("2024-01-01")
        segment_width = max(2, sequence_length // len(means))
        for row_idx in range(sequence_length):
            mean = means[(row_idx // segment_width) % len(means)]
            values = mean + rng.normal(0, 0.06, size=2)
            rows.append(
                {
                    "sector_id": f"synthetic:{seq_idx}",
                    "trade_date": date,
                    "f1": float(values[0]),
                    "f2": float(values[1]),
                }
            )
            date += pd.Timedelta(days=1)
        out.append(pd.DataFrame(rows))
    return out


def _benchmark_id(engine: str, n_jobs: int | str, n_iter: int, max_duration: int) -> str:
    return f"synthetic_{engine}_jobs_{n_jobs}_iter_{n_iter}_dur_{max_duration}"


def _base_row(
    *,
    engine: str,
    n_jobs: int | str,
    sequence_chunk_size: int,
    n_sequences: int,
    sequence_length: int,
    n_iter: int,
    max_duration: int,
) -> dict[str, object]:
    return {
        "benchmark_id": _benchmark_id(engine, n_jobs, n_iter, max_duration),
        "benchmark_version": BENCHMARK_VERSION,
        "engine_requested": engine,
        "engine_used": "not_run",
        "fallback_reason": "none",
        "n_jobs": n_jobs,
        "sequence_chunk_size": sequence_chunk_size,
        "n_sequences": n_sequences,
        "sequence_length": sequence_length,
        "n_iter": n_iter,
        "max_duration": max_duration,
        "fit_seconds": 0.0,
        "fit_decode_seconds": 0.0,
        "fit_update_seconds": 0.0,
        "fit_iteration_count": 0,
        "fit_parallel_enabled": False,
        "fit_parallel_fallback": False,
        "status": "not_run",
    }


def _numba_ready() -> tuple[bool, str]:
    result = check_hsmm_numba_engine(required=False)
    return result["status"] == "pass" and result["engine_used"] == "numba", str(result["fallback_reason"])


def run_synthetic_hsmm_benchmark(
    *,
    engines: Sequence[str] = ("python", "auto", "numba"),
    n_jobs_values: Sequence[int | str] = (1, 2, "auto"),
    n_sequences: int = 4,
    sequence_length: int = 48,
    n_iter: int = 3,
    max_duration: int = 12,
    sequence_chunk_size: int = 1,
    require_numba: bool = False,
) -> pd.DataFrame:
    sequences = synthetic_hsmm_sequences(n_sequences=n_sequences, sequence_length=sequence_length)
    rows: list[dict[str, object]] = []
    numba_available, numba_reason = _numba_ready()

    for engine in engines:
        engine = str(engine).strip().lower()
        if not engine:
            continue
        for n_jobs in n_jobs_values:
            row = _base_row(
                engine=engine,
                n_jobs=n_jobs,
                sequence_chunk_size=sequence_chunk_size,
                n_sequences=len(sequences),
                sequence_length=sequence_length,
                n_iter=n_iter,
                max_duration=max_duration,
            )
            if engine == "numba" and not numba_available:
                row.update(
                    {
                        "engine_used": "unavailable",
                        "fallback_reason": _normalize_reason(numba_reason),
                        "status": "failed" if require_numba else "skipped",
                    }
                )
                rows.append(row)
                continue
            try:
                model = DiscreteDurationGaussianHSMM(
                    n_states=4,
                    max_duration=max_duration,
                    n_iter=n_iter,
                    random_state=17,
                    engine=engine,
                    n_jobs=n_jobs,
                    sequence_chunk_size=sequence_chunk_size,
                )
                started = time.perf_counter()
                model.fit(sequences, FEATURE_COLUMNS)
                fit_seconds = time.perf_counter() - started
                status = "pass"
                if require_numba and engine in {"numba", "auto"} and model.engine_used_ != "numba":
                    status = "failed"
                row.update(
                    {
                        "engine_used": model.engine_used_,
                        "fallback_reason": _normalize_reason(model.engine_fallback_reason_),
                        "fit_seconds": fit_seconds,
                        "fit_decode_seconds": model.fit_decode_seconds_,
                        "fit_update_seconds": model.fit_update_seconds_,
                        "fit_iteration_count": model.fit_iteration_count_,
                        "fit_parallel_enabled": model.fit_parallel_enabled_,
                        "fit_parallel_fallback": model.fit_parallel_fallback_,
                        "status": status,
                    }
                )
            except Exception as exc:
                diagnostic = hsmm_core.last_hsmm_engine_diagnostic()
                row.update(
                    {
                        "engine_used": str(diagnostic.get("resolved_engine") or "failed"),
                        "fallback_reason": _normalize_reason(exc),
                        "status": "failed",
                    }
                )
            rows.append(row)
    return pd.DataFrame(rows)


def sample_benchmark_output_path(filename: str = "benchmark_matrix.jsonl") -> Path:
    return SAMPLE_BENCHMARK_DIR / filename


def write_benchmark_jsonl(rows: Iterable[dict[str, object]] | pd.DataFrame, output_path: Path | str | None = None) -> Path:
    path = Path(output_path) if output_path is not None else sample_benchmark_output_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(rows, pd.DataFrame):
        records = rows.to_dict(orient="records")
    else:
        records = list(rows)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    return path


def benchmark_required_columns() -> set[str]:
    return set(
        _base_row(
            engine="python",
            n_jobs=1,
            sequence_chunk_size=1,
            n_sequences=1,
            sequence_length=8,
            n_iter=1,
            max_duration=4,
        )
    )


def _parse_csv_values(value: str, *, coerce_jobs: bool = False) -> list[int | str] | list[str]:
    out: list[int | str] = []
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        if coerce_jobs and item.lower() != "auto":
            out.append(int(item))
        else:
            out.append(item.lower())
    return out


def _run_check_command(args: argparse.Namespace) -> int:
    result = check_hsmm_numba_engine(required=args.required)
    for line in format_numba_check_lines(result):
        print(line)
    if result["status"] == "failed":
        return 1
    if args.required and result["status"] != "pass":
        return 1
    return 0


def _run_synthetic_command(args: argparse.Namespace) -> int:
    rows = run_synthetic_hsmm_benchmark(
        engines=tuple(_parse_csv_values(args.engines)),
        n_jobs_values=tuple(_parse_csv_values(args.n_jobs, coerce_jobs=True)),
        n_sequences=args.n_sequences,
        sequence_length=args.sequence_length,
        n_iter=args.n_iter,
        max_duration=args.max_duration,
        sequence_chunk_size=args.sequence_chunk_size,
        require_numba=args.require_numba,
    )
    output_path = write_benchmark_jsonl(rows, args.output)
    print(f"HSMM_BENCHMARK_STATUS=pass mode=synthetic rows={len(rows)} output={output_path}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="HSMM numba operational checks and synthetic benchmarks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check-numba")
    check.add_argument("--required", action="store_true")
    check.set_defaults(func=_run_check_command)

    synthetic = subparsers.add_parser("synthetic")
    synthetic.add_argument("--engines", default="python,auto,numba")
    synthetic.add_argument("--n-jobs", default="1,2,auto")
    synthetic.add_argument("--n-sequences", type=int, default=4)
    synthetic.add_argument("--sequence-length", type=int, default=32)
    synthetic.add_argument("--n-iter", type=int, default=3)
    synthetic.add_argument("--max-duration", type=int, default=12)
    synthetic.add_argument("--sequence-chunk-size", type=int, default=1)
    synthetic.add_argument("--output", default=str(sample_benchmark_output_path()))
    synthetic.add_argument("--require-numba", action="store_true")
    synthetic.set_defaults(func=_run_synthetic_command)

    args = parser.parse_args()
    raise SystemExit(args.func(args))


if __name__ == "__main__":
    main()
