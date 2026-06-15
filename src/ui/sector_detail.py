from __future__ import annotations

import json

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analysis.sector_cycles import build_state_segments, build_stock_overlay_normalized_series
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import update_stock_histories
from src.data_pipeline.universe import custom_basket_sector_meta, universe_sector_ids
from src.features.stock_features import add_a_share_limit_flags
from src.models.inference import sector_state_history, transition_matrix
from src.scoring.stock_filter import filter_sector_stocks
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.formatters import format_probability, format_probability_columns
from src.ui.help_texts import display_state_label, rename_columns_for_display
from src.ui.run_context import render_run_scope_status
from src.ui.state_colors import SECTOR_STATE_BG_COLORS, SECTOR_STATE_COLORS
from src.utils.dates import today_yyyymmdd


SECTOR_TYPE_LABELS = {"industry": "行业", "concept": "概念", "custom": "自定义股票池"}


def _prefilled_sector_choice(meta: pd.DataFrame, preselected: object) -> tuple[str | None, str | None]:
    if preselected and not meta.empty and str(preselected) in set(meta["sector_id"].astype(str)):
        row = meta[meta["sector_id"].astype(str).eq(str(preselected))].iloc[0]
        return str(row["sector_type"]), str(row["sector_name"])
    return None, None


def _sector_transition_matrix(storage: DuckDBStorage, run_id: str | None) -> pd.DataFrame:
    if not run_id:
        return pd.DataFrame()
    run = storage.read_df("SELECT metrics_json FROM model_runs WHERE run_id = ?", [run_id])
    if run.empty:
        return transition_matrix(storage, run_id=run_id)
    metrics = json.loads(run.loc[0, "metrics_json"])
    matrix = metrics.get("transition_matrix", [])
    labels = {int(k): v for k, v in metrics.get("state_labels", {}).items()}
    if not matrix or not labels:
        return transition_matrix(storage, run_id=run_id)
    ordered = [label for label in ["TrendUp", "Neutral", "RiskOff"] if label in set(labels.values())]
    state_for_label = {label: state for state, label in labels.items()}
    rows: list[list[float]] = []
    for label in ordered:
        state = state_for_label[label]
        rows.append([float(matrix[state][state_for_label[target]]) for target in ordered])
    return pd.DataFrame(
        rows,
        index=[f"当前 {display_state_label(label)}" for label in ordered],
        columns=[f"模型迁移分布：{display_state_label(label)}" for label in ordered],
    )


def _select_sector(storage: DuckDBStorage, key_prefix: str = "sector", universe_id: str | None = None) -> str | None:
    meta = storage.read_df(
        """
        SELECT sector_id, sector_type, sector_name
        FROM sector_meta
        WHERE COALESCE(is_active, TRUE)
        ORDER BY sector_type, sector_name
        """
    )
    custom_meta = custom_basket_sector_meta(storage)
    if not custom_meta.empty:
        meta = pd.concat([meta, custom_meta], ignore_index=True)
    if universe_id:
        allowed_ids = set(universe_sector_ids(storage, universe_id, include_custom_baskets=True))
        meta = meta[meta["sector_id"].astype(str).isin(allowed_ids)]
    if meta.empty:
        st.info("暂无板块元数据。")
        return None
    available_types = meta["sector_type"].dropna().astype(str).drop_duplicates().tolist()
    pending_sector_id = st.session_state.pop("detail_overlay_pending_sector_id", None)
    preselected = pending_sector_id or st.session_state.get("selected_sector_id_for_detail")
    default_type, default_name = _prefilled_sector_choice(meta, preselected)
    if pending_sector_id and default_type and default_name:
        st.session_state[f"{key_prefix}_type"] = default_type
        st.session_state[f"{key_prefix}_name"] = default_name
    type_index = available_types.index(default_type) if default_type in available_types else 0
    board_type = st.selectbox("板块类型", available_types, index=type_index, format_func=lambda x: SECTOR_TYPE_LABELS.get(x, x), key=f"{key_prefix}_type")
    names = meta[meta["sector_type"] == board_type]["sector_name"].tolist()
    if not names:
        st.info("该类型暂无数据。")
        return None
    name_index = names.index(default_name) if default_name in names and board_type == default_type else 0
    name = st.selectbox("板块名称", names, index=name_index, key=f"{key_prefix}_name")
    row = meta[(meta["sector_type"] == board_type) & (meta["sector_name"] == name)].iloc[0]
    return str(row["sector_id"])


def _load_sector_ohlcv_for_detail(storage: DuckDBStorage, sector_id: str) -> pd.DataFrame:
    if sector_id.startswith("custom:"):
        return storage.read_df(
            """
            SELECT basket_id AS sector_id, trade_date, close, daily_ret AS pct_chg, volume, amount
            FROM custom_basket_ohlcv
            WHERE basket_id = ?
            ORDER BY trade_date
            """,
            [sector_id],
        )
    return storage.read_df("SELECT * FROM sector_ohlcv WHERE sector_id = ? ORDER BY trade_date", [sector_id])


def _constituents_for_detail(storage: DuckDBStorage, sector_id: str) -> pd.DataFrame:
    if sector_id.startswith("custom:"):
        return storage.read_df(
            """
            SELECT
              m.stock_code,
              COALESCE(NULLIF(m.stock_name, ''), u.stock_name, m.stock_code) AS stock_name
            FROM custom_stock_basket_members m
            LEFT JOIN all_a_stock_universe u ON u.stock_code = m.stock_code
            WHERE m.basket_id = ?
            ORDER BY m.stock_code
            """,
            [sector_id],
        )
    return storage.read_df(
        """
        SELECT
          c.stock_code,
          COALESCE(NULLIF(c.stock_name, ''), u.stock_name, c.stock_code) AS stock_name
        FROM sector_constituents c
        LEFT JOIN all_a_stock_universe u ON u.stock_code = c.stock_code
        WHERE c.sector_id = ?
        ORDER BY c.stock_code
        """,
        [sector_id],
    )


def _global_stock_sector_candidates(storage: DuckDBStorage) -> pd.DataFrame:
    sector_candidates = storage.read_df(
        """
        SELECT DISTINCT
          c.stock_code,
          COALESCE(NULLIF(c.stock_name, ''), u.stock_name, c.stock_code) AS stock_name,
          c.sector_id,
          m.sector_type,
          m.sector_name
        FROM sector_constituents c
        JOIN sector_meta m ON m.sector_id = c.sector_id
        LEFT JOIN all_a_stock_universe u ON u.stock_code = c.stock_code
        WHERE c.stock_code IS NOT NULL
          AND COALESCE(m.is_active, TRUE)
        ORDER BY c.stock_code, m.sector_type, m.sector_name
        """
    )
    custom_meta = custom_basket_sector_meta(storage)
    if not custom_meta.empty:
        custom_ids = custom_meta["sector_id"].astype(str).drop_duplicates().tolist()
        placeholders = ",".join(["?"] * len(custom_ids))
        custom_candidates = storage.read_df(
            f"""
            SELECT DISTINCT
              b.stock_code,
              COALESCE(NULLIF(b.stock_name, ''), u.stock_name, b.stock_code) AS stock_name,
              b.basket_id AS sector_id,
              'custom' AS sector_type
            FROM custom_stock_basket_members b
            LEFT JOIN all_a_stock_universe u ON u.stock_code = b.stock_code
            WHERE b.basket_id IN ({placeholders})
            ORDER BY b.stock_code
            """,
            custom_ids,
        )
        if not custom_candidates.empty:
            custom_candidates = custom_candidates.merge(
                custom_meta[["sector_id", "sector_name"]],
                on="sector_id",
                how="left",
            )
            sector_candidates = pd.concat([sector_candidates, custom_candidates], ignore_index=True)
    if sector_candidates.empty:
        return sector_candidates
    out = sector_candidates.copy()
    out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
    out["stock_name"] = out["stock_name"].fillna("").astype(str)
    out["sector_id"] = out["sector_id"].astype(str)
    out["sector_type"] = out["sector_type"].fillna("").astype(str)
    out["sector_name"] = out["sector_name"].fillna("").astype(str)
    return out.drop_duplicates(["stock_code", "sector_id"]).sort_values(["stock_code", "sector_type", "sector_name"]).reset_index(drop=True)


def _stock_option_label(stock_code: object, stock_name: object | None = None) -> str:
    code = str(stock_code).strip().zfill(6)
    name = "" if stock_name is None or pd.isna(stock_name) else str(stock_name).strip()
    return f"{name}（{code}）" if name else code


def _stock_sector_candidate_label(row: pd.Series | dict[str, object]) -> str:
    code = row.get("stock_code", "")
    name = row.get("stock_name", "")
    sector_type = SECTOR_TYPE_LABELS.get(str(row.get("sector_type", "")), str(row.get("sector_type", "")))
    sector_name = str(row.get("sector_name", "") or row.get("sector_id", ""))
    return f"{_stock_option_label(code, name)} | {sector_type}：{sector_name}"


def _filter_stock_sector_candidates(candidates: pd.DataFrame, query: str, limit: int = 50) -> pd.DataFrame:
    if candidates.empty:
        return candidates
    text = str(query or "").strip()
    if not text:
        return candidates.head(0)
    normalized_code = "".join(ch for ch in text if ch.isdigit())
    haystack = (
        candidates["stock_code"].astype(str)
        + " "
        + candidates["stock_name"].astype(str)
        + " "
        + candidates["sector_name"].astype(str)
    )
    mask = haystack.str.contains(text, case=False, regex=False, na=False)
    if normalized_code:
        mask = mask | candidates["stock_code"].astype(str).str.contains(normalized_code, regex=False, na=False)
    out = candidates[mask].copy()
    if out.empty:
        return out
    out["_rank"] = 3
    out.loc[out["stock_code"].astype(str).eq(normalized_code.zfill(6)), "_rank"] = 0
    out.loc[out["stock_name"].astype(str).eq(text), "_rank"] = 1
    out.loc[out["stock_name"].astype(str).str.contains(text, case=False, regex=False, na=False), "_rank"] = out["_rank"].clip(upper=2)
    return out.sort_values(["_rank", "sector_type", "sector_name", "stock_code"]).drop(columns=["_rank"]).head(limit)


def _overlay_option_maps(cons: pd.DataFrame) -> tuple[list[str], dict[str, str], dict[str, str]]:
    if cons.empty:
        return [], {}, {}
    work = cons.copy()
    work["stock_code"] = work["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(work["stock_code"].astype(str)).str.zfill(6)
    work["stock_name"] = work["stock_name"].fillna("").astype(str)
    labels = work.apply(lambda r: _stock_option_label(r["stock_code"], r.get("stock_name")), axis=1).tolist()
    label_to_code = dict(zip(labels, work["stock_code"], strict=False))
    code_to_label = dict(zip(work["stock_code"], labels, strict=False))
    return labels, label_to_code, code_to_label


def _sync_overlay_selection_state(options: list[str], code_to_label: dict[str, str], key: str, pending_code: object | None) -> None:
    existing = st.session_state.get(key, [])
    selected = [item for item in existing if item in options] if isinstance(existing, list) else []
    if pending_code is not None:
        code = str(pending_code).strip().zfill(6)
        label = code_to_label.get(code)
        if label and label not in selected:
            selected = [label, *selected]
            st.session_state.pop("detail_overlay_pending_stock_code", None)
    if selected != existing:
        st.session_state[key] = selected[:5]


def _render_stock_overlay_locator(
    storage: DuckDBStorage,
    current_sector_id: str,
    selected_universe: str | None,
) -> None:
    candidates = _global_stock_sector_candidates(storage)
    if candidates.empty:
        return
    left, right = st.columns([2, 3])
    query = left.text_input("按代码或名称定位个股", value="", placeholder="例如 002709 或 天赐材料", help="输入股票代码或名称，选择所属板块后自动切到该板块并加入叠加。")
    matches = _filter_stock_sector_candidates(candidates, query)
    if query.strip() and matches.empty:
        right.info("没有找到匹配个股。")
        return
    if matches.empty:
        right.caption("输入股票代码或名称后，会显示可切换的所属板块。")
        return
    labels = [_stock_sector_candidate_label(row) for _, row in matches.iterrows()]
    label_to_row = {label: row for label, (_, row) in zip(labels, matches.iterrows(), strict=False)}
    selected_label = right.selectbox("匹配结果", labels, key="detail_overlay_stock_locator_result")
    selected_row = label_to_row[selected_label]
    target_sector_id = str(selected_row["sector_id"])
    target_code = str(selected_row["stock_code"]).zfill(6)
    if st.button("切换到所属板块并叠加", key="detail_overlay_jump_to_stock"):
        st.session_state["selected_sector_id_for_detail"] = target_sector_id
        st.session_state["detail_overlay_pending_sector_id"] = target_sector_id
        st.session_state["detail_overlay_pending_stock_code"] = target_code
        if selected_universe:
            allowed_ids = set(universe_sector_ids(storage, selected_universe, include_custom_baskets=True))
            if target_sector_id not in allowed_ids:
                st.session_state["detail_use_universe"] = False
        if target_sector_id == current_sector_id:
            st.rerun()
        st.rerun()


def _stock_overlay_coverage(storage: DuckDBStorage, stock_codes: list[str], sector_ohlcv: pd.DataFrame) -> pd.DataFrame:
    if not stock_codes:
        return pd.DataFrame()
    placeholders = ",".join(["?"] * len(stock_codes))
    stocks = storage.read_df(
        f"""
        SELECT *
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
        ORDER BY stock_code, trade_date
        """,
        stock_codes,
    )
    if stocks.empty:
        return pd.DataFrame()
    stocks = add_a_share_limit_flags(stocks)
    sector = sector_ohlcv.copy()
    sector["trade_date"] = pd.to_datetime(sector["trade_date"])
    sector_ret20 = pd.to_numeric(sector.set_index("trade_date")["close"], errors="coerce").pct_change(20)
    rows: list[dict[str, object]] = []
    for code, group in stocks.groupby("stock_code"):
        g = group.sort_values("trade_date").copy()
        close = pd.to_numeric(g["close"], errors="coerce")
        latest = g.iloc[-1]
        trade_dates = pd.to_datetime(g["trade_date"])
        ret20 = close.iloc[-1] / close.iloc[-21] - 1 if len(close.dropna()) >= 21 else pd.NA
        latest_date = trade_dates.iloc[-1]
        rs20 = pd.NA
        if pd.notna(ret20) and latest_date in sector_ret20.index:
            rs20 = float(ret20 - sector_ret20.loc[latest_date])
        rows.append(
            {
                "stock_code": str(code).zfill(6),
                "first_date": trade_dates.min().date(),
                "last_date": latest_date.date(),
                "count": int(close.notna().sum()),
                "missing_recent": bool(latest_date < pd.to_datetime(sector["trade_date"]).max()),
                "ret_20d": ret20,
                "rs_vs_sector_20d": rs20,
                "is_limit_up": bool(latest.get("is_limit_up", False)),
                "is_limit_down": bool(latest.get("is_limit_down", False)),
                "is_one_word_limit": bool(latest.get("is_one_word_limit", False)),
                "consecutive_limit_up_days": int(latest.get("consecutive_limit_up_days", 0) or 0),
                "consecutive_limit_down_days": int(latest.get("consecutive_limit_down_days", 0) or 0),
                "gap_1d": latest.get("gap_1d"),
            }
        )
    return pd.DataFrame(rows)


def _resolve_overlay_start(ohlcv: pd.DataFrame, segments: pd.DataFrame, mode: str) -> pd.Timestamp:
    dates = pd.to_datetime(ohlcv["trade_date"], errors="coerce").dropna().sort_values().drop_duplicates()
    if dates.empty:
        return pd.Timestamp.today().normalize()
    if mode == "最近一次状态切换日" and not segments.empty:
        return pd.to_datetime(segments.iloc[-1]["start_date"])
    if mode == "最近60个交易日":
        return dates.iloc[max(len(dates) - 60, 0)]
    if mode == "当前窗口起点":
        return dates.iloc[0]
    return dates.iloc[max(len(dates) - 260, 0)]


def _overlay_scale_warning(overlay: pd.DataFrame) -> str:
    if overlay.empty or "normalized_close" not in overlay.columns:
        return ""
    stats = overlay.groupby("label")["normalized_close"].max()
    stats = pd.to_numeric(stats, errors="coerce").dropna()
    stats = stats[stats > 0]
    if len(stats) < 2:
        return ""
    ratio = float(stats.max() / stats.min())
    if ratio < 20:
        return ""
    return (
        f"当前窗口内不同曲线最大归一化净值相差约 {ratio:.1f} 倍，"
        "线性坐标会把较小曲线压到图底。建议缩短起始窗口，或切换为对数纵轴。"
    )


def _sector_extreme_return_warning(ohlcv: pd.DataFrame, start_date: pd.Timestamp) -> str:
    if ohlcv.empty:
        return ""
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work["close"] = pd.to_numeric(work["close"], errors="coerce")
    work = work[work["trade_date"] >= pd.to_datetime(start_date)].sort_values("trade_date")
    returns = work["close"].pct_change(fill_method=None).dropna()
    if returns.empty:
        return ""
    extreme = float(returns.abs().max())
    if extreme < 0.5:
        return ""
    date = work.loc[returns.abs().idxmax(), "trade_date"]
    return (
        f"当前窗口内板块本地聚合指数存在最大单日跳变 {extreme:.1%}（{date.date()}）。"
        "这通常来自成分股历史复权、北交所/历史行情异常或极端跳变，会明显拉大长周期坐标。"
    )


def render_sector_detail(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("板块详情")
    selected_universe = universe_id
    if universe_id:
        use_universe = st.checkbox("只显示当前板块池中的板块", value=True, key="detail_use_universe")
        selected_universe = universe_id if use_universe else None
    run_id = render_run_scope_status(storage, selected_universe)
    render_data_status_bar(storage, run_id=run_id, universe_id=selected_universe)
    sector_id = _select_sector(storage, "detail", universe_id=selected_universe)
    if not sector_id:
        return
    ohlcv = _load_sector_ohlcv_for_detail(storage, sector_id)
    history = sector_state_history(sector_id, storage, run_id=run_id, days=260) if run_id else pd.DataFrame()
    if ohlcv.empty:
        if sector_id.startswith("custom:"):
            st.warning("该自定义股票池尚未生成指数，请先更新股票池行情并生成指数。")
        else:
            st.warning("该板块暂无行情。")
        return
    ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"])
    ohlcv["sector_id"] = sector_id
    segments = build_state_segments(history, ohlcv) if not history.empty else pd.DataFrame()
    tab_overview, tab_cycles, tab_overlay, tab_rank = st.tabs(["状态总览", "周期切换", "高级：个股叠加", "高级：成分股排名"])

    with tab_overview:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ohlcv["trade_date"], y=ohlcv["close"], mode="lines", name="收盘价"))
        if not segments.empty:
            for row in segments.itertuples(index=False):
                fig.add_vrect(
                    x0=row.start_date,
                    x1=row.end_date,
                    fillcolor=SECTOR_STATE_BG_COLORS.get(row.state_label, "rgba(150,150,150,0.08)"),
                    opacity=0.7,
                    line_width=0,
                )
        fig.update_layout(height=420, title="价格与状态背景", xaxis_title="交易日期", yaxis_title="收盘价", xaxis_rangeslider_visible=False)
        st.plotly_chart(fig, width="stretch")

        if not history.empty:
            latest = history.iloc[-1]
            c1, c2, c3 = st.columns(3)
            c1.metric("当前状态", display_state_label(latest["state_label"]))
            c2.metric("TrendUp 状态后验", format_probability(latest["prob_trend_up"]))
            c3.metric("压力状态后验", format_probability(latest["prob_risk_off"]))
            state_source = latest.get("state_source", "in_sample_display")
            if state_source == "in_sample_display":
                st.warning("当前状态来源为训练样本内展示，仅用于观察模型拟合，不是因果回测状态。")
            else:
                st.info("当前状态来源为因果 walk-forward。")
            st.caption("模型迁移分布 JSON 属于内部转移矩阵字段；Stage 00 不把它展示为价格方向、收益或交易概率。")
            history_display = history.tail(60).drop(columns=["next_state_probs_json"], errors="ignore")
            history_display = format_probability_columns(
                history_display,
                ["prob_trend_up", "prob_neutral", "prob_risk_off"],
            )
            st.dataframe(rename_columns_for_display(history_display), width="stretch")

        st.subheader("状态转移矩阵")
        matrix = _sector_transition_matrix(storage, run_id)
        if matrix.empty:
            st.info("暂无状态转移矩阵。")
        else:
            fig_matrix = px.imshow(matrix, text_auto=".1%", aspect="auto", color_continuous_scale="Greens", title="状态转移矩阵")
            st.plotly_chart(fig_matrix, width="stretch")
            with st.expander("查看矩阵数据"):
                st.dataframe(matrix, width="stretch")

    with tab_cycles:
        if segments.empty:
            st.info("暂无状态周期数据。")
        else:
            display_segments = segments.copy()
            display_segments["状态"] = display_segments["state_label"].map(display_state_label)
            color_map = {display_state_label(k): v for k, v in SECTOR_STATE_COLORS.items()}
            fig_timeline = px.timeline(display_segments, x_start="start_date", x_end="end_date", y="sector_id", color="状态", color_discrete_map=color_map, title="状态周期时间轴")
            fig_timeline.update_yaxes(title="")
            st.plotly_chart(fig_timeline, width="stretch")
            fig_duration = px.bar(display_segments, x="segment_id", y="trading_days", color="状态", color_discrete_map=color_map, title="周期持续时间")
            fig_duration.update_layout(xaxis_title="状态段", yaxis_title="交易日数量")
            st.plotly_chart(fig_duration, width="stretch")
            current = segments.iloc[-1]
            past_year_cutoff = pd.to_datetime(ohlcv["trade_date"].max()) - pd.Timedelta(days=365)
            past_year = segments[segments["start_date"] >= past_year_cutoff]
            c1, c2, c3, c4, c5, c6 = st.columns(6)
            c1.metric("当前状态已持续交易日", int(current["trading_days"]))
            c2.metric("最近一次切换日期", str(current["start_date"].date()))
            c3.metric("过去一年趋势段数", int((past_year["state_label"] == "TrendUp").sum()))
            c4.metric("过去一年压力状态段数", int((past_year["state_label"] == "RiskOff").sum()))
            c5.metric("趋势段平均持续", f"{segments.loc[segments['state_label'].eq('TrendUp'), 'trading_days'].mean():.1f}")
            c6.metric("压力状态段平均持续", f"{segments.loc[segments['state_label'].eq('RiskOff'), 'trading_days'].mean():.1f}")
            table = segments.copy()
            table["state_label"] = table["state_label"].map(display_state_label)
            table["prev_state_label"] = table["prev_state_label"].map(lambda x: "" if pd.isna(x) else display_state_label(x))
            table["next_state_label"] = table["next_state_label"].map(lambda x: "" if pd.isna(x) else display_state_label(x))
            table = format_probability_columns(table, ["avg_prob_trend_up", "avg_prob_neutral", "avg_prob_risk_off"])
            st.dataframe(rename_columns_for_display(table), width="stretch")

    with tab_overlay:
        st.caption("归一化走势用于比较相对强弱，不代表价格绝对水平。")
        st.caption("涨跌停判断为近似估计，暂未精确区分 ST、创业板、科创板、北交所涨跌幅限制。")
        _render_stock_overlay_locator(storage, sector_id, selected_universe)
        cons = _constituents_for_detail(storage, sector_id)
        if cons.empty:
            st.info("暂无成分股或自定义股票池成员。")
        else:
            cons["stock_code"] = cons["stock_code"].astype(str).str.zfill(6)
            options, label_to_code, code_to_label = _overlay_option_maps(cons)
            overlay_key = "detail_overlay_selected_stocks"
            _sync_overlay_selection_state(options, code_to_label, overlay_key, st.session_state.get("detail_overlay_pending_stock_code"))
            selected = st.multiselect(
                "选择个股",
                options,
                max_selections=5,
                key=overlay_key,
                help="可输入股票名称或代码搜索；最多叠加 5 只，避免图表过于拥挤。",
            )
            selected_codes = [label_to_code[item] for item in selected if item in label_to_code]
            start_options = ["最近260个交易日", "最近60个交易日", "当前窗口起点"]
            if not segments.empty:
                start_options.append("最近一次状态切换日")
            start_mode = st.radio("起始日期", start_options, horizontal=True, help="默认使用最近 260 个交易日，避免长周期本地聚合指数把个股曲线压扁。")
            y_axis_mode = st.radio("纵轴尺度", ["线性", "对数"], horizontal=True, help="长周期倍率差很大时，对数纵轴更适合比较相对变化。")
            overlay_start = _resolve_overlay_start(ohlcv, segments, start_mode)
            if st.button("更新所选个股行情", disabled=not selected_codes):
                with st.spinner("正在更新所选个股行情..."):
                    summary = update_stock_histories(selected_codes, pd.to_datetime(overlay_start).strftime("%Y%m%d"), today_yyyymmdd(), incremental=True, lookback_days=10, storage=storage)
                st.write(f"更新完成：成功 {summary.sectors_updated}，失败 {len(summary.failures)}，过期缓存 {summary.stale_reads}")
            if selected_codes:
                placeholders = ",".join(["?"] * len(selected_codes))
                stocks = storage.read_df(
                    f"SELECT * FROM stock_ohlcv WHERE stock_code IN ({placeholders}) ORDER BY stock_code, trade_date",
                    selected_codes,
                )
                stock_names = dict(zip(cons["stock_code"], cons["stock_name"], strict=False))
                overlay = build_stock_overlay_normalized_series(ohlcv, stocks, stock_names=stock_names, start_date=overlay_start)
                if overlay.empty:
                    st.info("暂无所选个股行情。")
                else:
                    fig_overlay = go.Figure()
                    for row in segments.itertuples(index=False):
                        if row.end_date < pd.to_datetime(overlay_start):
                            continue
                        fig_overlay.add_vrect(
                            x0=max(row.start_date, pd.to_datetime(overlay_start)),
                            x1=row.end_date,
                            fillcolor=SECTOR_STATE_BG_COLORS.get(row.state_label, "rgba(150,150,150,0.08)"),
                            opacity=0.75,
                            line_width=0,
                        )
                    for label, group in overlay.groupby("label"):
                        fig_overlay.add_trace(go.Scatter(x=group["trade_date"], y=group["normalized_close"], mode="lines", name=label))
                    fig_overlay.update_layout(height=420, title="板块与个股归一化走势", xaxis_title="交易日期", yaxis_title="归一化净值")
                    if y_axis_mode == "对数" and (pd.to_numeric(overlay["normalized_close"], errors="coerce") > 0).all():
                        fig_overlay.update_yaxes(type="log")
                    st.plotly_chart(fig_overlay, width="stretch")
                    scale_warning = _overlay_scale_warning(overlay)
                    if scale_warning:
                        st.warning(scale_warning)
                    extreme_warning = _sector_extreme_return_warning(ohlcv, pd.to_datetime(overlay_start))
                    if extreme_warning:
                        st.warning(extreme_warning)
                    coverage = _stock_overlay_coverage(storage, selected_codes, ohlcv)
                    if not coverage.empty:
                        st.dataframe(rename_columns_for_display(coverage), width="stretch")

    with tab_rank:
        st.subheader("当前成分股排名")
        st.caption("个股排名会读取并计算成分股行情，数据较多时可能耗时；需要时再手动计算。")
        if st.button("计算当前成分股排名"):
            with st.spinner("正在计算成分股排名..."):
                scores = filter_sector_stocks(sector_id, storage=storage)
            if scores.empty:
                st.info("暂无个股评分。请先抓取该板块成分股对应的个股行情。")
            else:
                st.dataframe(rename_columns_for_display(scores.head(50)), width="stretch")
