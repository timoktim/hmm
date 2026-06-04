from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.ui.stage03r_ui_data import (  # noqa: E402
    ANNOTATION_PATH,
    EXPECTED_HORIZONS,
    append_annotation,
    build_annotation_record,
    build_model_context_snapshot,
    build_research_console_snapshot,
    forbidden_output_terms,
)


STATUS_LABELS = {
    "PASS": "通过（PASS）",
    "DEFER": "暂缓（DEFER）",
    "yes": "是",
    "no": "否",
    "unknown": "未知",
    "loaded": "已加载",
    "missing": "缺失",
    "holdout_candidate": "候选留出窗",
    "not_proven": "尚未证明",
    "pending": "等待复核",
    "not_requested": "未请求",
    "local_slice_only": "仅本地切片可用",
    "interpretation_only": "仅解释用途",
    "diagnostic_only_not_decision_input": "仅诊断，不作为决策输入",
    "not_available": "不可用",
}

REASON_LABELS = {
    "non-overlap with WP3-WP6.1 calibration/readiness evidence is not proven.": (
        "与 WP3-WP6.1 校准/就绪证据的非重叠关系尚未证明。"
    ),
}

READINESS_LABELS = {
    "usable_probability": "可用概率（usable_probability）",
    "baseline_only": "基线兜底（baseline_only）",
    "ordinal_only": "序数倾向（ordinal_only）",
    "insufficient_sample": "样本不足（insufficient_sample）",
    "invalid": "无效（invalid）",
}

ANNOTATION_DISPLAY = {
    "watch": "观察（watch）",
    "ignore": "忽略（ignore）",
    "investigate": "调查（investigate）",
    "paper_trade": "模拟跟踪（paper_trade）",
}

CONFIDENCE_DISPLAY = {
    "low": "低（low）",
    "medium": "中（medium）",
    "high": "高（high）",
}


def _label(value: object) -> object:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    text = str(value)
    return STATUS_LABELS.get(text, REASON_LABELS.get(text, value))


def _kv_table(values: dict[str, object], labels: dict[str, str] | None = None) -> pd.DataFrame:
    labels = labels or {}
    return pd.DataFrame(
        [{"字段": labels.get(key, key), "值": _label(value)} for key, value in values.items()]
    )


def _readiness_counts_table(counts: dict[str, int]) -> pd.DataFrame:
    return pd.DataFrame(
        [{"就绪状态": READINESS_LABELS.get(key, key), "切片数": value} for key, value in counts.items()]
    )


def _readiness_horizon_table(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    if frame.empty:
        return pd.DataFrame(columns=["观察周期（日）", "可用概率", "基线兜底", "序数倾向", "样本不足", "无效"])
    return frame.rename(
        columns={
            "horizon_days": "观察周期（日）",
            "usable_probability": "可用概率",
            "baseline_only": "基线兜底",
            "ordinal_only": "序数倾向",
            "insufficient_sample": "样本不足",
            "invalid": "无效",
        }
    )


def _render_static_table(frame: pd.DataFrame) -> None:
    if frame.empty:
        st.caption("暂无记录。")
        return
    st.table(frame.reset_index(drop=True).style.hide(axis="index"))


def render() -> None:
    st.set_page_config(page_title="Stage03R 研究控制台", layout="wide")
    st.markdown(
        """
        <style>
        #MainMenu,
        footer,
        [data-testid="stToolbar"],
        [data-testid="stDecoration"],
        [data-testid="stStatusWidget"],
        [data-testid="stDeployButton"] {
            display: none !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.title("Stage03R 研究控制台")
    st.caption("本地研究用途：观察已提交 Stage03R 工件，并收集 Stage04 前瞻复核标注。")

    snapshot = build_research_console_snapshot(root=ROOT)
    forbidden = forbidden_output_terms(snapshot)
    if forbidden:
        st.error("研究控制台摘要包含禁用输出字段，请先修复数据层。")
        st.stop()

    if snapshot["reports_missing"]:
        st.warning("缺少部分已提交报告：" + "；".join(snapshot["reports_missing"]))

    gate = snapshot["final_gate"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("最终门控", _label(gate["final_verdict"]))
    c2.metric("工程门控", _label(gate["engineering_gate"]))
    c3.metric("实证晋级", _label(gate["empirical_promotion"]))
    c4.metric("控制台模式", "仅研究")
    if gate["defer_reasons"]:
        st.info("暂缓原因：" + "；".join(str(_label(item)) for item in gate["defer_reasons"]))

    st.subheader("就绪状态计数")
    _render_static_table(_readiness_counts_table(snapshot["readiness_counts"]))

    st.subheader("可用概率与基线兜底按周期对照")
    _render_static_table(_readiness_horizon_table(snapshot["readiness_by_horizon"]))

    st.subheader("Hazard 使用范围")
    _render_static_table(
        _kv_table(
            snapshot["hazard_status"],
            {
                "locally_usable": "本地切片可用",
                "broadly_promoted": "是否广泛晋级",
                "baseline_only_majority": "基线兜底是否为多数",
                "scope": "范围",
            },
        )
    )

    st.subheader("HSMM 解释状态")
    _render_static_table(
        _kv_table(
            snapshot["hsmm_summary"],
            {
                "available": "是否可读",
                "row_count": "生命周期行数",
                "role": "定位",
                "numeric_policy": "数值退出概率策略",
                "diagnostic_policy": "诊断策略",
            },
        )
    )

    st.subheader("最终留出与前瞻复核")
    _render_static_table(
        _kv_table(
            snapshot["holdout_status"],
            {
                "status": "留出状态",
                "empirical_promotion": "实证晋级",
                "non_overlap_status": "非重叠状态",
                "consumption_count": "消费次数",
                "pending_review_horizons": "待复核周期",
                "future_review": "复核状态",
                "future_computation": "未来结果计算",
            },
        )
    )
    st.caption("待复核周期：1、3、5、10、20；除非明确请求，不计算未来观测结果。")

    st.subheader("Stage04 切分登记")
    _render_static_table(
        _kv_table(
            snapshot["split_registry"],
            {
                "available": "是否可用",
                "status": "状态",
                "path": "路径",
                "message": "说明",
                "schema_version": "schema 版本",
                "split_status": "切分状态",
                "entry_count": "条目数",
            },
        )
    )

    st.subheader("本地数据库状态")
    _render_static_table(
        _kv_table(
            {key: value for key, value in snapshot["local_db"].items() if key != "row_counts"},
            {"available": "是否存在", "opened_read_only": "只读打开", "path": "路径", "error": "错误"},
        )
    )
    if snapshot["local_db"].get("row_counts"):
        _render_static_table(
            pd.DataFrame(
                [{"表": key, "行数": value} for key, value in snapshot["local_db"]["row_counts"].items()]
            )
        )

    st.subheader("人工研究标注")
    st.caption(f"本地标注文件：{snapshot['annotation_path']}；该路径已加入 gitignore。")
    with st.form("stage04_research_annotation"):
        f1, f2, f3 = st.columns(3)
        sector_code = f1.text_input("板块代码")
        trade_date = f2.text_input("交易日期", help="输入已有观察日期，例如 2026-05-28。")
        horizon_days = f3.selectbox("观察周期（日）", EXPECTED_HORIZONS)
        f4, f5 = st.columns(2)
        human_label = f4.selectbox(
            "人工标签",
            ["watch", "ignore", "investigate", "paper_trade"],
            format_func=lambda value: ANNOTATION_DISPLAY.get(str(value), str(value)),
        )
        confidence = f5.selectbox(
            "人工置信度",
            ["medium", "low", "high"],
            format_func=lambda value: CONFIDENCE_DISPLAY.get(str(value), str(value)),
        )
        note = st.text_area("备注", height=110)
        submitted = st.form_submit_button("保存本地标注")
        if submitted:
            record = build_annotation_record(
                sector_code=sector_code,
                trade_date=trade_date,
                horizon_days=int(horizon_days),
                human_label=str(human_label),
                confidence=str(confidence),
                note=note,
                model_context_snapshot=build_model_context_snapshot(snapshot),
            )
            append_annotation(record, ROOT / ANNOTATION_PATH)
            st.success("已保存本地研究标注。")

    st.subheader("边界")
    _render_static_table(
        _kv_table(
            snapshot["boundary"],
            {
                "external_data_fetch": "外部数据抓取",
                "model_retrained": "模型重训",
                "threshold_tuning": "阈值调参",
                "trading_output": "交易相关输出",
                "decision_output": "决策输出",
                "annotation_files_committed": "标注文件提交",
                "duckdb_committed": "DuckDB 提交",
            },
        )
    )


if __name__ == "__main__":
    render()
