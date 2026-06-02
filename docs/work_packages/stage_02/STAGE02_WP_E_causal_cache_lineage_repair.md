# STAGE02_WP_E_causal_cache_lineage_repair

Stage: 02 / Causal evidence and reproducible validation gates
Work package: WP-E
Index ID: STAGE02-WP-E-v1
Executor: Codex Lineage
Recommended branch: `stage02/wp-e-causal-cache-lineage-repair`

## Objective

Resolve the biggest current Stage 02 blocker: causal cache rows exist, but the system cannot prove that a causal cache belongs to the resolved HMM run used by readiness reports.

Previous evidence:

- WP-A found `causal_cache_available=true`.
- WP-A found `cache_run_id=null` and `cache_linkage_status=latest_unlinked_cache`.
- WP-A found `coverage_ratio=0.052885` against the resolved HMM state rows.
- WP-C kept readiness at `research_only` because causal cache lineage and coverage are insufficient.

This package must repair the lineage layer if the existing DB contains enough evidence. If it does not contain enough evidence, it must not fake a link. It must instead create a durable lineage contract, a future-proof write path, and a regeneration/backfill plan.

The goal is not to make HMM decision-ready. The goal is to make causal cache provenance explicit and machine-readable.

## Starting point

Start from updated `main` after PR #9, PR #10, and PR #11 are merged.

```bash
git fetch origin
git checkout main
git pull --ff-only
git checkout -b stage02/wp-e-causal-cache-lineage-repair
```

Read first:

```text
docs/indexes/WORK_PACKAGE_INDEX.md
docs/runtime/LOCAL_DB_HANDOFF.md
reports/causal_cache/stage02_wp_a_causal_cache_audit.json
reports/readiness_gate/stage02_wp_c_readiness_gate_report.json
reports/ci_validation/stage02_wp_b_ci_validation_summary.json
```

Use the existing local V0 DB only. Do not fetch new data.

## Design principle

Do not force a false link.

A causal cache can be linked to a resolved run only if the evidence is strong enough. If the cache is a walk-forward sequence that does not conceptually map to a single static `model_runs.run_id`, the package must say so and introduce a separate `causal_evidence_id` / `causal_cache_key` contract rather than pretending it belongs to the static in-sample run.

## Allowed files

Allowed additions:

```text
src/evaluation/causal_cache_lineage.py
tests/test_causal_cache_lineage.py
reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.md
reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.json
docs/architecture/CAUSAL_CACHE_LINEAGE_CONTRACT.md
```

Allowed focused updates:

```text
src/evaluation/causal_cache_audit.py
src/evaluation/readiness_gate.py
src/data_pipeline/storage.py
.gitignore
```

Only update these files to integrate the lineage contract or report allowlist.

Do not modify:

```text
src/models/
src/features/
```

Do not modify HMM or HSMM training algorithms.

## Required schema

Add idempotent schema. It must be safe to run repeatedly.

### `causal_cache_run_linkage`

Required fields:

```text
linkage_id
cache_key
causal_cache_id
resolved_run_id
model_run_id
causal_evidence_id
linkage_status
linkage_confidence
linkage_method
feature_scope_id
universe_id
scope_type
feature_version
n_states
cache_start_date
cache_end_date
model_train_start
model_train_end
coverage_ratio
expected_state_rows
unique_cache_state_rows
duplicate_key_count
leakage_violation_count
missing_metadata_count
evidence_json
blocking_reasons_json
created_at
updated_at
```

Allowed `linkage_status` values:

```text
native_link
strict_inferred_link
weak_inferred_candidate
ambiguous
not_linkable
requires_regeneration
```

Rules:

- `native_link` requires an explicit run id column in cache metadata that matches the resolved run id.
- `strict_inferred_link` requires strong matching across feature scope, universe, scope type, feature version, n_states, date coverage, and no competing candidate.
- `weak_inferred_candidate` is evidence only. It must not upgrade readiness.
- `ambiguous`, `not_linkable`, and `requires_regeneration` must keep readiness conservative.

## Required analysis

The CLI must inspect at least:

```text
walk_forward_cache_runs
walk_forward_state_cache
model_runs
sector_state_daily
hmm_confidence_run_summary
hmm_label_alignment_audit
hmm_churn_dwell_run_summary
causal_cache_run_linkage, if present
```

It must answer:

1. Does the cache have native run linkage columns?
2. If not, can a strict inferred link be proven?
3. Are there multiple possible model run candidates?
4. Is the cache conceptually a walk-forward evidence unit that should not be mapped to one static model run?
5. What is the correct identity for readiness: `model_run_id`, `cache_key`, or `causal_evidence_id`?
6. What future schema fields must be written when walk-forward cache is generated?

## Required future write contract

Document and, where safe, implement helper functions so future cache generation can persist:

```text
cache_key
causal_cache_id
causal_evidence_id
source_model_family
source_training_policy
feature_scope_id
universe_id
scope_type
feature_version
n_states
train_window_days
retrain_frequency
state_date_mode
start_date
end_date
created_at
params_hash
parent_run_id, if conceptually valid
```

If there is an existing cache generation path, add the minimal integration to write these fields. If the path is hard to identify, create a helper and document the integration point. Do not perform a broad rewrite.

## CLI

Required CLI:

```bash
python -m src.evaluation.causal_cache_lineage \
  --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" \
  --run-id latest \
  --output reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.md \
  --summary-json reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.json \
  --no-fetch
```

Optional flags:

```text
--write-linkage-table
--dry-run
--strict-only
```

Default behavior should be conservative. If unsure, do not write a strong link.

## Required report result

The report must include:

```text
resolved_run_id
cache_key / causal_cache_id
linkage_status
linkage_confidence
linkage_method
candidate_count
competing_candidate_count
coverage_ratio
native_link_available yes/no
strict_inferred_link_available yes/no
readiness_effect
required_next_action
```

Expected possible outcomes:

- `native_link`: old issue resolved for this cache.
- `strict_inferred_link`: usable only if strict evidence is sufficient and unambiguous.
- `requires_regeneration`: old cache cannot be safely repaired; regenerate with lineage fields.
- `not_linkable`: the old cache and static run are different evidence units.

## Readiness integration

Update causal cache audit or readiness gate only enough to consume `causal_cache_run_linkage`.

If status is not `native_link` or `strict_inferred_link`, readiness must remain `research_only`.

Even with a strict link, this package must not output `decision_ready`.

## Tests

Add tests for:

- idempotent schema creation;
- native link detection;
- strict inferred link success with one candidate;
- ambiguous candidates do not upgrade;
- missing metadata produces `requires_regeneration` or `not_linkable`;
- weak inferred link does not upgrade readiness;
- CLI writes valid Markdown and JSON;
- no external fetch;
- no decision-ready output.

Required commands:

```bash
python -m compileall -q src tests
pytest -q tests/test_causal_cache_lineage.py
pytest -q tests/test_causal_cache_audit.py tests/test_readiness_gate.py
pytest -q tests/test_private_path_hygiene.py
bash scripts/check_no_private_paths.sh
bash scripts/validate_stage01_no_private_db.sh
pytest -q -m "not slow"
python -m src.evaluation.causal_cache_lineage --db "${ASHARE_HMM_DB_PATH:-data/db/a_share_hmm.duckdb}" --run-id latest --output reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.md --summary-json reports/causal_cache_lineage/stage02_wp_e_lineage_repair_report.json --no-fetch
```

If `python` is unavailable, use `.venv/bin/python` and document it.

## Acceptance criteria

Pass if:

- lineage status is explicit and machine-readable;
- no false link is created;
- future cache lineage contract is documented;
- if strong link is possible, it is written to `causal_cache_run_linkage` and consumed by audit/gate;
- if strong link is not possible, the report clearly states why and what must be regenerated;
- readiness remains conservative unless native or strict inferred linkage exists;
- no external data fetch;
- no training algorithm changes;
- no DuckDB/WAL commit;
- tests pass.

## Return format

```text
WP: STAGE02-WP-E-v1
status: pass / partial / fail
branch: stage02/wp-e-causal-cache-lineage-repair
PR: ...
commands run:
- ...
local DB:
- path used: ...
- preflight: pass/fail
lineage result:
- resolved_run_id: ...
- cache_key: ...
- causal_cache_id: ...
- linkage_status: ...
- linkage_confidence: ...
- linkage_method: ...
- candidate_count: ...
- competing_candidate_count: ...
- readiness_effect: ...
required next action:
- ...
files changed:
- ...
external data fetch: no
training algorithm modified: no
DuckDB committed: no
```
