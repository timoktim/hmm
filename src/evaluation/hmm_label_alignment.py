"""Stage 01 HMM label-alignment and state identity diagnostics.

The module audits existing HMM outputs only. It does not train models, change
training configuration, or fetch market data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd


READINESS_BLOCKED = "blocked"
READINESS_RESEARCH_ONLY = "research_only"
READINESS_INTERNAL_ONLY = "internal_only"
READINESS_PARTIAL = "partial"

SIGNATURE_NUMERIC_FIELDS = [
    "occupancy_share",
    "transition_out_share",
    "avg_dwell_days",
    "median_rs_20d",
    "median_vol_20d",
    "median_drawdown_20d",
    "median_ret_5d",
    "median_ret_20d",
    "avg_future_ret_5d",
    "avg_future_ret_10d",
    "avg_future_ret_20d",
]

LOCAL_FEATURE_COLUMNS = [
    "rs_20d",
    "vol_20d",
    "drawdown_20d",
    "ret_5d",
    "ret_20d",
    "amount_z_20d",
    "ma20_slope",
]


@dataclass(frozen=True)
class AlignmentConfig:
    db_path: Path
    run_id: str
    compare_mode: str
    output_path: Path
    summary_json_path: Path
    no_fetch: bool = True
    max_compare_runs: int = 5


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def pandas_utc_now_naive() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC").tz_convert(None)


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def stable_hash(prefix: str, parts: list[object]) -> str:
    normalized = "\x1f".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{digest}"


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(out) or math.isinf(out):
        return None
    return out


def _table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    result = con.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.tables
        WHERE table_name = ?
        """,
        [table_name],
    ).fetchone()
    return bool(result and result[0])


def _table_columns(con: duckdb.DuckDBPyConnection, table_name: str) -> list[str]:
    if not _table_exists(con, table_name):
        return []
    rows = con.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = ?
        ORDER BY ordinal_position
        """,
        [table_name],
    ).fetchall()
    return [str(row[0]) for row in rows]


def _select_existing_columns(columns: list[str], wanted: list[str]) -> list[str]:
    present = set(columns)
    return [column for column in wanted if column in present]


def ensure_alignment_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS hmm_state_signature (
          run_id TEXT NOT NULL,
          state_key TEXT NOT NULL,
          state_id INTEGER,
          state_label TEXT,
          signature_json TEXT NOT NULL,
          occupancy_share DOUBLE,
          transition_out_share DOUBLE,
          avg_dwell_days DOUBLE,
          feature_scope_id TEXT,
          universe_id TEXT,
          row_count INTEGER,
          created_at TIMESTAMP NOT NULL,
          PRIMARY KEY (run_id, state_key)
        )
        """
    )
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS hmm_label_alignment_audit (
          audit_id TEXT PRIMARY KEY,
          base_run_id TEXT NOT NULL,
          compare_run_id TEXT NOT NULL,
          base_state_key TEXT NOT NULL,
          matched_state_key TEXT,
          match_score DOUBLE,
          state_signature_distance DOUBLE,
          label_preserved BOOLEAN,
          ambiguous_match BOOLEAN,
          label_drift_severity TEXT,
          alignment_method TEXT,
          coverage_status TEXT,
          created_at TIMESTAMP NOT NULL
        )
        """
    )


def state_key_from_row(row: pd.Series) -> str:
    state_id = row.get("state_id")
    if state_id is not None and not pd.isna(state_id):
        try:
            return f"state_id:{int(state_id)}"
        except (TypeError, ValueError):
            return f"state_id:{state_id}"
    label = row.get("state_label")
    if label is not None and not pd.isna(label):
        return f"state_label:{label}"
    return "state:unknown"


def _normalize_state_rows(rows: pd.DataFrame, run_id: str | None = None) -> pd.DataFrame:
    if rows.empty:
        return pd.DataFrame()
    out = rows.copy()
    if "run_id" not in out.columns:
        out["run_id"] = run_id or "unknown_run"
    if run_id is not None:
        out["run_id"] = run_id
    if "state_id" not in out.columns:
        out["state_id"] = pd.NA
    if "state_label" not in out.columns:
        out["state_label"] = out["state_id"].map(lambda value: None if pd.isna(value) else f"State{int(value)}")
    out["state_label"] = out["state_label"].fillna(out["state_id"].map(lambda value: "Unknown" if pd.isna(value) else f"State{int(value)}"))
    if "sector_id" not in out.columns:
        out["sector_id"] = "all"
    if "trade_date" in out.columns:
        out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    else:
        out["trade_date"] = pd.NaT
    out["state_key"] = out.apply(state_key_from_row, axis=1)
    return out


def _median_numeric(group: pd.DataFrame, column: str) -> float | None:
    if column not in group.columns:
        return None
    values = pd.to_numeric(group[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.median())


def _mean_numeric(group: pd.DataFrame, column: str) -> float | None:
    if column not in group.columns:
        return None
    values = pd.to_numeric(group[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.mean())


def _transition_out_share(rows: pd.DataFrame, state_key: str) -> float | None:
    if rows.empty or "trade_date" not in rows.columns:
        return None
    ordered = rows.sort_values(["sector_id", "trade_date", "state_key"]).copy()
    ordered["next_state_key"] = ordered.groupby("sector_id")["state_key"].shift(-1)
    candidates = ordered[(ordered["state_key"] == state_key) & ordered["next_state_key"].notna()]
    if candidates.empty:
        return None
    return float(candidates["next_state_key"].ne(state_key).mean())


def _avg_dwell_days(rows: pd.DataFrame, state_key: str) -> float | None:
    if rows.empty or "trade_date" not in rows.columns:
        return None
    ordered = rows.sort_values(["sector_id", "trade_date", "state_key"]).copy()
    ordered["segment_id"] = ordered.groupby("sector_id")["state_key"].transform(lambda values: values.ne(values.shift()).cumsum())
    segments = (
        ordered.groupby(["sector_id", "segment_id", "state_key"], dropna=False)
        .size()
        .rename("days")
        .reset_index()
    )
    dwell = pd.to_numeric(segments[segments["state_key"].eq(state_key)]["days"], errors="coerce").dropna()
    if dwell.empty:
        return None
    return float(dwell.mean())


def build_state_signatures(
    state_rows: pd.DataFrame,
    *,
    run_id: str | None = None,
    feature_scope_id: str | None = None,
    universe_id: str | None = None,
) -> pd.DataFrame:
    """Create deterministic state signatures from existing state rows."""
    rows = _normalize_state_rows(state_rows, run_id=run_id)
    if rows.empty:
        return pd.DataFrame(
            columns=[
                "run_id",
                "state_key",
                "state_id",
                "state_label",
                "signature_json",
                "occupancy_share",
                "transition_out_share",
                "avg_dwell_days",
                "feature_scope_id",
                "universe_id",
                "row_count",
                "created_at",
            ]
        )

    created_at = pandas_utc_now_naive()
    total_rows = len(rows)
    signatures: list[dict[str, object]] = []
    for state_key, group in rows.groupby("state_key", sort=True, dropna=False):
        first = group.iloc[0]
        transition_out = _transition_out_share(rows, str(state_key))
        avg_dwell = _avg_dwell_days(rows, str(state_key))
        occupancy = len(group) / total_rows if total_rows else None
        signature: dict[str, object] = {
            "state_key": str(state_key),
            "state_id": None if pd.isna(first.get("state_id")) else int(first.get("state_id")),
            "state_label": str(first.get("state_label")),
            "occupancy_share": occupancy,
            "transition_out_share": transition_out,
            "avg_dwell_days": avg_dwell,
            "sector_count": int(group["sector_id"].nunique()) if "sector_id" in group.columns else None,
            "date_start": None if group["trade_date"].isna().all() else str(group["trade_date"].min().date()),
            "date_end": None if group["trade_date"].isna().all() else str(group["trade_date"].max().date()),
            "row_count": int(len(group)),
        }
        for column in LOCAL_FEATURE_COLUMNS:
            value = _median_numeric(group, column)
            if value is not None:
                signature[f"median_{column}"] = value
        for horizon in (5, 10, 20):
            value = _mean_numeric(group, f"future_ret_{horizon}d")
            if value is not None:
                signature[f"avg_future_ret_{horizon}d"] = value

        signatures.append(
            {
                "run_id": str(first.get("run_id") or run_id or "unknown_run"),
                "state_key": str(state_key),
                "state_id": signature["state_id"],
                "state_label": signature["state_label"],
                "signature_json": json_dumps(signature),
                "occupancy_share": _safe_float(occupancy),
                "transition_out_share": _safe_float(transition_out),
                "avg_dwell_days": _safe_float(avg_dwell),
                "feature_scope_id": feature_scope_id,
                "universe_id": universe_id,
                "row_count": int(len(group)),
                "created_at": created_at,
            }
        )
    return pd.DataFrame(signatures).sort_values(["run_id", "state_key"]).reset_index(drop=True)


def _signature_dict(row: pd.Series) -> dict[str, Any]:
    payload = row.get("signature_json")
    if isinstance(payload, str) and payload.strip():
        try:
            value = json.loads(payload)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            pass
    return {field: row.get(field) for field in SIGNATURE_NUMERIC_FIELDS if field in row.index}


def state_signature_distance(base: pd.Series, compare: pd.Series) -> float:
    base_sig = _signature_dict(base)
    compare_sig = _signature_dict(compare)
    diffs: list[float] = []
    for field in SIGNATURE_NUMERIC_FIELDS:
        left = _safe_float(base_sig.get(field, base.get(field) if field in base.index else None))
        right = _safe_float(compare_sig.get(field, compare.get(field) if field in compare.index else None))
        if left is None or right is None:
            continue
        if field == "avg_dwell_days":
            left = math.log1p(max(left, 0.0))
            right = math.log1p(max(right, 0.0))
        denom = max(abs(left), abs(right), 1.0)
        diffs.append(((left - right) / denom) ** 2)
    if not diffs:
        return float("inf")
    return float(math.sqrt(sum(diffs) / len(diffs)))


def _hungarian_pairs(costs: list[list[float]]) -> list[tuple[int, int]] | None:
    try:
        from scipy.optimize import linear_sum_assignment
    except Exception:
        return None
    row_ind, col_ind = linear_sum_assignment(costs)
    return [(int(row), int(col)) for row, col in zip(row_ind, col_ind, strict=False)]


def _greedy_pairs(costs: list[list[float]], base_keys: list[str], compare_keys: list[str]) -> list[tuple[int, int]]:
    candidates: list[tuple[float, str, str, int, int]] = []
    for i, row in enumerate(costs):
        for j, cost in enumerate(row):
            candidates.append((cost, base_keys[i], compare_keys[j], i, j))
    pairs: list[tuple[int, int]] = []
    used_base: set[int] = set()
    used_compare: set[int] = set()
    for _cost, _base_key, _compare_key, i, j in sorted(candidates):
        if i in used_base or j in used_compare:
            continue
        pairs.append((i, j))
        used_base.add(i)
        used_compare.add(j)
    return pairs


def _drift_severity(label_preserved: bool, distance: float, ambiguous: bool, coverage_status: str) -> str:
    if coverage_status != "ok" or math.isinf(distance):
        return "unknown"
    if ambiguous:
        return "medium"
    if not label_preserved:
        return "high" if distance <= 0.35 else "medium"
    if distance <= 0.05:
        return "none"
    if distance <= 0.20:
        return "low"
    if distance <= 0.50:
        return "medium"
    return "high"


def align_state_signatures(
    base_signatures: pd.DataFrame,
    compare_signatures: pd.DataFrame,
    *,
    base_run_id: str,
    compare_run_id: str,
    prefer_hungarian: bool = True,
    ambiguity_distance_gap: float = 0.05,
) -> tuple[pd.DataFrame, str]:
    """Align states by signature distance and return row-level audit results."""
    if base_signatures.empty or compare_signatures.empty:
        return pd.DataFrame(), "not_enough_states"

    base = base_signatures.sort_values("state_key").reset_index(drop=True)
    compare = compare_signatures.sort_values("state_key").reset_index(drop=True)
    base_keys = base["state_key"].astype(str).tolist()
    compare_keys = compare["state_key"].astype(str).tolist()
    costs = [[state_signature_distance(base.iloc[i], compare.iloc[j]) for j in range(len(compare))] for i in range(len(base))]

    if min(len(base), len(compare)) < 2:
        method = "not_enough_states"
        pairs = [(0, 0)]
    else:
        pairs = _hungarian_pairs(costs) if prefer_hungarian else None
        if pairs is None:
            method = "greedy_fallback"
            pairs = _greedy_pairs(costs, base_keys, compare_keys)
        else:
            method = "hungarian"

    created_at = pandas_utc_now_naive()
    rows: list[dict[str, object]] = []
    for i, j in sorted(pairs, key=lambda item: base_keys[item[0]]):
        distance = costs[i][j]
        finite_row_costs = sorted(value for value in costs[i] if not math.isinf(value))
        second_best = finite_row_costs[1] if len(finite_row_costs) > 1 else None
        ambiguous = second_best is not None and (second_best - distance) <= ambiguity_distance_gap
        base_label = str(base.loc[i, "state_label"])
        matched_label = str(compare.loc[j, "state_label"])
        label_preserved = base_label == matched_label
        coverage_status = "ok" if not math.isinf(distance) else "no_common_signature_fields"
        severity = _drift_severity(label_preserved, distance, bool(ambiguous), coverage_status)
        audit_id = stable_hash("hmm_label_alignment", [base_run_id, compare_run_id, base_keys[i], compare_keys[j]])
        rows.append(
            {
                "audit_id": audit_id,
                "base_run_id": base_run_id,
                "compare_run_id": compare_run_id,
                "base_state_key": base_keys[i],
                "matched_state_key": compare_keys[j],
                "match_score": None if math.isinf(distance) else float(1.0 / (1.0 + distance)),
                "state_signature_distance": None if math.isinf(distance) else distance,
                "label_preserved": bool(label_preserved),
                "ambiguous_match": bool(ambiguous),
                "label_drift_severity": severity,
                "alignment_method": method,
                "coverage_status": coverage_status,
                "created_at": created_at,
            }
        )
    return pd.DataFrame(rows), method


def summarize_audit_rows(audit_rows: pd.DataFrame) -> dict[str, object]:
    if audit_rows.empty:
        return {
            "states_compared": 0,
            "label_preserved_count": 0,
            "label_preserved_share": None,
            "ambiguous_count": 0,
            "ambiguous_share": None,
            "high_drift_count": 0,
            "high_drift_share": None,
            "state_identity_readiness_status": READINESS_RESEARCH_ONLY,
        }
    states_compared = len(audit_rows)
    preserved = int(audit_rows["label_preserved"].fillna(False).sum())
    ambiguous = int(audit_rows["ambiguous_match"].fillna(False).sum())
    high_drift = int(audit_rows["label_drift_severity"].eq("high").sum())
    ambiguous_share = ambiguous / states_compared
    high_drift_share = high_drift / states_compared
    if high_drift_share > 0.25 or ambiguous_share > 0.50:
        readiness = READINESS_RESEARCH_ONLY
    elif high_drift or ambiguous:
        readiness = READINESS_PARTIAL
    else:
        readiness = READINESS_INTERNAL_ONLY
    return {
        "states_compared": states_compared,
        "label_preserved_count": preserved,
        "label_preserved_share": preserved / states_compared,
        "ambiguous_count": ambiguous,
        "ambiguous_share": ambiguous_share,
        "high_drift_count": high_drift,
        "high_drift_share": high_drift_share,
        "state_identity_readiness_status": readiness,
    }


def _connect_read_write(db_path: Path) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(str(db_path))
    con.execute("SET timezone='Asia/Shanghai'")
    return con


def _resolve_run_id(con: duckdb.DuckDBPyConnection, requested_run_id: str) -> tuple[str | None, list[str]]:
    warnings: list[str] = []
    if requested_run_id != "latest":
        return requested_run_id, warnings
    if _table_exists(con, "model_runs") and "run_id" in _table_columns(con, "model_runs"):
        columns = _table_columns(con, "model_runs")
        order_by = "created_at DESC NULLS LAST" if "created_at" in columns else "run_id DESC"
        row = con.execute(f"SELECT run_id FROM model_runs ORDER BY {order_by} LIMIT 1").fetchone()
        if row and row[0]:
            return str(row[0]), warnings
    if _table_exists(con, "sector_state_daily") and "run_id" in _table_columns(con, "sector_state_daily"):
        row = con.execute("SELECT run_id FROM sector_state_daily GROUP BY run_id ORDER BY MAX(trade_date) DESC NULLS LAST LIMIT 1").fetchone()
        if row and row[0]:
            warnings.append("latest run resolved from sector_state_daily because model_runs was unavailable or empty")
            return str(row[0]), warnings
    warnings.append("unable to resolve latest run_id from local DB")
    return None, warnings


def _load_run_metadata(con: duckdb.DuckDBPyConnection, run_id: str) -> dict[str, object]:
    if not _table_exists(con, "model_runs"):
        return {}
    columns = _table_columns(con, "model_runs")
    if "run_id" not in columns:
        return {}
    rows = con.execute("SELECT * FROM model_runs WHERE run_id = ?", [run_id]).fetchdf()
    if rows.empty:
        return {}
    return rows.iloc[0].to_dict()


def _load_state_rows(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, list[str]]:
    warnings: list[str] = []
    if not _table_exists(con, "sector_state_daily"):
        warnings.append("source table missing: sector_state_daily")
        return pd.DataFrame(), warnings
    columns = _table_columns(con, "sector_state_daily")
    required = {"run_id", "state_id", "state_label"}
    if not required.intersection(columns):
        warnings.append("sector_state_daily lacks state identity columns")
        return pd.DataFrame(), warnings
    wanted = _select_existing_columns(
        columns,
        [
            "run_id",
            "sector_id",
            "trade_date",
            "state_id",
            "state_label",
            "state_source",
            "feature_scope_id",
            "universe_id",
        ],
    )
    rows = con.execute(
        f"SELECT {', '.join(wanted)} FROM sector_state_daily WHERE run_id = ?",
        [run_id],
    ).fetchdf()
    if rows.empty:
        warnings.append(f"no sector_state_daily rows found for run_id={run_id}")
    return rows, warnings


def _augment_with_sector_features(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty or "trade_date" not in rows.columns or not _table_exists(con, "sector_features"):
        return rows
    columns = _table_columns(con, "sector_features")
    feature_cols = _select_existing_columns(columns, LOCAL_FEATURE_COLUMNS)
    if not feature_cols or "sector_id" not in columns or "trade_date" not in columns:
        return rows
    query_cols = ["sector_id", "trade_date", *feature_cols]
    if "feature_scope_id" in columns:
        query_cols.append("feature_scope_id")
    features = con.execute(f"SELECT {', '.join(query_cols)} FROM sector_features").fetchdf()
    if features.empty:
        return rows
    out = rows.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    features["trade_date"] = pd.to_datetime(features["trade_date"], errors="coerce")
    keys = ["sector_id", "trade_date"]
    if "feature_scope_id" in out.columns and "feature_scope_id" in features.columns:
        keys.append("feature_scope_id")
    return out.merge(features, on=keys, how="left")


def _augment_with_future_returns(con: duckdb.DuckDBPyConnection, rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty or "trade_date" not in rows.columns or not _table_exists(con, "sector_ohlcv"):
        return rows
    columns = _table_columns(con, "sector_ohlcv")
    if not {"sector_id", "trade_date", "close"}.issubset(columns):
        return rows
    prices = con.execute("SELECT sector_id, trade_date, close FROM sector_ohlcv").fetchdf()
    if prices.empty:
        return rows
    prices["trade_date"] = pd.to_datetime(prices["trade_date"], errors="coerce")
    prices = prices.sort_values(["sector_id", "trade_date"])
    for horizon in (5, 10, 20):
        prices[f"future_ret_{horizon}d"] = prices.groupby("sector_id")["close"].shift(-horizon) / prices["close"] - 1
    out = rows.copy()
    out["trade_date"] = pd.to_datetime(out["trade_date"], errors="coerce")
    return out.merge(
        prices[["sector_id", "trade_date", "future_ret_5d", "future_ret_10d", "future_ret_20d"]],
        on=["sector_id", "trade_date"],
        how="left",
    )


def _load_signature_frame(con: duckdb.DuckDBPyConnection, run_id: str) -> tuple[pd.DataFrame, list[str]]:
    rows, warnings = _load_state_rows(con, run_id)
    if rows.empty:
        return build_state_signatures(rows, run_id=run_id), warnings
    rows = _augment_with_sector_features(con, rows)
    rows = _augment_with_future_returns(con, rows)
    metadata = _load_run_metadata(con, run_id)
    feature_scope_id = metadata.get("feature_scope_id")
    universe_id = metadata.get("universe_id")
    return build_state_signatures(
        rows,
        run_id=run_id,
        feature_scope_id=None if pd.isna(feature_scope_id) else str(feature_scope_id) if feature_scope_id is not None else None,
        universe_id=None if pd.isna(universe_id) else str(universe_id) if universe_id is not None else None,
    ), warnings


def _compatible_run_ids(con: duckdb.DuckDBPyConnection, base_run_id: str, limit: int) -> tuple[list[str], list[str]]:
    warnings: list[str] = []
    if not _table_exists(con, "model_runs"):
        if not _table_exists(con, "sector_state_daily"):
            return [], ["source tables missing: model_runs and sector_state_daily"]
        rows = con.execute(
            """
            SELECT run_id, MAX(trade_date) AS max_trade_date, COUNT(*) AS row_count
            FROM sector_state_daily
            WHERE run_id <> ?
            GROUP BY run_id
            ORDER BY max_trade_date DESC NULLS LAST, run_id DESC
            LIMIT ?
            """,
            [base_run_id, limit],
        ).fetchdf()
        warnings.append("comparable runs resolved from sector_state_daily because model_runs is unavailable")
        return rows["run_id"].astype(str).tolist(), warnings

    columns = _table_columns(con, "model_runs")
    if "run_id" not in columns:
        return [], ["model_runs lacks run_id"]
    runs = con.execute("SELECT * FROM model_runs").fetchdf()
    if runs.empty:
        return [], ["model_runs is empty"]
    base = runs[runs["run_id"].astype(str).eq(base_run_id)]
    if base.empty:
        warnings.append(f"run_id={base_run_id} missing from model_runs; falling back to recent distinct runs")
        candidates = runs[~runs["run_id"].astype(str).eq(base_run_id)].copy()
    else:
        base_row = base.iloc[0]
        candidates = runs[~runs["run_id"].astype(str).eq(base_run_id)].copy()
        for column in ["n_states", "universe_id", "scope_type", "feature_scope_id", "feature_scope_type"]:
            if column in candidates.columns and column in base_row.index:
                base_value = base_row.get(column, "__missing__")
                base_key = "__missing__" if pd.isna(base_value) else str(base_value)
                candidate_keys = candidates[column].astype("object").where(candidates[column].notna(), "__missing__").astype(str)
                candidates = candidates[candidate_keys.eq(base_key)]
    if "created_at" in candidates.columns:
        candidates = candidates.sort_values("created_at", ascending=False, na_position="last")
    else:
        candidates = candidates.sort_values("run_id", ascending=False)
    out = candidates["run_id"].astype(str).head(limit).tolist()
    if not out:
        warnings.append("no compatible recent model_runs found")
    return out, warnings


def _split_run_rows_for_self_compare(rows: pd.DataFrame, run_id: str) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    if rows.empty or "trade_date" not in rows.columns:
        return pd.DataFrame(), pd.DataFrame(), ["self-split requires state rows with trade_date"]
    ordered = rows.copy()
    ordered["trade_date"] = pd.to_datetime(ordered["trade_date"], errors="coerce")
    dates = ordered["trade_date"].dropna().sort_values().drop_duplicates()
    if len(dates) < 2:
        return pd.DataFrame(), pd.DataFrame(), ["self-split requires at least two distinct trade dates"]
    split_date = dates.iloc[len(dates) // 2]
    early = ordered[ordered["trade_date"] < split_date].copy()
    late = ordered[ordered["trade_date"] >= split_date].copy()
    early["run_id"] = f"{run_id}:early"
    late["run_id"] = f"{run_id}:late"
    return early, late, []


def _write_db_outputs(con: duckdb.DuckDBPyConnection, signatures: pd.DataFrame, audit_rows: pd.DataFrame) -> None:
    ensure_alignment_schema(con)
    if not signatures.empty:
        run_ids = signatures["run_id"].dropna().astype(str).drop_duplicates().tolist()
        for run_id in run_ids:
            con.execute("DELETE FROM hmm_state_signature WHERE run_id = ?", [run_id])
        con.register("incoming_signatures", signatures)
        con.execute(
            """
            INSERT INTO hmm_state_signature (
              run_id, state_key, state_id, state_label, signature_json,
              occupancy_share, transition_out_share, avg_dwell_days,
              feature_scope_id, universe_id, row_count, created_at
            )
            SELECT run_id, state_key, state_id, state_label, signature_json,
                   occupancy_share, transition_out_share, avg_dwell_days,
                   feature_scope_id, universe_id, row_count, created_at
            FROM incoming_signatures
            """
        )
    if not audit_rows.empty:
        audit_ids = audit_rows["audit_id"].dropna().astype(str).drop_duplicates().tolist()
        for audit_id in audit_ids:
            con.execute("DELETE FROM hmm_label_alignment_audit WHERE audit_id = ?", [audit_id])
        con.register("incoming_audit", audit_rows)
        con.execute(
            """
            INSERT INTO hmm_label_alignment_audit (
              audit_id, base_run_id, compare_run_id, base_state_key, matched_state_key,
              match_score, state_signature_distance, label_preserved, ambiguous_match,
              label_drift_severity, alignment_method, coverage_status, created_at
            )
            SELECT audit_id, base_run_id, compare_run_id, base_state_key, matched_state_key,
                   match_score, state_signature_distance, label_preserved, ambiguous_match,
                   label_drift_severity, alignment_method, coverage_status, created_at
            FROM incoming_audit
            """
        )


def _severity_distribution(audit_rows: pd.DataFrame) -> dict[str, int]:
    if audit_rows.empty or "label_drift_severity" not in audit_rows.columns:
        return {}
    counts = audit_rows["label_drift_severity"].fillna("unknown").value_counts().sort_index()
    return {str(key): int(value) for key, value in counts.items()}


def _signature_fields_used(signatures: pd.DataFrame) -> list[str]:
    fields: set[str] = {"occupancy_share", "transition_out_share", "avg_dwell_days"}
    for payload in signatures.get("signature_json", pd.Series(dtype=str)).dropna().astype(str):
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            fields.update(key for key in value if key.startswith(("median_", "avg_future_")))
    return sorted(fields)


def write_reports(summary: dict[str, object], output_path: Path, summary_json_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    summary_json_path.parent.mkdir(parents=True, exist_ok=True)
    report = [
        "# Stage 01 WP-B HMM Label Alignment Report",
        "",
        f"- index_id: {summary['index_id']}",
        f"- generated_at: {summary['generated_at']}",
        f"- status: {summary['status']}",
        f"- db_path: {summary['db_path']}",
        f"- db_used: {str(summary['db_used']).lower()}",
        f"- requested_run_id: {summary['requested_run_id']}",
        f"- resolved_run_id: {summary.get('resolved_run_id') or 'unavailable'}",
        f"- comparison_mode: {summary['comparison_mode']}",
        f"- alignment_method: {summary.get('alignment_method') or 'unavailable'}",
        f"- run_pairs_compared: {summary.get('run_pairs_compared', 0)}",
        f"- label_preserved_share: {summary.get('label_preserved_share')}",
        f"- ambiguous_match_share: {summary.get('ambiguous_share')}",
        f"- high_drift_share: {summary.get('high_drift_share')}",
        f"- state_identity_readiness_status: {summary.get('state_identity_readiness_status')}",
        f"- external_data_fetch: {summary['external_data_fetch']}",
        f"- training_algorithm_modified: {summary['training_algorithm_modified']}",
        "",
        "## State Signature Fields Used",
        "",
    ]
    fields = summary.get("state_signature_fields_used") or []
    if fields:
        report.extend([f"- {field}" for field in fields])
    else:
        report.append("- none")
    report.extend(["", "## Drift Severity Distribution", ""])
    distribution = summary.get("drift_severity_distribution") or {}
    if distribution:
        for key, value in dict(distribution).items():
            report.append(f"- {key}: {value}")
    else:
        report.append("- none")
    report.extend(["", "## Run Pairs", ""])
    run_pairs = summary.get("run_pairs") or []
    if run_pairs:
        for pair in run_pairs:
            report.append(f"- {pair}")
    else:
        report.append("- none")
    report.extend(["", "## Coverage Limitations", ""])
    warnings = summary.get("warnings") or []
    if warnings:
        for warning in warnings:
            report.append(f"- {warning}")
    else:
        report.append("- none")
    report.extend(
        [
            "",
            "## Boundary",
            "",
            "- Forward returns, when available, are empirical realized outcomes used only for state signatures.",
            "- HMM posterior values are not interpreted as return probabilities.",
            "- No HMM or HSMM training algorithm was modified by this diagnostic.",
        ]
    )
    output_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    summary_json_path.write_text(json_dumps(summary) + "\n", encoding="utf-8")


def _partial_summary(config: AlignmentConfig, warnings: list[str], *, db_used: bool = False) -> dict[str, object]:
    return {
        "index_id": "STAGE01-WP-B-v1",
        "path": "docs/work_packages/stage_01/STAGE01_WP_B_hmm_label_alignment_stability.md",
        "version": "v1",
        "generated_at": utc_now_iso(),
        "status": "partial",
        "db_path": str(config.db_path),
        "db_used": db_used,
        "requested_run_id": config.run_id,
        "resolved_run_id": None,
        "comparison_mode": config.compare_mode,
        "run_pairs_compared": 0,
        "alignment_method": None,
        "state_signature_fields_used": [],
        "states_compared": 0,
        "label_preserved_count": 0,
        "label_preserved_share": None,
        "ambiguous_count": 0,
        "ambiguous_share": None,
        "high_drift_count": 0,
        "high_drift_share": None,
        "state_identity_readiness_status": READINESS_RESEARCH_ONLY,
        "drift_severity_distribution": {},
        "run_pairs": [],
        "warnings": warnings,
        "external_data_fetch": "no",
        "training_algorithm_modified": "no",
        "implemented_wp_a_confidence": "no",
        "implemented_wp_c_ui_churn": "no",
        "output_report": str(config.output_path),
        "summary_json": str(config.summary_json_path),
    }


def run_label_alignment(config: AlignmentConfig) -> dict[str, object]:
    if not config.no_fetch:
        return _partial_summary(config, ["external fetch is not supported for Stage 01 WP-B; rerun with --no-fetch"])
    if config.compare_mode not in {"recent-runs", "self-split", "report-only"}:
        return _partial_summary(config, [f"unsupported compare_mode={config.compare_mode}"])
    if not config.db_path.exists():
        summary = _partial_summary(config, [f"local DB not found: {config.db_path}"], db_used=False)
        write_reports(summary, config.output_path, config.summary_json_path)
        return summary

    warnings: list[str] = []
    all_signatures: list[pd.DataFrame] = []
    audit_frames: list[pd.DataFrame] = []
    run_pairs: list[str] = []
    alignment_methods: list[str] = []
    resolved_run_id: str | None = None

    with _connect_read_write(config.db_path) as con:
        resolved_run_id, resolve_warnings = _resolve_run_id(con, config.run_id)
        warnings.extend(resolve_warnings)
        if not resolved_run_id:
            summary = _partial_summary(config, warnings, db_used=True)
            write_reports(summary, config.output_path, config.summary_json_path)
            return summary

        if config.compare_mode == "self-split":
            rows, row_warnings = _load_state_rows(con, resolved_run_id)
            warnings.extend(row_warnings)
            rows = _augment_with_sector_features(con, rows)
            rows = _augment_with_future_returns(con, rows)
            early, late, split_warnings = _split_run_rows_for_self_compare(rows, resolved_run_id)
            warnings.extend(split_warnings)
            base_signatures = build_state_signatures(early, run_id=f"{resolved_run_id}:early")
            compare_signatures = build_state_signatures(late, run_id=f"{resolved_run_id}:late")
            all_signatures.extend([base_signatures, compare_signatures])
            if not base_signatures.empty and not compare_signatures.empty:
                audit, method = align_state_signatures(
                    base_signatures,
                    compare_signatures,
                    base_run_id=f"{resolved_run_id}:early",
                    compare_run_id=f"{resolved_run_id}:late",
                )
                audit_frames.append(audit)
                alignment_methods.append(method)
                run_pairs.append(f"{resolved_run_id}:early -> {resolved_run_id}:late")
        else:
            base_signatures, sig_warnings = _load_signature_frame(con, resolved_run_id)
            warnings.extend(sig_warnings)
            all_signatures.append(base_signatures)
            if config.compare_mode == "recent-runs":
                compare_run_ids, compare_warnings = _compatible_run_ids(con, resolved_run_id, config.max_compare_runs)
                warnings.extend(compare_warnings)
                for compare_run_id in compare_run_ids:
                    compare_signatures, compare_sig_warnings = _load_signature_frame(con, compare_run_id)
                    warnings.extend(compare_sig_warnings)
                    all_signatures.append(compare_signatures)
                    if base_signatures.empty or compare_signatures.empty:
                        continue
                    audit, method = align_state_signatures(
                        base_signatures,
                        compare_signatures,
                        base_run_id=resolved_run_id,
                        compare_run_id=compare_run_id,
                    )
                    if not audit.empty:
                        audit_frames.append(audit)
                        alignment_methods.append(method)
                        run_pairs.append(f"{resolved_run_id} -> {compare_run_id}")
            else:
                warnings.append("report-only mode generated signatures without pairwise alignment")

        signature_frame = pd.concat([frame for frame in all_signatures if not frame.empty], ignore_index=True) if any(not frame.empty for frame in all_signatures) else pd.DataFrame()
        audit_rows = pd.concat([frame for frame in audit_frames if not frame.empty], ignore_index=True) if any(not frame.empty for frame in audit_frames) else pd.DataFrame()
        if not signature_frame.empty or not audit_rows.empty:
            _write_db_outputs(con, signature_frame, audit_rows)

    audit_summary = summarize_audit_rows(audit_rows)
    status = "pass" if not audit_rows.empty else "partial"
    if not audit_rows.empty and any(str(value).startswith("no ") for value in warnings):
        status = "partial"
    method = "mixed" if len(set(alignment_methods)) > 1 else alignment_methods[0] if alignment_methods else None
    summary: dict[str, object] = {
        "index_id": "STAGE01-WP-B-v1",
        "path": "docs/work_packages/stage_01/STAGE01_WP_B_hmm_label_alignment_stability.md",
        "version": "v1",
        "generated_at": utc_now_iso(),
        "status": status,
        "db_path": str(config.db_path),
        "db_used": True,
        "requested_run_id": config.run_id,
        "resolved_run_id": resolved_run_id,
        "comparison_mode": config.compare_mode,
        "run_pairs_compared": len(run_pairs),
        "alignment_method": method,
        "state_signature_fields_used": _signature_fields_used(signature_frame),
        "drift_severity_distribution": _severity_distribution(audit_rows),
        "run_pairs": run_pairs,
        "warnings": warnings,
        "external_data_fetch": "no",
        "training_algorithm_modified": "no",
        "implemented_wp_a_confidence": "no",
        "implemented_wp_c_ui_churn": "no",
        "output_report": str(config.output_path),
        "summary_json": str(config.summary_json_path),
    }
    summary.update(audit_summary)
    write_reports(summary, config.output_path, config.summary_json_path)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit HMM state label alignment and identity stability.")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb", help="Local DuckDB path.")
    parser.add_argument("--run-id", default="latest", help="Run id to audit, or latest.")
    parser.add_argument(
        "--compare-mode",
        choices=["recent-runs", "self-split", "report-only"],
        default="recent-runs",
        help="How to select comparable HMM state outputs.",
    )
    parser.add_argument(
        "--output",
        default="reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md",
        help="Markdown report path.",
    )
    parser.add_argument(
        "--summary-json",
        default="reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json",
        help="Machine-readable summary JSON path.",
    )
    parser.add_argument("--no-fetch", action="store_true", default=False, help="Required Stage 01 no-fetch mode.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    config = AlignmentConfig(
        db_path=Path(args.db),
        run_id=args.run_id,
        compare_mode=args.compare_mode,
        output_path=Path(args.output),
        summary_json_path=Path(args.summary_json),
        no_fetch=bool(args.no_fetch),
    )
    summary = run_label_alignment(config)
    print(json_dumps({"status": summary["status"], "report": summary["output_report"], "summary_json": summary["summary_json"]}))
    return 0 if summary["status"] in {"pass", "partial"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
