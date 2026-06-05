from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.config import PROJECT_ROOT
from src.evaluation import stage04_break_detector


REPORT_VERSION = "stage04_wp2_break_casebook_v1"
SCHEMA_VERSION = "stage04_break_annotation_v1"
INDEX_ID = "STAGE04-WP2"
SOURCE_INDEX_ID = "STAGE04-WP1"

DEFAULT_DB_PATH = Path("data/db/a_share_hmm.duckdb")
DEFAULT_SPLIT_REGISTRY_PATH = Path("reports/stage04/split_registry.json")
DEFAULT_WP1_SUMMARY_PATH = Path("reports/stage04/stage04_wp1_break_detector_report.json")
DEFAULT_OUTPUT_PATH = Path("reports/stage04/stage04_wp2_break_casebook_report.md")
DEFAULT_SUMMARY_JSON_PATH = Path("reports/stage04/stage04_wp2_break_casebook_report.json")
DEFAULT_SAMPLE_CSV_PATH = Path("reports/stage04/stage04_wp2_break_casebook_sample.csv")
DEFAULT_ANNOTATION_TEMPLATE_PATH = Path("reports/stage04/prospective_break_annotation.template.jsonl")
LOCAL_ANNOTATION_PATH = Path("reports/stage04/prospective_break_annotation.local.jsonl")

WARNING_LEVEL_RANK = {
    "high": 4,
    "elevated": 3,
    "watch": 2,
    "insufficient_data": 1,
    "normal": 0,
}
WARNING_LEVELS = {"watch", "elevated", "high"}
DEFAULT_MAX_CASES = 20
DEFAULT_MAX_CONTIGUOUS_GAP_DAYS = 7

BOUNDARY_FLAGS = {
    "external_data_fetch": "no",
    "model_retrained": "no",
    "hmm_hsmm_training_changed": "no",
    "hazard_model_changed": "no",
    "threshold_tuning": "no",
    "final_holdout_consumed": "no",
    "decision_engine_output": "no",
    "trading_output": "no",
    "duckdb_schema_changed": "no",
    "duckdb_committed": "no",
}

FORBIDDEN_OUTPUT_TERMS = (
    "decision_ready",
    "decision_surface",
    "risk_downshift",
    "trade_signal",
    "buy_signal",
    "sell_signal",
)


@dataclass(frozen=True)
class BreakCasebookConfig:
    db_path: Path = DEFAULT_DB_PATH
    split_registry_path: Path = DEFAULT_SPLIT_REGISTRY_PATH
    wp1_summary_path: Path = DEFAULT_WP1_SUMMARY_PATH
    max_cases: int = DEFAULT_MAX_CASES
    max_contiguous_gap_days: int = DEFAULT_MAX_CONTIGUOUS_GAP_DAYS


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
        return raw.as_posix()
    try:
        return raw.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return f"<local:{raw.name}>"


def load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {_public_path(path)}")
    return payload


def _level_rank(level: Any) -> int:
    return WARNING_LEVEL_RANK.get(str(level), -1)


def _peak_warning_level(levels: pd.Series) -> str:
    values = [str(level) for level in levels.dropna().tolist()]
    return max(values, key=_level_rank) if values else "normal"


def _label_components(labels: Any) -> list[str]:
    if labels is None or pd.isna(labels):
        return []
    components: list[str] = []
    for item in str(labels).split(";"):
        if not item:
            continue
        components.append(item.split(":", 1)[0])
    return components


def _dominant_components(labels: pd.Series) -> list[str]:
    counts: dict[str, int] = {}
    for value in labels.tolist():
        for component in _label_components(value):
            counts[component] = counts.get(component, 0) + 1
    return [name for name, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _max_numeric(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    return _json_safe(values.max()) if values.notna().any() else None


def _min_numeric(frame: pd.DataFrame, column: str) -> Any:
    if column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce")
    return _json_safe(values.min()) if values.notna().any() else None


def _warning_level_counts(frame: pd.DataFrame) -> dict[str, int]:
    if "break_warning_level" not in frame.columns:
        return {}
    counts = frame["break_warning_level"].astype(str).value_counts().to_dict()
    return {level: int(counts.get(level, 0)) for level in ["watch", "elevated", "high"] if counts.get(level, 0)}


def _peak_component_stress_labels(frame: pd.DataFrame, peak_level: str) -> str:
    if "component_stress_labels" not in frame.columns:
        return ""
    peak_rows = frame[frame["break_warning_level"].astype(str) == peak_level]
    candidates = peak_rows["component_stress_labels"].dropna().astype(str)
    candidates = candidates[candidates != ""]
    if not candidates.empty:
        return str(candidates.iloc[-1])
    all_labels = frame["component_stress_labels"].dropna().astype(str)
    all_labels = all_labels[all_labels != ""]
    return "" if all_labels.empty else str(all_labels.iloc[-1])


def _first_component_stress_labels(frame: pd.DataFrame) -> str:
    if "component_stress_labels" not in frame.columns:
        return ""
    values = frame["component_stress_labels"].dropna().astype(str)
    values = values[values != ""]
    return "" if values.empty else str(values.iloc[0])


def _data_availability_notes(frame: pd.DataFrame) -> list[str]:
    notes: list[str] = []
    component_columns = [
        "market_component_present",
        "breadth_component_present",
        "sector_component_present",
        "hmm_confidence_component_present",
    ]
    for column in component_columns:
        if column in frame.columns and not frame[column].fillna(False).astype(bool).all():
            notes.append(f"{column.replace('_component_present', '')} missing on at least one episode row")
    if not notes:
        notes.append("available components remained present across episode rows")
    return notes


def extract_warning_episodes(
    diagnostic: pd.DataFrame,
    *,
    max_contiguous_gap_days: int = DEFAULT_MAX_CONTIGUOUS_GAP_DAYS,
) -> list[dict[str, Any]]:
    if diagnostic.empty or "trade_date" not in diagnostic.columns or "break_warning_level" not in diagnostic.columns:
        return []
    data = diagnostic.copy()
    data["trade_date_dt"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data[data["trade_date_dt"].notna()].sort_values("trade_date_dt").reset_index(drop=True)
    episodes: list[pd.DataFrame] = []
    current_indices: list[int] = []
    previous_date: pd.Timestamp | None = None
    for idx, row in data.iterrows():
        level = str(row["break_warning_level"])
        trade_date = row["trade_date_dt"]
        is_warning = level in WARNING_LEVELS
        gap_break = previous_date is not None and (trade_date - previous_date).days > max_contiguous_gap_days
        if not is_warning or gap_break:
            if current_indices:
                episodes.append(data.loc[current_indices].copy())
                current_indices = []
        if is_warning:
            current_indices.append(idx)
        previous_date = trade_date
    if current_indices:
        episodes.append(data.loc[current_indices].copy())

    out: list[dict[str, Any]] = []
    latest_diagnostic_date = data["trade_date_dt"].max()
    for ordinal, frame in enumerate(episodes, start=1):
        start = frame["trade_date_dt"].min()
        end = frame["trade_date_dt"].max()
        peak = _peak_warning_level(frame["break_warning_level"])
        first_labels = _first_component_stress_labels(frame)
        peak_labels = _peak_component_stress_labels(frame, peak)
        breadth_proxy_candidates = [
            _max_numeric(frame, "breadth_stress_score"),
            _max_numeric(frame, "breadth_amount_z"),
            _max_numeric(frame, "breadth_up_ratio_z"),
        ]
        breadth_proxy = max(
            [value for value in breadth_proxy_candidates if isinstance(value, (int, float))],
            default=None,
        )
        hmm_values = [
            _max_numeric(frame, "hmm_stress_score"),
            _max_numeric(frame, "hmm_entropy_mean"),
        ]
        hmm_proxy = max([value for value in hmm_values if isinstance(value, (int, float))], default=None)
        out.append(
            {
                "episode_id": f"stage04-wp2-episode-{ordinal:03d}",
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "duration_observations": int(len(frame)),
                "peak_warning_level": peak,
                "severity_rank": _level_rank(peak),
                "warning_level_counts": _warning_level_counts(frame),
                "peak_component_stress_labels": peak_labels,
                "first_component_stress_labels": first_labels,
                "dominant_components": _dominant_components(frame.get("component_stress_labels", pd.Series(dtype="object"))),
                "max_market_volatility_z": _max_numeric(frame, "market_volatility_z"),
                "min_market_return_1d": _min_numeric(frame, "market_return_1d"),
                "max_breadth_stress_proxy": _json_safe(breadth_proxy),
                "max_sector_dispersion_z": _max_numeric(frame, "sector_dispersion_z"),
                "max_hmm_entropy_or_stress": _json_safe(hmm_proxy),
                "available_component_count_max": _max_numeric(frame, "available_component_count"),
                "data_availability_notes": _data_availability_notes(frame),
                "is_latest_active_episode": "yes" if end == latest_diagnostic_date else "no",
                "annotation_status": "unreviewed",
            }
        )
    return out


def build_casebook_sample(episodes: list[dict[str, Any]], *, max_cases: int = DEFAULT_MAX_CASES) -> list[dict[str, Any]]:
    if not episodes:
        return []
    ordered = sorted(episodes, key=lambda row: (int(row.get("severity_rank", -1)), str(row.get("end_date", ""))), reverse=True)
    sample = ordered[:max_cases]
    latest_active_candidates = [row for row in episodes if row.get("is_latest_active_episode") == "yes"]
    latest_active = max(latest_active_candidates, key=lambda row: str(row.get("end_date", "")), default=None)
    if latest_active and latest_active.get("peak_warning_level") in WARNING_LEVELS and latest_active["episode_id"] not in {row["episode_id"] for row in sample}:
        sample = sample[:-1] + [latest_active] if len(sample) >= max_cases else sample + [latest_active]
    sample = sorted(sample, key=lambda row: (int(row.get("severity_rank", -1)), str(row.get("end_date", ""))), reverse=True)
    return [{key: value for key, value in row.items() if key != "severity_rank"} for row in sample]


def _validate_split_registry_lock(registry: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    policy = registry.get("future_holdout_policy", {}) if registry else {}
    boundary = registry.get("boundary_flags", {}) if registry else {}

    checks = {
        "status": registry.get("status") if registry else None,
        "evidence_cutoff_date": registry.get("evidence_cutoff_date") if registry else None,
        "future_holdout_start_rule": registry.get("future_holdout_start_rule") if registry else None,
        "final_holdout_consumption_count": registry.get("final_holdout_consumption_count", boundary.get("final_holdout_consumption_count")),
        "threshold_tuning_after_lock": registry.get("threshold_tuning_after_lock") if registry else None,
        "model_retraining_after_lock": registry.get("model_retraining_after_lock") if registry else None,
        "decision_layer_output": registry.get("decision_surface_output") if registry else None,
        "external_data_fetch": registry.get("external_data_fetch") if registry else None,
        "expected_horizons": registry.get("expected_horizons") if registry else None,
        "minimum_candidate_holdout_start_date": policy.get("minimum_candidate_holdout_start_date"),
    }

    if not registry:
        issues.append("Stage04-WP0 split registry not found")
    if registry and checks["status"] != "locked":
        issues.append("split registry status is not locked")
    if registry and not checks["evidence_cutoff_date"]:
        issues.append("split registry evidence_cutoff_date is missing")
    if registry and checks["future_holdout_start_rule"] != "strictly_after_evidence_cutoff_date":
        issues.append("future holdout start rule is not strictly_after_evidence_cutoff_date")
    if registry and int(checks["final_holdout_consumption_count"] or 0) != 0:
        issues.append("final holdout consumption count is not zero")
    if registry and checks["threshold_tuning_after_lock"] != "forbidden":
        issues.append("threshold tuning after lock is not forbidden")
    if registry and checks["model_retraining_after_lock"] != "forbidden":
        issues.append("model retraining after lock is not forbidden")
    if registry and checks["decision_layer_output"] != "no":
        issues.append("locked registry does not forbid decision-layer output")
    if registry and checks["external_data_fetch"] != "no":
        issues.append("locked registry does not forbid external data fetch")

    summary = {
        "status": checks["status"] or "missing",
        "evidence_cutoff_date": checks["evidence_cutoff_date"],
        "future_holdout_start_rule": checks["future_holdout_start_rule"],
        "expected_horizons": checks["expected_horizons"] or [],
        "minimum_candidate_holdout_start_date": checks["minimum_candidate_holdout_start_date"],
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": int(checks["final_holdout_consumption_count"] or 0)
        if checks["final_holdout_consumption_count"] is not None
        else None,
        "threshold_tuning_after_lock": "no" if checks["threshold_tuning_after_lock"] == "forbidden" else checks["threshold_tuning_after_lock"],
        "model_retraining_after_lock": "no" if checks["model_retraining_after_lock"] == "forbidden" else checks["model_retraining_after_lock"],
        "decision_layer_output": checks["decision_layer_output"],
        "external_data_fetch": checks["external_data_fetch"],
    }
    return summary, issues


def build_annotation_template_record() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "template",
        "annotation_date": "<YYYY-MM-DD>",
        "diagnostic_trade_date": "<YYYY-MM-DD>",
        "break_warning_level": "watch|elevated|high",
        "component_stress_labels": "<component:level labels from casebook>",
        "available_component_count": "<integer>",
        "analyst_annotation": "confirmed_break|benign_noise|needs_context|insufficient_context",
        "observed_market_context": "<public-safe research note>",
        "followup_required": "yes|no",
        "forbidden_use_notice": "Research annotation only; not a trading signal, not a decision layer, and not empirical promotion evidence.",
        "boundary_flags": BOUNDARY_FLAGS,
    }


def _annotation_protocol_summary(annotation_template_path: Path) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "record_type": "template",
        "template_path": _public_path(annotation_template_path),
        "local_annotation_path": LOCAL_ANNOTATION_PATH.as_posix(),
        "local_annotations_gitignored": "yes",
        "required_fields": [
            "schema_version",
            "record_type",
            "annotation_date",
            "diagnostic_trade_date",
            "break_warning_level",
            "component_stress_labels",
            "available_component_count",
            "analyst_annotation",
            "observed_market_context",
            "followup_required",
            "forbidden_use_notice",
            "boundary_flags",
        ],
        "forbidden_use_notice": build_annotation_template_record()["forbidden_use_notice"],
    }


def _episode_summary(episodes: list[dict[str, Any]]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for episode in episodes:
        level = str(episode.get("peak_warning_level"))
        counts[level] = counts.get(level, 0) + 1
    return {
        "episode_count": len(episodes),
        "peak_warning_level_counts": dict(sorted(counts.items())),
        "earliest_episode_start": min((str(row["start_date"]) for row in episodes), default=None),
        "latest_episode_end": max((str(row["end_date"]) for row in episodes), default=None),
    }


def _blocked_defer_reasons(blocking_issues: list[str]) -> list[str]:
    reasons: list[str] = []
    if any("DuckDB" in issue for issue in blocking_issues):
        reasons.append("case extraction requires full in-memory Stage04-WP1 diagnostics from the local DuckDB")
    if any("WP1" in issue for issue in blocking_issues):
        reasons.append("Stage04-WP1 report evidence is unavailable or not passing")
    if any("registry" in issue.lower() for issue in blocking_issues):
        reasons.append("Stage04-WP0 prospective split lock is not proven")
    return reasons


def _wp1_full_diagnostic_from_db(db_path: Path) -> tuple[dict[str, Any], pd.DataFrame]:
    return stage04_break_detector.evaluate_break_detector(stage04_break_detector.BreakDetectorConfig(db_path=db_path))


def _wp1_committed_latest_date(wp1_summary: dict[str, Any]) -> pd.Timestamp | None:
    candidates = [
        (wp1_summary.get("latest_break_warning") or {}).get("trade_date"),
        (wp1_summary.get("data_quality_summary") or {}).get("latest_trade_date"),
    ]
    for candidate in candidates:
        if candidate:
            parsed = pd.to_datetime(candidate, errors="coerce")
            if not pd.isna(parsed):
                return parsed
    return None


def _cap_diagnostic_to_wp1_range(diagnostic: pd.DataFrame, latest_date: pd.Timestamp | None) -> pd.DataFrame:
    if diagnostic.empty or latest_date is None or "trade_date" not in diagnostic.columns:
        return diagnostic
    data = diagnostic.copy()
    trade_dates = pd.to_datetime(data["trade_date"], errors="coerce")
    return data[trade_dates.notna() & (trade_dates <= latest_date)].copy()


def _latest_diagnostic_snapshot(diagnostic: pd.DataFrame, fallback: dict[str, Any]) -> dict[str, Any]:
    if diagnostic.empty or "trade_date" not in diagnostic.columns:
        return fallback.get("latest_break_warning") or {}
    data = diagnostic.copy()
    data["trade_date_dt"] = pd.to_datetime(data["trade_date"], errors="coerce")
    data = data[data["trade_date_dt"].notna()].sort_values("trade_date_dt")
    if data.empty:
        return fallback.get("latest_break_warning") or {}
    row = data.iloc[-1]
    return {
        "trade_date": row["trade_date_dt"].date().isoformat(),
        "break_warning_level": str(row.get("break_warning_level")),
    }


def evaluate_casebook(config: BreakCasebookConfig) -> dict[str, Any]:
    registry = load_json_object(config.split_registry_path)
    wp1_committed_summary = load_json_object(config.wp1_summary_path)
    split_summary, lock_issues = _validate_split_registry_lock(registry)

    blocking_issues: list[str] = list(lock_issues)
    wp1_full_summary: dict[str, Any] = {}
    diagnostic = pd.DataFrame()
    db_exists = config.db_path.exists()

    if not wp1_committed_summary:
        blocking_issues.append("Stage04-WP1 summary JSON not found")
    elif wp1_committed_summary.get("index_id") != SOURCE_INDEX_ID:
        blocking_issues.append("Stage04-WP1 summary index_id mismatch")
    elif wp1_committed_summary.get("status") != "pass":
        blocking_issues.append("Stage04-WP1 summary status is not pass")

    if not db_exists:
        blocking_issues.append("local DuckDB not found")
    else:
        wp1_full_summary, diagnostic = _wp1_full_diagnostic_from_db(config.db_path)
        if wp1_full_summary.get("status") != "pass":
            blocking_issues.append("regenerated Stage04-WP1 diagnostics are not pass")
        committed_latest_date = _wp1_committed_latest_date(wp1_committed_summary)
        diagnostic = _cap_diagnostic_to_wp1_range(diagnostic, committed_latest_date)
        if diagnostic.empty:
            blocking_issues.append("regenerated Stage04-WP1 diagnostics are empty")

    episodes = [] if blocking_issues else extract_warning_episodes(diagnostic, max_contiguous_gap_days=config.max_contiguous_gap_days)
    if db_exists and not blocking_issues and not episodes:
        blocking_issues.append("no warning episodes could be extracted")
    casebook_sample = build_casebook_sample(episodes, max_cases=config.max_cases) if episodes else []
    if episodes and not casebook_sample:
        blocking_issues.append("casebook sample is empty")

    latest = _latest_diagnostic_snapshot(diagnostic, wp1_committed_summary)
    diagnostic_rows = int(len(diagnostic)) if db_exists else 0
    summary = {
        "status": "blocked" if blocking_issues else "pass",
        "report_version": REPORT_VERSION,
        "index_id": INDEX_ID,
        "source_wp1_report_version": wp1_committed_summary.get("report_version"),
        "split_registry_lock_summary": split_summary,
        "boundary_flags": BOUNDARY_FLAGS,
        "input_summary": {
            "db_available": "yes" if db_exists else "no",
            "db_path": _public_path(config.db_path),
            "wp1_summary_path": _public_path(config.wp1_summary_path),
            "split_registry_path": _public_path(config.split_registry_path),
            "wp1_committed_status": wp1_committed_summary.get("status"),
            "wp1_regenerated_status": wp1_full_summary.get("status"),
            "wp1_committed_latest_trade_date": _json_safe(_wp1_committed_latest_date(wp1_committed_summary)),
            "wp1_regenerated_latest_trade_date": (wp1_full_summary.get("data_quality_summary") or {}).get("latest_trade_date"),
            "diagnostic_rows": diagnostic_rows,
            "latest_diagnostic_trade_date": latest.get("trade_date"),
            "latest_break_warning_level": latest.get("break_warning_level"),
        },
        "episode_summary": _episode_summary(episodes),
        "casebook_sample": casebook_sample,
        "prospective_annotation_protocol": _annotation_protocol_summary(DEFAULT_ANNOTATION_TEMPLATE_PATH),
        "prospective_validation_status": "not_started" if blocking_issues else "annotation_only",
        "causal_boundary_summary": {
            "source_wp1_index_id": SOURCE_INDEX_ID,
            "source_wp1_rolling_baseline_excludes_current_row": (
                (wp1_full_summary or wp1_committed_summary).get("causal_sanity_summary", {}).get("rolling_baseline_excludes_current_row")
            ),
            "future_rows_used": (wp1_full_summary or wp1_committed_summary).get("causal_sanity_summary", {}).get("future_rows_used"),
            "casebook_source": "full_in_memory_wp1_diagnostic" if db_exists and diagnostic_rows else "none_missing_local_db",
            "casebook_capped_to_committed_wp1_range": "yes" if db_exists and diagnostic_rows else "not_applicable",
            "full_diagnostic_csv_written": "no",
        },
        "final_holdout_consumed": "no",
        "final_holdout_consumption_count": 0,
        "threshold_tuning_after_lock": "no",
        "model_retraining_after_lock": "no",
        "blocking_issues": blocking_issues,
        "defer_reasons": _blocked_defer_reasons(blocking_issues),
        "recommended_next_stage": "Collect local prospective annotations before any later package considers promotion criteria.",
    }
    _assert_no_forbidden_terms(summary)
    return summary


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Stage04-WP2 Break Diagnostic Casebook",
        "",
        f"- status: {summary.get('status')}",
        f"- report_version: {summary.get('report_version')}",
        f"- index_id: {summary.get('index_id')}",
        f"- source_wp1_report_version: {summary.get('source_wp1_report_version')}",
        "",
        "This report is annotation infrastructure only and does not provide trading, sizing, ranking, or decision output.",
        "",
        "## Boundary Flags",
    ]
    for key, value in summary.get("boundary_flags", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Split Registry Lock"])
    for key, value in summary.get("split_registry_lock_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Input Summary"])
    for key, value in summary.get("input_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Episode Summary"])
    for key, value in summary.get("episode_summary", {}).items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Casebook Sample"])
    rows = summary.get("casebook_sample", [])
    if rows:
        lines.append("| episode_id | start_date | end_date | duration | peak_warning_level | dominant_components |")
        lines.append("|---|---:|---:|---:|---|---|")
        for row in rows:
            components = ",".join(row.get("dominant_components", []))
            lines.append(
                f"| {row.get('episode_id')} | {row.get('start_date')} | {row.get('end_date')} | "
                f"{row.get('duration_observations')} | {row.get('peak_warning_level')} | {components} |"
            )
    else:
        lines.append("- none")

    protocol = summary.get("prospective_annotation_protocol", {})
    lines.extend(["", "## Prospective Annotation Protocol"])
    for key, value in protocol.items():
        lines.append(f"- {key}: {value}")

    lines.extend(["", "## Prospective Validation Status", str(summary.get("prospective_validation_status")), ""])

    lines.extend(["## Causal Boundary"])
    for key, value in summary.get("causal_boundary_summary", {}).items():
        lines.append(f"- {key}: {value}")

    if summary.get("blocking_issues"):
        lines.extend(["", "## Blocking Issues"])
        for issue in summary.get("blocking_issues", []):
            lines.append(f"- {issue}")
    if summary.get("defer_reasons"):
        lines.extend(["", "## Defer Reasons"])
        for reason in summary.get("defer_reasons", []):
            lines.append(f"- {reason}")

    lines.extend(["", "## Recommended Next Stage", str(summary.get("recommended_next_stage", "")), ""])
    markdown = "\n".join(lines)
    _assert_no_forbidden_terms(summary, markdown)
    return markdown


def _assert_no_forbidden_terms(summary: dict[str, Any], markdown: str = "") -> None:
    payload = json.dumps(_json_safe(summary), ensure_ascii=False) + "\n" + markdown
    hits = [term for term in FORBIDDEN_OUTPUT_TERMS if term in payload]
    if hits:
        raise ValueError(f"Stage04-WP2 report contains forbidden terms: {sorted(set(hits))}")


def _sample_frame(casebook_sample: list[dict[str, Any]]) -> pd.DataFrame:
    columns = [
        "episode_id",
        "start_date",
        "end_date",
        "duration_observations",
        "peak_warning_level",
        "warning_level_counts",
        "peak_component_stress_labels",
        "first_component_stress_labels",
        "dominant_components",
        "max_market_volatility_z",
        "min_market_return_1d",
        "max_breadth_stress_proxy",
        "max_sector_dispersion_z",
        "max_hmm_entropy_or_stress",
        "available_component_count_max",
        "data_availability_notes",
        "annotation_status",
    ]
    rows = []
    for row in casebook_sample:
        flat = dict(row)
        flat["warning_level_counts"] = json.dumps(row.get("warning_level_counts", {}), sort_keys=True)
        flat["dominant_components"] = ";".join(row.get("dominant_components", []))
        flat["data_availability_notes"] = ";".join(row.get("data_availability_notes", []))
        rows.append(flat)
    return pd.DataFrame(rows, columns=columns)


def write_outputs(
    summary: dict[str, Any],
    *,
    output: Path,
    summary_json: Path,
    sample_csv: Path,
    annotation_template: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    sample_csv.parent.mkdir(parents=True, exist_ok=True)
    annotation_template.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _sample_frame(summary.get("casebook_sample", [])).to_csv(sample_csv, index=False)
    annotation_template.write_text(
        json.dumps(build_annotation_template_record(), ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def run_from_paths(
    *,
    db: Path = DEFAULT_DB_PATH,
    split_registry: Path = DEFAULT_SPLIT_REGISTRY_PATH,
    wp1_summary: Path = DEFAULT_WP1_SUMMARY_PATH,
    output: Path = DEFAULT_OUTPUT_PATH,
    summary_json: Path = DEFAULT_SUMMARY_JSON_PATH,
    sample_csv: Path = DEFAULT_SAMPLE_CSV_PATH,
    annotation_template: Path = DEFAULT_ANNOTATION_TEMPLATE_PATH,
    max_cases: int = DEFAULT_MAX_CASES,
) -> dict[str, Any]:
    summary = evaluate_casebook(
        BreakCasebookConfig(
            db_path=db,
            split_registry_path=split_registry,
            wp1_summary_path=wp1_summary,
            max_cases=max_cases,
        )
    )
    write_outputs(summary, output=output, summary_json=summary_json, sample_csv=sample_csv, annotation_template=annotation_template)
    return summary


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage04-WP2 break diagnostic casebook")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--split-registry", default=str(DEFAULT_SPLIT_REGISTRY_PATH))
    parser.add_argument("--wp1-summary", default=str(DEFAULT_WP1_SUMMARY_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT_PATH))
    parser.add_argument("--summary-json", default=str(DEFAULT_SUMMARY_JSON_PATH))
    parser.add_argument("--sample-csv", default=str(DEFAULT_SAMPLE_CSV_PATH))
    parser.add_argument("--annotation-template", default=str(DEFAULT_ANNOTATION_TEMPLATE_PATH))
    parser.add_argument("--max-cases", type=int, default=DEFAULT_MAX_CASES)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    run_from_paths(
        db=Path(args.db),
        split_registry=Path(args.split_registry),
        wp1_summary=Path(args.wp1_summary),
        output=Path(args.output),
        summary_json=Path(args.summary_json),
        sample_csv=Path(args.sample_csv),
        annotation_template=Path(args.annotation_template),
        max_cases=args.max_cases,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
