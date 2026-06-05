# STAGE04_EXECUTION_INDEX

Status: active
Stage03R evidence boundary: PR #51, `final_holdout_artifact_v1`, `final_verdict=DEFER`

## Purpose

Stage04 starts after Stage03R produced engineering-safe but empirically deferred hazard evidence.
Its first task is to lock a prospective validation registry so future holdout validation can prove
non-overlap before final holdout consumption.

## Stage04 package sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| STAGE04-WP0 | Split Registry and Prospective Validation Lock | archived | stage04/wp0-split-registry-prospective-validation-lock | freeze Stage03R evidence boundary and define prospective holdout eligibility |
| STAGE04-WP1 | Structural Break Diagnostic | archived | codex/stage04-wp1-break-detector-v1 | compute read-only, low-cost break warning diagnostics |
| STAGE04-WP2 | Break Diagnostic Casebook and Annotation Protocol | archived | codex/stage04-wp2-break-casebook-annotation-protocol | turn WP1 diagnostics into a bounded public-safe casebook and prospective annotation schema |
| STAGE04-WP3 | Annotation Ledger Label Completeness Gate | archived | codex/stage04-wp3-annotation-ledger-label-gate | validate local annotation records and required-horizon label completeness |
| STAGE04-WP4 | Prospective Annotation Capture CLI | active | codex/stage04-wp4-annotation-capture-cli | preview or append local prospective annotation records to the ignored ledger |

## Execution rules

1. Stage04 packages must not fetch external data unless a later package explicitly allows it.
2. Stage04 packages must not retrain HMM, HSMM, or hazard models unless a later package explicitly allows it.
3. Stage04 packages must not tune thresholds.
4. Stage04 packages must not consume final holdout.
5. Future holdout candidates must start strictly after the frozen Stage03R evidence cutoff date.
6. Future holdout labels must be complete for horizons `[1, 3, 5, 10, 20]` before empirical validation.
7. Prospective validation ledger daily records must stay local/ignored unless explicitly promoted by a later package.
8. No decision layer, trading output, sizing, or recommendation output may be created by Stage04 WP0-WP3.

## WP0 deliverables

- `reports/stage04/split_registry.json`
- `reports/stage04/split_registry.md`
- `reports/stage04/prospective_validation_ledger.template.jsonl`
- `src/evaluation/stage04_split_registry.py`
- `tests/test_stage04_split_registry.py`

## WP1 deliverables

- `reports/stage04/stage04_wp1_break_detector_report.md`
- `reports/stage04/stage04_wp1_break_detector_report.json`
- `reports/stage04/stage04_wp1_break_detector_sample.csv`
- `src/evaluation/stage04_break_detector.py`
- `tests/test_stage04_break_detector.py`
- `docs/runtime/STAGE04_BREAK_DETECTOR.md`
- `scripts/stage04_break_detector.sh`

## WP2 deliverables

- `reports/stage04/stage04_wp2_break_casebook_report.md`
- `reports/stage04/stage04_wp2_break_casebook_report.json`
- `reports/stage04/stage04_wp2_break_casebook_sample.csv`
- `reports/stage04/prospective_break_annotation.template.jsonl`
- `src/evaluation/stage04_break_casebook.py`
- `tests/test_stage04_break_casebook.py`
- `docs/runtime/STAGE04_BREAK_CASEBOOK.md`
- `scripts/stage04_break_casebook.sh`

## WP3 deliverables

- `reports/stage04/stage04_wp3_annotation_label_gate_report.md`
- `reports/stage04/stage04_wp3_annotation_label_gate_report.json`
- `reports/stage04/stage04_wp3_annotation_label_gate_sample.csv`
- `src/evaluation/stage04_annotation_label_gate.py`
- `tests/test_stage04_annotation_label_gate.py`
- `docs/runtime/STAGE04_ANNOTATION_LABEL_GATE.md`
- `scripts/stage04_annotation_label_gate.sh`

## WP4 deliverables

- `reports/stage04/stage04_wp4_annotation_capture_report.md`
- `reports/stage04/stage04_wp4_annotation_capture_report.json`
- `reports/stage04/stage04_wp4_annotation_capture_sample.jsonl`
- `src/evaluation/stage04_annotation_capture.py`
- `tests/test_stage04_annotation_capture.py`
- `docs/runtime/STAGE04_ANNOTATION_CAPTURE.md`
- `scripts/stage04_annotation_capture.sh`

## Revision log

| date | change | by |
|---|---|---|
| 2026-06-04 | Activated Stage04 WP0 after PR #51 merged the Stage03R WP10.1 final holdout candidate and preserved empirical DEFER. | ChatGPT |
| 2026-06-04 | PR #52 accepted Stage04 WP0 split registry and prospective validation lock. | ChatGPT |
| 2026-06-05 | PR #55 accepted Stage04 WP1 structural break diagnostic; activated Stage04 WP2 break casebook annotation protocol. | ChatGPT |
| 2026-06-05 | PR #57 accepted Stage04 WP2 break casebook annotation protocol; activated Stage04 WP3 annotation label completeness gate. | ChatGPT |
| 2026-06-05 | PR #58 accepted Stage04 WP3 annotation label completeness gate; activated Stage04 WP4 prospective annotation capture CLI. | ChatGPT |
