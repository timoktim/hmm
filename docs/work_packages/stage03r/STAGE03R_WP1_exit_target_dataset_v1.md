# STAGE03R_WP1_exit_target_dataset_v1

Stage: 03R / Hazard-first lifecycle validation
Work package: WP1
Index ID: STAGE03R-WP1
Executor: Codex Stage03R-WP1
Recommended branch: `stage03r/wp1-exit-target-dataset-v1`

## Objective

Build the first causal, auditable, reproducible exit target dataset for the future Duration Hazard model.

This package creates the dataset contract and a data builder. It must not train a hazard model, calibrate probabilities, implement isotonic calibration, build a readiness matrix, implement BOCPD, or create a decision engine.

The output is a target dataset and sample-support report that later packages can use for leakage tests, logistic hazard baseline, age-bucket baseline, calibration, and readiness matrix.

## Starting point

Start from updated `main` after STAGE03R-WP0 has merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage03r/wp1-exit-target-dataset-v1
```

Read first:

```text
docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
docs/roadmap/stage03r_scope_freeze.md
configs/lifecycle_signal_contract_v1.yaml
configs/readiness_policy_lifecycle_v1.yaml
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
docs/runtime/LOCAL_DB_HANDOFF.md
```

Use local V0 DB only if available. No external data fetch.

## Scope

Allowed additions:

```text
src/evaluation/exit_target_dataset.py
tests/test_exit_target_dataset.py
reports/stage03r/exit_target_dataset_v1_report.md
reports/stage03r/exit_target_dataset_v1_report.json
```

Allowed small updates:

```text
src/data_pipeline/storage.py
docs/indexes/WORK_PACKAGE_INDEX.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
.gitignore
```

Storage changes should be limited to idempotent schema support for optional target dataset tables. Do not broadly modify existing model or UI code.

Do not modify:

```text
src/models/
src/backtest/
src/ui/
```

Do not train models.

## Dataset purpose

Create `exit_target_dataset_v1`, suitable for later discrete-time duration hazard modeling.

Each row represents a sector/date/state observation and a horizon-specific target. One sector-date may produce multiple rows, one per horizon.

## Required output fields

The dataset must include at least:

```text
target_dataset_id
run_id
source_run_id
sector_code
sector_id
trade_date
state_source
state_label
state_id
state_age
state_phase
duration_percentile
duration_percentile_status
duration_tail_status
horizon_days
exit_within_horizon
next_state_label_realized
target_observation_end_date
realized_exit_date
censoring_status
sample_weight
target_definition_version
profile_mode
profile_cutoff_date
state_date_policy
feature_cutoff_date
max_feature_date_used
feature_leakage_violation
purge_group_id
embargo_until_date
created_at
```

Recommended feature columns if available:

```text
hmm_state_label
hmm_state_confidence
hmm_state_entropy
hmm_posterior_margin
volatility_20d
rs_20d
drawdown_20d
breadth_feature
liquidity_feature
market_regime_label
```

Do not fail solely because optional features are missing. Record missing feature coverage in the report.

## Target semantics

For each row and horizon `h`:

```text
horizon_end_date = trade_date + h trading days
exit_within_horizon = 1 only if realized_exit_date is known and realized_exit_date <= horizon_end_date
exit_within_horizon = 0 only if the full horizon is observable and no exit occurs inside horizon
exit_within_horizon = null if horizon is right-censored or unknown
```

Required `censoring_status` values:

```text
observed_positive
observed_negative
right_censored_by_run_end
right_censored_by_cutoff
unknown_due_to_missing_state_sequence
unknown_due_to_missing_calendar
```

Right-censored samples must not be treated as non-exit.

## Source tables

Use whichever current tables are available, but prefer causal and lifecycle tables:

```text
hsmm_lifecycle_ui_daily
hsmm_display_label_episodes
hsmm_lifecycle_profile_metadata
sector_state_daily
walk_forward_state_cache
model_evidence_registry
validation_runs
```

The builder must be robust to missing optional tables. Missing required tables should return `partial_missing_source` rather than fake pass.

## Causal rules

1. `max_feature_date_used <= trade_date` whenever feature date metadata is available.
2. `feature_cutoff_date <= trade_date` whenever feature cutoff metadata is available.
3. `target_observation_end_date > trade_date` is allowed because it is target label construction, not feature construction.
4. `profile_cutoff_date` must be respected: targets after cutoff are censored, not observed.
5. Do not mix in-sample state sources into causal target datasets unless the output is explicitly marked research-only. Default dataset should prefer causal or lifecycle-asof state sources.
6. The dataset must record `target_definition_version='exit_target_dataset_v1'`.

## Purge and embargo contract

This package does not implement train/validation splits, but it must compute metadata that later packages can use:

```text
purge_group_id
embargo_until_date = target_observation_end_date
```

The report must explain that any later model training split must purge overlapping horizons and embargo rows through `embargo_until_date`.

## CLI

Required CLI:

```bash
python -m src.evaluation.exit_target_dataset \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/exit_target_dataset_v1_report.md \
  --summary-json reports/stage03r/exit_target_dataset_v1_report.json \
  --dataset-csv reports/stage03r/exit_target_dataset_v1_sample.csv \
  --no-fetch
```

The CSV may be a sample if the full dataset is large. The summary JSON must include row counts and sample-support statistics.

Default behavior must not fetch external data.

## Report requirements

Markdown and JSON reports must include:

```text
status: pass / partial / fail
run_id
source_tables_used
row_count
sector_count
trade_date_min
trade_date_max
horizons
censoring_status_counts
state_label_counts
state_label_x_horizon_support
age_bucket_x_horizon_support
missing_feature_columns
feature_leakage_violation_count
right_censored_count
observed_positive_count
observed_negative_count
target_definition_version
purge_embargo_policy_present: true/false
external_data_fetch: no
training_algorithm_modified: no
DuckDB_committed: no
```

Expected status can be `partial` if the local DB lacks a complete lifecycle table. That is acceptable only if the report is explicit and synthetic tests pass.

## Tests

Add `tests/test_exit_target_dataset.py` covering:

1. Simple sequence with exit inside horizon produces `observed_positive`.
2. Simple sequence with full horizon and no exit produces `observed_negative`.
3. Horizon extending beyond run end produces `right_censored_by_run_end` and `exit_within_horizon = null`.
4. Profile cutoff before horizon end produces `right_censored_by_cutoff`.
5. Right-censored rows are not counted as negative.
6. Feature date after trade_date sets `feature_leakage_violation=true`.
7. Missing optional feature columns do not fail dataset creation but are reported.
8. Purge/embargo metadata exists and `embargo_until_date >= target_observation_end_date`.
9. CLI writes Markdown and JSON.
10. No external fetch is attempted.

Use synthetic in-memory or temp DuckDB fixtures. Do not require the private V0 DB for unit tests.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_exit_target_dataset.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If local DB is available, run the CLI:

```bash
python -m src.evaluation.exit_target_dataset \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/exit_target_dataset_v1_report.md \
  --summary-json reports/stage03r/exit_target_dataset_v1_report.json \
  --dataset-csv reports/stage03r/exit_target_dataset_v1_sample.csv \
  --no-fetch
```

If feasible after changes:

```bash
bash scripts/stage03_preflight_gate.sh
```

If `python` is unavailable, use `.venv/bin/python` and `.venv/bin/pytest` and document it.

## Acceptance criteria

Pass if:

- target dataset builder exists;
- dataset contract includes causal, censoring, purge, and embargo metadata;
- right-censored samples are not converted to negatives;
- target labels do not leak into features;
- reports are generated;
- synthetic tests pass;
- no external data fetch;
- no training algorithm changes;
- no DuckDB/WAL commit.

## Return format

```text
WP: STAGE03R-WP1
status: pass / partial / fail
branch: stage03r/wp1-exit-target-dataset-v1
PR: ...
commands run:
- ...
local DB:
- used: yes/no
- path: ...
- preflight: pass/fail/not_run
dataset:
- status: ...
- row_count: ...
- sector_count: ...
- horizons: ...
- observed_positive_count: ...
- observed_negative_count: ...
- right_censored_count: ...
- feature_leakage_violation_count: ...
- purge_embargo_policy_present: true/false
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```