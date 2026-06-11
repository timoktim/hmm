# CODEX_STAGE03V_WP7_stage03v1_final_gate

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP7-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP7_stage03v1_final_gate.md`

Suggested branch: `stage03v/wp7-stage03v1-final-gate`

## Instruction

Start from updated `main`. Confirm PR85 / `STAGE03V-WP6-v1` has been merged and that `reports/stage03v/risk_validation_report.json` has `status=pass`, zero leakage violations, zero validation-boundary violations, and `prospective_holdout_rows_evaluated=0`.

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_WP7_stage03v1_final_gate.md
```

Do not open Stage03V2, Stage03V3, Stage04, UI, trading, or decision-engine work.

## Boundary reminders

WP7 is the Stage03V1 final gate package. It aggregates accepted WP0-WP6 artifacts and emits a final gate verdict.

It must not:

```text
fetch external data
train new models
recalibrate probabilities
reassign readiness categories
mutate target rows or labels
replace the fixed-threshold Stage03V1 target mainline with volatility-scaled labels
implement Stage03V2 or Stage03V3
consume prospective holdout performance unless explicitly authorized
claim decision-support promotion if the prospective holdout gate is insufficient or unconsumed
write persistent DB tables by default
commit full target, feature, raw-score, calibrated-score, or event matrices
create UI, trading, buy/sell, sizing, recommendation, portfolio action, execution, or decision outputs
```

The expected current outcome may be a historical/research pass with prospective decision-support promotion deferred if the prospective holdout is insufficient or unconsumed.

Use the return format specified in the work package when opening the PR.
