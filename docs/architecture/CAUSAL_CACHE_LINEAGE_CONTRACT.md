# Causal Cache Lineage Contract

Stage 02 WP-E makes causal walk-forward cache provenance explicit. The contract is intentionally conservative: a cache is linked to a resolved HMM run only when there is native run metadata or one strict inferred candidate with full supporting evidence.

## Identity Model

Use separate identities for separate evidence units:

- `model_run_id`: static HMM model run from `model_runs.run_id`.
- `cache_key`: physical walk-forward cache key used by `walk_forward_cache_runs` and `walk_forward_state_cache`.
- `causal_cache_id`: stable public identity for the causal cache. It may equal `cache_key` for legacy caches.
- `causal_evidence_id`: deterministic evidence identity for a cache/run lineage record.
- `parent_run_id`: optional model run id only when the cache is conceptually generated from that static run.

Do not assume every walk-forward cache belongs to one static `model_runs.run_id`. A rolling walk-forward cache can be its own causal evidence unit.

## Linkage Statuses

Allowed `linkage_status` values:

- `native_link`: cache metadata has an explicit run id column matching the resolved HMM run.
- `strict_inferred_link`: one unambiguous candidate matches required metadata and full coverage checks.
- `weak_inferred_candidate`: useful evidence exists, but it is not strong enough to upgrade readiness.
- `ambiguous`: multiple candidates compete.
- `not_linkable`: cache and model run are different evidence units.
- `requires_regeneration`: legacy evidence is insufficient; regenerate or backfill with lineage fields.

Only `native_link` and `strict_inferred_link` can satisfy the cache lineage gate. None of these statuses can make output `decision_ready`.

## Linkage Table

`causal_cache_run_linkage` is idempotent and machine-readable. Required fields:

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

Rows with weak or blocking statuses are evidence records only. They must not upgrade readiness.

## Future Cache Write Contract

Any future walk-forward cache generation must persist:

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

If `parent_run_id` is not conceptually valid, leave it empty and use `causal_evidence_id` as the readiness identity.

## Readiness Rule

Readiness remains `research_only` unless causal cache linkage is `native_link` or `strict_inferred_link` and all other gates also support a stronger status. Stage 02 WP-E does not output `decision_ready`.
