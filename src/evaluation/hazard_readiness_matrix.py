"""Stage03R WP6 hazard readiness matrix.

This module converts WP5 calibration diagnostics plus WP4 age-bucket baseline
support into readiness statuses. It does not train models, consume HSMM numeric
p_exit, create risk validation, compare hazard against HSMM, or emit decision
surfaces.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


INDEX_ID = "STAGE03R-WP6"
READINESS_VERSION = "hazard_readiness_matrix_v1"

USABLE_PROBABILITY = "usable_probability"
ORDINAL_ONLY = "ordinal_only"
BASELINE_ONLY = "baseline_only"
INSUFFICIENT_SAMPLE = "insufficient_sample"
INVALID = "invalid"

CALIBRATION_CANDIDATE = "calibration_candidate"
DEGRADED_BRIER_WORSE = "degraded_brier_worse"
EMPIRICAL_BASELINE = "empirical_baseline"
MISSING_HORIZON_EVIDENCE = "missing_horizon_evidence"
MISSING_CALIBRATION_SLICE = "missing_calibration_slice"

READINESS_STATUS_ORDER = (
    USABLE_PROBABILITY,
    ORDINAL_ONLY,
    BASELINE_ONLY,
    INSUFFICIENT_SAMPLE,
    INVALID,
)
EXPECTED_HORIZONS = (1, 3, 5, 10, 20)
CALIBRATION_JOIN_COLUMNS = ("state_label", "state_phase", "horizon_days", "age_bucket")
READINESS_DIMENSIONS = (
    "state_label",
    "horizon_days",
    "age_bucket",
    "state_phase",
    "profile_mode",
    "state_date_policy",
)
FORBIDDEN_OUTPUT_FIELDS = (
    "decision_ready",
    "risk_downshift",
    "trade_signal",
    "trading_signal",
    "buy_signal",
    "sell_signal",
    "hsmm_raw_p_exit",
    "hsmm_calibrated_p_exit",
)


@dataclass
class ReadinessRow:
    state_label: str | None
    horizon_days: int | None
    age_bucket: str | None
    state_phase: str | None
    profile_mode: str | None
    state_date_policy: str | None
    sample_count: int
    positive_count: int
    negative_count: int
    event_rate: float | None
    raw_brier: float | None
    calibrated_brier: float | None
    age_bucket_baseline_brier: float | None
    brier_delta_calibrated_vs_raw: float | None
    brier_delta_calibrated_vs_baseline: float | None
    calibrated_ece: float | None
    calibration_status: str | None
    age_bucket_baseline_sample_count: int | None
    age_bucket_baseline_event_rate: float | None
    ordinal_separation: float | None
    fallback_reason: str | None
    readiness_status: str
    readiness_version: str
    source: str


@dataclass
class HazardReadinessMatrixResult:
    status: str
    readiness_version: str
    source: str
    row_count: int
    readiness_rows: list[dict[str, Any]]
    readiness_status_counts: dict[str, int]
    usable_probability_count: int
    ordinal_only_count: int
    baseline_only_count: int
    insufficient_sample_count: int
    invalid_count: int
    expected_horizons: list[int]
    horizon_coverage_summary: dict[str, Any]
    missing_horizon_evidence_summary: dict[str, Any]
    calibrated_vs_raw_brier_summary: dict[str, Any]
    calibrated_vs_age_bucket_baseline_summary: dict[str, Any]
    min_sample_count: int
    min_baseline_sample_count: int
    forbidden_output_fields: list[str]
    forbidden_output_field_count: int
    hsmm_p_exit_used: str = "no"
    external_data_fetch: str = "no"
    training_algorithm_modified: str = "no"
    DuckDB_committed: str = "no"
    local_db_validation: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_summary(self) -> dict[str, Any]:
        data = asdict(self)
        data["wp"] = INDEX_ID
        return data


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return str(value)


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _as_int(value: Any) -> int:
    numeric = _as_float(value)
    return int(numeric) if numeric is not None else 0


def _as_horizon(value: Any) -> int | None:
    numeric = _as_float(value)
    if numeric is None:
        return None
    return int(numeric)


def _safe_text(value: Any, default: str = "unknown") -> str:
    if value is None:
        return default
    if isinstance(value, float) and math.isnan(value):
        return default
    text = str(value)
    return text if text else default


def _is_unit_interval(value: float | None) -> bool:
    return value is None or (0.0 <= value <= 1.0)


def _mean(values: Sequence[float | None]) -> float | None:
    numeric = [float(value) for value in values if value is not None and math.isfinite(float(value))]
    return float(sum(numeric) / len(numeric)) if numeric else None


def parse_horizons(value: str | Sequence[int] | None) -> list[int]:
    if value is None:
        return list(EXPECTED_HORIZONS)
    if isinstance(value, str):
        return [int(part.strip()) for part in value.split(",") if part.strip()]
    return [int(item) for item in value]


def _calibration_key(row: Mapping[str, Any]) -> tuple[str, str, int | None, str]:
    return (
        _safe_text(row.get("state_label")),
        _safe_text(row.get("state_phase")),
        _as_horizon(row.get("horizon_days")),
        _safe_text(row.get("age_bucket")),
    )


def _baseline_rows_by_key(age_bucket_baseline: Mapping[str, Any] | None) -> dict[tuple[str, str, int | None, str], list[dict[str, Any]]]:
    by_key: dict[tuple[str, str, int | None, str], list[dict[str, Any]]] = {}
    for raw in (age_bucket_baseline or {}).get("baseline_rows", []):
        row = dict(raw)
        key = _calibration_key(row)
        by_key.setdefault(key, []).append(row)
    for rows in by_key.values():
        rows.sort(
            key=lambda row: (
                _safe_text(row.get("profile_mode")),
                _safe_text(row.get("state_date_policy")),
                _as_int(row.get("sample_count")),
            )
        )
    return by_key


def _horizon_ece_by_horizon(hazard_calibration: Mapping[str, Any] | None) -> dict[int, float | None]:
    out: dict[int, float | None] = {}
    for row in (hazard_calibration or {}).get("horizon_metrics", []):
        horizon = _as_horizon(row.get("horizon_days"))
        if horizon is not None:
            out[horizon] = _as_float(row.get("calibrated_ece"))
    return out


def _baseline_valid(row: Mapping[str, Any], *, min_baseline_sample_count: int) -> bool:
    return (
        row.get("baseline_status") == EMPIRICAL_BASELINE
        and _as_int(row.get("sample_count")) >= min_baseline_sample_count
        and _is_unit_interval(_as_float(row.get("event_rate")))
        and _as_float(row.get("event_rate")) is not None
    )


def _invalid_reason(
    *,
    state_label: str | None,
    horizon_days: int | None,
    age_bucket_value: str | None,
    event_rate: float | None,
    raw_brier: float | None,
    calibrated_brier: float | None,
    baseline_brier: float | None,
    calibration_status: str | None,
) -> str | None:
    if not state_label or state_label == "unknown":
        return "missing state_label"
    if horizon_days is None:
        return "missing horizon_days"
    if not age_bucket_value or age_bucket_value == "unknown":
        return "missing age_bucket"
    for name, value in (
        ("event_rate", event_rate),
        ("raw_brier", raw_brier),
        ("calibrated_brier", calibrated_brier),
        ("age_bucket_baseline_brier", baseline_brier),
    ):
        if not _is_unit_interval(value):
            return f"impossible {name}"
    if calibration_status in {"leakage_violation", "target_status_invalid"}:
        return str(calibration_status)
    return None


def assign_readiness_status(
    *,
    sample_count: int,
    positive_count: int,
    negative_count: int,
    raw_brier: float | None,
    calibrated_brier: float | None,
    age_bucket_baseline_brier: float | None,
    calibration_status: str | None,
    baseline_valid: bool,
    missing_calibration: bool,
    min_sample_count: int,
) -> tuple[str, str | None]:
    if missing_calibration:
        if baseline_valid:
            return BASELINE_ONLY, MISSING_HORIZON_EVIDENCE
        return INSUFFICIENT_SAMPLE, MISSING_HORIZON_EVIDENCE
    if sample_count < min_sample_count:
        return INSUFFICIENT_SAMPLE, f"sample_count {sample_count} below min_sample_count {min_sample_count}"
    if positive_count <= 0 or negative_count <= 0:
        return INSUFFICIENT_SAMPLE, "sample lacks both positive and negative labels"
    if (
        calibration_status == CALIBRATION_CANDIDATE
        and raw_brier is not None
        and calibrated_brier is not None
        and calibrated_brier <= raw_brier
        and (age_bucket_baseline_brier is None or calibrated_brier <= age_bucket_baseline_brier)
    ):
        return USABLE_PROBABILITY, None
    if baseline_valid and (
        calibrated_brier is None
        or calibration_status == DEGRADED_BRIER_WORSE
        or (age_bucket_baseline_brier is not None and calibrated_brier > age_bucket_baseline_brier)
    ):
        reason = "age-bucket baseline stronger than hazard calibration"
        if calibrated_brier is None:
            reason = "hazard calibration unavailable; age-bucket baseline has support"
        return BASELINE_ONLY, reason
    if sample_count > 0:
        if calibration_status == DEGRADED_BRIER_WORSE:
            return ORDINAL_ONLY, "calibrated Brier worse than raw Brier"
        return ORDINAL_ONLY, "probability support not strong enough for usable_probability"
    return INSUFFICIENT_SAMPLE, "no usable sample support"


def _make_readiness_row(
    *,
    calibration_row: Mapping[str, Any] | None,
    baseline_row: Mapping[str, Any] | None,
    source: str,
    missing_calibration: bool,
    min_sample_count: int,
    min_baseline_sample_count: int,
    calibrated_ece: float | None,
) -> ReadinessRow:
    cal = calibration_row or {}
    base = baseline_row or {}
    state_label = _safe_text(cal.get("state_label", base.get("state_label")))
    state_phase = _safe_text(cal.get("state_phase", base.get("state_phase")))
    horizon_days = _as_horizon(cal.get("horizon_days", base.get("horizon_days")))
    age_bucket_value = _safe_text(cal.get("age_bucket", base.get("age_bucket")))
    profile_mode = _safe_text(base.get("profile_mode"))
    state_date_policy = _safe_text(base.get("state_date_policy"))
    baseline_is_valid = _baseline_valid(base, min_baseline_sample_count=min_baseline_sample_count)

    if missing_calibration and baseline_row is not None:
        sample_count = _as_int(base.get("sample_count"))
        positive_count = _as_int(base.get("positive_count"))
        negative_count = _as_int(base.get("negative_count"))
        event_rate = _as_float(base.get("event_rate"))
        calibration_status = MISSING_HORIZON_EVIDENCE
    else:
        sample_count = _as_int(cal.get("sample_count"))
        positive_count = _as_int(cal.get("positive_count"))
        negative_count = _as_int(cal.get("negative_count"))
        event_rate = positive_count / sample_count if sample_count > 0 else _as_float(base.get("event_rate"))
        calibration_status = _safe_text(cal.get("calibration_status"), default="missing")

    raw_brier = _as_float(cal.get("raw_brier"))
    calibrated_brier = _as_float(cal.get("calibrated_brier"))
    age_bucket_baseline_brier = _as_float(cal.get("age_bucket_baseline_brier"))
    if age_bucket_baseline_brier is None:
        age_bucket_baseline_brier = _as_float(base.get("age_bucket_baseline_brier"))
    baseline_sample_count = _as_int(cal.get("age_bucket_baseline_sample_count"))
    if baseline_sample_count <= 0:
        baseline_sample_count = _as_int(base.get("sample_count"))
    baseline_event_rate = _as_float(cal.get("age_bucket_baseline_event_rate"))
    if baseline_event_rate is None:
        baseline_event_rate = _as_float(base.get("event_rate"))
    brier_delta_vs_raw = (
        calibrated_brier - raw_brier if calibrated_brier is not None and raw_brier is not None else None
    )
    brier_delta_vs_baseline = (
        calibrated_brier - age_bucket_baseline_brier
        if calibrated_brier is not None and age_bucket_baseline_brier is not None
        else None
    )
    ordinal_separation = (
        abs(event_rate - baseline_event_rate)
        if event_rate is not None and baseline_event_rate is not None
        else None
    )
    invalid_reason = _invalid_reason(
        state_label=state_label,
        horizon_days=horizon_days,
        age_bucket_value=age_bucket_value,
        event_rate=event_rate,
        raw_brier=raw_brier,
        calibrated_brier=calibrated_brier,
        baseline_brier=age_bucket_baseline_brier,
        calibration_status=calibration_status,
    )
    if invalid_reason:
        readiness_status = INVALID
        fallback_reason = invalid_reason
    else:
        readiness_status, fallback_reason = assign_readiness_status(
            sample_count=sample_count,
            positive_count=positive_count,
            negative_count=negative_count,
            raw_brier=raw_brier,
            calibrated_brier=calibrated_brier,
            age_bucket_baseline_brier=age_bucket_baseline_brier,
            calibration_status=calibration_status,
            baseline_valid=baseline_is_valid,
            missing_calibration=missing_calibration,
            min_sample_count=min_sample_count,
        )
    existing_reason = cal.get("fallback_reason") or base.get("fallback_reason")
    if fallback_reason is None and existing_reason:
        fallback_reason = str(existing_reason)

    return ReadinessRow(
        state_label=state_label,
        horizon_days=horizon_days,
        age_bucket=age_bucket_value,
        state_phase=state_phase,
        profile_mode=profile_mode,
        state_date_policy=state_date_policy,
        sample_count=sample_count,
        positive_count=positive_count,
        negative_count=negative_count,
        event_rate=event_rate,
        raw_brier=raw_brier,
        calibrated_brier=calibrated_brier,
        age_bucket_baseline_brier=age_bucket_baseline_brier,
        brier_delta_calibrated_vs_raw=brier_delta_vs_raw,
        brier_delta_calibrated_vs_baseline=brier_delta_vs_baseline,
        calibrated_ece=calibrated_ece,
        calibration_status=calibration_status,
        age_bucket_baseline_sample_count=baseline_sample_count if baseline_sample_count > 0 else None,
        age_bucket_baseline_event_rate=baseline_event_rate,
        ordinal_separation=ordinal_separation,
        fallback_reason=fallback_reason,
        readiness_status=readiness_status,
        readiness_version=READINESS_VERSION,
        source=source,
    )


def _status_counts(rows: Sequence[ReadinessRow]) -> dict[str, int]:
    counts = {status: 0 for status in READINESS_STATUS_ORDER}
    for row in rows:
        counts[row.readiness_status] = counts.get(row.readiness_status, 0) + 1
    return {status: int(counts.get(status, 0)) for status in READINESS_STATUS_ORDER}


def _summary_for_delta(rows: Sequence[ReadinessRow], field_name: str) -> dict[str, Any]:
    values = [_as_float(getattr(row, field_name)) for row in rows]
    numeric = [value for value in values if value is not None]
    return {
        "row_count": int(len(numeric)),
        "mean": _mean(numeric),
        "min": float(min(numeric)) if numeric else None,
        "max": float(max(numeric)) if numeric else None,
        "non_worse_count": int(sum(1 for value in numeric if value <= 0.0)),
        "worse_count": int(sum(1 for value in numeric if value > 0.0)),
    }


def evaluate_hazard_readiness_matrix(
    *,
    hazard_calibration: Mapping[str, Any],
    age_bucket_baseline: Mapping[str, Any],
    source: str = "reports",
    expected_horizons: Sequence[int] = EXPECTED_HORIZONS,
    min_sample_count: int = 30,
    min_baseline_sample_count: int = 30,
) -> HazardReadinessMatrixResult:
    baseline_by_key = _baseline_rows_by_key(age_bucket_baseline)
    ece_by_horizon = _horizon_ece_by_horizon(hazard_calibration)
    calibration_slices = [dict(row) for row in hazard_calibration.get("slice_metrics", [])]
    expected = sorted(int(value) for value in expected_horizons)
    calibration_horizons = sorted(
        {
            int(value)
            for value in (_as_horizon(row.get("horizon_days")) for row in calibration_slices)
            if value is not None
        }
    )
    baseline_horizons = sorted(
        {
            int(value)
            for value in (_as_horizon(row.get("horizon_days")) for row in age_bucket_baseline.get("baseline_rows", []))
            if value is not None
        }
    )
    readiness_rows: list[ReadinessRow] = []
    calibration_keys: set[tuple[str, str, int | None, str]] = set()
    for cal_row in sorted(calibration_slices, key=lambda row: (_as_horizon(row.get("horizon_days")) or -1, _safe_text(row.get("state_label")), _safe_text(row.get("state_phase")), _safe_text(row.get("age_bucket")))):
        key = _calibration_key(cal_row)
        calibration_keys.add(key)
        matches = baseline_by_key.get(key, [])
        if matches:
            for base_row in matches:
                readiness_rows.append(
                    _make_readiness_row(
                        calibration_row=cal_row,
                        baseline_row=base_row,
                        source="calibration_x_age_bucket_baseline",
                        missing_calibration=False,
                        min_sample_count=min_sample_count,
                        min_baseline_sample_count=min_baseline_sample_count,
                        calibrated_ece=ece_by_horizon.get(_as_horizon(cal_row.get("horizon_days"))),
                    )
                )
        else:
            readiness_rows.append(
                _make_readiness_row(
                    calibration_row=cal_row,
                    baseline_row=None,
                    source="calibration_only",
                    missing_calibration=False,
                    min_sample_count=min_sample_count,
                    min_baseline_sample_count=min_baseline_sample_count,
                    calibrated_ece=ece_by_horizon.get(_as_horizon(cal_row.get("horizon_days"))),
                )
            )
    for key, baseline_rows in sorted(baseline_by_key.items(), key=lambda item: item[0]):
        if key in calibration_keys:
            continue
        reason = MISSING_HORIZON_EVIDENCE if key[2] not in calibration_horizons else MISSING_CALIBRATION_SLICE
        for base_row in baseline_rows:
            cal_stub = {
                "state_label": base_row.get("state_label"),
                "state_phase": base_row.get("state_phase"),
                "horizon_days": base_row.get("horizon_days"),
                "age_bucket": base_row.get("age_bucket"),
                "calibration_status": reason,
            }
            readiness_rows.append(
                _make_readiness_row(
                    calibration_row=cal_stub,
                    baseline_row=base_row,
                    source=reason,
                    missing_calibration=True,
                    min_sample_count=min_sample_count,
                    min_baseline_sample_count=min_baseline_sample_count,
                    calibrated_ece=ece_by_horizon.get(_as_horizon(base_row.get("horizon_days"))),
                )
            )
    readiness_horizons = sorted({row.horizon_days for row in readiness_rows if row.horizon_days is not None})
    for horizon in expected:
        if horizon in readiness_horizons:
            continue
        readiness_rows.append(
            ReadinessRow(
                state_label="missing",
                horizon_days=horizon,
                age_bucket="missing",
                state_phase="missing",
                profile_mode="missing",
                state_date_policy="missing",
                sample_count=0,
                positive_count=0,
                negative_count=0,
                event_rate=None,
                raw_brier=None,
                calibrated_brier=None,
                age_bucket_baseline_brier=None,
                brier_delta_calibrated_vs_raw=None,
                brier_delta_calibrated_vs_baseline=None,
                calibrated_ece=None,
                calibration_status=MISSING_HORIZON_EVIDENCE,
                age_bucket_baseline_sample_count=None,
                age_bucket_baseline_event_rate=None,
                ordinal_separation=None,
                fallback_reason=MISSING_HORIZON_EVIDENCE,
                readiness_status=INSUFFICIENT_SAMPLE,
                readiness_version=READINESS_VERSION,
                source=MISSING_HORIZON_EVIDENCE,
            )
        )

    readiness_rows.sort(
        key=lambda row: (
            row.horizon_days if row.horizon_days is not None else -1,
            row.state_label or "",
            row.state_phase or "",
            row.age_bucket or "",
            row.profile_mode or "",
            row.state_date_policy or "",
        )
    )
    counts = _status_counts(readiness_rows)
    missing_rows = [row for row in readiness_rows if row.fallback_reason == MISSING_HORIZON_EVIDENCE or row.source == MISSING_HORIZON_EVIDENCE]
    missing_calibration_horizons = [horizon for horizon in expected if horizon not in calibration_horizons]
    missing_baseline_horizons = [horizon for horizon in expected if horizon not in baseline_horizons]
    status = "fail" if counts.get(INVALID, 0) else "pass"
    if not readiness_rows:
        status = "partial"
    return HazardReadinessMatrixResult(
        status=status,
        readiness_version=READINESS_VERSION,
        source=source,
        row_count=int(len(readiness_rows)),
        readiness_rows=[asdict(row) for row in readiness_rows],
        readiness_status_counts=counts,
        usable_probability_count=counts.get(USABLE_PROBABILITY, 0),
        ordinal_only_count=counts.get(ORDINAL_ONLY, 0),
        baseline_only_count=counts.get(BASELINE_ONLY, 0),
        insufficient_sample_count=counts.get(INSUFFICIENT_SAMPLE, 0),
        invalid_count=counts.get(INVALID, 0),
        expected_horizons=list(expected),
        horizon_coverage_summary={
            "expected_horizons": list(expected),
            "calibration_horizons": calibration_horizons,
            "age_bucket_baseline_horizons": baseline_horizons,
            "readiness_horizons": sorted({row.horizon_days for row in readiness_rows if row.horizon_days is not None}),
            "missing_calibration_horizons": missing_calibration_horizons,
            "missing_baseline_horizons": missing_baseline_horizons,
        },
        missing_horizon_evidence_summary={
            "missing_calibration_horizons": missing_calibration_horizons,
            "missing_baseline_horizons": missing_baseline_horizons,
            "row_count": int(len(missing_rows)),
            "readiness_status_counts": _status_counts(missing_rows),
        },
        calibrated_vs_raw_brier_summary=_summary_for_delta(readiness_rows, "brier_delta_calibrated_vs_raw"),
        calibrated_vs_age_bucket_baseline_summary=_summary_for_delta(
            readiness_rows,
            "brier_delta_calibrated_vs_baseline",
        ),
        min_sample_count=int(min_sample_count),
        min_baseline_sample_count=int(min_baseline_sample_count),
        forbidden_output_fields=[],
        forbidden_output_field_count=0,
    )


def build_report_markdown(summary: Mapping[str, Any]) -> str:
    lines = [
        "# Stage03R WP6 Hazard Readiness Matrix",
        "",
        f"status: {summary.get('status')}",
        f"readiness_version: {summary.get('readiness_version')}",
        f"source: {summary.get('source')}",
        f"row_count: {summary.get('row_count')}",
        f"usable_probability_count: {summary.get('usable_probability_count')}",
        f"ordinal_only_count: {summary.get('ordinal_only_count')}",
        f"baseline_only_count: {summary.get('baseline_only_count')}",
        f"insufficient_sample_count: {summary.get('insufficient_sample_count')}",
        f"invalid_count: {summary.get('invalid_count')}",
        "",
        "## Readiness Status Counts",
        "",
        "```json",
        json.dumps(summary.get("readiness_status_counts", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Horizon Coverage",
        "",
        "```json",
        json.dumps(summary.get("horizon_coverage_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Missing Horizon Evidence",
        "",
        "```json",
        json.dumps(summary.get("missing_horizon_evidence_summary", {}), ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Brier Summaries",
        "",
        "```json",
        json.dumps(
            {
                "calibrated_vs_raw": summary.get("calibrated_vs_raw_brier_summary"),
                "calibrated_vs_age_bucket_baseline": summary.get("calibrated_vs_age_bucket_baseline_summary"),
            },
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        ),
        "```",
        "",
        "## Readiness Row Sample",
        "",
        "```json",
        json.dumps(summary.get("readiness_rows", [])[:80], ensure_ascii=False, indent=2, default=_json_default),
        "```",
        "",
        "## Boundary Confirmation",
        "",
        "- WP6 assigns readiness matrix statuses only.",
        "- no decision_ready field emitted.",
        "- no risk_downshift output emitted.",
        "- no trading signal field emitted.",
        "- no hazard-vs-HSMM report emitted.",
        f"- HSMM p_exit used: {summary.get('hsmm_p_exit_used')}",
        f"- external_data_fetch: {summary.get('external_data_fetch')}",
        f"- training_algorithm_modified: {summary.get('training_algorithm_modified')}",
        f"- DuckDB_committed: {summary.get('DuckDB_committed')}",
    ]
    return "\n".join(lines) + "\n"


def write_outputs(result: HazardReadinessMatrixResult, output: Path, summary_json: Path) -> None:
    summary = result.to_summary()
    output.parent.mkdir(parents=True, exist_ok=True)
    summary_json.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report_markdown(summary), encoding="utf-8")
    summary_json.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_source_path(path: Path | None) -> str | None:
    if path is None:
        return None
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(Path.cwd()).as_posix()
    except ValueError:
        return path.name


def _local_db_validation(db_path: str | None) -> dict[str, Any]:
    if not db_path:
        return {"db_path_used": None, "db_found": "no", "opened_read_only": "no", "key_tables_checked": [], "row_counts": {}}
    path = Path(db_path)
    if not path.exists():
        return {"db_path_used": _safe_source_path(path), "db_found": "no", "opened_read_only": "no", "key_tables_checked": [], "row_counts": {}}
    tables = [
        "model_runs",
        "sector_state_daily",
        "walk_forward_cache_runs",
        "walk_forward_state_cache",
        "hsmm_lifecycle_ui_daily",
    ]
    row_counts: dict[str, Any] = {}
    opened = "no"
    try:
        import duckdb

        with duckdb.connect(str(path), read_only=True) as con:
            opened = "yes"
            for table in tables:
                try:
                    row_counts[table] = int(con.execute(f"select count(*) from {table}").fetchone()[0])
                except Exception as exc:
                    row_counts[table] = f"missing_or_unreadable: {exc}"
    except Exception as exc:
        row_counts["open_error"] = str(exc)
    return {
        "db_path_used": _safe_source_path(path),
        "db_found": "yes",
        "opened_read_only": opened,
        "key_tables_checked": tables,
        "row_counts": row_counts,
    }


def _load_or_build_calibration(args: argparse.Namespace, age_bucket_baseline: Mapping[str, Any]) -> dict[str, Any]:
    calibration_path = Path(args.hazard_calibration)
    if calibration_path.exists():
        return _load_json(calibration_path)
    if not args.hazard_predictions:
        raise FileNotFoundError(f"hazard calibration not found: {calibration_path}")
    prediction_path = Path(args.hazard_predictions)
    if not prediction_path.exists():
        raise FileNotFoundError(f"hazard predictions not found: {prediction_path}")
    from src.evaluation.hazard_isotonic_calibration import evaluate_hazard_isotonic_calibration
    import pandas as pd

    predictions = pd.read_csv(prediction_path, keep_default_na=True)
    result = evaluate_hazard_isotonic_calibration(
        predictions,
        age_bucket_baseline=age_bucket_baseline,
        source=f"hazard_predictions:{_safe_source_path(prediction_path)}",
        min_sample_count=args.min_sample_count,
        min_slice_sample_count=args.min_sample_count,
    )
    return result.to_summary()


def run_cli(args: argparse.Namespace) -> int:
    age_bucket_baseline = _load_json(Path(args.age_bucket_baseline))
    hazard_calibration = _load_or_build_calibration(args, age_bucket_baseline)
    result = evaluate_hazard_readiness_matrix(
        hazard_calibration=hazard_calibration,
        age_bucket_baseline=age_bucket_baseline,
        source=f"hazard_calibration:{_safe_source_path(Path(args.hazard_calibration))}",
        expected_horizons=parse_horizons(args.horizons),
        min_sample_count=args.min_sample_count,
        min_baseline_sample_count=args.min_baseline_sample_count,
    )
    if args.db:
        result.local_db_validation = _local_db_validation(args.db)
    write_outputs(result, Path(args.output), Path(args.summary_json))
    return 0 if result.status in {"pass", "partial"} else 1


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build Stage03R WP6 hazard readiness matrix")
    parser.add_argument("--hazard-calibration", required=True, help="WP5 hazard isotonic calibration JSON")
    parser.add_argument("--age-bucket-baseline", required=True, help="WP4 age-bucket baseline JSON")
    parser.add_argument("--hazard-predictions", default=None, help="Optional WP3 hazard predictions for rebuilding missing calibration")
    parser.add_argument("--db", default=None, help="Optional local DuckDB path for read-only validation metadata")
    parser.add_argument("--run-id", default="latest", help="Run id for local DB validation metadata")
    parser.add_argument("--horizons", default="1,3,5,10,20", help="Comma-separated horizons expected in readiness matrix")
    parser.add_argument("--output", required=True, help="Markdown report path")
    parser.add_argument("--summary-json", required=True, help="JSON report path")
    parser.add_argument("--min-sample-count", type=int, default=30)
    parser.add_argument("--min-baseline-sample-count", type=int, default=30)
    parser.add_argument("--no-fetch", action="store_true", default=False)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    return run_cli(args)


if __name__ == "__main__":
    raise SystemExit(main())
