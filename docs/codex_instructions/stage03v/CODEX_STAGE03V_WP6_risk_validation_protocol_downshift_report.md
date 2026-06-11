# CODEX_STAGE03V_WP6_risk_validation_protocol_downshift_report

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP6-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP6_risk_validation_protocol_downshift_report.md`

Suggested branch: `stage03v/wp6-risk-validation-downshift-report`

## Instruction

Start from updated `main`. Confirm PR84 / `STAGE03V-WP5-v1` has been merged and that `reports/stage03v/calibration_readiness_report.json` has `status=pass`, zero leakage violations, zero calibration-boundary violations, and `prospective_holdout_rows_evaluated=0`.

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_WP6_risk_validation_protocol_downshift_report.md
```

Do not execute WP7 or any final-gate work.

## Boundary reminders

WP6 is a risk validation protocol and downshift research-report package. It prepares a historical-development validation evidence pack for WP7.

It must not:

```text
fetch external data
consume, score, inspect, or evaluate prospective final holdout rows
create trading, buy/sell, sizing, recommendation, portfolio action, execution, or UI decision outputs
mutate fixed-threshold target rows or labels
replace the fixed-threshold Stage03V1 mainline with volatility-scaled labels
train new model families
recalibrate probabilities beyond reading WP5 calibration artifacts
reassign readiness beyond protocol-level validation status
write persistent DB tables by default
commit full target, feature, raw-score, calibrated-score, or event matrices
modify HMM or HSMM training algorithms
implement Stage03V2 or Stage03V3
```

Use the return format specified in the work package when opening the PR.
