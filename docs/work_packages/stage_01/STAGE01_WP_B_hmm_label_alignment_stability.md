# STAGE01_WP_B_hmm_label_alignment_stability

Stage: 01 / HMM baseline strengthening  
Work package: WP-B  
Index id: STAGE01-WP-B-v1  
Suggested branch: `stage01/wp-b-hmm-label-alignment`  
Codex thread: B  
Date: 2026-06-01

## Objective

Build a HMM state identity and label-alignment audit layer. The goal is to detect whether state labels retain stable meaning across runs, random seeds, checkpoints, scopes, and time windows. This package does not change HMM training; it audits state identity drift and produces machine-readable stability verdicts.

Stage 01 needs this because HMM posterior confidence is not enough if state identities drift. A high-confidence state assignment is still not useful if the same label changes meaning across runs.

## Stage boundary

This work package belongs to Stage 01 only. It may read existing HMM model outputs, `model_runs`, reports, and local database content. It must not implement WP-A confidence metrics or WP-C UI/churn degradation, except for consuming their outputs if present. It must not implement robust/sticky HMM training or HSMM repair.

## Inputs

Default DB path:

```text
data/db/a_share_hmm.duckdb
```

Potential source tables:

```text
model_runs
sector_state_daily
walk_forward_cache_runs
walk_forward_state_cache
model_evidence_registry
validation_runs
```

Potential report sources:

```text
reports/signal_validation/**
reports/hmm_confidence/**
```

The implementation must inspect available columns and degrade gracefully if some tables or model artifact files are missing.

## Required concepts

Implement a state signature for every `(run_id, state_label or state_id)` that can be derived from available outputs. The signature should prefer out-of-sample/causal state rows when available.

Suggested signature components:

- state occupancy share
- average future 5/10/20 day returns if already present or computable from local feature/price data without fetching
- median `rs_20d` or equivalent feature if available
- median volatility / drawdown / breadth feature if available
- transition-out share if state sequence is available
- average dwell duration if state sequence is available

If rich features are unavailable, use a minimal signature from state label, state id, occupancy, transition rate, and sector/date coverage.

## Required metrics

For each comparable run pair or checkpoint pair:

- `state_signature_distance`
- `best_match_state`
- `match_score`
- `ambiguous_match`: true/false
- `label_preserved`: true/false
- `label_drift_severity`: `none`, `low`, `medium`, `high`, `unknown`
- `alignment_method`: `hungarian`, `greedy_fallback`, or `not_enough_states`
- `coverage_status`

For run-level summary:

- number of states compared
- label preserved count/share
- ambiguous count/share
- high drift count/share
- state identity readiness status using Stage 00 canonical readiness values

## Implementation guidance

Recommended new module:

```text
src/evaluation/hmm_label_alignment.py
```

Optional helper:

```text
src/models/state_identity.py
```

If `scipy` is available, use Hungarian assignment. If not available, implement a deterministic greedy fallback and document it in the report. The report must not silently claim Hungarian alignment if fallback was used.

The implementation must never interpret HMM posterior as return probability. Any forward-return use must be clearly labeled as empirical realized outcome used for state signature only.

## Schema requirements

Create idempotent tables or generate report-only output if schema integration is risky.

Suggested tables:

### `hmm_state_signature`

Minimum fields:

```text
run_id
state_key
state_id
state_label
signature_json
occupancy_share
transition_out_share
avg_dwell_days
feature_scope_id
universe_id
row_count
created_at
```

### `hmm_label_alignment_audit`

Minimum fields:

```text
audit_id
base_run_id
compare_run_id
base_state_key
matched_state_key
match_score
state_signature_distance
label_preserved
ambiguous_match
label_drift_severity
alignment_method
coverage_status
created_at
```

## CLI requirements

Required CLI:

```bash
python -m src.evaluation.hmm_label_alignment \
  --db data/db/a_share_hmm.duckdb \
  --run-id latest \
  --compare-mode recent-runs \
  --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md \
  --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json \
  --no-fetch
```

Supported compare modes:

- `recent-runs`: compare latest HMM run to recent prior HMM runs with compatible scope.
- `self-split`: compare earlier/later periods within one run if multiple runs are not available.
- `report-only`: generate partial diagnostics if no comparable runs exist.

## Tests

Add tests:

```text
tests/test_hmm_label_alignment.py
```

Minimum coverage:

- Signature generation from synthetic state rows.
- Alignment returns correct identity when signatures are permuted.
- Ambiguous matches are detected.
- Missing comparable runs produces partial report, not crash.
- Greedy fallback is deterministic when scipy is unavailable.
- CLI works on minimal temporary DuckDB.
- No external data updater is called.

Suggested commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_hmm_label_alignment.py
pytest -q -m "not slow"
python -m src.evaluation.hmm_label_alignment --db data/db/a_share_hmm.duckdb --run-id latest --compare-mode recent-runs --output reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md --summary-json reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json --no-fetch
```

## Reports

Generate:

```text
reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.md
reports/hmm_label_alignment/stage01_wp_b_label_alignment_report.json
```

Report must include:

- run IDs compared
- comparison mode
- alignment method used
- state signature fields used
- label preserved share
- ambiguous match share
- drift severity distribution
- coverage limitations
- external_data_fetch: no
- training_algorithm_modified: no

## Acceptance criteria

WP-B passes if:

- It generates deterministic state signatures.
- It compares at least one run pair or produces a clear partial report explaining why comparison is impossible.
- It identifies label-preserved vs drifted states in synthetic tests.
- It does not change HMM/HSMM training.
- It does not fetch external data.
- Reports are committed.

## Return format

```text
Thread: B
index_id: STAGE01-WP-B-v1
branch: stage01/wp-b-hmm-label-alignment
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
comparison mode: ...
run pairs compared: ...
alignment method: ...
label preserved share: ...
report paths:
- ...
DB used: yes/no
external data fetch: no
training algorithm modified: no
implemented WP-A confidence: no
implemented WP-C UI/churn: no
remaining risks:
- ...
```
