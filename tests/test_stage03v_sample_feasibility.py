from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.evaluation.stage03v_sample_feasibility import (
    assign_feasibility_verdict,
    build_sample_feasibility_report,
    compute_effective_event_evidence,
    compute_idiosyncratic_episodes,
    compute_mae_events,
    compute_market_event_blocks,
)


SLICE = {
    "horizon": 1,
    "threshold": 0.05,
    "threshold_type": "fixed",
    "target_kind": "sw2021_l2_downside_event",
}


def _event_panel(event_entities_by_date: dict[str, set[str]], *, n_entities: int = 10, horizon: int = 1) -> pd.DataFrame:
    dates = pd.date_range(min(event_entities_by_date), max(event_entities_by_date), freq="D")
    entities = [f"E{i:02d}" for i in range(n_entities)]
    rows = []
    for trade_date in dates:
        active = event_entities_by_date.get(trade_date.date().isoformat(), set())
        for entity_id in entities:
            rows.append(
                {
                    "entity_id": entity_id,
                    "trade_date": trade_date.date(),
                    "event_label": entity_id in active,
                    "horizon": horizon,
                    "threshold": 0.05,
                    "threshold_type": "fixed",
                    "target_kind": "sw2021_l2_downside_event",
                }
            )
    return pd.DataFrame(rows)


def test_mae_event_labels_are_correct_on_simple_price_paths() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["A"] * 4,
            "trade_date": pd.date_range("2026-01-01", periods=4, freq="D"),
            "close": [100.0, 98.0, 95.0, 97.0],
        }
    )

    events = compute_mae_events(prices, [2], [0.04, 0.06], "2026-01-04")

    jan1 = events[events["trade_date"].astype(str).eq("2026-01-01")].sort_values("threshold")
    assert jan1["mae"].round(4).tolist() == [-0.05, -0.05]
    assert jan1["event_label"].tolist() == [True, False]
    assert jan1["target_observation_end_date"].astype(str).tolist() == ["2026-01-03", "2026-01-03"]


def test_mae_off_by_one_uses_t_plus_1_through_t_plus_n() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["A"] * 3,
            "trade_date": pd.date_range("2026-01-01", periods=3, freq="D"),
            "close": [100.0, 101.0, 90.0],
        }
    )

    events = compute_mae_events(prices, [1, 2], [0.05], "2026-01-03")
    jan1_h1 = events[(events["trade_date"].astype(str) == "2026-01-01") & (events["horizon"] == 1)].iloc[0]
    jan1_h2 = events[(events["trade_date"].astype(str) == "2026-01-01") & (events["horizon"] == 2)].iloc[0]

    assert jan1_h1["event_label"] is False
    assert round(float(jan1_h1["mae"]), 4) == 0.01
    assert jan1_h2["event_label"] is True
    assert round(float(jan1_h2["mae"]), 4) == -0.1


def test_cross_cutoff_rows_are_censored_without_post_cutoff_labels() -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["A"] * 3,
            "trade_date": pd.to_datetime(["2026-06-09", "2026-06-10", "2026-06-11"]),
            "close": [100.0, 99.0, 80.0],
        }
    )

    events = compute_mae_events(prices, [2], [0.10], "2026-06-10")
    row = events[events["trade_date"].astype(str).eq("2026-06-09")].iloc[0]

    assert pd.isna(row["event_label"])
    assert pd.isna(row["mae"])
    assert row["target_observation_end_date"].isoformat() == "2026-06-11"
    assert row["censoring_status"] == "cross_cutoff_censored"


def test_market_blocks_merge_contiguous_active_dates() -> None:
    events = _event_panel(
        {
            "2026-01-01": {"E00", "E01"},
            "2026-01-02": {"E00", "E01"},
        },
        horizon=1,
    )

    result = compute_market_event_blocks(events, [0.20])

    counts = result["block_counts"]
    assert int(counts["market_event_block_count"].iloc[0]) == 1
    block = result["blocks"].iloc[0]
    assert block["block_start_date"].isoformat() == "2026-01-01"
    assert block["block_end_date"].isoformat() == "2026-01-02"


def test_market_blocks_merge_gaps_less_than_or_equal_to_horizon() -> None:
    events = _event_panel(
        {
            "2026-01-01": {"E00", "E01"},
            "2026-01-04": {"E00", "E01"},
        },
        horizon=2,
    )

    result = compute_market_event_blocks(events, [0.20])

    assert int(result["block_counts"]["market_event_block_count"].iloc[0]) == 1
    assert result["blocks"].iloc[0]["block_end_date"].isoformat() == "2026-01-04"


def test_event_share_sensitivity_counts_differ_correctly() -> None:
    events = _event_panel(
        {
            "2026-01-01": {"E00", "E01", "E02"},
            "2026-01-05": {"E00", "E01"},
            "2026-01-09": {"E00"},
        },
        horizon=1,
    )

    result = compute_market_event_blocks(events, [0.10, 0.20, 0.30])
    counts = {
        round(float(row.event_share_threshold), 2): int(row.market_event_block_count)
        for row in result["block_counts"].itertuples(index=False)
    }

    assert counts == {0.10: 3, 0.20: 2, 0.30: 1}


def test_idiosyncratic_events_outside_market_blocks_are_counted() -> None:
    events = _event_panel(
        {
            "2026-01-01": {"E00", "E01", "E02"},
            "2026-01-05": {"E00"},
        },
        horizon=1,
    )
    market = compute_market_event_blocks(events, [0.20])

    episodes = compute_idiosyncratic_episodes(events, market)

    assert int(episodes["idiosyncratic_industry_episode_count"].iloc[0]) == 1


def test_industry_events_overlapping_market_blocks_are_not_double_counted() -> None:
    events = _event_panel(
        {
            "2026-01-01": {"E00", "E01", "E02"},
        },
        horizon=1,
    )
    market = compute_market_event_blocks(events, [0.20])

    episodes = compute_idiosyncratic_episodes(events, market)

    assert int(episodes["idiosyncratic_industry_episode_count"].iloc[0]) == 0
    details = episodes.attrs["episode_details"]
    assert details["overlaps_primary_market_block"].any()
    assert not details["counted_as_idiosyncratic"].any()


def test_effective_evidence_uses_discount_sensitivities() -> None:
    market_counts = pd.DataFrame(
        [
            {
                **SLICE,
                "event_share_threshold": 0.20,
                "market_event_block_count": 2,
            }
        ]
    )
    idiosyncratic = pd.DataFrame([{**SLICE, "idiosyncratic_industry_episode_count": 4}])

    evidence = compute_effective_event_evidence(market_counts, idiosyncratic, [0.10, 0.25, 0.50])
    row = evidence.iloc[0]

    assert row["discounted_idiosyncratic_episode_count_0_10"] == 0.4
    assert row["effective_event_evidence_count_0_25"] == 3.0
    assert row["effective_event_evidence_count_0_50"] == 4.0


def test_low_evidence_slices_receive_expected_verdicts() -> None:
    assert (
        assign_feasibility_verdict(
            {
                "horizon": 5,
                "threshold_type": "fixed",
                "historical_development_labeled_count": 100,
                "positive_event_count": 1,
                "primary_market_event_block_count": 1,
                "effective_event_evidence_count_0_25": 4,
            }
        )
        == "drop_threshold"
    )
    assert (
        assign_feasibility_verdict(
            {
                "horizon": 5,
                "threshold_type": "fixed",
                "historical_development_labeled_count": 100,
                "positive_event_count": 3,
                "primary_market_event_block_count": 2,
                "effective_event_evidence_count_0_25": 7,
            }
        )
        == "diagnostic_only"
    )
    assert (
        assign_feasibility_verdict(
            {
                "horizon": 5,
                "threshold_type": "fixed",
                "historical_development_labeled_count": 100,
                "positive_event_count": 10,
                "primary_market_event_block_count": 2,
                "effective_event_evidence_count_0_25": 12,
            }
        )
        == "eligible"
    )
    assert assign_feasibility_verdict({"data_status": "partial_missing_db"}) == "partial_missing_data"
    assert assign_feasibility_verdict({"threshold_type": "vol_scaled", "historical_development_labeled_count": 10}) == "defer_threshold"


def test_missing_db_path_produces_partial_report_without_crashing(tmp_path: Path) -> None:
    output = tmp_path / "sample_feasibility_report.md"
    summary_json = tmp_path / "sample_feasibility_report.json"

    report = build_sample_feasibility_report(
        db_path=tmp_path / "missing.duckdb",
        output=output,
        summary_json=summary_json,
        no_fetch=True,
    )

    assert report["status"] == "partial_missing_db"
    assert report["db_availability"] == "missing"
    assert report["external_data_fetch"] == "no"
    assert report["boundary_flags"]["target_dataset_built"] == "no"
    assert output.exists()
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    assert payload["boundary_flags"]["external_data_fetch"] == "no"
    assert all(
        row["feasibility_verdict"] == "partial_missing_data"
        for row in payload["fixed_threshold_feasibility_matrix"]
    )


def test_no_external_data_fetch_is_attempted_for_synthetic_report(tmp_path: Path) -> None:
    prices = pd.DataFrame(
        {
            "entity_id": ["A", "A", "A", "B", "B", "B"],
            "trade_date": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-01", "2026-01-02", "2026-01-03"]
            ),
            "close": [100.0, 94.0, 95.0, 100.0, 101.0, 102.0],
        }
    )

    report = build_sample_feasibility_report(
        db_path=None,
        output=tmp_path / "report.md",
        summary_json=tmp_path / "report.json",
        no_fetch=True,
        price_frame=prices,
    )

    assert report["no_fetch"] is True
    assert report["external_data_fetch"] == "no"
    assert report["boundary_flags"]["target_dataset_built"] == "no"
    assert report["no_usable_probability_assigned"] is True
