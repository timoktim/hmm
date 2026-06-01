# Stage 01 WP-C HMM Churn/Dwell Report

index_id: STAGE01-WP-C-v1
status: partial
run_id: latest
state rows found: no
churn/dwell rows generated: 0
row coverage: 0 rows, 0 sectors
date coverage: n/a .. n/a

## Metrics

- transition_count: 0
- transition_rate_1d: None
- mean_dwell_days: None
- median_dwell_days: None
- p10_dwell_days: None
- p90_dwell_days: None
- single_day_episode_share: None
- episode_count: 0
- fragmentation_score: None
- churn_bucket: unknown

## Readiness

- dwell_readiness_status: blocked
- display_action: blocked
- confidence_integration_status: unavailable
- alignment_integration_status: unavailable
- causal_cache_available: None

## Threshold Defaults

- low: transition_rate_1d <= 0.10 and single_day_episode_share <= 0.15
- medium: transition_rate_1d <= 0.20 and single_day_episode_share <= 0.30
- high: transition_rate_1d <= 0.35 and single_day_episode_share <= 0.50
- excessive: either metric is above the high threshold
- unknown: missing or insufficient state sequence

## Boundary Flags

- external_data_fetch: no
- training_algorithm_modified: no
- implemented WP-A confidence: no
- implemented WP-B label alignment: no

## Warnings
- database file not found: data/db/a_share_hmm.duckdb
- hmm_confidence_low_or_unavailable
- missing_or_insufficient_hmm_state_sequence
