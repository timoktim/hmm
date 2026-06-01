from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pandas as pd

from src.evaluation import hmm_label_alignment as hla


def _state_rows(run_id: str, labels: dict[int, str] | None = None, id_order: list[int] | None = None) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=8, freq="D")
    labels = labels or {0: "TrendUp", 1: "RiskOff"}
    id_order = id_order or [0, 0, 0, 1, 1, 0, 1, 1]
    rows = []
    for sector in ["S1", "S2"]:
        for idx, date in enumerate(dates):
            state_id = id_order[idx]
            rows.append(
                {
                    "run_id": run_id,
                    "sector_id": sector,
                    "trade_date": date,
                    "state_id": state_id,
                    "state_label": labels[state_id],
                    "rs_20d": 0.8 if state_id == 0 else -0.4,
                    "vol_20d": 0.2 if state_id == 0 else 0.7,
                    "drawdown_20d": -0.03 if state_id == 0 else -0.22,
                    "future_ret_5d": 0.04 if state_id == 0 else -0.03,
                }
            )
    return pd.DataFrame(rows)


def test_signature_generation_from_synthetic_state_rows() -> None:
    signatures = hla.build_state_signatures(_state_rows("run-a"), run_id="run-a")

    assert signatures["state_key"].tolist() == ["state_id:0", "state_id:1"]
    trend = signatures[signatures["state_label"].eq("TrendUp")].iloc[0]
    payload = json.loads(trend["signature_json"])
    assert trend["row_count"] == 8
    assert trend["occupancy_share"] == 0.5
    assert payload["median_rs_20d"] == 0.8
    assert payload["avg_future_ret_5d"] == 0.04
    assert trend["avg_dwell_days"] > 1


def test_alignment_returns_correct_identity_when_signatures_are_permuted() -> None:
    base = hla.build_state_signatures(_state_rows("base"), run_id="base")
    compare_rows = _state_rows(
        "compare",
        labels={7: "TrendUp", 9: "RiskOff"},
        id_order=[7, 7, 7, 9, 9, 7, 9, 9],
    )
    compare = hla.build_state_signatures(compare_rows, run_id="compare")

    audit, method = hla.align_state_signatures(base, compare, base_run_id="base", compare_run_id="compare", prefer_hungarian=False)

    assert method == "greedy_fallback"
    matched = dict(zip(audit["base_state_key"], audit["matched_state_key"], strict=False))
    assert matched["state_id:0"] == "state_id:7"
    assert matched["state_id:1"] == "state_id:9"
    assert audit["label_preserved"].all()


def test_ambiguous_matches_are_detected() -> None:
    base = hla.build_state_signatures(_state_rows("base"), run_id="base")
    compare = base.copy()
    compare["run_id"] = "compare"
    compare["state_key"] = ["state_id:10", "state_id:11"]
    compare["state_id"] = [10, 11]
    compare["state_label"] = ["TrendUp", "RiskOff"]
    compare.loc[:, "signature_json"] = base.loc[0, "signature_json"]

    audit, _method = hla.align_state_signatures(base.iloc[[0]], compare, base_run_id="base", compare_run_id="compare", prefer_hungarian=False)

    assert bool(audit.iloc[0]["ambiguous_match"])
    assert audit.iloc[0]["label_drift_severity"] == "medium"


def test_missing_comparable_runs_produces_partial_report(tmp_path: Path) -> None:
    db_path = tmp_path / "one_run.duckdb"
    con = duckdb.connect(str(db_path))
    rows = _state_rows("only-run")
    con.execute(
        """
        CREATE TABLE model_runs (
          run_id TEXT,
          n_states INTEGER,
          universe_id TEXT,
          scope_type TEXT,
          feature_scope_id TEXT,
          feature_scope_type TEXT,
          created_at TIMESTAMP
        )
        """
    )
    con.execute("INSERT INTO model_runs VALUES ('only-run', 2, NULL, 'all', 'all', 'all', TIMESTAMP '2024-02-01')")
    con.execute("CREATE TABLE sector_state_daily AS SELECT * FROM rows")
    con.close()

    summary = hla.run_label_alignment(
        hla.AlignmentConfig(
            db_path=db_path,
            run_id="latest",
            compare_mode="recent-runs",
            output_path=tmp_path / "report.md",
            summary_json_path=tmp_path / "summary.json",
            no_fetch=True,
        )
    )

    assert summary["status"] == "partial"
    assert summary["run_pairs_compared"] == 0
    assert (tmp_path / "report.md").exists()
    assert (tmp_path / "summary.json").exists()


def test_greedy_fallback_is_deterministic_when_scipy_unavailable() -> None:
    base = hla.build_state_signatures(_state_rows("base"), run_id="base")
    compare = hla.build_state_signatures(_state_rows("compare"), run_id="compare")

    first, first_method = hla.align_state_signatures(base, compare, base_run_id="base", compare_run_id="compare", prefer_hungarian=False)
    second, second_method = hla.align_state_signatures(base, compare, base_run_id="base", compare_run_id="compare", prefer_hungarian=False)

    assert first_method == second_method == "greedy_fallback"
    assert first[["base_state_key", "matched_state_key"]].to_dict("records") == second[["base_state_key", "matched_state_key"]].to_dict("records")


def test_cli_works_on_minimal_temporary_duckdb(tmp_path: Path) -> None:
    db_path = tmp_path / "alignment.duckdb"
    con = duckdb.connect(str(db_path))
    run_a = _state_rows("run-a")
    run_b = _state_rows(
        "run-b",
        labels={3: "TrendUp", 4: "RiskOff"},
        id_order=[3, 3, 3, 4, 4, 3, 4, 4],
    )
    runs = pd.DataFrame(
        [
            {"run_id": "run-a", "n_states": 2, "universe_id": None, "scope_type": "all", "feature_scope_id": "all", "feature_scope_type": "all", "created_at": pd.Timestamp("2024-02-02")},
            {"run_id": "run-b", "n_states": 2, "universe_id": None, "scope_type": "all", "feature_scope_id": "all", "feature_scope_type": "all", "created_at": pd.Timestamp("2024-02-01")},
        ]
    )
    states = pd.concat([run_a, run_b], ignore_index=True)
    con.execute("CREATE TABLE model_runs AS SELECT * FROM runs")
    con.execute("CREATE TABLE sector_state_daily AS SELECT * FROM states")
    con.close()

    report = tmp_path / "report.md"
    summary_json = tmp_path / "summary.json"
    code = hla.main(
        [
            "--db",
            str(db_path),
            "--run-id",
            "latest",
            "--compare-mode",
            "recent-runs",
            "--output",
            str(report),
            "--summary-json",
            str(summary_json),
            "--no-fetch",
        ]
    )

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    assert code == 0
    assert summary["status"] == "pass"
    assert summary["run_pairs_compared"] == 1
    assert summary["external_data_fetch"] == "no"
    assert summary["training_algorithm_modified"] == "no"
    assert report.exists()
    con = duckdb.connect(str(db_path))
    assert con.execute("SELECT COUNT(*) FROM hmm_state_signature").fetchone()[0] == 4
    assert con.execute("SELECT COUNT(*) FROM hmm_label_alignment_audit").fetchone()[0] == 2
    con.close()


def test_no_external_data_updater_is_called_for_missing_db(tmp_path: Path) -> None:
    summary = hla.run_label_alignment(
        hla.AlignmentConfig(
            db_path=tmp_path / "missing.duckdb",
            run_id="latest",
            compare_mode="recent-runs",
            output_path=tmp_path / "report.md",
            summary_json_path=tmp_path / "summary.json",
            no_fetch=True,
        )
    )

    assert summary["status"] == "partial"
    assert summary["external_data_fetch"] == "no"
    assert "local DB not found" in summary["warnings"][0]
