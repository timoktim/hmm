from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.evidence_badges import readiness_badge
from src.ui.readiness_policy import evaluate_hsmm_lifecycle_field_display, is_numeric_p_exit_field
from src.ui.run_context import latest_completed_hsmm_lifecycle_run, list_completed_hsmm_lifecycle_profiles


LIFECYCLE_UI_COLUMNS = """
        run_id, profile_mode, state_date_policy, trade_date, sector_code, sector_name,
        state_label, display_episode_id, display_state_age_days, display_age_bucket,
        display_episode_start_date, state_phase, historical_median_duration_days,
        historical_p10_duration_days, historical_p25_duration_days,
        historical_p33_duration_days, historical_p66_duration_days,
        historical_p75_duration_days, historical_p90_duration_days,
        duration_percentile_display, exit_tendency_1d, exit_tendency_3d,
        exit_tendency_5d, exit_tendency_10d, exit_tendency_20d,
        exit_tendency_basis_1d, exit_tendency_basis_3d, exit_tendency_basis_5d,
        exit_tendency_basis_10d, exit_tendency_basis_20d,
        probability_display_policy, probability_status_1d, probability_status_3d,
        probability_status_5d, probability_status_10d, probability_status_20d,
        next_state_tendency, next_state_tendency_label,
        next_state_tendency_label_status, next_state_tendency_label_sample_count,
        next_state_tendency_label_top_share, next_state_tendency_phase_aware,
        next_state_tendency_phase_status, next_state_tendency_phase_sample_count,
        next_state_tendency_phase_top_share, next_state_tendency_age_bucket,
        next_state_tendency_age_status, next_state_tendency_age_sample_count,
        next_state_tendency_age_top_share, profile_cutoff_date,
        profile_sample_window_start, profile_sample_window_end,
        source_checkpoint_id, source_run_id, source_probability_run_id,
        state_source, created_at
"""

STATE_LABELS = {
    "Trend": "趋势",
    "Neutral": "中性",
    "Stress": "压力",
    "Repair": "修复",
    "Mixed": "混合",
    "Unavailable": "样本不足",
}
PHASE_LABELS = {
    "early": "早段",
    "mature": "中段",
    "late": "晚段",
    "unknown": "未知",
}
TENDENCY_LABELS = {
    "low": "低倾向",
    "medium": "中倾向",
    "high": "高倾向",
    "unavailable": "样本不足",
}


def _format_share(value: object) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "无"
    return f"{float(numeric):.1%}"


def _latest_lifecycle_run(storage: DuckDBStorage, require_profile_metadata: bool = False) -> str | None:
    if require_profile_metadata:
        return latest_completed_hsmm_lifecycle_run(storage)
    run = storage.read_df(
        """
        SELECT ui.run_id
        FROM hsmm_lifecycle_ui_daily ui
        JOIN hsmm_model_runs runs
          ON runs.run_id = ui.run_id
         AND runs.run_status = 'completed'
        ORDER BY ui.created_at DESC NULLS LAST
        LIMIT 1
        """
    )
    if not run.empty:
        return str(run.loc[0, "run_id"])
    states = storage.read_df(
        """
        SELECT states.run_id
        FROM hsmm_state_daily states
        JOIN hsmm_model_runs runs
          ON runs.run_id = states.run_id
         AND runs.run_status = 'completed'
        ORDER BY states.created_at DESC NULLS LAST
        LIMIT 1
        """
    )
    return None if states.empty else str(states.loc[0, "run_id"])


def _latest_profile_cutoff(storage: DuckDBStorage, run_id: str, profile_mode: str, state_date_policy: str) -> pd.Timestamp | None:
    cutoff = storage.read_df(
        """
        SELECT MAX(profile_cutoff_date) AS profile_cutoff_date
        FROM hsmm_lifecycle_ui_daily
        WHERE run_id = ?
          AND profile_mode = ?
          AND state_date_policy = ?
        """,
        [run_id, profile_mode, state_date_policy],
    )
    if cutoff.empty or pd.isna(cutoff.loc[0, "profile_cutoff_date"]):
        return None
    return pd.to_datetime(cutoff.loc[0, "profile_cutoff_date"], errors="coerce")


def _load_lifecycle_latest_daily(
    storage: DuckDBStorage,
    run_id: str,
    profile_mode: str,
    state_date_policy: str = "full_run",
    profile_cutoff_date: object | None = None,
) -> pd.DataFrame:
    cutoff = pd.to_datetime(profile_cutoff_date, errors="coerce") if profile_cutoff_date is not None else _latest_profile_cutoff(storage, run_id, profile_mode, state_date_policy)
    if cutoff is None or pd.isna(cutoff):
        return pd.DataFrame()
    df = storage.read_df(
        f"""
        SELECT
        {LIFECYCLE_UI_COLUMNS}
        FROM hsmm_lifecycle_ui_daily
        WHERE run_id = ?
          AND profile_mode = ?
          AND profile_cutoff_date = ?
          AND state_date_policy = ?
          AND trade_date = (
            SELECT MAX(trade_date)
            FROM hsmm_lifecycle_ui_daily
            WHERE run_id = ?
              AND profile_mode = ?
              AND profile_cutoff_date = ?
              AND state_date_policy = ?
          )
        ORDER BY sector_code
        """,
        [run_id, profile_mode, cutoff.date(), state_date_policy, run_id, profile_mode, cutoff.date(), state_date_policy],
    )
    for col in ["trade_date", "display_episode_start_date", "profile_cutoff_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df


def _load_sector_trajectory(
    storage: DuckDBStorage,
    run_id: str,
    sector_code: str,
    profile_mode: str,
    state_date_policy: str,
    profile_cutoff_date: object,
    lookback_days: int,
) -> pd.DataFrame:
    cutoff = pd.to_datetime(profile_cutoff_date, errors="coerce")
    if pd.isna(cutoff):
        return pd.DataFrame()
    df = storage.read_df(
        """
        SELECT trade_date, sector_code, sector_name, state_label, state_phase,
               display_state_age_days, exit_tendency_5d, exit_tendency_10d,
               next_state_tendency_phase_aware, next_state_tendency_phase_status,
               next_state_tendency_phase_sample_count, next_state_tendency_phase_top_share
        FROM hsmm_lifecycle_ui_daily
        WHERE run_id = ?
          AND profile_mode = ?
          AND profile_cutoff_date = ?
          AND state_date_policy = ?
          AND sector_code = ?
        ORDER BY trade_date DESC
        LIMIT ?
        """,
        [run_id, profile_mode, cutoff.date(), state_date_policy, sector_code, int(lookback_days)],
    )
    if df.empty:
        return df
    df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    return df.sort_values("trade_date").reset_index(drop=True)


def _load_profile_metadata(storage: DuckDBStorage, run_id: str, profile_mode: str, state_date_policy: str) -> pd.DataFrame:
    return storage.read_df(
        """
        SELECT *
        FROM hsmm_lifecycle_profile_metadata
        WHERE run_id = ?
          AND profile_mode = ?
          AND state_date_policy = ?
        ORDER BY created_at DESC NULLS LAST
        LIMIT 1
        """,
        [run_id, profile_mode, state_date_policy],
    )


def _load_duration_profile(
    storage: DuckDBStorage,
    run_id: str,
    profile_mode: str,
    profile_cutoff_date: object,
) -> pd.DataFrame:
    cutoff = pd.to_datetime(profile_cutoff_date, errors="coerce")
    if pd.isna(cutoff):
        return pd.DataFrame()
    return storage.read_df(
        """
        SELECT *
        FROM hsmm_lifecycle_duration_profile
        WHERE run_id = ?
          AND profile_mode = ?
          AND profile_cutoff_date = ?
        ORDER BY state_label
        """,
        [run_id, profile_mode, cutoff.date()],
    )


def _load_recent_display_episodes(
    storage: DuckDBStorage,
    run_id: str,
    sector_code: str,
    asof_date: object,
    limit: int = 8,
) -> pd.DataFrame:
    asof = pd.to_datetime(asof_date, errors="coerce")
    if pd.isna(asof):
        return pd.DataFrame()
    df = storage.read_df(
        """
        SELECT state_label, start_date, end_date, duration_trading_days,
               is_left_censored, is_right_censored
        FROM hsmm_display_label_episodes
        WHERE run_id = ?
          AND sector_code = ?
          AND start_date <= ?
        ORDER BY start_date DESC
        LIMIT ?
        """,
        [run_id, sector_code, asof.date(), int(limit)],
    )
    for col in ["start_date", "end_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    return df.sort_values("start_date").reset_index(drop=True)


def _load_lifecycle_ui_daily(storage: DuckDBStorage, run_id: str, profile_mode: str) -> pd.DataFrame:
    return _load_lifecycle_latest_daily(storage, run_id, profile_mode)


def _display_state(value: object) -> str:
    return STATE_LABELS.get(str(value), str(value))


def _display_phase(value: object) -> str:
    return PHASE_LABELS.get(str(value), str(value))


def _display_tendency(value: object) -> str:
    return TENDENCY_LABELS.get(str(value), str(value))


def _attach_lifecycle_readiness(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    decision = evaluate_hsmm_lifecycle_field_display("state_age")
    badge = readiness_badge(decision)
    out["evidence_level"] = decision.evidence_level
    out["readiness_status"] = decision.readiness_status
    out["readiness_badge"] = badge["label"]
    if "state_source" not in out.columns:
        out["state_source"] = "unknown_due_to_missing_metadata"
    return out


def _display_frame(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in list(out.columns):
        if is_numeric_p_exit_field(col):
            decision = evaluate_hsmm_lifecycle_field_display(col)
            if not decision.display:
                out.drop(columns=[col], inplace=True)
    for col in ["state_label", "next_state_tendency_phase_aware", "next_state_tendency_age_bucket"]:
        if col in out.columns:
            out[col] = out[col].map(_display_state)
    if "state_phase" in out.columns:
        out["state_phase"] = out["state_phase"].map(_display_phase)
    for col in ["exit_tendency_5d", "exit_tendency_10d", "exit_tendency_20d"]:
        if col in out.columns:
            out[col] = out[col].map(_display_tendency)
    return out


def render_lifecycle_page(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("状态生命周期")
    st.caption(
        "内部诊断页：用于观察板块展示状态的持续时间、阶段位置和低/中/高退出倾向。"
        "输出不是排序、交易建议或价格方向判断。"
    )

    run_id_default = _latest_lifecycle_run(storage, require_profile_metadata=True)
    if not run_id_default:
        render_data_status_bar(storage, run_id=None, universe_id=universe_id)
        st.warning("尚未生成状态生命周期数据。请先运行 HSMM 生命周期 UI 数据生成命令。")
        return
    render_data_status_bar(storage, run_id=run_id_default, universe_id=universe_id)

    available_runs = list_completed_hsmm_lifecycle_profiles(storage)
    if not available_runs.empty:
        available_runs = available_runs.drop_duplicates("run_id").sort_values("run_id")
    run_options = available_runs["run_id"].astype(str).tolist() if not available_runs.empty else [run_id_default]
    default_index = run_options.index(run_id_default) if run_id_default in run_options else 0
    c1, c2, c3 = st.columns([2, 1, 1])
    run_id = c1.selectbox("生命周期 run", run_options, index=default_index, help="选择已生成的生命周期 UI 数据 run。")
    profile_mode = c2.radio(
        "Profile 口径",
        ["latest_asof", "retrospective"],
        horizontal=True,
        help="latest_asof 使用截止日前已完成的展示状态周期；retrospective 使用完整 run 的已完成周期。",
    )
    state_date_policy = c3.radio(
        "日期口径",
        ["full_run", "cutoff_only"],
        horizontal=True,
        help="full_run 显示该 run 的最新截面；cutoff_only 用于历史回放，只显示截止日及之前的状态行。",
    )

    cutoff = _latest_profile_cutoff(storage, run_id, profile_mode, state_date_policy)
    ui = _load_lifecycle_latest_daily(storage, run_id, profile_mode, state_date_policy, cutoff)
    if ui.empty:
        st.warning("当前 run、profile 口径和日期口径下没有生命周期 UI 数据。")
        return

    metadata = _load_profile_metadata(storage, run_id, profile_mode, state_date_policy)
    latest_date = ui["trade_date"].max()
    latest = _attach_lifecycle_readiness(ui)
    if universe_id:
        items = storage.list_universe_items(universe_id)
        allowed = set(items["item_id"].astype(str)) if not items.empty else set()
        latest = latest[latest["sector_code"].astype(str).isin(allowed)].copy()

    st.subheader("当前状态概览")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("最新日期", latest_date.date() if pd.notna(latest_date) else "无")
    m2.metric("板块数量", len(latest))
    m3.metric("Profile 口径", profile_mode)
    m4.metric("Profile 截止日", cutoff.date() if pd.notna(cutoff) else "无")
    if not metadata.empty:
        row = metadata.iloc[0]
        st.caption(
            f"样本窗口：{row.get('profile_window_start')} 至 {row.get('profile_window_end')}；"
            f"已完成展示周期数：{row.get('completed_episode_count')}"
        )

    st.info(
        "退出倾向为低 / 中 / 高的内部诊断分组，不是百分比概率。"
        "历史下一状态倾向来自已实现的展示状态切换 profile，不是模型预测概率。"
        "Stress 表示当前压力状态，不代表未来一定走弱。"
    )

    st.subheader("状态分布")
    if not latest.empty:
        state_counts = latest["state_label"].map(_display_state).value_counts().rename_axis("状态").reset_index(name="板块数")
        phase_counts = latest["state_phase"].map(_display_phase).value_counts().rename_axis("阶段").reset_index(name="板块数")
        c3, c4 = st.columns(2)
        c3.dataframe(state_counts, use_container_width=True, hide_index=True)
        c4.dataframe(phase_counts, use_container_width=True, hide_index=True)

    st.subheader("关注列表")
    states = sorted(latest["state_label"].dropna().astype(str).unique())
    selected_states = st.multiselect(
        "展示状态",
        states,
        default=states,
        format_func=_display_state,
        help="当前板块展示状态。Stress 表示压力/弱势/高波动状态，不代表未来一定走弱。",
    )
    selected_tendency = st.multiselect(
        "5日退出倾向",
        ["low", "medium", "high", "unavailable"],
        default=["low", "medium", "high", "unavailable"],
        format_func=_display_tendency,
        help="历史统计和模型输出综合形成的相对退出倾向，仅分为低/中/高，不是精确概率。",
    )
    selected_tendency_10d = st.multiselect(
        "10日退出倾向",
        ["low", "medium", "high", "unavailable"],
        default=["low", "medium", "high", "unavailable"],
        format_func=_display_tendency,
        help="比 5 日更长的状态延续观察口径，仍只表示相对倾向。",
    )
    filtered = latest[
        latest["state_label"].astype(str).isin(selected_states)
        & latest["exit_tendency_5d"].astype(str).isin(selected_tendency)
        & latest["exit_tendency_10d"].astype(str).isin(selected_tendency_10d)
    ].copy()
    for col in [
        "next_state_tendency_phase_top_share",
        "next_state_tendency_age_top_share",
        "next_state_tendency_label_top_share",
    ]:
        if col in filtered.columns:
            filtered[col] = filtered[col].map(_format_share)
    display_cols = [
        "run_id",
        "sector_code",
        "sector_name",
        "state_label",
        "display_state_age_days",
        "state_phase",
        "historical_median_duration_days",
        "exit_tendency_5d",
        "exit_tendency_10d",
        "next_state_tendency_phase_aware",
        "next_state_tendency_phase_status",
        "next_state_tendency_phase_sample_count",
        "next_state_tendency_phase_top_share",
        "next_state_tendency_age_bucket",
        "profile_mode",
        "profile_cutoff_date",
        "state_date_policy",
        "state_source",
        "evidence_level",
        "readiness_status",
        "readiness_badge",
    ]
    display = _display_frame(filtered[[c for c in display_cols if c in filtered.columns]])
    display.rename(
        columns={
            "sector_code": "板块代码",
            "sector_name": "板块名称",
            "state_label": "当前状态",
            "display_state_age_days": "已持续交易日",
            "state_phase": "阶段",
            "historical_median_duration_days": "历史中位持续日",
            "exit_tendency_5d": "5日退出倾向",
            "exit_tendency_10d": "10日退出倾向",
            "next_state_tendency_phase_aware": "按阶段的下一状态倾向",
            "next_state_tendency_phase_status": "阶段样本状态",
            "next_state_tendency_phase_sample_count": "阶段样本数",
            "next_state_tendency_phase_top_share": "阶段历史样本占比",
            "next_state_tendency_age_bucket": "按年龄段的下一状态倾向",
            "run_id": "Run ID",
            "profile_mode": "Profile 口径",
            "profile_cutoff_date": "Profile 截止日",
            "state_date_policy": "状态日期口径",
            "state_source": "状态来源",
            "evidence_level": "证据层级",
            "readiness_status": "Readiness",
            "readiness_badge": "Readiness badge",
        },
        inplace=True,
    )
    st.dataframe(display, use_container_width=True, hide_index=True)

    st.subheader("单板块状态轨迹")
    if filtered.empty:
        st.caption("当前筛选条件下没有可查看的板块。")
    else:
        sector_labels = {
            str(row.sector_code): f"{row.sector_name} | {row.sector_code}"
            for row in filtered[["sector_code", "sector_name"]].drop_duplicates().itertuples(index=False)
        }
        selected_sector = st.selectbox(
            "选择板块",
            list(sector_labels.keys()),
            format_func=lambda code: sector_labels.get(str(code), str(code)),
            help="只读取所选板块的历史状态轨迹，不加载全表历史。",
        )
        lookback_days = st.radio(
            "轨迹窗口",
            [60, 120],
            horizontal=True,
            help="展示最近多少个交易日的展示状态、阶段和退出倾向变化。",
        )
        trajectory = _load_sector_trajectory(storage, run_id, selected_sector, profile_mode, state_date_policy, cutoff, lookback_days)
        if trajectory.empty:
            st.warning("该板块暂无可读取的生命周期轨迹。")
        else:
            age_chart = trajectory.set_index("trade_date")[["display_state_age_days"]].rename(columns={"display_state_age_days": "已持续交易日"})
            st.line_chart(age_chart, use_container_width=True)
            trajectory_display = trajectory.copy()
            trajectory_display["state_label"] = trajectory_display["state_label"].map(_display_state)
            trajectory_display["state_phase"] = trajectory_display["state_phase"].map(_display_phase)
            for col in ["exit_tendency_5d", "exit_tendency_10d"]:
                trajectory_display[col] = trajectory_display[col].map(_display_tendency)
            trajectory_display["next_state_tendency_phase_aware"] = trajectory_display["next_state_tendency_phase_aware"].map(_display_state)
            if "next_state_tendency_phase_top_share" in trajectory_display.columns:
                trajectory_display["next_state_tendency_phase_top_share"] = trajectory_display["next_state_tendency_phase_top_share"].map(_format_share)
            trajectory_display.rename(
                columns={
                    "trade_date": "交易日期",
                    "state_label": "状态",
                    "state_phase": "阶段",
                    "display_state_age_days": "已持续交易日",
                    "exit_tendency_5d": "5日退出倾向",
                    "exit_tendency_10d": "10日退出倾向",
                    "next_state_tendency_phase_aware": "历史同类阶段后续状态",
                    "next_state_tendency_phase_status": "样本状态",
                    "next_state_tendency_phase_sample_count": "样本数",
                    "next_state_tendency_phase_top_share": "历史占比",
                },
                inplace=True,
            )
            st.dataframe(
                trajectory_display[
                    [
                        "交易日期",
                        "状态",
                        "阶段",
                        "已持续交易日",
                        "5日退出倾向",
                        "10日退出倾向",
                        "历史同类阶段后续状态",
                        "样本状态",
                        "样本数",
                        "历史占比",
                    ]
                ],
                use_container_width=True,
                hide_index=True,
            )
            episodes = _load_recent_display_episodes(storage, run_id, selected_sector, latest_date)
            if not episodes.empty:
                episodes["state_label"] = episodes["state_label"].map(_display_state)
                episodes.rename(
                    columns={
                        "state_label": "状态",
                        "start_date": "开始日期",
                        "end_date": "结束日期",
                        "duration_trading_days": "持续交易日",
                        "is_left_censored": "左侧截断",
                        "is_right_censored": "右侧截断",
                    },
                    inplace=True,
                )
                st.dataframe(episodes, use_container_width=True, hide_index=True)

    st.subheader("历史持续时间")
    duration_rows = _load_duration_profile(storage, run_id, profile_mode, cutoff)
    if duration_rows.empty:
        st.caption("暂无 profile-specific 持续时间样本。")
    else:
        duration_rows = duration_rows.copy()
        duration_rows["state_label"] = duration_rows["state_label"].map(_display_state)
        duration_rows.rename(
            columns={
                "state_label": "状态",
                "completed_episode_count": "已完成周期数",
                "median_duration_days": "中位持续日",
                "mean_duration_days": "平均持续日",
                "p10_duration_days": "P10",
                "p25_duration_days": "P25",
                "p75_duration_days": "P75",
                "p90_duration_days": "P90",
                "left_censored_count": "左侧截断数",
                "right_censored_count": "右侧截断数",
            },
            inplace=True,
        )
        st.dataframe(
            duration_rows[["状态", "已完成周期数", "中位持续日", "平均持续日", "P10", "P25", "P75", "P90", "左侧截断数", "右侧截断数"]],
            use_container_width=True,
            hide_index=True,
        )

    with st.expander("字段说明", expanded=False):
        st.markdown(
            """
- **展示状态**：Trend / Neutral / Stress / Repair 的用户可见标签。
- **已持续交易日**：当前展示状态连续存在的交易日数量，跨 checkpoint 不重置。
- **阶段**：根据历史已完成展示周期长度划分为早段、中段、晚段。
- **退出倾向**：低 / 中 / 高相对分组，只表达当前展示状态在指定窗口内结束的内部诊断倾向强弱。
- **历史下一状态倾向**：基于历史上已实现的下一展示状态 profile；样本不足时显示“样本不足”，状态分散时显示“混合”，不是模型预测概率。
            """.strip()
        )
