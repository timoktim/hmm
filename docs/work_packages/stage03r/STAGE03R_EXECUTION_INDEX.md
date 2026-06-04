# STAGE03R_EXECUTION_INDEX

Status: active
Route anchor: `docs/roadmap/STAGE03R_ROUTE_ADJUSTMENT_20260603.md`
Preflight evidence: PR #38, `Stage03PreflightVerdict: PASS`, full pytest `400 passed, 2 skipped, 27 warnings`
WP0 evidence: PR #39, scope freeze and signal contract accepted
WP1 evidence: PR #40, exit target dataset accepted
WP2 evidence: PR #41, target leakage/purge tests accepted
WP3 evidence: PR #42, logistic hazard baseline accepted

## Purpose

Stage03R is the next development mainline after Stage03 preflight. It promotes Duration Hazard to the primary lifecycle exit signal and freezes HSMM as a lifecycle interpretation layer.

Stage03R must remain hazard-first and evidence-gated. Do not restart the older path of trying to make HSMM numeric `p_exit` broadly usable before hazard work.

## Stage03R route

```text
HMM causal regime context
+ HSMM lifecycle interpretation layer
+ Duration Hazard as primary lifecycle exit engine
+ ordinal fallback and abstain when sample support is insufficient
+ risk/calibration validation before any decision surface
```

## Stage03R package sequence

| index_id | package | status | branch | purpose |
|---|---|---|---|---|
| STAGE03R-WP0 | Scope Freeze and Signal Contract | archived | stage03r/wp0-scope-freeze-signal-contract | freeze HSMM / hazard responsibilities and field categories |
| STAGE03R-WP1 | Exit Target Dataset v1 | archived | stage03r/wp1-exit-target-dataset-v1 | causal, censored, purged exit target dataset |
| STAGE03R-WP2 | Target Leakage and Purge Tests | archived | stage03r/wp2-target-leakage-purge-tests | synthetic leakage/censoring/purge/embargo tests |
| STAGE03R-WP3 | Logistic Hazard Baseline | archived | stage03r/wp3-logistic-hazard-baseline | lightweight per-horizon logistic hazard |
| STAGE03R-WP4 | Age-Bucket Baseline | active | stage03r/wp4-age-bucket-baseline | empirical baseline for hazard promotion comparison |
| STAGE03R-WP5 | Isotonic Calibration | blocked_until_wp4 | stage03r/wp5-isotonic-calibration | calibration on validation folds only |
| STAGE03R-WP6 | Hazard Readiness Matrix | blocked_until_wp5 | stage03r/wp6-hazard-readiness-matrix | state × horizon × age_bucket readiness status |
| STAGE03R-WP7 | Hazard vs HSMM Report | blocked_until_wp6 | stage03r/wp7-hazard-vs-hsmm-report | compare hazard to HSMM raw p_exit and age-bucket baseline |
| STAGE03R-WP8 | Risk Validation Protocol | blocked_until_wp6 | stage03r/wp8-risk-validation-protocol | pre-register risk metrics and held-out final split discipline |
| STAGE03R-WP9 | Data Quality CI Invariants | blocked_until_wp3 | stage03r/wp9-data-quality-ci-invariants | persistent CI checks for ingestion and target leakage invariants |
| STAGE03R-WP10 | Stage03R Final Gate | blocked_until_wp1_to_wp9 | stage03r/wp10-stage03r-final-gate | final PASS/BLOCKED verdict |

## Execution rules

1. Execute only active packages.
2. Do not expand HSMM numerical probability responsibilities.
3. Do not use HSMM raw/calibrated `p_exit` as a decision input by default.
4. Duration Hazard v1 must be simple: logistic hazard, isotonic calibration, age-bucket baseline, readiness matrix, ordinal fallback.
5. Competing-risks hazard, full BOCPD, heavy-tail HMM, GH emission, VAR-HSMM, deep switching state-space, and full decision engine are explicitly out of Stage03R v1.
6. Every package must use causal walk-forward or explicit research-only mode.
7. Every promotion claim must include sample support, calibration status, readiness status, and fallback reason.
8. Final held-out testing discipline must be preserved. Do not tune repeatedly on final holdout.
9. Target labels may look forward only for label construction; feature columns and state inputs must not use post-trade-date information.
10. WP3 must emit raw logistic hazard baseline only. `usable_probability` is forbidden before calibration/readiness packages.
11. WP4 must emit empirical age-bucket baseline only. Sparse slices must stay ordinal-only or abstain; WP5 calibration remains blocked until WP4 is merged.

## Pass criteria for Stage03R

Stage03R can pass only if:

- `exit_target_dataset_v1` passes causal, censoring, purge, and embargo audit;
- hazard reaches at least stable `ordinal_only` on core horizons;
- any `usable_probability` slice does not worsen Brier after calibration;
- age-bucket baseline is explicitly compared;
- `insufficient_sample` is emitted instead of pseudo-probability;
- risk validation protocol and held-out final split discipline are implemented;
- data-quality CI minimum set is active.

## Failure policy

If hazard does not stand up, do not return to expanding HSMM numerical probability. Downgrade output granularity, keep ordinal tendency, expand abstain, merge sparse state/horizon/age buckets, and record sample-ceiling limitations.

## Revision log

| date | change | by |
|---|---|---|
| 2026-06-03 | Activated Stage03R WP0 after Stage03 preflight PASS via PR #38. | ChatGPT |
| 2026-06-03 | Archived WP0 and activated WP1 exit target dataset after PR #39 merge. | ChatGPT |
| 2026-06-04 | Archived WP1 and activated WP2 target leakage/purge tests after PR #40 merge. | ChatGPT |
| 2026-06-04 | Archived WP2 and activated WP3 logistic hazard baseline after PR #41 merge. | ChatGPT |
| 2026-06-04 | Archived WP3 and activated WP4 age-bucket baseline after PR #42 merge. | ChatGPT |
