# CODEX_STAGE03V_WP4_logistic_downside_risk_hazard_v1

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP4-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md`

Suggested branch: `stage03v/wp4-logistic-downside-risk-hazard-v1`

## Instruction

Start from updated `main`. Confirm PR82 / `STAGE03V-WP3.5-v1` has been merged and that `reports/stage03v/vol_scaled_threshold_sanity_report.json` has `status=pass` and `wp4_entry_recommendation=proceed_with_vol_scaled_candidate_tracking`.

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md
```

Do not execute WP5 or later work.

## Required boundary reminders

WP4 is the logistic downside-risk hazard package. It is allowed to train deterministic logistic hazard models on historical-development training folds only.

It must not:

```text
fetch external data
consume or evaluate prospective final holdout rows
calibrate probabilities
assign readiness / usable_probability / ordinal_only / baseline_only
replace the fixed-threshold Stage03V1 target mainline with volatility-scaled labels
implement Stage03V2 or Stage03V3
modify HMM or HSMM training algorithms
create UI, trading, buy/sell, sizing, recommendation, or decision outputs
commit full target, feature, or score matrices
write persistent DB tables by default
```

Use the return format specified in the work package when opening the PR.
