# Stage04-WP2 Break Diagnostic Casebook

Stage04-WP2 turns the Stage04-WP1 structural break diagnostic into a bounded,
public-safe casebook plus a prospective annotation template.

This package is annotation infrastructure only and does not provide trading,
sizing, ranking, or decision output.

## Boundaries

- External data fetch: no.
- Model retraining: no.
- HMM/HSMM training changes: no.
- Hazard model changes: no.
- Threshold tuning: no.
- Final holdout consumption: no.
- DuckDB schema migration: no.
- DuckDB, WAL, cache, full diagnostic CSV, and local annotation ledger commits: no.

## Inputs

- `reports/stage04/split_registry.json`
- `reports/stage04/stage04_wp1_break_detector_report.json`
- Local read-only DuckDB at `data/db/a_share_hmm.duckdb`, or `$ASHARE_HMM_DB_PATH`

The module imports Stage04-WP1 and regenerates the full diagnostic result in
memory when the local DuckDB exists. It does not use the committed WP1 sample CSV
as the full source of truth because that file is bounded.

If the local DuckDB is missing, the report status is `blocked`; the script writes
to a temporary directory so committed public reports are not overwritten.

## Episode Rules

Episodes are contiguous rows where `break_warning_level` is one of:

- `watch`
- `elevated`
- `high`

An episode ends when the warning level returns to `normal` or
`insufficient_data`, or when the date gap exceeds the configured continuity
guard.

Each episode records severity, start and end date, duration, component labels,
dominant components, and compact diagnostic extrema. The public sample is
bounded and sorted by severity, then recency.

## Outputs

- `reports/stage04/stage04_wp2_break_casebook_report.md`
- `reports/stage04/stage04_wp2_break_casebook_report.json`
- `reports/stage04/stage04_wp2_break_casebook_sample.csv`
- `reports/stage04/prospective_break_annotation.template.jsonl`

Local annotations must stay ignored:

- `reports/stage04/prospective_break_annotation.local.jsonl`
- `reports/stage04/daily_break_annotations*.jsonl`

## Run

```bash
python -m src.evaluation.stage04_break_casebook \
  --db data/db/a_share_hmm.duckdb \
  --split-registry reports/stage04/split_registry.json \
  --wp1-summary reports/stage04/stage04_wp1_break_detector_report.json \
  --output reports/stage04/stage04_wp2_break_casebook_report.md \
  --summary-json reports/stage04/stage04_wp2_break_casebook_report.json \
  --sample-csv reports/stage04/stage04_wp2_break_casebook_sample.csv \
  --annotation-template reports/stage04/prospective_break_annotation.template.jsonl \
  --no-fetch
```

Or use:

```bash
bash scripts/stage04_break_casebook.sh
```
