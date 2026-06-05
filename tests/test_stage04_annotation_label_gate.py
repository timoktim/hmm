from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

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


def _wp2_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "status": "pass",
        "index_id": "STAGE04-WP2",
        "report_version": "stage04_wp2_break_casebook_v1",
        "prospective_validation_status": "annotation_only",
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
    }
    payload.update(overrides)
    return payload


def _annotation_record(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "stage04_break_annotation_v1",
        "record_type": "annotation",
        "annotation_date": "2026-05-29",
        "diagnostic_trade_date": "2026-05-29",
        "break_warning_level": "watch",
        "component_stress_labels": "market:medium",
        "available_component_count": 3,
        "analyst_annotation": "needs_context",
        "observed_market_context": "public-safe research note",
        "followup_required": "no",
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


def _seed_inputs(tmp_path: Path, registry: dict[str, object] | None = None, wp2: dict[str, object] | None = None) -> tuple[Path, Path, Path, Path]:
    registry_path = tmp_path / "reports/stage04/split_registry.json"
    wp2_path = tmp_path / "reports/stage04/stage04_wp2_break_casebook_report.json"
    ledger_path = tmp_path / "reports/stage04/prospective_break_annotation.local.jsonl"
    db_path = tmp_path / "data/db/a_share_hmm.duckdb"
    _write_json(registry_path, registry or _registry_payload())
    _write_json(wp2_path, wp2 or _wp2_payload())
    return registry_path, wp2_path, ledger_path, db_path


def _evaluate(tmp_path: Path, *, registry: dict[str, object] | None = None, wp2: dict[str, object] | None = None, ledger_rows: list[dict[str, object]] | None = None, db_path: Path | None = None) -> dict:
    registry_path, wp2_path, ledger_path, default_db_path = _seed_inputs(tmp_path, registry=registry, wp2=wp2)
    if ledger_rows is not None:
        _write_jsonl(ledger_path, ledger_rows)
    return gate.evaluate_annotation_label_gate(
        gate.AnnotationLabelGateConfig(
            db_path=db_path or default_db_path,
            split_registry_path=registry_path,
            wp2_report_path=wp2_path,
            annotation_ledger_path=ledger_path,
        )
    )


def _write_calendar_db(path: Path, rows: list[tuple[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(path))
    try:
        con.execute("CREATE TABLE market_index_ohlcv(index_code VARCHAR, trade_date DATE)")
        con.executemany("INSERT INTO market_index_ohlcv VALUES (?, ?)", rows)
    finally:
        con.close()


def test_split_registry_lock_required_fields(tmp_path: Path) -> None:
    summary, issues = gate.validate_split_registry_lock(_registry_payload())
    assert not issues
    assert summary["expected_horizons"] == [1, 3, 5, 10, 20]

    broken = _registry_payload(final_holdout_consumption_count=1, threshold_tuning_after_lock="allowed")
    summary = _evaluate(tmp_path, registry=broken)

    assert summary["status"] == "blocked"
    assert "final holdout consumption count is not zero" in summary["blocking_issues"]
    assert "threshold tuning after lock is not forbidden" in summary["blocking_issues"]


def test_wp2_report_required_and_annotation_only(tmp_path: Path) -> None:
    summary, issues = gate.validate_wp2_report(_wp2_payload())
    assert not issues
    assert summary["prospective_validation_status"] == "annotation_only"

    bad_summary = _evaluate(tmp_path, wp2=_wp2_payload(status="blocked", prospective_validation_status="casebook_only"))

    assert bad_summary["status"] == "blocked"
    assert "Stage04-WP2 report status is not pass" in bad_summary["blocking_issues"]
    assert "Stage04-WP2 report is not annotation-only" in bad_summary["blocking_issues"]


def test_missing_annotation_ledger_is_not_failure(tmp_path: Path) -> None:
    summary = _evaluate(tmp_path)

    assert summary["status"] == "pass"
    assert summary["annotation_ledger_summary"]["annotation_record_count"] == 0
    assert summary["prospective_validation_status"] == "not_started"
    assert summary["label_completeness_summary"]["calendar"]["db_available"] == "no"


def test_annotation_record_boundary_validation(tmp_path: Path) -> None:
    valid_summary = _evaluate(tmp_path / "valid", ledger_rows=[_annotation_record()])

    assert valid_summary["status"] == "defer"
    assert valid_summary["annotation_ledger_summary"]["boundary_violation_count"] == 0
    assert valid_summary["label_completeness_summary"]["unknown_db_missing_record_count"] == 1

    pre_lock_summary = _evaluate(
        tmp_path / "pre_lock",
        ledger_rows=[_annotation_record(diagnostic_trade_date="2026-05-28")],
    )
    assert pre_lock_summary["status"] == "blocked"
    assert pre_lock_summary["annotation_record_sample"][0]["label_completeness_status"] == "pre_lock_violation"

    boundary_flags = dict(_annotation_record()["boundary_flags"])
    boundary_flags["external_data_fetch"] = "yes"
    flag_summary = _evaluate(tmp_path / "flag", ledger_rows=[_annotation_record(boundary_flags=boundary_flags)])
    assert flag_summary["status"] == "blocked"
    assert any("boundary flag external_data_fetch" in issue for issue in flag_summary["blocking_issues"])


def test_label_completeness_from_market_calendar(tmp_path: Path) -> None:
    registry_path, wp2_path, ledger_path, db_path = _seed_inputs(tmp_path)
    calendar = pd.bdate_range("2026-05-29", periods=35)
    _write_calendar_db(db_path, [("000300", day.date().isoformat()) for day in calendar])
    _write_jsonl(
        ledger_path,
        [
            _annotation_record(diagnostic_trade_date="2026-06-01"),
            _annotation_record(annotation_date="2026-07-01", diagnostic_trade_date=calendar[-3].date().isoformat()),
        ],
    )

    summary = gate.evaluate_annotation_label_gate(
        gate.AnnotationLabelGateConfig(
            db_path=db_path,
            split_registry_path=registry_path,
            wp2_report_path=wp2_path,
            annotation_ledger_path=ledger_path,
        )
    )

    statuses = [row["label_completeness_status"] for row in summary["annotation_record_sample"]]
    assert statuses == ["complete", "pending"]
    assert summary["annotation_record_sample"][0]["missing_horizons"] == []
    assert 20 in summary["annotation_record_sample"][1]["missing_horizons"]
    assert summary["prospective_validation_status"] == "collecting_annotations"


def test_uses_preferred_calendar_index(tmp_path: Path) -> None:
    db_path = tmp_path / "data/db/a_share_hmm.duckdb"
    _write_calendar_db(
        db_path,
        [
            ("000001", "2026-05-29"),
            ("000001", "2026-06-01"),
            ("000300", "2026-05-29"),
        ],
    )

    calendar = gate._load_market_calendar(db_path)

    assert calendar.selected_index_code == "000300"


def test_forbidden_terms_absent_from_outputs(tmp_path: Path) -> None:
    summary = _evaluate(
        tmp_path,
        ledger_rows=[_annotation_record(observed_market_context=gate._forbidden_output_terms()[0])],
    )
    markdown = gate.render_markdown(summary)
    payload = json.dumps(summary, ensure_ascii=False) + markdown

    assert summary["status"] == "blocked"
    assert not [term for term in gate._forbidden_output_terms() if term in payload]


def test_sample_csv_is_bounded_and_public_safe(tmp_path: Path) -> None:
    rows = [
        _annotation_record(
            annotation_date="2026-05-29",
            diagnostic_trade_date="2026-05-29",
            observed_market_context="long context " * 80,
        )
        for _ in range(205)
    ]
    summary = _evaluate(tmp_path, ledger_rows=rows)
    output = tmp_path / "out.md"
    summary_json = tmp_path / "out.json"
    sample_csv = tmp_path / "sample.csv"

    gate.write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv)
    sample = pd.read_csv(sample_csv)

    assert len(sample) == 200
    assert "observed_market_context" not in sample.columns
    assert list(sample.columns) == [
        "record_index",
        "record_type",
        "annotation_date",
        "diagnostic_trade_date",
        "break_warning_level",
        "label_completeness_status",
        "max_available_future_horizon",
        "missing_horizons",
        "boundary_status",
    ]


def test_cli_no_fetch_missing_db_clean_summary(tmp_path: Path) -> None:
    registry_path, wp2_path, ledger_path, db_path = _seed_inputs(tmp_path)
    output = tmp_path / "out.md"
    summary_json = tmp_path / "out.json"
    sample_csv = tmp_path / "sample.csv"

    status = gate.main(
        [
            "--db",
            str(db_path),
            "--split-registry",
            str(registry_path),
            "--wp2-report",
            str(wp2_path),
            "--annotation-ledger",
            str(ledger_path),
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--sample-csv",
            str(sample_csv),
            "--no-fetch",
        ]
    )

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert status == 0
    assert summary["status"] == "pass"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["annotation_ledger_summary"]["annotation_record_count"] == 0
    assert output.exists()
    assert sample_csv.exists()


def test_public_path_hygiene(tmp_path: Path) -> None:
    registry_path, wp2_path, ledger_path, db_path = _seed_inputs(tmp_path)
    output = tmp_path / "absolute-output.md"
    summary_json = tmp_path / "absolute-output.json"
    sample_csv = tmp_path / "absolute-output.csv"

    gate.main(
        [
            "--db",
            str(db_path),
            "--split-registry",
            str(registry_path),
            "--wp2-report",
            str(wp2_path),
            "--annotation-ledger",
            str(ledger_path),
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--sample-csv",
            str(sample_csv),
            "--no-fetch",
        ]
    )

    payload = summary_json.read_text(encoding="utf-8") + output.read_text(encoding="utf-8")
    assert "/" + "Users" + "/" not in payload
    assert "/" + "private" + "/" not in payload
    assert str(tmp_path) not in payload
