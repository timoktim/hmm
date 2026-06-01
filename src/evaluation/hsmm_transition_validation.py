from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from src.data_pipeline.storage import DuckDBStorage
from src.evaluation.hsmm_exit_targets import read_hsmm_states
from src.evaluation.hsmm_lifecycle_calibration import AGE_BUCKETS, age_bucket


def build_display_label_episodes(states: pd.DataFrame) -> pd.DataFrame:
    if states.empty:
        return pd.DataFrame()
    work = states.sort_values(["sector_code", "trade_date"]).copy()
    work["trade_date"] = pd.to_datetime(work["trade_date"])
    rows: list[dict[str, object]] = []
    for sector_code, group in work.groupby("sector_code", sort=False):
        group = group.reset_index(drop=True)
        start_idx = 0
        for i in range(1, len(group) + 1):
            boundary = i == len(group) or str(group.loc[i, "state_label"]) != str(group.loc[i - 1, "state_label"])
            if not boundary:
                continue
            segment = group.iloc[start_idx:i]
            next_row = group.iloc[i] if i < len(group) else None
            end_row = segment.iloc[-1]
            duration = int(len(segment))
            rows.append(
                {
                    "run_id": end_row.get("run_id"),
                    "sector_code": sector_code,
                    "state_label": end_row.get("state_label"),
                    "start_date": pd.Timestamp(segment["trade_date"].iloc[0]),
                    "end_date": pd.Timestamp(end_row.get("trade_date")),
                    "duration_days": duration,
                    "age_bucket": age_bucket(duration),
                    "next_state_label": None if next_row is None else str(next_row.get("state_label")),
                    "predicted_next_state_label": end_row.get("most_likely_next_state_label"),
                    "is_right_censored": next_row is None,
                }
            )
            start_idx = i
    return pd.DataFrame(rows)


def _mode(series: pd.Series) -> str | None:
    clean = series.dropna().astype(str)
    if clean.empty:
        return None
    return str(clean.value_counts().index[0])


def _distribution(series: pd.Series) -> dict[str, float]:
    clean = series.dropna().astype(str)
    if clean.empty:
        return {}
    counts = clean.value_counts(normalize=True)
    return {str(k): float(v) for k, v in counts.items()}


def _split_episodes(episodes: pd.DataFrame, train_ratio: float = 0.6) -> tuple[pd.DataFrame, pd.DataFrame]:
    if episodes.empty:
        return episodes.copy(), episodes.copy()
    dates = pd.Series(pd.to_datetime(episodes["end_date"]).drop_duplicates().sort_values()).reset_index(drop=True)
    cut_idx = max(0, min(len(dates) - 1, int(np.floor(len(dates) * train_ratio)) - 1))
    cut = dates.iloc[cut_idx]
    return episodes[episodes["end_date"] <= cut].copy(), episodes[episodes["end_date"] > cut].copy()


def _multiclass_brier(actual: pd.Series, probabilities: list[dict[str, float]], labels: list[str]) -> float:
    if len(actual) == 0:
        return np.nan
    values = []
    for y, probs in zip(actual.astype(str), probabilities, strict=False):
        values.append(sum(((1.0 if label == y else 0.0) - float(probs.get(label, 0.0))) ** 2 for label in labels))
    return float(np.mean(values))


def validate_transitions(states: pd.DataFrame, min_sample: int = 200, advantage: float = 0.02) -> dict[str, pd.DataFrame]:
    episodes = build_display_label_episodes(states)
    complete = episodes[(episodes["is_right_censored"] == False) & episodes["next_state_label"].notna()].copy()  # noqa: E712
    if complete.empty:
        empty = pd.DataFrame()
        return {"episodes": episodes, "summary": empty, "by_age_bucket": empty}
    train, test = _split_episodes(complete)
    labels = sorted(complete["next_state_label"].dropna().astype(str).unique())
    global_modes = train.groupby("state_label")["next_state_label"].apply(_mode).to_dict()
    age_modes = train.groupby(["state_label", "age_bucket"], observed=True)["next_state_label"].apply(_mode).to_dict()
    age_distributions = train.groupby(["state_label", "age_bucket"], observed=True)["next_state_label"].apply(_distribution).to_dict()

    rows: list[dict[str, object]] = []
    age_rows: list[dict[str, object]] = []
    for (label, bucket), group in test.groupby(["state_label", "age_bucket"], observed=True):
        actual = group["next_state_label"].astype(str)
        model_pred = group["predicted_next_state_label"].fillna("").astype(str)
        global_pred_label = global_modes.get(label)
        age_pred_label = age_modes.get((label, bucket), global_pred_label)
        model_acc = float((model_pred == actual).mean())
        global_acc = float((pd.Series(global_pred_label, index=group.index).astype(str) == actual).mean()) if global_pred_label else np.nan
        age_acc = float((pd.Series(age_pred_label, index=group.index).astype(str) == actual).mean()) if age_pred_label else np.nan
        empirical_dist = age_distributions.get((label, bucket), _distribution(train[train["state_label"].astype(str).eq(str(label))]["next_state_label"]))
        model_probs = [{pred: 1.0} for pred in model_pred]
        baseline_probs = [empirical_dist for _ in range(len(group))]
        model_brier = _multiclass_brier(actual, model_probs, labels)
        baseline_brier = _multiclass_brier(actual, baseline_probs, labels)
        valid_baselines = [value for value in [global_acc, age_acc] if pd.notna(value)]
        best_baseline = max(valid_baselines) if valid_baselines else np.nan
        if len(group) >= min_sample and model_acc > best_baseline + advantage:
            status = "usable_model_prediction"
        elif pd.notna(best_baseline) and best_baseline >= model_acc:
            status = "empirical_baseline_only"
        else:
            status = "hidden"
        row = {
            "state_label": label,
            "age_bucket": bucket,
            "sample_count": int(len(group)),
            "model_top1_accuracy": model_acc,
            "global_mode_accuracy": global_acc,
            "age_bucket_mode_accuracy": age_acc,
            "best_baseline_accuracy": best_baseline,
            "model_brier_multiclass": model_brier,
            "baseline_brier_multiclass": baseline_brier,
            "empirical_distribution": empirical_dist,
            "status": status,
        }
        age_rows.append(row)

    by_age = pd.DataFrame(age_rows)
    for label, group in by_age.groupby("state_label", observed=True):
        sample = int(group["sample_count"].sum())
        weighted_model = float((group["sample_count"] * group["model_top1_accuracy"]).sum() / sample) if sample else np.nan
        weighted_baseline = float((group["sample_count"] * group["best_baseline_accuracy"]).sum() / sample) if sample else np.nan
        if sample >= min_sample and weighted_model > weighted_baseline + advantage:
            status = "usable_model_prediction"
        elif pd.notna(weighted_baseline) and weighted_baseline >= weighted_model:
            status = "empirical_baseline_only"
        else:
            status = "hidden"
        rows.append(
            {
                "state_label": label,
                "sample_count": sample,
                "model_top1_accuracy": weighted_model,
                "best_baseline_accuracy": weighted_baseline,
                "status": status,
            }
        )
    return {"episodes": episodes, "summary": pd.DataFrame(rows), "by_age_bucket": by_age}


def write_transition_outputs(results: dict[str, pd.DataFrame], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    results["summary"].to_csv(output_dir / "transition_validation_summary.csv", index=False)
    results["by_age_bucket"].to_csv(output_dir / "transition_validation_by_age_bucket.csv", index=False)
    results["episodes"].to_csv(output_dir / "display_label_transition_profile.csv", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate HSMM next-state prediction fallback")
    parser.add_argument("--db", default="data/db/a_share_hmm.duckdb")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--age-buckets", default="1-3,4-7,8-14,15+")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    storage = DuckDBStorage(args.db)
    states = read_hsmm_states(storage, args.run_id)
    results = validate_transitions(states)
    write_transition_outputs(results, Path(args.output))
    print(f"transition_rows: {len(results['by_age_bucket'])}")
    print(f"output_dir: {args.output}")


if __name__ == "__main__":
    main()
