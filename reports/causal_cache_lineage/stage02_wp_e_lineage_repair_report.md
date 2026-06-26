# Stage 02 WP-E Causal Cache Lineage Repair

- index_id: STAGE02-WP-E-v1
- status: partial
- resolved_run_id: bea7ff20106a
- cache_key: dbefc30c9c4c2328fea7
- causal_cache_id: dbefc30c9c4c2328fea7
- causal_evidence_id: causal-evidence-9a2ca254d86fd586773f
- linkage_status: ambiguous
- linkage_confidence: 0.2
- linkage_method: multiple_metadata_candidates_without_native_link
- candidate_count: 7
- competing_candidate_count: 6
- coverage_ratio: 0.052885
- native_link_available: no
- strict_inferred_link_available: no
- readiness_effect: research_only_no_upgrade
- required_next_action: disambiguate competing caches by writing parent_run_id or causal_evidence_id
- external_data_fetch: no
- training_algorithm_modified: no
- DuckDB committed: no

## Linkage Decision

No linkage is promoted unless the cache has native run metadata or a strict single-candidate inferred contract. Weak candidates are evidence only and keep readiness conservative.

## Blocking Reasons

- multiple_cache_candidates_match_resolved_run_metadata
- strict_metadata_not_fully_matched
- coverage_incomplete
- walk_forward_cache_needs_explicit_causal_evidence_id

## Required Next Actions

- disambiguate competing caches by writing parent_run_id or causal_evidence_id

## Candidate Details

- cache_key: dbefc30c9c4c2328fea7
  causal_evidence_id: causal-evidence-9a2ca254d86fd586773f
  coverage_ratio: 0.052885
  matching_fields: n_states, feature_scope_id, scope_type, feature_version
  missing_or_mismatched_fields: universe_id
  conceptual_unit: walk_forward_evidence_unit

## Warnings

- none
