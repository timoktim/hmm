from __future__ import annotations

import json

import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.evidence_registry import (
    EvidenceRecord,
    describe_artifact_evidence,
    list_evidence_for_lineage,
    list_evidence_for_run,
    list_selectable_evidence,
    upsert_evidence_record,
)
from src.ui.components.model_workflow import build_model_workflow_status
from src.ui.lifecycle_page import _attach_lifecycle_readiness


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "evidence_contract.duckdb")
    storage.init_schema()
    return storage


def _seed_valid_cache(storage: DuckDBStorage, cache_key: str = "cache-a") -> None:
    storage.upsert_df(
        "walk_forward_cache_runs",
        pd.DataFrame(
            [
                {
                    "cache_key": cache_key,
                    "n_states": 3,
                    "train_window_days": 60,
                    "retrain_frequency": "monthly",
                    "feature_version": "v",
                    "start_date": pd.Timestamp("2024-01-01").date(),
                    "end_date": pd.Timestamp("2024-01-03").date(),
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": "all",
                    "lineage_hash": "lineage-cache-a",
                    "feature_lineage_hash": "feature-cache-a",
                    "cache_status": "completed",
                    "signal_count": 1,
                    "row_count": 1,
                    "created_at": pd.Timestamp("2024-02-01"),
                }
            ]
        ),
        ["cache_key"],
    )
    storage.upsert_df(
        "walk_forward_state_cache",
        pd.DataFrame(
            [
                {
                    "cache_key": cache_key,
                    "sector_id": "S1",
                    "trade_date": pd.Timestamp("2024-01-03").date(),
                    "state_id": 1,
                    "state_label": "TrendUp",
                    "prob_trend_up": 1.0,
                    "prob_neutral": 0.0,
                    "prob_risk_off": 0.0,
                    "next_state_probs_json": "{}",
                    "max_observation_date_used": pd.Timestamp("2024-01-03").date(),
                    "state_source": "causal_backtest",
                    "lineage_hash": "lineage-cache-a",
                    "feature_lineage_hash": "feature-cache-a",
                }
            ]
        ),
        ["cache_key", "sector_id", "trade_date"],
    )


def test_storage_schema_contains_wp11_minimal_registry_columns(tmp_path):
    storage = _storage(tmp_path)

    with storage.connect() as con:
        columns = {row[1] for row in con.execute("PRAGMA table_info('model_evidence_registry')").fetchall()}

    assert {
        "evidence_id",
        "run_id",
        "artifact_type",
        "artifact_path",
        "lineage_hash",
        "feature_scope_id",
        "universe_id",
        "profile_mode",
        "profile_cutoff_date",
        "state_date_policy",
        "evidence_level",
        "readiness_status",
        "verdict",
        "created_at",
        "metadata_json",
    }.issubset(columns)


def test_evidence_can_be_queried_by_run_id_and_lineage_hash(tmp_path):
    storage = _storage(tmp_path)
    evidence_id = upsert_evidence_record(
        str(storage.db_path),
        EvidenceRecord(
            run_id="run-a",
            model_type="hsmm",
            artifact_type="hsmm_lifecycle_profile",
            artifact_path="reports/lifecycle.md",
            lineage_hash="lineage-a",
            feature_scope_id="scope-a",
            evidence_level="internal_diagnostic",
            readiness_status="partial",
            verdict="Stage03ProfileInternalOnly",
            metadata_json={"profile_mode": "latest_asof"},
        ),
    )

    by_run = list_evidence_for_run(str(storage.db_path), "run-a")
    by_lineage = list_evidence_for_lineage(str(storage.db_path), "lineage-a")

    assert by_run["evidence_id"].tolist() == [evidence_id]
    assert by_lineage["evidence_id"].tolist() == [evidence_id]
    assert json.loads(by_run.iloc[0]["metadata_json"]) == {"profile_mode": "latest_asof"}


def test_invalid_readiness_artifact_is_hidden_by_default_selector(tmp_path):
    storage = _storage(tmp_path)
    upsert_evidence_record(
        str(storage.db_path),
        EvidenceRecord(
            run_id="run-blocked",
            model_type="hmm",
            artifact_type="walk_forward_cache",
            artifact_path="cache-blocked",
            lineage_hash="lineage-blocked",
            feature_scope_id="all",
            evidence_level="internal_diagnostic",
            readiness_status="blocked",
        ),
    )

    default = list_selectable_evidence(str(storage.db_path), artifact_type="walk_forward_cache")
    debug = list_selectable_evidence(str(storage.db_path), artifact_type="walk_forward_cache", include_legacy_debug=True)

    assert default.empty
    assert debug.iloc[0]["selection_status"] == "invalid_readiness"


def test_missing_evidence_is_marked_legacy_debug(tmp_path):
    storage = _storage(tmp_path)

    evidence = describe_artifact_evidence(str(storage.db_path), run_id="missing-run", artifact_type="walk_forward_cache")

    assert evidence["evidence_level"] == "legacy/debug"
    assert evidence["selection_status"] == "legacy_missing_evidence"


def test_model_workflow_reads_cache_evidence_level(tmp_path):
    storage = _storage(tmp_path)
    date = pd.Timestamp("2024-02-01").date()
    storage.upsert_df(
        "model_runs",
        pd.DataFrame(
            [
                {
                    "run_id": "run1",
                    "model_type": "GaussianHMM",
                    "n_states": 3,
                    "train_start": date,
                    "train_end": date,
                    "feature_version": "v",
                    "model_path": "",
                    "scaler_path": "",
                    "universe_id": None,
                    "scope_type": "all",
                    "include_custom_baskets": True,
                    "feature_scope_id": "all",
                    "feature_scope_type": "all",
                    "created_at": pd.Timestamp("2024-02-01"),
                    "metrics_json": "{}",
                }
            ]
        ),
        ["run_id"],
    )
    _seed_valid_cache(storage)
    upsert_evidence_record(
        str(storage.db_path),
        EvidenceRecord(
            run_id="cache-a",
            model_type="hmm",
            artifact_type="walk_forward_cache",
            artifact_path="cache-a",
            lineage_hash="lineage-cache-a",
            feature_scope_id="all",
            evidence_level="internal_diagnostic",
            readiness_status="partial",
        ),
    )

    status = build_model_workflow_status(storage)

    assert status.causal_cache_key == "cache-a"
    assert status.causal_cache_evidence_level == "internal_diagnostic"
    assert status.causal_cache_readiness_status == "partial"
    assert status.causal_cache_evidence_status == "valid"


def test_lifecycle_rows_can_attach_registry_evidence_level():
    ui = pd.DataFrame([{"run_id": "run-a", "state_source": "causal_hsmm"}])

    out = _attach_lifecycle_readiness(
        ui,
        {
            "evidence_id": "evidence-a",
            "evidence_level": "internal_diagnostic",
            "readiness_status": "partial",
            "selection_status": "valid",
        },
    )

    assert out.loc[0, "evidence_id"] == "evidence-a"
    assert out.loc[0, "evidence_level"] == "internal_diagnostic"
    assert out.loc[0, "evidence_selection_status"] == "valid"
