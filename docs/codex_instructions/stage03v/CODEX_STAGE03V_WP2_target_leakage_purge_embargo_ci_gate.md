# CODEX_STAGE03V_WP2_target_leakage_purge_embargo_ci_gate

Repository: timoktim/hmm

Index id: `STAGE03V-WP2-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md`

Suggested branch: `stage03v/wp2-target-leakage-purge-embargo-ci-gate`

## Instruction

Start from updated `main`. Confirm PR77 / Stage03V WP1 has been merged and that `reports/stage03v/risk_event_target_support.json` is present with `status=pass`. Create the suggested branch and execute only `STAGE03V-WP2-v1`.

This package creates the Stage03V target-control gate. It validates target label/window semantics, permanent cross-cutoff censoring, purge/embargo fold planning, and feature/target namespace leakage policy before any baseline or model package is opened.

Do not train models. Do not calibrate probabilities. Do not assign readiness. Do not consume holdout performance. Do not implement Stage03V2 or Stage03V3.

## Read first

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP2_target_leakage_purge_embargo_ci_gate.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
configs/stage03v_sw_l2_target_universe_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
reports/stage03v/risk_event_target_support.json
```

## Required precondition

Proceed only if WP1 support artifacts satisfy:

```text
reports/stage03v/risk_event_target_support.json status: pass
source_db_path: data/db/a_share_hmm_tushare_v7.duckdb or explicit STAGE03V_V7_DB
v7_coverage_available: yes
sw2021_l2_universe_coverage: pass
entity_count_after_silent_break_handling: 124
silent_entity_break_handling: excluded or segmented
cross-cutoff censoring enforced: yes
persistent_db_table_written: no unless explicitly requested
target_dataset_built: yes
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
stage03v2_implemented: no
stage03v3_implemented: no
```

If not, emit `blocked_wp1_not_ready` and stop.

## Required files

Create:

```text
src/evaluation/stage03v_target_controls.py
scripts/stage03v_target_controls_gate.sh
tests/test_stage03v_target_controls.py
tests/test_stage03v_purge_embargo.py
configs/stage03v_purge_embargo_policy_v1.yaml
reports/stage03v/target_controls_report.md
reports/stage03v/target_controls_report.json
reports/stage03v/purge_embargo_fold_plan.json
reports/stage03v/target_controls_audit_sample.csv
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

## CLI

Implement:

```bash
python -m src.evaluation.stage03v_target_controls \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --feasibility reports/stage03v/sample_feasibility_report.json \
  --policy configs/stage03v_purge_embargo_policy_v1.yaml \
  --output reports/stage03v/target_controls_report.md \
  --summary-json reports/stage03v/target_controls_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --audit-sample reports/stage03v/target_controls_audit_sample.csv \
  --no-fetch
```

DB behavior:

```text
Prefer STAGE03V_V7_DB if set.
Otherwise default to data/db/a_share_hmm_tushare_v7.duckdb.
If V7 DB is missing or invalid, emit blocked_missing_v7_db / blocked_invalid_v7_db.
Never fall back to data/db/a_share_hmm.duckdb.
CI unit tests must not require private DuckDB.
```

## Target-control invariants

Validate target row or synthetic equivalents:

```text
trade_date <= target_observation_end_date when end date is present
target_observation_start_date = next available trading date after trade_date
target_observation_end_date = t + horizon trading days for labeled rows
future_return uses C(t+horizon) / C(t) - 1
future_mae uses min over t+1 through t+N only
future_mdd uses future window t through t+N but must not include any pre-t prices
same-day move at t does not affect future_mae
event_label is null unless censoring_status = labeled
event_label is boolean only when labeled
censoring_status in {labeled, insufficient_future_prices, cross_cutoff_censored, excluded}
exclusion_reason is populated for excluded rows
sample_weight is finite and positive for usable rows
```

## Cross-cutoff hard regression

Information cutoff is `2026-06-10`.

Implement a synthetic regression:

```text
Build a tiny dataset ending at 2026-06-10.
Rows whose target windows cross the cutoff become cross_cutoff_censored or excluded.
Append post-cutoff prices that would make labels computable.
Rebuild with the same information_cutoff_date.
Assert the same historical-development rows remain censored/excluded and are not backfilled.
```

This is a hard acceptance gate.

## Purge and embargo policy

Create:

```text
configs/stage03v_purge_embargo_policy_v1.yaml
```

Required fields:

```text
index_id: STAGE03V-WP2-v1
policy_version: stage03v_purge_embargo_policy_v1
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
max_horizon_days: 20
purge_rule: remove any training row whose target observation interval overlaps a validation/test interval
embargo_rule: remove training rows whose trade_date falls within embargo_days after a validation/test interval
embargo_days: 20 trading days by default
fold_plan_source: historical_development_only
final_holdout_policy: withheld_not_scored
```

Default fold plan:

```text
Use historical-development rows only.
Use deterministic time-ordered folds.
Do not include final prospective holdout rows in fold metrics.
Use accepted WP1 eligible and diagnostic-only slices only.
Mark fold rows as train / validation / purged / embargoed / excluded.
Do not train a model.
```

For every fold:

```text
No train row target window may overlap validation/test target windows.
No train row trade_date may fall inside embargo window after validation/test period.
No validation/test row may be drawn from prospective final holdout.
All purged/embargoed rows must record reason.
```

## Feature / target namespace leakage policy

Forbidden in model feature namespace:

```text
event_label
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
target_observation_start_date
target_observation_end_date
censoring_status
exclusion_reason
holdout_label_status
any column prefixed with future_
any column prefixed with target_
any field derived from post-trade-date prices except labels in target namespace
```

Report:

```text
feature_namespace_forbidden_terms
target_namespace_columns
feature_asof_required: yes
feature_asof_max_date_policy: feature_asof_date <= trade_date
future_derived_feature_violation_count
feature_target_collision_violation_count
```

Since WP2 does not build feature matrices, use synthetic collision tests and report policy constraints.

## Support report

Create `reports/stage03v/target_controls_report.json` with at least:

```text
index_id
report_version
status
contract_status
wp1_support_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
entity_count_after_silent_break_handling
target_row_count_checked
sample_row_count_checked
label_window_violation_count
future_window_off_by_one_violation_count
mdd_window_violation_count
cross_cutoff_violation_count
cross_cutoff_regression_passed
cross_cutoff_censored_or_excluded_count
historical_development_bad_label_count
prospective_holdout_label_consumed_count
purge_policy_status
embargo_policy_status
fold_count
purge_violation_count
embargo_violation_count
feature_namespace_policy_status
future_derived_feature_violation_count
feature_target_collision_violation_count
ci_gate_status
boundary_flags
```

Boundary flags:

```text
external_data_fetch: no
target_dataset_modified: no
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
```

## Gate script

Create `scripts/stage03v_target_controls_gate.sh`.

Behavior:

```text
Prefer STAGE03V_V7_DB.
Else use data/db/a_share_hmm_tushare_v7.duckdb.
Print actual DB path.
Run compileall and WP2-specific tests.
Run target-control CLI in no-fetch mode.
Run JSON validation for report, fold plan, and policy.
Print stable marker:
STAGE03V_TARGET_CONTROLS_GATE=<status> db=<path> report=<path> summary_json=<path> fold_plan=<path> no_fetch=yes
```

## Tests

Create:

```text
tests/test_stage03v_target_controls.py
tests/test_stage03v_purge_embargo.py
```

Minimum coverage:

```text
Target windows use t+1 through t+N for MAE.
Same-day price movement is not included in future MAE.
MDD window semantics are deterministic.
Labeled historical-development rows never have target observation end after 2026-06-10.
Cross-cutoff censored rows remain censored when post-cutoff prices are appended.
Prospective final holdout rows are withheld and not scored.
Missing V7 DB returns blocked status and no fallback to old DB.
Silent-break entities remain excluded or segmented.
Purge removes training rows whose target interval overlaps validation/test interval.
Embargo removes training rows within embargo window after validation/test interval.
Fold plan boundaries are deterministic.
Target namespace columns cannot appear in feature namespace.
Any future_ / target_ feature collision is detected.
No external data fetch occurs.
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_target_controls.py tests/test_stage03v_purge_embargo.py
python -m src.evaluation.stage03v_target_controls \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --target-support reports/stage03v/risk_event_target_support.json \
  --target-universe configs/stage03v_sw_l2_target_universe_v1.yaml \
  --feasibility reports/stage03v/sample_feasibility_report.json \
  --policy configs/stage03v_purge_embargo_policy_v1.yaml \
  --output reports/stage03v/target_controls_report.md \
  --summary-json reports/stage03v/target_controls_report.json \
  --fold-plan reports/stage03v/purge_embargo_fold_plan.json \
  --audit-sample reports/stage03v/target_controls_audit_sample.csv \
  --no-fetch
bash scripts/stage03v_target_controls_gate.sh
python -m json.tool reports/stage03v/target_controls_report.json
python -m json.tool reports/stage03v/purge_embargo_fold_plan.json
python -m json.tool configs/stage03v_purge_embargo_policy_v1.yaml
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
```

Also run missing-V7 negative check to temporary outputs:

```bash
python -m src.evaluation.stage03v_target_controls \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp2_missing_v7.md \
  --summary-json tmp/stage03v_wp2_missing_v7.json \
  --fold-plan tmp/stage03v_wp2_missing_v7_fold_plan.json \
  --audit-sample tmp/stage03v_wp2_missing_v7_sample.csv \
  --no-fetch
```

Expected: blocked status, no crash, no fallback to old DB, no overwrite of formal outputs unless explicitly passed.

## Forbidden behavior

Do not fetch external data.

Do not train any model.

Do not calibrate probabilities.

Do not assign readiness or usable_probability.

Do not consume final holdout performance.

Do not backfill cross-cutoff historical-development labels.

Do not commit DuckDB, WAL, local cache, or full target extracts.

Do not modify HMM / HSMM training algorithms.

Do not implement Stage03V2 or Stage03V3.

Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Return format

Use the work package return contract exactly:

```text
index_id: STAGE03V-WP2-v1
branch: stage03v/wp2-target-leakage-purge-embargo-ci-gate
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
target row count checked: ...
label window violations: ...
cross-cutoff regression passed: yes/no
cross-cutoff violations: ...
historical bad label count: ...
prospective holdout label consumed count: ...
fold count: ...
purge violations: ...
embargo violations: ...
feature namespace policy status: pass/fail
future-derived feature violations: ...
feature-target collision violations: ...
audit sample rows: ...

external data fetch: no
target dataset modified: no
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
