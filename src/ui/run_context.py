from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.ui.help_texts import display_value


INVALID_SELECTION_STATUSES = {"invalid", "blocked", "missing", "unknown", "unverified"}
VALID_WALK_FORWARD_CACHE_STATUS = "completed"


def _normalize_universe_id(value: object) -> str:
    try:
        if pd.isna(value):
            return "all"
    except (TypeError, ValueError):
        pass
    text = str(value or "").strip()
    return "all" if text in {"", "all", "None", "nan"} else text


def _selection_status_is_valid(value: object) -> bool:
    text = str(value or "").strip()
    return text == "" or text not in INVALID_SELECTION_STATUSES


def scoped_run_id(storage: DuckDBStorage, universe_id: str | None = None) -> str | None:
    return storage.latest_run_for_current_scope(universe_id)


def scoped_run_frame(storage: DuckDBStorage, universe_id: str | None = None) -> pd.DataFrame:
    return storage.get_model_run(scoped_run_id(storage, universe_id))


def render_run_scope_status(storage: DuckDBStorage, universe_id: str | None = None) -> str | None:
    run_id = scoped_run_id(storage, universe_id)
    if not run_id:
        if universe_id:
            st.warning("当前板块池尚未训练 HMM。")
        else:
            st.info("全市场尚未训练 HMM。")
        return None
    run = storage.get_model_run(run_id)
    if run.empty:
        st.warning("当前 run 记录不存在。")
        return None
    row = run.iloc[0]
    scope = display_value(row.get("scope_type", "all"))
    universe = row.get("universe_id") or "全市场"
    st.caption(
        "当前 run："
        f"{row['run_id']} | 训练范围={scope} | "
        f"板块池={universe} | "
        f"训练开始={row.get('train_start')} | 训练结束={row.get('train_end')}"
    )
    return str(row["run_id"])


def list_completed_hsmm_lifecycle_profiles(storage: DuckDBStorage) -> pd.DataFrame:
    try:
        profiles = storage.read_df(
            """
            WITH latest_ui AS (
              SELECT run_id, profile_mode, profile_cutoff_date, state_date_policy,
                     MAX(created_at) AS latest_ui_created_at,
                     COUNT(*) AS ui_row_count
              FROM hsmm_lifecycle_ui_daily
              GROUP BY run_id, profile_mode, profile_cutoff_date, state_date_policy
            )
            SELECT meta.*, runs.run_status, runs.lineage_hash AS run_lineage_hash,
                   latest_ui.latest_ui_created_at, latest_ui.ui_row_count
            FROM hsmm_lifecycle_profile_metadata meta
            JOIN hsmm_model_runs runs
              ON runs.run_id = meta.run_id
             AND runs.run_status = 'completed'
            JOIN latest_ui
              ON latest_ui.run_id = meta.run_id
             AND latest_ui.profile_mode = meta.profile_mode
             AND latest_ui.profile_cutoff_date = meta.profile_cutoff_date
             AND latest_ui.state_date_policy = meta.state_date_policy
            ORDER BY latest_ui.latest_ui_created_at DESC NULLS LAST,
                     meta.created_at DESC NULLS LAST
            """
        )
    except Exception:
        return pd.DataFrame()
    if profiles.empty:
        return profiles
    valid = pd.Series(True, index=profiles.index)
    for column in ("readiness_status", "evidence_status", "validation_status"):
        if column in profiles.columns:
            valid &= profiles[column].map(_selection_status_is_valid)
    return profiles[valid].copy()


def latest_completed_hsmm_lifecycle_run(storage: DuckDBStorage) -> str | None:
    profiles = list_completed_hsmm_lifecycle_profiles(storage)
    return None if profiles.empty else str(profiles.iloc[0]["run_id"])


def list_valid_walk_forward_caches(
    storage: DuckDBStorage,
    universe_id: str | None = None,
    *,
    expected_lineage_hash: str | None = None,
    expected_feature_lineage_hash: str | None = None,
    include_legacy_debug: bool = False,
) -> pd.DataFrame:
    try:
        caches = storage.read_df(
            """
            SELECT r.cache_key, r.start_date, r.end_date, r.created_at, r.signal_count, r.row_count,
                   r.universe_id, r.scope_type, r.cache_status, r.lineage_hash, r.feature_lineage_hash,
                   r.feature_scope_id, r.state_date_mode,
                   COUNT(s.sector_id) AS actual_row_count,
                   COUNT(DISTINCT s.sector_id) AS cached_sectors,
                   MIN(s.trade_date) AS min_state_date,
                   MAX(s.trade_date) AS max_state_date,
                   SUM(CASE WHEN s.lineage_hash IS NULL OR s.lineage_hash <> r.lineage_hash THEN 1 ELSE 0 END)
                     AS lineage_mismatch_count,
                   SUM(CASE
                         WHEN r.feature_lineage_hash IS NOT NULL
                          AND (s.feature_lineage_hash IS NULL OR s.feature_lineage_hash <> r.feature_lineage_hash)
                         THEN 1 ELSE 0 END)
                     AS feature_lineage_mismatch_count,
                   SUM(CASE
                         WHEN s.max_observation_date_used IS NOT NULL
                          AND s.trade_date IS NOT NULL
                          AND s.max_observation_date_used > s.trade_date
                         THEN 1 ELSE 0 END)
                     AS future_observation_count
            FROM walk_forward_cache_runs r
            LEFT JOIN walk_forward_state_cache s USING(cache_key)
            GROUP BY r.cache_key, r.start_date, r.end_date, r.created_at, r.signal_count, r.row_count,
                     r.universe_id, r.scope_type, r.cache_status, r.lineage_hash, r.feature_lineage_hash,
                     r.feature_scope_id, r.state_date_mode
            ORDER BY r.created_at DESC NULLS LAST
            """,
        )
    except Exception:
        return pd.DataFrame()
    if caches.empty:
        return caches
    out = caches.copy()
    for column in ["row_count", "actual_row_count", "lineage_mismatch_count", "feature_lineage_mismatch_count", "future_observation_count"]:
        out[column] = pd.to_numeric(out[column], errors="coerce").fillna(0).astype(int)
    out["cache_status"] = out["cache_status"].fillna("legacy")
    out["selection_status"] = "valid"
    out.loc[out["cache_status"].ne(VALID_WALK_FORWARD_CACHE_STATUS), "selection_status"] = "invalid_cache_status"
    out.loc[out["lineage_hash"].isna() | out["lineage_hash"].astype(str).str.strip().eq(""), "selection_status"] = "legacy_missing_lineage"
    out.loc[
        out["feature_lineage_hash"].isna() | out["feature_lineage_hash"].astype(str).str.strip().eq(""),
        "selection_status",
    ] = "legacy_missing_feature_lineage"
    out.loc[out["row_count"].le(0), "selection_status"] = "empty_row_count"
    out.loc[out["actual_row_count"].ne(out["row_count"]), "selection_status"] = "row_count_mismatch"
    out.loc[out["lineage_mismatch_count"].gt(0), "selection_status"] = "lineage_mismatch"
    out.loc[out["feature_lineage_mismatch_count"].gt(0), "selection_status"] = "feature_lineage_mismatch"
    out.loc[out["future_observation_count"].gt(0), "selection_status"] = "future_observation_leak"
    if expected_lineage_hash is not None:
        out.loc[out["lineage_hash"].astype(str).ne(str(expected_lineage_hash)), "selection_status"] = "lineage_mismatch"
    if expected_feature_lineage_hash is not None:
        out.loc[out["feature_lineage_hash"].astype(str).ne(str(expected_feature_lineage_hash)), "selection_status"] = "feature_lineage_mismatch"
    expected_universe = _normalize_universe_id(universe_id)
    out["scope_match"] = out["universe_id"].map(_normalize_universe_id).eq(expected_universe)
    out.loc[~out["scope_match"], "selection_status"] = "universe_mismatch"
    out["legacy_debug_allowed"] = out["selection_status"].ne("valid")
    if include_legacy_debug:
        return out
    return out[out["selection_status"].eq("valid")].copy()
