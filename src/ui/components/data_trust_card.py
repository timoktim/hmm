from __future__ import annotations

import json
from dataclasses import dataclass

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.ui.help_texts import display_value


@dataclass
class DataTrustSummary:
    last_network_success: str
    stale_reads: int
    historical_stale_reads: int
    run_scope: str
    feature_scope: str
    market_width_level: str
    sector_count: int
    walk_forward_causal: str
    market_regime_uses_breadth: str
    comparable_scope: str


def _cache_health_counts(health: pd.DataFrame) -> tuple[int, int]:
    if health.empty:
        return 0, 0
    stale_series = health["stale_reads"] if "stale_reads" in health.columns else pd.Series([0])
    historical = int(pd.to_numeric(stale_series, errors="coerce").fillna(0).sum())
    if historical <= 0:
        return 0, 0

    def ts(column: str) -> pd.Series:
        if column not in health.columns:
            return pd.Series(pd.NaT, index=health.index)
        return pd.to_datetime(health[column], errors="coerce")

    last_success = ts("last_network_success")
    if last_success.isna().all() and "last_success" in health.columns:
        last_success = ts("last_success")
    last_failure = ts("last_network_failure")
    last_cache = ts("last_cache_hit")
    last_stale = ts("last_stale_cache_hit")
    has_stale_ts = last_stale.notna()
    active_by_stale_ts = has_stale_ts & (last_success.isna() | (last_stale > last_success))
    fallback_stale_ts = (~has_stale_ts) & last_failure.notna() & last_cache.notna()
    fallback_stale_ts &= (last_success.isna() | (last_failure > last_success))
    fallback_stale_ts &= last_cache >= last_failure
    active_mask = (pd.to_numeric(stale_series, errors="coerce").fillna(0) > 0) & (active_by_stale_ts | fallback_stale_ts)
    return int(active_mask.sum()), historical


def build_data_trust_summary(
    storage: DuckDBStorage,
    run_id: str | None = None,
    universe_id: str | None = None,
    walk_forward_causal: bool | None = None,
) -> DataTrustSummary:
    health = storage.read_df("SELECT * FROM data_health")
    if health.empty:
        last_network_success = "暂无"
        stale_reads = 0
        historical_stale_reads = 0
    else:
        success_col = "last_network_success" if "last_network_success" in health.columns else "last_success"
        last_network_success = str(health[success_col].dropna().max()) if health[success_col].notna().any() else "暂无"
        stale_reads, historical_stale_reads = _cache_health_counts(health)

    run = storage.get_model_run(run_id) if run_id else pd.DataFrame()
    if run.empty:
        run_scope = "未选择 run"
        feature_scope = "未选择"
    else:
        row = run.iloc[0]
        run_scope = display_value(row.get("scope_type") or "all")
        feature_scope = str(row.get("feature_scope_id") or "all")

    breadth = storage.read_df(
        """
        SELECT coverage_level, breadth_mode
        FROM market_breadth_daily
        WHERE breadth_mode IN ('full_market', 'local_sample')
        ORDER BY
          trade_date DESC,
          CASE WHEN breadth_mode = 'full_market' THEN 0 ELSE 1 END,
          fetched_at DESC NULLS LAST
        LIMIT 1
        """
    )
    if breadth.empty:
        market_width_level = "无宽度数据"
    else:
        row = breadth.loc[0]
        level = str(row.get("coverage_level") or "insufficient")
        mode = str(row.get("breadth_mode") or "local_sample")
        prefix = "全市场" if mode == "full_market" else "本地样本"
        market_width_level = f"{prefix}/{display_value(level)}"

    if universe_id:
        items = storage.list_universe_items(universe_id)
        sector_count = int(len(items))
    else:
        counts = storage.read_df("SELECT count(DISTINCT sector_id) AS n FROM sector_meta")
        sector_count = 0 if counts.empty else int(counts.loc[0, "n"] or 0)

    market_run = storage.read_df("SELECT metrics_json FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")
    if market_run.empty:
        market_regime_uses_breadth = "无大盘模型"
    else:
        metrics = json.loads(market_run.loc[0, "metrics_json"])
        market_regime_uses_breadth = "是" if metrics.get("used_breadth") else "否"

    causal_text = "因果 walk-forward" if walk_forward_causal else "非回测页/未运行" if walk_forward_causal is None else "非因果展示"
    comparable_scope = "一致" if not run.empty else "待确认"
    return DataTrustSummary(
        last_network_success=last_network_success,
        stale_reads=stale_reads,
        historical_stale_reads=historical_stale_reads,
        run_scope=run_scope,
        feature_scope=feature_scope,
        market_width_level=market_width_level,
        sector_count=sector_count,
        walk_forward_causal=causal_text,
        market_regime_uses_breadth=market_regime_uses_breadth,
        comparable_scope=comparable_scope,
    )


def render_data_trust_card(
    storage: DuckDBStorage,
    run_id: str | None = None,
    universe_id: str | None = None,
    walk_forward_causal: bool | None = None,
) -> None:
    summary = build_data_trust_summary(storage, run_id=run_id, universe_id=universe_id, walk_forward_causal=walk_forward_causal)
    with st.container(border=True):
        st.markdown("**结果可信度摘要**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("最近网络成功", summary.last_network_success)
        c2.metric("当前过期缓存接口", summary.stale_reads)
        c3.metric("Run 范围", summary.run_scope)
        c4.metric("Feature Scope", summary.feature_scope)
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("宽度覆盖", summary.market_width_level)
        c6.metric("板块数量", summary.sector_count)
        c7.metric("回测因果性", summary.walk_forward_causal)
        c8.metric("大盘模型用宽度", summary.market_regime_uses_breadth)
        if not summary.market_width_level.startswith("全市场/全市场") and summary.market_width_level != "无宽度数据":
            st.warning("市场宽度只代表本地已抓取股票样本，不代表全 A 市场。")
        if summary.stale_reads > 0:
            st.warning("当前仍有接口最近一次可用结果来自过期缓存，建议先在数据中心刷新关键数据。")
        elif summary.historical_stale_reads > 0:
            st.caption(f"历史累计过期缓存读取 {summary.historical_stale_reads} 次，表示过去发生过网络失败后的缓存兜底；当前状态未因此判为异常。")
