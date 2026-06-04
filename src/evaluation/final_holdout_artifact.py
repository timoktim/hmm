"""Stage03R WP10.1 final holdout artifact.

This module builds a deterministic, one-time final holdout artifact from the
local DuckDB in read-only mode. It computes only WP8 pre-registered metric
families against fixed, already accepted readiness-matrix slice probabilities.
It does not fetch data, retrain models, tune thresholds, or create decision
outputs.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from src.evaluation.age_bucket_baseline import age_bucket
from src.models.duration_hazard import _dataset_from_db


INDEX_ID = "STAGE03R-WP10.1"
ARTIFACT_VERSION = "final_holdout_artifact_v1"
EXPECTED_HORIZONS = [1, 3, 5, 10, 20]
READINESS_STATUSES = [
    "usable_probability",
    "ordinal_only",
    "baseline_only",
    "insufficient_sample",
    "invalid",
]
OBSERVED_STATUSES = {"observed_positive", "observed_negative"}
FORBIDDEN_OUTPUT_TERMS = [
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
]
DENIAL_FLAG_ALLOWLIST = {"decision_surface_output"}
READINESS_JOIN_COLUMNS = [
    "state_label",
    "horizon_days",
    "age_bucket",
    "state_phase",
    "profile_mode",
    "state_date_policy",
]


@dataclass
class FinalHoldoutArtifactResult:
    status: str
    artifact_version: str
    index_id: str
    source_db: str
    db_opened_read_only: str
    external_data_fetch: str
    holdout_policy: dict[str, Any]
    holdout_start_date: str | None
    holdout_end_date: str | None
    holdout_status: str
    holdout_selection_reason: str
    non_overlap_status: str
    non_overlap_evidence: dict[str, Any]
    consumption_count: int
    consumed_in_wp10: str
    tuned_on_holdout: str
    threshold_tuning_on_holdout: str
    model_retrained: str
    HMM_HSMM_retrained: str
    HSMM_p_exit_used_for_decision: str
    decision_surface_output: str
    readiness_status_counts: dict[str, int]
    metrics_by_readiness_status: dict[str, Any]
    readiness_status_verdicts: dict[str, Any]
    metrics_by_horizon: dict[str, Any]
    usable_probability_metrics: dict[str, Any]
    baseline_only_metrics: dict[str, Any]
    insufficient_sample_metrics: dict[str, Any]
    abstain_coverage: dict[str, Any]
    false_confidence_flags: list[dict[str, Any]]
    blocking_issues: list[str]
    defer_reasons: list[str]
    empirical_promotion_verdict: str
    final_recommendation: str
    local_db_status: dict[str, Any] = field(default_factory=dict)
    holdout_row_count: int = 0
    observed_metric_row_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        return asdict(self)


def _json_default(value: Any) -> Any:
    if isinstance(value, (pd.Timestamp, datetime, date)):
        if pd.isna(value):
            return None
        return pd.Timestamp(value).date().isoformat()
    if hasattr(value, "item"):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass
    return str(value)


def _safe_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_yes(value: Any) -> bool:
    return value in {"yes", "true", "1", True, 1}


def _metric_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _brier(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    if len(labels) == 0:
        return None
    return float(np.mean((probabilities - labels) ** 2))


def _log_loss(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    if len(labels) == 0:
        return None
    clipped = np.clip(probabilities, 1e-12, 1.0 - 1e-12)
    return float(-np.mean(labels * np.log(clipped) + (1.0 - labels) * np.log(1.0 - clipped)))


def _ece(labels: np.ndarray, probabilities: np.ndarray, *, n_bins: int = 10) -> float | None:
    if len(labels) == 0:
        return None
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    total = 0.0
    for idx in range(n_bins):
        lower = bins[idx]
        upper = bins[idx + 1]
        if idx == n_bins - 1:
            mask = (probabilities >= lower) & (probabilities <= upper)
        else:
            mask = (probabilities >= lower) & (probabilities < upper)
        if not mask.any():
            continue
        total += float(mask.mean()) * abs(float(labels[mask].mean()) - float(probabilities[mask].mean()))
    return float(total)


def _directional_separation(labels: np.ndarray, probabilities: np.ndarray) -> float | None:
    positives = probabilities[labels == 1]
    negatives = probabilities[labels == 0]
    if len(positives) == 0 or len(negatives) == 0:
        return None
    return float(np.mean(positives) - np.mean(negatives))


def _false_confidence_summary(labels: np.ndarray, probabilities: np.ndarray) -> dict[str, Any]:
    if len(labels) == 0:
        return {
            "high_confidence_probability_threshold": 0.8,
            "low_confidence_probability_threshold": 0.2,
            "high_confidence_row_count": 0,
            "false_high_probability_negative_count": 0,
            "false_low_probability_positive_count": 0,
            "false_confidence_row_count": 0,
        }
    high = probabilities >= 0.8
    low = probabilities <= 0.2
    false_high = high & (labels == 0)
    false_low = low & (labels == 1)
    return {
        "high_confidence_probability_threshold": 0.8,
        "low_confidence_probability_threshold": 0.2,
        "threshold_source": "fixed audit bands; not tuned on holdout",
        "high_confidence_row_count": int(high.sum()),
        "low_confidence_row_count": int(low.sum()),
        "false_high_probability_negative_count": int(false_high.sum()),
        "false_low_probability_positive_count": int(false_low.sum()),
        "false_confidence_row_count": int(false_high.sum() + false_low.sum()),
    }


def _metric_summary(rows: pd.DataFrame) -> dict[str, Any]:
    out = {
        "sample_count": int(len(rows)),
        "metric_row_count": 0,
        "positive_count": 0,
        "negative_count": 0,
        "brier_score": None,
        "log_loss": None,
        "expected_calibration_error": None,
        "directional_separation": None,
        "abstain_count": int(len(rows)),
        "false_confidence": _false_confidence_summary(np.array([], dtype=int), np.array([], dtype=float)),
    }
    if rows.empty:
        return out
    labels_all = pd.to_numeric(rows.get("exit_within_horizon", pd.Series(index=rows.index)), errors="coerce")
    out["positive_count"] = int(labels_all.eq(1).sum())
    out["negative_count"] = int(labels_all.eq(0).sum())
    metric_rows = rows[pd.to_numeric(rows.get("_metric_probability", pd.Series(index=rows.index)), errors="coerce").notna()].copy()
    out["metric_row_count"] = int(len(metric_rows))
    out["abstain_count"] = int(len(rows) - len(metric_rows))
    if metric_rows.empty:
        return out
    labels = pd.to_numeric(metric_rows["exit_within_horizon"], errors="coerce").astype(int).to_numpy()
    probs = pd.to_numeric(metric_rows["_metric_probability"], errors="coerce").astype(float).to_numpy()
    out["brier_score"] = _brier(labels, probs)
    out["log_loss"] = _log_loss(labels, probs)
    out["expected_calibration_error"] = _ece(labels, probs)
    out["directional_separation"] = _directional_separation(labels, probs)
    out["false_confidence"] = _false_confidence_summary(labels, probs)
    return out


def _local_db_status(db_path: str | None) -> dict[str, Any]:
    if not db_path:
        return {
            "db_path_used": None,
            "db_found": "no",
            "opened_read_only": "no",
            "row_counts": {},
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    path = Path(db_path)
    safe = _safe_source_path(path)
    if not path.exists():
        return {
            "db_path_used": safe,
            "db_found": "no",
            "opened_read_only": "no",
            "row_counts": {},
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    try:
        import duckdb

        con = duckdb.connect(str(path), read_only=True)
    except Exception as exc:
        return {
            "db_path_used": safe,
            "db_found": "yes",
            "opened_read_only": "no",
            "open_error": str(exc),
            "row_counts": {},
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    try:
        row_counts: dict[str, int] = {}
        for table in [
            "model_runs",
            "sector_state_daily",
            "walk_forward_cache_runs",
            "walk_forward_state_cache",
            "hsmm_lifecycle_ui_daily",
        ]:
            try:
                row_counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
            except Exception:
                row_counts[table] = 0
        return {
            "db_path_used": safe,
            "db_found": "yes",
            "opened_read_only": "yes",
            "row_counts": row_counts,
            "external_data_fetch": "no",
            "DuckDB_committed": "no",
        }
    finally:
        try:
            con.close()
        except Exception:
            pass


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _prepare_readiness_frame(hazard_readiness: Mapping[str, Any]) -> pd.DataFrame:
    rows = hazard_readiness.get("readiness_rows", [])
    if not rows:
        return pd.DataFrame(columns=READINESS_JOIN_COLUMNS)
    frame = pd.DataFrame(rows)
    for column in ["state_label", "age_bucket", "state_phase", "profile_mode", "state_date_policy", "readiness_status"]:
        if column not in frame.columns:
            frame[column] = "unknown"
        frame[column] = frame[column].fillna("unknown").astype(str)
    frame["horizon_days"] = pd.to_numeric(frame.get("horizon_days"), errors="coerce").astype("Int64")
    for column in ["event_rate", "age_bucket_baseline_event_rate", "sample_count", "positive_count"]:
        if column not in frame.columns:
            frame[column] = pd.NA
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def _select_holdout_window(dataset: pd.DataFrame, *, holdout_trading_days: int) -> tuple[list[Any], str | None, str | None]:
    observed = dataset[dataset.get("censoring_status", "").isin(OBSERVED_STATUSES)].copy()
    if observed.empty:
        return [], None, None
    pivot = observed.groupby(["trade_date", "horizon_days"]).size().unstack(fill_value=0)
    for horizon in EXPECTED_HORIZONS:
        if horizon not in pivot.columns:
            pivot[horizon] = 0
    complete_dates = pivot[(pivot[EXPECTED_HORIZONS] > 0).all(axis=1)].sort_index()
    if complete_dates.empty:
        return [], None, None
    selected = complete_dates.tail(max(1, holdout_trading_days))
    selected_dates = selected.index.tolist()
    return selected_dates, str(selected.index.min()), str(selected.index.max())


def _attach_readiness(holdout: pd.DataFrame, readiness: pd.DataFrame) -> pd.DataFrame:
    work = holdout.copy()
    for column in ["state_label", "state_phase", "profile_mode", "state_date_policy"]:
        if column not in work.columns:
            work[column] = "unknown"
        work[column] = work[column].fillna("unknown").astype(str)
    work["horizon_days"] = pd.to_numeric(work.get("horizon_days"), errors="coerce").astype("Int64")
    work["age_bucket"] = work.get("state_age", pd.Series(index=work.index)).map(age_bucket).fillna("unknown").astype(str)
    merged = work.merge(
        readiness[
            [
                *READINESS_JOIN_COLUMNS,
                "readiness_status",
                "event_rate",
                "age_bucket_baseline_event_rate",
                "sample_count",
                "positive_count",
            ]
        ],
        how="left",
        on=READINESS_JOIN_COLUMNS,
        suffixes=("", "_readiness"),
    )
    merged["readiness_status"] = merged["readiness_status"].fillna("invalid").astype(str)
    merged["_label_observed"] = merged["censoring_status"].isin(OBSERVED_STATUSES)
    merged["_metric_probability"] = np.nan
    usable = merged["readiness_status"].eq("usable_probability")
    baseline = merged["readiness_status"].eq("baseline_only")
    merged.loc[usable, "_metric_probability"] = pd.to_numeric(merged.loc[usable, "event_rate"], errors="coerce")
    merged.loc[baseline, "_metric_probability"] = pd.to_numeric(
        merged.loc[baseline, "age_bucket_baseline_event_rate"],
        errors="coerce",
    )
    merged["_metric_probability_source"] = "abstain"
    merged.loc[usable, "_metric_probability_source"] = "readiness_matrix_event_rate"
    merged.loc[baseline, "_metric_probability_source"] = "age_bucket_baseline_event_rate"
    return merged


def _readiness_counts(rows: pd.DataFrame) -> dict[str, int]:
    counts = rows.get("readiness_status", pd.Series(dtype=str)).value_counts(dropna=False).to_dict()
    return {status: int(counts.get(status, 0)) for status in READINESS_STATUSES}


def _metrics_by_status(rows: pd.DataFrame) -> dict[str, Any]:
    observed = rows[rows["_label_observed"]].copy()
    return {
        status: _metric_summary(observed[observed["readiness_status"].eq(status)])
        for status in READINESS_STATUSES
    }


def _metrics_by_horizon(rows: pd.DataFrame) -> dict[str, Any]:
    observed = rows[rows["_label_observed"]].copy()
    out: dict[str, Any] = {}
    for horizon in EXPECTED_HORIZONS:
        out[str(horizon)] = _metric_summary(observed[pd.to_numeric(observed["horizon_days"], errors="coerce").eq(horizon)])
    return out


def _abstain_coverage(rows: pd.DataFrame) -> dict[str, Any]:
    if rows.empty:
        return {
            "observed_holdout_row_count": 0,
            "probability_metric_row_count": 0,
            "abstain_count": 0,
            "abstain_rate": None,
            "coverage_rate": None,
            "coverage_scope": "readiness-approved usable_probability plus baseline_only fixed baseline probabilities",
        }
    observed = rows[rows["_label_observed"]].copy()
    metric_probabilities = pd.to_numeric(
        observed.get("_metric_probability", pd.Series(index=observed.index)),
        errors="coerce",
    )
    metric_rows = observed[metric_probabilities.notna()]
    total = int(len(observed))
    abstain = int(total - len(metric_rows))
    return {
        "observed_holdout_row_count": total,
        "probability_metric_row_count": int(len(metric_rows)),
        "abstain_count": abstain,
        "abstain_rate": float(abstain / total) if total else None,
        "coverage_rate": float(len(metric_rows) / total) if total else None,
        "coverage_scope": "readiness-approved usable_probability plus baseline_only fixed baseline probabilities",
    }


def _false_confidence_flags(metrics_by_status: Mapping[str, Any], metrics_by_horizon: Mapping[str, Any]) -> list[dict[str, Any]]:
    flags: list[dict[str, Any]] = []
    for status, metric in metrics_by_status.items():
        false_conf = dict(metric.get("false_confidence", {}))
        if _as_int(false_conf.get("false_confidence_row_count")):
            flags.append({"scope": f"readiness_status:{status}", **false_conf})
    for horizon, metric in metrics_by_horizon.items():
        false_conf = dict(metric.get("false_confidence", {}))
        if _as_int(false_conf.get("false_confidence_row_count")):
            flags.append({"scope": f"horizon_days:{horizon}", **false_conf})
    return flags[:20]


def _readiness_status_verdicts(metrics_by_status: Mapping[str, Any], non_overlap_status: str) -> dict[str, Any]:
    verdicts: dict[str, Any] = {}
    for status in READINESS_STATUSES:
        metrics = dict(metrics_by_status.get(status, {}))
        sample_count = _as_int(metrics.get("sample_count"))
        metric_count = _as_int(metrics.get("metric_row_count"))
        if status == "baseline_only" and metric_count:
            verdict = "LOCAL_ONLY"
            reason = "baseline-only rows use fixed age-bucket baseline probabilities, not broad hazard promotion."
        elif sample_count == 0:
            verdict = "DEFER"
            reason = "no holdout rows available for this readiness status."
        elif metric_count == 0:
            verdict = "DEFER"
            reason = "no probability metric rows available for this readiness status."
        elif non_overlap_status != "proven_non_overlap":
            verdict = "DEFER"
            reason = "non-overlap with WP3-WP6.1 evidence is not proven."
        else:
            verdict = "PASS"
            reason = "readiness-status metrics are available under proven non-overlap."
        verdicts[status] = {
            "verdict": verdict,
            "sample_count": sample_count,
            "metric_row_count": metric_count,
            "reason": reason,
        }
    return verdicts


def _reconstructed_non_overlap_evidence(dataset: pd.DataFrame, holdout_start: str | None, holdout_end: str | None) -> dict[str, Any]:
    try:
        from src.evaluation.exit_target_leakage_audit import build_purged_time_split_plan

        plan = build_purged_time_split_plan(dataset, n_splits=3, final_holdout_start=None)
        windows = [
            {
                "split_id": split.split_id,
                "validation_start_date": split.validation_start_date,
                "validation_end_date": split.validation_end_date,
            }
            for split in plan.splits
        ]
    except Exception:
        windows = []
    max_validation_end = max((item["validation_end_date"] for item in windows), default=None)
    overlaps = bool(holdout_start and max_validation_end and str(holdout_start) <= str(max_validation_end))
    return {
        "proof_status": "not_proven",
        "reconstructed_wp3_validation_windows": windows,
        "max_reconstructed_validation_end_date": max_validation_end,
        "candidate_holdout_start_date": holdout_start,
        "candidate_holdout_end_date": holdout_end,
        "candidate_overlaps_reconstructed_prior_validation": "yes" if overlaps else "unknown",
        "wp5_final_holdout_excluded_count": None,
        "metadata_gap": (
            "Accepted WP3-WP6.1 artifacts do not persist an explicit final_holdout_start or "
            "full split-role manifest proving this candidate was excluded from calibration/readiness selection."
        ),
    }


def _forbidden_output_hits(value: Any) -> list[str]:
    hits: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_text = str(key)
            if key_text in DENIAL_FLAG_ALLOWLIST and child == "no":
                continue
            for term in FORBIDDEN_OUTPUT_TERMS:
                if term in key_text:
                    hits.append(f"key:{term}:{key_text}")
            hits.extend(_forbidden_output_hits(child))
    elif isinstance(value, list):
        for child in value:
            hits.extend(_forbidden_output_hits(child))
    elif isinstance(value, str):
        for term in FORBIDDEN_OUTPUT_TERMS:
            if term in value:
                hits.append(f"value:{term}:{value[:80]}")
    return hits


def apply_final_holdout_verdict(summary: dict[str, Any]) -> dict[str, Any]:
    blocking = list(summary.get("blocking_issues", []))
    defer = list(summary.get("defer_reasons", []))
    if _as_int(summary.get("consumption_count")) > 1:
        blocking.append("final holdout consumption count exceeds one")
    if _as_yes(summary.get("tuned_on_holdout")) or _as_yes(summary.get("threshold_tuning_on_holdout")):
        blocking.append("threshold tuning on final holdout detected")
    if _as_yes(summary.get("model_retrained")) or _as_yes(summary.get("HMM_HSMM_retrained")):
        blocking.append("model retraining detected")
    if _as_yes(summary.get("HSMM_p_exit_used_for_decision")):
        blocking.append("HSMM p_exit decision input detected")
    if summary.get("decision_surface_output") not in {None, "no"}:
        blocking.append("surface output detected")
    forbidden_hits = _forbidden_output_hits(summary)
    if forbidden_hits:
        blocking.append(f"forbidden output terms detected: {forbidden_hits[:5]}")

    if blocking:
        summary["blocking_issues"] = sorted(set(blocking))
        summary["defer_reasons"] = defer
        summary["empirical_promotion_verdict"] = "BLOCKED"
        summary["final_recommendation"] = "BLOCKED: remediate final holdout artifact boundary violations."
        summary["status"] = "blocked"
        return summary

    if summary.get("db_opened_read_only") != "yes":
        defer.append("local DuckDB was not available read-only; final holdout metrics were not produced.")
    if summary.get("non_overlap_status") != "proven_non_overlap":
        defer.append("non-overlap with WP3-WP6.1 calibration/readiness evidence is not proven.")
    if _as_int(summary.get("observed_metric_row_count")) <= 0:
        defer.append("no observed probability metric rows were available for broad empirical promotion.")

    baseline_count = _as_int(summary.get("readiness_status_counts", {}).get("baseline_only"))
    usable_count = _as_int(summary.get("readiness_status_counts", {}).get("usable_probability"))
    if defer:
        summary["empirical_promotion_verdict"] = "DEFER"
        summary["final_recommendation"] = "DEFER: preserve local-slice hazard scope until non-overlap evidence is explicit."
        summary["status"] = "defer"
    elif baseline_count > usable_count:
        summary["empirical_promotion_verdict"] = "LOCAL_ONLY"
        summary["final_recommendation"] = "LOCAL_ONLY: hazard probability remains local-slice only; baseline_only remains majority."
        summary["status"] = "defer"
    else:
        summary["empirical_promotion_verdict"] = "PASS"
        summary["final_recommendation"] = "PASS: final holdout artifact supports the registered empirical promotion contract."
        summary["status"] = "pass"
    summary["blocking_issues"] = []
    summary["defer_reasons"] = sorted(set(defer))
    return summary


def _empty_defer_result(db_path: str | None, reason: str, local_db: Mapping[str, Any]) -> FinalHoldoutArtifactResult:
    summary = {
        "status": "defer",
        "artifact_version": ARTIFACT_VERSION,
        "index_id": INDEX_ID,
        "source_db": _safe_source_path(Path(db_path)) if db_path else None,
        "db_opened_read_only": local_db.get("opened_read_only", "no"),
        "external_data_fetch": "no",
        "holdout_policy": {"policy": "latest_complete_observed_horizon_window", "holdout_trading_days": 0},
        "holdout_start_date": None,
        "holdout_end_date": None,
        "holdout_status": "holdout_candidate",
        "holdout_selection_reason": reason,
        "non_overlap_status": "not_evaluated",
        "non_overlap_evidence": {"proof_status": "not_evaluated", "reason": reason},
        "consumption_count": 0,
        "consumed_in_wp10": "no",
        "tuned_on_holdout": "no",
        "threshold_tuning_on_holdout": "no",
        "model_retrained": "no",
        "HMM_HSMM_retrained": "no",
        "HSMM_p_exit_used_for_decision": "no",
        "decision_surface_output": "no",
        "readiness_status_counts": {status: 0 for status in READINESS_STATUSES},
        "metrics_by_readiness_status": {status: _metric_summary(pd.DataFrame()) for status in READINESS_STATUSES},
        "readiness_status_verdicts": {
            status: {
                "verdict": "DEFER",
                "sample_count": 0,
                "metric_row_count": 0,
                "reason": reason,
            }
            for status in READINESS_STATUSES
        },
        "metrics_by_horizon": {str(h): _metric_summary(pd.DataFrame()) for h in EXPECTED_HORIZONS},
        "usable_probability_metrics": _metric_summary(pd.DataFrame()),
        "baseline_only_metrics": _metric_summary(pd.DataFrame()),
        "insufficient_sample_metrics": _metric_summary(pd.DataFrame()),
        "abstain_coverage": _abstain_coverage(pd.DataFrame(columns=["_label_observed", "_metric_probability"])),
        "false_confidence_flags": [],
        "blocking_issues": [],
        "defer_reasons": [reason],
        "empirical_promotion_verdict": "DEFER",
        "final_recommendation": "DEFER: final holdout artifact could not be built from local DB.",
        "local_db_status": dict(local_db),
        "holdout_row_count": 0,
        "observed_metric_row_count": 0,
        "warnings": [],
    }
    return FinalHoldoutArtifactResult(**apply_final_holdout_verdict(summary))


def evaluate_final_holdout_artifact(
    *,
    db_path: str | None,
    hazard_readiness_path: Path,
    risk_protocol_path: Path,
    data_quality_path: Path,
    holdout_trading_days: int = 20,
) -> FinalHoldoutArtifactResult:
    local_db = _local_db_status(db_path)
    safe_db = _safe_source_path(Path(db_path)) if db_path else None
    if not db_path or local_db.get("opened_read_only") != "yes":
        return _empty_defer_result(db_path, "local DB missing or not opened read-only", local_db)

    hazard_readiness = _load_json(hazard_readiness_path)
    risk_protocol = _load_json(risk_protocol_path)
    data_quality = _load_json(data_quality_path)
    dataset, source = _dataset_from_db(argparse.Namespace(db=db_path, run_id="latest", horizons="1,3,5,10,20"))
    if dataset.empty:
        return _empty_defer_result(db_path, f"empty exit target dataset from {source}", local_db)

    selected_dates, holdout_start, holdout_end = _select_holdout_window(
        dataset,
        holdout_trading_days=holdout_trading_days,
    )
    if not selected_dates:
        return _empty_defer_result(db_path, "no complete observed horizon window available", local_db)

    readiness = _prepare_readiness_frame(hazard_readiness)
    holdout = dataset[dataset["trade_date"].isin(selected_dates)].copy()
    holdout_with_readiness = _attach_readiness(holdout, readiness)
    metrics_input = holdout_with_readiness[holdout_with_readiness["_label_observed"]].copy()

    metrics_by_status = _metrics_by_status(holdout_with_readiness)
    metrics_by_horizon = _metrics_by_horizon(holdout_with_readiness)
    counts = _readiness_counts(holdout_with_readiness)
    abstain = _abstain_coverage(holdout_with_readiness)
    false_flags = _false_confidence_flags(metrics_by_status, metrics_by_horizon)
    non_overlap = _reconstructed_non_overlap_evidence(dataset, holdout_start, holdout_end)
    non_overlap_status = "not_proven"
    readiness_verdicts = _readiness_status_verdicts(metrics_by_status, non_overlap_status)
    non_overlap["wp5_final_holdout_excluded_count"] = _as_int(
        _load_json(Path("reports/stage03r/hazard_isotonic_calibration_report.json")).get(
            "final_holdout_excluded_count",
            0,
        )
    ) if Path("reports/stage03r/hazard_isotonic_calibration_report.json").exists() else None
    protocol_rule = risk_protocol.get("split_and_final_holdout_discipline", {})
    data_quality_status = data_quality.get("status")

    summary = {
        "status": "defer",
        "artifact_version": ARTIFACT_VERSION,
        "index_id": INDEX_ID,
        "source_db": safe_db,
        "db_opened_read_only": "yes",
        "external_data_fetch": "no",
        "holdout_policy": {
            "policy": "latest_complete_observed_horizon_window",
            "holdout_trading_days": int(holdout_trading_days),
            "expected_horizons": EXPECTED_HORIZONS,
            "observed_statuses": sorted(OBSERVED_STATUSES),
            "right_censored_rows_excluded_from_metrics": "yes",
        },
        "holdout_start_date": holdout_start,
        "holdout_end_date": holdout_end,
        "holdout_status": "holdout_candidate",
        "holdout_selection_reason": (
            "latest deterministic trade-date window with observed labels available for all registered horizons"
        ),
        "non_overlap_status": non_overlap_status,
        "non_overlap_evidence": non_overlap,
        "consumption_count": 1,
        "consumed_in_wp10": "yes",
        "tuned_on_holdout": "no",
        "threshold_tuning_on_holdout": "no",
        "model_retrained": "no",
        "HMM_HSMM_retrained": "no",
        "HSMM_p_exit_used_for_decision": "no",
        "decision_surface_output": "no",
        "readiness_status_counts": counts,
        "metrics_by_readiness_status": metrics_by_status,
        "readiness_status_verdicts": readiness_verdicts,
        "metrics_by_horizon": metrics_by_horizon,
        "usable_probability_metrics": metrics_by_status.get("usable_probability", {}),
        "baseline_only_metrics": metrics_by_status.get("baseline_only", {}),
        "insufficient_sample_metrics": metrics_by_status.get("insufficient_sample", {}),
        "abstain_coverage": abstain,
        "false_confidence_flags": false_flags,
        "blocking_issues": [],
        "defer_reasons": [],
        "empirical_promotion_verdict": "DEFER",
        "final_recommendation": "",
        "local_db_status": dict(local_db),
        "holdout_row_count": int(len(holdout_with_readiness)),
        "observed_metric_row_count": int(
            pd.to_numeric(metrics_input.get("_metric_probability"), errors="coerce").notna().sum()
        ),
        "warnings": [
            "No model was retrained; metrics use fixed probabilities from accepted readiness/baseline artifacts.",
            "Exact non-overlap is not proven because prior artifacts lack a locked final_holdout_start manifest.",
            f"risk_protocol_final_holdout_rule={protocol_rule.get('final_holdout_consumption') if isinstance(protocol_rule, dict) else None}",
            f"data_quality_ci_status={data_quality_status}",
        ],
    }
    return FinalHoldoutArtifactResult(**apply_final_holdout_verdict(summary))


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    sections = [
        "# Stage03R WP10.1 Final Holdout Artifact",
        "",
        f"status: {summary.get('status')}",
        f"artifact_version: {summary.get('artifact_version')}",
        f"empirical_promotion_verdict: {summary.get('empirical_promotion_verdict')}",
        f"holdout_start_date: {summary.get('holdout_start_date')}",
        f"holdout_end_date: {summary.get('holdout_end_date')}",
        f"holdout_status: {summary.get('holdout_status')}",
        f"non_overlap_status: {summary.get('non_overlap_status')}",
        f"consumption_count: {summary.get('consumption_count')}",
        "",
        "## Holdout policy",
        "",
        "```json",
        json.dumps(summary.get("holdout_policy", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Non-overlap evidence",
        "",
        "```json",
        json.dumps(summary.get("non_overlap_evidence", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Metrics by readiness status",
        "",
        "```json",
        json.dumps(summary.get("metrics_by_readiness_status", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Verdicts by readiness status",
        "",
        "```json",
        json.dumps(summary.get("readiness_status_verdicts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Metrics by horizon",
        "",
        "```json",
        json.dumps(summary.get("metrics_by_horizon", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Abstain and false confidence",
        "",
        "```json",
        json.dumps(
            {
                "abstain_coverage": summary.get("abstain_coverage", {}),
                "false_confidence_flags": summary.get("false_confidence_flags", []),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        "```",
        "",
        "## Boundary confirmation",
        "",
        "- external_data_fetch: no",
        f"- db_opened_read_only: {summary.get('db_opened_read_only')}",
        "- model_retrained: no",
        "- threshold_tuning_on_holdout: no",
        "- HSMM_p_exit_used_for_decision: no",
        "- DuckDB_committed: no",
        "",
        "## Blocking issues",
        "",
        "```json",
        json.dumps(summary.get("blocking_issues", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Defer reasons",
        "",
        "```json",
        json.dumps(summary.get("defer_reasons", []), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Final recommendation",
        "",
        str(summary.get("final_recommendation")),
    ]
    return "\n".join(sections) + "\n"


def write_outputs(result: FinalHoldoutArtifactResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def run_cli(args: argparse.Namespace) -> int:
    result = evaluate_final_holdout_artifact(
        db_path=args.db,
        hazard_readiness_path=Path(args.hazard_readiness),
        risk_protocol_path=Path(args.risk_protocol),
        data_quality_path=Path(args.data_quality),
        holdout_trading_days=args.holdout_trading_days,
    )
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 1 if result.status == "blocked" else 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R WP10.1 final holdout artifact")
    parser.add_argument("--db", default=None)
    parser.add_argument("--hazard-readiness", required=True)
    parser.add_argument("--risk-protocol", required=True)
    parser.add_argument("--data-quality", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--summary-json", required=True)
    parser.add_argument("--holdout-trading-days", type=int, default=20)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
