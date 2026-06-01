# Stage 01 WP-A HMM Confidence Report

- index_id: STAGE01-WP-A-v1
- status: partial
- report_status: partial_missing_db
- db_path: data/db/a_share_hmm.duckdb
- local_db_used: false
- run_id: unresolved
- posterior_columns_found: false
- posterior_columns_used: none
- confidence_rows_generated: 0
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

- row_count: 0
- sector_count: 0
- data_range: n/a to n/a
- readiness_status: blocked
- median_posterior_max: n/a
- median_posterior_margin: n/a
- median_entropy_norm: n/a

## Confidence Bucket Distribution

| bucket | count | share |
|---|---:|---:|
| high | 0 | 0.000000 |
| medium | 0 | 0.000000 |
| low | 0 | 0.000000 |
| unclear | 0 | 0.000000 |
| missing | 0 | 0.000000 |

## Warnings

- database file not found: data/db/a_share_hmm.duckdb
