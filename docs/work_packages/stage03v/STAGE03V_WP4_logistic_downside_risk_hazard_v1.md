# STAGE03V_WP4_logistic_downside_risk_hazard_v1

Stage: 03V / Volatility and downside-risk hazard

Work package: WP4

Index id: `STAGE03V-WP4-v1`

Suggested branch: `stage03v/wp4-logistic-downside-risk-hazard-v1`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP4_logistic_downside_risk_hazard_v1.md`

Date: 2026-06-11

## Objective

Implement a causal logistic downside-risk hazard model for the accepted Stage03V1 fixed-threshold downside-event targets.

WP4 is the first learned-model package in Stage03V. It must train and evaluate deterministic logistic hazard models on historical-development folds using the accepted WP2 purge/embargo fold plan. It must compare results to WP3 baseline diagnostics and track WP3.5 volatility-scaled candidates as reference metadata only.

WP4 must not calibrate probabilities, assign readiness, consume prospective holdout performance, or implement Stage03V2 / Stage03V3.

The fixed-threshold Stage03V1 target remains the primary target family. Volatility-scaled candidates from WP3.5 are tracked only; they must not replace the fixed-threshold mainline.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md
docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md
docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md
docs/work_packages/stage03v/STAGE03V_WP3_volatility_range_empirical_baselines.md
docs/work_packages/stage03v/STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate.md
configs/risk_event_signal_contract_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
configs/stage03v_baseline_diagnostics_policy_v1.yaml
configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/purge_embargo_fold_plan.json
```

## Required preconditions

WP4 may proceed only if all are true:

```text
WP1 target support: pass
WP2 target controls: pass
WP2.1 full-target audit: pass
WP3 baseline diagnostics: pass
WP3.5 volatility-scaled threshold sanity: pass
V7 coverage: yes
SW2021 L2 universe: pass
source DB: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
full target rows checked: 7474840
target row count delta: 0
target violation total: 0
baseline leakage violation total: 0
WP3.5 leakage violation total: 0
prospective holdout rows evaluated: 0
```

If any precondition fails, emit `blocked_wp3_5_not_ready` and stop.

## Stage boundary

Allowed:

- Read V7 DuckDB read-only.
- Rebuild or stream accepted fixed-threshold Stage03V1 target rows.
- Use the accepted WP2 purge/embargo fold plan.
- Use causal features derived from data available at or before `feature_asof_date`.
- Train deterministic logistic hazard models on training folds only.
- Evaluate on validation folds only.
- Compare logistic hazard metrics with WP3 baseline metrics.
- Track WP3.5 volatility-scaled candidates as reference metadata only.
- Emit aggregate reports, fold metrics, slice metrics, coefficient summaries, model manifest, feature audit, and small capped audit samples.

Forbidden:

- Do not fetch external data.
- Do not score, inspect, or evaluate prospective final holdout rows.
- Do not calibrate probabilities: no isotonic, Platt scaling, beta calibration, recalibration, or reliability promotion.
- Do not assign readiness: no `usable_probability`, `ordinal_only`, `baseline_only`, or readiness matrix output.
- Do not implement Stage03V2 upside-trigger targets.
- Do not implement Stage03V3 competing-risk targets.
- Do not mutate fixed-threshold target rows, target labels, support reports, or target universe manifests.
- Do not replace fixed-threshold Stage03V1 mainline with volatility-scaled labels.
- Do not commit full target, feature, or score matrices.
- Do not write persistent DuckDB tables by default.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, recommendation, or decision outputs.

## Required deliverables

Create:

```text
src/evaluation/stage03v_logistic_hazard.py
scripts/stage03v_logistic_hazard_gate.sh
tests/test_stage03v_logistic_hazard.py
tests/test_stage03v_logistic_hazard_causality.py
configs/stage03v_logistic_hazard_policy_v1.yaml
reports/stage03v/logistic_hazard_report.md
reports/stage03v/logistic_hazard_report.json
reports/stage03v/logistic_hazard_fold_metrics.csv
reports/stage03v/logistic_hazard_slice_metrics.csv
reports/stage03v/logistic_hazard_coefficients.csv
reports/stage03v/logistic_hazard_model_manifest.json
reports/stage03v/logistic_hazard_feature_audit.csv
reports/stage03v/logistic_hazard_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Do not commit serialized model binaries. Commit coefficients and model metadata only as CSV / JSON.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_logistic_hazard \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_logistic_hazard_policy_v1.yaml \
  --output reports/stage03v/logistic_hazard_report.md \
  --summary-json reports/stage03v/logistic_hazard_report.json \
  --fold-metrics reports/stage03v/logistic_hazard_fold_metrics.csv \
  --slice-metrics reports/stage03v/logistic_hazard_slice_metrics.csv \
  --coefficients reports/stage03v/logistic_hazard_coefficients.csv \
  --model-manifest reports/stage03v/logistic_hazard_model_manifest.json \
  --feature-audit reports/stage03v/logistic_hazard_feature_audit.csv \
  --audit-sample reports/stage03v/logistic_hazard_audit_sample.csv \
  --asof-modes close_t_minus_1,close_t \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise default to `data/db/a_share_hmm_tushare_v7.duckdb`.
- If the V7 DB is missing or invalid, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Do not silently fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB.

## Model design

Implement deterministic logistic regression.

Preferred model:

```text
sklearn.linear_model.LogisticRegression
solver: lbfgs or liblinear
max_iter: explicit and sufficient
random_state: fixed where applicable
class_weight: configurable; default may be balanced for imbalanced slices
```

If scikit-learn is not available, either implement a deterministic fallback or emit `blocked_missing_sklearn` with clear report fields. Do not add heavy dependencies without checking existing project dependency conventions.

Model target:

```text
event_label for fixed-threshold Stage03V1 downside_event targets
censoring_status must be labeled
split_role must be historical_development
target_usage tracked separately as eligible vs diagnostic_only
diagnostic_only slices may be evaluated but must not be promoted
```

Model unit:

```text
Train per slice when sufficient data exists.
Slice key = horizon + threshold_type + threshold_value + target_usage.
If a slice has insufficient positive or negative training events, emit insufficient_data for that slice/fold and skip fitting.
Do not silently pool diagnostic_only and eligible slices.
Optional pooled model is allowed only as an extra diagnostic if per-slice reporting remains primary.
```

As-of modes:

```text
close_t_minus_1 is the conservative primary mode.
close_t may be reported as after-close diagnostic only.
Metrics must be reported separately by asof_mode.
WP4 pass/fail should be based on close_t_minus_1 fixed-threshold tracking, not close_t alone.
```

## Feature rules

Allowed feature families:

```text
realized_volatility
range_based_volatility
recent_drawdown
empirical_event_rate from training history only
cross_sectional_market_state from training/past history only
explicit slice metadata controls if encoded without target leakage
```

Forbidden feature inputs:

```text
event_label
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
target_observation_start_date
target_observation_end_date
censoring_status as a predictive feature
exclusion_reason
holdout_label_status
any column prefixed future_
any column prefixed target_
same-row validation labels
any prospective holdout labels
```

Feature causality:

```text
feature_asof_date <= trade_date for close_t mode.
feature_asof_date < trade_date for close_t_minus_1 mode.
Rolling statistics must use only prices available at feature_asof_date.
Empirical event-rate features must use only training rows with target_observation_end_date < validation_start_date.
Feature imputation must fit on training rows only.
Feature scaling / standardization must fit on training rows only.
Validation rows must never influence scaler, imputer, feature selector, class weights, or model coefficients.
```

Add tests for train-only scaler / imputer behavior.

## Metrics

For each asof_mode / fold / slice / model variant, report:

```text
row_count
train_row_count
validation_row_count
scored_row_count
positive_event_count
event_base_rate
score_available_rate
roc_auc
average_precision
brier_score_uncalibrated
log_loss_uncalibrated
spearman_score_vs_event
spearman_score_vs_future_mae
spearman_score_vs_future_mdd
quantile_lift_top_decile
quantile_lift_top_quintile
coefficient_l1_norm
coefficient_l2_norm
convergence_status
insufficient_data_reason
```

Compare against WP3 baselines:

```text
best_wp3_baseline_auc
best_wp3_baseline_average_precision
logistic_delta_auc_vs_best_baseline
logistic_delta_ap_vs_best_baseline
logistic_beats_best_baseline_flag
```

Outperformance is not a hard pass requirement in WP4. WP4 may pass with weak metrics if implementation and leakage gates are sound.

## Volatility-scaled candidate tracking

Read:

```text
reports/stage03v/vol_scaled_threshold_sanity_report.json
```

Required report fields:

```text
vol_scaled_candidate_tracking_status
wp3_5_wp4_entry_recommendation
vol_scaled_candidate_count
best_vol_scaled_candidate_by_event_support
fixed_threshold_mainline_status
```

Set:

```text
fixed_threshold_mainline_status: unchanged_primary_target
vol_scaled_candidate_tracking_status: tracked_reference_only
```

Do not train the primary WP4 model on volatility-scaled labels unless a later reviewed package explicitly activates that target family.

## Required report JSON fields

Create `reports/stage03v/logistic_hazard_report.json` with at least:

```text
index_id
report_version
status
wp1_support_status
wp2_controls_status
wp2_1_full_target_audit_status
wp3_baseline_diagnostics_status
wp3_5_vol_scaled_sanity_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
fold_plan_status
policy_status
model_family
model_variant_count
asof_modes_evaluated
primary_asof_mode
slice_count_evaluated
fold_count_evaluated
train_row_count_total
validation_row_count_evaluated
prospective_holdout_rows_evaluated
insufficient_data_slice_count
fitted_model_count
feature_count
feature_families
feature_audit_path
fold_metrics_path
slice_metrics_path
coefficients_path
model_manifest_path
audit_sample_path
metric_summary
best_logistic_model_by_auc
best_logistic_model_by_average_precision
baseline_comparison_summary
vol_scaled_candidate_tracking_status
wp3_5_wp4_entry_recommendation
fixed_threshold_mainline_status
leakage_violation_counts
training_boundary_violation_counts
ci_gate_status
boundary_flags
```

Boundary flags must include:

```text
external_data_fetch: no
target_dataset_modified: no
fixed_threshold_mainline_modified: no
persistent_db_table_written: no
full_target_matrix_committed: no
full_feature_matrix_committed: no
full_score_matrix_committed: no
model_training: yes
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Policy config

Create `configs/stage03v_logistic_hazard_policy_v1.yaml`.

Minimum fields:

```text
index_id: STAGE03V-WP4-v1
policy_version: stage03v_logistic_hazard_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
source_target_controls: reports/stage03v/target_controls_report.json
source_full_target_audit: reports/stage03v/full_target_streaming_audit_report.json
source_baseline_diagnostics: reports/stage03v/baseline_diagnostics_report.json
source_vol_scaled_sanity: reports/stage03v/vol_scaled_threshold_sanity_report.json
fold_plan: reports/stage03v/purge_embargo_fold_plan.json
primary_target_family: fixed_threshold_stage03v1_downside_event
vol_scaled_candidate_policy: tracked_reference_only
primary_asof_mode: close_t_minus_1
diagnostic_asof_modes:
  - close_t
  - close_t_minus_1
model_family: logistic_regression
calibration_policy: forbidden_in_wp4
readiness_policy: forbidden_in_wp4
final_holdout_policy: withheld_not_scored
feature_asof_policy:
  close_t: feature_asof_date <= trade_date
  close_t_minus_1: feature_asof_date < trade_date
training_policy: train_folds_only
validation_policy: validation_folds_only
purge_embargo_policy: accepted_wp2_fold_plan
full_feature_matrix_policy: forbidden_to_commit
persistent_db_table_policy: forbidden_by_default
external_fetch_policy: forbidden
```

JSON-formatted YAML is acceptable if consistent with current repo practice.

## Gate script

Create `scripts/stage03v_logistic_hazard_gate.sh`.

It must:

- Prefer `STAGE03V_V7_DB`.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall.
- Run WP4-specific tests.
- Run the WP4 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_LOGISTIC_HAZARD_GATE=<status> db=<path> fitted_models=<n> validation_rows=<n> primary_asof=<mode> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_logistic_hazard.py
tests/test_stage03v_logistic_hazard_causality.py
```

Minimum synthetic coverage:

- Missing V7 DB returns `blocked_missing_v7_db` and no old DB fallback.
- Missing/failed WP3.5 report blocks WP4.
- Training uses train folds only.
- Validation labels do not affect fitted coefficients.
- Same-row `event_label` does not affect feature values.
- `future_*` columns are rejected as model features.
- Target namespace columns are rejected as model features.
- `feature_asof_date` violations are detected.
- `close_t_minus_1` mode requires `feature_asof_date < trade_date`.
- `close_t` mode allows `feature_asof_date <= trade_date`.
- Scaler/imputer fit on training rows only.
- Changing validation feature distribution does not change train scaler/imputer parameters.
- Purged/embargoed rows are not used for training.
- Prospective holdout rows are withheld and not scored/evaluated.
- Insufficient positive/negative class slices are skipped with explicit reason.
- No calibration output is produced.
- No readiness output is produced.
- No external fetch occurs.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_logistic_hazard.py tests/test_stage03v_logistic_hazard_causality.py
python -m src.evaluation.stage03v_logistic_hazard \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_logistic_hazard_policy_v1.yaml \
  --output reports/stage03v/logistic_hazard_report.md \
  --summary-json reports/stage03v/logistic_hazard_report.json \
  --fold-metrics reports/stage03v/logistic_hazard_fold_metrics.csv \
  --slice-metrics reports/stage03v/logistic_hazard_slice_metrics.csv \
  --coefficients reports/stage03v/logistic_hazard_coefficients.csv \
  --model-manifest reports/stage03v/logistic_hazard_model_manifest.json \
  --feature-audit reports/stage03v/logistic_hazard_feature_audit.csv \
  --audit-sample reports/stage03v/logistic_hazard_audit_sample.csv \
  --asof-modes close_t_minus_1,close_t \
  --no-fetch
bash scripts/stage03v_logistic_hazard_gate.sh
python -m json.tool reports/stage03v/logistic_hazard_report.json
python -m json.tool reports/stage03v/logistic_hazard_model_manifest.json
python -m json.tool configs/stage03v_logistic_hazard_policy_v1.yaml
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
git diff --cached --check
```

Also run a missing-V7 negative check to temporary outputs:

```bash
python -m src.evaluation.stage03v_logistic_hazard \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp4_missing_v7.md \
  --summary-json tmp/stage03v_wp4_missing_v7.json \
  --fold-metrics tmp/stage03v_wp4_missing_v7_fold_metrics.csv \
  --slice-metrics tmp/stage03v_wp4_missing_v7_slice_metrics.csv \
  --coefficients tmp/stage03v_wp4_missing_v7_coefficients.csv \
  --model-manifest tmp/stage03v_wp4_missing_v7_model_manifest.json \
  --feature-audit tmp/stage03v_wp4_missing_v7_feature_audit.csv \
  --audit-sample tmp/stage03v_wp4_missing_v7_audit_sample.csv \
  --asof-modes close_t_minus_1,close_t \
  --no-fetch
```

Expected:

```text
status: blocked_missing_v7_db
old_db_fallback: false
external_data_fetch: no
formal reports are not overwritten unless explicitly passed
negative-check outputs remain under tmp/
```

## Acceptance criteria

WP4 passes if:

- WP1/WP2/WP2.1/WP3/WP3.5 inputs are all pass.
- V7 and SW2021 L2 verification is enforced.
- Missing V7 blocks and does not fall back.
- Logistic models fit only on training folds.
- Validation rows are used only for evaluation.
- Prospective holdout rows are not scored/evaluated.
- Feature namespace has zero target/future leakage violations.
- Feature-asof violations are zero.
- Training boundary violations are zero.
- No calibration is performed.
- No readiness is assigned.
- Fixed-threshold mainline remains unchanged.
- Vol-scaled candidates are tracked as reference only.
- Metrics are emitted per fold/slice/asof_mode.
- Coefficient summary and model manifest are emitted.
- No full feature/score matrices are committed.
- No persistent DB writes occur by default.
- No HMM/HSMM training code is modified.
- No Stage03V2/3 implementation occurs.
- CI and gate pass.

## Return format

```text
index_id: STAGE03V-WP4-v1
branch: stage03v/wp4-logistic-downside-risk-hazard-v1
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

model family: logistic_regression
primary target family: fixed_threshold_stage03v1_downside_event
primary asof mode: close_t_minus_1
asof modes evaluated: ...
slice count evaluated: ...
fold count evaluated: ...
train rows total: ...
validation rows evaluated: ...
prospective holdout rows evaluated: ...
fitted model count: ...
insufficient data slice count: ...
feature count: ...
feature families: ...
leakage violation count total: ...
feature_asof violations: ...
target namespace input violations: ...
future column input violations: ...
same-row label leakage count: ...
validation label leakage count: ...
training boundary violation count: ...
calibration output count: 0
readiness output count: 0

best logistic model by AUC: ...
best logistic model by AP: ...
baseline comparison summary: ...
vol_scaled_candidate_tracking_status: tracked_reference_only
wp3_5_wp4_entry_recommendation: ...
fixed_threshold_mainline_status: unchanged_primary_target

external data fetch: no
target dataset modified: no
fixed threshold mainline modified: no
persistent DB table written: no
full target matrix committed: no
full feature matrix committed: no
full score matrix committed: no
model training: yes
probability calibration: no
readiness assigned: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
