from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from src.config import settings
from src.data_pipeline.market_updater import MarketUpdateSummary, update_market_breadth
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.validators import validate_ohlcv
from src.data_sources.base import DataResult, MarketDataClient
from src.data_sources.factory import create_data_client
from src.data_sources.tushare_client import SOURCE_PRIORITY_PRIMARY, TushareClient
from src.features.custom_basket_features import build_custom_basket_ohlcv
from src.features.sector_features import add_sector_features, equal_weight_benchmark_ret20_from_close
from src.utils.dates import normalize_yyyymmdd, today_yyyymmdd


SNAPSHOT_COLUMNS = [
    "ts_code",
    "stock_code",
    "trade_date",
    "adj_factor",
    "source",
    "fetched_at",
    "source_priority",
    "validation_status",
]
STOCK_OHLCV_COLUMNS = [
    "stock_code",
    "trade_date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "pct_chg",
    "turnover",
    "source",
    "fetched_at",
    "source_priority",
    "is_provisional",
    "validation_status",
    "vendor_update_time",
]
AFFECTED_COLUMNS = [
    "stock_code",
    "earliest_affected_date",
    "latest_checked_date",
    "old_factor",
    "new_factor",
    "factor_change_count",
]
PLAN_COLUMNS = [
    *AFFECTED_COLUMNS,
    "rebuild_start_date",
    "rebuild_end_date",
]


def _stock_code_from_ts_code(value: object) -> str:
    return str(value or "").split(".", 1)[0].zfill(6)


def _ts_code_from_stock_code(stock_code: str) -> str:
    code = str(stock_code).zfill(6)
    if code.startswith(("4", "8", "920")):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _date(value: object) -> object:
    return pd.to_datetime(value, errors="coerce").date()


def _yyyymmdd(value: object) -> str:
    return pd.to_datetime(value).strftime("%Y%m%d")


def _empty_affected() -> pd.DataFrame:
    return pd.DataFrame(columns=AFFECTED_COLUMNS)


def _empty_plan() -> pd.DataFrame:
    return pd.DataFrame(columns=PLAN_COLUMNS)


def _safe_json_default(value: object) -> str:
    if isinstance(value, (pd.Timestamp,)):
        return value.strftime("%Y-%m-%dT%H:%M:%S")
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _normalize_adj_factor_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    out = df.copy()
    if "stock_code" not in out.columns:
        if "ts_code" not in out.columns:
            raise ValueError("adj_factor 缺少 ts_code/stock_code")
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
    if "ts_code" not in out.columns:
        out["ts_code"] = out["stock_code"].map(_ts_code_from_stock_code)
    if "trade_date" not in out.columns or "adj_factor" not in out.columns:
        raise ValueError("adj_factor 缺少 trade_date/adj_factor")
    out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
    out["adj_factor"] = pd.to_numeric(out["adj_factor"], errors="coerce")
    out = out.dropna(subset=["stock_code", "trade_date", "adj_factor"])
    out = out[out["adj_factor"] > 0].copy()
    now = pd.Timestamp.now()
    defaults = {
        "source": "tushare_adj_factor",
        "fetched_at": now,
        "source_priority": SOURCE_PRIORITY_PRIMARY,
        "validation_status": "validated",
    }
    for column, value in defaults.items():
        if column not in out.columns:
            out[column] = value
    return out[SNAPSHOT_COLUMNS].drop_duplicates(["stock_code", "trade_date"], keep="last").sort_values(["stock_code", "trade_date"])


def fetch_adj_factor_window(
    client: MarketDataClient,
    start_date: str,
    end_date: str,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    start = normalize_yyyymmdd(start_date)
    end = normalize_yyyymmdd(end_date)
    if not callable(getattr(client, "trade_dates", None)) or not callable(getattr(client, "_adj_factor_by_trade_date", None)):
        raise TypeError("client 必须支持 trade_dates 和 _adj_factor_by_trade_date")
    trade_dates = [str(date) for date in client.trade_dates(start, end, force_refresh=force_refresh)]
    frames: list[pd.DataFrame] = []
    for trade_date in trade_dates:
        res = client._adj_factor_by_trade_date(trade_date, force_refresh=force_refresh)  # type: ignore[attr-defined]
        frames.append(res.data)
    if not frames:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)
    return _normalize_adj_factor_frame(pd.concat(frames, ignore_index=True))


def update_adj_factor_snapshot(storage: DuckDBStorage, adj_df: pd.DataFrame) -> int:
    snapshot = _normalize_adj_factor_frame(adj_df)
    if snapshot.empty:
        return 0
    storage.upsert_df("tushare_adj_factor_snapshot", snapshot, ["stock_code", "trade_date"])
    return len(snapshot)


def detect_changed_adj_factors(storage: DuckDBStorage, new_adj_df: pd.DataFrame, tolerance: float = 1e-10) -> pd.DataFrame:
    storage.init_schema()
    new_adj = _normalize_adj_factor_frame(new_adj_df)
    if new_adj.empty:
        return _empty_affected()
    codes = new_adj["stock_code"].drop_duplicates().tolist()
    placeholders = ",".join(["?"] * len(codes))
    min_date = new_adj["trade_date"].min()
    max_date = new_adj["trade_date"].max()
    old = storage.read_df(
        f"""
        SELECT stock_code, trade_date, adj_factor AS old_factor
        FROM tushare_adj_factor_snapshot
        WHERE stock_code IN ({placeholders})
          AND trade_date BETWEEN ? AND ?
        """,
        [*codes, min_date, max_date],
    )
    if old.empty:
        return _empty_affected()
    old["stock_code"] = old["stock_code"].astype(str).str.zfill(6)
    old["trade_date"] = pd.to_datetime(old["trade_date"], errors="coerce").dt.date
    old["old_factor"] = pd.to_numeric(old["old_factor"], errors="coerce")
    merged = new_adj[["stock_code", "trade_date", "adj_factor"]].merge(
        old,
        on=["stock_code", "trade_date"],
        how="inner",
    )
    if merged.empty:
        return _empty_affected()
    merged["new_factor"] = pd.to_numeric(merged["adj_factor"], errors="coerce")
    changed = merged[(merged["old_factor"] - merged["new_factor"]).abs() > float(tolerance)].copy()
    if changed.empty:
        return _empty_affected()
    rows: list[dict[str, object]] = []
    latest_checked = new_adj.groupby("stock_code")["trade_date"].max().to_dict()
    for code, group in changed.sort_values("trade_date").groupby("stock_code", sort=True):
        first = group.iloc[0]
        rows.append(
            {
                "stock_code": str(code).zfill(6),
                "earliest_affected_date": first["trade_date"],
                "latest_checked_date": latest_checked.get(code, group["trade_date"].max()),
                "old_factor": float(first["old_factor"]),
                "new_factor": float(first["new_factor"]),
                "factor_change_count": int(len(group)),
            }
        )
    return pd.DataFrame(rows, columns=AFFECTED_COLUMNS)


def plan_affected_stock_rebuild(
    storage: DuckDBStorage,
    affected_df: pd.DataFrame,
    end_date: str,
    *,
    lookback_buffer_days: int = 30,
) -> pd.DataFrame:
    if affected_df.empty:
        return _empty_plan()
    affected = affected_df.copy()
    affected["stock_code"] = affected["stock_code"].astype(str).str.zfill(6)
    affected["earliest_affected_date"] = pd.to_datetime(affected["earliest_affected_date"], errors="coerce").dt.date
    end = pd.to_datetime(normalize_yyyymmdd(end_date)).date()
    codes = affected["stock_code"].drop_duplicates().tolist()
    placeholders = ",".join(["?"] * len(codes))
    local = storage.read_df(
        f"""
        SELECT stock_code, min(trade_date) AS min_trade_date, max(trade_date) AS max_trade_date
        FROM stock_ohlcv
        WHERE stock_code IN ({placeholders})
        GROUP BY stock_code
        """,
        codes,
    )
    local_map = {}
    if not local.empty:
        local["stock_code"] = local["stock_code"].astype(str).str.zfill(6)
        local_map = {row.stock_code: row for row in local.itertuples(index=False)}
    rows: list[dict[str, object]] = []
    for row in affected.itertuples(index=False):
        code = str(row.stock_code).zfill(6)
        earliest = pd.to_datetime(row.earliest_affected_date).date()
        buffered = (pd.to_datetime(earliest) - pd.Timedelta(days=max(0, int(lookback_buffer_days)))).date()
        local_row = local_map.get(code)
        if local_row is not None and not pd.isna(local_row.min_trade_date):
            local_min = pd.to_datetime(local_row.min_trade_date).date()
            rebuild_start = min(local_min, buffered)
        else:
            rebuild_start = buffered
        rows.append(
            {
                **{column: getattr(row, column) for column in AFFECTED_COLUMNS},
                "stock_code": code,
                "rebuild_start_date": rebuild_start,
                "rebuild_end_date": end,
            }
        )
    return pd.DataFrame(rows, columns=PLAN_COLUMNS).sort_values(["rebuild_start_date", "stock_code"])


def _ensure_stock_ohlcv_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "stock_code" not in out.columns:
        raise ValueError("rebased stock_ohlcv 缺少 stock_code")
    out["stock_code"] = out["stock_code"].astype(str).str.zfill(6)
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
    for column in ["open", "high", "low", "close", "volume", "amount", "pct_chg", "turnover"]:
        if column not in out.columns:
            out[column] = pd.NA
        out[column] = pd.to_numeric(out[column], errors="coerce")
    now = pd.Timestamp.now()
    defaults = {
        "source": "tushare_qfq_rebased",
        "fetched_at": now,
        "source_priority": SOURCE_PRIORITY_PRIMARY,
        "is_provisional": False,
        "validation_status": "validated_rebased",
        "vendor_update_time": pd.NaT,
    }
    for column, value in defaults.items():
        if column not in out.columns:
            out[column] = value
    return out[STOCK_OHLCV_COLUMNS].drop_duplicates(["stock_code", "trade_date"], keep="last").sort_values(["stock_code", "trade_date"])


def _fetch_rebased_stock_frame(
    client: MarketDataClient,
    stock_code: str,
    start_date: object,
    end_date: object,
    *,
    force_refresh: bool = False,
) -> pd.DataFrame:
    method = getattr(client, "stock_qfq_hist_with_reference", None)
    if not callable(method):
        raise TypeError("client 必须支持 stock_qfq_hist_with_reference")
    res: DataResult = method(
        str(stock_code).zfill(6),
        _yyyymmdd(start_date),
        _yyyymmdd(end_date),
        force_refresh=force_refresh,
    )
    return res.data.copy()


def rebuild_qfq_stock_ohlcv(
    storage: DuckDBStorage,
    client: MarketDataClient,
    affected_plan: pd.DataFrame,
    *,
    dry_run: bool = False,
    force_refresh: bool = False,
    max_stocks: int | None = None,
) -> dict[str, object]:
    storage.init_schema()
    if affected_plan.empty:
        return {"status": "noop", "stocks": 0, "rows": 0, "failures": []}
    plan = affected_plan.copy()
    plan["stock_code"] = plan["stock_code"].astype(str).str.zfill(6)
    if max_stocks is not None:
        plan = plan.head(max(0, int(max_stocks))).copy()
    failures: list[str] = []
    rows = 0
    rebuilt = 0
    for item in plan.itertuples(index=False):
        code = str(item.stock_code).zfill(6)
        try:
            data = _fetch_rebased_stock_frame(
                client,
                code,
                item.rebuild_start_date,
                item.rebuild_end_date,
                force_refresh=force_refresh,
            )
            data = _ensure_stock_ohlcv_columns(data)
            start = pd.to_datetime(item.rebuild_start_date).date()
            end = pd.to_datetime(item.rebuild_end_date).date()
            data = data[(data["stock_code"] == code) & (pd.to_datetime(data["trade_date"]).dt.date >= start) & (pd.to_datetime(data["trade_date"]).dt.date <= end)].copy()
            validate_ohlcv(data, f"QFQ rebuild {code}", entity_key="stock_code")
            rows += len(data)
            rebuilt += 1
            if not dry_run:
                storage.upsert_df("stock_ohlcv", data, ["stock_code", "trade_date"])
        except Exception as exc:
            failures.append(f"{code}: {type(exc).__name__}: {exc}")
    if not dry_run and rebuilt:
        codes = plan["stock_code"].drop_duplicates().tolist()
        placeholders = ",".join(["?"] * len(codes))
        duplicates = storage.read_df(
            f"""
            SELECT stock_code, trade_date, count(*) AS n
            FROM stock_ohlcv
            WHERE stock_code IN ({placeholders})
            GROUP BY stock_code, trade_date
            HAVING count(*) > 1
            """,
            codes,
        )
        if not duplicates.empty:
            raise ValueError("QFQ rebuild 写入后存在重复 stock_code+trade_date")
    return {
        "status": "dry_run" if dry_run else ("failed" if failures else "rebuilt"),
        "stocks": int(rebuilt),
        "rows": int(rows),
        "failures": failures,
    }


def _affected_sector_ids(storage: DuckDBStorage, affected_stock_codes: list[str]) -> list[str]:
    if not affected_stock_codes:
        return []
    placeholders = ",".join(["?"] * len(affected_stock_codes))
    sectors = storage.read_df(
        f"""
        SELECT DISTINCT sector_id
        FROM sector_constituents
        WHERE stock_code IN ({placeholders})
        ORDER BY sector_id
        """,
        affected_stock_codes,
    )
    return [] if sectors.empty else sectors["sector_id"].dropna().astype(str).tolist()


def _affected_custom_basket_ids(storage: DuckDBStorage, affected_stock_codes: list[str]) -> list[str]:
    if not affected_stock_codes:
        return []
    placeholders = ",".join(["?"] * len(affected_stock_codes))
    baskets = storage.read_df(
        f"""
        SELECT DISTINCT basket_id
        FROM custom_stock_basket_members
        WHERE stock_code IN ({placeholders})
        ORDER BY basket_id
        """,
        affected_stock_codes,
    )
    return [] if baskets.empty else baskets["basket_id"].dropna().astype(str).tolist()


def rebuild_sector_feature_cache(
    storage: DuckDBStorage,
    sector_ids: list[str],
    start_date: str,
    end_date: str,
) -> int:
    if not sector_ids:
        return 0
    start = pd.to_datetime(normalize_yyyymmdd(start_date))
    end = pd.to_datetime(normalize_yyyymmdd(end_date))
    calc_start = (start - pd.Timedelta(days=45)).date()
    ohlcv = storage.read_df(
        """
        SELECT sector_id, trade_date, open, high, low, close, volume, amount, pct_chg, turnover
        FROM sector_ohlcv
        WHERE trade_date BETWEEN ? AND ?
        ORDER BY sector_id, trade_date
        """,
        [calc_start, end.date()],
    )
    if ohlcv.empty:
        return 0
    tmp = ohlcv.copy()
    tmp["trade_date"] = pd.to_datetime(tmp["trade_date"])
    daily_close = tmp.pivot_table(index="trade_date", columns="sector_id", values="close")
    benchmark_ret20 = equal_weight_benchmark_ret20_from_close(daily_close)
    features = add_sector_features(
        ohlcv,
        benchmark_ret20=benchmark_ret20,
        feature_version=settings.default_feature_version,
        apply_winsorize=False,
        feature_scope_id="all",
        feature_scope_type="all",
    )
    if features.empty:
        return 0
    features = features[
        features["sector_id"].astype(str).isin(set(sector_ids))
        & (pd.to_datetime(features["trade_date"]) >= start)
        & (pd.to_datetime(features["trade_date"]) <= end)
    ].copy()
    if features.empty:
        return 0
    storage.upsert_df("sector_features", features, ["sector_id", "trade_date", "feature_version", "feature_scope_id"])
    return len(features)


def rebuild_dependent_aggregates(
    storage: DuckDBStorage,
    affected_stock_codes: list[str],
    start_date: str,
    end_date: str,
    *,
    dry_run: bool = False,
) -> dict[str, object]:
    storage.init_schema()
    codes = sorted({str(code).zfill(6) for code in affected_stock_codes})
    if dry_run:
        return {"status": "dry_run", "market_breadth_rows": 0, "sector_rows": 0, "custom_basket_rows": 0, "sector_feature_rows": 0}
    breadth_summary: MarketUpdateSummary = update_market_breadth(
        start_date,
        end_date,
        incremental=False,
        mode="full_market",
        storage=storage,
    )
    sector_ids = _affected_sector_ids(storage, codes)
    sector_rows = 0
    if sector_ids:
        local_client = TushareClient(storage=storage)
        for sector_id in sector_ids:
            if ":" not in sector_id:
                continue
            board_type, sector_name = sector_id.split(":", 1)
            result = local_client._local_sector_basket_hist(board_type, sector_name, start_date, end_date)
            validate_ohlcv(result.data, f"QFQ dependent sector {sector_id}", entity_key="sector_id")
            storage.upsert_df("sector_ohlcv", result.data, ["sector_id", "trade_date"])
            sector_rows += len(result.data)
    custom_rows = 0
    for basket_id in _affected_custom_basket_ids(storage, codes):
        existing = storage.read_df("SELECT min(trade_date) AS min_trade_date FROM custom_basket_ohlcv WHERE basket_id = ?", [basket_id])
        basket_start = start_date
        if not existing.empty and not pd.isna(existing.loc[0, "min_trade_date"]):
            basket_start = _yyyymmdd(existing.loc[0, "min_trade_date"])
        custom = build_custom_basket_ohlcv(basket_id, basket_start, end_date, storage=storage)
        custom_rows += len(custom)
    feature_rows = rebuild_sector_feature_cache(storage, sector_ids, start_date, end_date)
    return {
        "status": "rebuilt",
        "market_breadth_rows": int(getattr(breadth_summary, "rows", 0) or 0),
        "sector_rows": int(sector_rows),
        "custom_basket_rows": int(custom_rows),
        "sector_feature_rows": int(feature_rows),
        "market_breadth_failures": list(getattr(breadth_summary, "failures", []) or []),
        "sector_ids": sector_ids,
    }


def _write_rebuild_audit(
    storage: DuckDBStorage,
    *,
    rebuild_run_id: str,
    trigger_reason: str,
    start_date: str,
    end_date: str,
    affected_plan: pd.DataFrame,
    status: str,
    affected_row_count: int,
    summary: dict[str, object],
    created_at: pd.Timestamp,
) -> None:
    completed_at = pd.Timestamp.now()
    run_row = pd.DataFrame(
        [
            {
                "rebuild_run_id": rebuild_run_id,
                "trigger_reason": trigger_reason,
                "start_date": pd.to_datetime(normalize_yyyymmdd(start_date)).date(),
                "end_date": pd.to_datetime(normalize_yyyymmdd(end_date)).date(),
                "affected_stock_count": int(len(affected_plan)),
                "affected_row_count": int(affected_row_count),
                "status": status,
                "created_at": created_at,
                "completed_at": completed_at,
                "summary_json": json.dumps(summary, ensure_ascii=False, default=_safe_json_default),
            }
        ]
    )
    storage.upsert_df("qfq_rebuild_runs", run_row, ["rebuild_run_id"])
    if not affected_plan.empty:
        affected = affected_plan.copy()
        affected["rebuild_run_id"] = rebuild_run_id
        affected["status"] = "rebuilt" if status == "PASS" else status.lower()
        affected["note"] = ""
        storage.upsert_df(
            "qfq_rebuild_affected_stocks",
            affected[
                [
                    "rebuild_run_id",
                    "stock_code",
                    "earliest_affected_date",
                    "latest_checked_date",
                    "old_factor",
                    "new_factor",
                    "factor_change_count",
                    "rebuild_start_date",
                    "rebuild_end_date",
                    "status",
                    "note",
                ]
            ],
            ["rebuild_run_id", "stock_code"],
        )


def _force_affected_from_adj(new_adj_df: pd.DataFrame, end_date: str, max_stocks: int | None = None) -> pd.DataFrame:
    adj = _normalize_adj_factor_frame(new_adj_df)
    if adj.empty:
        return _empty_affected()
    rows: list[dict[str, object]] = []
    for code, group in adj.groupby("stock_code", sort=True):
        first = group.sort_values("trade_date").iloc[0]
        latest = group["trade_date"].max()
        rows.append(
            {
                "stock_code": str(code).zfill(6),
                "earliest_affected_date": first["trade_date"],
                "latest_checked_date": latest,
                "old_factor": float(first["adj_factor"]),
                "new_factor": float(first["adj_factor"]),
                "factor_change_count": 0,
            }
        )
    out = pd.DataFrame(rows, columns=AFFECTED_COLUMNS)
    if max_stocks is not None:
        out = out.head(max(0, int(max_stocks))).copy()
    return out


def _write_summary_json(path: str | Path | None, summary: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_safe_json_default), encoding="utf-8")


def _write_report(path: str | Path | None, summary: dict[str, object]) -> None:
    if not path:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    plan = summary.get("plan_preview", [])
    lines = [
        "# QFQ Rebase and Affected-Stock Rebuild",
        "",
        f"- status: {summary.get('status')}",
        f"- mode: {summary.get('mode')}",
        f"- start_date: {summary.get('start_date')}",
        f"- end_date: {summary.get('end_date')}",
        f"- affected_stock_count: {summary.get('affected_stock_count')}",
        f"- rebuilt_stock_count: {summary.get('rebuilt_stock_count')}",
        f"- rebuilt_row_count: {summary.get('rebuilt_row_count')}",
        f"- dependent_rebuild: {json.dumps(summary.get('dependent_rebuild', {}), ensure_ascii=False, default=_safe_json_default)}",
        "",
        "## Scope Guard",
        "",
        "- Token is read only from the runtime environment and is not written to this report.",
        "- HMM/HSMM/Hazard model runs, walk-forward cache, and final holdout artifacts are not retrained or consumed.",
        "- Custom universe/model feature caches may require a later explicit rebuild after this data repair.",
        "",
        "## Plan Preview",
        "",
    ]
    if plan:
        for item in plan:
            lines.append(
                f"- {item.get('stock_code')}: {item.get('rebuild_start_date')} to {item.get('rebuild_end_date')}, "
                f"earliest_factor_change={item.get('earliest_affected_date')}, changes={item.get('factor_change_count')}"
            )
    else:
        lines.append("- No affected stocks.")
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_qfq_rebuild(
    *,
    start: str,
    end: str,
    mode: str = "detect-and-rebuild",
    storage: DuckDBStorage | None = None,
    client: MarketDataClient | None = None,
    max_stocks: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    summary_json: str | Path | None = None,
    report: str | Path | None = None,
    trigger_reason: str = "manual",
    force_refresh: bool = False,
) -> dict[str, object]:
    if mode not in {"detect-only", "rebuild-only", "detect-and-rebuild"}:
        raise ValueError("mode must be detect-only, rebuild-only, or detect-and-rebuild")
    start_norm = normalize_yyyymmdd(start)
    end_norm = normalize_yyyymmdd(end)
    storage = storage or DuckDBStorage()
    storage.init_schema()
    client = client or create_data_client(storage=storage)
    rebuild_run_id = f"qfq-{uuid.uuid4().hex[:16]}"
    created_at = pd.Timestamp.now()
    new_adj = fetch_adj_factor_window(client, start_norm, end_norm, force_refresh=force_refresh)
    affected = _force_affected_from_adj(new_adj, end_norm, max_stocks=max_stocks) if force else detect_changed_adj_factors(storage, new_adj)
    if max_stocks is not None and not affected.empty:
        affected = affected.head(max(0, int(max_stocks))).copy()
    if mode == "rebuild-only" and not force:
        raise ValueError("rebuild-only 需要显式 --force，避免无差别重建。")
    plan = plan_affected_stock_rebuild(storage, affected, end_norm)
    if dry_run or mode == "detect-only" or plan.empty:
        status = "NOOP" if plan.empty else ("DRY_RUN" if dry_run else "DETECT_ONLY")
        snapshot_rows = 0
        summary = {
            "status": status,
            "mode": mode,
            "dry_run": bool(dry_run),
            "start_date": start_norm,
            "end_date": end_norm,
            "affected_stock_count": int(len(plan)),
            "rebuilt_stock_count": 0,
            "rebuilt_row_count": 0,
            "snapshot_rows": snapshot_rows,
            "dependent_rebuild": {"status": "skipped"},
            "plan_preview": plan.head(50).to_dict(orient="records"),
        }
        if not dry_run and mode == "detect-and-rebuild" and plan.empty:
            snapshot_rows = update_adj_factor_snapshot(storage, new_adj)
            summary["snapshot_rows"] = int(snapshot_rows)
            _write_rebuild_audit(
                storage,
                rebuild_run_id=rebuild_run_id,
                trigger_reason=trigger_reason,
                start_date=start_norm,
                end_date=end_norm,
                affected_plan=plan,
                status="NOOP",
                affected_row_count=0,
                summary=summary,
                created_at=created_at,
            )
        _write_summary_json(summary_json, summary)
        _write_report(report, summary)
        return summary
    try:
        rebuild_summary = rebuild_qfq_stock_ohlcv(
            storage,
            client,
            plan,
            dry_run=False,
            force_refresh=force_refresh,
            max_stocks=max_stocks,
        )
        if rebuild_summary.get("failures"):
            raise RuntimeError("; ".join(str(item) for item in rebuild_summary["failures"]))
        dependent_summary = rebuild_dependent_aggregates(
            storage,
            plan["stock_code"].astype(str).str.zfill(6).tolist(),
            _yyyymmdd(plan["rebuild_start_date"].min()),
            end_norm,
            dry_run=False,
        )
        if dependent_summary.get("market_breadth_failures"):
            raise RuntimeError("; ".join(str(item) for item in dependent_summary["market_breadth_failures"]))
        snapshot_rows = update_adj_factor_snapshot(storage, new_adj)
        summary = {
            "status": "PASS",
            "mode": mode,
            "dry_run": False,
            "start_date": start_norm,
            "end_date": end_norm,
            "affected_stock_count": int(len(plan)),
            "rebuilt_stock_count": int(rebuild_summary.get("stocks", 0) or 0),
            "rebuilt_row_count": int(rebuild_summary.get("rows", 0) or 0),
            "snapshot_rows": int(snapshot_rows),
            "dependent_rebuild": dependent_summary,
            "plan_preview": plan.head(50).to_dict(orient="records"),
        }
        _write_rebuild_audit(
            storage,
            rebuild_run_id=rebuild_run_id,
            trigger_reason=trigger_reason,
            start_date=start_norm,
            end_date=end_norm,
            affected_plan=plan,
            status="PASS",
            affected_row_count=int(rebuild_summary.get("rows", 0) or 0),
            summary=summary,
            created_at=created_at,
        )
        _write_summary_json(summary_json, summary)
        _write_report(report, summary)
        return summary
    except Exception as exc:
        summary = {
            "status": "FAILED",
            "mode": mode,
            "dry_run": False,
            "start_date": start_norm,
            "end_date": end_norm,
            "affected_stock_count": int(len(plan)),
            "rebuilt_stock_count": 0,
            "rebuilt_row_count": 0,
            "snapshot_rows": 0,
            "error_type": type(exc).__name__,
            "plan_preview": plan.head(50).to_dict(orient="records"),
        }
        _write_rebuild_audit(
            storage,
            rebuild_run_id=rebuild_run_id,
            trigger_reason=trigger_reason,
            start_date=start_norm,
            end_date=end_norm,
            affected_plan=plan,
            status="FAILED",
            affected_row_count=0,
            summary=summary,
            created_at=created_at,
        )
        _write_summary_json(summary_json, summary)
        _write_report(report, summary)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Detect Tushare adj_factor changes and rebuild affected QFQ stock_ohlcv rows.")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default=today_yyyymmdd())
    parser.add_argument("--mode", choices=["detect-only", "rebuild-only", "detect-and-rebuild"], default="detect-and-rebuild")
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--report", default=None)
    parser.add_argument("--force-refresh", action="store_true")
    args = parser.parse_args(argv)
    summary = run_qfq_rebuild(
        start=args.start,
        end=args.end,
        mode=args.mode,
        max_stocks=args.max_stocks,
        force=args.force,
        dry_run=args.dry_run,
        summary_json=args.summary_json,
        report=args.report,
        force_refresh=args.force_refresh,
    )
    print(
        "QFQ rebuild "
        f"status={summary.get('status')} "
        f"affected={summary.get('affected_stock_count')} "
        f"rebuilt_stocks={summary.get('rebuilt_stock_count')} "
        f"rows={summary.get('rebuilt_row_count')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
