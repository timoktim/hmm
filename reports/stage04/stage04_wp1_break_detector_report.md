# Stage04-WP1 Structural Break Diagnostic

- status: pass
- report_version: stage04_wp1_break_detector_v1
- index_id: STAGE04-WP1
- latest_break_warning: watch
- latest_trade_date: 2026-05-28

## Boundary Flags
- external_data_fetch: no
- model_retrained: no
- hmm_hsmm_training_changed: no
- hazard_model_changed: no
- final_holdout_consumed: no
- decision_engine_output: no
- duckdb_schema_changed: no
- duckdb_committed: no

## Component Availability
- market_volatility: available=True rows=1549 available_rows=1519 latest_status=normal
- breadth: available=True rows=1547 available_rows=1522 latest_status=normal
- sector_dispersion: available=True rows=1550 available_rows=1528 latest_status=watch
- hmm_confidence: available=True rows=953 available_rows=933 latest_status=normal

## Warning Level Counts
- elevated: 454
- high: 72
- insufficient_data: 26
- normal: 513
- watch: 485

## Latest Diagnostic Snapshot
- trade_date: 2026-05-28
- break_warning_level: watch
- available_component_count: 2
- market_volatility_z: -0.27585084470733945
- market_return_1d: 0.0012306012220439921
- market_volatility_status: normal
- breadth_up_ratio_z: None
- breadth_above_ma20_z: None
- breadth_amount_z: None
- breadth_status: None
- sector_dispersion_z: 1.443994899120726
- sector_dispersion_status: watch
- hmm_confidence_status: None
- hmm_max_prob_mean: None
- hmm_margin_mean: None
- hmm_entropy_mean: None
- component_stress_labels: breadth:insufficient_history;sector:medium;hmm_confidence:insufficient_history

## Causal Sanity
- rolling_window: 60
- min_periods: 20
- rolling_baseline_excludes_current_row: yes
- future_rows_used: no
- hmm_future_rows_excluded: 0

## Data Quality
- db_available: yes
- db_path: data/db/a_share_hmm.duckdb
- missing_tables: []
- unavailable_components: []
- diagnostic_rows: 1550
- latest_trade_date: 2026-05-28

## Recommended Next Stage
Use Stage04-WP1 diagnostics for prospective annotation review before any higher-cost break model.
