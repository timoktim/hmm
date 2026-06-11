# STAGE03V_WP7_stage03v1_final_gate

Stage: 03V / Volatility and downside-risk hazard

Work package: WP7

Index id: `STAGE03V-WP7-v1`

Suggested branch: `stage03v/wp7-stage03v1-final-gate`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP7_stage03v1_final_gate.md`

Date: 2026-06-11

## Objective

Implement the Stage03V1 Final Gate.

WP7 is the final aggregation and gate package for the Stage03V1 downside-risk branch. It must consume accepted WP0-WP6 artifacts, verify that all required contracts and boundary conditions hold, summarize historical-development evidence, check prospective-holdout readiness, and emit a final Stage03V1 gate verdict.

WP7 must not train new models, recalibrate probabilities, change readiness, alter target datasets, implement Stage03V2 / Stage03V3, or generate trading/decision outputs.

Important: Stage03V1 can pass engineering and historical-development validation gates before the prospective holdout is large enough. However, decision-support promotion must remain `DEFER` until prospective holdout minimum size and stress-event requirements are satisfied. If the holdout is insufficient or unconsumed, the correct final verdict is a defer/conditional verdict, not a false pass.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md
docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md
docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md
docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md
docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md
docs/work_packages/stage03v/STAGE03V_WP3_volatility_range_empirical_baselines.md
docs/work_packages/stage03v/STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate.md
docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md
docs/work_packages/stage03v/STAGE03V_WP5_calibration_clustered_inference_readiness.md
docs/work_packages/stage03v/STAGE03V_WP6_risk_validation_protocol_downshift_report.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
configs/stage03v_logistic_hazard_policy_v1.yaml
configs/stage03v_calibration_readiness_policy_v1.yaml
configs/stage03v_risk_validation_protocol_policy_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/stage03v_wp0_scope_freeze_report.json
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/logistic_hazard_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/risk_validation_report.json
reports/stage03v/downshift_research_report.json
reports/stage03v/wp7_final_gate_input_manifest.json
```

## Required preconditions

WP7 may proceed only if all are true:

```text
WP0 scope freeze: pass
WP0.5 sample feasibility: pass
WP1 target support: pass
WP2 target controls: pass
WP2.1 full target audit: pass
WP3 baseline diagnostics: pass
WP3.5 volatility-scaled sanity: pass
WP4 logistic hazard: pass
WP5 calibration readiness: pass
WP6 risk validation: pass
V7 coverage: yes
SW2021 L2 universe: pass
source DB: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
WP6 historical_development_only: yes
WP6 leakage violation total: 0
WP6 validation boundary violation total: 0
WP6 prospective holdout rows evaluated: 0
WP6 trading_or_decision_output: no
WP6 wp7_final_gate_input_manifest status: prepared_for_wp7
WP6 wp7_final_gate_executed: no
```

If any precondition fails, emit `blocked_wp6_not_ready` and stop.

## Stage boundary

Allowed:

- Read V7 DuckDB read-only.
- Read accepted WP0-WP6 artifacts.
- Verify artifact consistency, report hashes, route anchors, boundary flags, and locked dates.
- Summarize Stage03V1 historical-development evidence.
- Evaluate whether Stage03V1 meets engineering, causal, validation, and prospective-holdout readiness gates.
- Emit a final gate report, evidence matrix, verdict JSON, and post-gate checklist.

Forbidden:

- Do not fetch external data.
- Do not train new models.
- Do not recalibrate probabilities.
- Do not reassign readiness categories.
- Do not mutate fixed-threshold target rows, target labels, support reports, or target universe manifests.
- Do not replace fixed-threshold Stage03V1 target family with volatility-scaled labels.
- Do not implement Stage03V2 or Stage03V3.
- Do not write persistent DuckDB tables by default.
- Do not commit full target, feature, raw-score, calibrated-score, or event matrices.
- Do not create UI, trading, buy/sell, sizing, recommendation, portfolio action, execution, or decision outputs.
- Do not claim decision-support promotion if the prospective holdout gate is insufficient or unconsumed.

## Final gate semantics

WP7 must distinguish the following layers:

```text
engineering_gate
causality_gate
historical_validation_gate
calibration_readiness_gate
risk_validation_gate
prospective_holdout_readiness_gate
decision_support_promotion_gate
```

Allowed final verdicts:

```text
PASS_ENGINEERING_HISTORICAL_DEFER_PROSPECTIVE
PASS_STAGE03V1_RESEARCH_ONLY
DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT
FAIL_BOUNDARY_OR_LEAKAGE
FAIL_INPUT_ARTIFACTS
FAIL_VALIDATION_EVIDENCE
BLOCKED_INPUTS_NOT_READY
```

Decision-support promotion is allowed only if:

```text
all upstream artifacts pass
all boundary/leakage counts are zero
historical validation evidence is sufficient
prospective holdout minimum row/date/event/stress requirements are met
prospective holdout evaluation has been explicitly authorized and accounted for
no trading/decision output is produced
```

If prospective holdout is unavailable, too small, or deliberately unconsumed, the gate must return a defer verdict rather than a decision-support pass.

## Prospective holdout policy

The Stage03V holdout remains:

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
```

WP7 must report:

```text
prospective_holdout_policy
prospective_holdout_rows_available
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
prospective_holdout_minimum_requirement_status
prospective_holdout_stress_event_requirement_status
prospective_holdout_next_review_cadence
```

Default behavior:

```text
prospective_holdout_rows_evaluated: 0
prospective_holdout_consumption_count: 0
prospective_holdout_evaluation_authorized: false
prospective_holdout_gate_status: defer_or_insufficient
```

Do not evaluate prospective holdout performance unless a later explicit package or manual operator action authorizes it. The normal WP7 expected result at this stage is likely a historical/research pass with prospective promotion deferred.

## Required deliverables

Create:

```text
src/evaluation/stage03v_final_gate.py
scripts/stage03v_final_gate.sh
tests/test_stage03v_final_gate.py
tests/test_stage03v_final_gate_boundaries.py
configs/stage03v_final_gate_policy_v1.yaml
reports/stage03v/stage03v1_final_gate_report.md
reports/stage03v/stage03v1_final_gate_report.json
reports/stage03v/stage03v1_final_gate_verdict.json
reports/stage03v/stage03v1_final_gate_evidence_matrix.csv
reports/stage03v/stage03v1_final_gate_artifact_manifest.json
reports/stage03v/stage03v1_prospective_holdout_status.json
reports/stage03v/stage03v1_post_gate_action_plan.md
reports/stage03v/stage03v1_final_gate_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Do not commit full score/event/feature matrices.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_final_gate \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --risk-validation reports/stage03v/risk_validation_report.json \
  --downshift-research reports/stage03v/downshift_research_report.json \
  --wp7-input-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v1.yaml \
  --output reports/stage03v/stage03v1_final_gate_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_artifact_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_audit_sample.csv \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise use `data/db/a_share_hmm_tushare_v7.duckdb`.
- If V7 DB is missing or invalid, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Never fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB.

## Required report JSON fields

Create `reports/stage03v/stage03v1_final_gate_report.json` with at least:

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
historical_development_only_prior_to_wp7
wp0_scope_freeze_status
wp0_5_sample_feasibility_status
wp1_target_support_status
wp2_target_controls_status
wp2_1_full_target_audit_status
wp3_baseline_diagnostics_status
wp3_5_vol_scaled_sanity_status
wp4_logistic_hazard_status
wp5_calibration_readiness_status
wp6_risk_validation_status
engineering_gate_status
causality_gate_status
historical_validation_gate_status
calibration_readiness_gate_status
risk_validation_gate_status
prospective_holdout_readiness_gate_status
decision_support_promotion_gate_status
prospective_holdout_rows_available
prospective_holdout_rows_evaluated
prospective_holdout_consumption_count
prospective_holdout_minimum_requirement_status
prospective_holdout_stress_event_requirement_status
usable_probability_candidate_count
validation_pass_candidate_count
research_downshift_candidate_count
artifact_manifest_path
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

Create `configs/stage03v_final_gate_policy_v1.yaml`.

Minimum fields:

```text
index_id: STAGE03V-WP7-v1
policy_version: stage03v_final_gate_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
primary_target_family: fixed_threshold_stage03v1_downside_event
vol_scaled_candidate_policy: tracked_reference_only
stage03v2_policy: placeholder_only
stage03v3_policy: placeholder_only
final_gate_scope: stage03v1_downside_risk_only
historical_development_gate_policy: required
prospective_holdout_policy: defer_if_minimum_not_met
prospective_holdout_evaluation_authorized: false
prospective_holdout_min_trade_dates: 60
prospective_holdout_min_positive_events: 10
prospective_holdout_min_stress_event_blocks: 1
prospective_holdout_review_cadence: quarterly
allow_decision_support_promotion_without_holdout: false
allowed_final_verdicts:
  - PASS_ENGINEERING_HISTORICAL_DEFER_PROSPECTIVE
  - PASS_STAGE03V1_RESEARCH_ONLY
  - DEFER_PROSPECTIVE_HOLDOUT_INSUFFICIENT
  - FAIL_BOUNDARY_OR_LEAKAGE
  - FAIL_INPUT_ARTIFACTS
  - FAIL_VALIDATION_EVIDENCE
  - BLOCKED_INPUTS_NOT_READY
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

Create `scripts/stage03v_final_gate.sh`.

It must:

- Prefer `STAGE03V_V7_DB`.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall.
- Run WP7-specific tests.
- Run the WP7 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_FINAL_GATE=<status> verdict=<verdict> db=<path> holdout_evaluated=<n> decision_support_gate=<status> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_final_gate.py
tests/test_stage03v_final_gate_boundaries.py
```

Minimum synthetic coverage:

- Missing V7 DB returns `blocked_missing_v7_db` and no old DB fallback when inputs are present.
- Missing/failed WP6 report blocks WP7.
- Any upstream leakage/boundary violation forces fail/block verdict.
- WP7 refuses to claim decision-support promotion when prospective holdout is insufficient or unconsumed.
- WP7 final gate may produce historical/research pass with prospective defer.
- `wp7_final_gate_input_manifest` must have `status=prepared_for_wp7` and `wp7_final_gate_executed=no` before WP7.
- WP7 output manifest must mark `final_gate_executed=yes` and must not mark Stage03V2/3 implemented.
- No trading or decision output fields are produced.
- No full score matrices are written.
- No external fetch occurs.
- Policy allowed verdicts are enforced.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_final_gate.py tests/test_stage03v_final_gate_boundaries.py
python -m src.evaluation.stage03v_final_gate \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --scope-freeze reports/stage03v/stage03v_wp0_scope_freeze_report.json \
  --sample-feasibility reports/stage03v/sample_feasibility_report.json \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --risk-validation reports/stage03v/risk_validation_report.json \
  --downshift-research reports/stage03v/downshift_research_report.json \
  --wp7-input-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --ledger-template reports/stage04/prospective_validation_ledger.stage03v.template.jsonl \
  --policy configs/stage03v_final_gate_policy_v1.yaml \
  --output reports/stage03v/stage03v1_final_gate_report.md \
  --summary-json reports/stage03v/stage03v1_final_gate_report.json \
  --verdict-json reports/stage03v/stage03v1_final_gate_verdict.json \
  --evidence-matrix reports/stage03v/stage03v1_final_gate_evidence_matrix.csv \
  --artifact-manifest reports/stage03v/stage03v1_final_gate_artifact_manifest.json \
  --holdout-status reports/stage03v/stage03v1_prospective_holdout_status.json \
  --post-gate-action-plan reports/stage03v/stage03v1_post_gate_action_plan.md \
  --audit-sample reports/stage03v/stage03v1_final_gate_audit_sample.csv \
  --no-fetch
bash scripts/stage03v_final_gate.sh
python -m json.tool reports/stage03v/stage03v1_final_gate_report.json
python -m json.tool reports/stage03v/stage03v1_final_gate_verdict.json
python -m json.tool reports/stage03v/stage03v1_final_gate_artifact_manifest.json
python -m json.tool reports/stage03v/stage03v1_prospective_holdout_status.json
python -m json.tool configs/stage03v_final_gate_policy_v1.yaml
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

WP7 passes if:

- WP0-WP6 inputs are all pass and consistent.
- V7 and SW2021 L2 verification is enforced.
- Missing V7 blocks and does not fall back.
- Locked dates are preserved: information cutoff 2026-06-10 and holdout start 2026-06-11.
- All upstream leakage and boundary violation totals are zero.
- Final gate report, verdict JSON, evidence matrix, artifact manifest, holdout status, post-gate action plan, and audit sample are emitted.
- WP7 final verdict is one of the allowed policy verdicts.
- If prospective holdout is insufficient/unconsumed, decision-support promotion is explicitly `DEFER` or not approved.
- No holdout performance is consumed by default.
- No new model training, recalibration, readiness reassignment, full score matrix, persistent DB write, or trading/decision output occurs.
- Stage03V2/3 remain placeholders only.
- CI and gate pass.

## Return format

```text
index_id: STAGE03V-WP7-v1
branch: stage03v/wp7-stage03v1-final-gate
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
WP0 scope freeze status: pass/other
WP0.5 sample feasibility status: pass/other
WP1 target support status: pass/other
WP2 controls status: pass/other
WP2.1 full target audit status: pass/other
WP3 baseline diagnostics status: pass/other
WP3.5 vol-scaled sanity status: pass/other
WP4 logistic hazard status: pass/other
WP5 calibration readiness status: pass/other
WP6 risk validation status: pass/other

final gate verdict: ...
stage03v1 gate status: ...
engineering gate status: ...
causality gate status: ...
historical validation gate status: ...
calibration readiness gate status: ...
risk validation gate status: ...
prospective holdout readiness gate status: ...
decision support promotion gate status: ...
prospective holdout rows available: ...
prospective holdout rows evaluated: ...
prospective holdout consumption count: ...
usable probability candidate count: ...
validation pass candidate count: ...
research downshift candidate count: ...
leakage violation count total: ...
boundary violation count total: ...

external data fetch: no
target dataset modified: no
fixed threshold mainline modified: no
persistent DB table written: no
full target matrix committed: no
full feature matrix committed: no
full raw score matrix committed: no
full calibrated score matrix committed: no
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
