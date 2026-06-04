# Stage03R WP10 Final Gate Report

## Executive final verdict

Final verdict: DEFER. Engineering gate: PASS. Empirical promotion: DEFER.

Hazard probability remains readiness-approved local-slice evidence only. Age-bucket baseline remains the majority fallback, and HSMM remains interpretation-only.

## Stage03R package evidence summary

```json
{
  "stage03_preflight": {
    "pr": "#38",
    "evidence": "Stage03 preflight PASS"
  },
  "STAGE03R-WP0": {
    "pr": "#39",
    "status": "accepted",
    "evidence": "scope freeze and signal contract"
  },
  "STAGE03R-WP1": {
    "pr": "#40",
    "status": "accepted",
    "evidence": "exit_target_dataset_v1"
  },
  "STAGE03R-WP2": {
    "pr": "#41",
    "status": "accepted",
    "evidence": "target leakage and purge tests"
  },
  "STAGE03R-WP3": {
    "pr": "#42",
    "status": "accepted",
    "evidence": "logistic hazard baseline"
  },
  "STAGE03R-WP4": {
    "pr": "#43",
    "status": "accepted",
    "evidence": "age-bucket baseline"
  },
  "STAGE03R-WP5": {
    "pr": "#44",
    "status": "accepted",
    "evidence": "hazard isotonic calibration"
  },
  "STAGE03R-WP6": {
    "pr": "#45",
    "status": "accepted",
    "evidence": "hazard_readiness_matrix_v1"
  },
  "STAGE03R-WP6.1": {
    "pr": "#46",
    "status": "accepted",
    "evidence": "multi-horizon hazard regeneration"
  },
  "STAGE03R-WP7": {
    "pr": "#47",
    "status": "accepted",
    "evidence": "hazard_vs_hsmm_report_v1"
  },
  "STAGE03R-WP8": {
    "pr": "#48",
    "status": "accepted",
    "evidence": "risk_validation_protocol_v1"
  },
  "STAGE03R-WP9": {
    "pr": "#49",
    "status": "accepted",
    "evidence": "data_quality_ci_invariants_v1"
  },
  "STAGE03R-WP10": {
    "status": "active",
    "evidence": "stage03r_final_gate_v1"
  },
  "artifact_schema_summary": {
    "hazard_readiness_matrix": {
      "status": "pass",
      "version": "hazard_readiness_matrix_v1",
      "required_fields_present": true
    },
    "multi_horizon_hazard_verdict": {
      "present": "yes",
      "mentions_expected_horizons": true
    },
    "hazard_vs_hsmm": {
      "status": "pass",
      "version": "hazard_vs_hsmm_report_v1",
      "required_fields_present": true
    },
    "risk_validation_protocol": {
      "status": "pass",
      "version": "risk_validation_protocol_v1",
      "required_fields_present": true
    },
    "data_quality_ci": {
      "status": "pass",
      "version": "data_quality_ci_invariants_v1",
      "failure_count": 0,
      "required_fields_present": true
    }
  }
}
```

## Required gate status summary

```json
{
  "exit_target_dataset_gate": {
    "status": "pass",
    "returncode": 0,
    "stable_line": "STAGE03R_EXIT_TARGET_GATE=pass python=.venv/bin/python pytest=.venv/bin/pytest",
    "command": "bash scripts/stage03r_exit_target_gate.sh"
  },
  "data_quality_ci_gate": {
    "status": "pass",
    "returncode": 0,
    "stable_line": "STAGE03R_DATA_QUALITY_CI_GATE=pass python=.venv/bin/python",
    "command": "bash scripts/stage03r_data_quality_ci_gate.sh"
  },
  "private_data_hygiene": {
    "status": "pass",
    "returncode": 0,
    "stable_line": "PRIVATE_PATH_HYGIENE=pass scanned_files=99",
    "command": "bash scripts/check_no_private_paths.sh"
  },
  "stage01_no_private_db": {
    "status": "pass",
    "returncode": 0,
    "stable_line": "CI_SAFE_STAGE01_VALIDATION=pass private_db_required=no external_data_fetch=no",
    "command": "bash scripts/validate_stage01_no_private_db.sh"
  },
  "stage03_preflight_gate": {
    "status": "pass",
    "returncode": 0,
    "stable_line": "STAGE03_PREFLIGHT_GATE=pass python=.venv/bin/python pytest=.venv/bin/pytest",
    "command": "bash scripts/stage03_preflight_gate.sh"
  },
  "target_leakage_purge_tests": {
    "status": "pass",
    "source": "data_quality_ci.leakage_causal_target_summary"
  },
  "stage03_preflight_gate_includes_data_quality_ci": {
    "status": "pass",
    "source": "data_quality_ci.gate_integration_summary"
  }
}
```

## Hazard readiness final summary

```json
{
  "readiness_version": "hazard_readiness_matrix_v1",
  "row_count": 115,
  "counts": {
    "usable_probability": 21,
    "ordinal_only": 0,
    "baseline_only": 93,
    "insufficient_sample": 1,
    "invalid": 0
  },
  "by_horizon": {
    "1": {
      "usable_probability": 7,
      "ordinal_only": 0,
      "baseline_only": 16,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "3": {
      "usable_probability": 6,
      "ordinal_only": 0,
      "baseline_only": 17,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "5": {
      "usable_probability": 3,
      "ordinal_only": 0,
      "baseline_only": 20,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "10": {
      "usable_probability": 2,
      "ordinal_only": 0,
      "baseline_only": 21,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "20": {
      "usable_probability": 3,
      "ordinal_only": 0,
      "baseline_only": 19,
      "insufficient_sample": 1,
      "invalid": 0
    }
  },
  "expected_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "missing_calibration_horizons": [],
  "missing_baseline_horizons": [],
  "hazard_locally_usable": "yes",
  "hazard_broadly_promoted": "no",
  "baseline_only_majority": "yes"
}
```

## Multi-horizon evidence summary

```json
{
  "expected_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "missing_calibration_horizons": [],
  "missing_baseline_horizons": []
}
```

## Hazard vs baseline summary

```json
{
  "baseline_only_count": 93,
  "usable_probability_count": 21,
  "majority": "yes",
  "by_horizon": {
    "1": 16,
    "3": 17,
    "5": 20,
    "10": 21,
    "20": 19
  },
  "claim": "Age-bucket baseline remains stronger for most slices."
}
```

## Hazard vs HSMM summary

```json
{
  "role": "interpretation_only",
  "lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
  "diagnostic_count_field": "hsmm_lifecycle_probability_status_counts_diagnostic_only",
  "raw_or_calibrated_p_exit_decision_input": "no",
  "numeric_probability_policy": "not_available"
}
```

## Risk validation protocol compliance

```json
{
  "status": "pass",
  "protocol_version": "risk_validation_protocol_v1",
  "missing_required_fields": [],
  "final_holdout_rule": "final holdout can be consumed only by an explicit WP10 final-gate run.",
  "repeated_final_tuning_forbidden": "yes",
  "threshold_tuning_in_wp8": "no",
  "pre_registered_metric_count": 8,
  "forbidden_output_terms_detected": []
}
```

## Data-quality CI compliance

```json
{
  "status": "pass",
  "report_version": "data_quality_ci_invariants_v1",
  "failure_count": 0,
  "warning_count": 0,
  "failures": [],
  "private_path_hits": [],
  "duckdb_or_wal_files_committed": [],
  "full_prediction_csv_committed": [],
  "ci_requires_db": "no",
  "external_data_fetch": "no",
  "local_db_status": {
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
    "duckdb_committed": "no"
  }
}
```

## Final holdout discipline

```json
{
  "protocol_rule": "final holdout can be consumed only by an explicit WP10 final-gate run.",
  "repeated_final_tuning_forbidden": "yes",
  "artifact_path": null,
  "artifact_present": "no",
  "consumed_in_wp10": "no",
  "consumption_count": 0,
  "empirical_broad_promotion_allowed": "no"
}
```

## PASS/BLOCKED/DEFER rules

- PASS requires all engineering gates and a compliant empirical promotion artifact.
- BLOCKED is emitted for missing artifacts, failing gates, boundary violations, or repeated final holdout use.
- DEFER is emitted when engineering controls pass but broad empirical promotion is not yet supported.

## Remaining limitations

- Hazard usable probability is local-slice only.
- Baseline-only remains the majority readiness status.
- HSMM remains interpretation-only.
- No decision surface exists yet.

## Boundary confirmation

```json
{
  "external_data_fetch": "no",
  "training_algorithm_modified": "no",
  "hmm_hsmm_retrained": "no",
  "hsmm_p_exit_decision_input": "no",
  "final_holdout_consumed": "no",
  "surface_or_action_overlay_output": "no",
  "duckdb_committed": "no",
  "private_db_required_in_ci": "no"
}
```

## Next-stage recommendations

```json
[
  "Keep hazard probability local-slice only until an explicit final holdout artifact is evaluated once.",
  "Retain age-bucket baseline as the majority fallback and report baseline-only slices without pseudo-probability.",
  "Keep HSMM lifecycle outputs as interpretation-only context.",
  "Define any future decision surface in a later stage with separate pre-registration and trial accounting."
]
```

## Blocking issues

```json
[]
```

## Defer reasons

```json
[
  "No explicit final holdout artifact was provided; broad empirical promotion remains deferred."
]
```

## Remediation items

```json
[
  "Provide a WP8-compliant final holdout artifact and consume it once in WP10 before broad empirical promotion."
]
```
