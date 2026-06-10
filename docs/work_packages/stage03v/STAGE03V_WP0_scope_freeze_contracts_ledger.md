# STAGE03V_WP0_scope_freeze_contracts_ledger

Stage: 03V / Volatility and downside-risk hazard

Work package: WP0

Index id: STAGE03V-WP0-v1

Suggested branch: `stage03v/wp0-scope-freeze-contracts-ledger`

Codex instruction: `docs/codex_instructions/stage03v/CODEX_STAGE03V_WP0_scope_freeze_contracts_ledger.md`

Date: 2026-06-10

## Objective

Freeze Stage03V boundaries before any target building or modeling work. This package creates the execution index, signal contract, readiness policy, split-role or Stage04-ledger-compatible manifest, SW2021 level-2 universe manifest, and WP0 evidence report.

WP0 must make the Stage03V route machine-readable. It must not build risk-event targets, train a model, calibrate a model, consume holdout evidence, or create UI / decision surfaces.

## Route anchor

Use:

```text
docs/roadmap/STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN.md
```

## Stage boundary

Allowed:

- Create Stage03V docs, configs, reports, and config-validation tests.
- Register Stage03V in the Stage04 prospective validation ledger if the ledger mechanism is available.
- Create a Stage03V split-role manifest if Stage04 ledger integration is not available.
- Create a SW2021 L2 universe manifest with taxonomy and quality-filter policy.
- Create a readiness policy and risk-event signal contract.

Forbidden:

- Build `risk_event_target_dataset_v1`.
- Read or write DuckDB target tables.
- Train logistic hazard, volatility baseline, HAR diagnostic, calibration, readiness matrix, or downshift validation models.
- Fetch external data.
- Modify HMM or HSMM training algorithms.
- Consume or inspect prospective final holdout performance.
- Generate trading, buy/sell, or sizing output.

## Required deliverables

Create or update:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage03v/stage03v_wp0_scope_freeze_report.md
reports/stage03v/stage03v_wp0_scope_freeze_report.json
```

Also create one of the following, preferring Stage04-ledger compatibility:

```text
reports/stage04/prospective_validation_ledger.stage03v.template.jsonl
```

or, if Stage04 ledger integration is not available:

```text
configs/stage03v_split_role_manifest_v1.yaml
reports/stage03v/stage03v_split_role_manifest_v1.md
reports/stage03v/stage03v_split_role_manifest_v1.json
```

Add tests:

```text
tests/test_stage03v_contracts.py
```

## Required contract content

### Stage and module boundaries

The signal contract must record:

```text
stage_id: stage03v
active_module: Stage03V1 Downside Risk
placeholders: Stage03V2 Upside Trigger, Stage03V3 Competing Risks
stage03v1_entity_type: sw2021_l2_industry
stage03v2_implemented: false
stage03v3_implemented: false
```

### Holdout registration

The split-role or Stage04-ledger-compatible manifest must include:

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

Do not inherit Stage04's 2026-05-29 start date for Stage03V. Stage04's mechanism may be reused, but Stage03V must register its own information cutoff and holdout start.

### Permanent cross-cutoff censoring

The signal contract must include this invariant:

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
```

### Benchmark downside target

The contract must pre-register the benchmark target used in WP0.5 market-block counting:

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

### SW2021 L2 universe manifest

The universe manifest must include:

```text
taxonomy_provider: SW
taxonomy_version: SW2021
taxonomy_level: L2
index_history_policy: official_backfilled_index_history_if_available
reform_check_date: 2021-07-01 or actual local cutover date
constituent_count_min: 5 when constituent snapshot is available
history_continuity_required: true
no_performance_based_filtering: true
filter_list_frozen_in_manifest: true
empirical_promotion_universe: sw2021_l2_industry_only
optional_diagnostic_universe: sw2021_l1_aggregation
```

### Readiness and ordinal policy

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

Default ordinal buckets must be pre-registered:

```text
low:     score < validation q40
medium:  q40 <= score < q75
high:    q75 <= score < q90
extreme: score >= q90
```

Do not allow final holdout, post-hoc backtest appearance, or model performance to tune the ordinal bucket cutoffs.

### Event evidence and readiness gating

The readiness policy must include:

```text
market_event_share_sensitivity: [0.10, 0.20, 0.30]
primary_market_event_share: 0.20
idiosyncratic_discount_default: 0.25
idiosyncratic_discount_sensitivity: [0.10, 0.25, 0.50]
market_event_block_count_lt_2: usable_probability_forbidden
effective_event_evidence_count_lt_5: blocked_or_drop_threshold
effective_event_evidence_count_5_to_9: diagnostic_or_ordinal_only
effective_event_evidence_count_gte_10: modeling_eligible_not_auto_usable
```

The policy must also record:

```text
wp0_5_feasibility_counts_may_use: historical_development
wp5_usable_probability_evidence_counts_must_use: validation_fold_rows_only
training_period_evidence_cannot_satisfy_usable_probability: true
```

### Comparability break

The WP0 report must explicitly state:

```text
Stage03V1 uses SW2021 level-2 industries only. Earlier Stage03R and signal-validation artifacts based on roughly 465 mixed industry/concept boards are not directly comparable to Stage03V1 metrics without an explicit comparability adjustment.
```

## Tests

Add `tests/test_stage03v_contracts.py` with deterministic, CI-safe checks that do not require private DuckDB.

Minimum test coverage:

- All required config files exist.
- YAML files are parseable.
- `information_cutoff_date = 2026-06-10`.
- `holdout_start = 2026-06-11`.
- Permanent cross-cutoff censoring policy exists and forbids backfill.
- Benchmark downside target exists and uses MAE with same horizon and threshold policy as the evaluated slice.
- SW2021 L2 taxonomy and quality-filter fields exist.
- Readiness statuses and ordinal buckets exist.
- WP5 readiness evidence counts are declared validation-fold-only.
- Stage03V2 and Stage03V3 are placeholders only.

## Suggested commands

Run at minimum:

```bash
python -m compileall -q src tests
pytest -q tests/test_stage03v_contracts.py
pytest -q -m "not slow"
```

Do not run target builders, model training, calibration, or holdout evaluation in WP0.

## Reports

Generate:

```text
reports/stage03v/stage03v_wp0_scope_freeze_report.md
reports/stage03v/stage03v_wp0_scope_freeze_report.json
```

The report must include:

- index id;
- route anchor;
- contract paths;
- split-role or Stage04 ledger registration path;
- information cutoff and holdout start;
- permanent cross-cutoff censoring policy;
- benchmark downside target definition;
- SW2021 L2 taxonomy and universe quality filter;
- ordinal policy;
- readiness statuses;
- comparability break statement;
- external data fetch: no;
- target dataset built: no;
- model training: no;
- holdout consumed: no;
- HMM/HSMM training modified: no;
- decision or trading surface created: no.

## Acceptance criteria

WP0 passes if:

- Stage03V execution index exists and marks WP0 active / later packages blocked.
- Risk-event signal contract is machine-readable and contains all required policies.
- Readiness policy is machine-readable and pre-registers ordinal buckets, event evidence gates, and validation-fold-only readiness evidence.
- Stage03V holdout is registered with `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`.
- Permanent cross-cutoff censoring is explicitly required.
- Benchmark downside target is explicitly defined.
- SW2021 L2 taxonomy and universe quality filter are frozen.
- Comparability break versus earlier mixed-board evidence is recorded.
- Contract tests pass.
- No target dataset is built.
- No model is trained.
- No holdout evidence is consumed.
- No external data is fetched.
- No production UI or decision surface is created.

## Return format

```text
index_id: STAGE03V-WP0-v1
branch: stage03v/wp0-scope-freeze-contracts-ledger
PR: ...
status: pass / partial / fail
commands run:
- ...
results:
- ...
created files:
- ...
updated files:
- ...
contract paths:
- ...
ledger or split manifest path: ...
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
permanent cross-cutoff censoring: present / missing
benchmark downside target: present / missing
SW2021 L2 universe manifest: present / missing
external data fetch: no
target dataset built: no
model training: no
holdout consumed: no
HMM/HSMM training modified: no
decision or trading output: no
remaining risks:
- ...
```
