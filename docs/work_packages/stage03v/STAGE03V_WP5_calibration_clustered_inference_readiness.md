# STAGE03V_WP5_calibration_clustered_inference_readiness

Stage: 03V / Volatility and downside-risk hazard

Work package: WP5

Index id: `STAGE03V-WP5-v1`

Suggested branch: `stage03v/wp5-calibration-clustered-readiness`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP5_calibration_clustered_inference_readiness.md`

Date: 2026-06-11

## Objective

Implement Stage03V1 calibration diagnostics, clustered inference, and downside-risk readiness matrix on top of the accepted WP4 logistic hazard artifacts.

WP5 is the first package where probability calibration and readiness assignment are allowed. Calibration and readiness remain development / research artifacts only. They must not consume prospective final holdout performance and must not produce trading, sizing, recommendation, or UI decision outputs.

WP5 must preserve the fixed-threshold Stage03V1 target mainline. Volatility-scaled candidates from WP3.5 remain reference metadata unless a later reviewed package explicitly activates them.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP3.5_volatility_scaled_threshold_sanity_gate.md
docs/work_packages/stage03v/STAGE03V_WP4_logistic_downside_risk_hazard_v1.md
configs/risk_event_signal_contract_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
configs/stage03v_logistic_hazard_policy_v1.yaml
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/baseline_diagnostics_report.json
reports/stage03v/vol_scaled_threshold_sanity_report.json
reports/stage03v/logistic_hazard_report.json
reports/stage03v/logistic_hazard_fold_metrics.csv
reports/stage03v/logistic_hazard_slice_metrics.csv
reports/stage03v/logistic_hazard_model_manifest.json
reports/stage03v/logistic_hazard_coefficients.csv
reports/stage03v/purge_embargo_fold_plan.json
```

## Required preconditions

WP5 may proceed only if all are true:

```text
WP1 target support: pass
WP2 target controls: pass
WP2.1 full-target audit: pass
WP3 baseline diagnostics: pass
WP3.5 volatility-scaled sanity: pass
WP4 logistic hazard: pass
V7 coverage: yes
SW2021 L2 universe: pass
source DB: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
WP4 model_training: yes
WP4 probability_calibration: no
WP4 readiness_assigned: no
WP4 leakage violation total: 0
WP4 training boundary violation total: 0
WP4 prospective holdout rows evaluated: 0
WP4 fixed_threshold_mainline_status: unchanged_primary_target
```

If any precondition fails, emit `blocked_wp4_not_ready` and stop.

## Stage boundary

Allowed:

- Read V7 DuckDB read-only.
- Recompute or reuse WP4 historical-development logistic raw scores as needed.
- Fit calibration models on historical-development calibration partitions only.
- Evaluate calibrated outputs on validation partitions only.
- Compute reliability diagnostics and calibration metrics.
- Compute clustered uncertainty summaries by entity, date, fold, and slice.
- Assign development readiness categories to slice/as-of/model outputs.
- Emit aggregate reports, readiness matrices, calibration curves, inference summaries, and small capped audit samples.

Forbidden:

- Do not fetch external data.
- Do not consume or inspect prospective final holdout performance.
- Do not modify fixed-threshold target rows, labels, support reports, or target universe manifests.
- Do not replace fixed-threshold Stage03V1 target family with volatility-scaled labels.
- Do not train new non-logistic model families.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, recommendation, or decision outputs.
- Do not commit full target, feature, raw score, or calibrated score matrices.
- Do not write persistent DuckDB tables by default.
- Do not implement Stage03V2 or Stage03V3.

## Calibration design

WP5 may implement these calibration candidates:

```text
identity_uncalibrated_reference
platt_logistic_calibration
isotonic_calibration
```

Rules:

- `identity_uncalibrated_reference` is the raw WP4 logistic score reference.
- Platt and isotonic calibration must fit only on calibration rows that are strictly historical-development and not evaluation rows.
- A calibration candidate must be skipped with explicit reason if class support is insufficient.
- Do not fit a calibrator on the same rows used to report final calibrated validation metrics unless using a documented nested split or out-of-fold protocol.
- Do not use prospective final holdout rows.
- Do not claim final production calibration readiness. Readiness is Stage03V development readiness only.

Recommended protocol:

```text
For each accepted WP2 fold and fixed-threshold slice:
1. Use training rows before the fold validation window to fit the WP4-style logistic model.
2. Split the fold validation period deterministically into calibration_subperiod and evaluation_subperiod, preserving time order.
3. Fit calibration candidates on calibration_subperiod only.
4. Evaluate calibrated scores on evaluation_subperiod only.
5. Report calibration/evaluation row counts separately.
```

If the validation window is too short for that split, use a deterministic nested train/calibration split inside the training period and evaluate on the fold validation period. The report must state which protocol was used.

## Readiness categories

Allowed readiness categories in WP5:

```text
usable_probability_candidate
ordinal_only_candidate
baseline_only_candidate
research_only
insufficient_data
blocked_by_leakage
```

These are development readiness labels, not trading output.

Readiness must be assigned per:

```text
asof_mode
horizon
threshold_type
threshold_value
target_usage
calibration_method
```

Minimum readiness criteria must consider:

```text
calibration/evaluation row count
positive event count
negative event count
Brier score
log loss
ECE / expected calibration error
MCE / max calibration error
reliability slope/intercept
AUC / AP retention after calibration
clustered uncertainty width
stability across folds
monotonicity / bin support
known WP3.5 baseline sanity warnings
```

Readiness gates must be conservative. Diagnostic-only target_usage may not be promoted above `research_only` unless explicitly justified and still marked diagnostic.

## Clustered inference

Implement lightweight clustered uncertainty diagnostics. Heavy econometric dependencies are not required.

Required clusters:

```text
entity_id
trade_date
fold_id
slice_key
```

Required outputs:

```text
cluster_count
min_cluster_size
max_cluster_size
clustered_metric_mean
clustered_metric_std
bootstrap_or_cluster_se_rows
confidence_interval_low
confidence_interval_high
uncertainty_status
```

A deterministic bootstrap or cluster-level aggregation is acceptable. Use fixed random seed if sampling is used.

## Required deliverables

Create:

```text
src/evaluation/stage03v_calibration_readiness.py
scripts/stage03v_calibration_readiness_gate.sh
tests/test_stage03v_calibration_readiness.py
tests/test_stage03v_calibration_causality.py
configs/stage03v_calibration_readiness_policy_v1.yaml
reports/stage03v/calibration_readiness_report.md
reports/stage03v/calibration_readiness_report.json
reports/stage03v/calibration_fold_metrics.csv
reports/stage03v/calibration_slice_metrics.csv
reports/stage03v/calibration_curve_bins.csv
reports/stage03v/clustered_inference_summary.csv
reports/stage03v/downside_readiness_matrix.csv
reports/stage03v/calibration_model_manifest.json
reports/stage03v/calibration_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

Do not commit serialized calibration model binaries.

## Required CLI

Implement:

```bash
python -m src.evaluation.stage03v_calibration_readiness \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --logistic-fold-metrics reports/stage03v/logistic_hazard_fold_metrics.csv \
  --logistic-slice-metrics reports/stage03v/logistic_hazard_slice_metrics.csv \
  --logistic-model-manifest reports/stage03v/logistic_hazard_model_manifest.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_calibration_readiness_policy_v1.yaml \
  --output reports/stage03v/calibration_readiness_report.md \
  --summary-json reports/stage03v/calibration_readiness_report.json \
  --fold-metrics reports/stage03v/calibration_fold_metrics.csv \
  --slice-metrics reports/stage03v/calibration_slice_metrics.csv \
  --calibration-bins reports/stage03v/calibration_curve_bins.csv \
  --clustered-inference reports/stage03v/clustered_inference_summary.csv \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --model-manifest reports/stage03v/calibration_model_manifest.json \
  --audit-sample reports/stage03v/calibration_audit_sample.csv \
  --no-fetch
```

DB path behavior:

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise use `data/db/a_share_hmm_tushare_v7.duckdb`.
- If V7 DB is missing or invalid, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Never fall back to `data/db/a_share_hmm.duckdb`.
- CI unit tests must not require private DuckDB.

## Required report JSON fields

Create `reports/stage03v/calibration_readiness_report.json` with at least:

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
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
fold_plan_status
policy_status
calibration_methods_evaluated
primary_calibration_method
asof_modes_evaluated
primary_asof_mode
slice_count_evaluated
fold_count_evaluated
calibration_row_count_total
evaluation_row_count_total
prospective_holdout_rows_evaluated
calibration_model_count
skipped_calibration_count
readiness_category_counts
usable_probability_candidate_count
ordinal_only_candidate_count
baseline_only_candidate_count
research_only_count
insufficient_data_count
blocked_by_leakage_count
fold_metrics_path
slice_metrics_path
calibration_bins_path
clustered_inference_path
readiness_matrix_path
model_manifest_path
audit_sample_path
metric_summary
best_calibrated_candidate_by_brier
best_calibrated_candidate_by_log_loss
best_calibrated_candidate_by_ece
clustered_inference_summary
leakage_violation_counts
calibration_boundary_violation_counts
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
calibration_model_serialized: no
model_training: no_new_non_logistic_model
probability_calibration: yes
readiness_assigned: yes_development_only
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
trading_or_decision_output: no
```

## Policy config

Create `configs/stage03v_calibration_readiness_policy_v1.yaml`.

Minimum fields:

```text
index_id: STAGE03V-WP5-v1
policy_version: stage03v_calibration_readiness_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
source_logistic_hazard: reports/stage03v/logistic_hazard_report.json
source_vol_scaled_sanity: reports/stage03v/vol_scaled_threshold_sanity_report.json
fold_plan: reports/stage03v/purge_embargo_fold_plan.json
primary_target_family: fixed_threshold_stage03v1_downside_event
vol_scaled_candidate_policy: tracked_reference_only
primary_asof_mode: close_t_minus_1
calibration_methods:
  - identity_uncalibrated_reference
  - platt_logistic_calibration
  - isotonic_calibration
calibration_protocol: deterministic_time_ordered_calibration_then_evaluation
final_holdout_policy: withheld_not_scored
readiness_scope: development_only_not_trading
readiness_categories:
  - usable_probability_candidate
  - ordinal_only_candidate
  - baseline_only_candidate
  - research_only
  - insufficient_data
  - blocked_by_leakage
external_fetch_policy: forbidden
persistent_db_table_policy: forbidden_by_default
full_score_matrix_policy: forbidden_to_commit
```

JSON-formatted YAML is acceptable if consistent with existing repo practice.

## Gate script

Create `scripts/stage03v_calibration_readiness_gate.sh`.

It must:

- Prefer `STAGE03V_V7_DB`.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print actual DB path.
- Run compileall.
- Run WP5-specific tests.
- Run the WP5 CLI in no-fetch mode.
- Validate JSON reports and policy.
- Print stable marker:

```text
STAGE03V_CALIBRATION_READINESS_GATE=<status> db=<path> calibration_models=<n> readiness_rows=<n> usable_probability_candidates=<n> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_calibration_readiness.py
tests/test_stage03v_calibration_causality.py
```

Minimum synthetic coverage:

- Missing V7 DB returns `blocked_missing_v7_db` and no old DB fallback.
- Missing/failed WP4 report blocks WP5.
- Calibration rows are strictly before evaluation rows under the chosen protocol.
- Evaluation labels do not affect calibration model fit.
- Prospective holdout rows are withheld and not calibrated/evaluated.
- Platt calibration fits only calibration rows.
- Isotonic calibration fits only calibration rows.
- Insufficient class support skips calibration with explicit reason.
- Development readiness categories are assigned only from historical-development metrics.
- Diagnostic-only slices do not get promoted above conservative/research status without explicit flag.
- Clustered inference summaries are deterministic.
- No serialized calibration model binaries are written.
- No external fetch occurs.
- No trading or decision outputs are produced.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_calibration_readiness.py tests/test_stage03v_calibration_causality.py
python -m src.evaluation.stage03v_calibration_readiness \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --full-target-audit reports/stage03v/full_target_streaming_audit_report.json \
  --baseline-diagnostics reports/stage03v/baseline_diagnostics_report.json \
  --vol-scaled-sanity reports/stage03v/vol_scaled_threshold_sanity_report.json \
  --logistic-hazard reports/stage03v/logistic_hazard_report.json \
  --logistic-fold-metrics reports/stage03v/logistic_hazard_fold_metrics.csv \
  --logistic-slice-metrics reports/stage03v/logistic_hazard_slice_metrics.csv \
  --logistic-model-manifest reports/stage03v/logistic_hazard_model_manifest.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --policy configs/stage03v_calibration_readiness_policy_v1.yaml \
  --output reports/stage03v/calibration_readiness_report.md \
  --summary-json reports/stage03v/calibration_readiness_report.json \
  --fold-metrics reports/stage03v/calibration_fold_metrics.csv \
  --slice-metrics reports/stage03v/calibration_slice_metrics.csv \
  --calibration-bins reports/stage03v/calibration_curve_bins.csv \
  --clustered-inference reports/stage03v/clustered_inference_summary.csv \
  --readiness-matrix reports/stage03v/downside_readiness_matrix.csv \
  --model-manifest reports/stage03v/calibration_model_manifest.json \
  --audit-sample reports/stage03v/calibration_audit_sample.csv \
  --no-fetch
bash scripts/stage03v_calibration_readiness_gate.sh
python -m json.tool reports/stage03v/calibration_readiness_report.json
python -m json.tool reports/stage03v/calibration_model_manifest.json
python -m json.tool configs/stage03v_calibration_readiness_policy_v1.yaml
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

WP5 passes if:

- WP1/WP2/WP2.1/WP3/WP3.5/WP4 inputs are all pass.
- V7 and SW2021 L2 verification is enforced.
- Missing V7 blocks and does not fall back.
- Calibration candidates use calibration rows only.
- Evaluation rows are not used to fit calibrators.
- Prospective final holdout rows are not used.
- Calibration metrics, curve bins, clustered inference, and readiness matrix are emitted.
- Readiness categories are development-only and not trading outputs.
- No full score matrices are committed.
- No serialized calibration model binaries are committed.
- Fixed-threshold mainline remains unchanged.
- Volatility-scaled candidates remain reference-only.
- No Stage03V2/3 implementation occurs.
- CI and gate pass.

## Return format

```text
index_id: STAGE03V-WP5-v1
branch: stage03v/wp5-calibration-clustered-readiness
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

calibration methods evaluated: ...
primary calibration method: ...
asof modes evaluated: ...
primary asof mode: ...
fold count evaluated: ...
slice count evaluated: ...
calibration rows total: ...
evaluation rows total: ...
prospective holdout rows evaluated: ...
calibration model count: ...
skipped calibration count: ...
readiness category counts: ...
usable probability candidate count: ...
ordinal only candidate count: ...
baseline only candidate count: ...
research only count: ...
insufficient data count: ...
clustered inference summary: ...
leakage violation count total: ...
calibration boundary violation count total: ...

external data fetch: no
target dataset modified: no
fixed threshold mainline modified: no
persistent DB table written: no
full target matrix committed: no
full feature matrix committed: no
full score matrix committed: no
calibration model serialized: no
probability calibration: yes
readiness assigned: yes_development_only
holdout consumed: no
HMM/HSMM training modified: no
Stage03V2 implemented: no
Stage03V3 implemented: no
trading or decision output: no

remaining risks:
- ...
```
