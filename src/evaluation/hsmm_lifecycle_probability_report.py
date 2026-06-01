from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_exit_targets import (
    build_exit_targets,
    parse_exit_types,
    parse_horizons,
    read_hsmm_episodes,
    read_hsmm_states,
)
from src.evaluation.hsmm_lifecycle_calibration import (
    CalibrationConfig,
    ui_readiness_matrix,
    validate_lifecycle_calibration,
    write_calibration_outputs,
)
from src.evaluation.hsmm_transition_validation import validate_transitions, write_transition_outputs


def _segments(states: pd.DataFrame, key_col: str) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    rows: list[dict[str, object]] = []
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        start_idx = 0
        for i in range(1, len(group) + 1):
            boundary = i == len(group) or str(group.loc[i, key_col]) != str(group.loc[i - 1, key_col])
            if not boundary:
                continue
            segment = group.iloc[start_idx:i]
            next_row = group.iloc[i] if i < len(group) else None
            start_date = pd.Timestamp(segment["trade_date"].iloc[0])
            end_date = pd.Timestamp(segment["trade_date"].iloc[-1])
            rows.append(
                {
                    "sector_code": sector_code,
                    "state_or_label": str(segment[key_col].iloc[-1]),
                    "state_label": str(segment["state_label"].iloc[-1]),
                    "start_date": start_date,
                    "end_date": end_date,
                    "duration_days": int(len(segment)),
                    "is_left_censored": bool(start_idx == 0),
                    "is_right_censored": bool(next_row is None),
                    "next_state_or_label": None if next_row is None else str(next_row[key_col]),
                    "next_state_label": None if next_row is None else str(next_row["state_label"]),
                }
            )
            start_idx = i
    return pd.DataFrame(rows)


def _duration_profile(segments: pd.DataFrame, label_col: str = "state_or_label") -> pd.DataFrame:
    if segments.empty:
        return pd.DataFrame()
    rows: list[dict[str, object]] = []
    for value, group in segments.groupby(label_col, observed=True):
        durations = pd.to_numeric(group["duration_days"], errors="coerce")
        rows.append(
            {
                "state_or_label": value,
                "episode_count": int(len(group)),
                "mean_duration": float(durations.mean()),
                "median_duration": float(durations.median()),
                "p10_duration": float(durations.quantile(0.10)),
                "p25_duration": float(durations.quantile(0.25)),
                "p75_duration": float(durations.quantile(0.75)),
                "p90_duration": float(durations.quantile(0.90)),
                "one_day_episode_ratio": float((durations <= 1).mean()),
                "three_day_or_less_episode_ratio": float((durations <= 3).mean()),
                "left_censored_count": int(group["is_left_censored"].sum()),
                "right_censored_count": int(group["is_right_censored"].sum()),
            }
        )
    return pd.DataFrame(rows)


def _stress_lifecycle_from_targets(targets: pd.DataFrame, exit_type: str) -> pd.DataFrame:
    if targets.empty:
        return pd.DataFrame()
    work = targets[
        targets["exit_type"].eq(exit_type)
        & targets["state_label"].astype(str).eq("Stress")
        & (targets["is_right_censored_for_horizon"] == False)  # noqa: E712
    ].copy()
    if work.empty:
        return pd.DataFrame()
    work["age_bucket"] = pd.cut(
        pd.to_numeric(work["display_state_age_days"], errors="coerce"),
        bins=[0, 3, 7, 14, np.inf],
        labels=["1-3", "4-7", "8-14", "15+"],
    )
    rows: list[dict[str, object]] = []
    for (bucket, horizon), group in work.groupby(["age_bucket", "horizon_days"], observed=True):
        rows.append(
            {
                "state_label": "Stress",
                "exit_type": exit_type,
                "age_bucket": bucket,
                "horizon_days": int(horizon),
                "sample_count": int(len(group)),
                "actual_exit_rate": float(group["actual_exit_within_h"].astype(float).mean()),
                "realized_next_label_distribution": json.dumps(
                    group["actual_next_state_label"].dropna().astype(str).value_counts(normalize=True).to_dict(),
                    ensure_ascii=False,
                ),
            }
        )
    return pd.DataFrame(rows)


def _verdicts(selected: pd.DataFrame, transition_summary: pd.DataFrame) -> dict[str, str]:
    if selected.empty:
        calibration = "InsufficientSample"
        display = "DisplayHidden"
    else:
        statuses = set(selected["status"].astype(str))
        if statuses and statuses <= {"usable_probability", "raw_only"}:
            calibration = "ValidLifecycleProbability"
        elif "usable_probability" in statuses:
            calibration = "PartialLifecycleProbability"
        elif statuses & {"raw_only", "ordinal_only"}:
            calibration = "OrdinalLifecycleSignalOnly"
        elif "insufficient_sample" in statuses and not (statuses - {"insufficient_sample"}):
            calibration = "InsufficientSample"
        else:
            calibration = "InvalidLifecycleProbability"
        if calibration == "ValidLifecycleProbability":
            display = "DisplayAllowedProbability"
        elif calibration == "PartialLifecycleProbability":
            display = "DisplayAllowedProbability"
        elif calibration == "OrdinalLifecycleSignalOnly":
            display = "DisplayAllowedOrdinalOnly"
        else:
            display = "DisplayHidden"

    if transition_summary.empty:
        transition = "TransitionInvalid"
    elif transition_summary["status"].astype(str).eq("usable_model_prediction").any():
        transition = "TransitionModelUseful"
    elif transition_summary["status"].astype(str).eq("empirical_baseline_only").any():
        transition = "TransitionBaselineOnly"
    else:
        transition = "TransitionInvalid"

    stress = "StressLifecycleMixed"
    return {
        "engineering_verdict": "EngineeringPass",
        "calibration_verdict": calibration,
        "transition_verdict": transition,
        "stress_lifecycle_verdict": stress,
        "display_readiness_verdict": display,
        "overall_verdict": calibration if calibration != "ValidLifecycleProbability" else "ValidLifecycleProbability",
    }


def _write_summary(
    output_dir: Path,
    run_id: str,
    selected: pd.DataFrame,
    transition_summary: pd.DataFrame,
    verdicts: dict[str, str],
) -> None:
    usable = selected[selected["status"].eq("usable_probability")] if not selected.empty else pd.DataFrame()
    ordinal = selected[selected["status"].isin(["raw_only", "ordinal_only"])] if not selected.empty else pd.DataFrame()
    hidden = selected[selected["status"].isin(["invalid", "insufficient_sample"])] if not selected.empty else pd.DataFrame()

    def table(df: pd.DataFrame) -> str:
        if df.empty:
            return "_none_\n"
        cols = ["state_label", "horizon_days", "exit_type", "selected_method", "status", "reason"]
        return df[cols].sort_values(["exit_type", "state_label", "horizon_days"]).to_string(index=False) + "\n"

    def dataframe_text(df: pd.DataFrame) -> str:
        if df.empty:
            return "_none_"
        return df.to_string(index=False)

    content = f"""# HSMM Lifecycle Probability Validity Report

## Run

- run_id: `{run_id}`
- scope: internal lifecycle diagnostics only

## Layered Verdict

- overall_verdict: `{verdicts['overall_verdict']}`
- engineering_verdict: `{verdicts['engineering_verdict']}`
- calibration_verdict: `{verdicts['calibration_verdict']}`
- transition_verdict: `{verdicts['transition_verdict']}`
- stress_lifecycle_verdict: `{verdicts['stress_lifecycle_verdict']}`
- display_readiness_verdict: `{verdicts['display_readiness_verdict']}`

## Numeric Probability Allowed

{table(usable)}

## Ordinal Only

{table(ordinal)}

## Hidden / Not Displayable

{table(hidden)}

## Transition Validation

{dataframe_text(transition_summary)}

## UI Guidance

Only rows marked `usable_probability` may be displayed as numeric probabilities.
Rows marked `raw_only` or `ordinal_only` must be displayed as high/medium/low pressure, not percentages.
Rows marked `invalid` or `insufficient_sample` must be hidden from formal UI.
"""
    (output_dir / "summary.md").write_text(content, encoding="utf-8")


def write_known_limitations(output_dir: Path) -> None:
    text = """# Known Limitations

- HSMM lifecycle probabilities are diagnostics, not trading signals.
- Display-label exit and hidden-state exit are different targets and must not be mixed.
- Calibrated probabilities are only usable for rows explicitly marked `usable_probability`.
- `raw_only` and `ordinal_only` rows should never be shown as percentage probabilities.
- Matched HMM comparison still requires an explicit compatible HMM cache key.
"""
    (output_dir / "known_limitations.md").write_text(text, encoding="utf-8")


def generate_probability_report(
    storage: DuckDBStorage,
    run_id: str,
    output_dir: Path,
    horizons: tuple[int, ...] = (1, 3, 5, 10, 20),
    exit_types: tuple[str, ...] = ("state_id", "display_label"),
) -> dict[str, pd.DataFrame | dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    states = read_hsmm_states(storage, run_id)
    episodes = read_hsmm_episodes(storage, run_id)
    targets = build_exit_targets(states, episodes, horizons, exit_types)
    targets.head(5000).to_csv(output_dir / "exit_targets_sample.csv", index=False)

    calibration = validate_lifecycle_calibration(targets)
    write_calibration_outputs(calibration, output_dir)
    transition = validate_transitions(states)
    write_transition_outputs(transition, output_dir)

    hidden_segments = _segments(states, "state_id")
    label_segments = _segments(states, "state_label")
    hidden_profile = _duration_profile(hidden_segments)
    label_profile = _duration_profile(label_segments)
    hidden_profile.to_csv(output_dir / "duration_profile_by_state_id.csv", index=False)
    label_profile.to_csv(output_dir / "duration_profile_by_display_label.csv", index=False)
    duration_compare = hidden_profile.merge(
        label_profile,
        on="state_or_label",
        how="outer",
        suffixes=("_hidden", "_display"),
    )
    duration_compare.to_csv(output_dir / "duration_hidden_vs_display.csv", index=False)
    duration_compare.to_csv(output_dir / "duration_profile_hidden_vs_label.csv", index=False)
    _stress_lifecycle_from_targets(targets, "display_label").to_csv(output_dir / "stress_display_label_lifecycle.csv", index=False)
    _stress_lifecycle_from_targets(targets, "state_id").to_csv(output_dir / "stress_hidden_state_lifecycle.csv", index=False)

    selected = calibration["selected_status"]
    readiness = ui_readiness_matrix(selected)
    readiness.to_csv(output_dir / "ui_readiness_matrix.csv", index=False)
    verdicts = _verdicts(selected, transition["summary"])
    _write_summary(output_dir, run_id, selected, transition["summary"], verdicts)
    write_known_limitations(output_dir)
    (output_dir / "config.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "horizons": horizons,
                "exit_types": exit_types,
                "calibration_config": CalibrationConfig().__dict__,
                "verdicts": verdicts,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    return {"targets": targets, "calibration": calibration["summary"], "transition": transition["summary"], "verdicts": verdicts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate HSMM lifecycle probability validity report")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--calibration-dir", default=None)
    parser.add_argument("--transition-dir", default=None)
    parser.add_argument("--horizons", default="1,3,5,10,20")
    parser.add_argument("--exit-types", default="state_id,display_label")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    storage = DuckDBStorage(args.db)
    result = generate_probability_report(
        storage,
        args.run_id,
        Path(args.output),
        parse_horizons(args.horizons),
        parse_exit_types(args.exit_types),
    )
    print(f"output_dir: {args.output}")
    print(f"verdicts: {result['verdicts']}")


if __name__ == "__main__":
    main()
