from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from src.evaluation.stage03v_full_target_audit import (
    TARGET_KIND,
    build_full_target_audit_report,
    compare_slice_support,
    stream_full_target_audit,
    validate_target_rows_dataframe,
)
from src.evaluation.stage03v_risk_target_dataset import SliceSpec
from src.evaluation.stage03v_target_controls import detect_feature_namespace_violations, run_cross_cutoff_regression


SLICE = SliceSpec(
    horizon=1,
    threshold_value=0.05,
    threshold_type="fixed",
    source_target_kind="sw2021_l2_downside_event",
    feasibility_verdict="eligible",
    target_usage="eligible",
)


def _prices() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_id": ["industry:A"] * 3 + ["industry:B"] * 3,
            "trade_date": pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-03"] * 2),
            "close": [100.0, 99.0, 98.0, 100.0, 101.0, 102.0],
        }
    )


def _universe(ids: list[str] | None = None) -> dict:
    ids = ids or ["industry:A", "industry:B"]
    return {
        "entities": [{"entity_id": item, "entity_segment_id": f"{item}::segment_1"} for item in ids],
        "silent_entity_break_entities": [{"entity_id": "industry:break"}],
    }


def _universe_frame(ids: list[str] | None = None) -> pd.DataFrame:
    ids = ids or ["industry:A", "industry:B"]
    return pd.DataFrame(
        [{"entity_id": item, "sector_name": item, "entity_segment_id": f"{item}::segment_1"} for item in ids]
    )


def _support(target_rows: int = 6, *, usage: str = "eligible") -> dict:
    labeled = 4
    insufficient = target_rows - labeled
    return {
        "status": "pass",
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "entity_count_after_silent_break_handling": 124,
        "silent_entity_break_handling": "excluded",
        "target_row_count": target_rows,
        "slice_support_summary": [
            {
                "horizon": 1,
                "threshold_type": "fixed",
                "threshold_value": 0.05,
                "target_kind": TARGET_KIND,
                "target_usage": usage,
                "target_row_count": target_rows,
                "labeled_count": labeled,
                "positive_event_count": 0,
                "insufficient_future_price_count": insufficient,
            }
        ],
    }


def _controls() -> dict:
    return {
        "status": "pass",
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
        "v7_coverage_available": "yes",
        "sw2021_l2_universe_coverage": "pass",
        "entity_count_after_silent_break_handling": 124,
        "cross_cutoff_regression_passed": "yes",
        "purge_violation_count": 0,
        "embargo_violation_count": 0,
        "feature_namespace_policy_status": "pass",
    }


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "trade_date": "2026-01-01",
        "entity_id": "industry:A",
        "entity_segment_id": "industry:A::segment_1",
        "split_role": "historical_development",
        "target_usage": "eligible",
        "horizon": 1,
        "threshold_type": "fixed",
        "threshold_value": 0.05,
        "target_kind": TARGET_KIND,
        "target_observation_start_date": "2026-01-02",
        "target_observation_end_date": "2026-01-02",
        "future_return": -0.01,
        "future_mae": -0.01,
        "future_mdd": 0.01,
        "future_realized_vol": 0.0,
        "future_downside_vol": 0.0,
        "event_label": False,
        "censoring_status": "labeled",
        "sample_weight": 1.0,
        "source_db_path": "data/db/a_share_hmm_tushare_v7.duckdb",
    }
    row.update(overrides)
    return row


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_streaming_chunks_aggregate_to_exact_full_row_count() -> None:
    result = stream_full_target_audit(
        price_frame=_prices(),
        universe_frame=_universe_frame(),
        slices=[SLICE],
        target_support=_support(),
        target_universe_manifest=_universe(),
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        chunk_size=2,
    )

    assert result["full_target_rows_checked"] == 6
    assert result["chunk_count"] == 3
    assert max(chunk["rows_checked"] for chunk in result["chunk_summaries"]) == 2
    assert result["violation_count_total"] == 0


def test_duplicate_target_keys_are_detected() -> None:
    result = stream_full_target_audit(
        price_frame=_prices().query("entity_id == 'industry:A'"),
        universe_frame=_universe_frame(["industry:A"]),
        slices=[SLICE, SLICE],
        target_support=_support(target_rows=3),
        target_universe_manifest=_universe(["industry:A"]),
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        chunk_size=10,
    )

    assert result["violation_counts"]["duplicate_target_key_count"] > 0


def test_invalid_entity_outside_target_universe_is_detected() -> None:
    result = stream_full_target_audit(
        price_frame=_prices(),
        universe_frame=_universe_frame(["industry:A"]),
        slices=[SLICE],
        target_support=_support(),
        target_universe_manifest=_universe(["industry:A"]),
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        chunk_size=10,
    )

    assert result["violation_counts"]["entity_not_in_target_universe_count"] == 3


def test_invalid_slice_and_target_usage_are_detected() -> None:
    bad_slice = SliceSpec(
        horizon=1,
        threshold_value=0.05,
        threshold_type="fixed",
        source_target_kind="sw2021_l2_downside_event",
        feasibility_verdict="bad_usage",
        target_usage="bad_usage",
    )

    result = stream_full_target_audit(
        price_frame=_prices().query("entity_id == 'industry:A'"),
        universe_frame=_universe_frame(["industry:A"]),
        slices=[bad_slice],
        target_support=_support(target_rows=3, usage="eligible"),
        target_universe_manifest=_universe(["industry:A"]),
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
        chunk_size=10,
    )

    assert result["violation_counts"]["invalid_target_usage_count"] == 3
    assert result["violation_counts"]["invalid_slice_count"] == 3


def test_labeled_and_unlabeled_event_label_mismatches_are_detected() -> None:
    rows = pd.DataFrame(
        [
            _row(event_label=None, censoring_status="labeled"),
            _row(trade_date="2026-01-02", event_label=True, censoring_status="insufficient_future_prices"),
        ]
    )

    result = validate_target_rows_dataframe(
        rows,
        _prices(),
        target_universe_ids={"industry:A"},
        accepted_slice_keys={(1, "fixed", 0.05, TARGET_KIND, "eligible")},
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert result["violation_counts"]["labeled_without_event_label_count"] == 1
    assert result["violation_counts"]["unlabeled_with_event_label_count"] == 1


def test_future_return_mae_and_mdd_recompute_mismatches_are_detected() -> None:
    rows = pd.DataFrame(
        [
            _row(
                future_return=0.5,
                future_mae=0.5,
                future_mdd=0.5,
            )
        ]
    )

    result = validate_target_rows_dataframe(
        rows,
        _prices(),
        target_universe_ids={"industry:A"},
        accepted_slice_keys={(1, "fixed", 0.05, TARGET_KIND, "eligible")},
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert result["violation_counts"]["future_return_recompute_violation_count"] == 1
    assert result["violation_counts"]["future_mae_recompute_violation_count"] == 1
    assert result["violation_counts"]["future_mdd_recompute_violation_count"] == 1


def test_cross_cutoff_labeled_violation_is_detected() -> None:
    rows = pd.DataFrame([_row(target_observation_end_date="2026-06-11", censoring_status="labeled")])

    result = validate_target_rows_dataframe(
        rows,
        _prices(),
        target_universe_ids={"industry:A"},
        accepted_slice_keys={(1, "fixed", 0.05, TARGET_KIND, "eligible")},
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert result["violation_counts"]["cross_cutoff_violation_count"] == 1
    assert result["violation_counts"]["historical_development_bad_label_count"] == 1


def test_appended_post_cutoff_prices_do_not_backfill_cross_cutoff_rows() -> None:
    regression = run_cross_cutoff_regression()

    assert regression["passed"] is True


def test_slice_support_deltas_are_detected() -> None:
    rows = compare_slice_support(
        {(1, "fixed", 0.05, TARGET_KIND, "eligible"): {"actual_target_row_count": 5}},
        {(1, "fixed", 0.05, TARGET_KIND, "eligible"): {"target_row_count": 6}},
    )

    assert rows[0]["slice_status"] == "fail"
    assert rows[0]["row_count_delta"] == -1


def test_purge_embargo_input_compatibility_detects_missing_target_windows() -> None:
    rows = pd.DataFrame([_row(target_observation_start_date=None, target_observation_end_date=None)])

    result = validate_target_rows_dataframe(
        rows,
        _prices(),
        target_universe_ids={"industry:A"},
        accepted_slice_keys={(1, "fixed", 0.05, TARGET_KIND, "eligible")},
        source_db_path="data/db/a_share_hmm_tushare_v7.duckdb",
    )

    assert result["purge_embargo_input_violation_count"] == 1


def test_feature_target_namespace_collisions_are_detected() -> None:
    result = detect_feature_namespace_violations(["feature_asof_date", "future_mae", "target_observation_end_date"])

    assert result["feature_namespace_policy_status"] == "fail"
    assert result["future_derived_feature_violation_count"] == 1
    assert result["feature_target_collision_violation_count"] == 2


def test_missing_v7_db_returns_blocked_and_no_fallback(tmp_path: Path) -> None:
    support = tmp_path / "support.json"
    controls = tmp_path / "controls.json"
    universe = tmp_path / "universe.json"
    fold = tmp_path / "fold.json"
    _write_json(support, {**_support(target_rows=7_474_840), "entity_count_after_silent_break_handling": 124})
    _write_json(controls, _controls())
    _write_json(universe, _universe())
    _write_json(fold, {"max_horizon_days": 20})

    report = build_full_target_audit_report(
        db_path=tmp_path / "missing_stage03v_v7.duckdb",
        target_support=support,
        target_universe=universe,
        target_controls=controls,
        fold_plan=fold,
        output=tmp_path / "blocked.md",
        summary_json=tmp_path / "blocked.json",
        chunk_summary=tmp_path / "blocked_chunks.csv",
        error_sample=tmp_path / "blocked_errors.csv",
        no_fetch=True,
    )

    assert report["status"] == "blocked_missing_v7_db"
    assert report["source_db_path"] == "missing_stage03v_v7.duckdb"
    assert report["source_db_path"] != "data/db/a_share_hmm.duckdb"
    assert report["boundary_flags"]["external_data_fetch"] == "no"


def test_no_external_fetch_is_allowed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no-fetch only"):
        build_full_target_audit_report(
            db_path=tmp_path / "missing.duckdb",
            output=tmp_path / "out.md",
            summary_json=tmp_path / "out.json",
            chunk_summary=tmp_path / "chunks.csv",
            error_sample=tmp_path / "errors.csv",
            no_fetch=False,
        )
