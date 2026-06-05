# Stage04 Annotation Operations Runtime

`STAGE04-WP5` is an annotation operations rollup only. It summarizes local annotation ledger health, label completeness state reported by Stage04-WP3, and a bounded review queue for operator review.

WP5 does not require a local DuckDB. It does not recompute future label completeness from market data; it consumes the latest Stage04-WP3 report fields instead.

This tool does not validate predictive performance. It does not compute returns or outcomes, create a decision layer, provide trading output, tune thresholds, retrain models, fetch external data, or consume final holdout.

Local annotation ledgers stay ignored:

```text
reports/stage04/prospective_break_annotation.local.jsonl
```

## Outputs

- `reports/stage04/stage04_wp5_annotation_operations_report.md`
- `reports/stage04/stage04_wp5_annotation_operations_report.json`
- `reports/stage04/stage04_wp5_annotation_operations_sample.csv`

The sample CSV is bounded to the public-safe review queue fields. It excludes full `observed_market_context` text and does not include performance, returns, outcomes, score, or output-layer fields.

## Run

```bash
bash scripts/stage04_annotation_operations.sh
```

Equivalent module call:

```bash
python -m src.evaluation.stage04_annotation_operations \
  --split-registry reports/stage04/split_registry.json \
  --wp3-report reports/stage04/stage04_wp3_annotation_label_gate_report.json \
  --wp4-report reports/stage04/stage04_wp4_annotation_capture_report.json \
  --annotation-ledger reports/stage04/prospective_break_annotation.local.jsonl \
  --output reports/stage04/stage04_wp5_annotation_operations_report.md \
  --summary-json reports/stage04/stage04_wp5_annotation_operations_report.json \
  --sample-csv reports/stage04/stage04_wp5_annotation_operations_sample.csv \
  --no-fetch
```

## Review Queue

The review queue is bounded to 100 rows and prioritizes:

1. boundary validation issues,
2. label-complete records,
3. records waiting for required label horizons,
4. records awaiting annotation status context.

The queue is an operations aid for local annotation collection. It is not a ranking, sizing, action, or portfolio output.
