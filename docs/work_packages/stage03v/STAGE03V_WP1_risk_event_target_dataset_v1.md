# STAGE03V_WP1_risk_event_target_dataset_v1

Stage: 03V / Volatility and downside-risk hazard

Work package: WP1

Index id: `STAGE03V-WP1-v1`

Suggested branch: `stage03v/wp1-risk-event-target-dataset-v1`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP1_risk_event_target_dataset_v1.md`

Date: 2026-06-10

## Objective

Build the first formal Stage03V1 downside-risk target dataset builder and prove path-target correctness with synthetic tests.

WP1 converts the accepted WP0/WP0.5 contracts into a reproducible target dataset construction path for SW2021 L2 downside events. It may build local target rows and support artifacts, but it must not train models, calibrate probabilities, assign readiness, consume prospective holdout evidence, or implement Stage03V2 / Stage03V3.

## Required route anchors

Read these first:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
docs/work_packages/stage03v/STAGE03V_WP0.5_sample_feasibility_preflight.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
reports/stage03v/sample_feasibility_report.json
```

## Required input state

WP1 may proceed only if `reports/stage03v/sample_feasibility_report.json` contains:

```text
status: pass
v7_coverage_available: yes
v7_db_requirement_status: pass
sw2021_l2_universe_coverage: pass
universe_source_status: verified_sw2021_l2_tushare_classify or equivalent verified SW2021 L2 source
eligible_slice_count > 0
no_usable_probability_assigned: true
```

The accepted WP0.5 result used:

```text
db_path: data/db/a_share_hmm_tushare_v7.duckdb
coverage_start: 2014-01-02
coverage_end: 2026-06-09
industry_count_after_quality_filter: 124
eligible_slice_count: 11
diagnostic_only_slice_count: 9
```

If these conditions are not met, WP1 must fail with a clear `blocked_wp0_5_not_ready` status.

## Stage boundary

Allowed:

- Read the V7 local DuckDB read-only.
- Read WP0/WP0.5 contracts and sample feasibility report.
- Build Stage03V1 target rows for accepted fixed-threshold slices.
- Emit target support reports and small audit/sample CSVs.
- Optionally write a local target table only behind an explicit local flag; never commit the DB.
- Add deterministic synthetic tests for MAE, MDD, final return, censoring, and off-by-one semantics.
- Add target-builder tests that do not require private DuckDB.

Forbidden:

- Do not fetch external data.
- Do not build or implement Stage03V2 upside-trigger targets.
- Do not build or implement Stage03V3 competing-risk targets.
- Do not train logistic hazard, volatility baseline, HAR diagnostic, calibration, readiness matrix, or validation models.
- Do not assign `usable_probability`, `ordinal_only`, or any model readiness status.
- Do not consume or inspect prospective final holdout performance.
- Do not backfill historical-development labels whose observation window crosses the 2026-06-10 cutoff.
- Do not commit DuckDB, WAL, local cache, or full target dataset extracts.
- Do not modify HMM or HSMM training algorithms.
- Do not create UI, trading, buy/sell, sizing, or decision outputs.

## Required deliverables

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

The sample CSV must be small, deterministic, and audit-oriented. It must not be a full data dump. Cap it by default, for example at 500 or 1000 rows.

## Required CLI

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

- Prefer `STAGE03V_V7_DB` when set.
- Otherwise default to `data/db/a_share_hmm_tushare_v7.duckdb`.
- If the V7 DB is missing or not long-history, emit `blocked_missing_v7_db` or `blocked_invalid_v7_db`.
- Do not silently fall back to `data/db/a_share_hmm.duckdb`.

## Target definitions

For entity `i`, trade date `t`, close price `C_i(t)`, and horizon `N`:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
future_return_i(t, N) = C_i(t+N) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
MDD_i(t, N) = max_{0 <= a < b <= N} (1 - C_i(t+b) / C_i(t+a))
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

Primary event target:

```text
downside_event
```

Diagnostic target values:

```text
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
```

`MFE` is reserved for Stage03V2. It may appear in synthetic helper tests if useful, but it must not become a Stage03V1 output column unless explicitly marked diagnostic-only and not used for Stage03V2 activation.

## Slice policy

Use the accepted WP0.5 feasibility report as source of truth.

Default target rows should include fixed-threshold slices whose WP0.5 `feasibility_verdict` is:

```text
eligible
diagnostic_only
```

Rules:

- `eligible` slices may be used by later modeling packages.
- `diagnostic_only` slices may be emitted for support / analysis but must be marked diagnostic-only.
- `drop_threshold`, `defer_threshold`, `blocked_short_history`, `partial_missing_data`, and unknown verdicts must not be promoted into target-building eligibility.
- Do not recompute slice eligibility differently in WP1.
- Do not assign `usable_probability`.

## Split-role and permanent cross-cutoff censoring

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
  the row must be permanently marked cross_cutoff_censored or excluded from the development dataset.

A cross-cutoff censored row must not be backfilled in historical_development after future prices become available.
```

Default WP1 behavior:

```text
keep cross-cutoff rows with censoring_status = cross_cutoff_censored and event_label = null
```

Fallback behavior:

```text
exclude cross-cutoff rows with exclusion_reason = cross_cutoff_target_window
```

The chosen behavior must be recorded in the report and target-universe manifest.

## Prospective holdout policy

WP1 must not consume prospective final holdout labels.

If the input DB contains rows on or after 2026-06-11, target builder must not use those rows to label historical-development observations that cross the cutoff. The builder may either:

- exclude prospective rows from this WP1 development target artifact; or
- emit prospective rows with `split_role = prospective_final_holdout`, `event_label = null`, and `holdout_label_status = withheld`.

WP1 support metrics and sample-support counts must be based on historical-development rows only unless explicitly labelled as holdout inventory metadata. No performance metric may use holdout rows.

## Universe and quality policy

Use verified SW2021 L2 universe from the V7 DB and WP0.5 report.

Required handling:

- Use only quality-filtered SW2021 L2 entities.
- Persist the final target universe to `configs/stage03v_sw_l2_target_universe_v1.yaml`.
- Record `taxonomy_provider`, `taxonomy_version`, `taxonomy_level`, `source`, and `db_path`.
- Record `industry_count_after_quality_filter`.
- Record all exclusions and reasons.
- Record whether constituent-count filtering was applied.
- Record silent entity break handling.

The accepted WP0.5 report showed:

```text
silent_entity_break_count: 2
quality_filter_exclusion_count: 38
constituent_count_filter_status: partial_low_constituents
```

WP1 must not ignore this. Required behavior:

- Identify and record the two silent-break entities in the support report and target-universe manifest.
- Default to excluding silent-break entities from the v1 target universe unless the implementation proves they are false positives.
- If kept, assign explicit `entity_segment_id` and ensure no target path crosses an entity break.
- No target row may bridge an unexplained entity break.

## Minimum target dataset columns

The local target rows and sample CSV must include:

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

If `sector_name` is unavailable, use null and report it. If `feature_scope_id` is not yet available, use a deterministic Stage03V WP1 scope id and report that it is a target-scope placeholder, not a model feature scope.

## Sample weights

WP1 may create a simple date-aware placeholder weight, but it must not tune model weighting. Default:

```text
sample_weight = 1.0
```

If date-aware row weights are emitted, they must be deterministic and documented. Do not optimize or tune sample weights in WP1.

## Synthetic tests

Create tests for path semantics using small deterministic data frames.

Required cases:

- MAE labels are correct.
- MDD values are correct.
- Final future return is correct.
- Future realized volatility and downside volatility are deterministic.
- Horizon uses `t+1` through `t+N`, not `t`.
- A same-day drop at `t` is not counted in future MAE.
- Last dates without enough future path are censored, not labeled non-events.
- Cross-cutoff rows remain `cross_cutoff_censored` or excluded and are not backfilled when post-cutoff prices are appended.
- Diagnostic-only slices are emitted as diagnostic-only and not promoted.
- Dropped or deferred slices are excluded from target-building eligibility.
- Silent-break handling prevents target windows from crossing entity break gaps.
- Missing V7 DB emits a blocked status and does not fall back to the old DB.
- No external data fetch occurs.

## Required support report contents

`reports/stage03v/risk_event_target_support.json` must include:

```text
index_id
report_version
status
contract_status
feasibility_report_status
source_db_path
db_opened_read_only
v7_coverage_available
sw2021_l2_universe_coverage
benchmark_target_status
entity_count_total
entity_count_after_quality_filter
entity_count_after_silent_break_handling
silent_entity_break_count
silent_entity_break_entities
silent_entity_break_handling
quality_filter_exclusion_count
target_row_count
sample_csv_row_count
split_role_counts
censoring_status_counts
cross_cutoff_censored_count
cross_cutoff_excluded_count
historical_development_labeled_count
historical_development_unlabeled_due_to_cutoff_count
slice_support_summary
eligible_slice_count
diagnostic_only_slice_count
excluded_slice_count
target_definition_version
permanent_censoring_policy
boundary_flags
```

Boundary flags must include:

```text
external_data_fetch: no
target_dataset_built: yes
persistent_db_table_written: yes/no
model_training: no
probability_calibration: no
readiness_assigned: no
holdout_consumed: no
HMM_HSMM_training_modified: no
stage03v2_implemented: no
stage03v3_implemented: no
```

If a local table write option is implemented, the default PR evidence should use `persistent_db_table_written: no` unless explicitly agreed. Do not commit DB files.

## Gate script

Create `scripts/stage03v_risk_target_gate.sh`.

Required behavior:

- Prefer `STAGE03V_V7_DB` if set.
- Else use `data/db/a_share_hmm_tushare_v7.duckdb`.
- Print the actual DB path used.
- Run compileall and WP1-specific tests.
- Run the target builder CLI in no-fetch mode.
- Print a stable marker:

```text
STAGE03V_RISK_TARGET_GATE=<status> db=<path> report=<path> summary_json=<path> no_fetch=yes
```

## Suggested commands

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

Also run a negative check for missing V7 DB:

```bash
python -m src.evaluation.stage03v_risk_target_dataset \
  --db tmp/missing_stage03v_v7.duckdb \
  --output tmp/stage03v_wp1_missing_v7.md \
  --summary-json tmp/stage03v_wp1_missing_v7.json \
  --sample-csv tmp/stage03v_wp1_missing_v7_sample.csv \
  --no-fetch
```

Expected missing-DB result: blocked status, no crash, no fallback to old DB.

## Acceptance criteria

WP1 passes if:

- WP0.5 report status is pass and V7 / SW2021 L2 verification is enforced.
- Target builder uses V7 path and does not fall back to old DB.
- Synthetic MAE, MDD, future return, volatility, off-by-one, censoring, and cross-cutoff tests pass.
- Target rows are generated only for eligible and diagnostic-only fixed-threshold slices from WP0.5.
- Diagnostic-only slices remain marked diagnostic-only.
- No slice is marked `usable_probability`.
- No readiness status is assigned.
- Historical-development rows with target windows crossing 2026-06-10 are censored or excluded and never backfilled.
- Silent-break entities are recorded and either excluded or segmented so no target window crosses a break.
- Support reports exist and are machine-readable.
- Sample CSV is small and does not expose a full data dump.
- Missing V7 DB produces a blocked status and no fallback.
- No model is trained.
- No probability is calibrated.
- No holdout is consumed.
- No external data is fetched.
- No HMM / HSMM training algorithm is modified.
- Stage03V2 and Stage03V3 remain unimplemented.

## Return format

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
