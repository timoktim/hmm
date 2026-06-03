# Stage03R WP2 Target Leakage / Purge Audit

status: pass
row_count: 775590
strict: true
source: local_db

## Audit Counts

- feature_leakage_violation_count: 0
- censoring_violation_count: 0
- purge_embargo_violation_count: 0
- split_plan_violation_count: 0
- overlapping_window_pair_count: 31133350
- metadata_missing_count: 0
- right_censored_training_exclusion_policy: true
- final_holdout_policy_present: true

## Policy

- Right-censored and unknown rows are excluded from supervised training labels by default.
- Overlapping target windows are allowed in the dataset but must be purged across train/validation splits.
- Training rows are embargoed through `embargo_until_date` and must be excluded when the embargo reaches validation start.
- Final holdout may be defined once and must be locked before model tuning.

## Violation Sample

```json
[]
```

## Boundary Confirmation

- external_data_fetch: no
- training_algorithm_modified: no
- DuckDB_committed: no
