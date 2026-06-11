# CODEX_STAGE03V_WP5_calibration_clustered_inference_readiness

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP5-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP5_calibration_clustered_inference_readiness.md`

Suggested branch: `stage03v/wp5-calibration-clustered-readiness`

## Instruction

Start from updated `main`. Confirm PR83 / `STAGE03V-WP4-v1` has been merged and that `reports/stage03v/logistic_hazard_report.json` has `status=pass` with zero leakage and training-boundary violations.

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_WP5_calibration_clustered_inference_readiness.md
```

Do not execute WP6 or later work.

## Boundary reminders

WP5 is the calibration, clustered inference, and development-readiness package. It is allowed to fit calibration candidates and assign development-only readiness categories.

It must not:

```text
fetch external data
consume or evaluate prospective final holdout rows
modify fixed-threshold target rows or labels
replace the fixed-threshold Stage03V1 mainline with volatility-scaled labels
train new non-logistic model families
modify HMM or HSMM training algorithms
create UI, trading, buy/sell, sizing, recommendation, or decision outputs
commit full target, feature, raw score, or calibrated score matrices
write persistent DB tables by default
implement Stage03V2 or Stage03V3
```

Use the return format specified in the work package when opening the PR.
