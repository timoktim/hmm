# STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN

Date: 2026-06-10

Status: review_candidate_round2_revised

Scope: add a volatility and downside-risk hazard branch after Stage03R evidence-gated hazard work.

Review rule: this document is a planning anchor only. No Stage03V work package is active until this document is reviewed and explicitly accepted.

Round 1 review status: accepted. The plan added sample-feasibility preflight, prospective holdout locking, date-clustered inference, stronger volatility baselines, continuous downside-volatility diagnostics, and model-vs-baseline downshift comparison.

Round 2 review status: accepted with precise modifications. The plan now uses a dual market-block and idiosyncratic-industry episode feasibility design, Stage04-ledger-compatible holdout registration with a Stage03V information cutoff, SW2021 level-2 taxonomy controls, a pre-registered universe quality filter, optional SW level-1 diagnostic aggregation, and an explicit comparability break versus earlier mixed-board Stage03R evidence.

## 0. Route decision

Stage03V opens a risk-event hazard branch that moves one step outside hidden-state transition prediction.

```text
Existing HMM / HSMM infrastructure
+ Stage03R hazard, calibration, readiness, and validation discipline
-> Stage03V1 Downside Risk
-> Stage03V2 Upside Trigger
-> Stage03V3 Competing Risks
```

Stage03V1 is the first implementation target. Stage03V2 and Stage03V3 stay scoped placeholders unless Stage03V1 produces enough evidence to justify extension.

The first practical question is:

```text
For a SW2021 level-2 industry observed at trade_date t,
what is the probability that the future N-trading-day path suffers a downside move exceeding threshold X?
```

Stage03V must keep the same safety posture as Stage03R:

- HMM remains causal regime context.
- HSMM remains lifecycle interpretation context.
- Risk probabilities require calibration and readiness approval.
- Ordinal output and abstain are valid outputs.
- No raw score is a decision-ready probability.
- No Stage03V output is a buy/sell instruction.
- Cross-sectional rows are not independent evidence.
- Model promotion must be evaluated against the strongest eligible baseline, not only against doing nothing.
- Prior Stage03R and signal-validation artifacts built on roughly 465 mixed boards are not directly comparable to Stage03V1 evidence built on SW level-2 industries.

## 1. Review decisions

### 1.1 Round 1 accepted changes

- Add `STAGE03V-WP0.5` sample feasibility preflight before target dataset construction.
- Use the local V7 long-history database, if available, as the empirical Stage03V source.
- Restrict Stage03V1 v1 empirical universe to SW level-2 industries.
- Add independent event-block counts and effective sample diagnostics.
- Add date-clustered or block-bootstrap confidence intervals for model-vs-baseline deltas.
- Add date-weighted calibration.
- Add baseline-driven downshift comparison in WP6.
- Lock prospective holdout in WP0.
- Move synthetic MAE / MDD / off-by-one tests into WP1.
- Pre-register ordinal risk bucket rules in WP0.
- Add HAR-style continuous downside-volatility diagnostic track.
- Add range-based volatility baselines such as Parkinson and Garman-Klass.
- Add a volatility-scaled threshold supplement before readiness promotion.

### 1.2 Round 2 accepted changes

- Replace one-layer market-event counting with two-layer feasibility evidence:
  - market-level event blocks;
  - idiosyncratic industry episodes outside market-level blocks.
- Keep market-level blocks as a strict input to numeric probability promotion, while using effective total event evidence to avoid incorrectly blocking industry-specific slices.
- Add event-share sensitivity at 10%, 20%, and 30% instead of relying only on 20%.
- Document that `gap <= horizon` merging naturally lowers long-horizon event-block counts.
- Reuse the Stage04 prospective validation ledger mechanism where available, but register a separate Stage03V ledger entry with `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`.
- Add minimum prospective holdout requirements for final decision-support promotion.
- Add a quarterly holdout evaluation cadence with consumption counting.
- Add SW2021 taxonomy controls and 2021 reform break checks.
- Pre-register SW level-2 universe quality filters.
- Add optional SW level-1 diagnostic aggregation as a non-promotion cross-check.
- Add explicit comparability break versus earlier 465 mixed-board evidence.

### 1.3 Clarified decisions

Deep fixed-threshold slices such as 20d / 10% are not removed at the planning-document level. They are feasibility-gated. If market blocks, idiosyncratic episodes, or total effective evidence are insufficient, they are downgraded, deferred, or removed by `STAGE03V-WP0.5` evidence.

The prospective holdout starting after 2026-06-10 is structurally clean but initially small. Stage03V1 can pass engineering and historical-validation gates before the prospective holdout fills, but empirical promotion to decision-support status must remain `DEFER` until the prospective holdout satisfies the minimum size and stress-event requirements.

## 2. Module map

| module | name | responsibility | status in this plan |
|---|---|---|---|
| Stage03V1 | Downside Risk | estimate future downside path-event probability and ordinal risk tendency | first implementation target |
| Stage03V2 | Upside Trigger | estimate future upside touch probability, for example future MFE above +Y | placeholder only |
| Stage03V3 | Competing Risks | estimate first-hit balance between upside and downside barriers | placeholder only |

Stage03V1 owns only downside risk. It may compute shared target primitives that later support Stage03V2 or Stage03V3, but it must not implement upside-trigger models or competing-risk models in v1.

## 3. Data scope and sample assumptions

### 3.1 Primary empirical source

Stage03V1 empirical work should use the local V7 database when available.

Expected V7 role:

```text
local long-history empirical source
coverage target: around 2014 onward
purpose: include multiple stress and recovery regimes, such as 2015, 2018, 2020, 2021-2022, 2024, and later periods
```

If only the short 2025-2026 database is available, Stage03V1 may run smoke tests and schema tests, but it must not claim empirical readiness for deep downside events.

### 3.2 Universe policy

Stage03V1 v1 empirical universe:

```text
SW2021 level-2 industry only
```

The intended data contract is official SW2021 level-2 index history with official backfilled historical series where available.

Out of Stage03V1 v1 empirical scope:

```text
concept sectors
mixed old/new sector taxonomies
custom baskets
individual stocks
```

Reason: downside events are highly cross-sectionally correlated. A cleaner and smaller SW level-2 industry taxonomy gives fewer pseudo-replicates and cleaner effective-sample accounting.

### 3.3 SW taxonomy and universe quality policy

Stage03V-WP0 must pre-register the exact taxonomy and universe quality filter.

Minimum taxonomy fields:

```text
taxonomy_provider: SW
taxonomy_version: SW2021
taxonomy_level: L2
index_history_policy: official_backfilled_index_history_if_available
reform_check_date: 2021-07-01 or actual local cutover date
```

Minimum quality filter:

```text
constituent_count_min: 5 when constituent snapshot is available
history_continuity_required: true
no_performance_based_filtering: true
filter_list_frozen_in_manifest: true
```

WP0.5 and WP1 must check that there is no silent entity break, duplicated entity, or unexplained disappearance around the 2021 SW reform window. If a historical index series starts after the reform window, it can remain in the universe only if the manifest marks the shorter history and its eligibility is evaluated separately.

Optional diagnostic layer:

```text
SW2021 level-1 aggregation may be computed for market-event cross-checks.
SW level-1 diagnostics cannot become the Stage03V1 v1 empirical promotion universe.
```

### 3.4 Comparability break

Earlier Stage03R and signal-validation artifacts used a broader mixed-board universe, including industry and concept boards. Stage03V1 uses SW2021 level-2 industries only. Metrics, event counts, state distributions, cross-sectional dispersion, and validation results must not be compared one-to-one with the earlier 465-board reports without an explicit comparability adjustment.

### 3.5 Effective sample principle

For downside events, the effective sample size is closer to the number of independent market periods and idiosyncratic industry episodes than to `row_count = date_count × industry_count`.

All promotion reports must distinguish:

```text
row_count
trade_date_count
positive_row_count
positive_trade_date_count
market_event_block_count_10pct
market_event_block_count_20pct
market_event_block_count_30pct
idiosyncratic_industry_episode_count
discounted_idiosyncratic_episode_count
effective_event_evidence_count
effective_date_cluster_count
```

A broad market selloff that triggers many industries on the same dates counts primarily as one calendar event block for inference, not as dozens of independent positive examples. A single-industry or small-cluster policy shock can contribute independent evidence only when it is outside market-level event blocks and passes the idiosyncratic episode definition.

## 4. Upstream and downstream connection

### 4.1 Upstream inputs

Stage03V inherits the Stage03R discipline:

- causal walk-forward or explicit research-only mode;
- target leakage checks;
- purge and embargo discipline for overlapping horizons;
- validation fold accounting;
- readiness matrix instead of unconditional probability display;
- final held-out discipline;
- sample-support based downgrade;
- baseline comparison before model promotion;
- multiple-testing and trial-accounting awareness.

Stage03V may use the following existing project assets as context or features:

```text
sector_ohlcv
market_benchmark_ohlcv
market_index_ohlcv
market_breadth_daily
sector_features
walk_forward_state_cache
sector_state_daily
hsmm_lifecycle_ui_daily
model_runs
validation_runs
stage04_prospective_validation_registry or equivalent split ledger
```

Custom-basket assets are not part of Stage03V1 v1 empirical scope.

HMM and HSMM outputs are context features only. Stage03V must not treat HMM posterior probability as upside probability, and must not treat HSMM raw or calibrated `p_exit` as a default risk probability input.

### 4.2 Downstream consumers

Potential downstream consumers after validation:

```text
Stage04R break detector
Stage05R simplified decision engine
Research console / risk dashboard
Casebook and human review loop
```

A downstream consumer may read only readiness-approved Stage03V fields. Invalid, hidden, missing, insufficient-sample, or non-significant model-vs-baseline deltas cannot be displayed as numeric probability.

## 5. Stage03V1 function description

Stage03V1 builds a supervised, auditable downside-risk branch.

```text
Register Stage03V in the prospective validation ledger
-> freeze universe, taxonomy, ordinal policy, and holdout cadence
-> test sample feasibility on long-history SW2021 level-2 data
-> build future downside path-event targets
-> create causal risk features
-> train strong volatility and empirical baselines
-> run continuous downside-volatility diagnostics
-> train logistic downside hazard candidate only for feasible slices
-> calibrate only on validation folds with date-aware weighting
-> assign readiness status using market-block and idiosyncratic-episode evidence
-> validate whether model-driven risk downshift beats baseline-driven risk downshift
```

The primary output is an ordinal risk tendency:

```text
low / medium / high / extreme / insufficient_sample / invalid
```

Numeric probability can be emitted only when the relevant slice reaches `usable_probability` through the readiness matrix.

## 6. Stage03V1 target definitions

### 6.1 Core path quantities

For entity `i` on trade date `t`, with close price `C_i(t)` and horizon `N`:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
future_return_i(t, N) = C_i(t+N) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
MFE_i(t, N) = max_{1 <= k <= N} path_return_i(t, k)
MDD_i(t, N) = max_{0 <= a < b <= N} (1 - C_i(t+b) / C_i(t+a))
```

Stage03V1 primary target uses `MAE`. `MDD` may be calculated as a diagnostic if cheap, but it is not the primary v1 promotion target. `MFE` is reserved for Stage03V2.

### 6.2 Primary event target

```text
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

This answers:

```text
Did the future path suffer at least X downside from today's close at any point within the next N trading days?
```

### 6.3 Secondary research target

```text
tail_loss_event_i(t, N, X) = 1{ future_return_i(t, N) <= -X }
```

This is easier to compute but less path-sensitive. It can be used as a diagnostic and baseline comparison target.

### 6.4 Continuous diagnostic targets

Stage03V1 must include a continuous auxiliary track before probability promotion:

```text
future_realized_vol_i(t, N)
future_downside_vol_i(t, N)
future_range_vol_i(t, N)
```

Purpose:

```text
If simple HAR-style or EWMA/range-based volatility models cannot improve future downside-volatility diagnostics,
then event-probability modeling should be downgraded or stopped early unless event-target evidence is independently strong.
```

Continuous diagnostics are not decision signals. They are sample-efficient checks for whether the feature set contains forward-looking risk information beyond rolling volatility baselines.

### 6.5 Core horizons

Stage03V1 v1 should use:

```text
N in {5, 10, 20}
```

Optional diagnostic horizons:

```text
N in {1, 3}
```

Optional horizons must not become promotion targets until core horizons have evidence.

### 6.6 Threshold policy

Stage03V1 starts with a small fixed threshold grid:

```text
X in {0.03, 0.05, 0.08, 0.10}
```

Suggested core threshold mapping for the first readiness review:

```text
5d:  3% and 5%
10d: 5% and 8%
20d: 8% and 10%
```

Deep-threshold slices are feasibility-gated. A slice with insufficient market-block, idiosyncratic-episode, or total effective event evidence cannot be promoted to `usable_probability`.

A volatility-scaled threshold track must be scheduled before WP5 readiness promotion:

```text
X = k * ex_ante_vol_N, k in {1.0, 1.5, 2.0}
```

Volatility-scaled thresholds are the main test of whether the model adds information beyond volatility level itself. They do not block the first fixed-threshold target builder, but they must be evaluated before any final Stage03V1 readiness promotion.

## 7. Ordinal and readiness policy

Ordinal risk buckets must be pre-registered in `configs/readiness_policy_risk_event_v1.yaml` during WP0.

Default v1 ordinal policy:

```text
For each eligible horizon × threshold × target_kind:
  if readiness_status in {insufficient_sample, invalid}: use that status directly
  else compute risk bucket from validation-fold scores only
  low:     score < validation q40
  medium:  q40 <= score < q75
  high:    q75 <= score < q90
  extreme: score >= q90
```

Alternative fixed probability bands are allowed only if the slice has `usable_probability` and the bands are declared before evaluation.

Forbidden:

```text
post-hoc bucket tuning for better backtest appearance
using final holdout to choose bucket cutoffs
converting insufficient_sample into low risk
```

## 8. Stage03V1 output contract

Minimum output fields for a prediction or validation row:

```text
run_id
model_version
entity_type
entity_id
trade_date
horizon
threshold_type
threshold_value
target_kind
risk_raw_score
risk_calibrated_probability
risk_tendency_ordinal
calibration_status
readiness_status
sample_support
market_event_block_count_20pct
idiosyncratic_industry_episode_count
discounted_idiosyncratic_episode_count
effective_event_evidence_count
effective_date_cluster_count
baseline_model_id
model_vs_baseline_delta
model_vs_baseline_ci_low
model_vs_baseline_ci_high
fallback_reason
validation_fold_id
split_role
target_definition_version
feature_scope_id
universe_id
taxonomy_version
created_at
```

Allowed readiness statuses:

```text
usable_probability
ordinal_only
baseline_only
insufficient_sample
invalid
```

Allowed calibration statuses:

```text
not_calibrated
calibration_candidate
calibrated_pass
calibrated_fail
not_applicable
```

Evidence levels:

```text
research_only
internal_diagnostic
validated_risk_signal
decision_support_candidate
```

Only `usable_probability` can support numeric probability display. `ordinal_only` can support low / medium / high / extreme display. `baseline_only`, `insufficient_sample`, and `invalid` cannot be promoted into numeric risk probability.

## 9. Split-role, holdout, and evaluation cadence policy

Stage03V must lock split roles in WP0 before empirical modeling.

Stage03V should reuse the Stage04 prospective validation ledger mechanism if it exists and is machine-readable. It must register a Stage03V-specific entry rather than inheriting Stage04 dates blindly.

Required registry or manifest entry:

```text
stage_id: stage03v
information_cutoff_date: 2026-06-10
holdout_start: 2026-06-11
historical_development: trade_date <= 2026-06-10
prospective_final_holdout: trade_date >= 2026-06-11
horizons: [1, 3, 5, 10, 20]
label_completeness_required: true
consumption_count_enabled: true
```

If Stage04 already has a prospective ledger with `minimum_candidate_holdout_start_date = 2026-05-29`, Stage03V must not reuse that start date for Stage03V final promotion. The Stage03V route was designed after observing information through 2026-06-10, so the Stage03V holdout must start on 2026-06-11.

Required artifacts:

```text
configs/stage03v_split_role_manifest_v1.yaml
reports/stage03v/stage03v_split_role_manifest_v1.md
reports/stage03v/stage03v_split_role_manifest_v1.json
```

These artifacts may be exported from the Stage04 ledger if a compatible ledger exists. If no compatible ledger exists, WP0 creates a temporary Stage03V manifest and records the migration requirement.

Minimum prospective holdout size for final decision-support promotion:

```text
complete_20d_labeled_trade_dates >= 120
prospective_independent_market_event_blocks >= 2
all holdout consumptions recorded
```

Because a 20d label is complete only after the future 20 trading days are known, the last 20 trading days of the prospective period are not eligible for 20d final evaluation.

Holdout evaluation cadence:

```text
scheduled_holdout_review_frequency: quarterly
ad_hoc_holdout_peeking: forbidden
consumption_count_increment: every scheduled review or manual holdout read
```

A Stage03V1 final report may have:

```text
engineering_verdict: PASS
historical_validation_verdict: PASS or DEFER
prospective_holdout_verdict: DEFER
final_verdict: DEFER
```

This is acceptable while the prospective holdout is too small or lacks at least two independent market event blocks.

## 10. Stage03V1 development sequence

### STAGE03V-WP0: Scope freeze, signal contract, execution index, taxonomy manifest, and holdout ledger entry

Goal: freeze Stage03V boundaries before any modeling or target-building work.

ToDo:

- [ ] Create `docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md`.
- [ ] Create `configs/risk_event_signal_contract_v1.yaml`.
- [ ] Create `configs/readiness_policy_risk_event_v1.yaml`.
- [ ] Register Stage03V in the Stage04 prospective validation ledger if compatible, or create `configs/stage03v_split_role_manifest_v1.yaml` with a migration note.
- [ ] Set `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`.
- [ ] Pre-register quarterly holdout evaluation cadence and consumption-count requirements.
- [ ] Record Stage03V1 as active target and Stage03V2 / Stage03V3 as placeholders.
- [ ] Record SW2021 level-2 industry as the only Stage03V1 v1 empirical universe.
- [ ] Record taxonomy fields and the 2021 SW reform check window.
- [ ] Pre-register universe quality filter, including constituent count and history continuity rules.
- [ ] Record comparability break versus earlier 465 mixed-board evidence.
- [ ] Define field categories: `display_safe`, `internal_diagnostic`, `calibration_required`, `hidden`.
- [ ] Define readiness statuses and allowed UI behavior.
- [ ] Define ordinal bucket rules before evaluation.
- [ ] Define forbidden behavior: raw score as probability, direct trading signal, hidden sample filling, post-hoc bucket tuning.
- [ ] Add review checklist for Stage03V1 target semantics.

Deliverables:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
configs/stage03v_split_role_manifest_v1.yaml or Stage04 ledger entry export
configs/stage03v_sw_l2_universe_manifest_v1.yaml
reports/stage03v/stage03v_wp0_scope_freeze_report.md
reports/stage03v/stage03v_split_role_manifest_v1.md
reports/stage03v/stage03v_split_role_manifest_v1.json
```

Acceptance:

- [ ] Stage03V1 responsibilities are explicit.
- [ ] Stage03V2 and Stage03V3 are out of scope for implementation.
- [ ] Numeric risk probability is gated by readiness policy.
- [ ] Ordinal risk bucket rules are pre-registered.
- [ ] HMM and HSMM are context features only.
- [ ] Stage03V has a ledger-compatible entry with `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`.
- [ ] Quarterly holdout evaluation and consumption counting are specified.
- [ ] SW2021 L2 taxonomy and quality filter are frozen.
- [ ] The report explicitly states that Stage03V evidence is not directly comparable to previous 465 mixed-board Stage03R evidence.
- [ ] No production model code is changed.
- [ ] No target dataset is built yet.

### STAGE03V-WP0.5: Sample Feasibility Preflight

Goal: decide whether each horizon and threshold slice has enough independent evidence before the pipeline spends full implementation cost.

ToDo:

- [ ] Read the local V7 database when available.
- [ ] Verify date coverage and source database identity.
- [ ] Verify SW2021 level-2 industry universe coverage.
- [ ] Verify taxonomy version, quality filter, and 2021 reform-window continuity.
- [ ] Compute event base rates for candidate fixed thresholds.
- [ ] Compute preliminary volatility-scaled threshold base rates using causal ex-ante volatility estimates.
- [ ] Compute positive row count, positive trade-date count, and market-level event-block counts.
- [ ] Compute event-share sensitivity using 10%, 20%, and 30% thresholds.
- [ ] Compute idiosyncratic industry episodes outside market-level blocks.
- [ ] Compute discounted idiosyncratic episode count and total effective event evidence.
- [ ] Compute counts by split role, horizon, threshold, threshold type, and target kind.
- [ ] Compute expected sample support by state label, volatility bucket, and risk bucket where context fields are available.
- [ ] Optionally compute SW level-1 diagnostic aggregation for market-block cross-checks.
- [ ] Emit feasibility verdict per slice: `eligible`, `diagnostic_only`, `defer_threshold`, `drop_threshold`, or `blocked_short_history`.
- [ ] Emit a recommended Stage03V1 threshold set.

Market event-block rule:

```text
For each horizon × threshold × target_kind:
  compute cross-sectional event_share by trade_date
  mark event-active dates at event_share >= 10%, >= 20%, and >= 30%
  use 20% as the primary market-block threshold unless WP0.5 recommends a documented change
  also mark benchmark downside event dates when benchmark target is available
  merge contiguous active dates
  merge gaps <= horizon to avoid counting one selloff as many independent events
  count merged blocks as market_event_block_count
```

Idiosyncratic industry episode rule:

```text
For each industry × horizon × threshold × target_kind:
  find continuous industry event days
  merge gaps <= horizon
  remove or mark portions overlapping primary 20% market event blocks
  count remaining non-overlapping episodes as idiosyncratic_industry_episode_count
  treat different industries and non-overlapping periods as partially independent, not fully row-independent
```

Default effective evidence rule:

```text
market_event_block_count = primary 20% market-block count
idiosyncratic_discount = 0.25 by default
idiosyncratic_discount_sensitivity = [0.10, 0.25, 0.50]
discounted_idiosyncratic_episode_count = idiosyncratic_discount * idiosyncratic_industry_episode_count
effective_event_evidence_count = market_event_block_count + discounted_idiosyncratic_episode_count
```

Default gating:

```text
market_event_block_count < 2: usable_probability forbidden, even if idiosyncratic episodes exist
effective_event_evidence_count < 5: blocked or drop_threshold
5 <= effective_event_evidence_count < 10: diagnostic_only or ordinal_only maximum
effective_event_evidence_count >= 10: eligible for modeling, but not automatically usable_probability
```

Long-horizon note:

```text
The gap <= horizon merge rule intentionally makes long-horizon event blocks coarser.
For 20d horizons, a chain of selloff days across a quarter may count as one block.
This is a conservative effective-sample rule, not a data defect.
```

Candidate files:

```text
src/evaluation/stage03v_sample_feasibility.py
scripts/stage03v_sample_feasibility_gate.sh
reports/stage03v/sample_feasibility_report.md
reports/stage03v/sample_feasibility_report.json
tests/test_stage03v_sample_feasibility.py
```

Acceptance:

- [ ] Feasibility report exists.
- [ ] V7 coverage is recorded when available.
- [ ] SW2021 level-2 universe coverage is recorded.
- [ ] 2021 reform-window continuity is checked.
- [ ] Quality-filtered industry list is recorded and frozen.
- [ ] Each candidate horizon × threshold has base rate, market-block count, idiosyncratic episode count, and effective event evidence count.
- [ ] 10% / 20% / 30% event-share sensitivity is reported.
- [ ] Long-horizon block-merging interpretation is documented.
- [ ] Slices below the evidence threshold cannot become `usable_probability` later.
- [ ] If only short-history data is available, empirical promotion is blocked or deferred explicitly.
- [ ] No model training occurs.

### STAGE03V-WP1: Risk Event Target Dataset v1 with synthetic path tests

Goal: construct a causal, reproducible downside risk target dataset and prove path-target correctness.

ToDo:

- [ ] Add a builder for `risk_event_target_dataset_v1`.
- [ ] Support `entity_type = sw2021_l2_industry` as the v1 empirical entity type.
- [ ] Defer custom basket support.
- [ ] Enforce the WP0 SW2021 L2 universe manifest and quality filter.
- [ ] Compute `future_return`, `MAE`, optional diagnostic `MDD`, and future realized volatility fields.
- [ ] Generate `downside_event` labels by eligible horizon and threshold from WP0.5.
- [ ] Persist `target_observation_end_date`.
- [ ] Persist `censoring_status`.
- [ ] Persist `target_definition_version`.
- [ ] Persist taxonomy version and split role.
- [ ] Emit sample-support tables by horizon, threshold, entity type, state label, recent-volatility bucket, and split role.
- [ ] Keep all feature dates at or before `trade_date`.
- [ ] Add synthetic path fixtures with known MAE, MFE, MDD, final return, and off-by-one boundaries.
- [ ] Test `t+1` through `t+N` semantics.

Candidate files:

```text
src/evaluation/stage03v_risk_target_dataset.py
scripts/stage03v_risk_target_gate.sh
tests/test_stage03v_risk_target_dataset.py
tests/test_stage03v_path_targets.py
reports/stage03v/risk_event_target_support.md
reports/stage03v/risk_event_target_support.json
```

Minimum dataset columns:

```text
trade_date
entity_type
entity_id
sector_code
taxonomy_version
feature_scope_id
universe_id
split_role
horizon
threshold_type
threshold_value
target_kind
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
event_label
target_observation_end_date
censoring_status
sample_weight
target_definition_version
```

Acceptance:

- [ ] No feature column uses data after `trade_date`.
- [ ] Right-censored rows are not labeled as non-events.
- [ ] Last available dates with insufficient forward path are marked as censored or excluded according to policy.
- [ ] MAE, MDD, final return, and event labels match synthetic examples.
- [ ] Off-by-one tests pass.
- [ ] SW2021 L2 taxonomy version is persisted.
- [ ] No silent entity break or duplicate is detected around the 2021 reform window.
- [ ] Quality-filtered universe is enforced.
- [ ] Sample-support report exists.
- [ ] No model training occurs.

### STAGE03V-WP2: Target Leakage, Purge, Embargo, and CI Gate

Goal: make risk-event targets safe before modeling.

ToDo:

- [ ] Test right-censoring behavior near dataset end.
- [ ] Test purge and embargo boundaries for overlapping horizons.
- [ ] Test that future target columns are not accepted as feature columns.
- [ ] Test entity-level duplicate protection.
- [ ] Test split-role manifest and Stage04-ledger consumption enforcement.
- [ ] Add CI-safe tests that do not require private DuckDB availability.
- [ ] Document Stage03V target leakage policy.

Candidate files:

```text
tests/test_stage03v_target_leakage_policy.py
tests/test_stage03v_purge_embargo_policy.py
docs/validation/STAGE03V_TARGET_LEAKAGE_POLICY.md
scripts/stage03v_target_leakage_gate.sh
```

Acceptance:

- [ ] Purge and embargo tests pass.
- [ ] Feature leakage tests pass.
- [ ] Split-role and holdout-consumption enforcement tests pass.
- [ ] Tests are deterministic and CI-safe.
- [ ] No model training occurs.

### STAGE03V-WP3: Volatility, range-based, empirical, and continuous diagnostic baselines

Goal: establish strong, simple baselines before logistic modeling.

ToDo:

- [ ] Build rolling close-to-close realized volatility baseline.
- [ ] Build EWMA volatility baseline.
- [ ] Build downside volatility baseline.
- [ ] Build recent drawdown baseline.
- [ ] Build Parkinson range-volatility baseline.
- [ ] Build Garman-Klass range-volatility baseline.
- [ ] Optionally build Rogers-Satchell range-volatility diagnostic if OHLC semantics support it.
- [ ] Build empirical event-rate baseline by horizon and threshold.
- [ ] Build empirical event-rate baseline by recent-volatility bucket.
- [ ] Build optional HMM-state x volatility-bucket baseline.
- [ ] Build HAR-style regression diagnostic for `future_downside_vol` and `future_realized_vol`.
- [ ] Compare HAR-style diagnostics to rolling, EWMA, and range-based volatility baselines.
- [ ] Emit baseline-only ordinal risk tendency.
- [ ] Record baseline metrics in validation artifacts.

Candidate files:

```text
src/evaluation/stage03v_volatility_baselines.py
src/evaluation/stage03v_continuous_vol_diagnostics.py
scripts/stage03v_volatility_baseline_gate.sh
reports/stage03v/volatility_baseline_report.md
reports/stage03v/volatility_baseline_report.json
reports/stage03v/continuous_vol_diagnostic_report.md
reports/stage03v/continuous_vol_diagnostic_report.json
tests/test_stage03v_volatility_baselines.py
tests/test_stage03v_continuous_vol_diagnostics.py
```

Acceptance:

- [ ] Baselines run without future leakage.
- [ ] Baseline metrics include Brier, event rate, bucket monotonicity, sample support, market-block count, idiosyncratic episode count, and effective event evidence.
- [ ] Continuous diagnostics include MSE, QLIKE or equivalent volatility-loss metric, rank correlation, and fold-level stability.
- [ ] Sparse buckets emit `insufficient_sample` or `baseline_only`.
- [ ] Baseline probability is not promoted as `usable_probability`.
- [ ] If continuous diagnostics cannot beat simple rolling/EWMA/range baselines, WP4 must justify continuation or defer model training.
- [ ] Logistic modeling remains blocked until baseline report is accepted.

### STAGE03V-WP3.5: Volatility-Scaled Threshold Supplement

Goal: test whether risk-event modeling has information beyond volatility level itself.

ToDo:

- [ ] Build causal ex-ante volatility estimates for each horizon.
- [ ] Generate volatility-scaled thresholds: `X = k * ex_ante_vol_N` for `k in {1.0, 1.5, 2.0}`.
- [ ] Build volatility-scaled downside event labels.
- [ ] Compute base rates, market-block counts, idiosyncratic episodes, and effective event evidence counts.
- [ ] Compare fixed-threshold and volatility-scaled sample support.
- [ ] Decide which volatility-scaled slices are eligible for WP4 / WP5.

Candidate files:

```text
src/evaluation/stage03v_vol_scaled_targets.py
scripts/stage03v_vol_scaled_target_gate.sh
reports/stage03v/vol_scaled_threshold_report.md
reports/stage03v/vol_scaled_threshold_report.json
tests/test_stage03v_vol_scaled_targets.py
```

Acceptance:

- [ ] Volatility-scaled labels use only causal ex-ante volatility.
- [ ] Each scaled slice has base rate and effective evidence counts.
- [ ] Ineligible scaled slices are marked `diagnostic_only`, `defer_threshold`, or `drop_threshold`.
- [ ] WP5 readiness promotion is blocked until this supplement is accepted or explicitly waived with reason.
- [ ] No model training occurs.

### STAGE03V-WP4: Logistic Downside Risk Hazard v1

Goal: test whether a simple supervised model adds value over volatility and empirical baselines.

ToDo:

- [ ] Train per-horizon and per-threshold logistic models only for eligible slices.
- [ ] Use purged walk-forward train / validation folds.
- [ ] Use only causal features.
- [ ] Use date-aware sample weighting so each trade date does not create many pseudo-independent observations.
- [ ] Include feature families: recent volatility, downside volatility, range volatility, recent drawdown, breadth, dispersion, liquidity, RS, HMM context, HSMM lifecycle context.
- [ ] Exclude HSMM raw or calibrated numeric `p_exit` by default.
- [ ] Emit `risk_raw_score` only.
- [ ] Persist fold id, model version, feature set id, parameter set id, and baseline model id.
- [ ] Emit coefficient or feature summary where available.
- [ ] Compare raw model performance against the strongest eligible WP3 baseline for the same slice.

Candidate files:

```text
src/models/stage03v_downside_risk_hazard.py
src/evaluation/stage03v_logistic_risk_hazard.py
scripts/stage03v_logistic_risk_hazard_gate.sh
reports/stage03v/logistic_downside_risk_report.md
reports/stage03v/logistic_downside_risk_report.json
tests/test_stage03v_logistic_risk_hazard.py
```

Acceptance:

- [ ] Raw logistic scores are emitted.
- [ ] No row is marked `usable_probability` in this work package.
- [ ] Performance is compared against WP3 strongest eligible baselines, not only against unconditional event rate.
- [ ] Fold construction respects purge and embargo policy.
- [ ] Date-aware sample weighting is recorded.
- [ ] Feature set excludes target and future columns.
- [ ] No UI surface or decision surface is created.

### STAGE03V-WP5: Calibration, clustered inference, and downside risk readiness matrix

Goal: decide where numeric probability is allowed and where output must downgrade.

ToDo:

- [ ] Add isotonic calibration on validation folds only.
- [ ] Use date-aware calibration weighting or equivalent grouped evaluation.
- [ ] Compare raw logistic, calibrated logistic, and strongest eligible baselines.
- [ ] Compute Brier score, ECE, calibration slope / intercept, bucket monotonicity, PR-AUC, event rate, sample support, market-block count, idiosyncratic episode count, and effective event evidence.
- [ ] Compute model-vs-baseline deltas for Brier, ECE, PR-AUC, bucket separation, and risk-bucket monotonicity.
- [ ] Attach trade-date clustered or block-bootstrap confidence intervals to model-vs-baseline deltas.
- [ ] Build readiness matrix by horizon, threshold, threshold type, entity type, state label, volatility bucket, and risk bucket.
- [ ] Assign `usable_probability`, `ordinal_only`, `baseline_only`, `insufficient_sample`, or `invalid`.
- [ ] Emit fallback reason for every non-usable slice.
- [ ] Prevent calibration that worsens Brier from receiving `usable_probability`.
- [ ] Prevent slices whose model-vs-baseline CI includes zero from receiving `usable_probability`.
- [ ] Prevent slices with `market_event_block_count < 2` from receiving `usable_probability`.

Candidate files:

```text
src/evaluation/stage03v_risk_calibration.py
src/evaluation/stage03v_risk_readiness_matrix.py
src/evaluation/stage03v_clustered_inference.py
scripts/stage03v_risk_readiness_gate.sh
reports/stage03v/downside_risk_readiness_matrix.md
reports/stage03v/downside_risk_readiness_matrix.json
tests/test_stage03v_risk_readiness_matrix.py
tests/test_stage03v_clustered_inference.py
```

Acceptance:

- [ ] Readiness matrix exists.
- [ ] Calibration that worsens Brier cannot become `usable_probability`.
- [ ] Sparse slices downgrade cleanly.
- [ ] Numeric probability appears only in `usable_probability` slices.
- [ ] Model-vs-baseline deltas include date-clustered or block-bootstrap confidence intervals.
- [ ] If the confidence interval includes zero, the slice cannot be `usable_probability`.
- [ ] If market-block evidence is too low, the slice cannot be `usable_probability` even when idiosyncratic evidence prevents blocking.
- [ ] Calibration is not dominated by a few broad-market selloff dates without weighting or grouped evaluation disclosure.
- [ ] Most slices may be `ordinal_only`; this is acceptable.
- [ ] No decision output is created.

### STAGE03V-WP6: Risk Validation Protocol and Downshift Research Report

Goal: test whether downside-risk output improves risk management metrics under a pre-registered protocol.

ToDo:

- [ ] Pre-register risk validation metrics.
- [ ] Define research-only risk-downshift scenarios, for example avoiding or reducing exposure in top risk bucket.
- [ ] For every scenario, run three arms: no downshift, strongest WP3 baseline-driven downshift, and model-driven downshift.
- [ ] Make the primary comparison model-driven minus baseline-driven, not model-driven minus no-downshift.
- [ ] Measure future max drawdown reduction.
- [ ] Measure CVaR reduction.
- [ ] Measure realized volatility reduction.
- [ ] Measure stress-period recall only when market-block or total effective event evidence is sufficient; otherwise mark it diagnostic-only.
- [ ] Measure false risk-downshift rate.
- [ ] Measure missed-upside cost.
- [ ] Measure turnover or churn cost if a simulated exposure rule is used.
- [ ] Attach date-clustered or event-block bootstrap confidence intervals to risk-validation deltas.
- [ ] Record every trial in validation artifacts.
- [ ] Keep final holdout protected and respect quarterly consumption cadence.

Candidate files:

```text
reports/stage03v/risk_validation_protocol.md
src/evaluation/stage03v_risk_validation.py
scripts/stage03v_risk_validation_gate.sh
reports/stage03v/downside_risk_validation_report.md
reports/stage03v/downside_risk_validation_report.json
tests/test_stage03v_risk_validation_protocol.py
```

Acceptance:

- [ ] Primary risk metrics are pre-registered before final evaluation.
- [ ] Risk validation does not tune on final holdout.
- [ ] Return metrics remain secondary.
- [ ] Every downshift scenario includes no-downshift, baseline-driven, and model-driven arms.
- [ ] Main claim is model-driven improvement over baseline-driven control.
- [ ] Strong return with unstable risk metrics remains research-only.
- [ ] Results include abstain behavior.
- [ ] Stress-period recall is not promoted when the independent-event denominator is too small.
- [ ] No production trading recommendation is created.

### STAGE03V-WP7: Stage03V1 Final Gate

Goal: aggregate engineering, calibration, and risk-validation evidence into a final Stage03V1 verdict.

ToDo:

- [ ] Aggregate WP0 through WP6 evidence.
- [ ] Emit engineering gate verdict.
- [ ] Emit sample feasibility verdict.
- [ ] Emit calibration gate verdict.
- [ ] Emit risk validation verdict.
- [ ] Emit prospective holdout verdict.
- [ ] Emit final verdict: `PASS`, `DEFER`, or `BLOCKED`.
- [ ] Decide whether Stage03V2 or Stage03V3 deserves activation.
- [ ] Record limitations, sample ceilings, effective-sample caveats, and forbidden interpretations.

Candidate files:

```text
src/evaluation/stage03v_final_gate.py
scripts/stage03v_final_gate.sh
reports/stage03v/stage03v1_final_gate_report.md
reports/stage03v/stage03v1_final_gate_report.json
```

Acceptance:

- [ ] Final gate report exists.
- [ ] Verdict is machine-readable.
- [ ] If empirical evidence is weak, verdict is `DEFER` or `BLOCKED` rather than promoted.
- [ ] If prospective holdout has insufficient post-2026-06-10 data, fewer than 120 complete 20d labeled trade dates, or fewer than 2 independent market event blocks, final decision-support promotion remains `DEFER`.
- [ ] Stage03V2 and Stage03V3 remain blocked unless explicitly activated by a follow-up route document.

## 11. Stage03V1 global ToDo list

- [ ] Approve this route document after human review.
- [ ] Create Stage03V execution index.
- [ ] Create risk-event signal contract.
- [ ] Create risk-event readiness policy.
- [ ] Register Stage03V in the prospective validation ledger with Stage03V-specific cutoff and start date.
- [ ] Freeze SW2021 L2 taxonomy and universe quality filter.
- [ ] Run sample feasibility preflight on V7 SW2021 L2 data.
- [ ] Build risk-event target dataset.
- [ ] Add synthetic path-event tests in the target package.
- [ ] Add leakage, purge, embargo, split-role, and holdout-consumption tests.
- [ ] Build volatility, range-based, empirical, and continuous diagnostic baselines.
- [ ] Build volatility-scaled threshold supplement.
- [ ] Train logistic downside risk hazard candidate only for eligible slices.
- [ ] Add calibration, clustered inference, and readiness matrix.
- [ ] Pre-register risk validation protocol.
- [ ] Run baseline-controlled risk validation report.
- [ ] Emit Stage03V1 final gate verdict.
- [ ] Decide whether to activate Stage03V2 or Stage03V3.

## 12. Feature policy for Stage03V1

Allowed causal feature families:

```text
recent_return
rolling_volatility
EWMA_volatility
downside_volatility
Parkinson_range_volatility
Garman_Klass_range_volatility
high_low_range
ATR_style_range
recent_drawdown
vol_of_vol
market_breadth
cross_section_dispersion
sector_correlation_or_proxy
liquidity_and_turnover
relative_strength
HMM_state_label
HMM_posterior_confidence
HMM_entropy
HMM_margin
HSMM_state_age
HSMM_phase
HSMM_duration_percentile
SW2021_L1_diagnostic_context
```

Forbidden default features:

```text
future_return
future_mae
future_mdd
future_realized_vol
future_downside_vol
event_label
post_trade_date_feature
HSMM_raw_p_exit
HSMM_calibrated_p_exit_as_default_input
any final-holdout-derived tuning flag
custom_basket_feature_in_v1_empirical_promotion
concept_sector_feature_in_v1_empirical_promotion
posthoc_universe_filter
```

HSMM lifecycle context can be used only as non-probability context unless a later contract explicitly allows a readiness-approved field.

## 13. Validation and promotion policy

Stage03V1 can pass only if all of the following hold:

1. Stage03V is registered in the prospective validation ledger with `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`.
2. The split-role manifest locks prospective final holdout before modeling.
3. SW2021 L2 taxonomy, universe quality filter, and 2021 reform-window continuity checks pass.
4. Sample feasibility preflight passes or narrows the eligible slice set.
5. Risk target dataset passes causal, censoring, purge, and embargo audit.
6. Synthetic path target tests pass in WP1.
7. Baselines exist and are explicitly compared.
8. Continuous volatility diagnostics do not contradict the event-probability thesis, or the model path is downgraded honestly.
9. Volatility-scaled threshold supplement is evaluated before readiness promotion.
10. Logistic hazard adds evidence over the strongest eligible baseline or is downgraded honestly.
11. Calibration does not worsen Brier for any slice marked `usable_probability`.
12. Model-vs-baseline deltas for `usable_probability` slices have date-clustered or block-bootstrap confidence intervals that do not include zero.
13. `usable_probability` slices satisfy market-block and effective-event-evidence requirements.
14. Sparse or correlated slices emit `insufficient_sample`, `baseline_only`, or `ordinal_only`.
15. Risk validation protocol is pre-registered.
16. Downshift validation compares model-driven downshift against baseline-driven downshift.
17. Final holdout discipline, quarterly cadence, and consumption counting are preserved.
18. Output remains risk context or decision-support candidate, not trading instruction.

Stage03V1 should fail or defer if:

- V7 long-history data is unavailable and only short 2025-2026 data is available for empirical claims;
- the event base rate is too sparse for stable calibration;
- market-block and effective event evidence are too low;
- idiosyncratic episodes are the only evidence for a slice that seeks `usable_probability`;
- most apparent improvement comes from one market selloff block only;
- row-level metrics look good but date-clustered intervals do not support the delta;
- calibration improves ranking but worsens probability quality;
- model-driven downshift does not beat baseline-driven downshift;
- risk-downshift improves return but worsens drawdown or CVaR;
- final holdout discipline cannot be proven;
- implementation requires expanding Stage03V2 or Stage03V3 early.

## 14. Execution governance

After this plan is reviewed and accepted, every implementation step must follow this loop:

1. Create one GitHub work package document under `docs/work_packages/stage03v/`.
2. Create one Codex instruction document under `docs/codex_instructions/stage03v/`.
3. The user gives the Codex instruction to the executor.
4. Executor implements only the active work package.
5. Executor opens or updates the corresponding PR and evidence artifacts.
6. Review checks acceptance criteria and forbidden behavior.
7. If accepted, archive the package in `STAGE03V_EXECUTION_INDEX.md` and activate the next package.
8. If rejected, revise the same package or mark it blocked. Do not skip forward.

One package may not silently implement a later package. Work packages must be small enough for isolated review.

## 15. Review questions before activation

Reviewer should decide these before STAGE03V-WP0 starts:

- [ ] Is `MAE` the correct primary Stage03V1 event target?
- [ ] Should `MDD` be diagnostic only in v1, or should it be a primary target?
- [ ] Are the initial horizons `{5, 10, 20}` sufficient?
- [ ] Are the fixed thresholds `{3%, 5%, 8%, 10%}` acceptable as candidate thresholds subject to WP0.5 feasibility?
- [ ] Is SW2021 level-2 industry the correct v1 empirical universe?
- [ ] Should custom baskets stay deferred until sector-level evidence exists?
- [ ] Should volatility-scaled thresholds be mandatory before WP5 readiness promotion? This plan says yes.
- [ ] Should Stage03V1 consume Stage03R hazard outputs as features, or only HMM / HSMM context fields?
- [ ] Should the Stage03V holdout use `information_cutoff_date = 2026-06-10` and `holdout_start = 2026-06-11`? This plan says yes.
- [ ] Is `market_event_block_count < 2` too strict or too loose for forbidding `usable_probability`?
- [ ] Should the idiosyncratic episode discount default be 0.25? WP0.5 must report sensitivity at 0.10 / 0.25 / 0.50.
- [ ] Is quarterly holdout review cadence acceptable?

## 16. Out of scope for Stage03V1

The following are explicitly out of scope:

- Stage03V2 upside-trigger model implementation.
- Stage03V3 competing-risks model implementation.
- Full decision engine integration.
- Buy, sell, sizing, or automatic trading recommendations.
- Deep models, random forests, GBM, neural nets, VAR-HSMM, or switching state-space models.
- Repeated final-holdout tuning.
- UI display of uncalibrated numeric risk probability.
- Promotion of raw logistic score as probability.
- Concept-sector or custom-basket empirical promotion in v1.
- Row-count-only inference that treats industry-date rows as independent evidence.
- Silent reuse of Stage04 holdout dates that predate the Stage03V information cutoff.
- Post-hoc exclusion of SW level-2 industries based on model performance.

## 17. Revision log

| date | change | by |
|---|---|---|
| 2026-06-10 | Initial review-candidate Stage03V route plan. | ChatGPT |
| 2026-06-10 | Incorporated round 1 review: sample feasibility, V7/SW-L2 scope, clustered inference, baseline-controlled validation, prospective holdout lock, continuous-vol diagnostics, range-vol baselines, and volatility-scaled thresholds. | ChatGPT |
| 2026-06-10 | Incorporated round 2 review: dual market/idiosyncratic event evidence, event-share sensitivity, Stage04-ledger-compatible Stage03V holdout registration, prospective holdout minimum size and cadence, SW2021 taxonomy controls, universe quality filtering, SW L1 diagnostics, and comparability break. | ChatGPT |
