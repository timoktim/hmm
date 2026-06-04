# Stage03R WP5 Hazard Isotonic Calibration

status: pass
calibration_version: hazard_isotonic_calibration_v1
source: hazard_predictions:reports/stage03r/duration_hazard_logistic_predictions_sample.csv
hazard_prediction_row_count: 5000
calibration_sample_count: 5000
positive_count: 789
negative_count: 4211
horizons: [1]
validation_only: true
final_holdout_tuning: false
final_holdout_excluded_count: 0
non_validation_excluded_count: 0
usable_probability_count: 0

## Brier and ECE

- raw_brier_mean: 0.16306243306263382
- calibrated_brier_mean: 0.13146691814022105
- brier_delta_mean: -0.031595514922412776
- raw_ece_mean: 0.10477905866570841
- calibrated_ece_mean: 0.0
- age_bucket_baseline_brier_mean: 0.15728508659439483
- age_bucket_baseline_joined_row_count: 5000

## Calibration Status Counts

```json
{
  "calibration_candidate": 6,
  "degraded_brier_worse": 8,
  "ordinal_only": 6
}
```

## Horizon Metrics

```json
[
  {
    "horizon_days": 1,
    "sample_count": 5000,
    "positive_count": 789,
    "negative_count": 4211,
    "raw_brier": 0.16306243306263382,
    "calibrated_brier": 0.13146691814022105,
    "raw_ece": 0.10477905866570841,
    "calibrated_ece": 0.0,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "fold_count": 1,
    "raw_probability_min": 0.086963227841226,
    "raw_probability_max": 0.9486018057058132,
    "calibrated_probability_min": 0.10820895522388059,
    "calibrated_probability_max": 1.0
  }
]
```

## Slice Metrics

```json
[
  {
    "horizon_days": 1,
    "state_label": "Neutral",
    "state_phase": "early",
    "age_bucket": "1-3",
    "sample_count": 601,
    "positive_count": 167,
    "negative_count": 434,
    "raw_brier": 0.20121359462852895,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.2010329691066671,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 19318,
    "age_bucket_baseline_event_rate": 0.258515374262346
  },
  {
    "horizon_days": 1,
    "state_label": "Neutral",
    "state_phase": "late",
    "age_bucket": "4-7",
    "sample_count": 124,
    "positive_count": 26,
    "negative_count": 98,
    "raw_brier": 0.1663698755741921,
    "calibrated_brier": 0.16300941147536654,
    "age_bucket_baseline_brier": 0.1657489628682252,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 5568,
    "age_bucket_baseline_event_rate": 0.2036637931034483
  },
  {
    "horizon_days": 1,
    "state_label": "Neutral",
    "state_phase": "late",
    "age_bucket": "8-14",
    "sample_count": 116,
    "positive_count": 31,
    "negative_count": 85,
    "raw_brier": 0.19202608093752402,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.19834566297273803,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 7133,
    "age_bucket_baseline_event_rate": 0.21701948689191083
  },
  {
    "horizon_days": 1,
    "state_label": "Neutral",
    "state_phase": "mature",
    "age_bucket": "1-3",
    "sample_count": 182,
    "positive_count": 59,
    "negative_count": 123,
    "raw_brier": 0.21451647010991384,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.2270244557764837,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 6232,
    "age_bucket_baseline_event_rate": 0.2350770218228498
  },
  {
    "horizon_days": 1,
    "state_label": "Neutral",
    "state_phase": "mature",
    "age_bucket": "4-7",
    "sample_count": 217,
    "positive_count": 45,
    "negative_count": 172,
    "raw_brier": 0.16608236227475254,
    "calibrated_brier": 0.16154932837503516,
    "age_bucket_baseline_brier": 0.16466129317771488,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 8634,
    "age_bucket_baseline_event_rate": 0.19029418577716006
  },
  {
    "horizon_days": 1,
    "state_label": "Repair",
    "state_phase": "early",
    "age_bucket": "1-3",
    "sample_count": 615,
    "positive_count": 105,
    "negative_count": 510,
    "raw_brier": 0.1420248860210123,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.1421895243896542,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 18452,
    "age_bucket_baseline_event_rate": 0.19537177541729894
  },
  {
    "horizon_days": 1,
    "state_label": "Repair",
    "state_phase": "late",
    "age_bucket": "15+",
    "sample_count": 954,
    "positive_count": 82,
    "negative_count": 872,
    "raw_brier": 0.25351031277321867,
    "calibrated_brier": 0.08889761969141519,
    "age_bucket_baseline_brier": 0.07902433356353906,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 10832,
    "age_bucket_baseline_event_rate": 0.10736706056129985
  },
  {
    "horizon_days": 1,
    "state_label": "Repair",
    "state_phase": "late",
    "age_bucket": "8-14",
    "sample_count": 909,
    "positive_count": 94,
    "negative_count": 815,
    "raw_brier": 0.1010848554554147,
    "calibrated_brier": 0.09353487571473894,
    "age_bucket_baseline_brier": 0.09345467841222742,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 14658,
    "age_bucket_baseline_event_rate": 0.13057715923045435
  },
  {
    "horizon_days": 1,
    "state_label": "Repair",
    "state_phase": "mature",
    "age_bucket": "1-3",
    "sample_count": 240,
    "positive_count": 31,
    "negative_count": 209,
    "raw_brier": 0.11247669564089989,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.11299230221015658,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 6801,
    "age_bucket_baseline_event_rate": 0.1517423908248787
  },
  {
    "horizon_days": 1,
    "state_label": "Repair",
    "state_phase": "mature",
    "age_bucket": "4-7",
    "sample_count": 741,
    "positive_count": 78,
    "negative_count": 663,
    "raw_brier": 0.09583965296679615,
    "calibrated_brier": 0.09323585180001183,
    "age_bucket_baseline_brier": 0.09579470141509072,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 18513,
    "age_bucket_baseline_event_rate": 0.14541133257710798
  },
  {
    "horizon_days": 1,
    "state_label": "Stress",
    "state_phase": "early",
    "age_bucket": "1-3",
    "sample_count": 41,
    "positive_count": 12,
    "negative_count": 29,
    "raw_brier": 0.2014098732083501,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.21135480958061648,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 5894,
    "age_bucket_baseline_event_rate": 0.22684085510688837
  },
  {
    "horizon_days": 1,
    "state_label": "Stress",
    "state_phase": "late",
    "age_bucket": "4-7",
    "sample_count": 2,
    "positive_count": 1,
    "negative_count": 1,
    "raw_brier": 0.35413809540868707,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.4314453380561851,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 2 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 1945,
    "age_bucket_baseline_event_rate": 0.07403598971722365
  },
  {
    "horizon_days": 1,
    "state_label": "Stress",
    "state_phase": "mature",
    "age_bucket": "1-3",
    "sample_count": 10,
    "positive_count": 0,
    "negative_count": 10,
    "raw_brier": 0.03481042931549808,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.016893451516093623,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 10 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 1985,
    "age_bucket_baseline_event_rate": 0.12997481108312342
  },
  {
    "horizon_days": 1,
    "state_label": "Stress",
    "state_phase": "mature",
    "age_bucket": "4-7",
    "sample_count": 18,
    "positive_count": 2,
    "negative_count": 16,
    "raw_brier": 0.10687897685074774,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.11168261361862054,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 18 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 3190,
    "age_bucket_baseline_event_rate": 0.22476489028213167
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "early",
    "age_bucket": "1-3",
    "sample_count": 97,
    "positive_count": 34,
    "negative_count": 63,
    "raw_brier": 0.26582769076065893,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.24311193831178904,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 6866,
    "age_bucket_baseline_event_rate": 0.22618700844742207
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "late",
    "age_bucket": "15+",
    "sample_count": 14,
    "positive_count": 2,
    "negative_count": 12,
    "raw_brier": 0.23867361534860668,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.12486721367601882,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 14 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 979,
    "age_bucket_baseline_event_rate": 0.1920326864147089
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "late",
    "age_bucket": "4-7",
    "sample_count": 10,
    "positive_count": 1,
    "negative_count": 9,
    "raw_brier": 0.09061104921650213,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.09759242159980848,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 10 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 1197,
    "age_bucket_baseline_event_rate": 0.1871345029239766
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "late",
    "age_bucket": "8-14",
    "sample_count": 36,
    "positive_count": 7,
    "negative_count": 29,
    "raw_brier": 0.15981801230380155,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.15667081927198612,
    "calibration_status": "degraded_brier_worse",
    "fallback_reason": "calibrated Brier worse than raw Brier",
    "age_bucket_baseline_sample_count": 3868,
    "age_bucket_baseline_event_rate": 0.20036194415718717
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "mature",
    "age_bucket": "1-3",
    "sample_count": 26,
    "positive_count": 4,
    "negative_count": 22,
    "raw_brier": 0.13002440376550523,
    "calibrated_brier": null,
    "age_bucket_baseline_brier": 0.130260687594093,
    "calibration_status": "ordinal_only",
    "fallback_reason": "sample_count 26 below min_sample_count 30",
    "age_bucket_baseline_sample_count": 2387,
    "age_bucket_baseline_event_rate": 0.16296606619187265
  },
  {
    "horizon_days": 1,
    "state_label": "Trend",
    "state_phase": "mature",
    "age_bucket": "4-7",
    "sample_count": 47,
    "positive_count": 8,
    "negative_count": 39,
    "raw_brier": 0.1467925784593697,
    "calibrated_brier": 0.14474205526570627,
    "age_bucket_baseline_brier": 0.14155355477018838,
    "calibration_status": "calibration_candidate",
    "fallback_reason": null,
    "age_bucket_baseline_sample_count": 5147,
    "age_bucket_baseline_event_rate": 0.15251602875461434
  }
]
```

## Boundary Confirmation

- calibration_status is diagnostic only; no readiness promotion here.
- final holdout rows are excluded from calibration.
- HSMM raw/calibrated p_exit is not consumed.
- external_data_fetch: no
- training_algorithm_modified: no
- DuckDB_committed: no
- usable_probability: no
