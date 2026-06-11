# STAGE03V_FIX1_contract_repairs

Stage: 03V / Volatility and downside-risk hazard

Work package: FIX1

Index id: STAGE03V-FIX1-v1

Suggested branch: `stage03v/fix1-contract-repairs`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_FIX1_contract_repairs.md`

Date: 2026-06-11

## Background

The Stage03V1 post-completion audit (2026-06-11) found that all WP4-WP6 empirical
artifacts were produced against `reports/stage03v/purge_embargo_fold_plan.json`,
whose three folds cover only 2014-01-13 to 2014-02-12. That defect is repaired by
`STAGE03V-RERUN1-v1`, not by this package.

This package repairs the contract-compliance gaps found in the same audit so that
the RERUN1 re-execution consumes corrected evaluation code. It is code-and-tests
only. It must not re-run any empirical pipeline and must not regenerate any
`reports/stage03v/` evidence artifact.

## Objective

Close the following audit findings:

1. Missing hard ban: validation-fold `market_event_block_count < 2` does not
   currently forbid `usable_probability_candidate`.
2. Missing Brier-retention check: calibration that worsens Brier versus the
   uncalibrated identity reference can still reach `usable_probability_candidate`.
3. Missing date-aware sample weighting in the logistic hazard fit, which the
   route plan requires, with no recorded waiver.
4. Holdout-consumption counters are tracked but do not hard-block report status
   when any counter is greater than zero.
5. Cross-cutoff censored rows do not force `metrics = None` / `event_label = None`
   in the censoring branch (defence-in-depth for the permanent-censoring
   invariant).
6. The actual calibration-split semantics (time-ordered first fraction of the
   validation window) are not recorded in the signal contract, leaving ambiguity
   against the "calibrate only on validation folds" wording.

## Stage boundary

Allowed:

- Modify `src/evaluation/stage03v_calibration_readiness.py`,
  `src/evaluation/stage03v_logistic_hazard.py`,
  `src/evaluation/stage03v_risk_validation.py`,
  `src/evaluation/stage03v_risk_target_dataset.py`.
- Update `configs/risk_event_signal_contract_v1.yaml` and
  `configs/readiness_policy_risk_event_v1.yaml` with the new mandatory checks and
  the calibration-split semantics record.
- Add or extend tests under `tests/`.

Forbidden:

- Re-running WP0.5-WP6 pipelines or regenerating any `reports/stage03v/`
  evidence artifact.
- Modifying or regenerating `reports/stage03v/purge_embargo_fold_plan.json`
  (RERUN1 scope).
- Changing target definitions, horizons, thresholds, or the fixed-threshold
  mainline.
- Training new model families.
- Consuming or inspecting prospective final holdout data
  (`trade_date >= 2026-06-11`).
- Fetching external data.
- Creating UI, decision, trading, buy/sell, or sizing outputs.

## Required changes

### F1. Market-event-block hard ban

In the readiness-category assignment of
`src/evaluation/stage03v_calibration_readiness.py`:

```text
if validation-fold market_event_block_count < 2 for the slice:
    readiness_category cannot be usable_probability_candidate
    emit reason: market_event_block_evidence_below_minimum
```

The block count must be computed on validation-fold trade dates only, using the
primary 20% event-share definition from the signal contract.

### F2. Brier retention versus identity

```text
brier_retention = brier_identity_uncalibrated - brier_calibrated
if brier_retention < 0:
    readiness_category cannot be usable_probability_candidate
    emit reason: calibration_worsened_brier_score
```

Persist `brier_identity_uncalibrated`, `brier_calibrated`, and
`brier_retention` in the slice metrics output schema.

### F3. Date-aware sample weighting

Implement date-aware sample weighting in
`src/evaluation/stage03v_logistic_hazard.py` so that each trade date contributes
bounded total weight regardless of entity count, for example:

```text
row_weight = 1 / rows_on_same_trade_date_in_train_fold
```

combined multiplicatively with the existing class-balance handling. If the
implementation is explicitly waived instead, the waiver and its reason must be
recorded in `configs/risk_event_signal_contract_v1.yaml` under
`date_aware_weighting_waiver`, and the report schema must expose
`date_aware_weighting_status`. Silent absence is not acceptable.

### F4. Holdout-consumption hard block

In WP5 and WP6 report builders:

```text
if any holdout consumption counter > 0:
    report status = blocked_holdout_consumed
    ci gate must fail
```

### F5. Cross-cutoff censoring defence-in-depth

In the censoring branch of
`src/evaluation/stage03v_risk_target_dataset.py`, force
`metrics = None` and `event_label = None` whenever
`censoring_status = cross_cutoff_censored`, so a future code path cannot emit a
labeled row by accident. Keep the existing no-backfill regression test green and
extend it to assert the forced fields.

### F6. Calibration-split semantics record

Record in `configs/risk_event_signal_contract_v1.yaml`:

```text
calibration_split_policy:
  source: validation_fold_rows_only
  method: time_ordered_prefix_fraction
  calibration_fraction: 0.5
  evaluation_rows: time_ordered_suffix_complement
  independent_calibration_fold: false
```

This documents the implemented semantics so the contract and the code agree.

## Required tests

```text
tests/test_stage03v_fix1_market_block_ban.py
tests/test_stage03v_fix1_brier_retention.py
tests/test_stage03v_fix1_date_weighting.py
tests/test_stage03v_fix1_holdout_hard_block.py
extended: tests/test_stage03v_path_targets.py (forced censoring fields)
extended: tests/test_stage03v_contracts.py (calibration_split_policy present)
```

Each test must construct a synthetic case that fails without the fix and passes
with it.

## Acceptance

- [ ] All six findings F1-F6 are closed or explicitly waived in-contract (F3 only).
- [ ] New and extended tests pass; full not-slow suite result is reported.
- [ ] No `reports/stage03v/` evidence artifact changed in the diff.
- [ ] No fold plan changed in the diff.
- [ ] Prospective holdout untouched.
- [ ] No new model family, no decision output.

## Return contract

Report: PR link, commands run, created/updated files, and explicit yes/no flags:

```text
external data fetch
empirical pipeline rerun
fold plan modified
reports regenerated
holdout consumed
HMM/HSMM training modified
decision or trading output
```
