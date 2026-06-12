# STAGE03V_CLOSEOUT1_artifact_freeze

Stage: 03V / Volatility and downside-risk hazard

Work package: CLOSEOUT1

Index id: `STAGE03V-CLOSEOUT1-v1`

Suggested branch: `stage03v/closeout1-artifact-freeze`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_CLOSEOUT1_artifact_freeze.md`

Date: 2026-06-12

## Objective

Freeze the Stage03V1 first-phase artifact set after WP7-v2, record the final accepted interpretation, prevent future accidental citation of invalidated artifacts, and create a clean handoff into Stage03V Phase 2.

This package is a closeout / documentation / manifest package only. It must not run new experiments, train models, recalibrate probabilities, reassign readiness, consume prospective holdout, or change the Stage03V1 final gate verdict.

## Execution precondition

This package may run only after PR90 / `STAGE03V-WP7-v2` is merged into `main`.

Required accepted final gate facts:

```text
final_gate_verdict: PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
model_discrimination_status: model_discrimination_pass
primary_risk_metric_comparison_status: baseline_superior_on_primary_risk_metrics
secondary_return_status: model_retains_more_return_secondary_metric
prospective_holdout_readiness_gate_status: defer_or_insufficient
decision_support_promotion_gate_status: defer_or_reject_model_as_primary_downshift_driver
registered_holdout_min_complete_20d_label_trade_dates: 120
registered_holdout_min_market_event_blocks: 2
prospective_holdout_rows_evaluated: 0
prospective_holdout_consumption_count: 0
```

If PR90 is not merged or the WP7-v2 final gate artifacts are absent, emit `blocked_wp7_v2_not_accepted` and stop.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_RERUN1_full_scale_revalidation.md
docs/work_packages/stage03v/STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md
reports/stage03v/validation_trial_accounting.json
reports/stage03v/purge_embargo_fold_plan_v2.json
reports/stage03v/fold_plan_magnitude_overview.md
reports/stage03v/logistic_hazard_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/downshift_experiment_report.json
reports/stage03v/downshift_experiment_arm_metrics.csv
reports/stage03v/stage03v1_final_gate_v2_report.json
reports/stage03v/stage03v1_final_gate_v2_verdict.json
reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv
reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json
reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json
reports/stage03v/stage03v1_prospective_holdout_status_v2.json
reports/stage03v/stage03v1_post_gate_action_plan_v2.md
```

## Stage boundary

Allowed:

- Read accepted WP0-WP3.5, FIX1, RERUN1, and WP7-v2 artifacts.
- Create first-phase closeout reports and artifact-freeze manifests.
- Record invalidated artifact rules for old microfold WP4-WP6 and old WP7-v1.
- Record the final Stage03V1 first-phase verdict and interpretation.
- Create a Phase 2 handoff document that states baseline-first direction, hazard-overlay research role, and prospective holdout discipline.
- Update `STAGE03V_EXECUTION_INDEX.md` to mark Stage03V1 first phase closed after WP7-v2.

Forbidden:

- Do not run new empirical experiments.
- Do not retrain or refit models.
- Do not recalibrate probabilities.
- Do not reassign readiness.
- Do not modify target definitions, fixed-threshold target rows, universes, folds, exposure rules, or bucket rules.
- Do not consume, score, inspect, or evaluate prospective final holdout performance.
- Do not implement Stage03V2 or Stage03V3.
- Do not create trading, buy/sell, sizing, recommendation, execution, portfolio-action, or UI decision outputs.
- Do not modify HMM / HSMM training algorithms.
- Do not write persistent DuckDB tables.
- Do not commit full target, feature, raw-score, calibrated-score, exposure, or event matrices.

## Required deliverables

Create:

```text
reports/stage03v/stage03v1_phase1_closeout_report.md
reports/stage03v/stage03v1_phase1_closeout_report.json
reports/stage03v/stage03v1_artifact_freeze_manifest.json
reports/stage03v/stage03v1_invalidated_artifact_registry.json
reports/stage03v/stage03v1_phase2_handoff.md
reports/stage03v/stage03v1_phase2_handoff.json
docs/roadmap/STAGE03V_PHASE1_CLOSEOUT_AND_PHASE2_HANDOFF.md
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Optional only if useful:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
```

Do not overwrite WP7-v2 outputs.

## Artifact freeze manifest requirements

The artifact freeze manifest must list accepted canonical first-phase artifacts and their role:

```text
WP0 contract artifacts
WP0.5 feasibility artifacts
WP1 target artifacts
WP2 target-control artifacts
WP2.1 full-target audit artifacts
WP3 baseline diagnostics artifacts
WP3.5 volatility-scaled sanity artifacts
FIX1 contract repairs
RERUN1 fold plan v2 and trial-accounting artifacts
RERUN1 regenerated WP4 logistic hazard artifacts
RERUN1 regenerated WP5 calibration/readiness artifacts
RERUN1 B2 downshift experiment artifacts
WP7-v2 final gate artifacts
```

For each canonical artifact, record:

```text
path
artifact_class
source_stage_or_package
status
canonical_for_stage03v1_phase1: yes/no
supersedes
superseded_by
usage_policy
```

## Invalidated artifact registry requirements

The invalidated artifact registry must explicitly mark the following as non-canonical evidence:

```text
reports/stage03v/purge_embargo_fold_plan.json
original WP4 empirical outputs produced from the 2014 microfold plan
original WP5 empirical outputs produced from the 2014 microfold plan
original WP6 risk_validation_report.json / downshift_research_report.json / wp7_final_gate_input_manifest.json
old WP7-v1 final gate outputs, if present
```

For each invalidated artifact or artifact class, record:

```text
artifact_or_pattern
invalidated_reason
not_invalidated_due_to_observed_results: true/false
superseded_by
allowed_future_usage
forbidden_future_usage
```

Required invalidation status:

```text
invalidated_due_to_fold_coverage
```

The registry must state that old WP4-WP6 empirical artifacts must not be cited as evidence of signal strength or weakness.

## Closeout report requirements

The closeout report must state the final interpretation exactly and separately:

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

It must include headline evidence from WP7-v2:

```text
candidate_slice_count
scored_candidate_slice_count
validation_entity_day_count
wp4_validation_rows_evaluated
wp5_usable_probability_candidate_count
model_minus_baseline_delta_count
model_better_primary_risk_delta_count
baseline_better_primary_risk_delta_count
significant_model_better_primary_risk_delta_count
significant_baseline_better_primary_risk_delta_count
registered_holdout_min_complete_20d_label_trade_dates
registered_holdout_min_market_event_blocks
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
```

## Phase 2 handoff requirements

The Phase 2 handoff must recommend a baseline-first route:

```text
phase2_primary_direction: baseline_first_risk_control_architecture
primary_baseline_family: realized_volatility
model_role: research_only_hazard_overlay
prospective_holdout_role: future_authorized_quarterly_review_only
stage03v2_status: placeholder_not_started
stage03v3_status: placeholder_not_started
```

Recommended Phase 2 package sequence:

```text
PHASE2-WP0: Stage03V Phase 1 Closeout and Phase 2 Baseline-First Roadmap
PHASE2-WP1: Volatility Baseline Risk Overlay Artifact
PHASE2-WP2: Hazard-as-Overlay Residual Research
PHASE2-WP3: Prospective Holdout Ledger and Quarterly Review Harness
PHASE2-WP4: Research Console / Casebook Integration
```

The handoff must explicitly warn against immediate complex-model escalation unless a new pre-registered hypothesis is created.

## Required report JSON fields

Create `reports/stage03v/stage03v1_phase1_closeout_report.json` with at least:

```text
index_id
report_version
status
wp7_v2_status
wp7_v2_final_gate_verdict
stage03v1_phase1_status
phase1_closeout_status
artifact_freeze_manifest_path
invalidated_artifact_registry_path
phase2_handoff_path
canonical_artifact_count
invalidated_artifact_count
engineering_result
causality_result
model_discrimination_result
primary_risk_downshift_result
secondary_return_result
prospective_holdout_result
stage03v1_decision_support_status
stage03v1_model_usage_status
stage03v1_baseline_usage_status
recommended_phase2_direction
phase2_should_start_immediately
phase2_immediate_next_package
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
boundary_flags
blocking_reasons
remaining_risks
```

Boundary flags must include:

```text
external_data_fetch: no
new_experiment_run: no
model_training: no
probability_recalibration: no
readiness_reassigned: no
target_dataset_modified: no
fixed_threshold_mainline_modified: no
prospective_holdout_performance_consumed: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Tests / validation

Create tests only if the package adds code. If this package is documentation/report-only, no new Python module is required. At minimum, add or run a lightweight validation script if existing project style supports it.

Required validations:

```text
WP7-v2 artifacts exist and report status pass.
Final gate verdict matches PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE.
Artifact freeze manifest references RERUN1 artifacts.
Invalidated artifact registry marks old microfold WP4-WP6 and old WP7-v1 evidence as non-canonical.
Phase2 handoff states baseline-first route.
No holdout consumed.
No trading/decision output.
JSON artifacts are valid.
Private path hygiene passes.
```

## Suggested commands

Run at minimum:

```bash
python -m json.tool reports/stage03v/stage03v1_final_gate_v2_report.json
python -m json.tool reports/stage03v/stage03v1_final_gate_v2_verdict.json
python -m json.tool reports/stage03v/stage03v1_phase1_closeout_report.json
python -m json.tool reports/stage03v/stage03v1_artifact_freeze_manifest.json
python -m json.tool reports/stage03v/stage03v1_invalidated_artifact_registry.json
python -m json.tool reports/stage03v/stage03v1_phase2_handoff.json
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

If tests are added:

```bash
python -m compileall -q src tests
pytest -q <new closeout tests>
pytest -q -m "not slow"
```

## Acceptance criteria

CLOSEOUT1 passes if:

- PR90 / WP7-v2 is merged and accepted before execution.
- WP7-v2 final gate artifacts are present and pass.
- Closeout report freezes the exact Stage03V1 first-phase verdict.
- Artifact freeze manifest identifies canonical Stage03V1 phase-one artifacts.
- Invalidated artifact registry prevents reuse of old microfold WP4-WP6 and old WP7-v1 evidence.
- Phase 2 handoff recommends baseline-first risk-control architecture and hazard-as-overlay research.
- No new empirical work, model training, recalibration, readiness reassignment, holdout consumption, or trading/decision output occurs.

## Return format

```text
index_id: STAGE03V-CLOSEOUT1-v1
branch: stage03v/closeout1-artifact-freeze
PR: ...
status: pass / partial / fail

commands run:
- ...

files changed:
- ...

WP7-v2 merged: yes/no
WP7-v2 final gate verdict: ...
artifact freeze manifest path: ...
invalidated artifact registry path: ...
phase2 handoff path: ...
canonical artifact count: ...
invalidated artifact count: ...

engineering result: pass/other
causality result: pass/other
model discrimination result: pass/other
primary risk downshift result: baseline_superior_on_primary_risk_metrics/other
secondary return result: model_retains_more_return_secondary_metric/other
prospective holdout result: defer_or_insufficient/other
stage03v1 decision support status: not_promoted
recommended phase2 direction: baseline_first_risk_control_architecture

external data fetch: no
new experiment run: no
model training: no
probability recalibration: no
readiness reassigned: no
target dataset modified: no
fixed threshold mainline modified: no
prospective holdout performance consumed: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
