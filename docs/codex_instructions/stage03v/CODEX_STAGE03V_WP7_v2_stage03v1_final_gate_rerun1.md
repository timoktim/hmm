# CODEX_STAGE03V_WP7_v2_stage03v1_final_gate_rerun1

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP7-v2`

Work package: `docs/work_packages/stage03v/STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md`

Suggested branch: `stage03v/wp7-v2-stage03v1-final-gate-rerun1`

## Instruction

Start from updated `main`. Confirm PR89 / `STAGE03V-RERUN1-v1` has been merged and that RERUN1 artifacts are present and pass:

```text
reports/stage03v/purge_embargo_fold_plan_v2.json
reports/stage03v/logistic_hazard_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/downshift_experiment_report.json
reports/stage03v/downshift_experiment_arm_metrics.csv
reports/stage03v/validation_trial_accounting.json
```

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md
```

Do not use the old WP7-v1 work package as implementation source. Do not use old WP6 tier aggregation reports as final evidence.

## Required deltas

WP7-v2 must explicitly implement these three changes:

```text
1. Input manifest points to RERUN1 artifacts, especially purge_embargo_fold_plan_v2.json and downshift_experiment_report.json.
2. Verdict logic separates model discrimination from primary risk downshift comparison and can emit baseline_superior_on_primary_risk_metrics.
3. Registered prospective holdout requirement is 120 complete 20d-label trade dates and at least 2 market event blocks. The old 60/1 threshold is forbidden.
```

## Boundary reminders

WP7-v2 is a final-gate package after RERUN1 full-scale revalidation.

It must not:

```text
fetch external data
train new models
recalibrate probabilities
reassign readiness categories
consume prospective holdout performance unless explicitly authorized
claim decision-support promotion when baseline is superior on primary risk metrics
claim decision-support promotion when holdout is insufficient or unconsumed
mutate target rows, labels, support reports, readiness matrices, or RERUN1 artifacts
replace fixed-threshold Stage03V1 with volatility-scaled labels
implement Stage03V2 or Stage03V3
write persistent DB tables by default
commit full score/exposure/event matrices
create UI, trading, buy/sell, sizing, recommendation, portfolio action, execution, or decision outputs
```

Use the return format specified in the work package when opening the PR.
