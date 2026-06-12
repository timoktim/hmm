# STAGE03V_WP7_v2_stage03v1_final_gate_rerun1

Stage: 03V / Volatility and downside-risk hazard

Work package: WP7 v2

Index id: `STAGE03V-WP7-v2`

Suggested branch: `stage03v/wp7-v2-stage03v1-final-gate-rerun1`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP7_v2_stage03v1_final_gate_rerun1.md`

Date: 2026-06-12

## Objective

Implement the Stage03V1 final gate v2 after `STAGE03V-RERUN1-v1` full-scale revalidation.

WP7-v1 is closed and superseded. WP7-v2 must consume the accepted RERUN1 artifacts, not the invalidated WP6 tier aggregation artifacts. It must express the actual RERUN1/B2 result: the calibrated hazard model has real discrimination, but the volatility baseline is superior on pre-registered primary risk downshift metrics.

WP7-v2 must also correct the prospective-holdout threshold bug found in old WP7-v1. The final gate must use the registered holdout requirement:

```text
minimum complete 20d-label holdout trade dates: 120
minimum independent market event blocks in holdout: 2
```

The old accidental threshold of `60 trade dates / 1 event block` is forbidden and must be covered by tests.

## Delta from WP7-v1

WP7-v2 has three mandatory deltas:

1. RERUN1 input manifest replacement.

   WP7-v2 must point to RERUN1 full-scale artifacts:

   ```text
   reports/stage03v/purge_embargo_fold_plan_v2.json
   reports/stage03v/fold_plan_magnitude_overview.md
   reports/stage03v/fold_plan_magnitude_overview.csv
   reports/stage03v/validation_trial_accounting.json
   reports/stage03v/logistic_hazard_report.json
   reports/stage03v/calibration_readiness_report.json
   reports/stage03v/downshift_experiment_report.json
   reports/stage03v/downshift_experiment_arm_metrics.csv
   ```

   Do not use old `reports/stage03v/risk_validation_report.json`, `reports/stage03v/downshift_research_report.json`, or `reports/stage03v/wp7_final_gate_input_manifest.json` as final evidence. They may be referenced only as invalidated legacy artifacts.

2. Verdict state expansion for B2.

   WP7-v2 must separate these facts:

   ```text
   model_discrimination_status: model_discrimination_pass
   primary_risk_metric_comparison_status: baseline_superior_on_primary_risk_metrics
   secondary_return_status: model_retains_more_return_secondary_metric
   decision_support_promotion_gate_status: defer_or_reject_model_as_primary_downshift_driver
   ```

   Historical validation must not collapse this into a generic `research_pass`.

3. Registered holdout threshold correction.

   WP7-v2 must enforce:

   ```text
   prospective_holdout_min_complete_20d_label_trade_dates: 120
   prospective_holdout_min_market_event_blocks: 2
   ```

   The final gate must fail a policy/config test if `60` or `1` appears as the active holdout minimum. These registered values cannot be silently lowered inside implementation.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_RERUN1_full_scale_revalidation.md
docs/work_packages/stage03v/STAGE03V_FIX1_contract_repairs.md
docs/work_packages/stage03v/STAGE03V_WP7_stage03v1_final_gate.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/stage03v_wp0_scope_freeze_report.json
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/purge_embargo_fold_plan_v2.json
reports/stage03v/fold_plan_magnitude_overview.md
reports/stage03v/fold_plan_magnitude_overview.csv
reports/stage03v/validation_trial_accounting.json
reports/stage03v/logistic_hazard_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/downshift_experiment_report.json
reports/stage03v/downshift_experiment_arm_metrics.csv
```

## Required preconditions

WP7-v2 may proceed only if all are true:

```text
PR89 / STAGE03V-RERUN1-v1: merged
RERUN1 B0 fold plan v2 magnitude gate: pass
RERUN1 B1 logistic hazard rerun: pass
RERUN1 B1 calibration/readiness rerun: pass
RERUN1 B2 three-arm downshift experiment: pass
V7 coverage: yes
SW2021 L2 universe: pass
source DB: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
fold plan path: reports/stage03v/purge_embargo_fold_plan_v2.json
validation entity days >= 5,000,000 or exact accepted RERUN1 count
WP4 validation rows evaluated >= 6,000,000 or exact accepted RERUN1 count
WP5 usable_probability_candidate_count >= 5 or exact accepted RERUN1 count
B2 prospective holdout scores: 0
holdout consumed: no
trial accounting invalidation recorded: yes
```

If any precondition fails, emit `blocked_rerun1_not_ready` and stop.

## Stage boundary

Allowed:

- Read V7 DuckDB read-only.
- Read accepted WP0-WP3.5 artifacts and RERUN1 artifacts.
- Verify RERUN1 supersession of invalidated microfold WP4-WP6 artifacts.
- Verify fold-plan magnitude, trial-accounting invalidation, RERUN1 model discrimination, calibration/readiness, and B2 downshift experiment evidence.
- Emit final gate report, verdict JSON, evidence matrix, artifact manifest, RERUN1 input manifest, prospective holdout status, post-gate action plan, and capped audit sample.

Forbidden:

- Do not fetch external data.
- Do not train new models.
- Do not recalibrate probabilities.
- Do not reassign readiness categories.
- Do not rerun the B2 experiment except for read-only consistency checks.
- Do not consume prospective final holdout performance.
- Do not mutate target rows, labels, support reports, readiness matrices, or RERUN1 artifacts.
- Do not replace fixed-threshold Stage03V1 target family with volatility-scaled labels.
- Do not implement Stage03V2 or Stage03V3.
- Do not write persistent DuckDB tables by default.
- Do not commit full target, feature, raw-score, calibrated-score, exposure, or event matrices.
- Do not create UI, trading, buy/sell, sizing, recommendation, portfolio action, execution, or decision outputs.

## Final gate semantics

WP7-v2 must distinguish these layers:

```text
engineering_gate_status
causality_gate_status
rerun1_magnitude_gate_status
model_discrimination_gate_status
calibration_readiness_gate_status
primary_risk_metric_comparison_status
secondary_return_metric_status
prospective_holdout_readiness_gate_status
decision_support_promotion_gate_status
```

Required B2-aware statuses:

```text
model_discrimination_status:
  - model_discrimination_pass
  - model_discrimination_weak
  - model_discrimination_fail

primary_risk_metric_comparison_status:
  - baseline_superior_on_primary_risk_metrics
  - model_superior_on_primary_risk_metrics
  - inconclusive_on_primary_risk_metrics
  - blocked_missing_b2_evidence

secondary_return_status:
  - model_retains_more_return_secondary_metric
  - baseline_retains_more_return_secondary_metric
  - inconclusive_secondary_return_metric
  - not_evaluated
```

Allowed final verdicts:

```text
PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
PASS_RESEARCH_ONLY_BASELINE_SUPERIOR_ON_PRIMARY_RISK_METRICS
DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT
FAIL_BOUNDARY_OR_LEAKAGE
FAIL_INPUT_ARTIFACTS
FAIL_RERUN1_EVIDENCE_INCONSISTENT
FAIL_VALIDATION_EVIDENCE
BLOCKED_INPUTS_NOT_READY
```

Decision-support promotion is forbidden when:

```text
primary_risk_metric_comparison_status == baseline_superior_on_primary_risk_metrics
or prospective_holdout_readiness_gate_status != pass
or prospective_holdout_performance_consumed == no
or any upstream boundary/leakage count > 0
```

## B2 result interpretation requirements

WP7-v2 must read `reports/stage03v/downshift_experiment_report.json` and `reports/stage03v/downshift_experiment_arm_metrics.csv` and summarize:

```text
candidate_slice_count
scored_candidate_slice_count
validation_entity_day_count
prospective_holdout_score_count
baseline_name / baseline_family selections
model_minus_baseline_delta_count
model_better_primary_risk_delta_count
baseline_better_primary_risk_delta_count
significant_model_better_primary_risk_delta_count
significant_baseline_better_primary_risk_delta_count
primary_risk_metric_ci_status_summary
secondary_return_metric_summary
```

Primary risk metrics are:

```text
max_drawdown
cvar_95
realized_volatility
```

Primary interpretation rule:

```text
If no significant model-better primary-risk delta exists and any significant baseline-better primary-risk delta exists, set primary_risk_metric_comparison_status = baseline_superior_on_primary_risk_metrics.
```

The report must explicitly state that model discrimination and downshift control are separate claims.

Required narrative fields:

```text
model_discrimination_claim
primary_risk_downshift_claim
secondary_return_claim
recommended_use_after_gate
```

Expected narrative content:

```text
model_discrimination_claim: model_has_validated_discrimination_on_full_scale_rerun
primary_risk_downshift_claim: volatility_baseline_superior_for_primary_risk_reduction
default_recommended_use_after_gate: research_only_model_overlay_or_volatility_baseline_primary
```

## Prospective holdout policy

Locked Stage03V dates:

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
```

Registered holdout requirements:

```text
prospective_holdout_min_complete_20d_label_trade_dates: 120
prospective_holdout_min_market_event_blocks: 2
prospective_holdout_review_cadence: quarterly
prospective_holdout_consumption_accounting_required: true
```

Forbidden WP7-v2 active requirements:

```text
prospective_holdout_min_complete_20d_label_trade_dates: 60
prospective_holdout_min_market_event_blocks: 1
```

WP7-v2 must report:

```text
prospective_holdout_rows_available
prospective_holdout_complete_20d_label_trade_dates
prospective_holdout_market_event_block_count
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
prospective_holdout_minimum_requirement_status
prospective_holdout_stress_event_requirement_status
prospective_holdout_gate_status
prospective_holdout_threshold_source
```

Default behavior:

```text
prospective_holdout_rows_evaluated: 0
prospective_holdout_consumption_count: 0
prospective_holdout_evaluation_authorized: false
prospective_holdout_gate_status: defer_or_insufficient
```

Do not evaluate prospective holdout performance unless a later explicit package or operator action authorizes it.

## Required deliverables

Create:

```text
src/evaluation/stage03v_final_gate_v2.py
scripts/stage03v_final_gate_v2.sh
tests/test_stage03v_final_gate_v2.py
tests/test_stage03v_final_gate_v2_boundaries.py
configs/stage03v_final_gate_policy_v2.yaml
reports/stage03v/stage03v1_final_gate_v2_report.md
reports/stage03v/stage03v1_final_gate_v2_report.json
reports/stage03v/stage03v1_final_gate_v2_verdict.json
reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv
reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json
reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json
reports/stage03v/stage03v1_prospective_holdout_status_v2.json
reports/stage03v/stage03v1_post_gate_action_plan_v2.md
reports/stage03v/stage03v1_final_gate_v2_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Do not overwrite old WP7-v1 outputs except where explicitly superseded in index/report metadata.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_final_gate_v2 \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan-v2 reports/stage03v/purge_embargo_fold_plan_v2.json \
  --fold-magnitude-overview reports/stage03v/fold_plan_magnitude_overview.csv \
  --trial-accounting reports/stage03v/validation_trial_accounting.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --downshift-experiment reports/stage03v/downshift_experiment_report.json \
  --downshift-arm-metrics reports/stage03v/downshift_experiment_arm_metrics.csv \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v2.yaml \
  --output reports/stage03v/stage03v1_final_gate_v2_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_v2_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_v2_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json \
  --rerun1-input-manifest reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status_v2.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan_v2.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_v2_audit_sample.csv \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise use `data/db/a_share_hmm_tushare_v7.duckdb`.
- If V7 DB is missing or invalid, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Never fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB.

## Required report JSON fields

Create `reports/stage03v/stage03v1_final_gate_v2_report.json` with at least:

```text
index_id
report_version
status
final_gate_verdict
stage03v1_gate_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
information_cutoff_date
holdout_start
wp0_scope_freeze_status
wp0_5_sample_feasibility_status
wp1_target_support_status
wp2_target_controls_status
wp2_1_full_target_audit_status
wp3_baseline_diagnostics_status
wp3_5_vol_scaled_sanity_status
rerun1_fold_plan_v2_status
rerun1_logistic_hazard_status
rerun1_calibration_readiness_status
rerun1_downshift_experiment_status
trial_accounting_invalidation_recorded
engineering_gate_status
causality_gate_status
rerun1_magnitude_gate_status
model_discrimination_gate_status
calibration_readiness_gate_status
primary_risk_metric_comparison_status
secondary_return_metric_status
prospective_holdout_readiness_gate_status
decision_support_promotion_gate_status
model_discrimination_claim
primary_risk_downshift_claim
secondary_return_claim
recommended_use_after_gate
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
prospective_holdout_complete_20d_label_trade_dates
prospective_holdout_market_event_block_count
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
prospective_holdout_minimum_requirement_status
prospective_holdout_stress_event_requirement_status
prospective_holdout_threshold_source
artifact_manifest_path
rerun1_input_manifest_path
evidence_matrix_path
verdict_json_path
holdout_status_path
post_gate_action_plan_path
leakage_violation_counts
boundary_violation_counts
ci_gate_status
boundary_flags
blocking_reasons
remaining_risks
```

Boundary flags must include:

```text
external_data_fetch: no
target_dataset_modified: no
fixed_threshold_mainline_modified: no
persistent_db_table_written: no
full_target_matrix_committed: no
full_feature_matrix_committed: no
full_raw_score_matrix_committed: no
full_calibrated_score_matrix_committed: no
full_exposure_matrix_committed: no
model_training: no
probability_recalibration: no
readiness_reassigned: no
final_gate_executed: yes
prospective_holdout_performance_consumed: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Policy config

Create `configs/stage03v_final_gate_policy_v2.yaml`.

Minimum fields:

```text
index_id: STAGE03V-WP7-v2
policy_version: stage03v_final_gate_policy_v2
supersedes: STAGE03V-WP7-v1
supersession_reason: rerun1_full_scale_revalidation_replaced_invalidated_wp6_tier_aggregation
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
primary_target_family: fixed_threshold_stage03v1_downside_event
vol_scaled_candidate_policy: tracked_reference_only
stage03v2_policy: placeholder_only
stage03v3_policy: placeholder_only
final_gate_scope: stage03v1_downside_risk_only
required_inputs:
  fold_plan: reports/stage03v/purge_embargo_fold_plan_v2.json
  trial_accounting: reports/stage03v/validation_trial_accounting.json
  logistic_hazard: reports/stage03v/logistic_hazard_report.json
  calibration_readiness: reports/stage03v/calibration_readiness_report.json
  downshift_experiment: reports/stage03v/downshift_experiment_report.json
  downshift_arm_metrics: reports/stage03v/downshift_experiment_arm_metrics.csv
legacy_invalidated_inputs_forbidden_as_evidence:
  - reports/stage03v/risk_validation_report.json
  - reports/stage03v/downshift_research_report.json
  - reports/stage03v/wp7_final_gate_input_manifest.json
prospective_holdout_policy: defer_if_registered_minimum_not_met
prospective_holdout_evaluation_authorized: false
prospective_holdout_min_complete_20d_label_trade_dates: 120
prospective_holdout_min_market_event_blocks: 2
prospective_holdout_review_cadence: quarterly
allow_decision_support_promotion_without_holdout: false
primary_risk_metrics:
  - max_drawdown
  - cvar_95
  - realized_volatility
allowed_final_verdicts:
  - PASS_ENGINEERING_MODEL_DISCRIMINATION_BASELINE_SUPERIOR_DEFER_PROSPECTIVE
  - PASS_RESEARCH_ONLY_BASELINE_SUPERIOR_ON_PRIMARY_RISK_METRICS
  - DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT
  - FAIL_BOUNDARY_OR_LEAKAGE
  - FAIL_INPUT_ARTIFACTS
  - FAIL_RERUN1_EVIDENCE_INCONSISTENT
  - FAIL_VALIDATION_EVIDENCE
  - BLOCKED_INPUTS_NOT_READY
forbidden_active_holdout_minimums:
  complete_20d_label_trade_dates: 60
  market_event_blocks: 1
forbidden_outputs:
  - buy
  - sell
  - position_sizing
  - execution_instruction
  - portfolio_recommendation
external_fetch_policy: forbidden
persistent_db_table_policy: forbidden_by_default
full_score_matrix_policy: forbidden_to_commit
```

JSON-formatted YAML is acceptable if consistent with existing repo practice.

## Gate script

Create `scripts/stage03v_final_gate_v2.sh`.

It must:

- Prefer `STAGE03V_V7_DB`.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall.
- Run WP7-v2-specific tests.
- Run WP7-v2 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_FINAL_GATE_V2=<status> verdict=<verdict> primary_risk=<status> model_discrimination=<status> holdout_min_20d_days=<n> holdout_min_blocks=<n> db=<path> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_final_gate_v2.py
tests/test_stage03v_final_gate_v2_boundaries.py
```

Minimum synthetic coverage:

- Missing V7 DB returns `blocked_missing_v7_db` and no old DB fallback when inputs are present.
- Missing/failed RERUN1 downshift experiment blocks WP7-v2.
- WP7-v2 input manifest points to `purge_embargo_fold_plan_v2.json`, RERUN1 WP4/WP5 reports, and `downshift_experiment_report.json`.
- Legacy invalidated WP6 tier reports are not accepted as final evidence.
- Policy uses 120 complete 20d-label holdout days and 2 market event blocks.
- A policy using 60 days or 1 event block fails validation.
- B2 evidence with model discrimination pass but baseline-superior primary risk deltas produces `baseline_superior_on_primary_risk_metrics`.
- B2 evidence with secondary return advantage is recorded separately and does not override primary risk verdict.
- Decision-support promotion is deferred when prospective holdout is insufficient or unconsumed.
- Final verdict is one of the allowed WP7-v2 verdicts.
- No holdout performance is consumed by default.
- No trading or decision output fields are produced.
- No full score/exposure matrices are written.
- No external fetch occurs.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_final_gate_v2.py tests/test_stage03v_final_gate_v2_boundaries.py
python -m src.evaluation.stage03v_final_gate_v2 \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan-v2 reports/stage03v/purge_embargo_fold_plan_v2.json \
  --fold-magnitude-overview reports/stage03v/fold_plan_magnitude_overview.csv \
  --trial-accounting reports/stage03v/validation_trial_accounting.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --downshift-experiment reports/stage03v/downshift_experiment_report.json \
  --downshift-arm-metrics reports/stage03v/downshift_experiment_arm_metrics.csv \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v2.yaml \
  --output reports/stage03v/stage03v1_final_gate_v2_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_v2_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_v2_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_v2_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json \
  --rerun1-input-manifest reports/stage03v/stage03v1_final_gate_v2_rerun1_input_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status_v2.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan_v2.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_v2_audit_sample.csv \
  --no-fetch
bash scripts/stage03v_final_gate_v2.sh
python -m json.tool reports/stage03v/stage03v1_final_gate_v2_report.json
python -m json.tool reports/stage03v/stage03v1_final_gate_v2_verdict.json
python -m json.tool reports/stage03v/stage03v1_final_gate_v2_artifact_manifest.json
python -m json.tool reports/stage03v/stage03v1_prospective_holdout_status_v2.json
python -m json.tool configs/stage03v_final_gate_policy_v2.yaml
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

Also run a missing-V7 negative check to temporary outputs.

Expected missing-DB result:

```text
status: blocked_missing_v7_db
old_db_fallback: false
external_data_fetch: no
formal reports are not overwritten unless explicitly passed
negative-check outputs remain under tmp/
```

## Acceptance criteria

WP7-v2 passes if:

- RERUN1 inputs are all pass and accepted.
- V7 and SW2021 L2 verification is enforced.
- Missing V7 blocks and does not fall back.
- Input manifest points to RERUN1 artifacts, especially fold plan v2 and downshift experiment artifacts.
- Legacy invalidated WP6 tier reports are not used as final evidence.
- Registered holdout thresholds are exactly 120 complete 20d-label trade dates and 2 market event blocks.
- Policy/tests reject 60/1 holdout thresholds.
- B2 verdict separates model discrimination from baseline-superior primary risk metrics.
- Final gate does not claim decision-support promotion when baseline is superior on primary risk metrics.
- Final gate defers prospective promotion when holdout is insufficient or unconsumed.
- No holdout performance is consumed by default.
- No new model training, recalibration, readiness reassignment, full matrix commit, persistent DB write, or trading/decision output occurs.
- Stage03V2/3 remain placeholders only.
- CI and gate pass.

## Return format

```text
index_id: STAGE03V-WP7-v2
branch: stage03v/wp7-v2-stage03v1-final-gate-rerun1
PR: ...
status: pass / partial / fail

commands run:
- ...

results:
- ...

files changed:
- ...

DB used: yes/no
DB path: ...
V7 coverage verified: yes/no
SW2021 L2 universe verified: yes/no
RERUN1 fold plan v2 status: pass/other
RERUN1 logistic hazard status: pass/other
RERUN1 calibration readiness status: pass/other
RERUN1 downshift experiment status: pass/other
trial accounting invalidation recorded: yes/no

final gate verdict: ...
stage03v1 gate status: ...
engineering gate status: ...
causality gate status: ...
rerun1 magnitude gate status: ...
model discrimination status: ...
primary risk metric comparison status: ...
secondary return status: ...
prospective holdout readiness gate status: ...
decision support promotion gate status: ...
model discrimination claim: ...
primary risk downshift claim: ...
secondary return claim: ...
recommended use after gate: ...

candidate slice count: ...
scored candidate slice count: ...
validation entity day count: ...
WP4 validation rows evaluated: ...
WP5 usable probability candidate count: ...
model-minus-baseline delta count: ...
model better primary risk delta count: ...
baseline better primary risk delta count: ...
significant model better primary risk delta count: ...
significant baseline better primary risk delta count: ...

prospective holdout complete 20d-label trade dates: ...
prospective holdout market event block count: ...
registered holdout min complete 20d-label trade dates: 120
registered holdout min market event blocks: 2
prospective holdout rows evaluated: ...
prospective holdout consumption count: ...
prospective holdout minimum requirement status: ...
prospective holdout stress event requirement status: ...

external data fetch: no
target dataset modified: no
fixed threshold mainline modified: no
persistent DB table written: no
full target matrix committed: no
full feature matrix committed: no
full raw score matrix committed: no
full calibrated score matrix committed: no
full exposure matrix committed: no
model training: no
probability recalibration: no
readiness reassigned: no
final gate executed: yes
prospective holdout performance consumed: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
