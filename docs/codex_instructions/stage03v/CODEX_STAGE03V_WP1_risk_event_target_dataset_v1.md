# CODEX_STAGE03V_WP1_risk_event_target_dataset_v1

Repository: timoktim/hmm

Index id: `STAGE03V-WP1-v1`

Work package: `docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md`

Suggested branch: `stage03v/wp1-risk-event-target-dataset-v1`

## Instruction

Start from updated `main`. Confirm PR76 / Stage03V WP0.5 has been merged and that `reports/stage03v/sample_feasibility_report.json` is the V7 rerun report with `status=pass`. Create the suggested branch and execute only `STAGE03V-WP1-v1`.

This package builds the first formal Stage03V1 downside-risk target dataset builder and synthetic path-target tests. Do not train models. Do not calibrate probabilities. Do not assign readiness. Do not consume holdout performance. Do not implement Stage03V2 or Stage03V3.

## Read first

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP1_risk_event_target_dataset_v1.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
```

## Required precondition

WP1 may proceed only if `reports/stage03v/sample_feasibility_report.json` contains:

```text
status: pass
v7_coverage_available: yes
v7_db_requirement_status: pass
sw2021_l2_universe_coverage: pass
universe_source_status: verified_sw2021_l2_tushare_classify or equivalent verified source
eligible_slice_count > 0
no_usable_probability_assigned: true
```

The accepted WP0.5 report used:

```text
db_path: data/db/a_share_hmm_tushare_v7.duckdb
coverage_start: 2014-01-02
coverage_end: 2026-06-09
industry_count_after_quality_filter: 124
eligible_slice_count: 11
diagnostic_only_slice_count: 9
silent_entity_break_count: 2
quality_filter_exclusion_count: 38
```

If these conditions are not met, emit `blocked_wp0_5_not_ready` and stop.

## Required files

Create:

```text
src/evaluation/stage03v_risk_target_dataset.py
scripts/stage03v_risk_target_gate.sh
tests/test_stage03v_risk_target_dataset.py
tests/test_stage03v_path_targets.py
reports/stage03v/risk_event_target_support.md
reports/stage03v/risk_event_target_support.json
reports/stage03v/risk_event_target_dataset_sample.csv
configs/stage03v_sw_l2_target_universe_v1.yaml
```

Update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
```

## CLI

Implement:

```bash
python -m src.evaluation.stage03v_risk_target_dataset \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --feasibility reports/stage03v/sample_feasibility_report.json \
  --output reports/stage03v/risk_event_target_support.md \
  --summary-json reports/stage03v/risk_event_target_support.json \
  --sample-csv reports/stage03v/risk_event_target_dataset_sample.csv \
  --no-fetch
```

DB path behavior:

```text
Prefer STAGE03V_V7_DB when set.
Otherwise default to data/db/a_share_hmm_tushare_v7.duckdb.
If V7 DB is missing or invalid, emit blocked_missing_v7_db / blocked_invalid_v7_db.
Never fall back to data/db/a_share_hmm.duckdb.
```

## Target definitions

Use:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
future_return_i(t, N) = C_i(t+N) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
MDD_i(t, N) = max_{0 <= a < b <= N} (1 - C_i(t+b) / C_i(t+a))
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

Primary target kind: `downside_event`.

Diagnostic values:

```text
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
```

`MFE` is reserved for Stage03V2. Do not activate Stage03V2.

## Slice policy

Use `reports/stage03v/sample_feasibility_report.json` as the source of truth.

Emit fixed-threshold rows for slices with WP0.5 `feasibility_verdict` in:

```text
eligible
diagnostic_only
```

Rules:

```text
eligible slices: target rows may be used by later modeling packages.
diagnostic_only slices: emit only as diagnostic, not promoted.
drop/defer/blocked/partial slices: exclude from target-building eligibility.
Do not recompute eligibility in WP1.
Do not assign usable_probability.
```

## Split role and censoring

Locked dates:

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
historical_development: trade_date <= 2026-06-10
prospective_final_holdout: trade_date >= 2026-06-11
```

Hard invariant:

```text
For split_role = historical_development:
  target_observation_end_date must be <= information_cutoff_date.

If target_observation_end_date > information_cutoff_date:
  row must be cross_cutoff_censored or excluded.

Cross-cutoff historical-development rows must never be backfilled after future prices become available.
```

Default behavior: keep cross-cutoff rows with `censoring_status = cross_cutoff_censored` and `event_label = null`.

WP1 must not consume prospective final holdout labels. If prospective rows are emitted, they must have `event_label = null` and `holdout_label_status = withheld`.

## Universe and silent-break handling

Use verified SW2021 L2 universe from the V7 DB and WP0.5 report.

WP0.5 reported:

```text
silent_entity_break_count: 2
quality_filter_exclusion_count: 38
constituent_count_filter_status: partial_low_constituents
```

WP1 must:

```text
identify the two silent-break entities;
record them in support report and target-universe manifest;
default to excluding them unless proven false positive;
if kept, assign explicit entity_segment_id;
ensure no target window crosses an unexplained entity break.
```

Persist final target universe to:

```text
configs/stage03v_sw_l2_target_universe_v1.yaml
```

## Minimum target columns

Target rows and sample CSV must include:

```text
trade_date
entity_type
entity_id
sector_code
sector_name
taxonomy_provider
taxonomy_version
taxonomy_level
feature_scope_id
universe_id
entity_segment_id
split_role
horizon
threshold_type
threshold_value
target_kind
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
event_label
target_observation_end_date
censoring_status
exclusion_reason
sample_weight
target_definition_version
source_db_path
created_at
```

Sample CSV must be capped and audit-oriented, not a full dump.

## Tests

Create/modify:

```text
tests/test_stage03v_path_targets.py
tests/test_stage03v_risk_target_dataset.py
```

Minimum coverage:

```text
MAE labels are correct.
MDD values are correct.
Future return is correct.
Future realized/downside volatility is deterministic.
Horizon uses t+1 through t+N, not t.
A same-day drop at t is not counted in future MAE.
Last rows without enough future path are censored, not labeled non-events.
Cross-cutoff rows remain censored/excluded and are not backfilled after post-cutoff prices are appended.
Diagnostic-only slices remain diagnostic-only.
Dropped/deferred slices are excluded.
Silent-break handling prevents target windows from crossing entity breaks.
Missing V7 DB emits blocked status and does not fall back to old DB.
No external fetch occurs.
```

## Gate script

Create `scripts/stage03v_risk_target_gate.sh`.

Behavior:

```text
Prefer STAGE03V_V7_DB.
Else use data/db/a_share_hmm_tushare_v7.duckdb.
Print actual DB path.
Run compileall and WP1-specific tests.
Run target builder CLI in no-fetch mode.
Print stable marker:
STAGE03V_RISK_TARGET_GATE=<status> db=<path> report=<path> summary_json=<path> no_fetch=yes
```

## Required commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_path_targets.py tests/test_stage03v_risk_target_dataset.py
python -m src.evaluation.stage03v_risk_target_dataset \
  --db data/db/a_share_hmm_tushare_v7.duckdb \
  --feasibility reports/stage03v/sample_feasibility_report.json \
  --output reports/stage03v/risk_event_target_support.md \
  --summary-json reports/stage03v/risk_event_target_support.json \
  --sample-csv reports/stage03v/risk_event_target_dataset_sample.csv \
  --no-fetch
bash scripts/stage03v_risk_target_gate.sh
python -m json.tool reports/stage03v/risk_event_target_support.json
pytest -q -m "not slow"
bash scripts/check_no_private_paths.sh
git diff --check
```

Also run a missing-V7 negative check:

```bash
python -m src.evaluation.stage03v_risk_target_dataset \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp1_missing_v7.md \
  --summary-json tmp/stage03v_wp1_missing_v7.json \
  --sample-csv tmp/stage03v_wp1_missing_v7_sample.csv \
  --no-fetch
```

Expected: blocked status, no crash, no fallback to old DB.

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
index_id: STAGE03V-WP1-v1
branch: stage03v/wp1-risk-event-target-dataset-v1
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
WP0.5 feasibility report status: pass/other
eligible slices used: ...
diagnostic-only slices emitted: ...
dropped/deferred slices excluded: yes/no
entity_count_after_quality_filter: ...
entity_count_after_silent_break_handling: ...
silent_entity_break_count: ...
silent entity break handling: excluded/segmented/other
cross-cutoff censoring enforced: yes/no
historical target rows: ...
cross-cutoff censored rows: ...
sample CSV rows: ...
persistent DB table written: yes/no

external data fetch: no
target dataset built: yes
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
