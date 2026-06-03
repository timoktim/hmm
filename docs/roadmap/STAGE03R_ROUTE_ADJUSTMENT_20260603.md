# STAGE03R_ROUTE_ADJUSTMENT_20260603

Date: 2026-06-03
Status: approved as future development direction, blocked until Stage03 preflight gate passes
Scope: replaces the previous post-preflight Stage03 route that continued to deepen HSMM numerical probability calibration before Duration Hazard.

## Route decision

The development route is adjusted from:

```text
Continue deepening HSMM lifecycle probability calibration
-> Duration Hazard as later fallback
-> Change Point
-> Decision Engine
```

to:

```text
Freeze HSMM as lifecycle interpretation layer
-> promote Duration Hazard as the primary lifecycle exit engine
-> validate with risk metrics, calibration metrics, and final held-out discipline
-> default to ordinal tendency or abstain when sample support is insufficient
-> then proceed to low-cost break detection and a simplified decision engine
```

This does not discard prior Stage00-Stage03 preflight work. It changes the next model-development anchor: Duration Hazard becomes the default Stage03R mainline, while HSMM numerical `p_exit` remains gated and local.

## Current model responsibilities

### HMM

HMM remains the regime identification foundation. It is responsible for:

- causal walk-forward state paths;
- display labels / regime labels;
- state confidence, entropy, and posterior margin;
- state stability, churn, and label-identity monitoring.

HMM must not be treated as:

- a standalone alpha generator;
- direct trading signal;
- unvalidated return prediction engine.

### HSMM

HSMM is frozen as lifecycle interpretation layer. It is responsible for:

- state age;
- early / mature / late lifecycle phase;
- duration profile;
- display-label episode history;
- ordinal exit tendency: low / medium / high;
- next-state tendency as realized episode-supported description.

HSMM is not responsible for:

- generic numeric `p_exit` display;
- precise exit probability for every state × horizon;
- direct ranking, sizing, or trading decisions.

Numeric HSMM `p_exit` can only be shown locally when readiness gate explicitly permits it. It is not a default decision input.

### Duration Hazard

Duration Hazard becomes the main lifecycle exit signal for Stage03R. It is responsible for:

- age-conditioned exit probability / tendency;
- horizon-specific exit calibration;
- hazard vs HSMM raw `p_exit` comparison;
- state × horizon readiness matrix;
- insufficient-sample downgrade.

Stage03R v1 should stay lightweight:

```text
logistic hazard
+ isotonic calibration
+ age-bucket empirical baseline
+ sample_support/readiness_status
+ ordinal fallback
```

Do not include the full competing-risks model, GBM, random forest, BOCPD, VAR-HSMM, heavy-tail HMM, GH emission, or deep switching state-space in the first Stage03R version.

## Immediately frozen

These remain supported but should not expand in responsibility before Stage03R:

- HSMM lifecycle UI v0 hardening outputs;
- HSMM state age / phase / duration profile;
- HSMM ordinal exit tendency;
- realized-episode next-state tendency;
- current readiness gate and UI hiding policy.

## Immediately promoted into Stage03R

These become the Stage03R mainline:

- `exit_target_dataset_v1`;
- `duration_hazard_logistic_v1`;
- `hazard_isotonic_calibration_v1`;
- `age_bucket_baseline_v1`;
- `hazard_vs_hsmm_readiness_matrix`;
- `risk_calibration_validation_protocol`;
- purged / embargoed walk-forward;
- final held-out test split discipline;
- persistent data-quality CI invariants.

## Moved after Stage03R v1

These are not part of the first Stage03R implementation:

- full competing-risks hazard;
- full BOCPD model;
- heavy-tail HMM / generalized hyperbolic emission;
- VAR-HSMM;
- deep switching state-space model;
- full return-oriented decision engine fusion.

## Removed or downgraded from promotion gate

The following should not be used as primary Stage03R promotion gates:

- mandatory outperformance versus RS20 or equal-weight as the main promotion condition;
- numeric `p_exit` for every state × horizon;
- dependency on fully fixing HSMM calibration before hazard work starts;
- open-ended model search where the best of many models is promoted without trial accounting.

## Stage03R phases

### Stage03R.0 Scope freeze and evidence anchor

Deliverables:

```text
docs/roadmap/stage03r_scope_freeze.md
configs/lifecycle_signal_contract_v1.yaml
configs/readiness_policy_lifecycle_v1.yaml
```

Minimum acceptance:

- HSMM lifecycle fields are categorized as `display_safe`, `internal_diagnostic`, `calibration_required`, or `hidden`.
- UI does not query or show raw/calibrated HSMM `p_exit` by default.
- Future decision engine may consume readiness-approved hazard fields, not raw HSMM probabilities.

### Stage03R.1 Exit Target Dataset

Goal: build a causal, auditable, reproducible exit target dataset.

Core inputs:

```text
trade_date
sector_code
run_id
state_source
state_label
state_age
state_phase
duration_percentile
volatility_features
breadth_features
drawdown_features
liquidity_features
rs_features
profile_cutoff_date
state_date_policy
```

Core targets:

```text
exit_within_1d
exit_within_3d
exit_within_5d
exit_within_10d
exit_within_20d
next_state_label_realized
target_observation_end_date
censoring_status
sample_weight
target_definition_version
```

Acceptance:

- no feature date later than `trade_date`;
- horizon labels observe purge / embargo rules;
- right-censored samples are not treated as non-exit;
- state × horizon × age_bucket sample-support table exists;
- target definition version is persisted.

### Stage03R.2 Logistic Hazard and Isotonic Calibration

Goal: determine whether the hazard route stands up before adding complex models.

Pipeline:

```text
per-horizon binary logistic hazard
-> walk-forward train / validation
-> isotonic calibration on validation folds
-> age-bucket empirical baseline comparison
-> readiness matrix
```

Outputs:

```text
hazard_raw_score
hazard_calibrated_probability
exit_tendency_ordinal
calibration_status
sample_support
readiness_status
fallback_reason
model_version
validation_fold_id
```

Readiness statuses:

```text
usable_probability
ordinal_only
baseline_only
insufficient_sample
invalid
```

### Stage03R.3 Hazard vs HSMM Readiness Matrix

Matrix dimensions:

```text
state_label × horizon × age_bucket × profile_mode
```

Metrics:

```text
Brier score
ECE
calibration slope / intercept
bucket monotonicity
sample_count
positive_count
event_rate
hazard_vs_hsmm_raw_p_exit_delta
hazard_vs_age_bucket_baseline_delta
ordinal_separation
```

Acceptance:

- no one-slice accidental win is promoted;
- calibration that worsens Brier cannot be `usable_probability`;
- insufficient sample outputs `insufficient_sample`, not pseudo-probability;
- `ordinal_only` is acceptable for many slices.

### Stage03R.4 Risk validation protocol

Primary validation metrics:

```text
max_drawdown_reduction
CVaR_reduction
volatility_reduction
stress_period_recall
false_risk_downshift_rate
turnover_cost
missed_upside_cost
abstain_hit_rate
```

Secondary metrics:

```text
net_return
Sharpe
rank_IC
top_bottom_spread
```

Rules:

- primary metrics must be pre-registered;
- final held-out split can be used only once for final testing;
- every model / parameter trial must be recorded in `validation_runs`;
- multiple-testing count must be reflected in promotion gate;
- strong return with unstable risk metrics remains research-only.

### Stage03R.5 Data-quality CI invariants

Minimum CI invariants:

- OHLCV `high >= low`;
- OHLCV `low <= open/close <= high`;
- non-negative volume and amount;
- no duplicate `trade_date` per entity;
- universe coverage lower bound;
- index / sector / stock / benchmark ingestion validation;
- adjusted-price, suspension, limit-up/down policy checks;
- core causal tests;
- HSMM lifecycle hardening tests;
- hazard target leakage tests.

## Stage03R pass criteria

Stage03R can pass only if:

1. `exit_target_dataset_v1` passes causal, censoring, purge, and embargo audit.
2. Hazard reaches at least stable `ordinal_only` on core horizons, with some slices reaching `usable_probability` if evidence supports it.
3. Hazard calibration is not worse than HSMM raw `p_exit`.
4. Age-bucket baseline is explicitly compared.
5. `insufficient_sample` triggers normally.
6. Risk validation protocol is implemented and return is not the main promotion gate.
7. Final held-out test split is fixed and locked.
8. Data-quality CI minimum set is active.

If Stage03R does not pass, do not return to expanding HSMM numerical probability. Downgrade output granularity, keep ordinal tendency, expand abstain, merge sparse buckets where necessary, and record sample-ceiling limitations.

## Next route after Stage03R

If hazard passes:

```text
Stage04R: low-cost break detection
-> Stage05R: simplified decision engine
-> Stage06R: casebook and human review loop
```

If hazard partially passes:

```text
Stage03R.2: competing-risks hazard prototype
```

Only apply this to states with enough sample support.

If hazard does not pass:

```text
HMM regime context
+ HSMM lifecycle ordinal UI
+ break detector
+ strong abstain
```

## Execution principle

Prefer:

```text
low / medium / high + insufficient_sample + abstain
```

over precise but uncalibrated probabilities.

Prefer simple models that support stable risk judgment over complex generative models whose probability semantics cannot be validated.

Prefer explicit sample-ceiling acknowledgment over model zoo search and hidden multiple testing.
