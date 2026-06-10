# Stage03V WP0.5 Sample Feasibility Preflight

- index_id: STAGE03V-WP0.5-v1
- status: partial_missing_universe
- DB path: data/db/a_share_hmm.duckdb
- DB availability: available
- DB opened read-only: yes
- external data fetch: no
- SW2021 L2 universe coverage: partial
- benchmark target status: available
- vol_scaled_feasibility_status: deferred_to_wp3_5

## Contract Paths

- signal_contract: configs/risk_event_signal_contract_v1.yaml
- readiness_policy: configs/readiness_policy_risk_event_v1.yaml
- universe_manifest: configs/stage03v_sw_l2_universe_manifest_v1.yaml
- ledger_template: reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
- execution_index: docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md

## Source Coverage

- taxonomy_provider: SW
- taxonomy_version: SW2021
- taxonomy_level: L2
- industry_count_total: 119
- industry_count_after_quality_filter: 119
- min_trade_date: 2020-01-02
- max_trade_date: 2026-06-05
- coverage_start: 2020-01-02
- coverage_end: 2026-06-05
- history_continuity_status: partial_short_to_cutoff
- reform_window_continuity_status: pass
- silent_entity_break_count: 0
- duplicate_entity_count: 0
- short_history_entity_count: 0
- quality_filter_exclusion_count: 0
- constituent_count_filter_status: pass

## Cross-Cutoff Censoring

- cross_cutoff_censored_count: 0
- cross_cutoff_excluded_count: 0
- historical_development_labeled_count: 696240
- historical_development_unlabeled_due_to_cutoff_count: 0

## Feasibility Matrix

| horizon | threshold | historical_development_labeled_count | positive_event_count | market_event_block_count_10pct | market_event_block_count_20pct | market_event_block_count_30pct | idiosyncratic_industry_episode_count | effective_event_evidence_count_0_25 | benchmark_event_count | feasibility_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.0300 | 139860 | 5836 | 95 | 64 | 49 | 1312 | 392.0000 | 21 | partial_missing_data |
| 1 | 0.0500 | 139860 | 1426 | 28 | 16 | 11 | 399 | 115.7500 | 4 | partial_missing_data |
| 1 | 0.0800 | 139860 | 339 | 5 | 5 | 5 | 32 | 13.0000 | 2 | partial_missing_data |
| 1 | 0.1000 | 139860 | 105 | 4 | 2 | 1 | 20 | 7.0000 | 0 | partial_missing_data |
| 3 | 0.0300 | 139680 | 23021 | 96 | 88 | 80 | 1107 | 364.7500 | 122 | partial_missing_data |
| 3 | 0.0500 | 139680 | 8336 | 62 | 47 | 37 | 854 | 260.5000 | 35 | partial_missing_data |
| 3 | 0.0800 | 139680 | 2320 | 24 | 14 | 11 | 340 | 99.0000 | 9 | partial_missing_data |
| 3 | 0.1000 | 139680 | 1277 | 11 | 7 | 7 | 148 | 44.0000 | 3 | partial_missing_data |
| 5 | 0.0300 | 139500 | 36682 | 44 | 62 | 67 | 365 | 153.2500 | 237 | partial_missing_data |
| 5 | 0.0500 | 139500 | 16301 | 61 | 51 | 44 | 795 | 249.7500 | 79 | partial_missing_data |
| 5 | 0.0800 | 139500 | 5108 | 33 | 25 | 15 | 389 | 122.2500 | 19 | partial_missing_data |
| 5 | 0.1000 | 139500 | 2825 | 18 | 10 | 10 | 303 | 85.7500 | 9 | partial_missing_data |
| 10 | 0.0300 | 139050 | 57253 | 5 | 12 | 16 | 57 | 26.2500 | 447 | partial_missing_data |
| 10 | 0.0500 | 139050 | 33412 | 21 | 29 | 31 | 247 | 90.7500 | 191 | partial_missing_data |
| 10 | 0.0800 | 139050 | 13933 | 33 | 24 | 21 | 402 | 124.5000 | 57 | partial_missing_data |
| 10 | 0.1000 | 139050 | 8193 | 22 | 18 | 13 | 299 | 92.7500 | 35 | partial_missing_data |
| 20 | 0.0300 | 138150 | 75516 | 2 | 4 | 4 | 6 | 5.5000 | 689 | partial_missing_data |
| 20 | 0.0500 | 138150 | 52858 | 6 | 11 | 14 | 35 | 19.7500 | 395 | partial_missing_data |
| 20 | 0.0800 | 138150 | 29307 | 16 | 20 | 21 | 175 | 63.7500 | 161 | partial_missing_data |
| 20 | 0.1000 | 138150 | 19659 | 21 | 17 | 13 | 216 | 71.0000 | 105 | partial_missing_data |

## Verdict Counts

- partial_missing_data: 20

## Long-Horizon Interpretation

The gap <= horizon merge rule intentionally makes long-horizon event blocks coarser. For 20d horizons, a chain of selloff days across a quarter may count as one block. This is a conservative effective-sample rule, not a data defect.

## Boundary Flags

- external_data_fetch: no
- target_dataset_built: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no
