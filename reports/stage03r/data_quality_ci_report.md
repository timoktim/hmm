# Stage03R WP9 Data Quality CI Report

## Executive verdict

Stage03R data-quality CI status: pass.

## Artifact schema summary

```json
{
  "artifacts": {
    "hazard_readiness": {
      "path": "reports/stage03r/hazard_readiness_matrix_report.json",
      "exists": true,
      "required_fields_missing": []
    },
    "hazard_vs_hsmm": {
      "path": "reports/stage03r/hazard_vs_hsmm_report.json",
      "exists": true,
      "required_fields_missing": []
    },
    "risk_protocol": {
      "path": "reports/stage03r/risk_validation_protocol.json",
      "exists": true,
      "required_fields_missing": []
    }
  },
  "hazard_verdict": {
    "path": "reports/stage03r/multi_horizon_hazard_verdict.md",
    "exists": true,
    "contains_missing_calibration_horizons": true
  },
  "broad_hazard_promotion_claims": []
}
```

## Readiness invariant summary

```json
{
  "allowed_statuses": [
    "baseline_only",
    "insufficient_sample",
    "invalid",
    "ordinal_only",
    "usable_probability"
  ],
  "row_count": 115,
  "counts_from_rows": {
    "baseline_only": 93,
    "insufficient_sample": 1,
    "invalid": 0,
    "ordinal_only": 0,
    "usable_probability": 21
  },
  "reported_counts": {
    "usable_probability": 21,
    "ordinal_only": 0,
    "baseline_only": 93,
    "insufficient_sample": 1,
    "invalid": 0
  },
  "hazard_vs_hsmm_counts": {
    "usable_probability": 21,
    "ordinal_only": 0,
    "baseline_only": 93,
    "insufficient_sample": 1,
    "invalid": 0
  },
  "risk_protocol_counts": {
    "usable_probability": 21,
    "ordinal_only": 0,
    "baseline_only": 93,
    "insufficient_sample": 1,
    "invalid": 0
  },
  "usable_probability_source": "hazard_readiness_matrix_only",
  "baseline_only_majority": true,
  "insufficient_sample_count": 1,
  "invalid_count": 0
}
```

## Horizon coverage summary

```json
{
  "expected_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "required_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "hazard_prediction_sample_path": "reports/stage03r/duration_hazard_logistic_predictions_sample.csv",
  "hazard_prediction_sample_exists": true,
  "hazard_prediction_sample_columns": [
    "target_dataset_id",
    "sector_code",
    "trade_date",
    "state_label",
    "state_age",
    "state_phase",
    "horizon_days",
    "censoring_status",
    "exit_within_horizon",
    "fold_id",
    "split_role",
    "hazard_model_version",
    "hazard_raw_score",
    "hazard_raw_probability",
    "hazard_status",
    "sample_support",
    "fallback_reason"
  ],
  "hazard_prediction_sample_row_count": 5000,
  "hazard_prediction_sample_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "hazard_prediction_sample_horizon_counts": {
    "1": 1000,
    "3": 1000,
    "5": 1000,
    "10": 1000,
    "20": 1000
  },
  "missing_calibration_horizons": [],
  "missing_calibration_horizons_summary": [],
  "full_prediction_csv_committed": []
}
```

## Leakage and causal target summary

```json
{
  "target_sample_path": "reports/stage03r/exit_target_dataset_v1_sample.csv",
  "target_sample_exists": true,
  "target_sample_row_count": 1000,
  "required_columns_missing": [],
  "feature_leakage_violation_count": 0,
  "purge_group_id_missing_count": 0,
  "embargo_until_date_missing_count": 0,
  "right_censored_count": 30,
  "right_censored_bad_label_count": 0,
  "stage03r_exit_target_gate_required": "yes"
}
```

## HSMM diagnostic namespace summary

```json
{
  "legacy_hsmm_probability_status_counts_in_protocol": false,
  "diagnostic_count_field": "hsmm_lifecycle_probability_status_counts_diagnostic_only",
  "diagnostic_policy": "diagnostic_only_not_decision_input",
  "diagnostic_counts_by_horizon": {
    "1": {
      "ordinal_only": 311526,
      "raw_only": 169987,
      "usable_probability": 75591
    },
    "3": {
      "invalid": 58338,
      "ordinal_only": 498766
    },
    "5": {
      "ordinal_only": 557104
    },
    "10": {
      "invalid": 253188,
      "ordinal_only": 75591,
      "raw_only": 169987,
      "usable_probability": 58338
    },
    "20": {
      "invalid": 253188,
      "raw_only": 303916
    }
  },
  "hsmm_p_exit_used_for_decision": "no",
  "hsmm_numeric_p_exit_policy": "not_available"
}
```

## Risk protocol summary

```json
{
  "required_fields_missing": [],
  "final_holdout_consumption": "final holdout can be consumed only by an explicit WP10 final-gate run.",
  "repeated_final_tuning_forbidden": "yes",
  "threshold_tuning_in_wp8": "no",
  "forbidden_surface_terms": [],
  "boundary_flags": {
    "external_data_fetch": "no",
    "training_algorithm_modified": "no",
    "HMM_HSMM_retrained": "no",
    "HSMM_p_exit_used_for_decision": "no",
    "decision_surface_output": "no",
    "downside_action_overlay_output": "no",
    "DuckDB_committed": "no"
  }
}
```

## Private-data hygiene summary

```json
{
  "scanned_file_count": 339,
  "duckdb_or_wal_files_committed": [],
  "cache_files_committed": [],
  "full_prediction_csv_committed": [],
  "private_path_hits": [],
  "check_no_private_paths_required": "yes",
  "validate_stage01_no_private_db_required": "yes"
}
```

## Local DB status

```json
{
  "db_path_used": "data/db/a_share_hmm.duckdb",
  "db_found": "yes",
  "opened_read_only": "yes",
  "key_tables_checked": [
    "model_runs",
    "sector_state_daily",
    "walk_forward_cache_runs",
    "walk_forward_state_cache",
    "hsmm_lifecycle_ui_daily"
  ],
  "row_counts": {
    "model_runs": 25,
    "sector_state_daily": 2655935,
    "walk_forward_cache_runs": 7,
    "walk_forward_state_cache": 226810,
    "hsmm_lifecycle_ui_daily": 557104
  },
  "ci_requires_db": "no",
  "external_data_fetch": "no",
  "DuckDB_committed": "no"
}
```

## Gate integration summary

```json
{
  "stage03r_data_quality_ci_gate": "required",
  "stage03r_exit_target_gate": "required",
  "check_no_private_paths": "required",
  "validate_stage01_no_private_db": "required",
  "stage03_preflight_gate_includes_data_quality_ci": "yes"
}
```

## Boundary confirmation

```json
{
  "external_data_fetch": "no",
  "training_algorithm_modified": "no",
  "HMM_HSMM_retrained": "no",
  "HSMM_p_exit_used_for_decision": "no",
  "final_holdout_consumed": "no",
  "decision_surface_output": "no",
  "DuckDB_committed": "no"
}
```

## Failures

```json
[]
```

## Warnings

```json
[]
```
