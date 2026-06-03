# Stage03R WP1 Exit Target Dataset v1 Report

status: pass
report_status: pass
run_id: hsmm_lifecycle_primary_v1
target_definition_version: exit_target_dataset_v1

## Dataset

- source_tables_used: ['hsmm_lifecycle_ui_daily', 'hsmm_state_daily', 'sector_features']
- row_count: 775590
- sector_count: 464
- trade_date_min: 2025-01-02
- trade_date_max: 2026-05-28
- horizons: [1, 3, 5, 10, 20]
- censoring_status_counts: {'observed_negative': 304819, 'observed_positive': 464777, 'right_censored_by_run_end': 5994}
- state_label_counts: {'Neutral': 244440, 'Repair': 346280, 'Stress': 82435, 'Trend': 102435}
- missing_feature_columns: ['breadth_feature', 'hmm_posterior_margin', 'hmm_state_entropy', 'hmm_state_label', 'market_regime_label']
- feature_leakage_violation_count: 0
- right_censored_count: 5994
- observed_positive_count: 464777
- observed_negative_count: 304819
- purge_embargo_policy_present: true

## State Label x Horizon Support

```json
[
  {
    "state_label": "Neutral",
    "horizon_days": 1,
    "row_count": 48888,
    "observed_positive_count": 11102,
    "observed_negative_count": 37402,
    "right_censored_count": 384
  },
  {
    "state_label": "Neutral",
    "horizon_days": 3,
    "row_count": 48888,
    "observed_positive_count": 25145,
    "observed_negative_count": 23078,
    "right_censored_count": 665
  },
  {
    "state_label": "Neutral",
    "horizon_days": 5,
    "row_count": 48888,
    "observed_positive_count": 33546,
    "observed_negative_count": 14435,
    "right_censored_count": 907
  },
  {
    "state_label": "Neutral",
    "horizon_days": 10,
    "row_count": 48888,
    "observed_positive_count": 43481,
    "observed_negative_count": 4053,
    "right_censored_count": 1354
  },
  {
    "state_label": "Neutral",
    "horizon_days": 20,
    "row_count": 48888,
    "observed_positive_count": 47019,
    "observed_negative_count": 405,
    "right_censored_count": 1464
  },
  {
    "state_label": "Repair",
    "horizon_days": 1,
    "row_count": 69256,
    "observed_positive_count": 10406,
    "observed_negative_count": 58850,
    "right_censored_count": 0
  },
  {
    "state_label": "Repair",
    "horizon_days": 3,
    "row_count": 69256,
    "observed_positive_count": 25253,
    "observed_negative_count": 44003,
    "right_censored_count": 0
  },
  {
    "state_label": "Repair",
    "horizon_days": 5,
    "row_count": 69256,
    "observed_positive_count": 36002,
    "observed_negative_count": 33254,
    "right_censored_count": 0
  },
  {
    "state_label": "Repair",
    "horizon_days": 10,
    "row_count": 69256,
    "observed_positive_count": 51746,
    "observed_negative_count": 17510,
    "right_censored_count": 0
  },
  {
    "state_label": "Repair",
    "horizon_days": 20,
    "row_count": 69256,
    "observed_positive_count": 63705,
    "observed_negative_count": 5551,
    "right_censored_count": 0
  },
  {
    "state_label": "Stress",
    "horizon_days": 1,
    "row_count": 16487,
    "observed_positive_count": 3313,
    "observed_negative_count": 13137,
    "right_censored_count": 37
  },
  {
    "state_label": "Stress",
    "horizon_days": 3,
    "row_count": 16487,
    "observed_positive_count": 7844,
    "observed_negative_count": 8580,
    "right_censored_count": 63
  },
  {
    "state_label": "Stress",
    "horizon_days": 5,
    "row_count": 16487,
    "observed_positive_count": 11016,
    "observed_negative_count": 5390,
    "right_censored_count": 81
  },
  {
    "state_label": "Stress",
    "horizon_days": 10,
    "row_count": 16487,
    "observed_positive_count": 15188,
    "observed_negative_count": 1191,
    "right_censored_count": 108
  },
  {
    "state_label": "Stress",
    "horizon_days": 20,
    "row_count": 16487,
    "observed_positive_count": 16325,
    "observed_negative_count": 44,
    "right_censored_count": 118
  },
  {
    "state_label": "Trend",
    "horizon_days": 1,
    "row_count": 20487,
    "observed_positive_count": 3914,
    "observed_negative_count": 16530,
    "right_censored_count": 43
  },
  {
    "state_label": "Trend",
    "horizon_days": 3,
    "row_count": 20487,
    "observed_positive_count": 9163,
    "observed_negative_count": 11217,
    "right_censored_count": 107
  },
  {
    "state_label": "Trend",
    "horizon_days": 5,
    "row_count": 20487,
    "observed_positive_count": 12862,
    "observed_negative_count": 7466,
    "right_censored_count": 159
  },
  {
    "state_label": "Trend",
    "horizon_days": 10,
    "row_count": 20487,
    "observed_positive_count": 17852,
    "observed_negative_count": 2415,
    "right_censored_count": 220
  },
  {
    "state_label": "Trend",
    "horizon_days": 20,
    "row_count": 20487,
    "observed_positive_count": 19895,
    "observed_negative_count": 308,
    "right_censored_count": 284
  }
]
```

## Age Bucket x Horizon Support

```json
[
  {
    "age_bucket": "1-3",
    "horizon_days": 1,
    "row_count": 68240,
    "observed_positive_count": 14633,
    "observed_negative_count": 53302,
    "right_censored_count": 305
  },
  {
    "age_bucket": "1-3",
    "horizon_days": 3,
    "row_count": 68240,
    "observed_positive_count": 31775,
    "observed_negative_count": 36087,
    "right_censored_count": 378
  },
  {
    "age_bucket": "1-3",
    "horizon_days": 5,
    "row_count": 68240,
    "observed_positive_count": 42970,
    "observed_negative_count": 24783,
    "right_censored_count": 487
  },
  {
    "age_bucket": "1-3",
    "horizon_days": 10,
    "row_count": 68240,
    "observed_positive_count": 58145,
    "observed_negative_count": 9391,
    "right_censored_count": 704
  },
  {
    "age_bucket": "1-3",
    "horizon_days": 20,
    "row_count": 68240,
    "observed_positive_count": 65541,
    "observed_negative_count": 1868,
    "right_censored_count": 831
  },
  {
    "age_bucket": "15+",
    "horizon_days": 1,
    "row_count": 13689,
    "observed_positive_count": 1725,
    "observed_negative_count": 11952,
    "right_censored_count": 12
  },
  {
    "age_bucket": "15+",
    "horizon_days": 3,
    "row_count": 13689,
    "observed_positive_count": 4458,
    "observed_negative_count": 9201,
    "right_censored_count": 30
  },
  {
    "age_bucket": "15+",
    "horizon_days": 5,
    "row_count": 13689,
    "observed_positive_count": 6499,
    "observed_negative_count": 7154,
    "right_censored_count": 36
  },
  {
    "age_bucket": "15+",
    "horizon_days": 10,
    "row_count": 13689,
    "observed_positive_count": 9712,
    "observed_negative_count": 3934,
    "right_censored_count": 43
  },
  {
    "age_bucket": "15+",
    "horizon_days": 20,
    "row_count": 13689,
    "observed_positive_count": 12336,
    "observed_negative_count": 1310,
    "right_censored_count": 43
  },
  {
    "age_bucket": "4-7",
    "horizon_days": 1,
    "row_count": 44257,
    "observed_positive_count": 7339,
    "observed_negative_count": 36855,
    "right_censored_count": 63
  },
  {
    "age_bucket": "4-7",
    "horizon_days": 3,
    "row_count": 44257,
    "observed_positive_count": 18461,
    "observed_negative_count": 25622,
    "right_censored_count": 174
  },
  {
    "age_bucket": "4-7",
    "horizon_days": 5,
    "row_count": 44257,
    "observed_positive_count": 26549,
    "observed_negative_count": 17437,
    "right_censored_count": 271
  },
  {
    "age_bucket": "4-7",
    "horizon_days": 10,
    "row_count": 44257,
    "observed_positive_count": 37160,
    "observed_negative_count": 6577,
    "right_censored_count": 520
  },
  {
    "age_bucket": "4-7",
    "horizon_days": 20,
    "row_count": 44257,
    "observed_positive_count": 41918,
    "observed_negative_count": 1775,
    "right_censored_count": 564
  },
  {
    "age_bucket": "8-14",
    "horizon_days": 1,
    "row_count": 28932,
    "observed_positive_count": 5038,
    "observed_negative_count": 23810,
    "right_censored_count": 84
  },
  {
    "age_bucket": "8-14",
    "horizon_days": 3,
    "row_count": 28932,
    "observed_positive_count": 12711,
    "observed_negative_count": 15968,
    "right_censored_count": 253
  },
  {
    "age_bucket": "8-14",
    "horizon_days": 5,
    "row_count": 28932,
    "observed_positive_count": 17408,
    "observed_negative_count": 11171,
    "right_censored_count": 353
  },
  {
    "age_bucket": "8-14",
    "horizon_days": 10,
    "row_count": 28932,
    "observed_positive_count": 23250,
    "observed_negative_count": 5267,
    "right_censored_count": 415
  },
  {
    "age_bucket": "8-14",
    "horizon_days": 20,
    "row_count": 28932,
    "observed_positive_count": 27149,
    "observed_negative_count": 1355,
    "right_censored_count": 428
  }
]
```

## Purge / Embargo Policy

Later model splits must purge overlapping horizons and embargo rows through embargo_until_date.

## Warnings

- none

## Boundary Confirmation

- external_data_fetch: no
- training_algorithm_modified: no
- DuckDB_committed: no
