# Stage03V WP1 Risk Event Target Support

- index_id: STAGE03V-WP1-v1
- status: pass
- source_db_path: data/db/a_share_hmm_tushare_v7.duckdb
- feasibility_report_status: pass
- v7_coverage_available: yes
- sw2021_l2_universe_coverage: pass
- entity_count_after_quality_filter: 124
- entity_count_after_silent_break_handling: 124
- silent_entity_break_count: 2
- silent_entity_break_handling: excluded
- target_row_count: 7474840
- historical_development_labeled_count: 7455496
- cross_cutoff_censored_count: 0
- sample_csv_row_count: 500
- persistent_db_table_written: no

## Boundary Flags

- external_data_fetch: no
- target_dataset_built: yes
- persistent_db_table_written: no
- model_training: no
- probability_calibration: no
- readiness_assigned: no
- holdout_consumed: no
- HMM_HSMM_training_modified: no
- stage03v2_implemented: no
- stage03v3_implemented: no

## Silent Entity Breaks

- industry:医疗美容 医疗美容 max_gap_days=140 handling=silent_break_already_excluded_by_quality_filter
- industry:油气开采Ⅱ 油气开采Ⅱ max_gap_days=99 handling=silent_break_already_excluded_by_quality_filter

## Slice Support Summary

- horizon=1 threshold=0.03 usage=diagnostic_only rows=373742 labeled=373618 positives=20003
- horizon=1 threshold=0.05 usage=diagnostic_only rows=373742 labeled=373618 positives=7253
- horizon=1 threshold=0.08 usage=diagnostic_only rows=373742 labeled=373618 positives=2429
- horizon=1 threshold=0.1 usage=diagnostic_only rows=373742 labeled=373618 positives=285
- horizon=3 threshold=0.03 usage=diagnostic_only rows=373742 labeled=373370 positives=66406
- horizon=3 threshold=0.05 usage=diagnostic_only rows=373742 labeled=373370 positives=27811
- horizon=3 threshold=0.08 usage=diagnostic_only rows=373742 labeled=373370 positives=9764
- horizon=3 threshold=0.1 usage=diagnostic_only rows=373742 labeled=373370 positives=5581
- horizon=5 threshold=0.03 usage=eligible rows=373742 labeled=373122 positives=100595
- horizon=5 threshold=0.05 usage=eligible rows=373742 labeled=373122 positives=49093
- horizon=5 threshold=0.08 usage=eligible rows=373742 labeled=373122 positives=18897
- horizon=5 threshold=0.1 usage=eligible rows=373742 labeled=373122 positives=11541
- horizon=10 threshold=0.03 usage=eligible rows=373742 labeled=372502 positives=152746
- horizon=10 threshold=0.05 usage=eligible rows=373742 labeled=372502 positives=91478
- horizon=10 threshold=0.08 usage=eligible rows=373742 labeled=372502 positives=41755
- horizon=10 threshold=0.1 usage=eligible rows=373742 labeled=372502 positives=26387
- horizon=20 threshold=0.03 usage=diagnostic_only rows=373742 labeled=371262 positives=201022
- horizon=20 threshold=0.05 usage=eligible rows=373742 labeled=371262 positives=142885
- horizon=20 threshold=0.08 usage=eligible rows=373742 labeled=371262 positives=81453
- horizon=20 threshold=0.1 usage=eligible rows=373742 labeled=371262 positives=56545
