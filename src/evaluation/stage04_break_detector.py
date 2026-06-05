from __future__ import annotations

import argparse
import json
import math
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT, project_relative_path


REPORT_VERSION = "stage04_wp1_break_detector_v1"
INDEX_ID = "STAGE04-WP1"
DEFAULT_ROLLING_WINDOW = 60
DEFAULT_MIN_PERIODS = 20
SHORT_VOL_WINDOW = 20
FORBIDDEN_REPORT_TERMS = (
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
)
BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "model_retrained": "no",
    "hmm_hsmm_training_changed": "no",
    "hazard_model_changed": "no",
    "final_holdout_consumed": "no",
    "decision_engine_output": "no",
    "duckdb_schema_changed": "no",
    "duckdb_committed": "no",
}
INPUT_TABLES = (
    "market_index_ohlcv",
    "market_breadth_daily",
    "sector_features",
    "walk_forward_state_cache",
)


@dataclass(frozen=True)
class BreakDetectorConfig:
    db_path: Path
    rolling_window: int = DEFAULT_ROLLING_WINDOW
    min_periods: int = DEFAULT_MIN_PERIODS


def _to_trade_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


def _numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def causal_rolling_zscore(
    series: pd.Series,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> pd.Series:
    values = _numeric(series)
    prior = values.shift(1)
    mean = prior.rolling(rolling_window, min_periods=min_periods).mean()
    std = prior.rolling(rolling_window, min_periods=min_periods).std(ddof=0)
    std = std.mask(std <= 0)
    return (values - mean) / std


def _status_from_stress(stress: pd.Series) -> pd.Series:
    out = pd.Series("normal", index=stress.index, dtype="object")
    out[stress.isna()] = "insufficient_history"
    out[stress >= 1.0] = "watch"
    out[stress >= 2.0] = "high"
    return out


def _stress_label(stress: float | int | None) -> str:
    if stress is None or pd.isna(stress):
        return "insufficient_history"
    value = float(stress)
    if value >= 2.0:
        return "high"
    if value >= 1.0:
        return "medium"
    return "normal"


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if hasattr(value, "isoformat") and value.__class__.__name__ in {"date", "datetime"}:
        return value.isoformat()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        if np.isnan(value) or np.isinf(value):
            return None
        return float(value)
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if pd.isna(value) if not isinstance(value, (list, tuple, dict, pd.Series, pd.DataFrame)) else False:
        return None
    return value


def _public_path(path: Path | str | None) -> str | None:
    if path is None:
        return None
    raw = Path(path)
    if not raw.is_absolute():
        return str(raw)
    return project_relative_path(raw)


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT count(*) AS n
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and int(row[0] or 0) > 0)


def _table_summary(con: duckdb.DuckDBPyConnection, table_name: str) -> dict[str, Any]:
    if not _table_exists(con, table_name):
        return {"exists": False, "row_count": 0, "min_trade_date": None, "max_trade_date": None}
    count = int(con.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])
    date_cols = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'main' AND table_name = ? AND column_name = 'trade_date'
        """,
        [table_name],
    ).fetchall()
    if not date_cols or count == 0:
        return {"exists": True, "row_count": count, "min_trade_date": None, "max_trade_date": None}
    row = con.execute(f"SELECT min(trade_date), max(trade_date) FROM {table_name}").fetchone()
    return {
        "exists": True,
        "row_count": count,
        "min_trade_date": _json_safe(row[0]) if row else None,
        "max_trade_date": _json_safe(row[1]) if row else None,
    }


def _read_table(con: duckdb.DuckDBPyConnection, table_name: str, columns: list[str] | None = None) -> pd.DataFrame:
    if not _table_exists(con, table_name):
        return pd.DataFrame()
    if columns is None:
        return con.execute(f"SELECT * FROM {table_name}").fetchdf()
    existing = {
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
    selected = [column for column in columns if column in existing]
    if not selected:
        return pd.DataFrame()
    column_sql = ", ".join(selected)
    return con.execute(f"SELECT {column_sql} FROM {table_name}").fetchdf()


def _choose_market_index(df: pd.DataFrame) -> str | None:
    if df.empty or "index_code" not in df.columns:
        return None
    codes = df["index_code"].astype(str).str.zfill(6)
    if (codes == "000300").any():
        return "000300"
    if (codes == "000001").any():
        return "000001"
    counts = codes.value_counts()
    return None if counts.empty else str(counts.index[0])


def build_market_volatility_component(
    market_index_ohlcv: pd.DataFrame,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> pd.DataFrame:
    if market_index_ohlcv.empty:
        return pd.DataFrame()
    data = market_index_ohlcv.copy()
    data["index_code"] = data["index_code"].astype(str).str.zfill(6)
    data["trade_date"] = _to_trade_date(data["trade_date"])
    data["close"] = _numeric(data["close"])
    index_code = _choose_market_index(data)
    if index_code is None:
        return pd.DataFrame()
    data = data[(data["index_code"] == index_code) & data["trade_date"].notna()].sort_values("trade_date")
    data = data.drop_duplicates("trade_date")
    data["market_return_1d"] = data["close"].pct_change()
    min_short = min(10, SHORT_VOL_WINDOW)
    data["short_volatility"] = data["market_return_1d"].rolling(SHORT_VOL_WINDOW, min_periods=min_short).std(ddof=0)
    data["market_volatility_z"] = causal_rolling_zscore(data["short_volatility"], rolling_window=rolling_window, min_periods=min_periods)
    stress = data["market_volatility_z"].clip(lower=0)
    return pd.DataFrame(
        {
            "trade_date": data["trade_date"],
            "market_index_code": index_code,
            "market_return_1d": data["market_return_1d"],
            "market_volatility_z": data["market_volatility_z"],
            "market_volatility_status": _status_from_stress(stress),
            "market_stress_score": stress,
        }
    )


def _choose_breadth_mode(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None
    if "breadth_mode" not in df.columns:
        return None
    modes = df["breadth_mode"].astype(str)
    if (modes == "full_market").any():
        return "full_market"
    if (modes == "local_sample").any():
        return "local_sample"
    counts = modes.value_counts()
    return None if counts.empty else str(counts.index[0])


def build_breadth_component(
    market_breadth_daily: pd.DataFrame,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
    min_coverage_ratio: float = 0.6,
) -> pd.DataFrame:
    if market_breadth_daily.empty:
        return pd.DataFrame()
    data = market_breadth_daily.copy()
    mode = _choose_breadth_mode(data)
    if mode is None:
        return pd.DataFrame()
    data = data[data["breadth_mode"].astype(str) == mode].copy()
    data["trade_date"] = _to_trade_date(data["trade_date"])
    data = data[data["trade_date"].notna()].sort_values("trade_date").drop_duplicates("trade_date")
    for column in ["up_ratio", "above_ma20_ratio", "amount_z_20d", "coverage_ratio"]:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = _numeric(data[column])

    data["breadth_up_ratio_z"] = causal_rolling_zscore(data["up_ratio"], rolling_window=rolling_window, min_periods=min_periods)
    data["breadth_above_ma20_z"] = causal_rolling_zscore(data["above_ma20_ratio"], rolling_window=rolling_window, min_periods=min_periods)
    data["breadth_amount_z"] = causal_rolling_zscore(data["amount_z_20d"], rolling_window=rolling_window, min_periods=min_periods)
    stress = pd.concat(
        [
            (-data["breadth_up_ratio_z"]).clip(lower=0),
            (-data["breadth_above_ma20_z"]).clip(lower=0),
            data["breadth_amount_z"].clip(lower=0),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    stress[stress.isna()] = np.nan
    coverage_low = data["coverage_ratio"].notna() & (data["coverage_ratio"] < min_coverage_ratio)
    status = _status_from_stress(stress)
    status[coverage_low] = "data_limited"
    stress[coverage_low] = np.nan
    return pd.DataFrame(
        {
            "trade_date": data["trade_date"],
            "breadth_mode": mode,
            "breadth_up_ratio_z": data["breadth_up_ratio_z"],
            "breadth_above_ma20_z": data["breadth_above_ma20_z"],
            "breadth_amount_z": data["breadth_amount_z"],
            "breadth_coverage_ratio": data["coverage_ratio"],
            "breadth_status": status,
            "breadth_stress_score": stress,
        }
    )


def build_sector_dispersion_component(
    sector_features: pd.DataFrame,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
    min_sector_count: int = 3,
) -> pd.DataFrame:
    if sector_features.empty or "trade_date" not in sector_features.columns:
        return pd.DataFrame()
    data = sector_features.copy()
    data["trade_date"] = _to_trade_date(data["trade_date"])
    data = data[data["trade_date"].notna()]
    if data.empty:
        return pd.DataFrame()
    for column in ["ret_1d", "ret_5d", "rs_20d", "drawdown_20d"]:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = _numeric(data[column])
    grouped = data.groupby("trade_date", as_index=False).agg(
        sector_count=("sector_id", "nunique"),
        sector_ret_1d_std=("ret_1d", "std"),
        sector_ret_5d_std=("ret_5d", "std"),
        sector_rs_20d_std=("rs_20d", "std"),
        sector_drawdown_20d_median=("drawdown_20d", "median"),
    )
    grouped = grouped.sort_values("trade_date")
    grouped["sector_dispersion_z"] = causal_rolling_zscore(
        grouped["sector_ret_1d_std"],
        rolling_window=rolling_window,
        min_periods=min_periods,
    )
    stress = grouped["sector_dispersion_z"].clip(lower=0)
    status = _status_from_stress(stress)
    sparse = grouped["sector_count"] < min_sector_count
    status[sparse] = "data_limited"
    stress[sparse] = np.nan
    grouped["sector_dispersion_status"] = status
    grouped["sector_stress_score"] = stress
    return grouped


def _entropy(row: pd.Series) -> float:
    probs = np.array([row.get("prob_trend_up"), row.get("prob_neutral"), row.get("prob_risk_off")], dtype=float)
    probs = probs[np.isfinite(probs) & (probs > 0)]
    if probs.size == 0:
        return np.nan
    return float(-(probs * np.log(probs)).sum() / np.log(3))


def build_hmm_confidence_component(
    walk_forward_state_cache: pd.DataFrame,
    *,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if walk_forward_state_cache.empty or "trade_date" not in walk_forward_state_cache.columns:
        return pd.DataFrame(), {"future_leaking_rows_excluded": 0}
    data = walk_forward_state_cache.copy()
    data["trade_date"] = _to_trade_date(data["trade_date"])
    if "max_observation_date_used" in data.columns:
        data["max_observation_date_used"] = _to_trade_date(data["max_observation_date_used"])
        valid = data["max_observation_date_used"].isna() | (data["max_observation_date_used"] <= data["trade_date"])
    else:
        valid = pd.Series(True, index=data.index)
    excluded = int((~valid).sum())
    data = data[valid & data["trade_date"].notna()].copy()
    if data.empty:
        return pd.DataFrame(), {"future_leaking_rows_excluded": excluded}
    prob_cols = ["prob_trend_up", "prob_neutral", "prob_risk_off"]
    for column in prob_cols:
        if column not in data.columns:
            data[column] = np.nan
        data[column] = _numeric(data[column])
    probs = data[prob_cols]
    sorted_probs = np.sort(probs.to_numpy(dtype=float), axis=1)
    data["hmm_max_prob"] = np.nanmax(sorted_probs, axis=1)
    data["hmm_margin"] = sorted_probs[:, -1] - sorted_probs[:, -2]
    data["hmm_entropy"] = data.apply(_entropy, axis=1)
    grouped = data.groupby("trade_date", as_index=False).agg(
        hmm_sector_count=("sector_id", "nunique"),
        hmm_max_prob_mean=("hmm_max_prob", "mean"),
        hmm_margin_mean=("hmm_margin", "mean"),
        hmm_entropy_mean=("hmm_entropy", "mean"),
    )
    grouped = grouped.sort_values("trade_date")
    grouped["hmm_margin_z"] = causal_rolling_zscore(grouped["hmm_margin_mean"], rolling_window=rolling_window, min_periods=min_periods)
    grouped["hmm_entropy_z"] = causal_rolling_zscore(grouped["hmm_entropy_mean"], rolling_window=rolling_window, min_periods=min_periods)
    stress = pd.concat(
        [
            (-grouped["hmm_margin_z"]).clip(lower=0),
            grouped["hmm_entropy_z"].clip(lower=0),
        ],
        axis=1,
    ).max(axis=1, skipna=True)
    stress[stress.isna()] = np.nan
    grouped["hmm_confidence_status"] = _status_from_stress(stress)
    grouped["hmm_stress_score"] = stress
    return grouped, {"future_leaking_rows_excluded": excluded}


def aggregate_break_warnings(components: list[pd.DataFrame]) -> pd.DataFrame:
    non_empty = [frame for frame in components if not frame.empty and "trade_date" in frame.columns]
    if not non_empty:
        return pd.DataFrame()
    result = non_empty[0].copy()
    for frame in non_empty[1:]:
        result = result.merge(frame, on="trade_date", how="outer")
    result = result.sort_values("trade_date").reset_index(drop=True)
    stress_columns = ["market_stress_score", "breadth_stress_score", "sector_stress_score", "hmm_stress_score"]
    for column in stress_columns:
        if column not in result.columns:
            result[column] = np.nan
    levels: list[str] = []
    available_counts: list[int] = []
    high_counts: list[int] = []
    medium_counts: list[int] = []
    component_labels: list[str] = []
    for row in result[stress_columns].itertuples(index=False):
        values = [float(value) for value in row if pd.notna(value)]
        available = len(values)
        high = sum(value >= 2.0 for value in values)
        medium = sum(1.0 <= value < 2.0 for value in values)
        if available < 2:
            level = "insufficient_data"
        elif high >= 2:
            level = "high"
        elif high >= 1 or medium >= 2:
            level = "elevated"
        elif medium >= 1:
            level = "watch"
        else:
            level = "normal"
        levels.append(level)
        available_counts.append(available)
        high_counts.append(high)
        medium_counts.append(medium)
        labels = []
        for name, value in zip(["market", "breadth", "sector", "hmm_confidence"], row, strict=False):
            label = _stress_label(None if pd.isna(value) else float(value))
            if label != "normal":
                labels.append(f"{name}:{label}")
        component_labels.append(";".join(labels))
    result["break_warning_level"] = levels
    result["available_component_count"] = available_counts
    result["high_stress_component_count"] = high_counts
    result["medium_stress_component_count"] = medium_counts
    result["component_stress_labels"] = component_labels
    return result


def _component_summary(name: str, frame: pd.DataFrame, score_column: str, status_column: str) -> dict[str, Any]:
    if frame.empty:
        return {"component": name, "rows": 0, "available_rows": 0, "latest_status": "unavailable", "available": False}
    available_rows = int(frame[score_column].notna().sum()) if score_column in frame.columns else 0
    latest_status = str(frame[status_column].dropna().iloc[-1]) if status_column in frame.columns and frame[status_column].notna().any() else "unavailable"
    return {
        "component": name,
        "rows": int(len(frame)),
        "available_rows": available_rows,
        "latest_status": latest_status,
        "available": available_rows > 0,
    }


def _latest_warning(result: pd.DataFrame) -> dict[str, Any] | None:
    if result.empty:
        return None
    row = result.sort_values("trade_date").iloc[-1]
    keys = [
        "trade_date",
        "break_warning_level",
        "available_component_count",
        "market_volatility_z",
        "market_return_1d",
        "market_volatility_status",
        "breadth_up_ratio_z",
        "breadth_above_ma20_z",
        "breadth_amount_z",
        "breadth_status",
        "sector_dispersion_z",
        "sector_dispersion_status",
        "hmm_confidence_status",
        "hmm_max_prob_mean",
        "hmm_margin_mean",
        "hmm_entropy_mean",
        "component_stress_labels",
    ]
    return {key: _json_safe(row.get(key)) for key in keys if key in row.index}


def _blocked_summary(reason: str, *, db_path: Path | None = None) -> dict[str, Any]:
    return {
        "status": "blocked",
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "boundary_flags": BOUNDARY_FLAGS,
        "input_table_summary": {},
        "component_availability_summary": {},
        "latest_break_warning": None,
        "warning_level_counts": {},
        "causal_sanity_summary": {
            "rolling_baseline_excludes_current_row": "yes",
            "future_rows_used": "no",
        },
        "data_quality_summary": {
            "db_available": "no",
            "db_path": _public_path(db_path),
        },
        "blocking_issues": [reason],
        "defer_reasons": ["local DuckDB inputs are unavailable"],
        "recommended_next_stage": "Provide local read-only inputs before Stage04-WP1 review.",
    }


def evaluate_break_detector(config: BreakDetectorConfig) -> tuple[dict[str, Any], pd.DataFrame]:
    db_path = config.db_path
    if not db_path.exists():
        return _blocked_summary("local DuckDB not found", db_path=db_path), pd.DataFrame()

    with duckdb.connect(str(db_path), read_only=True) as con:
        input_summary = {table: _table_summary(con, table) for table in INPUT_TABLES}
        market = build_market_volatility_component(
            _read_table(con, "market_index_ohlcv", ["index_code", "trade_date", "close"]),
            rolling_window=config.rolling_window,
            min_periods=config.min_periods,
        )
        breadth = build_breadth_component(
            _read_table(
                con,
                "market_breadth_daily",
                ["trade_date", "breadth_mode", "up_ratio", "above_ma20_ratio", "amount_z_20d", "coverage_ratio", "effective_count", "expected_count"],
            ),
            rolling_window=config.rolling_window,
            min_periods=config.min_periods,
        )
        sector = build_sector_dispersion_component(
            _read_table(con, "sector_features", ["sector_id", "trade_date", "ret_1d", "ret_5d", "rs_20d", "drawdown_20d"]),
            rolling_window=config.rolling_window,
            min_periods=config.min_periods,
        )
        hmm, hmm_causality = build_hmm_confidence_component(
            _read_table(
                con,
                "walk_forward_state_cache",
                [
                    "sector_id",
                    "trade_date",
                    "prob_trend_up",
                    "prob_neutral",
                    "prob_risk_off",
                    "max_observation_date_used",
                ],
            ),
            rolling_window=config.rolling_window,
            min_periods=config.min_periods,
        )

    result = aggregate_break_warnings([market, breadth, sector, hmm])
    component_summary = {
        "market_volatility": _component_summary("market_volatility", market, "market_stress_score", "market_volatility_status"),
        "breadth": _component_summary("breadth", breadth, "breadth_stress_score", "breadth_status"),
        "sector_dispersion": _component_summary("sector_dispersion", sector, "sector_stress_score", "sector_dispersion_status"),
        "hmm_confidence": _component_summary("hmm_confidence", hmm, "hmm_stress_score", "hmm_confidence_status"),
    }
    available_components = sum(1 for item in component_summary.values() if item["available"])
    blocking_issues: list[str] = []
    if result.empty:
        blocking_issues.append("no diagnostic rows could be produced")
    if available_components == 0:
        blocking_issues.append("no components have sufficient causal history")
    warning_counts = {} if result.empty else {str(k): int(v) for k, v in result["break_warning_level"].value_counts().sort_index().items()}
    missing_tables = [table for table, summary in input_summary.items() if not summary.get("exists")]
    unavailable_components = [name for name, summary in component_summary.items() if not summary["available"]]
    summary = {
        "status": "blocked" if blocking_issues else "pass",
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "boundary_flags": BOUNDARY_FLAGS,
        "input_table_summary": input_summary,
        "component_availability_summary": component_summary,
        "latest_break_warning": _latest_warning(result),
        "warning_level_counts": warning_counts,
        "causal_sanity_summary": {
            "rolling_window": int(config.rolling_window),
            "min_periods": int(config.min_periods),
            "rolling_baseline_excludes_current_row": "yes",
            "future_rows_used": "no",
            "hmm_future_rows_excluded": int(hmm_causality.get("future_leaking_rows_excluded", 0)),
        },
        "data_quality_summary": {
            "db_available": "yes",
            "db_path": _public_path(db_path),
            "missing_tables": missing_tables,
            "unavailable_components": unavailable_components,
            "diagnostic_rows": int(len(result)),
            "latest_trade_date": _json_safe(result["trade_date"].max()) if not result.empty else None,
        },
        "blocking_issues": blocking_issues,
        "defer_reasons": [
            "some components are unavailable or have insufficient causal history"
        ]
        if unavailable_components
        else [],
        "recommended_next_stage": "Use Stage04-WP1 diagnostics for prospective annotation review before any higher-cost break model.",
    }
    return summary, result


def render_markdown(summary: dict[str, Any], result: pd.DataFrame) -> str:
    latest = summary.get("latest_break_warning") or {}
    component_summary = summary.get("component_availability_summary", {})
    lines = [
        "# Stage04-WP1 Structural Break Diagnostic",
        "",
        f"- status: {summary.get('status')}",
        f"- report_version: {summary.get('report_version')}",
        f"- index_id: {summary.get('index_id')}",
        f"- latest_break_warning: {latest.get('break_warning_level') if latest else None}",
        f"- latest_trade_date: {latest.get('trade_date') if latest else None}",
        "",
        "## Boundary Flags",
    ]
    for key, value in summary["boundary_flags"].items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Component Availability"])
    for name, item in component_summary.items():
        lines.append(
            f"- {name}: available={item.get('available')} rows={item.get('rows')} "
            f"available_rows={item.get('available_rows')} latest_status={item.get('latest_status')}"
        )
    lines.extend(["", "## Warning Level Counts"])
    for level, count in (summary.get("warning_level_counts") or {}).items():
        lines.append(f"- {level}: {count}")
    lines.extend(["", "## Latest Diagnostic Snapshot"])
    if latest:
        for key, value in latest.items():
            lines.append(f"- {key}: {value}")
    else:
        lines.append("- none")
    lines.extend(["", "## Causal Sanity"])
    for key, value in (summary.get("causal_sanity_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    lines.extend(["", "## Data Quality"])
    for key, value in (summary.get("data_quality_summary") or {}).items():
        lines.append(f"- {key}: {value}")
    if summary.get("blocking_issues"):
        lines.extend(["", "## Blocking Issues"])
        for issue in summary["blocking_issues"]:
            lines.append(f"- {issue}")
    if summary.get("defer_reasons"):
        lines.extend(["", "## Defer Reasons"])
        for reason in summary["defer_reasons"]:
            lines.append(f"- {reason}")
    lines.extend(["", "## Recommended Next Stage", str(summary.get("recommended_next_stage", "")), ""])
    markdown = "\n".join(lines)
    _assert_no_forbidden_terms(summary, markdown)
    return markdown


def _assert_no_forbidden_terms(summary: dict[str, Any], markdown: str) -> None:
    payload = json.dumps(_json_safe(summary), ensure_ascii=False) + "\n" + markdown
    hits = [term for term in FORBIDDEN_REPORT_TERMS if term in payload]
    if hits:
        raise ValueError(f"Stage04-WP1 report contains forbidden terms: {sorted(set(hits))}")


def write_outputs(summary: dict[str, Any], result: pd.DataFrame, *, output: Path, summary_json: Path, sample_csv: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    sample_csv.parent.mkdir(parents=True, exist_ok=True)
    markdown = render_markdown(summary, result)
    output.write_text(markdown, encoding="utf-8")
    summary_json.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sample = result.tail(200).copy() if not result.empty else pd.DataFrame(columns=["trade_date", "break_warning_level", "available_component_count"])
    sample.to_csv(sample_csv, index=False)


def _default_output_paths(db_path: Path, output: str | None, summary_json: str | None, sample_csv: str | None) -> tuple[Path, Path, Path]:
    if output and summary_json and sample_csv:
        return Path(output), Path(summary_json), Path(sample_csv)
    if not db_path.exists():
        tmp = Path(tempfile.mkdtemp(prefix="stage04_break_detector."))
        return (
            Path(output) if output else tmp / "stage04_wp1_break_detector_report.md",
            Path(summary_json) if summary_json else tmp / "stage04_wp1_break_detector_report.json",
            Path(sample_csv) if sample_csv else tmp / "stage04_wp1_break_detector_sample.csv",
        )
    report_dir = Path("reports/stage04")
    return (
        Path(output) if output else report_dir / "stage04_wp1_break_detector_report.md",
        Path(summary_json) if summary_json else report_dir / "stage04_wp1_break_detector_report.json",
        Path(sample_csv) if sample_csv else report_dir / "stage04_wp1_break_detector_sample.csv",
    )


def run_from_paths(
    *,
    db: Path,
    output: Path,
    summary_json: Path,
    sample_csv: Path,
    rolling_window: int = DEFAULT_ROLLING_WINDOW,
    min_periods: int = DEFAULT_MIN_PERIODS,
) -> dict[str, Any]:
    summary, result = evaluate_break_detector(
        BreakDetectorConfig(db_path=db, rolling_window=rolling_window, min_periods=min_periods)
    )
    write_outputs(summary, result, output=output, summary_json=summary_json, sample_csv=sample_csv)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage04-WP1 low-cost structural break diagnostic")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--output", default=None)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--sample-csv", default=None)
    parser.add_argument("--rolling-window", type=int, default=DEFAULT_ROLLING_WINDOW)
    parser.add_argument("--min-periods", type=int, default=DEFAULT_MIN_PERIODS)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    db_path = Path(args.db)
    output, summary_json, sample_csv = _default_output_paths(db_path, args.output, args.summary_json, args.sample_csv)
    summary = run_from_paths(
        db=db_path,
        output=output,
        summary_json=summary_json,
        sample_csv=sample_csv,
        rolling_window=args.rolling_window,
        min_periods=args.min_periods,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
