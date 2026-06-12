# CODEX_STAGE03V_CLOSEOUT1_artifact_freeze

Repository: `timoktim/hmm`

Index id: `STAGE03V-CLOSEOUT1-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_CLOSEOUT1_artifact_freeze.md`

Suggested branch: `stage03v/closeout1-artifact-freeze`

## Instruction

Start from updated `main`. Confirm PR90 / `STAGE03V-WP7-v2` has been merged and that the final gate artifacts are present and pass:

```text
reports/stage03v/stage03v1_final_gate_v2_report.json
reports/stage03v/stage03v1_final_gate_v2_verdict.json
reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json
reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json
reports/stage03v/stage03v1_prospective_holdout_status_v2.json
reports/stage03v/stage03v1_post_gate_action_plan_v2.md
```

Then execute only the work package below:

```text
docs/work_packages/stage03v/STAGE03V_CLOSEOUT1_artifact_freeze.md
```

If PR90 is not merged, emit `blocked_wp7_v2_not_accepted` and stop.

## Boundary reminders

This is a closeout / artifact-freeze package only.

It must not:

```text
run new empirical experiments
train or refit models
recalibrate probabilities
reassign readiness
modify targets, universes, folds, exposure rules, or bucket rules
consume, score, inspect, or evaluate prospective holdout performance
implement Stage03V2 or Stage03V3
create UI, trading, buy/sell, sizing, recommendation, execution, portfolio-action, or decision outputs
write persistent DuckDB tables
commit full target, feature, raw-score, calibrated-score, exposure, or event matrices
```

The package must freeze the Stage03V1 first-phase conclusion:

```text
engineering_result: pass
causality_result: pass
model_discrimination_result: pass
primary_risk_downshift_result: baseline_superior_on_primary_risk_metrics
secondary_return_result: model_retains_more_return_secondary_metric
prospective_holdout_result: defer_or_insufficient
stage03v1_decision_support_status: not_promoted
stage03v1_model_usage_status: research_only_overlay
stage03v1_baseline_usage_status: volatility_baseline_primary_for_risk_control_research
```

Use the return format specified in the work package when opening the PR.
