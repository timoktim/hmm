# STAGE03R_WP2_target_leakage_purge_tests

Stage: 03R / Hazard-first lifecycle validation
Work package: WP2
Index ID: STAGE03R-WP2
Executor: Codex Stage03R-WP2
Recommended branch: `stage03r/wp2-target-leakage-purge-tests`

## Objective

Lock the causal integrity of `exit_target_dataset_v1` before any Duration Hazard training begins.

WP1 created the exit target dataset. WP2 must add explicit leakage, censoring, purge, embargo, and split-discipline tests/gates so later hazard modeling cannot accidentally train on post-trade-date features, right-censored non-labels, overlapping horizons, or repeated final holdout tuning.

This package must not train a hazard model, fit calibration, create a readiness matrix, implement BOCPD, implement a decision engine, or modify model training algorithms.

## Starting point

Start from updated `main` after PR #40 has merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage03r/wp2-target-leakage-purge-tests
```

Read first:

```text
docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
docs/roadmap/stage03r_scope_freeze.md
configs/lifecycle_signal_contract_v1.yaml
configs/readiness_policy_lifecycle_v1.yaml
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
docs/work_packages/stage03r/STAGE03R_WP1_exit_target_dataset_v1.md
reports/stage03r/exit_target_dataset_v1_report.json
```

If report artifacts are not present on `main`, use the PR #40 body as evidence and run the WP1 CLI locally if DB is available.

## Scope

Allowed additions:

```text
src/evaluation/exit_target_leakage_audit.py
tests/test_exit_target_leakage_purge.py
scripts/stage03r_exit_target_gate.sh
reports/stage03r/target_leakage_purge_audit.md
reports/stage03r/target_leakage_purge_audit.json
docs/validation/STAGE03R_TARGET_LEAKAGE_POLICY.md
```

Allowed focused updates:

```text
src/evaluation/exit_target_dataset.py
docs/indexes/WORK_PACKAGE_INDEX.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
.gitignore
```

Only update `exit_target_dataset.py` if the audit needs exported helpers or if tests expose a real WP1 bug. Do not broaden scope.

Do not modify:

```text
src/models/
src/backtest/
src/ui/
src/scoring/
```

Do not train models.

## Required audit functions

Create an audit module with functions equivalent to:

```python
audit_exit_target_dataset(dataset: pd.DataFrame, *, strict: bool = True) -> ExitTargetAuditResult
validate_no_feature_leakage(dataset: pd.DataFrame) -> list[Violation]
validate_censoring_semantics(dataset: pd.DataFrame) -> list[Violation]
validate_purge_embargo_metadata(dataset: pd.DataFrame) -> list[Violation]
detect_overlapping_target_windows(dataset: pd.DataFrame) -> pd.DataFrame
build_purged_time_split_plan(dataset: pd.DataFrame, *, n_splits: int = 3, final_holdout_start: str | None = None) -> SplitPlan
validate_split_plan(dataset: pd.DataFrame, split_plan: SplitPlan) -> list[Violation]
```

Names may differ, but behavior must be covered.

## Required invariants

### Feature leakage

Fail if any row violates:

```text
max_feature_date_used <= trade_date
feature_cutoff_date <= trade_date
```

If either metadata field is missing, the audit must record `metadata_missing` and downgrade status to `partial` unless synthetic tests prove the field is optional for a specific source.

### Label semantics

Fail if:

```text
observed_positive has exit_within_horizon != 1
observed_negative has exit_within_horizon != 0
right_censored_by_run_end has non-null exit_within_horizon
right_censored_by_cutoff has non-null exit_within_horizon
unknown_* has non-null exit_within_horizon
observed_positive realized_exit_date > target_observation_end_date
observed_negative target_observation_end_date < trade_date
right-censored row sample_weight > 0
```

Right-censored rows must not be used as negatives.

### Purge / embargo metadata

Fail if:

```text
purge_group_id is missing
embargo_until_date is missing for observed rows
embargo_until_date < target_observation_end_date when target_observation_end_date is present
```

### Overlapping target windows

Implement detection for overlapping target windows by sector and date:

```text
window = [trade_date, target_observation_end_date]
rows overlap if same sector_code and windows intersect
```

This does not mean overlapping rows are invalid in the dataset. It means train/validation splits must purge them.

### Split discipline

Create a synthetic split-plan utility or policy validator that enforces:

- training rows must not overlap validation rows by target window;
- training rows with `embargo_until_date >= validation_start_date` must be excluded;
- final holdout may be defined once and marked `final_holdout_locked=true`;
- no split plan may put the same sector/date/horizon row in both train and validation;
- right-censored rows are excluded from supervised training labels unless a later package explicitly models censoring.

This package need not define the final real held-out dates, but it must define the policy and synthetic validator.

## Required CLI

Add CLI:

```bash
python -m src.evaluation.exit_target_leakage_audit \
  --dataset reports/stage03r/exit_target_dataset_v1_sample.csv \
  --output reports/stage03r/target_leakage_purge_audit.md \
  --summary-json reports/stage03r/target_leakage_purge_audit.json \
  --strict
```

If a full dataset CSV is not committed, the CLI should also support rebuilding from local DB using WP1 builder:

```bash
python -m src.evaluation.exit_target_leakage_audit \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/target_leakage_purge_audit.md \
  --summary-json reports/stage03r/target_leakage_purge_audit.json \
  --strict \
  --no-fetch
```

Default behavior must not fetch external data.

## Gate script

Create:

```text
scripts/stage03r_exit_target_gate.sh
```

It should run:

```bash
python -m compileall -q src tests
pytest -q tests/test_exit_target_dataset.py tests/test_exit_target_leakage_purge.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If local DB and WP1 sample/report are available, it may also run the audit CLI. The script must not require private DB in CI.

## Report requirements

Markdown and JSON audit reports must include:

```text
status: pass / partial / fail
row_count
feature_leakage_violation_count
censoring_violation_count
purge_embargo_violation_count
overlapping_window_pair_count
right_censored_training_exclusion_policy: true/false
final_holdout_policy_present: true/false
metadata_missing_count
strict
source: dataset_csv / local_db / synthetic
external_data_fetch: no
training_algorithm_modified: no
DuckDB_committed: no
```

Pass requires zero hard violations in strict mode.

## Tests

Add `tests/test_exit_target_leakage_purge.py` covering at least:

1. Feature date after trade date fails audit.
2. Observed positive with `realized_exit_date > target_observation_end_date` fails audit.
3. Observed negative with target horizon not fully observable fails audit.
4. Right-censored row with `exit_within_horizon=0` fails audit.
5. Right-censored row with positive `sample_weight` fails audit.
6. Missing `purge_group_id` fails audit.
7. `embargo_until_date < target_observation_end_date` fails audit.
8. Overlapping target windows are detected by sector.
9. Purged split plan excludes overlapping train rows from validation windows.
10. Embargo excludes train rows through validation start.
11. Final holdout policy is marked locked and cannot be used for repeated tuning in split metadata.
12. CLI writes Markdown and JSON.
13. No external fetch is attempted.

Use synthetic fixtures. Do not require private DB for unit tests.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_exit_target_dataset.py tests/test_exit_target_leakage_purge.py
bash scripts/stage03r_exit_target_gate.sh
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If local DB is available, also run:

```bash
python -m src.evaluation.exit_target_leakage_audit \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/target_leakage_purge_audit.md \
  --summary-json reports/stage03r/target_leakage_purge_audit.json \
  --strict \
  --no-fetch
```

If feasible:

```bash
bash scripts/stage03_preflight_gate.sh
```

If `python` is unavailable, use `.venv/bin/python` and `.venv/bin/pytest` and document it.

## Acceptance criteria

Pass if:

- audit module exists;
- synthetic leakage/censoring/purge/embargo tests pass;
- right-censored samples are not trainable negatives;
- split-plan utility prevents overlap and embargo violations;
- final-holdout discipline is encoded as metadata/policy;
- report is generated;
- no external data fetch;
- no training algorithm changes;
- no DuckDB/WAL commit.

## Return format

```text
WP: STAGE03R-WP2
status: pass / partial / fail
branch: stage03r/wp2-target-leakage-purge-tests
PR: ...
commands run:
- ...
local DB:
- used: yes/no
- path: ...
- preflight: pass/fail/not_run
audit:
- status: ...
- row_count: ...
- feature_leakage_violation_count: ...
- censoring_violation_count: ...
- purge_embargo_violation_count: ...
- overlapping_window_pair_count: ...
- right_censored_training_exclusion_policy: true/false
- final_holdout_policy_present: true/false
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```