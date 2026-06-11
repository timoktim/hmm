# CODEX_STAGE03V_WP3.5_volatility_scaled_threshold_sanity

Repository: `timoktim/hmm`

Index id: `STAGE03V-WP3.5-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate.md`

Suggested branch: `stage03v/wp3.5-volatility-scaled-threshold-sanity`

## Instruction

Start from updated `main` after PR80 / `STAGE03V-WP3-v1` has been merged. Confirm that WP1, WP2, WP2.1, and WP3 reports are present and have `status=pass`. Create or use the suggested branch and execute only `STAGE03V-WP3.5-v1`.

This package is a supplement and sanity gate between WP3 baseline diagnostics and WP4 logistic downside-risk hazard training. Do not open WP4 model training. Do not calibrate probabilities. Do not assign readiness. Do not consume prospective final holdout performance. Do not implement Stage03V2 or Stage03V3.

## Read first

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
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/purge_embargo_fold_plan.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/baseline_diagnostics_fold_metrics.csv
reports/stage03v/baseline_diagnostics_slice_metrics.csv
```

## Required precondition

Proceed only if:

```text
reports/stage03v/risk_event_target_support.json status: pass
reports/stage03v/target_controls_report.json status: pass
reports/stage03v/full_target_streaming_audit_report.json status: pass
reports/stage03v/baseline_diagnostics_report.json status: pass
WP3 leakage_violation_count_total: 0
WP3 prospective_holdout_rows_evaluated: 0
WP3 boundary flags: no external fetch, no model training, no calibration, no readiness, no holdout consumed
source_db_path: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
v7_coverage_available: yes
sw2021_l2_universe_coverage: pass
entity_count_after_silent_break_handling: 124
feature_namespace_policy_status: pass
purge_violation_count: 0
embargo_violation_count: 0
```

If not, emit the most specific blocked status and stop:

```text
blocked_wp1_not_ready
blocked_wp2_not_ready
blocked_wp2_1_not_ready
blocked_wp3_not_ready
blocked_missing_v7_db
blocked_invalid_v7_db
blocked_missing_fold_plan
blocked_invalid_fold_plan
```

Never silently fall back to `data/db/a_share_hmm.duckdb`.

## Required files

Create:

```text
src/evaluation/stage03v_vol_scaled_threshold_sanity.py
scripts/stage03v_vol_scaled_threshold_sanity_gate.sh
tests/test_stage03v_vol_scaled_threshold_sanity.py
tests/test_stage03v_baseline_metric_sanity.py
configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml
reports/stage03v/vol_scaled_threshold_sanity_report.md
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/vol_scaled_threshold_slice_summary.csv
reports/stage03v/baseline_metric_sanity_audit.csv
reports/stage03v/asof_shift_metric_sanity.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

CSV artifacts must be aggregate or capped samples only. Do not commit a full volatility-scaled target matrix, full feature matrix, full baseline score matrix, or per-row volatility-scaled score matrix.

## CLI

Implement:

```bash
python -m src.evaluation.stage03v_vol_scaled_threshold_sanity \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --baseline-report reports/stage03v/baseline_diagnostics_report.json \
  --baseline-fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --baseline-slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --baseline-policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --policy configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml \
  --output reports/stage03v/vol_scaled_threshold_sanity_report.md \
  --summary-json reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --vol-scaled-summary reports/stage03v/vol_scaled_threshold_slice_summary.csv \
  --metric-audit reports/stage03v/baseline_metric_sanity_audit.csv \
  --asof-shift-summary reports/stage03v/asof_shift_metric_sanity.csv \
  --no-fetch
```

DB behavior:

```text
Prefer STAGE03V_V7_DB when set.
Otherwise default to data/db/a_share_hmm_tushare_v7.duckdb.
If V7 DB is missing or invalid, emit blocked_missing_v7_db / blocked_invalid_v7_db.
Never fall back to data/db/a_share_hmm.duckdb.
CI unit tests must not require private DuckDB.
```

## Volatility-scaled threshold supplement

Evaluate volatility-scaled thresholds as supplement-only diagnostics. Do not replace the WP1 fixed-threshold mainline.

Minimum candidate set:

```text
volatility_estimators:
  rolling_close_to_close_vol_20
  rolling_close_to_close_vol_60
  ewma_close_to_close_vol_20_or_equivalent
horizons:
  1
  5
  10
  20
k_candidates:
  1.0
  1.5
  2.0
  2.5
clamp_min_abs_threshold:
  0.02
clamp_max_abs_threshold:
  0.15
```

Expected threshold convention:

```text
daily_vol = causal daily close-to-close volatility, not annualized
horizon_scaled_vol = daily_vol * sqrt(horizon)
threshold_abs = clamp(k * horizon_scaled_vol, clamp_min_abs_threshold, clamp_max_abs_threshold)
event_label_vol_scaled = future_max_drawdown_abs >= threshold_abs
```

If annualized volatility is used internally, convert it back to horizon-scale units before threshold comparison and document the conversion.

Causality requirements:

```text
Volatility features use returns ending at or before trade_date for asof_mode=close_t.
asof_mode=close_t_minus_1 shifts price-derived features so the latest observation ends strictly before trade_date.
No future_* column may enter volatility estimator construction.
No same-row event label may enter threshold or score construction.
Prospective final holdout rows must not be scored or evaluated.
Fold metrics use validation rows only.
Empirical history, if any, uses training rows only and respects purge/embargo.
```

Required comparison against fixed-threshold mainline:

```text
fixed_threshold_event_count
vol_scaled_event_count
fixed_threshold_event_base_rate
vol_scaled_event_base_rate
positive_count_by_entity_distribution
positive_count_by_fold_distribution
positive_count_by_slice_distribution
positive_count_by_date_concentration
market_event_block_count
effective_event_evidence_count
threshold_abs_mean
threshold_abs_median
threshold_abs_p10
threshold_abs_p90
clamp_min_hit_rate
clamp_max_hit_rate
```

## WP3 baseline metric sanity audit

Audit WP3 metrics before WP4 opens. At minimum, identify and audit:

```text
roc_auc >= 0.90
average_precision >= 0.25
abs(spearman_score_vs_future_mdd) >= 0.30
score_available_rate < 0.50
positive_event_count below policy minimum
event_base_rate below policy minimum or above policy maximum
any best_baseline_* record in reports/stage03v/baseline_diagnostics_report.json
```

For each flagged metric row or aggregate group, report:

```text
baseline_name
baseline_family
fold_id
slice_id or target_usage
horizon
threshold_value
metric_name
metric_value
row_count
scored_row_count
positive_event_count
event_base_rate
score_available_rate
diagnostic_only_flag
eligible_flag
largest_single_entity_share
largest_single_trade_date_share
largest_single_fold_share
entity_hhi
date_hhi
feature_asof_min
feature_asof_max
feature_asof_violation_count
same_row_label_leakage_count
future_column_input_violation_count
target_namespace_input_violation_count
artifact_flag
artifact_reason
```

The known WP3 high-AUC diagnostic-only metric must be explicitly covered:

```text
baseline_name: rolling_close_to_close_vol_60
baseline_family: realized_volatility
metric: roc_auc
value: approximately 0.9939857845817387
horizon: 1
threshold_value: 0.05
target_usage: diagnostic_only
```

Classify it as one of:

```text
explained_by_sample_or_slice_structure
explained_by_asof_semantics
explained_by_threshold_or_event_imbalance
unexplained_warning
no_artifact_detected
```

## Close-t versus t-minus-one as-of sanity

WP3 allowed price-derived baselines with `feature_asof_date = trade_date`, corresponding to a close-after-market diagnostic for future `t+1..t+N` risk.

WP3.5 must add a diagnostic-only comparison for price-derived baselines and volatility-scaled thresholds:

```text
asof_mode: close_t
asof_mode: close_t_minus_1
```

Required outputs:

```text
metric_close_t
metric_close_t_minus_1
metric_delta
row_count_close_t
row_count_close_t_minus_1
positive_event_count_close_t
positive_event_count_close_t_minus_1
score_available_rate_close_t
score_available_rate_close_t_minus_1
material_degradation_flag
asof_dependency_flag
```

If a t-minus-one comparison is not feasible for a specific baseline, emit `asof_shift_deferred` with a specific reason. A blanket omission is not acceptable.

## Routing fields

Do not assign readiness or calibrated probability status. Emit only package-sequencing routing fields:

```text
volatility_scaled_threshold_status:
  candidate_for_wp4_research_tracking
  diagnostic_only
  reject
  defer

baseline_sanity_status:
  pass
  warning
  fail

wp4_entry_recommendation:
  proceed_fixed_threshold_only
  proceed_with_vol_scaled_candidate_tracking
  defer_wp4_pending_metric_sanity
  blocked
```

## Report contents

Create `reports/stage03v/vol_scaled_threshold_sanity_report.json` with at least:

```text
index_id
report_version
status
wp1_support_status
wp2_controls_status
wp2_1_full_target_audit_status
wp3_baseline_diagnostics_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
fold_plan_status
policy_status
fixed_threshold_mainline_status
volatility_scaled_threshold_status
baseline_sanity_status
wp4_entry_recommendation
row_count_scored
validation_row_count_evaluated
prospective_holdout_rows_evaluated
slice_count_evaluated
fold_count_evaluated
vol_scaled_candidate_count
asof_mode_count
flagged_metric_row_count
vol_scaled_summary_path
metric_audit_path
asof_shift_summary_path
leakage_violation_counts
metric_sanity_summary
vol_scaled_threshold_summary
best_vol_scaled_candidate_by_event_support
high_metric_audit_summary
asof_shift_summary
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
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Policy config

Create `configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml` with at least:

```text
index_id: STAGE03V-WP3.5-v1
policy_version: stage03v_vol_scaled_threshold_sanity_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
source_target_controls: reports/stage03v/target_controls_report.json
source_full_target_audit: reports/stage03v/full_target_streaming_audit_report.json
source_baseline_report: reports/stage03v/baseline_diagnostics_report.json
fold_plan: reports/stage03v/purge_embargo_fold_plan.json
fixed_threshold_mainline_policy: unchanged_reference_only
volatility_scaled_threshold_policy: supplement_only_not_replacement
volatility_estimators:
  - rolling_close_to_close_vol_20
  - rolling_close_to_close_vol_60
  - ewma_close_to_close_vol_20_or_equivalent
horizons:
  - 1
  - 5
  - 10
  - 20
k_candidates:
  - 1.0
  - 1.5
  - 2.0
  - 2.5
threshold_formula: threshold_abs = clamp(k * daily_vol * sqrt(horizon), 0.02, 0.15)
asof_modes:
  - close_t
  - close_t_minus_1
feature_asof_policy: feature_asof_date <= trade_date for close_t; feature_asof_date < trade_date for close_t_minus_1
evaluation_split_policy: validation_rows_only
final_holdout_policy: withheld_not_scored
calibration_policy: forbidden_in_wp3_5
readiness_policy: forbidden_in_wp3_5
model_training_policy: forbidden_in_wp3_5
```

JSON-formatted YAML is acceptable.

## Gate script

Create `scripts/stage03v_vol_scaled_threshold_sanity_gate.sh`.

Required behavior:

```text
Prefer STAGE03V_V7_DB.
Else use data/db/a_share_hmm_tushare_v7.duckdb.
Print actual DB path.
Run compileall and WP3.5-specific tests.
Run the WP3.5 CLI in no-fetch mode.
Validate JSON reports and policy.
Print stable marker:
STAGE03V_VOL_SCALED_THRESHOLD_SANITY_GATE=<status> db=<path> candidates=<n> validation_rows=<n> flagged_metrics=<n> baseline_sanity=<status> wp4_recommendation=<value> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_vol_scaled_threshold_sanity.py
tests/test_stage03v_baseline_metric_sanity.py
```

Minimum synthetic coverage:

```text
Volatility-scaled threshold uses only causal returns.
close_t_minus_1 mode excludes same-date price information.
Annualized volatility, if provided, is converted to horizon-scale units before threshold comparison.
Clamp min and max are applied deterministically.
Same-row label does not influence threshold construction.
Future target columns are rejected as inputs.
Target namespace columns are rejected as feature inputs.
Feature-as-of violations are detected.
Prospective holdout rows are withheld and not evaluated.
Fixed-threshold WP1 target rows are not mutated.
Missing or failed WP3 report blocks WP3.5.
Missing V7 DB returns blocked status and no old-DB fallback.
High-AUC diagnostic-only metric rows trigger sanity audit coverage.
Low positive-event support triggers artifact warning.
Single-date or single-entity concentration triggers artifact warning.
Close-t versus t-minus-one metric deltas are reported or explicitly deferred with reason.
No external fetch occurs.
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_vol_scaled_threshold_sanity.py tests/test_stage03v_baseline_metric_sanity.py
python -m src.evaluation.stage03v_vol_scaled_threshold_sanity \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --baseline-report reports/stage03v/baseline_diagnostics_report.json \
  --baseline-fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --baseline-slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --baseline-policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --policy configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml \
  --output reports/stage03v/vol_scaled_threshold_sanity_report.md \
  --summary-json reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --vol-scaled-summary reports/stage03v/vol_scaled_threshold_slice_summary.csv \
  --metric-audit reports/stage03v/baseline_metric_sanity_audit.csv \
  --asof-shift-summary reports/stage03v/asof_shift_metric_sanity.csv \
  --no-fetch
bash scripts/stage03v_vol_scaled_threshold_sanity_gate.sh
python -m json.tool reports/stage03v/vol_scaled_threshold_sanity_report.json
python -m json.tool configs/stage03v_vol_scaled_threshold_sanity_policy_v1.yaml
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
```

Also run a missing-V7 negative check to temporary outputs:

```bash
python -m src.evaluation.stage03v_vol_scaled_threshold_sanity \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp3_5_missing_v7.md \
  --summary-json tmp/stage03v_wp3_5_missing_v7.json \
  --vol-scaled-summary tmp/stage03v_wp3_5_missing_v7_vol_scaled_summary.csv \
  --metric-audit tmp/stage03v_wp3_5_missing_v7_metric_audit.csv \
  --asof-shift-summary tmp/stage03v_wp3_5_missing_v7_asof_shift.csv \
  --no-fetch
```

Expected: blocked status, no crash, no old DB fallback, no overwrite of formal outputs/configs unless explicitly passed.

## Acceptance criteria

WP3.5 passes if:

```text
WP1, WP2, WP2.1, and WP3 support statuses are pass.
V7 / SW2021 L2 verification is enforced.
Missing V7 DB produces blocked status and no old-DB fallback.
Fixed-threshold WP1 target mainline is unchanged.
Volatility-scaled threshold variants are evaluated causally and reported as supplement-only diagnostics.
Close-t and close-t-minus-one as-of comparison is present or explicitly deferred per baseline with reason.
WP3 abnormal metric sanity audit is completed and covers the known high-AUC diagnostic-only baseline.
Fold metrics and slice metrics use validation rows only.
No prospective final holdout rows are evaluated.
Leakage and boundary violation counts are zero.
Machine-readable routing fields are emitted for WP4 sequencing.
No learned model is trained.
No probability is calibrated.
No readiness is assigned.
No trading, buy/sell, sizing, recommendation, or decision output is created.
```

## Forbidden behavior

Do not fetch external data.

Do not train logistic hazard or any learned model.

Do not calibrate probabilities.

Do not assign readiness or usable_probability.

Do not consume final holdout performance.

Do not replace or mutate the WP1 fixed-threshold target mainline.

Do not commit full target, feature, baseline-score, or volatility-scaled matrices.

Do not write persistent DB tables by default.

Do not modify HMM / HSMM training algorithms.

Do not implement Stage03V2 or Stage03V3.

Do not create UI, trading, buy/sell, sizing, recommendation, or decision outputs.

## Return format

Use the work package return contract exactly:

```text
index_id: STAGE03V-WP3.5-v1
branch: stage03v/wp3.5-volatility-scaled-threshold-sanity
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
fold count evaluated: ...
validation rows evaluated: ...
prospective holdout rows evaluated: ...
vol-scaled candidate count: ...
asof mode count: ...
flagged metric row count: ...
volatility_scaled_threshold_status: ...
baseline_sanity_status: ...
wp4_entry_recommendation: ...
leakage violation count total: ...
feature_asof violations: ...
target namespace input violations: ...
future column input violations: ...
same-row label leakage count: ...
validation label leakage count: ...
fixed threshold mainline mutation count: ...
metric sanity summary: ...
vol-scaled threshold summary: ...
high metric audit summary: ...
asof shift summary: ...

external data fetch: no
target dataset modified: no
fixed threshold mainline modified: no
persistent DB table written: no
full target matrix committed: no
full feature matrix committed: no
full score matrix committed: no
model training: no
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
