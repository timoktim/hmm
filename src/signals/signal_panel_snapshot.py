from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.models.inference import latest_causal_sector_states


ROOT = Path(__file__).resolve().parents[2]
STAGE03V_CLOSEOUT_REPORT_PATH = ROOT / "reports/stage03v/stage03v1_phase1_closeout_report.json"
STAGE03V_HANDOFF_PATH = ROOT / "reports/stage03v/stage03v1_phase2_handoff.json"
STAGE03V_FINAL_GATE_V2_PATH = ROOT / "reports/stage03v/stage03v1_final_gate_v2_report.json"
STAGE03V_READINESS_MATRIX_PATH = ROOT / "reports/stage03v/downside_readiness_matrix.csv"
STAGE03V_INVALIDATED_REGISTRY_PATH = ROOT / "reports/stage03v/stage03v1_invalidated_artifact_registry.json"

NO_CURRENT_STAGE03V_SCORE_SOURCE = "unavailable_current_per_entity_score_source"
CURRENT_STAGE03V_SCORE_SOURCE = "available_current_per_entity_score_source"

REQUIRED_SNAPSHOT_COLUMNS = [
    "signal_date",
    "sector_id",
    "sector_name",
    "sector_type",
    "data_freshness_status",
    "source_scope",
    "vol_20d",
    "vol_60d",
    "ewma_vol",
    "volatility_band",
    "volatility_percentile_cs",
    "downside_vol_share_20d",
    "downside_vol_share_60d",
    "negative_return_day_share_20d",
    "hmm_state_label",
    "hmm_confidence",
    "prob_trend_up",
    "prob_neutral",
    "prob_risk_off",
    "hsmm_state_phase",
    "hsmm_state_age_days",
    "hsmm_age_bucket",
    "hsmm_duration_percentile",
    "exit_tendency_5d",
    "exit_tendency_10d",
    "exit_tendency_20d",
    "stage03v_readiness_summary",
    "stage03v_probability_display_status",
    "stage03v_probability_source_status",
    "stage03v_risk_ordinal",
    "model_baseline_alignment_status",
    "human_review_note",
    "not_trading_output",
]

DISPLAY_EXTRA_COLUMNS = [
    "volatility_percentile_ts_if_available",
    "volatility_primary_source",
    "volatility_signal_status",
    "downside_vol_20d",
    "downside_vol_60d",
    "negative_return_day_share_60d",
    "downside_asymmetry_band",
    "hmm_state_source",
    "recent_state_switch_date",
    "recent_state_switch_flag",
    "exit_tendency_1d",
    "exit_tendency_3d",
    "next_state_tendency",
    "hsmm_probability_display_policy",
    "stage03v_usable_probability_slice_count",
    "stage03v_ordinal_only_slice_count",
    "stage03v_baseline_only_slice_count",
    "stage03v_research_only_slice_count",
    "stage03v_calibrated_probability_available",
    "stage03v_calibrated_probability_fields",
    "stage03v_calibrated_probability",
]

SNAPSHOT_COLUMNS = REQUIRED_SNAPSHOT_COLUMNS + DISPLAY_EXTRA_COLUMNS

FORBIDDEN_OUTPUT_COLUMN_TOKENS = (
    "buy",
    "sell",
    "position_size",
    "position_sizing",
    "recommendation",
    "execution",
    "trade_instruction",
    "portfolio_action",
)

NEGATIVE_GUARD_COLUMNS = {"not_trading_output"}

ACCEPTED_SIGNAL_SOURCE_PATHS = {
    "stage03v_closeout_verdict": "reports/stage03v/stage03v1_phase1_closeout_report.json",
    "stage03v_final_gate_v2": "reports/stage03v/stage03v1_final_gate_v2_report.json",
    "stage03v_readiness_matrix": "reports/stage03v/downside_readiness_matrix.csv",
    "stage03v_invalidated_artifact_registry": "reports/stage03v/stage03v1_invalidated_artifact_registry.json",
    "baseline_data_source": "sector_ohlcv / sector_features",
    "hmm_state_source": "walk_forward_state_cache",
    "hsmm_lifecycle_source": "hsmm_lifecycle_ui_daily",
}

INVALIDATED_SIGNAL_SOURCE_FORBIDDEN = (
    "reports/stage03v/purge_embargo_fold_plan.json",
    "reports/stage03v/risk_validation_report.json",
    "reports/stage03v/downshift_research_report.json",
    "reports/stage03v/wp7_final_gate_input_manifest.json",
    "old WP7-v1 final gate outputs",
)


class StorageLike(Protocol):
    def read_df(self, sql: str, params: tuple | list | None = None) -> pd.DataFrame:
        ...


@dataclass(frozen=True)
class Stage03VReadinessSummary:
    usable_probability_slice_count: int = 0
    ordinal_only_slice_count: int = 0
    baseline_only_slice_count: int = 0
    research_only_slice_count: int = 0
    probability_source_status: str = NO_CURRENT_STAGE03V_SCORE_SOURCE

    @property
    def summary_text(self) -> str:
        return (
            f"usable_probability_candidate={self.usable_probability_slice_count}; "
            f"ordinal_only_candidate={self.ordinal_only_slice_count}; "
            f"baseline_only_candidate={self.baseline_only_slice_count}; "
            f"research_only={self.research_only_slice_count}"
        )


def forbidden_output_columns(columns: list[str] | pd.Index) -> list[str]:
    violations: list[str] = []
    for column in columns:
        name = str(column)
        if name in NEGATIVE_GUARD_COLUMNS:
            continue
        lower = name.lower()
        if any(token in lower for token in FORBIDDEN_OUTPUT_COLUMN_TOKENS):
            violations.append(name)
    return violations


def validate_snapshot_schema(snapshot: pd.DataFrame) -> list[str]:
    missing = [column for column in REQUIRED_SNAPSHOT_COLUMNS if column not in snapshot.columns]
    forbidden = forbidden_output_columns(snapshot.columns)
    issues = [f"missing_column:{column}" for column in missing]
    issues.extend(f"forbidden_column:{column}" for column in forbidden)
    if "not_trading_output" in snapshot.columns and not snapshot["not_trading_output"].astype(str).eq("yes").all():
        issues.append("not_trading_output_not_always_yes")
    return issues


def signal_source_paths() -> dict[str, str]:
    return dict(ACCEPTED_SIGNAL_SOURCE_PATHS)


def load_stage03v_readiness_summary(
    readiness_matrix_path: Path = STAGE03V_READINESS_MATRIX_PATH,
    current_stage03v_scores: pd.DataFrame | None = None,
) -> Stage03VReadinessSummary:
    counts: dict[str, int] = {}
    if readiness_matrix_path.exists():
        matrix = pd.read_csv(readiness_matrix_path)
        if "readiness_category" in matrix.columns:
            counts = matrix["readiness_category"].astype(str).value_counts().to_dict()
    return Stage03VReadinessSummary(
        usable_probability_slice_count=int(counts.get("usable_probability_candidate", 0)),
        ordinal_only_slice_count=int(counts.get("ordinal_only_candidate", 0)),
        baseline_only_slice_count=int(counts.get("baseline_only_candidate", 0)),
        research_only_slice_count=int(counts.get("research_only", 0)),
        probability_source_status=(
            CURRENT_STAGE03V_SCORE_SOURCE
            if current_stage03v_scores is not None and not current_stage03v_scores.empty
            else NO_CURRENT_STAGE03V_SCORE_SOURCE
        ),
    )


def _safe_read_df(storage: StorageLike, sql: str, params: list[object] | None = None) -> pd.DataFrame:
    try:
        return storage.read_df(sql, params or [])
    except Exception:
        return pd.DataFrame()


def load_sector_ohlcv(
    storage: StorageLike,
    *,
    signal_date: object | None = None,
    universe_id: str | None = None,
    lookback_rows: int = 90,
) -> pd.DataFrame:
    where = []
    params: list[object] = []
    if signal_date is not None:
        where.append("o.trade_date <= ?")
        params.append(pd.to_datetime(signal_date).date())
    if universe_id:
        where.append("o.sector_id IN (SELECT item_id FROM user_universe_items WHERE universe_id = ?)")
        params.append(universe_id)
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    sql = f"""
        SELECT *
        FROM (
          SELECT o.sector_id, o.trade_date, o.open, o.high, o.low, o.close,
                 o.volume, o.amount, m.sector_type, m.sector_name,
                 row_number() OVER (PARTITION BY o.sector_id ORDER BY o.trade_date DESC) AS rn
          FROM sector_ohlcv o
          LEFT JOIN sector_meta m USING (sector_id)
          {where_sql}
        )
        WHERE rn <= ?
        ORDER BY sector_id, trade_date
    """
    params.append(int(lookback_rows))
    return _safe_read_df(storage, sql, params)


def _latest_causal_cache_key(storage: StorageLike, universe_id: str | None = None) -> str | None:
    if universe_id:
        df = _safe_read_df(
            storage,
            """
            SELECT cache_key
            FROM walk_forward_cache_runs
            WHERE universe_id = ?
              AND row_count > 0
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
            [universe_id],
        )
    else:
        df = _safe_read_df(
            storage,
            """
            SELECT cache_key
            FROM walk_forward_cache_runs
            WHERE (universe_id IS NULL OR universe_id IN ('', 'all'))
              AND row_count > 0
            ORDER BY created_at DESC NULLS LAST
            LIMIT 1
            """,
        )
    if df.empty or "cache_key" not in df.columns:
        return None
    return str(df.loc[0, "cache_key"])


def load_hmm_context(storage: StorageLike, universe_id: str | None = None) -> pd.DataFrame:
    cache_key = _latest_causal_cache_key(storage, universe_id)
    if not cache_key or not isinstance(storage, DuckDBStorage):
        return pd.DataFrame()
    try:
        return latest_causal_sector_states(storage, cache_key=cache_key, universe_id=universe_id)
    except Exception:
        return pd.DataFrame()


def load_hsmm_context(storage: StorageLike, universe_id: str | None = None) -> pd.DataFrame:
    where = []
    params: list[object] = []
    if universe_id:
        where.append("ui.sector_code IN (SELECT item_id FROM user_universe_items WHERE universe_id = ?)")
        params.append(universe_id)
    where_sql = "AND " + " AND ".join(where) if where else ""
    sql = f"""
        SELECT *
        FROM (
          SELECT ui.sector_code, ui.sector_name, ui.trade_date, ui.state_phase,
                 ui.display_state_age_days, ui.display_age_bucket,
                 ui.duration_percentile_display, ui.exit_tendency_1d,
                 ui.exit_tendency_3d, ui.exit_tendency_5d, ui.exit_tendency_10d,
                 ui.exit_tendency_20d, ui.next_state_tendency,
                 ui.probability_display_policy, ui.created_at,
                 row_number() OVER (
                   PARTITION BY ui.sector_code
                   ORDER BY ui.trade_date DESC, ui.created_at DESC NULLS LAST
                 ) AS rn
          FROM hsmm_lifecycle_ui_daily ui
          WHERE ui.trade_date = (SELECT MAX(trade_date) FROM hsmm_lifecycle_ui_daily)
          {where_sql}
        )
        WHERE rn = 1
        ORDER BY sector_code
    """
    return _safe_read_df(storage, sql, params)


def build_signal_panel_snapshot(
    storage: StorageLike | None = None,
    *,
    universe_id: str | None = None,
    signal_date: object | None = None,
    current_stage03v_scores: pd.DataFrame | None = None,
) -> pd.DataFrame:
    storage = storage or DuckDBStorage()
    ohlcv = load_sector_ohlcv(storage, signal_date=signal_date, universe_id=universe_id)
    hmm = load_hmm_context(storage, universe_id)
    hsmm = load_hsmm_context(storage, universe_id)
    readiness = load_stage03v_readiness_summary(current_stage03v_scores=current_stage03v_scores)
    return build_signal_panel_snapshot_from_frames(
        ohlcv,
        hmm_context=hmm,
        hsmm_context=hsmm,
        stage03v_readiness=readiness,
        current_stage03v_scores=current_stage03v_scores,
        signal_date=signal_date,
    )


def build_signal_panel_snapshot_from_frames(
    ohlcv: pd.DataFrame,
    *,
    hmm_context: pd.DataFrame | None = None,
    hsmm_context: pd.DataFrame | None = None,
    stage03v_readiness: Stage03VReadinessSummary | None = None,
    current_stage03v_scores: pd.DataFrame | None = None,
    signal_date: object | None = None,
) -> pd.DataFrame:
    readiness = stage03v_readiness or Stage03VReadinessSummary(
        probability_source_status=(
            CURRENT_STAGE03V_SCORE_SOURCE
            if current_stage03v_scores is not None and not current_stage03v_scores.empty
            else NO_CURRENT_STAGE03V_SCORE_SOURCE
        )
    )
    baseline = _build_baseline_frame(ohlcv, signal_date=signal_date)
    if baseline.empty:
        return pd.DataFrame(columns=SNAPSHOT_COLUMNS)

    snapshot = baseline
    snapshot = snapshot.merge(_normalize_hmm_context(hmm_context), on="sector_id", how="left")
    snapshot = snapshot.merge(_normalize_hsmm_context(hsmm_context), on="sector_id", how="left")
    snapshot = _attach_stage03v_readiness(snapshot, readiness, current_stage03v_scores)
    snapshot["model_baseline_alignment_status"] = snapshot.apply(_alignment_status, axis=1)
    snapshot["human_review_note"] = snapshot["model_baseline_alignment_status"].map(
        {
            "baseline_high_model_high": "risk evidence aligned",
            "baseline_high_model_low": "possible baseline false-alarm / overlay disagreement",
            "baseline_low_model_high": "possible residual risk / overlay disagreement",
            "baseline_low_model_low": "low-risk alignment",
            "baseline_available_model_unavailable": "baseline available; model overlay unavailable",
            "model_available_baseline_unavailable": "model overlay available; baseline unavailable",
            "insufficient_signal_sources": "insufficient signal sources",
        }
    )
    snapshot["not_trading_output"] = "yes"
    snapshot = _fill_context_defaults(snapshot)
    for column in SNAPSHOT_COLUMNS:
        if column not in snapshot.columns:
            snapshot[column] = np.nan
    return snapshot[SNAPSHOT_COLUMNS]


def _build_baseline_frame(ohlcv: pd.DataFrame, *, signal_date: object | None = None) -> pd.DataFrame:
    if ohlcv is None or ohlcv.empty:
        return pd.DataFrame()
    required = {"sector_id", "trade_date", "close"}
    if not required.issubset(ohlcv.columns):
        return pd.DataFrame()
    work = ohlcv.copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"], errors="coerce")
    work = work.dropna(subset=["sector_id", "trade_date", "close"]).sort_values(["sector_id", "trade_date"])
    if signal_date is not None:
        cutoff = pd.to_datetime(signal_date, errors="coerce")
        if not pd.isna(cutoff):
            work = work[work["trade_date"] <= cutoff]
    rows: list[dict[str, object]] = []
    for sector_id, group in work.groupby("sector_id", sort=False):
        group = group.sort_values("trade_date").copy()
        returns = pd.to_numeric(group["close"], errors="coerce").pct_change(fill_method=None)
        latest = group.iloc[-1]
        ret20 = returns.tail(20).dropna()
        ret60 = returns.tail(60).dropna()
        vol20 = _annualized_window_vol(ret20, 20)
        vol60 = _annualized_window_vol(ret60, 60)
        ewma_vol = _ewma_volatility(returns)
        downside20, downside_share20, negative_share20 = _downside_stats(ret20)
        downside60, downside_share60, negative_share60 = _downside_stats(ret60)
        rows.append(
            {
                "signal_date": latest["trade_date"].date(),
                "sector_id": str(sector_id),
                "sector_name": _safe_text(latest.get("sector_name"), str(sector_id)),
                "sector_type": _safe_text(latest.get("sector_type"), "unknown"),
                "data_freshness_status": "latest_available",
                "source_scope": "baseline_ohlcv_readonly",
                "vol_20d": vol20,
                "vol_60d": vol60,
                "ewma_vol": ewma_vol,
                "downside_vol_20d": downside20,
                "downside_vol_60d": downside60,
                "downside_vol_share_20d": downside_share20,
                "downside_vol_share_60d": downside_share60,
                "negative_return_day_share_20d": negative_share20,
                "negative_return_day_share_60d": negative_share60,
                "volatility_primary_source": "sector_ohlcv_readonly",
                "volatility_signal_status": "available" if pd.notna(vol20) else "insufficient_ohlcv_history",
            }
        )
    out = pd.DataFrame(rows)
    if out.empty:
        return out
    out["volatility_percentile_cs"] = out["vol_20d"].rank(pct=True, method="average")
    out["volatility_percentile_ts_if_available"] = np.nan
    out["volatility_band"] = out["volatility_percentile_cs"].map(_volatility_band)
    out.loc[out["vol_20d"].isna(), "volatility_band"] = "unavailable"
    out["downside_asymmetry_band"] = out.apply(_downside_band, axis=1)
    return out


def _annualized_window_vol(returns: pd.Series, window: int) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty or len(clean) < max(2, min(10, window)):
        return float("nan")
    return float(clean.std(ddof=0) * np.sqrt(window))


def _ewma_volatility(returns: pd.Series) -> float:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if len(clean) < 5:
        return float("nan")
    return float(clean.ewm(span=20, adjust=False).std(bias=True).iloc[-1] * np.sqrt(20))


def _downside_stats(returns: pd.Series) -> tuple[float, float, float]:
    clean = pd.to_numeric(returns, errors="coerce").dropna()
    if clean.empty:
        return (float("nan"), float("nan"), float("nan"))
    downside = np.minimum(clean.to_numpy(dtype=float), 0.0)
    downside_vol = float(np.sqrt(np.mean(np.square(downside))))
    total_vol = float(clean.std(ddof=0))
    downside_share = float(downside_vol / total_vol) if total_vol > 0 else float("nan")
    negative_share = float((clean < 0).mean())
    return (downside_vol, downside_share, negative_share)


def _volatility_band(percentile: object) -> str:
    value = _numeric_or_nan(percentile)
    if pd.isna(value):
        return "unavailable"
    if value >= 0.80:
        return "high"
    if value >= 0.60:
        return "elevated"
    if value <= 0.20:
        return "low"
    return "normal"


def _downside_band(row: pd.Series) -> str:
    share = _numeric_or_nan(row.get("downside_vol_share_60d"))
    negative = _numeric_or_nan(row.get("negative_return_day_share_60d"))
    if pd.isna(share) and pd.isna(negative):
        return "unavailable"
    if (pd.notna(share) and share >= 0.75) or (pd.notna(negative) and negative >= 0.60):
        return "high"
    if (pd.notna(share) and share >= 0.55) or (pd.notna(negative) and negative >= 0.50):
        return "medium"
    return "low"


def _normalize_hmm_context(hmm_context: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "sector_id",
        "hmm_state_label",
        "hmm_state_source",
        "hmm_confidence",
        "prob_trend_up",
        "prob_neutral",
        "prob_risk_off",
        "recent_state_switch_date",
        "recent_state_switch_flag",
    ]
    if hmm_context is None or hmm_context.empty or "sector_id" not in hmm_context.columns:
        return pd.DataFrame(columns=columns)
    work = hmm_context.copy()
    rename = {
        "state_label": "hmm_state_label",
        "state_source": "hmm_state_source",
    }
    work = work.rename(columns=rename)
    probs = [col for col in ["prob_trend_up", "prob_neutral", "prob_risk_off"] if col in work.columns]
    if probs:
        work["hmm_confidence"] = work[probs].apply(pd.to_numeric, errors="coerce").max(axis=1)
    if "recent_state_switch_flag" not in work.columns:
        work["recent_state_switch_flag"] = "unknown"
    for column in columns:
        if column not in work.columns:
            work[column] = np.nan
    return work[columns].drop_duplicates("sector_id")


def _normalize_hsmm_context(hsmm_context: pd.DataFrame | None) -> pd.DataFrame:
    columns = [
        "sector_id",
        "hsmm_state_phase",
        "hsmm_state_age_days",
        "hsmm_age_bucket",
        "hsmm_duration_percentile",
        "exit_tendency_1d",
        "exit_tendency_3d",
        "exit_tendency_5d",
        "exit_tendency_10d",
        "exit_tendency_20d",
        "next_state_tendency",
        "hsmm_probability_display_policy",
    ]
    if hsmm_context is None or hsmm_context.empty:
        return pd.DataFrame(columns=columns)
    work = hsmm_context.copy()
    rename = {
        "sector_code": "sector_id",
        "state_phase": "hsmm_state_phase",
        "display_state_age_days": "hsmm_state_age_days",
        "display_age_bucket": "hsmm_age_bucket",
        "duration_percentile_display": "hsmm_duration_percentile",
        "probability_display_policy": "hsmm_probability_display_policy",
    }
    work = work.rename(columns=rename)
    if "sector_id" not in work.columns:
        return pd.DataFrame(columns=columns)
    for column in columns:
        if column not in work.columns:
            work[column] = np.nan
    return work[columns].drop_duplicates("sector_id")


def _attach_stage03v_readiness(
    snapshot: pd.DataFrame,
    readiness: Stage03VReadinessSummary,
    current_stage03v_scores: pd.DataFrame | None,
) -> pd.DataFrame:
    out = snapshot.copy()
    out["stage03v_readiness_summary"] = readiness.summary_text
    out["stage03v_usable_probability_slice_count"] = readiness.usable_probability_slice_count
    out["stage03v_ordinal_only_slice_count"] = readiness.ordinal_only_slice_count
    out["stage03v_baseline_only_slice_count"] = readiness.baseline_only_slice_count
    out["stage03v_research_only_slice_count"] = readiness.research_only_slice_count
    out["stage03v_probability_source_status"] = readiness.probability_source_status
    out["stage03v_probability_display_status"] = "hidden_no_current_per_entity_score_source"
    out["stage03v_risk_ordinal"] = NO_CURRENT_STAGE03V_SCORE_SOURCE
    out["stage03v_calibrated_probability_available"] = "no"
    out["stage03v_calibrated_probability_fields"] = ""
    out["stage03v_calibrated_probability"] = np.nan

    if current_stage03v_scores is None or current_stage03v_scores.empty:
        return out
    score = current_stage03v_scores.copy()
    if "sector_id" not in score.columns:
        return out
    merge_cols = [col for col in ["sector_id", "readiness_category", "risk_ordinal", "calibrated_probability"] if col in score.columns]
    out = out.merge(score[merge_cols].drop_duplicates("sector_id"), on="sector_id", how="left")
    readiness_col = out.get("readiness_category", pd.Series(index=out.index, dtype=object)).astype(str)
    usable = readiness_col.eq("usable_probability_candidate")
    ordinal = readiness_col.eq("ordinal_only_candidate")

    if "risk_ordinal" in out.columns:
        out.loc[out["risk_ordinal"].notna(), "stage03v_risk_ordinal"] = out.loc[out["risk_ordinal"].notna(), "risk_ordinal"]
    out.loc[usable, "stage03v_probability_display_status"] = "readiness_gated_numeric_probability_available"
    out.loc[usable, "stage03v_calibrated_probability_available"] = "yes"
    out.loc[usable, "stage03v_calibrated_probability_fields"] = "stage03v_calibrated_probability"
    if "calibrated_probability" in out.columns:
        out.loc[usable, "stage03v_calibrated_probability"] = pd.to_numeric(out.loc[usable, "calibrated_probability"], errors="coerce")
    out.loc[ordinal, "stage03v_probability_display_status"] = "ordinal_only_no_numeric_probability"
    out.loc[ordinal, "stage03v_calibrated_probability_available"] = "no"
    out.loc[ordinal, "stage03v_calibrated_probability"] = np.nan
    out.loc[readiness_col.eq("baseline_only_candidate"), "stage03v_probability_display_status"] = "baseline_only_no_numeric_probability"
    out.loc[readiness_col.eq("research_only"), "stage03v_probability_display_status"] = "research_only_hidden_by_default"
    return out.drop(columns=[col for col in ["readiness_category", "risk_ordinal", "calibrated_probability"] if col in out.columns])


def _alignment_status(row: pd.Series) -> str:
    baseline_band = str(row.get("volatility_band") or "unavailable")
    model_status = str(row.get("stage03v_probability_source_status") or "")
    model_risk = str(row.get("stage03v_risk_ordinal") or "")
    baseline_available = baseline_band not in {"", "nan", "None", "unavailable"}
    model_available = model_status == CURRENT_STAGE03V_SCORE_SOURCE and model_risk not in {
        "",
        "nan",
        "None",
        NO_CURRENT_STAGE03V_SCORE_SOURCE,
    }
    if baseline_available and not model_available:
        return "baseline_available_model_unavailable"
    if model_available and not baseline_available:
        return "model_available_baseline_unavailable"
    if not baseline_available and not model_available:
        return "insufficient_signal_sources"
    baseline_high = baseline_band in {"high", "elevated"}
    model_high = model_risk in {"high", "extreme", "elevated"}
    if baseline_high and model_high:
        return "baseline_high_model_high"
    if baseline_high and not model_high:
        return "baseline_high_model_low"
    if not baseline_high and model_high:
        return "baseline_low_model_high"
    return "baseline_low_model_low"


def _fill_context_defaults(snapshot: pd.DataFrame) -> pd.DataFrame:
    out = snapshot.copy()
    hmm_defaults = {
        "hmm_state_label": "unavailable",
        "hmm_state_source": "unavailable_causal_cache",
        "recent_state_switch_flag": "unknown",
    }
    hsmm_defaults = {
        "hsmm_state_phase": "unavailable",
        "hsmm_age_bucket": "unavailable",
        "hsmm_probability_display_policy": "unavailable_lifecycle_source",
    }
    for column, value in {**hmm_defaults, **hsmm_defaults}.items():
        if column in out.columns:
            out[column] = out[column].fillna(value)
    return out


def _safe_text(value: object, fallback: str) -> str:
    if value is None or pd.isna(value):
        return fallback
    text = str(value).strip()
    return fallback if text == "" else text


def _numeric_or_nan(value: object) -> float:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return float(numeric) if pd.notna(numeric) else float("nan")


def build_signal_panel_contract_report() -> dict[str, object]:
    closeout = _load_json(STAGE03V_CLOSEOUT_REPORT_PATH)
    handoff = _load_json(STAGE03V_HANDOFF_PATH)
    return {
        "index_id": "STAGE03V-PHASE2-WP0-v1",
        "status": "pass",
        "signal_panel_page": "src/ui/signal_panel_page.py",
        "snapshot_adapter": "src/signals/signal_panel_snapshot.py",
        "navigation_label": "信号面板",
        "navigation_group": "当前状态",
        "baseline_first": "yes",
        "primary_baseline_family": "realized_volatility",
        "model_role": handoff.get("model_role", "research_only_hazard_overlay"),
        "stage03v1_decision_support_status": closeout.get("stage03v1_decision_support_status", "not_promoted"),
        "stage03v_probability_source_status_default": NO_CURRENT_STAGE03V_SCORE_SOURCE,
        "required_schema_columns": REQUIRED_SNAPSHOT_COLUMNS,
        "accepted_signal_source_paths": signal_source_paths(),
        "invalidated_signal_sources_forbidden": list(INVALIDATED_SIGNAL_SOURCE_FORBIDDEN),
        "boundary_flags": {
            "external_data_fetch": "no",
            "new_experiment_run": "no",
            "model_training": "no",
            "probability_recalibration": "no",
            "readiness_reassigned": "no",
            "target_dataset_modified": "no",
            "fixed_threshold_mainline_modified": "no",
            "prospective_holdout_performance_consumed": "no",
            "holdout_consumed": "no",
            "HMM_HSMM_training_modified": "no",
            "stage03v2_implemented": "no",
            "stage03v3_implemented": "no",
            "trading_or_decision_output": "no",
        },
    }


def _load_json(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
