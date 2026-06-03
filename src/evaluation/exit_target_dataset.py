"""Stage03R WP1 causal exit target dataset builder.

This module builds target labels only. It does not fetch market data, train
models, calibrate probabilities, or implement any decision engine.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import duckdb
import pandas as pd


INDEX_ID = "STAGE03R-WP1"
TARGET_DEFINITION_VERSION = "exit_target_dataset_v1"
DEFAULT_HORIZONS = (1, 3, 5, 10, 20)
OBSERVED_POSITIVE = "observed_positive"
OBSERVED_NEGATIVE = "observed_negative"
RIGHT_CENSORED_BY_RUN_END = "right_censored_by_run_end"
RIGHT_CENSORED_BY_CUTOFF = "right_censored_by_cutoff"
UNKNOWN_MISSING_STATE_SEQUENCE = "unknown_due_to_missing_state_sequence"
UNKNOWN_MISSING_CALENDAR = "unknown_due_to_missing_calendar"
REQUIRED_SOURCE_TABLES = ("hsmm_lifecycle_ui_daily", "hsmm_state_daily")
OPTIONAL_FEATURE_COLUMNS = (
    "hmm_state_label",
    "hmm_state_confidence",
    "hmm_state_entropy",
    "hmm_posterior_margin",
    "volatility_20d",
    "rs_20d",
    "drawdown_20d",
    "breadth_feature",
    "liquidity_feature",
    "market_regime_label",
)
TARGET_COLUMNS = (
    "target_dataset_id",
    "run_id",
    "source_run_id",
    "sector_code",
    "sector_id",
    "trade_date",
    "state_source",
    "state_label",
    "state_id",
    "state_age",
    "state_phase",
    "duration_percentile",
    "duration_percentile_status",
    "duration_tail_status",
    "horizon_days",
    "exit_within_horizon",
    "next_state_label_realized",
    "target_observation_end_date",
    "realized_exit_date",
    "censoring_status",
    "sample_weight",
    "target_definition_version",
    "profile_mode",
    "profile_cutoff_date",
    "state_date_policy",
    "feature_cutoff_date",
    "max_feature_date_used",
    "feature_leakage_violation",
    "purge_group_id",
    "embargo_until_date",
    "created_at",
    *OPTIONAL_FEATURE_COLUMNS,
)
FEATURE_ALIASES: Mapping[str, tuple[str, ...]] = {
    "hmm_state_label": ("hmm_state_label",),
    "hmm_state_confidence": ("hmm_state_confidence", "state_confidence", "confidence"),
    "hmm_state_entropy": ("hmm_state_entropy", "posterior_entropy"),
    "hmm_posterior_margin": ("hmm_posterior_margin", "posterior_margin"),
    "volatility_20d": ("volatility_20d", "vol_20d"),
    "rs_20d": ("rs_20d",),
    "drawdown_20d": ("drawdown_20d",),
    "breadth_feature": ("breadth_feature", "above_ma20_ratio", "up_ratio"),
    "liquidity_feature": ("liquidity_feature", "amount_z_20d", "amount_total"),
    "market_regime_label": ("market_regime_label",),
}
STATE_AGE_ALIASES = (
    "state_age",
    "display_state_age_days",
    "state_age_days",
    "state_age_days_by_label",
    "label_state_age_days",
    "duration_model_age_days",
)
FEATURE_CUTOFF_ALIASES = (
    "feature_cutoff_date",
    "max_feature_date_used",
    "max_observation_date_used",
    "train_end_date",
)
MAX_FEATURE_DATE_ALIASES = (
    "max_feature_date_used",
    "max_observation_date_used",
    "feature_cutoff_date",
    "train_end_date",
)
IN_SAMPLE_SOURCE_MARKERS = ("in_sample", "insample")


@dataclass
class ExitTargetDatasetResult:
    status: str
    report_status: str
    run_id: str | None
    dataset: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=TARGET_COLUMNS))
    summary: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def quote_identifier(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT COUNT(*)
        FROM information_schema.tables
        WHERE table_schema = 'main' AND table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(row and row[0])


def table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not table_exists(con, table_name):
        return []
    return [str(row[1]) for row in con.execute(f"PRAGMA table_info({quote_identifier(table_name)})").fetchall()]


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).isoformat()
    if hasattr(value, "item"):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(value)


def _date_str(value: Any) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(pd.Timestamp(value).date())


def _first_existing(columns: Sequence[str] | set[str], candidates: Sequence[str]) -> str | None:
    column_set = set(columns)
    for candidate in candidates:
        if candidate in column_set:
            return candidate
    return None


def _first_value(row: Mapping[str, Any], candidates: Sequence[str], default: Any = None) -> Any:
    for candidate in candidates:
        if candidate in row:
            value = row[candidate]
            try:
                if pd.isna(value):
                    continue
            except TypeError:
                pass
            return value
    return default


def _normalize_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None:
        return None
    timestamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(timestamp):
        return None
    return pd.Timestamp(timestamp).normalize()


def _empty_dataset() -> pd.DataFrame:
    return pd.DataFrame(columns=TARGET_COLUMNS)


def _target_dataset_id(run_id: str | None, source_run_id: str | None, profile_cutoff_date: str | None, horizons: Sequence[int]) -> str:
    seed = "|".join(
        [
            TARGET_DEFINITION_VERSION,
            str(run_id or "unknown_run"),
            str(source_run_id or run_id or "unknown_source_run"),
            str(profile_cutoff_date or "unknown_cutoff"),
            ",".join(str(int(horizon)) for horizon in horizons),
        ]
    )
    return f"{TARGET_DEFINITION_VERSION}:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def _age_bucket(value: Any) -> str:
    try:
        age = int(value)
    except Exception:
        return "unknown"
    if 1 <= age <= 3:
        return "1-3"
    if 4 <= age <= 7:
        return "4-7"
    if 8 <= age <= 14:
        return "8-14"
    if age >= 15:
        return "15+"
    return "unknown"


def _coerce_exit_value(value: Any) -> int | None:
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    if value is None:
        return None
    return int(value)


def _missing_feature_columns(data: pd.DataFrame) -> list[str]:
    missing: list[str] = []
    columns = set(data.columns)
    for output_col, aliases in FEATURE_ALIASES.items():
        if output_col in columns:
            continue
        if not any(alias in columns for alias in aliases):
            missing.append(output_col)
    return missing


def _optional_feature_value(row: Mapping[str, Any], output_col: str) -> Any:
    return _first_value(row, FEATURE_ALIASES[output_col], None)


def _duration_tail_status(row: Mapping[str, Any], horizon: int) -> Any:
    horizon_col = f"duration_tail_status_{int(horizon)}d"
    return _first_value(row, (horizon_col, "duration_tail_status"), "unavailable")


def _profile_cutoff_for_row(row: Mapping[str, Any], default_cutoff: pd.Timestamp | None) -> pd.Timestamp | None:
    return _normalize_timestamp(_first_value(row, ("profile_cutoff_date",), default_cutoff))


def _feature_leakage(row: Mapping[str, Any], trade_date: pd.Timestamp) -> tuple[Any, Any, bool]:
    feature_cutoff = _normalize_timestamp(_first_value(row, FEATURE_CUTOFF_ALIASES, trade_date))
    max_feature_date = _normalize_timestamp(_first_value(row, MAX_FEATURE_DATE_ALIASES, feature_cutoff or trade_date))
    cutoff_violation = feature_cutoff is not None and feature_cutoff > trade_date
    max_feature_violation = max_feature_date is not None and max_feature_date > trade_date
    return feature_cutoff, max_feature_date, bool(cutoff_violation or max_feature_violation)


def _filter_default_causal_sources(data: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if "state_source" not in data.columns:
        return data.copy(), ["state_source missing; dataset source remains unproven"]
    source = data["state_source"].fillna("").astype(str).str.lower()
    in_sample = source.apply(lambda value: any(marker in value for marker in IN_SAMPLE_SOURCE_MARKERS))
    if not in_sample.any():
        return data.copy(), []
    filtered = data.loc[~in_sample].copy()
    return filtered, [f"removed {int(in_sample.sum())} in-sample state_source rows from default causal target dataset"]


def build_exit_target_dataset(
    states: pd.DataFrame,
    horizons: Sequence[int] = DEFAULT_HORIZONS,
    *,
    run_id: str | None = None,
    profile_cutoff_date: str | pd.Timestamp | None = None,
    target_dataset_id: str | None = None,
    created_at: datetime | pd.Timestamp | None = None,
    filter_in_sample_sources: bool = True,
    source_tables_used: Sequence[str] = (),
    report_status: str | None = None,
) -> ExitTargetDatasetResult:
    """Build horizon-specific exit target rows from causal lifecycle states."""
    warnings: list[str] = []
    if states.empty:
        summary = summarize_exit_target_dataset(
            _empty_dataset(),
            run_id=run_id,
            source_tables_used=source_tables_used,
            missing_feature_columns=list(OPTIONAL_FEATURE_COLUMNS),
            warnings=["no source state rows available"],
            report_status=report_status or "partial_missing_source",
        )
        return ExitTargetDatasetResult("partial", report_status or "partial_missing_source", run_id, _empty_dataset(), summary, warnings)

    work = states.copy()
    if filter_in_sample_sources:
        work, source_warnings = _filter_default_causal_sources(work)
        warnings.extend(source_warnings)
    if work.empty:
        summary = summarize_exit_target_dataset(
            _empty_dataset(),
            run_id=run_id,
            source_tables_used=source_tables_used,
            missing_feature_columns=_missing_feature_columns(states),
            warnings=warnings,
            report_status=report_status or "partial_only_in_sample_source",
        )
        return ExitTargetDatasetResult("partial", report_status or "partial_only_in_sample_source", run_id, _empty_dataset(), summary, warnings)

    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    if "sector_code" not in work.columns and "sector_id" in work.columns:
        work["sector_code"] = work["sector_id"].astype(str)
    if "sector_id" not in work.columns and "sector_code" in work.columns:
        work["sector_id"] = work["sector_code"].astype(str)
    if "run_id" not in work.columns:
        work["run_id"] = run_id or "unknown_run"
    if "source_run_id" not in work.columns:
        work["source_run_id"] = work["run_id"]
    if "profile_mode" not in work.columns:
        work["profile_mode"] = "retrospective"
    if "state_date_policy" not in work.columns:
        work["state_date_policy"] = "full_run"

    if run_id is not None:
        run_id_value = run_id
    elif not work["run_id"].dropna().empty:
        run_id_value = str(work["run_id"].dropna().iloc[0])
    else:
        run_id_value = None
    default_cutoff = _normalize_timestamp(profile_cutoff_date)
    if default_cutoff is None:
        default_cutoff = _normalize_timestamp(work["profile_cutoff_date"].max()) if "profile_cutoff_date" in work.columns else None
    if default_cutoff is None:
        default_cutoff = _normalize_timestamp(work["trade_date"].max())
    source_run_id_value = (
        str(work["source_run_id"].dropna().iloc[0])
        if "source_run_id" in work.columns and not work["source_run_id"].dropna().empty
        else run_id_value
    )
    dataset_id = target_dataset_id or _target_dataset_id(run_id_value, source_run_id_value, _date_str(default_cutoff), horizons)
    created_ts = pd.Timestamp(created_at or datetime.now(UTC).replace(microsecond=0))
    missing_feature_columns = _missing_feature_columns(work)

    rows: list[dict[str, Any]] = []
    for sector_code, group in work.sort_values(["sector_code", "trade_date"]).groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        dates = pd.to_datetime(group["trade_date"], errors="coerce").dt.normalize()
        run_end = _normalize_timestamp(dates.max())
        for idx, source_row in group.iterrows():
            row = source_row.to_dict()
            trade_date = _normalize_timestamp(row.get("trade_date"))
            state_label = row.get("state_label")
            state_missing = trade_date is None or state_label is None or pd.isna(state_label)

            next_state_label = None
            realized_exit_date: pd.Timestamp | None = None
            exit_offset: int | None = None
            if not state_missing:
                current_label = str(state_label)
                for future_idx in range(idx + 1, len(group)):
                    future_label = group.loc[future_idx, "state_label"] if "state_label" in group.columns else None
                    future_date = _normalize_timestamp(group.loc[future_idx, "trade_date"])
                    if future_date is None or future_label is None or pd.isna(future_label):
                        continue
                    if str(future_label) != current_label:
                        next_state_label = str(future_label)
                        realized_exit_date = future_date
                        exit_offset = int(future_idx - idx)
                        break

            for horizon in horizons:
                horizon_int = int(horizon)
                horizon_end: pd.Timestamp | None = None
                if trade_date is not None and idx + horizon_int < len(dates):
                    horizon_end = _normalize_timestamp(dates.iloc[idx + horizon_int])
                row_cutoff = _profile_cutoff_for_row(row, default_cutoff)
                feature_cutoff, max_feature_date, leakage = (
                    (None, None, False)
                    if trade_date is None
                    else _feature_leakage(row, trade_date)
                )

                if state_missing:
                    status = UNKNOWN_MISSING_STATE_SEQUENCE
                    exit_value: int | None = None
                    observation_end = trade_date
                elif horizon_end is None and run_end is None:
                    status = UNKNOWN_MISSING_CALENDAR
                    exit_value = None
                    observation_end = trade_date
                else:
                    full_horizon_observable = horizon_end is not None
                    nominal_end = horizon_end or run_end
                    observation_end = nominal_end
                    cutoff_blocks_horizon = False
                    if row_cutoff is not None and observation_end is not None and row_cutoff < observation_end:
                        observation_end = row_cutoff
                        cutoff_blocks_horizon = True

                    positive_observed = (
                        exit_offset is not None
                        and exit_offset <= horizon_int
                        and realized_exit_date is not None
                        and observation_end is not None
                        and realized_exit_date <= observation_end
                    )
                    if positive_observed:
                        status = OBSERVED_POSITIVE
                        exit_value = 1
                    elif full_horizon_observable and not cutoff_blocks_horizon:
                        status = OBSERVED_NEGATIVE
                        exit_value = 0
                    elif cutoff_blocks_horizon:
                        status = RIGHT_CENSORED_BY_CUTOFF
                        exit_value = None
                    else:
                        status = RIGHT_CENSORED_BY_RUN_END
                        exit_value = None

                target_observation_end_date = _date_str(observation_end)
                base: dict[str, Any] = {
                    "target_dataset_id": dataset_id,
                    "run_id": row.get("run_id", run_id_value),
                    "source_run_id": row.get("source_run_id", row.get("run_id", run_id_value)),
                    "sector_code": str(sector_code),
                    "sector_id": row.get("sector_id", sector_code),
                    "trade_date": _date_str(trade_date),
                    "state_source": row.get("state_source", "unknown_due_to_missing_metadata"),
                    "state_label": None if state_label is None or pd.isna(state_label) else str(state_label),
                    "state_id": row.get("state_id"),
                    "state_age": _first_value(row, STATE_AGE_ALIASES),
                    "state_phase": row.get("state_phase", "unknown"),
                    "duration_percentile": _first_value(row, ("duration_percentile", "duration_percentile_display")),
                    "duration_percentile_status": _first_value(row, ("duration_percentile_status",), "available"),
                    "duration_tail_status": _duration_tail_status(row, horizon_int),
                    "horizon_days": horizon_int,
                    "exit_within_horizon": exit_value,
                    "next_state_label_realized": next_state_label,
                    "target_observation_end_date": target_observation_end_date,
                    "realized_exit_date": _date_str(realized_exit_date),
                    "censoring_status": status,
                    "sample_weight": 1.0 if status in {OBSERVED_POSITIVE, OBSERVED_NEGATIVE} else 0.0,
                    "target_definition_version": TARGET_DEFINITION_VERSION,
                    "profile_mode": row.get("profile_mode", "retrospective"),
                    "profile_cutoff_date": _date_str(row_cutoff),
                    "state_date_policy": row.get("state_date_policy", "full_run"),
                    "feature_cutoff_date": _date_str(feature_cutoff),
                    "max_feature_date_used": _date_str(max_feature_date),
                    "feature_leakage_violation": bool(leakage),
                    "purge_group_id": f"{row.get('source_run_id', row.get('run_id', run_id_value))}:{sector_code}:{_date_str(trade_date)}",
                    "embargo_until_date": target_observation_end_date or _date_str(trade_date),
                    "created_at": created_ts.isoformat(),
                }
                for output_col in OPTIONAL_FEATURE_COLUMNS:
                    base[output_col] = _optional_feature_value(row, output_col)
                rows.append(base)

    dataset = pd.DataFrame(rows, columns=TARGET_COLUMNS)
    summary = summarize_exit_target_dataset(
        dataset,
        run_id=run_id_value,
        source_tables_used=source_tables_used,
        missing_feature_columns=missing_feature_columns,
        warnings=warnings,
        report_status=report_status or ("pass" if not dataset.empty else "partial_missing_source"),
    )
    return ExitTargetDatasetResult(summary["status"], summary["report_status"], run_id_value, dataset, summary, warnings)


def summarize_exit_target_dataset(
    dataset: pd.DataFrame,
    *,
    run_id: str | None,
    source_tables_used: Sequence[str],
    missing_feature_columns: Sequence[str],
    warnings: Sequence[str] = (),
    report_status: str = "pass",
) -> dict[str, Any]:
    if dataset.empty:
        row_count = 0
        status = "partial" if str(report_status).startswith("partial") else "fail"
    else:
        row_count = int(len(dataset))
        status = "pass" if report_status == "pass" else "partial"

    status_counts = (
        dataset["censoring_status"].value_counts(dropna=False).sort_index().to_dict()
        if "censoring_status" in dataset.columns and not dataset.empty
        else {}
    )
    observed_positive_count = int(status_counts.get(OBSERVED_POSITIVE, 0))
    observed_negative_count = int(status_counts.get(OBSERVED_NEGATIVE, 0))
    right_censored_count = int(
        status_counts.get(RIGHT_CENSORED_BY_RUN_END, 0) + status_counts.get(RIGHT_CENSORED_BY_CUTOFF, 0)
    )

    if dataset.empty:
        state_label_x_horizon_support: list[dict[str, Any]] = []
        age_bucket_x_horizon_support: list[dict[str, Any]] = []
    else:
        work = dataset.copy()
        work["age_bucket"] = work["state_age"].map(_age_bucket)
        state_label_x_horizon_support = _support_records(work, ["state_label", "horizon_days"])
        age_bucket_x_horizon_support = _support_records(work, ["age_bucket", "horizon_days"])

    embargo_ok = False
    if not dataset.empty and {"purge_group_id", "embargo_until_date", "target_observation_end_date"}.issubset(dataset.columns):
        embargo = pd.to_datetime(dataset["embargo_until_date"], errors="coerce")
        target_end = pd.to_datetime(dataset["target_observation_end_date"], errors="coerce")
        embargo_ok = bool(dataset["purge_group_id"].notna().all() and ((embargo >= target_end) | target_end.isna()).all())

    return {
        "wp": INDEX_ID,
        "status": status,
        "report_status": report_status,
        "run_id": run_id,
        "source_tables_used": list(source_tables_used),
        "row_count": row_count,
        "sector_count": int(dataset["sector_code"].nunique()) if not dataset.empty and "sector_code" in dataset else 0,
        "trade_date_min": _date_str(dataset["trade_date"].min()) if not dataset.empty and "trade_date" in dataset else None,
        "trade_date_max": _date_str(dataset["trade_date"].max()) if not dataset.empty and "trade_date" in dataset else None,
        "horizons": sorted([int(value) for value in dataset["horizon_days"].dropna().unique().tolist()]) if not dataset.empty else [],
        "censoring_status_counts": {str(k): int(v) for k, v in status_counts.items()},
        "state_label_counts": (
            {str(k): int(v) for k, v in dataset["state_label"].value_counts(dropna=False).sort_index().to_dict().items()}
            if not dataset.empty and "state_label" in dataset
            else {}
        ),
        "state_label_x_horizon_support": state_label_x_horizon_support,
        "age_bucket_x_horizon_support": age_bucket_x_horizon_support,
        "missing_feature_columns": sorted(set(missing_feature_columns)),
        "feature_leakage_violation_count": int(dataset["feature_leakage_violation"].sum()) if not dataset.empty else 0,
        "right_censored_count": right_censored_count,
        "observed_positive_count": observed_positive_count,
        "observed_negative_count": observed_negative_count,
        "target_definition_version": TARGET_DEFINITION_VERSION,
        "purge_embargo_policy_present": embargo_ok,
        "purge_embargo_policy": "Later model splits must purge overlapping horizons and embargo rows through embargo_until_date.",
        "warnings": list(warnings),
        "external_data_fetch": "no",
        "training_algorithm_modified": "no",
        "DuckDB_committed": "no",
    }


def _support_records(data: pd.DataFrame, group_cols: list[str]) -> list[dict[str, Any]]:
    grouped = (
        data.groupby(group_cols, dropna=False)
        .agg(
            row_count=("censoring_status", "size"),
            observed_positive_count=("censoring_status", lambda s: int((s == OBSERVED_POSITIVE).sum())),
            observed_negative_count=("censoring_status", lambda s: int((s == OBSERVED_NEGATIVE).sum())),
            right_censored_count=(
                "censoring_status",
                lambda s: int(s.isin([RIGHT_CENSORED_BY_RUN_END, RIGHT_CENSORED_BY_CUTOFF]).sum()),
            ),
        )
        .reset_index()
        .sort_values(group_cols)
    )
    return [
        {
            key: (None if pd.isna(row[key]) else row[key])
            for key in [*group_cols, "row_count", "observed_positive_count", "observed_negative_count", "right_censored_count"]
        }
        for _, row in grouped.iterrows()
    ]


def _inspect_tables(con: duckdb.DuckDBPyConnection) -> dict[str, dict[str, Any]]:
    tables = [
        "hsmm_lifecycle_ui_daily",
        "hsmm_state_daily",
        "hsmm_lifecycle_profile_metadata",
        "hsmm_display_label_episodes",
        "sector_features",
        "sector_state_daily",
        "hsmm_model_runs",
    ]
    out: dict[str, dict[str, Any]] = {}
    for table in tables:
        if not table_exists(con, table):
            out[table] = {"present": False, "row_count": None, "columns": []}
            continue
        cols = table_columns(con, table)
        count = int(con.execute(f"SELECT COUNT(*) FROM {quote_identifier(table)}").fetchone()[0])
        out[table] = {"present": True, "row_count": count, "columns": cols}
    return out


def _resolve_latest_run_id(con: duckdb.DuckDBPyConnection) -> str | None:
    for table in ("hsmm_lifecycle_ui_daily", "hsmm_state_daily", "hsmm_model_runs"):
        if not table_exists(con, table) or "run_id" not in table_columns(con, table):
            continue
        columns = set(table_columns(con, table))
        order_terms = [
            f"MAX({quote_identifier(column)}) DESC NULLS LAST"
            for column in ("created_at", "profile_cutoff_date", "trade_date")
            if column in columns
        ]
        if table == "hsmm_model_runs" and "run_status" in columns:
            where = "WHERE run_status IS NULL OR run_status = 'completed'"
        else:
            where = ""
        order_by = ", ".join([*order_terms, "COUNT(*) DESC", "run_id DESC"])
        row = con.execute(
            f"""
            SELECT run_id
            FROM {quote_identifier(table)}
            {where}
            GROUP BY run_id
            ORDER BY {order_by}
            LIMIT 1
            """
        ).fetchone()
        if row and row[0] is not None:
            return str(row[0])
    return None


def _read_table_for_run(con: duckdb.DuckDBPyConnection, table_name: str, run_id: str) -> pd.DataFrame:
    if not table_exists(con, table_name) or "run_id" not in table_columns(con, table_name):
        return pd.DataFrame()
    return con.execute(
        f"SELECT * FROM {quote_identifier(table_name)} WHERE run_id = ? ORDER BY sector_code, trade_date",
        [run_id],
    ).fetchdf()


def _select_lifecycle_profile(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    work = rows.copy()
    if "profile_cutoff_date" in work.columns:
        work["profile_cutoff_date"] = pd.to_datetime(work["profile_cutoff_date"], errors="coerce")
        max_cutoff = work["profile_cutoff_date"].max()
        if pd.notna(max_cutoff):
            work = work[work["profile_cutoff_date"].eq(max_cutoff)].copy()
    if "profile_mode" in work.columns and work["profile_mode"].astype(str).eq("latest_asof").any():
        work = work[work["profile_mode"].astype(str).eq("latest_asof")].copy()
    if "state_date_policy" in work.columns and work["state_date_policy"].astype(str).eq("cutoff_only").any():
        work = work[work["state_date_policy"].astype(str).eq("cutoff_only")].copy()
    return work.sort_values(["sector_code", "trade_date"]).drop_duplicates(["sector_code", "trade_date"], keep="last")


def _merge_hsmm_state_context(lifecycle: pd.DataFrame, hsmm_states: pd.DataFrame) -> pd.DataFrame:
    if lifecycle.empty or hsmm_states.empty:
        return lifecycle
    merge_cols = ["sector_code", "trade_date"]
    for df in (lifecycle, hsmm_states):
        df["trade_date"] = pd.to_datetime(df["trade_date"], errors="coerce")
    state_cols = [
        col
        for col in [
            "sector_code",
            "trade_date",
            "state_id",
            "state_age_days",
            "display_state_age_days",
            "duration_percentile",
            "duration_percentile_status",
            "duration_tail_status",
            "max_observation_date_used",
            "state_source",
            "confidence",
        ]
        if col in hsmm_states.columns
    ]
    if len(state_cols) <= len(merge_cols):
        return lifecycle
    state_context = hsmm_states[state_cols].drop_duplicates(merge_cols, keep="last")
    merged = lifecycle.merge(state_context, on=merge_cols, how="left", suffixes=("", "_hsmm_state"))
    for col in ["state_id", "duration_percentile", "duration_percentile_status", "duration_tail_status", "max_observation_date_used", "confidence"]:
        alt = f"{col}_hsmm_state"
        if alt in merged.columns:
            if col not in merged.columns:
                merged[col] = merged[alt]
            else:
                merged[col] = merged[col].combine_first(merged[alt])
            merged = merged.drop(columns=[alt])
    if "state_source_hsmm_state" in merged.columns:
        if "state_source" not in merged.columns:
            merged["state_source"] = merged["state_source_hsmm_state"]
        else:
            merged["state_source"] = merged["state_source"].combine_first(merged["state_source_hsmm_state"])
        merged = merged.drop(columns=["state_source_hsmm_state"])
    return merged


def _merge_optional_sector_features(con: duckdb.DuckDBPyConnection, states: pd.DataFrame) -> pd.DataFrame:
    if states.empty or not table_exists(con, "sector_features"):
        return states
    columns = set(table_columns(con, "sector_features"))
    wanted = [col for col in ("sector_id", "trade_date", "vol_20d", "rs_20d", "drawdown_20d", "amount_z_20d") if col in columns]
    if {"sector_id", "trade_date"} - set(wanted):
        return states
    features = con.execute(
        f"SELECT {', '.join(quote_identifier(col) for col in wanted)} FROM sector_features"
    ).fetchdf()
    if features.empty:
        return states
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce")
    states = states.copy()
    states["trade_date"] = pd.to_datetime(states["trade_date"], errors="coerce")
    if "sector_id" not in states.columns and "sector_code" in states.columns:
        states["sector_id"] = states["sector_code"].astype(str)
    features = features.rename(columns={"vol_20d": "volatility_20d", "amount_z_20d": "liquidity_feature"})
    features = features.sort_values(["sector_id", "trade_date"]).drop_duplicates(["sector_id", "trade_date"], keep="last")
    return states.merge(features, on=["sector_id", "trade_date"], how="left")


def load_source_states(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, list[str], list[str]]:
    warnings: list[str] = []
    source_tables_used: list[str] = []
    lifecycle = _select_lifecycle_profile(_read_table_for_run(con, "hsmm_lifecycle_ui_daily", run_id))
    if not lifecycle.empty:
        source_tables_used.append("hsmm_lifecycle_ui_daily")
        source_run_ids = lifecycle.get("source_run_id", pd.Series(dtype=object)).dropna().astype(str).unique().tolist()
        hsmm_run_id = source_run_ids[0] if source_run_ids else run_id
        hsmm_states = _read_table_for_run(con, "hsmm_state_daily", hsmm_run_id)
        if not hsmm_states.empty:
            source_tables_used.append("hsmm_state_daily")
            lifecycle = _merge_hsmm_state_context(lifecycle, hsmm_states)
        lifecycle = _merge_optional_sector_features(con, lifecycle)
        if "sector_features" in _inspect_tables(con) and table_exists(con, "sector_features"):
            source_tables_used.append("sector_features")
        return lifecycle, source_tables_used, warnings

    hsmm_states = _read_table_for_run(con, "hsmm_state_daily", run_id)
    if not hsmm_states.empty:
        source_tables_used.append("hsmm_state_daily")
        hsmm_states = _merge_optional_sector_features(con, hsmm_states)
        if table_exists(con, "sector_features"):
            source_tables_used.append("sector_features")
        return hsmm_states, source_tables_used, warnings

    warnings.append("missing required lifecycle/state source rows for run_id")
    return pd.DataFrame(), source_tables_used, warnings


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP1 Exit Target Dataset v1 Report",
        "",
        f"status: {summary.get('status')}",
        f"report_status: {summary.get('report_status')}",
        f"run_id: {summary.get('run_id')}",
        f"target_definition_version: {summary.get('target_definition_version')}",
        "",
        "## Dataset",
        "",
        f"- source_tables_used: {summary.get('source_tables_used')}",
        f"- row_count: {summary.get('row_count')}",
        f"- sector_count: {summary.get('sector_count')}",
        f"- trade_date_min: {summary.get('trade_date_min')}",
        f"- trade_date_max: {summary.get('trade_date_max')}",
        f"- horizons: {summary.get('horizons')}",
        f"- censoring_status_counts: {summary.get('censoring_status_counts')}",
        f"- state_label_counts: {summary.get('state_label_counts')}",
        f"- missing_feature_columns: {summary.get('missing_feature_columns')}",
        f"- feature_leakage_violation_count: {summary.get('feature_leakage_violation_count')}",
        f"- right_censored_count: {summary.get('right_censored_count')}",
        f"- observed_positive_count: {summary.get('observed_positive_count')}",
        f"- observed_negative_count: {summary.get('observed_negative_count')}",
        f"- purge_embargo_policy_present: {str(summary.get('purge_embargo_policy_present')).lower()}",
        "",
        "## State Label x Horizon Support",
        "",
        "```json",
        json.dumps(summary.get("state_label_x_horizon_support", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Age Bucket x Horizon Support",
        "",
        "```json",
        json.dumps(summary.get("age_bucket_x_horizon_support", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Purge / Embargo Policy",
        "",
        str(summary.get("purge_embargo_policy")),
        "",
        "## Warnings",
        "",
    ]
    warnings = summary.get("warnings") or []
    if warnings:
        lines.extend([f"- {warning}" for warning in warnings])
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Boundary Confirmation",
            "",
            f"- external_data_fetch: {summary.get('external_data_fetch')}",
            f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
            f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
        ]
    )
    return "\n".join(lines) + "\n"


def _write_outputs(
    summary: Mapping[str, Any],
    dataset: pd.DataFrame,
    output: Path,
    summary_json: Path,
    dataset_csv: Path | None,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    if dataset_csv is not None:
        dataset_csv.parent.mkdir(parents=True, exist_ok=True)
        dataset.head(1000).to_csv(dataset_csv, index=False)


def partial_summary(
    report_status: str,
    *,
    run_id: str | None,
    warning: str,
    source_tables_used: Sequence[str] = (),
) -> dict[str, Any]:
    return summarize_exit_target_dataset(
        _empty_dataset(),
        run_id=run_id,
        source_tables_used=source_tables_used,
        missing_feature_columns=list(OPTIONAL_FEATURE_COLUMNS),
        warnings=[warning],
        report_status=report_status,
    )


def run_cli(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    output = Path(args.output)
    summary_json = Path(args.summary_json)
    dataset_csv = Path(args.dataset_csv) if args.dataset_csv else None

    if not db_path.exists():
        summary = partial_summary("partial_missing_db", run_id=None, warning=f"local DB missing at {args.db}")
        _write_outputs(summary, _empty_dataset(), output, summary_json, dataset_csv)
        return 0

    try:
        with duckdb.connect(str(db_path), read_only=True) as con:
            tables = _inspect_tables(con)
            resolved_run_id = _resolve_latest_run_id(con) if args.run_id == "latest" else args.run_id
            if resolved_run_id is None:
                summary = partial_summary("partial_missing_source", run_id=None, warning="no run_id found in source tables")
                summary["tables_checked"] = tables
                _write_outputs(summary, _empty_dataset(), output, summary_json, dataset_csv)
                return 0
            source_states, source_tables_used, warnings = load_source_states(con, resolved_run_id)
            if source_states.empty:
                summary = partial_summary(
                    "partial_missing_source",
                    run_id=resolved_run_id,
                    warning="no lifecycle or HSMM state rows found for resolved run_id",
                    source_tables_used=source_tables_used,
                )
                summary["tables_checked"] = tables
                _write_outputs(summary, _empty_dataset(), output, summary_json, dataset_csv)
                return 0
            result = build_exit_target_dataset(
                source_states,
                horizons=parse_horizons(args.horizons),
                run_id=resolved_run_id,
                source_tables_used=source_tables_used,
            )
            result.summary["tables_checked"] = tables
            result.summary["warnings"] = [*result.summary.get("warnings", []), *warnings]
            _write_outputs(result.summary, result.dataset, output, summary_json, dataset_csv)
            return 0
    except Exception as exc:
        summary = partial_summary("fail_exception", run_id=args.run_id, warning=f"exit target dataset builder failed: {exc}")
        _write_outputs(summary, _empty_dataset(), output, summary_json, dataset_csv)
        return 1


def parse_horizons(value: str | Sequence[int] | None) -> tuple[int, ...]:
    if value is None:
        return DEFAULT_HORIZONS
    if isinstance(value, str):
        horizons = [int(part.strip()) for part in value.split(",") if part.strip()]
    else:
        horizons = [int(part) for part in value]
    if not horizons or any(horizon <= 0 for horizon in horizons):
        raise ValueError("horizons must be positive integers")
    return tuple(horizons)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R exit_target_dataset_v1")
    parser.add_argument("--db", required=True, help="Path to local DuckDB database")
    parser.add_argument("--run-id", default="latest", help="HSMM/lifecycle run id or latest")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="Summary JSON report path")
    parser.add_argument("--dataset-csv", default=None, help="Optional sample CSV output path")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizon list")
    parser.add_argument("--no-fetch", action="store_true", default=False, help="Do not fetch external data")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
