# Stage04 Annotation Label Gate

Stage04-WP3 is an annotation gate, not empirical validation.

It validates local prospective break annotation records, checks that record boundary flags still match the Stage04 lock, and reports whether enough future trading days are locally available for required horizons `[1, 3, 5, 10, 20]`.

## Scope

- validates the Stage04 split registry lock
- validates the Stage04-WP2 annotation-only source report
- reads `reports/stage04/prospective_break_annotation.local.jsonl` when it exists
- treats a missing local annotation ledger as `not_started`, not as a failure
- uses only the local `market_index_ohlcv` calendar when a DuckDB file is available
- writes bounded public-safe report artifacts

## Boundaries

- external data fetch: no
- model retraining: no
- HMM/HSMM training changes: no
- hazard model changes: no
- threshold tuning: no
- final holdout consumption: no
- performance metric calculation: no
- returns/outcome quality calculation: no
- decision layer or trading output: no

Local annotation ledgers stay ignored. Public reports include only bounded status fields and omit long free-text market context.

## Command

```bash
bash scripts/stage04_annotation_label_gate.sh
```

The script chooses `PYTHON_BIN`, `.venv/bin/python`, `python`, or `python3` in that order. Set `ASHARE_HMM_DB_PATH` to point at a local DuckDB file when the worktree does not contain `data/db/a_share_hmm.duckdb`.

The module can also be run directly:

```bash
python -m src.evaluation.stage04_annotation_label_gate \
  --db data/db/a_share_hmm.duckdb \
  --split-registry reports/stage04/split_registry.json \
  --wp2-report reports/stage04/stage04_wp2_break_casebook_report.json \
  --annotation-ledger reports/stage04/prospective_break_annotation.local.jsonl \
  --output reports/stage04/stage04_wp3_annotation_label_gate_report.md \
  --summary-json reports/stage04/stage04_wp3_annotation_label_gate_report.json \
  --sample-csv reports/stage04/stage04_wp3_annotation_label_gate_sample.csv \
  --no-fetch
```

## Status Semantics

- `pass`: the gate infrastructure and source locks are valid, with either no annotations yet or only complete/pending label checks.
- `defer`: annotations exist but the local DB is missing, so label completeness cannot yet be checked.
- `blocked`: split registry, WP2 source, ledger JSON, annotation boundary flags, or post-cutoff date rules failed.

`prospective_validation_status` stays conservative:

- `not_started` when no annotation records exist
- `collecting_annotations` when records exist and any required horizon is incomplete or unknown
- `labels_complete_pending_review` when all annotation records have enough future trading days
- `blocked` when lock or annotation boundaries fail
