from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.evidence_registry import describe_artifact_evidence
from src.ui.run_context import list_valid_walk_forward_caches


@dataclass(frozen=True)
class ModelWorkflowStatus:
    scope_label: str
    sector_run_id: str | None
    sector_train_end: str
    causal_cache_key: str | None
    causal_cache_rows: int
    causal_cache_end: str
    causal_cache_evidence_level: str
    causal_cache_readiness_status: str
    causal_cache_evidence_status: str
    market_run_id: str | None
    market_train_end: str
    next_action: str


def _latest_cache_for_scope(storage: DuckDBStorage, universe_id: str | None = None) -> pd.DataFrame:
    caches = list_valid_walk_forward_caches(storage, universe_id)
    return caches.head(1).reset_index(drop=True).copy() if not caches.empty else pd.DataFrame()


def build_model_workflow_status(storage: DuckDBStorage, universe_id: str | None = None) -> ModelWorkflowStatus:
    scope_label = "当前板块池" if universe_id else "全市场"
    run_id = storage.latest_run_for_current_scope(universe_id)
    run = storage.get_model_run(run_id) if run_id else pd.DataFrame()
    sector_train_end = "无"
    if not run.empty:
        sector_train_end = str(run.iloc[0].get("train_end") or "无")

    cache = _latest_cache_for_scope(storage, universe_id)
    if cache.empty:
        cache_key = None
        cache_rows = 0
        cache_end = "无"
        cache_evidence = {
            "evidence_level": "legacy/debug",
            "readiness_status": "missing",
            "selection_status": "missing_cache",
        }
    else:
        cache_key = str(cache.loc[0, "cache_key"])
        cache_rows = int(cache.loc[0, "row_count"] or 0)
        cache_end = str(cache.loc[0].get("end_date") or "无")
        cache_evidence = describe_artifact_evidence(
            str(storage.db_path),
            run_id=cache_key,
            lineage_hash=str(cache.loc[0].get("lineage_hash") or ""),
            artifact_type="walk_forward_cache",
            feature_scope_id=str(cache.loc[0].get("feature_scope_id") or ""),
            universe_id=cache.loc[0].get("universe_id"),
        )

    market_run = storage.read_df("SELECT run_id, train_end FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")
    if market_run.empty:
        market_run_id = None
        market_train_end = "无"
    else:
        market_run_id = str(market_run.loc[0, "run_id"])
        market_train_end = str(market_run.loc[0].get("train_end") or "无")

    if not run_id:
        next_action = "先训练板块 HMM。"
    elif not cache_key:
        next_action = "运行因果 walk-forward 回测，生成可评估状态缓存。"
    elif not market_run_id:
        next_action = "可先评估/回测；如需大盘风险提示，再训练大盘 HMM。"
    else:
        next_action = "可进行模型评估或回测对照。"

    return ModelWorkflowStatus(
        scope_label=scope_label,
        sector_run_id=run_id,
        sector_train_end=sector_train_end,
        causal_cache_key=cache_key,
        causal_cache_rows=cache_rows,
        causal_cache_end=cache_end,
        causal_cache_evidence_level=str(cache_evidence.get("evidence_level") or "legacy/debug"),
        causal_cache_readiness_status=str(cache_evidence.get("readiness_status") or "missing"),
        causal_cache_evidence_status=str(cache_evidence.get("selection_status") or "legacy_missing_evidence"),
        market_run_id=market_run_id,
        market_train_end=market_train_end,
        next_action=next_action,
    )


def render_model_workflow(storage: DuckDBStorage, universe_id: str | None = None, active_step: str = "") -> None:
    status = build_model_workflow_status(storage, universe_id=universe_id)
    step_labels = {
        "train": "训练",
        "cache": "因果状态",
        "evaluate": "评估",
        "backtest": "回测",
    }
    active_label = step_labels.get(active_step, active_step or "模型实验")
    if status.sector_run_id and status.causal_cache_key:
        st.success(f"模型实验流程：{active_label} | 当前范围：{status.scope_label} | 下一步：{status.next_action}")
    elif status.sector_run_id:
        st.warning(f"模型实验流程：{active_label} | 当前范围：{status.scope_label} | 下一步：{status.next_action}")
    else:
        st.error(f"模型实验流程：{active_label} | 当前范围：{status.scope_label} | 下一步：{status.next_action}")
    with st.expander("查看模型实验流程状态", expanded=False):
        rows = [
            {
                "环节": "板块 HMM run",
                "状态": "已完成" if status.sector_run_id else "缺失",
                "标识": status.sector_run_id or "无",
                "截至日期": status.sector_train_end,
            },
            {
                "环节": "因果 walk-forward 状态缓存",
                "状态": "已完成" if status.causal_cache_key else "缺失",
                "标识": status.causal_cache_key or "无",
                "截至日期": status.causal_cache_end,
                "行数": status.causal_cache_rows,
                "证据层级": status.causal_cache_evidence_level,
                "证据状态": status.causal_cache_evidence_status,
            },
            {
                "环节": "大盘 HMM run",
                "状态": "已完成" if status.market_run_id else "可选缺失",
                "标识": status.market_run_id or "无",
                "截至日期": status.market_train_end,
            },
        ]
        st.dataframe(pd.DataFrame(rows), width="stretch")
        st.caption("样本内状态只用于解释模型划分；总览、评估和回测优先使用因果 walk-forward 状态缓存。")
