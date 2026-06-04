# Stage03R WP10.1 Final Holdout Artifact

status: defer
artifact_version: final_holdout_artifact_v1
empirical_promotion_verdict: DEFER
holdout_start_date: 2026-04-27
holdout_end_date: 2026-05-27
holdout_status: holdout_candidate
non_overlap_status: not_proven
consumption_count: 1

## Holdout policy

```json
{
  "policy": "latest_complete_observed_horizon_window",
  "holdout_trading_days": 20,
  "expected_horizons": [
    1,
    3,
    5,
    10,
    20
  ],
  "observed_statuses": [
    "observed_negative",
    "observed_positive"
  ],
  "right_censored_rows_excluded_from_metrics": "yes"
}
```

## Non-overlap evidence

```json
{
  "proof_status": "not_proven",
  "reconstructed_wp3_validation_windows": [
    {
      "split_id": "split_1",
      "validation_start_date": "2025-05-14",
      "validation_end_date": "2025-09-09"
    },
    {
      "split_id": "split_2",
      "validation_start_date": "2025-09-10",
      "validation_end_date": "2026-01-15"
    },
    {
      "split_id": "split_3",
      "validation_start_date": "2026-01-16",
      "validation_end_date": "2026-05-28"
    }
  ],
  "max_reconstructed_validation_end_date": "2026-05-28",
  "candidate_holdout_start_date": "2026-04-27",
  "candidate_holdout_end_date": "2026-05-27",
  "candidate_overlaps_reconstructed_prior_validation": "yes",
  "wp5_final_holdout_excluded_count": 0,
  "metadata_gap": "Accepted WP3-WP6.1 artifacts do not persist an explicit final_holdout_start or full split-role manifest proving this candidate was excluded from calibration/readiness selection."
}
```

## Metrics by readiness status

```json
{
  "usable_probability": {
    "sample_count": 6096,
    "metric_row_count": 6096,
    "positive_count": 2449,
    "negative_count": 3647,
    "brier_score": 0.1875858504631072,
    "log_loss": 0.5505032117017541,
    "expected_calibration_error": 0.04472056555781827,
    "directional_separation": 0.21716941136285178,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 651,
      "low_confidence_row_count": 1767,
      "false_high_probability_negative_count": 45,
      "false_low_probability_positive_count": 344,
      "false_confidence_row_count": 389
    }
  },
  "ordinal_only": {
    "sample_count": 0,
    "metric_row_count": 0,
    "positive_count": 0,
    "negative_count": 0,
    "brier_score": null,
    "log_loss": null,
    "expected_calibration_error": null,
    "directional_separation": null,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "high_confidence_row_count": 0,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 0
    }
  },
  "baseline_only": {
    "sample_count": 36607,
    "metric_row_count": 36607,
    "positive_count": 25855,
    "negative_count": 10752,
    "brier_score": 0.1439796735185035,
    "log_loss": 0.43637030194939425,
    "expected_calibration_error": 0.07811145461370683,
    "directional_separation": 0.35637950526287676,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 11824,
      "low_confidence_row_count": 3499,
      "false_high_probability_negative_count": 286,
      "false_low_probability_positive_count": 804,
      "false_confidence_row_count": 1090
    }
  },
  "insufficient_sample": {
    "sample_count": 3,
    "metric_row_count": 0,
    "positive_count": 3,
    "negative_count": 0,
    "brier_score": null,
    "log_loss": null,
    "expected_calibration_error": null,
    "directional_separation": null,
    "abstain_count": 3,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "high_confidence_row_count": 0,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 0
    }
  },
  "invalid": {
    "sample_count": 0,
    "metric_row_count": 0,
    "positive_count": 0,
    "negative_count": 0,
    "brier_score": null,
    "log_loss": null,
    "expected_calibration_error": null,
    "directional_separation": null,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "high_confidence_row_count": 0,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 0
    }
  }
}
```

## Verdicts by readiness status

```json
{
  "usable_probability": {
    "verdict": "DEFER",
    "sample_count": 6096,
    "metric_row_count": 6096,
    "reason": "non-overlap with WP3-WP6.1 evidence is not proven."
  },
  "ordinal_only": {
    "verdict": "DEFER",
    "sample_count": 0,
    "metric_row_count": 0,
    "reason": "no holdout rows available for this readiness status."
  },
  "baseline_only": {
    "verdict": "LOCAL_ONLY",
    "sample_count": 36607,
    "metric_row_count": 36607,
    "reason": "baseline-only rows use fixed age-bucket baseline probabilities, not broad hazard promotion."
  },
  "insufficient_sample": {
    "verdict": "DEFER",
    "sample_count": 3,
    "metric_row_count": 0,
    "reason": "no probability metric rows available for this readiness status."
  },
  "invalid": {
    "verdict": "DEFER",
    "sample_count": 0,
    "metric_row_count": 0,
    "reason": "no holdout rows available for this readiness status."
  }
}
```

## Metrics by horizon

```json
{
  "1": {
    "sample_count": 9276,
    "metric_row_count": 9276,
    "positive_count": 2078,
    "negative_count": 7198,
    "brier_score": 0.17524027574991524,
    "log_loss": 0.5371785665111621,
    "expected_calibration_error": 0.033560402156082525,
    "directional_separation": 0.004386148730353867,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 0,
      "low_confidence_row_count": 5266,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 1148,
      "false_confidence_row_count": 1148
    }
  },
  "3": {
    "sample_count": 8905,
    "metric_row_count": 8905,
    "positive_count": 4625,
    "negative_count": 4280,
    "brier_score": 0.2587405302160148,
    "log_loss": 0.711446341333168,
    "expected_calibration_error": 0.0877466317493713,
    "directional_separation": 0.0037391780570461552,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 0,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 0
    }
  },
  "5": {
    "sample_count": 8593,
    "metric_row_count": 8593,
    "positive_count": 6169,
    "negative_count": 2424,
    "brier_score": 0.21771358177375358,
    "log_loss": 0.6268853194093913,
    "expected_calibration_error": 0.10254387753006713,
    "directional_separation": 0.005036662783087675,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 54,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 12,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 12
    }
  },
  "10": {
    "sample_count": 8058,
    "metric_row_count": 8058,
    "positive_count": 7563,
    "negative_count": 495,
    "brier_score": 0.07340246563350819,
    "log_loss": 0.2863035617280993,
    "expected_calibration_error": 0.09331322578616591,
    "directional_separation": -0.009150130425123248,
    "abstain_count": 0,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 4550,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 317,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 317
    }
  },
  "20": {
    "sample_count": 7874,
    "metric_row_count": 7871,
    "positive_count": 7872,
    "negative_count": 2,
    "brier_score": 0.002831172307008004,
    "log_loss": 0.04039099471173182,
    "expected_calibration_error": 0.03740753818011805,
    "directional_separation": -0.03229961910870249,
    "abstain_count": 3,
    "false_confidence": {
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 7871,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 2,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 2
    }
  }
}
```

## Abstain and false confidence

```json
{
  "abstain_coverage": {
    "observed_holdout_row_count": 42706,
    "probability_metric_row_count": 42703,
    "abstain_count": 3,
    "abstain_rate": 7.024774036435162e-05,
    "coverage_rate": 0.9999297522596357,
    "coverage_scope": "readiness-approved usable_probability plus baseline_only fixed baseline probabilities"
  },
  "false_confidence_flags": [
    {
      "scope": "readiness_status:usable_probability",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 651,
      "low_confidence_row_count": 1767,
      "false_high_probability_negative_count": 45,
      "false_low_probability_positive_count": 344,
      "false_confidence_row_count": 389
    },
    {
      "scope": "readiness_status:baseline_only",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 11824,
      "low_confidence_row_count": 3499,
      "false_high_probability_negative_count": 286,
      "false_low_probability_positive_count": 804,
      "false_confidence_row_count": 1090
    },
    {
      "scope": "horizon_days:1",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 0,
      "low_confidence_row_count": 5266,
      "false_high_probability_negative_count": 0,
      "false_low_probability_positive_count": 1148,
      "false_confidence_row_count": 1148
    },
    {
      "scope": "horizon_days:5",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 54,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 12,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 12
    },
    {
      "scope": "horizon_days:10",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 4550,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 317,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 317
    },
    {
      "scope": "horizon_days:20",
      "high_confidence_probability_threshold": 0.8,
      "low_confidence_probability_threshold": 0.2,
      "threshold_source": "fixed audit bands; not tuned on holdout",
      "high_confidence_row_count": 7871,
      "low_confidence_row_count": 0,
      "false_high_probability_negative_count": 2,
      "false_low_probability_positive_count": 0,
      "false_confidence_row_count": 2
    }
  ]
}
```

## Boundary confirmation

- external_data_fetch: no
- db_opened_read_only: yes
- model_retrained: no
- threshold_tuning_on_holdout: no
- HSMM_p_exit_used_for_decision: no
- DuckDB_committed: no

## Blocking issues

```json
[]
```

## Defer reasons

```json
[
  "non-overlap with WP3-WP6.1 calibration/readiness evidence is not proven."
]
```

## Final recommendation

DEFER: preserve local-slice hazard scope until non-overlap evidence is explicit.
