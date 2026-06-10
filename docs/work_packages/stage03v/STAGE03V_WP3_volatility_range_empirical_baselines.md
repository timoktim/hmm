# STAGE03V_WP3_volatility_range_empirical_baselines

Stage: 03V / Volatility and downside-risk hazard

Work package: WP3

Index id: `STAGE03V-WP3-v1`

Suggested branch: `stage03v/wp3-volatility-range-empirical-baselines`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP3_volatility_range_empirical_baselines.md`

Date: 2026-06-10

## Objective

Implement Stage03V1 baseline diagnostics for downside-risk targets using only causal, pre-trade-date information. WP3 creates volatility, range-based, empirical, market-state, and continuous diagnostic baselines so later model packages can be judged against simple, transparent references.

WP3 is not the logistic hazard package. It must not calibrate probabilities, assign readiness, consume prospective holdout performance, or implement Stage03V2 / Stage03V3.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md
docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md
docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md
configs/risk_event_signal_contract_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/purge_embargo_fold_plan.json
```

## Required input state

WP3 may proceed only if:

```text
reports/stage03v/risk_event_target_support.json status: pass
reports/stage03v/target_controls_report.json status: pass
reports/stage03v/full_target_streaming_audit_report.json status: pass
full_target_rows_checked: 7474840
row_count_delta: 0
violation_count_total: 0
recompute_violation_count_total: 0
slice_support_delta_count: 0 or all slice deltas 0
source_db_path: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
v7_coverage_available: yes
sw2021_l2_universe_coverage: pass
entity_count_after_silent_break_handling: 124
feature_namespace_policy_status: pass
purge_violation_count: 0
embargo_violation_count: 0
```

If these conditions are not met, emit `blocked_wp2_1_not_ready` and stop.

## Stage boundary

Allowed:

- Read the V7 DuckDB read-only.
- Rebuild target rows or stream target rows as needed for baseline diagnostics.
- Use accepted WP2 purge / embargo fold plan.
- Compute causal ex-ante baseline scores based on historical data available at or before each trade date.
- Compute fold-level diagnostic metrics on historical-development folds only.
- Emit machine-readable baseline reports and small capped audit samples.
- Add synthetic tests for causal rolling windows and leakage controls.

Forbidden:

- Do not fetch external data.
- Do not train logistic hazard, gradient boosting, neural, HMM, HSMM, BOCPD, or any learned model.
- Do not calibrate probabilities.
- Do not assign `usable_probability`, `ordinal_only`, `baseline_only`, or any readiness status.
- Do not consume or inspect prospective final holdout performance.
- Do not build Stage03V2 upside-trigger targets.
- Do not build Stage03V3 competing-risk targets.
- Do not modify WP1 target rows, target labels, target support reports, or target universe manifests.
- Do not commit full target or full feature matrices.
- Do not write persistent DuckDB tables by default.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, recommendation, or decision outputs.

## Required deliverables

Create:

```text
src/evaluation/stage03v_baseline_diagnostics.py
scripts/stage03v_baseline_diagnostics_gate.sh
tests/test_stage03v_baseline_diagnostics.py
tests/test_stage03v_baseline_causality.py
configs/stage03v_baseline_diagnostics_policy_v1.yaml
reports/stage03v/baseline_diagnostics_report.md
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/baseline_diagnostics_fold_metrics.csv
reports/stage03v/baseline_diagnostics_slice_metrics.csv
reports/stage03v/baseline_diagnostics_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

CSV artifacts must be small or aggregate-only:

```text
fold_metrics: aggregate per fold / slice / baseline
slice_metrics: aggregate per slice / baseline
audit_sample: capped at 500 rows by default
```

Do not commit full baseline score matrices.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_baseline_diagnostics \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --output reports/stage03v/baseline_diagnostics_report.md \
  --summary-json reports/stage03v/baseline_diagnostics_report.json \
  --fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --audit-sample reports/stage03v/baseline_diagnostics_audit_sample.csv \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise default to `data/db/a_share_hmm_tushare_v7.duckdb`.
- If the V7 DB is missing or not long-history, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Do not silently fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB; synthetic tests are acceptance-critical.

## Baseline families

WP3 must include at least these baseline families:

```text
empirical_event_rate
entity_empirical_event_rate
cross_sectional_market_event_share
realized_volatility
range_based_volatility
recent_drawdown
continuous_target_proxy
```

### Empirical baselines

Allowed causal variants:

```text
rolling_global_event_rate
rolling_entity_event_rate
rolling_slice_event_rate
rolling_entity_slice_event_rate
expanding_global_event_rate
expanding_entity_event_rate
```

Rules:

- The event-rate window must use only rows strictly before the scored trade_date.
- No current-row label or future label may enter the score.
- Minimum history thresholds must be explicit.
- Missing history must emit a deterministic fallback, e.g. prior global expanding rate or null with `score_available=false`.

### Volatility baselines

Allowed causal variants:

```text
rolling_close_to_close_vol_20
rolling_close_to_close_vol_60
ewma_close_to_close_vol
rolling_downside_vol_20
rolling_downside_vol_60
```

Rules:

- Use only returns ending at or before trade_date.
- Do not use t+1 or later prices.
- Annualization, if used, must be documented but not required.

### Range-based baselines

Allowed causal variants if OHLC is available:

```text
parkinson_vol_20
parkinson_vol_60
garman_klass_vol_20
garman_klass_vol_60
rogers_satchell_vol_20
rogers_satchell_vol_60
intraday_range_ratio_20
```

If OHLC columns are unavailable or unreliable, emit `range_based_unavailable` for the affected baseline and continue. Do not synthesize OHLC from close-only data.

### Recent drawdown baselines

Allowed causal variants:

```text
rolling_max_drawdown_20
rolling_max_drawdown_60
rolling_distance_from_high_20
rolling_distance_from_high_60
```

Rules:

- Use price history up to trade_date only.
- Do not use future MAE / MDD target columns as features.

### Continuous target proxy diagnostics

Allowed diagnostics:

```text
rank_correlation_with_future_mae
rank_correlation_with_future_mdd
rank_correlation_with_future_return
quantile_lift_by_future_mae
quantile_lift_by_event_label
```

Rules:

- These are evaluation diagnostics only.
- They must be computed on validation fold rows only.
- They must not be converted into readiness or calibrated probabilities.

## Evaluation metrics

For each baseline / slice / fold, report applicable metrics:

```text
row_count
scored_row_count
positive_event_count
event_base_rate
score_available_rate
roc_auc
average_precision
brier_like_score_if_score_in_0_1
spearman_score_vs_event
spearman_score_vs_future_mae
spearman_score_vs_future_mdd
quantile_lift_top_decile
quantile_lift_top_quintile
monotonic_decile_event_rate_status
```

Rules:

- Use validation rows only for fold metrics.
- Use train rows only to fit/derive any empirical rates.
- No fold may score validation rows using validation labels in the score construction.
- No prospective final holdout rows may enter metrics.
- Metrics may be `null` where not applicable or where event count is insufficient.

## Fold / purge / embargo integration

Use the accepted WP2 fold plan.

Hard requirements:

```text
fold_plan_source: reports/stage03v/purge_embargo_fold_plan.json
purge_violation_count: 0
embargo_violation_count: 0
validation rows only for diagnostics
training rows only for empirical-rate history
embargoed / purged rows excluded from training history if they would leak into validation
```

If the fold plan is missing or invalid, emit `blocked_missing_fold_plan` or `blocked_invalid_fold_plan`.

## Causality and leakage controls

WP3 must prove:

```text
feature_asof_date <= trade_date for every baseline score
no baseline score uses columns in target namespace
no baseline score uses any future_* column as input
no baseline score uses target_observation_end_date to choose score history except as validation-only diagnostic grouping when explicitly allowed
no baseline score uses event_label from the same row
no baseline score uses validation labels when constructing training-derived empirical rates
no prospective holdout rows are scored or evaluated
```

Report counts:

```text
feature_asof_violation_count
target_namespace_input_violation_count
future_column_input_violation_count
same_row_label_leakage_count
validation_label_leakage_count
prospective_holdout_score_count
prospective_holdout_metric_count
```

All must be zero for pass.

## Report contents

Create `reports/stage03v/baseline_diagnostics_report.json` with at least:

```text
index_id
report_version
status
wp1_support_status
wp2_controls_status
wp2_1_full_target_audit_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
fold_plan_status
baseline_policy_status
baseline_families_implemented
baseline_families_unavailable
row_count_scored
validation_row_count_evaluated
prospective_holdout_rows_evaluated
slice_count_evaluated
fold_count_evaluated
baseline_count
fold_metrics_path
slice_metrics_path
audit_sample_path
leakage_violation_counts
metric_summary
best_baseline_by_auc
best_baseline_by_average_precision
best_baseline_by_rank_correlation
range_based_availability_status
continuous_diagnostic_status
ci_gate_status
boundary_flags
```

Boundary flags must include:

```text
external_data_fetch: no
target_dataset_modified: no
persistent_db_table_written: no
full_feature_matrix_committed: no
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
```

## Policy config

Create `configs/stage03v_baseline_diagnostics_policy_v1.yaml` with at least:

```text
index_id: STAGE03V-WP3-v1
policy_version: stage03v_baseline_diagnostics_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
source_target_controls: reports/stage03v/target_controls_report.json
source_full_target_audit: reports/stage03v/full_target_streaming_audit_report.json
fold_plan: reports/stage03v/purge_embargo_fold_plan.json
baseline_families:
  - empirical_event_rate
  - entity_empirical_event_rate
  - cross_sectional_market_event_share
  - realized_volatility
  - range_based_volatility
  - recent_drawdown
  - continuous_target_proxy
feature_asof_policy: feature_asof_date <= trade_date
evaluation_split_policy: validation_rows_only
final_holdout_policy: withheld_not_scored
calibration_policy: forbidden_in_wp3
readiness_policy: forbidden_in_wp3
model_training_policy: forbidden_in_wp3
```

The file may be JSON-formatted YAML, consistent with existing repo practice.

## Gate script

Create `scripts/stage03v_baseline_diagnostics_gate.sh`.

Required behavior:

- Prefer `STAGE03V_V7_DB` if set.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall and WP3-specific tests.
- Run baseline diagnostics CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_BASELINE_DIAGNOSTICS_GATE=<status> db=<path> baselines=<n> validation_rows=<n> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_baseline_diagnostics.py
tests/test_stage03v_baseline_causality.py
```

Minimum synthetic coverage:

- Rolling empirical event rate uses only prior rows.
- Same-row label does not influence baseline score.
- Validation labels do not influence training-derived empirical-rate scores.
- Rolling volatility uses only returns available at or before trade_date.
- Range-based volatility uses OHLC only when OHLC is available.
- Drawdown baseline uses only past prices.
- Feature_asof_date violations are detected.
- Target namespace columns are rejected as baseline inputs.
- `future_*` columns are rejected as baseline inputs.
- Prospective holdout rows are withheld and not evaluated.
- Missing V7 DB returns blocked status and no fallback.
- Missing/failed WP2.1 report blocks WP3.
- No external fetch occurs.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_baseline_diagnostics.py tests/test_stage03v_baseline_causality.py
python -m src.evaluation.stage03v_baseline_diagnostics \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_baseline_diagnostics_policy_v1.yaml \
  --output reports/stage03v/baseline_diagnostics_report.md \
  --summary-json reports/stage03v/baseline_diagnostics_report.json \
  --fold-metrics reports/stage03v/baseline_diagnostics_fold_metrics.csv \
  --slice-metrics reports/stage03v/baseline_diagnostics_slice_metrics.csv \
  --audit-sample reports/stage03v/baseline_diagnostics_audit_sample.csv \
  --no-fetch
bash scripts/stage03v_baseline_diagnostics_gate.sh
python -m json.tool reports/stage03v/baseline_diagnostics_report.json
python -m json.tool configs/stage03v_baseline_diagnostics_policy_v1.yaml
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
```

Also run a missing-V7 negative check to temporary outputs:

```bash
python -m src.evaluation.stage03v_baseline_diagnostics \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp3_missing_v7.md \
  --summary-json tmp/stage03v_wp3_missing_v7.json \
  --fold-metrics tmp/stage03v_wp3_missing_v7_fold_metrics.csv \
  --slice-metrics tmp/stage03v_wp3_missing_v7_slice_metrics.csv \
  --audit-sample tmp/stage03v_wp3_missing_v7_audit_sample.csv \
  --no-fetch
```

Expected missing-DB result: blocked status, no crash, no fallback to old DB, no overwrite of formal reports/configs unless explicitly passed.

## Acceptance criteria

WP3 passes if:

- WP1, WP2, and WP2.1 support statuses are pass.
- V7 / SW2021 L2 verification is enforced.
- Missing V7 DB produces blocked status and no fallback.
- Baseline score construction is causal and has zero leakage violations.
- Baseline diagnostics use validation rows only.
- No prospective final holdout rows are evaluated.
- Empirical, volatility, recent-drawdown, and continuous diagnostic baseline families are implemented.
- Range-based baselines are implemented if OHLC is available, or explicitly marked unavailable if not.
- Fold metrics and slice metrics are emitted and machine-readable.
- No calibration or readiness is assigned.
- No model is trained.
- No probability is calibrated.
- No target dataset is modified.
- No full feature matrix is committed.
- No external data is fetched.
- No HMM / HSMM training algorithm is modified.
- Stage03V2 and Stage03V3 remain unimplemented.

## Return format

```text
index_id: STAGE03V-WP3-v1
branch: stage03v/wp3-volatility-range-empirical-baselines
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
fold count evaluated: ...
validation rows evaluated: ...
prospective holdout rows evaluated: ...
baseline families implemented: ...
baseline families unavailable: ...
baseline count: ...
leakage violation count total: ...
feature_asof violations: ...
target namespace input violations: ...
future column input violations: ...
same-row label leakage count: ...
validation label leakage count: ...
metric summary: ...
best baseline by AUC: ...
best baseline by AP: ...
range based availability status: ...
continuous diagnostic status: ...

external data fetch: no
target dataset modified: no
persistent DB table written: no
full feature matrix committed: no
model training: no
probability calibration: no
readiness assigned: no
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no

remaining risks:
- ...
```
