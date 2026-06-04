# STAGE03R_WP3_logistic_hazard_baseline

Stage: 03R / Hazard-first lifecycle validation
Work package: WP3
Index ID: STAGE03R-WP3
Executor: Codex Stage03R-WP3
Recommended branch: `stage03r/wp3-logistic-hazard-baseline`

## Objective

Implement the first lightweight Duration Hazard baseline on top of `exit_target_dataset_v1`.

This package trains a simple per-horizon logistic hazard model under the WP2 leakage/purge discipline. It produces raw hazard scores, fold metrics, sample-support diagnostics, and a baseline report.

This package must not implement isotonic calibration, hazard readiness matrix, hazard-vs-HSMM promotion report, BOCPD, decision engine, robust HMM, sticky HMM, or any HSMM training changes.

## Starting point

Start from updated `main` after PR #41 has merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage03r/wp3-logistic-hazard-baseline
```

Read first:

```text
docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md
docs/roadmap/stage03r_scope_freeze.md
configs/lifecycle_signal_contract_v1.yaml
configs/readiness_policy_lifecycle_v1.yaml
docs/validation/STAGE03R_TARGET_LEAKAGE_POLICY.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
docs/work_packages/stage03r/STAGE03R_WP1_exit_target_dataset_v1.md
docs/work_packages/stage03r/STAGE03R_WP2_target_leakage_purge_tests.md
reports/stage03r/exit_target_dataset_v1_report.json
reports/stage03r/target_leakage_purge_audit.json
```

Use the local V0 DB only if available. No external data fetch.

## Scope

Allowed additions:

```text
src/models/duration_hazard.py
tests/test_duration_hazard_baseline.py
reports/stage03r/duration_hazard_logistic_baseline_report.md
reports/stage03r/duration_hazard_logistic_baseline_report.json
reports/stage03r/duration_hazard_logistic_predictions_sample.csv
```

Allowed focused updates:

```text
src/evaluation/exit_target_dataset.py
src/evaluation/exit_target_leakage_audit.py
docs/indexes/WORK_PACKAGE_INDEX.md
docs/work_packages/stage03r/STAGE03R_EXECUTION_INDEX.md
.gitignore
```

Only update WP1/WP2 modules if reusable helper exports are needed or tests expose a real defect. Do not modify their core semantics.

Do not modify:

```text
src/models/hsmm_model.py
src/models/hsmm_walk_forward.py
src/models/hmm_model.py
src/backtest/
src/ui/
src/scoring/
```

## Model scope

Implement only a simple logistic hazard baseline:

```text
per-horizon binary logistic regression
train on observed labels only
exclude right-censored and unknown rows from supervised labels
use WP2 purged/embargoed split discipline
emit raw hazard score / raw probability only
no isotonic calibration
no readiness matrix
```

Use existing project dependencies only. If scikit-learn is unavailable, implement a small deterministic logistic regression with numpy/scipy or use a simple GLM-like fallback. Do not add a new dependency unless already allowed in `requirements.txt`.

## Required inputs

The model should accept `exit_target_dataset_v1` rows with columns from WP1. Required minimum feature set:

```text
state_label
state_age
duration_percentile
state_phase
horizon_days
```

Optional numeric features if available:

```text
volatility_20d
rs_20d
drawdown_20d
liquidity_feature
breadth_feature
hmm_state_confidence
hmm_state_entropy
hmm_posterior_margin
```

Optional categorical features if available:

```text
market_regime_label
state_source
profile_mode
state_date_policy
```

Missing optional features must not fail training. They must be reported.

## Required target filtering

Training rows must satisfy:

```text
censoring_status in {observed_positive, observed_negative}
exit_within_horizon in {0, 1}
sample_weight > 0
feature_leakage_violation is false
```

Rows with right-censored or unknown status must be excluded from supervised training and counted in diagnostics.

## Required split discipline

Use the WP2 split builder or equivalent behavior:

- no train/validation target window overlap by sector;
- embargo training rows through validation start;
- final holdout policy is recorded but not repeatedly used for tuning;
- train and validation rows are disjoint;
- right-censored rows are excluded from supervised training.

For WP3, use rolling / expanding time folds from available rows. A simple deterministic split is sufficient if it respects purge/embargo.

## Required outputs

Predictions output, at least sample CSV, should include:

```text
target_dataset_id
sector_code
trade_date
state_label
state_age
state_phase
horizon_days
censoring_status
exit_within_horizon
fold_id
split_role
hazard_model_version
hazard_raw_score
hazard_raw_probability
hazard_status
sample_support
fallback_reason
```

Allowed `hazard_status` values for WP3:

```text
raw_probability_only
insufficient_sample
invalid
excluded_censored
```

Do not output `usable_probability` in WP3. That is reserved for calibration/readiness packages.

## Required metrics

Report metrics by fold and by horizon:

```text
train_row_count
validation_row_count
observed_positive_count
observed_negative_count
right_censored_excluded_count
feature_columns_used
missing_feature_columns
brier_raw
log_loss_raw
auc_raw, if both classes exist
positive_rate
prediction_min
prediction_max
prediction_mean
```

Also report support by:

```text
state_label × horizon
age_bucket × horizon
```

If a fold/horizon has only one class or insufficient samples, do not fake metrics. Mark `insufficient_sample`.

## Required CLI

Support CSV dataset input:

```bash
python -m src.models.duration_hazard \
  --dataset reports/stage03r/exit_target_dataset_v1_sample.csv \
  --output reports/stage03r/duration_hazard_logistic_baseline_report.md \
  --summary-json reports/stage03r/duration_hazard_logistic_baseline_report.json \
  --predictions-csv reports/stage03r/duration_hazard_logistic_predictions_sample.csv \
  --no-fetch
```

Support local DB rebuild via WP1 builder:

```bash
python -m src.models.duration_hazard \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/duration_hazard_logistic_baseline_report.md \
  --summary-json reports/stage03r/duration_hazard_logistic_baseline_report.json \
  --predictions-csv reports/stage03r/duration_hazard_logistic_predictions_sample.csv \
  --no-fetch
```

Default behavior must not fetch external data.

## Report requirements

Markdown and JSON reports must include:

```text
status: pass / partial / fail
model_version: duration_hazard_logistic_v1
source: dataset_csv / local_db / synthetic
row_count
trainable_row_count
right_censored_excluded_count
horizons
feature_columns_used
missing_feature_columns
fold_count
fold_metrics
horizon_metrics
state_label_x_horizon_support
age_bucket_x_horizon_support
purge_embargo_used: true/false
feature_leakage_violation_count
hazard_status_counts
usable_probability_count: 0
external_data_fetch: no
training_algorithm_modified: no
DuckDB_committed: no
```

Pass requires:

- no hard leakage/purge/censoring audit violations;
- at least one horizon/fold trainable with both classes;
- predictions generated for validation rows;
- `usable_probability_count == 0`.

A partial status is acceptable if local DB is missing but synthetic tests pass.

## Tests

Add `tests/test_duration_hazard_baseline.py` covering at least:

1. Right-censored rows are excluded from training.
2. Feature leakage rows are excluded or hard-fail before training.
3. Purged split plan prevents overlap between train and validation windows.
4. Logistic baseline can fit a synthetic two-class dataset.
5. Single-class fold/horizon returns `insufficient_sample`, not fake metric.
6. Missing optional feature columns do not fail and are reported.
7. Prediction output includes required hazard fields.
8. WP3 never emits `usable_probability`.
9. CLI writes Markdown, JSON, and predictions CSV.
10. No external fetch is attempted.

Use synthetic fixtures. Unit tests must not require the private V0 DB.

## Required commands

```bash
python -m compileall -q src tests
pytest -q tests/test_exit_target_dataset.py tests/test_exit_target_leakage_purge.py tests/test_duration_hazard_baseline.py
bash scripts/stage03r_exit_target_gate.sh
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
```

If local DB is available, run:

```bash
python -m src.models.duration_hazard \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/stage03r/duration_hazard_logistic_baseline_report.md \
  --summary-json reports/stage03r/duration_hazard_logistic_baseline_report.json \
  --predictions-csv reports/stage03r/duration_hazard_logistic_predictions_sample.csv \
  --no-fetch
```

If feasible:

```bash
bash scripts/stage03_preflight_gate.sh
```

If `python` is unavailable, use `.venv/bin/python` and `.venv/bin/pytest` and document it.

## Acceptance criteria

Pass if:

- logistic hazard baseline exists;
- model trains only on observed labels;
- right-censored rows are excluded from supervised labels;
- split discipline uses purge/embargo;
- validation predictions and raw metrics are generated;
- no calibrated probability or `usable_probability` is emitted;
- reports are generated;
- synthetic tests pass;
- no external data fetch;
- no HMM/HSMM training algorithm changes;
- no DuckDB/WAL commit.

## Return format

```text
WP: STAGE03R-WP3
status: pass / partial / fail
branch: stage03r/wp3-logistic-hazard-baseline
PR: ...
commands run:
- ...
local DB:
- used: yes/no
- path: ...
- preflight: pass/fail/not_run
hazard baseline:
- status: ...
- model_version: duration_hazard_logistic_v1
- row_count: ...
- trainable_row_count: ...
- right_censored_excluded_count: ...
- horizons: ...
- fold_count: ...
- feature_columns_used: ...
- missing_feature_columns: ...
- usable_probability_count: 0/nonzero
- purge_embargo_used: true/false
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```