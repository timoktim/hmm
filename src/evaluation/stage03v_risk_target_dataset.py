"""Stage03V WP1 downside-risk target dataset builder.

This module turns the accepted Stage03V WP0/WP0.5 contracts into a
reproducible target-row construction path. It is intentionally offline and
read-only: no fetchers, model training, calibration, readiness assignment, or
prospective holdout performance is used here.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd


INDEX_ID = "STAGE03V-WP1-v1"
REPORT_VERSION = "stage03v_risk_event_target_support_v1"
STAGE_ID = "stage03v"
TARGET_DEFINITION_VERSION = "stage03v1_downside_event_target_v1"
TARGET_KIND = "downside_event"
SOURCE_TARGET_KIND = "sw2021_l2_downside_event"
THRESHOLD_TYPE_FIXED = "fixed"
ENTITY_TYPE = "sw2021_l2_industry"
TAXONOMY_PROVIDER = "SW"
TAXONOMY_VERSION = "SW2021"
TAXONOMY_LEVEL = "L2"
FEATURE_SCOPE_ID = "stage03v_wp1_target_scope_v1"
UNIVERSE_ID = "stage03v_sw2021_l2_target_universe_v1"
INFORMATION_CUTOFF_DATE = "2026-06-10"
HOLDOUT_START = "2026-06-11"
DEFAULT_SAMPLE_ROWS = 500
SILENT_BREAK_GAP_DAYS = 45

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V7_DB = ROOT / "data" / "db" / "a_share_hmm_tushare_v7.duckdb"
DEFAULT_FEASIBILITY_REPORT = ROOT / "reports" / "stage03v" / "sample_feasibility_report.json"
DEFAULT_OUTPUT = ROOT / "reports" / "stage03v" / "risk_event_target_support.md"
DEFAULT_SUMMARY_JSON = ROOT / "reports" / "stage03v" / "risk_event_target_support.json"
DEFAULT_SAMPLE_CSV = ROOT / "reports" / "stage03v" / "risk_event_target_dataset_sample.csv"
DEFAULT_TARGET_UNIVERSE = ROOT / "configs" / "stage03v_sw_l2_target_universe_v1.yaml"

TARGET_COLUMNS = [
    "trade_date",
    "entity_type",
    "entity_id",
    "sector_code",
    "sector_name",
    "taxonomy_provider",
    "taxonomy_version",
    "taxonomy_level",
    "feature_scope_id",
    "universe_id",
    "entity_segment_id",
    "split_role",
    "target_usage",
    "horizon",
    "threshold_type",
    "threshold_value",
    "target_kind",
    "future_return",
    "future_mae",
    "future_mdd",
    "future_realized_vol",
    "future_downside_vol",
    "event_label",
    "target_observation_end_date",
    "censoring_status",
    "exclusion_reason",
    "sample_weight",
    "target_definition_version",
    "source_db_path",
    "created_at",
]

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "target_dataset_built": "yes",
    "persistent_db_table_written": "no",
    "model_training": "no",
    "probability_calibration": "no",
    "readiness_assigned": "no",
    "holdout_consumed": "no",
    "HMM_HSMM_training_modified": "no",
    "stage03v2_implemented": "no",
    "stage03v3_implemented": "no",
}


@dataclass(frozen=True)
class SliceSpec:
    horizon: int
    threshold_value: float
    threshold_type: str
    source_target_kind: str
    feasibility_verdict: str
    target_usage: str


@dataclass(frozen=True)
class V7Inputs:
    price_frame: pd.DataFrame
    universe_frame: pd.DataFrame
    exclusions: list[dict[str, Any]]
    silent_break_entities: list[dict[str, Any]]
    coverage: dict[str, Any]


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if value is pd.NA:
        return None
    return str(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.DataFrame):
        return [_json_safe(row) for row in value.to_dict(orient="records")]
    if isinstance(value, pd.Series):
        return [_json_safe(v) for v in value.tolist()]
    if isinstance(value, (datetime, date, pd.Timestamp)):
        return pd.Timestamp(value).date().isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    if value is pd.NA:
        return None
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _safe_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    candidate = Path(path)
    if not candidate.is_absolute():
        return candidate.as_posix()
    try:
        return candidate.relative_to(ROOT).as_posix()
    except ValueError:
        return candidate.name


def resolve_v7_db_path(cli_db_path: Path | str | None = None) -> Path:
    env_path = os.environ.get("STAGE03V_V7_DB")
    if env_path:
        return Path(env_path)
    if cli_db_path is not None:
        return Path(cli_db_path)
    return DEFAULT_V7_DB


def _empty_target_frame() -> pd.DataFrame:
    return pd.DataFrame(columns=TARGET_COLUMNS)


def _to_date(value: Any) -> date | None:
    if value is None or pd.isna(value):
        return None
    return pd.Timestamp(value).date()


def _normalise_prices(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    rename_map = {}
    if "sector_id" in data.columns and "entity_id" not in data.columns:
        rename_map["sector_id"] = "entity_id"
    if rename_map:
        data = data.rename(columns=rename_map)
    required = {"entity_id", "trade_date", "close"}
    missing = required.difference(data.columns)
    if missing:
        raise ValueError(f"price frame missing required columns: {sorted(missing)}")
    data["entity_id"] = data["entity_id"].astype(str)
    data["trade_date"] = pd.to_datetime(data["trade_date"], errors="coerce").dt.normalize()
    data["close"] = pd.to_numeric(data["close"], errors="coerce")
    data = data[data["trade_date"].notna() & data["close"].gt(0)].copy()
    return data.sort_values(["entity_id", "trade_date"]).drop_duplicates(["entity_id", "trade_date"], keep="last")


def compute_path_metrics(
    closes: Sequence[float],
    *,
    base_index: int,
    horizon: int,
) -> dict[str, float] | None:
    """Compute future path metrics using t+1 through t+N only."""

    end_index = int(base_index) + int(horizon)
    if base_index < 0 or end_index >= len(closes):
        return None
    path = np.asarray(closes[base_index : end_index + 1], dtype=float)
    base = float(path[0])
    if not np.isfinite(base) or base <= 0:
        return None
    future = path[1:]
    if len(future) != int(horizon) or not np.isfinite(future).all() or (future <= 0).any():
        return None
    returns = future / base - 1.0
    step_returns = np.diff(path) / path[:-1]
    drawdowns = 1.0 - path / np.maximum.accumulate(path)
    downside_steps = step_returns[step_returns < 0]
    downside_vol = float(np.std(downside_steps, ddof=0)) if len(downside_steps) else 0.0
    realized_vol = float(np.std(step_returns, ddof=0)) if len(step_returns) else 0.0
    return {
        "future_return": float(returns[-1]),
        "future_mae": float(np.min(returns)),
        "future_mdd": float(np.max(drawdowns)),
        "future_realized_vol": realized_vol,
        "future_downside_vol": downside_vol,
    }


def _slice_specs_from_feasibility(feasibility: Mapping[str, Any]) -> list[SliceSpec]:
    rows = feasibility.get("fixed_threshold_feasibility_matrix", [])
    specs: list[SliceSpec] = []
    for row in rows:
        verdict = str(row.get("feasibility_verdict", "unknown"))
        threshold_type = str(row.get("threshold_type", ""))
        if threshold_type != THRESHOLD_TYPE_FIXED:
            continue
        if verdict not in {"eligible", "diagnostic_only"}:
            continue
        specs.append(
            SliceSpec(
                horizon=int(row["horizon"]),
                threshold_value=float(row.get("threshold", row.get("threshold_value"))),
                threshold_type=threshold_type,
                source_target_kind=str(row.get("target_kind", SOURCE_TARGET_KIND)),
                feasibility_verdict=verdict,
                target_usage="eligible" if verdict == "eligible" else "diagnostic_only",
            )
        )
    specs.sort(key=lambda item: (item.horizon, item.threshold_value, item.target_usage))
    return specs


def validate_wp0_5_feasibility(feasibility: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    coverage = feasibility.get("source_coverage", {})
    if feasibility.get("status") != "pass":
        issues.append("status_not_pass")
    if coverage.get("v7_coverage_available") != "yes":
        issues.append("v7_coverage_available_not_yes")
    if coverage.get("v7_db_requirement_status") != "pass":
        issues.append("v7_db_requirement_status_not_pass")
    if feasibility.get("sw2021_l2_universe_coverage") != "pass" and coverage.get("sw2021_l2_universe_coverage") != "pass":
        issues.append("sw2021_l2_universe_coverage_not_pass")
    universe_status = str(coverage.get("universe_source_status", ""))
    if not (
        universe_status == "verified_sw2021_l2_tushare_classify"
        or (universe_status.startswith("verified") and "sw2021" in universe_status.lower() and "l2" in universe_status.lower())
    ):
        issues.append("universe_source_status_not_verified_sw2021_l2")
    if int(feasibility.get("eligible_slice_count", 0) or 0) <= 0:
        issues.append("eligible_slice_count_not_positive")
    if feasibility.get("no_usable_probability_assigned") is not True:
        issues.append("usable_probability_already_assigned_or_unknown")
    return issues


def load_feasibility_report(path: Path | str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def compute_path_target_rows(
    price_frame: pd.DataFrame,
    slices: Sequence[SliceSpec | Mapping[str, Any]],
    *,
    cutoff_date: str | date | pd.Timestamp = INFORMATION_CUTOFF_DATE,
    metadata_frame: pd.DataFrame | None = None,
    excluded_entity_ids: set[str] | None = None,
    source_db_path: Path | str | None = None,
    created_at: str | None = None,
) -> pd.DataFrame:
    """Build target rows for small or sampled panels.

    Real WP1 reports use this same function for the capped audit sample. The
    full support counts are aggregated without dumping all target rows.
    """

    data = _normalise_prices(price_frame)
    if data.empty or not slices:
        return _empty_target_frame()

    cutoff = pd.Timestamp(cutoff_date).normalize()
    excluded = excluded_entity_ids or set()
    created = created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    safe_db = _safe_path(source_db_path)
    meta_by_entity: dict[str, dict[str, Any]] = {}
    if metadata_frame is not None and not metadata_frame.empty:
        meta = metadata_frame.copy()
        if "sector_id" in meta.columns and "entity_id" not in meta.columns:
            meta = meta.rename(columns={"sector_id": "entity_id"})
        for row in meta.to_dict(orient="records"):
            meta_by_entity[str(row.get("entity_id"))] = row

    normalised_slices: list[SliceSpec] = []
    for item in slices:
        if isinstance(item, SliceSpec):
            normalised_slices.append(item)
        else:
            verdict = str(item.get("feasibility_verdict", item.get("target_usage", "eligible")))
            normalised_slices.append(
                SliceSpec(
                    horizon=int(item["horizon"]),
                    threshold_value=float(item.get("threshold_value", item.get("threshold"))),
                    threshold_type=str(item.get("threshold_type", THRESHOLD_TYPE_FIXED)),
                    source_target_kind=str(item.get("target_kind", SOURCE_TARGET_KIND)),
                    feasibility_verdict=verdict,
                    target_usage="eligible" if verdict == "eligible" else "diagnostic_only",
                )
            )

    rows: list[dict[str, Any]] = []
    for entity_id, group in data.groupby("entity_id", sort=False):
        if str(entity_id) in excluded:
            continue
        group = group.sort_values("trade_date").reset_index(drop=True)
        closes = group["close"].to_numpy(dtype=float)
        dates = group["trade_date"].tolist()
        info = meta_by_entity.get(str(entity_id), {})
        sector_name = info.get("sector_name")
        entity_segment_id = str(info.get("entity_segment_id") or f"{entity_id}::segment_1")
        for idx, trade_ts in enumerate(dates):
            trade_ts = pd.Timestamp(trade_ts).normalize()
            if trade_ts > cutoff:
                continue
            for spec in normalised_slices:
                end_idx = idx + int(spec.horizon)
                end_date = pd.Timestamp(dates[end_idx]).normalize() if end_idx < len(dates) else None
                split_role = "historical_development"
                metrics = None
                censoring_status = "insufficient_future_prices"
                if end_date is not None and end_date > cutoff:
                    censoring_status = "cross_cutoff_censored"
                elif end_date is not None:
                    metrics = compute_path_metrics(closes, base_index=idx, horizon=spec.horizon)
                    censoring_status = "labeled" if metrics is not None else "insufficient_future_prices"
                event_label: bool | None = None
                if metrics is not None and censoring_status == "labeled":
                    event_label = bool(metrics["future_mae"] <= -float(spec.threshold_value))
                if censoring_status == "cross_cutoff_censored":
                    metrics = None
                    event_label = None
                rows.append(
                    {
                        "trade_date": trade_ts.date(),
                        "entity_type": ENTITY_TYPE,
                        "entity_id": str(entity_id),
                        "sector_code": str(entity_id),
                        "sector_name": sector_name,
                        "taxonomy_provider": TAXONOMY_PROVIDER,
                        "taxonomy_version": TAXONOMY_VERSION,
                        "taxonomy_level": TAXONOMY_LEVEL,
                        "feature_scope_id": FEATURE_SCOPE_ID,
                        "universe_id": UNIVERSE_ID,
                        "entity_segment_id": entity_segment_id,
                        "split_role": split_role,
                        "target_usage": spec.target_usage,
                        "horizon": int(spec.horizon),
                        "threshold_type": spec.threshold_type,
                        "threshold_value": float(spec.threshold_value),
                        "target_kind": TARGET_KIND,
                        "future_return": None if metrics is None else metrics["future_return"],
                        "future_mae": None if metrics is None else metrics["future_mae"],
                        "future_mdd": None if metrics is None else metrics["future_mdd"],
                        "future_realized_vol": None if metrics is None else metrics["future_realized_vol"],
                        "future_downside_vol": None if metrics is None else metrics["future_downside_vol"],
                        "event_label": event_label,
                        "target_observation_end_date": _to_date(end_date),
                        "censoring_status": censoring_status,
                        "exclusion_reason": None,
                        "sample_weight": 1.0,
                        "target_definition_version": TARGET_DEFINITION_VERSION,
                        "source_db_path": safe_db,
                        "created_at": created,
                    }
                )

    if not rows:
        return _empty_target_frame()
    result = pd.DataFrame(rows)
    return result[TARGET_COLUMNS]


def _table_exists(con: Any, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT count(*) AS n
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _table_columns(con: Any, table_name: str) -> set[str]:
    if not _table_exists(con, table_name):
        return set()
    return {
        str(row[0])
        for row in con.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = ?
            """,
            [table_name],
        ).fetchall()
    }


def _workspace_metadata(con: Any) -> dict[str, str]:
    if not _table_exists(con, "database_workspace_metadata"):
        return {}
    try:
        rows = con.execute("SELECT key, value FROM database_workspace_metadata").fetchall()
    except Exception:
        return {}
    return {str(key): str(value) for key, value in rows if key is not None}


def _yyyymmdd_to_timestamp(value: str | None) -> pd.Timestamp | None:
    if not value:
        return None
    parsed = pd.to_datetime(str(value), format="%Y%m%d", errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def _table_summary(con: Any, table_name: str) -> dict[str, Any]:
    if not _table_exists(con, table_name):
        return {"exists": False, "row_count": 0, "min_trade_date": None, "max_trade_date": None}
    row_count = int(con.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])
    columns = _table_columns(con, table_name)
    if "trade_date" not in columns or row_count == 0:
        return {"exists": True, "row_count": row_count, "min_trade_date": None, "max_trade_date": None}
    row = con.execute(f"SELECT min(trade_date), max(trade_date) FROM {table_name}").fetchone()
    return {
        "exists": True,
        "row_count": row_count,
        "min_trade_date": _json_safe(row[0]) if row else None,
        "max_trade_date": _json_safe(row[1]) if row else None,
    }


def _blocked_v7_inputs(db_path: Path | str | None, status: str, reason: str) -> V7Inputs:
    coverage = {
        "status": status,
        "source_db_path": _safe_path(db_path),
        "db_path": _safe_path(db_path),
        "db_available": bool(db_path and Path(db_path).exists()),
        "db_opened_read_only": False,
        "v7_coverage_available": "no",
        "v7_db_requirement_status": status,
        "sw2021_l2_universe_coverage": "missing",
        "benchmark_target_status": "unavailable",
        "blocking_reasons": [reason],
        "entity_count_total": 0,
        "entity_count_after_quality_filter": 0,
        "entity_count_after_silent_break_handling": 0,
        "silent_entity_break_count": 0,
        "quality_filter_exclusion_count": 0,
    }
    return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)


def read_v7_inputs(db_path: Path | str) -> V7Inputs:
    if not Path(db_path).exists():
        return _blocked_v7_inputs(db_path, "blocked_missing_v7_db", "STAGE03V_V7_DB/--db path is missing")
    try:
        import duckdb  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        return _blocked_v7_inputs(db_path, "blocked_invalid_v7_db", "duckdb module is unavailable")

    try:
        con = duckdb.connect(str(db_path), read_only=True)
    except Exception as exc:
        return _blocked_v7_inputs(db_path, "blocked_invalid_v7_db", f"failed to open V7 DB read-only: {exc}")

    try:
        coverage: dict[str, Any] = {
            "status": "unknown",
            "source_db_path": _safe_path(db_path),
            "db_path": _safe_path(db_path),
            "db_available": True,
            "db_opened_read_only": True,
            "v7_coverage_available": "unknown",
            "v7_db_requirement_status": "unknown",
            "sw2021_l2_universe_coverage": "missing",
            "benchmark_target_status": "unavailable",
            "source_tables": {},
            "workspace_metadata": {},
            "taxonomy_provider": TAXONOMY_PROVIDER,
            "taxonomy_version": TAXONOMY_VERSION,
            "taxonomy_level": TAXONOMY_LEVEL,
            "blocking_reasons": [],
        }
        for table in ["sector_meta", "sector_ohlcv", "sector_constituents", "market_benchmark_ohlcv"]:
            coverage["source_tables"][table] = _table_summary(con, table)
        if not _table_exists(con, "sector_meta") or not _table_exists(con, "sector_ohlcv"):
            coverage["status"] = "blocked_invalid_v7_db"
            coverage["v7_db_requirement_status"] = "blocked_invalid_v7_db"
            coverage["blocking_reasons"].append("sector_meta and sector_ohlcv are required")
            return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)

        metadata = _workspace_metadata(con)
        coverage["workspace_metadata"] = {
            key: metadata.get(key)
            for key in [
                "label",
                "db_profile",
                "active_source",
                "market_data_source",
                "snapshot_start_date",
                "snapshot_end_date",
                "snapshot_effective_end_date",
                "snapshot_skipped_trade_dates",
                "build_status",
                "validation_status",
            ]
            if key in metadata
        }
        sector_meta = con.execute(
            """
            SELECT sector_id, sector_type, sector_name, source, sector_level
            FROM sector_meta
            WHERE sector_type = 'industry'
            """
        ).fetchdf()
        if sector_meta.empty:
            coverage["status"] = "blocked_invalid_v7_db"
            coverage["v7_db_requirement_status"] = "blocked_invalid_v7_db"
            coverage["blocking_reasons"].append("sector_meta has no industry rows")
            return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)
        sector_meta["sector_id"] = sector_meta["sector_id"].astype(str)
        sector_meta["source"] = sector_meta["source"].fillna("").astype(str)
        sector_meta["sector_level"] = sector_meta["sector_level"].fillna("").astype(str)
        coverage["entity_count_total"] = int(sector_meta["sector_id"].nunique())

        verified_mask = sector_meta["source"].str.lower().eq("tushare_sw_classify") & sector_meta[
            "sector_level"
        ].str.upper().eq("L2")
        verified_meta = sector_meta[verified_mask].copy()
        verified_ids = set(verified_meta["sector_id"].astype(str))
        coverage["sw2021_l2_verified_entity_count"] = int(len(verified_ids))
        coverage["non_verified_or_non_l2_industry_count"] = int(coverage["entity_count_total"] - len(verified_ids))
        coverage["universe_source_status"] = (
            "verified_sw2021_l2_tushare_classify" if verified_ids else "unverified_local_industry"
        )
        if not verified_ids:
            coverage["status"] = "blocked_invalid_v7_db"
            coverage["v7_db_requirement_status"] = "blocked_invalid_v7_db"
            coverage["blocking_reasons"].append("verified SW2021 L2 universe is unavailable")
            return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)

        placeholders = ",".join(["?"] * len(verified_ids))
        ohlcv = con.execute(
            f"""
            SELECT sector_id, trade_date, close
            FROM sector_ohlcv
            WHERE sector_id IN ({placeholders})
              AND close IS NOT NULL
            ORDER BY sector_id, trade_date
            """,
            sorted(verified_ids),
        ).fetchdf()
        if ohlcv.empty:
            coverage["status"] = "blocked_invalid_v7_db"
            coverage["v7_db_requirement_status"] = "blocked_invalid_v7_db"
            coverage["blocking_reasons"].append("verified SW2021 L2 sector_ohlcv is empty")
            return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)
        ohlcv["sector_id"] = ohlcv["sector_id"].astype(str)
        ohlcv["trade_date"] = pd.to_datetime(ohlcv["trade_date"], errors="coerce").dt.normalize()
        coverage_start = ohlcv["trade_date"].min()
        coverage_end = ohlcv["trade_date"].max()
        coverage["coverage_start"] = _json_safe(coverage_start)
        coverage["coverage_end"] = _json_safe(coverage_end)

        snapshot_start = _yyyymmdd_to_timestamp(metadata.get("snapshot_start_date"))
        label = metadata.get("label", "")
        profile = metadata.get("db_profile", "")
        source = metadata.get("market_data_source", metadata.get("active_source", ""))
        long_history_available = bool(pd.notna(coverage_start) and coverage_start <= pd.Timestamp("2014-01-03"))
        metadata_confirms_v7 = bool(
            "v7" in label.lower()
            and profile == "clean_tushare_snapshot"
            and source == "tushare"
            and metadata.get("build_status") == "pass"
            and metadata.get("validation_status") == "pass"
            and snapshot_start is not None
            and snapshot_start <= pd.Timestamp("2014-01-01")
        )
        v7_available = long_history_available and metadata_confirms_v7
        coverage["v7_coverage_available"] = "yes" if v7_available else "no"
        coverage["v7_db_requirement_status"] = "pass" if v7_available else "blocked_invalid_v7_db"
        if not v7_available:
            coverage["status"] = "blocked_invalid_v7_db"
            coverage["blocking_reasons"].append(
                "DB does not satisfy Stage03V V7 long-history clean Tushare snapshot requirement"
            )
            return V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], coverage)

        silent_break_entities = _detect_silent_break_entities(
            ohlcv.rename(columns={"sector_id": "entity_id"}),
            metadata_frame=verified_meta.rename(columns={"sector_id": "entity_id"}),
        )

        exclusions: list[dict[str, Any]] = []
        for _, row in sector_meta[~sector_meta["sector_id"].isin(verified_ids)].iterrows():
            exclusions.append(
                {
                    "entity_id": row["sector_id"],
                    "sector_name": row.get("sector_name"),
                    "reason": "non_verified_or_non_l2_industry",
                }
            )

        constituent_counts = pd.DataFrame(columns=["sector_id", "constituent_count"])
        if _table_exists(con, "sector_constituents"):
            constituent_counts = con.execute(
                f"""
                SELECT sector_id, count(DISTINCT stock_code) AS constituent_count
                FROM sector_constituents
                WHERE sector_id IN ({placeholders})
                GROUP BY sector_id
                """,
                sorted(verified_ids),
            ).fetchdf()
        low_constituent_ids: set[str] = set()
        if not constituent_counts.empty:
            constituent_counts["sector_id"] = constituent_counts["sector_id"].astype(str)
            constituent_counts["constituent_count"] = constituent_counts["constituent_count"].astype(int)
            coverage["constituent_snapshot_available"] = True
            coverage["constituent_count_min_observed"] = int(constituent_counts["constituent_count"].min())
            low_constituents = constituent_counts[constituent_counts["constituent_count"] < 5]
            low_constituent_ids = set(low_constituents["sector_id"].astype(str))
            coverage["constituent_count_filter_status"] = "pass" if not low_constituent_ids else "partial_low_constituents"
        else:
            coverage["constituent_snapshot_available"] = False
            coverage["constituent_count_filter_status"] = "not_applicable_missing_constituents"
        for entity_id in sorted(low_constituent_ids):
            row = verified_meta[verified_meta["sector_id"].eq(entity_id)].head(1)
            exclusions.append(
                {
                    "entity_id": entity_id,
                    "sector_name": None if row.empty else row.iloc[0].get("sector_name"),
                    "reason": "constituent_count_lt_5",
                }
            )

        entity_summary = (
            ohlcv.groupby("sector_id")
            .agg(min_trade_date=("trade_date", "min"), max_trade_date=("trade_date", "max"), row_count=("trade_date", "count"))
            .reset_index()
        )
        short_history_ids = set(
            entity_summary.loc[entity_summary["min_trade_date"] > pd.Timestamp("2021-07-01"), "sector_id"].astype(str)
        )
        coverage["short_history_entity_count"] = int(len(short_history_ids))
        for entity_id in sorted(short_history_ids):
            row = verified_meta[verified_meta["sector_id"].eq(entity_id)].head(1)
            exclusions.append(
                {
                    "entity_id": entity_id,
                    "sector_name": None if row.empty else row.iloc[0].get("sector_name"),
                    "reason": "short_history_after_2021_reform",
                }
            )

        quality_excluded_ids = {str(item["entity_id"]) for item in exclusions}
        quality_ids = sorted(verified_ids - quality_excluded_ids)
        coverage["quality_filter_exclusion_count"] = int(len(quality_excluded_ids))
        coverage["entity_count_after_quality_filter"] = int(len(quality_ids))

        silent_ids = {str(item["entity_id"]) for item in silent_break_entities}
        for item in silent_break_entities:
            item["handling"] = (
                "silent_break_already_excluded_by_quality_filter"
                if item["entity_id"] in quality_excluded_ids
                else "excluded"
            )
            exclusions.append(
                {
                    "entity_id": item["entity_id"],
                    "sector_name": item.get("sector_name"),
                    "reason": item["handling"],
                    "max_gap_days": item.get("max_gap_days"),
                    "break_gap_count": item.get("break_gap_count"),
                }
            )

        final_ids = sorted(set(quality_ids) - silent_ids)
        coverage["silent_entity_break_count"] = int(len(silent_break_entities))
        coverage["silent_entity_break_handling"] = "excluded"
        coverage["entity_count_after_silent_break_handling"] = int(len(final_ids))
        coverage["sw2021_l2_universe_coverage"] = "pass" if final_ids else "missing"
        coverage["benchmark_target_status"] = "available" if _table_exists(con, "market_benchmark_ohlcv") else "unavailable"
        coverage["status"] = "pass" if final_ids else "blocked_invalid_v7_db"

        universe_frame = verified_meta[verified_meta["sector_id"].isin(final_ids)].copy()
        universe_frame = universe_frame.rename(columns={"sector_id": "entity_id"})
        universe_frame["entity_segment_id"] = universe_frame["entity_id"].astype(str) + "::segment_1"
        universe_frame["taxonomy_provider"] = TAXONOMY_PROVIDER
        universe_frame["taxonomy_version"] = TAXONOMY_VERSION
        universe_frame["taxonomy_level"] = TAXONOMY_LEVEL
        price_frame = ohlcv[ohlcv["sector_id"].isin(final_ids)].rename(columns={"sector_id": "entity_id"})
        return V7Inputs(price_frame, universe_frame, exclusions, silent_break_entities, coverage)
    finally:
        con.close()


def _detect_silent_break_entities(
    price_frame: pd.DataFrame,
    *,
    metadata_frame: pd.DataFrame | None = None,
    gap_days: int = SILENT_BREAK_GAP_DAYS,
) -> list[dict[str, Any]]:
    data = _normalise_prices(price_frame)
    meta_by_entity: dict[str, dict[str, Any]] = {}
    if metadata_frame is not None and not metadata_frame.empty:
        meta = metadata_frame.copy()
        if "sector_id" in meta.columns and "entity_id" not in meta.columns:
            meta = meta.rename(columns={"sector_id": "entity_id"})
        for row in meta.to_dict(orient="records"):
            meta_by_entity[str(row.get("entity_id"))] = row

    rows: list[dict[str, Any]] = []
    for entity_id, group in data.groupby("entity_id", sort=False):
        gaps = group.sort_values("trade_date")["trade_date"].diff().dt.days.dropna()
        break_gaps = gaps[gaps > int(gap_days)]
        if break_gaps.empty:
            continue
        info = meta_by_entity.get(str(entity_id), {})
        rows.append(
            {
                "entity_id": str(entity_id),
                "sector_name": info.get("sector_name"),
                "max_gap_days": int(break_gaps.max()),
                "break_gap_count": int(len(break_gaps)),
                "handling": "excluded",
                "reason": "unexplained_price_history_gap_gt_45_calendar_days",
            }
        )
    rows.sort(key=lambda item: (-int(item["max_gap_days"]), item["entity_id"]))
    return rows


def _aggregate_support_counts(
    price_frame: pd.DataFrame,
    universe_frame: pd.DataFrame,
    slices: Sequence[SliceSpec],
    *,
    source_db_path: Path | str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if price_frame.empty or not slices:
        empty_summary = {
            "target_row_count": 0,
            "split_role_counts": {},
            "censoring_status_counts": {},
            "cross_cutoff_censored_count": 0,
            "cross_cutoff_excluded_count": 0,
            "historical_development_labeled_count": 0,
            "historical_development_unlabeled_due_to_cutoff_count": 0,
        }
        return pd.DataFrame(), empty_summary

    cutoff = pd.Timestamp(INFORMATION_CUTOFF_DATE).normalize()
    count_by_slice: dict[tuple[int, str, float, str, str, str], dict[str, Any]] = {}
    aggregate = {
        "target_row_count": 0,
        "split_role_counts": {"historical_development": 0},
        "censoring_status_counts": {},
        "cross_cutoff_censored_count": 0,
        "cross_cutoff_excluded_count": 0,
        "historical_development_labeled_count": 0,
        "historical_development_unlabeled_due_to_cutoff_count": 0,
    }
    max_sample_bases_per_entity = 2
    max_horizon = max(int(item.horizon) for item in slices)
    unique_horizons = sorted({int(item.horizon) for item in slices})
    sample_price_rows: list[pd.DataFrame] = []
    entity_to_name = (
        universe_frame[["entity_id", "sector_name", "entity_segment_id"]].copy()
        if not universe_frame.empty
        else pd.DataFrame(columns=["entity_id", "sector_name", "entity_segment_id"])
    )
    sample_entity_ids = sorted(price_frame["entity_id"].astype(str).unique().tolist())[:8]

    for entity_id, group in price_frame.groupby("entity_id", sort=False):
        group = group.sort_values("trade_date").reset_index(drop=True)
        closes = group["close"].to_numpy(dtype=float)
        dates = group["trade_date"].tolist()
        sample_indices: set[int] = set()
        if str(entity_id) in sample_entity_ids:
            cutoff_positions = [idx for idx, value in enumerate(dates) if pd.Timestamp(value).normalize() <= cutoff]
            sample_indices.update(cutoff_positions[:max_sample_bases_per_entity])
            if cutoff_positions:
                sample_indices.add(cutoff_positions[-1])

        for idx, trade_ts in enumerate(dates):
            trade_ts = pd.Timestamp(trade_ts).normalize()
            if trade_ts > cutoff:
                continue

            metrics_by_horizon: dict[int, tuple[str, dict[str, float] | None]] = {}
            for horizon in unique_horizons:
                end_idx = idx + horizon
                end_date = pd.Timestamp(dates[end_idx]).normalize() if end_idx < len(dates) else None
                metrics = None
                if end_date is not None and end_date > cutoff:
                    censoring_status = "cross_cutoff_censored"
                    metrics = None
                elif end_date is not None:
                    metrics = compute_path_metrics(closes, base_index=idx, horizon=horizon)
                    censoring_status = "labeled" if metrics is not None else "insufficient_future_prices"
                else:
                    censoring_status = "insufficient_future_prices"
                metrics_by_horizon[horizon] = (censoring_status, metrics)

            for spec in slices:
                aggregate["target_row_count"] += 1
                aggregate["split_role_counts"]["historical_development"] += 1
                censoring_status, metrics = metrics_by_horizon[int(spec.horizon)]
                aggregate["censoring_status_counts"][censoring_status] = (
                    aggregate["censoring_status_counts"].get(censoring_status, 0) + 1
                )
                if censoring_status == "labeled":
                    aggregate["historical_development_labeled_count"] += 1
                elif censoring_status == "cross_cutoff_censored":
                    aggregate["cross_cutoff_censored_count"] += 1
                    aggregate["historical_development_unlabeled_due_to_cutoff_count"] += 1

                key = (
                    int(spec.horizon),
                    spec.threshold_type,
                    float(spec.threshold_value),
                    TARGET_KIND,
                    spec.target_usage,
                    spec.feasibility_verdict,
                )
                if key not in count_by_slice:
                    count_by_slice[key] = {
                        "horizon": int(spec.horizon),
                        "threshold_type": spec.threshold_type,
                        "threshold_value": float(spec.threshold_value),
                        "target_kind": TARGET_KIND,
                        "target_usage": spec.target_usage,
                        "feasibility_verdict": spec.feasibility_verdict,
                        "target_row_count": 0,
                        "labeled_count": 0,
                        "cross_cutoff_censored_count": 0,
                        "insufficient_future_price_count": 0,
                        "positive_event_count": 0,
                    }
                row = count_by_slice[key]
                row["target_row_count"] += 1
                row["labeled_count"] += 1 if censoring_status == "labeled" else 0
                row["cross_cutoff_censored_count"] += 1 if censoring_status == "cross_cutoff_censored" else 0
                row["insufficient_future_price_count"] += 1 if censoring_status == "insufficient_future_prices" else 0
                row["positive_event_count"] += (
                    1
                    if metrics is not None
                    and censoring_status == "labeled"
                    and metrics["future_mae"] <= -float(spec.threshold_value)
                    else 0
                )

            if idx in sample_indices:
                start = max(0, idx - 1)
                end = min(len(group), idx + max_horizon + 1)
                sample_price_rows.append(group.iloc[start:end])

    counts = pd.DataFrame(count_by_slice.values())
    if counts.empty:
        summary = pd.DataFrame()
    else:
        summary = counts.sort_values(["horizon", "threshold_value", "target_usage"]).reset_index(drop=True)
        summary["event_base_rate"] = summary["positive_event_count"] / summary["labeled_count"].replace({0: np.nan})

    if sample_price_rows:
        sample_prices = pd.concat(sample_price_rows, ignore_index=True).drop_duplicates(["entity_id", "trade_date"])
        sample_rows = compute_path_target_rows(
            sample_prices,
            slices,
            cutoff_date=INFORMATION_CUTOFF_DATE,
            metadata_frame=entity_to_name,
            source_db_path=source_db_path,
            created_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        )
    else:
        sample_rows = _empty_target_frame()
    return summary, {**aggregate, "sample_rows": sample_rows}


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(dict(data)), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_markdown(path: Path, report: Mapping[str, Any]) -> None:
    lines = [
        "# Stage03V WP1 Risk Event Target Support",
        "",
        f"- index_id: {report.get('index_id')}",
        f"- status: {report.get('status')}",
        f"- source_db_path: {report.get('source_db_path')}",
        f"- feasibility_report_status: {report.get('feasibility_report_status')}",
        f"- v7_coverage_available: {report.get('v7_coverage_available')}",
        f"- sw2021_l2_universe_coverage: {report.get('sw2021_l2_universe_coverage')}",
        f"- entity_count_after_quality_filter: {report.get('entity_count_after_quality_filter')}",
        f"- entity_count_after_silent_break_handling: {report.get('entity_count_after_silent_break_handling')}",
        f"- silent_entity_break_count: {report.get('silent_entity_break_count')}",
        f"- silent_entity_break_handling: {report.get('silent_entity_break_handling')}",
        f"- target_row_count: {report.get('target_row_count')}",
        f"- historical_development_labeled_count: {report.get('historical_development_labeled_count')}",
        f"- cross_cutoff_censored_count: {report.get('cross_cutoff_censored_count')}",
        f"- sample_csv_row_count: {report.get('sample_csv_row_count')}",
        f"- persistent_db_table_written: {report.get('boundary_flags', {}).get('persistent_db_table_written')}",
        "",
        "## Boundary Flags",
        "",
    ]
    for key, value in report.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Silent Entity Breaks", ""])
    for item in report.get("silent_entity_break_entities", []):
        lines.append(
            f"- {item.get('entity_id')} {item.get('sector_name')} "
            f"max_gap_days={item.get('max_gap_days')} handling={item.get('handling')}"
        )
    if not report.get("silent_entity_break_entities"):
        lines.append("- none")
    lines.extend(["", "## Slice Support Summary", ""])
    for item in report.get("slice_support_summary", []):
        lines.append(
            "- "
            f"horizon={item.get('horizon')} threshold={item.get('threshold_value')} "
            f"usage={item.get('target_usage')} rows={item.get('target_row_count')} "
            f"labeled={item.get('labeled_count')} positives={item.get('positive_event_count')}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sample_csv(path: Path, sample_rows: pd.DataFrame, sample_cap: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    if sample_rows.empty:
        _empty_target_frame().to_csv(path, index=False)
        return 0
    sample = sample_rows.sort_values(["entity_id", "trade_date", "horizon", "threshold_value"]).head(int(sample_cap)).copy()
    sample.to_csv(path, index=False)
    return int(len(sample))


def _write_target_universe_manifest(path: Path, report: Mapping[str, Any], v7: V7Inputs) -> None:
    universe_rows = []
    if not v7.universe_frame.empty:
        for row in v7.universe_frame.sort_values("entity_id").to_dict(orient="records"):
            universe_rows.append(
                {
                    "entity_id": row.get("entity_id"),
                    "sector_code": row.get("entity_id"),
                    "sector_name": row.get("sector_name"),
                    "entity_segment_id": row.get("entity_segment_id"),
                    "taxonomy_provider": TAXONOMY_PROVIDER,
                    "taxonomy_version": TAXONOMY_VERSION,
                    "taxonomy_level": TAXONOMY_LEVEL,
                }
            )
    exclusion_reason_counts: dict[str, int] = {}
    for item in v7.exclusions:
        reason = str(item.get("reason", "unknown"))
        exclusion_reason_counts[reason] = exclusion_reason_counts.get(reason, 0) + 1
    quality_filter_summary = {
        "quality_filter_exclusion_count": report.get("quality_filter_exclusion_count"),
        "non_verified_or_non_l2_industry_count": report.get("non_verified_or_non_l2_industry_count"),
        "constituent_count_min_required": 5,
        "constituent_count_min_observed": report.get("constituent_count_min_observed"),
        "constituent_count_filter_status": report.get("constituent_count_filter_status"),
        "short_history_entity_count": report.get("short_history_entity_count"),
        "silent_entity_break_count": report.get("silent_entity_break_count"),
        "silent_entity_break_handling": report.get("silent_entity_break_handling"),
        "exclusion_reason_counts": exclusion_reason_counts,
    }
    manifest = {
        "metadata": {
            "schema_name": "stage03v_sw_l2_target_universe",
            "schema_version": "v1",
            "index_id": INDEX_ID,
            "stage_id": STAGE_ID,
            "target_definition_version": TARGET_DEFINITION_VERSION,
            "created_at": report.get("created_at"),
        },
        "source": {
            "db_path": report.get("source_db_path"),
            "feasibility_report": report.get("feasibility_report_path"),
            "taxonomy_source_status": report.get("universe_source_status"),
            "universe_source_status": report.get("universe_source_status"),
            "v7_coverage_available": report.get("v7_coverage_available"),
            "v7_db_requirement_status": report.get("v7_db_requirement_status"),
            "coverage_start": report.get("coverage_start"),
            "coverage_end": report.get("coverage_end"),
        },
        "universe": {
            "entity_type": ENTITY_TYPE,
            "taxonomy_provider": TAXONOMY_PROVIDER,
            "taxonomy_version": TAXONOMY_VERSION,
            "taxonomy_level": TAXONOMY_LEVEL,
            "feature_scope_id": FEATURE_SCOPE_ID,
            "universe_id": UNIVERSE_ID,
            "entity_count_total": report.get("entity_count_total"),
            "entity_count_after_quality_filter": report.get("entity_count_after_quality_filter"),
            "entity_count_after_silent_break_handling": report.get("entity_count_after_silent_break_handling"),
            "quality_filter_exclusion_count": report.get("quality_filter_exclusion_count"),
            "constituent_count_filter_status": report.get("constituent_count_filter_status"),
            "silent_entity_break_count": report.get("silent_entity_break_count"),
            "silent_entity_break_handling": report.get("silent_entity_break_handling"),
            "permanent_censoring_policy": report.get("permanent_censoring_policy"),
        },
        "quality_filter_summary": quality_filter_summary,
        "silent_entity_break_entities": report.get("silent_entity_break_entities", []),
        "exclusions": v7.exclusions,
        "entity_audit_summary": {
            "entity_list_materialized": True,
            "entity_count": len(universe_rows),
            "entity_id_field": "entity_id",
            "entity_segment_policy": "single_segment_after_excluding_unexplained_silent_breaks",
        },
        "entities": universe_rows,
        "boundary_flags": report.get("boundary_flags", {}),
    }
    _write_json(path, manifest)


def _blocked_report(
    *,
    status: str,
    db_path: Path | str | None,
    feasibility_path: Path | str,
    feasibility_status: str | None = None,
    reasons: Sequence[str] = (),
) -> dict[str, Any]:
    return {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "status": status,
        "contract_status": "blocked",
        "feasibility_report_path": _safe_path(feasibility_path),
        "feasibility_report_status": feasibility_status,
        "source_db_path": _safe_path(db_path),
        "db_opened_read_only": "no",
        "v7_coverage_available": "no",
        "sw2021_l2_universe_coverage": "missing",
        "benchmark_target_status": "unavailable",
        "blocking_reasons": list(reasons),
        "entity_count_total": 0,
        "entity_count_after_quality_filter": 0,
        "entity_count_after_silent_break_handling": 0,
        "silent_entity_break_count": 0,
        "silent_entity_break_entities": [],
        "silent_entity_break_handling": "not_applicable",
        "quality_filter_exclusion_count": 0,
        "target_row_count": 0,
        "sample_csv_row_count": 0,
        "split_role_counts": {},
        "censoring_status_counts": {},
        "cross_cutoff_censored_count": 0,
        "cross_cutoff_excluded_count": 0,
        "historical_development_labeled_count": 0,
        "historical_development_unlabeled_due_to_cutoff_count": 0,
        "slice_support_summary": [],
        "eligible_slice_count": 0,
        "diagnostic_only_slice_count": 0,
        "excluded_slice_count": 0,
        "target_definition_version": TARGET_DEFINITION_VERSION,
        "permanent_censoring_policy": "cross_cutoff_censored",
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "boundary_flags": {**BOUNDARY_FLAGS, "target_dataset_built": "no"},
    }


def build_risk_target_report(
    *,
    db_path: Path | str | None = None,
    feasibility_path: Path | str = DEFAULT_FEASIBILITY_REPORT,
    output: Path | str = DEFAULT_OUTPUT,
    summary_json: Path | str = DEFAULT_SUMMARY_JSON,
    sample_csv: Path | str = DEFAULT_SAMPLE_CSV,
    target_universe: Path | str | None = None,
    sample_cap: int = DEFAULT_SAMPLE_ROWS,
    no_fetch: bool = True,
) -> dict[str, Any]:
    resolved_db = resolve_v7_db_path(db_path)
    output_path = Path(output)
    summary_path = Path(summary_json)
    sample_path = Path(sample_csv)
    target_universe_explicit = target_universe is not None
    universe_path = Path(target_universe) if target_universe_explicit else DEFAULT_TARGET_UNIVERSE

    if not no_fetch:
        raise ValueError("Stage03V WP1 target builder is no-fetch only")

    feasibility = load_feasibility_report(feasibility_path)
    feasibility_issues = validate_wp0_5_feasibility(feasibility)
    if feasibility_issues:
        report = _blocked_report(
            status="blocked_wp0_5_not_ready",
            db_path=resolved_db,
            feasibility_path=feasibility_path,
            feasibility_status=feasibility.get("status"),
            reasons=feasibility_issues,
        )
        report["target_universe_manifest_path"] = _safe_path(universe_path) if target_universe_explicit else None
        report["target_universe_manifest_written"] = bool(target_universe_explicit)
        _write_markdown(output_path, report)
        _write_json(summary_path, report)
        _write_sample_csv(sample_path, _empty_target_frame(), sample_cap)
        if target_universe_explicit:
            _write_target_universe_manifest(universe_path, report, V7Inputs(pd.DataFrame(), pd.DataFrame(), [], [], {}))
        return report

    v7 = read_v7_inputs(resolved_db)
    if v7.coverage.get("status") != "pass":
        report = _blocked_report(
            status=str(v7.coverage.get("status", "blocked_invalid_v7_db")),
            db_path=resolved_db,
            feasibility_path=feasibility_path,
            feasibility_status=feasibility.get("status"),
            reasons=v7.coverage.get("blocking_reasons", []),
        )
        report["db_opened_read_only"] = "yes" if v7.coverage.get("db_opened_read_only") else "no"
        report["v7_coverage_available"] = v7.coverage.get("v7_coverage_available", "no")
        report["target_universe_manifest_path"] = _safe_path(universe_path) if target_universe_explicit else None
        report["target_universe_manifest_written"] = bool(target_universe_explicit)
        _write_markdown(output_path, report)
        _write_json(summary_path, report)
        _write_sample_csv(sample_path, _empty_target_frame(), sample_cap)
        if target_universe_explicit:
            _write_target_universe_manifest(universe_path, report, v7)
        return report

    slices = _slice_specs_from_feasibility(feasibility)
    all_slice_rows = feasibility.get("fixed_threshold_feasibility_matrix", [])
    excluded_slice_count = int(
        len(
            [
                row
                for row in all_slice_rows
                if str(row.get("threshold_type")) == THRESHOLD_TYPE_FIXED
                and str(row.get("feasibility_verdict")) not in {"eligible", "diagnostic_only"}
            ]
        )
    )
    slice_summary, aggregate = _aggregate_support_counts(
        v7.price_frame,
        v7.universe_frame,
        slices,
        source_db_path=resolved_db,
    )
    sample_rows = aggregate.pop("sample_rows", _empty_target_frame())
    sample_count = _write_sample_csv(sample_path, sample_rows, sample_cap)

    slice_support = [] if slice_summary.empty else slice_summary.to_dict(orient="records")
    eligible_slice_count = int(sum(1 for item in slices if item.target_usage == "eligible"))
    diagnostic_slice_count = int(sum(1 for item in slices if item.target_usage == "diagnostic_only"))
    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    report: dict[str, Any] = {
        "index_id": INDEX_ID,
        "report_version": REPORT_VERSION,
        "stage_id": STAGE_ID,
        "status": "pass",
        "contract_status": "pass",
        "feasibility_report_path": _safe_path(feasibility_path),
        "feasibility_report_status": feasibility.get("status"),
        "source_db_path": _safe_path(resolved_db),
        "db_opened_read_only": "yes",
        "v7_coverage_available": v7.coverage.get("v7_coverage_available"),
        "v7_db_requirement_status": v7.coverage.get("v7_db_requirement_status"),
        "sw2021_l2_universe_coverage": v7.coverage.get("sw2021_l2_universe_coverage"),
        "universe_source_status": v7.coverage.get("universe_source_status"),
        "benchmark_target_status": v7.coverage.get("benchmark_target_status"),
        "coverage_start": v7.coverage.get("coverage_start"),
        "coverage_end": v7.coverage.get("coverage_end"),
        "entity_count_total": v7.coverage.get("entity_count_total"),
        "entity_count_after_quality_filter": v7.coverage.get("entity_count_after_quality_filter"),
        "entity_count_after_silent_break_handling": v7.coverage.get("entity_count_after_silent_break_handling"),
        "silent_entity_break_count": v7.coverage.get("silent_entity_break_count"),
        "silent_entity_break_entities": v7.silent_break_entities,
        "silent_entity_break_handling": v7.coverage.get("silent_entity_break_handling"),
        "quality_filter_exclusion_count": v7.coverage.get("quality_filter_exclusion_count"),
        "non_verified_or_non_l2_industry_count": v7.coverage.get("non_verified_or_non_l2_industry_count"),
        "short_history_entity_count": v7.coverage.get("short_history_entity_count"),
        "constituent_count_min_observed": v7.coverage.get("constituent_count_min_observed"),
        "constituent_count_filter_status": v7.coverage.get("constituent_count_filter_status"),
        "target_row_count": aggregate["target_row_count"],
        "sample_csv_row_count": sample_count,
        "split_role_counts": aggregate["split_role_counts"],
        "censoring_status_counts": aggregate["censoring_status_counts"],
        "cross_cutoff_censored_count": aggregate["cross_cutoff_censored_count"],
        "cross_cutoff_excluded_count": aggregate["cross_cutoff_excluded_count"],
        "historical_development_labeled_count": aggregate["historical_development_labeled_count"],
        "historical_development_unlabeled_due_to_cutoff_count": aggregate[
            "historical_development_unlabeled_due_to_cutoff_count"
        ],
        "slice_support_summary": slice_support,
        "eligible_slice_count": eligible_slice_count,
        "diagnostic_only_slice_count": diagnostic_slice_count,
        "excluded_slice_count": excluded_slice_count,
        "target_definition_version": TARGET_DEFINITION_VERSION,
        "permanent_censoring_policy": "cross_cutoff_censored",
        "sample_weight_policy": "constant_1_0",
        "target_rows_materialized": "sample_csv_only",
        "sample_csv_path": _safe_path(sample_path),
        "target_universe_manifest_path": _safe_path(universe_path),
        "target_universe_manifest_written": True,
        "created_at": created_at,
        "no_fetch": True,
        "external_data_fetch": "no",
        "no_usable_probability_assigned": True,
        "readiness_assigned": "no",
        "holdout_consumed": "no",
        "boundary_flags": BOUNDARY_FLAGS,
    }
    _write_markdown(output_path, report)
    _write_json(summary_path, report)
    _write_target_universe_manifest(universe_path, report, v7)
    return report


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=None, help="V7 DuckDB path. STAGE03V_V7_DB takes precedence.")
    parser.add_argument("--feasibility", type=Path, default=DEFAULT_FEASIBILITY_REPORT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--summary-json", type=Path, default=DEFAULT_SUMMARY_JSON)
    parser.add_argument("--sample-csv", type=Path, default=DEFAULT_SAMPLE_CSV)
    parser.add_argument(
        "--target-universe",
        type=Path,
        default=None,
        help=(
            "Target universe manifest path. Successful V7 runs default to the formal config path; "
            "blocked runs write a manifest only when this option is explicit."
        ),
    )
    parser.add_argument("--sample-cap", type=int, default=DEFAULT_SAMPLE_ROWS)
    parser.add_argument("--no-fetch", action="store_true", default=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    report = build_risk_target_report(
        db_path=args.db,
        feasibility_path=args.feasibility,
        output=args.output,
        summary_json=args.summary_json,
        sample_csv=args.sample_csv,
        target_universe=args.target_universe,
        sample_cap=args.sample_cap,
        no_fetch=args.no_fetch,
    )
    print(
        "STAGE03V_RISK_TARGET="
        f"{report.get('status')} "
        f"db_path={report.get('source_db_path')} "
        f"report={_safe_path(args.output)} "
        f"summary_json={_safe_path(args.summary_json)} "
        f"sample_csv={_safe_path(args.sample_csv)} "
        "no_fetch=yes"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
