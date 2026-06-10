# CODEX_STAGE03V_WP2.1_full_target_streaming_audit

Repository: timoktim/hmm

Index id: `STAGE03V-WP2.1-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md`

Suggested branch: `stage03v/wp2.1-full-target-streaming-audit`

## Instruction

Start from updated `main`. Confirm PR78 / Stage03V WP2 has been merged and that `reports/stage03v/target_controls_report.json` is present with `status=pass`. Create the suggested branch and execute only `STAGE03V-WP2.1-v1`.

This package adds a full-target streaming / blockwise audit between WP2 and WP3. It validates the complete WP1 Stage03V1 target row universe, not just the 500-row audit sample. Do not open baseline or model work.

Do not train models. Do not calibrate probabilities. Do not assign readiness. Do not consume holdout performance. Do not write target DB tables. Do not commit full target datasets. Do not implement Stage03V2 or Stage03V3.

## Read first

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP2.1_full_target_streaming_audit.md
configs/risk_event_signal_contract_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
configs/stage03v_purge_embargo_policy_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
reports/stage03v/target_controls_report.json
reports/stage03v/purge_embargo_fold_plan.json
```

## Required precondition

Proceed only if:

```text
reports/stage03v/risk_event_target_support.json status: pass
reports/stage03v/target_controls_report.json status: pass
source_db_path: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
v7_coverage_available: yes
sw2021_l2_universe_coverage: pass
entity_count_after_silent_break_handling: 124
silent_entity_break_handling: excluded or segmented
target_row_count from WP1 support: 7474840
cross_cutoff_regression_passed: yes
purge_violation_count: 0
embargo_violation_count: 0
feature_namespace_policy_status: pass
```

If not, emit `blocked_wp2_not_ready` and stop.

## Required files

Create:

```text
src/evaluation/stage03v_full_target_audit.py
scripts/stage03v_full_target_audit_gate.sh
tests/test_stage03v_full_target_audit.py
reports/stage03v/full_target_streaming_audit_report.md
reports/stage03v/full_target_streaming_audit_report.json
reports/stage03v/full_target_streaming_audit_chunk_summary.csv
reports/stage03v/full_target_streaming_audit_error_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

CSV artifacts must be small audit artifacts:

```text
chunk_summary: aggregate per chunk / entity-block / slice-block only
error_sample: capped at 500 rows by default; empty or header-only if no violations
```

## CLI

Implement:

```bash
python -m src.evaluation.stage03v_full_target_audit \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --output reports/stage03v/full_target_streaming_audit_report.md \
  --summary-json reports/stage03v/full_target_streaming_audit_report.json \
  --chunk-summary reports/stage03v/full_target_streaming_audit_chunk_summary.csv \
  --error-sample reports/stage03v/full_target_streaming_audit_error_sample.csv \
  --chunk-size 250000 \
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

## Full-target audit requirements

Expected from WP1 support:

```text
target_row_count: 7474840
entity_count_after_silent_break_handling: 124
eligible slices: 11
diagnostic-only slices: 9
sample CSV rows committed: 500
persistent DB table written: no
```

Validate and report:

```text
full_target_rows_checked
expected_target_row_count
row_count_delta
entity_count_checked
slice_count_checked
eligible_slice_count_checked
diagnostic_only_slice_count_checked
chunk_count
max_chunk_size
chunking_strategy
memory_safety_status
```

Pass criteria:

```text
full_target_rows_checked == expected_target_row_count
row_count_delta == 0
entity_count_checked == 124
eligible_slice_count_checked == 11
diagnostic_only_slice_count_checked == 9
```

## Full-target invariants

Aggregate violation counts for every streamed chunk:

```text
missing_required_column_count
duplicate_target_key_count
entity_not_in_target_universe_count
silent_break_entity_row_count
invalid_target_usage_count
invalid_slice_count
labeled_without_event_label_count
unlabeled_with_event_label_count
invalid_event_label_type_count
invalid_censoring_status_count
label_window_violation_count
target_observation_start_violation_count
target_observation_end_violation_count
future_window_off_by_one_violation_count
future_return_recompute_violation_count
future_mae_recompute_violation_count
future_mdd_recompute_violation_count
future_realized_vol_recompute_violation_count
future_downside_vol_recompute_violation_count
cross_cutoff_violation_count
historical_development_bad_label_count
prospective_holdout_label_consumed_count
sample_weight_invalid_count
source_db_path_mismatch_count
```

All counts must be zero for pass. If numerical tolerance is needed, report:

```text
float_tolerance
max_abs_future_return_error
max_abs_future_mae_error
max_abs_future_mdd_error
max_abs_future_realized_vol_error
max_abs_future_downside_vol_error
```

Default tolerance: `1e-10` unless implementation documents a safer alternative.

## Cross-cutoff and holdout requirements

Enforce:

```text
For split_role = historical_development and censoring_status = labeled:
  target_observation_end_date <= 2026-06-10

If target_observation_end_date > 2026-06-10:
  censoring_status in {cross_cutoff_censored, excluded}
  event_label is null

Prospective final holdout rows, if present, must not be labeled or scored.
```

Report:

```text
cross_cutoff_rows_seen
cross_cutoff_censored_or_excluded_count
cross_cutoff_labeled_violation_count
prospective_holdout_rows_seen
prospective_holdout_label_consumed_count
```

## Slice support consistency

Aggregate by:

```text
horizon
threshold_type
threshold_value
target_kind
target_usage
```

Compare to WP1 `slice_support_summary` and report per slice:

```text
expected_target_row_count
actual_target_row_count
row_count_delta
expected_labeled_count
actual_labeled_count
labeled_count_delta
expected_positive_event_count
actual_positive_event_count
positive_event_count_delta
expected_insufficient_future_price_count
actual_insufficient_future_price_count
insufficient_future_price_count_delta
slice_status
```

Pass criteria:

```text
all slice_status == pass
all deltas == 0
```

## Purge / embargo input compatibility

Confirm the full target audit outputs are compatible with accepted purge/embargo policy:

```text
max_horizon_days from target rows <= policy.max_horizon_days
all target windows have start/end dates needed for purge logic
all rows have deterministic split_role
all rows have target_usage in {eligible, diagnostic_only}
all rows have entity_segment_id and no unexplained silent-break bridge
```

Report:

```text
purge_embargo_input_compatibility_status
purge_embargo_input_violation_count
max_horizon_observed
max_horizon_policy
```

## Feature / target namespace audit

Report:

```text
target_namespace_columns_present
feature_namespace_forbidden_terms
future_derived_feature_violation_count
feature_target_collision_violation_count
feature_asof_policy_status
```

This is a metadata/column namespace audit, not a model feature audit.

## Missing-V7 negative check

Run a missing-V7 negative check to temporary outputs:

```bash
python -m src.evaluation.stage03v_full_target_audit \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp2_1_missing_v7.md \
  --summary-json tmp/stage03v_wp2_1_missing_v7.json \
  --chunk-summary tmp/stage03v_wp2_1_missing_v7_chunk_summary.csv \
  --error-sample tmp/stage03v_wp2_1_missing_v7_error_sample.csv \
  --no-fetch
```

Expected:

```text
status: blocked_missing_v7_db
no fallback to data/db/a_share_hmm.duckdb
no overwrite of formal reports/configs unless explicitly passed
```

## Required report

Create `reports/stage03v/full_target_streaming_audit_report.json` with at least:

```text
index_id
report_version
status
wp1_support_status
wp2_controls_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
target_universe_status
full_target_rows_checked
expected_target_row_count
row_count_delta
entity_count_checked
expected_entity_count
slice_count_checked
eligible_slice_count_checked
diagnostic_only_slice_count_checked
chunk_count
max_chunk_size
chunking_strategy
memory_safety_status
violation_counts
float_tolerance
max_abs_recompute_errors
slice_support_consistency
cross_cutoff_audit
purge_embargo_input_compatibility_status
purge_embargo_input_violation_count
feature_namespace_policy_status
future_derived_feature_violation_count
feature_target_collision_violation_count
audit_sample_rows
error_sample_rows
ci_gate_status
boundary_flags
```

Boundary flags:

```text
external_data_fetch: no
target_dataset_modified: no
persistent_db_table_written: no
full_target_dataset_committed: no
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
```

## Gate script

Create `scripts/stage03v_full_target_audit_gate.sh`.

Behavior:

```text
Prefer STAGE03V_V7_DB.
Else use data/db/a_share_hmm_tushare_v7.duckdb.
Print actual DB path.
Run compileall and WP2.1-specific tests.
Run full-target audit CLI in no-fetch mode.
Run JSON validation for full audit report.
Print stable marker:
STAGE03V_FULL_TARGET_AUDIT_GATE=<status> db=<path> rows_checked=<n> expected_rows=<n> report=<path> summary_json=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_full_target_audit.py
```

Minimum coverage:

```text
Streaming chunks aggregate to exact full-row count.
Duplicate target keys are detected.
Invalid entity outside target universe is detected.
Invalid slice / target_usage is detected.
Labeled/unlabeled event-label mismatches are detected.
Future-return / MAE / MDD recomputation mismatches are detected.
Cross-cutoff labeled violations are detected.
Appended post-cutoff prices do not backfill historical cross-cutoff censored rows.
Slice support deltas are detected.
Purge/embargo input compatibility detects missing target windows.
Feature/target namespace collisions are detected.
Missing V7 DB returns blocked status and no fallback.
No external fetch occurs.
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_full_target_audit.py
python -m src.evaluation.stage03v_full_target_audit \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --target-controls reports/stage03v/target_controls_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --output reports/stage03v/full_target_streaming_audit_report.md \
  --summary-json reports/stage03v/full_target_streaming_audit_report.json \
  --chunk-summary reports/stage03v/full_target_streaming_audit_chunk_summary.csv \
  --error-sample reports/stage03v/full_target_streaming_audit_error_sample.csv \
  --chunk-size 250000 \
  --no-fetch
bash scripts/stage03v_full_target_audit_gate.sh
python -m json.tool reports/stage03v/full_target_streaming_audit_report.json
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
```

Also run the missing-V7 negative check above.

## Forbidden behavior

Do not fetch external data.

Do not modify target dataset.

Do not write persistent DB tables.

Do not commit full target dataset.

Do not train any model.

Do not calibrate probabilities.

Do not assign readiness or usable_probability.

Do not consume final holdout performance.

Do not modify HMM / HSMM training algorithms.

Do not implement Stage03V2 or Stage03V3.

Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Return format

Use the work package return contract exactly:

```text
index_id: STAGE03V-WP2.1-v1
branch: stage03v/wp2.1-full-target-streaming-audit
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
full target rows checked: ...
expected target rows: ...
row count delta: ...
entity count checked: ...
slice count checked: ...
chunk count: ...
max chunk size: ...
memory safety status: pass/fail
violation count total: ...
recompute violation count total: ...
slice support deltas: ...
cross-cutoff violations: ...
prospective holdout labels consumed: ...
purge/embargo input compatibility: pass/fail
feature namespace policy status: pass/fail
chunk summary rows: ...
error sample rows: ...

external data fetch: no
target dataset modified: no
persistent DB table written: no
full target dataset committed: no
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
