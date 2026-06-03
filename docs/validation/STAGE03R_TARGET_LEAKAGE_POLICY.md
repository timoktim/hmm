# Stage03R Target Leakage Policy

Index ID: STAGE03R-WP2
Applies to: `exit_target_dataset_v1`

## Purpose

This policy locks the causal boundary for Stage03R exit targets before any Duration Hazard training begins. Target labels may look forward only as labels. Feature columns and state inputs must not use information after `trade_date`.

## Feature Boundary

Every target row must satisfy:

```text
max_feature_date_used <= trade_date
feature_cutoff_date <= trade_date
```

If either metadata column or value is missing, strict audit mode must not silently pass. The audit records `metadata_missing` and downgrades status until the source contract is explicit.

## Label And Censoring Boundary

Observed labels are valid only when the horizon is observable:

- `observed_positive` requires `exit_within_horizon = 1`.
- `observed_negative` requires `exit_within_horizon = 0` and a complete observed horizon.
- `right_censored_by_run_end`, `right_censored_by_cutoff`, and `unknown_*` rows must keep `exit_within_horizon` null.
- Right-censored rows are not trainable negatives.
- Right-censored or unknown rows must have `sample_weight = 0` for supervised label training unless a later censoring-aware package explicitly changes the contract.

## Purge And Embargo Boundary

Every row must carry:

```text
purge_group_id
embargo_until_date
target_observation_end_date
```

`embargo_until_date` must be at least `target_observation_end_date` when the target end is known. Later split builders must purge overlapping target windows and exclude training rows whose embargo reaches validation start.

## Overlap Policy

Target windows are:

```text
[trade_date, target_observation_end_date]
```

Rows with the same `sector_code` and intersecting target windows are allowed in the dataset. Their existence means a later train/validation split must purge overlapping train rows against validation rows.

## Split Discipline

Any Stage03R training split must enforce:

- train rows do not overlap validation rows by sector target window;
- train rows with `embargo_until_date >= validation_start_date` are excluded;
- right-censored and unknown rows are excluded from supervised training labels by default;
- the same sector/date/horizon row cannot appear in both train and validation;
- final holdout is defined once, locked, and not reused for repeated tuning.

WP2 does not train a model and does not select final real holdout dates. It provides the audit and synthetic validator needed by later packages.

## Out Of Scope

This policy does not implement Duration Hazard, calibration, BOCPD, a readiness matrix, a decision engine, or any HMM/HSMM training algorithm changes.
