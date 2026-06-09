from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from src.config import PROJECT_ROOT, settings
from src.data_pipeline.market_updater import DEFAULT_MARKET_INDEX_CODES, update_market_breadth, update_market_indices
from src.data_pipeline.qfq_rebuild import rebuild_sector_feature_cache, update_adj_factor_snapshot
from src.data_pipeline.storage import DuckDBStorage
from src.data_pipeline.updater import update_market_benchmark
from src.data_pipeline.validators import validate_ohlcv
from src.data_sources.base import DataResult, MarketDataClient
from src.data_sources.factory import create_data_client
from src.data_sources.tushare_client import SOURCE_PRIORITY_PRIMARY, TushareClient
from src.runtime import db_workspace
from src.utils.dates import normalize_yyyymmdd, today_yyyymmdd


SNAPSHOT_PROFILE = "clean_tushare_snapshot"
DEFAULT_SUMMARY_JSON = PROJECT_ROOT / "reports" / "data" / "clean_tushare_snapshot_summary.json"
DEFAULT_REPORT = PROJECT_ROOT / "reports" / "data" / "clean_tushare_snapshot_report.md"

STAGE_NAMES = [
    "preflight",
    "create_target_db",
    "copy_user_assets",
    "fetch_trade_calendar",
    "fetch_all_a_stock_universe",
    "fetch_stock_ohlcv_qfq",
    "fetch_index_and_benchmark_ohlcv",
    "fetch_sector_constituents",
    "rebuild_sector_ohlcv_local_aggregate",
    "rebuild_market_breadth",
    "rebuild_sector_features",
    "validate_clean_snapshot",
    "write_snapshot_manifest",
    "stale_model_artifacts_plan",
]

STAGE_PROGRESS_WEIGHTS: dict[str, float] = {
    "preflight": 0.02,
    "create_target_db": 0.03,
    "copy_user_assets": 0.03,
    "fetch_trade_calendar": 0.04,
    "fetch_all_a_stock_universe": 0.05,
    "fetch_stock_ohlcv_qfq": 0.58,
    "fetch_index_and_benchmark_ohlcv": 0.04,
    "fetch_sector_constituents": 0.05,
    "rebuild_sector_ohlcv_local_aggregate": 0.06,
    "rebuild_market_breadth": 0.04,
    "rebuild_sector_features": 0.03,
    "validate_clean_snapshot": 0.02,
    "write_snapshot_manifest": 0.005,
    "stale_model_artifacts_plan": 0.005,
}
ProgressCallback = Callable[[dict[str, object]], None]

USER_ASSET_TABLE_KEYS: dict[str, list[str]] = {
    "user_universe": ["universe_id"],
    "user_universe_items": ["universe_id", "item_id"],
    "custom_stock_basket": ["basket_id"],
    "custom_stock_basket_members": ["basket_id", "stock_code"],
}

MARKET_OR_MODEL_TABLES = {
    "stock_ohlcv",
    "sector_ohlcv",
    "market_breadth_daily",
    "market_index_ohlcv",
    "market_benchmark_ohlcv",
    "sector_features",
    "custom_basket_ohlcv",
    "model_runs",
    "market_regime_runs",
    "market_regime_daily",
    "hsmm_model_runs",
    "hsmm_model_checkpoints",
    "hsmm_run_performance",
    "hsmm_state_daily",
    "hsmm_state_episodes",
    "hsmm_display_label_episodes",
    "hsmm_lifecycle_ui_daily",
    "hsmm_lifecycle_profile_metadata",
    "hsmm_lifecycle_duration_profile",
    "hsmm_next_state_tendency_profile",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "qfq_rebuild_runs",
    "qfq_rebuild_affected_stocks",
    "tushare_adj_factor_snapshot",
}

WP2_REQUIRED_TABLES = (
    "tushare_adj_factor_snapshot",
    "qfq_rebuild_runs",
    "qfq_rebuild_affected_stocks",
)

LEGACY_SOURCE_MARKERS = ("akshare", "ths", "eastmoney", "mootdx")
VALID_STOCK_SOURCES = {"tushare_qfq", "tushare_qfq_rebased"}


@dataclass
class StageRecord:
    name: str
    status: str = "pending"
    rows: int = 0
    duration_seconds: float = 0.0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status,
            "rows": int(self.rows),
            "duration_seconds": round(float(self.duration_seconds), 3),
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


@dataclass
class CleanSnapshotConfig:
    target_db: Path
    source_db: Path
    start: str
    end: str
    mode: str = "plan-only"
    allow_existing: bool = False
    copy_user_assets: bool = True
    max_trade_dates: int | None = None
    max_stocks: int | None = None
    force_refresh: bool = False
    summary_json: Path | None = None
    report: Path | None = None
    set_active: bool = False


def _display_path(path: Path | str) -> str:
    candidate = Path(path)
    try:
        absolute = Path(os.path.abspath(candidate))
        db_dir = Path(os.path.abspath(db_workspace.DEFAULT_DB_DIR))
        return str(Path("data") / "db" / absolute.relative_to(db_dir))
    except Exception:
        pass
    try:
        return str(Path(os.path.abspath(candidate)).relative_to(PROJECT_ROOT))
    except Exception:
        return candidate.name


def _safe_json_default(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    try:
        if pd.isna(value):
            return ""
    except Exception:
        pass
    return str(value)


def _progress_bounds(stage_name: str) -> tuple[float, float]:
    start = 0.0
    for name in STAGE_NAMES:
        weight = float(STAGE_PROGRESS_WEIGHTS.get(name, 0.0))
        if name == stage_name:
            return start, weight
        start += weight
    return 0.0, 0.0


def _stage_progress_value(stage_name: str, stage_progress: float = 1.0) -> float:
    start, weight = _progress_bounds(stage_name)
    bounded = min(1.0, max(0.0, float(stage_progress)))
    return min(1.0, max(0.0, start + weight * bounded))


def _emit_progress(
    callback: ProgressCallback | None,
    *,
    job_id: str | None = None,
    status: str = "running",
    stage: str,
    stage_progress: float = 1.0,
    message: str = "",
    rows: int | None = None,
    failures: list[str] | None = None,
    warnings: list[str] | None = None,
    stock_progress: float | None = None,
    stock_current: int | None = None,
    stock_total: int | None = None,
    stock_api: str | None = None,
    stock_trade_date: str | None = None,
) -> None:
    if callback is None:
        return
    stage_index = STAGE_NAMES.index(stage) + 1 if stage in STAGE_NAMES else 0
    payload: dict[str, object] = {
        "snapshot_profile": SNAPSHOT_PROFILE,
        "job_id": job_id or "",
        "status": status,
        "stage": stage,
        "stage_index": stage_index,
        "stage_total": len(STAGE_NAMES),
        "stage_progress": min(1.0, max(0.0, float(stage_progress))),
        "overall_progress": _stage_progress_value(stage, stage_progress),
        "message": message,
        "updated_at": pd.Timestamp.now().isoformat(),
    }
    if rows is not None:
        payload["rows"] = int(rows)
    if failures:
        payload["failures"] = list(failures)
    if warnings:
        payload["warnings"] = list(warnings)
    if stock_progress is not None:
        payload["stock_progress"] = min(1.0, max(0.0, float(stock_progress)))
        payload["stock_level_label"] = "个股日线批量拉取（按交易日/API，不逐股循环）"
    if stock_current is not None:
        payload["stock_current"] = int(stock_current)
    if stock_total is not None:
        payload["stock_total"] = int(stock_total)
    if stock_api:
        payload["stock_api"] = stock_api
    if stock_trade_date:
        payload["stock_trade_date"] = stock_trade_date
    callback(payload)


def _write_progress_json(path: Path | str | None, payload: dict[str, object]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    merged: dict[str, object] = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                merged.update(existing)
        except (OSError, json.JSONDecodeError):
            pass
    merged.update(payload)
    tmp = target.with_name(f"{target.name}.tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2, default=_safe_json_default) + "\n", encoding="utf-8")
    tmp.replace(target)


def _normalize_snapshot_date(value: str | None) -> str:
    if value is None or str(value).strip().lower() == "today":
        return today_yyyymmdd()
    return normalize_yyyymmdd(str(value))


def _date_obj(value: object) -> object:
    return pd.to_datetime(value, errors="coerce").date()


def _stock_code_from_ts_code(value: object) -> str:
    return str(value or "").split(".", 1)[0].zfill(6)


def _ts_code_from_stock_code(stock_code: str) -> str:
    code = str(stock_code).zfill(6)
    if code.startswith(("4", "8", "920")):
        return f"{code}.BJ"
    if code.startswith(("5", "6", "9")):
        return f"{code}.SH"
    return f"{code}.SZ"


def _table_exists(storage: DuckDBStorage, table: str) -> bool:
    df = storage.read_df(
        """
        SELECT count(*) AS n
        FROM information_schema.tables
        WHERE table_schema = 'main'
          AND table_name = ?
        """,
        [table],
    )
    return bool(int(df.loc[0, "n"]) if not df.empty else 0)


def _table_row_count(storage: DuckDBStorage, table: str) -> int:
    if not _table_exists(storage, table):
        return 0
    df = storage.read_df(f'SELECT count(*) AS n FROM "{table}"')
    return int(df.loc[0, "n"]) if not df.empty else 0


def _insert_or_upsert_df(storage: DuckDBStorage, table: str, df: pd.DataFrame, key_cols: list[str]) -> str:
    if df.empty:
        return "empty"
    if _table_row_count(storage, table) == 0:
        storage.insert_df(table, df)
        return "bulk_insert"
    storage.upsert_df(table, df, key_cols)
    return "upsert"


def _metadata_value(storage: DuckDBStorage, key: str) -> str | None:
    if not _table_exists(storage, "database_workspace_metadata"):
        return None
    df = storage.read_df("SELECT value FROM database_workspace_metadata WHERE key = ?", [key])
    return None if df.empty else str(df.loc[0, "value"])


def _write_metadata(storage: DuckDBStorage, rows: dict[str, object]) -> None:
    if not rows:
        return
    payload = pd.DataFrame(
        [{"key": str(key), "value": str(value), "updated_at": pd.Timestamp.now()} for key, value in rows.items()]
    )
    storage.upsert_df("database_workspace_metadata", payload, ["key"])


def _empty_or_clean_existing_target(storage: DuckDBStorage) -> bool:
    profile = _metadata_value(storage, "db_profile")
    if profile == SNAPSHOT_PROFILE:
        return True
    market_rows = sum(_table_row_count(storage, table) for table in MARKET_OR_MODEL_TABLES)
    user_rows = sum(_table_row_count(storage, table) for table in USER_ASSET_TABLE_KEYS)
    return market_rows == 0 and user_rows == 0


def _make_stage(name: str, status: str = "pending", rows: int = 0, failures: list[str] | None = None, warnings: list[str] | None = None) -> StageRecord:
    return StageRecord(name=name, status=status, rows=rows, failures=list(failures or []), warnings=list(warnings or []))


def _stage_dict(stages: list[StageRecord]) -> dict[str, dict[str, object]]:
    return {stage.name: stage.as_dict() for stage in stages}


def _base_summary(config: CleanSnapshotConfig) -> dict[str, object]:
    return {
        "snapshot_profile": SNAPSHOT_PROFILE,
        "status": "PENDING",
        "mode": config.mode,
        "target_db": _display_path(config.target_db),
        "source_db": _display_path(config.source_db),
        "start_date": config.start,
        "end_date": config.end,
        "trade_day_count": 0,
        "stock_count": 0,
        "stock_ohlcv_rows": 0,
        "adj_factor_rows": 0,
        "daily_basic_rows": 0,
        "index_rows": 0,
        "sector_count": 0,
        "sector_ohlcv_rows": 0,
        "market_breadth_rows": 0,
        "sector_feature_rows": 0,
        "source_distribution": {},
        "validation_status": "not_run",
        "failures": [],
        "warnings": [],
        "duration_by_stage": {},
        "stages": [],
        "stale_model_artifacts_plan": stale_model_artifacts_plan(),
        "set_active": bool(config.set_active),
    }


def _write_summary_json(path: Path | str | None, summary: dict[str, object]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_safe_json_default) + "\n", encoding="utf-8")


def _write_report(path: Path | str | None, summary: dict[str, object]) -> None:
    if path is None:
        return
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Clean Tushare DB Snapshot Rebuild",
        "",
        f"- status: {summary.get('status')}",
        f"- mode: {summary.get('mode')}",
        f"- target_db: {summary.get('target_db')}",
        f"- source_db: {summary.get('source_db')}",
        f"- start_date: {summary.get('start_date')}",
        f"- end_date: {summary.get('end_date')}",
        f"- trade_day_count: {summary.get('trade_day_count')}",
        f"- stock_count: {summary.get('stock_count')}",
        f"- stock_ohlcv_rows: {summary.get('stock_ohlcv_rows')}",
        f"- adj_factor_rows: {summary.get('adj_factor_rows')}",
        f"- daily_basic_rows: {summary.get('daily_basic_rows')}",
        f"- index_rows: {summary.get('index_rows')}",
        f"- sector_count: {summary.get('sector_count')}",
        f"- sector_ohlcv_rows: {summary.get('sector_ohlcv_rows')}",
        f"- market_breadth_rows: {summary.get('market_breadth_rows')}",
        f"- sector_feature_rows: {summary.get('sector_feature_rows')}",
        f"- validation_status: {summary.get('validation_status')}",
        "",
        "## Pipeline Stages",
        "",
    ]
    for stage in summary.get("stages", []) or []:
        lines.append(
            f"- {stage.get('name')}: {stage.get('status')}, rows={stage.get('rows')}, "
            f"duration_seconds={stage.get('duration_seconds')}"
        )
        for warning in stage.get("warnings", []) or []:
            lines.append(f"  - warning: {warning}")
        for failure in stage.get("failures", []) or []:
            lines.append(f"  - failure: {failure}")
    lines.extend(
        [
            "",
            "## Source Distribution",
            "",
            json.dumps(summary.get("source_distribution", {}), ensure_ascii=False, default=_safe_json_default),
            "",
            "## Stale Model Artifacts Plan",
            "",
            json.dumps(summary.get("stale_model_artifacts_plan", {}), ensure_ascii=False, indent=2, default=_safe_json_default),
            "",
            "## Scope Guard",
            "",
            "- Tushare token is read only from runtime configuration and is never written to this report.",
            "- The pipeline does not copy old market data, model artifacts, walk-forward cache, or QFQ audit runs from the source DB.",
            "- HMM, HSMM, Hazard training, and final holdout consumption are outside this work package.",
        ]
    )
    if summary.get("failures"):
        lines.extend(["", "## Failures", ""])
        lines.extend(f"- {failure}" for failure in summary.get("failures", []) or [])
    if summary.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {warning}" for warning in summary.get("warnings", []) or [])
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _record_stage(
    stages: list[StageRecord],
    name: str,
    status: str,
    *,
    rows: int = 0,
    start_time: float | None = None,
    failures: list[str] | None = None,
    warnings: list[str] | None = None,
) -> StageRecord:
    duration = 0.0 if start_time is None else time.monotonic() - start_time
    record = StageRecord(name=name, status=status, rows=rows, duration_seconds=duration, failures=list(failures or []), warnings=list(warnings or []))
    stages.append(record)
    return record


def _finalize_summary(summary: dict[str, object], stages: list[StageRecord]) -> None:
    summary["stages"] = [stage.as_dict() for stage in stages]
    summary["duration_by_stage"] = {stage.name: round(float(stage.duration_seconds), 3) for stage in stages}
    warnings: list[str] = []
    failures: list[str] = []
    for stage in stages:
        warnings.extend(stage.warnings)
        failures.extend(stage.failures)
    summary["warnings"] = warnings
    summary["failures"] = failures


def stale_model_artifacts_plan() -> dict[str, object]:
    return {
        "old_model_artifacts_status": "not_copied",
        "reason": "clean_tushare_snapshot_rebuild",
        "recommended_next_steps": [
            "rebuild feature cache",
            "train HMM on clean DB",
            "regenerate HSMM lifecycle if needed",
            "regenerate hazard target dataset",
        ],
    }


def preflight_clean_snapshot(config: CleanSnapshotConfig) -> dict[str, object]:
    errors: list[str] = []
    warnings: list[str] = []
    if config.mode not in {"plan-only", "build", "validate-only"}:
        errors.append("mode must be plan-only, build, or validate-only")
    if config.start > config.end:
        errors.append("start must be <= end")
    if not (os.getenv("ASHARE_HMM_TUSHARE_TOKEN") or settings.tushare_token or "").strip():
        errors.append("missing Tushare token in ASHARE_HMM_TUSHARE_TOKEN")
    if str(settings.market_data_source or settings.default_source or "").strip().lower() not in {"tushare", "ts"}:
        warnings.append(f"settings.market_data_source is {settings.market_data_source!r}; clean snapshot expects tushare")

    target = db_workspace.project_safe_db_path(config.target_db)
    source = db_workspace.project_safe_db_path(config.source_db)
    active = db_workspace.resolve_active_db_path(session_state={})
    if source == target:
        errors.append("target_db must not equal source_db")
    if config.mode != "validate-only" and target == active:
        errors.append("target_db must not equal current active DB")
    if not source.exists():
        errors.append(f"source_db does not exist: {_display_path(source)}")
    elif source.is_dir():
        errors.append("source_db points to a directory")
    else:
        source_storage = DuckDBStorage(source)
        missing_wp2 = [table for table in WP2_REQUIRED_TABLES if not _table_exists(source_storage, table)]
        if missing_wp2:
            errors.append("source_db missing WP2 required tables: " + ",".join(missing_wp2))

    if config.mode == "validate-only":
        if not target.exists():
            errors.append(f"target_db does not exist: {_display_path(target)}")
    elif target.exists():
        if not config.allow_existing:
            errors.append("target_db already exists; pass --allow-existing only for an empty or clean snapshot DB")
        else:
            try:
                if not _empty_or_clean_existing_target(DuckDBStorage(target)):
                    errors.append("target_db exists but is neither empty nor a clean snapshot profile")
            except Exception as exc:
                errors.append(f"target_db existing profile check failed: {type(exc).__name__}")

    if errors:
        raise ValueError("; ".join(errors))
    return {
        "target_db": _display_path(target),
        "source_db": _display_path(source),
        "warnings": warnings,
        "wp2_required_tables": list(WP2_REQUIRED_TABLES),
        "final_holdout_guard": "not_modified",
    }


def _read_table(storage: DuckDBStorage, table: str) -> pd.DataFrame:
    if not _table_exists(storage, table):
        return pd.DataFrame()
    return storage.read_df(f'SELECT * FROM "{table}"')


def copy_user_assets(source_storage: DuckDBStorage, target_storage: DuckDBStorage) -> dict[str, int]:
    copied: dict[str, int] = {}
    for table, key_cols in USER_ASSET_TABLE_KEYS.items():
        if not _table_exists(source_storage, table):
            copied[table] = 0
            continue
        frame = _read_table(source_storage, table)
        if frame.empty:
            copied[table] = 0
            continue
        target_storage.upsert_df(table, frame, key_cols)
        copied[table] = int(len(frame))
    return copied


def _normalize_adj_frame(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["ts_code", "stock_code", "trade_date", "adj_factor"])
    out = df.copy()
    if "stock_code" not in out.columns:
        if "ts_code" not in out.columns:
            raise ValueError("adj_factor missing ts_code/stock_code")
        out["stock_code"] = out["ts_code"].map(_stock_code_from_ts_code)
    if "ts_code" not in out.columns:
        out["ts_code"] = out["stock_code"].map(_ts_code_from_stock_code)
    if "trade_date" not in out.columns or "adj_factor" not in out.columns:
        raise ValueError("adj_factor missing trade_date/adj_factor")
    out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce").dt.date
    out["adj_factor"] = pd.to_numeric(out["adj_factor"], errors="coerce")
    out = out.dropna(subset=["stock_code", "trade_date", "adj_factor"])
    out = out[out["adj_factor"] > 0].copy()
    return out.drop_duplicates(["stock_code", "trade_date"], keep="last").sort_values(["stock_code", "trade_date"])


def build_reference_factors(adj_df: pd.DataFrame, end_date: str, stock_codes: list[str] | None = None) -> dict[str, float]:
    adj = _normalize_adj_frame(adj_df)
    end = pd.to_datetime(normalize_yyyymmdd(end_date)).date()
    codes = sorted({str(code).zfill(6) for code in stock_codes}) if stock_codes is not None else sorted(adj["stock_code"].astype(str).str.zfill(6).unique().tolist())
    code_set = set(codes)
    eligible = adj[adj["stock_code"].astype(str).str.zfill(6).isin(code_set) & (adj["trade_date"] <= end)].copy()
    if eligible.empty:
        references: dict[str, float] = {}
    else:
        latest = eligible.sort_values(["stock_code", "trade_date"]).drop_duplicates("stock_code", keep="last")
        references = dict(zip(latest["stock_code"].astype(str).str.zfill(6), latest["adj_factor"].astype(float), strict=False))
    missing = [code for code in codes if code not in references]
    if missing:
        raise ValueError("missing reference_factor for stock_code: " + ",".join(missing[:20]))
    return references


def normalize_all_qfq_with_reference(
    daily_df: pd.DataFrame,
    adj_df: pd.DataFrame,
    reference_factors: dict[str, float],
    daily_basic_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    return TushareClient.normalize_qfq_stock_daily_with_reference(
        daily_df,
        adj_df,
        reference_factors,
        daily_basic_df,
        validation_status="validated_rebased",
        source="tushare_qfq_rebased",
    )


def _client_result_data(result: DataResult | pd.DataFrame) -> pd.DataFrame:
    if isinstance(result, pd.DataFrame):
        return result
    return result.data


def fetch_clean_stock_ohlcv_qfq(
    client: MarketDataClient,
    storage: DuckDBStorage,
    trade_dates: list[str],
    selected_stock_codes: list[str],
    end_date: str,
    *,
    force_refresh: bool = False,
    progress_callback: ProgressCallback | None = None,
    job_id: str | None = None,
) -> dict[str, object]:
    daily_frames: list[pd.DataFrame] = []
    adj_frames: list[pd.DataFrame] = []
    basic_frames: list[pd.DataFrame] = []
    warnings: list[str] = []
    code_set = {str(code).zfill(6) for code in selected_stock_codes}
    daily_fn = getattr(client, "_daily_raw_by_trade_date", None)
    adj_fn = getattr(client, "_adj_factor_by_trade_date", None)
    if not callable(daily_fn) or not callable(adj_fn):
        raise TypeError("client must support _daily_raw_by_trade_date and _adj_factor_by_trade_date")
    basic_fn = getattr(client, "_daily_basic_by_trade_date", None)
    include_basic = callable(basic_fn)
    stock_total = max(1, len(trade_dates) * (2 + (1 if include_basic else 0)))
    stock_current = 0
    fetch_stage_share = 0.88

    def emit_stock(api_name: str, trade_date_value: str, message: str) -> None:
        fetch_progress = stock_current / stock_total
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status="running",
            stage="fetch_stock_ohlcv_qfq",
            stage_progress=fetch_stage_share * fetch_progress,
            message=message,
            stock_progress=fetch_progress,
            stock_current=stock_current,
            stock_total=stock_total,
            stock_api=api_name,
            stock_trade_date=trade_date_value,
        )

    def emit_post_fetch(api_name: str, stage_progress: float, message: str, rows: int | None = None) -> None:
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status="running",
            stage="fetch_stock_ohlcv_qfq",
            stage_progress=stage_progress,
            message=message,
            rows=rows,
            stock_progress=1.0,
            stock_current=stock_total,
            stock_total=stock_total,
            stock_api=api_name,
            stock_trade_date=str(trade_dates[-1] if trade_dates else ""),
        )

    for trade_date in trade_dates:
        emit_stock("daily", trade_date, f"Tushare daily(trade_date={trade_date})")
        daily_frames.append(_client_result_data(daily_fn(trade_date, force_refresh=force_refresh)))
        stock_current += 1
        emit_stock("daily", trade_date, f"Tushare daily done: {trade_date}")

        emit_stock("adj_factor", trade_date, f"Tushare adj_factor(trade_date={trade_date})")
        adj_frames.append(_client_result_data(adj_fn(trade_date, force_refresh=force_refresh)))
        stock_current += 1
        emit_stock("adj_factor", trade_date, f"Tushare adj_factor done: {trade_date}")

        if include_basic:
            emit_stock("daily_basic", trade_date, f"Tushare daily_basic(trade_date={trade_date})")
            try:
                basic_frames.append(_client_result_data(basic_fn(trade_date, force_refresh=force_refresh)))
            except Exception as exc:
                warnings.append(f"{trade_date}: daily_basic unavailable ({type(exc).__name__})")
            stock_current += 1
            emit_stock("daily_basic", trade_date, f"Tushare daily_basic done: {trade_date}")

    emit_post_fetch("concat_daily", 0.89, "合并 Tushare daily 批量结果")
    daily = pd.concat(daily_frames, ignore_index=True) if daily_frames else pd.DataFrame()
    emit_post_fetch("concat_adj_factor", 0.90, "合并 Tushare adj_factor 批量结果")
    adj = pd.concat(adj_frames, ignore_index=True) if adj_frames else pd.DataFrame()
    emit_post_fetch("concat_daily_basic", 0.91, "合并 Tushare daily_basic 批量结果")
    basic = pd.concat(basic_frames, ignore_index=True) if basic_frames else pd.DataFrame()
    if daily.empty:
        raise ValueError("Tushare daily returned no rows for clean snapshot")
    emit_post_fetch("filter_universe", 0.92, "按目标 universe 过滤 daily/adj_factor/daily_basic")
    if "ts_code" in daily.columns:
        daily = daily[daily["ts_code"].map(_stock_code_from_ts_code).isin(code_set)].copy()
    if "ts_code" in adj.columns:
        adj = adj[adj["ts_code"].map(_stock_code_from_ts_code).isin(code_set)].copy()
    if not basic.empty and "ts_code" in basic.columns:
        basic = basic[basic["ts_code"].map(_stock_code_from_ts_code).isin(code_set)].copy()
    emit_post_fetch("reference_factors", 0.94, "计算每只股票的 QFQ reference factor", rows=len(adj))
    reference_factors = build_reference_factors(adj, end_date, selected_stock_codes)
    emit_post_fetch("normalize_qfq", 0.96, "执行 QFQ 归一化与 daily_basic 合并", rows=len(daily))
    stock_ohlcv = normalize_all_qfq_with_reference(daily, adj, reference_factors, basic)
    stock_ohlcv = stock_ohlcv[stock_ohlcv["stock_code"].astype(str).str.zfill(6).isin(code_set)].copy()
    emit_post_fetch("validate_stock_ohlcv", 0.98, "校验 clean stock_ohlcv", rows=len(stock_ohlcv))
    validate_ohlcv(stock_ohlcv, "clean Tushare stock_ohlcv", entity_key="stock_code")
    emit_post_fetch("upsert_stock_ohlcv", 0.99, "写入 clean stock_ohlcv", rows=len(stock_ohlcv))
    stock_write_mode = _insert_or_upsert_df(storage, "stock_ohlcv", stock_ohlcv, ["stock_code", "trade_date"])
    emit_post_fetch("stock_ohlcv_written", 0.992, f"clean stock_ohlcv 写入完成 ({stock_write_mode})", rows=len(stock_ohlcv))
    emit_post_fetch("update_adj_snapshot", 0.995, "写入 adj_factor snapshot", rows=len(adj))
    snapshot_rows = update_adj_factor_snapshot(storage, adj)
    _emit_progress(
        progress_callback,
        job_id=job_id,
        status="running",
        stage="fetch_stock_ohlcv_qfq",
        stage_progress=1.0,
        message="个股日线批量拉取与 QFQ 写入完成",
        rows=len(stock_ohlcv),
        warnings=warnings,
        stock_progress=1.0,
        stock_current=stock_total,
        stock_total=stock_total,
        stock_api="write_stock_ohlcv",
        stock_trade_date=str(trade_dates[-1] if trade_dates else ""),
    )
    return {
        "stock_ohlcv_rows": int(len(stock_ohlcv)),
        "adj_factor_rows": int(snapshot_rows),
        "daily_basic_rows": int(len(basic)),
        "reference_factor_count": int(len(reference_factors)),
        "warnings": warnings,
    }


def _selected_universe_frame(universe: pd.DataFrame, max_stocks: int | None) -> pd.DataFrame:
    out = universe.copy()
    if "stock_code" not in out.columns:
        raise ValueError("universe missing stock_code")
    out["stock_code"] = out["stock_code"].astype(str).str.extract(r"(\d{6})", expand=False).fillna(out["stock_code"].astype(str)).str.zfill(6)
    out = out.drop_duplicates("stock_code").sort_values("stock_code")
    if max_stocks is not None:
        out = out.head(max(0, int(max_stocks))).copy()
    return out


def fetch_sector_constituents(client: MarketDataClient, storage: DuckDBStorage, *, force_refresh: bool = False) -> dict[str, object]:
    names_fn = getattr(client, "board_names", None)
    constituents_fn = getattr(client, "board_constituents", None)
    if not callable(names_fn) or not callable(constituents_fn):
        return {"sector_count": 0, "rows": 0, "warnings": ["client does not support Tushare sector classify/member APIs"]}
    meta_res = names_fn("industry", force_refresh=force_refresh)
    meta = _client_result_data(meta_res).copy()
    if meta.empty:
        return {"sector_count": 0, "rows": 0, "warnings": ["Tushare sector classify returned no rows"]}
    now = pd.Timestamp.now()
    if "is_active" not in meta.columns:
        meta["is_active"] = True
    if "active_checked_at" not in meta.columns:
        meta["active_checked_at"] = now
    storage.upsert_df("sector_meta", meta, ["sector_id"])
    rows = 0
    failures: list[str] = []
    for row in meta.itertuples(index=False):
        sector_name = str(getattr(row, "sector_name"))
        try:
            cons = _client_result_data(constituents_fn("industry", sector_name, force_refresh=force_refresh)).copy()
            if not cons.empty:
                storage.upsert_df("sector_constituents", cons, ["sector_id", "stock_code"])
                rows += len(cons)
        except Exception as exc:
            failures.append(f"{sector_name}: {type(exc).__name__}: {exc}")
    return {"sector_count": int(meta["sector_id"].nunique()), "rows": int(rows), "failures": failures}


def rebuild_sector_ohlcv_local_aggregate(storage: DuckDBStorage, start: str, end: str) -> dict[str, object]:
    meta = storage.read_df(
        """
        SELECT sector_id, sector_type, sector_name
        FROM sector_meta
        WHERE sector_type = 'industry'
          AND COALESCE(is_active, TRUE)
        ORDER BY sector_id
        """
    )
    if meta.empty:
        return {"rows": 0, "sector_count": 0, "warnings": ["no industry sectors available"]}
    local_client = TushareClient(storage=storage)
    rows = 0
    rebuilt = 0
    failures: list[str] = []
    for row in meta.itertuples(index=False):
        sector_name = str(row.sector_name)
        try:
            result = local_client._local_sector_basket_hist("industry", sector_name, start, end)
            validate_ohlcv(result.data, f"clean snapshot sector {sector_name}", entity_key="sector_id")
            storage.upsert_df("sector_ohlcv", result.data, ["sector_id", "trade_date"])
            rows += len(result.data)
            rebuilt += 1
        except Exception as exc:
            failures.append(f"{sector_name}: {type(exc).__name__}: {exc}")
    status = "pass" if not failures else ("partial" if rows else "failed")
    return {"rows": int(rows), "sector_count": int(rebuilt), "status": status, "failures": failures}


def rebuild_market_indices_and_benchmarks(client: MarketDataClient, storage: DuckDBStorage, start: str, end: str) -> dict[str, object]:
    index_summary = update_market_indices(start, end, DEFAULT_MARKET_INDEX_CODES, incremental=False, client=client, storage=storage)
    benchmark_rows = 0
    failures = list(index_summary.failures)
    for benchmark_id in ["hs300", "csi_all"]:
        summary = update_market_benchmark(benchmark_id, start, end, incremental=False, client=client, storage=storage)
        benchmark_rows += int(summary.rows)
        if summary.failure:
            failures.append(f"{benchmark_id}: {summary.failure}")
    return {"rows": int(index_summary.rows + benchmark_rows), "failures": failures}


def validate_clean_snapshot(storage: DuckDBStorage, trade_dates: list[str], selected_stock_codes: list[str]) -> dict[str, object]:
    failures: list[str] = []
    warnings: list[str] = []
    duplicates = storage.read_df(
        """
        SELECT count(*) AS n
        FROM (
          SELECT stock_code, trade_date, count(*) AS row_count
          FROM stock_ohlcv
          GROUP BY stock_code, trade_date
          HAVING count(*) > 1
        )
        """
    )
    duplicate_count = int(duplicates.loc[0, "n"]) if not duplicates.empty else 0
    if duplicate_count:
        failures.append("stock_ohlcv has duplicate stock_code + trade_date rows")
    stock = storage.read_df(
        """
        SELECT *
        FROM stock_ohlcv
        ORDER BY stock_code, trade_date
        """
    )
    if stock.empty:
        failures.append("stock_ohlcv is empty")
    else:
        try:
            validate_ohlcv(stock, "clean snapshot stock_ohlcv", entity_key="stock_code")
        except Exception as exc:
            failures.append(str(exc))
        null_validation = int(stock["validation_status"].isna().sum()) if "validation_status" in stock.columns else len(stock)
        if null_validation:
            failures.append("stock_ohlcv validation_status contains nulls")
        sources = set(stock.get("source", pd.Series(dtype=str)).dropna().astype(str).str.lower().tolist())
        legacy_sources = sorted(source for source in sources if any(marker in source for marker in LEGACY_SOURCE_MARKERS))
        invalid_sources = sorted(source for source in sources if source not in VALID_STOCK_SOURCES)
        if legacy_sources:
            failures.append("stock_ohlcv contains legacy source rows: " + ",".join(legacy_sources))
        if invalid_sources:
            failures.append("stock_ohlcv contains non-clean Tushare source rows: " + ",".join(invalid_sources))
    if trade_dates:
        latest_expected = pd.to_datetime(trade_dates[-1]).date()
        latest_df = storage.read_df("SELECT max(trade_date) AS latest_trade_date FROM stock_ohlcv")
        latest_actual = None if latest_df.empty or pd.isna(latest_df.loc[0, "latest_trade_date"]) else pd.to_datetime(latest_df.loc[0, "latest_trade_date"]).date()
        if latest_actual != latest_expected:
            failures.append(f"latest stock trade_date {latest_actual} does not match trade calendar {latest_expected}")
    if selected_stock_codes and trade_dates:
        counts = storage.read_df(
            """
            SELECT trade_date, count(DISTINCT stock_code) AS n
            FROM stock_ohlcv
            GROUP BY trade_date
            ORDER BY trade_date
            """
        )
        expected = len({str(code).zfill(6) for code in selected_stock_codes})
        low = counts[pd.to_numeric(counts["n"], errors="coerce") < max(1, int(expected * 0.8))]
        if not low.empty:
            failures.append("universe coverage below 80% on " + ",".join(pd.to_datetime(low["trade_date"]).dt.strftime("%Y%m%d").tolist()[:10]))
    breadth_rows = _table_row_count(storage, "market_breadth_daily")
    if breadth_rows == 0:
        failures.append("market_breadth_daily was not rebuilt")
    sector_constituent_rows = _table_row_count(storage, "sector_constituents")
    sector_rows = _table_row_count(storage, "sector_ohlcv")
    if sector_constituent_rows > 0 and sector_rows == 0:
        failures.append("sector_ohlcv was not rebuilt from target stock_ohlcv")
    feature_rows = _table_row_count(storage, "sector_features")
    if sector_rows > 0 and feature_rows == 0:
        failures.append("sector_features was not rebuilt after sector_ohlcv")
    source_distribution = {}
    if _table_exists(storage, "stock_ohlcv"):
        source_df = storage.read_df("SELECT source, count(*) AS rows FROM stock_ohlcv GROUP BY source ORDER BY source")
        source_distribution = dict(zip(source_df["source"].fillna("null").astype(str), source_df["rows"].astype(int), strict=False)) if not source_df.empty else {}
    status = "pass" if not failures else "failed"
    return {
        "validation_status": status,
        "duplicate_stock_trade_date_count": duplicate_count,
        "source_distribution": source_distribution,
        "failures": failures,
        "warnings": warnings,
    }


def write_snapshot_manifest(storage: DuckDBStorage, summary: dict[str, object]) -> None:
    keys = {
        "db_profile": SNAPSHOT_PROFILE,
        "created_by": "clean_tushare_snapshot",
        "snapshot_start_date": summary.get("start_date"),
        "snapshot_end_date": summary.get("end_date"),
        "market_data_source": "tushare",
        "qfq_policy": "explicit_reference_factor",
        "build_status": str(summary.get("validation_status") or summary.get("status")).lower(),
        "source_db_display_path": summary.get("source_db"),
        "completed_at": pd.Timestamp.now().isoformat(),
        "trade_day_count": summary.get("trade_day_count"),
        "stock_count": summary.get("stock_count"),
    }
    _write_metadata(storage, keys)


def run_clean_tushare_snapshot(
    *,
    target_db: str | Path,
    source_db: str | Path | None = None,
    start: str,
    end: str = "today",
    mode: str = "plan-only",
    allow_existing: bool = False,
    copy_user_assets_enabled: bool = True,
    max_trade_dates: int | None = None,
    max_stocks: int | None = None,
    force_refresh: bool = False,
    summary_json: str | Path | None = None,
    report: str | Path | None = None,
    set_active: bool = False,
    client: MarketDataClient | None = None,
    progress_callback: ProgressCallback | None = None,
    job_id: str | None = None,
) -> dict[str, object]:
    effective_mode = "plan-only" if mode == "dry-run" else mode
    target_path = db_workspace.project_safe_db_path(target_db)
    source_path = db_workspace.project_safe_db_path(source_db or db_workspace.resolve_active_db_path())
    config = CleanSnapshotConfig(
        target_db=target_path,
        source_db=source_path,
        start=_normalize_snapshot_date(start),
        end=_normalize_snapshot_date(end),
        mode=effective_mode,
        allow_existing=allow_existing,
        copy_user_assets=copy_user_assets_enabled,
        max_trade_dates=max_trade_dates,
        max_stocks=max_stocks,
        force_refresh=force_refresh,
        summary_json=Path(summary_json) if summary_json else None,
        report=Path(report) if report else None,
        set_active=set_active,
    )
    stages: list[StageRecord] = []
    summary = _base_summary(config)

    def emit_record(record: StageRecord, *, status: str = "running", message: str | None = None) -> None:
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status=status,
            stage=record.name,
            stage_progress=1.0,
            message=message or f"{record.name}: {record.status}",
            rows=record.rows,
            failures=record.failures,
            warnings=record.warnings,
        )

    try:
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status="running",
            stage="preflight",
            stage_progress=0.0,
            message="Clean Tushare snapshot job started",
        )
        started = time.monotonic()
        preflight = preflight_clean_snapshot(config)
        emit_record(_record_stage(stages, "preflight", "pass", start_time=started, warnings=list(preflight.get("warnings", []))))
        if effective_mode == "plan-only":
            for stage in STAGE_NAMES[1:]:
                _record_stage(stages, stage, "planned")
            summary.update(
                {
                    "status": "PLAN_ONLY",
                    "validation_status": "not_run",
                    "pipeline_stages": STAGE_NAMES,
                    "copy_user_assets": bool(config.copy_user_assets),
                    "target_exists": bool(target_path.exists()),
                }
            )
            _finalize_summary(summary, stages)
            _write_summary_json(config.summary_json, summary)
            _write_report(config.report, summary)
            _emit_progress(
                progress_callback,
                job_id=job_id,
                status="plan_only",
                stage="stale_model_artifacts_plan",
                stage_progress=1.0,
                message="Clean Tushare snapshot plan-only completed",
            )
            return summary

        if effective_mode == "validate-only":
            target_storage = DuckDBStorage(target_path)
            started = time.monotonic()
            validation = validate_clean_snapshot(target_storage, [], [])
            emit_record(
                _record_stage(
                    stages,
                    "validate_clean_snapshot",
                    validation["validation_status"],
                    start_time=started,
                    failures=list(validation.get("failures", [])),
                    warnings=list(validation.get("warnings", [])),
                )
            )
            summary.update(validation)
            summary["status"] = "PASS" if validation["validation_status"] == "pass" else "FAILED"
            if set_active:
                if validation["validation_status"] != "pass":
                    raise RuntimeError("set-active requires successful validation")
                db_workspace.set_active_db_path(target_path)
            _finalize_summary(summary, stages)
            _write_summary_json(config.summary_json, summary)
            _write_report(config.report, summary)
            _emit_progress(
                progress_callback,
                job_id=job_id,
                status=str(summary["status"]).lower(),
                stage="validate_clean_snapshot",
                stage_progress=1.0,
                message="Clean Tushare snapshot validate-only completed",
            )
            return summary

        source_storage = DuckDBStorage(source_path)
        started = time.monotonic()
        if target_path.exists():
            target_storage = DuckDBStorage(target_path)
            target_storage.init_schema()
        else:
            db_workspace.create_database(target_path, label=target_path.name, initialize_schema=True)
            target_storage = DuckDBStorage(target_path)
        _write_metadata(
            target_storage,
            {
                "db_profile": SNAPSHOT_PROFILE,
                "created_by": "clean_tushare_snapshot",
                "snapshot_start_date": config.start,
                "snapshot_end_date": config.end,
                "market_data_source": "tushare",
                "qfq_policy": "explicit_reference_factor",
                "build_status": "building",
                "source_db_display_path": _display_path(source_path),
                "created_at": pd.Timestamp.now().isoformat(),
            },
        )
        emit_record(_record_stage(stages, "create_target_db", "pass", start_time=started, rows=1))

        started = time.monotonic()
        copied: dict[str, int] = {}
        if config.copy_user_assets:
            copied = copy_user_assets(source_storage, target_storage)
        emit_record(_record_stage(stages, "copy_user_assets", "pass", start_time=started, rows=sum(copied.values())))
        summary["copied_user_assets"] = copied

        client = client or create_data_client(storage=target_storage)

        started = time.monotonic()
        trade_dates = [str(date) for date in client.trade_dates(config.start, config.end, force_refresh=config.force_refresh)]  # type: ignore[attr-defined]
        if config.max_trade_dates is not None:
            trade_dates = trade_dates[: max(0, int(config.max_trade_dates))]
        if not trade_dates:
            raise ValueError("Tushare trade_cal returned no open trade dates")
        emit_record(_record_stage(stages, "fetch_trade_calendar", "pass", start_time=started, rows=len(trade_dates)))
        summary["trade_day_count"] = int(len(trade_dates))
        effective_end = trade_dates[-1]
        summary["end_date"] = effective_end

        started = time.monotonic()
        universe_res = client.all_a_stock_universe(force_refresh=config.force_refresh)  # type: ignore[attr-defined]
        universe = _selected_universe_frame(_client_result_data(universe_res), config.max_stocks)
        target_storage.upsert_df("all_a_stock_universe", universe, ["stock_code"])
        selected_codes = universe["stock_code"].astype(str).str.zfill(6).drop_duplicates().tolist()
        if not selected_codes:
            raise ValueError("selected Tushare universe is empty")
        emit_record(_record_stage(stages, "fetch_all_a_stock_universe", "pass", start_time=started, rows=len(universe)))
        summary["stock_count"] = int(len(selected_codes))

        started = time.monotonic()
        stock_result = fetch_clean_stock_ohlcv_qfq(
            client,
            target_storage,
            trade_dates,
            selected_codes,
            effective_end,
            force_refresh=config.force_refresh,
            progress_callback=progress_callback,
            job_id=job_id,
        )
        emit_record(
            _record_stage(
                stages,
                "fetch_stock_ohlcv_qfq",
                "pass",
                start_time=started,
                rows=int(stock_result["stock_ohlcv_rows"]),
                warnings=list(stock_result.get("warnings", [])),
            )
        )
        summary["stock_ohlcv_rows"] = int(stock_result["stock_ohlcv_rows"])
        summary["adj_factor_rows"] = int(stock_result["adj_factor_rows"])
        summary["daily_basic_rows"] = int(stock_result["daily_basic_rows"])
        summary["reference_factor_count"] = int(stock_result["reference_factor_count"])

        started = time.monotonic()
        index_result = rebuild_market_indices_and_benchmarks(client, target_storage, config.start, effective_end)
        index_status = "pass" if not index_result.get("failures") else "partial"
        emit_record(_record_stage(stages, "fetch_index_and_benchmark_ohlcv", index_status, start_time=started, rows=int(index_result["rows"]), warnings=list(index_result.get("failures", []))))
        summary["index_rows"] = int(index_result["rows"])

        started = time.monotonic()
        sector_result = fetch_sector_constituents(client, target_storage, force_refresh=config.force_refresh)
        sector_status = "pass" if not sector_result.get("failures") else "partial"
        sector_warnings = list(sector_result.get("warnings", []))
        sector_failures = list(sector_result.get("failures", []))
        emit_record(
            _record_stage(
                stages,
                "fetch_sector_constituents",
                sector_status,
                start_time=started,
                rows=int(sector_result.get("rows", 0) or 0),
                warnings=sector_warnings + (sector_failures if sector_status == "partial" else []),
                failures=sector_failures if sector_status == "failed" else [],
            )
        )
        summary["sector_count"] = int(sector_result.get("sector_count", 0) or 0)

        started = time.monotonic()
        sector_ohlcv_result = rebuild_sector_ohlcv_local_aggregate(target_storage, config.start, effective_end)
        sector_ohlcv_status = str(sector_ohlcv_result.get("status", "pass"))
        sector_ohlcv_failures = list(sector_ohlcv_result.get("failures", []))
        emit_record(
            _record_stage(
                stages,
                "rebuild_sector_ohlcv_local_aggregate",
                sector_ohlcv_status,
                start_time=started,
                rows=int(sector_ohlcv_result.get("rows", 0) or 0),
                failures=sector_ohlcv_failures if sector_ohlcv_status == "failed" else [],
                warnings=list(sector_ohlcv_result.get("warnings", [])) + (sector_ohlcv_failures if sector_ohlcv_status == "partial" else []),
            )
        )
        summary["sector_ohlcv_rows"] = int(sector_ohlcv_result.get("rows", 0) or 0)
        if int(sector_ohlcv_result.get("sector_count", 0) or 0):
            summary["sector_count"] = int(sector_ohlcv_result.get("sector_count", 0) or 0)

        started = time.monotonic()
        breadth_summary = update_market_breadth(config.start, effective_end, incremental=False, mode="full_market", storage=target_storage)
        emit_record(_record_stage(stages, "rebuild_market_breadth", "pass" if not breadth_summary.failures else "failed", start_time=started, rows=int(breadth_summary.rows), failures=list(breadth_summary.failures)))
        summary["market_breadth_rows"] = int(breadth_summary.rows)

        started = time.monotonic()
        sectors = target_storage.read_df("SELECT DISTINCT sector_id FROM sector_ohlcv ORDER BY sector_id")
        sector_ids = sectors["sector_id"].astype(str).tolist() if not sectors.empty else []
        feature_rows = rebuild_sector_feature_cache(target_storage, sector_ids, config.start, effective_end)
        emit_record(_record_stage(stages, "rebuild_sector_features", "pass", start_time=started, rows=int(feature_rows)))
        summary["sector_feature_rows"] = int(feature_rows)

        started = time.monotonic()
        validation = validate_clean_snapshot(target_storage, trade_dates, selected_codes)
        emit_record(_record_stage(stages, "validate_clean_snapshot", validation["validation_status"], start_time=started, failures=list(validation.get("failures", [])), warnings=list(validation.get("warnings", []))))
        summary.update(validation)

        summary["stale_model_artifacts_plan"] = stale_model_artifacts_plan()
        if _table_row_count(target_storage, "model_runs") == 0 and _table_row_count(target_storage, "hsmm_model_runs") == 0:
            summary["stale_model_artifacts_plan"]["old_model_artifacts_status"] = "no_model_artifacts_in_clean_db"

        started = time.monotonic()
        write_snapshot_manifest(target_storage, summary)
        emit_record(_record_stage(stages, "write_snapshot_manifest", "pass", start_time=started, rows=1))

        started = time.monotonic()
        emit_record(_record_stage(stages, "stale_model_artifacts_plan", "pass", start_time=started, rows=1))

        summary["status"] = "PASS" if summary.get("validation_status") == "pass" else "FAILED"
        if summary["status"] == "PASS":
            _write_metadata(target_storage, {"build_status": "pass", "completed_at": pd.Timestamp.now().isoformat()})
        else:
            _write_metadata(target_storage, {"build_status": "failed", "completed_at": pd.Timestamp.now().isoformat()})
        if set_active:
            if summary["status"] != "PASS":
                raise RuntimeError("set-active requires successful validation")
            db_workspace.set_active_db_path(target_path)
        _finalize_summary(summary, stages)
        _write_summary_json(config.summary_json, summary)
        _write_report(config.report, summary)
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status=str(summary["status"]).lower(),
            stage="stale_model_artifacts_plan",
            stage_progress=1.0,
            message="Clean Tushare snapshot build completed",
        )
        return summary
    except Exception as exc:
        if stages and stages[-1].name != "preflight" and stages[-1].status not in {"failed", "FAILED"}:
            pass
        summary["status"] = "FAILED"
        summary["validation_status"] = "failed"
        summary["error_type"] = type(exc).__name__
        summary["error"] = str(exc)
        if effective_mode == "build" and target_path.exists():
            try:
                _write_metadata(DuckDBStorage(target_path), {"build_status": "failed", "completed_at": pd.Timestamp.now().isoformat()})
            except Exception:
                pass
        if not stages or stages[-1].status not in {"failed", "FAILED"}:
            missing_stage = next((name for name in STAGE_NAMES if name not in {stage.name for stage in stages}), "pipeline")
            _record_stage(stages, missing_stage, "failed", failures=[f"{type(exc).__name__}: {exc}"])
        _finalize_summary(summary, stages)
        _write_summary_json(config.summary_json, summary)
        _write_report(config.report, summary)
        failed_stage = stages[-1].name if stages else "preflight"
        _emit_progress(
            progress_callback,
            job_id=job_id,
            status="failed",
            stage=failed_stage,
            stage_progress=1.0,
            message=f"{type(exc).__name__}: {exc}",
            failures=[f"{type(exc).__name__}: {exc}"],
        )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a clean Tushare-only DuckDB snapshot without retraining models.")
    parser.add_argument("--target-db", required=True)
    parser.add_argument("--source-db", default=None)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", default="today")
    parser.add_argument("--mode", choices=["plan-only", "build", "validate-only"], default="plan-only")
    parser.add_argument("--allow-existing", action="store_true")
    asset_group = parser.add_mutually_exclusive_group()
    asset_group.add_argument("--copy-user-assets", dest="copy_user_assets", action="store_true", default=True)
    asset_group.add_argument("--skip-user-assets", dest="copy_user_assets", action="store_false")
    parser.add_argument("--max-trade-dates", type=int, default=None)
    parser.add_argument("--max-stocks", type=int, default=None)
    parser.add_argument("--force-refresh", action="store_true")
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON))
    parser.add_argument("--report", default=str(DEFAULT_REPORT))
    parser.add_argument("--progress-json", default=None)
    parser.add_argument("--job-id", default=None)
    parser.add_argument("--set-active", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    progress_callback: ProgressCallback | None = None
    if args.progress_json:
        progress_path = Path(args.progress_json)

        def progress_callback(payload: dict[str, object]) -> None:
            _write_progress_json(progress_path, payload)

    summary = run_clean_tushare_snapshot(
        target_db=args.target_db,
        source_db=args.source_db,
        start=args.start,
        end=args.end,
        mode="plan-only" if args.dry_run else args.mode,
        allow_existing=args.allow_existing,
        copy_user_assets_enabled=args.copy_user_assets,
        max_trade_dates=args.max_trade_dates,
        max_stocks=args.max_stocks,
        force_refresh=args.force_refresh,
        summary_json=args.summary_json,
        report=args.report,
        set_active=args.set_active,
        progress_callback=progress_callback,
        job_id=args.job_id,
    )
    print(
        "Clean Tushare snapshot "
        f"status={summary.get('status')} "
        f"mode={summary.get('mode')} "
        f"target={summary.get('target_db')} "
        f"stock_rows={summary.get('stock_ohlcv_rows')} "
        f"validation={summary.get('validation_status')}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
