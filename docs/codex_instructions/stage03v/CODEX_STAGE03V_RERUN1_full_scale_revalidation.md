# CODEX_STAGE03V_RERUN1_full_scale_revalidation

Repository: timoktim/hmm

Index id: STAGE03V-RERUN1-v1

Work package: `docs/work_packages/stage03v/STAGE03V_RERUN1_full_scale_revalidation.md`

Suggested branch: `stage03v/rerun1-full-scale-revalidation`

Depends on: `STAGE03V-FIX1-v1` accepted and merged into `main`.

## Instruction

Start from updated `main` containing the accepted FIX1 changes. Read the work
package in full. Execute only `STAGE03V-RERUN1-v1`, in sub-stage order
B0 -> B1 -> B2. Do not start B1 before B0 magnitude gates pass. Do not start
B2 before B1 readiness output exists.

Context you must internalize before writing code: the committed
`reports/stage03v/purge_embargo_fold_plan.json` is a defective artifact whose
three folds cover only 2014-01-13 to 2014-02-12. Every WP4-WP6 metric computed
from it is invalidated. You are rebuilding the fold plan from the full labeled
target dataset and re-running the evaluation chain at full scale.

### B0: fold plan rebuild and magnitude gates

Build `reports/stage03v/purge_embargo_fold_plan_v2.json` with anchored
expanding walk-forward: 8-10 folds, validation windows of about one year
covering 2016-01 through 2026-06-10, anchor training at 2014-01-02, embargo 20
trading days, existing purge rule unchanged, input = full labeled
historical_development rows (never a sample).

Enforce plan-level hard gates (any failure blocks the plan): validation date
span >= 60% of the development span; total validation trade dates >= 500;
per-fold per-slice train rows >= 5000; per-fold validation window >= 200
trading days. Emit the magnitude overview (md + csv) showing per-fold date
ranges, row counts, per-core-slice validation positives and market event
blocks. Assert `prospective_holdout_label_consumed_count = 0`.

### B1: full-scale WP4/WP5 re-execution

Re-run logistic hazard and calibration/readiness with FIX1 code and the v2
fold plan. Time one slice first; batch by horizon if the full grid is slow.
Every regenerated report must begin with a `## Magnitude Overview` section.
Record in report metadata: `supersedes: stage03v_wp4_v1_2014_microfold`,
reason `invalidated_due_to_fold_coverage`. Register the invalidation in
validation trial accounting with the audit-defect justification, so this run
counts as the first informative trial.

### B2: three-arm downshift experiment

Implement `src/evaluation/stage03v_downshift_experiment.py` exactly as
pre-registered in the work package: equal-weight SW2021 L2 exposure on
validation-fold dates; arms no_downshift / baseline_driven (strongest eligible
WP3 baseline) / model_driven (calibrated hazard); fixed exposure rule
(extreme bucket -> 0.5, high -> 0.75, else 1.0, next-day open, no lookahead);
metrics max_drawdown, CVaR_95, realized_volatility, total_return (secondary),
missed_upside_cost, turnover; trade-date-clustered or event-block bootstrap
confidence intervals. The primary claim is model-minus-baseline on
max_drawdown, CVaR_95, and realized_volatility. Do not tune the exposure rule
or buckets after the first full-scale run.

## Hard prohibitions

- No row with `trade_date >= 2026-06-11` may enter training, calibration,
  bucket assignment, selection, or evaluation. Assert and report the zero
  count in every sub-stage.
- No change to target definitions, horizons, thresholds, fixed-threshold
  mainline, or universe manifest.
- No model family beyond the existing logistic hazard.
- No readiness-threshold or ordinal-bucket tuning against observed results.
- No external data fetch.
- No UI, decision, trading, buy/sell, or sizing output. Downshift arms are
  research-only simulations.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_fold_plan_magnitude_gates.py
pytest -q tests/test_stage03v_downshift_experiment.py
pytest -q -m "not slow"
```

Plus the pipeline invocations for B0, B1, B2 against the local V7 database,
documented in the PR body with wall-clock durations.

## Return format

Use the return contract in the work package. Include per-sub-stage status, the
magnitude overview table, headline B1 readiness counts, headline B2
model-minus-baseline deltas with confidence intervals, and explicit yes/no
flags for:

```text
external data fetch
fold plan v2 magnitude gates passed
trial accounting invalidation recorded
holdout consumed
exposure rule or buckets tuned after first run
HMM/HSMM training modified
decision or trading output
```
