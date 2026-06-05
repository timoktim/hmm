from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.evaluation import stage04_break_casebook as casebook


FORBIDDEN_TERMS = {
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
}


def _diagnostic_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "trade_date": "2026-01-01",
                "break_warning_level": "normal",
                "available_component_count": 3,
                "component_stress_labels": "",
            },
            {
                "trade_date": "2026-01-02",
                "break_warning_level": "watch",
                "available_component_count": 3,
                "medium_stress_component_count": 1,
                "component_stress_labels": "market:medium",
                "market_volatility_z": 1.2,
                "market_return_1d": -0.01,
                "market_component_present": True,
            },
            {
                "trade_date": "2026-01-03",
                "break_warning_level": "elevated",
                "available_component_count": 3,
                "high_stress_component_count": 1,
                "component_stress_labels": "market:high;breadth:medium",
                "market_volatility_z": 2.4,
                "market_return_1d": -0.03,
                "breadth_stress_score": 1.4,
                "sector_dispersion_z": 0.4,
                "market_component_present": True,
                "breadth_component_present": True,
            },
            {
                "trade_date": "2026-01-04",
                "break_warning_level": "high",
                "available_component_count": 4,
                "high_stress_component_count": 2,
                "component_stress_labels": "market:high;sector:high",
                "market_volatility_z": 3.0,
                "market_return_1d": -0.05,
                "sector_dispersion_z": 2.5,
                "hmm_stress_score": 0.2,
                "market_component_present": True,
                "sector_component_present": True,
                "hmm_confidence_component_present": True,
            },
            {
                "trade_date": "2026-01-05",
                "break_warning_level": "normal",
                "available_component_count": 4,
                "component_stress_labels": "",
            },
            {
                "trade_date": "2026-01-06",
                "break_warning_level": "watch",
                "available_component_count": 2,
                "medium_stress_component_count": 1,
                "component_stress_labels": "sector:medium",
                "sector_dispersion_z": 1.1,
                "sector_component_present": True,
            },
        ]
    )


def _registry_payload(**overrides: object) -> dict:
    payload = {
        "status": "locked",
        "evidence_cutoff_date": "2026-05-28",
        "future_holdout_start_rule": "strictly_after_evidence_cutoff_date",
        "expected_horizons": [1, 3, 5, 10, 20],
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "forbidden",
        "model_retraining_after_lock": "forbidden",
        "decision_surface_output": "no",
        "external_data_fetch": "no",
        "future_holdout_policy": {
            "minimum_candidate_holdout_start_date": "2026-05-29",
            "required_label_horizons": [1, 3, 5, 10, 20],
        },
    }
    payload.update(overrides)
    return payload


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")


def _seed_inputs(tmp_path: Path, registry: dict | None = None) -> tuple[Path, Path, Path]:
    registry_path = tmp_path / "reports/stage04/split_registry.json"
    wp1_path = tmp_path / "reports/stage04/stage04_wp1_break_detector_report.json"
    db_path = tmp_path / "data/db/a_share_hmm.duckdb"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db_path.write_text("placeholder", encoding="utf-8")
    _write_json(registry_path, registry or _registry_payload())
    _write_json(
        wp1_path,
        {
            "status": "pass",
            "index_id": "STAGE04-WP1",
            "report_version": "stage04_wp1_break_detector_v1",
            "latest_break_warning": {"trade_date": "2026-01-06", "break_warning_level": "watch"},
            "causal_sanity_summary": {
                "rolling_baseline_excludes_current_row": "yes",
                "future_rows_used": "no",
            },
        },
    )
    return registry_path, wp1_path, db_path


def test_episode_extraction_contiguous_warning_runs() -> None:
    episodes = casebook.extract_warning_episodes(_diagnostic_frame())

    assert len(episodes) == 2
    assert episodes[0]["start_date"] == "2026-01-02"
    assert episodes[0]["end_date"] == "2026-01-04"
    assert episodes[0]["duration_observations"] == 3
    assert episodes[0]["peak_warning_level"] == "high"
    assert episodes[1]["start_date"] == "2026-01-06"


def test_episode_severity_order() -> None:
    episodes = [
        {"episode_id": "watch-new", "peak_warning_level": "watch", "severity_rank": 2, "end_date": "2026-01-10"},
        {"episode_id": "elevated-mid", "peak_warning_level": "elevated", "severity_rank": 3, "end_date": "2026-01-09"},
        {"episode_id": "high-old", "peak_warning_level": "high", "severity_rank": 4, "end_date": "2026-01-01"},
        {"episode_id": "high-new", "peak_warning_level": "high", "severity_rank": 4, "end_date": "2026-01-08"},
    ]

    sample = casebook.build_casebook_sample(episodes, max_cases=3)

    assert [row["episode_id"] for row in sample] == ["high-new", "high-old", "elevated-mid"]


def test_split_registry_lock_blocks_on_tuning_or_consumption(tmp_path: Path, monkeypatch) -> None:
    registry_path, wp1_path, db_path = _seed_inputs(
        tmp_path,
        _registry_payload(final_holdout_consumption_count=1, threshold_tuning_after_lock="allowed"),
    )
    monkeypatch.setattr(
        casebook,
        "_wp1_full_diagnostic_from_db",
        lambda _: (
            {"status": "pass", "latest_break_warning": {"trade_date": "2026-01-06", "break_warning_level": "watch"}},
            _diagnostic_frame(),
        ),
    )

    summary = casebook.evaluate_casebook(
        casebook.BreakCasebookConfig(db_path=db_path, split_registry_path=registry_path, wp1_summary_path=wp1_path)
    )

    assert summary["status"] == "blocked"
    assert "final holdout consumption count is not zero" in summary["blocking_issues"]
    assert "threshold tuning after lock is not forbidden" in summary["blocking_issues"]


def test_annotation_template_has_required_boundary_flags() -> None:
    record = casebook.build_annotation_template_record()

    assert record["record_type"] == "template"
    assert record["schema_version"] == "stage04_break_annotation_v1"
    assert record["boundary_flags"]["external_data_fetch"] == "no"
    assert record["boundary_flags"]["final_holdout_consumed"] == "no"
    assert record["boundary_flags"]["trading_output"] == "no"
    assert "not a trading signal" in record["forbidden_use_notice"]


def test_report_forbidden_terms_absent(tmp_path: Path, monkeypatch) -> None:
    registry_path, wp1_path, db_path = _seed_inputs(tmp_path)
    monkeypatch.setattr(
        casebook,
        "_wp1_full_diagnostic_from_db",
        lambda _: (
            {
                "status": "pass",
                "latest_break_warning": {"trade_date": "2026-01-06", "break_warning_level": "watch"},
                "causal_sanity_summary": {
                    "rolling_baseline_excludes_current_row": "yes",
                    "future_rows_used": "no",
                },
            },
            _diagnostic_frame(),
        ),
    )

    summary = casebook.evaluate_casebook(
        casebook.BreakCasebookConfig(db_path=db_path, split_registry_path=registry_path, wp1_summary_path=wp1_path)
    )
    markdown = casebook.render_markdown(summary)
    payload = json.dumps(summary, ensure_ascii=False) + markdown

    assert summary["status"] == "pass"
    assert not [term for term in FORBIDDEN_TERMS if term in payload]


def test_cli_no_fetch_missing_db_blocks_cleanly(tmp_path: Path) -> None:
    registry_path, wp1_path, _ = _seed_inputs(tmp_path)
    missing_db = tmp_path / "missing.duckdb"
    output = tmp_path / "out.md"
    summary_json = tmp_path / "out.json"
    sample_csv = tmp_path / "sample.csv"
    template = tmp_path / "template.jsonl"

    status = casebook.main(
        [
            "--db",
            str(missing_db),
            "--split-registry",
            str(registry_path),
            "--wp1-summary",
            str(wp1_path),
            "--output",
            str(output),
            "--summary-json",
            str(summary_json),
            "--sample-csv",
            str(sample_csv),
            "--annotation-template",
            str(template),
            "--no-fetch",
        ]
    )

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert status == 0
    assert summary["status"] == "blocked"
    assert summary["boundary_flags"]["external_data_fetch"] == "no"
    assert summary["input_summary"]["db_available"] == "no"
    assert output.exists()
    assert sample_csv.exists()
    assert template.exists()


def test_casebook_does_not_write_full_diagnostic_csv(tmp_path: Path, monkeypatch) -> None:
    registry_path, wp1_path, db_path = _seed_inputs(tmp_path)
    monkeypatch.setattr(
        casebook,
        "_wp1_full_diagnostic_from_db",
        lambda _: (
            {"status": "pass", "latest_break_warning": {"trade_date": "2026-01-06", "break_warning_level": "watch"}},
            _diagnostic_frame(),
        ),
    )

    summary = casebook.run_from_paths(
        db=db_path,
        split_registry=registry_path,
        wp1_summary=wp1_path,
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        sample_csv=tmp_path / "sample.csv",
        annotation_template=tmp_path / "template.jsonl",
        max_cases=20,
    )

    sample_rows = pd.read_csv(tmp_path / "sample.csv")
    assert summary["status"] == "pass"
    assert len(sample_rows) <= 20
    assert not list(tmp_path.glob("*full*.csv"))


def test_public_path_hygiene(tmp_path: Path) -> None:
    registry_path, wp1_path, _ = _seed_inputs(tmp_path)
    summary = casebook.run_from_paths(
        db=tmp_path / "missing.duckdb",
        split_registry=registry_path,
        wp1_summary=wp1_path,
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        sample_csv=tmp_path / "sample.csv",
        annotation_template=tmp_path / "template.jsonl",
    )
    payload = json.dumps(summary, ensure_ascii=False) + (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "/Users/" not in payload
    assert "/private/" not in payload
    assert str(tmp_path) not in payload
