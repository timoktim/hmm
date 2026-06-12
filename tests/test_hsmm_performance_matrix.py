from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from src.evaluation import hsmm_performance_matrix
from src.models import hsmm_benchmark, hsmm_core
from src.models.hsmm_performance_presets import (
    FORBIDDEN_VITERBI_FLAGS,
    DEFAULT_PRESET_CONFIG_PATH,
    load_hsmm_performance_preset_config,
    load_hsmm_performance_presets,
    validate_hsmm_performance_preset_config,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MATRIX_COLUMNS = {
    "profile_id",
    "profile_mode",
    "status",
    "sequence_count",
    "sequence_length",
    "n_states",
    "max_duration",
    "n_iter",
    "engine_requested",
    "engine_used",
    "engine_fallback_reason",
    "numba_available",
    "numba_compile_warmed",
    "n_jobs",
    "fit_n_jobs",
    "fit_n_jobs_resolved",
    "sequence_chunk_size",
    "fit_parallel_enabled",
    "fit_parallel_fallback",
    "fit_parallel_warning",
    "fit_iteration_count",
    "fit_decode_seconds",
    "fit_update_seconds",
    "snapshot_decode_mode",
    "snapshot_decode_seconds_if_available",
    "total_runtime_seconds",
    "bottleneck_classification",
    "no_db_write",
    "persistent_db_writes",
}
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
    env.pop("HSMM_PERF_LOCAL_DB", None)
    env.update(overrides)
    return env


def _simulate_numba_missing(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setattr(hsmm_core, "_NUMBA_KERNEL", None)
    monkeypatch.setattr(hsmm_core, "_NUMBA_LOAD_ATTEMPTED", False)
    monkeypatch.setattr(hsmm_core, "_NUMBA_LOAD_ERROR", None)
    monkeypatch.setattr(hsmm_core, "_NUMBA_COMPILE_WARMED", False)

    def _raise_missing():
        raise RuntimeError("simulated numba missing")

    monkeypatch.setattr(hsmm_core, "_load_numba_kernel", _raise_missing)


def test_synthetic_profile_matrix_returns_required_columns():
    rows = hsmm_performance_matrix.run_synthetic_profile_matrix(
        engines=("python",),
        n_iters=(1,),
        max_durations=(6,),
        fit_n_jobs_values=(1,),
        sequence_chunk_sizes=(2,),
        n_sequences=2,
        sequence_length=12,
        auto_jobs=1,
    )

    assert len(rows) == 1
    assert REQUIRED_MATRIX_COLUMNS.issubset(rows[0])
    assert rows[0]["status"] == "pass"
    assert rows[0]["no_db_write"] == "yes"
    assert rows[0]["persistent_db_writes"] == "no"


def test_synthetic_cli_does_not_require_duckdb(tmp_path):
    output = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    summary_csv = tmp_path / "summary.csv"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.hsmm_performance_matrix",
            "--mode",
            "synthetic",
            "--no-db-write",
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--summary-csv",
            str(summary_csv),
            "--preset-config",
            str(DEFAULT_PRESET_CONFIG_PATH),
        ],
        cwd=REPO_ROOT,
        env=_script_env(HSMM_PERF_SYNTHETIC_AUTO_JOBS="1"),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["mode"] == "synthetic"
    assert payload["summary"]["profile_count"] == 32
    assert output.exists()
    assert summary_csv.exists()


def test_missing_local_db_skips_without_failure(tmp_path):
    output = tmp_path / "local_report.md"
    summary_json = tmp_path / "local_report.json"
    summary_csv = tmp_path / "local_summary.csv"
    missing_db = tmp_path / "missing.duckdb"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "src.evaluation.hsmm_performance_matrix",
            "--mode",
            "local",
            "--db",
            str(missing_db),
            "--profile-only",
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--summary-csv",
            str(summary_csv),
            "--preset-config",
            str(DEFAULT_PRESET_CONFIG_PATH),
        ],
        cwd=REPO_ROOT,
        env=_script_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["status"] == "skipped"
    assert payload["summary"]["local_profile_status"] == "skipped_missing_db"
    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in summary_json.read_text(encoding="utf-8")
        assert term not in output.read_text(encoding="utf-8")


def test_preset_config_validates_maintenance_semantics():
    payload = load_hsmm_performance_preset_config(DEFAULT_PRESET_CONFIG_PATH)
    assert validate_hsmm_performance_preset_config(payload) == []
    presets = load_hsmm_performance_presets(DEFAULT_PRESET_CONFIG_PATH)

    assert presets["fast_maintenance"].n_iter in {8, 9, 10}
    assert presets["fast_maintenance"].max_duration == 40
    assert presets["standard_maintenance"].n_iter == 20
    assert presets["standard_maintenance"].max_duration == 60
    assert presets["full_maintenance"].n_iter >= presets["standard_maintenance"].n_iter


def test_no_preset_enables_approximate_or_pruned_viterbi():
    payload = load_hsmm_performance_preset_config(DEFAULT_PRESET_CONFIG_PATH)
    for preset in payload["presets"].values():
        for flag in FORBIDDEN_VITERBI_FLAGS:
            assert preset.get(flag) is False


def test_numba_unavailable_auto_mode_records_fallback(monkeypatch):
    _simulate_numba_missing(monkeypatch)

    rows = hsmm_performance_matrix.run_synthetic_profile_matrix(
        engines=("auto",),
        n_iters=(1,),
        max_durations=(6,),
        fit_n_jobs_values=(1,),
        sequence_chunk_sizes=(2,),
        n_sequences=2,
        sequence_length=12,
        auto_jobs=1,
    )

    assert rows[0]["status"] == "pass"
    assert rows[0]["engine_used"] == "python"
    assert rows[0]["engine_fallback_reason"] != "none"


def test_required_numba_mode_can_fail_clearly_when_unavailable(monkeypatch):
    _simulate_numba_missing(monkeypatch)

    result = hsmm_benchmark.check_hsmm_numba_engine(required=True)

    assert result["status"] == "failed"
    assert result["requested_engine"] == "numba"
    assert result["fallback_reason"] != "none"


def test_fit_parallel_fallback_fields_are_present():
    rows = hsmm_performance_matrix.run_synthetic_profile_matrix(
        engines=("python",),
        n_iters=(1,),
        max_durations=(6,),
        fit_n_jobs_values=("auto",),
        sequence_chunk_sizes=(2,),
        n_sequences=2,
        sequence_length=12,
        auto_jobs=1,
    )

    assert "fit_parallel_fallback" in rows[0]
    assert "fit_parallel_warning" in rows[0]


def test_bottleneck_classification_is_deterministic():
    row = {
        "fit_decode_seconds": 0.8,
        "fit_update_seconds": 0.1,
        "snapshot_decode_seconds_if_available": 0.1,
    }

    assert hsmm_performance_matrix.classify_bottleneck(row) == "fit_decode_dominant"


def test_reports_contain_no_private_paths_or_decision_terms(tmp_path):
    rows = hsmm_performance_matrix.run_synthetic_profile_matrix(
        engines=("python",),
        n_iters=(1,),
        max_durations=(6,),
        fit_n_jobs_values=(1,),
        sequence_chunk_sizes=(2,),
        n_sequences=2,
        sequence_length=12,
        auto_jobs=1,
    )
    payload = hsmm_performance_matrix.build_payload(
        rows=rows,
        mode="synthetic",
        preset_config=DEFAULT_PRESET_CONFIG_PATH,
        local_profile_status="not_run",
        local_db_path="not_run",
    )
    output = tmp_path / "report.md"
    summary_json = tmp_path / "report.json"
    summary_csv = tmp_path / "summary.csv"
    hsmm_performance_matrix.write_outputs(payload, output=output, summary_json=summary_json, summary_csv=summary_csv)
    public_text = "\n".join(
        [
            output.read_text(encoding="utf-8"),
            summary_json.read_text(encoding="utf-8"),
            summary_csv.read_text(encoding="utf-8"),
        ]
    )

    for term in FORBIDDEN_PUBLIC_TERMS:
        assert term not in public_text


def test_no_trading_or_decision_output_fields_are_created():
    rows = hsmm_performance_matrix.run_synthetic_profile_matrix(
        engines=("python",),
        n_iters=(1,),
        max_durations=(6,),
        fit_n_jobs_values=(1,),
        sequence_chunk_sizes=(2,),
        n_sequences=2,
        sequence_length=12,
        auto_jobs=1,
    )

    serialized = json.dumps(rows, ensure_ascii=False)
    for term in ["trade_signal", "buy_signal", "sell_signal", "decision_ready", "decision_surface"]:
        assert term not in serialized
