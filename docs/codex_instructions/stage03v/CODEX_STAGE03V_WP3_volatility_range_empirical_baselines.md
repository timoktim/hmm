# CODEX_STAGE03V_WP3_volatility_range_empirical_baselines

Repository: timoktim/hmm

Index id: `STAGE03V-WP3-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP3_volatility_range_empirical_baselines.md`

Suggested branch: `stage03v/wp3-volatility-range-empirical-baselines`

## Instruction

Start from updated `main`. Confirm PR79 / Stage03V WP2.1 has been merged and that `reports/stage03v/full_target_streaming_audit_report.json` is present with `status=pass`. Create the suggested branch and execute only `STAGE03V-WP3-v1`.

This package implements baseline diagnostics only: volatility, range-based, empirical, market-state, and continuous diagnostic baselines for Stage03V1 downside-risk targets. Do not open logistic hazard work. Do not calibrate probabilities. Do not assign readiness. Do not consume holdout performance. Do not implement Stage03V2 or Stage03V3.

## Read first

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP3_volatility_range_empirical_baselines.md
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

## Required precondition

Proceed only if:

```text
reports/stage03v/risk_event_target_support.json status: pass
reports/stage03v/target_controls_report.json status: pass
reports/stage03v/full_target_streaming_audit_report.json status: pass
full_target_rows_checked: 7474840
row_count_delta: 0
violation_count_total: 0
recompute_violation_count_total: 0
all slice deltas: 0
source_db_path: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
v7_coverage_available: yes
sw2021_l2_universe_coverage: pass
entity_count_after_silent_break_handling: 124
feature_namespace_policy_status: pass
purge_violation_count: 0
embargo_violation_count: 0
```

If not, emit `blocked_wp2_1_not_ready` and stop.

## Required files

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

Do not commit full baseline score matrices.

## CLI

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

DB behavior:

```text
Prefer STAGE03V_V7_DB when set.
Otherwise default to data/db/a_share_hmm_tushare_v7.duckdb.
If V7 DB is missing or invalid, emit blocked_missing_v7_db / blocked_invalid_v7_db.
Never fall back to data/db/a_share_hmm.duckdb.
CI unit tests must not require private DuckDB.
```

## Baseline families

Implement at least:

```text
empirical_event_rate
entity_empirical_event_rate
cross_sectional_market_event_share
realized_volatility
range_based_volatility
recent_drawdown
continuous_target_proxy
```

Empirical causal variants:

```text
rolling_global_event_rate
rolling_entity_event_rate
rolling_slice_event_rate
rolling_entity_slice_event_rate
expanding_global_event_rate
expanding_entity_event_rate
```

Volatility causal variants:

```text
rolling_close_to_close_vol_20
rolling_close_to_close_vol_60
ewma_close_to_close_vol
rolling_downside_vol_20
rolling_downside_vol_60
```

Range-based variants if OHLC exists:

```text
parkinson_vol_20
parkinson_vol_60
garman_klass_vol_20
garman_klass_vol_60
rogers_satchell_vol_20
rogers_satchell_vol_60
intraday_range_ratio_20
```

Recent drawdown variants:

```text
rolling_max_drawdown_20
rolling_max_drawdown_60
rolling_distance_from_high_20
rolling_distance_from_high_60
```

Continuous diagnostics:

```text
rank_correlation_with_future_mae
rank_correlation_with_future_mdd
rank_correlation_with_future_return
quantile_lift_by_future_mae
quantile_lift_by_event_label
```

Rules:

```text
All baseline score construction must be causal.
Use only data at or before trade_date.
No t+1 or later prices may enter baseline features.
No same-row event_label may enter baseline score.
No validation labels may enter training-derived empirical rates.
Range-based baselines must be marked unavailable if OHLC is missing or unreliable.
Continuous diagnostics are evaluation-only and must not become readiness or calibrated probability.
```

## Evaluation metrics

For each baseline / slice / fold, emit applicable metrics:

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

```text
Use validation rows only for fold metrics.
Use train rows only to derive empirical rates.
No prospective final holdout rows may enter metrics.
Metrics may be null where not applicable or event count is insufficient.
```

## Fold / purge / embargo integration

Use:

```text
reports/stage03v/purge_embargo_fold_plan.json
```

Hard requirements:

```text
fold_plan_source: accepted WP2 fold plan
purge_violation_count: 0
embargo_violation_count: 0
validation rows only for diagnostics
training rows only for empirical-rate history
embargoed / purged rows excluded from training history if they would leak into validation
```

If fold plan missing or invalid, emit `blocked_missing_fold_plan` or `blocked_invalid_fold_plan`.

## Causality and leakage controls

Prove and report zero counts for:

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

## Required report

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

Boundary flags:

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

JSON-formatted YAML is acceptable.

## Gate script

Create `scripts/stage03v_baseline_diagnostics_gate.sh`.

Behavior:

```text
Prefer STAGE03V_V7_DB.
Else use data/db/a_share_hmm_tushare_v7.duckdb.
Print actual DB path.
Run compileall and WP3-specific tests.
Run baseline diagnostics CLI in no-fetch mode.
Validate JSON reports and policy.
Print stable marker:
STAGE03V_BASELINE_DIAGNOSTICS_GATE=<status> db=<path> baselines=<n> validation_rows=<n> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_baseline_diagnostics.py
tests/test_stage03v_baseline_causality.py
```

Minimum coverage:

```text
Rolling empirical event rate uses only prior rows.
Same-row label does not influence baseline score.
Validation labels do not influence training-derived empirical-rate scores.
Rolling volatility uses only returns available at or before trade_date.
Range-based volatility uses OHLC only when OHLC is available.
Drawdown baseline uses only past prices.
Feature_asof_date violations are detected.
Target namespace columns are rejected as baseline inputs.
future_* columns are rejected as baseline inputs.
Prospective holdout rows are withheld and not evaluated.
Missing V7 DB returns blocked status and no fallback.
Missing/failed WP2.1 report blocks WP3.
No external fetch occurs.
```

## Required commands

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

Expected: blocked status, no crash, no old DB fallback, no overwrite of formal outputs unless explicitly passed.

## Forbidden behavior

Do not fetch external data.

Do not train logistic hazard or any learned model.

Do not calibrate probabilities.

Do not assign readiness or usable_probability.

Do not consume final holdout performance.

Do not modify target dataset.

Do not commit full feature matrix.

Do not write persistent DB tables by default.

Do not modify HMM / HSMM training algorithms.

Do not implement Stage03V2 or Stage03V3.

Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Return format

Use the work package return contract exactly:

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
