# Stage04 WP0 Split Registry

status: locked
registry_version: stage04_split_registry_v1
frozen_stage03r_commit: b90acf351826bc200130b0c94a8f156ea51cff5a
evidence_cutoff_date: 2026-05-28
max_reconstructed_validation_end_date: 2026-05-28
final_holdout_consumed: no

## Future Holdout Policy

```json
{
  "holdout_start_rule": "strictly_after_evidence_cutoff_date",
  "minimum_candidate_holdout_start_date": "2026-05-29",
  "required_label_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "labels_must_be_complete": "yes",
  "no_threshold_tuning_after_lock": "yes",
  "no_model_retraining_inside_locked_evaluation_path": "yes",
  "final_holdout_consumption_count_starts_at": 0,
  "final_holdout_consumed_in_wp0": "no",
  "external_data_fetch": "no",
  "locked_evaluation_path": "prospective_only"
}
```

## Stage03R Evidence Boundary

```json
{
  "stage03r_final_gate": {
    "engineering_gate_verdict": "PASS",
    "empirical_promotion_verdict": "DEFER",
    "final_verdict": "DEFER",
    "defer_reasons": [
      "non-overlap with WP3-WP6.1 calibration/readiness evidence is not proven."
    ]
  },
  "stage03r_final_holdout_candidate": {
    "holdout_status": "holdout_candidate",
    "holdout_start_date": "2026-04-27",
    "holdout_end_date": "2026-05-27",
    "non_overlap_status": "not_proven",
    "candidate_overlaps_reconstructed_prior_validation": "yes",
    "consumption_count": 1,
    "empirical_promotion_verdict": "DEFER"
  },
  "accepted_artifact_versions": {
    "final_holdout_artifact": {
      "version": "final_holdout_artifact_v1",
      "status": "defer",
      "index_id": "STAGE03R-WP10.1"
    },
    "final_gate": {
      "version": "stage03r_final_gate_v1",
      "status": "defer",
      "index_id": "STAGE03R-WP10"
    },
    "risk_protocol": {
      "version": "risk_validation_protocol_v1",
      "status": "pass",
      "index_id": "STAGE03R-WP8"
    },
    "hazard_readiness_matrix": {
      "version": "hazard_readiness_matrix_v1",
      "status": "pass",
      "index_id": null
    },
    "data_quality_ci": {
      "version": "data_quality_ci_invariants_v1",
      "status": "pass",
      "index_id": "STAGE03R-WP9"
    },
    "hazard_vs_hsmm": {
      "version": "hazard_vs_hsmm_report_v1",
      "status": "pass",
      "index_id": "STAGE03R-WP7"
    },
    "age_bucket_baseline": {
      "version": "age_bucket_baseline_v1",
      "status": "pass",
      "index_id": null
    },
    "hazard_isotonic_calibration": {
      "version": "hazard_isotonic_calibration_v1",
      "status": "pass",
      "index_id": null
    },
    "duration_hazard_logistic": {
      "version": "duration_hazard_logistic_v1",
      "status": "pass",
      "index_id": null
    },
    "exit_target_dataset": {
      "version": "exit_target_dataset_v1",
      "status": "pass",
      "index_id": null
    },
    "target_leakage_purge_audit": {
      "version": null,
      "status": "pass",
      "index_id": null
    }
  }
}
```

## Prospective Validation Ledger

```json
{
  "schema_version": "stage04_prospective_validation_ledger_v1",
  "template_path": "reports/stage04/prospective_validation_ledger.jsonl",
  "local_daily_records_path": "reports/stage04/prospective_validation_ledger.local.jsonl",
  "committed_template_allowed": "yes",
  "daily_local_records_gitignored": "yes",
  "append_only": "yes",
  "record_types": [
    "template",
    "candidate_check",
    "label_completeness_check",
    "consumption_event"
  ]
}
```

## Boundary Flags

```json
{
  "external_data_fetch": "no",
  "training_algorithm_modified": "no",
  "model_retrained": "no",
  "HMM_HSMM_retrained": "no",
  "threshold_tuning": "no",
  "final_holdout_consumed": "no",
  "final_holdout_consumption_count": 0,
  "HSMM_p_exit_used_for_decision": "no",
  "decision_surface_output": "no",
  "trading_output": "no",
  "DuckDB_committed": "no"
}
```

## Eligibility Rule

A future holdout is eligible only when its start date is strictly after 2026-05-28, labels are complete for horizons [1, 3, 5, 10, 20], and no threshold tuning, retraining, final-holdout consumption, or decision output occurs after lock.
