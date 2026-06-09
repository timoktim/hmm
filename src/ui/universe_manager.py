from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from src.data_pipeline.storage import DuckDBStorage, json_dumps
from src.data_pipeline.universe import parse_stock_lines
from src.data_sources.factory import create_data_client
from src.features.custom_basket_features import POLICY_DYNAMIC_AVAILABLE, POLICY_FIXED_ZERO_RETURN, custom_basket_quality_frame
from src.ui.components.data_status_bar import render_data_status_bar
from src.ui.help_texts import rename_columns_for_display


def _rerun() -> None:
    if hasattr(st, "rerun"):
        st.rerun()


def _universe_options(storage: DuckDBStorage) -> pd.DataFrame:
    universes = storage.list_universes()
    if universes.empty:
        return universes
    universes["label"] = universes.apply(
        lambda r: f"{r['universe_name']}（默认）" if bool(r.get("is_default", False)) else str(r["universe_name"]),
        axis=1,
    )
    return universes


def _add_sector_items(storage: DuckDBStorage, universe_id: str, sector_type: str, selected_names: list[str]) -> None:
    if not selected_names:
        return
    meta = storage.read_df(
        "SELECT sector_id, sector_name FROM sector_meta WHERE sector_type = ? AND sector_name IN ({})".format(
            ",".join(["?"] * len(selected_names))
        ),
        [sector_type, *selected_names],
    )
    for row in meta.itertuples(index=False):
        storage.add_universe_item(universe_id, sector_type, str(row.sector_id), str(row.sector_name))


def _refresh_board_names(storage: DuckDBStorage, sector_type: str) -> int:
    client = create_data_client(storage=storage)
    res = client.board_names(sector_type, force_refresh=True)  # type: ignore[arg-type]
    storage.upsert_df("sector_meta", res.data, ["sector_id"])
    return len(res.data)


def _custom_basket_status(storage: DuckDBStorage, items: pd.DataFrame) -> pd.DataFrame:
    custom_items = items[items["item_type"] == "custom_stock_basket"] if not items.empty else pd.DataFrame()
    rows: list[dict[str, object]] = []
    for item in custom_items.itertuples(index=False):
        basket_id = str(item.item_id)
        members = storage.list_basket_members(basket_id)
        basket = storage.read_df("SELECT basket_name, index_method, membership_policy FROM custom_stock_basket WHERE basket_id = ?", [basket_id])
        quality = custom_basket_quality_frame(basket_id, storage=storage)
        latest = quality.iloc[-1] if not quality.empty else {}
        rows.append(
            {
                "basket_id": basket_id,
                "basket_name": str(basket.loc[0, "basket_name"]) if not basket.empty else str(item.item_name),
                "index_method": str(basket.loc[0, "index_method"]) if not basket.empty else "equal_weight",
                "membership_policy": str(basket.loc[0, "membership_policy"]) if not basket.empty and "membership_policy" in basket else POLICY_FIXED_ZERO_RETURN,
                "index_method_effective": "" if quality.empty else str(latest.get("index_method_effective", "")),
                "成员数量": len(members),
                "指数开始": "" if quality.empty else str(quality["trade_date"].min()),
                "指数结束": "" if quality.empty else str(quality["trade_date"].max()),
                "最近有效成员数": "" if quality.empty else int(latest["member_count"]),
                "最近覆盖率": "" if quality.empty else f"{float(latest['coverage']):.1%}",
                "最近缺失成员数": "" if quality.empty else int(latest.get("missing_member_count", 0) or 0),
                "低覆盖日期数": 0 if quality.empty else int(quality["low_quality"].sum()),
            }
        )
    return pd.DataFrame(rows)


def render_universe_manager(storage: DuckDBStorage) -> None:
    st.title("板块池管理")
    render_data_status_bar(storage)

    with st.expander("新建板块池", expanded=True):
        name = st.text_input("板块池名称", value="")
        description = st.text_area("描述", value="")
        if st.button("保存板块池", disabled=not name.strip()):
            universe_id = storage.create_universe(name.strip(), description.strip())
            st.success(f"已创建：{universe_id}")
            _rerun()

    universes = _universe_options(storage)
    if universes.empty:
        st.info("还没有板块池。可以先创建一个，例如：AI 算力链。")
        return

    selected_label = st.selectbox("选择已有板块池", universes["label"].tolist())
    current = universes[universes["label"] == selected_label].iloc[0]
    universe_id = str(current["universe_id"])
    st.caption(f"当前板块池 ID：{universe_id}")

    c1, c2 = st.columns([1, 1])
    if c1.button("设为默认板块池"):
        storage.set_default_universe(universe_id)
        st.success("已设为默认板块池")
        _rerun()
    if c2.button("删除当前板块池"):
        storage.delete_universe(universe_id)
        st.warning("已删除当前板块池")
        _rerun()

    items = storage.list_universe_items(universe_id)
    st.subheader("当前条目")
    if items.empty:
        st.info("当前板块池还没有条目。")
    else:
        st.dataframe(rename_columns_for_display(items[["item_type", "item_id", "item_name", "weight", "note", "created_at"]]), width="stretch")
        basket_status = _custom_basket_status(storage, items)
        if not basket_status.empty:
            st.caption(
                "自定义股票池状态；fixed_weight_zero_return 对缺失/停牌成员按 0 收益保留原权重，"
                "dynamic_available_members 只在可用成员间临时归一化，输出会显式标记覆盖率和缺失成员数。"
            )
            st.dataframe(rename_columns_for_display(basket_status), width="stretch")
        remove_options = items.apply(lambda r: f"{r['item_type']} | {r['item_name']} | {r['item_id']}", axis=1).tolist()
        remove_label = st.selectbox("移除条目", [""] + remove_options)
        if st.button("移除所选条目", disabled=not remove_label):
            item_id = remove_label.split(" | ")[-1]
            storage.remove_universe_item(universe_id, item_id)
            st.success("已移除")
            _rerun()

    meta = storage.read_df("SELECT sector_id, sector_type, sector_name FROM sector_meta ORDER BY sector_type, sector_name")
    left, right = st.columns(2)
    with left:
        st.subheader("添加行业板块")
        if st.button("刷新行业板块名称列表"):
            try:
                count = _refresh_board_names(storage, "industry")
                st.success(f"行业板块名称已刷新：{count} 个")
                _rerun()
            except Exception as exc:
                st.error(f"刷新行业板块名称失败：{exc}")
        industry_names = meta.loc[meta["sector_type"] == "industry", "sector_name"].dropna().astype(str).tolist()
        selected_industries = st.multiselect("行业板块", industry_names)
        if st.button("添加行业板块", disabled=not selected_industries):
            _add_sector_items(storage, universe_id, "industry", selected_industries)
            st.success(f"已添加 {len(selected_industries)} 个行业板块")
            _rerun()
    with right:
        st.subheader("添加概念板块")
        if st.button("刷新概念板块名称列表"):
            try:
                count = _refresh_board_names(storage, "concept")
                st.success(f"概念板块名称已刷新：{count} 个")
                _rerun()
            except Exception as exc:
                st.error(f"刷新概念板块名称失败：{exc}")
        concept_names = meta.loc[meta["sector_type"] == "concept", "sector_name"].dropna().astype(str).tolist()
        selected_concepts = st.multiselect("概念板块", concept_names)
        if st.button("添加概念板块", disabled=not selected_concepts):
            _add_sector_items(storage, universe_id, "concept", selected_concepts)
            st.success(f"已添加 {len(selected_concepts)} 个概念板块")
            _rerun()

    st.subheader("新建自定义股票池")
    basket_name = st.text_input("股票池名称")
    basket_description = st.text_area("股票池描述")
    index_method = st.selectbox("指数计算方法", ["equal_weight", "custom_weight"], index=0, format_func=lambda x: "等权" if x == "equal_weight" else "自定义权重")
    membership_policy = st.selectbox(
        "成员缺失/停牌处理",
        [POLICY_FIXED_ZERO_RETURN, POLICY_DYNAMIC_AVAILABLE],
        index=0,
        format_func=lambda x: "固定权重，缺失收益按 0" if x == POLICY_FIXED_ZERO_RETURN else "动态可用成员归一化",
    )
    member_text = st.text_area("股票代码，每行一个", placeholder="300308\n300308 中际旭创\n300308.SZ 中际旭创\n300308 2.0 中际旭创")
    st.caption(
        "等权模式会忽略权重；自定义权重模式可在代码后写权重，例如：300308 2.0 中际旭创。"
        "固定权重策略不会把缺失/停牌成员权重临时分摊给其他成员。"
    )
    add_to_current = st.checkbox("保存后加入当前板块池", value=True)
    if st.button("保存自定义股票池", disabled=not basket_name.strip()):
        members = parse_stock_lines(member_text)
        if not members:
            st.error("没有识别到有效股票代码。")
        else:
            basket_id = storage.create_custom_stock_basket(
                basket_name.strip(),
                basket_description.strip(),
                index_method=index_method,
                membership_policy=membership_policy,
            )
            storage.add_basket_members(basket_id, members)
            if add_to_current:
                storage.add_universe_item(universe_id, "custom_stock_basket", basket_id, basket_name.strip())
            st.success(f"已保存自定义股票池：{basket_id}，成员 {len(members)} 只")
            _rerun()

    st.subheader("导入 / 导出 JSON")
    payload = storage.export_universe_json(universe_id)
    st.download_button(
        "导出当前板块池",
        data=json_dumps(payload),
        file_name=f"{current['universe_name']}_universe.json",
        mime="application/json",
    )
    uploaded = st.file_uploader("导入板块池 JSON", type=["json"])
    if uploaded is not None and st.button("导入 JSON"):
        try:
            imported = json.loads(uploaded.getvalue().decode("utf-8"))
            new_id = storage.import_universe_json(imported)
            st.success(f"导入完成：{new_id}")
            _rerun()
        except Exception as exc:
            st.error(f"导入失败：{exc}")
