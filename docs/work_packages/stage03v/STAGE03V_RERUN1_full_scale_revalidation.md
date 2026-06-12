# STAGE03V_RERUN1_full_scale_revalidation

Stage: 03V / Volatility and downside-risk hazard

Work package: RERUN1

Index id: STAGE03V-RERUN1-v1

Suggested branch: `stage03v/rerun1-full-scale-revalidation`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_RERUN1_full_scale_revalidation.md`

Date: 2026-06-11

Depends on: `STAGE03V-FIX1-v1` accepted and merged.

## Background

The Stage03V1 post-completion audit (2026-06-11) established that the committed
`reports/stage03v/purge_embargo_fold_plan.json` contains three micro-folds
covering only 2014-01-13 to 2014-02-12 (per-slice train rows 60-1,391), built
from the WP2 500-row audit sample. WP4-WP6 consumed this plan, so all existing
WP4-WP6 empirical metrics were computed on roughly six weeks of early-2014 data
out of a 12.4-year development period. Those metrics are uninformative: they do
not measure the signal, in either direction.

Separately, the WP6 deliverable shipped readiness-tier aggregation only; the
pre-registered three-arm downshift experiment (no-downshift / baseline-driven /
model-driven) was never implemented, so the route's primary risk-reduction
question remains unanswered.

This package rebuilds the experiment design at full scale and produces the first
statistically meaningful Stage03V1 evidence. It has three sub-stages: B0 fold
plan rebuild with magnitude gates, B1 full-scale WP4/WP5 re-execution, B2
three-arm downshift experiment. WP7 final gate stays blocked until this package
is accepted.

## Trial accounting

The 2014 micro-fold run must be registered in validation trial accounting as
`invalidated_due_to_fold_coverage`, with this package as its replacement. The
recorded reason must state that invalidation is due to a defective input
artifact discovered by audit, not due to dissatisfaction with observed results.
This run therefore counts as the first informative trial, not a second trial.

## Stage boundary

Allowed:

- Rebuild the fold plan from the full labeled target dataset.
- Re-execute WP4 (logistic hazard) and WP5 (calibration, clustered inference,
  readiness) with FIX1-repaired code and the new fold plan.
- Implement and run the three-arm downshift experiment on validation folds.
- Regenerate the corresponding `reports/stage03v/` artifacts, superseding the
  invalidated versions.
- Add tests for the new fold-plan magnitude gates and the downshift experiment.

Forbidden:

- Touching prospective final holdout rows (`trade_date >= 2026-06-11`) in any
  training, calibration, selection, threshold, bucket, or evaluation step.
- Modifying target definitions, horizons, thresholds, the fixed-threshold
  mainline, or the universe manifest.
- Training model families beyond the existing logistic hazard.
- Tuning ordinal bucket rules or readiness thresholds against observed results.
- Fetching external data.
- Creating UI, decision, trading, buy/sell, or sizing outputs. Downshift arms
  are research-only exposure simulations, not portfolio recommendations.

## B0. Fold plan rebuild and magnitude gates

### Fold design

```text
scheme: anchored expanding walk-forward
fold_count: 8 to 10
validation_window: about 1 calendar year per fold
validation_coverage: 2016-01 through 2026-06-10
minimum_train_history: folds anchor at 2014-01-02; first validation fold starts no earlier than 2016-01
embargo: 20 trading days after each validation window
purge: existing WP2 overlap rule, unchanged
input: full labeled historical_development target rows (not a sample)
```

### Magnitude hard gates (plan-level; any failure blocks the plan)

```text
validation_date_span >= 60% of the historical_development date span
total_validation_trade_dates >= 500
every fold: train_row_count_per_slice >= 5000
every fold: validation window covers >= 200 trading days
```

### Magnitude evidence (slice-level; recorded, consumed by readiness)

For every core slice (horizon x threshold), record on validation-fold dates
only:

```text
validation_positive_count
validation_market_event_block_count (primary 20% definition)
validation_idiosyncratic_episode_count
```

These feed the FIX1 market-block hard ban and the existing validation-fold-only
evidence rule. Slices below evidence floors downgrade per readiness policy; they
do not fail the plan.

### B0 deliverables

```text
reports/stage03v/purge_embargo_fold_plan_v2.json
reports/stage03v/fold_plan_magnitude_overview.md
reports/stage03v/fold_plan_magnitude_overview.csv
tests/test_stage03v_fold_plan_magnitude_gates.py
```

The magnitude overview must show, per fold: train/validation date ranges, train
rows, validation rows, validation positives per core slice, validation market
event blocks per core slice. The B0 report must assert
`prospective_holdout_label_consumed_count = 0`.

## B1. Full-scale WP4/WP5 re-execution

- Re-run the logistic hazard (WP4) and calibration/readiness (WP5) pipelines
  unchanged except: FIX1 code, `purge_embargo_fold_plan_v2.json` input.
- Estimate runtime on one slice before launching the full grid; batch by
  horizon if needed.
- Every regenerated report must begin with a mandatory `## Magnitude Overview`
  section listing: train/validation date ranges, train rows, validation rows,
  validation positives, validation market event blocks. A report without this
  section is not acceptable.
- Superseded 2014 micro-run artifacts must be replaced in place, with the
  supersession recorded in the report metadata
  (`supersedes: stage03v_wp4_v1_2014_microfold`, reason
  `invalidated_due_to_fold_coverage`).

### B1 deliverables

```text
reports/stage03v/logistic_hazard_report.{md,json} (regenerated)
reports/stage03v/logistic_hazard_fold_metrics.csv (regenerated)
reports/stage03v/logistic_hazard_slice_metrics.csv (regenerated)
reports/stage03v/calibration_readiness_report.{md,json} (regenerated)
reports/stage03v/downside_readiness_matrix.csv (regenerated)
reports/stage03v/clustered_inference_summary.csv (regenerated)
```

## B2. Three-arm downshift experiment (new implementation)

### Design (pre-registered; no tuning after first full run)

For each slice with readiness `usable_probability_candidate` or
`ordinal_only_candidate` after B1, simulate on validation-fold dates an
equal-weight SW2021 L2 universe exposure with three arms:

```text
arm_no_downshift:    full exposure at all times
arm_baseline_driven: exposure rule driven by the strongest eligible WP3
                     baseline score for the same slice
arm_model_driven:    identical exposure rule driven by the calibrated hazard
```

Exposure rule (identical across driven arms, fixed before evaluation):

```text
entity-day in top (extreme) pre-registered risk bucket -> exposure 0.5
entity-day in high bucket                              -> exposure 0.75
otherwise                                              -> exposure 1.0
next-day open application, no lookahead
```

### Metrics (pre-registered)

Per arm and per arm-pair difference, with trade-date-clustered or event-block
bootstrap confidence intervals:

```text
max_drawdown
CVaR_95
realized_volatility
total_return (secondary)
missed_upside_cost
turnover
```

Primary claim: `arm_model_driven - arm_baseline_driven` on max_drawdown,
CVaR_95, and realized_volatility. Comparison versus `arm_no_downshift` is
secondary context only.

### B2 deliverables

```text
src/evaluation/stage03v_downshift_experiment.py
scripts/stage03v_downshift_experiment_gate.sh
reports/stage03v/downshift_experiment_report.{md,json}
reports/stage03v/downshift_experiment_arm_metrics.csv
reports/stage03v/downshift_experiment_daily_exposure_sample.csv
tests/test_stage03v_downshift_experiment.py
```

Tests must include a synthetic case where a known-good score produces a known
drawdown reduction, and a no-skill score produces approximately zero
model-minus-baseline delta.

## Acceptance

- [ ] FIX1 merged before any B1/B2 execution.
- [ ] B0 magnitude hard gates all pass; magnitude overview artifact exists.
- [ ] B1 reports regenerated from `purge_embargo_fold_plan_v2.json` with
      Magnitude Overview sections.
- [ ] Trial accounting records the 2014 micro-run as
      `invalidated_due_to_fold_coverage` with this package as replacement.
- [ ] B2 three arms implemented and run; primary claim reported as
      model-minus-baseline with clustered confidence intervals.
- [ ] `prospective_holdout_label_consumed_count = 0` asserted in B0, B1, B2.
- [ ] No ordinal bucket, readiness threshold, or exposure rule changed after
      first full-scale evaluation (any change requires a new package).
- [ ] WP7 remains blocked until this package is accepted.

## Return contract

Report: PR link(s), commands run, per-sub-stage status (B0/B1/B2), the
magnitude overview table, headline B1 readiness counts, headline B2
model-minus-baseline deltas with confidence intervals, and explicit yes/no
flags:

```text
external data fetch
fold plan v2 magnitude gates passed
trial accounting invalidation recorded
holdout consumed
exposure rule or buckets tuned after first run
HMM/HSMM training modified
decision or trading output
```
