# STAGE02_WP_A_causal_cache_contract_audit

Stage: 02 / Causal evidence and reproducible validation gates
Work package: WP-A
Index ID: STAGE02-WP-A-v1
Executor: Codex A
Recommended branch: `stage02/wp-a-causal-cache-contract`

## Objective

Stage 01 ended with HMM confidence, label alignment, and churn/dwell diagnostics merged, but readiness remains `research_only` because causal cache metadata is unavailable. This package must turn causal walk-forward cache presence and validity into a machine-readable contract.

Goal: create a causal cache audit layer that can answer, for a given `run_id`, whether HMM state outputs are causal walk-forward states, whether the cache is usable for strategy/backtest/readiness, and why not.

This package must not train new models, fetch data, change HMM/HSMM training algorithms, or upgrade any signal to decision-ready.

## Starting point

Start from updated `main` after Stage 01 closure.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage02/wp-a-causal-cache-contract
```

Read first:

```text
docs/runtime/LOCAL_DB_HANDOFF.md
docs/acceptance/stage_01/STAGE01_FINAL_INTEGRATION_SUMMARY.md
docs/acceptance/stage_01/STAGE01_HARD_ISSUE_REVIEW.md
```

Use local DB only. No external data fetch.

## Scope

Allowed additions:

```text
src/evaluation/causal_cache_audit.py
tests/test_causal_cache_audit.py
reports/causal_cache/stage02_wp_a_causal_cache_audit.md
reports/causal_cache/stage02_wp_a_causal_cache_audit.json
```

Allowed small integration updates:

```text
src/ui/causal_boundary.py
src/ui/readiness_policy.py
```

Only touch UI readiness files if required to expose the audit result. Do not change display semantics beyond conservative gating.

Do not modify:

```text
src/models/
src/features/
src/evaluation/hmm_confidence.py
src/evaluation/hmm_label_alignment.py
src/evaluation/hmm_churn_dwell.py
```

## Required contract

Add a `CausalCacheAuditResult` data structure with at least:

```text
run_id
resolved_run_id
status: pass / partial / fail
causal_cache_available: true/false
causal_cache_id
cache_run_id
state_source
state_count
sector_count
min_trade_date
max_trade_date
coverage_ratio
train_end_max
max_observation_date_used_max
leakage_violation_count
missing_metadata_count
duplicate_key_count
exec_date_violation_count
readiness_status
readiness_reason
warnings
```

Readiness statuses must use Stage 00 canonical values: `blocked`, `research_only`, `internal_only`, `partial`, `validated`, `decision_ready`. This package should normally return no stronger than `partial` unless all required causal checks pass. It must never set `decision_ready`.

## Required checks

Audit at least the following tables if present:

```text
walk_forward_cache_runs
walk_forward_state_cache
sector_state_daily
model_runs
model_evidence_registry
validation_runs
```

Required checks:

1. Resolve `latest` HMM run id deterministically.
2. Check whether walk-forward cache rows exist for the resolved run.
3. Check `(run_id, sector_id/sector_code, trade_date)` uniqueness.
4. Check that state rows do not mix in-sample and causal sources silently.
5. Check that `train_end <= trade_date` wherever metadata is available.
6. Check that `max_observation_date_used <= trade_date` wherever metadata is available.
7. Check that `exec_date > signal_date` if execution metadata exists.
8. Compute row coverage versus expected sector-date coverage from available HMM state rows.
9. Return clear `unknown_due_to_missing_metadata` warnings rather than assuming pass.
10. Write a validation run/evidence record if Stage 00 registry tables exist. If not, write a JSON seed payload and warning.

## CLI

Required CLI:

```bash
python -m src.evaluation.causal_cache_audit \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/causal_cache/stage02_wp_a_causal_cache_audit.md \
  --summary-json reports/causal_cache/stage02_wp_a_causal_cache_audit.json \
  --no-fetch
```

`--no-fetch` must be default and must prevent any data updater/client call.

If DB is absent, report status must be `partial_missing_db` and tests must still pass with temp DuckDB fixtures.

## Tests

Add tests covering:

- missing DB returns partial_missing_db without creating fake pass;
- missing walk-forward tables returns explicit causal_cache_available=false;
- valid toy causal cache returns pass/partial according to metadata coverage;
- duplicate sector-date keys are counted;
- train_end > trade_date is counted as leakage violation;
- missing metadata does not pass silently;
- CLI writes valid Markdown and JSON;
- no external fetch is attempted.

Required commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_causal_cache_audit.py
pytest -q tests/test_ui_readiness_policy.py tests/test_ui_causal_boundary.py
pytest -q -m "not slow"
python -m src.evaluation.causal_cache_audit --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" --run-id latest --output reports/causal_cache/stage02_wp_a_causal_cache_audit.md --summary-json reports/causal_cache/stage02_wp_a_causal_cache_audit.json --no-fetch
```

## Acceptance criteria

Pass if:

- report clearly states causal cache availability and why readiness is or is not upgraded;
- no external data was fetched;
- no training algorithms changed;
- DuckDB/WAL not committed;
- missing metadata is explicit;
- readiness stays conservative unless all causal checks pass;
- tests pass.

Expected current result may be `partial` or `research_only` because Stage 01 found `causal_cache_available=false`. That is acceptable if accurately reported.

## Return format

```text
WP: STAGE02-WP-A-v1
status: pass / partial / fail
branch: stage02/wp-a-causal-cache-contract
PR: ...
commands run:
- ...
local DB:
- path used: ...
- preflight: pass/fail
report:
- ...
causal cache:
- available: true/false
- state_count: ...
- duplicate_key_count: ...
- leakage_violation_count: ...
- missing_metadata_count: ...
readiness:
- status: ...
- reason: ...
blocking issues:
- ...
tracked risks:
- ...
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```
