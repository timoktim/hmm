from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data_pipeline.market_updater import DEFAULT_MARKET_INDEX_CODES
from src.data_pipeline.storage import DuckDBStorage
from src.ui.help_texts import rename_columns_for_display


@dataclass
class CoverageRow:
    dimension: str
    expected_count: int | None
    stored_count: int
    latest_date: object | None = None
    coverage_ratio: float | None = None
    stale_count: int | None = None
    recent_count: int | None = None
    effective_count: int | None = None
    coverage_level: str | None = None
    breadth_mode: str | None = None
    note: str = ""


def _scalar(df: pd.DataFrame, column: str, default: Any = None) -> Any:
    if df.empty or column not in df.columns:
        return default
    value = df.loc[0, column]
    if pd.isna(value):
        return default
    return value


def _ratio(stored: int | float | None, expected: int | float | None) -> float | None:
    if expected is None or pd.isna(expected) or float(expected) <= 0:
        return None
    return float(stored or 0) / float(expected)


def _safe_int(value: Any, default: int = 0) -> int:
    if value is None or pd.isna(value):
        return default
    return int(value)


def _active_sector_filter_sql(sector_type: str) -> tuple[str, list[object]]:
    return (
        """
        sector_type = ?
        AND (
          NOT EXISTS (
            SELECT 1 FROM sector_meta marker
            WHERE marker.sector_type = ?
              AND marker.active_checked_at IS NOT NULL
          )
          OR COALESCE(is_active, TRUE) = TRUE
        )
        """,
        [sector_type, sector_type],
    )


def _universe_board_items(storage: DuckDBStorage, universe_id: str | None, sector_type: str | None = None) -> pd.DataFrame:
    if not universe_id:
        return pd.DataFrame()
    items = storage.list_universe_items(universe_id)
    if items.empty:
        return items
    items = items[items["item_type"].isin(["industry", "concept"])]
    if sector_type:
        items = items[items["item_type"] == sector_type]
    return items


def _sector_coverage(storage: DuckDBStorage, sector_type: str, universe_id: str | None = None) -> CoverageRow:
    dimension = "行业板块行情" if sector_type == "industry" else "概念板块行情"
    if universe_id:
        items = _universe_board_items(storage, universe_id, sector_type)
        expected = len(items)
        if expected == 0:
            return CoverageRow(
                dimension=dimension,
                expected_count=0,
                stored_count=0,
                coverage_ratio=None,
                note="当前板块池中没有该类型板块",
            )
        ids = items["item_id"].astype(str).tolist()
        placeholders = ",".join(["?"] * len(ids))
        stats = storage.read_df(
            f"""
            WITH per_sector AS (
              SELECT sector_id, max(trade_date) AS latest_date
              FROM sector_ohlcv
              WHERE sector_id IN ({placeholders})
              GROUP BY sector_id
            ),
            global_latest AS (
              SELECT max(latest_date) AS max_date FROM per_sector
            )
            SELECT count(*) AS stored_count,
                   max(latest_date) AS latest_date,
                   sum(CASE WHEN latest_date < (SELECT max_date FROM global_latest) THEN 1 ELSE 0 END) AS stale_count
            FROM per_sector
            """,
            ids,
        )
        missing = storage.read_df(
            f"""
            WITH expected AS (
              SELECT item_id AS sector_id, item_name AS sector_name
              FROM user_universe_items
              WHERE universe_id = ? AND item_type = ?
            ),
            stored AS (
              SELECT DISTINCT sector_id FROM sector_ohlcv
            )
            SELECT sector_name
            FROM expected
            LEFT JOIN stored USING (sector_id)
            WHERE stored.sector_id IS NULL
            ORDER BY sector_name
            LIMIT 8
            """,
            [universe_id, sector_type],
        )
        scope_note = "当前板块池口径"
    else:
        active_filter, active_params = _active_sector_filter_sql(sector_type)
        expected = _safe_int(
            _scalar(
                storage.read_df(f"SELECT count(*) AS n FROM sector_meta WHERE {active_filter}", active_params),
                "n",
                0,
            )
        )
        stats = storage.read_df(
            f"""
            WITH typed AS (
              SELECT sector_id FROM sector_meta WHERE {active_filter}
            ),
            per_sector AS (
              SELECT o.sector_id, max(o.trade_date) AS latest_date
              FROM sector_ohlcv o
              JOIN typed t USING (sector_id)
              GROUP BY o.sector_id
            ),
            global_latest AS (
              SELECT max(latest_date) AS max_date FROM per_sector
            )
            SELECT count(*) AS stored_count,
                   max(latest_date) AS latest_date,
                   sum(CASE WHEN latest_date < (SELECT max_date FROM global_latest) THEN 1 ELSE 0 END) AS stale_count
            FROM per_sector
            """,
            active_params,
        )
        missing = storage.read_df(
            f"""
            WITH expected AS (
              SELECT sector_id, sector_name
              FROM sector_meta
              WHERE {active_filter}
            ),
            stored AS (
              SELECT DISTINCT sector_id FROM sector_ohlcv
            )
            SELECT sector_name
            FROM expected
            LEFT JOIN stored USING (sector_id)
            WHERE stored.sector_id IS NULL
            ORDER BY sector_name
            LIMIT 8
            """,
            active_params,
        )
        scope_note = "全市场口径"
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    missing_count = max(int(expected or 0) - stored, 0)
    if missing_count > 0:
        examples = "、".join(missing["sector_name"].astype(str).tolist()) if not missing.empty else ""
        note = f"{scope_note}；缺少行情 {missing_count} 个"
        if examples:
            note += f"：{examples}"
            if missing_count > len(missing):
                note += " 等"
    else:
        note = f"{scope_note}；行情已覆盖"
    return CoverageRow(
        dimension=dimension,
        expected_count=expected,
        stored_count=stored,
        latest_date=_scalar(stats, "latest_date"),
        coverage_ratio=_ratio(stored, expected),
        stale_count=_safe_int(_scalar(stats, "stale_count", 0)),
        note=note,
    )


def _constituent_coverage(storage: DuckDBStorage, universe_id: str | None = None) -> CoverageRow:
    if universe_id:
        items = _universe_board_items(storage, universe_id)
        expected = len(items)
        ids = items["item_id"].astype(str).tolist()
        if not ids:
            return CoverageRow("板块成分股", expected_count=0, stored_count=0, coverage_ratio=None, note="当前板块池中没有行业或概念板块")
        placeholders = ",".join(["?"] * len(ids))
        stats = storage.read_df(
            f"""
            SELECT count(DISTINCT sector_id) AS stored_count,
                   count(*) AS total_constituents,
                   max(fetched_at) AS latest_date
            FROM sector_constituents
            WHERE sector_id IN ({placeholders})
            """,
            ids,
        )
    else:
        industry_filter, industry_params = _active_sector_filter_sql("industry")
        concept_filter, concept_params = _active_sector_filter_sql("concept")
        expected = _safe_int(
            _scalar(
                storage.read_df(
                    f"""
                    SELECT count(*) AS n
                    FROM sector_meta
                    WHERE ({industry_filter}) OR ({concept_filter})
                    """,
                    [*industry_params, *concept_params],
                ),
                "n",
                0,
            )
        )
        stats = storage.read_df(
            f"""
            WITH active_meta AS (
              SELECT sector_id FROM sector_meta WHERE ({industry_filter}) OR ({concept_filter})
            )
            SELECT count(DISTINCT sector_id) AS stored_count,
                   count(*) AS total_constituents,
                   max(fetched_at) AS latest_date
            FROM sector_constituents
            WHERE sector_id IN (SELECT sector_id FROM active_meta)
            """
            ,
            [*industry_params, *concept_params],
        )
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    total = _safe_int(_scalar(stats, "total_constituents", 0))
    return CoverageRow(
        dimension="板块成分股",
        expected_count=expected,
        stored_count=stored,
        latest_date=_scalar(stats, "latest_date"),
        coverage_ratio=_ratio(stored, expected),
        note=f"成分股记录 {total} 条",
    )


def _stock_expected_codes(storage: DuckDBStorage, universe_id: str | None = None) -> tuple[list[str], str]:
    if universe_id:
        items = _universe_board_items(storage, universe_id)
        codes: set[str] = set()
        board_ids = items["item_id"].astype(str).tolist() if not items.empty else []
        if board_ids:
            placeholders = ",".join(["?"] * len(board_ids))
            cons = storage.read_df(
                f"SELECT DISTINCT stock_code FROM sector_constituents WHERE sector_id IN ({placeholders})",
                board_ids,
            )
            codes.update(cons["stock_code"].astype(str).str.zfill(6).tolist())
        custom_items = storage.list_universe_items(universe_id)
        custom_ids = custom_items.loc[custom_items["item_type"] == "custom_stock_basket", "item_id"].astype(str).tolist() if not custom_items.empty else []
        if custom_ids:
            placeholders = ",".join(["?"] * len(custom_ids))
            members = storage.read_df(
                f"SELECT DISTINCT stock_code FROM custom_stock_basket_members WHERE basket_id IN ({placeholders})",
                custom_ids,
            )
            codes.update(members["stock_code"].astype(str).str.zfill(6).tolist())
        return sorted(codes), "当前板块池成分股"
    all_a = storage.read_df(
        """
        SELECT stock_code
        FROM all_a_stock_universe
        WHERE COALESCE(list_status, 'active') = 'active'
        """
    )
    if not all_a.empty:
        return all_a["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist(), "全 A 股票池"
    cons = storage.read_df("SELECT DISTINCT stock_code FROM sector_constituents")
    if cons.empty:
        return [], "板块成分股去重"
    return cons["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist(), "板块成分股去重"


def _stock_coverage(storage: DuckDBStorage, universe_id: str | None = None) -> CoverageRow:
    expected_codes, source = _stock_expected_codes(storage, universe_id)
    expected = len(expected_codes)
    if expected == 0:
        return CoverageRow(
            dimension="个股行情",
            expected_count=0,
            stored_count=0,
            coverage_ratio=None,
            recent_count=0,
            note=f"预期口径：{source}",
        )
    placeholders = ",".join(["?"] * expected)
    stats = storage.read_df(
        f"""
        WITH latest AS (
          SELECT max(trade_date) AS latest_date
          FROM stock_ohlcv
          WHERE stock_code IN ({placeholders})
        )
        SELECT count(DISTINCT stock_code) AS stored_count,
               (SELECT latest_date FROM latest) AS latest_date,
               count(DISTINCT CASE
                 WHEN trade_date >= (SELECT latest_date FROM latest) - INTERVAL 5 DAY
                 THEN stock_code
               END) AS recent_count
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
        """
        ,
        [*expected_codes, *expected_codes],
    )
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    return CoverageRow(
        dimension="个股行情",
        expected_count=expected,
        stored_count=stored,
        latest_date=_scalar(stats, "latest_date"),
        coverage_ratio=_ratio(stored, expected),
        recent_count=_safe_int(_scalar(stats, "recent_count", 0)),
        note=f"预期口径：{source}",
    )


def _all_a_universe_coverage(storage: DuckDBStorage) -> CoverageRow:
    stats = storage.read_df("SELECT count(*) AS stored_count, max(fetched_at) AS fetched_at FROM all_a_stock_universe")
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    return CoverageRow(
        dimension="全 A 股票池",
        expected_count=None,
        stored_count=stored,
        latest_date=_scalar(stats, "fetched_at"),
        coverage_ratio=None,
        note="预期数量随上市状态变化，无法静态给出",
    )


def _market_index_coverage(storage: DuckDBStorage) -> CoverageRow:
    stats = storage.read_df(
        """
        SELECT count(DISTINCT index_code) AS stored_count,
               max(trade_date) AS latest_date
        FROM market_index_ohlcv
        """
    )
    stored_codes = storage.read_df("SELECT DISTINCT index_code FROM market_index_ohlcv")
    stored_set = set(stored_codes["index_code"].astype(str).str.zfill(6).tolist()) if not stored_codes.empty else set()
    missing = [code for code in DEFAULT_MARKET_INDEX_CODES if code not in stored_set]
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    return CoverageRow(
        dimension="大盘指数",
        expected_count=len(DEFAULT_MARKET_INDEX_CODES),
        stored_count=stored,
        latest_date=_scalar(stats, "latest_date"),
        coverage_ratio=_ratio(stored, len(DEFAULT_MARKET_INDEX_CODES)),
        note="缺失指数：" + ("、".join(missing) if missing else "无"),
    )


def _breadth_rows(storage: DuckDBStorage) -> list[CoverageRow]:
    breadth = storage.read_df(
        """
        SELECT *
        FROM (
          SELECT *,
                 row_number() OVER (PARTITION BY breadth_mode ORDER BY trade_date DESC) AS rn
          FROM market_breadth_daily
          WHERE breadth_mode IN ('local_sample', 'full_market')
        )
        WHERE rn = 1
        ORDER BY CASE WHEN breadth_mode = 'local_sample' THEN 0 ELSE 1 END
        """
    )
    rows: list[CoverageRow] = []
    labels = {"local_sample": "市场宽度：本地样本", "full_market": "市场宽度：全 A"}
    for mode in ["local_sample", "full_market"]:
        one = breadth[breadth["breadth_mode"] == mode] if not breadth.empty else pd.DataFrame()
        if one.empty:
            rows.append(
                CoverageRow(
                    dimension=labels[mode],
                    expected_count=None,
                    stored_count=0,
                    coverage_ratio=None,
                    breadth_mode=mode,
                    note="暂无数据",
                )
            )
            continue
        row = one.iloc[0]
        expected = None if pd.isna(row.get("expected_count")) else int(row.get("expected_count"))
        effective = _safe_int(row.get("effective_count"))
        rows.append(
            CoverageRow(
                dimension=labels[mode],
                expected_count=expected,
                stored_count=effective,
                latest_date=row.get("trade_date"),
                coverage_ratio=None if pd.isna(row.get("coverage_ratio")) else float(row.get("coverage_ratio")),
                effective_count=effective,
                coverage_level=str(row.get("coverage_level") or ""),
                breadth_mode=mode,
                note=str(row.get("coverage_warning") or ""),
            )
        )
    return rows


def _benchmark_coverage(storage: DuckDBStorage) -> CoverageRow:
    stats = storage.read_df(
        """
        SELECT count(DISTINCT benchmark_id) AS stored_count,
               max(trade_date) AS latest_date
        FROM market_benchmark_ohlcv
        """
    )
    stored = _safe_int(_scalar(stats, "stored_count", 0))
    return CoverageRow(
        dimension="市场基准",
        expected_count=2,
        stored_count=stored,
        latest_date=_scalar(stats, "latest_date"),
        coverage_ratio=_ratio(stored, 2),
        note="建议至少包含沪深300和中证全指",
    )


def build_data_coverage_snapshot(storage: DuckDBStorage, universe_id: str | None = None) -> pd.DataFrame:
    rows: list[CoverageRow] = [
        _sector_coverage(storage, "industry", universe_id=universe_id),
        _sector_coverage(storage, "concept", universe_id=universe_id),
        _constituent_coverage(storage, universe_id=universe_id),
        _stock_coverage(storage, universe_id=universe_id),
        _all_a_universe_coverage(storage),
        _market_index_coverage(storage),
        *_breadth_rows(storage),
        _benchmark_coverage(storage),
    ]
    data = pd.DataFrame([row.__dict__ for row in rows])
    data["coverage_percent"] = data["coverage_ratio"].map(lambda x: None if pd.isna(x) else round(float(x) * 100, 2))
    return data


def _display_ratio(value: object) -> str:
    if value is None or pd.isna(value):
        return "无"
    return f"{float(value):.1%}"


def _coverage_level_label(level: object) -> str:
    labels = {
        "full_market": "全市场覆盖达标",
        "partial_sample": "样本覆盖不足",
        "insufficient": "样本严重不足",
        "": "暂无数据",
        None: "暂无数据",
    }
    return labels.get(str(level), str(level or "暂无数据"))


def _width_metric_text(row: pd.Series, mode: str) -> tuple[str, str]:
    level = str(row.get("coverage_level") or "")
    ratio = _display_ratio(row.get("coverage_ratio"))
    effective = int(row.get("stored_count") or 0)
    expected = row.get("expected_count")
    expected_text = "未知" if expected is None or pd.isna(expected) else str(int(expected))
    if mode == "full_market":
        if effective <= 0:
            return "暂无全 A 宽度", "请先更新全 A 宽度链路"
        return _coverage_level_label(level), f"覆盖 {ratio}；有效 {effective}/{expected_text} 只"
    if effective <= 0:
        return "暂无本地样本", "请先更新本地样本宽度"
    return "本地样本观察", f"有效 {effective} 只；不代表全 A"


def _render_progress_row(row: pd.Series) -> None:
    ratio = row.get("coverage_ratio")
    label = row.get("dimension", "")
    if ratio is None or pd.isna(ratio):
        st.caption(f"{label}：覆盖率暂无统一分母")
        return
    st.caption(f"{label}：{_display_ratio(ratio)}")
    st.progress(max(0.0, min(float(ratio), 1.0)))


def render_data_coverage_overview(storage: DuckDBStorage, universe_id: str | None = None) -> None:
    snapshot = build_data_coverage_snapshot(storage, universe_id=universe_id)
    if snapshot.empty:
        st.info("暂无可展示的数据覆盖信息。")
        return

    industry = snapshot[snapshot["dimension"] == "行业板块行情"].iloc[0]
    concept = snapshot[snapshot["dimension"] == "概念板块行情"].iloc[0]
    stock = snapshot[snapshot["dimension"] == "个股行情"].iloc[0]
    full_width = snapshot[snapshot["dimension"] == "市场宽度：全 A"].iloc[0]
    local_width = snapshot[snapshot["dimension"] == "市场宽度：本地样本"].iloc[0]

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("行业板块覆盖", _display_ratio(industry["coverage_ratio"]), f"{industry['stored_count']}/{industry['expected_count'] or 0}")
    c2.metric("概念板块覆盖", _display_ratio(concept["coverage_ratio"]), f"{concept['stored_count']}/{concept['expected_count'] or 0}")
    c3.metric("个股行情覆盖", _display_ratio(stock["coverage_ratio"]), f"{stock['stored_count']}/{stock['expected_count'] or 0}")
    full_label, full_delta = _width_metric_text(full_width, "full_market")
    local_label, local_delta = _width_metric_text(local_width, "local_sample")
    c4.metric("全 A 市场宽度", full_label, full_delta)
    c5.metric("本地样本宽度", local_label, local_delta)

    with st.expander("宽度覆盖等级说明", expanded=False):
        st.markdown(
            """
            - **全市场覆盖达标**：全 A 宽度覆盖率达到阈值，可作为大盘 HMM 的市场宽度输入。
            - **样本覆盖不足**：有效股票数或覆盖率未达全市场标准，只能作为样本观察。
            - **本地样本观察**：只基于本地已有个股行情，不代表全 A 市场。
            """
        )

    st.markdown("#### 数据维度覆盖")
    display = snapshot.copy()
    display["覆盖率"] = display["coverage_ratio"].map(_display_ratio)
    display = display[
        [
            "dimension",
            "stored_count",
            "expected_count",
            "recent_count",
            "latest_date",
            "覆盖率",
            "stale_count",
            "coverage_level",
            "note",
        ]
    ]
    st.dataframe(rename_columns_for_display(display), width="stretch")

    st.markdown("#### 覆盖率进度")
    for _, row in snapshot.iterrows():
        _render_progress_row(row)

    dated = snapshot[snapshot["latest_date"].notna()].copy()
    if not dated.empty:
        st.markdown("#### 最新日期分布")
        dated["latest_date"] = dated["latest_date"].astype(str)
        fig = px.bar(
            dated,
            x="dimension",
            y="stored_count",
            color="latest_date",
            labels={"dimension": "数据维度", "stored_count": "在库数量", "latest_date": "最新日期"},
            title="各类数据在库数量与最新日期",
        )
        st.plotly_chart(fig, width="stretch")

    st.markdown("#### 个股覆盖漏斗")
    stock_row = stock
    all_a_count = int(snapshot[snapshot["dimension"] == "全 A 股票池"].iloc[0]["stored_count"] or 0)
    funnel = pd.DataFrame(
        {
            "阶段": ["全 A 股票池", "有个股行情", "近 5 日有行情"],
            "数量": [all_a_count, int(stock_row["stored_count"] or 0), int(stock_row.get("recent_count") or 0)],
        }
    )
    st.bar_chart(funnel.set_index("阶段"))

    st.markdown("#### 市场宽度覆盖")
    width_rows = snapshot[snapshot["breadth_mode"].notna()][["dimension", "stored_count", "expected_count", "coverage_level"]].copy()
    width_rows["覆盖率"] = snapshot.loc[snapshot["breadth_mode"].notna(), "coverage_ratio"].map(_display_ratio).to_list()
    st.dataframe(rename_columns_for_display(width_rows), width="stretch")
