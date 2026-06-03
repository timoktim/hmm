from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.data_pipeline.market_updater import DEFAULT_MARKET_INDEX_CODES, update_all_a_stock_universe, update_market_breadth, update_market_indices
from src.data_pipeline.storage import DuckDBStorage
from src.data_sources.akshare_client import MARKET_INDEXES
from src.features.market_features import COVERAGE_MODE_FULL_MARKET, COVERAGE_MODE_LOCAL_SAMPLE, build_market_features, latest_market_index_status, normalize_breadth_coverage_columns
from src.models.market_hmm import latest_market_regime, market_regime_history, train_market_hmm
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.operation_result import render_operation_result
from src.ui.causal_boundary import classify_state_source
from src.ui.formatters import format_probability, format_probability_columns
from src.ui.help_texts import HELP_TEXTS, PROBABILITY_LABELS, display_state_label, rename_columns_for_display
from src.ui.state_colors import MARKET_STATE_BG_COLORS
from src.utils.dates import today_yyyymmdd


STATE_TEXT = {
    "RiskOn": "整体市场趋势向上，赚钱效应较好，板块趋势上行信号可信度较高。",
    "Neutral": "市场处于震荡或结构性状态，应减少持仓数量，优先选择最强板块。",
    "RiskOff": "市场处于弱势或高波动状态，板块相对强势可能只是抗跌，不宜简单追涨。",
}
FULL_MARKET_BREADTH_UI_ENABLED = True


def market_width_visibility_by_coverage(
    coverage_level: str | None,
    coverage_mode: str | None = None,
    full_market_coverage_ratio: object | None = None,
) -> tuple[bool, str]:
    mode = str(coverage_mode or "").strip()
    if mode == COVERAGE_MODE_LOCAL_SAMPLE:
        return False, "当前宽度是 local_sample，只代表本地已抓取股票样本，不代表全 A 覆盖。"
    level = str(coverage_level or "insufficient")
    if not mode and full_market_coverage_ratio is None:
        if level == "full_market":
            return True, "当前宽度可按全市场宽度解读。"
        return False, "当前宽度只代表本地已抓取股票样本，不代表全 A 市场。"
    ratio = pd.to_numeric(pd.Series([full_market_coverage_ratio]), errors="coerce").iloc[0]
    if mode == COVERAGE_MODE_FULL_MARKET and level == "full_market" and pd.notna(ratio) and float(ratio) >= 0.8:
        return True, "当前宽度可按全市场宽度解读。"
    if mode == COVERAGE_MODE_FULL_MARKET:
        return False, "当前全 A 宽度覆盖率不可用或不足，不能按完整全市场宽度解读。"
    return False, "当前宽度覆盖模式未知，不能按完整全市场宽度解读。"


def can_update_full_market_breadth(storage: DuckDBStorage) -> bool:
    count = storage.read_df("SELECT count(*) AS n FROM all_a_stock_universe")
    return False if count.empty else int(count.loc[0, "n"] or 0) > 0


def latest60_full_market_breadth_available(storage: DuckDBStorage) -> tuple[bool, str]:
    breadth = storage.read_df(
        """
        SELECT *
        FROM market_breadth_daily
        WHERE breadth_mode = 'full_market'
        ORDER BY trade_date DESC
        LIMIT 60
        """
    )
    if breadth.empty:
        return False, "缺少宽度数据，大盘 HMM 将使用纯指数特征。"
    if len(breadth) < 60:
        return False, f"全 A 市场宽度最近样本不足 60 日（当前 {len(breadth)} 日），大盘 HMM 将使用纯指数特征。"
    breadth = normalize_breadth_coverage_columns(breadth)
    usable = breadth["full_market_coverage_usable"].fillna(False)
    if usable.all():
        return True, "最近60日已有全市场宽度，可用于大盘 HMM。"
    usable_days = int(usable.sum())
    if usable_days >= 20:
        return True, f"最近60日全市场宽度有 {60 - usable_days} 日覆盖不足；训练会仅在具备全市场覆盖的日期使用宽度特征。"
    latest = breadth.iloc[0]
    effective = int(latest.get("effective_count") or 0)
    mode = str(latest.get("coverage_mode") or latest.get("breadth_mode") or "unknown")
    if mode != "full_market":
        return False, f"当前宽度模式为 {mode}，仅覆盖本地样本 {effective} 只股票，不代表全 A 覆盖。大盘 HMM 将使用纯指数特征。"
    return False, f"全 A 市场宽度可用日期不足（最近60日仅 {usable_days} 日满足覆盖要求）。大盘 HMM 将使用纯指数特征。"


def breadth_chart_diagnostics(breadth: pd.DataFrame) -> dict[str, object]:
    if breadth.empty:
        return {"flat_warning": False}
    up = pd.to_numeric(breadth.get("up_ratio"), errors="coerce").dropna()
    return {
        "effective_count": int(pd.to_numeric(breadth.get("effective_count"), errors="coerce").dropna().iloc[-1]) if "effective_count" in breadth.columns and pd.to_numeric(breadth.get("effective_count"), errors="coerce").notna().any() else 0,
        "total_count": int(pd.to_numeric(breadth.get("total_count"), errors="coerce").dropna().iloc[-1]) if "total_count" in breadth.columns and pd.to_numeric(breadth.get("total_count"), errors="coerce").notna().any() else 0,
        "ma20_valid_count": int(pd.to_numeric(breadth.get("ma20_valid_count"), errors="coerce").dropna().iloc[-1]) if "ma20_valid_count" in breadth.columns and pd.to_numeric(breadth.get("ma20_valid_count"), errors="coerce").notna().any() else 0,
        "up_ratio_min": float(up.min()) if not up.empty else pd.NA,
        "up_ratio_max": float(up.max()) if not up.empty else pd.NA,
        "up_ratio_std": float(up.std(ddof=0)) if not up.empty else pd.NA,
        "flat_warning": bool(not up.empty and up.std(ddof=0) < 0.005),
    }


def _latest_run(storage: DuckDBStorage) -> pd.DataFrame:
    return storage.read_df("SELECT * FROM market_regime_runs ORDER BY created_at DESC LIMIT 1")


def _transition_matrix(storage: DuckDBStorage) -> pd.DataFrame:
    run = _latest_run(storage)
    if run.empty:
        return pd.DataFrame()
    metrics = json.loads(run.loc[0, "metrics_json"])
    matrix = metrics.get("transition_matrix", [])
    labels = {int(k): v for k, v in metrics.get("state_labels", {}).items()}
    ordered = ["RiskOn", "Neutral", "RiskOff"]
    state_for_label = {label: state for state, label in labels.items()}
    if not matrix:
        return pd.DataFrame()
    rows: list[list[float]] = []
    for label in ordered:
        state = state_for_label.get(label)
        if state is None:
            rows.append([0.0, 0.0, 0.0])
            continue
        rows.append([float(matrix[state][state_for_label[target]]) if target in state_for_label else 0.0 for target in ordered])
    return pd.DataFrame(rows, index=[f"当前 {display_state_label(label)}" for label in ordered], columns=[f"下一状态：{display_state_label(label)}" for label in ordered])


def render_market_regime(storage: DuckDBStorage) -> None:
    st.title("大盘状态")
    st.caption(HELP_TEXTS["market_regime"])
    render_data_status_bar(storage)

    st.subheader("数据更新")
    c1, c2, c3 = st.columns([1, 1, 2])
    start_date = c1.text_input("起始日期", value="20200101", help=HELP_TEXTS["market_start_date"])
    end_date = c2.text_input("结束日期", value=today_yyyymmdd(), help=HELP_TEXTS["market_end_date"])
    index_options = [f"{code} {MARKET_INDEXES[code]['index_name']}" for code in DEFAULT_MARKET_INDEX_CODES]
    selected = c3.multiselect("指数选择", index_options, default=index_options[:6], help=HELP_TEXTS["market_indices"])
    index_codes = [item.split()[0] for item in selected]
    incremental = st.checkbox("增量更新", value=True, help=HELP_TEXTS["incremental_update"])
    lookback_days = st.number_input("回补天数", min_value=0, max_value=60, value=10, help=HELP_TEXTS["lookback_days"])
    u1, u2, u3, u4 = st.columns(4)
    if u1.button("更新大盘指数数据"):
        with st.spinner("正在更新大盘指数数据..."):
            summary = update_market_indices(start_date, end_date, index_codes=index_codes, incremental=incremental, lookback_days=int(lookback_days), storage=storage)
            render_operation_result(summary, "指数更新完成")
    if u2.button("更新本地样本宽度"):
        with st.spinner("正在计算本地样本宽度..."):
            summary = update_market_breadth(start_date, end_date, incremental=incremental, lookback_days=int(lookback_days), mode="local_sample", storage=storage)
            render_operation_result(summary, "本地样本宽度更新完成")
    if u3.button("更新全 A 股票池"):
        summary = update_all_a_stock_universe(storage=storage, force_refresh=True)
        render_operation_result(summary, "全 A 股票池更新完成")
    if u4.button("更新全 A 市场宽度", disabled=not can_update_full_market_breadth(storage)):
        with st.spinner("正在计算全 A 市场宽度..."):
            summary = update_market_breadth(start_date, end_date, incremental=incremental, lookback_days=int(lookback_days), mode="full_market", storage=storage)
            render_operation_result(summary, "全 A 市场宽度更新完成")
    if not can_update_full_market_breadth(storage):
        st.caption("尚未建立全 A 股票池，因此“更新全 A 市场宽度”暂不可用。可先在本页或数据中心更新全 A 股票池。")

    st.subheader("模型训练")
    m1, m2, m3 = st.columns(3)
    n_states = m1.number_input("隐藏状态数量", min_value=2, max_value=5, value=3, help=HELP_TEXTS["market_n_states"])
    breadth_ready, breadth_ready_message = latest60_full_market_breadth_available(storage)
    use_breadth = m2.checkbox(
        "使用全市场宽度",
        value=breadth_ready,
        disabled=not breadth_ready,
        help=HELP_TEXTS["use_breadth"] if breadth_ready else "当前没有最近60日全市场宽度数据，大盘 HMM 将使用纯指数特征。",
    )
    random_state = m3.number_input("随机种子", min_value=0, max_value=9999, value=42, help=HELP_TEXTS["random_state"])
    if not breadth_ready:
        st.warning(breadth_ready_message)
    allow_insufficient_index_coverage = st.checkbox(
        "允许指数覆盖不足时训练",
        value=False,
        help="默认要求沪深300、中证500、中证1000中至少两个指数有足够历史。若只抓到一个指数，可以勾选后继续训练，但结果仅适合临时观察。",
    )
    if st.button("训练大盘 HMM"):
        progress_bar = st.progress(0)
        progress_text = st.empty()
        progress_stats = st.empty()

        def on_progress(percent: int, stage: str, payload: dict[str, object]) -> None:
            progress_bar.progress(min(percent / 100, 1.0))
            progress_text.caption(f"{stage}（{percent}%）")
            if payload:
                progress_stats.caption("；".join(f"{k}: {v}" for k, v in payload.items()))

        try:
            result = train_market_hmm(
                start_date,
                end_date,
                n_states=int(n_states),
                use_breadth=use_breadth,
                random_state=int(random_state),
                allow_insufficient_index_coverage=allow_insufficient_index_coverage,
                storage=storage,
                progress_callback=on_progress,
            )
            render_operation_result(result, "大盘 HMM 训练完成")
            if result.index_coverage_warning:
                st.warning(result.index_coverage_warning)
            if result.breadth_coverage_warning:
                st.warning(result.breadth_coverage_warning)
        except Exception as exc:
            st.error(str(exc))

    st.subheader("当前市场状态总览")
    latest = latest_market_regime(storage)
    if latest.empty:
        st.info("尚未训练大盘 HMM。更新指数数据后，可在上方训练大盘状态模型。")
    else:
        row = latest.iloc[0]
        metrics = json.loads(row["metrics_json"])
        used_breadth = bool(metrics.get("used_breadth", False))
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("当前状态", display_state_label(row["state_label"]))
        c2.metric("风险偏好状态置信度", format_probability(row["prob_risk_on"]))
        c3.metric("中性状态置信度", format_probability(row["prob_neutral"]))
        c4.metric("风险回避状态置信度", format_probability(row["prob_risk_off"]))
        c5.metric("最新交易日", str(row["trade_date"]))
        state_source = classify_state_source(row.to_dict())
        st.caption(
            f"模型训练区间：{row['train_start']} 至 {row['train_end']}；"
            f"是否使用市场宽度：{'是' if used_breadth else '否'}；state_source: {state_source}"
        )
        if state_source == "unknown_due_to_missing_metadata":
            st.warning("当前大盘状态缺少 causal metadata，只能作为保守研究解释。")
        if metrics.get("index_coverage_warning"):
            st.warning(str(metrics["index_coverage_warning"]))
        if metrics.get("breadth_coverage_warning"):
            st.warning(str(metrics["breadth_coverage_warning"]))
        if not used_breadth:
            st.warning("当前模型未使用市场宽度。")
        st.info(STATE_TEXT.get(str(row["state_label"]), STATE_TEXT["Neutral"]))

    st.subheader("指数状态表")
    index_status = latest_market_index_status(storage)
    if index_status.empty:
        st.info("暂无指数状态数据。")
    else:
        st.dataframe(rename_columns_for_display(index_status), width="stretch")

    st.subheader("宽度指标")
    breadth = storage.read_df("SELECT * FROM market_breadth_daily ORDER BY breadth_mode, trade_date")
    if breadth.empty:
        st.warning("暂无市场宽度数据。市场宽度依赖个股行情数据。当前个股行情覆盖不足，宽度指标可能不完整。")
    else:
        breadth["trade_date"] = pd.to_datetime(breadth["trade_date"])
        breadth = normalize_breadth_coverage_columns(breadth)
        modes = [m for m in ["full_market", "local_sample"] if m in set(breadth["breadth_mode"].fillna("local_sample").astype(str))]
        mode_labels = {"full_market": "全 A 市场宽度", "local_sample": "本地样本宽度"}
        latest_run = _latest_run(storage)
        latest_model_used_breadth = False
        if not latest_run.empty:
            latest_metrics = json.loads(latest_run.loc[0, "metrics_json"])
            latest_model_used_breadth = bool(latest_metrics.get("used_breadth", False))
        tabs = st.tabs([mode_labels.get(mode, mode) for mode in modes])
        for tab, mode in zip(tabs, modes, strict=False):
            with tab:
                mode_breadth = breadth[breadth["breadth_mode"].fillna("local_sample").astype(str).eq(mode)].sort_values("trade_date")
                if mode_breadth.empty:
                    st.info(f"暂无{mode_labels.get(mode, mode)}。")
                    continue
                latest_breadth = mode_breadth.iloc[-1]
                coverage_value = latest_breadth.get("coverage_level")
                warning_value = latest_breadth.get("coverage_warning")
                latest_coverage_level = "insufficient" if pd.isna(coverage_value) or not str(coverage_value).strip() else str(coverage_value)
                latest_warning = "" if pd.isna(warning_value) else str(warning_value).strip()
                latest_effective_count = latest_breadth.get("effective_count")
                if pd.isna(latest_effective_count):
                    latest_effective_count = latest_breadth.get("total_count")
                latest_total_count = latest_breadth.get("total_count")
                latest_expected_count = latest_breadth.get("expected_count")
                latest_coverage_mode = str(latest_breadth.get("coverage_mode") or mode or "unknown")
                latest_full_market_coverage_ratio = latest_breadth.get("full_market_coverage_ratio")
                latest_local_sample_internal_coverage = latest_breadth.get("local_sample_internal_coverage")
                source_label = "全市场" if latest_coverage_mode == "full_market" and latest_coverage_level == "full_market" else "本地样本"
                latest60 = mode_breadth.tail(60)
                latest60_full = bool(mode == "full_market" and latest60["full_market_coverage_usable"].fillna(False).all()) if "full_market_coverage_usable" in latest60.columns else False

                b1, b2, b3, b4, b5, b6 = st.columns(6)
                b1.metric("最近交易日", str(latest_breadth["trade_date"].date()))
                b2.metric("指标来源", source_label)
                b3.metric("有效/应覆盖", f"{int(latest_effective_count) if pd.notna(latest_effective_count) else 0}/{int(latest_expected_count) if pd.notna(latest_expected_count) else int(latest_total_count) if pd.notna(latest_total_count) else 0}")
                if latest_coverage_mode == "local_sample":
                    b4.metric("样本内部覆盖率", "无" if pd.isna(latest_local_sample_internal_coverage) else f"{float(latest_local_sample_internal_coverage):.1%}")
                else:
                    b4.metric("全市场覆盖率", "无" if pd.isna(latest_full_market_coverage_ratio) else f"{float(latest_full_market_coverage_ratio):.1%}")
                b5.metric("最近60日全市场", "是" if latest60_full else "否")
                b6.metric("HMM 实际用宽度", "是" if latest_model_used_breadth and mode == "full_market" else "否")
                if latest_warning:
                    st.warning(latest_warning)
                if latest_coverage_mode == "local_sample":
                    st.warning("当前宽度是 local_sample，只代表本地已抓取股票样本；样本内部覆盖率不代表全 A 覆盖。")
                elif source_label != "全市场":
                    st.warning("当前宽度不能按完整全 A 市场覆盖解读。")
                if pd.notna(latest_effective_count) and int(latest_effective_count) < 500:
                    st.error("当前有效股票数不足 500，仅能作为样本观察，不应解释为市场宽度。")
                is_full_width, width_message = market_width_visibility_by_coverage(
                    latest_coverage_level,
                    coverage_mode=latest_coverage_mode,
                    full_market_coverage_ratio=latest_full_market_coverage_ratio,
                )
                if not is_full_width:
                    st.warning(width_message)
                st.caption("涨跌停数量为近似估计，暂未区分 ST、创业板、科创板、北交所涨跌幅限制。")
                diagnostics = breadth_chart_diagnostics(mode_breadth)
                diag_df = pd.DataFrame([diagnostics])
                st.dataframe(rename_columns_for_display(diag_df), width="stretch")
                if diagnostics.get("flat_warning"):
                    st.warning("上涨家数比例几乎不变，请检查本地股票样本是否过少或行情是否重复。")
                ratio_cols = [c for c in ["up_ratio", "above_ma20_ratio"] if c in mode_breadth.columns]
                ratio_df = mode_breadth[["trade_date", *ratio_cols]].rename(
                    columns={
                        "trade_date": "交易日期",
                        "up_ratio": "上涨家数比例",
                        "above_ma20_ratio": "高于20日均线比例",
                    }
                )
                fig_ratio = px.line(ratio_df, x="交易日期", y=[c for c in ratio_df.columns if c != "交易日期"], title=f"{mode_labels.get(mode, mode)}：上涨家数比例与均线宽度")
                fig_ratio.update_layout(legend_title_text="指标", yaxis_range=[0, 1])
                st.plotly_chart(fig_ratio, width="stretch")
                if "amount_z_20d" in mode_breadth.columns:
                    amount_df = mode_breadth[["trade_date", "amount_z_20d"]].rename(columns={"trade_date": "交易日期", "amount_z_20d": "成交额热度"})
                    fig_amount = px.line(amount_df, x="交易日期", y="成交额热度", title=f"{mode_labels.get(mode, mode)}：成交额热度")
                    st.plotly_chart(fig_amount, width="stretch")

    st.subheader("HMM 状态历史")
    history = market_regime_history(storage)
    if history.empty:
        st.info("暂无大盘 HMM 状态历史。")
    else:
        history["trade_date"] = pd.to_datetime(history["trade_date"])
        index_df = storage.read_df(
            """
            SELECT trade_date, index_code, index_name, close
            FROM market_index_ohlcv
            ORDER BY
              CASE index_code
                WHEN '000300' THEN 1
                WHEN '000985' THEN 2
                WHEN '000001' THEN 3
                ELSE 9
              END,
              index_code,
              trade_date
            """
        )
        if not index_df.empty:
            index_df["trade_date"] = pd.to_datetime(index_df["trade_date"])
            first_code = str(index_df["index_code"].iloc[0])
            first_name = str(index_df["index_name"].iloc[0])
            index_one = index_df[index_df["index_code"].astype(str) == first_code].sort_values("trade_date")
            close = index_one.set_index("trade_date")["close"].sort_index()
            nav = (close / close.dropna().iloc[0]).rename("指数净值").reset_index()
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=nav["trade_date"], y=nav["指数净值"], mode="lines", name=f"{first_name}净值"))
            hist_rows = history.reset_index(drop=True)
            for i, hrow in hist_rows.iterrows():
                x0 = hrow["trade_date"]
                x1 = hist_rows.loc[i + 1, "trade_date"] if i + 1 < len(hist_rows) else nav["trade_date"].iloc[-1]
                fig.add_vrect(x0=x0, x1=x1, fillcolor=MARKET_STATE_BG_COLORS.get(hrow["state_label"], "rgba(150,150,150,0.08)"), opacity=0.7, line_width=0)
            fig.update_layout(height=360, title="指数净值与大盘状态背景", xaxis_title="交易日期", yaxis_title="净值")
            st.plotly_chart(fig, width="stretch")
        probability_cols = ["prob_risk_on", "prob_neutral", "prob_risk_off"]
        prob_df = history[["trade_date", *probability_cols]].rename(columns={"trade_date": "交易日期", **PROBABILITY_LABELS})
        fig_prob = px.line(prob_df, x="交易日期", y=[PROBABILITY_LABELS[c] for c in probability_cols], title="大盘状态置信度")
        fig_prob.update_layout(legend_title_text="状态置信度", yaxis_tickformat=".0%")
        st.plotly_chart(fig_prob, width="stretch")

    st.subheader("状态转移矩阵")
    matrix = _transition_matrix(storage)
    if matrix.empty:
        st.info("暂无状态转移矩阵。")
    else:
        fig_matrix = px.imshow(matrix, text_auto=".1%", aspect="auto", color_continuous_scale="Greens", title="状态转移矩阵")
        st.plotly_chart(fig_matrix, width="stretch")
        with st.expander("查看矩阵数据"):
            st.dataframe(matrix, width="stretch")

    st.subheader("与板块模型联动说明")
    st.info("当前大盘状态只作为风险提示展示，尚未作为可操作过滤器接入回测结果。")
    st.caption("后续若接入回测，将确保每个信号日只使用当日及之前的大盘状态。")

    with st.expander("参数说明与模型解释"):
        st.write("这个模型不是预测明天涨跌，而是识别市场环境。它的输出应作为风险过滤器，而不是单独判断依据。")
        st.write("风险偏好表示整体风险环境较友好；中性震荡表示市场处于震荡或结构性环境；风险回避表示弱势或高波动环境。")
