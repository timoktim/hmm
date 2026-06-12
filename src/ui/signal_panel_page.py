from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.signals.signal_panel_snapshot import (
    ACCEPTED_SIGNAL_SOURCE_PATHS,
    INVALIDATED_SIGNAL_SOURCE_FORBIDDEN,
    NO_CURRENT_STAGE03V_SCORE_SOURCE,
    build_signal_panel_snapshot,
    validate_snapshot_schema,
)
from src.ui.help_texts import rename_columns_for_display


WARNING_TEXT = "此页面为研究信号与人工判断参考，不构成交易、仓位、买卖或执行建议。"


def render_signal_panel_page(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("信号面板")
    st.warning(WARNING_TEXT)

    snapshot = build_signal_panel_snapshot(storage, universe_id=universe_id)
    schema_issues = validate_snapshot_schema(snapshot)
    if schema_issues:
        st.error("信号快照结构校验未通过。")
        st.code("\n".join(schema_issues))
        return
    if snapshot.empty:
        st.info("暂无可展示的板块 OHLCV 信号。")
        _render_provenance()
        return

    _render_summary(snapshot)
    filtered = _render_filters(snapshot)
    _render_main_table(filtered)
    _render_detail_expanders(filtered)


def _render_summary(snapshot: pd.DataFrame) -> None:
    latest_date = snapshot["signal_date"].dropna().max()
    freshness = _compact_counts(snapshot, "data_freshness_status")
    band_counts = _compact_counts(snapshot, "volatility_band")
    hmm_counts = _compact_counts(snapshot, "hmm_state_label")
    hsmm_available = int(snapshot["hsmm_state_phase"].astype(str).ne("unavailable").sum())
    hsmm_total = len(snapshot)
    probability_source = _first_value(snapshot, "stage03v_probability_source_status", NO_CURRENT_STAGE03V_SCORE_SOURCE)
    readiness = _first_value(snapshot, "stage03v_readiness_summary", "")

    cols = st.columns(6)
    cols[0].metric("Signal date", str(latest_date))
    cols[1].metric("Data freshness", freshness)
    cols[2].metric("Primary baseline risk band", band_counts)
    cols[3].metric("HMM state", hmm_counts)
    cols[4].metric("HSMM lifecycle", f"{hsmm_available}/{hsmm_total}")
    cols[5].metric("Stage03V source", probability_source)
    st.caption(readiness)


def _render_filters(snapshot: pd.DataFrame) -> pd.DataFrame:
    st.subheader("信号列表")
    left, middle, right = st.columns([1, 1, 1])
    sector_types = sorted(str(v) for v in snapshot["sector_type"].dropna().unique())
    selected_types = left.multiselect("sector_type", sector_types, default=sector_types)
    search = middle.text_input("sector_name search", value="")
    bands = sorted(str(v) for v in snapshot["volatility_band"].dropna().unique())
    selected_bands = right.multiselect("volatility_band", bands, default=bands)

    c1, c2, c3, c4 = st.columns(4)
    alignments = sorted(str(v) for v in snapshot["model_baseline_alignment_status"].dropna().unique())
    selected_alignments = c1.multiselect("model_baseline_alignment_status", alignments, default=alignments)
    hmm_states = sorted(str(v) for v in snapshot["hmm_state_label"].dropna().unique())
    selected_hmm = c2.multiselect("HMM state", hmm_states, default=hmm_states)
    hsmm_phases = sorted(str(v) for v in snapshot["hsmm_state_phase"].dropna().unique())
    selected_hsmm = c3.multiselect("HSMM phase", hsmm_phases, default=hsmm_phases)
    readiness_values = sorted(str(v) for v in snapshot["stage03v_probability_display_status"].dropna().unique())
    selected_readiness = c4.multiselect("Stage03V readiness", readiness_values, default=readiness_values)

    t1, t2 = st.columns(2)
    high_only = t1.toggle("show only high baseline risk", value=False)
    disagreement_only = t2.toggle("show only model-baseline disagreement", value=False)

    filtered = snapshot.copy()
    filtered = filtered[filtered["sector_type"].astype(str).isin(selected_types)]
    filtered = filtered[filtered["volatility_band"].astype(str).isin(selected_bands)]
    filtered = filtered[filtered["model_baseline_alignment_status"].astype(str).isin(selected_alignments)]
    filtered = filtered[filtered["hmm_state_label"].astype(str).isin(selected_hmm)]
    filtered = filtered[filtered["hsmm_state_phase"].astype(str).isin(selected_hsmm)]
    filtered = filtered[filtered["stage03v_probability_display_status"].astype(str).isin(selected_readiness)]
    if search.strip():
        filtered = filtered[filtered["sector_name"].astype(str).str.contains(search.strip(), case=False, na=False)]
    if high_only:
        filtered = filtered[filtered["volatility_band"].isin(["high", "elevated"])]
    if disagreement_only:
        filtered = filtered[
            filtered["model_baseline_alignment_status"].isin(["baseline_high_model_low", "baseline_low_model_high"])
        ]
    return filtered


def _render_main_table(snapshot: pd.DataFrame) -> None:
    display_cols = [
        "signal_date",
        "sector_type",
        "sector_name",
        "volatility_band",
        "vol_20d",
        "vol_60d",
        "downside_asymmetry_band",
        "hmm_state_label",
        "hmm_confidence",
        "hsmm_state_phase",
        "exit_tendency_10d",
        "stage03v_probability_display_status",
        "stage03v_probability_source_status",
        "stage03v_risk_ordinal",
        "model_baseline_alignment_status",
        "human_review_note",
        "not_trading_output",
    ]
    st.dataframe(rename_columns_for_display(snapshot[[col for col in display_cols if col in snapshot.columns]]), width="stretch")


def _render_detail_expanders(snapshot: pd.DataFrame) -> None:
    with st.expander("Baseline volatility details", expanded=False):
        cols = [
            "sector_name",
            "vol_20d",
            "vol_60d",
            "ewma_vol",
            "volatility_percentile_cs",
            "volatility_primary_source",
            "volatility_signal_status",
            "downside_vol_20d",
            "downside_vol_60d",
            "downside_vol_share_20d",
            "downside_vol_share_60d",
            "negative_return_day_share_20d",
            "negative_return_day_share_60d",
            "downside_asymmetry_band",
        ]
        st.dataframe(rename_columns_for_display(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("HMM/HSMM context details", expanded=False):
        cols = [
            "sector_name",
            "hmm_state_label",
            "hmm_state_source",
            "hmm_confidence",
            "prob_trend_up",
            "prob_neutral",
            "prob_risk_off",
            "recent_state_switch_date",
            "recent_state_switch_flag",
            "hsmm_state_phase",
            "hsmm_state_age_days",
            "hsmm_age_bucket",
            "hsmm_duration_percentile",
            "exit_tendency_1d",
            "exit_tendency_3d",
            "exit_tendency_5d",
            "exit_tendency_10d",
            "exit_tendency_20d",
            "next_state_tendency",
            "hsmm_probability_display_policy",
        ]
        st.dataframe(rename_columns_for_display(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("Stage03V readiness and probability display policy", expanded=False):
        cols = [
            "sector_name",
            "stage03v_readiness_summary",
            "stage03v_usable_probability_slice_count",
            "stage03v_ordinal_only_slice_count",
            "stage03v_baseline_only_slice_count",
            "stage03v_research_only_slice_count",
            "stage03v_probability_display_status",
            "stage03v_probability_source_status",
            "stage03v_risk_ordinal",
            "stage03v_calibrated_probability_available",
            "stage03v_calibrated_probability_fields",
        ]
        st.dataframe(rename_columns_for_display(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("Evidence and artifact provenance", expanded=False):
        _render_provenance()


def _render_provenance() -> None:
    st.markdown("**Evidence and artifact provenance**")
    st.json(
        {
            "Stage03V closeout verdict path": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_closeout_verdict"],
            "Stage03V final gate v2 path": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_final_gate_v2"],
            "Stage03V readiness matrix path": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_readiness_matrix"],
            "Stage03V invalidated artifact registry path": ACCEPTED_SIGNAL_SOURCE_PATHS[
                "stage03v_invalidated_artifact_registry"
            ],
            "HMM state source": ACCEPTED_SIGNAL_SOURCE_PATHS["hmm_state_source"],
            "HSMM lifecycle source": ACCEPTED_SIGNAL_SOURCE_PATHS["hsmm_lifecycle_source"],
            "baseline data source": ACCEPTED_SIGNAL_SOURCE_PATHS["baseline_data_source"],
        }
    )
    st.warning("旧 pre-RERUN1 WP4-WP6 与旧 WP7-v1 产物已作废，不能作为信号强弱证据引用。")
    st.caption("Forbidden legacy signal sources: " + ", ".join(INVALIDATED_SIGNAL_SOURCE_FORBIDDEN))


def _compact_counts(snapshot: pd.DataFrame, column: str) -> str:
    if column not in snapshot.columns or snapshot.empty:
        return "无"
    counts = snapshot[column].fillna("unavailable").astype(str).value_counts().head(3)
    return " / ".join(f"{idx}:{int(value)}" for idx, value in counts.items())


def _first_value(snapshot: pd.DataFrame, column: str, fallback: str) -> str:
    if column not in snapshot.columns or snapshot.empty:
        return fallback
    values = snapshot[column].dropna().astype(str)
    return fallback if values.empty else values.iloc[0]
