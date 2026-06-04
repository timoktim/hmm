# Stage03R Research Console P0

## Scope

This is a local research-only Streamlit prototype for observing committed Stage03R outputs and collecting Stage04 forward-review annotations.

It does not fetch external data, retrain models, tune thresholds, produce trading guidance, produce position guidance, or create any decision output.

## Run

```bash
.venv/bin/streamlit run src/ui/stage03r_research_console.py
```

The UI is standalone and does not require the private DuckDB database.

## Public Inputs

The UI reads committed reports from `reports/stage03r/`:

- `stage03r_final_gate_report.json`
- `hazard_readiness_matrix_report.json`
- `hazard_vs_hsmm_report.json`
- `risk_validation_protocol.json`
- `data_quality_ci_report.json`
- `final_holdout_artifact.json`

It also checks `reports/stage04/split_registry.json` when present. On branches where Stage04 split registry is not merged yet, the UI shows the registry as missing and continues.

## Optional Local DB

If `data/db/a_share_hmm.duckdb` exists, the data layer opens it read-only and only reads aggregate row counts from known tables. If the DB is missing, the UI still runs from committed reports.

## Annotation File

Manual research notes are appended locally to:

```text
data/local_annotations/stage04_research_notes.jsonl
```

This path is gitignored. Annotation rows include:

- `created_at`
- `sector_code`
- `trade_date`
- `horizon_days`
- `human_label`: `watch`, `ignore`, `investigate`, or `paper_trade`
- `confidence`: `low`, `medium`, or `high`
- `note`
- `model_context_snapshot`

## Displayed Status

The console summarizes:

- final gate verdict
- engineering gate PASS and empirical promotion DEFER
- readiness counts
- usable probability versus baseline-only counts by horizon
- hazard as locally usable but not broadly promoted
- HSMM lifecycle state as interpretation-only
- final holdout and prospective validation status
- pending review horizons: 1, 3, 5, 10, 20
- Stage04 split registry status when available

No future-looking outcome computation is performed unless explicitly requested in a later work package.
