# Stage04 Annotation Capture Runtime

`STAGE04-WP4` previews or appends local annotation records for prospective break diagnostic review.

The default mode is `dry-run`. In dry-run mode the command writes only bounded public report artifacts and does not write the local ledger.

Append mode is explicit. It writes exactly one annotation record to:

```text
reports/stage04/prospective_break_annotation.local.jsonl
```

The append target must be ignored by git. If the local ledger is not confirmed ignored, the command blocks before writing.

This tool does not evaluate outcomes or performance. It does not compute returns, create a decision layer, provide trading output, tune thresholds, retrain models, fetch external data, or consume final holdout.

## Outputs

- `reports/stage04/stage04_wp4_annotation_capture_report.md`
- `reports/stage04/stage04_wp4_annotation_capture_report.json`
- `reports/stage04/stage04_wp4_annotation_capture_sample.jsonl`

The sample JSONL contains a sanitized candidate public preview when a candidate is created or appended. It does not include long `observed_market_context` text.

## Dry-Run Latest WP1

```bash
bash scripts/stage04_annotation_capture.sh
```

Equivalent module call:

```bash
python -m src.evaluation.stage04_annotation_capture \
  --split-registry reports/stage04/split_registry.json \
  --wp1-report reports/stage04/stage04_wp1_break_detector_report.json \
  --wp2-report reports/stage04/stage04_wp2_break_casebook_report.json \
  --wp3-report reports/stage04/stage04_wp3_annotation_label_gate_report.json \
  --annotation-ledger reports/stage04/prospective_break_annotation.local.jsonl \
  --output reports/stage04/stage04_wp4_annotation_capture_report.md \
  --summary-json reports/stage04/stage04_wp4_annotation_capture_report.json \
  --sample-jsonl reports/stage04/stage04_wp4_annotation_capture_sample.jsonl \
  --mode dry-run \
  --source latest_wp1 \
  --no-fetch
```

`latest_wp1` uses `latest_break_warning` from the Stage04-WP1 report. It creates a candidate only for `watch`, `elevated`, or `high` warning levels, and still blocks any diagnostic date that is not strictly after the evidence cutoff.

## Dry-Run Casebook Episode

```bash
STAGE04_ANNOTATION_CAPTURE_SOURCE=casebook_episode \
STAGE04_ANNOTATION_EPISODE_ID=stage04-wp2-episode-001 \
bash scripts/stage04_annotation_capture.sh
```

The casebook source uses the selected episode `end_date` as the diagnostic trade date, `peak_warning_level` as the warning level, and the peak component stress labels when available.

## Append Manual Record

```bash
STAGE04_ANNOTATION_CAPTURE_MODE=append \
STAGE04_ANNOTATION_CAPTURE_SOURCE=manual \
STAGE04_ANNOTATION_DIAGNOSTIC_TRADE_DATE=2026-05-29 \
STAGE04_ANNOTATION_BREAK_WARNING_LEVEL=watch \
STAGE04_ANNOTATION_COMPONENT_STRESS_LABELS=market:medium \
STAGE04_ANNOTATION_AVAILABLE_COMPONENT_COUNT=1 \
bash scripts/stage04_annotation_capture.sh
```

Manual mode requires diagnostic trade date, warning level, component stress labels, and available component count. Optional operator note fields are accepted through CLI flags or environment variables, but public report artifacts only expose whether observed context was present and a bounded character count.
