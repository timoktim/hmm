# Stage03R WP6.1 Multi-Horizon Hazard Verdict

index_id: STAGE03R-WP6.1
status: pass
source_db: data/db/a_share_hmm.duckdb
external_data_fetch: no
training_algorithm_modified: no
HMM_HSMM_retrained: no
HSMM_p_exit_used: no
decision_ready_output: no
DuckDB_committed: no

## Summary

WP6.1 regenerated Duration Hazard predictions from the local DuckDB across horizons
1, 3, 5, 10, and 20, then reran isotonic calibration and refreshed the WP6
readiness matrix. Calibration evidence now covers all expected horizons; no
horizon is passively downgraded because the calibration input was truncated to
horizon 1.

The result is useful but conservative. Calibration is non-worse than raw Brier
for all calibrated slices, but the age-bucket baseline remains stronger for many
slices, so only 21 of 115 readiness rows qualify as `usable_probability`.

## Artifact Coverage

- full prediction rows generated locally: 584310
- full prediction horizons: [1, 3, 5, 10, 20]
- committed prediction sample rows: 5000
- committed prediction sample distribution: 1000 rows per horizon
- calibration_horizons: [1, 3, 5, 10, 20]
- missing_calibration_horizons: []
- readiness row_count: 115

## Readiness Status Counts

```json
{
  "usable_probability": 21,
  "ordinal_only": 0,
  "baseline_only": 93,
  "insufficient_sample": 1,
  "invalid": 0
}
```

## Per-Horizon Verdict

| horizon_days | usable_probability | baseline_only | insufficient_sample | calibrated_vs_raw_mean | calibrated_vs_baseline_mean | verdict |
|---:|---:|---:|---:|---:|---:|---|
| 1 | 7 | 16 | 0 | -0.010583 | 0.000611 | mixed; usable slices exist, but baseline remains stronger for most slices |
| 3 | 6 | 17 | 0 | -0.025633 | 0.003248 | mixed; calibrated hazard improves raw, but baseline wins most slices |
| 5 | 3 | 20 | 0 | -0.022130 | 0.004941 | mostly baseline_only; limited usable probability support |
| 10 | 2 | 21 | 0 | -0.019078 | 0.005325 | mostly baseline_only; long-horizon support is weak against baseline |
| 20 | 3 | 19 | 1 | -0.007276 | 0.000568 | mixed but sparse; one slice is insufficient_sample |

## Brier Summaries

Calibrated vs raw Brier:

```json
{
  "row_count": 69,
  "mean": -0.017745441934844546,
  "min": -0.20406497463954562,
  "max": -0.00008951522174776433,
  "non_worse_count": 69,
  "worse_count": 0
}
```

Calibrated vs age-bucket baseline Brier:

```json
{
  "row_count": 69,
  "mean": 0.0030649593167521388,
  "min": -0.013705526344389651,
  "max": 0.04119284723259942,
  "non_worse_count": 21,
  "worse_count": 48
}
```

## Verdict

Multi-horizon hazard calibration is feasible in the local DB environment: the
pipeline can regenerate predictions and calibration evidence for all requested
horizons without using external data or weakening purge/embargo split discipline.
However, the honest readiness result is not broad promotion. Most slices remain
`baseline_only` because the age-bucket empirical baseline is stronger than the
calibrated hazard probability.

WP6.1 should therefore be treated as a successful diagnostic and artifact repair,
not as a decision-surface promotion. WP7/WP8 remain blocked until this evidence is
reviewed and any later comparison/risk protocol work stays outside WP6.1.

## Reproducibility Notes

- Full prediction CSV used for calibration: `reports/stage03r/duration_hazard_logistic_predictions_full.csv`
- The full CSV is 126 MB and is intentionally ignored/not committed.
- Committed sample CSV: `reports/stage03r/duration_hazard_logistic_predictions_sample.csv`
- Sample writing is stratified by `horizon_days`, preventing silent recurrence of
  horizon-1-only samples.
