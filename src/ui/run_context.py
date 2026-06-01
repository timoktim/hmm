from __future__ import annotations

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage
from src.ui.help_texts import display_value


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
