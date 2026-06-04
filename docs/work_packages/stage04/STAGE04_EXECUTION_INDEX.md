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
| STAGE04-WP0 | Split Registry and Prospective Validation Lock | active | stage04/wp0-split-registry-prospective-validation-lock | freeze Stage03R evidence boundary and define prospective holdout eligibility |

## Execution rules

1. WP0 must not fetch external data.
2. WP0 must not retrain HMM, HSMM, or hazard models.
3. WP0 must not tune thresholds.
4. WP0 must not consume final holdout.
5. Future holdout candidates must start strictly after the frozen Stage03R evidence cutoff date.
6. Future holdout labels must be complete for horizons `[1, 3, 5, 10, 20]` before empirical validation.
7. Prospective validation ledger daily records must stay local/ignored unless explicitly promoted by a later package.
8. No decision surface, trading output, sizing, or recommendation output may be created by WP0.

## WP0 deliverables

- `reports/stage04/split_registry.json`
- `reports/stage04/split_registry.md`
- `reports/stage04/prospective_validation_ledger.jsonl`
- `src/evaluation/stage04_split_registry.py`
- `tests/test_stage04_split_registry.py`

## Revision log

| date | change | by |
|---|---|---|
| 2026-06-04 | Activated Stage04 WP0 after PR #51 merged the Stage03R WP10.1 final holdout candidate and preserved empirical DEFER. | ChatGPT |
