# Stage03R WP7 Hazard vs HSMM Report

## Executive Verdict

Duration Hazard is locally usable but not broadly promoted. HSMM lifecycle fields remain interpretation-only context, and HSMM numeric p_exit is not used as a decision input.

Age-bucket baseline remains stronger for the majority of slices; usable hazard probability is limited to readiness-approved local slices.

## Input Artifacts And Versions

```json
{
  "hazard_readiness": "reports/stage03r/hazard_readiness_matrix_report.json",
  "hazard_verdict": "reports/stage03r/multi_horizon_hazard_verdict.md",
  "age_bucket_baseline": "reports/stage03r/age_bucket_baseline_report.json",
  "hazard_readiness_version": "hazard_readiness_matrix_v1",
  "age_bucket_baseline_version": "age_bucket_baseline_v1",
  "wp6_1_verdict_present": "yes"
}
```

## Hazard Readiness Summary

```json
{
  "usable_probability": 21,
  "ordinal_only": 0,
  "baseline_only": 93,
  "insufficient_sample": 1,
  "invalid": 0
}
```

## HSMM Lifecycle Availability Summary

```json
{
  "available": "yes",
  "row_count": 557104,
  "ordinal_tendency_available": "yes",
  "matched_numeric_artifact": "missing",
  "hsmm_numeric_p_exit_policy": "not_available",
  "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
  "p_exit_columns": [],
  "lifecycle_probability_status_columns_diagnostic_only": [
    "probability_status_1d",
    "probability_status_3d",
    "probability_status_5d",
    "probability_status_10d",
    "probability_status_20d",
    "raw_score_used_1d",
    "raw_score_used_3d",
    "raw_score_used_5d",
    "raw_score_used_10d",
    "raw_score_used_20d"
  ],
  "profile_policy_counts": [
    {
      "profile_mode": "latest_asof",
      "state_date_policy": "full_run",
      "row_count": 310236,
      "min_trade_date": "2025-01-02",
      "max_trade_date": "2026-05-28"
    },
    {
      "profile_mode": "retrospective",
      "state_date_policy": "full_run",
      "row_count": 155118,
      "min_trade_date": "2025-01-02",
      "max_trade_date": "2026-05-28"
    },
    {
      "profile_mode": "latest_asof",
      "state_date_policy": "cutoff_only",
      "row_count": 91750,
      "min_trade_date": "2025-01-02",
      "max_trade_date": "2025-10-31"
    }
  ]
}
```

## Hazard vs HSMM Comparison By Horizon

```json
[
  {
    "horizon_days": 1,
    "hazard_readiness_counts": {
      "usable_probability": 7,
      "ordinal_only": 0,
      "baseline_only": 16,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "usable_probability_count": 7,
    "baseline_only_count": 16,
    "hsmm_lifecycle_available": "yes",
    "hsmm_matched_hazard_slice_count": 23,
    "hsmm_ordinal_tendency_counts": {
      "high": 168599,
      "low": 169159,
      "medium": 219346
    },
    "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
    "hsmm_lifecycle_probability_status_counts_diagnostic_only": {
      "ordinal_only": 311526,
      "raw_only": 169987,
      "usable_probability": 75591
    },
    "verdict": "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked; baseline_only majority preserved"
  },
  {
    "horizon_days": 3,
    "hazard_readiness_counts": {
      "usable_probability": 6,
      "ordinal_only": 0,
      "baseline_only": 17,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "usable_probability_count": 6,
    "baseline_only_count": 17,
    "hsmm_lifecycle_available": "yes",
    "hsmm_matched_hazard_slice_count": 23,
    "hsmm_ordinal_tendency_counts": {
      "high": 170676,
      "low": 172730,
      "medium": 213698
    },
    "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
    "hsmm_lifecycle_probability_status_counts_diagnostic_only": {
      "invalid": 58338,
      "ordinal_only": 498766
    },
    "verdict": "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked; baseline_only majority preserved"
  },
  {
    "horizon_days": 5,
    "hazard_readiness_counts": {
      "usable_probability": 3,
      "ordinal_only": 0,
      "baseline_only": 20,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "usable_probability_count": 3,
    "baseline_only_count": 20,
    "hsmm_lifecycle_available": "yes",
    "hsmm_matched_hazard_slice_count": 23,
    "hsmm_ordinal_tendency_counts": {
      "high": 169223,
      "low": 169429,
      "medium": 218452
    },
    "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
    "hsmm_lifecycle_probability_status_counts_diagnostic_only": {
      "ordinal_only": 557104
    },
    "verdict": "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked; baseline_only majority preserved"
  },
  {
    "horizon_days": 10,
    "hazard_readiness_counts": {
      "usable_probability": 2,
      "ordinal_only": 0,
      "baseline_only": 21,
      "insufficient_sample": 0,
      "invalid": 0
    },
    "usable_probability_count": 2,
    "baseline_only_count": 21,
    "hsmm_lifecycle_available": "yes",
    "hsmm_matched_hazard_slice_count": 23,
    "hsmm_ordinal_tendency_counts": {
      "high": 172945,
      "low": 183077,
      "medium": 201082
    },
    "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
    "hsmm_lifecycle_probability_status_counts_diagnostic_only": {
      "invalid": 253188,
      "ordinal_only": 75591,
      "raw_only": 169987,
      "usable_probability": 58338
    },
    "verdict": "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked; baseline_only majority preserved"
  },
  {
    "horizon_days": 20,
    "hazard_readiness_counts": {
      "usable_probability": 3,
      "ordinal_only": 0,
      "baseline_only": 19,
      "insufficient_sample": 1,
      "invalid": 0
    },
    "usable_probability_count": 3,
    "baseline_only_count": 19,
    "hsmm_lifecycle_available": "yes",
    "hsmm_matched_hazard_slice_count": 23,
    "hsmm_ordinal_tendency_counts": {
      "high": 173862,
      "low": 185341,
      "medium": 197901
    },
    "hsmm_lifecycle_probability_status_policy": "diagnostic_only_not_decision_input",
    "hsmm_lifecycle_probability_status_counts_diagnostic_only": {
      "invalid": 253188,
      "raw_only": 303916
    },
    "verdict": "hazard locally usable; HSMM ordinal context available; age-bucket baseline still checked; baseline_only majority preserved"
  }
]
```

## Hazard vs Age-Bucket Baseline Summary

Age-bucket baseline remains stronger for the majority of slices; usable hazard probability is limited to readiness-approved local slices.

## Where Usable Probability Is Allowed

```json
{
  "count": 21,
  "source": "hazard_readiness_matrix_only",
  "broadly_promoted": "no",
  "by_horizon": {
    "1": 7,
    "3": 6,
    "5": 3,
    "10": 2,
    "20": 3
  }
}
```

## Where Baseline Only Should Dominate

```json
{
  "count": 93,
  "majority": "yes",
  "by_horizon": {
    "1": 16,
    "3": 17,
    "5": 20,
    "10": 21,
    "20": 19
  }
}
```

## Where HSMM Should Remain Interpretation-Only

- HSMM lifecycle fields provide state age, phase, duration profile, and ordinal exit tendency context.
- HSMM numeric exit probabilities are not used for decision input in this report.
- If HSMM numeric fields are present, their policy is diagnostic-only and not a promotion signal.

## Failure And Abstain Cases

```json
{
  "insufficient_sample_count": 1,
  "invalid_count": 0,
  "insufficient_sample_by_horizon": {
    "1": 0,
    "3": 0,
    "5": 0,
    "10": 0,
    "20": 1
  }
}
```

## Boundary Confirmation

- external data fetch: no
- training algorithm modified: no
- HMM/HSMM retrained: no
- HSMM numeric exit probability used for decision input: no
- decision-ready output: no
- DuckDB committed: no

## Warnings

```json
[
  "matched HSMM numeric p_exit artifact missing; no numeric probability comparison fabricated",
  "baseline_only is the majority readiness status"
]
```
