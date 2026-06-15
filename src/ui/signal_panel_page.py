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
from src.ui.components.status_display import StatusItem, render_status_grid
from src.ui.components.help_dock import render_help_chip_row
from src.ui.help_texts import display_value, rename_columns_for_display


WARNING_TEXT = "此页面为研究信号与人工判断参考，不构成交易、仓位、买卖或执行建议。"


SIGNAL_COLUMN_LABELS = {
    "signal_date": "信号日期",
    "data_freshness_status": "数据新鲜度",
    "source_scope": "来源范围",
    "vol_20d": "20日波动率",
    "vol_60d": "60日波动率",
    "ewma_vol": "EWMA 波动率",
    "volatility_band": "波动率分层",
    "volatility_percentile_cs": "横截面波动率分位",
    "volatility_percentile_ts_if_available": "时间序列波动率分位",
    "volatility_primary_source": "波动率主来源",
    "volatility_signal_status": "波动率信号状态",
    "downside_vol_20d": "20日下行波动",
    "downside_vol_60d": "60日下行波动",
    "downside_vol_share_20d": "20日下行波动占比",
    "downside_vol_share_60d": "60日下行波动占比",
    "negative_return_day_share_20d": "20日负收益日占比",
    "negative_return_day_share_60d": "60日负收益日占比",
    "downside_asymmetry_band": "下行不对称分层",
    "hmm_state_label": "HMM 状态",
    "hmm_state_source": "HMM 状态来源",
    "hmm_confidence": "HMM 状态置信度",
    "recent_state_switch_date": "最近状态切换日",
    "recent_state_switch_flag": "近期是否切换",
    "hsmm_state_phase": "HSMM 生命周期阶段",
    "hsmm_state_age_days": "HSMM 状态持续天数",
    "hsmm_age_bucket": "HSMM 持续时长分桶",
    "hsmm_duration_percentile": "HSMM 持续时长分位",
    "exit_tendency_1d": "1日退出倾向",
    "exit_tendency_3d": "3日退出倾向",
    "exit_tendency_5d": "5日退出倾向",
    "exit_tendency_10d": "10日退出倾向",
    "exit_tendency_20d": "20日退出倾向",
    "next_state_tendency": "下一状态倾向",
    "hsmm_probability_display_policy": "HSMM 概率显示策略",
    "stage03v_readiness_summary": "Stage03V 就绪摘要",
    "stage03v_usable_probability_slice_count": "可显示概率切片数",
    "stage03v_ordinal_only_slice_count": "仅序数切片数",
    "stage03v_baseline_only_slice_count": "仅基准切片数",
    "stage03v_research_only_slice_count": "仅研究切片数",
    "stage03v_probability_display_status": "Stage03V 概率显示状态",
    "stage03v_probability_source_status": "Stage03V 概率来源状态",
    "stage03v_risk_ordinal": "Stage03V 风险序数",
    "stage03v_calibrated_probability_available": "校准概率是否可显示",
    "stage03v_calibrated_probability_fields": "校准概率字段",
    "model_baseline_alignment_status": "模型-基准一致性",
    "human_review_note": "人工复核提示",
    "not_trading_output": "非交易输出",
}

SIGNAL_VALUE_LABELS = {
    "yes": "是",
    "no": "否",
    "true": "是",
    "false": "否",
    "latest_available": "已用最新可得数据",
    "available": "可用",
    "unavailable": "不可用",
    "insufficient_ohlcv_history": "OHLCV 历史不足",
    "baseline_ohlcv_readonly": "只读 OHLCV 基准",
    "sector_ohlcv_readonly": "只读板块 OHLCV",
    "low": "低",
    "normal": "正常",
    "medium": "中",
    "elevated": "偏高",
    "high": "高",
    "extreme": "极高",
    "early": "早期",
    "mature": "成熟期",
    "late": "后期",
    "walk_forward_state_cache": "滚动因果状态缓存",
    "unavailable_causal_cache": "因果状态缓存不可用",
    "unavailable_lifecycle_source": "生命周期来源不可用",
    "diagnostic_only_not_decision_input": "仅诊断展示，不作为决策输入",
    "hidden_no_current_per_entity_score_source": "隐藏：缺少当前实体级分数来源",
    "readiness_gated_numeric_probability_available": "就绪门控通过：可显示数值概率",
    "ordinal_only_no_numeric_probability": "仅序数展示：不显示数值概率",
    "baseline_only_no_numeric_probability": "仅基准展示：不显示数值概率",
    "research_only_hidden_by_default": "仅研究：默认隐藏",
    "unavailable_current_per_entity_score_source": "当前实体级分数来源不可用",
    "available_current_per_entity_score_source": "当前实体级分数来源可用",
    "baseline_high_model_high": "基准高风险，模型也偏高",
    "baseline_high_model_low": "基准高风险，模型偏低",
    "baseline_low_model_high": "基准低风险，模型偏高",
    "baseline_low_model_low": "基准低风险，模型也偏低",
    "baseline_available_model_unavailable": "基准可用，模型覆盖不可用",
    "model_available_baseline_unavailable": "模型覆盖可用，基准不可用",
    "insufficient_signal_sources": "信号来源不足",
    "risk evidence aligned": "风险证据一致",
    "possible baseline false-alarm / overlay disagreement": "可能是基准误报，或模型覆盖不一致",
    "possible residual risk / overlay disagreement": "可能存在残余风险，或模型覆盖不一致",
    "low-risk alignment": "低风险证据一致",
    "baseline available; model overlay unavailable": "基准可用；模型覆盖不可用",
    "model overlay available; baseline unavailable": "模型覆盖可用；基准不可用",
    "insufficient signal sources": "信号来源不足",
}

SIGNAL_VALUE_COLUMNS = {
    "data_freshness_status",
    "sector_type",
    "volatility_band",
    "volatility_primary_source",
    "volatility_signal_status",
    "downside_asymmetry_band",
    "hmm_state_label",
    "hmm_state_source",
    "recent_state_switch_flag",
    "hsmm_state_phase",
    "hsmm_age_bucket",
    "exit_tendency_1d",
    "exit_tendency_3d",
    "exit_tendency_5d",
    "exit_tendency_10d",
    "exit_tendency_20d",
    "next_state_tendency",
    "hsmm_probability_display_policy",
    "stage03v_probability_display_status",
    "stage03v_probability_source_status",
    "stage03v_risk_ordinal",
    "stage03v_calibrated_probability_available",
    "model_baseline_alignment_status",
    "human_review_note",
    "not_trading_output",
}

READINESS_TEXT_LABELS = {
    "usable_probability_candidate": "可显示概率候选",
    "ordinal_only_candidate": "仅序数候选",
    "baseline_only_candidate": "仅基准候选",
    "research_only": "仅研究",
    "probability_source_status": "概率来源状态",
}


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
    items, readiness = _build_summary_items(snapshot)
    render_status_grid(items)
    st.caption(readiness)


def _build_summary_items(snapshot: pd.DataFrame) -> tuple[tuple[StatusItem, ...], str]:
    latest_date = snapshot["signal_date"].dropna().max()
    freshness = _compact_counts(snapshot, "data_freshness_status")
    band_counts = _compact_counts(snapshot, "volatility_band")
    hmm_counts = _compact_counts(snapshot, "hmm_state_label")
    hsmm_available = int(snapshot["hsmm_state_phase"].astype(str).ne("unavailable").sum())
    hsmm_total = len(snapshot)
    probability_source = _display_value(_first_value(snapshot, "stage03v_probability_source_status", NO_CURRENT_STAGE03V_SCORE_SOURCE))
    readiness = _localize_readiness_text(_first_value(snapshot, "stage03v_readiness_summary", ""))
    return (
        (
            StatusItem("信号日期", _format_signal_date(latest_date), "blue"),
            StatusItem("数据新鲜度", freshness, "green" if "已用最新可得数据" in freshness else "yellow"),
            StatusItem("基准风险分层", band_counts, "neutral"),
            StatusItem("HMM 状态", hmm_counts, "neutral"),
            StatusItem("HSMM 生命周期覆盖", f"{hsmm_available}/{hsmm_total}", "green" if hsmm_available else "yellow"),
            StatusItem("Stage03V 来源", probability_source, "green" if "可用" in probability_source and "不可用" not in probability_source else "yellow"),
        ),
        readiness,
    )


def _format_signal_date(value: object) -> str:
    if value is None or pd.isna(value):
        return "无"
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    return str(value)


def _render_filters(snapshot: pd.DataFrame) -> pd.DataFrame:
    st.subheader("信号列表")
    left, middle, right = st.columns([1, 1, 1])
    sector_types = sorted(str(v) for v in snapshot["sector_type"].dropna().unique())
    selected_types = left.multiselect("板块类型", sector_types, default=sector_types, format_func=_display_value)
    search = middle.text_input("板块名称搜索", value="")
    bands = sorted(str(v) for v in snapshot["volatility_band"].dropna().unique())
    selected_bands = right.multiselect("波动率分层", bands, default=bands, format_func=_display_value)

    c1, c2, c3, c4 = st.columns(4)
    alignments = sorted(str(v) for v in snapshot["model_baseline_alignment_status"].dropna().unique())
    selected_alignments = c1.multiselect("模型-基准一致性", alignments, default=alignments, format_func=_display_value)
    hmm_states = sorted(str(v) for v in snapshot["hmm_state_label"].dropna().unique())
    selected_hmm = c2.multiselect("HMM 状态", hmm_states, default=hmm_states, format_func=_display_value)
    hsmm_phases = sorted(str(v) for v in snapshot["hsmm_state_phase"].dropna().unique())
    selected_hsmm = c3.multiselect("HSMM 阶段", hsmm_phases, default=hsmm_phases, format_func=_display_value)
    readiness_values = sorted(str(v) for v in snapshot["stage03v_probability_display_status"].dropna().unique())
    selected_readiness = c4.multiselect("Stage03V 显示状态", readiness_values, default=readiness_values, format_func=_display_value)

    t1, t2 = st.columns(2)
    high_only = t1.toggle("仅显示基准高风险", value=False)
    disagreement_only = t2.toggle("仅显示模型-基准不一致", value=False)

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
    render_help_chip_row(display_cols, labels=SIGNAL_COLUMN_LABELS)
    st.dataframe(_signal_display_frame(snapshot[[col for col in display_cols if col in snapshot.columns]]), width="stretch")


def _render_detail_expanders(snapshot: pd.DataFrame) -> None:
    with st.expander("基准波动率明细", expanded=False):
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
        render_help_chip_row(cols, labels=SIGNAL_COLUMN_LABELS)
        st.dataframe(_signal_display_frame(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("HMM/HSMM 上下文明细", expanded=False):
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
        render_help_chip_row(cols, labels=SIGNAL_COLUMN_LABELS)
        st.dataframe(_signal_display_frame(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("Stage03V 就绪与概率显示策略", expanded=False):
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
        render_help_chip_row(cols, labels=SIGNAL_COLUMN_LABELS)
        st.dataframe(_signal_display_frame(snapshot[[col for col in cols if col in snapshot.columns]]), width="stretch")

    with st.expander("证据与产物来源", expanded=False):
        _render_provenance()


def _render_provenance() -> None:
    st.markdown("**证据与产物来源**")
    st.json(
        {
            "Stage03V 收尾结论路径": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_closeout_verdict"],
            "Stage03V 最终门禁 v2 路径": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_final_gate_v2"],
            "Stage03V 就绪矩阵路径": ACCEPTED_SIGNAL_SOURCE_PATHS["stage03v_readiness_matrix"],
            "Stage03V 已作废产物登记路径": ACCEPTED_SIGNAL_SOURCE_PATHS[
                "stage03v_invalidated_artifact_registry"
            ],
            "HMM 状态来源": ACCEPTED_SIGNAL_SOURCE_PATHS["hmm_state_source"],
            "HSMM 生命周期来源": ACCEPTED_SIGNAL_SOURCE_PATHS["hsmm_lifecycle_source"],
            "基准数据来源": ACCEPTED_SIGNAL_SOURCE_PATHS["baseline_data_source"],
        }
    )
    st.warning("旧 pre-RERUN1 WP4-WP6 与旧 WP7-v1 产物已作废，不能作为信号强弱证据引用。")
    st.caption("禁止引用的旧信号来源：" + ", ".join(INVALIDATED_SIGNAL_SOURCE_FORBIDDEN))


def _compact_counts(snapshot: pd.DataFrame, column: str) -> str:
    if column not in snapshot.columns or snapshot.empty:
        return "无"
    counts = snapshot[column].fillna("unavailable").astype(str).value_counts().head(3)
    return " / ".join(f"{_display_value(idx)}:{int(value)}" for idx, value in counts.items())


def _first_value(snapshot: pd.DataFrame, column: str, fallback: str) -> str:
    if column not in snapshot.columns or snapshot.empty:
        return fallback
    values = snapshot[column].dropna().astype(str)
    return fallback if values.empty else values.iloc[0]


def _display_value(value: object) -> object:
    if value is None or pd.isna(value):
        return value
    text = str(value)
    return SIGNAL_VALUE_LABELS.get(text, display_value(text))


def _localize_signal_values(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for column in SIGNAL_VALUE_COLUMNS:
        if column in out.columns:
            out[column] = out[column].map(_display_value)
    if "stage03v_readiness_summary" in out.columns:
        out["stage03v_readiness_summary"] = out["stage03v_readiness_summary"].map(_localize_readiness_text)
    return out


def _signal_display_frame(df: pd.DataFrame) -> pd.DataFrame:
    localized = _localize_signal_values(df)
    display = rename_columns_for_display(localized)
    return display.rename(columns={col: SIGNAL_COLUMN_LABELS.get(col, col) for col in display.columns})


def _localize_readiness_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value)
    replacements = {**SIGNAL_VALUE_LABELS, **READINESS_TEXT_LABELS}
    for raw in sorted(replacements, key=len, reverse=True):
        label = replacements[raw]
        text = text.replace(raw, str(label))
    return text.replace("; ", "；")
