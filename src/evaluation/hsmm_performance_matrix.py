from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from src.models import hsmm_benchmark, hsmm_core
from src.models.hsmm_benchmark import FEATURE_COLUMNS, synthetic_hsmm_sequences
from src.models.hsmm_model import DiscreteDurationGaussianHSMM
from src.models.hsmm_performance_presets import (
    DEFAULT_PRESET_CONFIG_PATH,
    load_hsmm_performance_preset_config,
    load_hsmm_performance_presets,
    validate_hsmm_performance_preset_config,
)


INDEX_ID = "HSMM-PERF0-1-2-v1"
DEFAULT_OUTPUT = Path("reports/hsmm_diagnostics/hsmm_performance_matrix_report.md")
DEFAULT_SUMMARY_JSON = Path("reports/hsmm_diagnostics/hsmm_performance_matrix_report.json")
DEFAULT_SUMMARY_CSV = Path("reports/hsmm_diagnostics/hsmm_performance_matrix_summary.csv")
DEFAULT_ENGINES = ("python", "auto")
DEFAULT_N_ITERS = (2, 3)
DEFAULT_MAX_DURATIONS = (20, 40)
DEFAULT_FIT_N_JOBS = (1, "auto")
DEFAULT_SEQUENCE_CHUNK_SIZES = (8, 32)
FORBIDDEN_PUBLIC_TERMS = (
    "/Users/",
    "/private/tmp",
    "HMM高阶分析器",
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
)


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _round_seconds(value: object) -> float:
    try:
        return round(float(value), 6)
    except Exception:
        return 0.0


def _normalize_reason(value: object) -> str:
    if value is None or value == "":
        return "none"
    return str(value).replace("\n", " ").strip() or "none"


def _public_path(path: str | Path | None) -> str:
    if path is None or str(path) == "":
        return "not_provided"
    raw = Path(path)
    try:
        resolved = raw.resolve()
        return resolved.relative_to(Path.cwd().resolve()).as_posix()
    except Exception:
        return "<external-path-redacted>"


def _resolved_fit_jobs(value: int | str, auto_jobs: int) -> int:
    if isinstance(value, str) and value.strip().lower() == "auto":
        return max(1, int(auto_jobs))
    return max(1, int(value))


def _profile_id(engine: str, n_iter: int, max_duration: int, fit_n_jobs: int | str, chunk_size: int) -> str:
    jobs = str(fit_n_jobs).replace(" ", "_")
    return f"synthetic__engine_{engine}__iter_{n_iter}__dur_{max_duration}__fitjobs_{jobs}__chunk_{chunk_size}"


def classify_bottleneck(row: dict[str, object]) -> str:
    fit_decode = float(row.get("fit_decode_seconds", 0.0) or 0.0)
    fit_update = float(row.get("fit_update_seconds", 0.0) or 0.0)
    snapshot = float(row.get("snapshot_decode_seconds_if_available", 0.0) or 0.0)
    total = max(fit_decode + fit_update + snapshot, 1e-12)
    shares = {
        "fit_decode_dominant": fit_decode / total,
        "fit_update_dominant": fit_update / total,
        "snapshot_decode_dominant": snapshot / total,
    }
    label, share = max(shares.items(), key=lambda item: (item[1], item[0]))
    if share < 0.45:
        return "balanced_or_inconclusive"
    return label


def _timing_shares(row: dict[str, object]) -> dict[str, float]:
    fit_decode = float(row.get("fit_decode_seconds", 0.0) or 0.0)
    fit_update = float(row.get("fit_update_seconds", 0.0) or 0.0)
    snapshot = float(row.get("snapshot_decode_seconds_if_available", 0.0) or 0.0)
    total = max(fit_decode + fit_update + snapshot, 1e-12)
    return {
        "fit_decode_share": round(fit_decode / total, 6),
        "fit_update_share": round(fit_update / total, 6),
        "snapshot_decode_share": round(snapshot / total, 6),
    }


def _measure_snapshot_decode(model: DiscreteDurationGaussianHSMM, sequence: pd.DataFrame) -> tuple[int, float]:
    if sequence.empty:
        return 0, 0.0
    dates = pd.to_datetime(sequence["trade_date"]).tail(2).tolist()
    started = time.perf_counter()
    snapshots = model.lifecycle_snapshots_from_sequence(sequence, dates)
    seconds = time.perf_counter() - started
    return len(snapshots), seconds


def _row_for_failed_profile(
    *,
    profile_id: str,
    engine_requested: str,
    n_iter: int,
    max_duration: int,
    fit_n_jobs: int | str,
    fit_n_jobs_resolved: int,
    sequence_chunk_size: int,
    sequence_count: int,
    sequence_length: int,
    numba_check: dict[str, object],
    exc: Exception,
) -> dict[str, object]:
    diagnostic = hsmm_core.last_hsmm_engine_diagnostic()
    row = {
        "profile_id": profile_id,
        "profile_mode": "synthetic",
        "status": "failed",
        "sequence_count": sequence_count,
        "sequence_length": sequence_length,
        "n_states": 4,
        "max_duration": max_duration,
        "n_iter": n_iter,
        "engine_requested": engine_requested,
        "engine_used": str(diagnostic.get("resolved_engine") or "failed"),
        "engine_fallback_reason": _normalize_reason(exc),
        "numba_available": _yes_no(numba_check.get("status") == "pass" and numba_check.get("engine_used") == "numba"),
        "numba_compile_warmed": _yes_no(bool(numba_check.get("compile_warmed"))),
        "n_jobs": fit_n_jobs,
        "fit_n_jobs": fit_n_jobs,
        "fit_n_jobs_resolved": fit_n_jobs_resolved,
        "sequence_chunk_size": sequence_chunk_size,
        "fit_parallel_enabled": "no",
        "fit_parallel_fallback": "no",
        "fit_parallel_warning": "none",
        "fit_iteration_count": 0,
        "fit_decode_seconds": 0.0,
        "fit_update_seconds": 0.0,
        "fit_total_seconds": 0.0,
        "snapshot_decode_mode": "prefix",
        "snapshot_decode_count": 0,
        "snapshot_decode_seconds_if_available": 0.0,
        "total_runtime_seconds": 0.0,
        "bottleneck_classification": "failed",
        "no_db_write": "yes",
        "persistent_db_writes": "no",
    }
    row.update(_timing_shares(row))
    return row


def run_synthetic_profile_matrix(
    *,
    engines: Iterable[str] = DEFAULT_ENGINES,
    n_iters: Iterable[int] = DEFAULT_N_ITERS,
    max_durations: Iterable[int] = DEFAULT_MAX_DURATIONS,
    fit_n_jobs_values: Iterable[int | str] = DEFAULT_FIT_N_JOBS,
    sequence_chunk_sizes: Iterable[int] = DEFAULT_SEQUENCE_CHUNK_SIZES,
    n_sequences: int = 3,
    sequence_length: int = 24,
    auto_jobs: int | None = None,
) -> list[dict[str, object]]:
    auto_jobs = auto_jobs or int(os.environ.get("HSMM_PERF_SYNTHETIC_AUTO_JOBS", "2"))
    auto_jobs = max(1, min(int(auto_jobs), 2))
    os.environ.setdefault("LOKY_MAX_CPU_COUNT", str(auto_jobs))
    sequences = synthetic_hsmm_sequences(n_sequences=n_sequences, sequence_length=sequence_length)
    numba_check = hsmm_benchmark.check_hsmm_numba_engine(required=False)
    rows: list[dict[str, object]] = []

    for engine in engines:
        engine = str(engine).strip().lower()
        if not engine:
            continue
        for n_iter in n_iters:
            for max_duration in max_durations:
                for fit_n_jobs in fit_n_jobs_values:
                    fit_n_jobs_resolved = _resolved_fit_jobs(fit_n_jobs, auto_jobs)
                    for chunk_size in sequence_chunk_sizes:
                        profile_id = _profile_id(engine, int(n_iter), int(max_duration), fit_n_jobs, int(chunk_size))
                        started = time.perf_counter()
                        try:
                            model = DiscreteDurationGaussianHSMM(
                                n_states=4,
                                max_duration=int(max_duration),
                                n_iter=int(n_iter),
                                random_state=17,
                                engine=engine,
                                n_jobs=fit_n_jobs_resolved,
                                sequence_chunk_size=int(chunk_size),
                            )
                            model.fit(sequences, FEATURE_COLUMNS)
                            snapshot_count, snapshot_seconds = _measure_snapshot_decode(model, sequences[0])
                            total_seconds = time.perf_counter() - started
                            engine_fallback_reason = _normalize_reason(model.engine_fallback_reason_)
                            status = "pass"
                            row: dict[str, object] = {
                                "profile_id": profile_id,
                                "profile_mode": "synthetic",
                                "status": status,
                                "sequence_count": len(sequences),
                                "sequence_length": sequence_length,
                                "n_states": model.n_states,
                                "max_duration": int(max_duration),
                                "n_iter": int(n_iter),
                                "engine_requested": engine,
                                "engine_used": model.engine_used_,
                                "engine_fallback_reason": engine_fallback_reason,
                                "numba_available": _yes_no(numba_check.get("status") == "pass" and numba_check.get("engine_used") == "numba"),
                                "numba_compile_warmed": _yes_no(bool(numba_check.get("compile_warmed"))),
                                "n_jobs": fit_n_jobs,
                                "fit_n_jobs": fit_n_jobs,
                                "fit_n_jobs_resolved": model.fit_n_jobs_,
                                "sequence_chunk_size": int(chunk_size),
                                "fit_parallel_enabled": _yes_no(model.fit_parallel_enabled_),
                                "fit_parallel_fallback": _yes_no(model.fit_parallel_fallback_),
                                "fit_parallel_warning": _normalize_reason(model.fit_parallel_warning_),
                                "fit_iteration_count": model.fit_iteration_count_,
                                "fit_decode_seconds": _round_seconds(model.fit_decode_seconds_),
                                "fit_update_seconds": _round_seconds(model.fit_update_seconds_),
                                "fit_total_seconds": _round_seconds(model.fit_decode_seconds_ + model.fit_update_seconds_),
                                "snapshot_decode_mode": "prefix",
                                "snapshot_decode_count": snapshot_count,
                                "snapshot_decode_seconds_if_available": _round_seconds(snapshot_seconds),
                                "total_runtime_seconds": _round_seconds(total_seconds),
                                "no_db_write": "yes",
                                "persistent_db_writes": "no",
                            }
                            row["bottleneck_classification"] = classify_bottleneck(row)
                            row.update(_timing_shares(row))
                        except Exception as exc:
                            row = _row_for_failed_profile(
                                profile_id=profile_id,
                                engine_requested=engine,
                                n_iter=int(n_iter),
                                max_duration=int(max_duration),
                                fit_n_jobs=fit_n_jobs,
                                fit_n_jobs_resolved=fit_n_jobs_resolved,
                                sequence_chunk_size=int(chunk_size),
                                sequence_count=len(sequences),
                                sequence_length=sequence_length,
                                numba_check=numba_check,
                                exc=exc,
                            )
                        rows.append(row)
    return rows


def run_local_profile_matrix(*, db_path: str | None) -> tuple[list[dict[str, object]], str, str]:
    resolved = db_path or os.environ.get("HSMM_PERF_LOCAL_DB") or os.environ.get("HSMM_PROFILE_DB")
    if not resolved:
        return [], "skipped_missing_db", "not_provided"
    path = Path(resolved)
    if not path.exists():
        return [], "skipped_missing_db", _public_path(path)
    return [], "not_run_explicit_local_db_execution_deferred", _public_path(path)


def _dominant_bottleneck(rows: list[dict[str, object]]) -> str:
    counts: dict[str, int] = {}
    for row in rows:
        label = str(row.get("bottleneck_classification", "unknown"))
        counts[label] = counts.get(label, 0) + 1
    if not counts:
        return "none"
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def summarize_rows(
    rows: list[dict[str, object]],
    *,
    mode: str,
    local_profile_status: str,
    local_db_path: str,
    numba_check: dict[str, object],
    preset_validation_errors: list[str],
) -> dict[str, object]:
    fallback_rows = [
        row
        for row in rows
        if str(row.get("engine_fallback_reason", "none")).lower() not in {"", "none", "nan"}
        or str(row.get("engine_requested")) != str(row.get("engine_used"))
    ]
    fit_parallel_fallback_rows = [row for row in rows if str(row.get("fit_parallel_fallback", "no")).lower() in {"yes", "true"}]
    pass_rows = [row for row in rows if row.get("status") == "pass"]
    status = "pass" if rows and not preset_validation_errors and len(pass_rows) == len(rows) else "partial"
    if mode == "local" and local_profile_status.startswith("skipped"):
        status = "skipped"
    return {
        "status": status,
        "profile_count": len(rows),
        "pass_profile_count": len(pass_rows),
        "fallback_rows": len(fallback_rows),
        "fit_parallel_fallback_rows": len(fit_parallel_fallback_rows),
        "bottleneck_classification": _dominant_bottleneck(rows),
        "local_profile_status": local_profile_status,
        "local_db_path": local_db_path,
        "numba_status": numba_check.get("status", "unknown"),
        "numba_engine_used": numba_check.get("engine_used", "unknown"),
        "numba_fallback_reason": numba_check.get("fallback_reason", "none"),
        "preset_validation_status": "pass" if not preset_validation_errors else "fail",
        "no_db_write": "yes",
        "persistent_db_writes": "no",
    }


def build_payload(
    *,
    rows: list[dict[str, object]],
    mode: str,
    preset_config: str | Path,
    local_profile_status: str,
    local_db_path: str,
) -> dict[str, object]:
    preset_payload = load_hsmm_performance_preset_config(preset_config)
    preset_validation_errors = validate_hsmm_performance_preset_config(preset_payload)
    presets = {
        name: preset.walk_forward_overrides()
        for name, preset in load_hsmm_performance_presets(preset_config).items()
    } if not preset_validation_errors else {}
    numba_check = hsmm_benchmark.check_hsmm_numba_engine(required=False)
    summary = summarize_rows(
        rows,
        mode=mode,
        local_profile_status=local_profile_status,
        local_db_path=local_db_path,
        numba_check=numba_check,
        preset_validation_errors=preset_validation_errors,
    )
    return {
        "index_id": INDEX_ID,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": mode,
        "preset_config_path": Path(preset_config).as_posix(),
        "status": summary["status"],
        "summary": summary,
        "preset_validation": {
            "status": "pass" if not preset_validation_errors else "fail",
            "errors": preset_validation_errors,
            "presets": presets,
        },
        "numba_check": {
            "status": numba_check.get("status", "unknown"),
            "requested_engine": numba_check.get("requested_engine", "numba"),
            "resolved_engine": numba_check.get("resolved_engine", numba_check.get("engine_used", "unknown")),
            "engine_used": numba_check.get("engine_used", "unknown"),
            "fallback_reason": numba_check.get("fallback_reason", "none"),
            "numba_importable": _yes_no(bool(numba_check.get("numba_importable"))),
            "numba_available": _yes_no(numba_check.get("status") == "pass" and numba_check.get("engine_used") == "numba"),
            "compile_warmed": _yes_no(bool(numba_check.get("compile_warmed"))),
        },
        "boundary_flags": {
            "model_semantics_changed": "no",
            "approximate_pruned_viterbi_added": "no",
            "production_hsmm_model_rows_written": "no",
            "persistent_db_writes": "no",
            "stage03v_artifacts_modified": "no",
            "holdout_consumed": "no",
            "trading_or_decision_output": "no",
        },
        "rows": rows,
    }


def _write_json(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(path, index=False)


def _markdown_table(rows: list[dict[str, object]]) -> list[str]:
    columns = [
        "profile_id",
        "status",
        "engine_requested",
        "engine_used",
        "engine_fallback_reason",
        "fit_n_jobs",
        "fit_n_jobs_resolved",
        "max_duration",
        "n_iter",
        "total_runtime_seconds",
        "bottleneck_classification",
    ]
    lines = ["|" + "|".join(columns) + "|", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        values = [str(row.get(column, "")) for column in columns]
        lines.append("|" + "|".join(value.replace("|", "/") for value in values) + "|")
    return lines


def _write_markdown(payload: dict[str, object], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(payload["summary"])
    preset_validation = dict(payload["preset_validation"])
    numba_check = dict(payload["numba_check"])
    lines = [
        "# HSMM Performance Matrix Report",
        "",
        f"- index_id: {payload['index_id']}",
        f"- status: {payload['status']}",
        f"- mode: {payload['mode']}",
        f"- profile_count: {summary['profile_count']}",
        f"- pass_profile_count: {summary['pass_profile_count']}",
        f"- fallback_rows: {summary['fallback_rows']}",
        f"- fit_parallel_fallback_rows: {summary['fit_parallel_fallback_rows']}",
        f"- bottleneck_classification: {summary['bottleneck_classification']}",
        f"- numba_status: {summary['numba_status']}",
        f"- numba_engine_used: {summary['numba_engine_used']}",
        f"- numba_fallback_reason: {summary['numba_fallback_reason']}",
        f"- local_profile_status: {summary['local_profile_status']}",
        f"- no_db_write: {summary['no_db_write']}",
        f"- persistent_db_writes: {summary['persistent_db_writes']}",
        "",
        "## Preset Validation",
        "",
        f"- preset_config_path: {payload['preset_config_path']}",
        f"- preset_validation_status: {preset_validation['status']}",
        "",
        "## Numba Check",
        "",
        f"- requested_engine: {numba_check['requested_engine']}",
        f"- resolved_engine: {numba_check['resolved_engine']}",
        f"- fallback_reason: {numba_check['fallback_reason']}",
        f"- numba_available: {numba_check['numba_available']}",
        f"- compile_warmed: {numba_check['compile_warmed']}",
        "",
        "## Boundary Flags",
        "",
    ]
    for key, value in dict(payload["boundary_flags"]).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Profiles", ""])
    lines.extend(_markdown_table(list(payload["rows"])))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def assert_public_safe(payload: dict[str, object], *paths: Path) -> None:
    text = json.dumps(payload, ensure_ascii=False, default=str)
    for path in paths:
        if path.exists():
            text += "\n" + path.read_text(encoding="utf-8", errors="ignore")
    findings = [term for term in FORBIDDEN_PUBLIC_TERMS if term in text]
    if findings:
        raise ValueError(f"private or forbidden terms in HSMM performance report: {findings}")


def write_outputs(payload: dict[str, object], *, output: Path, summary_json: Path, summary_csv: Path) -> None:
    _write_json(payload, summary_json)
    _write_csv(list(payload["rows"]), summary_csv)
    _write_markdown(payload, output)
    assert_public_safe(payload, output, summary_json, summary_csv)


def run_matrix(args: argparse.Namespace) -> dict[str, object]:
    mode = str(args.mode)
    rows: list[dict[str, object]] = []
    local_status = "not_run"
    local_db_path = "not_run"
    if mode in {"synthetic", "both"}:
        rows.extend(run_synthetic_profile_matrix())
    if mode in {"local", "both"}:
        local_rows, local_status, local_db_path = run_local_profile_matrix(db_path=args.db)
        rows.extend(local_rows)
    payload = build_payload(
        rows=rows,
        mode=mode,
        preset_config=args.preset_config,
        local_profile_status=local_status,
        local_db_path=local_db_path,
    )
    write_outputs(
        payload,
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        summary_csv=Path(args.summary_csv),
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="HSMM synthetic/local performance profile matrix")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--summary-csv", default=str(DEFAULT_SUMMARY_CSV))
    parser.add_argument("--preset-config", default=str(DEFAULT_PRESET_CONFIG_PATH))
    parser.add_argument("--mode", choices=["synthetic", "local", "both"], default="synthetic")
    parser.add_argument("--db", default=None)
    parser.add_argument("--profile-only", action="store_true")
    parser.add_argument("--no-db-write", action="store_true")
    args = parser.parse_args()

    if args.mode == "synthetic" and not args.no_db_write:
        raise SystemExit("--no-db-write is required for synthetic performance matrix runs")

    payload = run_matrix(args)
    summary = payload["summary"]
    print(
        "HSMM_PERFORMANCE_MATRIX_STATUS="
        f"{payload['status']} mode={payload['mode']} profiles={summary['profile_count']} "
        f"bottleneck={summary['bottleneck_classification']} "
        f"numba_status={summary['numba_status']} fallback_rows={summary['fallback_rows']} "
        f"report={args.output} summary_json={args.summary_json} no_db_write=yes"
    )


if __name__ == "__main__":
    main()
