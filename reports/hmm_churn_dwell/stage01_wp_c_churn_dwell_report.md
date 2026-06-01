# Stage 01 WP-C HMM Churn/Dwell Report

index_id: STAGE01-WP-C-v1
status: pass
run_id: bea7ff20106a
state rows found: yes
churn/dwell rows generated: 42210
row coverage: 584981 rows, 464 sectors
date coverage: 2020-02-07 .. 2026-05-28

## Metrics

- transition_count: 41746
- transition_rate_1d: 0.07142
- mean_dwell_days: 13.858825
- median_dwell_days: 9.0
- p10_dwell_days: 1.0
- p90_dwell_days: 32.0
- single_day_episode_share: 0.107581
- episode_count: 42210
- fragmentation_score: 0.20961
- churn_bucket: low

## Readiness

- dwell_readiness_status: research_only
- display_action: research_only
- confidence_integration_status: unavailable
- alignment_integration_status: available_table_without_run_id
- causal_cache_available: False

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
- hmm_confidence_low_or_unavailable
- missing_causal_cache_id
