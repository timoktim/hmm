# Stage03V WP0 Scope Freeze Report

index_id: STAGE03V-WP0-v1

branch: `stage03v/wp0-scope-freeze-contracts-ledger`

status: pass

## Scope

WP0 freezes the Stage03V route before target building or modeling. Stage03V1 is
the only active module and covers downside risk for SW2021 level-2 industries.
Stage03V2 Upside Trigger and Stage03V3 Competing Risks are placeholders only.

## Route Anchors

- `docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md`
- `docs/roadmap/STAGE03V_ROUND3_FINAL_ADDENDUM_20260610.md`
- `docs/work_packages/stage03v/STAGE03V_WP0_scope_freeze_contracts_ledger.md`
- `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP0_scope_freeze_contracts_ledger.md`

## Contract Paths

- `docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md`
- `configs/risk_event_signal_contract_v1.yaml`
- `configs/readiness_policy_risk_event_v1.yaml`
- `configs/stage03v_sw_l2_universe_manifest_v1.yaml`
- `reports/stage04/prospective_validation_ledger.stage03v.template.jsonl`

## Holdout Registration

Stage03V uses a Stage03V-specific Stage04-ledger-compatible template:

`reports/stage04/prospective_validation_ledger.stage03v.template.jsonl`

```text
stage_id: stage03v
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
historical_development: trade_date <= 2026-06-10
prospective_final_holdout: trade_date >= 2026-06-11
required_label_horizons: [1, 3, 5, 10, 20]
label_completeness_required: true
consumption_count_enabled: true
scheduled_holdout_review_frequency: quarterly
ad_hoc_holdout_peeking: forbidden
```

The Stage04 mechanism is reused as a template export, but Stage03V does not
inherit Stage04's 2026-05-29 holdout start.

## Permanent Cross-Cutoff Censoring

Permanent cross-cutoff censoring is present in
`configs/risk_event_signal_contract_v1.yaml`.

```text
cross_cutoff_censoring_policy: permanent
information_cutoff_date: 2026-06-10
label_cutoff_date: 2026-06-10
allowed_cross_cutoff_handling: [cross_cutoff_censored, exclude_with_reason]
forbidden_cross_cutoff_handling: [backfill_after_cutoff, fill_from_holdout_prices]
```

For `split_role = historical_development`, `target_observation_end_date` must be
less than or equal to the information cutoff date. Rows whose target window
crosses the cutoff must remain permanently censored or be excluded with an
explicit reason, and must not be backfilled later from prospective holdout
prices.

## Benchmark Downside Target

The benchmark downside target is present in
`configs/risk_event_signal_contract_v1.yaml`.

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

## SW2021 L2 Universe

The SW2021 L2 universe manifest is present in
`configs/stage03v_sw_l2_universe_manifest_v1.yaml`.

```text
taxonomy_provider: SW
taxonomy_version: SW2021
taxonomy_level: L2
index_history_policy: official_backfilled_index_history_if_available
reform_check_date: 2021-07-01
constituent_count_min: 5 when constituent snapshot is available
history_continuity_required: true
no_performance_based_filtering: true
filter_list_frozen_in_manifest: true
empirical_promotion_universe: sw2021_l2_industry_only
optional_diagnostic_universe: sw2021_l1_aggregation
```

Stage03V1 uses SW2021 level-2 industries only. Earlier Stage03R and signal-validation artifacts based on roughly 465 mixed industry/concept boards are not directly comparable to Stage03V1 metrics without an explicit comparability adjustment.

## Readiness And Ordinal Policy

Readiness statuses:

```text
usable_probability
ordinal_only
baseline_only
insufficient_sample
invalid
```

Calibration statuses:

```text
not_calibrated
calibration_candidate
calibrated_pass
calibrated_fail
not_applicable
```

Default ordinal buckets are pre-registered from validation-fold scores only:

```text
low:     score < validation q40
medium:  q40 <= score < q75
high:    q75 <= score < q90
extreme: score >= q90
```

Final holdout rows, post-hoc visual appearance, and model performance are not
allowed to tune ordinal bucket cutoffs.

## Event Evidence Gates

```text
market_event_share_sensitivity: [0.10, 0.20, 0.30]
primary_market_event_share: 0.20
idiosyncratic_discount_default: 0.25
idiosyncratic_discount_sensitivity: [0.10, 0.25, 0.50]
market_event_block_count_lt_2: usable_probability_forbidden
effective_event_evidence_count_lt_5: blocked_or_drop_threshold
effective_event_evidence_count_5_to_9: diagnostic_or_ordinal_only
effective_event_evidence_count_gte_10: modeling_eligible_not_auto_usable
wp0_5_feasibility_counts_may_use: historical_development
wp5_usable_probability_evidence_counts_must_use: validation_fold_rows_only
training_period_evidence_cannot_satisfy_usable_probability: true
```

## Boundary Flags

```text
external data fetch: no
target dataset built: no
model training: no
probability calibration: no
holdout consumed: no
HMM/HSMM training modified: no
decision or trading surface created: no
decision or trading output: no
buy/sell output: no
sizing output: no
STAGE03V-WP0.5 started: no
```

## Remaining Risks

- WP0 is contract-only; later packages must implement runtime enforcement for
  target building, censoring regression tests, sample feasibility, and
  validation-fold evidence counts.
- Future local Stage03V holdout-read ledgers must remain ignored unless a later
  reviewed package promotes them.
