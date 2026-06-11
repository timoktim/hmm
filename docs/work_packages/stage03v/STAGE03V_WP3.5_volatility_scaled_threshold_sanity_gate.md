# STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate

Stage: 03V / Volatility and downside-risk hazard

Work package: WP3.5

Index id: `STAGE03V-WP3.5-v1`

Suggested branch: `stage03v/wp3.5-volatility-scaled-threshold-sanity`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP3.5_volatility_scaled_threshold_sanity.md`

Date: 2026-06-11

## Objective

Implement a Stage03V1 supplement and sanity gate between WP3 baseline diagnostics and WP4 logistic downside-risk hazard training.

WP3.5 does not replace the WP1 fixed-threshold target mainline. It evaluates whether volatility-scaled threshold variants should be tracked as research candidates, and it audits WP3 baseline metrics for artifacts before any learned model, probability calibration, readiness assignment, or downstream risk validation package opens.

The package has two primary goals:

```text
1. Evaluate causal volatility-scaled downside-risk threshold variants as aggregate diagnostics only.
2. Audit abnormal WP3 baseline metrics, especially extreme diagnostic-only results, for sample, fold, date, entity, as-of, and threshold artifacts.
```

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

## Required input state

WP3.5 may proceed only if:

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

If these conditions are not met, emit the most specific blocked status and stop:

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

Do not silently fall back to `data/db/a_share_hmm.duckdb`.

## Stage boundary

Allowed:

- Read the V7 DuckDB read-only.
- Read accepted WP1, WP2, WP2.1, and WP3 artifacts.
- Rebuild or stream historical-development target rows as needed for aggregate diagnostics.
- Compute causal volatility estimators available at or before each scored `trade_date`.
- Compute in-memory or temporary volatility-scaled threshold event labels for historical-development diagnostics.
- Compare fixed-threshold support and volatility-scaled support at aggregate, fold, slice, entity, and date levels.
- Audit WP3 baseline metrics for sample-size, event-count, fold, date, entity, threshold, target-usage, and as-of artifacts.
- Emit machine-readable aggregate reports and capped audit samples.
- Add synthetic tests for volatility-scaled threshold causality, baseline metric sanity, and as-of shift checks.

Forbidden:

- Do not replace, rewrite, or mutate the WP1 fixed-threshold target dataset, target labels, support reports, or target universe manifest.
- Do not train logistic hazard, gradient boosting, neural, HMM, HSMM, BOCPD, or any learned model.
- Do not calibrate probabilities.
- Do not assign `usable_probability`, `ordinal_only`, `baseline_only`, readiness, trading, or model-promotion status.
- Do not consume or inspect prospective final holdout performance.
- Do not build Stage03V2 upside-trigger targets.
- Do not build Stage03V3 competing-risk targets.
- Do not commit full target matrices, full feature matrices, full baseline score matrices, or per-row volatility-scaled score matrices.
- Do not write persistent DuckDB tables by default.
- Do not fetch external data.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, recommendation, or decision outputs.

## Required deliverables

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

CSV artifacts must be aggregate or capped samples only:

```text
vol_scaled_threshold_slice_summary: aggregate per threshold candidate / horizon / slice / fold / target_usage
baseline_metric_sanity_audit: capped high-metric audit rows and aggregate concentration diagnostics
asof_shift_metric_sanity: aggregate close_t vs close_t_minus_1 metric comparison, no full score matrix
```

Do not commit a full volatility-scaled target matrix or a full baseline score matrix.

## Required CLI

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

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise default to `data/db/a_share_hmm_tushare_v7.duckdb`.
- If the V7 DB is missing or not long-history, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Never fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB; synthetic tests are acceptance-critical.

## Volatility-scaled threshold supplement

Evaluate volatility-scaled thresholds as a supplement, not as a replacement for WP1 fixed thresholds.

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

Threshold formula must be explicit and unit-consistent. The default expected convention is:

```text
daily_vol = causal daily close-to-close volatility, not annualized
horizon_scaled_vol = daily_vol * sqrt(horizon)
threshold_abs = clamp(k * horizon_scaled_vol, clamp_min_abs_threshold, clamp_max_abs_threshold)
event_label_vol_scaled = future_max_drawdown_abs >= threshold_abs
```

If the implementation uses annualized volatility, it must convert back to the target horizon before threshold comparison and document the conversion in the report.

Causality rules:

- Volatility features must use returns ending at or before `trade_date` for `asof_mode=close_t`.
- The diagnostic `asof_mode=close_t_minus_1` must shift price-derived features so the latest return or OHLC observation ends strictly before `trade_date`.
- No `future_*` target column may enter volatility estimator construction.
- No same-row event label may enter any threshold or score construction.
- Prospective final holdout rows must not be scored or evaluated.
- Fold metrics must use validation rows only; empirical history, if any, must use training rows only and must respect purge/embargo.

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

WP3.5 must audit WP3 metrics before WP4 opens.

At minimum, identify and audit:

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

The known WP3 diagnostic that must be explicitly covered is the high-AUC diagnostic-only baseline:

```text
baseline_name: rolling_close_to_close_vol_60
baseline_family: realized_volatility
metric: roc_auc
value: approximately 0.9939857845817387
horizon: 1
threshold_value: 0.05
target_usage: diagnostic_only
```

WP3.5 does not need to prove this result is invalid. It must classify it as one of:

```text
explained_by_sample_or_slice_structure
explained_by_asof_semantics
explained_by_threshold_or_event_imbalance
unexplained_warning
no_artifact_detected
```

## Close-t versus t-minus-one as-of sanity

WP3 allowed price-derived baseline features with `feature_asof_date = trade_date`, corresponding to a close-after-market diagnostic for future `t+1..t+N` risk.

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

If the t-minus-one comparison is not feasible for a specific baseline, emit `asof_shift_deferred` with a specific reason. A blanket omission is not acceptable.

## Decision fields for downstream routing

WP3.5 must not assign readiness or calibrated probability status. It may emit routing recommendations for package sequencing only:

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

These fields are not trading decisions and must not be interpreted as model readiness.

## Evaluation metrics

For volatility-scaled threshold candidates, report aggregate diagnostics by candidate / horizon / slice / fold:

```text
row_count
scored_row_count
positive_event_count
event_base_rate
score_available_rate
threshold_abs_mean
threshold_abs_median
threshold_abs_p10
threshold_abs_p90
clamp_min_hit_rate
clamp_max_hit_rate
entity_count_with_positive_events
median_positive_events_per_entity
min_positive_events_per_fold
market_event_block_count
effective_event_evidence_count
fixed_threshold_event_count
fixed_threshold_event_base_rate
vol_scaled_to_fixed_event_count_ratio
```

For metric sanity, report the flagged-row audit fields listed above and summary counts:

```text
flagged_metric_row_count
high_auc_flag_count
high_ap_flag_count
high_rank_correlation_flag_count
low_support_flag_count
concentration_warning_count
asof_dependency_warning_count
diagnostic_only_flag_count
unexplained_warning_count
metric_sanity_fail_count
```

## Causality and leakage controls

WP3.5 must prove and report zero counts for:

```text
feature_asof_violation_count
target_namespace_input_violation_count
future_column_input_violation_count
same_row_label_leakage_count
validation_label_leakage_count
prospective_holdout_score_count
prospective_holdout_metric_count
fixed_threshold_mainline_mutation_count
persistent_db_write_count
external_fetch_count
```

All must be zero for `status=pass`. Metric sanity warnings may produce `baseline_sanity_status=warning` while the package `status` remains `pass` if the audit completed and no boundary or leakage violation occurred.

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

The file may be JSON-formatted YAML, consistent with existing repo practice.

## Gate script

Create `scripts/stage03v_vol_scaled_threshold_sanity_gate.sh`.

Required behavior:

- Prefer `STAGE03V_V7_DB` if set.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall and WP3.5-specific tests.
- Run the WP3.5 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_VOL_SCALED_THRESHOLD_SANITY_GATE=<status> db=<path> candidates=<n> validation_rows=<n> flagged_metrics=<n> baseline_sanity=<status> wp4_recommendation=<value> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_vol_scaled_threshold_sanity.py
tests/test_stage03v_baseline_metric_sanity.py
```

Minimum synthetic coverage:

- Volatility-scaled threshold uses only causal returns.
- `close_t_minus_1` mode excludes same-date price information.
- Annualized volatility, if provided, is converted to horizon-scale units before threshold comparison.
- Clamp min and max are applied deterministically.
- Same-row label does not influence threshold construction.
- Future target columns are rejected as inputs.
- Target namespace columns are rejected as feature inputs.
- Feature-as-of violations are detected.
- Prospective holdout rows are withheld and not evaluated.
- Fixed-threshold WP1 target rows are not mutated.
- Missing or failed WP3 report blocks WP3.5.
- Missing V7 DB returns blocked status and no old-DB fallback.
- High-AUC diagnostic-only metric rows trigger sanity audit coverage.
- Low positive-event support triggers artifact warning.
- Single-date or single-entity concentration triggers artifact warning.
- Close-t versus t-minus-one metric deltas are reported or explicitly deferred with reason.
- No external fetch occurs.

## Suggested commands

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

Expected missing-DB result: blocked status, no crash, no fallback to old DB, no overwrite of formal outputs/configs unless explicitly passed.

## Acceptance criteria

WP3.5 passes if:

- WP1, WP2, WP2.1, and WP3 support statuses are pass.
- V7 / SW2021 L2 verification is enforced.
- Missing V7 DB produces blocked status and no old-DB fallback.
- Fixed-threshold WP1 target mainline is unchanged.
- Volatility-scaled threshold variants are evaluated causally and reported as supplement-only diagnostics.
- Close-t and close-t-minus-one as-of comparison is present or explicitly deferred per baseline with reason.
- WP3 abnormal metric sanity audit is completed and covers the known high-AUC diagnostic-only baseline.
- Fold metrics and slice metrics use validation rows only.
- No prospective final holdout rows are evaluated.
- Leakage and boundary violation counts are zero.
- Machine-readable routing fields are emitted for WP4 sequencing.
- No learned model is trained.
- No probability is calibrated.
- No readiness is assigned.
- No trading, buy/sell, sizing, recommendation, or decision output is created.
