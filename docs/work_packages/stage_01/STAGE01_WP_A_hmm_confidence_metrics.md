# STAGE01_WP_A_hmm_confidence_metrics

Stage: 01 / HMM baseline strengthening  
Work package: WP-A  
Index id: STAGE01-WP-A-v1  
Suggested branch: `stage01/wp-a-hmm-confidence`  
Codex thread: A  
Date: 2026-06-01

## Objective

Build a conservative HMM state confidence layer on top of the existing causal HMM outputs. This package must quantify whether each HMM state assignment is clear or ambiguous, without changing HMM/HSMM training algorithms and without promoting HMM posterior probabilities into return, rising, falling, or profit probabilities.

The primary outputs are daily confidence metrics, run-level confidence summaries, and a report that can be consumed by later UI/readiness work.

## Stage boundary

This work package belongs to Stage 01 only. It may compute and store HMM confidence metrics from existing local data. It must not implement WP-B label alignment or WP-C churn/dwell UI degradation. It must not implement Robust HMM, Sticky HMM, Student-t emissions, HSMM repair, duration hazard, change point, or decision engine.

## Inputs

Use the current repository `main` branch, after Stage 00 has been closed.

Default DB path:

```text
data/db/a_share_hmm.duckdb
```

Primary source tables, if available:

```text
sector_state_daily
model_runs
model_evidence_registry
validation_runs
ui_readiness_policy
```

The implementation must inspect actual table columns instead of assuming exact probability column names. Prefer columns that clearly represent HMM posterior probabilities, such as `prob_*`, `state_prob_*`, or equivalent. If no posterior columns are found, generate a report with `status=partial_missing_posterior_columns` and do not invent probabilities.

## Required metrics

For each row with HMM posterior probabilities, compute at minimum:

- `posterior_max`: largest state posterior.
- `posterior_second`: second largest posterior.
- `posterior_margin`: `posterior_max - posterior_second`.
- `posterior_entropy`: entropy of posterior distribution.
- `posterior_entropy_norm`: entropy divided by `log(n_states)`.
- `confidence_bucket`: one of `high`, `medium`, `low`, `unclear`, `missing`.
- `confidence_reason`: short machine-readable reason.
- `state_confidence_readiness`: one of Stage 00 canonical readiness statuses.

Suggested default bucket rules:

```text
missing: no posterior vector or invalid posterior
high: posterior_max >= 0.70 and posterior_margin >= 0.25 and posterior_entropy_norm <= 0.65
medium: posterior_max >= 0.55 and posterior_margin >= 0.12 and posterior_entropy_norm <= 0.85
low: posterior vector valid but below medium threshold
unclear: near-tie, high entropy, or otherwise ambiguous
```

The exact thresholds may be configurable, but the defaults must be documented.

## Schema requirements

Add idempotent schema creation. Prefer integration through `DuckDBStorage.init_schema()`; if integration is risky, provide an explicit `ensure_hmm_confidence_schema(db_path)` and call it from CLI/tests.

Create tables if they do not exist.

### `hmm_confidence_daily`

Minimum fields:

```text
run_id
trade_date
sector_id or sector_code
sector_name
state_id
state_label
posterior_max
posterior_second
posterior_margin
posterior_entropy
posterior_entropy_norm
confidence_bucket
confidence_reason
state_confidence_readiness
posterior_columns_json
feature_scope_id
universe_id
created_at
```

Use a primary key that avoids duplicates, such as `(run_id, trade_date, sector_id)` or equivalent actual sector identifier.

### `hmm_confidence_run_summary`

Minimum fields:

```text
run_id
row_count
sector_count
min_trade_date
max_trade_date
high_count
medium_count
low_count
unclear_count
missing_count
high_share
medium_share
low_share
unclear_share
missing_share
median_posterior_max
median_posterior_margin
median_entropy_norm
readiness_status
report_path
created_at
```

## API / CLI requirements

Add one of:

```text
src/evaluation/hmm_confidence.py
```

or a similarly named evaluation module.

Required CLI:

```bash
python -m src.evaluation.hmm_confidence \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --output reports/hmm_confidence/stage01_wp_a_confidence_report.md \
  --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json \
  --no-fetch
```

Required behavior:

- `--no-fetch` is default and must never call data updaters.
- `--run-id latest` resolves latest HMM run from `model_runs` or equivalent.
- If DB is missing, produce a partial report and still pass unit tests on temporary DuckDB data.
- If posterior columns are missing, produce a partial report and machine-readable warning.
- If Stage 00 registry exists, optionally write or update a `validation_runs` record with validation_type `signal_validation` or an accepted Stage 01-specific value only if schema supports it. If not supported, write a JSON seed report instead; do not break.

## Tests

Add tests, at minimum:

```text
tests/test_hmm_confidence.py
```

Coverage requirements:

- Confidence metrics from synthetic posterior vectors.
- Entropy normalization is finite and bounded for valid posterior vectors.
- Bucket assignment for high/medium/low/unclear/missing.
- CLI works on temporary DuckDB with minimal `sector_state_daily` and `model_runs` tables.
- Missing DB and missing posterior columns are handled without unhandled exceptions.
- No external data updater is called.

Suggested commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_confidence.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_confidence --db data/db/a_share_hmm.duckdb --run-id latest --output reports/hmm_confidence/stage01_wp_a_confidence_report.md --summary-json reports/hmm_confidence/stage01_wp_a_confidence_report.json --no-fetch
```

## Reports

Generate:

```text
reports/hmm_confidence/stage01_wp_a_confidence_report.md
reports/hmm_confidence/stage01_wp_a_confidence_report.json
```

Report must include:

- run_id
- data range
- row count / sector count
- posterior columns used
- confidence bucket distribution
- median posterior max / margin / entropy norm
- partial/blocked reasons if any
- statement that HMM posterior is state confidence, not return probability
- external_data_fetch: no
- training_algorithm_modified: no

## Acceptance criteria

WP-A passes if:

- Confidence metrics are computed for valid HMM posterior rows or a clear partial report is generated when posterior columns are unavailable.
- New tests pass.
- Main not-slow suite passes or failure is fully documented and unrelated.
- No external data is fetched.
- No HMM/HSMM training algorithm is modified.
- Reports are committed.
- The report clearly states that posterior probabilities are state confidence only.

## Return format

```text
Thread: A
index_id: STAGE01-WP-A-v1
branch: stage01/wp-a-hmm-confidence
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
posterior columns found: yes/no
confidence rows generated: ...
report paths:
- ...
DB used: yes/no
external data fetch: no
training algorithm modified: no
implemented WP-B label alignment: no
implemented WP-C UI/churn: no
remaining risks:
- ...
```
