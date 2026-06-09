from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.models import hsmm_benchmark, hsmm_core


REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN_PUBLIC_TERMS = [
    "/Users/",
    "/private/tmp",
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]


def _script_env(**overrides: str) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHON_BIN"] = sys.executable
    env.pop("ASHARE_HMM_DB_PATH", None)
    env.pop("HSMM_PROFILE_DB", None)
    env.update(overrides)
    return env


def _parse_key_lines(output: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for line in output.splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        pairs[key] = value
    return pairs


def _simulate_numba_missing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(hsmm_core, "_NUMBA_KERNEL", None)
    monkeypatch.setattr(hsmm_core, "_NUMBA_LOAD_ATTEMPTED", False)
    monkeypatch.setattr(hsmm_core, "_NUMBA_LOAD_ERROR", None)
    monkeypatch.setattr(hsmm_core, "_NUMBA_COMPILE_WARMED", False)

    def _raise_missing():
        raise RuntimeError("simulated numba missing")

    monkeypatch.setattr(hsmm_core, "_load_numba_kernel", _raise_missing)


def test_numba_check_script_no_db_machine_readable_output():
    result = subprocess.run(
        ["bash", "scripts/check_hsmm_numba_engine.sh"],
        cwd=REPO_ROOT,
        env=_script_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    lines = _parse_key_lines(result.stdout)
    assert lines["HSMM_NUMBA_CHECK_STATUS"] in {"pass", "fallback", "failed"}
    assert lines["numba_importable"] in {"yes", "no"}
    assert lines["engine_used"] in {"numba", "python", "unavailable", "failed"}
    assert lines["compile_warmed"] in {"yes", "no"}
    assert "db_path" not in result.stdout


def test_numba_required_mode_fails_explicitly_when_unavailable(monkeypatch):
    _simulate_numba_missing(monkeypatch)

    result = hsmm_benchmark.check_hsmm_numba_engine(required=True)

    assert result["status"] == "failed"
    assert result["engine_used"] in {"python", "unavailable", "failed"}
    assert result["fallback_reason"] != "none"


def test_synthetic_benchmark_outputs_required_columns():
    rows = hsmm_benchmark.run_synthetic_hsmm_benchmark(
        engines=("python",),
        n_jobs_values=(1,),
        n_sequences=2,
        sequence_length=12,
        n_iter=1,
        max_duration=6,
    )

    assert hsmm_benchmark.benchmark_required_columns().issubset(rows.columns)
    assert len(rows) == 1
    assert rows.iloc[0]["status"] == "pass"
    assert rows.iloc[0]["engine_used"] == "python"


def test_synthetic_benchmark_auto_fallback_without_numba(monkeypatch):
    _simulate_numba_missing(monkeypatch)

    rows = hsmm_benchmark.run_synthetic_hsmm_benchmark(
        engines=("auto", "numba"),
        n_jobs_values=(1,),
        n_sequences=2,
        sequence_length=12,
        n_iter=1,
        max_duration=6,
    )

    by_engine = {str(row["engine_requested"]): row for row in rows.to_dict(orient="records")}
    assert by_engine["auto"]["status"] == "pass"
    assert by_engine["auto"]["engine_used"] == "python"
    assert by_engine["auto"]["fallback_reason"] != "none"
    assert by_engine["numba"]["status"] == "skipped"
    assert by_engine["numba"]["engine_used"] == "unavailable"


def test_benchmark_sample_output_is_public_safe(tmp_path):
    output_path = hsmm_benchmark.sample_benchmark_output_path()
    assert output_path.as_posix().startswith("reports/hsmm_diagnostics/benchmark_sample/")

    rows = hsmm_benchmark.run_synthetic_hsmm_benchmark(
        engines=("python",),
        n_jobs_values=(1,),
        n_sequences=2,
        sequence_length=12,
        n_iter=1,
        max_duration=6,
    )
    written = hsmm_benchmark.write_benchmark_jsonl(rows, tmp_path / "benchmark_matrix.jsonl")
    payload = written.read_text(encoding="utf-8")
    records = [json.loads(line) for line in payload.splitlines()]

    assert len(records) == 1
    assert records[0]["benchmark_version"] == hsmm_benchmark.BENCHMARK_VERSION
    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in payload


def test_benchmark_matrix_local_mode_skips_missing_db(tmp_path):
    missing_db = tmp_path / "missing.duckdb"
    result = subprocess.run(
        ["bash", "scripts/hsmm_benchmark_matrix.sh"],
        cwd=REPO_ROOT,
        env=_script_env(HSMM_BENCHMARK_MODE="local", HSMM_BENCHMARK_DB=str(missing_db)),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "HSMM_BENCHMARK_STATUS=skipped reason=missing_db"


def test_benchmark_matrix_script_synthetic_smoke(tmp_path):
    output = tmp_path / "sample.jsonl"
    result = subprocess.run(
        ["bash", "scripts/hsmm_benchmark_matrix.sh"],
        cwd=REPO_ROOT,
        env=_script_env(
            HSMM_BENCHMARK_ENGINES="python",
            HSMM_BENCHMARK_N_JOBS="1",
            HSMM_BENCHMARK_N_ITER="1",
            HSMM_BENCHMARK_MAX_DURATION="6",
            HSMM_BENCHMARK_N_SEQUENCES="2",
            HSMM_BENCHMARK_SEQUENCE_LENGTH="12",
            HSMM_BENCHMARK_OUTPUT=str(output),
        ),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "HSMM_BENCHMARK_STATUS=pass mode=synthetic rows=1" in result.stdout
    assert output.exists()
