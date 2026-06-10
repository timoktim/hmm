# STAGE03V_VOLATILITY_DRAWDOWN_RISK_PLAN

Date: 2026-06-10

Status: review_candidate

Scope: add a volatility and downside-risk hazard branch after Stage03R evidence-gated hazard work.

Review rule: this document is a planning anchor only. No Stage03V work package is active until this document is reviewed and explicitly accepted.

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

The core shift is from predicting model-produced state transitions to predicting observable future path-risk events. The first practical question is:

```text
For a sector or custom basket observed at trade_date t,
what is the probability that the future N-trading-day path suffers a downside move exceeding threshold X?
```

Stage03V must keep the same safety posture as Stage03R:

- HMM remains causal regime context.
- HSMM remains lifecycle interpretation context.
- Risk probabilities require calibration and readiness approval.
- Ordinal output and abstain are valid outputs.
- No raw score is a decision-ready probability.
- No Stage03V output is a buy/sell instruction.

## 1. Module map

| module | name | responsibility | status in this plan |
|---|---|---|---|
| Stage03V1 | Downside Risk | estimate future downside path-event probability and ordinal risk tendency | first implementation target |
| Stage03V2 | Upside Trigger | estimate future upside touch probability, for example future MFE above +Y | placeholder only |
| Stage03V3 | Competing Risks | estimate first-hit balance between upside and downside barriers | placeholder only |

Stage03V1 owns only downside risk. It may compute some shared target primitives that later support Stage03V2 or Stage03V3, but it must not implement upside-trigger models or competing-risk models in v1.

## 2. Upstream and downstream connection

### 2.1 Upstream inputs

Stage03V inherits the Stage03R discipline:

- causal walk-forward or explicit research-only mode;
- target leakage checks;
- purge and embargo discipline for overlapping horizons;
- validation fold accounting;
- readiness matrix instead of unconditional probability display;
- final held-out discipline;
- sample-support based downgrade.

Stage03V may use the following existing project assets as context or features:

```text
sector_ohlcv
custom_basket_ohlcv
market_benchmark_ohlcv
market_index_ohlcv
market_breadth_daily
sector_features
walk_forward_state_cache
sector_state_daily
hsmm_lifecycle_ui_daily
model_runs
validation_runs
```

HMM and HSMM outputs are context features only. Stage03V must not treat HMM posterior probability as upside probability, and must not treat HSMM raw or calibrated `p_exit` as a default risk probability input.

### 2.2 Downstream consumers

Potential downstream consumers after validation:

```text
Stage04R break detector
Stage05R simplified decision engine
Research console / risk dashboard
Casebook and human review loop
```

A downstream consumer may read only readiness-approved Stage03V fields. Invalid, hidden, missing, or insufficient-sample probability cannot be displayed as numeric probability.

## 3. Stage03V1 function description

Stage03V1 builds a supervised, auditable downside-risk branch.

The function is:

```text
Build future downside path-event targets
-> create causal risk features
-> train simple downside risk baselines
-> train logistic downside hazard candidate
-> calibrate only on validation folds
-> assign readiness status
-> validate whether risk-downshift style use reduces future risk
```

The primary output is an ordinal risk tendency:

```text
low / medium / high / extreme / insufficient_sample / invalid
```

Numeric probability can be emitted only when the relevant slice reaches `usable_probability` through the readiness matrix.

## 4. Stage03V1 target definitions

### 4.1 Core path quantities

For entity `i` on trade date `t`, with close price `C_i(t)` and horizon `N`:

```text
path_return_i(t, k) = C_i(t+k) / C_i(t) - 1
future_return_i(t, N) = C_i(t+N) / C_i(t) - 1
MAE_i(t, N) = min_{1 <= k <= N} path_return_i(t, k)
MFE_i(t, N) = max_{1 <= k <= N} path_return_i(t, k)
MDD_i(t, N) = max_{0 <= a < b <= N} (1 - C_i(t+b) / C_i(t+a))
```

Stage03V1 primary target uses `MAE`. `MDD` may be calculated as a diagnostic if cheap, but it is not the primary v1 promotion target. `MFE` is reserved for Stage03V2.

### 4.2 Primary event target

```text
downside_event_i(t, N, X) = 1{ MAE_i(t, N) <= -X }
```

This answers:

```text
Did the future path suffer at least X downside from today's close at any point within the next N trading days?
```

### 4.3 Secondary research target

```text
tail_loss_event_i(t, N, X) = 1{ future_return_i(t, N) <= -X }
```

This is easier to compute but less path-sensitive. It can be used as a diagnostic and baseline comparison target.

### 4.4 Core horizons

Stage03V1 v1 should use:

```text
N in {5, 10, 20}
```

Optional diagnostic horizons:

```text
N in {1, 3}
```

Optional horizons must not become promotion targets until core horizons have evidence.

### 4.5 Threshold policy

Stage03V1 should start with a small fixed threshold grid:

```text
X in {0.03, 0.05, 0.08, 0.10}
```

Suggested core threshold mapping for the first readiness review:

```text
5d:  3% and 5%
10d: 5% and 8%
20d: 8% and 10%
```

A volatility-scaled threshold can be added after the first target dataset and baseline reports exist:

```text
X = k * ex_ante_vol_N, k in {1.0, 1.5, 2.0}
```

Volatility-scaled thresholds are useful for cross-sector comparability, but they should not delay the first fixed-threshold dataset.

## 5. Stage03V1 output contract

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
fallback_reason
validation_fold_id
target_definition_version
feature_scope_id
universe_id
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

Only `usable_probability` can support numeric probability display. `ordinal_only` can support low / medium / high display. `baseline_only`, `insufficient_sample`, and `invalid` cannot be promoted into numeric risk probability.

## 6. Stage03V1 development sequence

### STAGE03V-WP0: Scope freeze, signal contract, and execution index

Goal: freeze Stage03V boundaries before any modeling or target-building work.

ToDo:

- [ ] Create `docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md`.
- [ ] Create `configs/risk_event_signal_contract_v1.yaml`.
- [ ] Create `configs/readiness_policy_risk_event_v1.yaml`.
- [ ] Record Stage03V1 as active target and Stage03V2 / Stage03V3 as placeholders.
- [ ] Define field categories: `display_safe`, `internal_diagnostic`, `calibration_required`, `hidden`.
- [ ] Define readiness statuses and allowed UI behavior.
- [ ] Define forbidden behavior: raw score as probability, direct trading signal, hidden sample filling.
- [ ] Add review checklist for Stage03V1 target semantics.

Deliverables:

```text
docs/work_packages/stage03v/STAGE03V_EXECUTION_INDEX.md
configs/risk_event_signal_contract_v1.yaml
configs/readiness_policy_risk_event_v1.yaml
reports/stage03v/stage03v_wp0_scope_freeze_report.md
```

Acceptance:

- [ ] Stage03V1 responsibilities are explicit.
- [ ] Stage03V2 and Stage03V3 are out of scope for implementation.
- [ ] Numeric risk probability is gated by readiness policy.
- [ ] HMM and HSMM are context features only.
- [ ] No production model code is changed.
- [ ] No target dataset is built yet.

### STAGE03V-WP1: Risk Event Target Dataset v1

Goal: construct a causal, reproducible downside risk target dataset.

ToDo:

- [ ] Add a builder for `risk_event_target_dataset_v1`.
- [ ] Support `entity_type` at least for sector-style price series.
- [ ] Include custom basket support only if existing OHLCV semantics are stable and tests are cheap.
- [ ] Compute `future_return`, `MAE`, optional diagnostic `MDD`, and future realized volatility fields.
- [ ] Generate `downside_event` labels by horizon and threshold.
- [ ] Persist `target_observation_end_date`.
- [ ] Persist `censoring_status`.
- [ ] Persist `target_definition_version`.
- [ ] Emit sample-support tables by horizon, threshold, entity type, state label, and recent-volatility bucket.
- [ ] Keep all feature dates at or before `trade_date`.

Candidate files:

```text
src/evaluation/stage03v_risk_target_dataset.py
scripts/stage03v_risk_target_gate.sh
tests/test_stage03v_risk_target_dataset.py
reports/stage03v/risk_event_target_support.md
reports/stage03v/risk_event_target_support.json
```

Minimum dataset columns:

```text
trade_date
entity_type
entity_id
sector_code
feature_scope_id
universe_id
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
- [ ] MAE and event labels match synthetic examples.
- [ ] Sample-support report exists.
- [ ] No model training occurs.

### STAGE03V-WP2: Target Leakage, Path Event, Purge, and Embargo Tests

Goal: make risk-event targets safe before modeling.

ToDo:

- [ ] Add synthetic path fixtures with known MAE, MFE, MDD, and final return.
- [ ] Test off-by-one semantics for `t+1` through `t+N`.
- [ ] Test right-censoring behavior near dataset end.
- [ ] Test purge and embargo boundaries for overlapping horizons.
- [ ] Test that future target columns are not accepted as feature columns.
- [ ] Test entity-level duplicate protection.
- [ ] Add CI-safe tests that do not require private DuckDB availability.

Candidate files:

```text
tests/test_stage03v_path_targets.py
tests/test_stage03v_target_leakage_policy.py
docs/validation/STAGE03V_TARGET_LEAKAGE_POLICY.md
scripts/stage03v_target_leakage_gate.sh
```

Acceptance:

- [ ] Synthetic target tests pass.
- [ ] Purge and embargo tests pass.
- [ ] Feature leakage tests pass.
- [ ] Tests are deterministic and CI-safe.
- [ ] No model training occurs.

### STAGE03V-WP3: Volatility and Empirical Risk Baselines

Goal: establish strong, simple baselines before logistic modeling.

ToDo:

- [ ] Build rolling realized volatility baseline.
- [ ] Build EWMA volatility baseline.
- [ ] Build downside volatility baseline.
- [ ] Build recent drawdown baseline.
- [ ] Build empirical event-rate baseline by horizon and threshold.
- [ ] Build empirical event-rate baseline by recent-volatility bucket.
- [ ] Build optional HMM-state x volatility-bucket baseline.
- [ ] Emit baseline-only ordinal risk tendency.
- [ ] Record baseline metrics in validation artifacts.

Candidate files:

```text
src/evaluation/stage03v_volatility_baselines.py
scripts/stage03v_volatility_baseline_gate.sh
reports/stage03v/volatility_baseline_report.md
reports/stage03v/volatility_baseline_report.json
tests/test_stage03v_volatility_baselines.py
```

Acceptance:

- [ ] Baselines run without future leakage.
- [ ] Baseline metrics include Brier, event rate, bucket monotonicity, and sample support.
- [ ] Sparse buckets emit `insufficient_sample` or `baseline_only`.
- [ ] Baseline probability is not promoted as `usable_probability`.
- [ ] Logistic modeling remains blocked until baseline report is accepted.

### STAGE03V-WP4: Logistic Downside Risk Hazard v1

Goal: test whether a simple supervised model adds value over volatility and empirical baselines.

ToDo:

- [ ] Train per-horizon and per-threshold logistic models.
- [ ] Use purged walk-forward train / validation folds.
- [ ] Use only causal features.
- [ ] Include feature families: recent volatility, downside volatility, recent drawdown, breadth, dispersion, liquidity, RS, HMM context, HSMM lifecycle context.
- [ ] Exclude HSMM raw or calibrated numeric `p_exit` by default.
- [ ] Emit `risk_raw_score` only.
- [ ] Persist fold id, model version, feature set id, and parameter set id.
- [ ] Emit coefficient or feature summary where available.

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
- [ ] Performance is compared against WP3 baselines.
- [ ] Fold construction respects purge and embargo policy.
- [ ] Feature set excludes target and future columns.
- [ ] No UI surface or decision surface is created.

### STAGE03V-WP5: Calibration and Downside Risk Readiness Matrix

Goal: decide where numeric probability is allowed and where output must downgrade.

ToDo:

- [ ] Add isotonic calibration on validation folds only.
- [ ] Compare raw logistic, calibrated logistic, and baselines.
- [ ] Compute Brier score, ECE, calibration slope / intercept, bucket monotonicity, PR-AUC, event rate, and sample support.
- [ ] Build readiness matrix by horizon, threshold, entity type, state label, and risk bucket.
- [ ] Assign `usable_probability`, `ordinal_only`, `baseline_only`, `insufficient_sample`, or `invalid`.
- [ ] Emit fallback reason for every non-usable slice.
- [ ] Prevent calibration that worsens Brier from receiving `usable_probability`.

Candidate files:

```text
src/evaluation/stage03v_risk_calibration.py
src/evaluation/stage03v_risk_readiness_matrix.py
scripts/stage03v_risk_readiness_gate.sh
reports/stage03v/downside_risk_readiness_matrix.md
reports/stage03v/downside_risk_readiness_matrix.json
tests/test_stage03v_risk_readiness_matrix.py
```

Acceptance:

- [ ] Readiness matrix exists.
- [ ] Calibration that worsens Brier cannot become `usable_probability`.
- [ ] Sparse slices downgrade cleanly.
- [ ] Numeric probability appears only in `usable_probability` slices.
- [ ] Most slices may be `ordinal_only`; this is acceptable.
- [ ] No decision output is created.

### STAGE03V-WP6: Risk Validation Protocol and Downshift Research Report

Goal: test whether downside-risk output improves risk management metrics under a pre-registered protocol.

ToDo:

- [ ] Pre-register risk validation metrics.
- [ ] Define research-only risk-downshift scenarios, for example avoiding or reducing exposure in top risk bucket.
- [ ] Measure future max drawdown reduction.
- [ ] Measure CVaR reduction.
- [ ] Measure realized volatility reduction.
- [ ] Measure stress-period recall.
- [ ] Measure false risk-downshift rate.
- [ ] Measure missed-upside cost.
- [ ] Measure turnover or churn cost if a simulated exposure rule is used.
- [ ] Record every trial in validation artifacts.
- [ ] Keep final holdout protected.

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
- [ ] Strong return with unstable risk metrics remains research-only.
- [ ] Results include abstain behavior.
- [ ] No production trading recommendation is created.

### STAGE03V-WP7: Stage03V1 Final Gate

Goal: aggregate engineering, calibration, and risk-validation evidence into a final Stage03V1 verdict.

ToDo:

- [ ] Aggregate WP0 through WP6 evidence.
- [ ] Emit engineering gate verdict.
- [ ] Emit calibration gate verdict.
- [ ] Emit risk validation verdict.
- [ ] Emit final verdict: `PASS`, `DEFER`, or `BLOCKED`.
- [ ] Decide whether Stage03V2 or Stage03V3 deserves activation.
- [ ] Record limitations, sample ceilings, and forbidden interpretations.

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
- [ ] Stage03V2 and Stage03V3 remain blocked unless explicitly activated by a follow-up route document.

## 7. Stage03V1 global ToDo list

- [ ] Approve this route document after human review.
- [ ] Create Stage03V execution index.
- [ ] Create risk-event signal contract.
- [ ] Create risk-event readiness policy.
- [ ] Build risk-event target dataset.
- [ ] Add synthetic path-event tests.
- [ ] Add leakage, purge, and embargo tests.
- [ ] Build volatility and empirical baselines.
- [ ] Train logistic downside risk hazard candidate.
- [ ] Add calibration and readiness matrix.
- [ ] Pre-register risk validation protocol.
- [ ] Run risk validation report.
- [ ] Emit Stage03V1 final gate verdict.
- [ ] Decide whether to activate Stage03V2 or Stage03V3.

## 8. Feature policy for Stage03V1

Allowed causal feature families:

```text
recent_return
rolling_volatility
EWMA_volatility
downside_volatility
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
```

HSMM lifecycle context can be used only as non-probability context unless a later contract explicitly allows a readiness-approved field.

## 9. Validation and promotion policy

Stage03V1 can pass only if all of the following hold:

1. Risk target dataset passes causal, censoring, purge, and embargo audit.
2. Synthetic path target tests pass.
3. Baselines exist and are explicitly compared.
4. Logistic hazard adds evidence over simple baselines or is downgraded honestly.
5. Calibration does not worsen Brier for any slice marked `usable_probability`.
6. Sparse slices emit `insufficient_sample`, `baseline_only`, or `ordinal_only`.
7. Risk validation protocol is pre-registered.
8. Final holdout discipline is preserved.
9. Output remains risk context or decision-support candidate, not trading instruction.

Stage03V1 should fail or defer if:

- the event base rate is too sparse for stable calibration;
- most apparent improvement comes from one slice only;
- calibration improves ranking but worsens probability quality;
- risk-downshift improves return but worsens drawdown or CVaR;
- final holdout discipline cannot be proven;
- implementation requires expanding Stage03V2 or Stage03V3 early.

## 10. Execution governance

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

## 11. Review questions before activation

Reviewer should decide these before STAGE03V-WP0 starts:

- [ ] Is `MAE` the correct primary Stage03V1 event target?
- [ ] Should `MDD` be diagnostic only in v1, or should it be a primary target?
- [ ] Are the initial horizons `{5, 10, 20}` sufficient?
- [ ] Are the fixed thresholds `{3%, 5%, 8%, 10%}` acceptable for the first pass?
- [ ] Should custom baskets be included in v1, or deferred until sector-level evidence exists?
- [ ] Should volatility-scaled thresholds be deferred until after fixed-threshold baselines?
- [ ] Should Stage03V1 consume Stage03R hazard outputs as features, or only HMM / HSMM context fields?
- [ ] What final holdout split should be locked before empirical promotion?

## 12. Out of scope for Stage03V1

The following are explicitly out of scope:

- Stage03V2 upside-trigger model implementation.
- Stage03V3 competing-risks model implementation.
- Full decision engine integration.
- Buy, sell, sizing, or automatic trading recommendations.
- Deep models, random forests, GBM, neural nets, VAR-HSMM, or switching state-space models.
- Repeated final-holdout tuning.
- UI display of uncalibrated numeric risk probability.
- Promotion of raw logistic score as probability.

## 13. Revision log

| date | change | by |
|---|---|---|
| 2026-06-10 | Initial review-candidate Stage03V route plan. | ChatGPT |
