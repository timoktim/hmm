from __future__ import annotations

import pandas as pd

from src.analysis.sector_cycles import load_sector_states_for_analysis
from src.data_pipeline.storage import DuckDBStorage
from src.ui.run_context import list_valid_walk_forward_caches


def _storage(tmp_path) -> DuckDBStorage:
    storage = DuckDBStorage(tmp_path / "wp9_analysis_cache.duckdb")
    storage.init_schema()
    storage.upsert_df(
        "sector_meta",
        pd.DataFrame([{"sector_id": "S1", "sector_name": "Sector 1", "sector_type": "industry"}]),
        ["sector_id"],
    )
    return storage


def _seed_cache(
    storage: DuckDBStorage,
    cache_key: str,
    *,
    lineage_hash: str = "lineage-a",
    feature_lineage_hash: str = "feature-a",
    universe_id: str | None = None,
    cache_status: str = "completed",
    row_count: int = 1,
) -> None:
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
                    "params_json": "{}",
                    "params_hash": "params-a",
                    "universe_id": universe_id,
                    "scope_type": "universe" if universe_id else "all",
                    "include_custom_baskets": True,
                    "rebalance_days": 5,
                    "state_date_mode": "rebalance_signals_v2",
                    "feature_scope_id": universe_id or "all",
                    "lineage_hash": lineage_hash,
                    "feature_lineage_hash": feature_lineage_hash,
                    "cache_status": cache_status,
                    "signal_count": row_count,
                    "row_count": row_count,
                    "created_at": pd.Timestamp("2024-02-01"),
                }
            ]
        ),
        ["cache_key"],
    )
    if row_count <= 0:
        return
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
                    "train_start": pd.Timestamp("2024-01-01").date(),
                    "train_end": pd.Timestamp("2024-01-03").date(),
                    "max_observation_date_used": pd.Timestamp("2024-01-03").date(),
                    "probability_type": "posterior",
                    "state_source": "causal_backtest",
                    "lineage_hash": lineage_hash,
                    "feature_lineage_hash": feature_lineage_hash,
                }
            ]
        ),
        ["cache_key", "sector_id", "trade_date"],
    )


def test_cache_selector_ignores_universe_mismatch_cache(tmp_path) -> None:
    storage = _storage(tmp_path)
    _seed_cache(storage, "all_cache")
    _seed_cache(storage, "u2_cache", universe_id="u2")

    all_scope = list_valid_walk_forward_caches(storage)
    u1_scope = list_valid_walk_forward_caches(storage, universe_id="u1", include_legacy_debug=True)

    assert all_scope["cache_key"].tolist() == ["all_cache"]
    assert "u2_cache" not in set(list_valid_walk_forward_caches(storage, universe_id="u1")["cache_key"])
    assert u1_scope.set_index("cache_key").loc["u2_cache", "selection_status"] == "universe_mismatch"


def test_analysis_loader_rejects_lineage_mismatch_cache(tmp_path) -> None:
    storage = _storage(tmp_path)
    _seed_cache(storage, "cache-a", lineage_hash="lineage-a", feature_lineage_hash="feature-a")

    mismatch = load_sector_states_for_analysis(
        storage,
        "run-a",
        source="walk_forward",
        cache_key="cache-a",
        expected_lineage_hash="lineage-b",
    )
    matched = load_sector_states_for_analysis(
        storage,
        "run-a",
        source="walk_forward",
        cache_key="cache-a",
        expected_lineage_hash="lineage-a",
        expected_feature_lineage_hash="feature-a",
    )

    assert mismatch.empty
    assert len(matched) == 1
    assert matched.loc[0, "state_source"] == "causal_backtest"


def test_cache_selector_rejects_non_completed_or_row_count_mismatch(tmp_path) -> None:
    storage = _storage(tmp_path)
    _seed_cache(storage, "running_cache", cache_status="running")
    _seed_cache(storage, "row_mismatch_cache", row_count=2)

    valid = list_valid_walk_forward_caches(storage)
    debug = list_valid_walk_forward_caches(storage, include_legacy_debug=True).set_index("cache_key")

    assert valid.empty
    assert debug.loc["running_cache", "selection_status"] == "invalid_cache_status"
    assert debug.loc["row_mismatch_cache", "selection_status"] == "row_count_mismatch"
