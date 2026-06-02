# Stage 02 WP-C Readiness Gate Report

index_id: STAGE02-WP-C-v1
status: pass
run_id: bea7ff20106a
local DB available: yes
db preflight: pass

## Readiness Gate

- evidence_level: exploratory
- readiness_status: research_only
- display_action: research_only
- state_confidence_status: available
- label_identity_status: available
- churn_dwell_status: available
- causal_cache_status: available
- ci_validation_status: available

## Inputs

### confidence

- availability: available
- source: db:hmm_confidence_run_summary
- status: pass
- readiness_status: internal_only
- display_action: n/a
- reasons: none
- warnings: none

### label_alignment

- availability: available
- source: db:hmm_label_alignment_audit
- status: pass
- readiness_status: research_only
- display_action: n/a
- reasons: label_alignment_ambiguity_high
- warnings: none

### churn_dwell

- availability: available
- source: db:hmm_churn_dwell_run_summary
- status: pass
- readiness_status: research_only
- display_action: research_only
- reasons: none
- warnings: none

### causal_cache

- availability: available
- source: reports/causal_cache/stage02_wp_a_causal_cache_audit.json
- status: partial
- readiness_status: research_only
- display_action: n/a
- reasons: cache_not_linked_to_resolved_run_id, causal_cache_not_linked_to_resolved_run_id, causal_cache_coverage_partial, causal_cache_missing_metadata
- warnings: walk_forward_cache_runs lacks run_id linkage metadata, audited latest walk-forward cache because no cache row can be proven to belong to the resolved HMM run, execution metadata absent; exec_date > signal_date was not audited, Stage 00 registry tables missing; wrote registry seed payload to summary JSON

### ci_validation

- availability: available
- source: reports/ci_validation/stage02_wp_b_ci_validation_summary.json
- status: pass
- readiness_status: n/a
- display_action: n/a
- reasons: ci_validation_no_private_db_not_db_backed
- warnings: none

## Blocking / Downgrade Reasons

- label_alignment_ambiguity_high
- cache_not_linked_to_resolved_run_id
- causal_cache_not_linked_to_resolved_run_id
- causal_cache_coverage_partial
- causal_cache_missing_metadata
- ci_validation_no_private_db_not_db_backed
- label_identity_not_strong_enough_for_validated_readiness
- churn_dwell_gate_keeps_display_research_only

## Required Next Evidence

- link causal cache rows to resolved HMM run_id in metadata or registry
- raise causal cache coverage before stronger readiness
- reduce or explain high label alignment ambiguity
- produce CI evidence beyond no-private-DB smoke validation before stronger claims

## Boundary Flags

- external_data_fetch: no
- training_algorithm_modified: no
- duckdb_committed: no
- decision_ready_emitted: no
- HMM posterior semantic role: state confidence diagnostics only

## Warnings
- walk_forward_cache_runs lacks run_id linkage metadata
- audited latest walk-forward cache because no cache row can be proven to belong to the resolved HMM run
- execution metadata absent; exec_date > signal_date was not audited
- Stage 00 registry tables missing; wrote registry seed payload to summary JSON
