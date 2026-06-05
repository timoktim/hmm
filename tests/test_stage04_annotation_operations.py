from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

from src.evaluation import stage04_annotation_label_gate as gate
from src.evaluation import stage04_annotation_operations as ops


def _registry_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "locked",
        "evidence_cutoff_date": "2026-05-28",
        "future_holdout_start_rule": "strictly_after_evidence_cutoff_date",
        "expected_horizons": [1, 3, 5, 10, 20],
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "forbidden",
        "model_retraining_after_lock": "forbidden",
        "HMM_HSMM_retraining_after_lock": "forbidden",
        gate.HSMM_EXIT_USE_KEY: "no",
        gate.SURFACE_OUTPUT_KEY: "no",
        "external_data_fetch": "no",
        "private_db_required_in_ci": "no",
    }
    payload.update(overrides)
    return payload


def _wp3_payload(
    *,
    status: str = "pass",
    sample: list[dict[str, object]] | None = None,
    complete: int = 0,
    pending: int = 0,
    unknown: int = 0,
    pre_lock: int = 0,
    invalid: int = 0,
    **overrides: object,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": status,
        "index_id": "STAGE04-WP3",
        "report_version": "stage04_wp3_annotation_label_gate_v1",
        "prospective_validation_status": "collecting_annotations" if sample else "not_started",
        "annotation_ledger_summary": {"annotation_record_count": len(sample or [])},
        "label_completeness_summary": {
            "complete_record_count": complete,
            "pending_record_count": pending,
            "unknown_db_missing_record_count": unknown,
            "pre_lock_violation_record_count": pre_lock,
            "invalid_date_record_count": invalid,
            "required_horizons": [1, 3, 5, 10, 20],
            "label_completeness_status_counts": {
                key: value
                for key, value in {
                    "complete": complete,
                    "pending": pending,
                    "unknown_db_missing": unknown,
                    "pre_lock_violation": pre_lock,
                    "invalid_date": invalid,
                }.items()
                if value
            },
        },
        "annotation_record_sample": sample or [],
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
        "causal_boundary_summary": {
            "performance_metrics_computed": "no",
            "returns_or_outcomes_computed": "no",
        },
    }
    payload.update(overrides)
    return payload


def _wp4_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "pass",
        "index_id": "STAGE04-WP4",
        "report_version": "stage04_wp4_annotation_capture_v1",
        "mode": "dry-run",
        "capture_status": "candidate_created",
        "append_summary": {"appended_record_count": 0},
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
        "causal_boundary_summary": {
            "performance_metrics_computed": "no",
            "returns_or_outcomes_computed": "no",
        },
    }
    payload.update(overrides)
    return payload


def _record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "stage04_break_annotation_v1",
        "record_type": "annotation",
        "annotation_date": "2026-05-29",
        "diagnostic_trade_date": "2026-05-29",
        "break_warning_level": "watch",
        "component_stress_labels": "market:medium",
        "available_component_count": 1,
        "analyst_annotation": "needs_context",
        "observed_market_context": "operator research note",
        "followup_required": "yes",
        "forbidden_use_notice": "Research annotation only; diagnostic review note with no trading output.",
        "boundary_flags": {
            "external_data_fetch": "no",
            "model_retrained": "no",
            "hmm_hsmm_training_changed": "no",
            "hazard_model_changed": "no",
            "threshold_tuning": "no",
            "final_holdout_consumed": "no",
            "decision_engine_output": "no",
            "trading_output": "no",
        },
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(row, sort_keys=True) for row in rows) + "\n", encoding="utf-8")


def _seed_inputs(
    tmp_path: Path,
    *,
    registry: dict[str, object] | None = None,
    wp3: dict[str, object] | None = None,
    wp4: dict[str, object] | None = None,
    ledger_rows: list[dict[str, object]] | None = None,
) -> dict[str, Path]:
    paths = {
        "registry": tmp_path / "reports/stage04/split_registry.json",
        "wp3": tmp_path / "reports/stage04/stage04_wp3_annotation_label_gate_report.json",
        "wp4": tmp_path / "reports/stage04/stage04_wp4_annotation_capture_report.json",
        "ledger": tmp_path / "reports/stage04/prospective_break_annotation.local.jsonl",
        "output": tmp_path / "reports/stage04/stage04_wp5_annotation_operations_report.md",
        "summary": tmp_path / "reports/stage04/stage04_wp5_annotation_operations_report.json",
        "sample": tmp_path / "reports/stage04/stage04_wp5_annotation_operations_sample.csv",
    }
    _write_json(paths["registry"], registry or _registry_payload())
    _write_json(paths["wp3"], wp3 or _wp3_payload())
    _write_json(paths["wp4"], wp4 or _wp4_payload())
    if ledger_rows is not None:
        _write_jsonl(paths["ledger"], ledger_rows)
    return paths


def _config(tmp_path: Path, monkeypatch, **overrides: object) -> ops.AnnotationOperationsConfig:
    monkeypatch.setattr(ops, "_is_gitignored", lambda path, *, git_root: "yes")
    paths = _seed_inputs(
        tmp_path,
        registry=overrides.pop("registry", None),
        wp3=overrides.pop("wp3", None),
        wp4=overrides.pop("wp4", None),
        ledger_rows=overrides.pop("ledger_rows", None),
    )
    kwargs = {
        "split_registry_path": paths["registry"],
        "wp3_report_path": paths["wp3"],
        "wp4_report_path": paths["wp4"],
        "annotation_ledger_path": paths["ledger"],
        "git_root": tmp_path,
    }
    kwargs.update(overrides)
    return ops.AnnotationOperationsConfig(**kwargs)


def test_missing_ledger_passes_as_no_annotations(tmp_path: Path, monkeypatch) -> None:
    summary = ops.evaluate_annotation_operations(_config(tmp_path, monkeypatch))

    assert summary["status"] == "pass"
    assert summary["operations_status"] == "no_annotations_yet"
    assert summary["operations_rollup"]["annotation_record_count"] == 0
    assert summary["review_queue_sample"] == []


def test_valid_ledger_rollup_counts_records(tmp_path: Path, monkeypatch) -> None:
    rows = [
        _record(record_type="annotation", break_warning_level="watch", annotation_date="2026-05-29"),
        _record(record_type="review", break_warning_level="elevated", annotation_date="2026-05-30"),
        _record(record_type="candidate_check", break_warning_level="high", annotation_date="2026-05-31"),
        _record(record_type="template"),
    ]
    summary = ops.evaluate_annotation_operations(_config(tmp_path, monkeypatch, ledger_rows=rows))

    assert summary["status"] == "pass"
    assert summary["operations_rollup"]["annotation_record_count"] == 3
    assert summary["operations_rollup"]["template_record_count"] == 1
    assert summary["operations_rollup"]["record_type_counts"] == {"annotation": 1, "candidate_check": 1, "review": 1}
    assert summary["operations_rollup"]["warning_level_counts"] == {"elevated": 1, "high": 1, "watch": 1}


def test_boundary_violation_blocks_operations(tmp_path: Path, monkeypatch) -> None:
    summary = ops.evaluate_annotation_operations(
        _config(tmp_path, monkeypatch, ledger_rows=[_record(diagnostic_trade_date="2026-05-28")])
    )

    assert summary["status"] == "blocked"
    assert summary["operations_status"] == "blocked"
    assert summary["review_queue_sample"][0]["review_queue_status"] == "boundary_fix_required"


def test_wp3_defer_propagates_defer_without_blocking(tmp_path: Path, monkeypatch) -> None:
    sample = [
        {
            "record_index": 1,
            "record_type": "annotation",
            "annotation_date": "2026-05-29",
            "diagnostic_trade_date": "2026-05-29",
            "break_warning_level": "watch",
            "label_completeness_status": "unknown_db_missing",
            "boundary_status": "valid",
        }
    ]
    summary = ops.evaluate_annotation_operations(
        _config(
            tmp_path,
            monkeypatch,
            wp3=_wp3_payload(status="defer", sample=sample, unknown=1),
            ledger_rows=[_record()],
        )
    )

    assert summary["status"] == "defer"
    assert summary["causal_boundary_summary"]["performance_metrics_computed"] == "no"
    assert summary["causal_boundary_summary"]["returns_or_outcomes_computed"] == "no"
    assert summary["defer_reasons"]


def test_review_queue_prioritization(tmp_path: Path, monkeypatch) -> None:
    label_sample = [
        {"record_index": 1, "label_completeness_status": "pending"},
        {"record_index": 2, "label_completeness_status": "complete"},
        {"record_index": 3, "label_completeness_status": "pending"},
    ]
    rows = [
        _record(annotation_date="2026-06-02", break_warning_level="watch"),
        _record(annotation_date="2026-06-01", break_warning_level="high"),
        _record(annotation_date="2026-06-03", diagnostic_trade_date="2026-05-28"),
    ]
    summary = ops.evaluate_annotation_operations(
        _config(tmp_path, monkeypatch, wp3=_wp3_payload(sample=label_sample, complete=1, pending=2), ledger_rows=rows)
    )
    statuses = [row["review_queue_status"] for row in summary["review_queue_sample"]]

    assert statuses[:3] == ["boundary_fix_required", "ready_for_operator_review", "waiting_for_label_horizon"]


def test_no_long_context_in_sample(tmp_path: Path, monkeypatch) -> None:
    long_context = "public research context " * 80
    config = _config(tmp_path, monkeypatch, ledger_rows=[_record(observed_market_context=long_context)])
    summary = ops.evaluate_annotation_operations(config)
    output = tmp_path / "out.md"
    summary_json = tmp_path / "out.json"
    sample_csv = tmp_path / "sample.csv"
    ops.write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv)
    payload = output.read_text(encoding="utf-8") + summary_json.read_text(encoding="utf-8") + sample_csv.read_text(encoding="utf-8")

    assert long_context not in payload
    assert "observed_market_context" not in pd.read_csv(sample_csv).columns


def test_forbidden_terms_absent_and_rejected(tmp_path: Path, monkeypatch) -> None:
    forbidden = gate._forbidden_output_terms()[0]
    summary = ops.evaluate_annotation_operations(
        _config(tmp_path, monkeypatch, ledger_rows=[_record(observed_market_context=forbidden)])
    )
    payload = json.dumps(summary, ensure_ascii=False)

    assert summary["status"] == "blocked"
    assert not [term for term in gate._forbidden_output_terms() if term in payload]


def test_gitignore_required_for_local_ledger(tmp_path: Path, monkeypatch) -> None:
    paths = _seed_inputs(tmp_path, ledger_rows=[_record()])
    monkeypatch.setattr(ops, "_is_gitignored", lambda path, *, git_root: "no")
    summary = ops.evaluate_annotation_operations(
        ops.AnnotationOperationsConfig(
            split_registry_path=paths["registry"],
            wp3_report_path=paths["wp3"],
            wp4_report_path=paths["wp4"],
            annotation_ledger_path=paths["ledger"],
            git_root=tmp_path,
        )
    )

    assert summary["status"] == "blocked"
    assert "local annotation ledger is not confirmed gitignored" in summary["blocking_issues"]


def test_cli_no_fetch_clean(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(ops, "_is_gitignored", lambda path, *, git_root: "yes")
    paths = _seed_inputs(tmp_path, ledger_rows=[_record()])
    cmd = [
        sys.executable,
        "-m",
        "src.evaluation.stage04_annotation_operations",
        "--split-registry",
        str(paths["registry"]),
        "--wp3-report",
        str(paths["wp3"]),
        "--wp4-report",
        str(paths["wp4"]),
        "--annotation-ledger",
        "reports/stage04/prospective_break_annotation.local.jsonl",
        "--output",
        str(paths["output"]),
        "--summary-json",
        str(paths["summary"]),
        "--sample-csv",
        str(paths["sample"]),
        "--no-fetch",
    ]
    # Use a path under the repository for this CLI smoke so the real gitignore check applies.
    subprocess.run(cmd, cwd=ops.PROJECT_ROOT, check=True)
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))

    assert summary["status"] == "pass"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["final_holdout_consumed"] == "no"
    assert summary["causal_boundary_summary"]["returns_or_outcomes_computed"] == "no"


def test_public_path_hygiene(tmp_path: Path, monkeypatch) -> None:
    config = _config(tmp_path, monkeypatch, ledger_rows=[_record()])
    summary = ops.evaluate_annotation_operations(config)
    output = tmp_path / "stage04_wp5_annotation_operations_report.md"
    summary_json = tmp_path / "stage04_wp5_annotation_operations_report.json"
    sample_csv = tmp_path / "stage04_wp5_annotation_operations_sample.csv"
    ops.write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv)
    payload = output.read_text(encoding="utf-8") + summary_json.read_text(encoding="utf-8") + sample_csv.read_text(encoding="utf-8")

    assert ("/" + "Users/") not in payload
    assert ("/" + "private/") not in payload
    assert str(tmp_path) not in payload
