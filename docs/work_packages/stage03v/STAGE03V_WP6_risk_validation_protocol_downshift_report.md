# STAGE03V_WP6_risk_validation_protocol_downshift_report

Stage: 03V / Volatility and downside-risk hazard

Work package: WP6

Index id: `STAGE03V-WP6-v1`

Suggested branch: `stage03v/wp6-risk-validation-downshift-report`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP6_risk_validation_protocol_downshift_report.md`

Date: 2026-06-11

## Objective

Implement Stage03V1 risk validation protocol and downshift research report on top of the accepted WP5 calibration/readiness artifacts.

WP6 must turn WP5 development-readiness outputs into a historical-development validation evidence pack. It should evaluate how calibrated downside-risk candidates behave as research-only risk-warning / downshift candidates across folds, slices, entities, and dates.

WP6 must not create trading, sizing, buy/sell, recommendation, or UI decision outputs. It must not consume prospective final holdout performance. WP6 prepares the evidence and protocol needed before WP7 final gate.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md
docs/work_packages/stage03v/STAGE03V_WP5_calibration_clustered_inference_readiness.md
configs/risk_event_signal_contract_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
configs/stage03v_logistic_hazard_policy_v1.yaml
configs/stage03v_calibration_readiness_policy_v1.yaml
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/logistic_hazard_report.json
reports/stage03v/calibration_readiness_report.json
reports/stage03v/calibration_fold_metrics.csv
reports/stage03v/calibration_slice_metrics.csv
reports/stage03v/calibration_curve_bins.csv
reports/stage03v/clustered_inference_summary.csv
reports/stage03v/downside_readiness_matrix.csv
reports/stage03v/calibration_model_manifest.json
reports/stage03v/purge_embargo_fold_plan.json
```

## Required preconditions

WP6 may proceed only if all are true:

```text
WP1 target support: pass
WP2 target controls: pass
WP2.1 full-target audit: pass
WP3 baseline diagnostics: pass
WP3.5 volatility-scaled sanity: pass
WP4 logistic hazard: pass
WP5 calibration readiness: pass
V7 coverage: yes
SW2021 L2 universe: pass
source DB: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
WP5 leakage violation total: 0
WP5 calibration boundary violation total: 0
WP5 prospective holdout rows evaluated: 0
WP5 probability_calibration: yes
WP5 readiness_assigned: yes_development_only
WP5 trading_or_decision_output: no
WP5 fixed_threshold_mainline_status: unchanged_primary_target
```

If any precondition fails, emit `blocked_wp5_not_ready` and stop.

## Stage boundary

Allowed:

- Read V7 DuckDB read-only.
- Read accepted WP1/WP2/WP2.1/WP3/WP3.5/WP4/WP5 artifacts.
- Recompute historical-development target rows and calibrated-score evidence if needed.
- Evaluate development-only risk-warning / downshift candidates on historical-development folds.
- Produce validation protocol artifacts for later WP7 final gate.
- Produce a downshift research report with non-actionable evidence.
- Emit aggregate metrics, candidate matrix, validation protocol, clustered summaries, and capped audit samples.

Forbidden:

- Do not fetch external data.
- Do not consume, score, inspect, or evaluate prospective final holdout performance.
- Do not create trading, buy/sell, sizing, recommendation, portfolio action, execution, or UI decision outputs.
- Do not call any output `signal` unless it is explicitly marked `research_only` and `not_trading_output`.
- Do not mutate fixed-threshold target rows, target labels, support reports, or target universe manifests.
- Do not replace fixed-threshold Stage03V1 target family with volatility-scaled labels.
- Do not train new model families.
- Do not recalibrate probabilities beyond reading WP5 calibration artifacts.
- Do not assign new readiness categories beyond protocol-level validation status.
- Do not write persistent DuckDB tables by default.
- Do not commit full target, feature, raw-score, calibrated-score, or event matrices.
- Do not modify HMM or HSMM training algorithms.
- Do not implement Stage03V2 or Stage03V3.

## Risk validation protocol

Define a protocol that evaluates each WP5 readiness candidate by:

```text
asof_mode
horizon
threshold_type
threshold_value
target_usage
calibration_method
readiness_category
```

Required validation dimensions:

```text
coverage and support
calibration stability
fold stability
clustered uncertainty
lead-time and event capture
false alarm concentration
drawdown/event lift by score quantile
threshold sensitivity
entity concentration
calendar-date concentration
baseline comparison
known WP3/WP3.5 anomaly handling
```

Validation status categories:

```text
validation_pass_candidate
validation_watchlist
research_only_evidence
insufficient_validation_support
blocked_by_boundary_or_leakage
```

These are validation statuses only. They must not be interpreted as trading decisions.

## Downshift research report

The report may define research-only downshift candidate tiers such as:

```text
research_downshift_watch
research_downshift_candidate
research_downshift_insufficient
research_downshift_blocked
```

Every such tier must include:

```text
research_only: yes
not_trading_output: yes
no_position_sizing: yes
no_buy_sell_recommendation: yes
no_execution_instruction: yes
```

The report must avoid language that implies actionable portfolio decisions. It may discuss evidence quality and validation strength only.

## Required deliverables

Create:

```text
src/evaluation/stage03v_risk_validation.py
scripts/stage03v_risk_validation_gate.sh
tests/test_stage03v_risk_validation.py
tests/test_stage03v_risk_validation_boundaries.py
configs/stage03v_risk_validation_protocol_policy_v1.yaml
reports/stage03v/risk_validation_protocol.md
reports/stage03v/risk_validation_report.md
reports/stage03v/risk_validation_report.json
reports/stage03v/risk_validation_metrics.csv
reports/stage03v/downshift_research_report.md
reports/stage03v/downshift_research_report.json
reports/stage03v/downshift_candidate_matrix.csv
reports/stage03v/risk_validation_clustered_summary.csv
reports/stage03v/risk_validation_audit_sample.csv
reports/stage03v/wp7_final_gate_input_manifest.json
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Do not commit full score/event matrices.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_risk_validation \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --calibration-fold-metrics reports/stage03v/calibration_fold_metrics.csv \
  --calibration-slice-metrics reports/stage03v/calibration_slice_metrics.csv \
  --calibration-bins reports/stage03v/calibration_curve_bins.csv \
  --clustered-inference reports/stage03v/clustered_inference_summary.csv \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_risk_validation_protocol_policy_v1.yaml \
  --protocol-output reports/stage03v/risk_validation_protocol.md \
  --output reports/stage03v/risk_validation_report.md \
  --summary-json reports/stage03v/risk_validation_report.json \
  --metrics reports/stage03v/risk_validation_metrics.csv \
  --downshift-report reports/stage03v/downshift_research_report.md \
  --downshift-json reports/stage03v/downshift_research_report.json \
  --candidate-matrix reports/stage03v/downshift_candidate_matrix.csv \
  --clustered-summary reports/stage03v/risk_validation_clustered_summary.csv \
  --audit-sample reports/stage03v/risk_validation_audit_sample.csv \
  --wp7-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise use `data/db/a_share_hmm_tushare_v7.duckdb`.
- If V7 DB is missing or invalid, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Never fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB.

## Required report JSON fields

Create `reports/stage03v/risk_validation_report.json` with at least:

```text
index_id
report_version
status
wp1_support_status
wp2_controls_status
wp2_1_full_target_audit_status
wp3_baseline_diagnostics_status
wp3_5_vol_scaled_sanity_status
wp4_logistic_hazard_status
wp5_calibration_readiness_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
fold_plan_status
policy_status
validation_protocol_status
historical_development_only
prospective_holdout_rows_evaluated
readiness_rows_evaluated
candidate_rows_evaluated
validation_status_counts
downshift_tier_counts
usable_probability_candidate_count
ordinal_only_candidate_count
baseline_only_candidate_count
research_only_count
validation_pass_candidate_count
validation_watchlist_count
research_only_evidence_count
insufficient_validation_support_count
blocked_by_boundary_or_leakage_count
risk_validation_metrics_path
downshift_candidate_matrix_path
clustered_summary_path
audit_sample_path
wp7_manifest_path
metric_summary
lead_time_summary
event_capture_summary
false_alarm_summary
clustered_concentration_summary
baseline_comparison_summary
leakage_violation_counts
validation_boundary_violation_counts
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
validation_protocol_created: yes
research_report_created: yes
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Policy config

Create `configs/stage03v_risk_validation_protocol_policy_v1.yaml`.

Minimum fields:

```text
index_id: STAGE03V-WP6-v1
policy_version: stage03v_risk_validation_protocol_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
source_calibration_readiness: reports/stage03v/calibration_readiness_report.json
source_readiness_matrix: reports/stage03v/downside_readiness_matrix.csv
fold_plan: reports/stage03v/purge_embargo_fold_plan.json
primary_target_family: fixed_threshold_stage03v1_downside_event
vol_scaled_candidate_policy: tracked_reference_only
historical_development_only: true
final_holdout_policy: withheld_not_scored
validation_scope: development_research_protocol_only
validation_statuses:
  - validation_pass_candidate
  - validation_watchlist
  - research_only_evidence
  - insufficient_validation_support
  - blocked_by_boundary_or_leakage
downshift_research_tiers:
  - research_downshift_watch
  - research_downshift_candidate
  - research_downshift_insufficient
  - research_downshift_blocked
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

Create `scripts/stage03v_risk_validation_gate.sh`.

It must:

- Prefer `STAGE03V_V7_DB`.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall.
- Run WP6-specific tests.
- Run the WP6 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_RISK_VALIDATION_GATE=<status> db=<path> candidates=<n> validation_pass_candidates=<n> holdout_evaluated=<n> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_risk_validation.py
tests/test_stage03v_risk_validation_boundaries.py
```

Minimum synthetic coverage:

- Missing V7 DB returns `blocked_missing_v7_db` and no old DB fallback.
- Missing/failed WP5 report blocks WP6.
- WP6 refuses WP5 artifacts where holdout was consumed.
- WP6 refuses WP5 artifacts with calibration/readiness boundary violations.
- Prospective holdout rows are withheld and not validated.
- Validation protocol statuses are assigned from historical-development evidence only.
- Diagnostic-only rows cannot become validation-pass candidates.
- Downshift tiers are marked research-only and not trading output.
- Forbidden output tokens such as buy/sell/sizing/recommendation/decision do not appear in machine-output column names.
- Full score matrices are not written.
- WP7 input manifest is produced and references only accepted artifacts and WP6 outputs.
- No external fetch occurs.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_risk_validation.py tests/test_stage03v_risk_validation_boundaries.py
python -m src.evaluation.stage03v_risk_validation \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --calibration-readiness reports/stage03v/calibration_readiness_report.json \
  --calibration-fold-metrics reports/stage03v/calibration_fold_metrics.csv \
  --calibration-slice-metrics reports/stage03v/calibration_slice_metrics.csv \
  --calibration-bins reports/stage03v/calibration_curve_bins.csv \
  --clustered-inference reports/stage03v/clustered_inference_summary.csv \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_risk_validation_protocol_policy_v1.yaml \
  --protocol-output reports/stage03v/risk_validation_protocol.md \
  --output reports/stage03v/risk_validation_report.md \
  --summary-json reports/stage03v/risk_validation_report.json \
  --metrics reports/stage03v/risk_validation_metrics.csv \
  --downshift-report reports/stage03v/downshift_research_report.md \
  --downshift-json reports/stage03v/downshift_research_report.json \
  --candidate-matrix reports/stage03v/downshift_candidate_matrix.csv \
  --clustered-summary reports/stage03v/risk_validation_clustered_summary.csv \
  --audit-sample reports/stage03v/risk_validation_audit_sample.csv \
  --wp7-manifest reports/stage03v/wp7_final_gate_input_manifest.json \
  --no-fetch
bash scripts/stage03v_risk_validation_gate.sh
python -m json.tool reports/stage03v/risk_validation_report.json
python -m json.tool reports/stage03v/downshift_research_report.json
python -m json.tool reports/stage03v/wp7_final_gate_input_manifest.json
python -m json.tool configs/stage03v_risk_validation_protocol_policy_v1.yaml
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

WP6 passes if:

- WP1/WP2/WP2.1/WP3/WP3.5/WP4/WP5 inputs are all pass.
- V7 and SW2021 L2 verification is enforced.
- Missing V7 blocks and does not fall back.
- WP6 remains historical-development only.
- Prospective final holdout rows are not scored, validated, or evaluated.
- Risk validation protocol is emitted.
- Downshift research report is emitted and clearly marked research-only / not trading output.
- Candidate matrix, metrics, clustered summary, audit sample, and WP7 manifest are emitted.
- No full target/feature/raw-score/calibrated-score matrices are committed.
- No recalibration or new model training occurs.
- No readiness reassignment occurs beyond validation protocol status.
- Fixed-threshold mainline remains unchanged.
- Volatility-scaled candidates remain reference-only.
- No Stage03V2/3 implementation occurs.
- CI and gate pass.

## Return format

```text
index_id: STAGE03V-WP6-v1
branch: stage03v/wp6-risk-validation-downshift-report
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
WP1 support status: pass/other
WP2 controls status: pass/other
WP2.1 full target audit status: pass/other
WP3 baseline diagnostics status: pass/other
WP3.5 vol-scaled sanity status: pass/other
WP4 logistic hazard status: pass/other
WP5 calibration readiness status: pass/other

historical development only: yes/no
prospective holdout rows evaluated: ...
readiness rows evaluated: ...
candidate rows evaluated: ...
validation status counts: ...
downshift tier counts: ...
validation pass candidate count: ...
validation watchlist count: ...
research only evidence count: ...
insufficient validation support count: ...
blocked by boundary/leakage count: ...
lead time summary: ...
event capture summary: ...
false alarm summary: ...
clustered concentration summary: ...
baseline comparison summary: ...
leakage violation count total: ...
validation boundary violation count total: ...

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
validation protocol created: yes
research report created: yes
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
