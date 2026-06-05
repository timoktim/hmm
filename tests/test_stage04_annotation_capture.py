from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from src.evaluation import stage04_annotation_capture as capture
from src.evaluation import stage04_annotation_label_gate as gate


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


def _wp1_payload(*, level: str = "watch", trade_date: str = "2026-05-29", **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "pass",
        "index_id": "STAGE04-WP1",
        "report_version": "stage04_wp1_break_detector_v1",
        "latest_break_warning": {
            "trade_date": trade_date,
            "break_warning_level": level,
            "component_stress_labels": "market:medium;sector:medium",
            "available_component_count": 3,
        },
    }
    payload.update(overrides)
    return payload


def _wp2_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "pass",
        "index_id": "STAGE04-WP2",
        "report_version": "stage04_wp2_break_casebook_v1",
        "casebook_sample": [
            {
                "episode_id": "stage04-wp2-episode-001",
                "end_date": "2026-05-31",
                "peak_warning_level": "high",
                "peak_component_stress_labels": "breadth:high",
                "first_component_stress_labels": "breadth:medium",
                "available_component_count_max": 4,
            }
        ],
    }
    payload.update(overrides)
    return payload


def _wp3_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "pass",
        "index_id": "STAGE04-WP3",
        "report_version": "stage04_wp3_annotation_label_gate_v1",
        "prospective_validation_status": "not_started",
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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _seed_inputs(
    tmp_path: Path,
    *,
    registry: dict[str, object] | None = None,
    wp1: dict[str, object] | None = None,
    wp2: dict[str, object] | None = None,
    wp3: dict[str, object] | None = None,
) -> dict[str, Path]:
    paths = {
        "registry": tmp_path / "reports/stage04/split_registry.json",
        "wp1": tmp_path / "reports/stage04/stage04_wp1_break_detector_report.json",
        "wp2": tmp_path / "reports/stage04/stage04_wp2_break_casebook_report.json",
        "wp3": tmp_path / "reports/stage04/stage04_wp3_annotation_label_gate_report.json",
        "ledger": tmp_path / "reports/stage04/prospective_break_annotation.local.jsonl",
        "output": tmp_path / "reports/stage04/stage04_wp4_annotation_capture_report.md",
        "summary": tmp_path / "reports/stage04/stage04_wp4_annotation_capture_report.json",
        "sample": tmp_path / "reports/stage04/stage04_wp4_annotation_capture_sample.jsonl",
    }
    _write_json(paths["registry"], registry or _registry_payload())
    _write_json(paths["wp1"], wp1 or _wp1_payload())
    _write_json(paths["wp2"], wp2 or _wp2_payload())
    _write_json(paths["wp3"], wp3 or _wp3_payload())
    return paths


def _config(tmp_path: Path, **overrides: object) -> capture.AnnotationCaptureConfig:
    paths = _seed_inputs(
        tmp_path,
        registry=overrides.pop("registry", None),
        wp1=overrides.pop("wp1", None),
        wp2=overrides.pop("wp2", None),
        wp3=overrides.pop("wp3", None),
    )
    kwargs = {
        "split_registry_path": paths["registry"],
        "wp1_report_path": paths["wp1"],
        "wp2_report_path": paths["wp2"],
        "wp3_report_path": paths["wp3"],
        "annotation_ledger_path": paths["ledger"],
        "git_root": tmp_path,
    }
    kwargs.update(overrides)
    return capture.AnnotationCaptureConfig(**kwargs)


def test_dry_run_latest_wp1_creates_candidate_when_warning(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="dry-run", source="latest_wp1")
    summary = capture.evaluate_annotation_capture(config)

    assert summary["status"] == "pass"
    assert summary["capture_status"] == "candidate_created"
    assert summary["candidate_record_public_preview"]["diagnostic_trade_date"] == "2026-05-29"
    assert not config.annotation_ledger_path.exists()


def test_latest_wp1_no_candidate_for_normal(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="dry-run", source="latest_wp1", wp1=_wp1_payload(level="normal"))
    summary = capture.evaluate_annotation_capture(config)
    sample = tmp_path / "sample.jsonl"
    capture.write_outputs(summary, output=tmp_path / "out.md", summary_json=tmp_path / "out.json", sample_jsonl=sample)
    sample_lines = sample.read_text(encoding="utf-8").splitlines()

    assert summary["status"] == "pass"
    assert summary["capture_status"] == "no_candidate"
    assert summary["candidate_record_public_preview"] is None
    assert len(sample_lines) == 1
    assert json.loads(sample_lines[0])["record_type"] == "no_candidate"
    assert not config.annotation_ledger_path.exists()


def test_casebook_episode_source_uses_episode_end_date(tmp_path: Path) -> None:
    config = _config(tmp_path, source="casebook_episode", episode_id="stage04-wp2-episode-001")
    summary = capture.evaluate_annotation_capture(config)

    assert summary["status"] == "pass"
    assert summary["capture_status"] == "candidate_created"
    assert summary["candidate_record_public_preview"]["diagnostic_trade_date"] == "2026-05-31"
    assert summary["candidate_record_public_preview"]["break_warning_level"] == "high"


def test_manual_source_requires_fields(tmp_path: Path) -> None:
    missing = capture.evaluate_annotation_capture(_config(tmp_path / "missing", source="manual"))
    assert missing["status"] == "blocked"
    assert missing["capture_status"] == "blocked"

    valid = capture.evaluate_annotation_capture(
        _config(
            tmp_path / "valid",
            source="manual",
            diagnostic_trade_date="2026-05-29",
            break_warning_level="elevated",
            component_stress_labels="breadth:medium",
            available_component_count=2,
        )
    )
    assert valid["status"] == "pass"
    assert valid["capture_status"] == "candidate_created"


def test_append_mode_appends_one_record_only_when_gitignored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_is_gitignored", lambda path, *, git_root: "yes")
    config = _config(
        tmp_path,
        mode="append",
        source="manual",
        diagnostic_trade_date="2026-05-29",
        break_warning_level="watch",
        component_stress_labels="market:medium",
        available_component_count=1,
    )

    first = capture.evaluate_annotation_capture(config)
    second = capture.evaluate_annotation_capture(config)
    lines = config.annotation_ledger_path.read_text(encoding="utf-8").splitlines()

    assert first["capture_status"] == "appended"
    assert second["capture_status"] == "appended"
    assert len(lines) == 2
    assert [json.loads(line)["record_type"] for line in lines] == ["annotation", "annotation"]


def test_append_blocks_when_ledger_not_gitignored(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(capture, "_is_gitignored", lambda path, *, git_root: "no")
    config = _config(
        tmp_path,
        mode="append",
        source="manual",
        diagnostic_trade_date="2026-05-29",
        break_warning_level="watch",
        component_stress_labels="market:medium",
        available_component_count=1,
    )
    summary = capture.evaluate_annotation_capture(config)

    assert summary["status"] == "blocked"
    assert summary["capture_status"] == "blocked"
    assert not config.annotation_ledger_path.exists()


def test_pre_cutoff_diagnostic_date_blocks(tmp_path: Path) -> None:
    summary = capture.evaluate_annotation_capture(
        _config(
            tmp_path,
            source="manual",
            diagnostic_trade_date="2026-05-28",
            break_warning_level="watch",
            component_stress_labels="market:medium",
            available_component_count=1,
        )
    )

    assert summary["status"] == "blocked"
    assert any("not after the evidence cutoff" in issue for issue in summary["blocking_issues"])


def test_forbidden_terms_absent_and_rejected(tmp_path: Path) -> None:
    forbidden = gate._forbidden_output_terms()[0]
    summary = capture.evaluate_annotation_capture(
        _config(
            tmp_path,
            source="manual",
            diagnostic_trade_date="2026-05-29",
            break_warning_level="watch",
            component_stress_labels="market:medium",
            available_component_count=1,
            observed_market_context=forbidden,
        )
    )
    payload = json.dumps(summary, ensure_ascii=False)

    assert summary["status"] == "blocked"
    assert not [term for term in gate._forbidden_output_terms() if term in payload]


def test_public_preview_sanitizes_long_context(tmp_path: Path) -> None:
    long_context = "public context " * 80
    config = _config(
        tmp_path,
        source="manual",
        diagnostic_trade_date="2026-05-29",
        break_warning_level="watch",
        component_stress_labels="market:medium",
        available_component_count=1,
        observed_market_context=long_context,
    )
    summary = capture.evaluate_annotation_capture(config)
    capture.write_outputs(summary, output=tmp_path / "out.md", summary_json=tmp_path / "out.json", sample_jsonl=tmp_path / "sample.jsonl")
    payload = (tmp_path / "out.json").read_text(encoding="utf-8") + (tmp_path / "sample.jsonl").read_text(encoding="utf-8")

    assert summary["status"] == "pass"
    assert summary["candidate_record_public_preview"]["observed_market_context_present"] == "yes"
    assert summary["candidate_record_public_preview"]["observed_market_context_preview_chars"] == 80
    assert long_context not in payload


def test_script_or_cli_no_fetch_clean(tmp_path: Path) -> None:
    paths = _seed_inputs(tmp_path)
    cmd = [
        sys.executable,
        "-m",
        "src.evaluation.stage04_annotation_capture",
        "--split-registry",
        str(paths["registry"]),
        "--wp1-report",
        str(paths["wp1"]),
        "--wp2-report",
        str(paths["wp2"]),
        "--wp3-report",
        str(paths["wp3"]),
        "--annotation-ledger",
        str(paths["ledger"]),
        "--output",
        str(paths["output"]),
        "--summary-json",
        str(paths["summary"]),
        "--sample-jsonl",
        str(paths["sample"]),
        "--source",
        "manual",
        "--diagnostic-trade-date",
        "2026-05-29",
        "--break-warning-level",
        "watch",
        "--component-stress-labels",
        "market:medium",
        "--available-component-count",
        "1",
        "--mode",
        "dry-run",
        "--no-fetch",
    ]
    subprocess.run(cmd, cwd=capture.PROJECT_ROOT, check=True)
    summary = json.loads(paths["summary"].read_text(encoding="utf-8"))

    assert summary["status"] == "pass"
    assert summary["capture_status"] == "candidate_created"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["final_holdout_consumed"] == "no"
    assert not paths["ledger"].exists()


def test_public_path_hygiene(tmp_path: Path) -> None:
    config = _config(
        tmp_path,
        source="manual",
        diagnostic_trade_date="2026-05-29",
        break_warning_level="watch",
        component_stress_labels="market:medium",
        available_component_count=1,
    )
    summary = capture.evaluate_annotation_capture(config)
    output = tmp_path / "stage04_wp4_annotation_capture_report.md"
    summary_json = tmp_path / "stage04_wp4_annotation_capture_report.json"
    sample_jsonl = tmp_path / "stage04_wp4_annotation_capture_sample.jsonl"
    capture.write_outputs(summary, output=output, summary_json=summary_json, sample_jsonl=sample_jsonl)
    payload = output.read_text(encoding="utf-8") + summary_json.read_text(encoding="utf-8") + sample_jsonl.read_text(encoding="utf-8")

    assert ("/" + "Users/") not in payload
    assert ("/" + "private/") not in payload
    assert str(tmp_path) not in payload
