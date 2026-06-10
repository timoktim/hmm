# STAGE03V_ROUND3_FINAL_ADDENDUM_20260610

Status: approved_addendum_for_wp0

Parent route: `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`

This addendum is binding for Stage03V-WP0 and later Stage03V1 work packages. It records the final review additions required before WP0 execution.

## 1. Permanent cross-cutoff censoring

Problem: historical-development rows near the Stage03V information cutoff can have target observation windows that extend beyond the cutoff. If a target builder is rerun months later, those rows could be silently backfilled using prospective holdout prices.

Hard rule:

```text
For split_role = historical_development:
  target_observation_end_date must be <= information_cutoff_date.

If target_observation_end_date > information_cutoff_date:
  the row must be permanently marked cross_cutoff_censored or excluded from the development dataset.

A cross-cutoff censored row must not be backfilled in historical_development after future prices become available.
```

Required policy fields:

```text
cross_cutoff_censoring_policy: permanent
information_cutoff_date: 2026-06-10
label_cutoff_date: 2026-06-10
allowed_cross_cutoff_handling: [cross_cutoff_censored, exclude_with_reason]
forbidden_cross_cutoff_handling: [backfill_after_cutoff, fill_from_holdout_prices]
preferred: keep the row with censoring_status = cross_cutoff_censored and event_label = null
fallback: exclude the row with explicit exclusion_reason = cross_cutoff_target_window
```

WP1 acceptance must include:

```text
historical-development rows satisfy target_observation_end_date <= 2026-06-10
or remain permanently cross-cutoff censored / excluded.
```

WP2 acceptance must include a rerun regression test:

```text
build with data through 2026-06-10
append post-cutoff prices
rebuild
assert cross-cutoff historical-development rows remain censored or excluded
```

## 2. Benchmark downside target must be pre-registered

WP0 must pre-register the benchmark downside target used by WP0.5 market-block counting.

Default benchmark target:

```text
benchmark_target_name: broad_a_share_downside_event
preferred_benchmark_name: CSI All Share / 中证全指
source_table: market_benchmark_ohlcv
target_kind: downside_event
path_metric: MAE
horizon_policy: same_as_slice
threshold_policy: same_as_slice
fallback_if_unavailable: benchmark_target_unavailable
benchmark_selection_after_modeling: forbidden
```

If the configured benchmark is unavailable, WP0.5 must report `benchmark_target_unavailable` and market blocks must be computed from cross-sectional event-share only.

## 3. Readiness evidence counts must use validation-fold rows

WP0.5 may report feasibility counts across historical development.

WP5 `usable_probability` readiness must use validation-fold evidence counts only.

Required readiness policy fields:

```text
wp0_5_feasibility_counts_may_use: historical_development
wp5_usable_probability_evidence_counts_must_use: validation_fold_rows_only
training_period_evidence_cannot_satisfy_usable_probability: true
```

A slice cannot be marked `usable_probability` if its qualifying market-block or effective-event evidence exists only in the training period.

## 4. Stage03V holdout registration remains unchanged

Stage03V must use its own information cutoff and holdout start:

```text
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
```

Stage04 prospective-validation ledger mechanics may be reused, but Stage03V must not inherit Stage04's 2026-05-29 start date.

## 5. WP0 implication

Stage03V-WP0 must include this addendum in:

```text
reports/stage03v/stage03v_wp0_scope_freeze_report.md
reports/stage03v/stage03v_wp0_scope_freeze_report.json
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
```

WP0 must remain contract-only. It must not build targets, train models, calibrate scores, consume prospective holdout evidence, or implement Stage03V2 / Stage03V3.

## Revision log

| date | change | by |
|---|---|---|
| 2026-06-10 | Added final Stage03V round3 addendum covering permanent cross-cutoff censoring, benchmark downside target, and validation-fold-only readiness evidence counts. | ChatGPT |
