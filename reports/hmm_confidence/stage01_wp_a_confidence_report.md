# Stage 01 WP-A HMM Confidence Report

- index_id: STAGE01-WP-A-v1
- status: pass
- report_status: pass
- db_path: data/db/a_share_hmm.duckdb
- local_db_used: true
- run_id: bea7ff20106a
- posterior_columns_found: true
- posterior_columns_used: prob_trend_up, prob_neutral, prob_risk_off
- confidence_rows_generated: 584981
- external_data_fetch: false
- training_algorithm_modified: false

## Semantics

HMM posterior probabilities are state confidence diagnostics only. They are not return probability, rising probability, falling probability, profit probability, buy probability, or sell probability.

## Threshold Defaults

| bucket | rule | readiness |
|---|---|---|
| high | posterior_max >= 0.70, posterior_margin >= 0.25, entropy_norm <= 0.65 | internal_only |
| medium | posterior_max >= 0.55, posterior_margin >= 0.12, entropy_norm <= 0.85 | internal_only |
| unclear | posterior_margin < 0.08 or entropy_norm >= 0.90 | research_only |
| low | valid posterior vector below medium threshold | research_only |
| missing | missing or invalid posterior vector | blocked |

## Run Summary

- row_count: 584981
- sector_count: 464
- data_range: 2020-02-07 00:00:00 to 2026-05-28 00:00:00
- readiness_status: internal_only
- median_posterior_max: 0.999817
- median_posterior_margin: 0.999648
- median_entropy_norm: 0.001636

## Confidence Bucket Distribution

| bucket | count | share |
|---|---:|---:|
| high | 561174 | 0.959303 |
| medium | 16755 | 0.028642 |
| low | 2437 | 0.004166 |
| unclear | 4615 | 0.007889 |
| missing | 0 | 0.000000 |

## Warnings

- none
