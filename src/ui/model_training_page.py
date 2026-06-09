from __future__ import annotations

from pathlib import Path

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_display_lifecycle import DEFAULT_HORIZONS, STATE_DATE_POLICIES, write_lifecycle_ui_outputs
from src.models.hmm_model import train_hmm
from src.models.hsmm_walk_forward import HSMMWalkForwardConfig, run_hsmm_walk_forward
from src.models.market_hmm import train_market_hmm
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.components.model_workflow import render_model_workflow
from src.ui.components.operation_result import render_operation_result
from src.ui.help_texts import HELP_TEXTS
from src.ui.market_regime_page import latest60_full_market_breadth_available
from src.utils.dates import today_yyyymmdd


def _training_progress():
    bar = st.progress(0)
    text = st.empty()
    stats = st.empty()

    def on_progress(percent: int, stage: str, payload: dict[str, object]) -> None:
        bar.progress(min(max(percent, 0) / 100, 1.0))
        text.caption(f"{stage}（{percent}%）")
        if payload:
            stats.caption("；".join(f"{k}: {v}" for k, v in payload.items()))

    return on_progress


_HSMM_STAGE_LABELS = {
    "checkpoint_fit_started": "训练检查点",
    "checkpoint_trained": "检查点训练完成",
    "checkpoint_decode_started": "解码检查点",
    "checkpoint_decode_finished": "检查点解码完成",
    "snapshot_decoded": "生成每日状态",
    "insufficient_training_data": "训练样本不足",
    "profile_ready": "性能画像完成",
}


def _parse_hsmm_horizons(value: str) -> tuple[int, ...]:
    parts = [part.strip() for part in value.replace("，", ",").split(",") if part.strip()]
    if not parts:
        raise ValueError("生命周期窗口不能为空。")
    horizons: list[int] = []
    for part in parts:
        try:
            horizon = int(part)
        except ValueError as exc:
            raise ValueError("生命周期窗口必须是整数，并用逗号分隔。") from exc
        if horizon <= 0 or horizon > 250:
            raise ValueError("生命周期窗口必须在 1 到 250 个交易日之间。")
        if horizon not in horizons:
            horizons.append(horizon)
    return tuple(horizons)


def _safe_path_fragment(value: str) -> str:
    text = str(value or "").strip()
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in text)
    return (safe or "hsmm_run")[:120]


def _hsmm_lifecycle_output_dir(run_id: str, profile_mode: str, state_date_policy: str) -> Path:
    fragment = _safe_path_fragment(run_id)
    return Path("reports") / "hsmm_display_lifecycle" / f"{fragment}_{profile_mode}_{state_date_policy}"


def _hsmm_progress():
    bar = st.progress(0)
    text = st.empty()
    stats = st.empty()

    def on_progress(current: int, total: int, trade_date: pd.Timestamp, stage: str) -> None:
        total = max(int(total or 0), 1)
        current = min(max(int(current or 0), 0), total)
        percent = current / total
        bar.progress(percent)
        label = _HSMM_STAGE_LABELS.get(stage, stage)
        date_text = pd.Timestamp(trade_date).strftime("%Y-%m-%d") if trade_date is not None else "N/A"
        text.caption(f"{label}（{current}/{total}）")
        stats.caption(f"日期：{date_text}")

    return on_progress


def _load_hsmm_run_summary(storage: DuckDBStorage) -> pd.DataFrame:
    try:
        return storage.read_df(
            """
            WITH lifecycle AS (
              SELECT run_id,
                     COUNT(*) AS lifecycle_ui_rows,
                     MAX(profile_cutoff_date) AS lifecycle_cutoff_date,
                     MAX(created_at) AS lifecycle_created_at
              FROM hsmm_lifecycle_ui_daily
              GROUP BY run_id
            )
            SELECT runs.run_id,
                   runs.run_status,
                   runs.start_date,
                   runs.end_date,
                   runs.n_states,
                   runs.max_duration,
                   runs.train_window_days,
                   runs.actual_snapshot_count,
                   runs.actual_state_row_count,
                   runs.universe_id,
                   runs.completed_at,
                   runs.created_at,
                   COALESCE(lifecycle.lifecycle_ui_rows, 0) AS lifecycle_ui_rows,
                   lifecycle.lifecycle_cutoff_date,
                   lifecycle.lifecycle_created_at
            FROM hsmm_model_runs runs
            LEFT JOIN lifecycle ON lifecycle.run_id = runs.run_id
            ORDER BY COALESCE(runs.completed_at, runs.created_at) DESC NULLS LAST
            LIMIT 30
            """
        )
    except Exception:
        return pd.DataFrame()


def _write_hsmm_lifecycle_for_ui(
    storage: DuckDBStorage,
    run_id: str,
    *,
    horizons: tuple[int, ...],
    profile_mode: str,
    profile_cutoff_date: str | None,
    state_date_policy: str,
) -> dict[str, object]:
    output_dir = _hsmm_lifecycle_output_dir(run_id, profile_mode, state_date_policy)
    result = write_lifecycle_ui_outputs(
        storage,
        run_id,
        output_dir,
        horizons=horizons,
        profile_mode=profile_mode,
        profile_cutoff_date=profile_cutoff_date or None,
        state_date_policy=state_date_policy,
    )
    lifecycle_rows = len(result.get("lifecycle_ui_daily", pd.DataFrame()))
    episode_rows = len(result.get("display_label_episodes", pd.DataFrame()))
    metadata = dict(result.get("metadata", {}) or {})
    return {
        "run_id": run_id,
        "rows": lifecycle_rows,
        "display_label_episodes": episode_rows,
        "profile_mode": profile_mode,
        "state_date_policy": state_date_policy,
        "profile_cutoff_date": metadata.get("profile_cutoff_date", profile_cutoff_date or ""),
        "output_dir": str(output_dir),
        "horizons": list(horizons),
        "lifecycle_cleanup_summary": result.get("lifecycle_cleanup_summary", {}),
    }


def _render_hsmm_run_status(storage: DuckDBStorage) -> pd.DataFrame:
    runs = _load_hsmm_run_summary(storage)
    if runs.empty:
        st.info("尚未生成 HSMM 生命周期 run。")
        return runs

    completed = runs[runs["run_status"].astype(str).eq("completed")]
    latest = completed.iloc[0] if not completed.empty else runs.iloc[0]
    m1, m2, m3 = st.columns(3)
    m1.metric("最近 HSMM run", str(latest.get("run_id", ""))[:24])
    m2.metric("状态行数", int(latest.get("actual_state_row_count") or 0))
    m3.metric("生命周期 UI 行数", int(latest.get("lifecycle_ui_rows") or 0))

    preview_cols = [
        "run_id",
        "run_status",
        "start_date",
        "end_date",
        "actual_snapshot_count",
        "actual_state_row_count",
        "lifecycle_ui_rows",
        "lifecycle_cutoff_date",
        "completed_at",
    ]
    st.dataframe(runs[[col for col in preview_cols if col in runs.columns]], hide_index=True, use_container_width=True)
    return runs


def render_model_training(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    st.title("模型训练")
    st.caption("这里集中训练板块 HMM、大盘 HMM 和 HSMM 生命周期。数据更新请回到“数据中心”。")
    run_id = storage.latest_run_for_current_scope(universe_id)
    render_model_workflow(storage, universe_id=universe_id, active_step="train")
    render_data_status_bar(storage, run_id=run_id, universe_id=universe_id)

    tab_sector, tab_market, tab_hsmm = st.tabs(["板块 HMM", "大盘 HMM", "HSMM 生命周期"])

    with tab_sector:
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        start = c1.text_input("训练起始日期", value="20200101", key="sector_train_start")
        end = c2.text_input("训练结束日期", value=today_yyyymmdd(), key="sector_train_end")
        states = c3.selectbox("隐藏状态数量", [2, 3, 4], index=1, key="sector_hmm_states")
        n_iter = c4.number_input("最大迭代次数", min_value=20, max_value=500, value=300, step=20, key="sector_hmm_iter")
        with st.expander("高级训练参数", expanded=False):
            a1, a2 = st.columns(2)
            random_state = a1.number_input("随机种子", min_value=0, max_value=9999, value=42, key="sector_hmm_seed", help=HELP_TEXTS["random_state"])
            n_init = a2.number_input("随机重启次数", min_value=1, max_value=10, value=3, step=1, key="sector_hmm_n_init", help=HELP_TEXTS["hmm_n_init"])
        train_current_universe = st.checkbox("只训练当前板块池", value=universe_id is not None, disabled=universe_id is None)
        if universe_id is None:
            st.caption("当前未选择板块池，将按全市场范围训练。")
        if st.button("开始训练板块 HMM", type="primary"):
            try:
                result = train_hmm(
                    start,
                    end,
                    int(states),
                    storage=storage,
                    universe_id=universe_id if train_current_universe else None,
                    n_iter=int(n_iter),
                    random_state=int(random_state),
                    n_init=int(n_init),
                    progress_callback=_training_progress(),
                )
                render_operation_result(result, "板块 HMM 训练完成")
            except Exception as exc:
                st.error(str(exc))

    with tab_market:
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        start = c1.text_input("训练起始日期", value="20200101", key="market_train_start")
        end = c2.text_input("训练结束日期", value=today_yyyymmdd(), key="market_train_end")
        states = c3.selectbox("隐藏状态数量", [2, 3, 4], index=1, key="market_hmm_states")
        random_state = c4.number_input("随机种子", min_value=0, max_value=9999, value=42, key="market_hmm_seed")
        breadth_ready, breadth_message = latest60_full_market_breadth_available(storage)
        use_breadth = st.checkbox(
            "使用全 A 市场宽度",
            value=breadth_ready,
            disabled=not breadth_ready,
            help="只有最近 60 日 full_market 宽度覆盖达标时，才会用于大盘 HMM。",
        )
        if not breadth_ready:
            st.warning(breadth_message)
        if st.button("开始训练大盘 HMM", type="primary"):
            try:
                result = train_market_hmm(
                    start,
                    end,
                    n_states=int(states),
                    use_breadth=bool(use_breadth),
                    random_state=int(random_state),
                    storage=storage,
                    progress_callback=_training_progress(),
                )
                render_operation_result(result, "大盘 HMM 训练完成")
            except Exception as exc:
                st.error(str(exc))

    with tab_hsmm:
        st.caption("用于生成状态生命周期诊断数据；输出不作为排序、交易建议或价格方向判断。")
        hsmm_runs = _render_hsmm_run_status(storage)

        st.subheader("运行 HSMM walk-forward")
        c1, c2, c3, c4 = st.columns([1.2, 1.2, 1, 1])
        hsmm_start = c1.text_input("HSMM 起始日期", value="20200101", key="hsmm_train_start")
        hsmm_end = c2.text_input("HSMM 结束日期", value=today_yyyymmdd(), key="hsmm_train_end")
        hsmm_states = c3.selectbox("HSMM 状态数量", [3, 4, 5], index=1, key="hsmm_states")
        max_duration = c4.number_input("最大持续期", min_value=10, max_value=250, value=60, step=5, key="hsmm_max_duration")

        c5, c6, c7, c8 = st.columns([1, 1, 1, 1])
        train_window_days = c5.number_input("训练窗口交易日", min_value=60, max_value=1500, value=504, step=21, key="hsmm_train_window")
        n_iter = c6.number_input("最大迭代次数", min_value=2, max_value=200, value=20, step=2, key="hsmm_n_iter")
        train_frequency = c7.selectbox(
            "训练频率",
            ["monthly", "every_n_trade_days"],
            index=0,
            format_func=lambda value: "按月" if value == "monthly" else "每 N 个交易日",
            key="hsmm_train_frequency",
        )
        train_every_n_trade_days = None
        if train_frequency == "every_n_trade_days":
            train_every_n_trade_days = c8.number_input("N", min_value=5, max_value=120, value=20, step=5, key="hsmm_train_every_n")
        else:
            c8.caption("按月训练")

        with st.expander("HSMM 高级参数", expanded=False):
            a1, a2, a3, a4 = st.columns(4)
            random_state = a1.number_input("随机种子", min_value=0, max_value=9999, value=42, key="hsmm_seed")
            n_jobs = a2.text_input("解码并行数", value="1", key="hsmm_n_jobs")
            fit_n_jobs = a3.text_input("训练并行数", value="1", key="hsmm_fit_n_jobs")
            overwrite = a4.checkbox("覆盖同名 run", value=False, key="hsmm_overwrite")
            include_custom_baskets = st.checkbox("包含自定义篮子", value=True, key="hsmm_include_custom_baskets")
            hsmm_run_id = st.text_input("HSMM run_id（可留空自动生成）", value="", key="hsmm_run_id")

        st.subheader("生成生命周期 UI 数据")
        l1, l2, l3, l4 = st.columns([1, 1, 1.2, 1.2])
        profile_mode = l1.selectbox("Profile 模式", ["latest_asof", "retrospective"], index=0, key="hsmm_profile_mode")
        state_date_policy = l2.selectbox("状态日期策略", list(STATE_DATE_POLICIES), index=0, key="hsmm_state_date_policy")
        horizons_text = l3.text_input("生命周期窗口", value=",".join(str(h) for h in DEFAULT_HORIZONS), key="hsmm_horizons")
        profile_cutoff_date = l4.text_input("Profile 截止日期", value="", placeholder="留空使用最新状态日期", key="hsmm_profile_cutoff")

        if st.button("运行 HSMM walk-forward 并生成生命周期 UI 数据", type="primary"):
            try:
                horizons = _parse_hsmm_horizons(horizons_text)
                config = HSMMWalkForwardConfig(
                    start_date=hsmm_start,
                    end_date=hsmm_end,
                    universe_id=universe_id,
                    include_custom_baskets=bool(include_custom_baskets),
                    n_states=int(hsmm_states),
                    max_duration=int(max_duration),
                    train_window_days=int(train_window_days),
                    train_frequency=str(train_frequency),
                    train_every_n_trade_days=None if train_every_n_trade_days is None else int(train_every_n_trade_days),
                    n_iter=int(n_iter),
                    random_state=int(random_state),
                    run_id=hsmm_run_id.strip() or None,
                    overwrite=bool(overwrite),
                    snapshot_decode_mode="prefix",
                    n_jobs=n_jobs.strip() or "1",
                    fit_n_jobs=fit_n_jobs.strip() or None,
                    notes="ui_hsmm_lifecycle_maintenance",
                )
                result = run_hsmm_walk_forward(config, storage=storage, progress_callback=_hsmm_progress())
                lifecycle_result = _write_hsmm_lifecycle_for_ui(
                    storage,
                    str(result["run_id"]),
                    horizons=horizons,
                    profile_mode=str(profile_mode),
                    profile_cutoff_date=profile_cutoff_date.strip() or None,
                    state_date_policy=str(state_date_policy),
                )
                summary = {
                    "run_id": result["run_id"],
                    "rows": lifecycle_result["rows"],
                    "hsmm_state_rows": len(result.get("states", pd.DataFrame())),
                    "hsmm_episode_rows": len(result.get("episodes", pd.DataFrame())),
                    "checkpoint_count": len(result.get("checkpoints", pd.DataFrame())),
                    "lifecycle": lifecycle_result,
                    "cleanup_summary": result.get("cleanup_summary", {}),
                }
                render_operation_result(summary, "HSMM 生命周期生成完成", expanded=True)
            except Exception as exc:
                st.error(str(exc))

        completed_runs = hsmm_runs[hsmm_runs["run_status"].astype(str).eq("completed")] if not hsmm_runs.empty else pd.DataFrame()
        if completed_runs.empty:
            st.info("没有可复用的 completed HSMM run。")
        else:
            run_options = completed_runs["run_id"].astype(str).tolist()
            selected_run = st.selectbox("选择已有 HSMM run", run_options, key="hsmm_existing_run")
            if st.button("仅生成生命周期 UI 数据"):
                try:
                    horizons = _parse_hsmm_horizons(horizons_text)
                    lifecycle_result = _write_hsmm_lifecycle_for_ui(
                        storage,
                        selected_run,
                        horizons=horizons,
                        profile_mode=str(profile_mode),
                        profile_cutoff_date=profile_cutoff_date.strip() or None,
                        state_date_policy=str(state_date_policy),
                    )
                    render_operation_result(lifecycle_result, "生命周期 UI 数据生成完成", expanded=True)
                except Exception as exc:
                    st.error(str(exc))
