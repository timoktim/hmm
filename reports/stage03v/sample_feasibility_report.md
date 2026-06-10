# Stage03V WP0.5 Sample Feasibility Preflight

- index_id: STAGE03V-WP0.5-v1
- status: pass
- DB path: data/db/a_share_hmm_tushare_v7.duckdb
- DB availability: available
- DB opened read-only: yes
- external data fetch: no
- V7 coverage available: yes
- SW2021 L2 universe coverage: pass
- universe source status: verified_sw2021_l2_tushare_classify
- benchmark target status: available
- vol_scaled_feasibility_status: deferred_to_wp3_5

## Contract Paths

- signal_contract: configs/risk_event_signal_contract_v1.yaml
- readiness_policy: configs/readiness_policy_risk_event_v1.yaml
- universe_manifest: configs/stage03v_sw_l2_universe_manifest_v1.yaml
- ledger_template: reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
- execution_index: docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md

## Source Coverage

- v7_db_required: True
- v7_db_requirement_status: pass
- v7_coverage_available: yes
- taxonomy_provider: SW
- taxonomy_version: SW2021
- taxonomy_level: L2
- universe_source_status: verified_sw2021_l2_tushare_classify
- universe_sources: ['tushare_sw_classify']
- sw2021_l2_verified_entity_count: 131
- non_verified_or_non_l2_industry_count: 31
- industry_count_total: 162
- industry_count_after_quality_filter: 124
- min_trade_date: 2014-01-02
- max_trade_date: 2026-06-09
- coverage_start: 2014-01-02
- coverage_end: 2026-06-09
- history_continuity_status: pass_to_snapshot_effective_end
- reform_window_continuity_status: pass
- silent_entity_break_count: 2
- duplicate_entity_count: 0
- short_history_entity_count: 0
- quality_filter_exclusion_count: 38
- constituent_count_filter_status: partial_low_constituents
- workspace_metadata: {'label': 'a_share_hmm_tushare_v7.duckdb', 'db_profile': 'clean_tushare_snapshot', 'active_source': 'tushare', 'market_data_source': 'tushare', 'snapshot_start_date': '20140101', 'snapshot_end_date': '20260609', 'snapshot_effective_end_date': '20260609', 'snapshot_skipped_trade_dates': '20260610', 'build_status': 'pass', 'validation_status': 'pass'}

## Cross-Cutoff Censoring

- cross_cutoff_censored_count: 0
- cross_cutoff_excluded_count: 0
- historical_development_labeled_count: 1863874
- historical_development_unlabeled_due_to_cutoff_count: 0

## Feasibility Matrix

| horizon | threshold | historical_development_labeled_count | positive_event_count | market_event_block_count_10pct | market_event_block_count_20pct | market_event_block_count_30pct | idiosyncratic_industry_episode_count | effective_event_evidence_count_0_25 | benchmark_event_count | feasibility_verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 0.0300 | 373618 | 20003 | 193 | 146 | 119 | 3397 | 995.2500 | 76 | diagnostic_only |
| 1 | 0.0500 | 373618 | 7253 | 74 | 52 | 44 | 1130 | 334.5000 | 26 | diagnostic_only |
| 1 | 0.0800 | 373618 | 2429 | 24 | 22 | 20 | 186 | 68.5000 | 4 | diagnostic_only |
| 1 | 0.1000 | 373618 | 285 | 6 | 2 | 2 | 152 | 40.0000 | 0 | diagnostic_only |
| 3 | 0.0300 | 373370 | 66406 | 177 | 175 | 156 | 2529 | 807.2500 | 287 | diagnostic_only |
| 3 | 0.0500 | 373370 | 27811 | 121 | 94 | 81 | 2294 | 667.5000 | 102 | diagnostic_only |
| 3 | 0.0800 | 373370 | 9764 | 51 | 33 | 25 | 974 | 276.5000 | 34 | diagnostic_only |
| 3 | 0.1000 | 373370 | 5581 | 24 | 18 | 17 | 427 | 124.7500 | 16 | diagnostic_only |
| 5 | 0.0300 | 373122 | 100595 | 91 | 108 | 121 | 1045 | 369.2500 | 506 | eligible |
| 5 | 0.0500 | 373122 | 49093 | 117 | 104 | 90 | 1878 | 573.5000 | 188 | eligible |
| 5 | 0.0800 | 373122 | 18897 | 62 | 48 | 35 | 1197 | 347.2500 | 73 | eligible |
| 5 | 0.1000 | 373122 | 11541 | 35 | 22 | 21 | 757 | 211.2500 | 39 | eligible |
| 10 | 0.0300 | 372502 | 152746 | 19 | 32 | 40 | 239 | 91.7500 | 886 | eligible |
| 10 | 0.0500 | 372502 | 91478 | 45 | 59 | 62 | 566 | 200.5000 | 388 | eligible |
| 10 | 0.0800 | 372502 | 41755 | 61 | 52 | 44 | 983 | 297.7500 | 167 | eligible |
| 10 | 0.1000 | 372502 | 26387 | 43 | 34 | 25 | 784 | 230.0000 | 108 | eligible |
| 20 | 0.0300 | 371262 | 201022 | 1 | 6 | 9 | 15 | 9.7500 | 1324 | diagnostic_only |
| 20 | 0.0500 | 371262 | 142885 | 12 | 20 | 27 | 91 | 42.7500 | 752 | eligible |
| 20 | 0.0800 | 371262 | 81453 | 32 | 34 | 37 | 399 | 133.7500 | 355 | eligible |
| 20 | 0.1000 | 371262 | 56545 | 36 | 35 | 27 | 576 | 179.0000 | 249 | eligible |

## Verdict Counts

- diagnostic_only: 9
- eligible: 11

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
